"""Explicit judge-only recovery of already executed, independently accepted native plans."""
from pathlib import Path
from .protocol import sha

VERSION='whitebox-native-plan-capture-recovery.v1'


def verify_recorded_capture(root,current,recorded):
    from . import batch, multiclient
    root=Path(root).resolve()
    receipt=batch.read(root/'native_capture_recovery.json')
    if receipt.get('schema')!=VERSION or receipt.get('execution_allowed') is not False:
        raise ValueError('Invalid native capture recovery contract')
    source=Path(receipt['source_attempt']).resolve()
    if source==root or source.parent!=root.parent:
        raise ValueError('Native capture recovery must use another preserved attempt in this batch')
    qualification=source/'independent_native_plan_capture_audit.json'
    if sha(qualification)!=receipt.get('qualification_sha256'):
        raise ValueError('Original native capture qualification changed')
    accepted=batch.read(qualification)
    if (accepted.get('schema')!='whitebox-native-plan-capture-acceptance.v1'
            or accepted.get('valid') is not True or accepted.get('plan_valid') is not True
            or accepted.get('source_run')!=str(source) or accepted.get('planning_identity')!=recorded
            or accepted.get('formal_eval_complete') is not False or not accepted.get('bindings')):
        raise ValueError('Historical plan lacks independent native capture acceptance')
    required={'sol_plan.json','input/pilot_rubric.json','input_manifest.json','static_existence.json',
        'runtime/frame_index.jsonl','runtime/actions.jsonl','runtime/state_trace.jsonl','runtime/event_trace.jsonl',
        'runtime/multisession_index.json','runtime/multisession_sources.json','runtime/capture_schedule.json',
        'runtime/action_frame_links.json'}
    if not required<=accepted['bindings'].keys(): raise ValueError('Native acceptance lacks required physical bindings')
    for name,digest in accepted['bindings'].items():
        for attempt in [source,root]:
            path=(attempt/name).resolve()
            if not path.is_relative_to(attempt) or not path.is_file() or sha(path)!=digest:
                raise ValueError('Native accepted evidence changed: '+name)
    if any(recorded.get(k)!=v for k,v in current.items() if k!='constraints_sha256'):
        raise ValueError('Native recovery changed frozen source, contract or rubric')
    if batch.read(root/'sol_plan.json').get('planning_identity')!=recorded:
        raise ValueError('Historical plan identity changed')
    if not accepted.get('core12_sha256') or not accepted.get('validator_bindings',{}).get('endpoint_channels.py'):
        raise ValueError('Original native acceptance lacks validator source bindings')
    multiclient.audit_capture(root/'runtime',batch.read(root/'runtime/capture_schedule.json'))
    multiclient.verify_projects(root)
    return recorded
