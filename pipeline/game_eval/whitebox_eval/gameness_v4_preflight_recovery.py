"""Explicit pre-invocation-only exact packet recovery; preserve earlier claims."""
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha
from . import exact_evidence_alias as alias

VERSION = 'gameness-v4-exact-preflight-recovery.v1'
AUTH = 'engineering/gameness_exact_preflight_recovery.json'


def authorization(root, name):
    path = Path(root)/AUTH
    if not path.exists():
        return None
    receipt = runner.read(path)
    if (receipt.get('version') != VERSION or name not in receipt['tasks'] or
            receipt.get('no_invocation_at_authorization') is not True):
        raise ValueError('Invalid exact preflight recovery identity')
    from .gameness_v4_production_continuation import verified_bindings
    try:
        verified_bindings(path,receipt['bindings'])
    except ValueError as error:
        raise ValueError('Exact preflight recovery source changed: '+str(error)) from error
    return receipt


def verify_previous_binding(root, name, file, digest):
    # An accepted inline request can predate an unrelated runtime dispatcher
    # repair. Its exact immutable producer continuation changes no request bytes.
    inline = Path(root)/'engineering/gameness_inline_schema'/(name+'.json')
    if inline.exists():
        previous = runner.read(inline)
        if (previous.get('first_delivery') is True
                and previous.get('task') == name
                and previous.get('source_bindings', {}).get(str(file)) == digest):
            from .gameness_v4_production_continuation import verified_bindings
            try:
                verified_bindings(inline, previous['source_bindings'])
            except ValueError:
                pass  # The separately bound original preflight route may qualify.
            else:
                return True
    receipt = authorization(root, name)
    return (receipt is not None and receipt['before_code_bindings'].get(str(file)) == digest
            and str(file) in receipt['after_code_bindings']
            and receipt['after_code_bindings'][str(file)] == receipt['bindings'].get(str(file)))


def apply(root, name, body):
    from .gameness_v4_suffix_preflight import apply as suffix_packet
    wire, proof = suffix_packet(root, name, body)
    if proof is not None:
        return wire, proof
    from .gameness_v4_raw_shard_continuation import apply as continued_packet
    wire, proof = continued_packet(root, name, body)
    if proof is not None:
        return wire, proof
    from .gameness_v4_raw_parent_correction import apply as corrected_packet
    wire, proof = corrected_packet(root, name, body)
    if proof is not None:
        return wire, proof
    from .gameness_v4_raw_preflight import apply as raw_packet
    wire, proof = raw_packet(root, name, body)
    if proof is not None:
        return wire, proof
    from .gameness_v4_literal_container import apply as complete_packet
    wire, proof = complete_packet(root, name, body)
    if proof is not None:
        return wire, proof
    receipt = authorization(root, name)
    if receipt is None:
        return body, None
    original = body
    shared_proofs = []
    packets = receipt.get("exact_shared_source_packets", {})
    if packets:
        from .gameness_v4_shared_source_transport import apply as shared_apply
        body, shared_proofs = shared_apply(root, packets, body)
    wire, proof = alias.encode(body)
    if packets:
        from .gameness_v4_shared_source_transport import expand
        if expand(root, packets, alias.decode(wire), shared_proofs) != original:
            raise ValueError("Shared Gameness packet does not reconstruct the complete original body")
        proof = dict(version=VERSION, original_sha256=alias.digest(original),
            submitted_sha256=alias.digest(wire), original_bytes=len(original.encode()),
            submitted_bytes=len(wire.encode()), alias_proof=proof, shared_sources=shared_proofs,
            exact_expansion=True, physical_lines_unchanged=True)
    folder = Path(root)/'requests'/name/'exact_evidence_transport'
    for filename, text in [('original_body.txt', original), ('submitted_body.txt', wire)]:
        path = folder/filename
        if path.exists() and path.read_text() != text:
            raise ValueError('Retained exact packet changed')
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    proof.update(authorization_path=str(Path(root)/AUTH), authorization_sha256=sha(Path(root)/AUTH))
    path = folder/'equivalence.json'
    if path.exists():
        if runner.read(path) != proof:
            raise ValueError('Retained exact packet equivalence changed')
    else:
        runner.exclusive_json(path, proof)
    return wire, dict(path=str(path.relative_to(root)), sha256=sha(path),
                      original_body_sha256=proof['original_sha256'], exact_expansion=True)


def authorize(root, tasks, diagnosis, before_directory, *, exact_shared_source_packets=None):
    """One source-bound change after saved measured overflow, before any call."""
    import hashlib
    root=Path(root).resolve();diagnosis=Path(diagnosis).resolve();before_directory=Path(before_directory).resolve()
    measurement=runner.read(diagnosis/'measurement.json');prompt=diagnosis/'prompt.txt'
    if (measurement['prompt_sha256']!=sha(prompt) or measurement['prompt_bytes']!=len(prompt.read_bytes())
            or measurement['prompt_bytes']<=measurement['transport']['maximum_prompt_bytes']):
        raise ValueError('Saved preflight must prove original unchanged request exceeded the cap')
    if not tasks or len(set(tasks))!=len(tasks) or any((root/'model_calls'/name).exists() for name in tasks):
        raise ValueError('Preflight-only repair cannot replace an actual model invocation')
    code=Path(__file__).parent.resolve()
    changed=['gameness_v3_runtime.py','gameness_v4_inline_schema.py']
    before={str(code/name):sha(before_directory/name) for name in changed}
    after={str(code/name):sha(code/name) for name in changed}
    files=[prompt,diagnosis/'measurement.json',root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json']
    files += [before_directory/name for name in changed]
    files += [code/name for name in changed+['gameness_v4_preflight_recovery.py','exact_evidence_alias.py']]
    packets=exact_shared_source_packets or {}
    if packets:
        from .mechanic_v3_shared_source_transport import validate_packet
        for ident,packet_path in packets.items():
            _,source_path,_=validate_packet(root,ident,packet_path)
            files += [Path(packet_path).resolve(),source_path.resolve()]
        files += [code/name for name in ['gameness_v4_shared_source_transport.py',
            'mechanic_v3_shared_source_transport.py','shared_document_wire.py']]
    prior={}
    for name in tasks:
        claim=root/'engineering/gameness_inline_schema'/(name+'.json')
        if claim.exists():
            value=runner.read(claim)
            if value.get('first_delivery') is not True:
                raise ValueError('Preflight requires unchanged original first-delivery claim')
            for file,digest in value['source_bindings'].items():
                if sha(Path(file))!=digest and before.get(file)!=digest:
                    raise ValueError('Prior claim has unrelated drift')
            files.append(claim);prior[name]=sha(claim)
    value=dict(version=VERSION,tasks=tasks,no_invocation_at_authorization=True,
        classification='NON_SCORING_TOOL_TRANSPORT',
        root_cause='Full original packet exceeded frozen prompt cap; share only exact repeated numbered evidence bodies. No sources, physical citations or real frames removed; preserve previous first-delivery claims.',
        before_code_bindings=before,after_code_bindings=after,prior_claims=prior,
        bindings={str(p):sha(p) for p in files},model_recalled=False,limits_unchanged=True)
    if packets:
        value['exact_shared_source_packets']={k:str(Path(v).resolve()) for k,v in packets.items()}
    path=root/AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Existing preflight recovery differs')
    else:runner.exclusive_json(path,value)
    return value
