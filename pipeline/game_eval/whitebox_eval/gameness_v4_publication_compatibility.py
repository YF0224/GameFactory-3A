"""Exact, read-only continuation of already published v4 result bindings.

Only the historical-view resolver and publication dispatcher may change here.
Every old producer byte and the unchanged publication remain bound. This cannot
qualify a new recording, source review, model call, or scoring rule.
"""
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-saved-publication-compatibility.v1'
ALLOWED = frozenset({'qualified_history.py', 'gameness_v3_runtime.py'})


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _directory(parent):
    return parent.parent/'saved_publication_compatibility'/sha(parent)


def authorize(parent, before_directory, engineering_receipt):
    parent = Path(parent).resolve()
    value = runner.read(parent)
    if value.get('scoring_protocol') != 'whitebox-gameness10-50-100.v4':
        raise ValueError('Only a retained v4 publication may continue')
    bindings = value['bindings']
    code = Path(__file__).resolve().parent
    before = Path(before_directory).resolve()
    changed = {}
    for name, digest in bindings.items():
        path = Path(name).resolve()
        if sha(path) == digest:
            continue
        archive = before/path.name
        if path.parent != code or path.name not in ALLOWED or not archive.is_file() or sha(archive) != digest:
            raise ValueError('Unrelated publication binding drift: '+name)
        changed[name] = dict(before_sha256=digest, archive=str(archive), after_sha256=sha(path))
    if not changed:
        raise ValueError('No exact publication producer drift')
    proof = Path(engineering_receipt).resolve()
    result = dict(version=VERSION, parent=dict(path=str(parent), sha256=sha(parent)),
        original_bindings=bindings, changes=changed,
        engineering_receipt=dict(path=str(proof), sha256=sha(proof)),
        classification='NON_SCORING_SAVED_PUBLICATION_COMPATIBILITY',
        model_recalled=False, native_recorded=False,
        source_frames_contract_checks_and_scores_unchanged=True,
        bindings={**{p:d for p,d in bindings.items() if p not in changed},
            str(parent):sha(parent), str(proof):sha(proof),
            str(Path(__file__).resolve()):sha(Path(__file__)),
            str(code/'gameness_v3_runtime.py'):sha(code/'gameness_v3_runtime.py'),
            **{v['archive']:v['before_sha256'] for v in changed.values()},
            **{p:v['after_sha256'] for p,v in changed.items()}})
    path = _directory(parent)/(_digest(result)+'.json')
    if not path.exists():
        runner.exclusive_json(path, result)
    elif runner.read(path) != result:
        raise ValueError('Immutable publication compatibility differs')
    return dict(path=str(path), sha256=sha(path))


def verify(parent, bindings):
    parent = Path(parent).resolve()
    if runner.read(parent).get('bindings') != bindings:
        raise ValueError('Publication compatibility parent differs')
    paths = list(_directory(parent).glob('*.json'))
    if not paths:
        return False
    code = Path(__file__).resolve().parent
    drift = {p:d for p,d in bindings.items() if sha(Path(p)) != d}
    if any(Path(p).resolve().parent != code or Path(p).name not in ALLOWED for p in drift):
        raise ValueError('Unrelated saved publication binding changed')
    valid = []
    for path in paths:
        value = runner.read(path)
        if (path.stem != _digest(value) or value.get('version') != VERSION
                or value.get('parent') != dict(path=str(parent), sha256=sha(parent))
                or value.get('original_bindings') != bindings
                or value.get('classification') != 'NON_SCORING_SAVED_PUBLICATION_COMPATIBILITY'
                or value.get('model_recalled') is not False or value.get('native_recorded') is not False
                or value.get('source_frames_contract_checks_and_scores_unchanged') is not True):
            raise ValueError('Saved publication compatibility changed')
        changes = value['changes']
        if set(changes) != set(drift):
            continue
        if any(v['before_sha256'] != bindings[p] or sha(Path(p)) != v['after_sha256']
                for p,v in changes.items()):
            continue
        expected = {p:d for p,d in bindings.items() if p not in drift}
        expected.update({str(parent):sha(parent), str(Path(__file__).resolve()):sha(Path(__file__)),
            str(code/'gameness_v3_runtime.py'):sha(code/'gameness_v3_runtime.py')})
        proof = value['engineering_receipt']
        expected[proof['path']] = proof['sha256']
        for p,v in changes.items():
            if sha(Path(v['archive'])) != v['before_sha256']:
                raise ValueError('Exact historical publication producer changed')
            expected[v['archive']] = v['before_sha256']
            expected[p] = v['after_sha256']
        if any(value['bindings'].get(p) != d for p,d in expected.items()):
            raise ValueError('Publication compatibility omits required binding')
        for p,d in value['bindings'].items():
            if sha(Path(p)) != d:
                raise ValueError('Publication compatibility binding changed: '+p)
        valid.append(path)
    if len(valid) != 1:
        raise ValueError('Missing or ambiguous saved publication compatibility')
    return True


def native_source_bindings(root, publication):
    """Check the unchanged author-entry claim through its exact published binding.

    The historical source proof can bind the old resolver as well. Its lineage,
    every original source byte and the exact archived resolver remain mandatory.
    This route is restricted to an already published, explicitly continued result.
    """
    from .gameness_v4_author_entry_source import PROOF, VERSION as SOURCE_VERSION
    root, publication = Path(root).resolve(), Path(publication).resolve()
    value = runner.read(publication)
    if not verify(publication, value['bindings']):
        raise ValueError('Native source needs exact saved publication compatibility')
    if Path(value['score_file']).resolve().parent != root:
        raise ValueError('Saved native source is outside the published result')
    path = root/PROOF
    if not path.exists():
        return {}
    proof = runner.read(path)
    claim_path = Path(proof['claim_path'])
    if proof.get('version') != SOURCE_VERSION or sha(claim_path) != proof['claim_sha256']:
        raise ValueError('Saved native source proof changed')
    claim = runner.read(claim_path)
    if claim['recovery_root'] != str(root) or claim['source_bindings'] != proof['source_bindings']:
        raise ValueError('Saved native source lineage changed')
    bindings = {**proof['source_bindings'], str(claim_path):proof['claim_sha256'], str(path):sha(path)}
    if any(value['bindings'].get(p) != d for p,d in bindings.items()):
        raise ValueError('Saved native source proof lacks original publication binding')
    return bindings
