"""Reuse a qualified source verdict without impersonating its original attempt."""
from pathlib import Path
import shutil
from . import batch, static_existence as static, cli_runtime_recovery as recovery
from .protocol import checked_path, dump, sha

VERSION = 'whitebox-cli-static-reuse.v1'
RECEIPT = 'cli_static_reuse.json'
BINDINGS = ('input_manifest.json', 'input/pilot_rubric.json',
            'static_existence.json', 'cli_runtime_recovery/static_existence.json')


def _files(source):
    paths = [source/'static_existence.json', source/'cli_runtime_recovery/static_existence.json']
    paths += [p for p in sorted((source/'model_calls').glob('static_existence*/*')) if p.is_file()]
    return {str(p.relative_to(source)): sha(p) for p in paths}


def _origin(source):
    source=Path(source).resolve()
    if (source/RECEIPT).is_file():
        verify(source,batch.read(source/'input/pilot_rubric.json'))
        source=Path(batch.read(source/RECEIPT)['source_attempt']).resolve()
    if not (source/'static_existence.json').is_file() or (source/RECEIPT).exists():
        raise ValueError('Direct qualified static origin required')
    result=static.load(source,batch.read(source/'input/pilot_rubric.json'))
    recovery.verify_static(source,batch.read(source/'input/pilot_rubric.json'))
    return source,result


def copy_judgment(source,target):
    source,result=_origin(source);target=Path(target).resolve()
    if source==target or source.parent!=target.parent:
        raise ValueError('Static handoff requires distinct attempts in the same batch')
    batch.verify_inputs(target)
    if result['identity']!=static.identity(target,batch.read(target/'input/pilot_rubric.json')):
        raise ValueError('Static handoff source/contract identity changed')
    if (target/RECEIPT).exists() or (target/'static_existence.json').exists():
        raise ValueError('Existing static handoff protected')
    copied = _files(source)
    # Fail before copying any bytes if an existing response would be overwritten.
    if any((target/rel).exists() for rel in copied):
        raise ValueError('Existing model call protected during static handoff')
    for rel in copied:
        destination=target/rel;destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/rel,destination)
    dump(target/RECEIPT,{'version':VERSION,'source_attempt':str(source),'target_attempt':str(target),
        'source_bindings':{rel:sha(source/rel) for rel in BINDINGS},
        'copied_file_sha256':copied,'model_calls_added':0,'identity_rewritten':False,
        'verdict_rewritten':False})
    return verify(target,batch.read(target/'input/pilot_rubric.json'))


def verify(root,protocol):
    root=Path(root).resolve();value=batch.read(root/RECEIPT)
    source=Path(value['source_attempt']).resolve()
    if (value.get('version')!=VERSION or value.get('target_attempt')!=str(root)
            or source==root or source.parent!=root.parent or (source/RECEIPT).exists()
            or value.get('model_calls_added')!=0 or value.get('identity_rewritten') is not False
            or value.get('verdict_rewritten') is not False):
        raise ValueError('Invalid static handoff identity')
    if set(value['source_bindings']) != set(BINDINGS):
        raise ValueError('Incomplete static handoff origin bindings')
    for rel,digest in value['source_bindings'].items():
        if sha(checked_path(source,rel))!=digest:raise ValueError('Static handoff origin changed: '+rel)
    batch.verify_inputs(source);batch.verify_inputs(root)
    result=recovery.verify_static(source,batch.read(source/'input/pilot_rubric.json'))
    if result['identity']!=static.identity(root,protocol):
        raise ValueError('Static handoff frozen source/contract mismatch')
    if value['copied_file_sha256'] != _files(source):
        raise ValueError('Static handoff lacks complete original request/response inventory')
    for rel,digest in value['copied_file_sha256'].items():
        if sha(checked_path(source,rel))!=digest or sha(checked_path(root,rel))!=digest:
            raise ValueError('Static handoff accepted request/response changed: '+rel)
    if batch.read(root/'static_existence.json')!=batch.read(source/'static_existence.json'):
        raise ValueError('Static handoff verdict changed')
    return static.validate_result(root,protocol,result)
