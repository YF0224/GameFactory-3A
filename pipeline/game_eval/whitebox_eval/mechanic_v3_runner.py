"""Independent opt-in Mechanic v3 execution, historical evidence remains read-only.

Production code lives here. Workspace files are data/configuration only.
"""
from __future__ import annotations
from contextlib import contextmanager, ExitStack
from pathlib import Path
import argparse
import copy
import datetime
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time

from . import mechanic_v3 as v3
from . import mechanic_v3_revision as revisions
from . import batch, sparse_native, sparse_evidence, frame_budget
from .codex import call_codex, load_plan_json
from .protocol import dump, sha, checked_path

VERSION = 'whitebox-mechanic-only-runner.v1'
RESERVE = 8 * 1024**3


def read(path):
    return load_plan_json(Path(path))


def stamp():
    return datetime.datetime.now().astimezone().isoformat()


def exclusive_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


@contextmanager
def held(workspace, source_batch, *, native=False):
    """Serialize this workspace; shared engine leases are mandatory for native work.

    Historical read-only evidence/judging touches no shared engine or queue state.
    Snapshot occupied shared locks without acquiring/bypassing them for those phases.
    """
    from .runtime import active_gui_engines
    config = read(source_batch/'native_capture_configuration.json')
    control = Path(config['control_root'])
    if (control/'background_record_cleanup_block.json').exists():
        raise BlockingIOError('Unresolved shared cleanup marker')
    shared = config['outer_execution_locks'] + [config['runtime_owned_gui_lock']]
    snapshot = []
    for name in shared:
        with Path(name).open('a+') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                snapshot.append(dict(path=name, occupied=False))
            except BlockingIOError:
                owners=subprocess.run(['lsof','-n','--',name],capture_output=True,text=True).stdout
                snapshot.append(dict(path=name, occupied=True, owners=owners))
    dump(workspace/'engineering/phase_snapshots'/(str(time.time_ns())+'.json'),
         dict(time=stamp(), native=native, shared_locks=snapshot,
              active_native_engines=active_gui_engines(),
              policy='Read-only historical inputs and independent workspace outputs; no shared engine, queue, or source mutation'))
    paths = (shared if native else []) + [str(workspace/'.publication.lock')]
    with ExitStack() as stack:
        for name in paths:
            path = Path(name); path.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(path.open('a+'))
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if native and active_gui_engines():
            raise BlockingIOError('Another native engine is running')
        guard=dict(paths=paths,publication_handle=handle,pid=os.getpid(),workspace=str(workspace),active=True)
        try:yield guard
        finally:guard['active']=False


def disk(root, phase, estimated_bytes=1024**3):
    root.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(root).free
    value = dict(time=stamp(), phase=phase, available_bytes=free, estimated_next_stage_bytes=estimated_bytes,
                 reserve_bytes=RESERVE, shortfall_bytes=max(0, RESERVE+estimated_bytes-free))
    dump(root/'disk_checks'/(str(time.time_ns())+'_'+phase+'.json'), value)
    if value['shortfall_bytes']:
        raise OSError('Insufficient space: '+json.dumps(value))
    return value


def configure_cli(batch_root):
    binding = read(batch_root/'engineering/qualified_cli.json')
    for name, digest in binding['verified_bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Qualified CLI source changed: '+name)
    runtime = binding['runtime']
    os.environ['A3GAME_CODEX_EXECUTABLE'] = runtime['path']
    os.environ['A3GAME_CODEX_EXECUTABLE_SHA256'] = runtime['sha256']


def freeze_inventory(workspace, batches):
    path = workspace/'inventory.json'
    if path.exists():
        saved = read(path)
        for name, digest in saved['inventory_bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Frozen candidate inventory changed')
        return saved
    bindings, entries = {}, []
    for source_batch in batches:
        inventory = source_batch/'inventory.json'; bindings[str(inventory)] = sha(inventory)
        original = read(inventory)
        if len(original['entries']) != 20:
            raise ValueError('Expected all twenty frozen identities')
        for entry in original['entries']:
            qualified = entry.get('tier') == 'S' and entry.get('actual_engine') in {'godot', 'three_js'}
            roots = [p for p in (source_batch/'runs').iterdir() if (p/'input_manifest.json').is_file()
                     and read(p/'input_manifest.json')['entry']['id'] == entry['id']]
            roots.sort(key=lambda p: ('native_slot_evidence_recovery' in p.name,
                                      'native_observation_reader_revision' in p.name,
                                      (p/'runtime/frame_index.jsonl').exists(), len(p.name)), reverse=True)
            recorded = [p for p in roots if (p/'runtime/frame_index.jsonl').exists()]
            entries.append(dict(entry=entry, source_batch=str(source_batch), in_scope=qualified,
                scope_reason='S original Godot/Three.js' if qualified else 'MISSING_DELIVERY_OR_ENGINE',
                historical_attempts=list(map(str, roots)), preferred_record=str(recorded[0]) if recorded else None,
                initial_stage='HISTORICAL_RECORD_REQUIRES_QUALIFICATION' if recorded else 'NEEDS_ENTRY_PLAN_RECORD'))
    result = dict(version=VERSION, created=stamp(), selection='Use frozen original candidates; never select on scores',
                  inventory_bindings=bindings, entries=entries)
    exclusive_json(path, result)
    return result


def contract_source(workspace, case, inventory, *, folder=None):
    """Only frozen requirements and author implementation, never runtime outcomes."""
    path = folder or workspace/'contracts'/case
    path.mkdir(parents=True, exist_ok=True)
    rows = [r for r in inventory['entries'] if r['entry']['case_id'] == case]
    if len(rows) != 2:
        from .mechanic_v3_scope import single_model_authorized
        if revisions.revision(workspace) != 'outcome_frame_v1' or not single_model_authorized(inventory, case, rows):
            raise ValueError('Pair contract must include both frozen model identities')
    bindings, parts, protocols = {}, [], []
    for row in rows:
        e = row['entry']; source_batch = Path(row['source_batch'])
        root = Path(e['project']) if e.get('project') else None
        if root is None or not root.is_dir():
            # A missing original has neither an engine nor a valid attempt to
            # derive. Its available counterpart supplies the common frozen
            # mechanism definitions; no synthetic engine/source is assigned.
            for source in (Path(e['requirement']), Path(e['frozen_rubric']),
                           source_batch/'inventory.json'):
                if source.is_file():bindings[str(source)] = sha(source)
            parts.append(e['method']+': no delivered project. Do not invent implementation.')
            continue
        if row['historical_attempts'] and case not in inventory.get('single_model_contract_cases', []):
            proto_path = Path(row['historical_attempts'][0])/'input/pilot_rubric.json'
            proto = read(proto_path)
            bindings[str(proto_path)] = sha(proto_path)
        else:
            # A never-started frozen candidate has no attempt. Reconstruct the
            # same effective Mechanic IDs from its locked original rubric; do
            # not invent an attempt, choose another delivery, or use runtime.
            from . import core12, endpoint_sparse
            original = batch.verify_protocol(source_batch, e)
            contract, planning_source = core12.load_sources(e)
            planning_source['scoring_protocol_sha256'] = core12.fingerprint(original)
            proto = core12.make_protocol(contract, original, planning_source)
            endpoint_sparse.freeze(proto)
            locked = read(source_batch/'protocol_lock.json')[case]
            locked_source = Path(locked['path'])
            if not locked_source.is_file():
                locked_source = source_batch/'protocols'/case/'rubric.json'
            if sha(locked_source) != locked['sha256']:
                raise ValueError('Retained contract protocol differs from original lock')
            for name in (source_batch/'protocol_lock.json', locked_source,
                         Path(e['frozen_rubric']), Path(planning_source['source_path'])):
                bindings[str(name)] = sha(name)
            dump(path/(e['method']+'.derived_protocol.json'), proto)
        protocols.append(proto)
        texts = []
        for file in sorted(root.rglob('*')):
            if not file.is_file() or file.suffix.lower() not in v3.SOURCE_SUFFIXES:
                continue
            rel = file.relative_to(root)
            if any(x in rel.parts for x in ('node_modules','.godot','.git','dist','build')):
                continue
            bindings[str(file)] = sha(file)
            texts.append('AUTHOR '+e['method']+' '+str(rel)+' SHA256 '+sha(file)+'\n'+''.join(
                f'{n}: {line}\n' for n,line in enumerate(file.read_text(errors='replace').splitlines(),1)))
        req = Path(e['requirement']);bindings[str(req)] = sha(req)
        parts.append('MODEL '+e['method']+'\nORIGINAL REQUIREMENT\n'+req.read_text()+'\n'+'\n'.join(texts))
    checks = [v3.mechanisms(p) for p in protocols]
    if not checks:raise ValueError('No delivered counterpart for frozen mechanic contract')
    expected = [(c['id'],c['requirement']) for c in checks[0]]
    if any([(c['id'],c['requirement']) for c in items] != expected for items in checks[1:]):
        raise ValueError('Paired frozen mechanic requirements disagree')
    text='\n'.join(parts)
    exclusive_json(path/'source_binding.json', dict(created=stamp(), case_id=case, bindings=bindings,
        policy='Contract formed from frozen rubric and explicitly selected original implementations; no runtime outcome or old verdict supplied',
        scope_binding=inventory.get('scope_binding'), models=[r['entry']['method'] for r in rows]))
    (path/'author_sources.txt').write_text(text)
    return path, protocols[0], text


CONTRACT_PROMPT = '''You define a paired frozen basic-function contract for an explicitly authorized new protocol whitebox-mechanic10-50-100.v3. You are NOT judging runtime and have NO runtime evidence. Use only frozen original requirements and the two author implementations below. Apply identical functional standards to Astra and Opus, regardless of their implementation completeness. Do not invent missing product features. Return the exact supplied JSON schema; read its file before responding. Each full_requirement must be copied byte-for-byte from CHECKS.requirement.
10% means valid implementation existence; 50% means the specific basic function was actually exercised and works correctly with no basic-function bug. 100% means every full requirement strictly proven. Define a genuinely basic representative path, not a smaller complete specification. Numeric deviation alone (correct target loses 11 health instead of required 10) may get 50%; wrong target, healing enemy on attack, fabricating reload resources are basic bugs. Separate these explicitly. For a negative/refusal mechanism, define the real precondition, consumed operation, and positive proof of correct rejection; unchanged state alone is insufficient. Automatic mechanisms may demonstrate sustained real outputs/pattern switching without a keyboard input. Held/delayed responses must use a source-grounded finite causal window, not an arbitrary convenient time. Include an explicit causal_window_basis explaining the bound from the original code/requirement; do not inspect any runtime files or scores. Preserve every basic failure condition relevant to the mechanism; do not demand all precise numbers or all boundaries for 50%. A started game, no crash, or animation alone proves no gameplay function. Each original atom stays a separate scored atom, even if it describes an edge case. REPRESENTATIVE PATH RULE (uniform correction, based only on user instructions): 50% requires ONE representative functional transaction or ONE correctly processed refusal branch of this mechanism. Do not require all alternative triggers, both directions, all modes, every combined subcase, positive-control gameplay, complete resource/expiry/reset/pause cycles, or all original edges as prerequisites to50%. For example, an actually processed full-magazine reload attempt correctly refused is sufficient basic rejection even without testing zero-reserve reload or a legal reload in the same record. Guard execution/consumed input plus refusal evidence is required; unchanged state alone never suffices. For automatic scan, actual detection/markers bound to real enemies may prove the basic scan; full expiry/pause-phase/type coverage belongs to100% unless an observed basic bug contradicts the claimed function. Correct-target attack and actual HP loss remain inseparable; animation alone never suffices. All known basic bugs still disqualify50%, including observed wrong-target/healing/resource fabrication, even outside the representative branch. Leave unexercised branches UNVERIFIED; do not equate lack of coverage with a product bug. Do not select the path from successful footage: none is supplied. Describe alternatives as sufficient alternatives, not cumulative mandatory steps. Preserve the full original requirement verbatim for100%. Return summary and checks only.
'''


def freeze_contract(workspace, case, inventory):
    if revisions.revision(workspace)=='outcome_frame_v1':
        from .mechanic_v3_outcome_runner import freeze
        return freeze(workspace,case,inventory)
    folder = revisions.contract_dir(workspace,case)
    if (folder/'frozen.json').exists():
        frozen = read(folder/'frozen.json')
        if sha(folder/'contract.json') != frozen['contract_sha256']:
            raise ValueError('Frozen basic contract changed')
        for name,digest in read(folder/'source_binding.json')['bindings'].items():
            if sha(Path(name)) != digest:raise ValueError('Contract source changed')
        return read(folder/'contract.json')
    if (folder/'model_calls').exists():
        raise ValueError('Previous contract attempt retained; diagnose before recovery')
    folder, proto, text = contract_source(workspace, case, inventory,folder=folder)
    (folder/'input').mkdir(exist_ok=True)
    schema=v3.contract_schema(proto)
    prompt=CONTRACT_PROMPT+'\nCHECKS\n'+json.dumps(v3.mechanisms(proto),ensure_ascii=False)+'\nAUTHOR SOURCES\n'+text
    if len(prompt.encode()) > 1000000:
        raise ValueError('Contract source exceeds bounded request; must partition without clipping')
    dump(folder/'planned_schema.json',schema)
    prompt+='\nEXACT SCHEMA FILE '+str(folder/'planned_schema.json')
    disk(folder,'contract',64*1024**2)
    result=call_codex(folder,name='basic_contract_v3',prompt=prompt,schema=schema,model=v3.MODEL,
        timeout=600,max_attempts=1,response_validator=lambda raw:v3.validate_contract(proto,raw))
    exclusive_json(folder/'contract.json',result)
    exclusive_json(folder/'frozen.json',dict(version=v3.CONTRACT_VERSION, case_id=case, created=stamp(),
        contract_sha256=sha(folder/'contract.json'), source_binding_sha256=sha(folder/'source_binding.json'),
        schema_sha256=sha(folder/'planned_schema.json'), model=v3.MODEL,
        historical_record_notice='按新冻结契约重新评价历史实录；契约晚于历史录制，早于新版runtime judge',
        runtime_evidence_supplied=False))
    return result


def link_tree(source, target, *, runtime=False):
    """Copy-on-write evidence view: link immutable files, never edit a linked file."""
    target.mkdir(parents=True,exist_ok=True)
    for file in source.rglob('*'):
        rel=file.relative_to(source)
        if runtime and any(part in ('node_modules','.godot','Library','Temp','obj') for part in rel.parts):
            continue
        if file.is_symlink():
            raise ValueError('Evidence view refuses symlinks: '+str(file))
        if file.is_file():
            dest=target/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            os.link(file,dest)


def source_scope_authorization(entry, workspace=None):
    """Keep the original S default; M requires the SHA-bound active selection."""
    if entry['actual_engine'] not in {'godot', 'three_js'}:
        raise ValueError('Not a frozen native engine identity')
    if entry['tier'] == 'S':return None
    if entry['tier'] != 'M' or workspace is None or revisions.revision(Path(workspace)) != 'outcome_frame_v1':
        raise ValueError('Non-S source requires explicit outcome scope authorization')
    from .mechanic_v3_scope import load_inventory
    inventory = load_inventory(workspace)
    if entry['id'] not in inventory.get('primary_selection', []):
        raise ValueError('M source is outside the explicit active selection')
    row = next((row for row in inventory['entries'] if row['entry']['id'] == entry['id']), None)
    fields = ('id', 'method', 'case_id', 'actual_engine', 'tier', 'project')
    if (row is None or not row['in_scope'] or entry['method'] != 'Opus' or not entry.get('project')
            or any(entry.get(key) != row['entry'].get(key) for key in fields)):
        raise ValueError('M source identity differs from frozen supplemental delivery')
    return dict(revision='outcome_frame_v1', scope_binding=inventory['scope_binding'],
                entry_id=entry['id'], tier='M', original_mechanism_weights_unchanged=True)


def qualify_source(source, *, workspace=None):
    batch.verify_inputs(source);batch.verify_runtime_sources(source)
    proto=read(source/'input/pilot_rubric.json');manifest=read(source/'evidence_manifest.json')
    entry=read(source/'input_manifest.json')['entry'];engine=entry['actual_engine']
    authorization=source_scope_authorization(entry, workspace)
    from . import godot_native_telemetry_reuse as telemetry_reuse
    if (source/telemetry_reuse.PROVENANCE).exists():
        acceptance=telemetry_reuse.verify_origin(source)
    else:
        acceptance=sparse_native.verify_acceptance(source.parents[1],engine)
    from .pending_publication import cleanup_source
    cleanup,origin=cleanup_source(source)
    if not cleanup:raise ValueError('Missing real cleanup evidence')
    gate=batch.validate_capture_bundle(source,manifest,proto)
    isolated_slot=gate.get('issues')==['Invalid action evidence index: endpoint frames are not the predeclared final observations']
    difference=None
    if not gate['valid']:
        if not isolated_slot:raise ValueError('Historical raw capture is invalid: '+str(gate))
        from .native_slot_recovery import slot_difference
        difference=slot_difference(proto,read(source/'sol_plan.json'),batch.load_lines(source/'runtime/frame_index.jsonl'),manifest,
                                   sparse_evidence.audit_capture(source/'runtime'))
    bindings={str(source/name):sha(source/name) for name in ('input_manifest.json','input/pilot_rubric.json',
        'sol_plan.json','evidence_manifest.json','trace_summary.json','runtime/action_frame_links.json',
        'runtime/capture_schedule.json','runtime/frame_index.jsonl','runtime/actions.jsonl','runtime/state_trace.jsonl','runtime/event_trace.jsonl')}
    for file,digest in cleanup.items():bindings[str((source/file).resolve())]=digest
    if (source/telemetry_reuse.PROVENANCE).exists():
        bindings[str(source/telemetry_reuse.PROVENANCE)]=sha(source/telemetry_reuse.PROVENANCE)
    if (source/'native_capture_admission.json').exists():
        from .engine_scoped_capture import qualify as qualify_engine_scope
        bindings.update(qualify_engine_scope(source))
    return dict(time=stamp(),source=str(source),entry_id=entry['id'],engine=engine,source_bindings=bindings,
                native_acceptance=acceptance,original_capture_gate=gate,slot_delivery_correction=difference,
                cleanup_bindings=cleanup,cleanup_origin=origin,recording='REUSED_HISTORICAL_REAL_RECORD',
                explicit_scope_authorization=authorization,
                notice='按新冻结契约重新评价历史实录；不是新录制；未复用旧判词')


def prepare_view(workspace, row):
    source=Path(row['preferred_record']);ident=row['entry']['id'];root=workspace/'runs'/ident
    if (root/'source_qualification.json').exists():
        receipt=read(root/'source_qualification.json')
        for name,digest in receipt['source_bindings'].items():
            if sha(Path(name))!=digest:raise ValueError('Historical source binding changed')
        return root
    if root.exists():raise ValueError('Incomplete view retained; diagnose before recovery')
    qualification=qualify_source(source,workspace=workspace)
    root.mkdir(parents=True);disk(root,'evidence_view',1024**3)
    link_tree(source/'input',root/'input')
    link_tree(source/'runtime',root/'runtime',runtime=True)
    for name in ('input_manifest.json','sol_plan.json','trace_summary.json'):
        shutil.copy2(source/name,root/name)
    # Validate native acceptance at the new data root using the same exact sources.
    for engine in ('godot','three_js'):
        src=source.parents[1]/'engineering/native_acceptance'/(engine+'.json')
        dst=workspace/'engineering/native_acceptance'/(engine+'.json')
        if src.exists():
            dst.parent.mkdir(parents=True,exist_ok=True)
            if dst.exists() and dst.read_bytes()!=src.read_bytes():
                raise ValueError('Conflicting native acceptance')
            if not dst.exists():shutil.copy2(src,dst)
    proto=read(root/'input/pilot_rubric.json');manifest=read(source/'evidence_manifest.json')
    if qualification['slot_delivery_correction']:
        manifest=sparse_evidence.deliver(root,proto,manifest)
    else:
        # Unchanged delivery pixels from the qualified source; not a replay.
        for sheet in manifest['delivery_sheets']:
            p=checked_path(source,sheet['path']);dest=root/sheet['path'];dest.parent.mkdir(parents=True,exist_ok=True)
            os.link(p,dest)
    sparse_evidence.validate(root,proto,manifest)
    dump(root/'evidence_manifest.json',manifest)
    qualification.update(view_manifest_sha256=sha(root/'evidence_manifest.json'),
        corrected_delivery_validated=True,raw_record_reused=True,new_recording=False)
    exclusive_json(root/'source_qualification.json',qualification)
    return root


def prepare_case(workspace, ident, inventory):
    row=next(r for r in inventory['entries'] if r['entry']['id']==ident)
    if not row['in_scope'] or not row['preferred_record']:
        raise ValueError('Identity needs original entry/plan/native recording first')
    if not (revisions.contract_dir(workspace,row['entry']['case_id'])/'frozen.json').exists():
        raise ValueError('Freeze the paired basic contract before runtime evaluation')
    return prepare_view(workspace,row)


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--batch',type=Path,action='append',required=True)
    p.add_argument('--contract-case',action='append',default=[])
    p.add_argument('--prepare',action='append',default=[])
    p.add_argument('--plan-native',action='append',default=[])
    p.add_argument('--record-native',action='append',default=[])
    p.add_argument('--judge',action='append',default=[])
    args=p.parse_args(argv);workspace=args.workspace.resolve();batches=[x.resolve() for x in args.batch]
    workspace.mkdir(parents=True,exist_ok=True)
    with held(workspace,batches[0]) as publication_guard:
        configure_cli(batches[0]);inventory=freeze_inventory(workspace,batches)
        for case in args.contract_case:
            freeze_contract(workspace,case,inventory)
            print(json.dumps(dict(case=case,stage='CONTRACT_FROZEN',time=stamp())),flush=True)
        for ident in args.prepare:
            root=prepare_case(workspace,ident,inventory)
            print(json.dumps(dict(identity=ident,stage='HISTORICAL_RECORD_QUALIFIED',root=str(root))),flush=True)
        for ident in dict.fromkeys(args.plan_native+args.record_native):
            from . import mechanic_v3_native
            row=next(r for r in inventory['entries'] if r['entry']['id']==ident)
            if ident in args.record_native:mechanic_v3_native.record(workspace,row)
            else:mechanic_v3_native.prepare_and_plan(workspace,row)
        for ident in args.judge:
            from .mechanic_v3_execution import judge_and_publish,verify_publication
            if (revisions.publication_dir(workspace)/(ident+'.json')).exists():
                verify_publication(workspace,ident)
                print(json.dumps(dict(identity=ident,stage='SKIP_SCORED_V3')),flush=True)
                continue
            root=workspace/'runs'/ident
            if not (root/'source_qualification.json').is_file() or not read(root/'source_qualification.json').get('new_recording'):
                root=prepare_case(workspace,ident,inventory)
            judge_and_publish(workspace,root,inventory,publication_guard=publication_guard)


if __name__ == '__main__':
    main()
