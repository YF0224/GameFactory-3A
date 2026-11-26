"""Bounded pre-record readiness/shared-web recovery for exact approved failures.

Preserves original attempts and accepted first plan. Uses the formal Stage1
entry, at most two genuine 75s takes, Astra planning only for unresolved operate.
No game sources or dependency declarations are repaired. Archived code is never
executed. Each native boundary archives actual production bytes; concurrent drift is retained.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from urllib.parse import urlsplit

from pipeline.eval.whitebox.core import prepare, plan
from pipeline.eval.whitebox.core.paths import read_json, sha256, write_json
from .vite_build_only_recovery import (require, digest, tree, retained, production,
    locked, accepted, native_cleanup, check_space, ROOT)

VERSION = 'stage1-web-readiness-recovery.v1'
LINEAGE = 'recovery/web_readiness_v1'
IDENTITIES = {('sol', 'G036_salt_flat_timetrial'), ('sol', 'G042_highland_seed_farm'),
              ('glm', 'G012_gravity_mine'), ('glm', 'G017_lighthouse_prism'),
              ('glm', 'G057_rhythm_machine_hall'), ('sol', 'G051_village_lost_found'),
              ('glm', 'G027_dune_maze_td'), ('glm', 'G026_signal_tower_td'),
              ('astra', 'G011_cloud_mail_runner'), ('glm', 'G011_cloud_mail_runner'),
              ('glm', 'G016_theater_sorting'), ('glm', 'G036_salt_flat_timetrial'),
              ('glm', 'G037_night_drift_yard'), ('astra', 'G017_lighthouse_prism'), ('astra', 'G027_dune_maze_td'),
              ('astra', 'G012_gravity_mine'), ('astra', 'G016_theater_sorting'), ('astra', 'G037_night_drift_yard'),
              ('astra', 'G041_frontier_market'), ('astra', 'G026_signal_tower_td'),
              ('astra', 'G036_salt_flat_timetrial'), ('astra', 'G042_highland_seed_farm'),
              ('astra', 'G051_village_lost_found')}
CONFIGURED_VITE_IDENTITIES = {('kimi', 'G041_frontier_market'), ('kimi', 'G042_highland_seed_farm')}
IDENTITIES |= CONFIGURED_VITE_IDENTITIES
AUTHORED_STATIC_IDENTITIES = {('astra', 'G027_dune_maze_td'), ('astra', 'G026_signal_tower_td')}
CASES = {case for _, case in IDENTITIES}
SHARED = ROOT.parent / '.tools/whitebox-web-deps'


@contextmanager
def environment(project, *, shared=False):
    previous = os.environ.get('A3GAME_WEB_ENV')
    if shared:
        os.environ['A3GAME_WEB_ENV'] = str(SHARED.resolve())
    else:
        # Only own installed dependencies may supply this case's toolchain.
        os.environ['A3GAME_WEB_ENV'] = str(project.resolve())
    try:
        from engine_adapters.three_js.playtest.launch import build_environment
        build_environment(project)
        yield
    finally:
        if previous is None: os.environ.pop('A3GAME_WEB_ENV', None)
        else: os.environ['A3GAME_WEB_ENV'] = previous


def authored_static_launch(source, runtime, launch):
    """Require the unchanged delivered nested bundle, including author report hashes."""
    from engine_adapters.three_js.playtest.launch import resolve_launch
    source, runtime = source.resolve(), runtime.resolve()
    expected = resolve_launch(source)
    require(expected['mode'] == 'static' and expected.get('author_entry'),
            'not an explicitly authored static bundle')
    for key in ('mode', 'script', 'build_script', 'url_path'):
        require(launch.get(key) == expected.get(key), 'authored static route changed: ' + key)
    for key in ('cwd', 'serve_root', 'entry'):
        relative = Path(expected[key]).relative_to(source)
        require(Path(launch[key]).resolve() == runtime/relative,
                'authored static path changed: ' + key)
    proof = dict(expected['author_entry'])
    proof['report'] = str(runtime/'generation_report.json')
    require(launch.get('author_entry') == proof, 'authored static entry proof changed')
    return proof


def authored_configured_vite_launch(source, runtime, launch):
    """Bind the native route to the unchanged delivered config, package and HTML."""
    from engine_adapters.three_js.playtest.launch import resolve_launch
    source, runtime = source.resolve(), runtime.resolve()
    expected = resolve_launch(source)
    require(expected['mode'] == 'configured_vite', 'not authored scriptless Vite')
    for key in ('mode', 'script', 'build_script', 'url_path'):
        require(launch.get(key) == expected.get(key), 'configured Vite route changed: ' + key)
    for key in ('cwd', 'serve_root', 'entry'):
        require(Path(launch[key]).resolve() == runtime / Path(expected[key]).relative_to(source),
                'configured Vite path changed: ' + key)
    proof = dict(expected['authored_vite'])
    proof['config'] = str(runtime / Path(proof['config']).relative_to(source))
    require(launch.get('authored_vite') == proof, 'configured Vite source proof changed')
    return proof


def configured_vite_failed_capture(out, manifest, adapter, launch):
    """Only the exact module-resolution failure before any native frame/input."""
    require(launch['mode'] == 'static' and launch.get('script') is None
            and launch.get('build_script') is None, 'not mistaken static fallback')
    require(adapter['ok'] is False and adapter['errors'] ==
            ['Invalid current playtest evidence: Recorder exited with code 1'], 'unexpected adapter failure')
    roots = list((out/'takes/1/record/native').iterdir())
    require(len(roots) == 1 and roots[0].is_dir() and not roots[0].is_symlink(), 'ambiguous failed native')
    native = roots[0]
    require(Path(adapter['payload']['report_path']).resolve() == (native/'report.json').resolve(),
            'failed report binding changed')
    progress = read_json(native/'recording_progress.json')
    error = 'Failed to resolve module specifier "three". Relative references must start with either "/", "./", or "../".'
    require(progress['status'] == 'failed' and progress['frames'] == 0
            and progress['recorded_seconds'] == 0 and progress['reason'] == error
            and progress['channels_written'] == {'actions':0, 'states':0, 'events':0},
            'not exact zero-frame module failure')
    require(not any((native/'frames').iterdir()) and not (native/'frame_index.jsonl').read_text().strip(),
            'existing frame evidence requires separate recovery')
    native_cleanup(native)
    source = Path(manifest['project_source'])
    from engine_adapters.three_js.playtest.launch import resolve_launch
    selected = resolve_launch(source)
    authored_configured_vite_launch(source, source, selected)


def failed_parent(out):
    manifest = read_json(out/'manifest.json')
    identity = (manifest['delivery']['model'], manifest['game_id'])
    require(identity in IDENTITIES and manifest['engine'] == 'three_js', 'outside approved identities')
    require(manifest['delivery'].get('required_real_clients', 1) == 1,
            'multi-client target requires canonical dual-client recovery')
    require(manifest['models'] == {'planner':PLANNER_MODEL,'judge':'none'}, 'unexpected models')
    require(sorted(p.name for p in (out/'takes').iterdir()) == ['1'], 'unexpected existing takes')
    require(not (out/'playable_score.json').exists(), 'already scored')
    state = read_json(out/'status.json')
    require(state['state'] == 'HARNESS_ERROR' and state['step'] == 'record_t1', 'not terminal record_t1')
    record = out/'takes/1/record'
    require(not (record/'record_result.json').exists(), 'qualified native exists')
    adapter = read_json(record/'adapter_result.json')
    launch = read_json(record/'launch_selection.json')
    if identity in CONFIGURED_VITE_IDENTITIES:
        configured_vite_failed_capture(out, manifest, adapter, launch)
        source = Path(manifest['project_source'])
        require(prepare.tree_digest(prepare.tree_hashes(source)) == manifest['project_digest'], 'source drift')
        return manifest, accepted(out)
    require(not any((record/'native').glob('*')), 'native artifacts exist; inspect last qualified stage')
    require(adapter['ok'] is False and not adapter['payload']['url']
            and adapter['payload'].get('report_path') is None, 'not a pre-record failure')
    launch = read_json(record/'launch_selection.json')
    errors = adapter['errors']
    shared = manifest['game_id'] == 'G057_rhythm_machine_hall'
    if shared:
        require(len(errors) == 1 and 'dev server exited with code 127:' in errors[0]
                and re.search(r'(?:vite: command not found|vite: not found)', errors[0]),
                'not exact missing-vite failure')
        source = Path(manifest['project_source'])
        package = read_json(source/'package.json')
        require(not package.get('dependencies') and not package.get('devDependencies')
                and package['scripts'].get('dev') == 'vite'
                and 'A3GAME_WEB_ENV' in (source/'vite.config.js').read_text(),
                'not authored explicit shared toolchain')
    else:
        expected = 'cannot serve the project for recording: RuntimeError: dev server did not answer on '
        require(errors == [expected + launch['url'] + ' within 45s'], 'not exact readiness timeout')
    source = Path(manifest['project_source'])
    require(prepare.tree_digest(prepare.tree_hashes(source)) == manifest['project_digest'], 'source drift')
    if identity[0] == 'sol':
        from engine_adapters.three_js.playtest.launch import build_only_vite
        require(build_only_vite(read_json(source/'package.json')) and launch['mode'] == 'static'
                and launch['build_script'] is None, 'not omitted build-only Vite')
    elif identity in AUTHORED_STATIC_IDENTITIES:
        authored_static_launch(source, out/'runtime/project', launch)
    else:
        require(launch['mode'] == 'script' and launch['script'] == 'dev', 'not authored dev entry')
    return manifest, accepted(out)


def pre_record_process_check(out):
    """Read-only check: never stop an old server or release another session's locks."""
    launch = read_json(out/'takes/1/record/launch_selection.json')
    target = urlsplit(launch['url'])
    require(target.hostname == '127.0.0.1' and target.port is not None, 'unexpected old endpoint')
    lsof = subprocess.run(['lsof','-nP',f'-iTCP:{target.port}','-sTCP:LISTEN'],capture_output=True,text=True)
    require(lsof.returncode in (0,1), 'cannot inspect old endpoint ownership')
    require(not lsof.stdout.strip() and not lsof.stderr.strip(), 'old endpoint occupied; preserve and inspect')
    ps = subprocess.run(['ps','-axo','pid,ppid,command'],capture_output=True,text=True,check=True)
    runtime = str((out/'runtime/project').resolve())
    require(not any(runtime in line for line in ps.stdout.splitlines()), 'old runtime still has a process')
    return {'old_url':launch['url'],'old_endpoint_has_listener':False,
            'old_runtime_processes':[], 'external_processes_modified':False}


def prepare_child(out):
    lineage = out/LINEAGE
    manifest, original_plan = failed_parent(out)
    check_space(out)
    process_check = pre_record_process_check(out)
    binding = {'parent': str(out), 'parent_files': retained(out), 'accepted_plan': original_plan,
               'source_digest': manifest['project_digest'], 'production': production(),
               'max_gameplay_takes': 2, 'gameplay_ms': 75000}
    child = lineage/'child'
    ready = lineage/'prepared.json'
    if ready.exists():
        saved = read_json(ready)
        require({k:v for k,v in saved['binding'].items() if k != 'production'} ==
                {k:v for k,v in binding.items() if k != 'production'}, 'recovery parent drift')
        require(tree(lineage/'production_sources') == saved['binding']['production'], 'saved producer drift')
        require(child.is_dir(), 'prepared child missing')
        return saved
    require(not child.exists(), 'partial preparation exists; preserve and inspect')
    lineage.mkdir(parents=True, exist_ok=True)
    write_json(lineage/'binding.json', binding)
    write_json(lineage/'pre_record_process_check.json', process_check)
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


def authored_version(source, name, declaration):
    """Honor exact pins or the author's existing lock; never resolve a new range."""
    if re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', declaration):
        return declaration
    lock = read_json(source/'package-lock.json')
    version = lock.get('packages', {}).get('node_modules/'+name, {}).get('version')
    require(isinstance(version, str) and bool(re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version)),
            f'author range for {name} requires an existing frozen lock version')
    return version


def ensure_environment(child, lineage):
    from engine_adapters.three_js.config import ThreeClientConfig
    from engine_adapters.three_js._internal.transport.node import NodeToolchain
    from engine_adapters.three_js.playtest import dependencies
    from engine_adapters.three_js.playtest.launch import resolve_launch
    project = child/'runtime/project'
    manifest = read_json(child/'manifest.json')
    shared = manifest['game_id'] == 'G057_rhythm_machine_hall'
    before = sha256(project/'package.json')
    toolchain = NodeToolchain(ThreeClientConfig.resolve(project_path=project))
    if not shared and dependencies.project_needs_install(project):
        with (lineage/'dependency_install_claim.json').open('x') as f:
            json.dump({'project':str(project),'timeout_s':90},f)
        dependencies.install_project_dependencies(project,toolchain,timeout=90,log_dir=lineage/'environment')
    # No package/dependency injection for the author's explicitly shared case.
    require(sha256(project/'package.json') == before, 'authored package changed')
    root = SHARED if shared else project
    shared_proof = None
    if shared:
        proof_path = ROOT/'workspaces/whitebox_eval_mechanic_basic_path_v3/engineering/glm057_launch_diagnosis_20261104_180707/qualified_toolchain.json'
        shared_proof = read_json(proof_path)
        require(Path(shared_proof['shared_environment']).resolve() == root.resolve(), 'shared environment identity drift')
        for name, expected in shared_proof['files'].items():
            require(Path(name).resolve().is_relative_to(root.resolve()) and sha256(Path(name)) == expected,
                    'explicit shared toolchain differs from qualified original')
    require(not dependencies.verify_critical_packages(root,['vite','three']), 'toolchain incomplete')
    versions = {}
    package = read_json(project/'package.json')
    declared = {**package.get('dependencies',{}), **package.get('devDependencies',{})}
    for name in ('vite','three'):
        p = root/'node_modules'/name/'package.json'; version=read_json(p)['version']
        if not shared:
            expected = authored_version(child/'input/project', name, declared[name])
            require(version == expected, f'installed {name} differs from author pin/lock')
        versions[name] = {'version':version,'manifest_sha256':sha256(p)}
    with environment(project,shared=shared): selected=resolve_launch(project)
    if manifest['delivery']['model'] == 'sol':
        require(selected.get('build_kind') == 'vite_build_only', 'build-only route not selected')
    elif (manifest['delivery']['model'], manifest['game_id']) in AUTHORED_STATIC_IDENTITIES:
        authored_static_launch(child/'input/project', project, selected)
    elif (manifest['delivery']['model'], manifest['game_id']) in CONFIGURED_VITE_IDENTITIES:
        authored_configured_vite_launch(child/'input/project', project, selected)
    else: require(selected['mode'] == 'script' and selected['script'] == 'dev', 'dev route changed')
    files = [root/'package.json',root/'package-lock.json',root/'node_modules/vite/package.json',
             root/'node_modules/three/package.json',root/'node_modules/vite/bin/vite.js']
    receipt = {'environment':{'A3GAME_WEB_ENV':str(root.resolve())},'shared':shared,'packages':versions,
               'package_sha256':before,'selection':selected,'shared_qualification':shared_proof,
               'toolchain_sha256':{str(p):sha256(p) for p in files if p.is_file()}}
    snapshot = lineage/'environment_snapshot'
    for file in files:
        if file.is_file():
            dest = snapshot/file.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists(): require(sha256(dest) == sha256(file), 'environment snapshot drift')
            else: shutil.copy2(file,dest)
    receipt['snapshot_files'] = tree(snapshot)
    existing = lineage/'environment.json'
    if existing.exists(): require(read_json(existing) == receipt, 'environment binding drift')
    else: write_json(existing,receipt)
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
    manifest = read_json(child/'manifest.json')
    if manifest['delivery']['model'] == 'sol':
        require(launch.get('build_kind') == 'vite_build_only'
                and launch.get('preview_provider') == 'python_http_server'
                and Path(launch['serve_root']).name == 'dist', 'not serving authored build')
        require(adapter['payload'].get('delivered_build_completed') is True
                and (r/'delivered_build.log').is_file(), 'authored build unproven')
    elif (manifest['delivery']['model'], manifest.get('game_id')) in AUTHORED_STATIC_IDENTITIES:
        source = child/'input/project'
        if not source.is_dir():
            source = child.parent/'source_archive'
        authored_static_launch(source, child/'runtime/project', launch)
    elif (manifest['delivery']['model'], manifest.get('game_id')) in CONFIGURED_VITE_IDENTITIES:
        source = child/'input/project'
        if not source.is_dir():
            source = child.parent/'source_archive'
        authored_configured_vite_launch(source, child/'runtime/project', launch)
    else:
        require(launch['mode'] == 'script' and launch['script'] == 'dev', 'not authored dev entry')
    readiness = read_json(r/'server_readiness.json')
    require(readiness['schema'] == 'three-server-readiness.v1' and readiness['state'] == 'ready'
            and readiness['transport'] == 'direct_loopback_http.v1'
            and readiness['url'] == launch['url'] and readiness['attempts']
            and readiness['server_pid'] > 0 and readiness['server_returncode'] is None,
            'direct server readiness unproven')
    last = readiness['attempts'][-1]
    require(last['ready'] is True and 200 <= last['status'] < 300
            and last['url'] == launch['url'] and last['transport'] == readiness['transport'],
            'no actual HTTP success')
    return {'take':take,'frames':progress['frames'],'wallclock_seconds':report['wallclock_seconds'],
            'actions':progress['channels_written']['actions'],'record_sha256':sha256(r/'record_result.json'),
            'readiness_sha256':sha256(r/'server_readiness.json'),
            'native':str(paths[0].parent.relative_to(child))}

def _verify_parent(out, prepared):
    require(retained(out) == prepared['binding']['parent_files'], 'parent diagnostics changed')
    archive = out/LINEAGE/'parent_archive'
    require(tree(archive) == prepared['binding']['parent_files'], 'parent archive changed')
    manifest = read_json(out/'manifest.json')
    require(prepare.tree_digest(prepare.tree_hashes(Path(manifest['project_source'])))
            == prepared['binding']['source_digest'], 'original source changed')


def production_boundary(lineage, label, initial):
    """Archive disk producer at each boundary without rewriting the initial binding.

    Python imports remain those loaded by this process. These receipts explicitly
    disclose concurrent on-disk drift; archived sources are never executed.
    """
    import time
    folder = lineage/'production_boundaries'/f'{label}_{time.time_ns()}'
    files = production()
    for name, expected in files.items():
        dest = folder/'sources'/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, dest)
        require(sha256(dest) == expected, 'producer changed while taking boundary snapshot')
    delta = {name: {'initial':initial.get(name), 'current':files.get(name)}
             for name in initial.keys() | files.keys() if initial.get(name) != files.get(name)}
    receipt = {'label': label, 'pid':os.getpid(), 'files':files, 'sha256':digest(files),
               'initial_sha256':digest(initial), 'disk_drift':delta,
               'python_imports':'process cached modules; no archived code executed'}
    write_json(folder/'receipt.json', receipt)
    return receipt


def lock_metadata_proof(before, after):
    """Exact npm repair observed on G026: materialize an already-declared Linux optional.

    No existing package/root metadata may change. The added platform binary is
    not usable on this native macOS run. Keep both original and installed locks.
    """
    import copy
    original, installed = read_json(before), read_json(after)
    package = 'node_modules/@rollup/rollup-linux-arm64-gnu'
    expected = {'version':'4.64.8',
        'resolved':'https://registry.npmjs.org/@rollup/rollup-linux-arm64-gnu/-/rollup-linux-arm64-gnu-4.64.8.tgz',
        'integrity':'sha512-KBNMmyw4lPdL+2KtvE5vqODZRJgv7Y0Qg/v8uBL+i2KYLtAnfrvW6ukxZPO2lt6mfCOmvKJ1IcKAp3Smi3JpBQ==',
        'cpu':['arm64'],'dev':True,'license':'MIT','optional':True,'os':['linux'],'libc':['glibc']}
    require(package not in original['packages'] and installed['packages'].get(package) == expected,
            'not exact nonhost optional lock metadata')
    require(original['packages']['node_modules/rollup']['optionalDependencies'].get('@rollup/rollup-linux-arm64-gnu') == '4.64.8',
            'optional package was not already authored')
    restored = copy.deepcopy(installed); del restored['packages'][package]
    require(restored == original, 'other authored lock entries changed')
    return {'path':'package-lock.json','original_sha256':sha256(before),'installed_sha256':sha256(after),
            'kind':'npm_materialized_already_declared_nonhost_optional', 'added_package':package,
            'all_existing_entries_unchanged':True,'original_dependency_declarations_unchanged':True}


def runtime_source_check(child, prepared, lineage):
    manifest = read_json(child/'manifest.json')
    changes = []
    for name, expected in prepared['child_source_files'].items():
        actual = child/'runtime/project'/name
        if sha256(actual) == expected:
            continue
        require(manifest['game_id'] == 'G026_signal_tower_td' and name == 'package-lock.json'
                and os.uname().sysname == 'Darwin', f'authored runtime source changed: {name}')
        proof = lock_metadata_proof(child/'input/project'/name, actual)
        require(not (child/'runtime/project'/proof['added_package']).exists(), 'nonhost optional unexpectedly installed')
        require(sha256(lineage/'environment_snapshot'/name) == proof['installed_sha256'], 'installed lock not archived')
        changes.append(proof)
    return changes


def playable_manifest(manifest):
    """Match formal run_playable's in-memory budget; keep saved manifest unchanged."""
    from ..stage1.pipeline import PLAYABLE_GAMEPLAY_MS
    require(PLAYABLE_GAMEPLAY_MS == 75000, 'formal playable duration changed')
    budget = dict(manifest['budget'])
    extra = PLAYABLE_GAMEPLAY_MS - budget['gameplay_ms']
    for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
        budget[key] += extra
    budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
    require(budget['gameplay_ms'] == budget['recording_ms'] == 75000,
            'inconsistent original gameplay/recording budget')
    return {**manifest, 'budget': budget}


def execute(out):
    from pipeline.eval.whitebox.core import pipeline, playable_rules, record
    out = Path(out).resolve(); lineage = out/LINEAGE
    with locked(out/'.web-readiness-recovery.lock'):
        if (lineage/'replacement.json').exists():
            score = qualified_replacement_score(out)
            require(score is not None, 'existing replacement failed verification')
            return score
        with locked(out/'takes/1/record/.postprocess.lock'):
            prepared = prepare_child(out)
        child = lineage/'child'
        pinned = prepared['binding']['production']
        production_boundary(lineage, 'execution_start', pinned)
        ensure_environment(child, lineage)
        saved_manifest = prepare.verify(child)
        manifest = playable_manifest(saved_manifest)
        write_json(child/'playable_budget.json', {'saved_budget':saved_manifest['budget'],
                   'runtime_budget':manifest['budget'], 'policy':'pipeline.run_playable',
                   'saved_manifest_unchanged':True})
        feedback = None
        recordings = []
        with environment(child/'runtime/project', shared=manifest['game_id']=='G057_rhythm_machine_hall'):
            for take in (1, 2):
                check_space(out)
                production_boundary(lineage, f'take_{take}_start', pinned)
                if take == 2:
                    require(feedback is not None, 'second take lacks unresolved operate feedback')
                executable = plan.make_plan(child, manifest, take, ['play.launch', 'play.operate'], feedback)
                require(executable['max_duration_ms'] <= 75000, 'accepted plan exceeds bounded duration')
                plan.validate(executable, manifest, child/'input/project')
                r = child/f'takes/{take}/record'
                if not (r/'record_result.json').exists():
                    claim = lineage/f'record_t{take}_claim.json'
                    with claim.open('x') as f:
                        json.dump({'take': take, 'plan_sha256': sha256(child/f'takes/{take}/plan.json'),
                                   'production_sha256': digest(pinned), 'gameplay_ms': 75000}, f)
                    try:
                        record.record(child, manifest, executable, take)
                    finally:
                        production_boundary(lineage, f'take_{take}_end', pinned)
                recordings.append(qualified_record(child, take))
                verdicts = playable_rules.evaluate(child, manifest, take)
                write_json(lineage/f'take_{take}_qualified.json', {'record': recordings[-1], 'verdicts': verdicts})
                if verdicts['play.operate']['status'] == 'PASS' or verdicts['play.launch']['status'] == 'FAIL':
                    break
                feedback = {'earlier_plans': [read_json(child/f'takes/{k}/plan.json')['summary']
                                               for k in range(1, take+1)],
                            'judge_reasons': {'play.operate': verdicts['play.operate']['reason']}}
        production_boundary(lineage, 'native_complete', pinned)
        env_receipt = read_json(lineage/'environment.json')
        require(tree(lineage/'environment_snapshot') == env_receipt['snapshot_files'], 'saved environment drift')
        for name, value in env_receipt['toolchain_sha256'].items():
            require(sha256(Path(name)) == value, 'toolchain changed during recording')
        _verify_parent(out, prepared)
        # Every take is now qualified and cached: the official entry only evaluates/scores.
        score = pipeline.run_playable(Path(manifest['delivery_dir']), child,
                                      models={'planner': PLANNER_MODEL, 'judge': 'none'}, takes=len(recordings))
        require(score['complete'] is True, 'official playable score incomplete')
        metadata_changes = runtime_source_check(child, prepared, lineage)
        source_receipt = {'source_digest': prepared['binding']['source_digest'],
                          'files': prepared['child_source_files'], 'original_unchanged': True,
                          'original_and_runtime_unchanged': not metadata_changes,
                          'runtime_metadata_changes': metadata_changes}
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
                 'environment_sha256': sha256(lineage/'environment.json'),
                 'production_boundaries': tree(lineage/'production_boundaries'),
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
        require(tree(lineage/'production_boundaries') == final['production_boundaries'], 'boundary producer changed')
        require(tree(child, skip=('runtime',)) == final['evidence_files'], 'child evidence changed')
        require(sha256(lineage/'environment.json') == final['environment_sha256'], 'environment receipt changed')
        require(tree(lineage/'environment_snapshot') == read_json(lineage/'environment.json')['snapshot_files'],
                'saved environment changed')
        require(sha256(lineage/'source_integrity.json') == final['source_receipt_sha256']
                and tree(lineage/'source_archive') == final['source_archive_files']
                == prepared['child_source_files'], 'saved author source changed')
        source_receipt = read_json(lineage/'source_integrity.json')
        if source_receipt.get('runtime_metadata_changes'):
            require(read_json(child/'manifest.json')['game_id'] == 'G026_signal_tower_td', 'metadata exception identity differs')
            proof = lock_metadata_proof(lineage/'source_archive/package-lock.json', lineage/'environment_snapshot/package-lock.json')
            require(source_receipt['runtime_metadata_changes'] == [proof], 'metadata proof changed')
        require(sha256(child/'playable_score.json') == replacement['child_score_sha256'] == final['score_sha256'],
                'score changed')
        score = read_json(child/'playable_score.json')
        require((read_json(out/'manifest.json')['delivery']['model'], score['game_id']) in IDENTITIES and score['engine'] == 'three_js' and score['complete'] is True
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
