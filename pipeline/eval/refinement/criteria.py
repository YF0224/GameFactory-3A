"""Stage3 refine criteria: one check per refine task of the game.

Inputs per game: ``test_data/outputs/game_refine/inputs/<GameID>/``
(``mechanic_gamefeel.json``, ``vfx.json``, ``import.json``; copied byte-for-byte
from ``outputs/playtest/gN``), plus the detailed import acceptance criteria in
``game_refine/repair_import_collect.json`` (JSONL, joined by ``import_id``).

Dimensions (metric keys): ``mechanic``, ``gamefeel``, ``vfx``, ``import``, ``texture``.
Check id = ``selection_id`` (mechanic / gamefeel / vfx), ``import_id``, or
``<import_id>.texture`` (close-view texture check for at most MAX_TEXTURE_CHECKS representative
3D assets per game: scene first, then character-like objects, then task order).
Nothing is game-specific: every game is built by the same rules.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..whitebox.paths import OUTPUTS, read_json, sha256

VERSION = 'stage3-criteria.v3'          # v3: asset_id on import/texture rows -> in-engine 4-view VIEW evidence
INPUTS = OUTPUTS / 'game_refine' / 'inputs'
IMPORT_DETAIL = OUTPUTS / 'game_refine' / 'repair_import_collect.json'
FILES = ('mechanic_gamefeel.json', 'vfx.json', 'import.json')
TEXTURED_KINDS = ('3d_object', '3d_scene')          # get a separate close-view texture check


def _row(ident, metric, mode, group, requirement, **extra):
    return {'id': ident, 'metric': metric, 'mode': mode, 'group': group,
            'requirement': requirement, 'requirement_ids': [], **extra}


def _lines(*pairs) -> str:
    out = []
    for label, value in pairs:
        if value in (None, '', [], {}):
            continue
        if isinstance(value, list):
            value = '\n' + '\n'.join(f'- {v}' for v in value)
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        out.append(f'{label}：{value}')
    return '\n'.join(out)


def _import_details() -> dict:
    if not IMPORT_DETAIL.is_file():
        return {}
    rows = [json.loads(line) for line in IMPORT_DETAIL.read_text(encoding='utf-8').splitlines() if line.strip()]
    return {r['import_id']: r for r in rows if r.get('import_id')}


MAX_TEXTURE_CHECKS = 3      # per game: close views are costly; keep it within what a take can actually verify
TEXTURE_ROLES = ('player', 'hero', 'protagonist', 'character', 'enemy', 'boss', 'npc', 'creature')


def texture_targets(imports: list[dict]) -> set:
    """Deterministic, model-independent choice of the few 3D assets that get a texture check:
    the 3D scene(s) first, then character-like objects (player / enemy / NPC ...), then task order."""
    candidates = [t for t in imports if t['asset_kind'] in TEXTURED_KINDS]

    def rank(t):
        target = json.dumps(t.get('target') or {}, ensure_ascii=False).lower() + ' ' + str(t.get('asset_name', '')).lower()
        if t['asset_kind'] == '3d_scene':
            return 0
        return 1 if any(role in target for role in TEXTURE_ROLES) else 2

    ordered = sorted(enumerate(candidates), key=lambda it: (rank(it[1]), it[0]))
    return {t['import_id'] for _, t in ordered[:MAX_TEXTURE_CHECKS]}


def build(game_id: str) -> dict:
    folder = INPUTS / game_id
    if not folder.is_dir():
        raise ValueError(f'{game_id}: no stage3 refine inputs at {folder}')
    rows = []
    for t in read_json(folder / 'mechanic_gamefeel.json'):
        if t['game_id'] != game_id:
            raise ValueError(f'{t["selection_id"]}: belongs to another game')
        mechanic = t['selection_kind'] == 'mechanic'
        rows.append(_row(t['selection_id'], 'mechanic' if mechanic else 'gamefeel',
                         'runtime' if mechanic else 'visual',
                         'mechanic' if mechanic else (t.get('category') or 'gamefeel'),
                         _lines(('修复目标', t['repair_goal']), ('测试动作', t['test_action']),
                                ('通过条件', t['pass_condition'])),
                         **({} if mechanic else {'requires_temporal_evidence': True})))
    for t in read_json(folder / 'vfx.json'):
        rows.append(_row(t['gamefeel_id'] if 'selection_id' not in t else t['selection_id'], 'vfx', 'visual',
                         t.get('effect_type') or 'vfx',
                         _lines(('效果目标', t['repair_goal']), ('验收标准', t.get('acceptance_criteria')),
                                ('需要粒子系统', t.get('particle_system_required'))),
                         requires_temporal_evidence=True))
    details = _import_details()
    imports = read_json(folder / 'import.json')
    texture_ids = texture_targets(imports)
    for t in imports:
        d = details.get(t['import_id'], {})
        refs = [Path(r if isinstance(r, str) else r.get('path', '')).name for r in t.get('reference_images') or []]
        asset_id = Path(t.get('asset_path') or t['import_id']).name
        rows.append(_row(t['import_id'], 'import', 'visual', t['asset_kind'],
                         _lines(('导入目标', t['import_goal']), ('资产', f'{t.get("asset_name")}（{t.get("name_zh", "")}）'),
                                ('描述', t.get('description')), ('目标挂载', t.get('target')),
                                ('资产要求', t.get('asset_requirements')),
                                ('验收标准', d.get('acceptance_criteria')),
                                ('触发约定', d.get('trigger_contract')), ('动作约定', d.get('motion_contract')),
                                ('参考图（REF:*_<文件名>）', refs)),
                         asset_kind=t['asset_kind'], reference_images=refs, asset_id=asset_id,
                         requires_temporal_evidence=t['asset_kind'] in ('motion', 'audio', 'cg_video'),
                         **({'needs_motion_strip': True} if t['asset_kind'] == 'motion' else {})))
        if t['import_id'] in texture_ids:
            rows.append(_row(t['import_id'] + '.texture', 'texture', 'visual', t['asset_kind'],
                             _lines(('贴图目标', f'导入后的 {t.get("asset_name")}（{t.get("name_zh", "")}）表面贴图与材质正确'),
                                    ('描述', t.get('description')), ('资产要求', t.get('asset_requirements')),
                                    ('参考图（REF:*_<文件名>）', refs),
                                    ('只评', '贴图/材质：主色分区、表面图案、材质质感与参考图及描述一致；'
                                            '无缺失贴图（纯灰/纯白/粉色缺省材质）、贴错对象或明显 UV 错乱。'
                                            '是否接入槽位与位置由 import 判项负责，这里不评。')),
                             asset_kind=t['asset_kind'], reference_images=refs, import_id=t['import_id'],
                             asset_id=asset_id))
    # Optional dimension subset for a run (e.g. A3GAME_STAGE3_DIMENSIONS=mechanic,gamefeel,import,texture).
    wanted = [d.strip() for d in os.environ.get('A3GAME_STAGE3_DIMENSIONS', '').split(',') if d.strip()]
    excluded = []
    if wanted:
        excluded = [{'id': r['id'], 'metric': r['metric'], 'reason': 'dimension not in this run'}
                    for r in rows if r['metric'] not in wanted]
        rows = [r for r in rows if r['metric'] in wanted]
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f'{game_id}: duplicate refine task ids')
    sources = {f: {'path': str(folder / f), 'sha256': sha256(folder / f)} for f in FILES}
    if IMPORT_DETAIL.is_file():
        sources['import_detail'] = {'path': str(IMPORT_DETAIL), 'sha256': sha256(IMPORT_DETAIL)}
    return {'version': VERSION, 'game_id': game_id, 'criteria': rows, 'excluded': excluded,
            'dimensions': wanted or None, 'sources': sources}
