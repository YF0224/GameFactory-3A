"""Verify one additive shared-tool revision against immutable native-slot pins.

Original repair proofs, claims and captures remain unchanged. This accepts only
exact AST additions for the separate Unity supplemental-diagnostic path; every
other token represented in the AST and the entire reviewed helper stay pinned.
Archived sources are parsed as data, never imported or executed.
"""
from pathlib import Path
import ast
import copy
import json

from .protocol import sha

VERSION = 'whitebox-native-slot-additive-toolchain-compatibility.v1'
CERTIFICATE = 'native_slot_toolchain_compatibility.json'


def tree(text):
    return ast.parse(text)


def shape(node):
    return ast.dump(node, include_attributes=False)


def statements(text):
    return tree(text).body


PACKET_NEW = statements("""body = '\\n'.join(parts)
from .unity_deferred_source_judge import require_packet as require_supplemental_packet
require_supplemental_packet(root, manifest, body)
return body,omitted
""")
PACKET_OLD = statements("return '\\n'.join(parts),omitted")
DOCUMENT_PACKET_ADDITION = statements("if e['type'] in {'source', 'document'} and (root / 'supplemental_source_diagnostic.json').is_file() and (e['id'] not in manifest.get('delivered_channel_lines', {})):\n    from .document_wire import section as document_section, verify_section as verify_document\n    raw_document = (root / e['path']).read_text(errors='strict')\n    raw_characters = sum((len(f'{n}: {line}\\n') for n, line in enumerate(raw_document.splitlines(), 1)))\n    encoded_document = document_section(root / e['path'], e['id'])\n    document_limit = 300000 if static else 180000\n    if len(encoded_document) < raw_characters and len(encoded_document) <= 90000 and (characters['static'] + len(encoded_document) <= document_limit):\n        if not verify_document(encoded_document, root / e['path'], e['id']):\n            raise ValueError('Exact document delivery differs')\n        parts.append(encoded_document)\n        characters['static'] += len(encoded_document)\n        from .document_wire import persist as persist_document\n        persist_document(root, e, encoded_document)\n        continue")[0]
PUBLICATION_ADDITIONS = [statements(text) for text in (
    'from .unity_deferred_source_judge import disclosure as supplemental_disclosure',
    'supplemental = supplemental_disclosure(attempt)',
    "if supplemental:\n    status=status[:-1]+'；补充源码诊断未完成）'",
    "if supplemental:\n    record['supplemental_source_diagnostic'] = supplemental\n    record['source_bindings'][supplemental['path']] = supplemental['sha256']",
)]


def additive_only(before, after, name):
    """Return true only for the exact reviewed full-module transformation."""
    old, current = tree(before), tree(after)
    current = copy.deepcopy(current)
    if name == 'batch.py':
        functions = [n for n in current.body if isinstance(n, ast.FunctionDef) and n.name == 'packet']
        if len(functions) != 1 or [shape(n) for n in functions[0].body[-4:]] != [shape(n) for n in PACKET_NEW]:
            return False
        functions[0].body[-4:] = copy.deepcopy(PACKET_OLD)
        class RemoveDocument(ast.NodeTransformer):
            count = 0
            def visit_If(self, node):
                if shape(node) == shape(DOCUMENT_PACKET_ADDITION):
                    self.count += 1
                    return None
                return self.generic_visit(node)
        removal = RemoveDocument()
        removal.visit(functions[0])
        if removal.count > 1:
            return False
    elif name == 'pending_publication.py':
        counts = [0]*len(PUBLICATION_ADDITIONS)
        class Remove(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                if node.name != 'publish':
                    return node
                self.generic_visit(node)
                return node
            def visit(self, node):
                for i, pattern in enumerate(PUBLICATION_ADDITIONS):
                    if shape(node) == shape(pattern[0]):
                        counts[i] += 1
                        return None
                return super().visit(node)
        # Only mutate the publish function, never unrelated functions/module code.
        functions = [n for n in current.body if isinstance(n, ast.FunctionDef) and n.name == 'publish']
        if len(functions) != 1:
            return False
        Remove().visit(functions[0])
        if counts != [1]*len(counts):
            return False
    else:
        return False
    return shape(old) == shape(current)


def verify(proof_path, changed_path, expected):
    """Strictly verify a persisted, source-bound reviewed compatibility proof."""
    proof_path, changed_path = Path(proof_path).resolve(), Path(changed_path).resolve()
    path = proof_path.parent/CERTIFICATE
    if not path.is_file():
        return False
    proof, receipt = json.loads(proof_path.read_text()), json.loads(path.read_text())
    native = Path(__file__).resolve().parent
    if (receipt.get('version') != VERSION or receipt.get('proof_path') != str(proof_path)
            or receipt.get('proof_sha256') != sha(proof_path)
            or changed_path.parent != native or changed_path.name not in {'batch.py','pending_publication.py'}
            or str(native/'native_slot_recovery.py') not in proof.get('changed_files', {})
            or set(receipt.get('sources', {})) != {'batch.py','pending_publication.py'}
            or receipt.get('non_scoring_semantics') is not True
            or receipt.get('helper_path') != str(native/'unity_deferred_source_judge.py')
            or sha(native/'unity_deferred_source_judge.py') != receipt.get('helper_sha256')
            or not receipt.get('regressions')):
        return False
    # The additional exact branch only applies to explicit Unity supplemental
    # diagnostics. Bind its entire reversible document implementation as well.
    document_branch = any(shape(n) == shape(DOCUMENT_PACKET_ADDITION)
                          for n in ast.walk(tree((native/'batch.py').read_text())))
    additional = receipt.get('additional_helpers', {})
    if document_branch:
        if (set(additional) != {str(native/'document_wire.py')}
                or any(sha(Path(file)) != digest for file, digest in additional.items())):
            return False
    elif additional:
        return False
    for file, digest in receipt['regressions'].items():
        if sha(Path(file)) != digest:
            return False
    for name, row in receipt['sources'].items():
        original = Path(row['original_path'])
        current = native/name
        bound = proof['changed_files'].get(str(current), {}).get('after_sha256')
        if (sha(original) != bound or row.get('original_sha256') != bound
                or sha(current) != row.get('current_sha256')
                or not additive_only(original.read_text(), current.read_text(), name)):
            return False
    return receipt['sources'][changed_path.name]['original_sha256'] == expected
