"""Complete delivery qualification including immutable runtime decoder metadata."""
from pathlib import Path
import argparse
import copy
import json
from . import mechanic_v3_delivery_audit_v3 as native
from .state_packet import DESCRIPTION
from .mechanic_v3_runner import read,stamp
from .protocol import sha,dump

VERSION='mechanic-published-delivery-audit.v4'


def upgrade(receipt):
    if receipt.get('version') not in {native.VERSION,VERSION}:
        raise ValueError('Unsupported actual-delivery receipt')
    result=copy.deepcopy(receipt);result['version']=VERSION
    root=Path(result['root'])
    for task in result['tasks']:
        path=root/'model_calls'/task['task']/'prompt.txt'
        if task['bindings'].get(str(path))!=sha(path):
            raise ValueError('Runtime metadata submitted prompt changed')
        prompt=path.read_text()
        actual_path=root/'requests'/task['task']/'actual_delivery.json'
        actual=read(actual_path) if actual_path.exists() else {}
        if actual.get('mechanic_persistent_complete_source'):
            from .mechanic_v3_persistent_text import verify_delivery
            prompt=verify_delivery(root,task['task'],actual)
        if actual.get('persistent_original_pixel_recovery'):
            from .persistent_original_pixel_recovery import verify_delivery
            prompt=verify_delivery(root,task['task'],actual)['expanded_prompt']
        needed={'state_decoder':'\n'+DESCRIPTION+'\n',
            'state_citation_whitelist':'\nSTATE CITATION WHITELIST (original raw line numbers, exhaustive):\n'}
        missing=[key for key,text in needed.items() if text not in prompt]
        if missing and not any(i['kind']=='RUNTIME_METADATA_NOT_SUBMITTED' for i in task['issues']):
            task['issues'].append(dict(kind='RUNTIME_METADATA_NOT_SUBMITTED',missing=missing))
        task['qualified']=not task['issues']
    result['qualified']=all(t['qualified'] for t in result['tasks'])
    return result


def publication(workspace,identity):
    return upgrade(native.publication(workspace,identity))


def upgrade_scope(path):
    old=read(path)
    if old.get('version')!=native.VERSION:raise ValueError('Expected retained native v3 audit')
    result=dict(old,version=VERSION,time=stamp(),parent_audit=str(path),parent_audit_sha256=sha(path))
    result['rows']=[dict(upgrade(r),status='DELIVERY_QUALIFIED' if upgrade(r)['qualified'] else 'DELIVERY_REPAIR_REQUIRED')
        if 'tasks' in r else r for r in old['rows']]
    result['delivery_qualified']=sum(r.get('qualified',False) for r in result['rows'])
    return result


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--parent-audit',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args(argv)
    if args.output.exists():raise ValueError('Audit receipts are immutable')
    result=upgrade_scope(args.parent_audit.resolve());dump(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}));return 0

if __name__=='__main__':raise SystemExit(main())
