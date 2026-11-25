"""Exact default-Sol routing continuation for an immutable failed planner claim.

This records old/current producer bytes; it never rewrites claims, responses,
validators, limits or invocation counts. No other producer drift is admitted.
"""
from pathlib import Path
import argparse
import fcntl
from . import evaluation_model_profile as models
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'mechanic-v3-planner-default-sol-producer-continuation.v1'
PRODUCER = 'mechanic_v3_planner_validation_recovery.py'
BEFORE_SHA = 'db866831051c93cfbdb236a037d5f839465510d89a8ac50bd1a8b4fcf08a06b0'
CLAIM = 'engineering/planner_validation_correction/claim.json'
RECEIPT = 'engineering/planner_response_correction/producer_continuation.json'


def _routing_only(before, current):
    if sha(before) != BEFORE_SHA:
        raise ValueError('Exact archived planner producer required')
    original = before.read_bytes()
    replacements = [
        (b'from pathlib import Path\n', b'from . import evaluation_model_profile as eval_models\nfrom pathlib import Path\n', 1),
        (b'runner.v3.MODEL', b'eval_models.model_for(root, "planner")', 2),
    ]
    for old, new, count in replacements:
        if original.count(old) != count:
            raise ValueError('Unknown planner routing transformation')
        original = original.replace(old, new)
    if original != current.read_bytes():
        raise ValueError('Planner producer change exceeds exact model routing')


def _default_sol(root):
    if models.profile_for(root) is not None or runner.v3.MODEL != models.DEFAULT:
        raise ValueError('Producer continuation requires unchanged default Sol')


def _changes(bindings):
    return {p: d for p, d in bindings.items() if sha(Path(p)) != d}


def authorize(root, before, engineering_receipt):
    root = Path(root).resolve(); before = Path(before).resolve()
    parent = root / CLAIM; claim = runner.read(parent)
    producer = Path(__file__).resolve().with_name(PRODUCER)
    bindings = claim['bindings']; drift = _changes(bindings)
    if (claim.get('task') != 'plan_v3_outcome_validation_correction_v1' or
            claim.get('maximum_correction_invocations') != 1 or
            drift != {str(producer): BEFORE_SHA}):
        raise ValueError('Earlier planner correction lineage changed beyond routing')
    _default_sol(root); _routing_only(before, producer)
    proof = Path(engineering_receipt).resolve()
    retained = {p: d for p, d in bindings.items() if p not in drift}
    for task in ('plan_v3_outcome_frame_v1', 'plan_v3_outcome_validation_correction_v1'):
        folder = root / 'model_calls' / task
        if (folder / 'accepted_response.json').exists():
            raise ValueError('Accepted planner cannot receive producer continuation')
        failure = runner.read(folder / 'validation_error.json')
        if (failure.get('phase') != 'response_plan_validation' or
                failure.get('response_sha256') != sha(folder / 'response.json')):
            raise ValueError('Planner failure lineage differs')
        if task.endswith('validation_correction_v1') and failure.get('exception') != 'invalid native probe count':
            raise ValueError('Different exhausted correction needs separate repair')
        for name in ('response.json', 'validation_error.json', 'invocation.json', 'schema.json', 'prompt.txt'):
            p = folder / name; retained[str(p)] = sha(p)
    value = dict(version=VERSION, parent=dict(path=str(parent), sha256=sha(parent)),
        original_bindings=bindings, before=str(before), before_sha256=BEFORE_SHA,
        producer=str(producer), after_sha256=sha(producer),
        classification='NON_SCORING_EXACT_DEFAULT_SOL_ROUTING_EQUIVALENCE',
        old_claim_and_attempts_preserved=True, schema_and_validators_unchanged=True,
        bindings={**retained, str(parent):sha(parent), str(before):sha(before),
            str(producer):sha(producer), str(proof):sha(proof),
            str(Path(__file__).resolve()):sha(Path(__file__)),
            str(Path(models.__file__).resolve()):sha(Path(models.__file__))})
    path = root / RECEIPT
    if path.exists():
        if runner.read(path) != value:
            raise ValueError('Immutable planner producer continuation differs')
    else:
        runner.exclusive_json(path, value)
    return verified_bindings(root, bindings)


def verified_bindings(root, bindings):
    root = Path(root).resolve(); drift = _changes(bindings)
    if not drift:
        return dict(bindings)
    producer = Path(__file__).resolve().with_name(PRODUCER)
    path = root / RECEIPT; parent = root / CLAIM
    if drift != {str(producer): BEFORE_SHA} or not path.is_file():
        raise ValueError('Earlier planner correction lineage changed: exact continuation missing')
    value = runner.read(path)
    if (value.get('version') != VERSION or value.get('original_bindings') != bindings or
            value.get('parent') != dict(path=str(parent), sha256=sha(parent)) or
            value.get('producer') != str(producer) or value.get('after_sha256') != sha(producer) or
            value.get('before_sha256') != BEFORE_SHA):
        raise ValueError('Planner producer continuation parent changed')
    _default_sol(root); _routing_only(Path(value['before']), producer)
    for p, digest in value['bindings'].items():
        if sha(Path(p)) != digest:
            raise ValueError('Planner producer continuation binding changed: ' + p)
    return {**{p:d for p,d in bindings.items() if p not in drift},
        **value['bindings'], str(path):sha(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--engineering-receipt', type=Path, required=True)
    args = parser.parse_args()
    root=args.root.resolve(); workspace=root.parent.parent
    if root.parent.name != 'runs':
        raise ValueError('Formal workspace run required')
    lock=workspace/'locks'/('outcome_frame_v1_'+root.name+'.lock')
    lock.parent.mkdir(exist_ok=True)
    with lock.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        verified_bindings_value = authorize(root, args.before, args.engineering_receipt)
    print(dict(receipt=str(root / RECEIPT), bindings=len(verified_bindings_value)))


if __name__ == '__main__':
    main()
