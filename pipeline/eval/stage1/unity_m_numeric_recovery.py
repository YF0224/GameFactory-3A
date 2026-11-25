"""Restricted real acceptance of bounded, exact EVENT lexemes after capacity failure.

No batch admission is granted. Existing publications and requests are immutable.
"""
from pathlib import Path
import hashlib
import json
from . import batch, event_wire, unity_m_admission as admission
from .protocol import sha

VERSION = 'unity-m-bounded-shared-numeric-event-repair.v2'
IDENTITY = 'Sol__G004_desert_observatory'
FILES = {'unity_m_numeric_recovery.py', 'unity_m_event_packets.py',
         'unity_m_judge.py', 'unity_m_delivery.py', 'unity_m_runtime_wire.py',
         'unity_m_intake_recovery.py', 'unity_m_plan_recovery.py', 'unity_m_runtime.py',
         'unity_m_schema_recovery.py', 'unity_m_runtime_reuse.py', 'unity_m_output_recovery.py'}


def require(workspace, identity, column, descriptor):
    if identity != IDENTITY or column != 'Gameness':
        raise ValueError('Numeric EVENT acceptance is restricted to its actual failed column')
    workspace = Path(workspace).resolve()
    value = batch.read(descriptor)
    if (value.get('version') != VERSION or value.get('identity') != identity
            or value.get('column') != column or value.get('batch_admitted') is not False):
        raise ValueError('Exact restricted numeric EVENT repair descriptor required')
    prior_path = Path(value['prior_admission'])
    if sha(prior_path) != value['prior_admission_sha256']:
        raise ValueError('Prior complete native E2E admission changed')
    prior = batch.read(prior_path)
    before, after = prior['verification_production'], admission.production()
    if value['current_production'] != after or prior.get('version') != admission.VERSION:
        raise ValueError('Current full numeric repair production drift')
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    if changed != set(value['changed_files']) or not changed:
        raise ValueError('Complete exact numeric repair delta required')
    for p in changed:
        if Path(p).parent != Path(__file__).resolve().parent or Path(p).name not in FILES:
            raise ValueError('Numeric EVENT repair cannot change native or scoring dependencies')
        archive = value['changed_files'][p]
        if p in before:
            if not archive or sha(Path(archive)) != before[p]:
                raise ValueError('Exact pre-repair bytes required')
        elif archive is not None:
            raise ValueError('New recovery dependency must be explicit')
    # Verify the immutable historical gate transition against its historical map.
    transition = Path(prior['gate_transition'])
    if sha(transition) != prior['gate_transition_sha256']:
        raise ValueError('Historical gate transition changed')
    old = batch.read(transition)
    if (old['current_production'] != before or old['executed_producer'] != prior['executed_producer']
            or old['classification'] != 'GATE_ONLY_NO_SCORING_OR_TRANSPORT_CHANGE'):
        raise ValueError('Historical complete gate provenance changed')
    executed = old['executed_producer']['production']
    delta = {p for p in executed.keys() | before.keys() if executed.get(p) != before.get(p)}
    if delta != set(old['changed_files']):
        raise ValueError('Historical gate delta changed')
    for p in delta:
        if Path(p).parent != Path(__file__).resolve().parent or Path(p).name not in admission.GATE_FILES:
            raise ValueError('Historical gate contains a non-gate change')
        archived = old['changed_files'][p]
        if (p in executed and (not archived or sha(Path(archived)) != executed[p])) or (p not in executed and archived is not None):
            raise ValueError('Historical executed bytes changed')
    for spec in (value['regression'], old['regression']):
        report = Path(spec['path'])
        if (sha(report) != spec['sha256'] or batch.read(report).get('exit_code') != 0
                or batch.read(report).get('tests_passed', 0) < 1):
            raise ValueError('Passing targeted and historical regressions required')
    recorded = workspace/'runs'/identity
    pointer = recorded/'unity_m_evidence.json'
    root = Path(batch.read(pointer)['root'])
    if (value['source_pointer_sha256'] != sha(pointer) or value['root'] != str(root)
            or value['scope_sha256'] != sha(workspace/'scopes/unity_m_original/scope.json')):
        raise ValueError('Exact recorded original and scope required')
    failure = Path(value['parent_failure'])
    if (sha(failure) != value['parent_failure_sha256'] or
            'ValueError: Complete runtime context exceeds frozen per-turn cap' not in failure.read_text()):
        raise ValueError('Actual complete runtime capacity failure required')
    # Current verifier rechecks all original sources, pixels, accepted judgments and sync.
    old_root, proof = admission.evidence(workspace, prior['e2e']['identity'])
    if proof != prior['e2e']:
        raise ValueError('Historical accepted two-column E2E changed')
    candidates = [old_root/'unity_m_judge_producer.json', old_root/'unity_m_judge_continuation.json',
                  *sorted((old_root/'unity_m_judge_continuations').glob('*.json'))]
    if not any(p.exists() and batch.read(p).get('after_producer',batch.read(p)) == prior['executed_producer'] for p in candidates):
        raise ValueError('Historical executed producer missing')
    from .unity_m_judge import exact_json
    old_pointer = root/'unity_m_numeric_event_repair.json'
    if sha(old_pointer) != value['previous_repair_pointer_sha256']:
        raise ValueError('Previous failed numeric repair pointer changed')
    previous = batch.read(old_pointer)
    previous_descriptor = Path(previous['descriptor'])
    if sha(previous_descriptor) != previous['sha256'] or batch.read(previous_descriptor)['root'] != str(root):
        raise ValueError('Previous failed numeric descriptor changed')
    target = root/'unity_m_shared_numeric_event_repair.json'
    pointer = dict(descriptor=str(Path(descriptor).resolve()), sha256=sha(Path(descriptor)))
    if target.exists() and batch.read(target) != pointer:
        parent = value.get('parent_shared_repair', {})
        old = batch.read(target)
        if (parent.get('pointer_sha256') != sha(target) or parent.get('descriptor') != old['descriptor']
                or parent.get('descriptor_sha256') != old['sha256'] or sha(Path(old['descriptor'])) != old['sha256']):
            raise ValueError('Exact preserved shared-runtime repair parent required')
        for path, digest in value.get('continuation_failure_bindings', {}).items():
            if sha(Path(path)) != digest:raise ValueError('Shared-runtime continuation failure changed')
        if not value.get('continuation_failure_bindings'):
            raise ValueError('Actual shared-runtime continuation failure required')
        target = root/'unity_m_shared_numeric_event_repair_continuations'/(pointer['sha256']+'.json')
    exact_json(target, pointer)
    return value


def enabled(root):
    pointer = Path(root)/'unity_m_shared_numeric_event_repair.json'
    if not pointer.exists():
        return False
    value = batch.read(pointer); descriptor = Path(value['descriptor'])
    if sha(descriptor) != value['sha256']:
        raise ValueError('Numeric EVENT repair binding changed')
    repair = batch.read(descriptor)
    if (repair['version'] != VERSION or repair['root'] != str(Path(root).resolve())
            or repair['identity'] != IDENTITY or repair['column'] != 'Gameness'):
        raise ValueError('Numeric EVENT repair identity changed')
    return True


def verify_task(root, task):
    """Verify all actual prompt wires against every original physical occurrence."""
    if not task.get('numeric_event_packets'):
        return None
    if not enabled(root) or task['column'] != 'Gameness':
        raise ValueError('Numeric task lacks qualified original recovery')
    path = Path(root)/'runtime/event_trace.jsonl'
    raw = path.read_bytes(); lines = raw.splitlines(keepends=True)
    expected_rows = [n for n, row in enumerate(lines, 1) if row.strip()]
    from .unity_m_runtime_wire import verify
    packet_texts, shared_proof = verify(task['prompt'], task['shared_runtime_packets'])
    expected_packet_hashes=[]
    for parent in task['parents'].values():
        for packet in parent.get('packets',[]):
            digest=packet['packet_sha256']
            if digest not in expected_packet_hashes: expected_packet_hashes.append(digest)
    prefix='\nBOUNDED ORIGINAL RUNTIME PACKET\n'
    if (any(not p.startswith(prefix) for p in packet_texts) or
            [hashlib.sha256(p[len(prefix):].encode()).hexdigest() for p in packet_texts] != expected_packet_hashes):
        raise ValueError('Full decoded runtime metadata differs from bound original packets')
    runtime_text = ''.join(packet_texts)
    sections = runtime_text.split(event_wire.MARKER)[1:]
    actual = [s.split('\n', 1)[0] for s in sections]
    from .endpoint_channels import ROW_LIMIT, BYTE_LIMIT
    decoded_sections = {}
    for submitted in actual:
        wire = json.loads(submitted)
        binding = event_wire.binding(wire)
        decoded = event_wire.decode(wire)
        if (submitted != event_wire.dumps(wire) or wire['encoding'] != event_wire.NUMERIC_VERSION
                or binding['source_sha256'] != hashlib.sha256(raw).hexdigest()
                or len(decoded) > ROW_LIMIT or binding['wire_bytes'] > BYTE_LIMIT
                or sum(len(json.dumps(json.loads(data),ensure_ascii=False).encode()) for data in decoded.values()) > BYTE_LIMIT
                or any(n < 1 or n > len(lines) or data != lines[n-1] for n,data in decoded.items())):
            raise ValueError('Bounded decoded original EVENT bytes changed')
        decoded_sections[binding['wire_sha256']] = (submitted,binding,list(decoded))
    expected = []
    for parent in task['parents'].values():
        union = []
        for packet in parent.get('packets', []):
            binding = packet.get('event_wire')
            if binding is None or binding['wire_sha256'] not in decoded_sections:
                raise ValueError('Numeric parent omitted its reversible EVENT packet')
            submitted,actual_binding,numbers = decoded_sections[binding['wire_sha256']]
            if binding != actual_binding or numbers != packet['physical_lines']:
                raise ValueError('Decoded original EVENT selection changed')
            union.extend(numbers)
            if submitted not in expected:
                expected.append(submitted)
        if union != expected_rows:
            raise ValueError('All original physical EVENT occurrences required in order')
    if actual != expected:
        raise ValueError('Actual ordered EVENT delivery differs from complete original packets')
    if task['rules'].get('EVENT') != {'enum': expected_rows}:
        raise ValueError('Original physical EVENT citation whitelist changed')
    return dict(version=VERSION,source_sha256=hashlib.sha256(raw).hexdigest(),
                original_rows=len(expected_rows),bounded_packets=len(expected),
                exact_original_bytes=True,extended_row_policy=False,shared_runtime=shared_proof)
