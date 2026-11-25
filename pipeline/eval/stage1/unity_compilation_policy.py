"""User-authorized acceptance of regenerated Unity IDE compilation metadata.

The recorded and frozen files stay intact. Gameplay code, asmdefs, scenes and
runtime settings are outside this allowance.
"""
import json
from pathlib import Path

from .protocol import sha

VERSION = 'whitebox-unity-generated-compilation-policy.v1'
NAME = 'unity_compilation_policy.json'


def generated_path(relative):
    path = Path(relative)
    return (len(path.parts) == 1 and not path.is_absolute()
            and path.name not in {'.', '..'} and path.suffix in {'.csproj', '.sln', '.slnx'})


def _proof(recorded, relative, observed_folder):
    if not generated_path(relative):
        return None
    recorded = Path(recorded).resolve()
    policy_path = recorded.parents[1]/NAME
    if not policy_path.is_file():
        return None
    policy = json.loads(policy_path.read_text())
    if policy.get('version') != VERSION or policy.get('mode') != 'allow_generated_metadata':
        raise ValueError('Invalid Unity compilation metadata policy')
    before = recorded/'input/project'/relative
    after = recorded/observed_folder/relative
    if (not before.is_file() or not after.is_file() or before.is_symlink()
            or after.is_symlink()):
        return None
    return {'kind': 'user_authorized_generated_compilation_metadata', 'path': relative,
        'before_sha256': sha(before), 'after_sha256': sha(after),
        'policy_path': str(policy_path), 'policy_sha256': sha(policy_path),
        'user_authorization': policy['user_authorization'],
        'original_judge_input_preserved': True, 'recorded_metadata_preserved': True,
        'scope': 'Generated root IDE solution/project files. Actual authored source and runtime changes are verified separately.'}


def proof(recorded, relative):
    return _proof(recorded, relative, 'background_record/project')


def runtime_proof(attempt, relative):
    """Apply the same explicit root-only allowance to canonical runtime copies."""
    return _proof(attempt, relative, 'runtime/project')
