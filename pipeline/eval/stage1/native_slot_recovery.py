"""One bound evidence continuation for equal native int/float capture slots.

The original record, failed requests, budgets and accepted static judgments stay
intact. Only evidence whose exact predeclared frame was omitted is repackaged.
"""
from pathlib import Path
import json
import shutil
import time

from . import batch, core12, sparse_evidence, sparse_native
from .protocol import dump, sha, checked_path

VERSION = 'whitebox-native-slot-evidence-recovery.v1'
RECEIPT = 'native_slot_evidence_recovery.json'
CLAIM = 'native_slot_evidence_recovery_claim.json'
# These receipts name their original active attempt. Preserve them in the
# archive; validate their unchanged complete graph on that original source.
SOURCE_IDENTITY_RECEIPTS = ('native_saved_plan_handoff.json',
    'native_diagnostic_plan_recovery.json', 'native_service_recovery.json',
    'native_static_partition_recovery.json')


def archive_source_identities(root, archive):
    for name in SOURCE_IDENTITY_RECEIPTS:
        path = root/name
        if path.exists():
            shutil.move(path, archive/name)


def preserve_plan_identity(root, protocol, engine, plan):
    from . import plan_invocation_identity
    current = core12.plan_identity(root, protocol, engine)
    recorded = plan.get('planning_identity')
    if (not isinstance(recorded, dict) or
            plan_invocation_identity.resolve(root, current, recorded, write=True) != recorded):
        raise ValueError('Native slot handoff changed the original plan invocation identity')


def slot_difference(protocol, plan, frames, manifest, audit):
    """Qualify this precise decoder bug; no nearest-time selection or tolerance."""
    from .multiclient import enabled
    if enabled(protocol):
        raise ValueError('Single native capture slots required')
    if audit != manifest.get('sparse_capture_audit') or audit['missing_slots_ms']:
        raise ValueError('Complete unchanged original native capture audit required')
    legacy = {ident: ([audit['slot_frames'][str(endpoint['at_ms'])]]
                      if endpoint['probe_ids'] and str(endpoint['at_ms']) in audit['slot_frames'] else [])
              for ident, endpoint in plan['capture_plan']['endpoints'].items()}
    corrected = sparse_evidence.selections(protocol, plan, frames, audit)
    if manifest.get('endpoint_frames') != legacy or corrected == legacy:
        raise ValueError('No exact numeric slot representation delivery defect')
    changed = [ident for ident in corrected if corrected[ident] != legacy[ident]]
    if any(legacy[ident] or len(corrected[ident]) != 1 for ident in changed):
        raise ValueError('Recovery may only restore an omitted declared frame')
    return {'before': legacy, 'after': corrected, 'changed_criteria': changed}


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    source = Path(value['source_attempt']).resolve()
    if (value.get('version') != VERSION or value.get('destination') != str(root)
            or source == root or source.parent != root.parent
            or value.get('execution_allowed') is not False
            or value.get('new_recordings') != 0 or value.get('maximum_recoveries') != 1
            or not value.get('authorization')):
        raise ValueError('Invalid native slot recovery identity')
    if sha(source/CLAIM) != value['claim_sha256'] or sha(root/CLAIM) != value['claim_sha256']:
        raise ValueError('Native slot recovery claim changed')
    claim = batch.read(source/CLAIM)
    if (claim['destination'] != str(root) or claim['source_attempt'] != str(source)
            or claim['maximum_recoveries'] != 1):
        raise ValueError('Native slot recovery claim identity changed')
    from .judge_format_recovery import repair_proof
    if repair_proof(value['engineering_repair']['path']) != value['engineering_repair']:
        raise ValueError('Native slot engineering repair changed')
    if 'source_audit_bindings' in value:
        from . import integrity
        if integrity.audit_bindings(source) != value['source_audit_bindings']:
            raise ValueError('Original native recovery provenance graph changed')
    for name, digest in value['source_bindings'].items():
        if sha(checked_path(source, name)) != digest:
            raise ValueError('Original native slot source changed: '+name)
    for name, digest in value['immutable_copy_bindings'].items():
        if sha(checked_path(root, name)) != digest:
            raise ValueError('Original native slot record/input changed: '+name)
    for name, digest in value['archived_bindings'].items():
        if sha(checked_path(root, name)) != digest:
            raise ValueError('Archived native slot failure changed: '+name)
    for name, raw in value['preserved_raw'].items():
        if batch.read(root/'judgments'/(name+'.json'))['raw'] != raw:
            raise ValueError('Accepted native slot judgment changed: '+name)
    if sha(root/'evidence_manifest.json') != value['manifest_sha256']:
        raise ValueError('Corrected native slot manifest changed')
    allowed = set(value['original_active_calls']) | set(value['new_model_calls_allowed'])
    if {p.name for p in (root/'model_calls').iterdir() if p.is_dir()} - allowed:
        raise ValueError('Unauthorized native slot model invocation')
    return {str(root/RECEIPT):sha(root/RECEIPT), str(source/CLAIM):sha(source/CLAIM),
            **{str(source/name):digest for name,digest in value['source_bindings'].items()}}


def prepare(source, *, engineering_repair, authorization):
    """Caller holds the configured execution/publication locks for this handoff."""
    from . import recovery_publish, frame_budget, static_existence, static_judge_shards
    from . import request_reuse, integrity
    from .codex import saved_model_response, decode_keyed_judgment
    from .pending_publication import cleanup_source
    from .judge_format_recovery import repair_proof
    source = Path(source).resolve()
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError('Explicit native slot engineering authorization required')
    if any((source/name).exists() for name in (CLAIM, RECEIPT)):
        raise ValueError('Existing native slot recovery or saved score protected')
    engine = batch.plan_engine(source)
    if engine not in {'godot', 'three_js'}:
        raise ValueError('Original native Godot/Three.js capture required')
    repair = repair_proof(engineering_repair)
    supersedes = None
    if (source/'scores.json').exists():
        from . import native_scored_cache
        # A score is eligible only for this proven evidence decoder defect,
        # with all four exact saved pending rows; audited results stay protected.
        native_scored_cache.qualified_score(source.parents[1],source)
        ident=batch.read(source/'input_manifest.json')['entry']['id']
        supersedes=batch.read(source.parents[1]/'pending_audits.json')['entries'][ident]
        if supersedes.get('audit_status') != 'PENDING' or supersedes.get('formal_effective_valid') is not False:
            raise ValueError('Audited/formal score cannot be corrected by this recovery')
    batch.verify_inputs(source); batch.verify_runtime_sources(source)
    protocol = core12.verify_attempt(source, engine)
    static_existence.load(source, protocol); cleanup_source(source)
    plan = batch.read(source/'sol_plan.json')
    batch.validate_operation_plan(source, plan, engine, record_validation=False)
    frames = batch.load_lines(source/'runtime/frame_index.jsonl')
    manifest = batch.read(source/'evidence_manifest.json')
    audit = sparse_evidence.audit_capture(source/'runtime')
    difference = slot_difference(protocol, plan, frames, manifest, audit)
    original_gate = batch.validate_capture_bundle(source,manifest,protocol)
    if original_gate.get('issues') != ['Invalid action evidence index: endpoint frames are not the predeclared final observations']:
        raise ValueError('Native slot recovery cannot conceal another capture defect: '+str(original_gate))
    for item in manifest['items']:
        if sha(checked_path(source,item['path'])) != item['sha256']:
            raise ValueError('Original native slot evidence SHA mismatch')
    root = source.with_name(source.name+'__native_slot_evidence_recovery_v1')
    if root.exists():
        raise ValueError('Native slot recovery destination already exists')
    sparse_native.space(source,'native_slot_evidence_handoff',estimated_bytes=2*1024**3)
    original_graph = integrity.audit_bindings(source)
    bindings = {str(p.relative_to(source)):sha(p) for p in source.rglob('*') if p.is_file()}
    claim = {'version':VERSION,'source_attempt':str(source),'destination':str(root),
             'maximum_recoveries':1,'created_unix':time.time(),'engineering_repair':repair}
    with (source/CLAIM).open('x') as stream:
        json.dump(claim, stream, indent=2)
    recovery_publish.clone_attempt(source,root)
    archive = root/'inherited_attempt/slot_delivery'; archive.mkdir(parents=True)
    archive_source_identities(root, archive)
    for name in ('delivery','evidence_manifest.json','trace_summary.json'):
        if (root/name).exists(): shutil.move(root/name, archive/name)
    # Preserve every failed/dynamic call. Unchanged accepted shards are restored
    # only after exact request/packet comparison against the corrected delivery.
    for name in ('model_calls','judgments'):
        for path in list((root/name).iterdir()):
            if path.name.startswith('evidence_'):
                target=archive/name/path.name;target.parent.mkdir(exist_ok=True)
                shutil.move(path,target)
    preserve_plan_identity(root, protocol, engine, plan)
    updated = batch.deliver(root)
    if static_judge_shards.FIELD in manifest:
        if manifest[static_judge_shards.FIELD] != static_judge_shards.partition(protocol):
            raise ValueError('Original static judge partition changed')
        updated[static_judge_shards.FIELD] = manifest[static_judge_shards.FIELD]
        static_judge_shards.tasks(protocol,updated)
        dump(root/'evidence_manifest.json',updated)
    gate=batch.validate_capture_bundle(root,updated,protocol)
    if gate.get('valid') is not True:
        raise ValueError('Corrected native slot capture gate failed: '+str(gate))
    preserved={}; fresh=[]
    for name,specs,is_static in frame_budget.tasks(protocol,updated):
        artifact=source/'judgments'/(name+'.json')
        same=False
        if artifact.is_file():
            before=frame_budget.for_task(manifest,name);after=frame_budget.for_task(updated,name)
            same=(batch.packet(source,before,is_static)==batch.packet(root,after,is_static)
                  and [v for v in before['items'] if v['type'] in {'frame','reference'}]
                  ==[v for v in after['items'] if v['type'] in {'frame','reference'}]
                  and before['delivery_sheets']==after['delivery_sheets'])
        if not same:
            if is_static and artifact.is_file():
                raise ValueError('Native slot repair changed accepted static context')
            fresh.append(name);continue
        request_reuse.audit_one(source,name,protocol,manifest)
        raw=batch.read(artifact)['raw']
        if raw != decode_keyed_judgment(batch.read(saved_model_response(source,name)),specs):
            raise ValueError('Accepted native slot raw differs from original response')
        if name.startswith('evidence_'):
            shutil.copy2(artifact,root/'judgments'/artifact.name)
            for folder in (source/'model_calls').glob(name+'*'):
                shutil.copytree(folder,root/'model_calls'/folder.name)
        preserved[name]=raw
    dump(root/RECEIPT,{'version':VERSION,'source_attempt':str(source),'destination':str(root),
         'source_plan_sha256':sha(source/'sol_plan.json'),'source_bindings':bindings,
         'source_audit_bindings':original_graph,
         'claim_sha256':sha(source/CLAIM),'engineering_repair':repair,
         'authorization':authorization,'maximum_recoveries':1,'execution_allowed':False,
         'new_recordings':0,'difference':difference,'preserved_raw':preserved,
         'supersedes_pending':supersedes,
         'new_model_calls_allowed':fresh,
         'original_active_calls':[p.name for p in (root/'model_calls').iterdir() if p.is_dir()],
         'manifest_sha256':sha(root/'evidence_manifest.json'),'capture_gate':gate,
         'immutable_copy_bindings':{str(p.relative_to(root)):sha(p) for folder in
             ('input','runtime') for p in (root/folder).rglob('*') if p.is_file()}
             | {name:sha(root/name) for name in ('input_manifest.json','sol_plan.json','static_existence.json')},
         'archived_bindings':{str(p.relative_to(root)):sha(p) for p in (root/'inherited_attempt').rglob('*') if p.is_file()},
         'created_unix':time.time()})
    dump(root/'channel_transport_recovery.json',{'schema':'whitebox-endpoint-channel-recovery.v1',
         'source_attempt':str(source),'qualification':str(root/RECEIPT),
         'qualification_sha256':sha(root/RECEIPT),'reused_judge_shards':list(preserved)})
    verify(root)
    return root


def authorize_pending_replacement(root, previous):
    """Replace one pending row only after a proven, fully judged slot repair."""
    from . import native_scored_cache
    from .pending_publication import STATUS
    root=Path(root).resolve()
    if not (root/RECEIPT).is_file():
        raise ValueError('Existing pending score protected; no bound slot correction')
    verify(root)
    value=batch.read(root/RECEIPT);source=Path(value['source_attempt']).resolve()
    if (value.get('supersedes_pending') != previous
            or previous.get('attempt') != str(source.relative_to(root.parents[1]))
            or previous.get('status') != STATUS or previous.get('audit_status') != 'PENDING'
            or previous.get('formal_effective_valid') is not False
            or not value['difference']['changed_criteria']):
        raise ValueError('Exact original pending row and substantive slot defect required')
    native_scored_cache.qualified_score(root.parents[1],source)
    if batch.read(root/'input_manifest.json')['entry'] != batch.read(source/'input_manifest.json')['entry']:
        raise ValueError('Slot correction changed the evaluated delivery')
    gate=batch.validate_capture_bundle(root)
    if not gate['valid']:
        raise ValueError('Slot correction requires the full corrected capture gate')
    return {'version':VERSION,'source_attempt':str(source),
            'source_score_sha256':sha(source/'scores.json'),
            'source_publication_sha256':sha(source/'pending_publication_receipt.json'),
            'repair_receipt':str(root/RECEIPT),'repair_receipt_sha256':sha(root/RECEIPT),
            'previous_pending_record':previous,'audit_status':'PENDING',
            'reason':'Proven equal native numeric slot was omitted from actual endpoint evidence; unchanged raw capture, frozen rubric and credit rules.'}
