"""Reuse official native scene admission and isolated input migration for refine."""
from pathlib import Path
import re
from types import SimpleNamespace
from .common import dump, read, sha


def delivery_format(project, scenes):
    """Check asset metadata too: a Unity scene may reference Tuanjie scripts."""
    from ..whitebox_eval.unity_editor_selection import delivery_format as inspect
    project = Path(project)
    result = inspect(project, scenes)
    for path in sorted((project / 'Assets').rglob('*.meta')):
        guid = re.search(r'(?m)^guid:\s*(\S+)', path.read_text(errors='replace'))
        if (guid and re.fullmatch(r'[A-Za-z0-9+/]{40,}={0,2}', guid[1])
                and not re.fullmatch(r'[a-fA-F0-9]{32}', guid[1])):
            result['family'] = 'tuanjie'
            relative = str(path.relative_to(project))
            if not any(r['path'] == relative for r in result['evidence']):
                result['evidence'].append({'path': relative, 'sha256': sha(path),
                    'reason': 'Encoded Tuanjie asset GUID; ordinary Unity ignores the corresponding asset'})
    return result


def select_acceptance(unity, format_record):
    from ..whitebox_eval.unity_editor_selection import editor_family
    paths = [unity['editor_acceptance'], *unity.get('editor_acceptances', [])]
    for path in dict.fromkeys(paths):
        record = read(path)
        if editor_family(record['editor'], record.get('editor_version', '')) == format_record['family']:
            return Path(path).resolve(), record
    raise ValueError('No accepted Editor matches delivered serialization family: ' + format_record['family'])


def open_project(folder, game, config):
    from ..whitebox_eval import unity_admission, unity_safety, batch
    from ..whitebox_eval.unity_editor_selection import NativeAdmissionError
    from engine_adapters.unity3d.playtest import native_acceptance
    folder = Path(folder)
    unity = config['unity']
    adapter = Path(unity['adapter_root']).resolve()
    if adapter != Path(__file__).resolve().parents[3]:
        raise ValueError('Admission must use this delivered framework adapter root')
    project = folder / 'input/project'
    scenes = sorted(str(p.relative_to(project)) for p in project.glob('Assets/**/*.unity'))
    preferred = game['project'].get('launch_entry')
    if preferred:
        source = Path(game['project']['project_root'])
        entry = Path(preferred)
        relative = str(entry.relative_to(source)) if entry.is_absolute() and entry.is_relative_to(source) else str(entry)
        if relative in scenes:
            scenes.remove(relative)
            scenes.insert(0, relative)
    if not scenes:
        raise ValueError('No existing delivered scene; no scene may be synthesized')
    format_record = delivery_format(project, scenes)
    acceptance, accepted = select_acceptance(unity, format_record)
    editor = Path(accepted['editor']).resolve()
    native_acceptance.verify(acceptance, adapter, editor)
    candidate = {'id': game['game_id'], 'selected_project': str(project), 'scenes': scenes,
        'selected_editor': str(editor), 'delivery_format': format_record,
        'native_editor_acceptance': {'path': str(acceptance), 'sha256': sha(acceptance),
                                    'editor': str(editor)}}
    runner = SimpleNamespace(batch=batch, sha=sha, dump=dump, MIGRATION=Path(unity['control_root']),
        ROOT=adapter, open_timeout_seconds=unity.get('admission_timeout_seconds', 300),
        input_system_package_root=unity.get('input_system_package_root'),
        locks_clear=lambda: unity_safety.locks_clear(unity, check_external=True))
    try:
        opened = unity_admission.prepare_source(candidate, {}, runner, folder / 'admission')
    except NativeAdmissionError as exc:
        if exc.failure_class != 'PRODUCT':
            raise
        receipts = list((folder / 'admission/native_admission' / game['game_id']).glob('*/result.json'))
        if len(receipts) != 1:
            raise ValueError('Product admission failure lacks one unambiguous native receipt') from exc
        receipt = receipts[0]
        record = read(receipt)
        if (record['source_unchanged'].get('ok') is not True
                or not all(record['cleanup'].get(k) is True for k in unity_safety.CLEANUP_KEYS)):
            raise unity_safety.SafetyStop('Product failure native cleanup/source integrity uncertain') from exc
        unity_safety.locks_clear(unity, check_external=True)
        return {'status': 'PRODUCT_FAILURE', 'failure_class': 'PRODUCT', 'receipt': str(receipt),
                'receipt_sha256': sha(receipt), 'editor_log': str(receipt.parent / 'editor.log'),
                'editor_log_sha256': sha(receipt.parent / 'editor.log'),
                'source_snapshot_sha256': sha(receipt.parent / 'source_snapshot.json')}
    receipt = Path(opened['native_open_receipt'])
    return {'status': 'OPENED', 'project': opened['selected_project'], 'scene': opened['scenes'][0],
            'editor_acceptance': str(acceptance), 'editor': str(editor),
            'receipt': str(receipt), 'receipt_sha256': sha(receipt)}
