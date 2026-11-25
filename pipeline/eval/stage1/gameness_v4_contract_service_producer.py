"""Exact immutable producer continuation for the complete inline text dispatcher.

Every changed producer must have exact archived bytes. All data and unrelated
code bindings remain strict. Receipts/claims and accepted replies are immutable.
"""
import hashlib
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'gameness-v4-contract-service-producer-continuation.v1'
ALLOWED = frozenset({'batch.py', 'gameness_v4_inline_text_recovery.py', 'gameness_v4_preflight_recovery.py', 'gameness_v3_runtime.py'})


def _directory(parent):
    return parent.parent/'contract_service_producer_continuations'/sha(parent)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def authorize(parent, bindings, before_directory, engineering_receipt):
    parent=Path(parent).resolve();before=Path(before_directory).resolve()
    code=Path(__file__).parent.resolve();changes={};preserved={}
    for name,digest in bindings.items():
        p=Path(name).resolve()
        if sha(p)==digest:
            preserved[str(p)]=digest
        else:
            archive=before/p.name
            if p.parent!=code or p.name not in ALLOWED or not archive.is_file() or sha(archive)!=digest:
                raise ValueError('Unrelated binding drift cannot continue: '+name)
            changes[str(p)]=dict(before_sha256=digest,archive=str(archive),after_sha256=sha(p))
    if not changes:raise ValueError('No exact producer drift to continue')
    proof=Path(engineering_receipt).resolve()
    value=dict(version=VERSION,parent=dict(path=str(parent),sha256=sha(parent)),
        original_bindings=bindings,changes=changes,
        classification='NON_SCORING_PUBLICATION_COMPATIBILITY',model_recalled=False,
        source_frames_contract_checks_and_scores_unchanged=True,
        bindings={**preserved,str(parent):sha(parent),str(proof):sha(proof),
            str(Path(__file__).resolve()):sha(Path(__file__)),
            **{v['archive']:v['before_sha256'] for v in changes.values()},
            **{p:v['after_sha256'] for p,v in changes.items()}})
    path=_directory(parent)/(_digest(value)+'.json')
    if not path.exists():runner.exclusive_json(path,value)
    elif runner.read(path)!=value:raise ValueError('Immutable producer continuation differs')
    return dict(path=str(path),sha256=sha(path))


def verified_bindings(parent, bindings):
    parent=Path(parent).resolve()
    drift={name:digest for name,digest in bindings.items() if sha(Path(name))!=digest}
    if not drift:return dict(bindings)
    code=Path(__file__).parent.resolve()
    if any(Path(p).resolve().parent!=code or Path(p).name not in ALLOWED for p in drift):
        raise ValueError('Unrelated retained data/code binding changed')
    valid=[]
    for path in _directory(parent).glob('*.json'):
        value=runner.read(path)
        if path.stem!=_digest(value):raise ValueError('Producer continuation receipt changed')
        if (value.get('version')!=VERSION or value.get('parent')!=dict(path=str(parent),sha256=sha(parent))
                or value.get('original_bindings')!=bindings):
            raise ValueError('Producer continuation parent changed')
        changes=value['changes']
        if set(changes)!={str(Path(p).resolve()) for p in drift}:continue
        if any(changes[str(Path(p).resolve())]['before_sha256']!=digest for p,digest in drift.items()):
            raise ValueError('Producer continuation original SHA changed')
        if any(sha(Path(p))!=v['after_sha256'] for p,v in changes.items()):continue
        for p,digest in value['bindings'].items():
            if sha(Path(p))!=digest:raise ValueError('Producer continuation binding changed: '+p)
        for p,v in changes.items():
            if (Path(p).resolve().parent!=code or Path(p).name not in ALLOWED
                    or sha(Path(v['archive']))!=v['before_sha256']
                    or value['bindings'].get(v['archive'])!=v['before_sha256']
                    or value['bindings'].get(p)!=v['after_sha256']):
                raise ValueError('Producer continuation lacks exact before/after proof')
        valid.append({**{p:d for p,d in bindings.items() if p not in drift},
            **value['bindings'],str(path):sha(path)})
    if len(valid)!=1:raise ValueError('Missing or ambiguous exact producer continuation')
    return valid[0]
