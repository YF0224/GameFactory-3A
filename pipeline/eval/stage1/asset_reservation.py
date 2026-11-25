"""Asset proof from the frozen C3 inventory, with versioned scoring.

New tiered attempts average placeholder/binding/hook coverage at equal weights.
Historical generic three-check and conjunctive per-slot policies stay readable;
requirements, item identities and task source hashes are frozen before judging.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import copy
import json

from .protocol import COLUMNS, sha

VERSION = 'whitebox-required-asset-slots.v1'
DIMENSION_VERSION = 'whitebox-asset-three-dimension-coverage.v1'
DEFAULT_VERSION = DIMENSION_VERSION
SUPPORTED_VERSIONS = {VERSION, DIMENSION_VERSION}
DIMENSIONS = {
    'placeholder': '占位：该需求对应的实际占位对象、组件或资源目标已在交付源码/场景中创建并连接真实入口。单有需求清单或声明不算实现；本项不要求替换和挂点也已完成。',
    'binding': '替换：该需求的资源引用、加载、实例化或场景赋值链已真实连接，可将占位资源换成最终资源；只定义未被使用的字段或函数不算。单独核实本项，不要求其他两项同时通过。',
    'hook': '挂点：该需求对应的挂载位置、动作/音效/特效/播放触发接口或场景接入点存在，并有真实调用或绑定链；无调用的空接口不算。单独核实本项，不要求其他两项同时通过。',
}
DIMENSION_INSTRUCTION = (
    '资产预留分三个等权维度：占位、替换、挂点。对每个冻结需求分别核实三个独立检查；'
    '控制器计算100/3*(占位已实现数/应占位数+替换已实现数/应替换数+挂点已实现数/应挂点数)。'
    '不能把某一维度整组判成全有或全无，也不能因为一个维度未完成而否定该资产的其他维度。'
    '分母只取冻结需求清单，交付缺失仍保留在分母；同名但不同角色/任务分别核实。'
    'PASS须引用实际交付源码或场景的路径/行号和真实连接依据；需求清单不能证明实现。'
    '不要求最终成品资源或美术品质；不由模型自行增删需求、维度或计算总分。')
COLUMN = COLUMNS[2]
TASK_FILES = {
    '3d_object': '3D_object/object_tasks.jsonl',
    '3d_scene': '3D_scene/scene_tasks.jsonl',
    'motion': 'motion/motion_tasks.jsonl',
    'audio': 'audio/audio_tasks.jsonl',
    'cg_video': 'cg_video/cg_tasks.jsonl',
}
INSTRUCTION = ('资产预留逐个核对冻结任务的对应插口：须有实际占位/绑定目标、可替换引用或接口及真实调用路径。'
               '通用函数可共享，但必须分别证明每个任务与调用方的绑定；只有声明、清单、字符串或无调用挂点不通过。'
               '不要求成品资源或最终美术品质；缺插口按该项0，不能因为同组有一项缺失就整组归零。'
               '相同动作名属于不同角色时分别核对，不把一个角色的绑定推给另一个。')


def enabled(protocol):
    return protocol.get('asset_reservation_policy', {}).get('version') in SUPPORTED_VERSIONS


def instruction(protocol):
    return (DIMENSION_INSTRUCTION if protocol.get('asset_reservation_policy', {}).get('version')
            == DIMENSION_VERSION else INSTRUCTION)


def _task_label(task, kind):
    if kind == '3d_scene':
        return task.get('asset_name') or task['task_id']
    return (task.get('asset_name') or task.get('name') or task.get('cg_name')
            or task.get('motion_name') or task['task_id'])


def freeze(protocol, contract, *, case_directory, rubric_sha256, version=VERSION):
    """Use C3 subitems, never the number of endpoint groups or delivery slots.

    Task lists enrich repeated names with the source character/task ID. Their
    hashes must be those already bound to the frozen rubric. No model extraction.
    """
    if version not in SUPPORTED_VERSIONS:
        raise ValueError('unknown requested asset reservation policy')
    if 'asset_reservation_policy' in protocol:
        raise ValueError('asset reservation policy already frozen')
    if contract.get('game_id') != protocol.get('case_id'):
        raise ValueError('asset inventory case mismatch')
    case = Path(case_directory)
    sources = contract.get('task_coverage_policy', {}).get('source_inputs', {})
    tasks = defaultdict(list)
    task_sources = {}
    for kind, relative in TASK_FILES.items():
        if relative not in sources:
            continue
        path = case / relative
        if not path.is_file() or path.is_symlink() or sha(path) != sources[relative]:
            raise ValueError('asset task source differs from frozen rubric: ' + relative)
        task_sources[relative] = sources[relative]
        for number, text in enumerate(path.read_text().splitlines(), 1):
            if not text.strip():
                continue
            task = json.loads(text)
            if task.get('game_id', protocol['case_id']) != protocol['case_id']:
                raise ValueError('asset task belongs to a different game')
            tasks[(kind, str(_task_label(task, kind)))].append((number, task))
    rows = []
    seen = set()
    task_ids = set()
    for endpoint in contract['assertions']:
        if endpoint['table_column'] != 'C3' or endpoint.get('applicable') is False:
            continue
        for sub in endpoint['binding']['subchecks']:
            if sub.get('scoring_role', 'scored') != 'scored':
                continue
            ident = 'asset.' + endpoint['assertion_id'] + '.' + sub['id']
            if ident in seen:
                raise ValueError('duplicate frozen asset item')
            seen.add(ident)
            kind = sub['system']
            row = {'id': ident, 'column': COLUMN, 'mode': 'static', 'group': kind,
                   'asset_policy': VERSION, 'asset_kind': kind,
                   'frozen_assertion_id': endpoint['assertion_id'],
                   'frozen_subcheck_id': sub['id'],
                   'requirement_ids': list(sub['requirement_ids']),
                   'requirement': sub['text']}
            # Repeated labels are matched in the original physical task order,
            # not deduplicated. No arbitrary delivery-specific substitutions.
            if kind in TASK_FILES:
                label = sub['text'].split('：', 1)[0].removeprefix(kind + '/')
                matched = tasks.get((kind, label), [])
                if not matched:
                    raise ValueError('frozen C3 item has no matching frozen task: ' + sub['text'])
                number, task = matched.pop(0)
                if task['task_id'] in task_ids:
                    raise ValueError('one task assigned to multiple asset requirements')
                task_ids.add(task['task_id'])
                row['asset_task_id'] = task['task_id']
                row['task_source'] = {'path': TASK_FILES[kind], 'line': number,
                                      'sha256': task_sources[TASK_FILES[kind]]}
                row['asset_binding'] = {key: task[key] for key in (
                    'asset_name', 'character', 'source_asset', 'motion_name', 'action_name',
                    'trigger', 'event_binding', 'cg_name', 'cg_type', 'start_condition',
                    'end_condition', 'skip_behavior', 'next_state') if key in task}
            else:
                # Some frozen contracts contain a single conjunctive VFX item.
                # Preserve its full requirement, and label it as such in reports.
                row['inventory_unit'] = 'frozen_requirement'
            rows.append(row)
    if not rows:
        raise ValueError('no required asset items; cannot default the asset column to 100')
    if any(queue for queue in tasks.values()):
        raise ValueError('frozen task list is not fully covered by C3 inventory')
    if version == DIMENSION_VERSION:
        return _freeze_dimensions(protocol, rows, task_sources, rubric_sha256)
    counts = dict(Counter(row['asset_kind'] for row in rows))
    protocol['asset_reservation_policy'] = {
        'version': VERSION, 'rubric_sha256': rubric_sha256,
        'task_sources': task_sources, 'required_count': len(rows),
        'required_by_kind': counts, 'criterion_ids': [row['id'] for row in rows],
        'formula': '100 * verified_bound_slots / frozen_required_items; each required item counted once',
        'indicator_weight': 1 / 8,
        'instructions': INSTRUCTION,
    }
    protocol['criteria'] = [row for row in protocol['criteria'] if row['column'] != COLUMN] + rows
    validate(protocol)
    return protocol['asset_reservation_policy']


def _freeze_dimensions(protocol, items, task_sources, rubric_sha256):
    rows = []
    for item in items:
        for dimension, requirement in DIMENSIONS.items():
            row = copy.deepcopy(item)
            row.update(id=item['id']+'.'+dimension, asset_item_id=item['id'],
                       asset_policy=DIMENSION_VERSION, asset_dimension=dimension,
                       requirement=item['requirement']+'\n'+requirement)
            rows.append(row)
    protocol['asset_reservation_policy'] = {
        'version': DIMENSION_VERSION, 'rubric_sha256': rubric_sha256,
        'task_sources': task_sources, 'required_count': len(items),
        'required_by_kind': dict(Counter(item['asset_kind'] for item in items)),
        'inventory_ids': [item['id'] for item in items],
        'criterion_ids': [row['id'] for row in rows],
        'required_by_dimension': {dimension: len(items) for dimension in DIMENSIONS},
        'dimension_weights': {dimension: 1/3 for dimension in DIMENSIONS},
        'formula': '100 / 3 * (placeholder_pass/placeholder_required + binding_pass/binding_required + hook_pass/hook_required)',
        'indicator_weight': 1/8, 'instructions': DIMENSION_INSTRUCTION,
    }
    protocol['criteria'] = [row for row in protocol['criteria'] if row['column'] != COLUMN]+rows
    validate(protocol)
    return protocol['asset_reservation_policy']


def _validate_dimensions(policy, rows):
    inventory = policy.get('inventory_ids', [])
    count = policy.get('required_count')
    expected_ids = [item+'.'+dimension for item in inventory for dimension in DIMENSIONS]
    if (not inventory or len(set(inventory)) != len(inventory) or count != len(inventory)
            or [row['id'] for row in rows] != expected_ids
            or policy.get('criterion_ids') != expected_ids
            or policy.get('required_by_dimension') != {dimension: count for dimension in DIMENSIONS}
            or policy.get('dimension_weights') != {dimension: 1/3 for dimension in DIMENSIONS}
            or policy.get('indicator_weight') != 1/8):
        raise ValueError('asset dimension denominator/identity drift')
    for index, item in enumerate(inventory):
        group = rows[index*3:index*3+3]
        for dimension, row in zip(DIMENSIONS, group):
            if (row.get('asset_item_id') != item or row.get('asset_dimension') != dimension
                    or row.get('asset_policy') != DIMENSION_VERSION or row.get('mode') != 'static'):
                raise ValueError('asset dimension denominator/identity drift')
        # Each dimension must refer to precisely the same frozen task/source.
        keys = ('asset_kind', 'asset_task_id', 'task_source', 'asset_binding',
                'frozen_assertion_id', 'frozen_subcheck_id', 'requirement_ids', 'inventory_unit')
        if any(any(row.get(key) != group[0].get(key) for key in keys) for row in group[1:]):
            raise ValueError('asset dimension task/source drift')
    if dict(Counter(rows[index*3]['asset_kind'] for index in range(count))) != policy.get('required_by_kind'):
        raise ValueError('asset dimension inventory kind drift')


def validate(protocol):
    policy = protocol.get('asset_reservation_policy')
    if policy is None:
        return
    if policy.get('version') == DIMENSION_VERSION:
        return _validate_dimensions(policy, [row for row in protocol['criteria'] if row['column'] == COLUMN])
    if policy.get('version') != VERSION:
        raise ValueError('unknown asset reservation policy')
    rows = [row for row in protocol['criteria'] if row['column'] == COLUMN]
    ids = [row['id'] for row in rows]
    if (not rows or len(set(ids)) != len(ids) or ids != policy['criterion_ids']
            or len(rows) != policy['required_count']
            or dict(Counter(row['asset_kind'] for row in rows)) != policy['required_by_kind']
            or any(row.get('asset_policy') != VERSION or row.get('mode') != 'static' for row in rows)
            or policy.get('indicator_weight') != 1 / 8):
        raise ValueError('asset inventory denominator/identity drift')


def coverage(rows):
    """Only validated item PASS verdicts contribute; never accept model totals."""
    if not rows or not any(row.get('asset_policy') for row in rows):
        return None
    if all(row.get('asset_policy') == DIMENSION_VERSION for row in rows):
        return _dimension_coverage(rows)
    if any(row.get('asset_policy') != VERSION for row in rows):
        raise ValueError('mixed asset reservation policies')
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate asset verdict')
    result = {}
    for kind in sorted({row['asset_kind'] for row in rows}):
        group = [row for row in rows if row['asset_kind'] == kind]
        present = sum(row['status'] == 'PASS' and row['score'] == 1 for row in group)
        result[kind] = {'reserved': present, 'required': len(group),
                        'score': round(100 * present / len(group), 2),
                        'item_ids': [row['id'] for row in group]}
    return {'policy': VERSION, 'reserved': sum(row['reserved'] for row in result.values()),
            'required': len(rows), 'by_kind': result,
            'items': [{'id': row['id'], 'task_id': row.get('asset_task_id'),
                       'kind': row['asset_kind'], 'status': row['status'],
                       'bound': row['status'] == 'PASS' and row['score'] == 1,
                       'evidence': copy.deepcopy(row.get('evidence', []))} for row in rows]}


def _dimension_coverage(rows):
    ids = [row['id'] for row in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate asset verdict')
    items = list(dict.fromkeys(row.get('asset_item_id') for row in rows))
    expected = {(item, dimension) for item in items for dimension in DIMENSIONS}
    actual = {(row.get('asset_item_id'), row.get('asset_dimension')) for row in rows}
    if not items or None in items or actual != expected or len(rows) != len(expected):
        raise ValueError('asset dimension verdict denominator/identity drift')
    dimensions = {}
    for dimension in DIMENSIONS:
        group = [row for row in rows if row['asset_dimension'] == dimension]
        passed = sum(row['status'] == 'PASS' and row['score'] == 1 for row in group)
        dimensions[dimension] = {'reserved': passed, 'required': len(group), 'weight': 1/3,
                                 'score': round(100*passed/len(group), 2),
                                 'item_ids': [row['id'] for row in group]}
    # Use exact counts until the final column rounding; never average rounded percentages.
    score = 100/3*sum(group['reserved']/group['required'] for group in dimensions.values())
    return {'policy': DIMENSION_VERSION, 'score': round(score, 2), 'required': len(items),
            'by_dimension': dimensions,
            'items': [{'id': row['id'], 'item_id': row['asset_item_id'],
                       'task_id': row.get('asset_task_id'), 'kind': row['asset_kind'],
                       'dimension': row['asset_dimension'], 'status': row['status'],
                       'bound': row['status'] == 'PASS' and row['score'] == 1,
                       'evidence': copy.deepcopy(row.get('evidence', []))} for row in rows]}


def verify_recovery(root, protocol, source):
    """Prove the only changed frozen target is the asset slot inventory.

    This explicit policy migration may reuse unchanged runtime judge requests;
    it never authorizes reuse of the historical three generic asset verdicts.
    """
    from . import batch
    root, source = Path(root).resolve(), Path(source).resolve()
    if source == root or source.parent != root.parent:
        raise ValueError('asset recovery source escapes the preserved batch')
    receipt = batch.read(root/'asset_reservation_recovery.json')
    if (receipt.get('schema') != VERSION or receipt.get('source_attempt') != str(source)
            or receipt.get('source_protocol_sha256') != sha(source/'input/pilot_rubric.json')
            or receipt.get('source_input_manifest_sha256') != sha(source/'input_manifest.json')
            or receipt.get('source_static_existence_sha256') != sha(source/'static_existence.json')):
        raise ValueError('asset recovery source receipt changed')
    original = batch.read(source/'input/pilot_rubric.json')
    if 'asset_reservation_policy' in original:
        raise ValueError('asset recovery must start from an unchanged historical asset policy')
    expected = copy.deepcopy(original)
    frozen = batch.read(root/'input/frozen_rubric.json')
    freeze(expected, frozen, case_directory=root/'input/asset_tasks',
           rubric_sha256=sha(root/'input/frozen_rubric.json'))
    if expected != protocol:
        raise ValueError('asset recovery changed non-asset scoring/planning/capture targets')
    before = batch.read(source/'input_manifest.json')
    after = batch.read(root/'input_manifest.json')
    old_entry, new_entry = copy.deepcopy(before['entry']), copy.deepcopy(after['entry'])
    if new_entry.pop('asset_reservation_policy', None) != VERSION or old_entry != new_entry:
        raise ValueError('asset recovery changed delivery or source selection')
    if before['snapshot_hashes'] != after['snapshot_hashes']:
        raise ValueError('asset recovery changed project source')
    expected_hashes = dict(before['input_hashes'])
    expected_hashes['pilot_rubric.json'] = sha(root/'input/pilot_rubric.json')
    for relative, digest in protocol['asset_reservation_policy']['task_sources'].items():
        expected_hashes['asset_tasks/'+relative] = digest
    if after['input_hashes'] != expected_hashes:
        raise ValueError('asset recovery changed frozen inputs outside its declared inventory')
    return receipt
