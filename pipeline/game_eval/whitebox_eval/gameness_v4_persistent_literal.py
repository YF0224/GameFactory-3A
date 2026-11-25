"""Explicit persistent readable literal transport after an uninvoked overflow.

No source is omitted: every nonrecursive definition is literal and the exact
inverse is checked before each turn and after the final complete conversation.
Frozen per-turn limits, native images, references and scoring remain unchanged.
"""
from pathlib import Path
import json
from . import gameness_v4_persistent_text as persistent
from . import exact_evidence_alias as alias
from .protocol import sha

VERSION = 'gameness-v4-persistent-flat-literal.v1'
HIERARCHICAL_VERSION = 'gameness-v4-persistent-two-literal-layers.v1'
HIERARCHICAL_HEADER = 'TWO_LITERAL_LAYERS_V1\n'
NOTICE = ("PERSISTENT COMPLETE LITERAL DICTIONARY: concatenate every earlier ORIGINAL_TEXT_PART "
          "in order, without wrappers. It contains one JSON dictionary followed by \\nTEMPLATE\\n "
          "and a literal template. Each dictionary key in the template stands for its complete "
          "literal string value. Definitions are nonrecursive; expand keys in the template once, "
          "then expand any EXACT_EVIDENCE_BODY_ALIAS using its included rules. This reconstructs "
          "every character, source line and original evidence ID. Definitions and template are "
          "directly supplied text in this conversation, never a summary or a file-read request. "
          "Cite only original evidence IDs and physical source lines, never dictionary keys. "
          "Use all attached original native images and every original criterion. No compaction, "
          "tools, source rejudging, invented facts or credit for intake acknowledgements.\n")


def _flat_inverse(wire, *, nested=False):
    """One nonrecursive layer; only an explicitly outer layer may contain a delimiter."""
    if ('\nTEMPLATE\n' not in wire if nested else wire.count('\nTEMPLATE\n') != 1):
        raise ValueError('One exact flat dictionary and literal template required')
    header, template = wire.split('\nTEMPLATE\n', 1)
    table = json.loads(header, object_pairs_hook=persistent.codex.unique_json_object)
    if set(table) != {'dictionary'} or not isinstance(table['dictionary'], dict) or not table['dictionary']:
        raise ValueError('Nonempty flat literal dictionary required')
    dictionary = table['dictionary']; keys = sorted(dictionary)
    if any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in dictionary.items()):
        raise ValueError('Complete nonempty literal definitions required')
    if any(b.startswith(a) for a,b in zip(keys,keys[1:])):
        raise ValueError('Dictionary keys must be prefix-free')
    # A reserved initial character cannot occur literally in definitions. This
    # makes expansion unambiguous and prevents recursive/escaped definitions.
    initials = {k[0] for k in keys}
    if any(any(ch in v for ch in initials) for v in dictionary.values()):
        raise ValueError('Recursive or ambiguous literal definitions forbidden')
    trie={}
    for key,value in dictionary.items():
        node=trie
        for ch in key:node=node.setdefault(ch,{})
        node[None]=value
    result=[];index=0;seen=set()
    while index<len(template):
        if template[index] not in initials:
            start=index;index+=1
            while index<len(template) and template[index] not in initials:index+=1
            result.append(template[start:index]);continue
        node=trie;end=index
        while end<len(template) and template[end] in node:
            node=node[template[end]];end+=1
            if None in node:break
        if None not in node:raise ValueError('Unknown reserved dictionary key in literal template')
        seen.add(template[index:end]);result.append(node[None]);index=end
    if seen!=set(keys):raise ValueError('Unused definitions are not part of exact literal transport')
    return ''.join(result)

def decode(wire):
    return alias.decode(_flat_inverse(wire))

def decode_wire(wire, version):
    from . import gameness_v4_sequential_lines as sequential
    if version == sequential.VERSION:
        if not wire.startswith(sequential.WIRE_HEADER):
            raise ValueError('Explicit sequential complete-source header required')
        outer = _flat_inverse(wire[len(sequential.WIRE_HEADER):], nested=True)
        return alias.decode(sequential.decode(_flat_inverse(outer, nested=True)))
    if version == VERSION:
        return decode(wire)
    if version != HIERARCHICAL_VERSION or not wire.startswith(HIERARCHICAL_HEADER):
        raise ValueError('Explicit two-layer literal version and header required')
    inner = _flat_inverse(wire[len(HIERARCHICAL_HEADER):], nested=True)
    return decode(inner)

def notice(auth):
    version = auth['literal_transport']['version']
    from . import gameness_v4_sequential_lines as sequential
    if version == sequential.VERSION:
        return NOTICE + '\n' + sequential.NOTICE
    if version == VERSION:
        return NOTICE
    if version != HIERARCHICAL_VERSION:
        raise ValueError('Unknown explicit literal transport')
    return (NOTICE + '\nEXPLICIT TWO LITERAL LAYERS: remove TWO_LITERAL_LAYERS_V1 header; split at the FIRST '
        '\nTEMPLATE\n delimiter to get the outer dictionary and template. Expand outer keys exactly once, '
        'including all literal newlines. This reconstructs the complete inner flat dictionary wire. '
        'Split that inner wire at its single delimiter, expand its nonrecursive dictionary exactly once, '
        'then apply EXACT_EVIDENCE_BODY_ALIAS rules as above. Both layers are complete directly supplied '
        'literal text; all original bytes, physical lines, criteria and native images remain required.\n')


def complete_wire(auth, body):
    from . import gameness_v4_sequential_lines as sequential
    info=auth['literal_transport'];path=Path(info['wire_path'])
    if (info.get('version') not in {VERSION,HIERARCHICAL_VERSION,sequential.VERSION} or sha(path)!=info['wire_sha256']
            or persistent.digest(body.encode())!=auth['original_body_sha256']):
        raise ValueError('Persistent literal wire or original body changed')
    wire=path.read_bytes().decode('utf-8')
    if decode_wire(wire,info['version'])!=body:raise ValueError('Persistent flat literal inverse differs from every original byte')
    return wire


def verify_invocations(call,auth,count):
    """The context override is scoped to these exact pinned CLI invocations."""
    for turn in [*(call/'persistent_turns'/f'intake_{i:02d}' for i in range(1,count+1)),call/'persistent_turns/final']:
        inv=persistent.runner.read(turn/'invocation.json');cmd=inv['command']
        if (inv.get('model_requested')!='gpt-6.1-sol' or inv.get('exit_code')!=0
                or inv.get('attempt')!=1 or '--ephemeral' in cmd
                or cmd.count('model_context_window='+str(auth['model_context_window']))!=1
                or cmd.count('model_auto_compact_token_limit=100000000')!=1):
            raise ValueError('Scoped context configuration or complete invocation changed')


def authorize(workspace,root,parent_task,repair):
    """Only a retained measured overflow with no attempted sibling qualifies."""
    runtime=persistent.runtime;runner=persistent.runner
    diagnosis=runner.read(repair);code=Path(__file__).resolve().parent
    if (diagnosis.get('classification')!='NON_SCORING_PERSISTENT_LITERAL_PREFLIGHT'
            or not diagnosis.get('root_cause') or diagnosis.get('model')!='gpt-6.1-sol'
            or diagnosis.get('model_context_window')!=1050000):
        raise ValueError('Explicit source-bound complete literal repair required')
    required={str(code/n) for n in ['gameness_v4_persistent_literal.py','gameness_v4_persistent_text.py']}
    if not required<=diagnosis.get('after_source_bindings',{}).keys():
        raise ValueError('Every new or modified formal producer must be bound')
    for name,expected in diagnosis['after_source_bindings'].items():
        if sha(Path(name))!=expected:raise ValueError('Repaired producer changed')
    before=diagnosis['before_source_bindings'];old=str(code/'gameness_v4_persistent_text.py')
    if old not in before:raise ValueError('Exact original persistent producer archive required')
    for name,record in before.items():
        if sha(Path(record['archive']))!=record['sha256']:raise ValueError('Original producer archive changed')
    directory=Path(diagnosis['measurement_directory']);measurement=directory/'measurement.json'
    measured=runner.read(measurement);prompt_path=directory/'prompt.txt';body_path=directory/'body.txt'
    body=body_path.read_bytes().decode('utf-8');prompt=prompt_path.read_bytes().decode('utf-8')
    if (measured.get('model_called') is not False or measured.get('prompt_bytes',0)<=persistent.MAX_PROMPT
            or measured['prompt_bytes']!=len(prompt.encode()) or measured['prompt_sha256']!=sha(prompt_path)
            or measured['transport']['maximum_prompt_bytes']!=persistent.MAX_PROMPT
            or measured['transport']['maximum_images']!=100 or prompt.count(body)!=1):
        raise ValueError('Unchanged measured complete pre-invocation overflow required')
    frozen=persistent.tasks(root);names=[n for n,_,_ in frozen];parents={p for _,p,_ in frozen}
    found=[s['id'] for _,_,specs in frozen for s in specs]
    expected=[s['id'] for s in persistent.policy.criteria(runtime.authored_rubric.protocol_for_run(root))]
    if parent_task not in names or len(parents)!=1 or len(found)!=len(set(found)) or set(found)!=set(expected):
        raise ValueError('Every original check and one identical full native parent required')
    if ((root/'model_calls').exists() and any((root/'model_calls'/n).exists() for n in names)
            or list((root/'judgments').glob('gameness_v4_*.json'))
            or runtime.publication_path(workspace,root.name).exists()):
        raise ValueError('Cannot replace any attempted or accepted runtime')
    for relative in ['engineering/gameness_runtime_chunks.json','engineering/gameness_runtime_read_manifest.json',
                     'engineering/gameness_literal_container.json','engineering/gameness_raw_preflight.json']:
        if (root/relative).exists():raise ValueError('Competing route needs its own substantive continuation')
    if runner.read(root/'evidence_manifest.json').get('channel_transport',{}).get('event_wire_transport'):
        raise ValueError('Required literal EVENT route cannot be superseded')
    files=[repair,measurement,prompt_path,body_path,root/'input_manifest.json',root/'source_qualification.json',
           root/'evidence_manifest.json',root/'gameness_source_review.json',root/'gameness_source_review_binding.json']
    files += [Path(p) for p in diagnosis['after_source_bindings']]
    files += [Path(v['archive']) for v in before.values()]
    for name in names:
        claim=root/'engineering/gameness_inline_schema'/(name+'.json')
        if not claim.exists():
            # Ordinary evaluation stops on the first preflight overflow. Later
            # siblings remain genuinely uninvoked; use their formal admission,
            # never manufacture a claim or replace an attempted sibling.
            from .gameness_v4_inline_schema import admit
            admit(root, name)
        v=runner.read(claim)
        if v.get('task')!=name or v.get('first_delivery') is not True:
            raise ValueError('Immutable original first-delivery claim required')
        for file,expected_sha in v['source_bindings'].items():
            if sha(Path(file))!=expected_sha:
                old_producer=diagnosis.get('parent_producer_archives',{}).get(name,{}).get(file,{})
                if (Path(file).parent!=code or Path(file).name!='gameness_v3_runtime.py'
                        or old_producer.get('sha256')!=expected_sha
                        or sha(Path(old_producer['archive']))!=expected_sha):
                    raise ValueError('Unproved original inline producer drift: '+file)
                files.append(Path(old_producer['archive']))
            files.append(Path(file))
        files.append(claim)
    name=parent_task+'_persistent_literal_'+sha(repair)[:12]
    value=dict(version=persistent.VERSION,identity=root.name,repair=str(repair),repair_sha256=sha(repair),
        original_body_path=str(body_path),original_body_sha256=sha(body_path),evidence_set=parents.pop(),
        task=name,criterion_ids=found,superseded_tasks=names,maximum_prompt_bytes=persistent.MAX_PROMPT,
        chunk_bytes=persistent.CHUNK_BYTES,maximum_attempts=1,no_invocation_at_authorization=True,
        original_failures_claims_and_counts_preserved=True,model_context_window=1050000,
        literal_transport=dict(version=VERSION,wire_path=diagnosis['wire_path'],
                               wire_sha256=sha(Path(diagnosis['wire_path']))))
    wire=complete_wire(value,body);wire_path=Path(diagnosis['wire_path']);files.append(wire_path)
    # Rebuild the full real request using the original validators before any call.
    packet=persistent.packet(workspace,root,value,persist=False)
    if packet[6]!=body:raise ValueError('Complete current packet differs from retained overflow')
    images=packet[7]
    if ([dict(path=str(p),sha256=sha(p)) for p in images]!=measured['images']
            or len(images)!=measured['image_count']):
        raise ValueError('Every original native image must be unchanged')
    for text in persistent.parts(wire):
        if len(persistent.chunk_prompt(1,99,text).encode())>persistent.MAX_PROMPT:
            raise ValueError('Persistent intake exceeds unchanged frozen limit')
    files.extend(images)
    for item in packet[-1]['complete_author_sources']:files.append(root/item['path'])
    value['bindings']={str(p.resolve()):sha(p) for p in files}
    runner.exclusive_json(root/persistent.AUTH,value)
    return value
