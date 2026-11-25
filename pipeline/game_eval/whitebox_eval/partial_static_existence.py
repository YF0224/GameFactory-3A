"""Withdraw unsupported source-existence claims without inventing source evidence.

This explicit recovery preserves the successful raw Sol reply and all references.
It can only lower EXISTS to UNKNOWN when entry/implementation/binding roles or
an affirmative entry connection are absent. Source identities, paths, hashes,
line ranges, schema, model provenance, and every retained claim remain strict.
"""
import copy
from pathlib import Path

from . import codex, static_existence
from .protocol import dump, sha

VERSION = 'whitebox-partial-static-existence.v1'
RECEIPT = 'static_existence_normalization.json'


def normalize(root, protocol, original):
    """Return a reproducible conservative derivation or reject invalid evidence."""
    root = Path(root)
    sources = codex.load_plan_json(root/'input_manifest.json')['snapshot_hashes']
    codex.validate_schema(original, static_existence.schema(
        protocol, static_existence.identity(root, protocol), sources))
    result = copy.deepcopy(original)
    withdrawals = []
    for ident, row in result['checks'].items():
        roles = {ref['role'] for ref in row['evidence']}
        missing = sorted({'implementation', 'entry', 'binding'} - roles)
        if row['static_existence'] != 'EXISTS' or (row['connected_to_entry'] and not missing):
            continue
        # An empty explanation is a malformed response, not a claim to repair.
        if not row['reason'].strip():
            raise ValueError('Partial static recovery requires the original limitation reason')
        withdrawals.append({'criterion_id': ident, 'from': 'EXISTS', 'to': 'UNKNOWN',
            'missing_roles': missing, 'original_connected_to_entry': row['connected_to_entry']})
        row['static_existence'] = 'UNKNOWN'
        row['connected_to_entry'] = False
        row['reason'] = ('[PARTIAL_STATIC: unsupported EXISTS withdrawn; source evidence retained] '
                         + row['reason'])
    # This validates ALL preserved references, including those of withdrawn
    # claims. No bad SHA/path/physical range can disappear through normalization.
    static_existence.validate_result(root, protocol, result)
    return result, withdrawals


def successful_reply(root, response):
    root, response = Path(root).resolve(), Path(response).resolve()
    if (not response.is_relative_to(root/'model_calls') or not response.is_file()
            or response.name != 'response.json'
            or not response.parent.name.startswith('static_existence')):
        raise ValueError('Partial static recovery requires a preserved raw static response')
    invocation = codex.load_plan_json(response.parent/'invocation.json')
    command = invocation.get('command', [])
    model = static_existence.MODEL
    if (invocation.get('exit_code') != 0 or invocation.get('model_requested') != model
            or '--model' not in command or command.index('--model')+1 >= len(command)
            or command[command.index('--model')+1] != model):
        raise ValueError('Partial static recovery requires a successful real Sol invocation')
    return invocation


def accept(root, protocol, response, *, authorization):
    """Create an explicit artifact once; never replace a previously accepted review."""
    root, response = Path(root).resolve(), Path(response).resolve()
    if not isinstance(authorization, str) or not authorization.strip():
        raise ValueError('Explicit partial static authorization required')
    if any((root/name).exists() for name in ('static_existence.json', RECEIPT, 'sol_plan.json', 'background_record')):
        raise ValueError('Existing review/plan/capture is protected')
    successful_reply(root, response)
    original = codex.load_plan_json(response)
    result, withdrawals = normalize(root, protocol, original)
    if not withdrawals:
        raise ValueError('No unsupported EXISTS claim qualifies for partial static recovery')
    receipt = {'version': VERSION, 'authorization': authorization,
        'response': str(response.relative_to(root)), 'response_sha256': sha(response),
        'invocation_sha256': sha(response.parent/'invocation.json'),
        'withdrawals': withdrawals, 'source_references_unchanged': True,
        'model_calls_added': 0, 'gameplay_verified': False}
    dump(root/RECEIPT, receipt)
    dump(root/'static_existence.json', {'version': static_existence.SCHEMA,
        'result': result, 'response_sha256': sha(response),
        'model': static_existence.MODEL, 'policy': static_existence.policy(protocol)['version'],
        'normalization_sha256': sha(root/RECEIPT)})
    return verify(root, protocol)


def verify(root, protocol):
    root = Path(root).resolve()
    receipt = codex.load_plan_json(root/RECEIPT)
    artifact = codex.load_plan_json(root/'static_existence.json')
    if (receipt.get('version') != VERSION or not receipt.get('authorization')
            or artifact.get('version') != static_existence.SCHEMA
            or artifact.get('policy') != static_existence.policy(protocol)['version']
            or artifact.get('model') != static_existence.MODEL
            or artifact.get('normalization_sha256') != sha(root/RECEIPT)):
        raise ValueError('Partial static recovery identity/receipt changed')
    response = root/receipt['response']
    successful_reply(root, response)
    if (sha(response) != receipt['response_sha256']
            or sha(response.parent/'invocation.json') != receipt['invocation_sha256']
            or artifact['response_sha256'] != receipt['response_sha256']):
        raise ValueError('Preserved static response/invocation changed')
    result, withdrawals = normalize(root, protocol, codex.load_plan_json(response))
    if (not withdrawals or receipt.get('withdrawals') != withdrawals
            or artifact.get('result') != result
            or receipt.get('source_references_unchanged') is not True
            or receipt.get('model_calls_added') != 0 or receipt.get('gameplay_verified') is not False):
        raise ValueError('Partial static recovery differs from its conservative derivation')
    return result


POLICY_FILE = 'unity_partial_static_policy.json'
POLICY_VERSION = 'whitebox-unity-partial-static-policy.v1'


def authorization(root):
    path = Path(root).resolve().parents[1]/POLICY_FILE
    if not path.is_file():
        return None
    value = codex.load_plan_json(path)
    if (value.get('version') != POLICY_VERSION or value.get('withdraw_unbound_exists') is not True
            or not isinstance(value.get('authorization'), str) or not value['authorization'].strip()):
        raise ValueError('Unknown explicit partial static policy')
    return value['authorization']


def saved_rejected_reply(root):
    """Select the final attempted raw review; never fall back across later failures."""
    import re
    root = Path(root)
    calls = []
    for folder in (root/'model_calls').glob('static_existence*'):
        match = re.fullmatch(r'static_existence(?:_(\d+))?', folder.name)
        if match and folder.is_dir():
            calls.append((int(match.group(1) or '1'), folder))
    if not calls:
        raise ValueError('No preserved static review')
    _, folder = max(calls, key=lambda item: item[0])
    response = folder/'response.json'
    successful_reply(root, response)
    error = codex.load_plan_json(folder/'validation_error.json')
    if (error.get('response_sha256') != sha(response)
            or not str(error.get('exception', '')).startswith(
                'EXISTS needs implementation plus actual entry and binding evidence: ')):
        raise ValueError('No terminal missing-binding static rejection')
    return response


def eligible(root):
    root = Path(root)
    if any((root/name).exists() for name in ('static_existence.json', RECEIPT, 'sol_plan.json', 'background_record')):
        return False
    try:
        if not authorization(root):
            return False
        response = saved_rejected_reply(root)
        _, withdrawals = normalize(root, codex.load_plan_json(root/'input/pilot_rubric.json'),
                                   codex.load_plan_json(response))
        return bool(withdrawals)
    except (OSError, KeyError, TypeError, ValueError, IndexError):
        return False


def recover(root):
    root = Path(root)
    if not eligible(root):
        raise ValueError('No explicit bounded partial static recovery qualifies')
    from . import batch
    batch.verify_inputs(root)
    return accept(root, codex.load_plan_json(root/'input/pilot_rubric.json'),
                  saved_rejected_reply(root), authorization=authorization(root))
