"""Scope-bound Godot duration recovery: authoritative targets + runner.result_dir.

Dual-client targets never admit their historical single-client retest directory.
Each native recovery still consumes the one remaining slot under frozen helper.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from . import godot_duration_recovery as d
from . import godot_duration_metadata_recovery as metadata
from . import godot_existing_window_recovery as existing
from ..stage1.paths import read_json,write_json,sha256

BENCH = d.ROOT.parent
RUNNER = BENCH/'pipeline/eval/stage1/playable_support.py'
from pipeline.eval.stage1.paths import DATA_ROOT
TARGETS = DATA_ROOT / 'outputs/eval/whitebox/_playable_retest/targets.json'
VERSION = 'stage1-godot-duration-target-admission.v1'


def runner():
    sys.path.insert(0,str(RUNNER.parent))
    spec = importlib.util.spec_from_file_location('pipeline.eval.stage1.playable_support',RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def qualification(root,target,route):
    out = route(Path(root).absolute(),target)
    row = {'target':target,'out':str(out),'eligible':False,'window_qualified':False}
    if target['engine'] != 'godot':
        return {**row,'disposition':'NOT_GODOT'}
    if target.get('required_real_clients',1) != 1:
        return {**row,'disposition':'EXCLUDED_DUAL_CLIENT_TARGET','reason':'pair target; historical single-client retest is not completion evidence'}
    try:
        d.require(out.name == 'retest','unexpected single-client route')
        if (out/'manifest.json').exists():
            m = read_json(out/'manifest.json')
            d.require(m['engine'] == target['engine'] and m['game_id'] == target['game_id']
                      and m['delivery']['model'].lower() == target['model'].lower()
                      and Path(m['project_source']).resolve() == Path(target['project']).resolve(),
                      'manifest does not match authoritative target source/identity')
        for module,relative in ((existing,existing.LINEAGE),(metadata,metadata.RELATIVE),(d,d.LINEAGE)):
            if (out/relative/'replacement.json').exists():
                score = module.qualified_replacement_score(out)
                d.require(score is not None,'existing replacement failed independent verification')
                return {**row,'disposition':'KEEP_VERIFIED_REPLACEMENT','window_qualified':True,'score':score}
        return {**d.qualification(out),'target':target}
    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        return {**row,'disposition':'BLOCKED_TARGET_BINDING','reason':str(exc)}


def run(root,receipt_dir,*,execute=False):
    root,receipt_dir = Path(root).absolute(),Path(receipt_dir).absolute()
    routing = runner()
    targets_bytes = TARGETS.read_bytes()
    targets_sha = sha256(TARGETS)
    data = json.loads(targets_bytes)
    d.require(len(data['targets']) == 173,'authoritative target denominator changed')
    receipt_dir.mkdir(parents=True,exist_ok=False)
    (receipt_dir/'targets.json').write_bytes(targets_bytes)
    (receipt_dir/'runner.py.txt').write_bytes(RUNNER.read_bytes())
    (receipt_dir/'batch.py.txt').write_bytes(Path(__file__).read_bytes())
    write_json(receipt_dir/'scope_binding.json',{'version':VERSION,'targets_path':str(TARGETS),
               'targets_sha256':targets_sha,'runner_sha256':sha256(RUNNER),'batch_sha256':sha256(Path(__file__)),
               'required_real_clients':1,'routing':'official runner.result_dir','execute':execute})
    results=[]
    for target in data['targets']:
        if target['engine'] != 'godot':
            continue
        d.require(sha256(TARGETS) == targets_sha,'targets changed; stop before next native')
        q=qualification(root,target,routing.result_dir)
        if execute and q['eligible']:
            identity=target['model']+'__'+target['case']
            out=Path(q['out'])
            write_json(receipt_dir/(identity+'__preflight.json'),q)
            d.require(sha256(TARGETS) == targets_sha,'targets changed before dispatch')
            print('DISPATCH',identity,flush=True)
            with (receipt_dir/(identity+'__execute.log')).open('x') as log:
                result=subprocess.run([sys.executable,'-m','pipeline.eval.repair.godot_duration_recovery',str(out),'--execute'],
                                      stdout=log,stderr=subprocess.STDOUT)
            score=d.qualified_replacement_score(out)
            offline_error=None
            if score is None and (out/d.LINEAGE/'failure.json').exists():
                failure=read_json(out/d.LINEAGE/'failure.json')
                if failure.get('error') == 'child runtime author drift':
                    try:score=metadata.recover(out)
                    except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:offline_error=str(exc)
            q={**q,'eligible':False,'exit_code':result.returncode,'score':score,'offline_error':offline_error,
               'window_qualified':score is not None,'disposition':'RECOVERED_VERIFIED' if score else 'RECOVERY_BLOCKED_NO_RETRY'}
            print('FINISHED',identity,q['disposition'],score['checks'] if score else offline_error,flush=True)
        results.append(q)
        write_json(receipt_dir/'results.json',results)
    return results


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('receipt_dir',type=Path)
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    rows=run(args.root,args.receipt_dir,execute=args.execute)
    counts={}
    for row in rows:counts[row['disposition']]=counts.get(row['disposition'],0)+1
    print(json.dumps(counts,indent=2))
