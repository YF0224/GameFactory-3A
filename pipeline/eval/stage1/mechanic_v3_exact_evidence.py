"""Opt-in lossless full-prompt evidence aliases for diagnosed preflight overflow.

The immutable original pending claim is retained by source preflight recovery.
Historical delivery verification depends on saved bytes, never current code SHA.
"""
from pathlib import Path
from . import exact_evidence_alias as alias
from . import mechanic_v3_source_delivery as source
from . import mechanic_v3_shared_source_transport as shared
from .mechanic_v3_runner import exclusive_json, read
from .protocol import sha
from .codex import READ_ONLY_EVAL_INSTRUCTIONS

VERSION = 'mechanic-exact-evidence-preflight.v1'


def directory(root, name):
    return Path(root)/'requests'/name/'exact_evidence_transport'


def apply(root, name, prompt):
    claim = source.authorization(root, name)
    if not claim or claim.get('exact_evidence_body_transport') is not True:
        return prompt, None
    if not claim.get('pending_claim_preserved'):
        raise ValueError('Exact evidence transport requires diagnosed preflight lineage')
    path = directory(root, name); path.mkdir(parents=True, exist_ok=True)
    intermediary, shared_proofs = shared.apply(
        root, claim.get('exact_shared_source_packets', {}), prompt, path)
    wire, proof = alias.encode(intermediary)
    if ((not proof['aliases'] and not shared_proofs) or
            len(wire.encode()) >= len(prompt.encode())):
        raise ValueError('Exact evidence transport did not reduce the complete packet')
    for filename, text in [('original_prompt.txt', prompt), ('submitted_prompt.txt', wire)]:
        target = path/filename
        if target.exists():
            if target.read_text() != text:
                raise ValueError('Preserved exact evidence packet differs')
        else:
            with target.open('x') as handle:
                handle.write(text)
    claim_path = source._path(root, name)
    value = dict(version=VERSION, alias_proof=proof, authorization=str(claim_path),
                 authorization_sha256=sha(claim_path), unchanged_limits=True,
                 scoring_semantics_unchanged=True)
    if shared_proofs:
        value['shared_sources'] = shared_proofs
        value['original_prompt_sha256'] = alias.digest(prompt)
    target = path/'equivalence.json'
    if target.exists():
        if read(target) != value:
            raise ValueError('Preserved exact evidence equivalence differs')
    else:
        exclusive_json(target, value)
    return wire, value


def expanded(root, name, submitted):
    """Validate actual submitted bytes and reconstruct for full-source auditing."""
    path = directory(root, name)
    if not (path/'equivalence.json').exists():
        return submitted
    value = read(path/'equivalence.json')
    if value.get('version') != VERSION or value.get('unchanged_limits') is not True:
        raise ValueError('Unknown exact evidence equivalence')
    claim_path = Path(value['authorization'])
    if claim_path.resolve() != source._path(root, name).resolve() or sha(claim_path) != value['authorization_sha256']:
        raise ValueError('Exact evidence authorization changed')
    claim = read(claim_path)
    if claim.get('exact_evidence_body_transport') is not True or not claim.get('pending_claim_preserved'):
        raise ValueError('Missing exact preflight authorization')
    prefix = READ_ONLY_EVAL_INSTRUCTIONS if submitted.startswith(READ_ONLY_EVAL_INSTRUCTIONS) else ''
    wire = submitted[len(prefix):]
    if wire != (path/'submitted_prompt.txt').read_text():
        raise ValueError('Actual exact evidence wire differs')
    original = (path/'original_prompt.txt').read_text()
    intermediary = alias.decode(wire)
    reconstructed = shared.expand(root, claim.get('exact_shared_source_packets', {}),
        intermediary, value.get('shared_sources', []), path)
    encoded, proof = alias.encode(intermediary)
    if (encoded != wire or proof != value['alias_proof'] or reconstructed != original or
            ('shared_sources' in value and value.get('original_prompt_sha256') != alias.digest(original))):
        raise ValueError('Exact evidence original/submitted expansion differs')
    return prefix+original


def bindings(root, name):
    path = directory(root, name)
    return {str(p): sha(p) for p in sorted(path.rglob('*')) if p.is_file()}
