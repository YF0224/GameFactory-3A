"""Bounded Sol G027/G037/G041 Vite build recovery, preserving parent diagnostics.

Only formal Stage1 planner/record/rules/scoring are executed. A fixed child owns
at most two 75s takes. The first accepted plan is reused; a second planner call
is permitted only after a qualified first take leaves operate unresolved.
No parent score, hold, claim, native evidence or project is changed.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil

from pipeline.eval.whitebox.core import prepare, plan
from pipeline.eval.whitebox.core.paths import read_json, sha256, write_json

VERSION = 'stage1-vite-build-only-recovery.v1'
LINEAGE = 'recovery/vite_build_only_v1'
CASES = {'G027_dune_maze_td', 'G037_night_drift_yard', 'G041_frontier_market'}
RESERVE = 8 * 1024 ** 3
ROOT = Path(__file__).resolve().parents[3]
ERROR = 'Failed to resolve module specifier "three".'


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def tree(root, *, skip=()):
    """Hash retained files without following links or including live lock files."""
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        base = Path(directory)
        dirs[:] = [d for d in dirs if str((base/d).relative_to(root)) not in skip]
        for name in dirs + names:
            p = base/name
            require(not p.is_symlink(), f'linked evidence: {p}')
        for name in names:
            if name.endswith('.lock'):
                continue
            p = base/name
            result[str(p.relative_to(root))] = sha256(p)
    return result


def retained(root):
    return tree(root, skip=('runtime', 'input/project', 'recovery'))


def production():
    roots = ['pipeline/eval/stage1', 'engine_adapters/three_js', 'engine_adapters/common']
    files = {str(p.relative_to(ROOT)): sha256(p) for name in roots for p in (ROOT/name).rglob('*')
             if p.is_file() and p.suffix in {'.py', '.mjs', '.js', '.cs', '.json'}
             and '__pycache__' not in p.parts}
    for name in ('engine_adapters/_input_capabilities.py', 'engine_adapters/_mouse_plan.py',
                 'pipeline/eval/model_config.py'):
        files[name] = sha256(ROOT/name)
    return files


@contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


@contextmanager
def environment(project):
    """The own installed copy is the explicit environment the authored config uses."""
    from engine_adapters.three_js.playtest.launch import build_environment
    previous = os.environ.get('A3GAME_WEB_ENV')
    os.environ['A3GAME_WEB_ENV'] = str(project.resolve())
    try:
        build_environment(project)
        yield
    finally:
        if previous is None:
            os.environ.pop('A3GAME_WEB_ENV', None)
        else:
            os.environ['A3GAME_WEB_ENV'] = previous


def accepted(out):
    receipt_path = out/'model_calls/plan_t1/accepted_response.json'
    receipt = read_json(receipt_path)
    response = (receipt_path.parent/receipt['path']).resolve()
    require(response.is_relative_to((out/'model_calls').resolve()), 'accepted response escapes model calls')
    require(sha256(response) == receipt['sha256'], 'accepted planner SHA mismatch')
    executable = read_json(out/'takes/1/plan.json')
    require(executable == read_json(response), 'executable differs from accepted response')
    return {'receipt_sha256': sha256(receipt_path), 'response_sha256': sha256(response),
            'plan_sha256': sha256(out/'takes/1/plan.json')}


def native_cleanup(native):
    inputs = read_json(native/'input_view_cleanup.json')
    browser = read_json(native/'browser_cleanup.json')
    host = read_json(native/'host_process_cleanup.json')
    require(inputs.get('input_cleanup') is True and inputs.get('held_keys_after_release') == 0
            and inputs.get('held_buttons_after_release') == 0, 'input cleanup unproven')
    require(all(browser.get(k) is True for k in ('view_cleanup', 'browser_cleanup', 'input_cleanup')),
            'browser cleanup unproven')
    require(host.get('process_cleanup') is True and host.get('server_group_alive') is False
            and host.get('recorder', {}).get('process_cleanup') is True
            and host['recorder'].get('group_alive') is False, 'owned process cleanup unproven')


def failed_parent(out):
    manifest = read_json(out/'manifest.json')
    require(manifest['game_id'] in CASES and manifest['engine'] == 'three_js'
            and manifest['delivery']['model'] == 'sol', 'outside approved recovery identities')
    require(manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'}, 'unexpected model route')
    require(sorted(p.name for p in (out/'takes').iterdir()) == ['1'], 'unexpected existing takes')
    source = Path(manifest['project_source'])
    require(prepare.tree_digest(prepare.tree_hashes(source)) == manifest['project_digest'], 'original source drift')
    from engine_adapters.three_js.playtest.launch import build_only_vite
    require(build_only_vite(read_json(source/'package.json')), 'not strictly build-only Vite')
    launch = read_json(out/'takes/1/record/launch_selection.json')
    require(launch['mode'] == 'static' and launch['build_script'] is None
            and Path(launch['serve_root']).name == 'project', 'not omitted Vite build')
    progress = list((out/'takes/1/record/native').glob('*/recording_progress.json'))
    require(len(progress) == 1, 'ambiguous original native attempt')
    native = progress[0].parent
    native_cleanup(native)
    if manifest['game_id'] == 'G027_dune_maze_td':
        hold = read_json(out/'qualification_hold.json')
        require(hold['kind'] == 'HARNESS_VITE_BUILD_OMITTED', 'missing parent qualification hold')
        for name, value in hold['diagnostic_evidence_sha256'].items():
            require(sha256(out/name) == value, f'held diagnostic drift: {name}')
        for name, value in hold['source_files'].items():
            require(sha256(Path(name)) == value, 'held source drift')
        rules = read_json(out/'playable_rules.json')
        require(rules['launch']['1']['valid'] == 0 and rules['launch']['1']['sampled'] > 0,
                'cannot replace qualified game-content recording')
    else:
        require(not (out/'playable_score.json').exists(), 'already scored')
        state = read_json(out/'status.json')
        require(state['state'] == 'HARNESS_ERROR' and state['step'] == 'record_t1', 'not failed record_t1')
        p = read_json(progress[0])
        require(p['status'] == 'failed' and p['frames'] == 0 and p['recorded_seconds'] == 0
                and all(p['channels_written'].get(k) == 0 for k in ('actions', 'states', 'events'))
                and p['reason'].startswith(ERROR), 'not the proven zero-frame/zero-input module failure')
        require(not (out/'takes/1/record/record_result.json').exists(), 'qualified record exists')
    return manifest, accepted(out)


def check_space(root, size=2 * 1024**3):
    require(shutil.disk_usage(root).free >= RESERVE + size, 'insufficient free space plus 8GiB reserve')


def prepare_child(out):
    lineage = out/LINEAGE
    manifest, original_plan = failed_parent(out)
    check_space(out)
    binding = {'parent': str(out), 'parent_files': retained(out), 'accepted_plan': original_plan,
               'source_digest': manifest['project_digest'], 'production': production(),
               'max_gameplay_takes': 2, 'gameplay_ms': 75000}
    child = lineage/'child'
    ready = lineage/'prepared.json'
    if ready.exists():
        saved = read_json(ready)
        require(saved['binding'] == binding, 'recovery parent/producer drift')
        require(child.is_dir(), 'prepared child missing')
        return saved
    require(not child.exists(), 'partial preparation exists; preserve and inspect')
    lineage.mkdir(parents=True, exist_ok=True)
    write_json(lineage/'binding.json', binding)
    # Exact parent bytes and executable production are archival only, never imported.
    for name in binding['parent_files']:
        dest = lineage/'parent_archive'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(out/name, dest)
    for name in binding['production']:
        dest = lineage/'production_sources'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, dest)
    child.mkdir()
    shutil.copy2(out/'manifest.json', child/'manifest.json')
    shutil.copytree(out/'input', child/'input', ignore=lambda directory, names:
                    ['project'] if Path(directory) == out/'input' else [])
    frozen = out/'input/project'
    if frozen.is_dir():
        shutil.copytree(frozen, child/'input/project')
    else:
        require((out/'cleanup.json').is_file(), 'missing snapshot without formal cleanup')
        shutil.copytree(Path(manifest['project_source']), child/'input/project', ignore=prepare.IGNORE)
    shutil.copytree(child/'input/project', child/'runtime/project')
    shutil.copytree(out/'model_calls', child/'model_calls')
    (child/'takes/1').mkdir(parents=True)
    for name in ('plan.json', 'plan_coverage.json'):
        shutil.copy2(out/'takes/1'/name, child/'takes/1'/name)
    prepare.verify(child)
    require(accepted(child) == original_plan, 'plan changed while preparing child')
    require(retained(out) == binding['parent_files'], 'parent changed during preparation')
    prepared = {'schema': VERSION, 'binding': binding, 'child': str(child),
                'child_source_files': prepare.tree_hashes(child/'input/project')}
    write_json(ready, prepared)
    return prepared


def ensure_environment(child, lineage):
    from engine_adapters.three_js.config import ThreeClientConfig
    from engine_adapters.three_js._internal.transport.node import NodeToolchain
    from engine_adapters.three_js.playtest import dependencies
    from engine_adapters.three_js.playtest.launch import resolve_launch
    project = child/'runtime/project'
    before = sha256(project/'package.json')
    toolchain = NodeToolchain(ThreeClientConfig.resolve(project_path=project))
    if dependencies.project_needs_install(project):
        claim = lineage/'dependency_install_claim.json'
        with claim.open('x') as f:
            json.dump({'project': str(project), 'timeout_s': 90}, f)
        dependencies.install_project_dependencies(project, toolchain, timeout=90, log_dir=lineage/'environment')
    require(sha256(project/'package.json') == before, 'authored package changed')
    packages = read_json(project/'package.json')
    versions = {}
    for name in ('vite', 'three'):
        file = project/'node_modules'/name/'package.json'
        version = read_json(file)['version']
        declared = {**packages.get('dependencies', {}), **packages.get('devDependencies', {})}[name]
        require(version == declared, f'installed {name} differs from frozen exact version')
        versions[name] = {'version': version, 'manifest_sha256': sha256(file)}
    with environment(project):
        selected = resolve_launch(project)
    require(selected.get('build_kind') == 'vite_build_only', 'new build route not selected')
    receipt = {'environment': {'A3GAME_WEB_ENV': str(project.resolve())}, 'packages': versions,
               'package_sha256': before, 'selection': selected,
               'reason': 'Own exact declared dependencies; env inherited before authored npm build'}
    write_json(lineage/'environment.json', receipt)
    return receipt


def qualified_record(child, take):
    r = child/f'takes/{take}/record'
    result = read_json(r/'record_result.json')
    adapter = read_json(r/'adapter_result.json')
    require(adapter.get('ok') is True, 'adapter record not successful')
    paths = list((r/'native').glob('*/recording_progress.json'))
    require(len(paths) == 1, 'ambiguous child native recording')
    progress = read_json(paths[0]); native_cleanup(paths[0].parent)
    report = read_json(paths[0].parent/'report.json')
    require(progress['status'] == 'completed' and progress['requested_seconds'] == 75
            and report.get('sampling_complete') is True and report.get('wallclock_seconds', 0) >= 75
            and report.get('capture_deadline_ms') == 75000 and progress['frames'] > 0
            and progress['channels_written']['actions'] > 0, 'incomplete genuine 75s capture')
    launch = read_json(r/'launch_selection.json')
    require(launch.get('build_kind') == 'vite_build_only'
            and launch.get('preview_provider') == 'python_http_server'
            and Path(launch['serve_root']).name == 'dist', 'not serving the authored build')
    require(adapter['payload'].get('delivered_build_completed') is True, 'build not completed')
    require((r/'delivered_build.log').is_file(), 'missing authored build log')
    return {'take': take, 'frames': progress['frames'], 'wallclock_seconds': report['wallclock_seconds'],
            'actions': progress['channels_written']['actions'], 'record_sha256': sha256(r/'record_result.json'),
            'build_log_sha256': sha256(r/'delivered_build.log'), 'native': str(paths[0].parent.relative_to(child))}


def _verify_parent(out, prepared):
    require(retained(out) == prepared['binding']['parent_files'], 'parent diagnostics changed')
    archive = out/LINEAGE/'parent_archive'
    require(tree(archive) == prepared['binding']['parent_files'], 'parent archive changed')
    manifest = read_json(out/'manifest.json')
    require(prepare.tree_digest(prepare.tree_hashes(Path(manifest['project_source'])))
            == prepared['binding']['source_digest'], 'original source changed')


def execute(out):
    from pipeline.eval.whitebox.core import pipeline, playable_rules, record
    out = Path(out).resolve(); lineage = out/LINEAGE
    with locked(out/'.vite-build-only-recovery.lock'):
        if (lineage/'replacement.json').exists():
            score = qualified_replacement_score(out)
            require(score is not None, 'existing replacement failed verification')
            return score
        with locked(out/'takes/1/record/.postprocess.lock'):
            prepared = prepare_child(out)
        child = lineage/'child'
        pinned = prepared['binding']['production']
        require(production() == pinned, 'producer drift before execution')
        ensure_environment(child, lineage)
        manifest = prepare.verify(child)
        require(manifest['budget']['gameplay_ms'] == manifest['budget']['recording_ms'] == 75000,
                'unexpected playable duration')
        feedback = None
        recordings = []
        with environment(child/'runtime/project'):
            for take in (1, 2):
                check_space(out)
                require(production() == pinned, 'producer drift before take')
                if take == 2:
                    require(feedback is not None, 'second take lacks unresolved operate feedback')
                executable = plan.make_plan(child, manifest, take, ['play.launch', 'play.operate'], feedback)
                r = child/f'takes/{take}/record'
                if not (r/'record_result.json').exists():
                    claim = lineage/f'record_t{take}_claim.json'
                    with claim.open('x') as f:
                        json.dump({'take': take, 'plan_sha256': sha256(child/f'takes/{take}/plan.json'),
                                   'production_sha256': digest(pinned), 'gameplay_ms': 75000}, f)
                    record.record(child, manifest, executable, take)
                recordings.append(qualified_record(child, take))
                verdicts = playable_rules.evaluate(child, manifest, take)
                write_json(lineage/f'take_{take}_qualified.json', {'record': recordings[-1], 'verdicts': verdicts})
                if verdicts['play.operate']['status'] == 'PASS' or verdicts['play.launch']['status'] == 'FAIL':
                    break
                feedback = {'earlier_plans': [read_json(child/f'takes/{k}/plan.json')['summary']
                                               for k in range(1, take+1)],
                            'judge_reasons': {'play.operate': verdicts['play.operate']['reason']}}
        require(production() == pinned, 'producer drift after native recording')
        _verify_parent(out, prepared)
        # Every take is now qualified and cached: the official entry only evaluates/scores.
        score = pipeline.run_playable(Path(manifest['delivery_dir']), child,
                                      models={'planner': PLANNER_MODEL, 'judge': 'none'}, takes=len(recordings))
        require(score['complete'] is True, 'official playable score incomplete')
        for name, value in prepared['child_source_files'].items():
            require(sha256(child/'runtime/project'/name) == value, f'authored runtime source changed: {name}')
        source_receipt = {'source_digest': prepared['binding']['source_digest'],
                          'files': prepared['child_source_files'], 'original_and_runtime_unchanged': True}
        write_json(lineage/'source_integrity.json', source_receipt)
        # Retain all evidence and exact author-source snapshot, remove only this child's copies.
        shutil.copytree(child/'input/project', lineage/'source_archive')
        removed = []; freed = 0
        for rel in ('runtime/project', 'input/project'):
            cache = child/rel
            freed += sum(p.stat().st_size for p in cache.rglob('*') if p.is_file() and not p.is_symlink())
            shutil.rmtree(cache); removed.append(rel)
        write_json(child/'cleanup.json', {'removed': removed, 'freed_bytes': freed,
                   'native_input_view_process_cleanup': True, 'source_archive': '../source_archive'})
        evidence_files = tree(child, skip=('runtime',))
        final = {'schema': VERSION, 'parent': str(out), 'child': str(child), 'records': recordings,
                 'parent_binding_sha256': sha256(lineage/'prepared.json'), 'production_sha256': digest(pinned),
                 'evidence_files': evidence_files, 'score_sha256': sha256(child/'playable_score.json'),
                 'source_receipt_sha256': sha256(lineage/'source_integrity.json'),
                 'source_archive_files': tree(lineage/'source_archive'),
                 'parent_diagnostics_preserved': True, 'scoring_entry': 'pipeline.eval.whitebox.pipeline.run_playable'}
        write_json(lineage/'finalization.json', final)
        write_json(lineage/'replacement.json', {'schema': VERSION, 'child': str(child.relative_to(out)),
                    'finalization_sha256': sha256(lineage/'finalization.json'),
                    'child_score_sha256': final['score_sha256'], 'parent_score_and_hold_preserved': True})
        require(qualified_replacement_score(out) == score, 'replacement independent verification failed')
        return score


def qualified_replacement_score(out):
    """Read-only runner hook; validates saved producer, parent, sources and every child byte."""
    try:
        out = Path(out).resolve(); lineage = out/LINEAGE; child = lineage/'child'
        replacement = read_json(lineage/'replacement.json')
        final = read_json(lineage/'finalization.json'); prepared = read_json(lineage/'prepared.json')
        require(replacement['schema'] == final['schema'] == VERSION, 'wrong receipt schema')
        require(replacement['child'] == str(child.relative_to(out)) and final['parent'] == str(out)
                and final['child'] == str(child), 'replacement identity differs')
        require(sha256(lineage/'finalization.json') == replacement['finalization_sha256']
                and sha256(lineage/'prepared.json') == final['parent_binding_sha256'], 'receipt changed')
        require(tree(lineage/'production_sources') == prepared['binding']['production']
                and digest(prepared['binding']['production']) == final['production_sha256'], 'saved producer changed')
        _verify_parent(out, prepared)
        require(tree(child, skip=('runtime',)) == final['evidence_files'], 'child evidence changed')
        require(sha256(lineage/'source_integrity.json') == final['source_receipt_sha256']
                and tree(lineage/'source_archive') == final['source_archive_files']
                == prepared['child_source_files'], 'saved author source changed')
        require(sha256(child/'playable_score.json') == replacement['child_score_sha256'] == final['score_sha256'],
                'score changed')
        score = read_json(child/'playable_score.json')
        require(score['game_id'] in CASES and score['engine'] == 'three_js' and score['complete'] is True
                and score['planner'] == PLANNER_MODEL and read_json(child/'status.json')['state'] == 'done'
                and len(final['records']) in (1, 2), 'not completed')
        require([qualified_record(child, r['take']) for r in final['records']] == final['records'], 'record drift')
        require(score['game_id'] == read_json(out/'manifest.json')['game_id'], 'parent identity mismatch')
        return score
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if args.execute:
        value = execute(args.out)
    else:
        manifest, receipt = failed_parent(args.out.resolve())
        value = {'eligible': True, 'game_id': manifest['game_id'], 'accepted_plan': receipt,
                 'replacement': qualified_replacement_score(args.out)}
    print(json.dumps(value, indent=2))


if __name__ == '__main__':
    main()
