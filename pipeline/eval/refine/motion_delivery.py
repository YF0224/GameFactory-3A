"""Provider-independent delivery of frozen source motions; no rigging or evaluation."""
from __future__ import annotations

from pathlib import Path
import re
import shutil

from .common import dump, read, resolve, sha


def key(item):
    return item['game_id'], item['task_id'], item['import_id']


def indexed(items):
    result = {key(item): item for item in items}
    if len(result) != len(items):
        raise ValueError('Duplicate frozen motion identity')
    for identity in result:
        if any(not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', part) for part in identity):
            raise ValueError('Unsafe motion identity')
    return result


def reference(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha(path)}


def checked(path, expected):
    path = Path(path).resolve()
    if sha(path) != expected:
        raise ValueError('Frozen motion source changed: ' + str(path))
    return path


def load_sources(config):
    """Validate the old acquisition as read-only source data, without adopting its run."""
    binding = config.get('motion_sources')
    if not binding:
        return {}
    paths = {name: checked(resolve(config['bench_root'], binding[name]['path']),
                           binding[name]['sha256']) for name in ('contract', 'decoded_contract')}
    contract, decoded_contract = (read(paths[name]) for name in ('contract', 'decoded_contract'))
    if (contract.get('schema') != 'refine.motion-handoff.v1' or
            decoded_contract.get('schema') != 'refine.motion-decoded-contract.v1' or
            decoded_contract['source_contract_sha256'] != sha(paths['contract'])):
        raise ValueError('Invalid motion source contract')
    origin = Path(contract['acquisition_root']).resolve()
    inventory_path = checked(Path(contract['output']) / 'inventory.json', contract['inventory_sha256'])
    completion_path = checked(origin / 'completion.json', contract['acquisition_completion_sha256'])
    completion = read(completion_path)
    selection_path = checked(origin / 'acquisition_selection.json', completion['selection_sha256'])
    selection = read(selection_path)
    decoded_path = checked(decoded_contract['manifest_path'], decoded_contract['manifest_sha256'])
    decoded = read(decoded_path)
    if (decoded_path != origin / 'decoded_manifest.json' or
            completion.get('schema') != 'refine.git-motion-acquisition.v1' or
            selection.get('schema') != 'refine.git-motion-selection.v1' or
            selection['inventory_sha256'] != contract['inventory_sha256'] or
            contract['git_commit'] != selection['commit'] or completion['commit'] != selection['commit'] or
            decoded.get('schema') != 'refine.motion-decoded-manifest.v1' or
            decoded['source_completion_sha256'] != sha(completion_path)):
        raise ValueError('Motion acquisition provenance changed')
    expected = {(g['game_id'], i['simple']['task_id'], i['simple']['import_id'])
                for g in read(inventory_path)['games'] for i in g['imports']
                if i['simple']['asset_kind'] == 'motion'}
    selected, acquired, missing, originals, readable = map(indexed, (
        selection['items'], completion['files'], completion['missing'], contract['items'], decoded['files']))
    if (set(selected) != expected or set(acquired) | set(missing) != expected or
            set(acquired) & set(missing) or set(originals) != set(acquired) or
            set(readable) != set(acquired) or {tuple(x) for x in contract['missing']} != set(missing) or
            any(value != len(expected) for value in (selection['selected'], completion['selected'], contract['selected'])) or
            contract['matched'] != len(acquired) or decoded_contract['files'] != len(acquired)):
        raise ValueError('Motion acquisition task coverage changed')
    provenance = [reference(p) for p in (*paths.values(), inventory_path, completion_path, selection_path, decoded_path)]
    result = {}
    for identity in sorted(expected):
        gid, task, _ = identity
        if identity in missing:
            if selected[identity].get('available') is not False:
                raise ValueError('Missing motion disagrees with frozen selection')
            result[identity] = {'status': 'MISSING_PAYLOAD', 'path': None, 'sha256': None,
                                'reason': 'SOURCE_NOT_IN_FROZEN_ACQUISITION', 'source_refs': provenance}
            continue
        original, source, decoded_item = originals[identity], acquired[identity], readable[identity]
        raw = checked(original['source_path'], original['sha256'])
        text = checked(decoded_item['path'], decoded_item['sha256'])
        if (raw != origin / 'payloads' / gid / task / 'motion.npz' or
                Path(source['path']).resolve() != raw or
                text != origin / 'decoded' / gid / task / 'motion.json' or
                Path(decoded_item['source_path']).resolve() != raw or
                decoded_item['source_sha256'] != original['sha256'] or
                decoded_item.get('typed_array_roundtrip_bytes_equal') is not True or
                any(original[k] != source[k] for k in ('sha256', 'git_path', 'git_blob_oid')) or
                any(source[k] != selected[identity][k] for k in ('git_path', 'git_blob_oid')) or
                selected[identity].get('available') is not True):
            raise ValueError('Motion source/decoded identity changed: ' + task)
        result[identity] = {'status': 'READY', **reference(raw),
                            'selection_method': 'frozen_motion_acquisition',
                            'readable_json': reference(text), 'source_refs': provenance,
                            'git_commit': contract['git_commit'], 'git_path': source['git_path'],
                            'git_blob_oid': source['git_blob_oid'], 'native_import_verified': False}
    return result


def _safe_target(root, target):
    if not target.is_relative_to(root):
        raise ValueError('Motion target escaped delivery root')
    for path in (target, *target.parents):
        if path.is_symlink():
            raise ValueError('Motion delivery target is a symlink: ' + str(path))
        if path == root:
            break


def _freeze(path, value):
    if path.exists():
        if read(path) != value:
            raise ValueError('Frozen motion delivery changed: ' + str(path))
    else:
        dump(path, value)


def prepare_delivery(game, folder, config, prepare):
    """Prepare original inputs and decoded companions before the first model call."""
    sources = load_sources(config)
    motions = [item for item in game.get('imports', []) if item['simple']['asset_kind'] == 'motion']
    for item in motions:
        identity = key(item['simple'])
        if identity not in sources or item['payload'] != sources[identity]:
            raise ValueError('Frozen game motion inputs differ from bound source: ' + str(identity))
    new_project = not (folder / 'original_project.json').exists()
    required = 2 * sum(Path(item['payload']['readable_json']['path']).stat().st_size
                       for item in motions if item['payload']['status'] == 'READY')
    if new_project:
        from .session import snapshot_required_bytes
        required += snapshot_required_bytes(Path(game['project']['project_root']))
        required += 2 * sum(Path(item['payload']['path']).stat().st_size
                            for item in game.get('imports', []) if item['payload']['status'] == 'READY')
    free = shutil.disk_usage(folder).free
    if free < required + 8 * 1024**3:
        from ..stage1.unity_safety import SafetyStop
        raise SafetyStop('Insufficient space for project/motion inputs plus 8GiB reserve')
    if new_project:
        prepare(game, folder, config)
    workspace, frozen = folder / 'workspace', folder / 'frozen'
    delivered, refs = [], []
    for item in motions:
        task, payload = item['simple'], item['payload']
        row = {k: task[k] for k in ('game_id', 'task_id', 'import_id')}
        row.update(status=payload['status'], native_import_verified=False)
        if payload['status'] != 'READY':
            row.update(reason=payload['reason'])
        else:
            # The unchanged single-project preparation copied the original NPZ.
            for base in (workspace, frozen):
                raw = base / 'assets' / task['task_id'] / 'motion.npz'
                _safe_target(base, raw)
                checked(raw, payload['sha256'])
                text = raw.with_suffix('.json')
                _safe_target(base, text)
                if not text.exists():
                    shutil.copyfile(payload['readable_json']['path'], text)
                checked(text, payload['readable_json']['sha256'])
                refs.extend((reference(raw), reference(text)))
            row.update(source=reference(workspace / 'assets' / task['task_id'] / 'motion.npz'),
                       readable_json=reference(workspace / 'assets' / task['task_id'] / 'motion.json'),
                       source_refs=payload['source_refs'], git_commit=payload['git_commit'],
                       git_path=payload['git_path'], git_blob_oid=payload['git_blob_oid'])
        delivered.append(row)
    document = {'schema': 'refine.batch-motion-delivery.v1', 'game_id': game['game_id'],
                'items': delivered, 'native_import_verified': False, 'runtime_evaluated': False,
                'budget': 'Shared project budget: at most ten rounds including all repair categories'}
    for base in (workspace, frozen):
        path = base / 'motion_handoff.json'
        _safe_target(base, path)
        _freeze(path, document)
        refs.append(reference(path))
    return {'path': str(workspace / 'motion_handoff.json'), 'sources': refs}


def verify_delivery(delivery):
    for ref in delivery['sources']:
        checked(ref['path'], ref['sha256'])


def prompt(delivery):
    return (f"另外读取 {delivery['path']}，按原 import_id 处理全部 motion 导入任务。"
            '提供的NPZ和无损JSON只是原始动作数据，不代表已导入或可直接播放。'
            '按motion技能完成所需骨骼/蒙皮绑定、retarget、引擎导入、触发接线与真实播放复查；'
            '保持原动作来源、角色纹理与材质，禁止用静态姿势或装饰动画冒充源动作。'
            '缺少源文件的任务记录具体外部阻塞并继续其他任务，不另开轮数。')
