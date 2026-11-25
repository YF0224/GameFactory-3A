"""Resume one accepted non-scoring capacity probe after a local event-parser failure.

This never grants another scoring attempt, replaces a source authorization or
reissues the accepted probe. Every original producer byte and parent data SHA is
retained; only the still-missing paired probe and original judge may proceed.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-accepted-capacity-probe-resume.v1'
RECEIPT = 'engineering/gameness_accepted_capacity_probe_resume.json'
PRODUCERS = {'mechanic_v3_persistent_text.py','gameness_v4_persistent_text.py',
             'gameness_v4_final_literal.py','gameness_v4_persistent_capacity.py'}


def proof(root, auth_path):
    root,auth_path=Path(root).resolve(),Path(auth_path).resolve()
    value=runner.read(root/RECEIPT)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('authorization')!={'path':str(auth_path),'sha256':sha(auth_path)}
            or value.get('maximum_remaining_scoring_attempts')!=1
            or value.get('accepted_probe_must_not_repeat') is not True):
        raise ValueError('Exact bounded accepted-probe continuation required')
    auth=runner.read(auth_path);code=Path(__file__).resolve().parent
    expected={p:d for p,d in auth['bindings'].items() if Path(p).parent!=code and not Path(p).is_relative_to(code/'deliveries')}
    if value.get('unchanged_parent_data')!=expected:
        raise ValueError('Every original non-code parent binding must remain pinned')
    for name,digest in expected.items():
        if sha(Path(name))!=digest:raise ValueError('Accepted-probe parent data changed')
    for field in ['parent_failure','regression','equivalence']:
        item=value[field]
        if sha(Path(item['path']))!=item['sha256']:raise ValueError('Immutable recovery proof changed')
    failure=runner.read(Path(value['parent_failure']['path']))
    if failure.get('error')!="ValueError('Persistent turn failed')":
        raise ValueError('Only the diagnosed pre-scoring event parser failure is admitted')
    equivalence=runner.read(Path(value['equivalence']['path']))
    if any(equivalence.get(k) is not True for k in ['scoring_unchanged','all_original_bytes_and_pixels_required','compaction_still_rejected']):
        raise ValueError('Exact non-scoring transport equivalence required')
    regression=runner.read(Path(value['regression']['path']))
    if regression.get('exit_code')!=0 or regression.get('tests_passed',0)<1:
        raise ValueError('Passed targeted accepted-probe recovery regressions required')
    return value


def verify_producer(root,auth_path,producer,expected):
    producer=Path(producer).resolve();value=proof(root,auth_path)
    if producer.parent!=Path(__file__).resolve().parent or producer.name not in PRODUCERS:
        raise ValueError('Accepted-probe recovery cannot change unrelated production')
    archive=value['parent_producer_archives'].get(str(producer),{})
    if (archive.get('sha256')!=expected or sha(Path(archive['path']))!=expected
            or value['after_source_bindings'].get(str(producer))!=sha(producer)):
        raise ValueError('Exact before/after accepted-probe producer binding required')
    return value


def begin(root,auth,repair_path):
    from . import gameness_v4_persistent_capacity as capacity, gameness_v4_final_literal as final
    from . import gameness_v4_persistent_text as base, gameness_v3_runtime as runtime
    root=Path(root).resolve();auth_path=root/capacity.AUTH
    if Path(repair_path).resolve()!=(root/RECEIPT).resolve():
        raise ValueError('Accepted capacity probe must use its fixed recovery receipt')
    value=proof(root,auth_path)
    if value['after_source_bindings']!=runtime.production_bindings():
        raise ValueError('Accepted probe recovery must bind entire current production')
    call=root/'model_calls'/auth['task'];folder=call/'capacity_probe_original'
    files={str(p.resolve()) for p in folder.rglob('*') if p.is_file() and p.name!='retained_session.jsonl'}
    bindings=value['accepted_probe_bindings']
    if set(bindings)!=files or any(sha(Path(p))!=d for p,d in bindings.items()):
        raise ValueError('Every accepted probe artifact must be retained unchanged')
    if (call/'capacity_probe_encoded').exists() or (call/'persistent_turns').exists() or (call/'accepted_response.json').exists():
        raise ValueError('Only the missing paired probe and unattempted original scoring calls may continue')
    if list((root/'judgments').glob('gameness_v4_*.json')):
        raise ValueError('Accepted scoring judgments cannot use pre-scoring recovery')
    parent=Path(auth['final_literal_transport']['parent_prompt']).read_text()
    inv=runner.read(folder/'invocation.json');cmd=inv.get('command',[])
    if ((folder/'prompt.txt').read_text()!=final.probe_prompt(parent)
            or runner.read(folder/'schema.json')!=final.SCHEMA or runner.read(folder/'response.json')!=final.ACK
            or inv.get('exit_code')!=0 or inv.get('attempt')!=1
            or inv.get('model_requested')!='gpt-6.1-sol' or '--image' in cmd or 'resume' in cmd):
        raise ValueError('Exact completed same-model inert original probe required')
    sid=base.event_values(folder/'events.jsonl');source=base.session_path(sid)
    base.verify_session(source,sid,[final.probe_prompt(parent)],'gpt-6.1-sol')
    base.save(folder/'retained_session.jsonl',source.read_bytes())
    runner.exclusive_json(call/'accepted_probe_resume_claim.json',dict(version=VERSION,
        receipt=str(repair_path),receipt_sha256=sha(repair_path),accepted_probe_session=sid,
        maximum_remaining_probe_calls=1,maximum_remaining_scoring_attempts=1))
    return True


def calibrate_missing_pair(root,call,auth,encoded,model,deadline):
    import json
    from . import gameness_v4_persistent_text as base, gameness_v4_final_literal as final
    folder=call/'capacity_probe_encoded'
    value,sid=base.invoke(root,folder,final.probe_prompt(encoded),final.SCHEMA,model,deadline,
        context_tokens=auth['model_context_window'])
    if value!=final.ACK:raise ValueError('Missing capacity probe acknowledgment differs')
    base.save(folder/'retained_session.jsonl',base.session_path(sid).read_bytes())
    result=final.verify_calibration(root,call,auth,encoded,model)
    base.save(call/'final_capacity_calibration.json',(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
    return result
