"""Contract regression only; synthetic fixtures do NOT constitute native acceptance."""
import copy
import json
from pathlib import Path
from contextlib import contextmanager

import pytest
from pipeline.eval.stage1 import dual_client_unity as u


def plan():
    return {'summary': 'source-reviewed route', 'steps': [
        {'client_role': r, 'key': k, 'duration_ms': 1000, 'purpose': 'probe'}
        for r,k in [('BOTH','enter'),('BOTH',''),('A','d'),('B','e')]]}


def write_rows(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(''.join(json.dumps(x)+'\n' for x in rows))


def synthetic_pair(folder):
    session='regression-only'
    u.write_json(folder/'session.json', {'model':'Sol','session':session,'port':49991})
    events=[{'type':'input_accepted','role':r,'detail':'ready#1','source_event_id':i,
             'state_seq':i,'host_ms':42,'simulated_sec':0} for i,r in enumerate(('A','B'),1)]
    for i,role in enumerate(u.ROLES,100):
        native=folder/'sessions'/role
        state={'session':session,'players':[{'role':r,'connected':True,'inputSeq':1,'x':1} for r in ('A','B')]}
        rows=[]
        for seq in range(3):
            rows.append({'schema':'stage1-unity-pair-observation.v1','model':'Sol','role':role,
                'actual_role':role,'session':session,'pid':i,'is_host':role=='HOST','test_mode':False,
                'ignore_focus':False,'error':'','connected':True,'unix_ms':seq*1000,
                'state_json':json.dumps(dict(state,stateSeq=seq))})
        write_rows(native/'observations.jsonl',rows)
        write_rows(native/'author_evidence'/('host_events.jsonl' if role=='HOST' else f'client_{role}.jsonl'),events)
        args=u.arguments('Sol',role,49991,session,native,folder/'STOP_OWNED_PAIR')
        owner={'pid':i,'project':str(folder/('project_'+role)),'args':args,
               'command':['editor','-projectPath',str(folder/('project_'+role)),*args]}
        u.write_json(native/'owned_process.json' if role=='HOST' else folder/'workers'/role/'owned_editor.json',owner)
    return session


def test_action_budget_and_independent_routing():
    from pipeline.eval.stage1.multiclient import split_actions
    from engine_adapters.unity3d.playtest.client import UnityPlaytestClient
    actions=u.actions_for(plan())
    assert sum(a['duration_ms'] for a in actions)==75000
    for role in ('A','B'):
        routed=split_actions(actions,role)
        assert sum(a['duration_ms'] for a in routed)==75000
        assert UnityPlaytestClient._load_actions(None,None,routed)[1] is None
    bad=plan();bad['steps']*=20
    with pytest.raises(ValueError):u.actions_for(bad)
    bad=plan()
    for s in bad['steps']:s['client_role']='A'
    with pytest.raises(ValueError):u.actions_for(bad)


@pytest.mark.parametrize('key',['f12','mouse_move','d+f','ctrl'])
def test_unreviewed_input_rejected(key):
    bad=plan();bad['steps'][0]['key']=key
    with pytest.raises(ValueError):u.actions_for(bad)


def test_editor_uses_shared_policy_and_reports_gap(monkeypatch,tmp_path):
    binary=tmp_path/'Unity';binary.write_bytes(b'not an editor')
    selected={'editor':{'binary':str(binary),'family':'unity','version':'2022.3.62f3c1'},
              'delivery':{'project_version':'2022.3.62f3'},'rule':'same_minor_closest','version_gap':True}
    monkeypatch.setattr(u.unity_editor,'choose',lambda p:copy.deepcopy(selected))
    result=u.select_editor(tmp_path)
    assert result['version_gap'] is True
    assert result['requested_version']=='2022.3.62f3'
    assert result['actual_version']=='2022.3.62f3c1'


def test_network_fixture_checks_transfer_not_windows(tmp_path):
    session=synthetic_pair(tmp_path)
    result=u.qualify_network(tmp_path,'Sol',session)
    assert len(set(result['native_pids'].values()))==3
    assert set(result['host_accepted_input_received'])=={'A','B'}
    (tmp_path/'sessions/B/author_evidence/client_B.jsonl').write_text('')
    with pytest.raises(u.llm.HarnessError,match='host-accepted'):
        u.qualify_network(tmp_path,'Sol',session)


@pytest.mark.parametrize('mutation',['pid','role','port','state','session'])
def test_network_mismatch_rejected(tmp_path,mutation):
    session=synthetic_pair(tmp_path)
    path=tmp_path/'sessions/B/observations.jsonl'
    rows=[json.loads(l) for l in path.read_text().splitlines()]
    if mutation=='pid':
        for r in rows:r['pid']=101
        owner=tmp_path/'workers/B/owned_editor.json';v=u.read_json(owner);v['pid']=101;u.write_json(owner,v)
    if mutation=='role':
        for r in rows:r['actual_role']='A'
    if mutation=='state':
        for r in rows:
            v=json.loads(r['state_json']);v['players'][0]['connected']=False;r['state_json']=json.dumps(v)
    if mutation=='session':
        for r in rows:r['session']='foreign'
    if mutation=='port':
        owner=tmp_path/'workers/B/owned_editor.json';v=u.read_json(owner);v['args'][v['args'].index('--ww-port')+1]='49992';u.write_json(owner,v)
    write_rows(path,rows)
    with pytest.raises(u.llm.HarnessError):u.qualify_network(tmp_path,'Sol',session)


def test_blocked_lock_does_not_consume_take(monkeypatch,tmp_path):
    @contextmanager
    def occupied():
        raise u.llm.HarnessError('BLOCKED_LOCK')
        yield
    monkeypatch.setattr(u,'native_locks',occupied)
    take=tmp_path/'take'
    with pytest.raises(u.llm.HarnessError,match='BLOCKED_LOCK'):
        u.record_pair(tmp_path/'original',take,model='Sol',profile={},plan=plan(),editor={},production={},hashes={})
    assert not take.exists()


def test_reject_flag_only_receipt(tmp_path):
    path=tmp_path/'pair_receipt.json'
    u.write_json(path,{'qualified':True,'required_real_clients':2,'evidence_sha256':{},'network':{'session':'fake'}})
    with pytest.raises((KeyError,FileNotFoundError,u.llm.HarnessError)):
        u.verify_receipt(tmp_path,{'pair_evidence_receipt':path.name,'pair_evidence_sha256':u.sha256(path)})


def test_receipt_hash_tamper_rejected(tmp_path):
    path=tmp_path/'pair_receipt.json';path.write_text('{}')
    score={'pair_evidence_receipt':path.name,'pair_evidence_sha256':u.sha256(path)}
    path.write_text('{"qualified":true}')
    with pytest.raises(u.llm.HarnessError,match='receipt changed'):u.verify_receipt(tmp_path,score)


def test_original_profile_bindings_are_current():
    for model,profile in u.read_json(u.PROFILES).items():
        for name,digest in profile['reviewed_sha256'].items():
            assert u.sha256(Path(profile['project'])/name)==digest


def recovery_fixture(tmp_path):
    parent=tmp_path/'takes/1';original=tmp_path/'original'
    original.mkdir(); parent.mkdir(parents=True)
    hashes={'Assets/authored.cs':'unused'}
    f=parent/'project_HOST/Assets/authored.cs';f.parent.mkdir(parents=True);f.write_text('original')
    hashes['Assets/authored.cs']=u.sha256(f)
    observer=parent/'project_HOST/Assets/Stage1DualUnityObserver/Editor/Stage1DualUnityObserver.cs'
    observer.parent.mkdir(parents=True);observer.write_bytes(u.OBSERVER.read_bytes())
    editor={'binary':'native-editor','binary_sha256':'editor-sha','requested_version':'v','actual_version':'v','version_gap':False}
    u.write_json(parent/'cleanup.json',{'ok':True,'source_unchanged':True,'owned_processes':{'import_HOST':{'ok':True},'import_A':{'ok':True}}})
    u.write_json(parent/'source_snapshot.json',{'source':str(original),'files_sha256':hashes})
    u.write_json(parent/'imports/HOST/import_result.json',{'exit_code':0,'timeout':False,'editor':editor})
    u.write_json(parent/'production.json',{'files':{u.recovery.INPUT:'old'}})
    (parent/'imports/A').mkdir();(parent/'imports/A/import.log').write_text('interrupted')
    args=dict(project=original,hashes=hashes,editor=editor,production={'files':{u.recovery.INPUT:'new'}},observer=u.OBSERVER)
    return parent,args


def test_recovery_preserves_interrupted_client_and_binds_parent(tmp_path):
    parent,args=recovery_fixture(tmp_path)
    binding=u.recovery.prepare(parent,**args)
    child=parent/u.recovery.RECOVERY
    u.write_json(child/'import_recovery.json',binding)
    assert u.recovery.verify(child)==parent/'project_HOST'
    assert (parent/'imports/A/import.log').read_text()=='interrupted'
    (parent/'imports/A/import.log').write_text('tampered')
    with pytest.raises(u.llm.HarnessError,match='evidence changed'):u.recovery.verify(child)


@pytest.mark.parametrize('invalid',['cleanup','gameplay','source','editor','observer','same_producer','repeat'])
def test_recovery_admission_rejects_unsafe_reuse(tmp_path,invalid):
    parent,args=recovery_fixture(tmp_path)
    if invalid=='cleanup':u.write_json(parent/'cleanup.json',{'ok':False,'source_unchanged':True})
    if invalid=='gameplay':u.write_json(parent/'request_A.json',{})
    if invalid=='source':(parent/'project_HOST/Assets/authored.cs').write_text('changed')
    if invalid=='editor':args['editor']['binary_sha256']='changed'
    if invalid=='observer':(parent/'project_HOST/Assets/Stage1DualUnityObserver/Editor/Stage1DualUnityObserver.cs').write_text('changed')
    if invalid=='same_producer':args['production']['files'][u.recovery.INPUT]='old'
    if invalid=='repeat':(parent/u.recovery.RECOVERY).mkdir()
    with pytest.raises(u.llm.HarnessError):u.recovery.prepare(parent,**args)


@pytest.mark.parametrize('first_qualified,operate,second_qualified,expected_takes',[
    (True,'UNVERIFIED',True,2),(False,'PASS',True,2),(True,'PASS',True,1),(False,'PASS',False,2)])
def test_bounded_take_selection_contract(monkeypatch,tmp_path,first_qualified,operate,second_qualified,expected_takes):
    # Control-flow fixture only. Native qualification is separately tested above.
    source=tmp_path/'original';source.mkdir()
    output=tmp_path/'retest_dual_client_v1'
    targets=tmp_path/'targets.json'
    u.write_json(targets, {'targets': [{'game_id': 'G014'}]})
    monkeypatch.setattr(u,'TARGETS',targets)
    monkeypatch.setattr(u,'profile_for',lambda p:({'game_id':'G014'},source,{'model':'Sol'},{}))
    monkeypatch.setattr(u,'source_hashes',lambda p:{})
    monkeypatch.setattr(u,'select_editor',lambda p:{})
    monkeypatch.setattr(u,'production_binding',lambda:{})
    monkeypatch.setattr(u,'make_plan',lambda *a,**kw:plan())
    monkeypatch.setattr(u,'verify_receipt',lambda *a,**kw:{})
    calls=[]
    def record(project,folder,**kw):
        calls.append(folder)
        u.write_json(folder/'pair_receipt.json',{'qualified':first_qualified if len(calls)==1 else second_qualified,'error':None})
    monkeypatch.setattr(u,'record_pair',record)
    monkeypatch.setattr(u,'_checks',lambda folder,take:({'play.import':'PASS','play.launch':'PASS',
                    'play.operate':operate if take==1 else 'PASS'},{}))
    if not first_qualified and not second_qualified:
        with pytest.raises(u.llm.HarnessError,match='No qualified'):u.run_playable(tmp_path,output)
        assert not (output/'playable_score.json').exists()
    else:
        result=u.run_playable(tmp_path,output)
        assert result['required_real_clients']==2 and result['pair_evidence_sha256']
        assert not Path(result['pair_evidence_receipt']).is_absolute()
    assert len(calls)==expected_takes


def test_astra_requires_nonidle_host_input_and_exact_event_transfer(tmp_path):
    session=synthetic_pair(tmp_path)
    u.write_json(tmp_path/'session.json',{'model':'Astra','session':session,'port':49991})
    events=[{'key':'input_accepted','owner':r,'input_seq':i,'state_seq':10+i,'host_ms':123}
            for i,r in enumerate(('A','B'),1)]
    for role in u.ROLES:
        native=tmp_path/'sessions'/role
        observations=[json.loads(l) for l in (native/'observations.jsonl').read_text().splitlines()]
        states=[]
        for i,row in enumerate(observations):
            state={'connectedA':True,'connectedB':True,'role':role,'state_seq':i}
            row.update(model='Astra',state_json=json.dumps(state));states.append(state)
        write_rows(native/'observations.jsonl',observations)
        write_rows(native/'author_evidence/events.jsonl',events)
        if role=='HOST':
            write_rows(native/'author_evidence/states.jsonl',states)
            write_rows(native/'author_evidence/inputs.jsonl',[{'role':r,'seq':i,'command':'ready'}
                       for i,r in enumerate(('A','B'),1)])
        owner_path=native/'owned_process.json' if role=='HOST' else tmp_path/'workers'/role/'owned_editor.json'
        owner=u.read_json(owner_path)
        args=u.arguments('Astra',role,49991,session,native,tmp_path/'STOP_OWNED_PAIR')
        owner.update(args=args,command=['editor','-projectPath',str(tmp_path/('project_'+role)),*args])
        u.write_json(owner_path,owner)
    assert u.qualify_network(tmp_path,'Astra',session)['native_pids']['A']!=u.qualify_network(tmp_path,'Astra',session)['native_pids']['B']
    write_rows(tmp_path/'sessions/HOST/author_evidence/inputs.jsonl',[{'role':'A','seq':1,'command':'ready'},{'role':'B','seq':2,'move':0}])
    with pytest.raises(u.llm.HarnessError,match='host-accepted'):u.qualify_network(tmp_path,'Astra',session)


@pytest.mark.parametrize('exit_code', [0, 1, None])
def test_owned_observation_exit_race_keeps_live_identity_guard(exit_code):
    from types import SimpleNamespace
    def race(proc, observed):
        raise ValueError('Owned worker PID identity changed')
    ownership = SimpleNamespace(observe_owned_group=race)
    proc = SimpleNamespace(poll=lambda: exit_code)
    if exit_code is None:
        with pytest.raises(ValueError, match='identity changed'):
            u.observe_owned(ownership, proc, {})
    else:
        u.observe_owned(ownership, proc, {})


def exit_race_fixture(tmp_path):
    parent, args = recovery_fixture(tmp_path)
    (parent/'imports/HOST/import_result.json').unlink()
    u.write_json(parent/'session.json', {'editor': args['editor']})
    u.write_json(parent/'cleanup.json', {'ok': True, 'source_unchanged': True,
        'owned_processes': {'import_HOST': {'ok': True}},
        'error': {'type': 'ValueError', 'error': 'Owned worker PID identity changed'}})
    u.write_json(parent/'cleanup_import_HOST.json', {'ok': True, 'exit_code': 0, 'remaining': []})
    (parent/'imports/HOST/import.log').write_text('Exiting batchmode successfully now!\n')
    u.write_json(parent/'production.json', {'files': {u.recovery.INPUT: 'same', u.recovery.BACKEND: 'old'}})
    args['production'] = {'files': {u.recovery.INPUT: 'same', u.recovery.BACKEND: 'fixed'}}
    return parent, args


def test_exit_race_recovery_preserves_missing_result_and_binds_exit_evidence(tmp_path):
    parent, args = exit_race_fixture(tmp_path)
    binding = u.recovery.prepare(parent, **args)
    assert binding['recovered_import_result']['exit_code'] == 0
    assert binding['recovered_import_result']['parent_import_result_missing'] is True
    assert not (parent/'imports/HOST/import_result.json').exists()
    assert 'cleanup_import_HOST.json' in binding['parent_evidence_sha256']
    assert binding['prior_backend_sha256'] != binding['backend_sha256']


@pytest.mark.parametrize('bad', ['exit', 'remaining', 'log', 'failure', 'producer'])
def test_exit_race_recovery_rejects_unproven_import(tmp_path, bad):
    parent, args = exit_race_fixture(tmp_path)
    if bad == 'exit':
        u.write_json(parent/'cleanup_import_HOST.json', {'ok': True, 'exit_code': 1, 'remaining': []})
    if bad == 'remaining':
        u.write_json(parent/'cleanup_import_HOST.json', {'ok': True, 'exit_code': 0, 'remaining': [123]})
    if bad == 'log':
        (parent/'imports/HOST/import.log').write_text('failed')
    if bad == 'failure':
        u.write_json(parent/'cleanup.json', {'ok': True, 'source_unchanged': True})
    if bad == 'producer':
        args['production']['files'][u.recovery.BACKEND] = 'old'
    with pytest.raises(u.llm.HarnessError):
        u.recovery.prepare(parent, **args)


def test_import_metadata_allows_only_editor_stamp_and_registry_mirror(tmp_path):
    original, host = tmp_path/'original', tmp_path/'host'
    editor = {'requested_version': '2022.3.62f3', 'actual_version': '2022.3.62f3c1'}
    for root, version in [(original, editor['requested_version']), (host, editor['actual_version'])]:
        p = root/'ProjectSettings/ProjectVersion.txt';p.parent.mkdir(parents=True)
        p.write_text(f'm_EditorVersion: {version}\nm_EditorVersionWithRevision: {version} (abc123)\n')
    assert u.recovery.imported_metadata_equivalent(original, host, 'ProjectSettings/ProjectVersion.txt', editor)
    for root, domain in [(original, 'com'), (host, 'cn')]:
        u.write_json(root/'Packages/packages-lock.json', {'dependencies': {'package': {
            'url': 'https://packages.unity.' + domain, 'version': '1.0'}}})
    assert u.recovery.imported_metadata_equivalent(original, host, 'Packages/packages-lock.json', editor)
    u.write_json(host/'Packages/packages-lock.json', {'dependencies': {'package': {
        'url': 'https://packages.unity.cn', 'version': '2.0'}}})
    assert not u.recovery.imported_metadata_equivalent(original, host, 'Packages/packages-lock.json', editor)
