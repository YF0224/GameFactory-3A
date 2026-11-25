"""Strict source contract for stopped, independently recorded native client pairs."""
from pathlib import Path
from . import batch, multiclient
from .protocol import dump, sha, checked_path

VERSION = 'unity-native-pair-project-sources.v2'
CAPTURE_FILES = ('result.json','verification.json','cleanup.json','multisession_index.json',
                 'source_binding.json','capture_schedule.json','client_snapshots.json','project_reuse.json')

def bound_path(root, name):
    path = Path(name)
    if not path.is_absolute(): path = root/path
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Native source path outside attempt or symlink')
    for parent in [path,*path.parents]:
        if parent == root.parent: break
        if parent.is_symlink():raise ValueError('Native source symlink ancestor')
    return path.resolve()

def binding(folder):
    names=list(CAPTURE_FILES)
    if (folder/'postprocess_recovery.json').is_file():
        names+=['postprocess_recovery.json','recovered_result.json','recovered_verification.json']
    return {name:sha(folder/name) for name in names}

def check_bindings(folder, expected):
    if set(expected) != set(binding(folder)):
        raise ValueError('Incomplete native capture source bindings')
    for name, digest in expected.items():
        if sha(checked_path(folder,name)) != digest:
            raise ValueError('Native source binding changed: '+name)

def capture(root, folder, baseline, acceptance, expected=None):
    from engine_adapters.unity3d.playtest.project_snapshot import snapshot_files
    from .unity_failed_import_reuse import validate_import
    if expected is not None: check_bindings(folder,expected)
    result=batch.read(folder/'result.json');verification=batch.read(folder/'verification.json')
    if (folder/'postprocess_recovery.json').is_file():
        from .unity_native_pair_recovery import verify as verify_recovery
        result,verification=verify_recovery(folder)
    if (result.get('ok') is not True or result.get('status')!='NATIVE_PAIR_CAPTURE_VERIFIED'
            or result.get('source_binding_sha256')!=sha(folder/'source_binding.json')
            or result.get('project_reuse_sha256')!=sha(folder/'project_reuse.json')
            or not verification.get('checks')
            or not all(v is True for v in verification['checks'].values())
            or not all(batch.read(folder/'cleanup.json').get(k) is True for k in
                       ('input_cleanup','view_cleanup','process_cleanup','source_unchanged'))):
        raise ValueError('Native capture result, verification or cleanup invalid')
    multiclient.audit_capture(folder,batch.read(folder/'capture_schedule.json'))
    source=root/'input/project';source_binding=batch.read(folder/'source_binding.json')
    snapshot={str(p.relative_to(source)):sha(p) for p in snapshot_files(source,[])}
    if (source_binding['planning_source']!=str(source)
            or source_binding['planning_source_sha256']!=snapshot
            or source_binding['normal_authored_tcp'] is not True
            or any(source_binding.get(k) is not False for k in ('automation','replay','ignore_focus'))
            or source_binding['adapter_pin']!=acceptance['adapter_pin']
            or source_binding['adapter_pin_sha256']!=acceptance['adapter_pin_sha256']
            or source_binding['observer_contract']!=acceptance['observer_contract']
            or source_binding['observer_contract_sha256']!=acceptance['observer_contract_sha256']):
        raise ValueError('Native capture changed planning, pin or observer identity')
    project_root=bound_path(root,source_binding['project_root'])
    reused=batch.read(folder/'project_reuse.json')
    if (reused['source']!=str(source) or reused['source_hashes']!=baseline
            or reused['project_root']!=str(project_root)):
        raise ValueError('Executed native project source/root binding differs')
    snapshots=batch.read(folder/'client_snapshots.json')
    projects={};engine={};observer=None
    for role in multiclient.ROLES:
        if snapshots[role]['files_sha256']!=snapshot:
            raise ValueError('Native copy snapshot differs from planning source: '+role)
        project=bound_path(root,project_root/('project_'+role))
        installed=batch.read(project/'Assets/GameFactory3AEvaluation/installation.json')
        if installed.get('schema')!='unity-observer-installation.v1' or not installed.get('files'):
            raise ValueError('Native observer installation absent')
        if observer is None: observer=installed['files']
        if installed['files']!=observer:
            raise ValueError('Independent clients have different observer sources')
        current,allowed=validate_import(source,project,observer)
        if current!=reused['projects'][role]:
            raise ValueError('Executed native client changed since recording: '+role)
        projects[role]={'path':str(project.relative_to(root)),'files_sha256':current}
        engine[role]=allowed
    return {'project_root':str(project_root),'projects':projects,'engine_initialization':engine,
            'observer':observer,'bindings':binding(folder)}

def inspect(root, acceptance_path):
    """Recompute all checks from raw recordings, never trust a claimed boolean."""
    from .unity_native_pair_record import process_identities,verified_host_reuse
    root=Path(root).resolve();source=root/'input/project';runtime=root/'runtime'
    baseline=batch.read(root/'input_manifest.json')['snapshot_hashes']
    if batch.hashes(source)!=baseline:raise ValueError('Frozen native planning source changed')
    acceptance_path=Path(acceptance_path).resolve();accepted=batch.read(acceptance_path)
    if (accepted.get('accepted') is not True or accepted.get('source')!=str(source)
            or set(accepted.get('stages',{}))!={'20','180'}):
        raise ValueError('Matching 20/180 native Editor acceptance required')
    if (sha(Path(accepted['adapter_pin']))!=accepted['adapter_pin_sha256']
            or sha(Path(accepted['observer_contract']))!=accepted['observer_contract_sha256']):
        raise ValueError('Accepted native pin or observer contract changed')
    stages={}
    for seconds,row in accepted['stages'].items():
        folder=bound_path(root,row['capture'])
        for key,name in [('result_sha256','result.json'),('verification_sha256','verification.json'),
                         ('cleanup_sha256','cleanup.json')]:
            if sha(folder/name)!=row[key]:raise ValueError('Native acceptance stage changed: '+seconds)
        request=Path(accepted['backend_application']).parent/('acceptance_'+seconds+'.json')
        if sha(request)!=row['request_sha256']:
            raise ValueError('Accepted native route request changed: '+seconds)
        if seconds=='20' and 'recovered_result' in row:
            recovered=bound_path(root,row['recovered_result'])
            if sha(recovered)!=row['recovered_result_sha256'] or batch.read(recovered).get('ok') is not True:
                raise ValueError('Recovered real native acceptance changed')
            # Original successful raw result and failed derivation are preserved.
            if not (folder/'derivation_failure.json').is_file():
                raise ValueError('Original native derivation failure missing')
            multiclient.audit_capture(folder,batch.read(folder/'capture_schedule.json'))
            if not all(v is True for v in batch.read(folder/'verification.json')['checks'].values()):
                raise ValueError('Recovered native acceptance verification invalid')
            if not all(batch.read(folder/'cleanup.json').get(k) is True for k in
                       ('input_cleanup','view_cleanup','process_cleanup','source_unchanged')):
                raise ValueError('Recovered native acceptance cleanup invalid')
            stages[seconds]={'capture':str(folder),'bindings':binding(folder),
                             'recovered_result_sha256':sha(recovered)}
        else:
            stages[seconds]={'capture':str(folder),**capture(root,folder,baseline,accepted)}
    product=capture(root,runtime,baseline,accepted)
    prior=stages['180']
    if any(product[key]!=prior[key] for key in ('project_root','projects','observer','engine_initialization')):
        raise ValueError('Product clients differ from matching accepted native projects')
    source_binding=batch.read(runtime/'source_binding.json')
    reused=source_binding.get('verified_project_reuse',{})
    if (reused.get('receipt')!=str(Path(prior['capture'])/'result.json')
            or reused.get('receipt_sha256')!=sha(Path(reused['receipt']))
            or reused.get('project_reuse_sha256')!=sha(Path(prior['capture'])/'project_reuse.json')):
        raise ValueError('Product imported-client reuse proof differs')
    host=source_binding.get('verified_host_reuse',{})
    _,verified=verified_host_reuse(source_binding['candidate'],Path(host['receipt']))
    if host!=verified:raise ValueError('Actual authored host binding changed')
    identities=process_identities()
    projects=[str(bound_path(root,p['path'])) for p in product['projects'].values()]+[host['project']]
    if any(any(p in row['command'] for p in projects) for row in identities.values()):
        raise ValueError('Native project processes still occupied')
    return {'schema':VERSION,'version':multiclient.VERSION,'baseline_sha256':baseline,
            'native_acceptance':str(acceptance_path),'native_acceptance_sha256':sha(acceptance_path),
            'stages':stages,'product':product,'host':host,
            'clock':'independent recorder sessions; NO cross-session synchronization'}

def prepare(root, acceptance_path):
    root=Path(root).resolve();destination=root/'runtime/multisession_sources.json'
    value=inspect(root,acceptance_path)
    if destination.exists():
        if batch.read(destination)!=value:raise ValueError('Preserve existing native source receipt')
    else:dump(destination,value)
    return verify(root)

def verify(root):
    root=Path(root).resolve();path=root/'runtime/multisession_sources.json';value=batch.read(path)
    if value.get('schema')!=VERSION:raise ValueError('Unsupported native source contract')
    from . import event_wire_recovery
    if (root/event_wire_recovery.RECEIPT).is_file():
        origin=event_wire_recovery.native_source_origin(root)
        verified=verify(origin)
        return {**verified,'recovery_source_attempt':str(origin),
                'recovery_source_receipt_sha256':sha(path)}
    actual=inspect(root,value['native_acceptance'])
    if actual!=value:raise ValueError('Native source contract no longer matches actual evidence')
    return {'valid':True,'roles':list(multiclient.ROLES),'source_receipt_sha256':sha(path),
            'clock':'independent native client clocks'}
