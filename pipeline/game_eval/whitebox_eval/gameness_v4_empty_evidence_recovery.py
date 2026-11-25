"""Source-bound continuation when a Gameness group lost same-take native frames.

Never change the frozen capture manifest or select successful frames. The only
eligible defect is a rejected zero-image call while sibling groups retain real,
predeclared endpoint frames. Preserve all parent calls and route every affected
check to one bounded, complete native delivery.
"""
from pathlib import Path
import hashlib
import json
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-empty-native-group-handoff.v1'
AUTH = 'engineering/gameness_empty_evidence_recovery.json'
ERROR = 'HARNESS_ERROR: original Gameness native images missing or unreadable'


def declared_frames(manifest, parent):
    subset = manifest['evidence_sets'][parent]
    if subset['frames'] or subset['delivery_sheets'] or subset['delivered_frame_count']:
        raise ValueError('Only an originally empty native evidence group qualifies')
    if any(w['frame_ids'] for w in manifest['sparse_capture_audit']['windows'].values()):
        raise ValueError('Declared temporal windows already have a delivery route')
    declared = {i for ids in manifest['endpoint_frames'].values() for i in ids}
    existing = {i for s in manifest['evidence_sets'].values() for i in s['frames']}
    if not declared or declared != existing:
        raise ValueError('Require all original predeclared same-take endpoint frames')
    return sorted(declared)


def receipt(root):
    root = Path(root); path = root/AUTH
    if not path.exists():
        return None
    value = runner.read(path)
    if value.get('version') != VERSION or value.get('root') != str(root.resolve()):
        raise ValueError('Native handoff authorization identity changed')
    for p, digest in value['bindings'].items():
        if sha(Path(p)) != digest:
            raise ValueError('Native handoff source binding changed: '+p)
    manifest = runner.read(root/'evidence_manifest.json')
    if declared_frames(manifest, value['parent']) != value['all_original_frame_ids']:
        raise ValueError('Native handoff original frame set changed')
    return value


def supplement(root, manifest, parent):
    value = receipt(root)
    if value is None or value['parent'] != parent:
        return set(), None
    if manifest != runner.read(Path(root)/'evidence_manifest.json'):
        raise ValueError('Native handoff must start from the unchanged original manifest')
    return set(value['all_original_frame_ids']), dict(path=str(Path(root)/AUTH),
        sha256=sha(Path(root)/AUTH), version=VERSION,
        all_original_frame_ids=value['all_original_frame_ids'],
        parent_failed_task=value['failed_task'], original_failure_preserved=True)


def permits_literal_task(root, name, original_tasks):
    value = receipt(root)
    if value is None:
        return False
    return any(old in original_tasks and new == name for old,new in value['task_routes'].items())


def qualify(root, failed_task, parent):
    from . import gameness_v3_runtime as runtime, gameness_v4 as policy
    root = Path(root).resolve(); folder = root/'model_calls'/failed_task
    if (folder/'accepted_response.json').exists():
        raise ValueError('Never replace an accepted Gameness response')
    error = runner.read(folder/'validation_error.json'); raw = runner.read(folder/'response.json')
    if (error.get('phase') != 'response_plan_validation' or error.get('exception') != ERROR
            or error.get('response_sha256') != sha(folder/'response.json')
            or raw.get('runtime_delivery_status') != 'MISSING_OR_UNREADABLE'):
        raise ValueError('Exact preserved zero-image delivery failure required')
    actual_path = root/'requests'/failed_task/'actual_delivery.json'; actual = runner.read(actual_path)
    if (actual.get('scoring_protocol') != policy.VERSION or actual.get('evidence_set') != parent
            or actual.get('images') != [] or actual.get('image_count') != 0
            or actual.get('actual_frame_ids') != [] or not actual.get('complete_author_sources')
            or actual.get('prompt_sha256') != sha(folder/'prompt.txt')):
        raise ValueError('Preserved call must prove zero images and complete original source')
    invocation = runner.read(folder/'invocation.json'); command = invocation.get('command', [])
    if (invocation.get('exit_code') != 0 or '--image' in command or '--model' not in command
            or command[command.index('--model')+1] != runtime.eval_models.model_for(root,'judge')):
        raise ValueError('Original completed judge invocation differs')
    runtime.shared_execution.audit_invocation(root,failed_task,actual)
    for item in actual['complete_author_sources']:
        p = root/item['path']
        if sha(p) != item['sha256'] or len(p.read_text(errors='replace').splitlines()) != item['line_count']:
            raise ValueError('Complete original author source changed')
    manifest = runner.read(root/'evidence_manifest.json')
    native = runner.read(root/'input/pilot_rubric.json')
    runtime.sparse_evidence.validate(root,native,manifest)
    frames = declared_frames(manifest,parent)
    qualification = runner.read(root/'source_qualification.json')
    runtime.verify_bindings(qualification['source_bindings'])
    paths = [p for p in folder.rglob('*') if p.is_file()]
    paths += [p for p in (root/'requests'/failed_task).rglob('*') if p.is_file()]
    paths += [root/n for n in ['input_manifest.json','source_qualification.json','evidence_manifest.json',
                              'sol_plan.json','input/pilot_rubric.json','runtime/frame_index.jsonl',
                              'requests/gameness_native_delivery/'+parent+'/proof.json']]
    for subset in manifest['evidence_sets'].values():
        paths += [root/item['path'] for item in subset['frames'].values()]
    return manifest,frames,{str(p):sha(p) for p in paths}


def authorize(root, failed_task, parent, tasks, repair_path):
    """Call while holding the ordinary per-identity Gameness lock."""
    from . import mechanic_v3_judge_transport as routing
    root=Path(root).resolve();repair_path=Path(repair_path).resolve()
    old = receipt(root)
    if old is not None:
        if old['failed_task'] != failed_task or old['parent'] != parent:
            raise ValueError('Existing native handoff is a different recovery')
        install_routes(root,old)
        return old
    manifest,frames,bindings=qualify(root,failed_task,parent)
    repair=runner.read(repair_path)
    if repair.get('classification')!='NON_SCORING_TOOL_TRANSPORT':
        raise ValueError('Explicit substantive tool repair diagnosis required')
    for p,digest in repair['after_source_bindings'].items():
        if sha(Path(p))!=digest:raise ValueError('Native handoff repair code changed')
    names=[name for name,group,_ in tasks if group==parent]
    ids=[spec['id'] for _,group,specs in tasks if group==parent for spec in specs]
    if (failed_task not in names or len(names)!=len(set(names)) or len(ids)!=len(set(ids))
            or set(ids)!=set(manifest['evidence_sets'][parent]['criterion_ids'])):
        raise ValueError('Every original affected criterion must retain its task identity')
    for name in names:
        if name!=failed_task and (root/'model_calls'/name).exists():
            raise ValueError('Sibling invocation already exists; do not replace or duplicate it')
        if (root/'engineering/judge_transport_recovery'/(name+'.json')).exists():
            raise ValueError('Existing task recovery cannot be bypassed')
        prior=root/'engineering/gameness_inline_schema'/(name+'.json')
        if prior.is_file():bindings[str(prior)]=sha(prior)
    bindings.update(repair['after_source_bindings'])
    bindings[str(repair_path)]=sha(repair_path)
    bindings[str(Path(__file__).resolve())]=sha(Path(__file__))
    fingerprint=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest()[:12]
    routes={name:name+'_native_handoff_'+fingerprint for name in names}
    value=dict(version=VERSION,root=str(root),failed_task=failed_task,parent=parent,
        all_original_frame_ids=frames,task_routes=routes,bindings=bindings,
        original_failure_preserved=True,original_manifest_unchanged=True,
        source_contract_criteria_weights_and_limits_unchanged=True,
        new_recording=False,score_requested=None,root_cause=repair['root_cause'])
    runner.exclusive_json(root/AUTH,value)
    install_routes(root,value)
    return value


def install_routes(root,value):
    from . import mechanic_v3_judge_transport as routing
    for name,recovered in value['task_routes'].items():
        path=root/'engineering/judge_transport_recovery'/(name+'.json')
        route=dict(transport_version=routing.VERSION,original_task=name,recovery_task=recovered,
            bindings={**value['bindings'],str(root/AUTH):sha(root/AUTH)},reason=value['root_cause'],
            original_failure_preserved=True,scoring_semantics_unchanged=True,
            images_and_parent_context_unchanged=False,
            all_original_predeclared_frames_added=True,new_recording=False)
        if path.exists():
            if runner.read(path)!=route:raise ValueError('Native handoff route changed')
        else:runner.exclusive_json(path,route)
