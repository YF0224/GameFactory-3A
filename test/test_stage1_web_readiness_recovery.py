"""Recovery refuses preexisting native work and unverifiable readiness evidence."""
import json
from pathlib import Path
import pytest
from pipeline.eval.repair import web_readiness_recovery as r


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def parent(tmp_path):
    out=tmp_path/'out'; source=tmp_path/'source'
    put(source/'package.json', {'scripts':{'dev':'vite'}, 'dependencies':{'three':'0.185.0'},'devDependencies':{'vite':'5.4.10'}})
    put(out/'manifest.json', {'delivery':{'model':'glm'},'game_id':'G012_gravity_mine',
        'engine':'three_js','models':{'planner':'gpt-6-astra','judge':'none'},
        'project_source':str(source),'project_digest':r.prepare.tree_digest(r.prepare.tree_hashes(source))})
    put(out/'status.json', {'state':'HARNESS_ERROR','step':'record_t1'})
    rec=out/'takes/1/record'
    put(rec/'adapter_result.json', {'ok':False,'payload':{'url':'','report_path':None},
        'errors':['cannot serve the project for recording: RuntimeError: dev server did not answer on http://127.0.0.1:54321 within 45s']})
    put(rec/'launch_selection.json', {'url':'http://127.0.0.1:54321','mode':'script','script':'dev'})
    put(out/'model_calls/plan_t1/response.json', {'summary':'accepted first plan'})
    response=out/'model_calls/plan_t1/response.json'
    put(response.parent/'accepted_response.json',{'path':'response.json','sha256':r.sha256(response)})
    (out/'takes/1/plan.json').write_bytes(response.read_bytes())
    return out


def test_exact_failed_parent_accepts_original_plan(parent):
    m,p=r.failed_parent(parent)
    assert m['game_id']=='G012_gravity_mine'
    assert p['plan_sha256']==r.sha256(parent/'takes/1/plan.json')


@pytest.mark.parametrize('path', ['playable_score.json','takes/1/record/record_result.json','takes/1/record/native/one-frame.png'])
def test_existing_success_or_any_native_file_refused(parent,path):
    put(parent/path,{})
    with pytest.raises(ValueError): r.failed_parent(parent)


@pytest.mark.parametrize('change', ['source','plan','timeout','second_take','identity'])
def test_wrong_parent_cannot_enter_recovery(parent,change):
    if change=='source':
        Path(json.loads((parent/'manifest.json').read_text())['project_source']).joinpath('extra.js').write_text('changed')
    elif change=='plan': put(parent/'takes/1/plan.json',{'summary':'replacement'})
    elif change=='timeout':
        p=parent/'takes/1/record/adapter_result.json';v=json.loads(p.read_text());v['errors']=['timeout'];put(p,v)
    elif change=='second_take': (parent/'takes/2').mkdir()
    else:
        p=parent/'manifest.json';v=json.loads(p.read_text());v['game_id']='G999';put(p,v)
    with pytest.raises(ValueError):r.failed_parent(parent)


@pytest.fixture
def captured(tmp_path):
    child=tmp_path/'child';rec=child/'takes/1/record';n=rec/'native/gameplay'
    put(child/'manifest.json',{'delivery':{'model':'glm'}})
    put(rec/'record_result.json',{'frames':100})
    put(rec/'adapter_result.json',{'ok':True})
    put(rec/'launch_selection.json',{'mode':'script','script':'dev','url':'http://127.0.0.1:54321'})
    put(n/'recording_progress.json',{'status':'completed','requested_seconds':75,'frames':100,'channels_written':{'actions':16}})
    put(n/'report.json',{'sampling_complete':True,'wallclock_seconds':75.01,'capture_deadline_ms':75000})
    put(n/'input_view_cleanup.json',{'input_cleanup':True,'held_keys_after_release':0,'held_buttons_after_release':0})
    put(n/'browser_cleanup.json',{'input_cleanup':True,'view_cleanup':True,'browser_cleanup':True})
    put(n/'host_process_cleanup.json',{'process_cleanup':True,'server_group_alive':False,'recorder':{'process_cleanup':True,'group_alive':False}})
    put(rec/'server_readiness.json',{'schema':'three-server-readiness.v1','state':'ready','transport':'direct_loopback_http.v1',
        'url':'http://127.0.0.1:54321','server_pid':123,'server_returncode':None,'attempts':[{'ready':True,'status':200,
        'url':'http://127.0.0.1:54321','transport':'direct_loopback_http.v1'}]})
    return child


def test_qualified_record_needs_real_duration_and_http(captured):
    assert r.qualified_record(captured,1)['actions']==16
    p=captured/'takes/1/record/native/gameplay/report.json';v=json.loads(p.read_text());v['wallclock_seconds']=2;put(p,v)
    with pytest.raises(ValueError,match='75s'):r.qualified_record(captured,1)


@pytest.mark.parametrize('change',['status','url','pid','returncode','transport','missing'])
def test_readiness_flags_do_not_qualify(captured,change):
    p=captured/'takes/1/record/server_readiness.json';v=json.loads(p.read_text())
    if change=='status':v['attempts'][-1]['status']=404
    elif change=='url':v['attempts'][-1]['url']='http://127.0.0.1:1'
    elif change=='pid':v['server_pid']=0
    elif change=='returncode':v['server_returncode']=1
    elif change=='transport':v['transport']='urllib-global'
    if change=='missing':p.unlink()
    else:put(p,v)
    with pytest.raises((ValueError,FileNotFoundError)):r.qualified_record(captured,1)


def test_flag_only_replacement_rejected(tmp_path):
    put(tmp_path/r.LINEAGE/'replacement.json',{'qualified':True,'complete':True})
    assert r.qualified_replacement_score(tmp_path) is None


def test_boundary_retains_both_versions_without_rebinding(tmp_path,monkeypatch):
    root=tmp_path/'production';root.mkdir();p=root/'a.py';p.write_text('original')
    monkeypatch.setattr(r,'ROOT',root);monkeypatch.setattr(r,'production',lambda:{'a.py':r.sha256(p)})
    initial=r.production();before=dict(initial)
    one=r.production_boundary(tmp_path/'lineage','start',initial)
    p.write_text('concurrent change')
    two=r.production_boundary(tmp_path/'lineage','end',initial)
    assert not one['disk_drift'] and two['disk_drift']['a.py']['initial']==initial['a.py']
    assert initial==before
    assert sorted(x.read_text() for x in (tmp_path/'lineage/production_boundaries').glob('*/sources/a.py'))==['concurrent change','original']


@pytest.fixture
def shared_case(tmp_path,monkeypatch):
    from engine_adapters.three_js.playtest import dependencies, launch
    from engine_adapters.three_js.config import ThreeClientConfig
    from engine_adapters.three_js._internal.transport import node
    child=tmp_path/'child';lineage=tmp_path/'lineage';root=tmp_path/'shared';producer=tmp_path/'producer'
    project=child/'runtime/project'
    put(project/'package.json',{'scripts':{'dev':'vite','build':'vite build'}})
    put(child/'manifest.json',{'game_id':'G057_rhythm_machine_hall','delivery':{'model':'glm'}})
    put(root/'package.json',{'private':True});put(root/'package-lock.json',{'lockfileVersion':3})
    put(root/'node_modules/vite/package.json',{'version':'6.2.6'})
    put(root/'node_modules/three/package.json',{'version':'0.185.0'})
    cli=root/'node_modules/vite/bin/vite.js';cli.parent.mkdir();cli.write_text('qualified cli')
    files={str(p):r.sha256(p) for p in root.rglob('*') if p.is_file()}
    proof=producer/'workspaces/whitebox_eval_mechanic_basic_path_v3/engineering/glm057_launch_diagnosis_20261104_180707/qualified_toolchain.json'
    put(proof,{'shared_environment':str(root),'files':files})
    monkeypatch.setattr(r,'SHARED',root);monkeypatch.setattr(r,'ROOT',producer)
    monkeypatch.setattr(ThreeClientConfig,'resolve',lambda **kw:None)
    monkeypatch.setattr(node,'NodeToolchain',lambda c:None)
    monkeypatch.setattr(dependencies,'verify_critical_packages',lambda *a:[])
    monkeypatch.setattr(dependencies,'install_project_dependencies',lambda *a,**kw:pytest.fail('shared case must not install/inject dependencies'))
    monkeypatch.setattr(launch,'build_environment',lambda p:{})
    monkeypatch.setattr(launch,'resolve_launch',lambda p:{'mode':'script','script':'dev'})
    return child,lineage,root


def test_shared_toolchain_reuses_exact_qualification_without_dependency_injection(shared_case):
    child,lineage,root=shared_case;p=child/'runtime/project/package.json';before=p.read_bytes()
    receipt=r.ensure_environment(child,lineage)
    assert p.read_bytes()==before
    assert receipt['shared'] is True and receipt['shared_qualification']['files']
    assert r.tree(lineage/'environment_snapshot')==receipt['snapshot_files']
    assert r.ensure_environment(child,lineage)==receipt


def test_shared_toolchain_changed_bytes_refused(shared_case):
    child,lineage,root=shared_case
    (root/'node_modules/vite/bin/vite.js').write_text('changed cli')
    with pytest.raises(ValueError,match='qualified original'):r.ensure_environment(child,lineage)


def test_saved_shared_environment_cannot_be_silently_rebound(shared_case):
    child,lineage,root=shared_case
    r.ensure_environment(child,lineage)
    (lineage/'environment_snapshot/package.json').write_text('tampered archive')
    with pytest.raises(ValueError,match='snapshot drift'):r.ensure_environment(child,lineage)


def test_authored_ranges_use_existing_frozen_lock(tmp_path):
    put(tmp_path/'package-lock.json',{'packages':{'node_modules/vite':{'version':'5.4.21'}}})
    assert r.authored_version(tmp_path,'vite','^5.0.0')=='5.4.21'
    assert r.authored_version(tmp_path,'vite','5.4.10')=='5.4.10'
    with pytest.raises(ValueError,match='existing frozen lock'):r.authored_version(tmp_path,'three','^0.160.0')


@pytest.fixture
def lock_metadata(tmp_path):
    before={'lockfileVersion':3,'packages':{'':{'devDependencies':{'vite':'^5.0.0'}},
        'node_modules/rollup':{'version':'4.64.8','optionalDependencies':{'@rollup/rollup-linux-arm64-gnu':'4.64.8'}}}}
    after=json.loads(json.dumps(before))
    after['packages']['node_modules/@rollup/rollup-linux-arm64-gnu']={
        'version':'4.64.8','resolved':'https://registry.npmjs.org/@rollup/rollup-linux-arm64-gnu/-/rollup-linux-arm64-gnu-4.64.8.tgz',
        'integrity':'sha512-KBNMmyw4lPdL+2KtvE5vqODZRJgv7Y0Qg/v8uBL+i2KYLtAnfrvW6ukxZPO2lt6mfCOmvKJ1IcKAp3Smi3JpBQ==',
        'cpu':['arm64'],'dev':True,'license':'MIT','optional':True,'os':['linux'],'libc':['glibc']}
    a,b=tmp_path/'before.json',tmp_path/'after.json';put(a,before);put(b,after)
    return a,b


def test_nonhost_lock_materialization_keeps_existing_entries(lock_metadata):
    before,after=lock_metadata;proof=r.lock_metadata_proof(before,after)
    assert proof['original_sha256']==r.sha256(before)
    assert proof['installed_sha256']==r.sha256(after)
    assert proof['original_dependency_declarations_unchanged']


@pytest.mark.parametrize('change',['host','version','integrity','existing','root','extra','undeclared'])
def test_lock_metadata_exception_cannot_hide_dependency_changes(lock_metadata,change):
    before,after=lock_metadata;v=json.loads(after.read_text());p=v['packages']['node_modules/@rollup/rollup-linux-arm64-gnu']
    if change=='host':p['os']=['darwin']
    elif change=='version':p['version']='5.0.0'
    elif change=='integrity':p['integrity']='changed'
    elif change=='existing':v['packages']['node_modules/rollup']['version']='5.0.0'
    elif change=='root':v['packages']['']['devDependencies']['vite']='6.0.0'
    elif change=='extra':v['packages']['node_modules/new']={'version':'1.0.0'}
    else:
        old=json.loads(before.read_text());old['packages']['node_modules/rollup']['optionalDependencies']={};put(before,old)
    put(after,v)
    with pytest.raises(ValueError):r.lock_metadata_proof(before,after)


@pytest.mark.parametrize('duration', [75000, 125000])
def test_formal_playable_budget_is_in_memory_and_bounded(duration):
    import copy
    manifest = {'budget':{'gameplay_ms':duration,'recording_ms':duration,
                         'total_wall_clock_ms':duration+117000,'engine_call_ms':duration+145000}}
    original = copy.deepcopy(manifest)
    result = r.playable_manifest(manifest)
    assert manifest == original
    assert result['budget'] == {'gameplay_ms':75000,'recording_ms':75000,
                               'total_wall_clock_ms':192000,'engine_call_ms':220000}


def test_inconsistent_budget_cannot_silently_truncate():
    manifest = {'budget':{'gameplay_ms':125000,'recording_ms':75000,
                         'total_wall_clock_ms':242000,'engine_call_ms':270000}}
    with pytest.raises(ValueError, match='inconsistent original'):
        r.playable_manifest(manifest)


@pytest.mark.parametrize('model', ['astra', 'sol', 'glm'])
def test_new_astra_readiness_identity_is_exact(parent, model):
    p = parent/'manifest.json'; manifest = json.loads(p.read_text())
    manifest['delivery']['model'] = model; manifest['game_id'] = 'G011_cloud_mail_runner'
    put(p, manifest)
    if model in ('astra', 'glm'):
        assert r.failed_parent(parent)[0]['game_id'] == 'G011_cloud_mail_runner'
    else:
        with pytest.raises(ValueError, match='outside approved'):
            r.failed_parent(parent)


@pytest.mark.parametrize('case', ['G016_theater_sorting', 'G036_salt_flat_timetrial', 'G037_night_drift_yard'])
def test_new_glm_terminal_readiness_cases_remain_strict(parent, case):
    p = parent/'manifest.json'; manifest = json.loads(p.read_text())
    manifest['game_id'] = case; put(p, manifest)
    assert r.failed_parent(parent)[0]['game_id'] == case
    put(parent/'takes/1/record/native/partial-frame.png', {})
    with pytest.raises(ValueError, match='native artifacts'):
        r.failed_parent(parent)


@pytest.mark.parametrize('model', ['astra', 'glm', 'sol'])
@pytest.mark.parametrize('case', ['G017_lighthouse_prism', 'G012_gravity_mine', 'G016_theater_sorting', 'G037_night_drift_yard', 'G041_frontier_market'])
def test_astra_dev_identity_and_no_existing_native_are_required(parent, model, case):
    p = parent/'manifest.json'; manifest = json.loads(p.read_text())
    manifest['delivery']['model'] = model; manifest['game_id'] = case
    put(p, manifest)
    if model == 'sol' or (case == 'G041_frontier_market' and model != 'astra'):
        with pytest.raises(ValueError, match='outside approved'):
            r.failed_parent(parent)
        return
    assert r.failed_parent(parent)[0]['game_id'] == case
    put(parent/'takes/1/record/native/partial-frame.png', {})
    with pytest.raises(ValueError, match='native artifacts'):
        r.failed_parent(parent)


def test_multi_client_manifest_cannot_enter_single_client_recovery(parent):
    p = parent/'manifest.json'; manifest = json.loads(p.read_text())
    manifest['delivery']['required_real_clients'] = 2
    put(p, manifest)
    with pytest.raises(ValueError, match='multi-client'):
        r.failed_parent(parent)


@pytest.fixture(params=['G027_dune_maze_td', 'G026_signal_tower_td'])
def static_parent(parent, request):
    from engine_adapters.three_js.playtest.launch import resolve_launch
    p = parent/'manifest.json'; manifest = json.loads(p.read_text())
    source = Path(manifest['project_source'])
    entry = source/'builds/browser/index.html'; entry.parent.mkdir(parents=True)
    entry.write_text('<html><script src="./app.js"></script></html>')
    (entry.parent/'app.js').write_text('console.log("authored bundle");')
    put(source/'generation_report.json', {'schema_version':'gamefactory3a.generation_report.v1',
        'engine':'three_js','entrypoint':'builds/browser/index.html'})
    manifest['delivery']['model'] = 'astra'; manifest['game_id'] = request.param
    manifest['project_digest'] = r.prepare.tree_digest(r.prepare.tree_hashes(source)); put(p, manifest)
    runtime = parent/'runtime/project'
    launch = resolve_launch(source)
    for key in ('cwd','serve_root','entry'):
        launch[key] = str(runtime/Path(launch[key]).relative_to(source))
    launch['author_entry']['report'] = str(runtime/'generation_report.json')
    launch['url'] = 'http://127.0.0.1:54321'
    put(parent/'takes/1/record/launch_selection.json',launch)
    return parent


def test_delivered_static_bundle_keeps_accepted_plan(static_parent):
    assert r.failed_parent(static_parent)[0]['game_id'] == json.loads((static_parent/'manifest.json').read_text())['game_id']


@pytest.mark.parametrize('change', ['entry', 'serve_root', 'proof', 'script', 'source', 'identity', 'native'])
def test_static_recovery_refuses_route_or_source_substitution(static_parent, change):
    p = static_parent/'takes/1/record/launch_selection.json'; launch = json.loads(p.read_text())
    if change in ('entry','serve_root'):
        launch[change] = str(static_parent/'runtime/project/index.html')
    elif change == 'proof': launch['author_entry']['entry_sha256'] = '0'*64
    elif change == 'script': launch['script'] = 'dev'
    elif change == 'source':
        manifest = json.loads((static_parent/'manifest.json').read_text())
        (Path(manifest['project_source'])/'builds/browser/index.html').write_text('modified')
    elif change == 'identity':
        m = static_parent/'manifest.json'; manifest = json.loads(m.read_text())
        manifest['game_id'] = 'G017_lighthouse_prism'; put(m,manifest)
    elif change == 'native': put(static_parent/'takes/1/record/native/frame.png',{})
    put(p,launch)
    with pytest.raises(ValueError): r.failed_parent(static_parent)


def test_static_environment_and_archived_record_keep_delivered_route(static_parent, captured, monkeypatch):
    import shutil
    from engine_adapters.three_js.playtest import dependencies, launch
    from engine_adapters.three_js.config import ThreeClientConfig
    from engine_adapters.three_js._internal.transport import node
    manifest = json.loads((static_parent/'manifest.json').read_text())
    source = Path(manifest['project_source']); child = captured
    shutil.copytree(source, child/'input/project')
    project = child/'runtime/project'; shutil.copytree(source, project)
    put(child/'manifest.json', manifest)
    for name, version in [('vite','5.4.10'),('three','0.185.0')]:
        put(project/f'node_modules/{name}/package.json', {'version':version})
    cli = project/'node_modules/vite/bin/vite.js'; cli.parent.mkdir(); cli.write_text('fixture')
    binfile = project/'node_modules/.bin/vite'; binfile.parent.mkdir(); binfile.write_text('fixture')
    monkeypatch.setattr(ThreeClientConfig,'resolve',lambda **kw:None)
    monkeypatch.setattr(node,'NodeToolchain',lambda c:None)
    monkeypatch.setattr(dependencies,'verify_critical_packages',lambda *a:[])
    monkeypatch.setattr(dependencies,'project_needs_install',lambda *a:False)
    monkeypatch.setattr(dependencies,'install_project_dependencies',lambda *a,**kw:pytest.fail('no extra install'))
    lineage = child.parent/'static_receipts'
    receipt = r.ensure_environment(child,lineage)
    assert receipt['selection']['mode'] == 'static'
    assert receipt['selection']['entry'].endswith('/builds/browser/index.html')
    selected = launch.resolve_launch(project); selected['url'] = 'http://127.0.0.1:54321'
    put(child/'takes/1/record/launch_selection.json', selected)
    assert r.qualified_record(child,1)['frames'] == 100
    shutil.move(child/'input/project', child.parent/'source_archive')
    assert r.qualified_record(child,1)['frames'] == 100
    selected['author_entry']['entry_sha256'] = '0'*64
    put(child/'takes/1/record/launch_selection.json', selected)
    with pytest.raises(ValueError,match='entry proof'):
        r.qualified_record(child,1)


@pytest.mark.parametrize('case', ['G036_salt_flat_timetrial', 'G042_highland_seed_farm', 'G051_village_lost_found'])
def test_later_astra_dev_failures_preserve_native_guard(parent, case):
    p = parent/'manifest.json'; manifest = json.loads(p.read_text())
    manifest['delivery']['model'] = 'astra'; manifest['game_id'] = case
    put(p, manifest)
    assert r.failed_parent(parent)[0]['game_id'] == case
    put(parent/'takes/1/record/native/partial-frame.png', {})
    with pytest.raises(ValueError, match='native artifacts'):
        r.failed_parent(parent)


@pytest.fixture
def configured_parent(parent):
    m=json.loads((parent/'manifest.json').read_text());s=Path(m['project_source'])
    put(s/'package.json',{'dependencies':{'three':'0.185.0'},'devDependencies':{'vite':'6.2.6'}})
    (s/'index.html').write_text('<script type="module" src="/main.js"></script>')
    (s/'vite.config.js').write_text("export default {root:'.'}")
    m.update(delivery={'model':'kimi'},game_id='G041_frontier_market',project_digest=r.prepare.tree_digest(r.prepare.tree_hashes(s)))
    put(parent/'manifest.json',m)
    rec=parent/'takes/1/record';n=rec/'native/gameplay';(n/'frames').mkdir(parents=True)
    (n/'frame_index.jsonl').write_text('')
    put(rec/'launch_selection.json',{'mode':'static','script':None,'build_script':None,'url':'http://127.0.0.1:54321'})
    put(rec/'adapter_result.json',{'ok':False,'errors':['Invalid current playtest evidence: Recorder exited with code 1'],
        'payload':{'report_path':str(n/'report.json')}})
    put(n/'report.json',{'status':'failed'})
    put(n/'recording_progress.json',{'status':'failed','frames':0,'recorded_seconds':0,
        'channels_written':{'actions':0,'states':0,'events':0},
        'reason':'Failed to resolve module specifier "three". Relative references must start with either "/", "./", or "../".'})
    put(n/'input_view_cleanup.json',{'input_cleanup':True,'held_keys_after_release':0,'held_buttons_after_release':0})
    put(n/'browser_cleanup.json',{'input_cleanup':True,'view_cleanup':True,'browser_cleanup':True})
    put(n/'host_process_cleanup.json',{'process_cleanup':True,'server_group_alive':False,'recorder':{'process_cleanup':True,'group_alive':False}})
    return parent


def test_configured_vite_zero_frame_parent_reuses_accepted_plan(configured_parent):
    before=r.retained(configured_parent)
    m,accepted=r.failed_parent(configured_parent)
    assert m['game_id']=='G041_frontier_market'
    assert accepted['plan_sha256']==r.sha256(configured_parent/'takes/1/plan.json')
    assert r.retained(configured_parent)==before


@pytest.mark.parametrize('change',['frame','input','error','cleanup','entry','report','identity'])
def test_configured_vite_recovery_fails_closed(configured_parent,change):
    out=configured_parent;n=out/'takes/1/record/native/gameplay'
    if change in ('frame','input','error'):
        p=n/'recording_progress.json';v=json.loads(p.read_text())
        if change=='frame':v['frames']=1
        if change=='input':v['channels_written']['actions']=1
        if change=='error':v['reason']='other error'
        put(p,v)
    elif change=='cleanup':put(n/'host_process_cleanup.json',{'process_cleanup':False})
    elif change=='entry':
        m=json.loads((out/'manifest.json').read_text());(Path(m['project_source'])/'vite.config.js').unlink()
    elif change=='report':
        p=out/'takes/1/record/adapter_result.json';v=json.loads(p.read_text());v['payload']['report_path']='/tmp/other/report.json';put(p,v)
    else:
        p=out/'manifest.json';v=json.loads(p.read_text());v['game_id']='G011_cloud_mail_runner';put(p,v)
    with pytest.raises((ValueError,OSError)):r.failed_parent(out)


def test_configured_vite_route_binds_author_config_and_runtime(tmp_path):
    import shutil
    from engine_adapters.three_js.playtest.launch import resolve_launch
    source=tmp_path/'source';runtime=tmp_path/'runtime'
    put(source/'package.json',{'devDependencies':{'vite':'6.2.6'}})
    (source/'vite.config.js').write_text("export default {root:'.'}")
    (source/'index.html').write_text('<html></html>')
    shutil.copytree(source,runtime)
    launch=resolve_launch(runtime)
    r.authored_configured_vite_launch(source,runtime,launch)
    launch['authored_vite']['entry_sha256']='wrong'
    with pytest.raises(ValueError,match='proof changed'):r.authored_configured_vite_launch(source,runtime,launch)
