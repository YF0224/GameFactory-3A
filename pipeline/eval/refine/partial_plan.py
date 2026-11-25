"""Source-bound projection of an incomplete model route into a legal local plan.

Never adds, removes, reorders or retimes gameplay actions. Original conditions
stay intact. Unsupported endpoints become explicit coverage gaps, not defects.
"""
from copy import deepcopy
from pathlib import Path
import re
import tempfile
from .common import read, sha, dump, once
from .planning import compile_plan
from ..stage1.codex import validate_schema
from ..stage1.runtime import NATIVE_KEYS, native_actions

VERSION = 'refine.saved-route-local-projection.v1'


def project(raw, project_root, tasks, budget, schema, marker, default_map):
    validate_schema(raw, schema)
    result = deepcopy(raw)
    plan = result['native_plan']
    before = native_actions(plan)
    changes = []
    if plan['engine'] not in ('ue5', 'Unreal Engine'):
        raise ValueError('Projection cannot infer a different engine')
    if plan['launch_scene'] != default_map or default_map != '/Engine/Maps/Entry':
        raise ValueError('Projection requires the same delivered UE default map')
    source = plan['launch_source']
    if source != marker and ('project/'+marker not in source or 'project/Config/DefaultEngine.ini' not in source):
        raise ValueError('Projection cannot infer the launch source')
    if not (Path(project_root)/marker).is_file():
        raise ValueError('Actual admitted marker is missing from frozen project')
    for field, value in [('engine','ue5'),('launch_source',marker),('launch_scene','')]:
        if plan[field] != value:
            changes.append({'field':field,'original':plan[field],'normalized':value})
            plan[field] = value
    keys = {key.lower():key for key in NATIVE_KEYS}
    for probe in plan['probes']:
        for step in probe['steps']:
            if step['kind'] not in ('input','wait'):
                raise ValueError('Projection only supports encoded physical key/wait routes')
            if step['kind'] == 'input':
                try: key = '+'.join(keys[k.lower()] for k in step['key'].split('+'))
                except KeyError: raise ValueError('Projection cannot infer an unknown physical key')
                if key != step['key']:
                    changes.append({'action_id':probe['id']+'/'+step['id'], 'original_key':step['key'],'normalized_key':key})
                    step['key'] = key
    if native_actions(plan) != before:
        raise ValueError('Projection changed physical actions or timing')
    for endpoint in result['endpoints']:
        if endpoint['executable']:
            endpoint.update(executable=False,last_action_id='',at_ms=0,
                reason='LOCAL_PLAN_COVERAGE_GAP: no validated encoded route for this endpoint; not a product defect. '+endpoint['reason'])
    excluded, kept = [], []
    with tempfile.TemporaryDirectory(prefix='refine-local-projection-') as temporary:
        schedule = Path(temporary)/'schedule.json'
        for index, endpoint in enumerate(raw['endpoints']):
            if not endpoint['executable']:
                continue
            candidate = deepcopy(result)
            candidate['endpoints'][index] = deepcopy(endpoint)
            try:
                compile_plan(candidate, project_root, 'ue5', tasks, budget, schedule)
            except ValueError as exc:
                excluded.append({'task_id':endpoint['task_id'],'reason':str(exc)})
            else:
                result = candidate
                kept.append(endpoint['task_id'])
        compile_plan(result, project_root, 'ue5', tasks, budget, schedule)
    return result, {'metadata_normalization':changes,'physical_actions_identical':True,
                    'retained_endpoints':kept,'excluded_endpoints':excluded,
                    'coverage_note':'Only the encoded local route is executed. No product-unreachable claim or new gameplay route.'}


def recover(folder, schema, config, validator):
    folder = Path(folder)
    auth_path = folder/'partial_plan_authorization.json'
    auth = read(auth_path)
    if auth.get('version') != VERSION or auth.get('model_calls_added') != 0:
        raise ValueError('Local plan projection requires explicit no-new-model authorization')
    parents = {'failure':folder/'stages/plan.json', 'response':folder/'model_calls/plan/response.json',
               'schema':folder/'model_calls/plan/schema.json', 'admission':folder/'native_admission.json',
               'source':folder/'input/source_manifest.json','tasks':folder/'input/tasks.json',
               'recovery_failure':folder/'stages/plan_recovery_001.json',
               'recovery_invocation':folder/'model_calls/plan_recovery_001/invocation.json'}
    if set(auth.get('parents',{})) != set(parents):
        raise ValueError('Local projection lacks full parent lineage')
    for name,path in parents.items():
        if auth['parents'][name] != {'path':str(path.resolve()),'sha256':sha(path)}:
            raise ValueError('Local projection parent changed: '+name)
    if (read(parents['failure'])['status'] != 'ERROR'
            or read(parents['recovery_failure'])['status'] != 'ERROR'
            or read(parents['recovery_invocation']).get('status') != 'TIMEOUT'):
        raise ValueError('Local projection requires the preserved rejected plan and bounded timeout')
    admitted = read(parents['admission'])
    if config.get('ue_native_backend') != 'dock_native_sparse.v1' or admitted.get('scene') != '':
        raise ValueError('Local projection requires matching default-map UE native admission')
    project_root = folder/'input/project'
    source = read(parents['source'])['files']
    for relative,digest in source.items():
        if sha(project_root/relative) != digest:
            raise ValueError('Frozen model source changed: '+relative)
    ini = (project_root/'Config/DefaultEngine.ini').read_text()
    maps = re.findall(r'^GameDefaultMap=(\S+)\s*$',ini,re.M)
    if len(maps) != 1:
        raise ValueError('Cannot prove a unique author default map')
    marker = Path(admitted['uproject']).name
    def invoke():
        result,receipt = project(read(parents['response']),project_root,read(parents['tasks']),
                                 config.get('recording_ms',180000),schema,marker,maps[0])
        validator(result)
        dump(folder/'partial_plan/receipt.json',dict(receipt,parents=auth['parents'],
             authorization_sha256=sha(auth_path),model_calls_added=0,repair_calls_added=0))
        dump(folder/'partial_plan/accepted_plan.json',result)
        return result
    result = once(folder,'partial_plan',invoke)
    if result != read(folder/'partial_plan/accepted_plan.json'):
        raise ValueError('Projected plan binding changed')
    validator(result)
    dump(folder/'plan.json',result)
    return result
