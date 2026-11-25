"""Persist never-invoked full-context shards while a prior invocation needs repair.

This mode cannot retry a failed call, aggregate a partial score, or publish.
All full-capture, source, schema, citation and request gates remain in batch.judge.
"""
from pathlib import Path
import time
from .protocol import dump, sha

VERSION = 'whitebox-full-capture-judge-checkpoint.v1'


def claim(root, tasks, names, capture_validation):
    root = Path(root)
    known = [name for name, _, _ in tasks]
    if (capture_validation.get('valid') is not True or not names
            or len(set(names)) != len(names) or set(names) - set(known)
            or (root/'scores.json').exists()):
        raise ValueError('Invalid full-capture checkpoint selection')
    for name in names:
        if not isinstance(name, str) or '/' in name or '\\' in name:
            raise ValueError('Invalid checkpoint task identity')
        if (root/'judgments'/(name+'.json')).exists() or (root/'model_calls'/name).exists():
            raise ValueError('Checkpoint only admits never-invoked shards: '+name)
        if any((root/'model_calls').glob(name+'_*')):
            raise ValueError('Checkpoint cannot hide invocation history: '+name)
    saved = {str(p.relative_to(root)): sha(p) for p in (root/'judgments').glob('*.json')}
    calls = {str(p.relative_to(root)): sha(p) for p in (root/'model_calls').rglob('*') if p.is_file()}
    binding = {n: sha(root/n) for n in ('input_manifest.json','input/pilot_rubric.json','evidence_manifest.json')}
    out = root/'judge_checkpoint_claims'/str(time.time_ns())
    out.mkdir(parents=True, exist_ok=False)
    record = {'version':VERSION, 'at':time.time(), 'requested':list(names),
              'full_task_order':known, 'source_bindings':binding,
              'saved_judgments':saved, 'original_call_files':calls,
              'retry_permitted':False, 'score_created':False,
              'complete_eight_columns':False, 'publication_eligible':False}
    dump(out/'claim.json',record)
    return out


def finish(root, directory, tasks, rows, capture_validation):
    from .batch import read, status
    root, directory = Path(root), Path(directory)
    record = read(directory/'claim.json')
    if capture_validation.get('valid') is not True:
        raise ValueError('Checkpoint full capture ceased to be valid')
    for name, digest in {**record['source_bindings'], **record['saved_judgments'], **record['original_call_files']}.items():
        if sha(root/name) != digest:
            raise ValueError('Checkpoint changed prior bound material: '+name)
    result = {'version':VERSION, 'completed_shards':[task[0] for task in tasks],
              'criterion_ids':[row['id'] for row in rows], 'claim_sha256':sha(directory/'claim.json'),
              'full_capture_validation':capture_validation, 'complete_eight_columns':False,
              'score_created':False, 'publication_eligible':False}
    dump(directory/'receipt.json',result)
    status(root,'CHECKPOINT_JUDGMENTS_SAVED',score=None,complete_eight_columns=False,publication_eligible=False)
    return result
