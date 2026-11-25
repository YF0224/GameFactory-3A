"""Offline-only reuse of a full second Godot take after a short first take.

Never invokes record/planner. Deterministic rules see a temporary byte-exact
projection of take2 alone, with explicit projection identity in the receipt.
"""

from ..model_config import PLANNER_MODEL
from pathlib import Path
import argparse
import tempfile
import shutil

from . import godot_duration_recovery as duration
from ..stage1 import playable_rules
from ..stage1.paths import read_json, write_json, sha256

VERSION = 'stage1-godot-existing-window.v1'
LINEAGE = Path('recovery/godot_existing_window_v1')
require = duration.require


def parent_files(out):
    return duration.tree(out, skip=(str(LINEAGE),))


def proof(out):
    out = Path(out).absolute()
    duration.plain(out)
    manifest = read_json(out/'manifest.json')
    require(manifest['engine'] == 'godot' and manifest['suite'] == 'stage1'
            and manifest['models'] == {'planner':PLANNER_MODEL,'judge':'none'}, 'outside Stage1 Godot route')
    require(read_json(out/'status.json')['state'] in duration.TERMINAL, 'parent not terminal')
    hold = out/'qualification_hold.json'
    if hold.exists():
        h = read_json(hold)
        require(h.get('kind') == duration.HOLD_KIND and h.get('qualified') is False
                and h.get('recovery') in (str(duration.LINEAGE),str(LINEAGE)), 'unknown hold')
    takes = duration.inventory(out)
    require([t['take'] for t in takes] == [1,2] and all(t['consumed'] for t in takes), 'requires exactly two consumed takes')
    descendants = [p for pattern in ('**/dispatch.json','**/takes/*/record')
                   for p in (out/'recovery').glob(pattern)
                   if 'parent_archive' not in p.relative_to(out/'recovery').parts]
    require(not descendants, 'other native lineage blocks offline reuse')
    required = duration.effective_budget(manifest)['recording_ms']
    require(type(takes[0]['duration_ms']) in (int,float) and 0 < takes[0]['duration_ms'] < required,
            'first take is not short')
    plans = []
    for take in (1,2):
        receipt_path = out/f'model_calls/plan_t{take}/accepted_response.json'
        receipt = read_json(receipt_path)
        response = receipt_path.parent/receipt['path']
        duration.plain(response)
        require(response.resolve().is_relative_to((out/'model_calls').resolve()), 'accepted path escape')
        plan = out/f'takes/{take}/plan.json'
        require(sha256(response) == receipt['sha256'] and read_json(plan) == read_json(response), 'accepted plan drift')
        plans.append({'take':take,'plan_sha256':sha256(plan),'receipt_sha256':sha256(receipt_path),
                      'response_sha256':sha256(response)})
    return {'source':duration.source_proof(out,manifest),'plans':plans,'takes':takes,
            'required_ms':required,'manifest_recording_ms':manifest['budget']['recording_ms'],
            'native':duration.native_evidence(out,2,full_window=True,required_ms=required)}


def qualification(out):
    row = {'eligible':False,'window_qualified':False,'disposition':'MISSING','native_count':0}
    out = Path(out).absolute()
    if not (out/'manifest.json').is_file():
        return row
    try:
        with duration.existing_locks(out):
            p = proof(out)
        row.update(eligible=True,disposition='ELIGIBLE_OFFLINE_FULL_SECOND_TAKE',native_count=2,proof=p)
    except (OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        row.update(disposition='BLOCKED_OFFLINE_REUSE',reason=str(exc))
    return row


def evaluate_second(out):
    """Copy native evidence without edits; short take never enters rule inputs."""
    with tempfile.TemporaryDirectory(prefix='godot-existing-window-') as temp:
        projected = Path(temp).resolve()
        shutil.copytree(out/'takes/2/record',projected/'takes/1/record')
        require(duration.tree(projected/'takes/1/record') == duration.tree(out/'takes/2/record'), 'projection bytes differ')
        verdicts = playable_rules.evaluate(projected,read_json(out/'manifest.json'),1)
        report = read_json(projected/'playable_rules.json')
        require(report['takes'] == [1] and not report['harness_errors'], 'rules projection incomplete')
        return verdicts,report


def score(out,p,verdicts):
    manifest = read_json(out/'manifest.json')
    checks = {k:verdicts.get(k,{}).get('status','HARNESS_ERROR') for k in playable_rules.IDS}
    require('HARNESS_ERROR' not in checks.values(), 'incomplete rule outcome')
    return {'version':playable_rules.VERSION,'game_id':manifest['game_id'],'engine':'godot',
            'planner':manifest['models']['planner'],'checks':checks,'complete':True,
            'playable':round(100*sum(v == 'PASS' for v in checks.values())/3,2),
            'takes':[{'take':1,'consumed':True,'qualified_75s':False,'duration_ms':p['takes'][0]['duration_ms'],
                      'used_for_scoring':False},
                     {'take':2,'consumed':True,'qualified_75s':True,'duration_ms':p['native']['duration_ms'],
                      'used_for_scoring':True,'checks':checks}],
            'rules_projection':{'T1':'parent/takes/2','excluded_parent_takes':[1]},
            'native_takes_consumed':2,'max_native_takes':2,'native_recordings_added':0,'model_calls_added':0,
            'window_qualified':True,'publication_status':'SCORED_PENDING_AUDIT'}


def producer():
    names = ('godot_existing_window_recovery.py','godot_duration_recovery.py','playable_rules.py',
             'native_log.py','prepare.py','paths.py')
    return {name:sha256(Path(__file__).with_name(name)) for name in names}


def recover(out):
    out = Path(out).absolute()
    with duration.locked(out),duration.existing_locks(out):
        target = out/LINEAGE
        if (target/'replacement.json').exists():
            verified = qualified_replacement_score(out)
            require(verified is not None,'existing offline receipt failed verification')
            return verified
        require(not target.exists(),'partial offline receipt preserved')
        p = proof(out)
        duration.process_check(out)
        before = parent_files(out)
        duration.check_space(out,sum((out/k).stat().st_size for k in before)*2)
        target.mkdir(parents=True)
        duration.archive(before,out,target/'parent_archive')
        prod = producer()
        duration.archive(prod,Path(__file__).parent,target/'producer')
        shutil.copy2(Path(__file__).with_name('plan.py'),target/'producer/plan.py')
        verdicts,report = evaluate_second(out)
        result = score(out,p,verdicts)
        write_json(target/'proof.json',p)
        write_json(target/'verdicts_playable_rules.json',verdicts)
        write_json(target/'playable_rules.json',report)
        write_json(target/'playable_score.json',result)
        require(parent_files(out) == before and producer() == prod,'parent/producer changed during offline evaluation')
        write_json(target/'replacement.json',{'version':VERSION,'qualified':True,'parent_files':before,
            'producer':prod,'plan_archive_sha256':sha256(target/'producer/plan.py'),
            'artifacts':{n:sha256(target/n) for n in ('proof.json','verdicts_playable_rules.json','playable_rules.json','playable_score.json')},
            'native_recordings_added':0,'model_calls_added':0,'native_takes_consumed':2})
        require(qualified_replacement_score(out) == result,'offline replacement failed verification')
        return result


def qualified_replacement_score(out):
    out = Path(out).absolute()
    try:
        target = out/LINEAGE
        receipt = read_json(target/'replacement.json')
        require(receipt['version'] == VERSION and receipt['qualified'] is True
                and receipt['native_recordings_added'] == receipt['model_calls_added'] == 0
                and receipt['native_takes_consumed'] == 2,'invalid offline receipt')
        require(parent_files(out) == receipt['parent_files']
                and duration.tree(target/'parent_archive') == receipt['parent_files'],'parent/archive drift')
        require(producer() == receipt['producer'],'offline verifier producer drift')
        require(duration.tree(target/'producer') == {**receipt['producer'],'plan.py':receipt['plan_archive_sha256']},'producer archive drift')
        require(duration.plan_dependency(Path(__file__).with_name('plan.py')) ==
                duration.plan_dependency(target/'producer/plan.py'),'planner dependency drift')
        for name,h in receipt['artifacts'].items():
            require(sha256(target/name) == h,'offline artifact drift')
        p = proof(out)
        require(p == read_json(target/'proof.json'),'native/source proof drift')
        verdicts,report = evaluate_second(out)
        require(verdicts == read_json(target/'verdicts_playable_rules.json')
                and report == read_json(target/'playable_rules.json'),'rules differ')
        result = score(out,p,verdicts)
        require(result == read_json(target/'playable_score.json'),'score inconsistent with rules')
        return result
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    parser.add_argument('--recover',action='store_true')
    args = parser.parse_args()
    import json
    print(json.dumps(recover(args.out) if args.recover else qualification(args.out),indent=2))
