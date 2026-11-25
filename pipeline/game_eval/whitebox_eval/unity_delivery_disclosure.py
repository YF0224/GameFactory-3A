"""Trace explicit author-repair authorization in result metadata, never scoring."""
from pathlib import Path
from .protocol import sha

SUBJECT = 'original_delivery_with_explicitly_authorized_author_repairs'


def describe(entry):
    """Resolve the frozen source pointer without changing any judge evidence."""
    from .batch import read
    binding = entry.get('authorized_authored_repair')
    if binding is None:
        return None
    if not isinstance(binding, dict) or binding.get('evaluation_subject') != SUBJECT:
        raise ValueError('Unknown authorized repaired delivery subject')
    source = Path(binding['path'])
    if not source.is_file() or sha(source) != binding.get('sha256'):
        raise ValueError('Authorized author repair provenance SHA changed')
    value = read(source)
    if (value.get('evaluation_subject') != SUBJECT
            or value.get('original_project') != binding.get('original_project')
            or not value.get('repaired_source_project')):
        raise ValueError('Authorized author repair provenance does not bind delivery')
    return {'evaluation_subject': SUBJECT, 'provenance': str(source),
            'provenance_sha256': binding['sha256'],
            'original_project': value['original_project'],
            'repaired_source_project': value['repaired_source_project']}
