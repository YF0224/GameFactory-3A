"""Bounded complete-source Mechanic transport, with independent shard conversations.

This capability is distinct from Gameness acceptance. Original claims, failures,
check partitions, native pixels and per-turn limits stay immutable. Only literal,
exactly reversible text can move to earlier turns of the same uncompacted thread.
"""
from pathlib import Path
import hashlib
import json
import re
import time
from . import mechanic_v3_runner as runner, mechanic_v3_execution as execution
from . import mechanic_v3_revision as revision, mechanic_v3 as policy
from . import batch, frame_budget, codex, exact_evidence_alias as alias
from . import gameness_v4_persistent_text as transport
from . import gameness_v4_persistent_literal as literal
from . import evaluation_model_profile as models
from .protocol import dump, sha

VERSION = 'mechanic-v3-persistent-complete-source.v1'
AUTH = 'engineering/mechanic_persistent_complete_source.json'
BODY_START = '\nACTUAL DELIVERED PARENT CONTEXT (unchanged for each subtask):\n'
BODY_END = '\nPREDECLARED ENDPOINT CONTRACTS:\n'
NOTICE = ("\nMECHANIC COMPLETE LITERAL CONTEXT: concatenate the earlier ORIGINAL_TEXT_PART "
          "payloads in this exact conversation in order. Split at newline-TEMPLATE-newline. "
          "Expand each nonrecursive literal dictionary key once, then expand the included "
          "EXACT_EVIDENCE_BODY_ALIAS grammar. This recovers the complete original parent "
          "context, every author source line, runtime channel, STATE decoder and citation "
          "whitelist. Cite only original evidence IDs/physical lines. All native images "
          "are attached now. No tools, summaries, compaction or credit for intake receipts. "
          "Judge only this shard's original CHECKS using the unchanged frozen contract.\n")
# Old pending source claims may have these exact historical transport producers.
HISTORICAL = {'mechanic_v3_image_transport.py', 'mechanic_v3_source_delivery.py',
              'mechanic_v3_execution.py'}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def flat_encode(body, dictionary):
    """Reuse literal definitions as data; only exact used occurrences are transmitted."""
    encoded, _ = alias.encode(body)
    keys = sorted(dictionary)
    if not keys or any(not k or not isinstance(dictionary[k], str) or not dictionary[k] for k in keys):
        raise ValueError('Nonempty literal definitions required')
    if any(b.startswith(a) for a, b in zip(keys, keys[1:])):
        raise ValueError('Prefix-free dictionary required')
    initials = {k[0] for k in keys}
    if any(ch in encoded for ch in initials):
        raise ValueError('Reserved literal key already occurs in original context')
    if any(any(ch in text for ch in initials) for text in dictionary.values()):
        raise ValueError('Recursive literal definitions forbidden')
    inverse = {}
    for key in keys:
        value = dictionary[key]
        inverse.setdefault(value, key)
    pattern = re.compile('|'.join(re.escape(s) for s in sorted(inverse, key=len, reverse=True)))
    used = set()
    def replace(match):
        key = inverse[match.group()]; used.add(key); return key
    template = pattern.sub(replace, encoded)
    selected = {k: dictionary[k] for k in keys if k in used}
    if not selected:
        raise ValueError('Dictionary did not match this complete context')
    wire = json.dumps({'dictionary': selected}, ensure_ascii=False, separators=(',', ':'))+'\nTEMPLATE\n'+template
    if decode_wire(wire) != body:
        raise ValueError('Every complete original context byte must round-trip')
    return wire


def decode_wire(wire):
    version = literal.HIERARCHICAL_VERSION if wire.startswith(literal.HIERARCHICAL_HEADER) else literal.VERSION
    return literal.decode_wire(wire, version)


def wire_notice(wire):
    if wire.startswith(literal.HIERARCHICAL_HEADER):
        return ("\nEXPLICIT TWO LITERAL LAYERS: remove TWO_LITERAL_LAYERS_V1 header; split at the FIRST "
                "\nTEMPLATE\n delimiter. Expand outer nonrecursive literal dictionary keys exactly once to "
                "recover the entire inner dictionary wire. Split inner wire at its single delimiter, "
                "expand inner keys exactly once, then expand EXACT_EVIDENCE_BODY_ALIAS. Every original "
                "context byte and physical source line is retained.\n")
    return ''


def authorization(root, *, historical=False):
    path = root/AUTH; value = runner.read(path)
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('maximum_attempts') != 1 or value.get('maximum_prompt_bytes') != 1000000
            or value.get('maximum_images') != 100):
        raise ValueError('Exact Mechanic authorization and unchanged limits required')
    for name, expected in value['bindings'].items():
        archive=value.get('producer_archives',{}).get(name)
        if historical and archive:
            if sha(Path(archive)) != expected:
                raise ValueError('Exact historical producer snapshot changed: '+name)
        elif sha(Path(name)) != expected:
            raise ValueError('Mechanic persistent source/producer changed: '+name)
    return value


def capacity_reference(root, call, images, prompt):
    """Capacity calibration only; never reuse a Gameness verdict as Mechanic."""
    from PIL import Image
    import tiktoken
    from .gameness_v4_persistent_capacity import telemetry
    session = call/'persistent_session.jsonl'
    values = telemetry(session)
    if len(values) < 2:
        raise ValueError('Measured complete final capacity reference required')
    model = models.model_for(root, 'judge')
    parent_prompts = [(call/'persistent_turns'/n/'prompt.txt').read_text()
        for n in sorted(p.name for p in (call/'persistent_turns').iterdir() if p.name.startswith('intake_'))]
    parent_prompts.append((call/'prompt.txt').read_text())
    sid = transport.event_values(call/'persistent_turns/final/events.jsonl')
    transport.verify_session(session, sid, parent_prompts, model)
    actual = runner.read(call/'actual_delivery.json')
    parent_root = call.parent.parent
    original_images = [parent_root/item['path'] for item in actual['images']]
    if len(images) != len(original_images):
        raise ValueError('Capacity reference must contain every identical native image')
    for old, new in zip(original_images, images):
        with Image.open(old) as first, Image.open(new) as second:
            if first.size != second.size or first.convert('RGB').tobytes() != second.convert('RGB').tobytes():
                raise ValueError('Capacity calibration native pixels differ')
    encoding = tiktoken.get_encoding('o200k_base')
    old_tokens = len(encoding.encode(parent_prompts[-1]))
    new_tokens = len(encoding.encode(prompt))
    # Retained real usage supplies all image/system overhead. Only half of a
    # measured text reduction is credited, with another 4096-token margin.
    increment = values[-1]['input_tokens'] - values[-2]['input_tokens'] - values[-2]['output_tokens']
    reduction = max(0, (old_tokens-new_tokens)//2)
    increase = max(0, (new_tokens-old_tokens)*2)
    if increment <= 0:
        raise ValueError('Measured reference final increment required')
    return dict(final_increment_upper_bound=max(1, increment-reduction+increase+4096),
        observed_context_window=values[-1]['window'], reference_call=str(call),
        reference_final_text_tokens=old_tokens, mechanic_final_text_tokens=new_tokens,
        identical_native_images=len(images), no_compaction=True)


def capacity_gate(session, reference):
    from .gameness_v4_persistent_capacity import capacity_gate as check
    return check(session, reference)


def authorize(workspace, root, repair_path):
    if (root/AUTH).exists():
        if (root/transport.JSONL_CONTINUATION).exists():
            transport.jsonl_continuation(root,root/AUTH)
            value = authorization(root,historical=True)
        else:
            value = authorization(root)
        if value['repair'] != str(repair_path):
            raise ValueError('Retained Mechanic capability cannot be replaced by a new repair')
        return value
    repair = runner.read(repair_path)
    if (repair.get('classification') != 'NON_SCORING_MECHANIC_PERSISTENT_COMPLETE_SOURCE'
            or not repair.get('root_cause') or repair.get('all_original_bytes_and_pixels_required') is not True
            or repair.get('scoring_unchanged') is not True):
        raise ValueError('Substantive independent Mechanic repair required')
    regression = runner.read(Path(repair['regression']['path']))
    if (sha(Path(repair['regression']['path'])) != repair['regression']['sha256']
            or regression.get('exit_code') != 0 or regression.get('tests_passed', 0) < 1):
        raise ValueError('Passed targeted Mechanic regressions required')
    from .mechanic_v3_cli import production_source_bindings
    production = production_source_bindings()
    if production != repair['after_source_bindings']:
        raise ValueError('Repair must bind the entire current formal production')
    producer_archives=repair['after_producer_archives']
    if set(producer_archives)!=set(production) or any(sha(Path(producer_archives[p]))!=d for p,d in production.items()):
        raise ValueError('Exact full production snapshots required for future historical verification')
    reference = Path(repair['capacity_reference_call'])
    reference_actual = runner.read(reference/'actual_delivery.json')
    reference_files = [reference/'persistent_session.jsonl', reference/'prompt.txt', reference/'actual_delivery.json']
    reference_files += [p for p in (reference/'persistent_turns').rglob('*') if p.is_file()]
    reference_files += [reference.parent.parent/i['path'] for i in reference_actual['images']]
    files = [*reference_files, repair_path, Path(repair['regression']['path']), Path(repair['dictionary_path']), Path(repair['literal_wire_path']),
             root/'input_manifest.json', root/'source_qualification.json', root/'evidence_manifest.json',
             root/'input/pilot_rubric.json', root/'runtime/frame_index.jsonl']
    for old, archive in repair['before_source_bindings'].items():
        p = Path(archive['archive'])
        if sha(p) != archive['sha256']:
            raise ValueError('Exact before bytes changed: '+old)
        files.append(p)
    claims = sorted((root/'engineering/complete_source_delivery').glob('*.json'))
    claims += sorted((root/'engineering/complete_source_preflight').glob('*.json'))
    if not claims:
        raise ValueError('Retained complete-source preflight lineage required')
    code = Path(__file__).resolve().parent
    for path in claims:
        old = runner.read(path); files.append(path)
        for name, expected in old['bindings'].items():
            p = Path(name)
            if sha(p) == expected:
                files.append(p); continue
            archive = repair.get('parent_producer_archives', {}).get(name, {}).get(expected)
            if (p.parent != code or p.name not in HISTORICAL or not archive
                    or sha(Path(archive)) != expected):
                raise ValueError('Exact pending parent producer archive required: '+name)
            files.append(Path(archive))
    protocol = runner.read(root/'input/pilot_rubric.json'); manifest = runner.read(root/'evidence_manifest.json')
    tasks = execution.partitions(protocol, manifest, prefix=revision.task_prefix(workspace))
    if list((root/'judgments').glob('mechanic_v3_*.json')):
        raise ValueError('Accepted Mechanic partitions require separate continuation; do not replace them')
    if any(p.is_dir() for p in (root/'model_calls').glob('mechanic_v3_*')):
        raise ValueError('Invoked Mechanic failures require their own diagnosis; this route is preflight-only')
    case = runner.read(root/'input_manifest.json')['entry']['case_id']
    folder = revision.contract_dir(workspace, case)
    files += [folder/n for n in ['contract.json', 'frozen.json', 'source_binding.json']]
    for mapping in [runner.read(root/'source_qualification.json')['source_bindings'],
                    runner.read(folder/'source_binding.json')['bindings']]:
        for name, expected in mapping.items():
            if sha(Path(name)) != expected: raise ValueError('Author/native/frozen source changed: '+name)
            files.append(Path(name))
    for item in manifest['items']:
        if item['type'] == 'source':
            if sha(root/item['path']) != item['sha256']: raise ValueError('Original complete author source changed')
            files.append(root/item['path'])
    files += [Path(p) for p in producer_archives.values()]
    bindings = {str(p.resolve()): sha(p) for p in files}; bindings.update(production)
    value = dict(version=VERSION, identity=root.name, repair=str(repair_path),
        repair_sha256=sha(repair_path), maximum_attempts=1, maximum_prompt_bytes=1000000,
        maximum_images=100, dictionary_path=repair['dictionary_path'],
        literal_wire_path=repair['literal_wire_path'],
        capacity_reference_call=str(reference),
        producer_archives=producer_archives, independent_mechanic_acceptance_required=True, preserved_parent_claims=[str(p) for p in claims],
        tasks=[dict(canonical=n, task=n+'_persistent_'+sha(repair_path)[:12], parent=p,
                    criterion_ids=[s['id'] for s in specs]) for n,p,specs in tasks],
        bindings=bindings)
    runner.exclusive_json(root/AUTH, value)
    return value


def complete_body(root, selected):
    from .mechanic_v3_source_delivery import _section
    body, omitted = batch.packet(root, selected, False)
    for item in selected['items']:
        if item['type'] != 'source': continue
        path = root/item['path']
        if sha(path) != item['sha256']: raise ValueError('Source changed during complete packet creation')
        start, end, _ = _section(body, item['id'])
        text = path.read_text(errors='strict')
        full = '\nEVIDENCE '+item['id']+'\n'+''.join(f'{i}: {line}\n' for i,line in enumerate(text.splitlines(),1))+'\n'
        body = body[:start]+full+body[end:]
    return body


def packet(workspace, root, auth, task, *, persist=True):
    from . import mechanic_v3_outcome_evidence as evidence, mechanic_v3_outcome as outcome
    from .mechanic_v3_judge_transport import group
    protocol = runner.read(root/'input/pilot_rubric.json'); manifest = runner.read(root/'evidence_manifest.json')
    name, parent = task['task'], task['parent']
    canonical = next(t for t in execution.partitions(protocol, manifest, prefix=revision.task_prefix(workspace)) if t[0] == task['canonical'])
    specs = canonical[2]
    if [s['id'] for s in specs] != task['criterion_ids'] or parent != canonical[1]:
        raise ValueError('Independent frozen Mechanic partition changed')
    case = runner.read(root/'input_manifest.json')['entry']['case_id']; folder = revision.contract_dir(workspace, case)
    frozen = runner.read(folder/'frozen.json'); contract = runner.read(folder/'contract.json')
    if sha(folder/'contract.json') != frozen['contract_sha256']: raise ValueError('Frozen contract changed')
    manifest = evidence.prepare(root, protocol, manifest, parent, revision='outcome_frame_v1', contract_sha256=frozen['contract_sha256'])
    selected = frame_budget.for_task(manifest, parent)
    body = complete_body(root, selected)
    rules = batch.judge_citation_rules(root, selected, [], False)
    original_schema = outcome.judgment_schema(specs, rules, selected); schema, schema_proof = group(original_schema)
    images = [root/i['path'] for i in selected['items'] if i['type']=='reference']+[root/i['path'] for i in selected['delivery_sheets']]
    final = (codex.READ_ONLY_EVAL_INSTRUCTIONS+outcome.INSTRUCTION+NOTICE+
        '\nFROZEN CONTRACT BINDING:\n'+json.dumps(frozen,ensure_ascii=False)+
        '\nPAIRED PREDEFINED BASIC CONTRACT (entire contract, all atoms):\n'+json.dumps(contract,ensure_ascii=False)+
        BODY_START+'PERSISTENT_COMPLETE_BODY_SHA256 '+digest(body)+BODY_END+
        json.dumps(selected.get('endpoint_contracts',{}),ensure_ascii=False)+
        '\nIMAGE MAP:\n'+json.dumps(selected['delivery_sheets'],ensure_ascii=False)+
        '\nCHECKS (evaluate exactly these, once each):\n'+json.dumps(specs,ensure_ascii=False)+
        '\nEXACT INLINE OUTPUT SCHEMA:\n'+json.dumps(schema,ensure_ascii=False,separators=(',',':'))+
        '\nOUTCOME_FRAME_V1 OVERRIDE: CHECKS.requirement和旧PREDECLARED ENDPOINT CONTRACTS仅用于来源诊断；时间/空间/精确数值/边界/稳定性/全分支条件不参与50或100。只用PAIRED契约的visible_goal和真实结果画面判100。完整上下文不代表已证明。')
    dictionary = json.loads(Path(auth['dictionary_path']).read_text().split('\nTEMPLATE\n',1)[0])['dictionary']
    wire = Path(auth['literal_wire_path']).read_text() if auth.get('literal_wire_path') else flat_encode(body, dictionary)
    if decode_wire(wire) != body:
        raise ValueError('Pinned optimized literal wire must recover every original context byte')
    final += wire_notice(wire)
    # Only the actual final turn is subject to validate_request. Intake turns
    # independently enforce the identical byte/image caps in the formal invoker.
    request_manifest = dict(manifest, evidence_sets={name:manifest['evidence_sets'][parent]})
    actual = frame_budget.validate_request(root, name, protocol, request_manifest, images, final)
    actual.update(v3_task=name, parent_evidence_set=parent, evidence_set=parent,
        contract_sha256=frozen['contract_sha256'], full_parent_context_preserved=True,
        mechanic_persistent_complete_source=dict(version=VERSION, authorization=str(root/AUTH),
            authorization_sha256=sha(root/AUTH) if persist else None, body_sha256=digest(body), wire_sha256=digest(wire)))
    if persist:
        req = root/'requests'/name; req.mkdir(parents=True,exist_ok=True)
        for filename,text in [('complete_body.txt',body),('literal_wire.txt',wire),('expanded_prompt.txt',final.replace('PERSISTENT_COMPLETE_BODY_SHA256 '+digest(body),body,1))]:
            transport.save(req/filename,text.encode())
        for filename,value in [('actual_delivery.json',actual),('citation_rules.json',rules),('selected_manifest.json',selected),
                ('original_schema.json',original_schema),('schema_transport.json',schema_proof),
                ('context_binding.json',dict(body_sha256=digest(body),body_bytes=len(body.encode()),omitted_source_ranges=[],
                    task_mechanisms=task['criterion_ids'],all_parent_mechanisms=manifest['evidence_sets'][parent]['criterion_ids'],full_parent_context_preserved=True))]:
            transport.save(req/filename,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    return protocol,specs,selected,rules,contract,images,schema,final,body,wire,actual


def verify_delivery(root, name, actual):
    """Return exact complete context only after proving every actual input turn."""
    auth = authorization(root,historical=True)
    task = next((t for t in auth['tasks'] if t['task']==name),None)
    if not task: raise ValueError('Persistent task outside immutable original partitions')
    proof = actual['mechanic_persistent_complete_source']
    if proof['authorization_sha256'] != sha(root/AUTH): raise ValueError('Persistent authorization changed')
    req=root/'requests'/name; call=root/'model_calls'/name
    body=(req/'complete_body.txt').read_text(); wire=(req/'literal_wire.txt').read_text()
    if digest(body)!=proof['body_sha256'] or digest(wire)!=proof['wire_sha256'] or decode_wire(wire)!=body:
        raise ValueError('Complete source inverse differs')
    prompts=[];session=None;model=models.model_for(root,'judge'); chunks=transport.parts(wire)
    for index,text in enumerate(chunks,1):
        folder=call/'persistent_turns'/f'intake_{index:02d}'; prompt=transport.chunk_prompt(index,len(chunks),text)
        schema=codex.obj({'chunk':{'type':'integer','enum':[index]},'sha256':{'type':'string','enum':[transport.digest(text.encode())]}})
        if (folder/'prompt.txt').read_text()!=prompt or runner.read(folder/'schema.json')!=schema or runner.read(folder/'response.json')!=dict(chunk=index,sha256=transport.digest(text.encode())):
            raise ValueError('Exact complete Mechanic intake/receipt changed')
        prompts.append(prompt)
        sid=transport.event_values(folder/'events.jsonl')
        if session is not None and sid!=session:raise ValueError('Mechanic intake conversation changed')
        session=sid
    final=call/'persistent_turns/final';prompt=(call/'prompt.txt').read_text();prompts.append(prompt)
    if (final/'prompt.txt').read_text()!=prompt or digest(prompt)!=actual['prompt_sha256']:
        raise ValueError('Exact final Mechanic input changed')
    if transport.event_values(final/'events.jsonl')!=session: raise ValueError('Final judge opened another conversation')
    for index,folder in enumerate([call/'persistent_turns'/f'intake_{i:02d}' for i in range(1,len(chunks)+1)]+[final]):
        inv=runner.read(folder/'invocation.json');cmd=inv['command']
        if inv.get('exit_code')!=0 or inv.get('attempt')!=1 or inv.get('model_requested')!=model:
            raise ValueError('Independent Mechanic invocation/model changed')
        if ('--ephemeral' in cmd or cmd.count('model_context_window=1050000')!=1
                or cmd.count('model_auto_compact_token_limit=100000000')!=1):
            raise ValueError('Exact persistent context configuration required')
        if index and ('resume' not in cmd or session not in cmd):raise ValueError('Retained same conversation resume required')
        if index<len(chunks) and '--image' in cmd:raise ValueError('Intake cannot claim final image delivery')
    for file in ['prompt.txt','schema.json','invocation.json','response.json']:
        if (call/file).read_bytes()!=(final/file).read_bytes():raise ValueError('Final invocation artifact differs: '+file)
    retained=call/'persistent_session.jsonl'
    transport.verify_session(retained,session,prompts,model)
    expanded=prompt.replace('PERSISTENT_COMPLETE_BODY_SHA256 '+digest(body),body,1)
    if expanded==(prompt) or (req/'expanded_prompt.txt').read_text()!=expanded:raise ValueError('Full original Mechanic context missing')
    return expanded


def evaluate(workspace, root, auth, task):
    name=task['task']; call=root/'model_calls'/name; dest=root/'judgments'/(name+'.json')
    if dest.exists():
        artifact=runner.read(dest);actual=runner.read(root/'requests'/name/'actual_delivery.json')
        verify_delivery(root,name,actual)
        if sha(call/'accepted_response.json')!=artifact['accepted_response_sha256'] or sha(Path(artifact['response_path']))!=artifact['response_sha256']:
            raise ValueError('Accepted independent Mechanic shard changed')
        return artifact['checks']
    continuing=call.exists()
    if continuing:
        if not (root/transport.JSONL_CONTINUATION).exists():
            raise ValueError('Retained Mechanic persistent failure; substantive bounded continuation required')
        transport.jsonl_continuation(root,root/AUTH)
        if (call/'persistent_turns/final').exists():
            raise ValueError('Unicode intake continuation cannot repeat Mechanic final scoring')
    proto,specs,selected,rules,contract,images,schema,prompt,body,wire,actual=packet(workspace,root,auth,task)
    reference=capacity_reference(root,Path(auth['capacity_reference_call']),images,prompt)
    models.verify_call(root,name,'judge');runner.disk(root,'mechanic_complete_source_judge',128*1024**2)
    if not continuing:call.mkdir(parents=True)
    transport.save(call/'prompt.txt',prompt.encode())
    transport.save(call/'schema.json',(json.dumps(schema,ensure_ascii=False,indent=2)+'\n').encode())
    deadline=time.monotonic()+900;session=None;prompts=[];model=models.model_for(root,'judge');chunks=transport.parts(wire)
    for index,text in enumerate(chunks,1):
        intake=transport.chunk_prompt(index,len(chunks),text)
        ack=codex.obj({'chunk':{'type':'integer','enum':[index]},'sha256':{'type':'string','enum':[transport.digest(text.encode())]}})
        folder=call/'persistent_turns'/f'intake_{index:02d}'
        if folder.exists():
            value,session=transport.retained_intake(root,call,folder,intake,ack,model,session,context_tokens=1050000)
        else:
            value,session=transport.invoke(root,folder,intake,ack,model,deadline,session,context_tokens=1050000)
        if value!=dict(chunk=index,sha256=transport.digest(text.encode())):raise ValueError('Complete source intake receipt differs')
        prompts.append(intake);transport.verify_session(transport.session_path(session),session,prompts,model)
        print(json.dumps(dict(identity=root.name,task=name,stage='MECHANIC_COMPLETE_SOURCE_INTAKE',part=index,total=len(chunks),bytes=len(text.encode()))),flush=True)
    gate=capacity_gate(transport.session_path(session),reference)
    dump(call/'capacity_gate.json',dict(reference=reference,gate=gate))
    final=call/'persistent_turns/final'
    raw,session=transport.invoke(root,final,prompt,schema,model,deadline,session,images,context_tokens=1050000)
    prompts.append(prompt);source=transport.session_path(session);transport.verify_session(source,session,prompts,model)
    for filename in ['events.jsonl','stderr.log','response.json','invocation.json']:
        transport.save(call/filename,(final/filename).read_bytes())
    if (final/'cli_runtime.json').exists():transport.save(call/'cli_runtime.json',(final/'cli_runtime.json').read_bytes())
    transport.save(call/'persistent_session.jsonl',source.read_bytes());verify_delivery(root,name,actual)
    checks=policy.evaluate(root,proto,selected,rules,contract,raw,specs)
    dump(call/'accepted_response.json',dict(path='response.json',sha256=sha(call/'response.json')))
    execution.audit_invocation(root,name,actual)
    dump(dest,dict(version=policy.VERSION,task=name,parent=task['parent'],raw=raw,checks=checks,
        actual_delivery_sha256=sha(call/'actual_delivery.json'),accepted_response_sha256=sha(call/'accepted_response.json'),
        response_path=str(call/'response.json'),response_sha256=sha(call/'response.json')))
    print(json.dumps(dict(identity=root.name,task=name,stage='NEW_MECHANIC_SHARD_COMPLETE')),flush=True)
    return checks


def retained_capacity_intake(root,call,repair_path,repair,intake,schema,model):
    proof = repair['capacity_manifest_continuation']
    parent_path = Path(proof['parent_repair']['path'])
    if sha(parent_path) != proof['parent_repair']['sha256']:
        raise ValueError('Original failed calibration repair changed')
    parent = runner.read(parent_path)
    if (parent.get('capacity_reference_call') != str(call)
            or parent.get('calibrate_native_images') is not True
            or parent.get('literal_wire_path') != repair.get('literal_wire_path')
            or parent.get('original_body_sha256') != repair.get('original_body_sha256')):
        raise ValueError('Capacity continuation must retain original source, wire and fixed call')
    failure = Path(proof['parent_failure']['path'])
    if (sha(failure) != proof['parent_failure']['sha256']
            or runner.read(failure).get('identity') != root.name
            or runner.read(failure).get('error') != "ValueError('judge image arguments do not match this evidence shard')"):
        raise ValueError('Only exact diagnosed pre-final manifest failure may continue')
    current = repair['after_source_bindings']; before = parent['after_source_bindings']
    changed = {p for p,d in before.items() if current.get(p) != d}
    permitted = {'mechanic_v3_persistent_text.py','gameness_v4_persistent_text.py',
        'gameness_v4_persistent_capacity.py','gameness_v4_final_literal.py'}
    if not changed or any(Path(p).name not in permitted for p in changed):
        raise ValueError('Only the explicitly repaired capacity transport producers may change')
    for name,digest in before.items():
        archive = parent['after_producer_archives'][name]
        if sha(Path(archive)) != digest:
            raise ValueError('Exact original calibration producer bytes required')
    bindings = proof['retained_intake_bindings']
    files = {str(p.resolve()) for p in (call/'persistent_turns/intake_01').rglob('*') if p.is_file()}
    if not files or set(bindings) != files or any(sha(Path(p))!=d for p,d in bindings.items()):
        raise ValueError('All accepted first-intake artifacts must remain immutable')
    if (call/'persistent_turns/final').exists():
        raise ValueError('Capacity final already attempted; preserve bounded continuation')
    folder=call/'persistent_turns/intake_01'; inv=runner.read(folder/'invocation.json'); cmd=inv['command']
    if ((folder/'prompt.txt').read_text()!=intake or runner.read(folder/'schema.json')!=schema
            or runner.read(folder/'response.json')!={'receipt':'CAPACITY_ONLY_NO_VERDICT'}
            or inv.get('exit_code')!=0 or inv.get('attempt')!=1 or inv.get('model_requested')!=model
            or '--image' in cmd or 'resume' in cmd or cmd.count('model_context_window=1050000')!=1):
        raise ValueError('Exact accepted capacity-only first intake required')
    session=transport.event_values(folder/'events.jsonl')
    transport.verify_session(transport.session_path(session),session,[intake],model)
    runner.exclusive_json(call/'manifest_continuation_claim.json',dict(
        repair=str(repair_path),repair_sha256=sha(repair_path),session=session,
        parent_failure=str(failure),parent_failure_sha256=sha(failure),
        maximum_remaining_model_calls=1,first_intake_reused=True))
    return session


def calibrate_capacity(workspace, root, repair_path):
    """Measure the identical final text/images without judging absent source context."""
    repair = runner.read(repair_path)
    if repair.get('calibrate_native_images') is not True:
        return
    call = Path(repair['capacity_reference_call']).resolve()
    if call != (root/'capacity_calls/mechanic_complete_native_images').resolve():
        raise ValueError('Capacity calibration must retain one fixed original-root path')
    if (call/'capacity_complete.json').exists():
        proof = runner.read(call/'capacity_complete.json')
        if proof['repair_sha256'] != sha(repair_path):
            raise ValueError('Retained calibration repair changed')
        for name,digest in proof['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Retained capacity calibration changed')
        return
    continuing = call.exists()
    if continuing and not repair.get('capacity_manifest_continuation'):
        raise ValueError('Retained incomplete calibration needs substantive continuation')
    from .mechanic_v3_cli import production_source_bindings
    if production_source_bindings() != repair['after_source_bindings']:
        raise ValueError('Calibration must bind full current production')
    protocol = runner.read(root/'input/pilot_rubric.json')
    manifest = runner.read(root/'evidence_manifest.json')
    canonical,parent,specs = execution.partitions(protocol,manifest,prefix=revision.task_prefix(workspace))[0]
    task = dict(task=canonical+'_capacity_only',canonical=canonical,parent=parent,criterion_ids=[x['id'] for x in specs])
    _,_,selected,_,_,images,_,prompt,_,_,_ = packet(workspace,root,repair,task,persist=False)
    model = models.model_for(root,'judge')
    if not continuing: call.mkdir(parents=True)
    deadline = time.monotonic()+900
    schema = codex.obj({'receipt':{'type':'string','enum':['CAPACITY_ONLY_NO_VERDICT']}})
    intake = 'Capacity calibration only. Reply with receipt CAPACITY_ONLY_NO_VERDICT. No source context or scoring is supplied.'
    if continuing:
        session = retained_capacity_intake(root,call,repair_path,repair,intake,schema,model)
        value = runner.read(call/'persistent_turns/intake_01/response.json')
    else:
        value,session = transport.invoke(root,call/'persistent_turns/intake_01',intake,schema,model,deadline,None,context_tokens=1050000)
    if value != {'receipt':'CAPACITY_ONLY_NO_VERDICT'}:
        raise ValueError('Capacity-only intake acknowledgment differs')
    final = ('CAPACITY CALIBRATION ONLY. The quoted final-turn document and all original images '
             'are inputs for measuring actual context use. Complete author source is intentionally '
             'absent in this calibration; issue no judgment, score or criterion answer. Return only '
             'the receipt CAPACITY_ONLY_NO_VERDICT.\nBEGIN QUOTED FINAL DOCUMENT\n'+prompt+
             '\nEND QUOTED FINAL DOCUMENT. Return only the capacity receipt.')
    frame_budget.validate_request(root,task['task'],protocol,
        dict(selected,evidence_sets={task['task']:selected['evidence_sets'][parent]}),images,final)
    value,session = transport.invoke(root,call/'persistent_turns/final',final,schema,model,deadline,session,images,context_tokens=1050000)
    if value != {'receipt':'CAPACITY_ONLY_NO_VERDICT'}:
        raise ValueError('Capacity-only final acknowledgment differs')
    source = transport.session_path(session)
    transport.verify_session(source,session,[intake,final],model)
    transport.save(call/'persistent_session.jsonl',source.read_bytes())
    transport.save(call/'prompt.txt',final.encode())
    dump(call/'actual_delivery.json',dict(capacity_only=True,not_a_judgment=True,
        images=[dict(path=str(p.relative_to(root)),sha256=sha(p)) for p in images]))
    files=[p for p in call.rglob('*') if p.is_file()]+images+[repair_path]
    dump(call/'capacity_complete.json',dict(repair_sha256=sha(repair_path),
        maximum_model_calls=2,criterion_answers=0,native_images_unchanged=True,
        bindings={str(p.resolve()):sha(p) for p in files}))
    print(json.dumps(dict(identity=root.name,stage='MECHANIC_NATIVE_IMAGE_CAPACITY_MEASURED',images=len(images),scoring_calls=0)),flush=True)


def run(workspace, root, repair):
    calibrate_capacity(workspace,root,repair)
    auth=authorize(workspace,root,repair);checks={}
    for task in auth['tasks']:
        part=evaluate(workspace,root,auth,task)
        if set(checks)&set(part):raise ValueError('Duplicate independent Mechanic checks')
        checks.update(part)
    result=policy.aggregate(runner.read(root/'input/pilot_rubric.json'),checks)
    result['assessment_revision']='outcome_frame_v1';dump(revision.result_path(workspace,root),result)
    from . import mechanic_v3_delivery_audit_v3 as native_delivery, mechanic_v3_delivery_audit_v4 as full_delivery
    manifest=runner.read(root/'evidence_manifest.json')
    tasks=[native_delivery.task_delivery(root,runner.read(root/'judgments'/(t['task']+'.json')),manifest) for t in auth['tasks']]
    prepublish=full_delivery.upgrade(dict(version=native_delivery.VERSION,root=str(root),tasks=tasks))
    if not prepublish['qualified']:raise ValueError('Independent complete delivery required before publication')
    publication=execution.finalize_publication(workspace,root,result)
    from . import two_column_sync, mechanic_v3_delivery_audit_v4 as delivery
    receipt=delivery.publication(workspace,root.name)
    if not receipt['qualified']:raise ValueError('Independent Mechanic complete delivery acceptance failed')
    two_column_sync.sync(workspace,root.name,'Mechanic')
    dump(root/'engineering/mechanic_persistent_real_acceptance.json',dict(version=VERSION,
        status='MECHANIC_REAL_E2E_ACCEPTED',production_bindings=auth['bindings'],delivery=receipt,
        new_recording=False,independent_shards=len(auth['tasks']),product_score=result['score'],
        actual_deleted_bytes=execution.cache_check(workspace,root,publication).get('actual_deleted_bytes'),
        status_note='SCORED_PENDING_AUDIT'))
    return result
