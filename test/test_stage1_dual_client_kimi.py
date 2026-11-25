"""Offline qualification tests. Synthetic traces below are never native evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.dont_write_bytecode = True
FRAMEWORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FRAMEWORK))
DRAFT = FRAMEWORK/'test_data/outputs/eval/whitebox/_playable_retest/engineering/kimi_all_20261109/dual_G043_draft'
FORMAL = FRAMEWORK/'pipeline/eval/stage1'
MODULE_ROOT = FORMAL if (FORMAL/'dual_client_kimi.py').exists() else DRAFT
for leaf in ('dual_client_kimi_plan','dual_client_kimi'):
    name = 'pipeline.eval.stage1.'+leaf
    spec = importlib.util.spec_from_file_location(name, MODULE_ROOT/(leaf+'.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
m = sys.modules['pipeline.eval.stage1.dual_client_kimi']
plan_module = sys.modules['pipeline.eval.stage1.dual_client_kimi_plan']


def put(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value))


def rows(p, values):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(v)+'\n' for v in values))


def no_external(monkeypatch):
    def forbidden(*a, **kw):
        raise AssertionError('offline tests must not dispatch model/native')
    monkeypatch.setattr(m.subprocess,'Popen',forbidden)
    monkeypatch.setattr(m.subprocess,'run',forbidden)
    monkeypatch.setattr(plan_module.llm,'call_model',forbidden)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    no_external(monkeypatch)


def test_draft_cannot_execute_or_plan(tmp_path):
    if MODULE_ROOT == FORMAL:
        pytest.skip('draft-location guard only')
    with pytest.raises(m.HarnessError,match='draft'):
        m.run_playable(tmp_path,tmp_path/'out',models={'planner':'gpt-6-astra'})
    with pytest.raises(m.HarnessError,match='draft'):
        m.record_pair(tmp_path,tmp_path/'pair',profile='kimi_g043',plan={})
    with pytest.raises(m.HarnessError,match='draft'):
        plan_module.make_plan(tmp_path,tmp_path/'plan',profile='kimi_g043',model='gpt-6-astra',requirement=tmp_path/'r')
    assert not (tmp_path/'out').exists()


def test_real_frozen_source_review():
    profile = m.read_profiles(MODULE_ROOT/'dual_client_kimi_profiles.json', reader=m.read_json)['kimi_g043']
    assert m.review_target(profile['target']) == profile


@pytest.mark.parametrize('field,value', [('engine','unity3d'),('case','G038'),('required_real_clients',1),('model','Sol'),('project','/tmp/substitute')])
def test_scope_identity_never_falls_back(field,value):
    target = m.read_profiles(MODULE_ROOT/'dual_client_kimi_profiles.json', reader=m.read_json)['kimi_g043']['target'].copy()
    target[field] = value
    with pytest.raises(m.HarnessError): m.review_target(target)


def test_scope_relocation_rejected(tmp_path):
    profile = m.read_profiles(MODULE_ROOT/'dual_client_kimi_profiles.json', reader=m.read_json)['kimi_g043']
    copied = tmp_path/'targets.json'
    copied.write_bytes(Path(profile['scope_path']).read_bytes())
    with pytest.raises(m.HarnessError,match='scope'): m.review_target(profile['target'],scope_path=copied)


@pytest.fixture
def evidence(tmp_path,monkeypatch):
    """Construct a full synthetic receipt to exercise verifier branches only."""
    out = tmp_path/'out'; pair = out/'takes/take_01/pair'; project = tmp_path/'original'
    project.mkdir(); (project/'main.gd').write_text('# fixture, not author source\n')
    put(out/'input/requirement.txt',{'fixture':True})
    source = m.source_hashes(project)
    profile = {'project':str(project),'target':{'fixture':True},'reviewed_sha256':source,
               'requirement':{'sha256':m.sha256(out/'input/requirement.txt')}}
    real_read = m.read_json
    monkeypatch.setattr(m,'read_json',lambda p: {'kimi_g043':profile} if Path(p).name == 'dual_client_kimi_profiles.json' else real_read(p))
    monkeypatch.setattr(m,'review_target',lambda *a,**k: profile)
    monkeypatch.setattr(m,'profile_for',lambda *a,**k:'kimi_g043')
    session = 'synthetic-test-session'; epoch = 100000.0
    actions = [dict(role=r,key=k,duration_s=.8,wait_s=1.,purpose='synthetic') for r in m.ROLES for k in ('D','A')]
    review = dict(duration_s=75,entry_supported=True,entry_review='fixture',replication_review='fixture',product_limitations=[],source_references=[dict(path='main.gd',line=1,finding='fixture')]*3,actions=actions)
    calls = pair.parent/'model_calls/source_review'; put(calls/'response.json',review)
    put(calls/'accepted_response.json',{'path':'response.json','sha256':m.sha256(calls/'response.json')})
    producer = {}
    for name in m.PRODUCER_NAMES:
        raw = ('synthetic producer '+name).encode(); import hashlib
        digest = hashlib.sha256(raw).hexdigest()
        p = pair/'producer_blobs'/digest;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        producer['pipeline/eval/stage1/'+name] = digest
    observer_sha = producer['pipeline/eval/stage1/dual_client_kimi_observer.gd']
    plan = dict(protocol=m.VERSION,planner='gpt-6-astra',duration_s=75,required_real_clients=2,profile='kimi_g043',
                source_sha256=source,requirement_sha256=profile['requirement']['sha256'],review=review,
                observer_sha256=observer_sha,accepted_response_sha256=m.sha256(calls/'accepted_response.json'))
    put(pair/'plan.json',plan); put(pair.parent/'plan.json',plan)
    put(pair/'source_binding.json',dict(project=str(project),files=source,session=session,observer_sha256=observer_sha,module_sha256=producer['pipeline/eval/stage1/dual_client_kimi.py']))
    put(pair/'producer_start.json',producer); put(pair/'producer_end.json',producer)
    put(pair/'capture_start.json',{'session':session,'start_unix':epoch})
    launch,clean,recording,traces,inputs = {},{},{},{r:[] for r in m.ROLES},{r:[] for r in m.ROLES}
    for role,pid in [('host',444001),('client',444002)]:
        root=pair/role; runtime=pair/'projects'/role;runtime.mkdir(parents=True);(runtime/'main.gd').write_bytes((project/'main.gd').read_bytes())
        user=pair/'users'/role/'data';user.mkdir(parents=True)
        launch[role]={'pid':pid,'project':str(runtime),'command':['godot','--path',str(runtime),'-s',str(FORMAL/'dual_client_kimi_observer.gd'),'--',f'--pair-output={root}','--pair-profile=kimi_g043',f'--pair-role={role}',f'--pair-session={session}']}
        process=dict(pid=pid,role=role,project=str(runtime),origin_unix=epoch+.01,session=session,capture_epoch=epoch,user_data=str(user))
        put(root/'process.json',process);put(root/'observer_ready.json',process)
        recording[role]=dict(pid=pid,role=role,session=session,duration_ms=75020,requested_duration_ms=75000,capture_epoch=epoch)
        put(root/'recording_complete.json',recording[role])
        clean[role]=dict(pid=pid,process_cleanup=True,exit_code=0,forced=False,input_view=dict(pid=pid,role=role,session=session,input_cleanup=True,view_cleanup=True))
        put(root/'input_view_cleanup.json',clean[role]['input_view'])
        (root/'engine.log').write_text('synthetic\n');(root/'import.log').write_text('synthetic\n');put(root/'import_result.json',dict(exit_code=0,product_errors=False,timeout=False))
        frames=[]
        for i,t in enumerate(range(0,75001,500)):
            path=f'frames/{i:06}.png'; f=root/path;f.parent.mkdir(exist_ok=True);f.write_bytes(b'synthetic-not-a-native-png')
            frames.append(dict(frame_id=str(i),path=path,t_ms=t,pid=pid,session=session,unix=epoch+t/1000))
        rows(root/'frame_index.jsonl',frames)
    proofs=[]
    for i,act in enumerate(actions):
        role=act['role']; t=10000+i*10000; before={};after={}
        for r in m.ROLES:
            before[r]=dict(pid=launch[r]['pid'],role=r,peer_id=1 if r=='host' else 20,peers=[20] if r=='host' else [1],room='1234',unix=epoch+(t-100)/1000,t_ms=t-100,session=session,state={'players':{'1':{'pos':[0.,0.]},'2':{'pos':[0.,0.]}},'phase':'play','authored_role':r})
            after[r]=copy.deepcopy(before[r]);after[r].update(unix=epoch+(t+1800)/1000,t_ms=t+1800)
            after[r]['state']['players']['1' if role=='host' else '2']['pos']=[1.,0.]
            traces[r] += [before[r],after[r]]
        action=dict(action_id=f'{role}:{i+1}',action='key',t_ms=t,end_t_ms=t+800,unix=epoch+(t+800)/1000,
                    command={'id':i+1,'kind':'key','key':act['key'],'duration':.8},sent=True,ok=True,route='Input.parse_input_event',pid=launch[role]['pid'],session=session)
        inputs[role].append(action)
        proof=m.validate_interaction(before,after,role);proof['action']=action;proofs.append(proof)
    for role in m.ROLES:
        rows(pair/role/'state_trace.jsonl',traces[role]);rows(pair/role/'actions.jsonl',inputs[role])
    put(pair/'launch.json',launch)
    receipt=dict(version=m.VERSION,duration_s=75,required_real_clients=2,qualified=True,profile='kimi_g043',session=session,
                 plan_sha256=m.sha256(pair/'plan.json'),source_binding_sha256=m.sha256(pair/'source_binding.json'),cleanup=clean,
                 source_unchanged=True,runtime_authored_unchanged=True,producer_unchanged=True,recording=recording,interactions=proofs)
    def rehash():
        receipt['evidence_sha256']={str(p.relative_to(pair)):m.sha256(p) for role in m.ROLES for p in (pair/role).rglob('*') if p.is_file()}
        receipt['root_evidence_sha256']={n:m.sha256(pair/n) for n in ('launch.json','capture_start.json','producer_start.json','producer_end.json')}
        put(pair/'pair_receipt.json',receipt)
    rehash()
    return out,pair,project,receipt,rehash


def test_complete_synthetic_pair_verifies(evidence):
    _,pair,project,receipt,_ = evidence
    assert m.verify_pair(pair,project) == receipt


@pytest.mark.parametrize('kind', ['short','asynchronous','shared_user','wrong_session','forced_cleanup','missing_frames','unhashed_frame','autoplay','producer_drift','no_remote_motion','one_role','wrong_action','missing_accepted','native_input_route','foreign_pid','source_drift'])
def test_semantic_tampering_rejected_even_if_local_hashes_resealed(evidence,kind):
    _,pair,project,receipt,rehash = evidence
    def change(name,fn):
        value=m.read_json(pair/name);fn(value);put(pair/name,value)
    if kind=='short': change('host/recording_complete.json',lambda x:x.update(duration_ms=74000))
    elif kind=='asynchronous': change('client/process.json',lambda x:x.update(origin_unix=x['origin_unix']+1))
    elif kind=='shared_user': change('client/process.json',lambda x:x.update(user_data=m.read_json(pair/'host/process.json')['user_data']))
    elif kind=='wrong_session': change('client/process.json',lambda x:x.update(session='other'))
    elif kind=='forced_cleanup': receipt['cleanup']['host']['forced']=True
    elif kind=='missing_frames': rows(pair/'host/frame_index.jsonl',m._rows(pair/'host/frame_index.jsonl')[20:])
    elif kind=='unhashed_frame':
        fs=m._rows(pair/'host/frame_index.jsonl');fs[5]['path']='frames/missing.png';rows(pair/'host/frame_index.jsonl',fs)
    elif kind=='autoplay': change('launch.json',lambda x:x['host']['command'].append('--autoplay=core'))
    elif kind=='producer_drift': change('producer_end.json',lambda x:x.update(extra='changed'))
    elif kind=='no_remote_motion': receipt['interactions'][0]['after']['client']['state']['players']['1']['pos']=[0.,0.]
    elif kind=='one_role': receipt['interactions']=[p for p in receipt['interactions'] if p['actor']=='host']
    elif kind=='wrong_action': receipt['interactions'][0]['action']['command']['duration']=.2
    elif kind=='missing_accepted': (pair.parent/'model_calls/source_review/accepted_response.json').unlink()
    elif kind=='native_input_route': receipt['interactions'][0]['action']['route']='direct_rpc'
    elif kind=='foreign_pid': change('host/process.json',lambda x:x.update(pid=999))
    elif kind=='source_drift': (project/'main.gd').write_text('changed')
    rehash()
    with pytest.raises((m.HarnessError,ValueError,KeyError,TypeError,OSError)): m.verify_pair(pair,project)


def test_raw_evidence_tamper_rejected(evidence):
    _,pair,project,_,_=evidence
    (pair/'client/frames/000005.png').write_bytes(b'tampered')
    with pytest.raises(m.HarnessError,match='evidence'):m.verify_pair(pair,project)


def test_no_opposite_peer_motion_is_not_replication(evidence):
    _,_,_,receipt,_=evidence
    proof=copy.deepcopy(receipt['interactions'][0]);proof['after']['client']['peers']=[]
    with pytest.raises(ValueError):m.validate_interaction(proof['before'],proof['after'],'host')


def seal_fixture(evidence,monkeypatch):
    out,pair,project,receipt,_=evidence
    checks={k:'PASS' for k in m.playable_rules.IDS};verdicts={r:{k:{'status':'PASS'} for k in checks} for r in m.ROLES}
    monkeypatch.setattr(m,'_rules',lambda *a,**kw:(checks,verdicts))
    put(out/'manifest.json',{'delivery':{'project_root':str(project)}})
    put(out/'qualification_hold.json',{'reason':'synthetic unit test'})
    score={'complete':True,'required_real_clients':2,'version':m.VERSION,'engine':'godot','game_id':'G043_airship_kitchen','takes':['takes/take_01/pair'],'pair_evidence_receipt':'takes/take_01/pair/pair_receipt.json','pair_evidence_sha256':m.sha256(pair/'pair_receipt.json'),'checks':checks,'client_checks':verdicts,'playable':100.0}
    put(out/'playable_score.json',score)
    return out,pair,project,score


def test_cleanup_and_post_cleanup_qualification(evidence,monkeypatch):
    out,pair,project,score=seal_fixture(evidence,monkeypatch)
    def gone(pid,sig):raise ProcessLookupError()
    monkeypatch.setattr(m.os,'kill',gone)
    assert m._qualified_score(out,cleaned=False)==score
    clean=m.cleanup_projects(out,[pair])
    assert (project/'main.gd').exists()
    assert not (pair/'projects/host').exists()
    assert m.verify_pair(pair,project)['qualified']
    clean['user_paths']={}
    for role in m.ROLES:
        target=pair/'users'/role;m.shutil.rmtree(target);clean['user_paths'][str(target)]={'complete':True}
    put(out/'pair_projects_cleanup.json',clean)
    assert m._qualified_score(out,cleaned=True)==score
    put(out/'kimi_pair_completion.json',{'schema':'stage1-kimi-pair-completion.v1','score':score,'releases_hold_sha256':m.sha256(out/'qualification_hold.json'),'evidence_files':m._retained_files(out)})
    assert m.qualified_completion_score(out)==score
    assert (out/'qualification_hold.json').exists()
    (pair/'host/frames/000009.png').write_bytes(b'changed after cleanup')
    assert m.qualified_completion_score(out) is None


def test_canonical_score_alone_never_qualifies(evidence,monkeypatch):
    out,*_=seal_fixture(evidence,monkeypatch)
    assert m.qualified_completion_score(out) is None


def test_cleanup_refuses_live_pid(evidence,monkeypatch):
    out,pair,_,_=seal_fixture(evidence,monkeypatch)
    monkeypatch.setattr(m.os,'kill',lambda *a:None)
    with pytest.raises(m.HarnessError,match='PID'):m.cleanup_projects(out,[pair])
    assert (pair/'projects/host').exists()


def test_cleanup_refuses_foreign_or_symlink_project(evidence,monkeypatch,tmp_path):
    out,pair,_,_=seal_fixture(evidence,monkeypatch)
    def gone(*a):raise ProcessLookupError()
    monkeypatch.setattr(m.os,'kill',gone)
    owned=pair/'projects/host';m.shutil.rmtree(owned);foreign=tmp_path/'other';foreign.mkdir();owned.symlink_to(foreign,target_is_directory=True)
    with pytest.raises(m.HarnessError):m.cleanup_projects(out,[pair])
    assert foreign.exists()


def test_qualified_gate_never_invokes_native_on_garbage(tmp_path):
    put(tmp_path/'playable_score.json',{'complete':True,'playable':100})
    assert m.qualified_completion_score(tmp_path) is None


def test_observer_has_only_native_input_and_readonly_product_observation():
    source=(MODULE_ROOT/'dual_client_kimi_observer.gd').read_text()
    assert 'Input.parse_input_event' in source
    assert 'capture_start.json' in source and '75000' in source
    source='\n'.join(line.split('#',1)[0] for line in source.splitlines())
    for forbidden in ('.rpc(','.rpc_id(','.host_create(','.client_join(','.send_ready(','.snapshot(','.set(', 'Engine.time_scale', 'code_input.text ='):
        assert forbidden not in source
    assert 'game.get("client_snap")' in source and 'sim.get("chefs")' in source


def test_four_gap_receipts_are_static_and_two_client_only():
    for case in ('G003','G008','G014','G038'):
        r=json.loads((DRAFT/'source_gaps'/f'{case}.json').read_text())
        assert r['native_calls']==r['model_calls']==0 and r['score'] is None
        assert r['target']['required_real_clients']==2 and not r['single_client_fallback']
        for e in r['source_excerpts']:
            path=Path(e['path']); assert m.sha256(path)==e['sha256']
            lines=path.read_text().splitlines()
            assert all(lines[x['line']-1]==x['text'] for x in e['lines'])


def test_native_dispatch_requires_persisted_accepted_plan(evidence,monkeypatch):
    _,pair,project,_,_=evidence
    plan=m.read_json(pair/'plan.json')
    observer=pair/'producer_blobs'/plan['observer_sha256']
    monkeypatch.setattr(m,'OBSERVER',observer)
    m.validate_native_plan(project,pair.parent,plan)
    (pair.parent/'model_calls/source_review/response.json').write_text('{}')
    with pytest.raises((m.HarnessError,ValueError)):
        m.validate_native_plan(project,pair.parent,plan)


def test_native_dispatch_rejects_accepted_false_entry(evidence,monkeypatch):
    _,pair,project,_,_=evidence
    plan=m.read_json(pair/'plan.json')
    monkeypatch.setattr(m,'OBSERVER',pair/'producer_blobs'/plan['observer_sha256'])
    plan['review']['entry_supported']=False
    calls=pair.parent/'model_calls/source_review'
    put(calls/'response.json',plan['review'])
    put(calls/'accepted_response.json',{'path':'response.json','sha256':m.sha256(calls/'response.json')})
    plan['accepted_response_sha256']=m.sha256(calls/'accepted_response.json')
    put(pair.parent/'plan.json',plan)
    with pytest.raises(m.HarnessError,match='rejected'):
        m.validate_native_plan(project,pair.parent,plan)


def test_interrupted_pair_is_never_redispatched(tmp_path,monkeypatch):
    from pipeline.eval.stage1 import prepare
    project=tmp_path/'original';project.mkdir();(project/'a').write_text('source')
    samples=tmp_path/'samples';(samples/'G043_airship_kitchen').mkdir(parents=True)
    (samples/'G043_airship_kitchen/general_requirement.txt').write_text('requirement')
    delivery=tmp_path/'delivery';put(delivery/'delivery.json',{'game_id':'G043_airship_kitchen','project_root':str(project)})
    out=tmp_path/'out';pair=out/'takes/take_01/pair';pair.mkdir(parents=True);(pair/'claim.json').write_text('interrupted')
    monkeypatch.setattr(m,'require_official',lambda:None)
    monkeypatch.setattr(m,'profile_for',lambda *a:'kimi_g043')
    monkeypatch.setattr(prepare,'SAMPLES',samples)
    monkeypatch.setattr(m,'make_plan',lambda *a,**kw:{'fixture':'accepted'})
    monkeypatch.setattr(m,'record_pair',lambda *a,**kw:pytest.fail('must not replay existing attempt'))
    with pytest.raises(m.HarnessError,match='interrupted'):
        m._run_playable(delivery,out,models={'planner':'gpt-6-astra'})
    assert (pair/'claim.json').read_text()=='interrupted'
    assert not (out/'takes/take_02').exists()


def test_unaccepted_planner_attempt_preserved_no_new_call(tmp_path,monkeypatch):
    project=tmp_path/'project';project.mkdir();(project/'main.gd').write_text('source')
    requirement=tmp_path/'requirement';requirement.write_text('two real clients')
    take=tmp_path/'take';(take/'model_calls/source_review').mkdir(parents=True)
    failed=take/'model_calls/source_review/response.json';failed.write_text('rejected raw response')
    real_read=plan_module.read_json
    monkeypatch.setattr(plan_module,'read_json',lambda p:{'kimi_g043':{'reviewed_sha256':{'main.gd':m.sha256(project/'main.gd')}}} if Path(p).name=='dual_client_kimi_profiles.json' else real_read(p))
    monkeypatch.setattr(m,'require_official',lambda:None)
    with pytest.raises(m.HarnessError,match='unaccepted'):
        plan_module.make_plan(project,take,profile='kimi_g043',model='gpt-6-astra',requirement=requirement)
    assert failed.read_text()=='rejected raw response'


def test_pair_slot_partial_acquisition_is_released(tmp_path,monkeypatch):
    import fcntl
    monkeypatch.setattr(m.tempfile,'gettempdir',lambda:str(tmp_path))
    monkeypatch.setenv('A3GAME_GUI_SLOTS','2')
    other=tmp_path/'gamefactory-sol-whitebox-gui.slot1.lock'
    with other.open('a') as held:
        fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(m.HarnessError,match='busy'):
            with m.pair_slots(wait_s=0):pytest.fail('one busy slot must prevent both clients')
        with (tmp_path/'gamefactory-sol-whitebox-gui.lock').open('a') as probe:
            fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)


def test_frame_path_escape_is_rejected(evidence):
    _,pair,project,receipt,rehash=evidence
    f=m._rows(pair/'host/frame_index.jsonl');f[0]['path']='../../../../../outside.png';rows(pair/'host/frame_index.jsonl',f);rehash()
    with pytest.raises(m.HarnessError):m.verify_pair(pair,project)


def runner_gate():
    """Exercise the migrated production gate without the old batch CLI."""
    from pipeline.eval.stage1.playable_support import _kimi_pair_gate
    return _kimi_pair_gate


def test_runner_gate_legacy_and_explicit_hold(tmp_path, monkeypatch):
    gate = runner_gate()
    score = {'complete': True, 'required_real_clients': 2}
    monkeypatch.setattr(m, 'qualified_completion_score', lambda out: score)
    assert gate(tmp_path, {'model': 'Kimi', 'case': 'G043'}) == (True, score)
    put(tmp_path/'qualification_hold.json', {'schema': 'stage1-kimi-pair-hold.v1'})
    assert gate(tmp_path, {}) == (True, score)


@pytest.mark.parametrize('target', [{'model':'Sol'}, {'engine':'unity3d'}, {'required_real_clients':1}, {'case':'G038'}])
def test_runner_gate_marker_cannot_override_wrong_target(tmp_path, monkeypatch, target):
    put(tmp_path/'kimi_pair_completion.json', {})
    monkeypatch.setattr(m, 'qualified_completion_score', lambda out: pytest.fail('wrong identity must not reach verifier'))
    assert runner_gate()(tmp_path, target) == (True, None)


def test_runner_gate_unqualified_never_canonical_fallback(tmp_path, monkeypatch):
    put(tmp_path/'playable_score.json', {'complete':True, 'score':100})
    monkeypatch.setattr(m, 'qualified_completion_score', lambda out: None)
    assert runner_gate()(tmp_path, {'model':'Kimi','case':'G043'}) == (True, None)
    assert runner_gate()(tmp_path, {'model':'Sol','case':'G043'}) == (False, None)


def test_runner_gate_malformed_hold_fails_closed(tmp_path):
    (tmp_path/'qualification_hold.json').write_text('not JSON')
    assert runner_gate()(tmp_path, {}) == (True, None)

def keep_fixture(evidence, monkeypatch):
    out,pair,project,score = seal_fixture(evidence,monkeypatch)
    put(out/'qualification_hold.json',{'schema':'stage1-kimi-pair-hold.v1','cache_policy':'KEEP_PROJECTS'})
    def gone(*args): raise ProcessLookupError()
    monkeypatch.setattr(m.os,'kill',gone)
    return out,pair,project,score


def test_keep_wrapper_never_deletes_and_seals(evidence, monkeypatch):
    out,pair,project,score = keep_fixture(evidence,monkeypatch)
    monkeypatch.setattr(m,'require_official',lambda:None)
    monkeypatch.setattr(m,'_run_playable',lambda *a,**kw:score)
    def forbidden(*a,**kw): pytest.fail('KEEP_PROJECTS must never delete')
    monkeypatch.setattr(m,'cleanup_projects',forbidden)
    monkeypatch.setattr(m.shutil,'rmtree',forbidden)
    assert m.run_playable(out/'delivery',out,models={'planner':'gpt-6-astra'},keep_projects=True)==score
    assert m.qualified_completion_score(out)==score
    receipt=m.read_json(out/'pair_projects_cleanup.json')
    assert receipt['disposition']=='PRESERVED' and receipt['deleted_bytes']==0
    for role in m.ROLES:
        assert (pair/'projects'/role/'main.gd').read_bytes()==(project/'main.gd').read_bytes()
        assert (pair/'users'/role).is_dir()


@pytest.mark.parametrize('tamper',['author','missing_user','false_deleted','wrong_policy','native_cleanup'])
def test_keep_tamper_fails_closed(evidence,monkeypatch,tamper):
    out,pair,project,score=keep_fixture(evidence,monkeypatch)
    put(out/'pair_projects_cleanup.json',m._preserved_cache_receipt(out,[pair],check_live=True))
    if tamper=='author': (pair/'projects/host/main.gd').write_text('changed')
    elif tamper=='missing_user': (pair/'users/host').rename(pair/'users/host_gone')
    elif tamper=='false_deleted':
        clean=m.read_json(out/'pair_projects_cleanup.json');clean['deleted_bytes']=1;put(out/'pair_projects_cleanup.json',clean)
    elif tamper=='wrong_policy': put(out/'qualification_hold.json',{'cache_policy':'DELETE_QUALIFIED_COPIES'})
    else:
        clean=m.read_json(pair/'pair_receipt.json');clean['cleanup']['host']['process_cleanup']=False;put(pair/'pair_receipt.json',clean)
    put(out/'kimi_pair_completion.json',{'schema':'stage1-kimi-pair-completion.v1','score':score,'releases_hold_sha256':m.sha256(out/'qualification_hold.json'),'evidence_files':m._retained_files(out)})
    assert m.qualified_completion_score(out) is None


def test_keep_live_pid_blocks_seal(evidence,monkeypatch):
    out,pair,_,_=keep_fixture(evidence,monkeypatch)
    monkeypatch.setattr(m.os,'kill',lambda *a:None)
    with pytest.raises(m.HarnessError,match='PID'): m._preserved_cache_receipt(out,[pair],check_live=True)


def test_keep_hold_blocks_direct_cleanup(evidence,monkeypatch):
    out,pair,_,_=keep_fixture(evidence,monkeypatch)
    with pytest.raises(m.HarnessError,match='KEEP_PROJECTS'): m.cleanup_projects(out,[pair])


def test_keep_policy_switch_blocks_before_native(evidence,monkeypatch):
    out,_,_,_=keep_fixture(evidence,monkeypatch)
    monkeypatch.setattr(m,'require_official',lambda:None)
    monkeypatch.setattr(m,'_run_playable',lambda *a,**kw:pytest.fail('policy mismatch must block native'))
    with pytest.raises(m.HarnessError,match='cache policy differs'):m.run_playable(out/'delivery',out,models={},keep_projects=False)


# Epoch serialization recovery tests; all mutation uses synthetic tmp_path data.
@pytest.mark.parametrize('actual,expected,accepted', [
    (1794241992.31971,1794241992.319712,True),
    (1794241992.319712,1794241992.319712,True),
    (1794241992.319711,1794241992.319712,False),
    (1794241992.31972,1794241992.319712,False),
    (1794241992.32,1794241992.319712,False),
    (1794241993.31971,1794241992.319712,False),
    (float('nan'),float('nan'),False), (float('inf'),float('inf'),False),
    (True,1,False), ('1794241992.31971',1794241992.319712,False),
    (100000,100000.0,True),
    (17942419923.1971,17942419923.19712,False),
])
def test_epoch_decimal_identity_is_not_a_time_tolerance(actual,expected,accepted):
    assert m._same_capture_epoch(actual,expected) is accepted


def epoch_fixture(evidence):
    out,pair,project,receipt,rehash=evidence
    epoch=1794241992.319712
    barrier=m.read_json(pair/'capture_start.json');barrier['start_unix']=epoch
    put(pair/'capture_start.json',barrier)
    for role in m.ROLES:
        process=m.read_json(pair/role/'process.json')
        process.update(capture_epoch=1794241992.31971,origin_unix=1794241992.32624)
        put(pair/role/'process.json',process)
        recording=m.read_json(pair/role/'recording_complete.json')
        recording['capture_epoch']=1794241992.31971
        put(pair/role/'recording_complete.json',recording)
    rehash()
    return out,pair,project,receipt,rehash


def test_rounded_epoch_pair_passes_full_verifier(evidence):
    _,pair,project,_,_=epoch_fixture(evidence)
    assert m.verify_pair(pair,project)['qualified']


@pytest.mark.parametrize('tamper',['late_origin','early_origin','other_epoch','mismatched_serialization','short_capture','wrong_session','missing_frame'])
def test_rounded_epoch_keeps_other_guards(evidence,tamper):
    _,pair,project,_,rehash=epoch_fixture(evidence)
    path=pair/'host/process.json';native=m.read_json(path)
    if tamper=='late_origin':native['origin_unix']=1794241992.60
    elif tamper=='early_origin':native['origin_unix']=1794241992.30
    elif tamper=='other_epoch':native['capture_epoch']=1794241992.31972
    elif tamper=='mismatched_serialization':native['capture_epoch']=1794241992.319712
    elif tamper=='wrong_session':native['session']='another-room'
    elif tamper=='short_capture':
        rec=m.read_json(pair/'host/recording_complete.json');rec['duration_ms']=74000
        put(pair/'host/recording_complete.json',rec)
    else:
        frames=m._rows(pair/'host/frame_index.jsonl');frames.pop()
        rows(pair/'host/frame_index.jsonl',frames)
    put(path,native);rehash()
    with pytest.raises(m.HarnessError):m.verify_pair(pair,project)


@pytest.fixture
def recovery_fixture(evidence,monkeypatch,tmp_path):
    out,pair,project,score=keep_fixture(evidence,monkeypatch)
    (out/'playable_score.json').unlink()
    epoch_fixture(evidence)
    profile=m.read_profiles(MODULE_ROOT/'dual_client_kimi_profiles.json', reader=m.read_json)['kimi_g043']
    put(out/'qualification_hold.json',{'schema':'stage1-kimi-pair-hold.v1','cache_policy':'KEEP_PROJECTS','target':profile['target']})
    put(out/'manifest.json',{'delivery':{'project_root':str(project),'game_id':'G043_airship_kitchen'},'models':{'planner':'gpt-6-astra','judge':'none'}})
    put(out/'status.json',{'state':'HARNESS_ERROR','error':m.EPOCH_FAILURE,'complete':False})
    put(out/'_kimi_batch/failure.json',{'type':'HarnessError','error':m.EPOCH_FAILURE,'traceback':'synthetic test failure'})
    put(out/'_kimi_batch/attempt.json',{'pid':987654,'target':profile['target']})
    put(out/'_kimi_batch/blocked.json',{'synthetic':'preserve zero-call preflight blocker'})
    put(out/'_kimi_batch/pair_preflight_release.json',{'blocked_native_calls':0,'blocked_model_calls':0})
    producer=m.read_json(pair/'producer_start.json')
    bench=tmp_path/'synthetic_producer';bench.mkdir()
    for name,digest in producer.items():
        path=bench/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes((pair/'producer_blobs'/digest).read_bytes())
    key='pipeline/eval/stage1/dual_client_kimi.py'
    (bench/key).write_bytes(Path(m.__file__).read_bytes())
    current={name:m.sha256(bench/name) for name in producer}
    monkeypatch.setattr(m,'BENCH',bench)
    monkeypatch.setattr(m,'FRAMEWORK',bench)
    launch=m.read_json(pair/'launch.json')
    for row in launch.values():
        row['command'][row['command'].index('-s')+1]=str(m.FRAMEWORK/'pipeline/eval/stage1/dual_client_kimi_observer.gd')
    put(pair/'launch.json',launch)
    evidence[-1]()
    monkeypatch.setattr(m,'producer_snapshot',lambda:current)
    monkeypatch.setattr(m,'require_official',lambda:None)
    def forbidden(*a,**kw):pytest.fail('offline recovery must never plan/native/delete')
    for name in ('make_plan','record_pair','_run_playable','cleanup_projects'):
        monkeypatch.setattr(m,name,forbidden)
    monkeypatch.setattr(m.shutil,'rmtree',forbidden)
    kwargs=dict(expected_failure_sha256=m.sha256(out/'_kimi_batch/failure.json'),
                expected_pair_sha256=m.sha256(pair/'pair_receipt.json'),
                reviewed_module_sha256=m.sha256(Path(m.__file__)))
    return out,pair,project,kwargs,current


def test_offline_recovery_preserves_failed_take_and_closes_gate(recovery_fixture):
    out,pair,project,kwargs,_=recovery_fixture
    before={str(p.relative_to(out)):p.read_bytes() for p in out.rglob('*') if p.is_file()}
    score=m.recover_completed_pair(out,**kwargs)
    assert score['playable']==100 and score['complete']
    assert score['takes']==['takes/take_01/pair']
    assert m.qualified_completion_score(out)==score
    root=out/m.EPOCH_RECOVERY;receipt=m.read_json(root/'receipt.json')
    assert receipt['new_native_takes']==receipt['new_model_calls']==0
    assert receipt['consumed_native_takes']==1 and receipt['total_take_limit']==2
    for name,data in before.items():
        if name=='status.json': assert (root/'before'/name).read_bytes()==data
        else: assert (out/name).read_bytes()==data
    assert (out/'qualification_hold.json').exists()
    clean=m.read_json(out/'pair_projects_cleanup.json')
    assert clean['deleted_bytes']==0 and clean['disposition']=='PRESERVED'
    assert not (out/'takes/take_02').exists()
    assert m.recover_completed_pair(out,**kwargs)==score


@pytest.mark.parametrize('tamper',['failure_sha','pair_sha','review_sha','wrong_failure','wrong_status','take2','take3','score','policy','producer','live_pid','unoperable','held_lock','planner'])
def test_offline_recovery_preconditions_fail_closed(recovery_fixture,monkeypatch,tamper):
    out,pair,_,kwargs,current=recovery_fixture
    handle=None
    if tamper=='failure_sha':kwargs['expected_failure_sha256']='0'*64
    elif tamper=='pair_sha':kwargs['expected_pair_sha256']='0'*64
    elif tamper=='review_sha':kwargs['reviewed_module_sha256']='0'*64
    elif tamper=='wrong_failure':
        put(out/'_kimi_batch/failure.json',{'type':'HarnessError','error':'different error'})
        kwargs['expected_failure_sha256']=m.sha256(out/'_kimi_batch/failure.json')
    elif tamper=='wrong_status':put(out/'status.json',{'state':'RUNNING'})
    elif tamper=='planner':
        manifest=m.read_json(out/'manifest.json');manifest['models']['planner']='wrong-model';put(out/'manifest.json',manifest)
    elif tamper in ('take2','take3'):(out/'takes'/('take_02' if tamper=='take2' else 'take_03')).mkdir()
    elif tamper=='score':put(out/'playable_score.json',{'complete':True})
    elif tamper=='policy':put(out/'qualification_hold.json',{'schema':'stage1-kimi-pair-hold.v1','cache_policy':'DELETE_QUALIFIED_COPIES'})
    elif tamper=='producer':current['pipeline/eval/stage1/record.py']='f'*64
    elif tamper=='live_pid':monkeypatch.setattr(m.os,'kill',lambda *a:None)
    elif tamper=='unoperable':monkeypatch.setattr(m,'_rules',lambda *a,**k:({'play.operate':'UNVERIFIED'},{}))
    elif tamper=='held_lock':
        handle=(out/'.kimi_pair.lock').open('a');m.fcntl.flock(handle,m.fcntl.LOCK_EX|m.fcntl.LOCK_NB)
    try:
        with pytest.raises(m.HarnessError):m.recover_completed_pair(out,**kwargs)
        assert not (out/m.EPOCH_RECOVERY).exists()
        assert m.qualified_completion_score(out) is None
    finally:
        if handle:handle.close()


@pytest.mark.parametrize('tamper',['archive','failure','claim','hold','pair','producer_blob','budget','score','cache','partial_seal'])
def test_recovered_gate_rejects_tamper(recovery_fixture,tamper):
    out,pair,_,kwargs,_=recovery_fixture
    m.recover_completed_pair(out,**kwargs)
    root=out/m.EPOCH_RECOVERY
    if tamper=='archive':(root/'before/_kimi_batch/failure.json').write_text('{}')
    elif tamper=='failure':(out/'_kimi_batch/failure.json').write_text('{}')
    elif tamper=='claim':(out/'_kimi_batch/attempt.json').write_text('{}')
    elif tamper=='hold':(out/'qualification_hold.json').write_text('{}')
    elif tamper=='pair':(pair/'pair_receipt.json').write_text('{}')
    elif tamper=='producer_blob':next((root/'producer_blobs').iterdir()).write_text('changed')
    elif tamper=='budget':
        r=m.read_json(root/'receipt.json');r['total_take_limit']=3;put(root/'receipt.json',r)
    elif tamper=='score':(out/'playable_score.json').write_text('{}')
    elif tamper=='cache':(pair/'projects/host/main.gd').write_text('tampered author copy')
    else:(out/'kimi_pair_completion.json').unlink()
    assert m.qualified_completion_score(out) is None
    with pytest.raises((m.HarnessError,KeyError)):
        m.recover_completed_pair(out,**kwargs)


def test_interrupted_recovery_keeps_hold_and_never_replays(recovery_fixture,monkeypatch):
    out,_,_,kwargs,_=recovery_fixture
    monkeypatch.setattr(m,'_preserved_cache_receipt',lambda *a,**kw:(_ for _ in ()).throw(m.HarnessError('synthetic cache receipt failure')))
    with pytest.raises(m.HarnessError,match='synthetic cache'):m.recover_completed_pair(out,**kwargs)
    assert (out/m.EPOCH_RECOVERY/'failure.json').exists()
    assert (out/'qualification_hold.json').exists()
    assert m.qualified_completion_score(out) is None
    with pytest.raises(m.HarnessError,match='already claimed'):m.recover_completed_pair(out,**kwargs)


def test_real_finished_take_readonly_epoch_verification():
    out=FRAMEWORK/'test_data/outputs/eval/whitebox/stage1_playable_kimi_all_20261109__plan-gpt-6-astra/kimi_k3/G043_airship_kitchen/retest_dual_client_v1'
    pair=out/'takes/take_01/pair'
    if not (pair/'pair_receipt.json').exists():pytest.skip('local actual capture unavailable')
    before={str(p):m.sha256(p) for p in [out/'status.json',out/'_kimi_batch/failure.json',pair/'pair_receipt.json']}
    assert m.verify_pair(pair,Path(m.read_json(pair/'source_binding.json')['project']))['qualified']
    for role in m.ROLES:
        assert len(m._rows(pair/role/'frame_index.jsonl'))==297
    assert {n:m.sha256(Path(n)) for n in before}==before


@pytest.mark.parametrize('tamper',['claim_budget','receipt_budget','claim_parent','producer'])
def test_recovery_semantics_reject_locally_resealed_lineage(recovery_fixture,tamper):
    out,_,_,kwargs,_=recovery_fixture
    m.recover_completed_pair(out,**kwargs)
    root=out/m.EPOCH_RECOVERY
    if tamper in ('claim_budget','claim_parent'):
        path=root/'claim.json';value=m.read_json(path)
        value['total_take_limit' if tamper=='claim_budget' else 'parent_pair_sha256']=3 if tamper=='claim_budget' else '0'*64
    else:
        path=root/'receipt.json';value=m.read_json(path)
        if tamper=='receipt_budget':value['total_take_limit']=3
        else:value['producer']['pipeline/eval/stage1/record.py']='0'*64
    put(path,value)
    seal=m.read_json(out/'kimi_pair_completion.json');seal['evidence_files']=m._retained_files(out)
    put(out/'kimi_pair_completion.json',seal)
    assert m.qualified_completion_score(out) is None
