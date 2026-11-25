"""Formal source-contract, complete native delivery, judge and publication entry.

Workspace paths are data only. This entry never launches other-column judges,
executes workspace code, edits original projects, or replaces old publications.
"""
from __future__ import annotations
import argparse
import copy
import fcntl
import hashlib
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from . import gameness_v3 as policy
from . import gameness_v3_static as static_review
from . import gameness_v3_rubric as authored_rubric
from . import gameness_v3_independent as independent
from . import gameness_v3_original as original_rubric
from . import batch, core12, endpoint_sparse, frame_budget, sparse_evidence
from . import mechanic_v3_runner as runner, mechanic_v3_full_scope as scope
from . import mechanic_v3_execution as shared_execution
from .mechanic_v3_image_transport import encode
from .mechanic_v3_judge_transport import group, selected_task
from .codex import call_codex, saved_model_response, READ_ONLY_EVAL_INSTRUCTIONS
from . import evaluation_model_profile as eval_models
from .protocol import dump, sha, checked_path, load_lines
from .action_links import frame_id

TABLES=('gameness_scores.md','gameness_comparison.md')
EXCLUDED={'node_modules','.godot','.git','dist','build','Library','Temp','obj','Intermediate','DerivedDataCache'}



def workspace_policy(workspace):
    """Resolve an explicitly initialized protocol without mutating module state."""
    version=runner.read(Path(workspace)/'gameness_assessment_revision.json')['scoring_protocol']
    if version==policy.VERSION:return policy
    from . import gameness_v4
    if version==gameness_v4.VERSION:return gameness_v4
    raise ValueError('Unknown explicit Gameness scoring protocol')


def task_prefix(selected):
    return 'gameness_v4' if selected.VERSION.endswith('.v4') else 'gameness_v3'


def verify_bindings(bindings):
    for name,digest in bindings.items():
        if sha(Path(name))!=digest:raise ValueError('Immutable source changed: '+name)


def source_files(project):
    # Source completeness, not score-based excerpting; original vendor/runtime
    # sources remain when delivered as author source. Generated caches excluded.
    return [p for p in sorted(project.rglob('*')) if p.is_file()
            and p.suffix.lower() in policy.SOURCE_SUFFIXES
            and not set(p.relative_to(project).parts)&EXCLUDED]


def initialize(workspace, scope_workspace, rubric_policy=None, *, scoring_policy=policy):
    policy=scoring_policy
    inventory=scope.load(scope_workspace)
    auth=scope_workspace/'columns_authorization_20261103.json'
    value=runner.read(auth)
    if value['authorized_columns']!=['Mechanic','Gameness'] or value['scope_binding']!=inventory['full_scope_binding']:
        raise ValueError('Explicit new two-column source scope required')
    workspace.mkdir(parents=True,exist_ok=True)
    revision=dict(scoring_protocol=policy.VERSION,assessment_revision=policy.REVISION,model=policy.MODEL,
        scope_workspace=str(scope_workspace),scope_binding=inventory['full_scope_binding'],
        authorization_path=str(auth),authorization_sha256=sha(auth),
        authorized_columns=['Gameness'],other_columns='NOT_REEVALUATED',eight_column_total=None)
    path=workspace/'gameness_assessment_revision.json'
    # Existing workspaces keep their frozen rubric. New workspaces explicitly
    # bind the authored Gameness-only revision; no Mechanic files are changed.
    if rubric_policy is None:
        rubric_policy=(runner.read(path).get('gameness_rubric_policy') if path.exists()
                       else original_rubric.VERSION if policy.VERSION.endswith('.v4') else authored_rubric.VERSION)
    if policy.VERSION.endswith('.v4'):
        if rubric_policy!=original_rubric.VERSION:raise ValueError('Gameness v4 requires ALL original rubric checks')
        from .gameness_v4_rubric import freeze as freeze_rubric
        revision['original_rubric_manifest']=freeze_rubric(workspace,inventory)
    if rubric_policy == original_rubric.VERSION:
        revision.update(gameness_rubric_policy=rubric_policy,
            gameness_rubric_bindings={str(Path(r['entry']['frozen_rubric'])):sha(Path(r['entry']['frozen_rubric']))
                for r in inventory['entries'] if r['in_scope']})
    elif rubric_policy is not None:
        rubric_module=authored_rubric.policy_module(rubric_policy)
        rubric_bindings={}
        for directory in sorted({r['entry']['case_directory'] for r in inventory['entries'] if r['in_scope']}):
            value,bound=rubric_module.load(directory)
            rubric_bindings.update(value['source_bindings']);rubric_bindings.update(bound)
        revision.update(gameness_rubric_policy=rubric_policy,gameness_rubric_bindings=rubric_bindings)
    if path.exists():
        if runner.read(path)!=revision:raise ValueError('Existing Gameness revision differs')
    else:runner.exclusive_json(path,revision)
    original=runner.read(Path(inventory['full_scope_binding']['path']))
    source_workspace=Path(original['source_workspace'])
    for name in ('native_capture_configuration.json',):
        src=scope_workspace/name;dst=workspace/name
        if dst.exists() and dst.read_bytes()!=src.read_bytes():raise ValueError('Native configuration conflict')
        if not dst.exists():shutil.copy2(src,dst)
    return inventory


def load(workspace):
    policy=workspace_policy(workspace)
    value=runner.read(workspace/'gameness_assessment_revision.json')
    if value['scoring_protocol']!=policy.VERSION or value['model']!=policy.MODEL:
        raise ValueError('Not an explicit Gameness v3 workspace')
    if sha(Path(value['authorization_path']))!=value['authorization_sha256']:
        raise ValueError('Gameness authorization changed')
    inventory=scope.load(Path(value['scope_workspace']))
    if inventory['full_scope_binding']!=value['scope_binding']:raise ValueError('Gameness scope changed')
    verify_bindings(value.get('gameness_rubric_bindings',{}))
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_rubric import verify
        verify(workspace,inventory)
    return inventory


def contract_dir(workspace,case):return workspace/'gameness_contracts'/policy.REVISION/case


def source_protocol(row,workspace=None):
    if workspace is not None and row['entry']['method']=='Kimi':
        from .mechanic_v3_kimi_scope import verify_sources
        verify_sources(Path(runner.read(workspace/'gameness_assessment_revision.json')['scope_workspace']),row)
    original,bindings=_original_source_protocol(row)
    if workspace is not None:
        original,bound=authored_rubric.scoring_protocol(workspace,original,row['entry'])
        bindings.update(bound)
        if workspace_policy(workspace).VERSION.endswith('.v4'):
            from .gameness_v4_rubric import validate_protocol
            validate_protocol(workspace,row['entry']['case_id'],original)
    return original,bindings


def _original_source_protocol(row):
    for path in row.get('historical_attempts',[])+row.get('record_candidates',[]):
        path=Path(path)/'input/pilot_rubric.json'
        if path.is_file():return runner.read(path),{str(path):sha(path)}
    # Freeze only this column's original criteria, never reconstruct the
    # unrelated Mechanic planner/tier policy for deliveries without history.
    e=row['entry'];original=batch.verify_protocol(Path(row['source_batch']),e)
    return original,{str(Path(e['frozen_rubric'])):sha(Path(e['frozen_rubric']))}


def freeze(workspace,case,inventory):
    policy=workspace_policy(workspace)
    folder=contract_dir(workspace,case);folder.mkdir(parents=True,exist_ok=True)
    if (folder/'frozen.json').exists():
        frozen=runner.read(folder/'frozen.json');verify_bindings(runner.read(folder/'source_binding.json')['bindings'])
        if frozen.get('contract_source_transport'):
            from .gameness_v4_contract_source_transport import verify as verify_transport
            verify_transport(frozen['contract_source_transport'])
        if frozen.get('contract_chunk_transport'):
            from .gameness_v4_contract_chunks import verify_delivery
            from .gameness_v4_frozen_manifest import verify_frozen_delivery, verify_accepted_contract
            verify_frozen_delivery(folder, frozen['contract_chunk_transport'])
            verify_accepted_contract(folder)
        if frozen.get('contract_metadata_recovery'):
            if policy.VERSION.endswith('.v4'):
                from .gameness_v4_contract_source_transport import verify_prior_recovery
                verify_prior_recovery(folder,frozen['contract_metadata_recovery'])
            else:
                from .gameness_v3_contract_metadata import verify
                verify(frozen['contract_metadata_recovery'])
        if sha(folder/'contract.json')!=frozen['contract_sha256']:raise ValueError('Gameness contract changed')
        contract=runner.read(folder/'contract.json')
        proto=runner.read(folder/'frozen_protocol.json')
        (independent if independent.active(proto) else policy).validate_contract(proto,contract)
        return contract
    rows=[r for r in inventory['entries'] if r['entry']['case_id']==case and r['in_scope']]
    if not rows:raise ValueError('No authorized original sources')
    bindings={};parts=[];protocols=[]
    for row in rows:
        e=row['entry'];proto,bound=source_protocol(row,workspace);bindings.update(bound);protocols.append(proto)
        project=Path(e['project']) if e.get('project') else None
        req=Path(e['requirement']);bindings[str(req)]=sha(req)
        parts.append('MODEL '+e['method']+' ORIGINAL REQUIREMENT\n'+req.read_text())
        if project is None or not project.is_dir():parts.append('NO ORIGINAL DELIVERY; do not invent source');continue
        for file in source_files(project):
            bindings[str(file)]=sha(file)
            parts.append('AUTHOR '+e['method']+' '+str(file.relative_to(project))+' SHA256 '+sha(file)+'\n'
                +''.join(f'{n}: {line}\n' for n,line in enumerate(file.read_text(errors='replace').splitlines(),1)))
    proto=protocols[0];expected=policy.criteria(proto)
    if any(policy.criteria(p)!=expected for p in protocols[1:]):
        raise ValueError('Cross-model original Gameness IDs/requirements/groups disagree')
    text='\n'.join(parts)
    binding=dict(bindings=bindings,models=[r['entry']['method'] for r in rows],
        scope_binding=inventory['full_scope_binding'],runtime_evidence_supplied=False,old_verdict_supplied=False)
    for name,value in [('source_binding.json',binding),('frozen_protocol.json',proto)]:
        path=folder/name
        if path.exists() and runner.read(path)!=value:raise ValueError('Retained source packet differs')
        if not path.exists():runner.exclusive_json(path,value)
    source_path=folder/'author_sources.txt'
    if source_path.exists() and source_path.read_text()!=text:raise ValueError('Retained author source changed')
    if not source_path.exists():source_path.write_text(text)
    contract_policy=independent if independent.active(proto) else policy
    schema=contract_policy.contract_schema(proto);schema_path=folder/'planned_schema.json';dump(schema_path,schema)
    name=task_prefix(policy)+'_source_contract';call_folder=folder/'model_calls'/name
    prompt=contract_policy.CONTRACT_PROMPT+'\nCHECKS\n'+json.dumps(expected,ensure_ascii=False)+'\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '+str(schema_path)
    source_transport=None
    chunk_transport=None
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_contract_read_manifest_recovery import apply as service_packet
        prompt,chunk_transport=service_packet(folder,prompt,text)
        if chunk_transport is None:
            from .gameness_v4_contract_source_transport import apply as source_packet
            prompt,source_transport=source_packet(folder,prompt,text)
    if len(prompt.encode())>1000000:raise ValueError('Full source packet exceeds cap; partition losslessly, never clip')
    runner.disk(folder,'gameness_source_contract',64*1024**2)
    (folder/'input').mkdir(exist_ok=True)
    recovery=None
    def validate_contract_response(raw):
        if chunk_transport is not None:
            from .gameness_v4_contract_chunks import verify_delivery
            verify_delivery(chunk_transport,call_folder)
        contract_policy.validate_contract(proto,raw)
    if call_folder.exists():
        if not (call_folder/'accepted_response.json').exists():
            error_path=call_folder/'validation_error.json'
            from .gameness_v4_contract_service_recovery import AUTH as service_auth
            if policy.VERSION.endswith('.v4') and (folder/service_auth).is_file():
                from .gameness_v4_contract_read_manifest_recovery import recover
            elif (policy.VERSION.endswith('.v4') and error_path.is_file()
                    and runner.read(error_path).get('exception')=='Freeze basic bugs and trigger alternatives'):
                from .gameness_v4_contract_correction import recover
            elif (policy.VERSION.endswith('.v4') and error_path.is_file()
                    and runner.read(error_path).get('exception')=='Original Gameness identity/requirement changed'):
                from .gameness_v4_contract_identity_correction import recover
            else:
                from .gameness_v3_contract_metadata import recover
            contract,recovery=recover(folder,proto,prompt,schema)
        else:
            if (call_folder/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+prompt:raise ValueError('Retained contract request changed')
            contract=runner.read(saved_model_response(folder,name));validate_contract_response(contract)
    else:
        runner.configure_cli(Path(rows[0]['source_batch']))
        contract=call_codex(folder,name=name,prompt=prompt,schema=schema,model=policy.MODEL,timeout=900,max_attempts=1,
            response_validator=validate_contract_response)
    if not (folder/'contract.json').exists():runner.exclusive_json(folder/'contract.json',contract)
    runner.exclusive_json(folder/'frozen.json',dict(protocol=policy.VERSION,revision=policy.REVISION,case_id=case,
        created=runner.stamp(),contract_sha256=sha(folder/'contract.json'),source_binding_sha256=sha(folder/'source_binding.json'),
        original_protocol_sha256=sha(folder/'frozen_protocol.json'),model=policy.MODEL,
        runtime_evidence_supplied=False,old_verdict_supplied=False,source_only_common_standard=True,
        **({'contract_source_transport':source_transport} if source_transport else {}),
        **({'contract_chunk_transport':chunk_transport} if chunk_transport else {}),
        **({'contract_metadata_recovery':recovery} if recovery else {})))
    print(json.dumps(dict(case=case,stage='GAMENESS_V3_CONTRACT_FROZEN')),flush=True)
    return contract


def prepare(workspace,row,source,*,source_repair=None):
    policy=workspace_policy(workspace)
    source=source.resolve();root=workspace/'runs'/row['entry']['id']
    # Qualification goes back to the original accepted native take, not a score.
    if (source/'source_qualification.json').exists():
        parent=runner.read(source/'source_qualification.json');verify_bindings(parent['source_bindings'])
        source=Path(parent['source'])
    value=runner.read(source/'input_manifest.json')['entry']
    if not scope.same_original(row['entry'],value):raise ValueError('Historical record is not the frozen original')
    if policy.VERSION.endswith('.v4') and (source/'source_qualification.json').exists():
        from .qualified_history import prepare_view
        retained=root/'source_qualification.json'
        if retained.is_file() and Path(runner.read(retained)['source']).resolve()!=source:
            from .gameness_v4_author_entry_source import prepare as recover_source
            root=recover_source(workspace,row,source,source_repair)
        else:
            root=prepare_view(workspace,row,source)
    else:
        root=runner.prepare_view(workspace,dict(row,preferred_record=str(source)))
    proto=runner.read(root/'input/pilot_rubric.json');common=runner.read(contract_dir(workspace,row['entry']['case_id'])/'frozen_protocol.json')
    scoring,bound=authored_rubric.scoring_protocol(workspace,proto,row['entry'])
    if policy.criteria(scoring)!=policy.criteria(common):raise ValueError('Record Gameness rubric differs from frozen source-only contract')
    if 'gameness_rubric' in scoring:
        path=root/'gameness_scoring_protocol.json'
        if path.exists() and runner.read(path)!=scoring:raise ValueError('Retained scoring rubric changed')
        if not path.exists():runner.exclusive_json(path,scoring)
    return root


def complete_sources(root,manifest):
    result=copy.deepcopy(manifest);existing={i['path']:i for i in result['items']}
    for file in source_files(root/'input/project'):
        rel=str(file.relative_to(root))
        if rel in existing:
            item=existing[rel]
            if item['sha256']!=sha(file):raise ValueError('Author source manifest changed')
            item['type']='source'
        else:
            result['items'].append(dict(id='SRC:'+str(file.relative_to(root/'input/project')),
                path=rel,type='source',sha256=sha(file)))
    return result


def delivery(root,protocol,manifest,parent):
    """All preregistered real windows, lossless/native-size, never selected by success."""
    from .mechanic_v3_outcome_evidence import validate_pixels
    sparse_evidence.validate(root,protocol,manifest)
    result=complete_sources(root,manifest);subset=result['evidence_sets'][parent]
    wanted=set(subset['frames'])
    for window in manifest['sparse_capture_audit']['windows'].values():wanted.update(window['frame_ids'])
    from .gameness_v4_empty_evidence_recovery import supplement
    additional,handoff=supplement(root,manifest,parent)
    wanted.update(additional)
    rows=load_lines(root/'runtime/frame_index.jsonl');indexed={frame_id(r,n):r for n,r in enumerate(rows,1)}
    if not wanted<=set(indexed):raise ValueError('Predeclared frame missing')
    # Reuse the formal native sheet builder (no change to pixel/capture rules),
    # with a Gameness-specific immutable transport policy rather than a Mechanic contract.
    from PIL import Image,ImageDraw
    identifiers=[frame_id(r,n) for n,r in enumerate(rows,1) if frame_id(r,n) in wanted]
    subset['frames']={};subset['delivery_sheets']=[];proofs=[]
    for start in range(0,len(identifiers),4):
        block=identifiers[start:start+4];sizes=[]
        for ident in block:
            with Image.open(checked_path(root/'runtime',indexed[ident]['path'])) as im:sizes.append(im.size)
        width=max(s[0] for s in sizes);height=max(s[1] for s in sizes)
        sheet=Image.new('RGB',(2*width,2*(height+26)),'#101010');draw=ImageDraw.Draw(sheet)
        relative=Path('delivery/gameness_v3_native')/parent/f'sheet_{start//4+1:03d}.png';path=root/relative
        for tile,ident in enumerate(block):
            r=indexed[ident];raw=checked_path(root/'runtime',r['path']);left=tile%2*width;top=tile//2*(height+26)
            draw.text((left+6,top+5),f'{ident} | {r["t_ms"]} ms',fill='white')
            with Image.open(raw) as im:
                iw,ih=im.size;sheet.paste(im.convert('RGB'),(left,top+26))
            item=dict(id=ident,path=str(raw.relative_to(root)),type='frame',sha256=sha(raw),t_ms=r['t_ms'],
                frame_id=ident,delivered_to_judge=True,delivery_sheet=str(relative),tile=tile,tile_rect=[left,top+26,iw,ih])
            for key in ('session_id','client_role'):
                if key in r:item[key]=r[key]
            subset['frames'][ident]=item
        path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists():
            with Image.open(path) as old:
                if old.convert('RGB').tobytes()!=sheet.tobytes() or old.size!=sheet.size:raise ValueError('Retained sheet differs')
        else:sheet.save(path)
        webp=relative.with_suffix('.webp');proofs.append(encode(path,root/webp))
        subset['delivery_sheets'].append(dict(path=str(webp),sha256=sha(root/webp)))
        for ident in block:subset['frames'][ident]['delivery_sheet']=str(webp)
    subset['delivered_frame_count']=len(wanted)
    union={i['id']:i for s in result['evidence_sets'].values() for i in s['frames'].values()}
    result['items']=sorted([i for i in result['items'] if i['type']!='frame'],key=lambda i:(i['type']!='source',i['path']))+list(union.values())
    validate_pixels(root,subset,indexed,wanted)
    proof_dir='gameness_native_delivery_handoff' if handoff is not None else 'gameness_native_delivery'
    dump(root/'requests'/proof_dir/parent/'proof.json',dict(
        original_manifest_sha256=sha(root/'evidence_manifest.json'),all_predeclared_frame_ids=identifiers,
        native_pixels_verified=True,lossless_images=proofs,source_selection='all original authored source, no clipping',
        **({'native_evidence_handoff':handoff} if handoff is not None else {})))
    return result


def request(root,protocol,manifest,contract,frozen,name,parent,specs,review=None, *, scoring_policy=policy):
    policy=scoring_policy
    # Qualify the record against its ORIGINAL frozen native capture protocol.
    # Scoring targets are separately source-bound; never relabel a capture plan.
    native_protocol=runner.read(root/'input/pilot_rubric.json')
    manifest=delivery(root,native_protocol,manifest,parent)
    png_authorization=root/'engineering/gameness_png_transport'/(name+'.json')
    if png_authorization.exists():
        from PIL import Image
        auth=runner.read(png_authorization);verify_bindings(auth['source_bindings'])
        if auth['format']!='original_native_pixels_png':raise ValueError('Unknown Gameness image recovery')
        subset=manifest['evidence_sets'][parent];mapping={};proof=[]
        for page in subset['delivery_sheets']:
            before=root/page['path'];after=before.with_suffix('.png')
            with Image.open(before) as a,Image.open(after) as b:
                if a.size!=b.size or a.convert('RGB').tobytes()!=b.convert('RGB').tobytes():
                    raise ValueError('PNG delivery differs from original native pixels')
            old=page['path'];page.update(path=str(after.relative_to(root)),sha256=sha(after))
            mapping[old]=page['path'];proof.append(dict(webp_path=old,webp_sha256=sha(before),png_path=page['path'],png_sha256=sha(after),native_pixels_identical=True))
        for item in list(subset['frames'].values())+manifest['items']:
            if item.get('delivery_sheet') in mapping:item['delivery_sheet']=mapping[item['delivery_sheet']]
        dump(root/'requests'/name/'png_delivery_proof.json',dict(authorization_sha256=sha(png_authorization),images=proof,all_predeclared_frames_preserved=True))
    selected=frame_budget.for_task(manifest,parent)
    runtime=copy.deepcopy(selected);runtime['items']=[i for i in runtime['items'] if i['type']!='source']
    body,omitted=batch.packet(root,runtime,False);full_sources=[]
    for item in selected['items']:
        if item['type']!='source':continue
        path=checked_path(root,item['path'])
        if sha(path)!=item['sha256']:raise ValueError('Complete source SHA changed')
        text=''.join(f'{n}: {line}\n' for n,line in enumerate(path.read_text(errors='replace').splitlines(),1))
        body+='\nEVIDENCE '+item['id']+' (complete original source)\n'+text
        full_sources.append(dict(id=item['id'],path=item['path'],sha256=item['sha256'],line_count=len(path.read_text(errors='replace').splitlines())))
    exact_transport=None
    runtime_chunks=None
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_runtime_read_manifest import apply as chunk_packet
        body,runtime_chunks=chunk_packet(root,name,body)
        if runtime_chunks is None:
            from .gameness_v4_preflight_recovery import apply as exact_packet
            body,exact_transport=exact_packet(root,name,body)
    rules=batch.judge_citation_rules(root,selected,omitted,False)
    new_policy=independent.active(protocol)
    staged_original=review is not None and 'gameness_rubric' not in protocol
    original=(independent.judgment_schema(specs,rules,selected,contract,review is not None) if new_policy else
        original_rubric.runtime_schema(specs,rules,selected) if staged_original else
        static_review.runtime_schema(specs,rules,selected) if review is not None else policy.judgment_schema(specs,rules,selected))
    schema,proof=group(original)
    images=[root/i['path'] for i in selected['items'] if i['type']=='reference']+[root/i['path'] for i in selected['delivery_sheets']]
    # v1 accepted prompts remain byte-identical. v2 isolates static provenance
    # from this request's actual runtime image delivery, never relabels old calls.
    runtime_binding=(dict(stage='earlier_source_only_freeze', provenance={k:v for k,v in frozen.items()
        if k not in {'runtime_evidence_supplied','old_verdict_supplied'}}) if new_policy else
        original_rubric.runtime_binding(frozen) if staged_original else frozen)
    instruction=independent.INSTRUCTION if new_policy else policy.INSTRUCTION
    runtime_notice=('\nCURRENT RUNTIME DELIVERY: native images are attached below; all declared real frames and complete author sources are delivered. '
        'Earlier source-only freeze is provenance, not current runtime availability.\n' if new_policy else
        '\n'+original_rubric.DELIVERY_NOTICE if staged_original else '')
    prompt=(instruction+runtime_notice+'\nEXACT SCHEMA FILE (only allowed read): '+str(root/'model_calls'/name/'schema.json')
        +'\nFROZEN SOURCE-ONLY CONTRACT BINDING:\n'+json.dumps(runtime_binding,ensure_ascii=False)
        +('\nCOMMON INDEPENDENT GAMENESS CONTRACT (only exact time/fine space diagnostic):\n' if new_policy else '\nCOMMON GAMENESS CONTRACT (original exact requirements are diagnostic ONLY):\n')+json.dumps(contract,ensure_ascii=False)
        +('\nIMMUTABLE FIRST-STAGE SOURCE REVIEW (already validated; do not rejudge source_existence):\n'
            +json.dumps({s['id']:review['checks'][s['id']] for s in specs},ensure_ascii=False)
            +('\nReturn basic_function/result_outcome/diagnostics AND scope_proof per criterion; top-level runtime_delivery_status is required. ' if new_policy else '\nReturn runtime_delivery_status plus basic_function/result_outcome/diagnostics per criterion. ' if staged_original else '\nReturn only basic_function/result_outcome/diagnostics per criterion. ')+'Trigger recipes are planning inputs, NOT proof of actual observation.' if review is not None else '')
        +'\nACTUAL COMPLETE AUTHOR SOURCE AND NATIVE CONTEXT:\n'+body
        +'\nIMAGE MAP:\n'+json.dumps(selected['delivery_sheets'],ensure_ascii=False)
        +'\nCHECKS (only these frozen Gameness criteria):\n'+json.dumps(specs,ensure_ascii=False))
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_inline_schema import apply as inline_schema
        prompt=inline_schema(root,name,prompt,schema)
        if runtime_chunks is not None:
            from .gameness_v4_runtime_read_manifest import allow_reads
            prompt=allow_reads(prompt)
    actual=frame_budget.validate_request(root,parent,native_protocol,manifest,images,READ_ONLY_EVAL_INSTRUCTIONS+prompt)
    actual.update(task=name,column='Gameness',scoring_protocol=policy.VERSION,contract_sha256=frozen['contract_sha256'],
        complete_author_sources=full_sources,all_predeclared_frames_delivered=True)
    if runtime_chunks is not None:
        actual['runtime_text_chunks']=runtime_chunks
    if exact_transport is not None:
        actual['exact_evidence_transport']=exact_transport
    if review is not None:
        actual['source_review_sha256']=sha(root/'gameness_source_review.json')
    if 'gameness_rubric' in protocol:
        actual.update(gameness_rubric=protocol['gameness_rubric'],
            scoring_protocol_sha256=sha(root/'gameness_scoring_protocol.json'),
            scored_criterion_ids=[s['id'] for s in specs],
            native_capture_protocol_sha256=sha(root/'input/pilot_rubric.json'),
            coverage_notice='All real declared frames delivered; new rubric does not imply new triggers occurred')
    folder=root/'requests'/name
    dump(folder/'actual_delivery.json',actual);dump(folder/'selected_manifest.json',selected)
    dump(folder/'citation_rules.json',rules);dump(folder/'original_schema.json',original);dump(folder/'schema_transport.json',proof)
    return selected,rules,images,schema,prompt


def evaluate_task(workspace,root,protocol,manifest,contract,frozen,task,review=None, *, scoring_policy=policy):
    policy=scoring_policy
    name,parent,specs=selected_task(root,task)
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_runtime_read_manifest import selected_task as text_task
        name,parent,specs=text_task(root,(name,parent,specs))
    if policy.VERSION.endswith('.v4') and not (root/'model_calls'/name).exists():
        from .gameness_v4_inline_schema import admit
        admit(root,name)
    selected,rules,images,schema,prompt=request(root,protocol,manifest,contract,frozen,name,parent,specs,review=review,scoring_policy=policy)
    evaluate_response=lambda raw: (independent.evaluate(root,protocol,selected,rules,contract,raw,specs,review)
        if independent.active(protocol) else
        original_rubric.evaluate(root,protocol,selected,rules,contract,raw,specs,review,scoring_policy=policy)
        if review is not None and 'gameness_rubric' not in protocol else static_review.runtime_evaluate(root,protocol,selected,rules,contract,raw,specs,review,scoring_policy=policy)
        if review is not None else policy.evaluate(root,protocol,selected,rules,contract,raw,specs))
    original_evaluate_response=evaluate_response
    def evaluate_response(raw):
        from .gameness_v4_runtime_read_manifest import verify_delivery
        verify_delivery(root,name)
        return original_evaluate_response(raw)
    folder=root/'model_calls'/name
    eval_models.verify_call(root,name,'judge')
    if folder.exists():
        if (folder/'prompt.txt').read_text()!=READ_ONLY_EVAL_INSTRUCTIONS+prompt or runner.read(folder/'schema.json')!=schema:
            raise ValueError('Accepted Gameness request differs')
        if not (folder/'accepted_response.json').exists():
            if policy.VERSION!='whitebox-gameness10-50-100.v4':
                raise ValueError('Retained failed request needs substantive source-bound recovery: '+name)
            from .gameness_v4_validation_recovery import recover
            recover(folder,policy=policy,schema=schema,submitted_prompt=READ_ONLY_EVAL_INSTRUCTIONS+prompt,
                evaluate_response=evaluate_response,actual=runner.read(root/'requests'/name/'actual_delivery.json'))
        raw=runner.read(saved_model_response(root,name))
    else:
        try:
            raw=call_codex(root,name=name,prompt=prompt,schema=schema,images=images,model=eval_models.model_for(root, "judge"),timeout=900,max_attempts=1,
                explicit_stdin_separator=True,response_validator=evaluate_response)
        except Exception as error:
            dump(root/'failures'/(name+'.json'),dict(time=runner.stamp(),category='HARNESS_ERROR',error=repr(error),
                product_score=None,request_preserved=True,next_action='Inspect raw service events/response/schema and actual delivery; no unchanged retry'))
            raise
    shared_execution.audit_invocation(root,name,runner.read(root/'requests'/name/'actual_delivery.json'))
    checks=evaluate_response(raw)
    dump(root/'judgments'/(name+'.json'),dict(protocol=policy.VERSION,task=name,raw=raw,checks=checks,
        actual_delivery_sha256=sha(root/'requests'/name/'actual_delivery.json'),
        response_path=str(saved_model_response(root,name)),response_sha256=sha(saved_model_response(root,name))))
    print(json.dumps(dict(identity=root.name,stage='GAMENESS_V3_SHARD_COMPLETE',task=name)),flush=True)
    return checks


def publication_path(workspace,identity):return workspace/'publications/gameness_outcome_frame_v1'/(identity+'.json')


def verify_publication(workspace,identity):
    policy=workspace_policy(workspace)
    value=runner.read(publication_path(workspace,identity))
    if value['scoring_protocol']!=policy.VERSION or value['identity']!=identity:raise ValueError('Gameness publication identity/protocol mismatch')
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_contract_source_transport import verify_publication_bindings
        from .gameness_v4_publication_compatibility import verify as verify_saved_producers
        publication = publication_path(workspace,identity)
        saved_producers = verify_saved_producers(publication,value['bindings'])
        if not saved_producers:
            verify_publication_bindings(contract_dir(workspace,value['case_id']),value['bindings'],publication)
    else:
        verify_bindings(value['bindings'])
    root=Path(value['score_file']).parent;result=runner.read(Path(value['score_file']))
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_author_entry_source import publication_bindings
        if saved_producers:
            from .gameness_v4_publication_compatibility import native_source_bindings
            native_bindings = native_source_bindings(root,publication)
        else:
            native_bindings = publication_bindings(root)
        if any(value['bindings'].get(p)!=d for p,d in native_bindings.items()):
            raise ValueError('Unbound Gameness native source recovery')
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_rubric import verify,validate_protocol
        inventory=load(workspace);verify(workspace,inventory)
        validate_protocol(workspace,value['case_id'],authored_rubric.protocol_for_run(root))
    if (root/'gameness_scoring_protocol.json').is_file() and str(root/'gameness_scoring_protocol.json') not in value['bindings']:
        raise ValueError('Unbound Gameness scoring revision')
    if (root/'gameness_migration.json').is_file():
        from .gameness_v4_migration import verify as verify_migration
        verify_migration(root)
    calculated=policy.aggregate(authored_rubric.protocol_for_run(root),result['checks'])
    if calculated!=result or value['gameness_score']!=calculated['score']:raise ValueError('Gameness publication calculation mismatch')
    return value


def rebuild_tables(workspace):
    label='v4' if workspace_policy(workspace).VERSION.endswith('.v4') else 'v3'
    values=[verify_publication(workspace,p.stem) for p in sorted((workspace/'publications/gameness_outcome_frame_v1').glob('*.json'))]
    text='# Gameness '+label+' — SCORED_PENDING_AUDIT（未审计）\n\nOnly Gameness; other six columns and Mechanic untouched; no eight-column total.\n\n| identity | Gameness '+label+' | old | recording |\n|---|---:|---:|---|\n'
    for p in values:text+=f"| {p['identity']} | {p['gameness_score']:.2f} | {p['old_gameness']} | {p.get('recording_notice', '历史原生实录按新契约独立重评')} |\n"
    for name in TABLES:(workspace/name).write_text(text)


def recording_provenance(qualification, frozen):
    """Distinguish a new task take from reuse under a later scoring contract."""
    provenance = dict(task_new_recording=False, new_recording=False,
        recording_notice='按新结果导向契约重新评价历史实录')
    source = Path(qualification['source']).resolve()
    path = source/'source_qualification.json'
    if path.is_file():
        original = runner.read(path)
        verify_bindings(original['source_bindings'])
        if (Path(original['source']).resolve() != source or
                original['entry_id'] != qualification['entry_id']):
            raise ValueError('Native recording provenance identity changed')
        from .mechanic_v3_revision import fresh_under_contract
        fresh = fresh_under_contract(original, frozen)
        task_new = original.get('new_recording') is True
        notice = ('按本列冻结契约新增真实原生录制' if fresh else
            '本任务新增真实原生录制；按后冻结的本列契约重新评价该实录' if task_new else
            '按新结果导向契约重新评价历史实录')
        provenance.update(task_new_recording=task_new, new_recording=fresh,
            recording_notice=notice,
            native_take_qualification=dict(path=str(path), sha256=sha(path)))
    return provenance


def publish(workspace,root,result,guard):
    policy=workspace_policy(workspace)
    entry=runner.read(root/'input_manifest.json')['entry'];case=entry['case_id'];folder=contract_dir(workspace,case)
    qualification=runner.read(root/'source_qualification.json');source=Path(qualification['source']);old=None
    if (source/'scores.json').is_file():
        d=runner.read(source/'scores.json');old=d.get('columns',{}).get('Gameness',d.get('scores',{}).get('Gameness'))
        if isinstance(old,dict):old=old.get('score')
    paths=[root/'gameness_score.json',root/'source_qualification.json',root/'input_manifest.json',root/'evidence_manifest.json',
        workspace/'gameness_assessment_revision.json',folder/'contract.json',folder/'frozen.json',folder/'source_binding.json']
    if policy.VERSION.endswith('.v4'):
        paths.append(Path(runner.read(workspace/'gameness_assessment_revision.json')['original_rubric_manifest']['path']))
    for name in ('gameness_source_review.json','gameness_source_review_binding.json','gameness_coverage.json','gameness_scoring_protocol.json','gameness_migration.json'):
        if (root/name).is_file():paths.append(root/name)
    from .gameness_v4_empty_evidence_recovery import AUTH as handoff_auth
    if (root/handoff_auth).is_file():paths.append(root/handoff_auth)
    for directory in ('judgments','model_calls','requests'):
        paths.extend(p for p in (root/directory).rglob('*') if p.is_file())
    bindings={str(p):sha(p) for p in paths}
    bindings.update(eval_models.binding(root))
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_author_entry_source import publication_bindings
        bindings.update(publication_bindings(root))
    recovery=runner.read(folder/'frozen.json').get('contract_metadata_recovery')
    if recovery:
        if policy.VERSION.endswith('.v4'):
            from .gameness_v4_contract_source_transport import publication_recovery_bindings
            bindings.update(publication_recovery_bindings(folder,recovery))
        else:
            from .gameness_v3_contract_metadata import verify
            verify(recovery);bindings.update(recovery['bindings']);bindings[recovery['path']]=recovery['sha256']
    source_review_binding=root/'gameness_source_review_binding.json'
    if source_review_binding.is_file():
        static_binding=runner.read(source_review_binding)
        verify_bindings(static_binding['bindings']);bindings.update(static_binding['bindings'])
        bindings[static_binding['path']]=static_binding['sha256']
    bindings.update(qualification['source_bindings']);bindings.update(runner.read(folder/'source_binding.json')['bindings'])
    if (root/'gameness_migration.json').is_file():
        bindings.update(runner.read(root/'gameness_migration.json')['bindings'])
    value=dict(scoring_protocol=policy.VERSION,contract_revision=policy.REVISION,identity=entry['id'],case_id=case,method=entry['method'],
        engine=entry['actual_engine'],status='SCORED_PENDING_AUDIT',audit_status='未审计',published_at=runner.stamp(),
        gameness_score=result['score'],old_gameness=old,score_file=str(root/'gameness_score.json'),old_score_source=str(source/'scores.json'),
        recording_notice='按新结果导向契约重新评价历史实录',new_recording=False,other_columns='NOT_REEVALUATED',eight_column_total=None,bindings=bindings)
    if policy.VERSION.endswith('.v4'):
        provenance=recording_provenance(qualification,runner.read(folder/'frozen.json'))
        value.update(provenance)
        if 'native_take_qualification' in provenance:
            binding=provenance['native_take_qualification']
            bindings[binding['path']]=binding['sha256']
    scoring_protocol=authored_rubric.protocol_for_run(root)
    if 'gameness_rubric' in scoring_protocol:
        value['gameness_rubric']=scoring_protocol['gameness_rubric']
    if (root/'gameness_migration.json').is_file():
        value['version_migration']=dict(path=str(root/'gameness_migration.json'),sha256=sha(root/'gameness_migration.json'),new_judgment=False)
        value['recording_notice']='复用原判项三档独立判词，逐项等价校验后迁入v4；历史真实原生实录；未重新judge或录制'
    profile=eval_models.publication_profile(root,'Gameness')
    if profile is not None: value['evaluation_model_profile']=profile
    path=publication_path(workspace,root.name)
    if path.exists():
        saved=verify_publication(workspace,root.name)
        if saved['bindings']!=bindings:raise ValueError('Existing Gameness publication differs')
    else:runner.exclusive_json(path,value)
    rebuild_tables(workspace)
    from . import two_column_sync
    two_column_sync.sync(workspace,root.name,'Gameness',workspace_locked=True)
    print(json.dumps(dict(identity=root.name,stage='SCORED_PENDING_AUDIT',column='Gameness',score=result['score'])),flush=True)
    from . import gameness_v3_cache
    receipt=gameness_v3_cache.run(workspace,root,publication_guard=guard)
    dump(root/'gameness_cache_check.json',receipt)
    return value


def judge(workspace,row,inventory,source,workers=2,*,source_repair=None,network_recovery=False):
    policy=workspace_policy(workspace)
    identity=row['entry']['id']
    if publication_path(workspace,identity).exists():return verify_publication(workspace,identity)
    case=row['entry']['case_id'];folder=contract_dir(workspace,case)
    reused=None
    if policy.VERSION.endswith('.v4'):
        from .gameness_v4_reassessment_sources import prepare as reuse_sources
        reused=reuse_sources(workspace,row)
    contract=freeze(workspace,case,inventory);frozen=runner.read(folder/'frozen.json')
    original,_=source_protocol(row,workspace)
    runner.disk(workspace,'gameness_static_sources',256*1024**2)
    if reused is None and policy.VERSION.endswith('.v4'):
        from .gameness_v4_original_material_sources import review_if_recovered
        reused=review_if_recovered(workspace,row,source,original,contract,frozen)
    if reused is None:
        review,review_path=static_review.review(workspace,row,original,contract,frozen,source_files(Path(row['entry']['project'])),scoring_policy=policy)
        dump(review_path.parent/'gameness_capture_requirements.json',static_review.capture_requirements(review))
    else:
        review,review_path,_=reused
    root=prepare(workspace,row,source,source_repair=source_repair);runner.disk(root,'gameness_evidence_and_judge',1024**3)
    dump(root/'gameness_source_review.json',review)
    dump(root/'gameness_source_review_binding.json',dict(path=str(review_path),sha256=sha(review_path),
        bindings={**{str(p):sha(p) for p in review_path.parent.rglob('*') if p.is_file() and 'input' not in p.relative_to(review_path.parent).parts},
            **(reused[2] if reused is not None else {})}))
    protocol=authored_rubric.protocol_for_run(root);manifest=runner.read(root/'evidence_manifest.json')
    native_protocol=runner.read(root/'input/pilot_rubric.json')
    expected=policy.criteria(protocol);seen=set();tasks=[]
    for parent,subset in manifest['evidence_sets'].items():
        specs=[s for s in expected if s['id'] in subset['criterion_ids']]
        for start in range(0,len(specs),5):
            chunk=specs[start:start+5]
            if seen & {s['id'] for s in chunk}:raise ValueError('Duplicate Gameness criterion in evidence sets')
            seen.update(s['id'] for s in chunk);tasks.append((f'{task_prefix(policy)}_of1_{len(tasks)+1:02d}',parent,chunk))
    tiered_tasks=authored_rubric.runtime_tasks(protocol,manifest,native_protocol)
    if tiered_tasks is not None:
        tasks=tiered_tasks;seen={s['id'] for _,_,specs in tasks for s in specs}
    if seen!={s['id'] for s in expected}:raise ValueError('Missing Gameness parent evidence')
    # Prepare each parent exactly once before parallel model calls. No races on sheets.
    for parent in dict.fromkeys(t[1] for t in tasks):delivery(root,native_protocol,manifest,parent)
    checks={}
    # Packet generation shares validator histories per parent, so keep one writer.
    # Model concurrency can be added only with isolated prepared request artifacts.
    deferred=set()
    if network_recovery:
        if policy.VERSION != 'whitebox-gameness10-50-100.v4':
            raise ValueError('Network continuation is explicit v4 only')
        from . import mechanic_v3_service_recovery as network
        tasks,deferred=network.network_tasks(root,tasks)
    for task in tasks:
        if task[0] in deferred:
            network.prepare_network(root,task[0],network.latest_network_success(root,task[0]))
        values=evaluate_task(workspace,root,protocol,manifest,contract,frozen,task,review=review,scoring_policy=policy)
        if set(checks) & set(values):raise ValueError('Duplicate Gameness check in network continuation')
        checks.update(values)
    result=policy.aggregate(protocol,checks);dump(root/'gameness_score.json',result)
    dump(root/'gameness_coverage.json',static_review.coverage_report(review,checks))
    source_batch=Path(row['source_batch'])
    with runner.held(workspace,source_batch,native=False) as guard:publish(workspace,root,result,guard)
    return verify_publication(workspace,identity)


def production_bindings():
    """Complete formal evaluator binding, including recovery modules added later."""
    directory=Path(__file__).resolve().parent
    return {str(p):sha(p) for p in sorted(directory.rglob('*.py'))}


def acceptance_path(workspace,capability):
    if capability not in {'runtime_judge','equivalent_migration'}:raise ValueError('Unknown Gameness capability')
    if not workspace_policy(workspace).VERSION.endswith('.v4'):
        return workspace/'engineering/gameness_production_acceptance.json'
    digest=hashlib.sha256(json.dumps(production_bindings(),sort_keys=True).encode()).hexdigest()
    return workspace/'engineering/gameness_production_acceptances'/capability/(digest+'.json')


def production_gate(workspace, *, capability='runtime_judge'):
    path=acceptance_path(workspace,capability)
    if not path.is_file():raise ValueError('Real Gameness E2E acceptance required; use one explicit --acceptance-case')
    receipt=runner.read(path)
    if receipt['production_bindings']!=production_bindings():
        raise ValueError('Production SHA changed after acceptance; preserve receipt and perform source-bound reacceptance')
    verify_publication(workspace,receipt['identity'])
    return receipt


def acceptance_deliveries(root, *, scoring_policy=policy):
    """Bind every independent scoring check to its complete native delivery."""
    policy=scoring_policy
    prefix=task_prefix(policy)
    protocol=authored_rubric.protocol_for_run(root)
    expected={s['id'] for s in policy.criteria(protocol)}
    seen=set();deliveries=[]
    for judgment in sorted((root/'judgments').glob(prefix+'_*.json')):
        value=runner.read(judgment);task=value['task']
        if not (task.startswith(prefix+'_of1_') or task.startswith(prefix+'_tiered_')):
            raise ValueError('Unknown Gameness acceptance task')
        ids=set(value['checks'])
        if not ids or ids-expected or ids & seen:
            raise ValueError('Invalid or duplicate acceptance scoring checks')
        delivery=root/'requests'/task/'actual_delivery.json'
        if (sha(delivery)!=value['actual_delivery_sha256']
                or not runner.read(delivery).get('all_predeclared_frames_delivered')):
            raise ValueError('Acceptance needs complete real frame delivery')
        seen.update(ids);deliveries.append(delivery)
    if not deliveries or seen!=expected:
        raise ValueError('Acceptance needs every scoring check and complete real frame delivery')
    return deliveries


def accept_real_case(workspace,identity,before):
    policy=workspace_policy(workspace)
    if before!=production_bindings():raise ValueError('Production changed during real acceptance')
    publication=verify_publication(workspace,identity)
    root=Path(publication['score_file']).parent
    deliveries=acceptance_deliveries(root,scoring_policy=policy)
    from . import gameness_v3_cache
    qualification=gameness_v3_cache.qualify(workspace,root)
    cache=runner.read(root/'gameness_cache_check.json')
    if cache['status'] not in {'COMPLETE','BLOCKED_LOCK'}:raise ValueError('Resolve real cache-check engineering failure before acceptance')
    receipt=dict(protocol=policy.VERSION,identity=identity,time=runner.stamp(),
        acceptance=('real original native history -> complete independent original-check three-tier judgments -> read-only per-check/delivery revalidation -> equivalent v4 migration -> verified publication -> exact cache check' if (root/'gameness_migration.json').is_file() else 'real original native history -> independent new judge -> verified Gameness-only publication -> exact cache check'),
        production_bindings=before,publication_path=str(publication_path(workspace,identity)),
        publication_sha256=sha(publication_path(workspace,identity)),native_qualification=qualification,
        delivery_bindings={str(p):sha(p) for p in deliveries},cache_status=cache['status'])
    capability='equivalent_migration' if (root/'gameness_migration.json').is_file() else 'runtime_judge'
    receipt['accepted_capability']=capability
    path=acceptance_path(workspace,capability)
    if path.exists():
        retained=runner.read(path)
        if retained['production_bindings']!=before:raise ValueError('Acceptance binding changed')
        verify_publication(workspace,retained['identity'])
    else:runner.exclusive_json(path,receipt)
    print(json.dumps(dict(identity=identity,stage='GAMENESS_REAL_E2E_ACCEPTED')),flush=True)
    return receipt


def main(argv=None, *, scoring_policy=policy):
    policy=scoring_policy
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--scope-workspace',type=Path)
    parser.add_argument('--rubric-policy',choices=([original_rubric.VERSION] if policy.VERSION.endswith('.v4') else [authored_rubric.VERSION,independent.VERSION,original_rubric.VERSION]),help='Source-authored Gameness targets; default for new workspaces')
    parser.add_argument('--phase',choices=['init','freeze','static','judge','resume-publication','verify','cache','prepare-chunks'],required=True)
    parser.add_argument('--identities',nargs='*',default=[])
    parser.add_argument('--source',type=Path,help='One qualified original native take; never a replay')
    parser.add_argument('--acceptance-case',action='store_true',help='Explicit single real E2E validation before broad production use')
    parser.add_argument('--payload-diagnosis',type=Path)
    parser.add_argument('--payload-repair',type=Path)
    parser.add_argument('--source-repair',type=Path,help='Explicit immutable wrong-entry native source continuation diagnosis')
    parser.add_argument('--network-recovery',action='store_true',help='Complete independent shards before one restored-service continuation of an empty network timeout')
    args=parser.parse_args(argv);workspace=args.workspace.resolve()
    inventory=initialize(workspace,args.scope_workspace.resolve(),args.rubric_policy,scoring_policy=policy) if args.phase=='init' else load(workspace)
    revision_path=workspace/'gameness_assessment_revision.json'
    if revision_path.is_file() and workspace_policy(workspace).VERSION!=policy.VERSION:raise ValueError('Entry/workspace Gameness version mismatch')
    if args.phase=='init':print(json.dumps(dict(stage=task_prefix(policy).upper()+'_INITIALIZED',scope=inventory['full_scope_binding'])));return 0
    entries={r['entry']['id']:r for r in inventory['entries'] if r['in_scope']}
    # The same source-bound, qualified CLI used by the native evaluation chain.
    # A PATH-resolved CLI is not evidence of matching image-delivery capability.
    selected_rows=[entries[i] for i in args.identities if i in entries]
    if args.phase in {'freeze','static','judge'} and selected_rows:
        runner.configure_cli(Path(selected_rows[0]['source_batch']))
    acceptance_before=None
    if args.acceptance_case:
        if args.phase not in {'judge','resume-publication'} or len(args.identities)!=1:raise ValueError('Acceptance requires exactly one real judge case')
        acceptance_before=production_bindings()
    elif args.phase in {'judge','resume-publication'}:production_gate(workspace)
    for ident in args.identities:
        if ident not in entries:raise ValueError('Not a selected original S identity: '+ident)
        row=entries[ident]
        if row['entry']['method']=='Kimi' and args.phase not in {'verify','cache','freeze'}:
            from .mechanic_v3_kimi_scope import verify_sources
            verify_sources(Path(runner.read(workspace/'gameness_assessment_revision.json')['scope_workspace']),row)
        lock=workspace/'locks'/(task_prefix(policy)+'_'+ident+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
        with lock.open('a+') as handle:
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            try:
                if args.phase=='freeze':freeze(workspace,row['entry']['case_id'],inventory)
                elif args.phase=='static':
                    contract=freeze(workspace,row['entry']['case_id'],inventory)
                    frozen=runner.read(contract_dir(workspace,row['entry']['case_id'])/'frozen.json')
                    original,_=source_protocol(row,workspace)
                    runner.disk(workspace,'gameness_static_sources',256*1024**2)
                    review,report=static_review.review(workspace,row,original,contract,frozen,source_files(Path(row['entry']['project'])),scoring_policy=policy)
                    dump(report.parent/'gameness_capture_requirements.json',static_review.capture_requirements(review))
                elif args.phase=='resume-publication':
                    if policy.VERSION!='whitebox-gameness10-50-100.v4':raise ValueError('Saved publication is explicit v4 only')
                    from .gameness_v4_saved_publication import resume
                    resume(workspace,row)
                    if acceptance_before is not None:accept_real_case(workspace,ident,acceptance_before)
                elif args.phase=='prepare-chunks':
                    if policy.VERSION!='whitebox-gameness10-50-100.v4' or args.payload_diagnosis is None or args.payload_repair is None:
                        raise ValueError('Explicit v4 full-payload diagnosis and production repair required')
                    if runner.read(args.payload_repair).get('classification')=='NON_SCORING_BOUNDED_TEXT_DELIVERY':
                        from .gameness_v4_bounded_text import authorize
                        repair=runner.read(args.payload_repair)
                        admitted=authorize(workspace/'runs'/ident,repair['parent_task'],args.payload_repair)
                    else:
                        from .gameness_v4_runtime_chunks import authorize
                        admitted=authorize(workspace/'runs'/ident,args.payload_diagnosis,args.payload_repair)
                    print(json.dumps(admitted,ensure_ascii=False))
                elif args.phase=='verify':print(json.dumps(verify_publication(workspace,ident),ensure_ascii=False))
                elif args.phase=='cache':
                    from . import gameness_v3_cache
                    publication=verify_publication(workspace,ident)
                    print(json.dumps(gameness_v3_cache.run(workspace,Path(publication['score_file']).parent)))
                else:
                    if args.source is None:raise ValueError('Explicit --source native take required')
                    judge(workspace,row,inventory,args.source,source_repair=args.source_repair,network_recovery=args.network_recovery)
                    if acceptance_before is not None:accept_real_case(workspace,ident,acceptance_before)
            except Exception as error:
                dump(workspace/'engineering/failures'/(ident+'_'+str(time.time_ns())+'.json'),
                    dict(time=runner.stamp(),identity=ident,phase=args.phase,category='HARNESS_ERROR',error=repr(error),product_score=None))
                raise
    return 0


if __name__=='__main__':raise SystemExit(main())
