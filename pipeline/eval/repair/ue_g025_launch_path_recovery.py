"""Exact G025 rejected-plan lexical continuation; no planner and one global take2.

Install this NEW module only. Historical artifacts are data, never executed.
--inspect is read-only. --execute is one shot; a failed/partial child cannot replay.
--verify / qualified_replacement_score provide independent reporter qualification.
"""
import argparse
import copy
import shutil
from pathlib import Path
import traceback

from . import ue_g025_take2_recovery as old
from ..stage1.llm import parse_strict, validate_schema

VERSION = 'stage1-kimi-g025-launch-prefix-recovery.v1'
SELF = 'pipeline/eval/repair/ue_g025_launch_path_recovery.py'
REL = old.REL / 'launch_path_recovery_v1'
FAILED_DIGEST = 'cce5aa6b8989e433b8f55fe694cd731c1887657edb64a26e9289718343d10a68'
RAW_SHA = 'a64b92bbebe81b2cd4732b98f36e735199680bbc8712781f518d060070704439'
FAILURE_SHA = '735b4e826a640fe3d332107744d084b38130df91d7969db1f83577cb48b4876b'
OLD_HELPER_SHA = '74ba5167aa0f676365946b519ac5d3a187d8e96717c9f05ddf4806c2999c8745'
ENTRY_SHA = 'cda7b2b9ca543dce17f6c3e9f15448e4e84ca7f281d528d036ed3f34956d7084'
OLD_SOURCE = 'project/BrokenContinentRTS.uproject'
NEW_SOURCE = 'BrokenContinentRTS.uproject'
ERROR = 'launch_source ' + OLD_SOURCE + ' does not exist in the project'
LIMITS = {**old.LIMITS, 'new_planner_calls': 0, 'max_attempts': 0,
          'reused_rejected_planner_calls': 1, 'normalization_fields': ['launch_source']}
HOLD = {'version': VERSION, 'qualified': False, 'require': 'verified replacement.json'}
SOURCE_KEYS = ('delivery', 'delivery_dir', 'project_source', 'project_digest', 'snapshot_digest',
               'input_hashes', 'criteria_sha256', 'models', 'suite', 'engine', 'entry', 'game_id', 'budget')
# Only read/execute current formal imports. Their historical SHA must still match;
# unrelated newly installed modules do not invalidate a sealed completion.
VERIFY_PREFIXES = ('pipeline/eval/repair/', 'engine_adapters/ue5/',
                   'pipeline/game_eval/whitebox_eval/', 'pipeline/game_eval/refine/')
require, read_json, sha256 = old.require, old.read_json, old.sha256


def installed():
    require(Path(__file__).resolve() == old.BENCH / SELF, 'install formal module before dispatch')


def compatible_helper():
    require(Path(old.__file__).resolve() == old.BENCH / old.SELF
            and sha256(old.BENCH / old.SELF) == OLD_HELPER_SHA, 'old helper pin changed')


def normalize(raw, project, original, schema, manifest):
    """One exact prefix removal, with full schema/plan validation and source binding."""
    require(isinstance(raw, dict) and raw.get('launch_source') == OLD_SOURCE, 'not exact reviewed prefix')
    project, original = old.plain(project), old.plain(original)
    require(not (project / OLD_SOURCE).exists() and not (original / OLD_SOURCE).exists(),
            'prefixed source exists; normalization could select another authored entry')
    require(sha256(old.plain(project / NEW_SOURCE)) == ENTRY_SHA
            == sha256(old.plain(original / NEW_SOURCE)), 'uproject source binding changed')
    validate_schema(raw, schema)
    try:
        old.plan.validate(raw, old.short_manifest(manifest), project)
    except ValueError as exc:
        require(str(exc) == ERROR, 'raw plan has a different validation error')
    else:
        raise ValueError('raw plan no longer has the reviewed failure')
    normalized = copy.deepcopy(raw)
    normalized['launch_source'] = NEW_SOURCE
    validate_schema(normalized, schema)
    old.plan.validate(normalized, old.short_manifest(manifest), project)
    old.require_key_plan(normalized)
    require(normalized['max_duration_ms'] == 75000, 'plan budget changed')
    raw_actions = old.plan.native_actions(raw, 'ue5')
    actions = old.plan.native_actions(normalized, 'ue5')
    require(raw_actions == actions, 'normalization changed actions')
    from engine_adapters.ue5.playtest import native_client, native_record
    schedule, end = native_client.plan_actions(actions, {})
    events = native_record.expand(schedule)
    require(end <= 75000 and events, 'plan lacks bounded native input')
    proof = {'policy': 'exact_project_prefix_removal.v1', 'changes': [
        {'field': 'launch_source', 'before': OLD_SOURCE, 'after': NEW_SOURCE}],
        'entry_sha256': ENTRY_SHA, 'raw_json_digest': old.digest(raw),
        'normalized_json_digest': old.digest(normalized), 'native_actions_digest': old.digest(actions),
        'action_end_ms': end, 'input_events': len(events), 'max_duration_ms': 75000,
        'planner_accepted': False, 'derived_executable': True}
    return normalized, proof


def failed_files(out):
    # New continuation lives inside the original recovery exclusion; canonical
    # take1 parent digest and every old failed artifact remain unchanged.
    return old.tree(out / old.REL, skip=('launch_path_recovery_v1',))


def inspect(out):
    compatible_helper()
    out = old.plain(out)
    require(out == old.OUT, 'only exact canonical Kimi G025 is authorized')
    files = failed_files(out)
    require(old.digest(files) == FAILED_DIGEST, 'failed attempt changed or extra native/call exists')
    folder, child = out / old.REL, out / old.REL / 'child'
    require(sha256(folder / 'failure.json') == FAILURE_SHA, 'different parent failure')
    require(ERROR in read_json(folder / 'failure.json')['traceback'], 'failure lineage differs')
    require(not (folder / 'native_dispatch.claim.json').exists() and not (child / 'takes').exists()
            and not (child / 'runtime/ue_admission').exists(), 'failed attempt already reached native/build')
    require(read_json(folder / 'planner.claim.json') == {'take': 2, 'max_attempts': 1}, 'old planner claim changed')
    calls = child / 'model_calls'
    require({p.name for p in calls.iterdir()} == {'plan_t2'}, 'extra old planner calls')
    call = calls / 'plan_t2'
    require(not (call / 'accepted_response.json').exists(), 'must preserve rejected response, not accepted')
    require(sha256(call / 'response.json') == RAW_SHA, 'wrong rejected response')
    require(read_json(call / 'schema_error.json') == {'response_sha256': RAW_SHA, 'error': ERROR},
            'rejection is not the exact launch prefix failure')
    invocation = read_json(call / 'invocation.json')
    require(invocation['model_requested'] == old.MODELS['planner'] and invocation['attempt'] == 1
            and invocation['exit_code'] == 0 and invocation.get('retry_of') is None, 'planner lineage differs')
    parent_proof, start = old.verify_activation(out)
    end = read_json(folder / 'producer_end.json')['files']
    old.producer_archive(end)
    require(start == end, 'failed attempt producer drift')
    manifest, parent = old.prepare.verify(child), old.prepare.verify(out)
    require(all(manifest[k] == parent[k] for k in SOURCE_KEYS), 'failed child source differs')
    raw = parse_strict((call / 'response.json').read_bytes())
    executable, normalization = normalize(raw, child / 'input/project', Path(manifest['project_source']),
                                         read_json(call / 'schema.json'), manifest)
    return {'version': VERSION, 'parent': parent_proof, 'failed_files': files,
            'failed_files_digest': FAILED_DIGEST, 'failure_sha256': FAILURE_SHA,
            'raw_response': str(call / 'response.json'), 'raw_response_sha256': RAW_SHA,
            'schema_sha256': sha256(call / 'schema.json'), 'invocation_sha256': sha256(call / 'invocation.json'),
            'normalization': normalization, 'executable': executable, 'limits': LIMITS,
            'ui_acceptance': old.ui_acceptance()}


def normalization_receipt(proof):
    return {**proof['normalization'], 'version': VERSION,
            'raw_response': proof['raw_response'], 'raw_response_sha256': RAW_SHA,
            'schema_sha256': proof['schema_sha256'], 'invocation_sha256': proof['invocation_sha256'],
            'failed_files_digest': FAILED_DIGEST, 'failure_sha256': FAILURE_SHA}


def coverage(executable):
    ids = ['play.launch', 'play.operate']
    planned = sorted({i for p in executable['probes'] for i in p['criterion_ids']})
    return {'take': 2, 'targets': ids, 'planned': planned, 'unplanned': sorted(set(ids) - set(planned))}


def verify_plan(child, proof):
    require(not (child / 'model_calls').exists(), 'new planner calls/accepted receipts forbidden')
    require({p.name for p in (child / 'takes').iterdir()} == {'2'}, 'only remaining global take2 permitted')
    manifest, parent = old.prepare.verify(child), old.prepare.verify(old.OUT)
    require(all(manifest[k] == parent[k] for k in SOURCE_KEYS), 'new child source differs')
    executable = read_json(child / 'takes/2/plan.json')
    require(executable == proof['executable'], 'derived plan differs from exact lexical normalization')
    require(read_json(child / 'takes/2/plan_coverage.json') == coverage(executable), 'coverage changed')
    require(read_json(child / 'takes/2/normalization.json') == normalization_receipt(proof), 'normalization receipt changed')
    old.plan.validate(executable, old.short_manifest(manifest), child / 'input/project')
    old.require_key_plan(executable)
    return executable


def verify_child(child, proof):
    executable = verify_plan(child, proof)
    native = child / 'takes/2/record/native/take'
    require(read_json(native / 'capture_schedule.json') == old.expected_schedule(executable), 'capture policy changed')
    old.verify_admission(child)
    return old.native_proof(child, 2)


def verify_activation(out):
    proof = inspect(out)
    folder = out / REL
    start = read_json(folder / 'producer_start.json')['files']
    old.producer_archive(start)
    require(start.get(SELF) == sha256(Path(__file__)), 'continuation verifier pin changed')
    require(read_json(folder / 'qualification_hold.json') == HOLD, 'qualification hold changed')
    require(read_json(folder / 'activation.json') == {
        'version': VERSION, 'proof': proof, 'limits': LIMITS,
        'producer_start_sha256': sha256(folder / 'producer_start.json')}, 'activation changed')
    for rel, value in proof['failed_files'].items():
        # Preserve small control/raw/producer bytes as an additional exact archive.
        # Original input, runtime copies and already archived take1 evidence stay retained in place.
        if archive_file(rel):
            require(sha256(old.plain(folder / 'failed_archive' / rel)) == value, 'failed archive changed: ' + rel)
    return proof, start


def archive_file(rel):
    return not rel.startswith(('child/input/', 'child/runtime/', 'parent_archive/'))


def completion_payload(out):
    proof, start = verify_activation(out)
    folder, child = out / REL, out / REL / 'child'
    require(not (folder / 'failure.json').exists(), 'failed continuation cannot qualify or automatically replay')
    require(read_json(folder / 'native_dispatch.claim.json') == LIMITS, 'native claim changed')
    end = read_json(folder / 'producer_end.json')['files']
    old.producer_archive(end)
    require(old.runner().producer_closure(start) == old.runner().producer_closure(end), 'native producer drift')
    for rel, value in start.items():
        if rel.startswith(VERIFY_PREFIXES) or rel == 'pipeline/eval/stage1/recovery_support.py':
            require(sha256(old.plain(old.BENCH / rel)) == value, 'verification dependency changed: ' + rel)
    native = verify_child(child, proof)
    require(read_json(folder / 'native_finished.json') == native, 'native proof changed')
    score = old.formal_score(child)
    require(read_json(child / 'playable_score.json') == score, 'score differs from formal rules')
    require(read_json(child / 'status.json') == done_status(), 'child status changed')
    return {'version': VERSION, 'qualified': True, 'score': score, 'native': native,
            'activation_sha256': sha256(folder / 'activation.json'),
            'producer_end_sha256': sha256(folder / 'producer_end.json'),
            'normalization_sha256': sha256(child / 'takes/2/normalization.json'),
            'disk_evidence': disk_evidence(folder), 'child_evidence': old.evidence(child), 'limits': LIMITS, 'freed_bytes': 0}


def done_status():
    return {'step': 'playable', 'state': 'done', 'complete': True, 'version': VERSION}


def replacement(folder):
    return {'version': VERSION, 'child': 'child', 'completion_sha256': sha256(folder / 'completion.json'),
            'score_sha256': sha256(folder / 'child/playable_score.json')}


def verify_completion(out):
    out = old.plain(out)
    require(out == old.OUT, 'foreign recovery')
    payload = completion_payload(out)
    folder = out / REL
    require(read_json(folder / 'completion.json') == payload, 'completion evidence changed')
    require(read_json(folder / 'replacement.json') == replacement(folder), 'replacement binding changed')
    return payload['score']


def qualified_replacement_score(out):
    try:
        return verify_completion(Path(out))
    except Exception:
        return None


GIB = 1024 ** 3
REMAINING_CACHE_BYTES = 8 * GIB
RESERVE_BYTES = 8 * GIB


def snapshot_copy_budget(out):
    """Measure exactly the source files formal prepare will copy, before any writes."""
    manifest = old.prepare.verify(out)
    original = old.plain(Path(manifest['project_source']))
    files = old.snapshot_files(original)
    require(bool(files) and old.prepare.tree_digest(files) == manifest['snapshot_digest'],
            'original snapshot digest changed before disk gate')
    require(files == old.tree(out / 'input/project'), 'original differs from frozen input before disk gate')
    sizes = {}
    for rel, expected in files.items():
        raw = old.plain(original / rel).read_bytes()
        require(old.hashlib.sha256(raw).hexdigest() == expected, 'source changed while measuring copy budget')
        sizes[rel] = len(raw)
    require(old.snapshot_files(original) == files, 'source inventory changed while measuring copy budget')
    return {'policy': 'formal-snapshot-copy-bytes.v1', 'project_source': str(original),
            'snapshot_digest': manifest['snapshot_digest'], 'files': files, 'file_bytes': sizes,
            'source_bytes': sum(sizes.values()), 'copy_count': 2,
            'required_copy_bytes': 2 * sum(sizes.values())}


def pre_copy_disk(out, proof):
    snapshot = snapshot_copy_budget(out)
    target, source = proof['parent']['target'], proof['parent']['source']
    require(target['engine'] == 'ue5' and target['required_real_clients'] == 1,
            'disk accounting requires single UE client')
    # Keep the formal gate unchanged; replace only its inaccurate raw-delivery
    # byte estimate with the measured snapshot it will actually copy twice.
    measured = {**source, 'source_bytes': snapshot['source_bytes']}
    estimate = old.runner().check_disk(old.ROOT, target, measured)
    require(estimate['copy_estimate_bytes'] == snapshot['required_copy_bytes']
            and estimate['engine_cache_allowance_bytes'] == REMAINING_CACHE_BYTES
            and estimate['reserve_bytes'] == RESERVE_BYTES, 'unexpected formal snapshot disk estimate')
    return {**estimate, 'stage': 'pre_copy', 'snapshot_copy_budget': snapshot,
            'original_source_inventory': source, 'original_source_inventory_bytes': source['source_bytes']}


def copied_sources(child):
    """Before native mutation, verify both complete, independent authored copies."""
    manifest = old.prepare.verify(child)
    original = old.plain(Path(manifest['project_source']))
    expected = old.snapshot_files(original)
    require(bool(expected), 'empty source inventory')
    require(old.prepare.tree_digest(expected) == manifest['snapshot_digest'], 'source snapshot digest changed')
    roots = [old.plain(child / rel) for rel in ('input/project', 'runtime/project')]
    require(len({original.resolve(), *(root.resolve() for root in roots)}) == 3,
            'source copies are not independent')
    for root in roots:
        require(root.is_dir() and old.tree(root) == expected, 'source copy incomplete or changed: ' + str(root))
        for rel in expected:
            require(not (root / rel).samefile(original / rel), 'source copy aliases original')
    require(all(not (roots[0] / rel).samefile(roots[1] / rel) for rel in expected),
            'source copies alias each other')
    sizes = {rel: (roots[0] / rel).stat().st_size for rel in expected}
    return {'files': expected, 'snapshot_digest': manifest['snapshot_digest'],
            'bytes_per_copy': sum(sizes.values()), 'copy_count': 2,
            'verified_copy_bytes': 2 * sum(sizes.values()),
            'paths': [str(root) for root in roots]}


def post_copy_disk(folder, child):
    copies = copied_sources(child)  # Never discount estimated copies until BOTH verify.
    pre = read_json(folder / 'disk_pre_copy.json')
    require(copies['files'] == pre['snapshot_copy_budget']['files']
            and copies['snapshot_digest'] == pre['snapshot_copy_budget']['snapshot_digest']
            and copies['verified_copy_bytes'] == pre['snapshot_copy_budget']['required_copy_bytes'],
            'copies differ from pre-copy measured budget')
    require(pre['engine_cache_allowance_bytes'] == REMAINING_CACHE_BYTES
            and pre['reserve_bytes'] == RESERVE_BYTES, 'unexpected original cache/reserve allowance')
    free = shutil.disk_usage(old.ROOT).free
    receipt = {'policy': 'g025-verified-copies-remaining-allocation.v1', 'stage': 'pre_native_post_copy',
        'pre_copy_sha256': sha256(folder / 'disk_pre_copy.json'), 'copies': copies,
        'original_copy_estimate_bytes': pre['copy_estimate_bytes'], 'remaining_copy_bytes': 0,
        'engine_cache_allowance_bytes': REMAINING_CACHE_BYTES, 'reserve_bytes': RESERVE_BYTES,
        'required_free_bytes': REMAINING_CACHE_BYTES + RESERVE_BYTES, 'free_bytes': free,
        'observed_free_change_bytes': pre['free_bytes'] - free,
        'passed': free >= REMAINING_CACHE_BYTES + RESERVE_BYTES}
    # Persist even a low-disk rejection, before any native claim.
    old.exclusive(folder / 'disk_post_copy.json', receipt)
    require(receipt['passed'], 'post-copy disk reserve: remaining 8GiB cache + 8GiB reserve unavailable')
    return receipt


def disk_evidence(folder):
    pre = read_json(folder / 'disk_pre_copy.json')
    post = read_json(folder / 'disk_post_copy.json')
    require(post['pre_copy_sha256'] == sha256(folder / 'disk_pre_copy.json')
            and post['passed'] is True and post['remaining_copy_bytes'] == 0
            and post['engine_cache_allowance_bytes'] == pre['engine_cache_allowance_bytes'] == REMAINING_CACHE_BYTES
            and post['reserve_bytes'] == pre['reserve_bytes'] == RESERVE_BYTES
            and post['required_free_bytes'] == REMAINING_CACHE_BYTES + RESERVE_BYTES
            and post['free_bytes'] >= post['required_free_bytes']
            and pre['required_free_bytes'] == pre['copy_estimate_bytes'] + REMAINING_CACHE_BYTES + RESERVE_BYTES
            and pre['free_bytes'] >= pre['required_free_bytes'], 'disk stage accounting changed')
    # Runtime is legitimately modified by admission/native; validate its pre-dispatch
    # copy inventory against the still-frozen input, not against the mutated runtime.
    manifest = old.prepare.verify(folder / 'child')
    budget = pre['snapshot_copy_budget']
    require(budget == snapshot_copy_budget(folder / 'child')
            and pre['source_bytes'] == budget['source_bytes']
            and pre['copy_estimate_bytes'] == budget['required_copy_bytes']
            and pre['original_source_inventory_bytes'] == pre['original_source_inventory']['source_bytes'],
            'pre-copy snapshot budget changed')
    require(post['copies']['copy_count'] == 2
            and post['copies']['files'] == old.tree(folder / 'child/input/project')
            and post['copies']['snapshot_digest'] == manifest['snapshot_digest'], 'disk copy proof changed')
    return {name: sha256(folder / name) for name in ('disk_pre_copy.json', 'disk_post_copy.json')}


def execute(out):
    installed()
    out = old.plain(out)
    require(out == old.OUT, 'foreign recovery')
    r = old.runner()
    with r.locked(old.ROOT / '_kimi_batch/locks/G025.lock'), r.locked(out / 'takes/1/record/.postprocess.lock'):
        folder, child = out / REL, out / REL / 'child'
        require(not folder.exists(), 'one-shot continuation already exists; preserve partial/failed native')
        proof = inspect(out)  # Includes sealed G020 UI acceptance before any copies/claim.
        pre_copy = pre_copy_disk(out, proof)
        start = r.production()
        require(start.get(SELF) == sha256(Path(__file__)), 'producer does not include new module')
        r.archive_producer(old.ROOT, start)
        folder.mkdir(parents=True, exist_ok=False)
        old.exclusive(folder / 'disk_pre_copy.json', pre_copy)
        old.exclusive(folder / 'qualification_hold.json', HOLD)
        old.exclusive(folder / 'producer_start.json', {'files': start})
        old.exclusive(folder / 'activation.json', {'version': VERSION, 'proof': proof, 'limits': LIMITS,
            'producer_start_sha256': sha256(folder / 'producer_start.json')})
        try:
            for rel, expected in proof['failed_files'].items():
                if archive_file(rel):
                    raw = (out / old.REL / rel).read_bytes()
                    require(old.hashlib.sha256(raw).hexdigest() == expected, 'failed bytes changed during archive')
                    dest = folder / 'failed_archive' / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open('xb') as handle:
                        handle.write(raw)
            parent = old.prepare.verify(out)
            manifest = old.prepare.prepare(Path(parent['delivery_dir']), child,
                models=old.MODELS, suite='stage1', playable_only=True)
            require(all(manifest[k] == parent[k] for k in SOURCE_KEYS), 'fresh child changed source')
            executable = proof['executable']
            old.exclusive(child / 'takes/2/plan.json', executable)
            old.exclusive(child / 'takes/2/plan_coverage.json', coverage(executable))
            old.exclusive(child / 'takes/2/normalization.json', normalization_receipt(proof))
            verify_plan(child, proof)
            require(inspect(out) == proof, 'failed/source/UI lineage changed before native')
            old.verify_current(start)
            post_copy_disk(folder, child)
            old.exclusive(folder / 'native_dispatch.claim.json', LIMITS)
            # Formal record owns shared GUI slot, build, capture and cleanup. No retry loop.
            old.record.record(child, old.short_manifest(manifest), executable, 2)
            native = verify_child(child, proof)
            old.exclusive(folder / 'native_finished.json', native)
            score = old.formal_score(child, save=True)
            old.exclusive(child / 'playable_score.json', score)
            old.exclusive(child / 'status.json', done_status())
            end = r.production()
            r.archive_producer(old.ROOT, end)
            old.exclusive(folder / 'producer_end.json', {'files': end})
            old.exclusive(folder / 'completion.json', completion_payload(out))
            old.exclusive(folder / 'replacement.json', replacement(folder))
            return verify_completion(out)
        except BaseException as exc:
            old.exclusive(folder / 'failure.json', {'type': type(exc).__name__, 'error': str(exc),
                                                   'traceback': traceback.format_exc()})
            raise
        finally:
            if not (folder / 'producer_end.json').exists():
                end = r.production()
                r.archive_producer(old.ROOT, end)
                old.exclusive(folder / 'producer_end.json', {'files': end})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    for name in ('inspect', 'execute', 'verify'):
        group.add_argument('--' + name, action='store_true')
    args = parser.parse_args(argv)
    installed()
    result = inspect(args.out) if args.inspect else execute(args.out) if args.execute else verify_completion(args.out)
    print(old.json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
