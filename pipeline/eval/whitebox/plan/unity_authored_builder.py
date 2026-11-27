"""Source-bound admission for the reviewed GLM G005/G009 delivered scene builders.

Only each author's exact reviewed builder may create the bound scene.
The frozen input remains untouched. No general C# entry fallback is provided.
"""
from __future__ import annotations

from ...model_config import PLANNER_MODEL

from contextlib import contextmanager
import fcntl
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from dataclasses import dataclass

from ..core import prepare
from ..core.llm import HarnessError
from ..core.paths import FRAMEWORK, read_json, sha256, write_json

VERSION = 'stage1-unity-authored-builder.v1'
REL = Path('recovery/authored_builder_v1')
SOURCE = 'Assets/Editor/WbSceneTools.cs'
SOURCE_SHA = '167da915892c3b386c7d4929663eaeebccdfa3d1d2d2470318b2bf3d95352934'
METHOD = 'WbSceneTools.CreateScene'
SCENE = 'Assets/Scenes/BrokenRealmEcho.unity'
GAME = 'G005_broken_realm_echo'
RESERVE = 8 * 1024 ** 3

G009_SOURCE_SHA = 'd34a546b0d0ac211385111fcdac2da241c13510de8813ccd0bc6eab998de0a98'


@dataclass(frozen=True)
class Entry:
    source: str
    sha256: str
    method: str
    scene: str
    bootstrap_meta: str
    completion_log: str
    registers_build_scene: bool


def reviewed(out):
    game = read_json(Path(out) / 'manifest.json')['game_id']
    if game == GAME:
        return Entry(SOURCE, SOURCE_SHA, METHOD, SCENE, 'Bootstrap.cs.meta',
                     '[WbSceneTools] created ' + SCENE + ' and registered build scene', True)
    require(game == 'G009_blackout_stealth', 'authored builder is reviewed only for GLM G005/G009')
    return Entry('Assets/Scripts/Editor/G009EditorValidation.cs', G009_SOURCE_SHA,
                 'G009EditorValidation.BuildScene', 'Assets/Scenes/G009Game.unity',
                 'Assets/Scripts/Mechanic/G009SceneBootstrap.cs.meta',
                 '[G009] scene saved: Assets/Scenes/G009Game.unity', False)


def require(ok, message):
    if not ok:
        raise HarnessError(message)


def exclusive(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


@contextmanager
def locked(out):
    folder = Path(out) / REL
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HarnessError('authored builder recovery already active') from exc
        yield


def producer():
    names = ('unity_authored_builder', 'plan', 'planner', 'record', 'pipeline', 'prepare',
             'llm', 'paths', 'capture', 'playable_rules', 'unity_editor', 'unity_input',
             'budgets', 'delivery', 'suites', 'native_log', 'unity_imgui_transport_recovery')
    paths = [Path(__file__).with_name(n + '.py') for n in names
             if Path(__file__).with_name(n + '.py').is_file()]
    paths += [p for p in (FRAMEWORK / 'engine_adapters/common').rglob('*')
              if p.is_file() and p.suffix in ('.py', '.json')]
    paths += [FRAMEWORK / 'engine_adapters/_input_capabilities.py',
              FRAMEWORK / 'engine_adapters/_mouse_plan.py',
              FRAMEWORK / 'pipeline/game_eval/whitebox_eval/unity_runtime_dependencies.py']
    paths += [p for p in (FRAMEWORK / 'engine_adapters/unity3d').rglob('*')
              if p.suffix in ('.py', '.cs')]
    paths += [FRAMEWORK / 'engine_adapters/action_provenance.py',
              FRAMEWORK / 'pipeline/eval/model_config.py',
              FRAMEWORK / 'engine_adapters/unity3d/playtest/resources/GameFactoryInput.provenance.json']
    return {str(p.relative_to(FRAMEWORK)): sha256(p) for p in sorted(paths)}


def original(out):
    out = Path(out).resolve()
    entry = reviewed(out)
    manifest = prepare.verify(out)
    require(manifest['engine'] == 'unity3d'
            and manifest['delivery']['model'] == 'glm'
            and manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'},
            'authored builder is reviewed only for GLM G005/G009 / Astra playable')
    source = Path(manifest['project_source']).resolve()
    require(source != (out / 'runtime/project').resolve(), 'builder cannot run on original')
    require(prepare.tree_digest(prepare.tree_hashes(source)) == manifest['project_digest'],
            'original source tree changed')
    frozen = out / 'input/project'
    for root in (source, frozen):
        require((root / entry.source).is_file() and not (root / entry.source).is_symlink()
                and sha256(root / entry.source) == entry.sha256, 'reviewed authored builder source changed')
        require(not any((root / 'Assets').rglob('*.unity')), 'use existing authored scene entry')
    return manifest


def verify_archive(out):
    folder = Path(out) / REL
    archive = read_json(folder / 'archive.json')
    for item in archive['files']:
        path = (folder / item['archive']).resolve()
        require(path.is_relative_to(folder.resolve()) and sha256(path) == item['sha256'],
                'parent archive changed')
        # Status may advance, production may be patched; raw model calls never change.
        if '/model_calls/' in item['path'] or item['path'].endswith('/manifest.json'):
            require(sha256(Path(item['path'])) == item['sha256'], 'parent evidence changed')
    return archive


def _binding(out, receipt):
    manifest = original(out)
    entry = reviewed(out)
    require(receipt.get('version') == VERSION and receipt.get('qualified') is True,
            'qualified authored builder receipt required')
    require(receipt['manifest_sha256'] == sha256(out / 'manifest.json')
            and receipt['project_digest'] == manifest['project_digest']
            and receipt['snapshot_digest'] == manifest['snapshot_digest']
            and receipt['builder'] == {'source': entry.source, 'sha256': entry.sha256, 'method': entry.method}
            and receipt['scene'] == entry.scene and receipt['out'] == str(out.resolve()),
            'builder receipt identity differs')
    require(receipt['execution']['exit_code'] == 0 and receipt['execution']['timeout'] is False,
            'author builder did not exit successfully')
    expected = [receipt['editor']['editor']['binary'], '-batchmode', '-nographics', '-quit',
                '-projectPath', str(out / 'runtime/project'), '-executeMethod', entry.method,
                '-logFile', str(out / REL / 'builder.log')]
    require(receipt['execution']['cmd'] == expected, 'builder command differs from reviewed invocation')
    for rel, digest in receipt['evidence_sha256'].items():
        path = out / REL / rel
        require(path.resolve().is_relative_to((out / REL).resolve()) and sha256(path) == digest,
                f'builder evidence changed: {rel}')
    require(receipt['scene_sha256'] == sha256(out / REL / 'generated' / entry.scene),
            'generated scene archive changed')
    verify_archive(out)
    return manifest


def context(out):
    """Return an admitted entry only when its fixed receipt and original binding verify."""
    out = Path(out).resolve()
    path = out / REL / 'receipt.json'
    if not path.exists():
        return None
    receipt = read_json(path)
    entry = reviewed(out)
    _binding(out, receipt)
    return {'launch_source': entry.source, 'launch_scene': entry.scene, 'method': entry.method,
            'receipt_sha256': sha256(path), 'source_sha256': entry.sha256}


def validate_plan(out, executable):
    ctx = context(out)
    entry = reviewed(out)
    require(ctx is not None, 'C# launch source requires verified authored builder receipt')
    require(executable['launch_source'] == entry.source and executable['launch_scene'] == entry.scene,
            'plan differs from reviewed authored builder/scene')
    return ctx


def claim_plan(out, take):
    out = Path(out).resolve()
    require(take in (1, 2), 'authored builder recovery allows at most two actual takes')
    validate = context(out)
    require(validate is not None, 'authored builder admission missing')
    folder = out / REL
    receipt = read_json(folder / 'receipt.json')
    require(producer() == receipt['production'], 'production changed since authored builder admission')
    exclusive(folder / f'planner_t{take}.claim.json', {
        'version': VERSION, 'take': take, 'max_format_attempts': 2,
        'parent_archive_sha256': sha256(folder / 'archive.json'),
        'builder_receipt_sha256': sha256(folder / 'receipt.json'),
        'call_name': f'plan_t{take}_authored_builder_v1', 'model': PLANNER_MODEL})


def record_scene(project, executable, record_dir):
    """Minimal record dispatch: resolve to the generated scene, never the C# file."""
    project = Path(project).resolve()
    if executable['launch_source'].endswith('.scene'):
        from . import unity_authored_scene
        return unity_authored_scene.record_scene(project, executable, record_dir)
    if executable['launch_source'].endswith('.unity'):
        return executable['launch_source']
    out = project.parent.parent
    entry = reviewed(out)
    validate_plan(out, executable)
    receipt = read_json(out / REL / 'receipt.json')
    require(project == out / 'runtime/project', 'unexpected authored builder runtime project')
    require(sha256(project / entry.source) == entry.sha256 and sha256(project / entry.scene) == receipt['scene_sha256'],
            'authored builder or generated scene changed before capture')
    # The ordinary native input migration is the only permitted change to author C#.
    from .unity_input import migrate_device_reads
    migration = read_json(out / 'runtime/unity_input_migration.json')
    changes = {r['path']: r for r in migration.get('changes', [])}
    for source in (out / 'input/project/Assets').rglob('*.cs'):
        rel = str(source.relative_to(out / 'input/project'))
        actual = project / rel
        before = source.read_bytes()
        if actual.read_bytes() == before:
            require(rel not in changes, 'input migration receipt contradicts unchanged source')
            continue
        after = migrate_device_reads(before.decode('utf-8')).encode('utf-8')
        require(migration.get('migrated') is True and migration.get('gameplay_changes') == []
                and actual.read_bytes() == after and changes.get(rel) == {
                    'path': rel, 'before_sha256': hashlib.sha256(before).hexdigest(),
                    'after_sha256': hashlib.sha256(after).hexdigest(), 'kind': 'input_device_reads_only'},
                f'non-input authored source change: {rel}')
    write_json(Path(record_dir) / 'authored_builder_entry.json', {
        'version': VERSION, 'receipt': str(out / REL / 'receipt.json'),
        'receipt_sha256': sha256(out / REL / 'receipt.json'), 'scene': entry.scene,
        'scene_sha256': receipt['scene_sha256'], 'builder_source_sha256': entry.sha256})
    return entry.scene


def bootstrap_guid(project, frozen, log_text, metadata='Bootstrap.cs.meta'):
    """Bind actual imported script GUID; Tuanjie original metas may be encrypted."""
    metas = ([frozen / metadata] if '/' in metadata
             else list((frozen / 'Assets').rglob(metadata)))
    require(all(p.is_file() for p in metas), 'Bootstrap metadata missing')
    require(len(metas) == 1, 'Bootstrap source metadata ambiguous')
    rel = metas[0].relative_to(frozen)
    raw = re.search(r'(?m)^guid: ([^\r\n]+)$', metas[0].read_text())
    current = re.search(r'(?m)^guid: ([^\r\n]+)$', (project / rel).read_text())
    require(raw is not None and current is not None and raw[1] == current[1],
            'authored Bootstrap metadata GUID changed')
    if re.fullmatch(r'[0-9a-f]{32}', raw[1]):
        return raw[1]
    script = str(rel).removesuffix('.meta')
    found = set(re.findall(r'Start importing ' + re.escape(script)
                          + r' using Guid\(([0-9a-f]{32})\)', log_text))
    require(len(found) == 1, 'encrypted Bootstrap GUID needs unique native import evidence')
    return found.pop()


def build(out):
    """Invoke the exact delivered builder once on the untouched execution copy."""
    from . import record, unity_editor
    out = Path(out).resolve()
    entry = reviewed(out)
    folder = out / REL
    if (folder / 'receipt.json').is_file():
        context(out)
        return read_json(folder / 'receipt.json')
    manifest = original(out)
    verify_archive(out)
    require(read_json(out / 'status.json')['step'] == 'plan_t1'
            and not list((out / 'takes').glob('*/plan.json'))
            and not list((out / 'takes').glob('*/record/native')),
            'recovery requires rejected initial plan and no native attempts')
    require(not list((out / 'model_calls').glob('*/accepted_response.json')),
            'existing accepted plan must not be replaced')
    project = out / 'runtime/project'
    if (folder / 'builder.claim.json').exists():
        require(manifest['game_id'] == GAME, 'G009 claimed builder cannot be reinvoked')
        # One narrowly bound offline continuation; never invoke a completed builder twice.
        claim = read_json(folder / 'builder.claim.json')
        execution = read_json(folder / 'builder_execution.json')
        current = producer()
        changed = {k for k in set(current) | set(claim['production'])
                   if current.get(k) != claim['production'].get(k)}
        require(changed == {'pipeline/eval/stage1/unity_authored_builder.py'}
                and execution.get('exit_code') == 0 and execution.get('timeout') is False,
                'claimed builder cannot repeat; offline recovery requires only helper correction')
        recovery_claim = folder / 'guid_postprocess.claim.json'
        if recovery_claim.exists():
            prior = read_json(recovery_claim)
            require(prior['parent_builder_claim_sha256'] == sha256(folder / 'builder.claim.json')
                    and prior['parent_execution_sha256'] == sha256(folder / 'builder_execution.json'),
                    'offline parent execution changed')
            recovery_claim = folder / 'output_postprocess.claim.json'
        exclusive(recovery_claim, {
            'version': VERSION, 'mode': 'completed_builder_offline_only',
            'parent_builder_claim_sha256': sha256(folder / 'builder.claim.json'),
            'parent_execution_sha256': sha256(folder / 'builder_execution.json'),
            'production_before': claim['production'], 'production_after': current,
            'additional_builder_invocations': 0})
        return seal_builder(out, manifest, claim['editor'], execution, current)
    require(prepare.tree_digest(prepare.tree_hashes(project)) == manifest['snapshot_digest'],
            'builder working copy must match frozen original snapshot')
    choice = unity_editor.choose(project)
    production = producer()
    write_json(folder / 'stage1_production_before.json', {p.name: sha256(p) for p in Path(__file__).parent.glob('*.py')})
    require(not (folder / 'builder.claim.json').exists(), 'builder invocation already claimed; inspect retained evidence')
    # Exact old bytes were archived before edits; retain this producer independently.
    for rel in production:
        dst = folder / 'production' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(FRAMEWORK / rel, dst)
    exclusive(folder / 'builder.claim.json', {'version': VERSION, 'editor': choice,
              'manifest_sha256': sha256(out / 'manifest.json'), 'production': production,
              'max_builder_invocations': 1, 'max_actual_takes': 2, 'parent_failure': read_json(out / 'status.json')})
    require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3,
            'builder requires 2GiB estimated usage plus 8GiB reserve')
    command = [choice['editor']['binary'], '-batchmode', '-nographics', '-quit',
               '-projectPath', str(project), '-executeMethod', entry.method,
               '-logFile', str(folder / 'builder.log')]
    # Both Stage1 per-take lock and shared GUI slot protect this native phase.
    with record._record_lock(out, 1), record.gui_slot() as slot:
        require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3, 'insufficient free space')
        execution = record._run(command, folder / 'builder_console.log', timeout=600)
        write_json(folder / 'builder_execution.json', {**execution, 'gui_slot': str(slot)})
    return seal_builder(out, manifest, choice, execution, production)


def seal_builder(out, manifest, choice, execution, production):
    folder, project = out / REL, out / 'runtime/project'
    entry = reviewed(out)
    text = (folder / 'builder.log').read_text(errors='replace') if (folder / 'builder.log').exists() else ''
    require(execution['exit_code'] == 0 and not execution['timeout']
            and not re.search(r'error CS\d+|Scripts have compiler errors', text),
            'delivered scene builder failed; preserve compiler evidence, do not repair author code')
    require(entry.completion_log in text,
            'author builder completion log missing')
    original(out)
    for p in (out / 'input/project/Assets').rglob('*'):
        if p.is_file() and p.suffix != '.meta':
            require(sha256(p) == sha256(project / p.relative_to(out / 'input/project')),
                    f'author asset changed during scene build: {p.name}')
    scene = project / entry.scene
    require(scene.is_file() and scene.read_text().startswith('%YAML'), 'author did not save a Unity scene')
    guid = bootstrap_guid(project, out / 'input/project', text, entry.bootstrap_meta)
    require('guid: ' + guid in scene.read_text(),
            'generated scene does not reference authored Bootstrap')
    build_settings = project / 'ProjectSettings/EditorBuildSettings.asset'
    if entry.registers_build_scene:
        require('path: ' + entry.scene in build_settings.read_text(), 'author did not register build scene')
    else:
        require('path: ' + entry.scene not in build_settings.read_text(),
                'BuildScene alone must not invoke BuildPlayer registration')
    generated = [entry.scene, entry.scene + '.meta', 'ProjectSettings/EditorBuildSettings.asset']
    # Unity removes Temp on exit. Retain the author's report when present; never fabricate it.
    report_present = (project / 'Temp/wb_scene_report.json').is_file()
    if report_present:
        generated.append('Temp/wb_scene_report.json')
    for rel in generated:
        src = project / rel
        require(src.is_file(), f'author output missing: {rel}')
        dst = folder / 'generated' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            require(sha256(dst) == sha256(src), 'previously archived generated output changed')
        else:
            shutil.copyfile(src, dst)
    require(producer() == production, 'production changed during builder execution')
    evidence = ['builder.log', 'builder_console.log', 'builder_execution.json', 'builder.claim.json']
    evidence += ['generated/' + rel for rel in generated]
    receipt = {'version': VERSION, 'qualified': True, 'out': str(out),
               'manifest_sha256': sha256(out / 'manifest.json'), 'project_digest': manifest['project_digest'],
               'snapshot_digest': manifest['snapshot_digest'], 'builder': {
                   'source': entry.source, 'sha256': entry.sha256, 'method': entry.method},
               'scene': entry.scene, 'scene_sha256': sha256(scene), 'execution': execution,
               'editor': choice, 'production': production, 'author_source_unchanged': True,
               'bootstrap_import_guid': guid, 'transient_author_report_present_after_exit': report_present,
               'builder_production': read_json(folder / 'builder.claim.json')['production'],
               'evidence_sha256': {rel: sha256(folder / rel) for rel in evidence}}
    exclusive(folder / 'receipt.json', receipt)
    context(out)
    return receipt


def execute(out):
    """One corrected planner lineage, max two real takes, official rules/score/cleanup."""
    from . import pipeline
    out = Path(out).resolve()
    with locked(out):
        receipt = build(out)
        folder = out / REL
        exclusive(folder / 'execute.claim.json', {'version': VERSION, 'max_actual_takes': 2,
                  'receipt_sha256': sha256(folder / 'receipt.json'), 'at': time.time()})
        require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3, 'insufficient recording reserve')
        os.environ.setdefault('GAMEFACTORY_UNITY_IMGUI_FORWARD', '1')
        manifest = original(out)
        hold = {'version': 'stage1-authored-builder-finalization-hold.v1',
                'reason': 'Await official score, source/evidence/producer qualification and cleanup',
                'lineage': str(REL), 'created_at': time.time()}
        exclusive(out / 'qualification_hold.json', hold)
        shutil.copyfile(out / 'qualification_hold.json', folder / 'finalization_hold.original.json')
        result = pipeline.run_playable(Path(manifest['delivery_dir']), out,
                                      models=manifest['models'], takes=2)
        require(producer() == receipt['production'], 'relevant production changed during recovery')
        return finish(out, result, receipt)


def finish(out, result, receipt):
    folder = out / REL
    require(result['complete'] is True, 'official playable result is incomplete')
    original(out)
    from ..repair.unity_imgui_transport_recovery import cleanup_ok
    for take in result['takes']:
        k = take['take']
        capture = out / 'takes' / str(k) / 'record'
        cleanup_ok(capture)
        result_record = read_json(capture / 'record_result.json')
        report = read_json(capture / 'native/report.json')
        require(result_record['frames'] > 0 and not result_record['failed_actions']
                and result_record['plan_sha256'] == sha256(out / f'takes/{k}/plan.json'),
                'native record identity/frames/input failure')
        require(report.get('status') == 'passed' and report.get('requested_seconds') == 75
                and report.get('recorded_seconds', 0) >= 75
                and not report.get('errors') and report.get('engine') == 'unity3d'
                and Path(report['url']).resolve() == out / 'runtime/project'
                and Path(report['output_dir']).resolve() == capture / 'native',
                'native report does not prove the requested 75s take')
        from .llm import accepted_response
        accepted = accepted_response(out / 'model_calls', f'plan_t{k}_authored_builder_v1')
        require(accepted == read_json(out / 'takes' / str(k) / 'plan.json'), 'plan differs from accepted response')
    verify_archive(out)
    retained = {str(p.relative_to(out)): sha256(p) for p in out.rglob('*') if p.is_file()
                and not any(p.is_relative_to(out / part) for part in ('input/project', 'runtime/project'))
                and p.name != '.lock' and not p.name.endswith('.lock')
                and p != out / 'qualification_hold.json'}
    write_json(folder / 'stage1_production_after.json', {p.name: sha256(p) for p in Path(__file__).parent.glob('*.py')})
    write_json(folder / 'completion.json', {'version': VERSION, 'qualified': True,
               'score': result, 'evidence_sha256': retained,
               'producer_at_record': receipt['production'], 'producer_at_completion': producer(),
               'source_unchanged': True, 'parent_failures_preserved': True})
    # The official runner owns the existing cleanup implementation.
    import sys
    sys.path.insert(0, str(FRAMEWORK.parent / 'scripts_new'))
    import playable_retest
    cleanup = playable_retest.cleanup(out)
    source = Path(read_json(out / 'manifest.json')['project_source'])
    require(prepare.tree_digest(prepare.tree_hashes(source)) == receipt['project_digest'],
            'original changed during cleanup')
    retire_finalization_hold(out)
    require(playable_retest.completed_score(out, {}) == result, 'runner did not recognize completed score')
    write_json(folder / 'parent_completion_verification.json', {
        'version': VERSION, 'score_sha256': sha256(out / 'playable_score.json'),
        'cleanup_sha256': sha256(out / 'cleanup.json'), 'cleanup': cleanup,
        'qualified_complete': True})
    return result


def retire_finalization_hold(out):
    hold = out / 'qualification_hold.json'
    if not hold.exists():
        return
    folder = out / REL
    archived = folder / 'finalization_hold.original.json'
    require(archived.is_file() and hold.read_bytes() == archived.read_bytes()
            and read_json(hold).get('version') == 'stage1-authored-builder-finalization-hold.v1',
            'unrelated qualification hold must remain')
    require(read_json(folder / 'completion.json').get('qualified') is True
            and (out / 'cleanup.json').is_file()
            and not (out / 'runtime/project').exists() and not (out / 'input/project').exists(),
            'qualification/cleanup incomplete; keep hold')
    exclusive(folder / 'hold_release.json', {'version': VERSION,
        'hold_sha256': sha256(hold), 'preserved': str(archived),
        'completion_sha256': sha256(folder / 'completion.json'),
        'cleanup_sha256': sha256(out / 'cleanup.json'), 'reason': 'Verified completed official score and cleanup'})
    hold.unlink()


def godot_only_change(before, after):
    """Compare complete Python ASTs excluding only the unrelated Godot function."""
    trees = [ast.parse(text) for text in (before, after)]
    for tree in trees:
        found = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_godot']
        require(len(found) == 1, 'expected one Godot dispatch function')
        tree.body.remove(found[0])
    require(ast.dump(trees[0]) == ast.dump(trees[1]), 'Unity/shared recording code changed')


def finalize(out):
    """Offline only: finish the existing G005 score after the reviewed Godot-only drift."""
    out = Path(out).resolve()
    with locked(out):
        folder = out / REL
        receipt = read_json(folder / 'receipt.json')
        context(out)
        require((folder / 'execute.claim.json').is_file(), 'original execution claim missing')
        result = read_json(out / 'playable_score.json')
        require(result.get('complete') is True and result.get('game_id') == GAME
                and result.get('engine') == 'unity3d' and result.get('planner') == PLANNER_MODEL
                and [x['take'] for x in result['takes']] == [1], 'completed G005 take1 required')
        current = producer()
        before = receipt['production']
        helper = 'pipeline/eval/stage1/unity_authored_builder.py'
        record = 'pipeline/eval/stage1/record.py'
        require(set(before) == set(current) and
                {k for k in before if before[k] != current[k]} <= {helper, record},
                'unreviewed producer drift')
        require(sha256(folder / 'helper_before_finalization.py.txt') == before[helper]
                == 'badb906ab62d654743f270b448aa9ded94e68273593395f7bcc67064b56088ad', 'finalization predecessor differs')
        drift = folder / 'godot_duration_drift'
        require(sha256(drift / 'record_before.py.txt') == before[record]
                == 'd03da035ddb1230c8a474d85003a294414fa61c0965cd8dc57bbce9d669a128d'
                and sha256(drift / 'record_after.py.txt') == current[record]
                == 'a4024be1506bd078e3db49bd6475982fbddeb0cec7aa2ca557733ad5b8cd7105',
                'Godot duration patch differs from reviewed bytes')
        godot_only_change((drift / 'record_before.py.txt').read_text(),
                          (drift / 'record_after.py.txt').read_text())
        exclusive(folder / 'finalize.claim.json', {'version': VERSION,
            'parent_receipt_sha256': sha256(folder / 'receipt.json'),
            'score_sha256': sha256(out / 'playable_score.json'),
            'producer_at_record': before, 'producer_at_finalization': current,
            'additional_model_calls': 0, 'additional_native_invocations': 0,
            'reason': 'Reviewed Godot-only duration fix after Unity native started; cached official score'})
        return finish(out, result, receipt)



G010_PREFLIGHT = Path('recovery/authored_builder_preflight_v1')
G010_SOURCE = 'Assets/Mechanics/Editor/WhiteboxSceneBuilder.cs'
G010_SHA = '8ea883b7d0de7e5959d28cb005838c7810675821c12ca615c5ef515854466f28'
G010_METHOD = 'G010.Mechanics.EditorTools.WhiteboxSceneBuilder.Build'
G010_SCENE = 'Assets/Scenes/WhiteboxStation.unity'


def g010_source(out):
    """Review the exact target only; never admit a C# planner fallback."""
    import sys
    sys.path.insert(0, str(FRAMEWORK.parent / 'scripts_new'))
    import playable_retest as runner
    targets = [t for t in read_json(runner.TARGETS)['targets']
               if t['model'] == 'GLM' and t['case'] == 'G010']
    require(len(targets) == 1, 'expected one GLM G010 target')
    target = targets[0]
    out = Path(out).resolve()
    require(target.get('required_real_clients', 1) == 1 and target['engine'] == 'unity3d'
            and runner.result_dir(runner.BASE / 'stage1_playable_v1__plan-gpt-6-astra', target) == out,
            'G010 preflight requires the exact single-client runner result directory')
    manifest = prepare.verify(out)
    source = Path(target['project'])
    require(manifest['project_source'] == str(source)
            and manifest['game_id'] == 'G010_orbital_extraction'
            and manifest['delivery']['model'] == 'glm' and manifest['engine'] == 'unity3d'
            and manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'}
            and prepare.tree_digest(prepare.tree_hashes(source)) == manifest['project_digest'],
            'G010 original/target/frozen identity changed')
    for root in (source, out / 'input/project'):
        require(sha256(root / G010_SOURCE) == G010_SHA and not (root / G010_SOURCE).is_symlink()
                and not any((root / 'Assets').rglob('*.unity')), 'G010 reviewed original builder changed')
    return manifest


def preflight_g010(out):
    """One original builder invocation; compile errors remain product evidence.

    This preflight cannot publish a score or admit a scene/accepted plan. If the
    author builder succeeds, its generated scene needs the same full binding
    review as G005 before the official planner/recorder may consume it.
    """
    from . import record, unity_editor
    out = Path(out).resolve()
    folder = out / G010_PREFLIGHT
    with locked(out):
        manifest = g010_source(out)
        status = read_json(out / 'status.json')
        require(status.get('step') == 'plan_t1' and status.get('state') == 'HARNESS_ERROR'
                and not list((out / 'takes').glob('*/plan.json'))
                and not list((out / 'takes').glob('*/record/native'))
                and not list((out / 'model_calls').glob('*/accepted_response.json'))
                and not (out / 'playable_score.json').exists(),
                'G010 preflight requires terminal rejected plan and no accepted/native/score')
        require(not (folder / 'native.claim.json').exists(), 'G010 native preflight already claimed; do not retry')
        project = out / 'runtime/project'
        require(prepare.tree_digest(prepare.tree_hashes(project)) == manifest['snapshot_digest'],
                'G010 runtime must match the original frozen copy')
        production = producer()
        files = []
        for path in sorted(out.rglob('*')):
            if (not path.is_file() or path.is_relative_to(out / 'runtime/project')
                    or path.is_relative_to(out / 'input/project') or path.is_relative_to(out / 'recovery')
                    or path.name.endswith('.lock')):
                continue
            rel = path.relative_to(out)
            dest = folder / 'parent_archive' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            require(not dest.exists(), 'existing G010 archive must not be overwritten')
            shutil.copyfile(path, dest)
            files.append({'path': str(path), 'archive': str(dest.relative_to(folder)), 'sha256': sha256(path)})
        exclusive(folder / 'archive.json', {'version': VERSION, 'files': files})
        for rel in production:
            dest = folder / 'production' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FRAMEWORK / rel, dest)
        choice = unity_editor.choose(project)
        command = [choice['editor']['binary'], '-batchmode', '-nographics', '-quit',
                   '-projectPath', str(project), '-executeMethod', G010_METHOD,
                   '-logFile', str(folder / 'builder.log')]
        require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3, 'insufficient G010 native reserve')
        with record._record_lock(out, 1), record.gui_slot() as slot:
            require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3, 'insufficient native reserve')
            exclusive(folder / 'native.claim.json', {'version': VERSION, 'max_builder_invocations': 1,
                'additional_model_calls': 0, 'gameplay_takes': 0, 'editor': choice, 'cmd': command,
                'production': production, 'source_sha256': G010_SHA,
                'manifest_sha256': sha256(out / 'manifest.json'),
                'parent_archive_sha256': sha256(folder / 'archive.json')})
            execution = record._run(command, folder / 'console.log', timeout=600)
            write_json(folder / 'execution.json', {**execution, 'gui_slot': str(slot)})
        g010_source(out)
        for item in files:
            require(sha256(folder / item['archive']) == item['sha256']
                    and sha256(Path(item['path'])) == item['sha256'], 'G010 parent evidence changed')
        text = (folder / 'builder.log').read_text(errors='replace') if (folder / 'builder.log').exists() else ''
        errors = [line for line in text.splitlines() if re.search(r'error CS\d+', line)]
        classification = ('PRODUCT_COMPILE_FAILURE' if errors and execution['exit_code'] != 0
                          and not execution['timeout'] else
                          'BUILDER_FINISHED_REQUIRES_ADMISSION' if execution['exit_code'] == 0
                          and not execution['timeout'] else 'HARNESS_ERROR')
        current = producer()
        result = {'version': VERSION, 'classification': classification, 'complete': False,
                  'score_written': False, 'additional_model_calls': 0, 'gameplay_takes': 0,
                  'original_and_frozen_verified': True, 'source': manifest['project_source'],
                  'project_digest': manifest['project_digest'], 'snapshot_digest': manifest['snapshot_digest'],
                  'errors': errors, 'generated_scene_exists': (project / G010_SCENE).is_file(),
                  'execution_sha256': sha256(folder / 'execution.json'),
                  'native_claim_sha256': sha256(folder / 'native.claim.json'),
                  'archive_sha256': sha256(folder / 'archive.json'),
                  'log_sha256': sha256(folder / 'builder.log') if (folder / 'builder.log').exists() else None,
                  'production_drift': {key: {'before': production.get(key), 'after': current.get(key)}
                                       for key in set(production) | set(current)
                                       if production.get(key) != current.get(key)}}
        exclusive(folder / 'result.json', result)
        return result

def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--execute', action='store_true')
    mode.add_argument('--finalize', action='store_true')
    mode.add_argument('--preflight-g010', action='store_true')
    args = parser.parse_args()
    if args.preflight_g010:
        print(json.dumps(preflight_g010(args.out), ensure_ascii=False, indent=2))
    elif args.finalize:
        print(json.dumps(finalize(args.out), ensure_ascii=False, indent=2))
    elif not args.execute:
        manifest = original(args.out)
        entry = reviewed(args.out)
        print(json.dumps({'game_id': manifest['game_id'], 'builder': entry.source, 'method': entry.method,
                          'scene': entry.scene, 'source_sha256': entry.sha256}, indent=2))
    else:
        print(json.dumps(execute(args.out), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
