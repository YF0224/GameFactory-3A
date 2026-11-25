"""Immutable, source-bound evaluator roles for explicitly authorized reassessments.

Ordinary workspaces keep Sol. A profile cannot change rubric/weights, replace
source, reopen an old claim, or silently reuse a different model's accepted call.
"""
from pathlib import Path
import json
from .protocol import sha

VERSION = 'source-bound-evaluation-model-profile.v1'
FILE = 'evaluation_model_profile.json'
LOCK = 'evaluation_model_profile.lock.json'
DEFAULT = 'gpt-6.1-sol'
ASTRA = 'gpt-6-astra'


def profile_for(root):
    root = Path(root).resolve()
    for workspace in (root, *root.parents):
        path = workspace / FILE
        lock = workspace / LOCK
        if not path.exists() and not lock.exists():
            continue
        if not path.is_file() or not lock.is_file():
            raise ValueError('Incomplete evaluator model profile')
        value = json.loads(path.read_text())
        frozen = json.loads(lock.read_text())
        if value.get('version') != VERSION or frozen.get('profile_sha256') != sha(path):
            raise ValueError('Evaluator model profile changed')
        if value.get('roles') != {'static': DEFAULT, 'planner': ASTRA, 'judge': ASTRA}:
            raise ValueError('Unauthorized evaluator role mapping')
        if value.get('purpose') != 'user_authorized_opus_below60_reassessment':
            raise ValueError('Explicit independent reassessment authorization required')
        for name, digest in value['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Reassessment parent binding changed: ' + name)
        identity = next((part for part in reversed(root.parts) if part in value['baselines']), None)
        if identity is None and root != workspace:
            raise ValueError('Model profile cannot route an identity outside its frozen selection')
        for ident, columns in value['baselines'].items():
            if not ident.startswith('Opus__') or not columns:
                raise ValueError('Astra reassessment requires original Opus identities')
            for col, baseline in columns.items():
                if col not in {'Mechanic', 'Gameness'} or not 0 <= baseline['score'] < 60:
                    raise ValueError('Reassessment baseline must be a complete score below60')
                p = Path(baseline['publication'])
                if sha(p) != baseline['publication_sha256']:
                    raise ValueError('Reassessment baseline publication changed')
        return workspace, value, identity
    return None


def model_for(root, role):
    if role not in {'static', 'planner', 'judge'}:
        raise ValueError('Unknown evaluator role')
    found = profile_for(root)
    return found[1]['roles'][role] if found else DEFAULT


def binding(root):
    found = profile_for(root)
    if found is None:
        return {}
    workspace, value, identity = found
    return {str(workspace / name): sha(workspace / name) for name in (FILE, LOCK)}


def publication_profile(root, column):
    found = profile_for(root)
    if found is None:
        return None
    workspace, value, identity = found
    if identity is None or column not in value['baselines'][identity]:
        raise ValueError('Column is outside the authorized below60 reassessment')
    return dict(version=VERSION, profile=str(workspace / FILE), profile_sha256=sha(workspace / FILE),
                roles=value['roles'], baseline=value['baselines'][identity][column],
                independent_reassessment=True, old_publication_preserved=True)


def verify_call(root, name, role):
    """Reject retained calls from a different model before accepting their output."""
    invocation = Path(root) / 'model_calls' / name / 'invocation.json'
    if not invocation.exists():
        return
    command = json.loads(invocation.read_text()).get('command', [])
    if '--model' not in command or command[command.index('--model') + 1] != model_for(root, role):
        raise ValueError('Retained evaluator call does not match its frozen model role')
