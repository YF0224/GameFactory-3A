"""Bounded recovery for reviewed original AfterSceneLoad entries only.

Activation requires a terminal rejected ordinary plan. The original failure and
producer bytes are archived before a corrected-contract call. The canonical
score remains held until native evidence and official cleanup are verified.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

import argparse
import ast
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import time

from ..stage1 import prepare, unity_natural_entry as entry
from ..stage1.llm import accepted_response
from ..stage1.paths import FRAMEWORK, read_json, sha256, write_json

VERSION = 'stage1-unity-natural-entry-recovery.v1'
REL = entry.REL
require = entry.require
RESERVE = 8 * 1024 ** 3


def exclusive(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


@contextmanager
def locked(out):
    folder = Path(out) / REL
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.lock').open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('natural entry recovery already active') from exc
        yield


def producer():
    names = ('unity_natural_entry', 'unity_natural_entry_recovery', 'plan', 'planner',
             'record', 'pipeline', 'prepare', 'llm', 'paths', 'capture', 'playable_rules',
             'unity_editor', 'unity_input', 'budgets', 'delivery', 'suites')
    paths = [Path(__file__).with_name(name + '.py') for name in names]
    paths += [FRAMEWORK / 'engine_adapters' / name for name in
              ('_input_capabilities.py', '_mouse_plan.py', 'action_provenance.py')]
    paths += [FRAMEWORK / 'pipeline/eval/stage1/unity_runtime_dependencies.py',
              FRAMEWORK / 'pipeline/eval/model_config.py',
              FRAMEWORK / 'engine_adapters/unity3d/playtest/resources/GameFactoryInput.provenance.json']
    for directory, suffixes in (('engine_adapters/common', ('.py', '.json')),
                                ('engine_adapters/unity3d', ('.py', '.cs'))):
        paths += [p for p in (FRAMEWORK / directory).rglob('*') if p.is_file() and p.suffix in suffixes]
    return {str(p.relative_to(FRAMEWORK)): sha256(p) for p in sorted(paths) if p.is_file()}


def verify_archive(out):
    folder = Path(out) / REL
    archive = read_json(folder / 'archive.json')
    require(archive['version'] == VERSION, 'unknown natural parent archive')
    for relative, digest in archive['files'].items():
        path = folder / 'parent_archive' / relative
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts
                and not path.is_symlink() and sha256(path) == digest, 'parent archive changed')
        if relative.startswith('model_calls/') or relative == 'manifest.json':
            require(sha256(Path(out) / relative) == digest, 'original parent evidence changed')
    return archive


def verify_producer(out):
    folder = Path(out) / REL
    before = read_json(folder / 'activation.json')['production']
    current = producer()
    require(set(before) == set(current), 'natural producer file set changed')
    drift = {}
    for relative, digest in before.items():
        archived = folder / 'production' / relative
        require(sha256(archived) == digest, 'archived producer changed')
        if current[relative] != digest:
            # Explicitly preserve the previous Godot-only edit allowance. This
            # compares every other AST node, including the entire Unity branch.
            require(relative == 'pipeline/eval/stage1/record.py', 'natural producer changed: ' + relative)
            trees = [ast.parse(text) for text in (archived.read_text(), (FRAMEWORK / relative).read_text())]
            for tree in trees:
                functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_godot']
                require(len(functions) == 1, 'expected one Godot dispatch')
                tree.body.remove(functions[0])
            require(ast.dump(trees[0]) == ast.dump(trees[1]), 'Unity/shared recording code changed')
            drift[relative] = {'before': digest, 'after': current[relative],
                               'qualification': 'only_godot_function_ast_changed'}
    return {'production_at_activation': before, 'production_now': current, 'reviewed_drift': drift}


def activate(out):
    """Called under recovery lock only, after the ordinary lane is terminal."""
    out = Path(out).resolve()
    value = entry.review(out)
    status = read_json(out / 'status.json')
    require(status.get('step') == 'plan_t1' and status.get('state') in ('HARNESS_ERROR', 'ERROR'),
            'wait for ordinary lane terminal plan_t1 failure or explicit handoff implementation')
    require(not list((out / 'takes').rglob('plan.json'))
            and not list((out / 'takes').glob('*/record'))
            and not list((out / 'model_calls').glob('*/accepted_response.json'))
            and not (out / 'playable_score.json').exists(),
            'existing accepted plan/native/score requires separate evidence recovery')
    require(not (out / 'qualification_hold.json').exists(), 'existing qualification hold must be preserved')
    folder = out / REL
    require(not (folder / 'activation.json').exists() and not (folder / 'contract.json').exists(),
            'natural recovery already activated; do not reissue claims')
    files = {}
    for path in sorted(out.rglob('*')):
        if (not path.is_file() or any(path.is_relative_to(out / part) for part in
                                     ('input/project', 'runtime/project', 'recovery'))
                or path.name.endswith('.lock')):
            continue
        require(not path.is_symlink(), 'symlinked parent evidence')
        relative = str(path.relative_to(out))
        destination = folder / 'parent_archive' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(path.read_bytes())
        files[relative] = sha256(destination)
    require(any(name.startswith('model_calls/') for name in files), 'missing rejected parent model call')
    exclusive(folder / 'archive.json', {'version': VERSION, 'files': files})
    production = producer()
    for relative, digest in production.items():
        destination = folder / 'production' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write((FRAMEWORK / relative).read_bytes())
        require(sha256(destination) == digest, 'producer changed while archiving')
    hold = {'version': VERSION, 'lineage': str(REL), 'reason': 'Await native lifecycle, 75s, source and cleanup qualification'}
    exclusive(out / 'qualification_hold.json', hold)
    exclusive(folder / 'hold.original.json', hold)
    exclusive(folder / 'contract.json', value)
    exclusive(folder / 'activation.json', {'version': VERSION, 'out': str(out),
              'contract_sha256': sha256(folder / 'contract.json'), 'parent_status': status,
              'archive_sha256': sha256(folder / 'archive.json'), 'production': production,
              'max_actual_takes': 2, 'planner': PLANNER_MODEL, 'at': time.time()})
    return value


def claim_plan(out, take):
    out = Path(out).resolve()
    require(type(take) is int and take in (1, 2), 'natural recovery allows at most two actual takes')
    require(entry.context(out) is not None, 'natural entry contract absent')
    activation = read_json(out / REL / 'activation.json')
    require(activation['contract_sha256'] == sha256(out / REL / 'contract.json')
            and activation['archive_sha256'] == sha256(out / REL / 'archive.json'), 'activation binding changed')
    verify_archive(out)
    verify_producer(out)
    exclusive(out / REL / f'planner_t{take}.claim.json', {'version': VERSION, 'take': take,
              'activation_sha256': sha256(out / REL / 'activation.json'),
              'call_name': f'plan_t{take}_natural_entry_v1', 'max_format_attempts': 2,
              'model': PLANNER_MODEL})


def execute(out):
    os.environ.setdefault('A3GAME_GUI_SLOTS', '2')
    os.environ.setdefault('A3GAME_CODEX_INLINE_SCHEMA', '1')
    from ..stage1 import pipeline
    out = Path(out).resolve()
    with locked(out):
        require(shutil.disk_usage(out).free >= RESERVE + 2 * 1024 ** 3,
                'natural recovery requires 2GiB estimated usage plus 8GiB reserve')
        activate(out)
        exclusive(out / REL / 'execute.claim.json', {'version': VERSION, 'max_actual_takes': 2, 'at': time.time()})
        os.environ.setdefault('GAMEFACTORY_UNITY_IMGUI_FORWARD', '1')
        manifest = prepare.verify(out)
        result = pipeline.run_playable(Path(manifest['delivery_dir']), out, models=manifest['models'], takes=2)
        return finish(out, result)


def cleanup_ok(capture):
    native = capture / 'native'
    editor = read_json(native / 'editor_cleanup.json')
    require(all(editor.get(key) is True for key in ('ok', 'process_exit_verified',
            'group_exit_verified', 'detached_exit_verified'))
            and read_json(capture / 'editor_cleanup.json') == editor, 'editor cleanup not proven')
    inputs = read_json(native / 'background_input_cleanup.json')
    require(all(inputs.get(key) is True for key in ('ok', 'keys_and_buttons_released',
            'virtual_devices_removed', 'settings_restored', 'muted_devices_restored',
            'input_filter_removed')), 'input cleanup not proven')
    require(read_json(native / 'background_view_cleanup.json').get('ok') is True, 'view cleanup not proven')


def verify_capture_files(capture, count):
    for channel in ('actions.jsonl', 'state_trace.jsonl', 'event_trace.jsonl', 'frame_index.jsonl'):
        require(sha256(capture / channel) == sha256(capture / 'native' / channel),
                'canonical/native evidence differs: ' + channel)
    frames = [json.loads(line) for line in (capture / 'frame_index.jsonl').read_text().splitlines() if line.strip()]
    require(type(count) is int and count > 0 and len(frames) == count, 'retained frame count differs')
    paths = []
    for frame in frames:
        relative = Path(frame['path'])
        require(not relative.is_absolute() and '..' not in relative.parts and relative.parts[0] == 'frames',
                'frame escapes capture')
        canonical, raw = capture / relative, capture / 'native' / relative
        require(not canonical.is_symlink() and not raw.is_symlink() and sha256(canonical) == sha256(raw),
                'canonical/raw frame bytes differ')
        paths.append(str(relative))
    require(len(set(paths)) == len(paths), 'duplicate retained frames')


def verify_takes(out, result):
    require(result.get('complete') is True and result == read_json(out / 'playable_score.json'),
            'official complete playable score required')
    takes = result.get('takes', [])
    require([row.get('take') for row in takes] in ([1], [1, 2]), 'invalid bounded take sequence')
    require({p.name for p in (out / 'takes').iterdir() if p.is_dir()} == {str(row['take']) for row in takes},
            'unaccounted take directory')
    for row in takes:
        k = row['take']
        capture = out / f'takes/{k}/record'
        executable = read_json(out / f'takes/{k}/plan.json')
        entry.validate_plan(out, executable)
        require(accepted_response(out / 'model_calls', f'plan_t{k}_natural_entry_v1') == executable,
                'plan differs from actual accepted corrected-contract response')
        cleanup_ok(capture)
        command = read_json(capture / 'native/editor_cleanup.json')['command']
        entry.verify_arguments(command)
        from engine_adapters.unity3d.playtest.runtime_initializer import METHOD
        for flag, expected in (('-executeMethod', METHOD),
                               ('-projectPath', str(out / 'runtime/project')),
                               ('--gamefactory-evaluation-scene', ''),
                               ('--gamefactory-runtime-entry-source', executable['launch_source']),
                               ('--gamefactory-runtime-entry-receipt', str(capture / 'native/runtime_initializer_native.json'))):
            require(command.count(flag) == 1 and command[command.index(flag) + 1] == expected,
                    'native command differs from natural entry: ' + flag)
        record = read_json(capture / 'record_result.json')
        report = read_json(capture / 'native/report.json')
        require(record['frames'] > 0 and not record['failed_actions']
                and record['plan_sha256'] == sha256(out / f'takes/{k}/plan.json'), 'record identity/input failed')
        require(report.get('status') == 'passed' and report.get('requested_seconds') == 75
                and report.get('recorded_seconds', 0) >= 75 and not report.get('errors')
                and report.get('engine') == 'unity3d'
                and Path(report['url']).resolve() == out / 'runtime/project'
                and Path(report['output_dir']).resolve() == capture / 'native', 'no qualified real 75s capture')
        require(report.get('frames') == record['frames'], 'native frame count differs')
        verify_capture_files(capture, record['frames'])
        native = read_json(capture / 'native/runtime_initializer_native.json')
        entry.verify_native_lifecycle(out, native)
        binding = read_json(capture / 'runtime_initializer_entry.json')
        require(binding['plan_sha256'] == sha256(out / f'takes/{k}/plan.json')
                and binding['contract_sha256'] == sha256(out / REL / 'contract.json'), 'native binding changed')
        entry.verify_runtime(out, capture)


def finish(out, result):
    """Offline qualification; never calls a planner or recorder."""
    folder = out / REL
    entry.review(out)
    verify_archive(out)
    production = verify_producer(out)
    verify_takes(out, result)
    # Recompute deterministic official rules from the existing recordings before
    # cleanup; the pipeline's canonical score must agree, not a hand-written score.
    from ..stage1 import playable_rules
    checks = playable_rules.evaluate(out, read_json(out / 'manifest.json'), len(result['takes']))
    require(result['checks'] == {key: checks[key]['status'] for key in playable_rules.IDS}
            and result['playable'] == round(100 * sum(row['status'] == 'PASS' for row in checks.values()) / 3, 2),
            'official score differs from retained rule evidence')
    evidence = {str(p.relative_to(out)): sha256(p) for p in out.rglob('*') if p.is_file()
                and not any(p.is_relative_to(out / part) for part in ('input/project', 'runtime/project'))
                and not p.name.endswith('.lock') and p.name != 'qualification_hold.json'
                and p not in (folder / 'completion.json', folder / 'hold_release.json',
                              folder / 'parent_completion_verification.json')}
    exclusive(folder / 'completion.json', {'version': VERSION, 'qualified': True, 'out': str(out),
              'score': result, 'evidence_sha256': evidence, **production})
    return complete_cleanup(out)


def complete_cleanup(out):
    """Resume after qualification without any model/native operation."""
    folder = out / REL
    verify_completion(out, cleaned=False)
    hold = out / 'qualification_hold.json'
    require(hold.read_bytes() == (folder / 'hold.original.json').read_bytes(), 'hold changed')
    import sys
    sys.path.insert(0, str(FRAMEWORK.parent / 'scripts_new'))
    import playable_retest as runner
    if not (out / 'cleanup.json').exists():
        runner.cleanup(out)
    result = verify_completion(out, cleaned=True)
    hold = out / 'qualification_hold.json'
    require(hold.read_bytes() == (folder / 'hold.original.json').read_bytes(), 'hold changed')
    release = folder / 'hold_release.json'
    value = {'version': VERSION, 'hold_sha256': sha256(hold),
             'completion_sha256': sha256(folder / 'completion.json'), 'cleanup_sha256': sha256(out / 'cleanup.json')}
    if release.exists():
        require(read_json(release) == value, 'hold release changed')
    else:
        exclusive(release, value)
    hold.unlink()
    require(runner.completed_score(out, {}) == result, 'runner did not recognize qualified official score')
    write_json(folder / 'parent_completion_verification.json', {'version': VERSION, 'qualified_complete': True,
               'score_sha256': sha256(out / 'playable_score.json'), 'cleanup_sha256': sha256(out / 'cleanup.json')})
    return result


def verify_completion(out, *, cleaned=True):
    out = Path(out).resolve()
    folder = out / REL
    completion = read_json(folder / 'completion.json')
    require(completion['version'] == VERSION and completion['qualified'] is True
            and completion['out'] == str(out), 'unknown natural completion')
    for relative, digest in completion['evidence_sha256'].items():
        path = out / relative
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts
                and not path.is_symlink() and sha256(path) == digest, 'retained evidence changed: ' + relative)
    manifest = read_json(out / 'manifest.json')
    value = read_json(folder / 'contract.json')
    target, routed = entry.resolve_target(manifest['game_id'])
    require(routed == out and target.get('required_real_clients', 1) == 1
            and target['project'] == manifest['project_source'] == value['project_source']
            and sha256(out / 'manifest.json') == value['manifest_sha256']
            and prepare.tree_digest(prepare.tree_hashes(Path(manifest['project_source']))) == value['project_digest'],
            'completed source or target changed')
    verify_archive(out)
    if cleaned:
        cleanup = read_json(out / 'cleanup.json')
        require(cleanup.get('removed') == ['runtime/project', 'input/project']
                and isinstance(cleanup.get('freed_bytes'), int) and cleanup['freed_bytes'] >= 0
                and not (out / 'runtime/project').exists() and not (out / 'input/project').exists(),
                'official cleanup incomplete')
    require(completion['score'] == read_json(out / 'playable_score.json'), 'canonical score changed')
    return completion['score']



def qualified_completion_score(out):
    """Runner interface: read-only, no runner imports or recursive completion calls.

    No released completion returns None. Corrupt/tampered evidence raises;
    the runner must fail closed. The original hold is retained in the lineage.
    """
    out = Path(out).resolve()
    folder = out / REL
    if ((out / 'qualification_hold.json').exists()
            or not (folder / 'completion.json').is_file()
            or not (folder / 'hold_release.json').is_file()):
        return None
    release = read_json(folder / 'hold_release.json')
    require(release == {'version': VERSION,
                       'hold_sha256': sha256(folder / 'hold.original.json'),
                       'completion_sha256': sha256(folder / 'completion.json'),
                       'cleanup_sha256': sha256(out / 'cleanup.json')}, 'natural hold release changed')
    return verify_completion(out, cleaned=True)


def finalize(out):
    out = Path(out).resolve()
    with locked(out):
        if (out / REL / 'hold_release.json').exists() and not (out / 'qualification_hold.json').exists():
            return verify_completion(out)
        if (out / REL / 'completion.json').exists():
            return complete_cleanup(out)
        return finish(out, read_json(out / 'playable_score.json'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out', type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preview', action='store_true')
    group.add_argument('--execute', action='store_true')
    group.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    result = entry.review(args.out) if args.preview else execute(args.out) if args.execute else finalize(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
