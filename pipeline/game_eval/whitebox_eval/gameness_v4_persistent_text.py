"""Explicit complete original-text delivery in one persistent judge conversation.

Only retained incomplete-read failures qualify. Every original byte is submitted
as user text, below the existing prompt cap, before native images and scoring.
The saved conversation must contain those exact messages, in order, without any
compaction. No summary, local file-read assertion or changed rubric is accepted.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from . import gameness_v3_runtime as runtime, gameness_v4 as policy
from . import gameness_v3_original as original, gameness_v3_static as static
from . import mechanic_v3_runner as runner, evaluation_model_profile as models
from . import batch, frame_budget, mechanic_v3_execution as execution
from . import codex
from .protocol import dump, sha, checked_path

VERSION = 'gameness-v4-persistent-original-text.v1'
AUTH = 'engineering/gameness_persistent_original_text.json'
MAX_PROMPT = 1000000
CHUNK_BYTES = 780000


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def parts(text):
    """Split on UTF-8 character boundaries, retaining every byte in order."""
    raw = text.encode(); result = []
    while raw:
        end = min(CHUNK_BYTES, len(raw))
        while end < len(raw) and raw[end] & 0xc0 == 0x80:
            end -= 1
        result.append(raw[:end].decode()); raw = raw[end:]
    if not result or ''.join(result) != text:
        raise ValueError('Complete nonempty original text required')
    return result


def save(path, raw):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('Immutable persistent artifact changed: '+str(path))
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as out: out.write(raw)


def tasks(root):
    proto = runtime.authored_rubric.protocol_for_run(root)
    manifest = runner.read(root/'evidence_manifest.json')
    native = runner.read(root/'input/pilot_rubric.json')
    found = runtime.authored_rubric.runtime_tasks(proto, manifest, native)
    if found is None:
        found = []; seen = set()
        for parent, subset in manifest['evidence_sets'].items():
            specs = [s for s in policy.criteria(proto) if s['id'] in subset['criterion_ids']]
            for start in range(0, len(specs), 5):
                chunk = specs[start:start+5]
                if seen & {s['id'] for s in chunk}: raise ValueError('Duplicate frozen task')
                seen.update(s['id'] for s in chunk)
                found.append((f'gameness_v4_of1_{len(found)+1:02d}', parent, chunk))
    return found


def authorization(root):
    path = root/AUTH; value = runner.read(path)
    if (value.get('version') != VERSION or value.get('identity') != root.name
            or value.get('maximum_prompt_bytes') != MAX_PROMPT
            or value.get('chunk_bytes') != CHUNK_BYTES):
        raise ValueError('Persistent text authorization identity or limits changed')
    if (root/JSONL_CONTINUATION).exists():
        jsonl_continuation(root,path)
        return value
    from . import gameness_v4_saved_original_text_producers as saved
    if saved.matches(path):
        saved.verified_bindings(path,value['bindings'])
        return value
    for file, expected in value['bindings'].items():
        if sha(Path(file)) != expected:
            from .gameness_v4_producer_history import verify
            try: verify(root, path, Path(file), expected)
            except ValueError as error:
                raise ValueError('Persistent parent changed: '+file) from error
    return value


def authorize(workspace, root, parent_task, repair):
    path = root/AUTH
    if path.exists():
        if (root/JSONL_CONTINUATION).exists():
            jsonl_continuation(root,path)
            value = runner.read(path)
        else:
            value = authorization(root)
        if value['repair'] != str(repair): raise ValueError('Persistent repair is immutable')
        return value
    diagnosis = runner.read(repair)
    if diagnosis.get('classification') == 'NON_SCORING_PERSISTENT_LITERAL_PREFLIGHT':
        from . import gameness_v4_persistent_literal as literal
        return literal.authorize(workspace, root, parent_task, repair)
    required = {str(Path(__file__).resolve()), str(Path(__file__).with_name('gameness_v4_runtime.py').resolve()),
                str(Path(__file__).with_name('gameness_v4_bounded_text.py').resolve())}
    if (diagnosis.get('classification') != 'NON_SCORING_PERSISTENT_COMPLETE_TEXT'
            or not diagnosis.get('root_cause')
            or not required <= diagnosis.get('after_source_bindings', {}).keys()):
        raise ValueError('Substantive source-bound persistent transport repair required')
    call = root/'model_calls'/parent_task
    inv = runner.read(call/'invocation.json'); error = runner.read(call/'validation_error.json')
    if (inv.get('exit_code') != 0 or inv.get('attempt') != 1
            or error.get('response_sha256') != sha(call/'response.json')
            or 'did not receive every complete source chunk in order' not in error.get('exception', '')
            or (call/'accepted_response.json').exists()
            or list((root/'judgments').glob('gameness_v4_*.json'))
            or runtime.publication_path(workspace, root.name).exists()):
        raise ValueError('Only a retained incomplete-read failure without any accepted score qualifies')
    from .gameness_v4_runtime_read_manifest import PERMISSION_AUTH, PERMISSION_VERSION
    prior = runner.read(root/PERMISSION_AUTH)
    if (prior.get('version') != PERMISSION_VERSION
            or parent_task not in prior['recovery_tasks'].values()):
        raise ValueError('Exact latest failed permission route required')
    actual_path = root/'requests'/parent_task/'actual_delivery.json'; actual = runner.read(actual_path)
    proof_path = root/actual['runtime_text_chunks']['path']; proof = runner.read(proof_path)
    body_path = proof_path.parent/'original_body.txt'
    if (sha(proof_path) != actual['runtime_text_chunks']['sha256']
            or sha(body_path) != proof['original_body_sha256']
            or sha(body_path) != prior['original_body_sha256']
            or actual.get('all_predeclared_frames_delivered') is not True
            or actual.get('scoring_protocol') != policy.VERSION
            or actual.get('prompt_sha256') != sha(call/'prompt.txt')):
        raise ValueError('Complete immutable original v4 parent context required')
    from .gameness_v4_runtime_chunks import payloads, ordered_source_outputs
    try: ordered_source_outputs((call/'events.jsonl').read_text(), payloads(body_path.read_text()))
    except ValueError: pass
    else: raise ValueError('Parent already received every byte')
    frozen_tasks = tasks(root); parents = {p for _, p, _ in frozen_tasks}
    expected = {s['id'] for s in policy.criteria(runtime.authored_rubric.protocol_for_run(root))}
    found = [s['id'] for _, _, specs in frozen_tasks for s in specs]
    if (parents != {actual['evidence_set']} or len(found) != len(set(found)) or set(found) != expected):
        raise ValueError('One identical complete parent and all original checks required for lossless merge')
    untouched = [n for n in prior['recovery_tasks'].values() if n != parent_task]
    if any((root/'model_calls'/n).exists() for n in untouched):
        raise ValueError('Cannot supersede any independently attempted sibling task')
    files = [repair, actual_path, proof_path, body_path, root/PERMISSION_AUTH,
             root/'input_manifest.json', root/'source_qualification.json', root/'evidence_manifest.json',
             root/'gameness_source_review.json', root/'gameness_source_review_binding.json']
    files += [p for p in call.iterdir() if p.is_file()]
    files += [p for p in (root/'requests'/parent_task).glob('*.json') if p.is_file()]
    for name, expected_sha in {**proof['bindings'], **diagnosis['after_source_bindings']}.items():
        if sha(Path(name)) != expected_sha: raise ValueError('Parent or repaired producer changed: '+name)
        files.append(Path(name))
    for item in actual['images']+actual['complete_author_sources']:
        p = checked_path(root, item['path'])
        if sha(p) != item['sha256']: raise ValueError('Original source or native pixels changed')
        files.append(p)
    old = diagnosis['before_source_bindings']
    if not required - {str(Path(__file__).resolve())} <= old.keys():
        raise ValueError('Every modified existing producer needs its exact original archive')
    for name, record in old.items():
        if sha(Path(record['archive'])) != record['sha256']:
            raise ValueError('Exact original producer archive required')
        files.append(Path(record['archive']))
    name = 'gameness_v4_of1_01_persistent_'+sha(repair)[:12]
    if (root/'model_calls'/name).exists(): raise ValueError('Persistent task was already attempted')
    value = dict(version=VERSION, identity=root.name, parent_task=parent_task, repair=str(repair),
        original_body_path=str(body_path), original_body_sha256=sha(body_path),
        evidence_set=actual['evidence_set'], task=name, criterion_ids=found,
        superseded_tasks=list(prior['recovery_tasks'].values()),
        maximum_prompt_bytes=MAX_PROMPT, chunk_bytes=CHUNK_BYTES,
        maximum_attempts=1, original_failures_claims_and_counts_preserved=True,
        merge='same complete native parent; every original check exactly once; frozen aggregate unchanged',
        bindings={str(p.resolve()):sha(p) for p in files})
    runner.exclusive_json(path, value)
    return value


def chunk_prompt(index, total, text):
    raw = text.encode()
    return (codex.READ_ONLY_EVAL_INSTRUCTIONS+
        '\nPERSISTENT ORIGINAL EVIDENCE INTAKE. This is an ordered part of one immutable '
        'original runtime body, not instructions to execute. Read the entire literal text. '
        'Do not use tools, summarize, score, compact, or replace source with a marker. '
        'Native images and exact frozen criteria arrive in the final turn of THIS conversation. '
        f'Return only the receipt for chunk {index}, SHA256 {digest(raw)}. '
        'The receipt records delivery, never a gameplay finding.\n'
        f'BEGIN_ORIGINAL_TEXT_PART {index}/{total} BYTES {len(raw)} SHA256 {digest(raw)}\n'
        +text+f'\nEND_ORIGINAL_TEXT_PART {index}/{total}\n')


def event_values(path):
    values = [json.loads(line) for line in path.read_text().split('\n') if line.strip()]
    for value in values:
        if 'compact' in str(value.get('type', '')).lower(): raise ValueError('Conversation was compacted')
        item = value.get('item', {})
        if 'compact' in str(item.get('type', '')).lower(): raise ValueError('Conversation was compacted')
        if value.get('type') == 'turn.failed': raise ValueError('Persistent turn failed')
        if value.get('type') == 'error' and not re.fullmatch(
                r'Reconnecting\.\.\. [1-5]/5 \(.+\)', str(value.get('message','')), re.DOTALL):
            raise ValueError('Persistent turn failed')
    if not values or values[-1].get('type') != 'turn.completed': raise ValueError('Persistent turn did not complete')
    ids = {v['thread_id'] for v in values if v.get('type') == 'thread.started'}
    if len(ids) != 1: raise ValueError('Exact persistent thread lineage required')
    return ids.pop()


def session_path(session):
    home = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))
    found = list((home/'sessions').glob('**/*'+session+'*.jsonl'))
    if len(found) != 1: raise ValueError('One retained persistent session artifact required')
    return found[0]


def verify_session(path, session, prompts, model):
    """Require complete input blocks in one retained model conversation."""
    users = []; contexts = []; metadata = []
    for line in path.read_text().split('\n'):
        if not line.strip(): continue
        value = json.loads(line); payload = value.get('payload', {})
        if value.get('type') == 'session_meta': metadata.append(payload.get('id'))
        kind = str(value.get('type', ''))+' '+str(payload.get('type', ''))
        if 'compact' in kind.lower(): raise ValueError('Retained conversation contains compaction')
        if value.get('type') == 'turn_context': contexts.append(payload.get('model'))
        if value.get('type') == 'response_item' and payload.get('type') == 'message' and payload.get('role') == 'user':
            # CLI image attachments may add separate labels and image blocks. The
            # submitted literal prompt itself must remain one exact input block.
            users.append([x.get('text', '') for x in payload.get('content', [])
                          if x.get('type') in {'input_text','text'}])
    if metadata != [session]: raise ValueError('One exact retained session identity required')
    matched = [text for blocks in users for text in blocks if text in prompts]
    if matched != prompts or any(sum(blocks.count(p) for blocks in users) != 1 for p in prompts):
        raise ValueError('Every complete original prompt must occur once in the same conversation in order')
    if not contexts or any(m != model for m in contexts): raise ValueError('Persistent model changed')
    return dict(session=session,session_sha256=sha(path),turns=len(prompts),model=model,
        original_user_prompt_sha256=[digest(p.encode()) for p in prompts],no_compaction=True)



JSONL_CONTINUATION = 'engineering/persistent_jsonl_continuation.json'


def jsonl_continuation(root, auth_path):
    """Exact bounded continuation after the Unicode splitlines audit failure.

    This admits no replacement inputs, new scoring attempts or failed model
    responses. Only already successful intake turns may be reused.
    """
    path = root/JSONL_CONTINUATION
    value = runner.read(path)
    if (value.get('version') != 'persistent-jsonl-unicode-continuation.v1'
            or value.get('identity') != root.name
            or value.get('authorization') != {'path':str(auth_path.resolve()),'sha256':sha(auth_path)}
            or value.get('maximum_original_intake_attempts') != 1
            or value.get('scoring_unchanged') is not True
            or value.get('all_original_bytes_and_pixels_required') is not True):
        raise ValueError('Exact Unicode JSONL continuation required')
    from .mechanic_v3_cli import production_source_bindings
    if value.get('after_source_bindings') != production_source_bindings():
        raise ValueError('Unicode continuation must bind full current production')
    regression = value['regression']; proof = runner.read(Path(regression['path']))
    if (sha(Path(regression['path'])) != regression['sha256']
            or proof.get('exit_code') != 0 or proof.get('tests_passed',0) < 1):
        raise ValueError('Passed Unicode JSONL regressions required')
    parent = value['parent_failure']; failure = runner.read(Path(parent['path']))
    if (sha(Path(parent['path'])) != parent['sha256']
            or 'JSONDecodeError' not in str(failure.get('error',''))):
        raise ValueError('Preserved original JSONL audit failure required')
    code = Path(__file__).resolve().parent
    changed = {}
    for name, expected in runner.read(auth_path)['bindings'].items():
        if sha(Path(name)) == expected: continue
        if (Path(name).parent != code or Path(name).name not in {
                'gameness_v4_persistent_text.py','mechanic_v3_persistent_text.py',
                'gameness_v4_persistent_capacity.py'}):
            raise ValueError('Continuation cannot change original data or unrelated producer: '+name)
        archive = value['before_producer_archives'].get(name)
        if not archive or Path(archive).resolve() == Path(name) or sha(Path(archive)) != expected:
            raise ValueError('Exact old Unicode transport producer required')
        changed[name] = expected
    if set(changed) != set(value['before_producer_archives']):
        raise ValueError('Only exact changed parent producers may be continued')
    files = value['retained_turn_bindings']
    if not files or any(sha(Path(p)) != d for p,d in files.items()):
        raise ValueError('Original successful intake artifacts changed')
    return value


def retained_intake(root, call, folder, prompt, schema, model, session, *, context_tokens=None):
    """Reuse one successful exact intake; never invoke it a second time."""
    receipt = runner.read(root/JSONL_CONTINUATION)
    expected = receipt['retained_turn_bindings']
    paths = [p for p in folder.iterdir() if p.is_file()]
    if not paths or any(expected.get(str(p.resolve())) != sha(p) for p in paths):
        raise ValueError('Intake is outside explicit retained artifact bindings')
    if (folder/'prompt.txt').read_text() != prompt or runner.read(folder/'schema.json') != schema:
        raise ValueError('Retained complete intake prompt/schema changed')
    inv = runner.read(folder/'invocation.json');cmd=inv['command']
    if (inv.get('exit_code') != 0 or inv.get('attempt') != 1
            or inv.get('model_requested') != model or '--ephemeral' in cmd
            or cmd.count('model_auto_compact_token_limit=100000000') != 1
            or (context_tokens is not None and cmd.count('model_context_window='+str(context_tokens)) != 1)):
        raise ValueError('Only successful original full-context intake may be reused')
    found = event_values(folder/'events.jsonl')
    if session and (found != session or 'resume' not in cmd or session not in cmd):
        raise ValueError('Retained intake changed conversation')
    if not session and 'resume' in cmd:
        raise ValueError('First retained intake must establish the original conversation')
    return runner.read(folder/'response.json'), found

def invoke(root, folder, prompt, schema, model, deadline, session=None, images=(), *, context_tokens=None):
    if len(prompt.encode()) > MAX_PROMPT or len(images) > 100:
        raise ValueError('Unchanged prompt/image limit exceeded')
    folder.mkdir(parents=True, exist_ok=False)
    save(folder/'prompt.txt', prompt.encode()); dump(folder/'schema.json', schema)
    executable, binding = codex.evaluation_executable('codex')
    common = [executable,'--ask-for-approval','never','exec','--sandbox','read-only',
              '-C',str(root/'input'),'--color','never']
    if session: common += ['resume']
    command = common+['--model',model,'-c','model_reasoning_effort='+json.dumps(os.environ.get('A3GAME_SOL_REASONING_EFFORT','medium')),
        '-c','model_auto_compact_token_limit=100000000','--ignore-rules','--json',
        '--output-schema',str(folder/'schema.json'),'-o',str(folder/'response.json')]
    if context_tokens is not None:
        if context_tokens != 1050000 or model != 'gpt-6.1-sol':
            raise ValueError('Only the explicitly bound Sol context configuration is admitted')
        command += ['-c', 'model_context_window='+str(context_tokens)]
    for image in images: command += ['--image',str(image)]
    command += ['--']+([session] if session else [])+['-']
    env = dict(os.environ)
    for key in list(env):
        if any(s in key.upper() for s in ('DASHSCOPE','AWS_SECRET','ANTHROPIC_API','GEMINI_API')): env.pop(key)
    started = time.monotonic(); remaining = deadline-started
    if remaining <= 0: raise RuntimeError('Persistent original deadline exhausted before launch')
    with (folder/'events.jsonl').open('w') as stdout, (folder/'stderr.log').open('w') as stderr:
        process = subprocess.Popen(command,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,
            text=True,env=env,start_new_session=True)
        try: process.communicate(prompt,timeout=remaining)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGTERM);process.wait(timeout=10)
            dump(folder/'invocation.json',dict(model_requested=model,command=command,status='TIMEOUT',attempt=1))
            raise RuntimeError('Persistent original deadline exhausted; retained without unchanged retry')
    inv = dict(model_requested=model,command=command,exit_code=process.returncode,attempt=1,
        response_present=(folder/'response.json').is_file(),seconds=round(time.monotonic()-started,2))
    if binding is not None: inv['cli_runtime'] = binding; dump(folder/'cli_runtime.json',binding)
    dump(folder/'invocation.json',inv)
    if process.returncode or not inv['response_present']: raise RuntimeError('Persistent CLI failed; inspect retained events and stderr')
    actual_session = event_values(folder/'events.jsonl')
    if session is not None and session != actual_session: raise ValueError('Resume opened a different thread')
    value = json.loads((folder/'response.json').read_text(),object_pairs_hook=codex.unique_json_object,
        parse_constant=codex.reject_json_constant)
    codex.validate_schema(value,schema)
    return value,actual_session


def packet(workspace, root, auth, *, persist=True):
    proto = runtime.authored_rubric.protocol_for_run(root); specs = policy.criteria(proto)
    manifest = runner.read(root/'evidence_manifest.json'); parent = auth['evidence_set']
    native = runner.read(root/'input/pilot_rubric.json')
    manifest = runtime.delivery(root,native,manifest,parent)
    selected = frame_budget.for_task(manifest,parent)
    context = dict(selected); context['items'] = [i for i in selected['items'] if i['type'] != 'source']
    body, omitted = batch.packet(root,context,False); sources=[]
    for item in selected['items']:
        if item['type'] != 'source': continue
        path = checked_path(root,item['path'])
        if sha(path) != item['sha256']: raise ValueError('Complete original source changed')
        lines = path.read_text(errors='replace').splitlines()
        body += '\nEVIDENCE '+item['id']+' (complete original source)\n'+''.join(f'{n}: {line}\n' for n,line in enumerate(lines,1))
        sources.append(dict(id=item['id'],path=item['path'],sha256=item['sha256'],line_count=len(lines)))
    if digest(body.encode()) != auth['original_body_sha256']:
        raise ValueError('Rebuilt complete native packet differs from retained original')
    folder = runtime.contract_dir(workspace,runner.read(root/'input_manifest.json')['entry']['case_id'])
    frozen = runner.read(folder/'frozen.json');contract = runner.read(folder/'contract.json')
    if sha(folder/'contract.json') != frozen['contract_sha256']: raise ValueError('Frozen contract changed')
    runtime.verify_bindings(runner.read(folder/'source_binding.json')['bindings'])
    review = runner.read(root/'gameness_source_review.json');bound=runner.read(root/'gameness_source_review_binding.json')
    runtime.verify_bindings(bound['bindings'])
    if sha(Path(bound['path'])) != bound['sha256'] or runner.read(Path(bound['path'])) != review:
        raise ValueError('Complete original static source findings changed')
    policy.validate_contract(proto,contract)
    from .gameness_v4_rubric import validate_protocol
    validate_protocol(workspace,runner.read(root/'input_manifest.json')['entry']['case_id'],proto)
    rules = batch.judge_citation_rules(root,selected,omitted,False)
    original_schema = original.runtime_schema(specs,rules,selected)
    schema, schema_proof = runtime.group(original_schema)
    wire_schema = json.dumps(schema,ensure_ascii=False,separators=(',',':'))
    prompt = (codex.READ_ONLY_EVAL_INSTRUCTIONS+policy.INSTRUCTION+'\n'+original.DELIVERY_NOTICE+
        '\nPERSISTENT ORIGINAL CONTEXT: every earlier ORIGINAL_TEXT_PART in THIS exact thread, in order, '
        'constitutes the complete original body. Do not read paths, call tools, compact or summarize it. '
        'The following original native images are attached to THIS final invocation. Apply every original '
        'criterion exactly once. Text intake receipts award no credit.\n'
        'COMPLETE_BODY_SHA256 '+auth['original_body_sha256']+'\n'
        'FROZEN SOURCE-ONLY CONTRACT BINDING:\n'+json.dumps(original.runtime_binding(frozen),ensure_ascii=False)+
        '\nCOMMON GAMENESS CONTRACT (original exact requirements are diagnostic ONLY):\n'+json.dumps(contract,ensure_ascii=False)+
        '\nIMMUTABLE FIRST-STAGE SOURCE REVIEW (do not rejudge source_existence):\n'+json.dumps(review['checks'],ensure_ascii=False)+
        '\nEXACT INLINE OUTPUT SCHEMA:\n'+wire_schema)
    if auth.get('literal_transport'):
        from .gameness_v4_persistent_literal import notice
        prompt += '\n'+notice(auth)
    images=[root/i['path'] for i in selected['items'] if i['type']=='reference']+[root/i['path'] for i in selected['delivery_sheets']]
    native=runner.read(root/'input/pilot_rubric.json')
    # Preserve the parent validation receipt: this task has its own alias of
    # the identical complete parent, and its own request validation artifact.
    request_manifest=dict(manifest,evidence_sets={auth['task']:manifest['evidence_sets'][parent]})
    actual=frame_budget.validate_request(root,auth['task'],native,request_manifest,images,prompt)
    actual['evidence_set']=parent
    actual.update(task=auth['task'],column='Gameness',scoring_protocol=policy.VERSION,
        contract_sha256=frozen['contract_sha256'],complete_author_sources=sources,
        all_predeclared_frames_delivered=True,source_review_sha256=sha(root/'gameness_source_review.json'))
    if not persist:
        return proto,specs,selected,rules,contract,review,body,images,schema,prompt,actual
    req=root/'requests'/auth['task'];ref=req/'persistent_original_text/equivalence.json'
    save(ref.parent/'original_body.txt',body.encode())
    proof=dict(version=VERSION,authorization=dict(path=str(root/AUTH),sha256=sha(root/AUTH)),
        original_body_sha256=auth['original_body_sha256'],all_original_text_retained=True,
        native_images_unchanged=True,bindings={str(ref.parent/'original_body.txt'):sha(ref.parent/'original_body.txt')})
    save(ref,(json.dumps(proof,ensure_ascii=False,indent=2)+'\n').encode())
    actual['runtime_text_chunks']=dict(version=VERSION,path=str(ref.relative_to(root)),sha256=sha(ref))
    for filename,value in [('actual_delivery.json',actual),('selected_manifest.json',selected),('citation_rules.json',rules),
            ('original_schema.json',original_schema),('schema_transport.json',schema_proof)]:dump(req/filename,value)
    return proto,specs,selected,rules,contract,review,body,images,schema,prompt,actual


def delivery_parts(auth, body):
    if auth.get('literal_transport'):
        from .gameness_v4_persistent_literal import complete_wire
        return parts(complete_wire(auth,body))
    return parts(body)


def verify_delivery(root,name,actual=None):
    root=Path(root);actual=actual if actual is not None else runner.read(root/'requests'/name/'actual_delivery.json')
    reference=actual.get('runtime_text_chunks',{})
    if reference.get('version') != VERSION: raise ValueError('Expected persistent complete text delivery')
    auth=authorization(root)
    if auth['task'] != name: raise ValueError('Persistent accepted task differs')
    ref=root/reference['path']
    if not ref.resolve().is_relative_to((root/'requests'/name).resolve()) or sha(ref)!=reference['sha256']:
        raise ValueError('Persistent equivalence binding changed')
    proof=runner.read(ref)
    if proof['authorization'] != dict(path=str(root/AUTH),sha256=sha(root/AUTH)):
        raise ValueError('Persistent repair authorization changed')
    for file,expected in proof['bindings'].items():
        if sha(Path(file)) != expected: raise ValueError('Persistent source text changed')
    body=(ref.parent/'original_body.txt').read_text();chunks=delivery_parts(auth,body)
    if digest(body.encode()) != auth['original_body_sha256']: raise ValueError('Original body hash differs')
    call=root/'model_calls'/name;prompts=[];session=None
    for index,text in enumerate(chunks,1):
        turn=call/'persistent_turns'/f'intake_{index:02d}'
        prompt=chunk_prompt(index,len(chunks),text)
        if (turn/'prompt.txt').read_text()!=prompt:raise ValueError('Persistent original chunk missing or changed')
        inv=runner.read(turn/'invocation.json');response=runner.read(turn/'response.json')
        if inv.get('exit_code')!=0 or inv.get('model_requested')!=models.model_for(root,'judge'):
            raise ValueError('Persistent intake did not succeed with frozen model')
        if response!=dict(chunk=index,sha256=digest(text.encode())):raise ValueError('Intake response does not acknowledge exact part')
        sid=event_values(turn/'events.jsonl')
        if session is None:session=sid
        elif sid!=session:raise ValueError('Original text was split across conversations')
        prompts.append(prompt)
    final=(call/'prompt.txt').read_text()
    if sha(call/'prompt.txt')!=actual['prompt_sha256'] or event_values(call/'events.jsonl')!=session:
        raise ValueError('Final judge is outside complete original conversation')
    prompts.append(final)
    proof=verify_session(call/'persistent_session.jsonl',session,prompts,models.model_for(root,'judge'))
    if auth.get('literal_transport'):
        from .gameness_v4_persistent_literal import verify_invocations
        verify_invocations(call,auth,len(chunks))
    receipt=dict(version=VERSION,task=name,all_original_text_actually_delivered=True,
        original_body_sha256=auth['original_body_sha256'],chunk_count=len(chunks),ordered_session_proof=proof,
        prompt_sha256=actual['prompt_sha256'],native_images_attached_unchanged=True)
    dest=ref.parent/'actual_text_delivery.json'
    save(dest,(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n').encode())
    return receipt


def evaluate(workspace, root, auth):
    from . import gameness_v4_saved_original_text_producers as saved
    if saved.matches(root/AUTH):
        raise ValueError('Saved original-text producer verification grants no new model calls')
    proto,specs,selected,rules,contract,review,body,images,schema,prompt,actual=packet(workspace,root,auth)
    name=auth['task'];call=root/'model_calls'/name
    models.verify_call(root,name,'judge')
    if call.exists():
        if not (root/JSONL_CONTINUATION).exists():
            raise ValueError('Retained persistent call needs substantive continuation, never unchanged retry')
        jsonl_continuation(root,root/AUTH)
        final_turn = call/'persistent_turns/final'
        final_complete = all((final_turn/name).is_file() for name in
                             ('events.jsonl', 'invocation.json', 'response.json'))
        if final_complete:
            raise ValueError('Unicode intake continuation cannot repeat final scoring')
    else:
        call.mkdir(parents=True)
    deadline=time.monotonic()+900;model=models.model_for(root,'judge');chunks=delivery_parts(auth,body);session=None;prompts=[]
    # Main scoring artifacts use the same complete frozen schema and prompt as audit_invocation.
    save(call/'prompt.txt',prompt.encode());dump(call/'schema.json',schema)
    for index,text in enumerate(chunks,1):
        ingest=chunk_prompt(index,len(chunks),text)
        ack_schema=codex.obj({'chunk':{'type':'integer','enum':[index]},'sha256':{'type':'string','enum':[digest(text.encode())]}})
        folder=call/'persistent_turns'/f'intake_{index:02d}'
        if folder.exists():
            value,session=retained_intake(root,call,folder,ingest,ack_schema,model,session,context_tokens=auth.get('model_context_window'))
        else:
            value,session=invoke(root,folder,ingest,ack_schema,model,deadline,session,context_tokens=auth.get('model_context_window'))
        if value!=dict(chunk=index,sha256=digest(text.encode())):raise ValueError('Original intake acknowledgement differs')
        prompts.append(ingest)
        source=session_path(session);verify_session(source,session,prompts,model)
        print(json.dumps(dict(identity=root.name,stage='PERSISTENT_ORIGINAL_TEXT_PART',part=index,total=len(chunks),bytes=len(text.encode()))),flush=True)
    final=call/'persistent_turns/final'
    raw,session=invoke(root,final,prompt,schema,model,deadline,session,images,context_tokens=auth.get('model_context_window'))
    prompts.append(prompt);source=session_path(session);verify_session(source,session,prompts,model)
    for filename in ['events.jsonl','stderr.log','response.json','invocation.json']:
        save(call/filename,(final/filename).read_bytes())
    if (final/'cli_runtime.json').is_file():save(call/'cli_runtime.json',(final/'cli_runtime.json').read_bytes())
    save(call/'persistent_session.jsonl',source.read_bytes())
    verify_delivery(root,name,actual)
    checks=original.evaluate(root,proto,selected,rules,contract,raw,specs,review,scoring_policy=policy)
    dump(call/'accepted_response.json',dict(path='response.json',sha256=sha(call/'response.json')))
    execution.audit_invocation(root,name,actual)
    dump(root/'judgments'/(name+'.json'),dict(protocol=policy.VERSION,task=name,raw=raw,checks=checks,
        actual_delivery_sha256=sha(root/'requests'/name/'actual_delivery.json'),
        response_path=str(call/'response.json'),response_sha256=sha(call/'response.json')))
    score=policy.aggregate(proto,checks);dump(root/'gameness_score.json',score)
    dump(root/'gameness_coverage.json',static.coverage_report(review,checks))
    return score


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--phase',choices=['persistent-judge'],required=True)
    parser.add_argument('--identities',nargs='+',required=True);parser.add_argument('--persistent-repair',type=Path,required=True)
    parser.add_argument('--acceptance-case',action='store_true');args=parser.parse_args(argv)
    workspace=args.workspace.resolve();inventory=runtime.load(workspace)
    if len(args.identities)!=1 or runtime.workspace_policy(workspace).VERSION!=policy.VERSION:
        raise ValueError('One explicit original-check v4 identity required')
    identity=args.identities[0];row=next(r for r in inventory['entries'] if r['entry']['id']==identity and r['in_scope'])
    runner.configure_cli(Path(row['source_batch']));before=runtime.production_bindings()
    if not args.acceptance_case:runtime.production_gate(workspace)
    lock=workspace/'locks'/('gameness_v4_'+identity+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        root=workspace/'runs'/identity;repair=args.persistent_repair.resolve()
        try:
            runner.disk(root,'gameness_persistent_original_text',256*1024**2)
            batch.verify_inputs(root)
            from .gameness_v3_cache import qualify
            q=runner.read(root/'source_qualification.json');runtime.verify_bindings(q['source_bindings'])
            from .pending_publication import cleanup_source
            if not cleanup_source(Path(q['source']))[0]:raise ValueError('Real source native cleanup required')
            from . import sparse_native
            sparse_native.verify_acceptance(workspace,row['entry']['actual_engine'])
            if not runtime.scope.same_original(runner.read(root/'input_manifest.json')['entry'],row['entry']):
                raise ValueError('Persistent identity differs from frozen source')
            diagnosis=runner.read(repair)
            auth=authorize(workspace,root,diagnosis['parent_task'],repair)
            score=evaluate(workspace,root,auth)
            with runner.held(workspace,Path(row['source_batch']),native=False) as guard:
                runtime.publish(workspace,root,score,guard)
            if args.acceptance_case:runtime.accept_real_case(workspace,identity,before)
        except Exception as error:
            dump(root/'failures'/('persistent_text_'+str(time.time_ns())+'.json'),dict(time=runner.stamp(),
                category='HARNESS_ERROR',error=repr(error),product_score=None,old_failures_claims_and_counts_preserved=True))
            raise
    return 0
