"""Opt-in exact shared literals for complete author source sections.

Only source IDs and immutable packets explicitly bound by a diagnosed preflight
repair are eligible. Original bytes/physical lines, all other prompt text, and
all image/size limits remain unchanged. No code from a workspace is executed.
"""
from pathlib import Path
from . import shared_document_wire as shared, document_wire
from .protocol import sha, checked_path
from .mechanic_v3_runner import read

VERSION = 'mechanic-exact-shared-source-preflight.v1'


def source_entry(root, ident):
    matches = [v for v in read(Path(root)/'evidence_manifest.json')['items']
               if v['type'] == 'source' and v['id'] == ident]
    if len(matches) != 1:
        raise ValueError('Shared source identity absent or duplicated: '+ident)
    entry = matches[0]; path = checked_path(root, entry['path'])
    if sha(path) != entry['sha256']:
        raise ValueError('Shared author source bytes changed: '+ident)
    return entry, path


def validate_packet(root, ident, packet_path):
    entry, path = source_entry(root, ident)
    packet = Path(packet_path).read_text()
    marker = '\nEVIDENCE '+ident+' (exact document shared text):\n'
    # Each opt-in packet has exactly one full document and its literal table.
    if (packet.count(shared.TABLE_MARKER) != 1 or packet.count('\nEVIDENCE ') != 1
            or packet.count(marker) != 1 or not shared.verify_section(packet, path, ident)):
        raise ValueError('Shared source packet is not the exact original document: '+ident)
    return entry, path, packet


def original_section(prompt, path, ident):
    full = '\nEVIDENCE '+ident+'\n'+''.join(
        f'{n}: {line}\n' for n, line in enumerate(path.read_text().splitlines(), 1))+'\n'
    candidates = [full, document_wire.section(path, ident)+'\n']
    matches = [v for v in candidates if prompt.count(v) == 1]
    if len(matches) != 1:
        raise ValueError('Shared transport requires one complete original source section: '+ident)
    return matches[0]


def immutable_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_text() != text:
            raise ValueError('Preserved shared source transport differs')
    else:
        with path.open('x') as handle:
            handle.write(text)


def apply(root, packets, prompt, directory):
    proofs = []; body = prompt
    for index, (ident, packet_path) in enumerate(sorted(packets.items()), 1):
        entry, path, packet = validate_packet(root, ident, packet_path)
        original = original_section(body, path, ident)
        submitted = packet+'\n'
        if len(submitted.encode()) >= len(original.encode()):
            raise ValueError('Shared source transport does not reduce its source section')
        folder = Path(directory)/f'shared_source_{index:03d}'
        before = folder/'original_section.txt'; after = folder/'submitted_section.txt'
        immutable_text(before, original); immutable_text(after, submitted)
        body = body.replace(original, submitted, 1)
        proofs.append(dict(version=VERSION, evidence_id=ident, source=entry,
            source_sha256=sha(path), physical_line_count=len(path.read_text().splitlines()),
            authorized_packet=str(Path(packet_path).resolve()), authorized_packet_sha256=sha(Path(packet_path)),
            original_section=str(before.resolve()), original_section_sha256=sha(before),
            submitted_section=str(after.resolve()), submitted_section_sha256=sha(after),
            exact_source_bytes=True, original_physical_lines=True))
    return body, proofs


def expand(root, packets, submitted, proofs, directory):
    if len(proofs) != len(packets) or {p['evidence_id'] for p in proofs} != set(packets):
        raise ValueError('Shared source proof IDs differ from explicit authorization')
    body = submitted
    for index, proof in reversed(list(enumerate(proofs, 1))):
        ident = proof['evidence_id']; entry, path, packet = validate_packet(root, ident, packets[ident])
        folder = Path(directory)/f'shared_source_{index:03d}'
        before = folder/'original_section.txt'; after = folder/'submitted_section.txt'
        expected = dict(version=VERSION, evidence_id=ident, source=entry,
            source_sha256=sha(path), physical_line_count=len(path.read_text().splitlines()),
            authorized_packet=str(Path(packets[ident]).resolve()), authorized_packet_sha256=sha(Path(packets[ident])),
            original_section=str(before.resolve()), original_section_sha256=sha(before),
            submitted_section=str(after.resolve()), submitted_section_sha256=sha(after),
            exact_source_bytes=True, original_physical_lines=True)
        if proof != expected or after.read_text() != packet+'\n':
            raise ValueError('Shared source packet/proof binding differs')
        original = before.read_text(); replacement = after.read_text()
        if original_section(original, path, ident) != original or body.count(replacement) != 1:
            raise ValueError('Shared source original section or actual delivery differs')
        body = body.replace(replacement, original, 1)
    return body
