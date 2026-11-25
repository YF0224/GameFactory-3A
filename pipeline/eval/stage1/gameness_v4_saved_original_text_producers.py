"""Offline exact-producer continuation for one immutable saved complete-capacity judgment.

This route verifies existing source, pixels, requests, responses and publication.
It cannot authorize a model invocation, replace a verdict, or accept changed data.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha

PARENTS = {
 '26248909936ace19d99fef486638d5704832bb5a5f03459aa56c77ccffd030db':'GLM__G011_cloud_mail_runner',
 '220f0a50bcf17643058bb0b4d9ed8a6707eaa9bfc96fcd2e0a4b534e54f1cf84':'Sol__G011_cloud_mail_runner',
 '8cde6f024a74a3a2566c59830531de49454ed0779d3bb9ed7b9f6686c1d38da4':'Sol__G012_gravity_mine',
 '93c2e5172ad752cf49421a668abada3badca513bd1edc095717e46db9442906d':'Sol__G017_lighthouse_prism',
}
RECEIPT = 'saved_original_text_exact_producers.json'
VERSION = 'gameness-saved-original-text-exact-producers.v1'

def matches(parent):
 parent=Path(parent)
 return parent.is_file() and parent.name=='gameness_persistent_original_text.json' and sha(parent) in PARENTS


def verified_bindings(parent, bindings):
    parent = Path(parent).resolve()
    if not matches(parent) or runner.read(parent)['bindings'] != bindings:
        raise ValueError('Exact saved inline authorization required')
    root = parent.parent.parent
    if root.name != PARENTS[sha(parent)]:
        raise ValueError('Saved inline identity differs')
    path = parent.parent/RECEIPT
    value = runner.read(path)
    if (value.get('version') != VERSION or value.get('parent') != dict(path=str(parent), sha256=sha(parent))
            or value.get('classification') != 'OFFLINE_SAVED_RESULT_EXACT_PRODUCERS'
            or value.get('maximum_new_model_calls') != 0 or value.get('maximum_new_native_calls') != 0
            or value.get('original_bindings') != bindings):
        raise ValueError('Saved producer continuation changed')
    code = Path(__file__).resolve().parent
    producers = value['exact_producers']
    expected = {name:digest for name,digest in bindings.items() if Path(name).resolve().parent == code}
    if set(producers) != set(expected):
        raise ValueError('Saved producer list must include every original producer')
    preserved = {name:digest for name,digest in bindings.items() if name not in expected}
    for name,digest in expected.items():
        old = producers[name]
        if old['sha256'] != digest or sha(Path(old['archive'])) != digest:
            raise ValueError('Exact original producer archive changed')
        preserved[old['archive']] = digest
    # Protect accepted replies, failures, all original requests and saved score.
    saved = value['saved_result_bindings']
    required = [Path(runner.read(Path(value['publication']['path']))['score_file'])]
    required += [p for folder in ('model_calls','judgments','requests','failures') for p in (root/folder).rglob('*') if p.is_file()]
    if any(str(p.resolve()) not in saved for p in required):
        raise ValueError('Saved producer proof omits an original request or verdict')
    publication = Path(value['publication']['path'])
    if publication.name != PARENTS[sha(parent)]+'.json' or saved.get(str(publication)) != value['publication']['sha256']:
        raise ValueError('Saved publication binding differs')
    if Path(runner.read(publication)['score_file']).resolve().parent != root:
        raise ValueError('Saved publication belongs to another root')
    preserved.update(saved)
    regression = value['regression']
    preserved[regression['path']] = regression['sha256']
    if runner.read(Path(regression['path'])).get('exit_code') != 0:
        raise ValueError('Saved producer regression not passed')
    preserved.update({str(parent):sha(parent), str(Path(__file__).resolve()):value['verifier_sha256']})
    for name,digest in preserved.items():
        if sha(Path(name)) != digest:
            raise ValueError('Immutable saved source/result/archive changed: '+name)
    return {**preserved, str(path):sha(path)}
