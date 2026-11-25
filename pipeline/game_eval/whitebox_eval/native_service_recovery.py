"""A single source-bound native pre-plan continuation after proven 503 recovery."""
from pathlib import Path
import json
import shutil
import time

from . import batch, core12, static_existence
from .protocol import dump, sha
from .unity_service_recovery import service_failures

VERSION = 'whitebox-native-service-recovery.v1'
RECEIPT = 'native_service_recovery.json'
CLAIM = 'native_service_recovery_claim.json'


def verify_probe(batch_dir, probe, *, checked_unix=None):
    batch_dir,probe=Path(batch_dir).resolve(),Path(probe).resolve()
    checked_unix=time.time() if checked_unix is None else checked_unix
    if not probe.is_relative_to(batch_dir/'engineering/native_service_recovery'):
        raise ValueError('Native service probe must belong to the frozen batch')
    folder=probe/'model_calls/service_probe';inv=batch.read(folder/'invocation.json');command=inv.get('command',[])
    if (inv.get('exit_code')!=0 or inv.get('model_requested')!=static_existence.MODEL
            or '--model' not in command or command[command.index('--model')+1]!=static_existence.MODEL
            or batch.read(folder/'response.json')!={'status':'READY'}
            or not 0<=checked_unix-(folder/'invocation.json').stat().st_mtime<=900
            or not 0<inv.get('seconds',0)<=90
            or batch.read(folder/'budget.json').get('effective_timeout_seconds')!=90
            or any((probe/'model_calls').glob('service_probe_*'))):
        raise ValueError('No recent successful single bounded native Sol service probe')
    return {str(p):sha(p) for p in folder.iterdir() if p.is_file()}


def prepare(source, *, probe, authorization):
    source=Path(source).resolve()
    if not isinstance(authorization,str) or not authorization.strip():raise ValueError('Authorization required')
    if any((source/n).exists() for n in (CLAIM,RECEIPT,'sol_plan.json','scores.json','runtime/frame_index.jsonl')):
        raise ValueError('Existing score, plan, capture or recovery protected')
    engine=batch.plan_engine(source)
    if engine not in {'godot','three_js'}:raise ValueError('Native service continuation requires original Godot/Three.js')
    if not (source/'harness_error.json').is_file():raise ValueError('Preserved native harness failure required')
    failures=service_failures(source)
    if not failures or any(row['stage'] not in {'plan','static_existence'} for row in failures):
        raise ValueError('No supported actual native pre-plan 503 failure')
    health=verify_probe(source.parents[1],probe)
    batch.verify_inputs(source);protocol=core12.verify_attempt(source,engine)
    entry=batch.read(source/'input_manifest.json')['entry']
    root=source.parent/(source.name+'__native_service_recovery_v1')
    if root.exists():raise ValueError('Native service destination already exists')
    with (source/CLAIM).open('x') as stream:json.dump({'version':VERSION,'destination':str(root),'maximum_recoveries':1},stream)
    batch.prepare(source.parents[1],entry,root,previous_attempt=source)
    if core12.verify_attempt(root,engine)!=protocol:raise ValueError('Native service continuation changed frozen protocol')
    if batch.read(root/'input_manifest.json')['snapshot_hashes']!=batch.read(source/'input_manifest.json')['snapshot_hashes']:
        raise ValueError('Native service continuation changed source snapshot')
    _preserve_frozen_input_bytes(source, root)
    return _finish(source, root, probe=probe, health=health, authorization=authorization)


def _preserve_frozen_input_bytes(source, root):
    batch.verify_inputs(source)
    batch.verify_inputs(root)
    old = batch.read(root/'input_manifest.json')
    frozen = batch.read(source/'input_manifest.json')
    names = ('pilot_rubric.json', 'input_capabilities.json')
    for key in set(old) | set(frozen):
        if key not in {'input_hashes', 'protocol_sha256'} and old.get(key) != frozen.get(key):
            raise ValueError('Native frozen manifest semantic drift: '+key)
    for name in set(old['input_hashes']) | set(frozen['input_hashes']):
        if name not in names and old['input_hashes'].get(name) != frozen['input_hashes'].get(name):
            raise ValueError('Native frozen input difference outside serialization: '+name)
    canonical = lambda value: json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    for name in names:
        if canonical(batch.read(source/'input'/name)) != canonical(batch.read(root/'input'/name)):
            raise ValueError('Native frozen JSON semantic drift: '+name)
    archive = root/'engineering/frozen_input_byte_preservation'
    if archive.exists():
        raise ValueError('Frozen input preservation already started; inspect saved archive')
    archive.mkdir(parents=True)
    paths = ['input_manifest.json', *('input/'+n for n in names)]
    before, after = {}, {}
    for name in paths:
        target = archive/'before'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/name, target)
        before[name] = sha(target)
        after[name] = sha(source/name)
    dump(archive/'equivalence.json', {
        'version': 'whitebox-native-frozen-input-bytes.v1',
        'source_attempt': str(source), 'target_attempt': str(root),
        'before_sha256': before, 'frozen_sha256': after,
        'allowed_json_files': list(names), 'json_values_identical': True,
        'other_manifest_fields_identical': True,
        'scope': 'Exact original bytes restored; original accepted identities, schemas, source, protocol and all evidence are unchanged.'})
    for name in paths:
        shutil.copy2(source/name, root/name)
    batch.verify_inputs(root)
    if core12.verify_attempt(root, batch.plan_engine(root)) != core12.verify_attempt(source, batch.plan_engine(source)):
        raise ValueError('Frozen byte preservation changed protocol')
    return archive


def resume_preparation(source, *, probe, authorization):
    # Continue the original claimed identity, with no new model dispatch.
    source = Path(source).resolve()
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError('Authorization required')
    claim = batch.read(source/CLAIM)
    root = source.parent/(source.name+'__native_service_recovery_v1')
    if claim != {'version': VERSION, 'destination': str(root), 'maximum_recoveries': 1}:
        raise ValueError('Original native recovery claim changed')
    protected = (RECEIPT, 'sol_plan.json', 'scores.json', 'runtime/frame_index.jsonl', 'runtime/capture_bundle.json')
    if any((p/name).exists() for p in (source, root) for name in protected):
        raise ValueError('Existing plan, score, capture or recovery protected')
    if not root.is_dir() or not (source/'harness_error.json').is_file():
        raise ValueError('Preserved partial preparation and failure required')
    failures = service_failures(source)
    if not failures or any(row['stage'] not in {'plan', 'static_existence'} for row in failures):
        raise ValueError('No supported actual native pre-plan 503 failure')
    checked = (source/CLAIM).stat().st_mtime
    health = verify_probe(source.parents[1], probe, checked_unix=checked)
    batch.verify_inputs(source)
    batch.verify_inputs(root)
    if batch.plan_engine(source) not in {'godot', 'three_js'} or batch.plan_engine(root) != batch.plan_engine(source):
        raise ValueError('Partial native recovery engine changed')
    if core12.verify_attempt(source, batch.plan_engine(source)) != core12.verify_attempt(root, batch.plan_engine(root)):
        raise ValueError('Partial native recovery protocol changed')
    for name in ('static_existence.json', 'static_format_recovery.json'):
        if (root/name).exists() and (not (source/name).is_file() or sha(root/name) != sha(source/name)):
            raise ValueError('Partial accepted static changed: '+name)
    calls = root/'model_calls'
    if calls.exists():
        for folder in calls.iterdir():
            original = source/'model_calls'/folder.name
            if not folder.is_dir() or not folder.name.startswith('static_existence') or not original.is_dir() or batch.hashes(folder) != batch.hashes(original):
                raise ValueError('Partial preparation contains new or changed model calls')
    _preserve_frozen_input_bytes(source, root)
    dump(root/'engineering/preparation_resumed.json', {
        'source_attempt': str(source), 'target_attempt': str(root),
        'claim_sha256': sha(source/CLAIM), 'claim_created_unix': checked,
        'resumed_unix': time.time(), 'new_model_calls': 0,
        'maximum_recoveries': 1, 'authorization': authorization,
        'cause': 'JSON key-order byte drift rejected accepted frozen static identity before plan dispatch; original bytes restored after exact semantic equivalence checks.'})
    return _finish(source, root, probe=probe, health=health, authorization=authorization, health_checked_unix=checked)


def _finish(source, root, *, probe, health, authorization, health_checked_unix=None):
    protocol=core12.verify_attempt(source,batch.plan_engine(source))
    failures=service_failures(source)
    copied=['input_manifest.json', 'input/pilot_rubric.json', 'input/input_capabilities.json']
    if (source/'static_existence.json').is_file():
        static_existence.load(source,protocol)
        for name in ('static_existence.json','static_format_recovery.json'):
            if (source/name).exists():shutil.copy2(source/name,root/name);copied.append(name)
        for folder in (source/'model_calls').glob('static_existence*'):
            if folder.is_dir():
                target=root/'model_calls'/folder.name
                if target.exists():
                    if batch.hashes(target)!=batch.hashes(folder):
                        raise ValueError('Partial accepted static copy changed')
                else:shutil.copytree(folder,target)
                copied.extend(str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file())
        static_existence.load(root,protocol)
    copied.extend(str(p.relative_to(root)) for p in (root/'engineering').rglob('*') if p.is_file())
    bindings={str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'target_attempt':str(root),
        'bindings':bindings,'copied_bindings':{n:sha(root/n) for n in copied},'probe':str(Path(probe).resolve()),
        'probe_bindings':health,'health_checked_unix':time.time() if health_checked_unix is None else health_checked_unix,'failures':failures,
        'maximum_recoveries':1,'authorization':authorization})
    verify(root)
    return root


def verify(root):
    root=Path(root).resolve();value=batch.read(root/RECEIPT);source=Path(value['source_attempt']).resolve()
    if (value.get('version')!=VERSION or value.get('target_attempt')!=str(root)
            or value.get('maximum_recoveries')!=1 or source==root or source.parent!=root.parent
            or not value.get('authorization') or (source/RECEIPT).exists()):
        raise ValueError('Invalid native service recovery lineage')
    claim=batch.read(source/CLAIM)
    if claim.get('destination')!=str(root) or claim.get('maximum_recoveries')!=1:
        raise ValueError('Native service claim changed')
    for name,digest in value['bindings'].items():
        path=(source/name).resolve()
        if not path.is_relative_to(source) or sha(path)!=digest:raise ValueError('Native service original failure/input changed: '+name)
    for name,digest in value['copied_bindings'].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or sha(path)!=digest:raise ValueError('Native service accepted static changed: '+name)
    for name,digest in value['probe_bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Native service health evidence changed')
    if verify_probe(root.parents[1],value['probe'],checked_unix=value['health_checked_unix'])!=value['probe_bindings']:
        raise ValueError('Native service probe binding changed')
    return {str(root/RECEIPT):sha(root/RECEIPT),**{str(source/n):d for n,d in value['bindings'].items()},**value['probe_bindings']}
