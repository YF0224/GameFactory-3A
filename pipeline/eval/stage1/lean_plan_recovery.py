"""One explicitly authorized fresh v3 planning attempt with verified static reuse."""
import argparse
import copy
import fcntl
import os
import shutil
import time
from pathlib import Path

from . import batch, core12, static_existence
from .protocol import dump, sha

RECEIPT = 'lean_plan_recovery.json'
VERSION = 'whitebox-lean-plan-recovery.v1'
AUTHORIZATION = 'User 2026-10-29: 用精简版的跑一下吧; Sol G005 only, preserve static and failed attempts.'


def verify(root, protocol, source):
    root, source = Path(root).resolve(), Path(source).resolve()
    receipt = batch.read(root/RECEIPT)
    if (receipt.get('version') != VERSION or root == source or source.parent != root.parent
            or receipt['source_attempt'] != str(source) or not receipt['authorization']):
        raise ValueError('Invalid lean planning recovery source')
    for folder in (root, source):
        batch.verify_inputs(folder)
        core12.verify_attempt(folder, 'unity3d')
    if protocol != batch.read(source/'input/pilot_rubric.json'):
        raise ValueError('Lean planning recovery changed frozen protocol')
    before, after = (batch.read(folder/'input_manifest.json') for folder in (source, root))
    for key in ('entry','source_hashes_before','snapshot_hashes','input_hashes','planning_contract','model_requested'):
        if before[key] != after[key]:
            raise ValueError('Lean planning recovery changed inputs: '+key)
    for name, digest in receipt['source_bindings'].items():
        if sha(source/name) != digest:
            raise ValueError('Lean planning recovery source changed: '+name)
    for name in receipt['copied_files']:
        if sha(root/name) != sha(source/name):
            raise ValueError('Lean planning recovery copied evidence changed: '+name)
    from .route_first_capture import LEAN_PROMPT_POLICY
    if batch.read(root/'planning_prompt_policy.json')['version'] != LEAN_PROMPT_POLICY:
        raise ValueError('Lean recovery requires explicit v3 prompt')
    if receipt.get('cleanup_reconciliation'):
        path=Path(receipt['cleanup_reconciliation'])
        if sha(path)!=receipt['cleanup_reconciliation_sha256']:
            raise ValueError('Restart cleanup reconciliation changed')
    return True


def prepare(source, *, restart_plan=False, reconciliation=None):
    source = Path(source).resolve()
    if (source/RECEIPT).exists() and not restart_plan:
        raise ValueError('One lean recovery only; preserve failure and diagnose before further calls')
    if ((source/'scores.json').exists() or (not restart_plan and
            any((source/name).exists() for name in ('sol_plan.json','background_record')))):
        raise ValueError('Existing plan, recording or score protected')
    invocation = source/'model_calls/plan/invocation.json'
    if not invocation.is_file():
        raise ValueError('Lean recovery requires a preserved previous plan invocation')
    ident = batch.read(source/'input_manifest.json')['entry']['id']
    if ident != 'Sol__G005_broken_realm_echo':
        raise ValueError('This authorization applies only to Sol G005')
    suffix='__lean_plan_restart_v1_' if restart_plan else '__lean_plan_v3_'
    for receipt in source.parent.glob(ident+suffix+'*/'+RECEIPT):
        if batch.read(receipt)['source_attempt'] == str(source):
            raise ValueError('Lean recovery already prepared; resume its explicit saved run')
    batch.verify_inputs(source)
    protocol = core12.verify_attempt(source, 'unity3d')
    original = static_existence.load(source, protocol)
    entry = batch.read(source/'input_manifest.json')['entry']
    from .effective import resolve_result
    if resolve_result(source.parents[1], entry)['valid']:
        raise ValueError('Existing effective score protected')
    root = source.parent/(ident+suffix+str(time.time_ns()))
    if restart_plan:
        # Keep the source/rubric/static identity; only the new plan is regenerated.
        root.mkdir()
        shutil.copytree(source/'input',root/'input')
        for name in ('input_manifest.json','attempt_manifest.json','unsupported_input_policy.json','route_metadata_repair.json'):
            if (source/name).is_file():shutil.copy2(source/name,root/name)
    else:
        batch.prepare(source.parents[1], entry, root, previous_attempt=source)
    if batch.read(root/'input/pilot_rubric.json') != protocol:
        raise ValueError('Fresh preparation changed frozen protocol; preserved partial attempt, no model call')
    from .route_first_capture import install_compact_policy, LEAN_PROMPT_POLICY
    install_compact_policy(root, version=LEAN_PROMPT_POLICY)
    files = ['static_existence.json']
    shutil.copy2(source/'static_existence.json', root/'static_existence.json')
    for folder in (source/'model_calls').glob('static_existence*'):
        if folder.is_dir():
            shutil.copytree(folder, root/'model_calls'/folder.name)
            files.extend(str(path.relative_to(source)) for path in folder.rglob('*') if path.is_file())
    bindings = files + ['input_manifest.json','input/pilot_rubric.json']
    if restart_plan:
        bindings.extend(name for name in ('sol_plan.json','unsupported_input_policy.json','route_metadata_repair.json')
                        if (source/name).is_file())
    bindings.extend(str(path.relative_to(source)) for folder in (source/'model_calls').glob('plan*')
                    if folder.is_dir() for path in folder.iterdir() if path.is_file())
    dump(root/RECEIPT, {'version':VERSION, 'source_attempt':str(source),
        'source_bindings':{name:sha(source/name) for name in bindings}, 'copied_files':files,
        'authorization':('User 2026-10-29: restart G005 from a fresh plan using the added restart guidance.'
                         if restart_plan else AUTHORIZATION), 'static_model_calls_added':0,
        'explicit_plan_restart':restart_plan,
        'cleanup_reconciliation':str(reconciliation) if reconciliation else None,
        'cleanup_reconciliation_sha256':sha(reconciliation) if reconciliation else None,
        'plan_timeout_seconds':protocol['runtime_budget']['plan_timeout_seconds'], 'maximum_recoveries':1,
        'scope':'Fresh v3 prompt/schema; subsequent correction uses field patches; unchanged rubric, delivery and static verdicts'})
    if static_existence.load(root, protocol) != original:
        raise ValueError('Lean recovery static judgments changed')
    return root


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--restart-plan', action='store_true', help='Explicit new plan with current lean guidance; preserve previous plan/capture')
    args = parser.parse_args()
    output = args.output.resolve()
    config = batch.read(output/'configuration.json')
    from . import unity_single
    from engine_adapters.unity3d.playtest import native_acceptance
    acceptance = Path(config['editor_acceptance'])
    editor = Path(batch.read(acceptance)['editor'])
    control = Path(config['control_root'])
    with (control/'whitebox_production_queue.lock').open('a+') as lease:
        fcntl.flock(lease, fcntl.LOCK_EX|fcntl.LOCK_NB)
        state = batch.read(output/'single_state.json')
        if state.get('pid') and state['pid'] != os.getpid():
            try: os.kill(state['pid'], 0)
            except ProcessLookupError: pass
            else: raise ValueError('Previous single-case process still alive')
        native_acceptance.verify(acceptance, Path(config['adapter_root']), editor)
        native = batch.read(acceptance)
        reconciliation=None
        if args.restart_plan:
            from .unity_axis_recovery import reconcile_interrupted_cleanup
            reconciliation=reconcile_interrupted_cleanup(output,Path(state['attempt']),config)
        cleanup = unity_single.check_cleanup(config, Path(native['stages'][-1]['verification']['path']).parent)
        dump(output/'lean_plan_preflight.json', {'checked_unix':time.time(), 'cleanup':cleanup,
             'acceptance_sha256':sha(acceptance), 'production_lease_acquired':True})
        root = prepare(Path(state['attempt']),restart_plan=args.restart_plan,reconciliation=reconciliation)
        dump(output/'state_history'/('before_lean_plan_'+str(time.time_ns())+'.json'), state)
        unity_single.phase(output, 'static_reused', attempt=str(root), previous_attempt=state['attempt'],
                           prompt_policy='whitebox-route-first-prompt.v3', static_model_calls_added=0)
        try:
            unity_single.continue_stages(output, root)
        except BaseException as exc:
            unity_single.phase(output, 'HARNESS_ERROR', attempt=str(root), reason=str(exc))
            raise


if __name__ == '__main__':
    main()
