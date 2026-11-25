"""Opt-in readable raw literal transport for a preserved, uninvoked overflow.

The original claims, complete evidence body, native images and fixed request cap
remain bound. An actual invocation may never be replaced by this entry point.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v4_raw_literal_container as raw
from . import gameness_v4_literal_container as shared
from . import exact_evidence_alias as alias
from .protocol import sha

VERSION = 'gameness-v4-complete-raw-preflight.v1'
AUTH = 'engineering/gameness_raw_preflight.json'


def authorize(root, tasks, diagnosis, body_path, template_path):
    root=Path(root).resolve(); diagnosis=Path(diagnosis).resolve()
    body_path=Path(body_path).resolve(); template_path=Path(template_path).resolve()
    prompt_path=diagnosis/'prompt.txt'; measure_path=diagnosis/'measurement.json'
    measure=runner.read(measure_path); prompt=prompt_path.read_bytes().decode()
    body=body_path.read_bytes().decode()
    if (measure.get('model_called') is not False or measure['prompt_sha256']!=sha(prompt_path)
            or measure['prompt_bytes']!=prompt_path.stat().st_size
            or measure['transport']['maximum_prompt_bytes']!=1000000
            or measure['prompt_bytes']<=1000000 or prompt.count(body)!=1 or not body):
        raise ValueError('Preserved complete uninvoked preflight overflow required')
    if (not tasks or len(tasks)!=len(set(tasks))
            or any((root/'model_calls'/n).exists() for n in tasks)
            or list((root/'judgments').glob('gameness_v4_*.json'))):
        raise ValueError('Raw preflight cannot replace an attempted or accepted runtime')
    manifest=runner.read(root/'evidence_manifest.json')
    if manifest.get('channel_transport',{}).get('event_wire_transport'):
        raise ValueError('Literal EVENT wire must retain its own transport')
    # Competing routes need their own explicit continuation, never silent priority.
    for name in [shared.AUTH,'engineering/gameness_runtime_chunks.json']:
        if (root/name).exists():raise ValueError('Existing complete-text route requires separate continuation')
    prior=root/'engineering/gameness_exact_preflight_recovery.json'
    if prior.exists() and runner.read(prior).get('exact_shared_source_packets'):
        raise ValueError('Existing shared source route requires separate continuation')
    template=template_path.read_bytes().decode()
    wire,proof=raw.encode(body,template)
    estimate=measure['prompt_bytes']-len(body.encode())+len(wire.encode())
    if estimate>1000000 or len(wire.encode())>=len(body.encode()):
        raise ValueError('Complete raw transport still exceeds unchanged cap')
    from .gameness_v4_preflight_recovery import verify_previous_binding
    files=[prompt_path,measure_path,body_path,template_path,root/'input_manifest.json',
        root/'source_qualification.json',root/'evidence_manifest.json']
    if prior.exists():files.append(prior)
    for name in tasks:
        claim=root/'engineering/gameness_inline_schema'/(name+'.json')
        value=runner.read(claim)
        if value.get('first_delivery') is not True or value.get('task')!=name:
            raise ValueError('Unchanged original first-delivery claim required')
        for file,digest in value['source_bindings'].items():
            if sha(Path(file))!=digest and not verify_previous_binding(root,name,file,digest):
                raise ValueError('Prior inline claim changed')
            files.append(Path(file))
        files.append(claim)
    code=Path(__file__).resolve().parent
    files += [code/name for name in ['gameness_v4_raw_preflight.py','gameness_v4_raw_literal_container.py',
        'gameness_v4_literal_container.py','gameness_v4_preflight_recovery.py','shared_document_wire.py',
        'exact_evidence_alias.py','gameness_v4_inline_schema.py','gameness_v3_runtime.py']]
    value=dict(version=VERSION,identity=root.name,tasks=tasks,no_invocation_at_authorization=True,
        classification='NON_SCORING_TOOL_TRANSPORT',template_path=str(template_path),
        original_body_sha256=alias.digest(body),original_body_path=str(body_path),
        estimated_prompt_bytes=estimate,maximum_prompt_bytes=1000000,
        original_claims_failures_preserved=True,all_sources_and_native_frames_preserved=True,
        bindings={str(p):sha(p) for p in files},proof=proof)
    path=root/AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Raw preflight authorization changed')
    else:runner.exclusive_json(path,value)
    return value


def apply(root,name,body):
    root=Path(root);path=root/AUTH
    if not path.exists():return body,None
    value=runner.read(path)
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('no_invocation_at_authorization') is not True
            or value.get('maximum_prompt_bytes')!=1000000 or name not in value['tasks']):
        raise ValueError('Invalid complete raw preflight identity')
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(path,value['bindings'])
    if alias.digest(body)!=value['original_body_sha256']:
        raise ValueError('Complete original evidence body changed')
    wire,proof=raw.encode(body,Path(value['template_path']).read_bytes().decode())
    if proof!=value['proof'] or raw.decode(wire)!=body:
        raise ValueError('Complete raw expansion changed')
    proof=dict(proof,authorization_path=str(path),authorization_sha256=sha(path))
    folder=root/'requests'/name/'exact_evidence_transport'
    for filename,text in [('original_body.txt',body),('submitted_body.txt',wire)]:
        dest=folder/filename
        if dest.exists() and dest.read_bytes()!=text.encode():raise ValueError('Retained raw request differs')
        if not dest.exists():
            dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(text.encode())
    dest=folder/'equivalence.json'
    if dest.exists():
        if runner.read(dest)!=proof:raise ValueError('Retained raw equivalence differs')
    else:runner.exclusive_json(dest,proof)
    return wire,dict(path=str(dest.relative_to(root)),sha256=sha(dest),
        original_body_sha256=value['original_body_sha256'],exact_expansion=True)
