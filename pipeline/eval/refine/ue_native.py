"""Stage3 UE native admission/record integration, independent of historic scores."""
from pathlib import Path
import shutil
from .common import dump, read, sha, jsonl
from engine_adapters.ue5.playtest import native_record


def admission(folder, game, config):
    folder = Path(folder)
    opened = native_record.prepare(folder, config)
    from ..stage1.endpoint_sparse import CAPTURE_VERSION
    # Native acceptance: actual Enter -> existing room_entered event and real view.
    meta = {'action_id':'acceptance/enter','probe_id':'acceptance','step_id':'enter',
            'criterion_ids':['native_acceptance'],'purpose':'Verify delivered native key input',
            'expected_observation':'Existing title-to-room transition'}
    actions = [dict(meta,action='key',key='enter',duration_ms=150,planned_t_ms=500,planned_end_t_ms=650)]
    schedule = {'version':CAPTURE_VERSION,'warmup_ms':1000,'tolerance_ms':350,
                'points':[{'at_ms':2000,'capture_ids':['endpoint/native_acceptance'],
                           'criterion_ids':['native_acceptance']}],
                'plan':{'endpoints':[],'windows':[]}}
    take = folder/'ue_native_acceptance/take'
    native_record.record(opened,actions,schedule,take,4000)
    events = [r for _,r in jsonl(take/'event_trace.jsonl')]
    if not any(e.get('event')=='room_entered' and e.get('source_client')=='client_slot_0' for e in events):
        raise RuntimeError('HARNESS_ERROR: native key acceptance lacks existing room_entered effect')
    paths = [p for p in take.rglob('*') if p.is_file()]
    receipt = {'version':'stage3.ue-native-acceptance.v1','ok':True,
               'pin_sha256':sha(opened['pin']), 'build_sha256':sha(folder/'ue_build.json'),
               'files':{str(p):sha(p) for p in paths},
               'accepted':'Native key transport, game viewport sparse capture, clocks and process cleanup',
               'not_accepted':'True multiplayer or product task success'}
    dump(folder/'ue_native_acceptance/acceptance.json',receipt)
    opened['native_acceptance'] = str(folder/'ue_native_acceptance/acceptance.json')
    opened['native_acceptance_sha256'] = sha(opened['native_acceptance'])
    return opened


def record(folder, plan, schedule, config):
    folder = Path(folder)
    admitted = read(folder/'native_admission.json')
    if sha(admitted['native_acceptance']) != admitted['native_acceptance_sha256']:
        raise ValueError('UE native acceptance changed')
    accepted = read(admitted['native_acceptance'])
    if not accepted['ok'] or accepted['pin_sha256'] != sha(admitted['pin']):
        raise ValueError('UE native acceptance does not match pin')
    for path,digest in accepted['files'].items():
        if sha(path)!=digest: raise ValueError('UE native acceptance evidence changed')
    actions = read(folder/'native_actions.json')['actions']
    take = folder/'background_record/take'
    result = native_record.record(admitted,actions,schedule,take,plan['native_plan']['max_duration_ms'])
    for name in ('verification.json','runner_exit.json','cleanup.json'):
        shutil.copy2(take/name,folder/'background_record'/name)
    return result
