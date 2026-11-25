"""Explicit planner timeout recovery; original model responses remain immutable."""
import copy
import shutil
import time
from pathlib import Path

from . import batch, budgets, core12, static_existence
from .protocol import dump, sha

VERSION = 'whitebox-plan-budget-recovery.v1'
RECEIPT = 'plan_budget_recovery.json'


def verify(root, protocol, source):
    root, source = Path(root).resolve(), Path(source).resolve()
    receipt = batch.read(root / RECEIPT)
    if (receipt.get('version') != VERSION or source == root
            or source.parent != root.parent
            or Path(receipt['source_attempt']).resolve() != source):
        raise ValueError('Invalid planner budget recovery source')
    for folder in (source, root):
        batch.verify_inputs(folder)
        core12.verify_attempt(folder, 'unity3d')
    for name, digest in receipt['source_bindings'].items():
        if sha(source / name) != digest:
            raise ValueError('Planner budget recovery source changed: ' + name)
    original = batch.read(source / 'input/pilot_rubric.json')
    expected = copy.deepcopy(original)
    override = protocol['runtime_budget'].get('plan_timeout_override')
    seconds = budgets.validate_plan_override(override)
    expected['runtime_budget']['plan_timeout_seconds'] = seconds
    expected['runtime_budget']['plan_timeout_override'] = override
    if expected != protocol:
        raise ValueError('Planner budget recovery changed non-timeout protocol fields')
    old_manifest = batch.read(source / 'input_manifest.json')
    new_manifest = batch.read(root / 'input_manifest.json')
    for key in ('source_hashes_before', 'snapshot_hashes', 'planning_contract', 'model_requested'):
        if old_manifest[key] != new_manifest[key]:
            raise ValueError('Planner budget recovery changed delivery identity')
    for manifest in (old_manifest, new_manifest):
        manifest['input_hashes'].pop('pilot_rubric.json')
    if old_manifest['input_hashes'] != new_manifest['input_hashes']:
        raise ValueError('Planner budget recovery changed non-protocol input files')
    old_entry = copy.deepcopy(old_manifest['entry'])
    new_entry = copy.deepcopy(new_manifest['entry'])
    new_entry.pop('plan_timeout_override', None)
    if old_entry != new_entry:
        raise ValueError('Planner budget recovery changed entry')
    for name in receipt['model_call_files']:
        if sha(root / name) != sha(source / name):
            raise ValueError('Planner budget recovery changed original static model call')
    return True


def prepare(source, seconds, authorization):
    source = Path(source).resolve()
    if (source / RECEIPT).exists():
        raise ValueError('A timeout recovery already exists; do not retry indefinitely')
    if (source / 'sol_plan.json').exists() or (source / 'background_record').exists():
        raise ValueError('Existing plan/capture protected')
    invocation = batch.read(source / 'model_calls/plan/invocation.json')
    if invocation.get('status') != 'TIMEOUT':
        raise ValueError('Recovery requires the preserved timed-out plan invocation')
    protocol = core12.verify_attempt(source, 'unity3d')
    if protocol['runtime_budget']['plan_timeout_seconds'] >= seconds:
        raise ValueError('Planner recovery must explicitly increase the old timeout')
    original_result = static_existence.load(source, protocol)
    override = {'version': budgets.PLAN_OVERRIDE_VERSION, 'seconds': seconds,
                'authorization': authorization}
    budgets.validate_plan_override(override)
    entry = copy.deepcopy(batch.read(source / 'input_manifest.json')['entry'])
    from .effective import resolve_result
    if resolve_result(source.parents[1], entry)['valid']:
        raise ValueError('Existing effective score protected')
    entry['plan_timeout_override'] = override
    root = source.parent / (entry['id'] + '__plan1800_recovery_' + str(time.time_ns()))
    batch.prepare(source.parents[1], entry, root, previous_attempt=source)
    from .route_first_capture import install_compact_policy
    install_compact_policy(root)
    # Keep the exact original model invocation, schema, prompt and response bytes.
    model_files = []
    for folder in sorted((source / 'model_calls').glob('static_existence*')):
        if not folder.is_dir():
            continue
        shutil.copytree(folder, root / 'model_calls' / folder.name)
        model_files.extend(str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file())
    bindings = {name: sha(source / name) for name in (
        'input_manifest.json', 'input/pilot_rubric.json', 'static_existence.json',
        'model_calls/plan/invocation.json')}
    bindings.update({name: sha(source / name) for name in model_files})
    dump(root / RECEIPT, {'version': VERSION, 'source_attempt': str(source),
        'source_bindings': bindings, 'model_call_files': model_files,
        'authorization': authorization, 'plan_timeout_seconds': seconds,
        'static_model_calls_added': 0, 'scope': 'Only planner timeout changed'})
    artifact = copy.deepcopy(batch.read(source / 'static_existence.json'))
    artifact['result'] = copy.deepcopy(original_result)
    artifact['result']['identity'] = static_existence.identity(root, batch.read(root / 'input/pilot_rubric.json'))
    dump(root / 'static_existence.json', artifact)
    static_existence.load(root, batch.read(root / 'input/pilot_rubric.json'))
    return root
