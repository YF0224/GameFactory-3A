"""Exact Kimi G011 addon-alias recovery. One child, cached plan, one 75s take.

No retry/reset, model call, parent overwrite, or project deletion. Install before
execution; engineering copies are review/test material only.
"""

from ..model_config import PLANNER_MODEL
import argparse
import copy
from contextlib import contextmanager
import hashlib
import re
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import traceback

from ..stage1 import pipeline, plan, playable_rules, prepare
from ..stage1.llm import accepted_response
from ..stage1.paths import BENCH, read_json, sha256
from .web_readiness_recovery import pre_record_process_check, qualified_record

VERSION = 'stage1-kimi-g011-addon-recovery.v1'
FULL_SHA = 'd482ec268038a8a19bfa20f961fa2c7f83c38d9f7227431b21e8923047c2ab60'
REL = Path('recovery/three_addon_v1')
from pipeline.eval.stage1.paths import DATA_ROOT
ROOT = DATA_ROOT / 'outputs/eval/whitebox/stage1_playable_kimi_all_20261109__plan-gpt-6-astra'
OUT = ROOT / 'kimi_k3/G011_cloud_mail_runner/retest'
SELF = 'pipeline/eval/repair/three_g011_addon_recovery.py'
PLUGIN = BENCH / 'engine_adapters/three_js/plugin/A3GamePlayable'
MODELS = {'planner': PLANNER_MODEL, 'judge': 'none'}
IDENTITY = {'model': 'Kimi', 'case': 'G011', 'game_id': 'G011_cloud_mail_runner',
            'engine': 'three_js', 'entry': 'index.html', 'required_real_clients': 1}
LIMITS = {'parent_browser_launched': True, 'parent_recorded_seconds': 0, 'parent_frames': 0,
          'activation_native_takes': 1, 'recording_ms': 75000, 'new_model_calls': 0,
          'cache_policy': 'KEEP_PROJECTS'}
HOLD = {'version': VERSION, 'qualified': False, 'require': 'verified replacement.json; retain hold'}

ADAPTER = {'engine_adapters/three_js/plugin/A3GamePlayable/src/engine/runtime-host.js': {'before': '118c52d20e1f4ba99350e9c4df29b18338c55a6fadcd4e4e45089a14a050f55d', 'after': '8a83002d420ccdd235964aabd482ad7a51fc8a782ca785864b1e5074893f57fd', 'imports': 4}, 'engine_adapters/three_js/plugin/A3GamePlayable/src/engine/scene-loader.js': {'before': '20705c406595a3b54cca280dbf3ee7aff6aa0201bd9866cf9c7688c36c783bd3', 'after': '56eb48869121cc50c71e129058b90af76340a8d5f368f546951d0ae52eeef8ef', 'imports': 1}, 'engine_adapters/three_js/plugin/A3GamePlayable/src/engine/asset-library.js': {'before': '558d21dba8b8338e356f238bfadfa9166e9344760239d8252ab97de7ad68a4ad', 'after': '9648fef8870606fd2c7c7bf48ef32930a3309cb9e134994ba4eea676c3fb6a96', 'imports': 8}, 'engine_adapters/three_js/plugin/A3GamePlayable/src/engine/visual-kit.js': {'before': 'eb8ab04e04e027e9e951a21fb9049ad45913469eec1531526a05772849b0f00b', 'after': '1d55bddbcb756427c6b4b138050091c5cf8971deca46c530ba5f8f4ab54dc24e', 'imports': 3}}
PARENT = {'_kimi_batch/attempt.json': '6afcb3b7d2fce77379812de4a20c89e7eb285ffa3fe663c7d37e9aa28edb2d31', '_kimi_batch/failure.json': '27e0dcc1c50efdb42525d9e09a146269ba1fa0e97a23879680e76d5cece33554', '_kimi_batch/producer_end.json': '01221230680a58c3d7d41c2502e12c5ce851b234fc4724b7f1fbeafb024c1289', '_kimi_batch/producer_start.json': '1f8cc4d345f7591305b15cb081faf1f4ad879f0b969acd59cc19ac26e611e295', 'manifest.json': 'ef7d0df055a397c82ec36eb28b53ec69855430a87da6705085f32f67a0480af9', 'model_calls/plan_t1/accepted_response.json': '50b5d02202e1f6a5875b68506711f99a710013f0038ea9a863a1739abd0fce47', 'model_calls/plan_t1_002/response.json': '8fcd523c1771fc9112cc181eae4f8138e0d3daf9c779baddd818f3a74f09e844', 'runtime/project/package-lock.json': '953e11193f832ae9551c183bef0f6b014b07c3eecc8f444a55912266eabb7fc0', 'status.json': 'b5fcaa2473341e82adea0f16d243206ecb2e3747f164808c356dd9ec834e9d22', 'takes/1/plan.json': '9c105c3a4e06adce9ee1ab56ee95c619a164d6691162fb42722e51835a38011f', 'takes/1/plan_coverage.json': 'db70f315245f0ed6046b6abb04c68ebb07a02c0a9a6ae77e53b4ab6d99ff37e3', 'takes/1/record/.postprocess.lock': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'takes/1/record/action_schedule.json': '7a1c58c17d33626c2cd6b9d6c9cf3827f6b2c8bc3504087a2d884e9c594fc6ad', 'takes/1/record/adapter_result.json': 'a1ab354cb0547c55d5bd1bda08c22821e01f91bd10a68574e0148fe9cdda96cd', 'takes/1/record/capture_mode.json': 'fa2b4ab32443cd6d1d5ef079913bc2d6643072ad921807da037a57ba3c3b8210', 'takes/1/record/capture_schedule.json': '52fe1ab785385052c56d876f4e372ea0d984da8e6eda8d31c7b36da205d58034', 'takes/1/record/dependency_install_stderr.log': '94d1faeefd58d6155e839dad97cba60732fa7163b323822461d02d219c1224eb', 'takes/1/record/dependency_install_stdout.log': '95f6e6dea316ca05833964f1b295ccc8730ffc75f00369541ccfce4dfb17fc22', 'takes/1/record/dev_server.log': 'fed6cc7ba4338f78adf462138c515a346bba7189074e0dbc1694130675a92253', 'takes/1/record/launch_selection.json': '51603f8a5b4e4d022b042c2cf4a05ef33fd30710242408907788b78db3e4d1f5', 'takes/1/record/native/gameplay-2026-11-09T16-32-53-955Z-r4bzWP/audio_capture.json': '26b2f464fab3e15db131d45f90138586902d1c62c85bd62cb882779837a75dd1', 'takes/1/record/native/gameplay-2026-11-09T16-32-53-955Z-r4bzWP/browser_cleanup.json': '43dd7c9acd8dc3c1b5b217572ed874495fb0ea7bb542bbd0708336453e209009', 'takes/1/record/native/gameplay-2026-11-09T16-32-53-955Z-r4bzWP/host_process_cleanup.json': 'f0eda706f96d496daae214c0a3e052c120ea86eee3ec3398d57483210f80c335', 'takes/1/record/native/gameplay-2026-11-09T16-32-53-955Z-r4bzWP/manifest.json': '520b71b7429f616ca59b951567fb37ff418c3919c28b5d5c5920099161ea4d42', 'takes/1/record/native/gameplay-2026-11-09T16-32-53-955Z-r4bzWP/recording_progress.json': '1150e8967865db32ed4c1f2300eb20e394a833fb73404a3b5b237d09f7dfa6d5', 'takes/1/record/native/gameplay-2026-11-09T16-32-53-955Z-r4bzWP/report.json': '48b81f31da61af79478eef7931815b737fc5e388d70aed43c97e4e6d885126d8', 'takes/1/record/server_failure.json': '11f665a574915a47c35e765e02b0d6841d3e45e3cfe5f7b1d67fc004cc0153ba', 'takes/1/record/server_readiness.json': '4bdfc2c21648426863c9b7bcd0d4a381ce700dcf63a5cf8b1dcee7394bc9612e', 'takes/1/record/three_js_action_plan.json': '53bed8564f698e79cda1ee66603e51818bfdd2041d21ad11a7b4cb24ff4d2e56'}


ENV_RESUME = 'environment_resume_v1'
ENV_OLD_HELPER_SHA = '1d684d3417e9ab680bc0633a67ee779ead071d0be77a1402417f145631347cca'
ENV_FAILURE_SHA = '812b8eedf827ab111707c7b1a73f79521f2f1e29aee2433f0e89b71c684ac086'
ENV_FAILED_TREE_SHA = 'b98f698beec2de0eb9c14dcf6a4d6f32c805578898fe900535c278a6cfaff1df'
ENV_FIX_SOURCE_SHA = 'd8dd5096a11154de4c1c6d1d6d268f064801e3261b12b7c17b3d44e0c0281b56'
ENV_POLICY = {'A3GAME_WEB_ENV': 'unset_during_pipeline_restore_after',
              'dependency_provisioning': 'normal_formal_pipeline_own_project',
              'same_child': True, 'same_native_claim': True, 'takes': 1, 'new_model_calls': 0}


def map_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def fix_source_digest(data):
    # Self-normalized pin: stable historical verification of the reviewed new
    # helper archive, without comparing any future live producer bytes.
    normalized = re.sub(rb"^ENV_FIX_SOURCE_SHA = '[^']*'$", b"ENV_FIX_SOURCE_SHA = '<SELF>'", data, flags=re.M)
    return hashlib.sha256(normalized).hexdigest()


@contextmanager
def environment(project):
    """G011 uses local declared dependencies; normal recording installs them."""
    configs = list(Path(project).glob('vite.config.*'))
    require(configs and all('A3GAME_WEB_ENV' not in p.read_text() for p in configs),
            'authored Vite config requires a different environment contract')
    previous = os.environ.pop('A3GAME_WEB_ENV', None)
    try:
        from engine_adapters.three_js.playtest.launch import build_environment
        require(build_environment(project) == {}, 'unexpected shared environment')
        yield
    finally:
        if previous is None:
            os.environ.pop('A3GAME_WEB_ENV', None)
        else:
            os.environ['A3GAME_WEB_ENV'] = previous


def verify_environment_fix(old, new):
    old_relevant, new_relevant = relevant(old), relevant(new)
    require(old_relevant.get(SELF) == ENV_OLD_HELPER_SHA, 'not the reviewed failed helper')
    require({k: v for k, v in old_relevant.items() if k != SELF} ==
            {k: v for k, v in new_relevant.items() if k != SELF}, 'unreviewed relevant producer change')
    producer_archive(new)
    new_sha = new_relevant.get(SELF)
    require(new_sha and new_sha != ENV_OLD_HELPER_SHA, 'environment fix not installed')
    require(fix_source_digest((ROOT / '_kimi_batch/producer_blobs' / new_sha).read_bytes()) ==
            ENV_FIX_SOURCE_SHA, 'not the exact reviewed environment fix')
    return {'path': SELF, 'before': ENV_OLD_HELPER_SHA, 'after': new_sha,
            'normalized_after_sha256': ENV_FIX_SOURCE_SHA}


def review_environment_failure(out):
    """Read-only exact failed activation admission; no installed-code requirement."""
    out = plain(out)
    require(out == OUT, 'foreign recovery')
    proof, start = verify_activation(out)
    folder, child = out / REL, out / REL / 'child'
    require(sha256(plain(folder / 'failure.json')) == ENV_FAILURE_SHA, 'not exact environment failure')
    failure = read_json(folder / 'failure.json')
    require(failure['type'] == 'ValueError' and failure['error'] ==
            'A3GAME_WEB_ENV lacks a complete Vite/Three build environment', 'wrong preparation failure')
    require(read_json(folder / 'producer_end.json')['files'] == start, 'failed producer changed')
    prior = tree(folder)
    require(map_digest(prior) == ENV_FAILED_TREE_SHA, 'failed activation tree changed or already resumed')
    require(not (child / 'takes/1/record').exists() and not (child / 'status.json').exists()
            and not (child / 'playable_score.json').exists(), 'child already reached pipeline/native')
    require(not (child / 'runtime/project/node_modules').exists(), 'unexpected prior dependency installation')
    before = read_json(folder / 'before_install.json')
    require(project_files(child / 'runtime/project') == before == read_json(folder / 'failed_source.json')
            and tree(folder / 'failed_source') == before, 'failed source changed before continuation')
    require(tree(child / 'model_calls') == tree(out / 'model_calls')
            and sha256(child / 'takes/1/plan.json') == PARENT['takes/1/plan.json'], 'cached plan/calls changed')
    configs = list((child / 'runtime/project').glob('vite.config.*'))
    require(configs and all('A3GAME_WEB_ENV' not in p.read_text() for p in configs), 'shared config not eligible')
    return {'version': VERSION, 'failed_files': prior, 'failure_sha256': ENV_FAILURE_SHA,
            'failed_tree_sha256': ENV_FAILED_TREE_SHA, 'policy': ENV_POLICY}


def verify_environment_continuation(out, old):
    folder = out / REL
    continuation = folder / ENV_RESUME
    require(not (continuation / 'failure.json').exists(), 'environment continuation failed; no retry')
    receipt = read_json(continuation / 'receipt.json')
    prior = tree(continuation / 'prior_archive')
    require(map_digest(prior) == ENV_FAILED_TREE_SHA, 'prior failed activation archive changed')
    for name, expected in prior.items():
        # Runtime npm lock relocation is checked by the existing source verifier.
        if not name.startswith('child/runtime/project/'):
            require(sha256(plain(folder / name)) == expected, 'retained preparation evidence changed: ' + name)
    require(sha256(folder / 'failure.json') == ENV_FAILURE_SHA, 'retained environment failure changed')
    start = read_json(continuation / 'producer_start.json')['files']
    migration = verify_environment_fix(old, start)
    require(receipt == {'version': VERSION, 'failed_files': prior, 'failure_sha256': ENV_FAILURE_SHA,
            'failed_tree_sha256': ENV_FAILED_TREE_SHA, 'policy': ENV_POLICY,
            'migration': migration, 'producer_start_sha256': sha256(continuation / 'producer_start.json')},
            'environment continuation receipt changed')
    require(read_json(continuation / 'dispatch.json') == {'receipt_sha256': sha256(continuation / 'receipt.json'),
            'native_claim_sha256': sha256(folder / 'native_dispatch.claim.json'), 'policy': ENV_POLICY},
            'environment dispatch binding changed')
    return start, {'environment_continuation_sha256': sha256(continuation / 'receipt.json'),
                   'environment_dispatch_sha256': sha256(continuation / 'dispatch.json')}


def completion_context(out, old):
    folder = out / REL
    if (folder / 'failure.json').exists():
        start, binding = verify_environment_continuation(out, old)
        return start, folder / ENV_RESUME / 'producer_end.json', binding
    require(not (folder / ENV_RESUME).exists(), 'continuation without original failure')
    return old, folder / 'producer_end.json', {}


def check_unstarted_child_processes(child):
    # No launch_selection exists for this exact pre-pipeline failure. Inspect
    # command lines instead; never create a native client or signal a process.
    result = subprocess.run(['ps', '-axo', 'pid,ppid,command'], capture_output=True,
                            text=True, check=True)
    require(not result.stderr.strip(), 'cannot inspect child process ownership')
    runtime = str((child / 'runtime/project').resolve())
    require(not any(runtime in line for line in result.stdout.splitlines()), 'child runtime still has a process')


def resume_environment(out):
    installed()
    out = plain(out)
    require(out == OUT, 'foreign recovery')
    r = runner()
    with r.locked(ROOT / '_kimi_batch/locks/G011.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        reviewed = review_environment_failure(out)
        proof, old = verify_activation(out)
        folder, child = out / REL, out / REL / 'child'
        pre_record_process_check(out)
        check_unstarted_child_processes(child)
        r.check_disk(ROOT, proof['target'], proof['source'])
        start = r.production()
        # Archive only, never execute old production bytes.
        r.archive_producer(ROOT, start)
        migration = verify_environment_fix(old, start)
        require(start.get(SELF) == sha256(Path(__file__)), 'installed helper differs from dispatch producer')
        continuation = folder / ENV_RESUME
        continuation.mkdir(exist_ok=False)
        try:
            archive_files(folder, reviewed['failed_files'], continuation / 'prior_archive')
            exclusive(continuation / 'producer_start.json', {'files': start})
            exclusive(continuation / 'receipt.json', {**reviewed, 'migration': migration,
                      'producer_start_sha256': sha256(continuation / 'producer_start.json')})
            with environment(child / 'runtime/project'):
                require(relevant(start) == relevant(r.production()), 'producer changed before resumed pipeline')
                exclusive(continuation / 'dispatch.json', {'receipt_sha256': sha256(continuation / 'receipt.json'),
                          'native_claim_sha256': sha256(folder / 'native_dispatch.claim.json'), 'policy': ENV_POLICY})
                parent = read_json(out / 'manifest.json')
                pipeline.run_playable(Path(parent['delivery_dir']), child, models=MODELS, takes=1)
            return finalize(out)
        except BaseException as exc:
            if not (continuation / 'producer_end.json').exists():
                end = r.production()
                r.archive_producer(ROOT, end)
                exclusive(continuation / 'producer_end.json', {'files': end})
            exclusive(continuation / 'failure.json', {'type': type(exc).__name__, 'error': str(exc),
                                                    'traceback': traceback.format_exc()})
            raise


def require(value, message):
    if not value:
        raise ValueError(message)


def runner():
    scripts = str(BENCH / 'scripts/eval')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from pipeline.eval.stage1 import recovery_support as kimi_playable_retest
    return kimi_playable_retest


def installed():
    require(Path(__file__).resolve() == BENCH / SELF, 'install reviewed formal module before execution')


def plain(path):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'linked path: ' + str(path))
    return path


def exclusive(path, value):
    plain(path).parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def tree(root, *, skip=()):
    """Include lock bytes; exclude only explicit regenerable dependency caches."""
    root = plain(root)
    require(root.is_dir(), 'missing tree: ' + str(root))
    result = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            p = Path(directory) / name
            if p.relative_to(root).as_posix() in skip or name == '__pycache__':
                dirs.remove(name)
            else:
                plain(p)
        for name in names:
            p = Path(directory) / name
            rel = p.relative_to(root).as_posix()
            if rel not in skip and not name.endswith('.pyc'):
                result[rel] = sha256(plain(p))
    return dict(sorted(result.items()))


def parent_tree(out):
    return tree(out, skip=(str(REL), 'runtime/project/node_modules', 'input/project/node_modules'))


def project_files(root):
    # Original snapshot copies use these same formal prepare exclusions.
    result = {}
    for directory, dirs, names in os.walk(plain(root)):
        ignored = prepare.IGNORE(directory, dirs + names)
        dirs[:] = [d for d in dirs if d not in ignored]
        for name in names:
            if name not in ignored:
                p = plain(Path(directory) / name)
                result[p.relative_to(root).as_posix()] = sha256(p)
    return dict(sorted(result.items()))


def archive_files(root, values, destination):
    for rel, value in values.items():
        require(not Path(rel).is_absolute() and '..' not in Path(rel).parts, 'escaping archive path')
        src, dest = plain(root / rel), plain(destination / rel)
        require(sha256(src) == value, 'archive source drift: ' + rel)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as f:
            f.write(src.read_bytes())
        require(sha256(dest) == value, 'archive copy differs')


def producer_archive(values):
    for value in set(values.values()):
        require(len(value) == 64 and all(c in '0123456789abcdef' for c in value), 'bad producer SHA')
        require(sha256(plain(ROOT / '_kimi_batch/producer_blobs' / value)) == value, 'producer archive differs')


def relevant(values):
    # Full maps are retained. Only this route's dependency set gates live dispatch.
    core = {'__init__', 'pipeline', 'plan', 'planner', 'prepare', 'paths', 'budgets', 'suites',
            'delivery', 'criteria', 'playable_rules', 'record', 'capture', 'llm', 'asset_views',
            'evidence', 'judge', 'standards', 'source', 'source_bundle',
            'web_readiness_recovery', 'vite_build_only_recovery', 'three_g011_addon_recovery'}
    prefixes = ('engine_adapters/three_js/', 'engine_adapters/common/',
                'pipeline/common/',
                'pipeline/game_eval/whitebox_eval/sparse_evidence',
                'pipeline/game_eval/whitebox_eval/sparse_capture')
    stage = 'pipeline/eval/repair/'
    return {k: v for k, v in values.items() if k.startswith(prefixes)
            or (k.startswith(stage) and Path(k).stem in core)
            or Path(k).parent == Path('engine_adapters')
            or k in {'pipeline/eval/stage1/recovery_support.py', 'scripts/eval/_common.py'}}


def adapter_pin(values):
    require(all(values.get(k) == v['after'] for k, v in ADAPTER.items()), 'reviewed addon imports not installed')


def relocated_lock(before, after, after_project):
    """Allow only npm's local linked-plugin key/resolved relocation; all else equal."""
    a, b = copy.deepcopy(before), copy.deepcopy(after)
    link = 'node_modules/@a3game/playable'
    for value in (a, b):
        require(value.get('lockfileVersion') == 3, 'unexpected npm lock version')
        packages = value['packages']
        entry = packages[link]
        require(set(entry) == {'resolved', 'link'} and entry['link'] is True, 'plugin is not exact file link')
        key = entry['resolved']
        require(isinstance(key, str) and key in packages and not Path(key).is_absolute(), 'invalid linked key')
        payload = packages.pop(key)
        require(payload.get('name') == '@a3game/playable', 'foreign linked plugin')
        entry['resolved'] = '<FORMAL_PLUGIN>'
        require('<FORMAL_PLUGIN>' not in packages, 'duplicate normalized link')
        packages['<FORMAL_PLUGIN>'] = payload
    require(a == b, 'npm lock changed beyond linked-plugin relocation')
    key = after['packages'][link]['resolved']
    require((after_project / key).resolve() == PLUGIN.resolve(), 'linked plugin resolves outside formal root')
    return {'policy': 'formal_plugin_relative_path_only.v1', 'resolved': key, 'plugin': str(PLUGIN)}


def runtime_source(out):
    before, after = project_files(out / 'input/project'), project_files(out / 'runtime/project')
    require(set(before) == set(after), 'runtime authored file set differs')
    require(all(after[k] == v for k, v in before.items() if k != 'package-lock.json'), 'runtime authored bytes changed')
    relocation = relocated_lock(read_json(out / 'input/project/package-lock.json'),
                               read_json(out / 'runtime/project/package-lock.json'), out / 'runtime/project')
    return {'input_files': before, 'runtime_files': after, 'lock_relocation': relocation}


def parent_zero_capture(record):
    paths = list((record / 'native').glob('*/recording_progress.json'))
    require(len(paths) == 1, 'ambiguous parent browser attempt')
    native = paths[0].parent
    progress, report = read_json(paths[0]), read_json(native / 'report.json')
    require(progress['status'] == report['status'] == 'failed'
            and progress['frames'] == report['frames'] == 0
            and progress['recorded_seconds'] == report['recorded_seconds'] == 0
            and all(v == 0 for v in progress['channels_written'].values())
            and report['executed_actions'] == [] and 'ERR_CONNECTION_REFUSED' in report['crash'],
            'parent is not the reviewed zero-capture browser failure')
    browser, host = read_json(native / 'browser_cleanup.json'), read_json(native / 'host_process_cleanup.json')
    require(browser['browser_cleanup'] is True and browser['view_cleanup'] is True
            and host['process_cleanup'] is True and host['server_group_alive'] is False
            and host['recorder']['process_cleanup'] is True and host['recorder']['group_alive'] is False,
            'parent browser/server cleanup unproven')
    # Retain input_cleanup=false honestly: navigation failed before any input.
    return {'native': str(native.relative_to(record)), 'browser_launched': True,
            'frames': 0, 'recorded_seconds': 0, 'input_cleanup': browser['input_cleanup']}


def review_parent(out):
    out = plain(out)
    require(out == OUT, 'only exact canonical Kimi G011 may recover')
    for rel, value in PARENT.items():
        require(sha256(plain(out / rel)) == value, 'frozen parent changed: ' + rel)
    r = runner()
    claim = read_json(out / '_kimi_batch/attempt.json')
    t = claim['target']
    require(all(t.get(k) == v for k, v in IDENTITY.items()), 'foreign identity')
    require(claim['models'] == MODELS and claim['max_takes'] == 2, 'parent model/budget differs')
    scope = ROOT / '_kimi_batch/scopes' / (claim['scope_sha256'] + '.json')
    require(claim['scope_sha256'] == FULL_SHA
            and sha256(plain(scope)) == claim['scope_sha256'] and t in read_json(scope)['targets'], 'scope differs')
    require(sha256(plain(ROOT / '_kimi_batch/authorization.json')) == claim['authorization_sha256'], 'authorization differs')
    require(r.source_binding(t, r.selection(t)) == claim['source'], 'original source/provenance differs')
    manifest = prepare.verify(out)
    require(manifest['engine'] == 'three_js' and manifest['project_source'] == t['project']
            and manifest['models'] == MODELS, 'manifest identity differs')
    require(project_files(Path(t['project'])) == project_files(out / 'input/project'), 'original snapshot differs')
    delivery = plain(Path(manifest['delivery_dir']) / 'delivery.json')
    require(read_json(delivery) == manifest['delivery'], 'delivery shim differs')
    start = read_json(out / '_kimi_batch/producer_start.json')['files']
    require(start == read_json(out / '_kimi_batch/producer_end.json')['files'], 'historical producer drift')
    producer_archive(start)
    require(all(start.get(k) == v['before'] for k, v in ADAPTER.items()), 'unexpected original adapter')
    status = read_json(out / 'status.json')
    require(status['state'] == 'HARNESS_ERROR' and status['step'] == 'record_t1', 'not terminal record failure')
    failure = read_json(out / 'takes/1/record/server_failure.json')
    require(failure['stage'] == 'project_server_exited' and failure['exit_code'] == 1
            and 'node_modules/three/addons/' in json.dumps(failure), 'not reviewed addon failure')
    require({p.name for p in (out / 'takes').iterdir()} == {'1'} and not (out / 'playable_score.json').exists(),
            'parent progressed beyond failed take')
    require({p.name for p in (out / 'model_calls').iterdir()} == {'plan_t1', 'plan_t1_002'}, 'extra model call')
    executable = accepted_response(out / 'model_calls', 'plan_t1')
    require(executable is not None and executable == read_json(out / 'takes/1/plan.json'), 'accepted plan differs')
    require(manifest['budget']['recording_ms'] == manifest['budget']['gameplay_ms'] == 75000, 'non75s budget')
    plan.validate(executable, manifest, out / 'input/project')
    return {'target': t, 'source': claim['source'], 'parent_files': parent_tree(out),
            'delivery_sha256': sha256(delivery), 'runtime_source': runtime_source(out),
            'zero_capture': parent_zero_capture(out / 'takes/1/record'), 'limits': LIMITS}


def evidence(child):
    return tree(child, skip=('runtime/project', 'input/project'))


def verify_child(child, proof):
    manifest = prepare.verify(child)
    parent = read_json(OUT / 'manifest.json')
    require(all(manifest[k] == parent[k] for k in ('delivery', 'project_source', 'snapshot_digest',
            'input_hashes', 'criteria_sha256', 'budget', 'models')), 'child input identity differs')
    require(tree(child / 'model_calls') == tree(OUT / 'model_calls'), 'model calls changed or added')
    require(sha256(child / 'takes/1/plan.json') == PARENT['takes/1/plan.json'], 'cached plan changed')
    require(accepted_response(child / 'model_calls', 'plan_t1') == read_json(child / 'takes/1/plan.json'), 'accepted cache differs')
    require({p.name for p in (child / 'takes').iterdir()} == {'1'}, 'more than one child take')
    source = runtime_source(child)
    status, score = read_json(child / 'status.json'), read_json(child / 'playable_score.json')
    require(status['state'] == 'done' and status['step'] == 'playable' and status['complete'] is True, 'child incomplete')
    require(score['complete'] is True and score['game_id'] == IDENTITY['game_id']
            and score['engine'] == 'three_js' and score['planner'] == MODELS['planner']
            and score['version'] == playable_rules.VERSION, 'not official complete score')
    with tempfile.TemporaryDirectory(prefix='g011-rules-') as temp:
        verdicts = playable_rules.evaluate(child, manifest, 1, report_dir=Path(temp))
    checks = {i: verdicts.get(i, {}).get('status', 'HARNESS_ERROR') for i in playable_rules.IDS}
    require('HARNESS_ERROR' not in checks.values() and score['checks'] == checks
            and score['takes'] == [{'take': 1, 'checks': checks}]
            and score['playable'] == round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2), 'official rules/score differ')
    native = qualified_record(child, 1)
    record = child / 'takes/1/record'
    result = read_json(record / 'record_result.json')
    require(result['plan_sha256'] == PARENT['takes/1/plan.json'] and result['engine'] == 'three_js'
            and result['take'] == 1, 'record identity differs')
    require(Path(read_json(record / 'launch_selection.json')['cwd']) == child / 'runtime/project', 'wrong working copy launched')
    return score, {'native': native, 'sources': source}


def verify_activation(out):
    proof = review_parent(out)
    folder = out / REL
    require(read_json(folder / 'qualification_hold.json') == HOLD, 'hold changed')
    require(read_json(folder / 'native_dispatch.claim.json') == LIMITS, 'native budget claim changed')
    require(read_json(folder / 'activation.json') == {'version': VERSION, 'proof': proof, 'limits': LIMITS,
            'producer_start_sha256': sha256(folder / 'producer_start.json')}, 'activation binding differs')
    require(tree(folder / 'parent_archive') == proof['parent_files'], 'parent archive differs')
    before = read_json(folder / 'before_install.json')
    require(before == project_files(folder / 'child/input/project')
            and tree(folder / 'before_install_source') == before, 'before-install source archive differs')
    start = read_json(folder / 'producer_start.json')['files']
    producer_archive(start)
    adapter_pin(start)
    return proof, start


def source_receipt(child):
    folder = child.parent / 'source_receipts'
    values = {}
    for label, path in {'original': Path(read_json(child / 'manifest.json')['project_source']),
                        'child_input': child / 'input/project', 'child_runtime': child / 'runtime/project',
                        'parent_runtime': OUT / 'runtime/project'}.items():
        lock = path / 'package-lock.json'
        dest = folder / (label + '_package-lock.json')
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('xb') as f:
                f.write(lock.read_bytes())
        require(sha256(dest) == sha256(lock), 'npm lock archive differs')
        values[label] = {'files': project_files(path), 'lock_sha256': sha256(dest)}
    return values


def verify_completion(out):
    out = plain(out)
    proof, start = verify_activation(out)
    folder, child = out / REL, out / REL / 'child'
    start, end_path, continuation_binding = completion_context(out, start)
    end = read_json(end_path)['files']
    require(relevant(start) == relevant(end), 'relevant producer drift during recording')
    producer_archive(end)
    score, native = verify_child(child, proof)
    # Historical qualification never compares producer receipts with current code.
    receipt = read_json(folder / 'completion.json')
    require(receipt == {'version': VERSION, 'qualified': True, 'score': score, 'proof': native,
            'evidence': evidence(child), 'source_receipts': read_json(folder / 'sources.json'),
            'cache_policy': 'KEEP_PROJECTS', 'freed_bytes': 0,
            'producer_end_sha256': sha256(end_path), **continuation_binding}, 'completion evidence differs')
    for label, value in receipt['source_receipts'].items():
        lock = folder / 'source_receipts' / (label + '_package-lock.json')
        require(sha256(plain(lock)) == value['lock_sha256'] == value['files']['package-lock.json'], 'source lock archive changed')
    require(receipt['source_receipts']['child_input']['files'] == native['sources']['input_files']
            and receipt['source_receipts']['child_runtime']['files'] == native['sources']['runtime_files']
            and receipt['source_receipts']['original']['files'] == native['sources']['input_files']
            and receipt['source_receipts']['parent_runtime']['files'] == proof['runtime_source']['runtime_files'],
            'source receipt mismatch')
    require(read_json(folder / 'replacement.json') == {'version': VERSION, 'child': 'child',
            'activation_sha256': sha256(folder / 'activation.json'), 'completion_sha256': sha256(folder / 'completion.json'),
            'score_sha256': sha256(child / 'playable_score.json')}, 'replacement differs')
    return score


def qualified_replacement_score(out):
    try:
        return verify_completion(Path(out))
    except Exception:
        return None


def finalize(out):
    installed()
    proof, start = verify_activation(out)
    folder, child = out / REL, out / REL / 'child'
    start, end_path, continuation_binding = completion_context(out, start)
    if (folder / 'replacement.json').exists():
        return verify_completion(out)
    end = runner().production()
    require(relevant(start) == relevant(end), 'relevant producer drift before finalization')
    score, native = verify_child(child, proof)
    sources = source_receipt(child)
    runner().archive_producer(ROOT, end)
    exclusive(end_path, {'files': end})
    exclusive(folder / 'sources.json', sources)
    exclusive(folder / 'completion.json', {'version': VERSION, 'qualified': True, 'score': score, 'proof': native,
        'evidence': evidence(child), 'source_receipts': sources, 'cache_policy': 'KEEP_PROJECTS', 'freed_bytes': 0,
        'producer_end_sha256': sha256(end_path), **continuation_binding})
    exclusive(folder / 'replacement.json', {'version': VERSION, 'child': 'child',
        'activation_sha256': sha256(folder / 'activation.json'), 'completion_sha256': sha256(folder / 'completion.json'),
        'score_sha256': sha256(child / 'playable_score.json')})
    return verify_completion(out)


def execute(out):
    installed()
    out = plain(out)
    require(out == OUT, 'foreign recovery')
    r = runner()
    with r.locked(ROOT / '_kimi_batch/locks/G011.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        proof = review_parent(out)
        pre_record_process_check(out)
        r.check_disk(ROOT, proof['target'], proof['source'])
        folder, child = out / REL, out / REL / 'child'
        require(not folder.exists(), 'one-shot activation already exists; preserve failed child')
        start = r.production()
        adapter_pin(start)
        r.archive_producer(ROOT, start)
        folder.mkdir(parents=True, exist_ok=False)
        exclusive(folder / 'qualification_hold.json', HOLD)
        exclusive(folder / 'producer_start.json', {'files': start})
        exclusive(folder / 'activation.json', {'version': VERSION, 'proof': proof, 'limits': LIMITS,
            'producer_start_sha256': sha256(folder / 'producer_start.json')})
        try:
            archive_files(out, proof['parent_files'], folder / 'parent_archive')
            parent = read_json(out / 'manifest.json')
            manifest = prepare.prepare(Path(parent['delivery_dir']), child, models=MODELS, suite='stage1', playable_only=True)
            require(all(manifest[k] == parent[k] for k in ('delivery', 'project_source', 'snapshot_digest',
                    'input_hashes', 'criteria_sha256')), 'new child snapshot differs')
            # Freeze the exact already-75s parent manifest; no authored bytes changed.
            (child / 'manifest.json').write_bytes((out / 'manifest.json').read_bytes())
            shutil.copytree(out / 'model_calls', child / 'model_calls')
            (child / 'takes/1').mkdir(parents=True)
            for name in ('plan.json', 'plan_coverage.json'):
                shutil.copyfile(out / 'takes/1' / name, child / 'takes/1' / name)
            before = project_files(child / 'runtime/project')
            require(before == project_files(child / 'input/project'), 'child source differs before install')
            archive_files(child / 'runtime/project', before, folder / 'before_install_source')
            exclusive(folder / 'before_install.json', before)
            require(review_parent(out) == proof, 'parent changed during child preparation')
            require(relevant(start) == relevant(r.production()), 'producer changed before native dispatch')
            exclusive(folder / 'native_dispatch.claim.json', LIMITS)
            with environment(child / 'runtime/project'):
                pipeline.run_playable(Path(parent['delivery_dir']), child, models=MODELS, takes=1)
            return finalize(out)
        except BaseException as exc:
            # No retry, overwrite, claim release or parent runtime recreation.
            if (child / 'runtime/project').exists():
                failed_source = project_files(child / 'runtime/project')
                archive_files(child / 'runtime/project', failed_source, folder / 'failed_source')
                exclusive(folder / 'failed_source.json', failed_source)
            if not (folder / 'producer_end.json').exists():
                end = r.production()
                r.archive_producer(ROOT, end)
                exclusive(folder / 'producer_end.json', {'files': end})
            exclusive(folder / 'failure.json', {'type': type(exc).__name__, 'error': str(exc), 'traceback': traceback.format_exc()})
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('inspect', 'execute', 'finalize', 'verify', 'inspect-environment', 'resume-environment'):
        group.add_argument('--' + name, action='store_true')
    args = parser.parse_args(argv)
    installed()
    if args.inspect_environment:
        result = review_environment_failure(args.out)
    elif args.resume_environment:
        result = resume_environment(args.out)
    elif args.inspect:
        result = review_parent(args.out)
    elif args.execute:
        result = execute(args.out)
    elif args.finalize:
        with runner().locked(ROOT / '_kimi_batch/locks/G011.lock'):
            result = finalize(args.out)
    else:
        result = verify_completion(args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
