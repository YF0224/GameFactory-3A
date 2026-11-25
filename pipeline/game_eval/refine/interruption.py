"""Explicit diagnosed timeout checkpoints; an attempted turn is never retried for free."""
from pathlib import Path
from .common import read, sha


def checkpoint(folder, number, config):
    folder = Path(folder)
    index = folder / 'repair_interruptions.json'
    if not index.is_file() or str(number) not in read(index):
        return None
    ref = read(index)[str(number)]
    if sha(ref['path']) != ref['sha256']:
        raise ValueError('Interruption checkpoint binding changed')
    value = read(ref['path'])
    root = folder / 'repair_rounds' / f'round_{number:03d}'
    if value['round'] != number or value['root'] != str(root):
        raise ValueError('Interruption checkpoint escaped its original round')
    for item in value['sources']:
        if sha(item['path']) != item['sha256']:
            raise ValueError('Original interrupted attempt changed')
    marker = read(folder / 'stages' / f'repair_round_{number:03d}.json')
    report = read(root / 'agent_report.json')
    identity = read(root / 'agent_identity.json')
    original = read(folder / 'agent_identity.json')
    if (marker['status'] != 'ERROR' or report['status'] != 'timeout' or
            identity['session_ids'] != original['session_ids'] or
            identity['model'] != config['agent']['model'] or identity['provider_completed'] or
            value['session_ids'] != original['session_ids'] or
            value['reason'] != 'PROVIDER_TIMEOUT_PRESERVED_PARTIAL_EDITS' or
            sha(value['manifest']) != value['manifest_sha256'] or
            value['counts_toward_limit'] is not True or not value['next_action']):
        raise ValueError('Interruption is not a diagnosed same-session timeout')
    return value


def preserve_timeout(folder, number, previous, config):
    """Freeze partial source once after a real timeout; no provider call or marker overwrite."""
    from .common import dump
    from .session import inventory
    folder = Path(folder)
    root = folder / 'repair_rounds' / f'round_{number:03d}'
    report = root / 'agent_report.json'
    if not report.is_file() or read(report).get('status') != 'timeout':
        return None
    identity_path = root / 'agent_identity.json'
    identity = read(identity_path)
    initial = read(folder / 'agent_identity.json')
    if (identity['session_ids'] != initial['session_ids'] or len(identity['session_ids']) != 1 or
            identity['model'] != config['agent']['model'] or identity['provider_completed']):
        return None
    original = read(folder / 'original_project.json')
    if inventory(original['root']) != original['files']:
        raise ValueError('Author source changed before timeout checkpoint')
    from .batch import code_identity
    manifest = root / 'interrupted_project.json'
    receipt = root / 'interruption_checkpoint.json'
    if manifest.exists() or receipt.exists():
        raise ValueError('Existing timeout checkpoint cannot be replaced')
    sources = [folder / 'stages' / f'repair_round_{number:03d}.json', report,
               identity_path, root / 'binding.json', root / 'agent_session/raw/zcode.jsonl']
    if read(sources[0])['status'] != 'ERROR':
        raise ValueError('Timeout checkpoint requires preserved failed stage')
    dump(manifest, {'files': inventory(folder / 'workspace/project')})
    value = {'round': number, 'root': str(root), 'session_ids': identity['session_ids'],
        'reason': 'PROVIDER_TIMEOUT_PRESERVED_PARTIAL_EDITS', 'counts_toward_limit': True,
        'next_action': 'Continue bounded source edits in the exact original session; request per-task completion status.',
        'previous_manifest': str(previous), 'previous_manifest_sha256': sha(previous),
        'manifest': str(manifest), 'manifest_sha256': sha(manifest), 'runtime_verdict': None,
        'implementation': code_identity(),
        'sources': [{'path': str(p), 'sha256': sha(p)} for p in sources]}
    dump(receipt, value)
    index_path = folder / 'repair_interruptions.json'
    index = read(index_path) if index_path.is_file() else {}
    if str(number) in index:
        raise ValueError('Cannot replace interruption identity')
    index[str(number)] = {'path': str(receipt), 'sha256': sha(receipt)}
    dump(index_path, index)
    return checkpoint(folder, number, config)
