"""Recognize an exact immutable author-source copy, never native instrumentation."""
from pathlib import Path
from . import batch
from .protocol import sha


def qualified(root,item):
    relative=item['path']
    if relative.startswith('input/project/'):
        return True
    prefix='original_author_source/'
    if not relative.startswith(prefix):return False
    receipt=Path(root)/'unity_m_original_author_sources.json'
    if not receipt.is_file():return False
    data=batch.read(receipt);name=relative[len(prefix):]
    if not name or Path(name).is_absolute() or '..' in Path(name).parts:
        raise ValueError('Original author path escapes its source root')
    source=Path(data['recorded'])/'input/project'/name
    if (item['id']!='ORIGINAL_SRC:'+name or data['original_source_hashes'].get(name)!=item['sha256']
        or sha(source)!=item['sha256'] or sha(Path(root)/relative)!=item['sha256']):
        raise ValueError('Original author source proof changed')
    return True
