"""Bind native screenshot settling to frozen action IDs, without game-state writes."""
import hashlib
import json
from pathlib import Path


def guards(schedule_path, actions):
    schedule_path = Path(schedule_path)
    schedule = json.loads(schedule_path.read_text())
    indexed = {row['action_id']:row for row in actions if row.get('action_id')}
    result = []
    for ident, endpoint in schedule['plan'].get('endpoints',{}).items():
        if endpoint.get('reachability') != 'EXECUTABLE':
            continue
        action = indexed.get(endpoint['last_action_id'])
        capture_id = 'endpoint/'+ident
        points = [row for row in schedule['points'] if capture_id in row['capture_ids']]
        if (action is None or action['action'] == 'wait' or ident not in action.get('criterion_ids',[])
                or endpoint['stable_after_ms'] < 150 or len(points) != 1
                or points[0]['at_ms'] != endpoint['at_ms']
                or action['planned_end_t_ms']+endpoint['stable_after_ms'] > endpoint['at_ms']):
            raise ValueError('Native settling guard differs from frozen endpoint/action/timing')
        result.append({'capture_id':capture_id,'action_id':action['action_id'],
                       'stable_after_ms':endpoint['stable_after_ms']})
    return {'schema':'whitebox-native-endpoint-settle.v1',
        'capture_schedule_sha256':hashlib.sha256(schedule_path.read_bytes()).hexdigest(),
        'endpoints':result,'game_state_writes':False}
