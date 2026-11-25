"""Bounded, anchored field edits to a preserved plan; never a replacement plan."""
import bisect
import copy
import hashlib
import json
import re
from pathlib import Path

VERSION = 'whitebox-plan-field-patch.v1'
PATCH_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['base_sha256', 'edits'],
    'properties': {
        'base_sha256': {'type': 'string'},
        'edits': {'type': 'array', 'minItems': 1, 'maxItems': 96, 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['op', 'path', 'before_json', 'value_json'],
            'properties': {
                'op': {'type': 'string', 'enum': ['add', 'replace', 'remove']},
                'path': {'type': 'string'}, 'before_json': {'type': 'string'},
                'value_json': {'type': 'string'}}}}}}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def loads(raw):
    from .codex import unique_json_object, reject_json_constant
    return json.loads(raw, object_pairs_hook=unique_json_object, parse_constant=reject_json_constant)


def tokens(pointer):
    if not pointer.startswith('/') or re.search(r'~(?![01])', pointer):
        raise ValueError('patch path must be a non-root JSON pointer')
    return [part.replace('~1', '/').replace('~0', '~') for part in pointer[1:].split('/')]


def member(parent, token):
    if isinstance(parent, dict):
        if token not in parent:
            raise ValueError('patch path does not exist: ' + token)
        return token
    if isinstance(parent, list) and re.fullmatch(r'0|[1-9][0-9]*', token) and int(token) < len(parent):
        return int(token)
    raise ValueError('patch path has invalid container/index: ' + token)


def small_value(value):
    return not isinstance(value, (dict, list)) or (
        isinstance(value, list) and len(value) <= 48
        and all(not isinstance(item, (dict, list)) for item in value))


def apply(base_raw, patch):
    from .codex import validate_schema
    validate_schema(patch, PATCH_SCHEMA)
    if patch['base_sha256'] != digest(base_raw):
        raise ValueError('patch base SHA256 mismatch')
    result = copy.deepcopy(loads(base_raw))
    paths = [tokens(edit['path']) for edit in patch['edits']]
    for i, path in enumerate(paths):
        if path[0] == 'planning_identity':
            raise ValueError('patch cannot alter frozen planning_identity')
        if any(path[:len(other)] == other or other[:len(path)] == path for other in paths[:i]):
            raise ValueError('patch paths overlap or repeat')
    for edit, path in zip(patch['edits'], paths):
        parent = result
        for token in path[:-1]:
            parent = parent[member(parent, token)]
        before, value = loads(edit['before_json']), loads(edit['value_json'])
        if not small_value(value):
            raise ValueError('patch must edit fields, not replace plan/probe/step objects')
        if edit['op'] == 'add':
            if not isinstance(parent, dict) or path[-1] in parent or before is not None:
                raise ValueError('patch add needs an absent object field and null before_json')
            parent[path[-1]] = value
        else:
            key = member(parent, path[-1])
            current = parent[key]
            if not small_value(current):
                raise ValueError('patch cannot remove/replace a structured subtree')
            if json.dumps(current, sort_keys=True) != json.dumps(before, sort_keys=True):
                raise ValueError('patch before_json differs from original field: ' + edit['path'])
            if edit['op'] == 'replace':
                parent[key] = value
            else:
                if not isinstance(parent, dict) or value is not None:
                    raise ValueError('patch remove only supports object fields and null value_json')
                del parent[key]
    return result


def locations(raw):
    """Physical source coordinates, including compact one-line JSON responses."""
    text = raw.decode('utf-8')
    lexer = re.finditer(r'"(?:[^"\\]|\\.)*"|[{}\[\]:,]|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?', text)
    stream = iter(lexer)
    token = next(stream, None)
    found = {}
    newlines = [match.start() for match in re.finditer('\n', text)]
    def visit(path):
        nonlocal token
        line = bisect.bisect_left(newlines, token.start())
        found[path] = {'line': line + 1, 'column': token.start() - (newlines[line-1] if line else -1)}
        kind = token.group()
        token = next(stream, None)
        if kind == '{':
            while token.group() != '}':
                key = json.loads(token.group()).replace('~', '~0').replace('/', '~1')
                next(stream)  # colon
                token = next(stream)
                visit(path + '/' + key)
                if token.group() == ',':
                    token = next(stream)
            token = next(stream, None)
        elif kind == '[':
            index = 0
            while token.group() != ']':
                visit(path + '/' + str(index))
                index += 1
                if token.group() == ',':
                    token = next(stream)
            token = next(stream, None)
    visit('')
    return found


def feedback(base_path, error):
    """Small correction-only context; never resend the original planning prompt."""
    base_path = Path(base_path).resolve()
    raw = base_path.read_bytes()
    coords = locations(raw)
    errors = copy.deepcopy(getattr(error, 'diagnostics', []))
    if not errors:
        match = re.match(r'\$((?:\.[^.:\[ ]+|\[\d+\])*)', str(error))
        path = ''
        if match:
            path = ''.join('/' + (item[1:-1] if item.startswith('[') else item[1:])
                           for item in re.findall(r'\.[^.:\[ ]+|\[\d+\]', match.group(1)))
        errors = [{'path': path, 'reason': str(error)}]
    supported_keys = next((row.get('supported_keys') for row in errors if row.get('supported_keys')), None)
    for row in errors:
        row.pop('supported_keys', None)
        row.pop('hint', None)
        row.update(coords.get(row.get('path', ''), {}))
    report = {'version': VERSION, 'base_path': str(base_path), 'base_sha256': digest(raw),
              'errors': errors, 'original_schema': str(base_path.parent/'schema.json')}
    if supported_keys:
        report['supported_keys'] = supported_keys
    text = ('Repair the preserved plan with field edits ONLY. Do not regenerate a plan or repeat source analysis.\n'
            + json.dumps(report, ensure_ascii=False, separators=(',', ':')) + '\n'
            'Read the base JSON once; inspect only diagnosed fields and directly affected timing/coverage/endpoint links. '
            'Use targeted source excerpts only when the diagnosis requires control bindings. '
            'Return base_sha256 and edits with op=add/replace/remove, path=JSON pointer, '
            'before_json=serialized original value (null for add), value_json=serialized new value (null for remove). '
            'Do not return a full plan. Edit leaf fields or small primitive arrays; no object/route replacement. '
            'For keyboard-to-mouse conversion edit kind, remove keyboard-only fields, add button/x/y. '
            'Keep unrelated fields and frozen planning_identity unchanged; preserve original rubric and evidence. '
            'All original schema, source, input, timing and endpoint validators still apply. '
            'Do not invent controls, observations or successful gameplay. Source paths are input/project-relative. '
            'There is one correction, within the original deadline; no new budget.\n')
    return report, text


def save_application(folder, base_path, patch, derived):
    from .protocol import dump, sha
    folder, base_path = Path(folder), Path(base_path).resolve()
    dump(folder/'applied_plan.json', derived)
    import os
    receipt = {'version': VERSION, 'base_path': os.path.relpath(base_path, folder),
               'base_sha256': sha(base_path), 'patch_sha256': sha(folder/'response.json'),
               'derived_sha256': sha(folder/'applied_plan.json'), 'edits': patch['edits']}
    dump(folder/'patch_application.json', receipt)
    return folder/'applied_plan.json'


def verify_application(path, binding):
    from .protocol import sha
    path = Path(path)
    receipt_path = path.parent/'patch_application.json'
    if binding.get('patch_receipt_sha256') != sha(receipt_path):
        raise ValueError('plan patch receipt SHA256 mismatch')
    receipt = loads(receipt_path.read_bytes())
    base = (path.parent/receipt['base_path']).resolve()
    if not base.is_relative_to(path.parent.parent.resolve()) or not base.is_file():
        raise ValueError('plan patch base escapes model_calls or is missing')
    patch_path = path.parent/'response.json'
    if (receipt['version'] != VERSION or sha(base) != receipt['base_sha256']
            or sha(patch_path) != receipt['patch_sha256'] or sha(path) != receipt['derived_sha256']):
        raise ValueError('plan patch source SHA256 mismatch')
    patch = loads(patch_path.read_bytes())
    if patch['edits'] != receipt['edits'] or apply(base.read_bytes(), patch) != loads(path.read_bytes()):
        raise ValueError('plan patch replay differs from derived plan')
