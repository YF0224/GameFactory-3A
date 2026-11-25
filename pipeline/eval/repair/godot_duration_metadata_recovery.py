"""Offline completion for a full duration child rejected only for import sidecars.

The original verifier failure stays intact. Author bytes must match exactly;
only script UID and texture import metadata tied to frozen files are allowed.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import godot_duration_recovery as d
from ..stage1 import playable_rules
from ..stage1.paths import read_json, write_json, sha256

VERSION = 'stage1-godot-duration-import-metadata.v1'
RELATIVE = d.LINEAGE/'metadata_finalization_v1'
require = d.require


def metadata_proof(runtime, frozen):
    files = d.tree(runtime)
    require(all(files.get(k) == h for k,h in frozen.items()), 'authored file changed or missing')
    additions = {}
    for name in sorted(files.keys()-frozen.keys()):
        if name.startswith('.godot/'):
            continue
        path = runtime/name
        if name.endswith('.gd.uid'):
            source = name[:-4]
            require(source in frozen and re.fullmatch(r'uid://[a-z0-9]+\n?',path.read_text()) is not None,
                    'UID sidecar lacks unchanged authored script or valid UID')
            additions[name] = {'sha256':files[name],'source':source,'source_sha256':frozen[source],'kind':'script_uid'}
        elif name.endswith('.import'):
            source = name[:-7]
            require(source in frozen and Path(source).suffix.lower() in {'.png','.jpg','.jpeg','.svg','.webp'},
                    'import sidecar lacks unchanged authored texture')
            text = path.read_text()
            require(re.findall(r'^source_file="([^"]+)"$',text,re.M) == ['res://'+source],
                    'import source does not match exact frozen authored input')
            require('[remap]' in text and '[deps]' in text and '[params]' in text
                    and re.findall(r'^importer="([^"]+)"$',text,re.M) == ['texture']
                    and re.findall(r'^type="([^"]+)"$',text,re.M) == ['CompressedTexture2D'],
                    'unexpected import sidecar type')
            paths = re.findall(r'"(res://[^"]+)"',text)
            for value in paths:
                if value == 'res://'+source:
                    continue
                relative = value[len('res://'):]
                require(relative.startswith('.godot/imported/') and '..' not in Path(relative).parts
                        and (runtime/relative).is_file(), 'import output escapes generated cache or is missing')
            require(len(paths) >= 3,'missing native import output references')
            additions[name] = {'sha256':files[name],'source':source,'source_sha256':frozen[source],'kind':'texture_import'}
        else:
            raise ValueError('unrecognized runtime addition: '+name)
    require(additions,'no import metadata qualification gap')
    return additions


def proof(out):
    target = out/d.LINEAGE
    saved = d._prepared(out)
    child = target/'child'
    failure = read_json(target/'failure.json')
    require(failure == {'type':'ValueError','error':'child runtime author drift',
                        'native_slot_consumed':True,'retry_allowed':False}, 'not metadata-only verifier failure')
    dispatch = read_json(target/'dispatch.json')
    require(dispatch['prepared_sha256'] == sha256(target/'prepared.json'), 'dispatch/prepared drift')
    require(d.tree(target/'production_dispatch') == dispatch['production'], 'dispatch archive drift')
    finished = read_json(target/'finished.json')
    require(finished['success'] is True and finished['production_after'] == dispatch['production'], 'runtime producer drift')
    for name in ('godot_duration_recovery.py','playable_rules.py','native_log.py','prepare.py','paths.py'):
        require(sha256(Path(__file__).with_name(name)) == dispatch['production']['pipeline/eval/stage1/'+name],
                'live verifier dependency drift')
    require(d.plan_dependency(Path(__file__).with_name('plan.py')) ==
            d.plan_dependency(target/'production_dispatch/pipeline/eval/stage1/plan.py'), 'plan dependency drift')
    live = [p for p in target.glob('**/takes/*/record') if 'parent_archive' not in p.relative_to(target).parts
            and ((p/'native').exists() or (p/'execution.json').exists())]
    require(live == [child/'takes/1/record'], 'extra native descendant; max2 exhausted')
    inventory = d.inventory(child)
    require(len(inventory) == 1 and inventory[0]['consumed'],'child count changed')
    additions = metadata_proof(child/'runtime/project',saved['source']['snapshot_files'])
    native = d.native_evidence(child,1,full_window=True)
    require(native['observation_plan'] == str(child/'takes/1/record/recording_plan.json')
            and native['plan_max_duration_ms'] == saved['accepted_plan']['max_duration_ms'], 'configuration drift')
    return {'native':native,'generated_metadata':additions,
            'retained_failure_sha256':sha256(target/'failure.json')}


def evaluate(out):
    child = out/d.LINEAGE/'child'
    with tempfile.TemporaryDirectory(prefix='godot-metadata-verify-') as temp:
        verdicts = playable_rules.evaluate(child,read_json(child/'manifest.json'),1,report_dir=Path(temp))
        return verdicts,read_json(Path(temp)/'playable_rules.json')


def bindings(out):
    target = out/d.LINEAGE
    return {'receipts':{name:sha256(target/name) for name in ('prepared.json','dispatch.json','finished.json','failure.json')},
            'child_files':d.tree(target/'child')}


def recover(out):
    out = Path(out).absolute()
    with d.locked(out),d.existing_locks(out):
        target = out/RELATIVE
        if (target/'replacement.json').exists():
            score = qualified_replacement_score(out)
            require(score is not None,'existing metadata receipt invalid')
            return score
        require(not target.exists(),'partial offline metadata finalization retained')
        p = proof(out)
        d.process_check(out)
        d.check_space(out,1024**2)
        before = bindings(out)
        target.mkdir()
        shutil.copy2(out/d.LINEAGE/'failure.json',target/'original_failure.json')
        shutil.copy2(Path(__file__),target/'producer.py.txt')
        verdicts,report = evaluate(out)
        score = d._score(out,verdicts,p['native'])
        write_json(target/'proof.json',p)
        write_json(target/'playable_score.json',score)
        write_json(target/'verdicts_playable_rules.json',verdicts)
        write_json(target/'playable_rules.json',report)
        require(bindings(out) == before,'child/receipt changed during offline finalization')
        write_json(target/'replacement.json',{'version':VERSION,'qualified':True,'bindings':before,
                    'producer_sha256':sha256(Path(__file__)),
                    'artifacts':{n:sha256(target/n) for n in ('proof.json','playable_score.json',
                         'verdicts_playable_rules.json','playable_rules.json','original_failure.json','producer.py.txt')},
                    'native_recordings_added':0,'model_calls_added':0,'native_takes_consumed':2})
        require(qualified_replacement_score(out) == score,'metadata replacement failed independent verification')
        return score


def qualified_replacement_score(out):
    out = Path(out).absolute()
    try:
        target = out/RELATIVE
        receipt = read_json(target/'replacement.json')
        require(receipt['version'] == VERSION and receipt['qualified'] is True
                and receipt['native_recordings_added'] == receipt['model_calls_added'] == 0
                and receipt['native_takes_consumed'] == 2,'invalid metadata receipt')
        require(sha256(Path(__file__)) == receipt['producer_sha256'] == sha256(target/'producer.py.txt'), 'metadata verifier drift')
        require(bindings(out) == receipt['bindings'],'native evidence/receipt drift')
        for name,h in receipt['artifacts'].items():
            require(sha256(target/name) == h,'metadata artifact drift')
        p = proof(out)
        require(p == read_json(target/'proof.json') and p['retained_failure_sha256'] == sha256(target/'original_failure.json'),
                'metadata/source/failure proof drift')
        verdicts,report = evaluate(out)
        require(verdicts == read_json(target/'verdicts_playable_rules.json') and report == read_json(target/'playable_rules.json'),
                'rules recalculation differs')
        score = d._score(out,verdicts,p['native'])
        require(score == read_json(target/'playable_score.json'),'score disagrees with unchanged rules')
        return score
    except (OSError,ValueError,TypeError,KeyError,RuntimeError):
        return None


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('out',type=Path)
    args = parser.parse_args()
    print(json.dumps(recover(args.out),indent=2))
