"""Content identity for rubrics and child bindings, independent of file formatting."""
import copy
import hashlib
import json


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def contract_digest(contract):
    payload = copy.deepcopy(contract)
    payload.pop('contract_id', None)
    for key in list(payload):
        if key.startswith('_'):
            payload.pop(key)
    for row in payload.get('assertions', []):
        row.get('binding', {}).pop('contract_identity', None)
    return fingerprint(payload)


def identity(contract):
    return {'contract_id': contract['contract_id'], 'version': contract['version'],
            'content_sha256': contract_digest(contract)}


def seal(contract):
    sha = contract_digest(contract)
    contract['contract_id'] = f"{contract['game_id']}.whitebox.{contract['version']}.{sha}"
    value = identity(contract)
    for row in contract['assertions']:
        row['binding']['contract_identity'] = dict(value)
    return value


def verify(contract):
    value = identity(contract)
    for row in contract['assertions']:
        bound = row.get('binding', {}).get('contract_identity')
        if bound is not None and bound != value:
            raise ValueError('rubric content/identity mismatch: ' + row['assertion_id'])
    return value
