"""Opt-in exact source literals for Gameness complete original-source bodies.

Every source byte and original physical line is validated; runtime context and
all frame delivery rules remain unchanged. Only measured preflight repairs opt in.
"""
from pathlib import Path
from . import mechanic_v3_shared_source_transport as shared_source
from .protocol import sha

VERSION = 'gameness-v4-exact-shared-source.v1'


def section(path, ident):
    return '\nEVIDENCE '+ident+' (complete original source)\n'+''.join(
        f'{n}: {line}\n' for n, line in enumerate(path.read_text(errors='replace').splitlines(), 1))


def apply(root, packets, body):
    proofs = []
    for ident, packet_path in sorted(packets.items()):
        entry, path, packet = shared_source.validate_packet(root, ident, packet_path)
        original = section(path, ident)
        if body.count(original) != 1:
            raise ValueError('Expected one complete original Gameness source: '+ident)
        submitted = packet+'\n'
        if len(submitted.encode()) >= len(original.encode()):
            raise ValueError('Shared Gameness source does not reduce the original section')
        body = body.replace(original, submitted, 1)
        proofs.append(dict(version=VERSION, evidence_id=ident, source=entry,
            source_sha256=sha(path), packet_path=str(Path(packet_path).resolve()),
            packet_sha256=sha(Path(packet_path)), original_sha256=__import__('hashlib').sha256(original.encode()).hexdigest(),
            physical_line_count=len(path.read_text(errors='replace').splitlines()),
            exact_source_bytes=True, original_physical_lines=True))
    return body, proofs


def expand(root, packets, body, proofs):
    if len(proofs) != len(packets) or {p['evidence_id'] for p in proofs} != set(packets):
        raise ValueError('Shared Gameness source proof identities differ')
    for proof in reversed(proofs):
        ident = proof['evidence_id']
        entry, path, packet = shared_source.validate_packet(root, ident, packets[ident])
        original = section(path, ident)
        # Recompute every field from original immutable sources and packets.
        _, expected = apply(root, {ident: packets[ident]}, original)
        if proof != expected[0] or body.count(packet+'\n') != 1:
            raise ValueError('Shared Gameness source proof or submitted bytes changed')
        body = body.replace(packet+'\n', original, 1)
    return body
