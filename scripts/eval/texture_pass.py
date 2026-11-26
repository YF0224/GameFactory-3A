#!/usr/bin/env python3
"""Texture = original asset vs the same asset after import into the engine (stage3).

For every finished stage3 eval dir: render the ORIGINAL asset files (SRCVIEW, same editor, light rig
and four angles as the imported VIEW), then judge each texture check by comparing
VIEW:<asset> (imported) with SRCVIEW:<asset> (original). REF is context only. The verdicts go to
``<eval dir>/texture_src/verdicts_evidence_tex.json`` and replace the texture dimension in score.json
(the earlier REF-based texture verdicts stay on disk). Nothing is recorded or replayed.

    python scripts/eval/texture_pass.py --draft-standards            # fixed generic standard per game
    python scripts/eval/texture_pass.py --approve <GameID>|all --reviewer <name>
    python scripts/eval/texture_pass.py --run [--suffix _refine_eval_20261110]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _common import common

from pipeline.eval.whitebox.core import asset_views, judge, pipeline, standards  # noqa: E402
from pipeline.eval.whitebox.core.paths import read_json, sha256, write_json  # noqa: E402
from pipeline.eval.refinement import criteria as s3criteria  # noqa: E402

VERSION = 'stage3-texture-src.v1'
ROOT = common.OUTPUTS / 'eval' / 'refine' / 'stage3_v3__judge-claude-opus-5-5'
REQ = ('贴图目标：比较同一资产导入引擎后的渲染（VIEW:{a}）与原始资产文件的渲染（SRCVIEW:{a}），两者使用相同引擎、'
       '灯光与四个视角。\n只评：导入后表面贴图/材质（主色分区、表面图案、材质质感）是否保留原始资产外观；'
       '贴图缺失、缺省灰白/粉色材质、贴错贴图或通道、原始资产没有的 UV 错乱为基本bug。REF 参考图只作背景，不作门槛；'
       '接入位置、动作与玩法不评。')


def rows_for(game_id: str) -> list[dict]:
    rows = [r for r in s3criteria.build(game_id)['criteria'] if r['metric'] == 'texture']
    return [dict(r, requirement=REQ.format(a=r['asset_id'])) for r in rows]


def standard_for(game_id: str, rows: list[dict]) -> dict:
    checks = {}
    for r in rows:
        a = r['asset_id']
        checks[r['id']] = {
            'visible_goal': f'导入引擎后的 {a} 表面贴图与材质保留了原始资产文件的外观。',
            'result_frame_description': f'VIEW:{a} 四视图的主色分区、表面图案与材质观感与 SRCVIEW:{a} 对应视角大体一致。',
            'correct_target_and_information': f'对比的是同一资产：VIEW:{a}（引擎导入后）与 SRCVIEW:{a}（原始资产文件）。',
            'necessary_context': f'同一渲染设置下的 VIEW:{a} 与 SRCVIEW:{a} 四视图；REF 仅作背景。',
            'representative_basic_function': f'VIEW:{a} 中资产带有贴图材质，主要颜色分区可辨认，没有明显显示错误。',
            'basic_function_bugs': ['原始资产有贴图，导入后贴图缺失或变成缺省灰、白或粉色材质。',
                                    '导入后的颜色分区或表面图案与原始资产明显不同（贴错贴图或通道）。',
                                    '导入后出现原始资产没有的 UV 错乱、拉伸或破面。'],
            'permitted_trigger_modes': ['automatic'],
            'original_requirement_diagnostic_only': r['requirement']}
    return {'revision': standards.VERSION,
            'summary': '贴图维度统一标准：以原始资产文件在同一引擎、同一灯光与视角下的渲染（SRCVIEW）为基准，'
                       '比较导入引擎后的渲染（VIEW）。10% 源码/资源证明资产被赋予材质；50% VIEW 中贴图材质正常显示但与'
                       ' SRCVIEW 的一致性不能充分判断；100% VIEW 清楚保留 SRCVIEW 的主色分区、图案与质感。REF 只作背景。',
            'diagnostic_only_categories': list(standards.DIAGNOSTIC), 'checks': checks}


def bench_dir(game_id: str) -> Path:
    return standards.BENCH_STANDARDS / 'stage3' / VERSION / game_id


def draft_all() -> None:
    from pipeline.eval.whitebox.core import suites
    metrics = suites.get('stage3').metrics
    for game in sorted(p.name for p in s3criteria.INPUTS.iterdir() if p.is_dir() and p.name[:1] == 'G'):
        rows = rows_for(game)
        if not rows:
            continue
        folder = bench_dir(game)
        folder.mkdir(parents=True, exist_ok=True)
        std = standard_for(game, rows)
        standards.validate('texture', rows, std, metrics)
        write_json(folder / 'texture.json', {'version': standards.VERSION, 'suite': 'stage3', 'criteria_version': VERSION,
                                             'metric': 'texture', 'game_id': game, 'model': 'template (no model)',
                                             'criteria_ids': [r['id'] for r in rows], 'standard': std})
        standards.write_review(folder, rows, 'stage3')
        print(game, len(rows), 'checks ->', folder / 'review.md')


def load(game_id: str, rows: list[dict]) -> dict:
    folder = bench_dir(game_id)
    if not (folder / 'approved.json').is_file():
        raise ValueError(f'{game_id}: texture-src standard not approved ({folder})')
    if sha256(folder / 'texture.json') != read_json(folder / 'approved.json')['metrics']['texture']:
        raise ValueError(f'{game_id}: texture-src standard changed after approval')
    return {'texture': read_json(folder / 'texture.json')['standard']}


def run_one(out: Path) -> dict:
    status = read_json(out / 'status.json') if (out / 'status.json').is_file() else {}
    if not (status.get('step') == 'score' and status.get('state') == 'done'):
        return {'skip': 'evaluation not finished'}
    manifest = read_json(out / 'manifest.json')
    if manifest['engine'] != 'unity3d':
        return {'skip': 'no in-engine view renderer for this engine yet'}
    views = read_json(out / 'asset_views' / 'asset_views.json')
    binary = read_json(out / 'takes' / '1' / 'record' / 'unity_editor.json')['editor']['binary']
    src = asset_views.render_source_unity(out, binary)
    rows = [r for r in rows_for(manifest['game_id'])]
    frozen = load(manifest['game_id'], rows)
    sub = out / 'texture_src'
    (sub / 'input').mkdir(parents=True, exist_ok=True)
    write_json(sub / 'input' / 'criteria.json', {'version': VERSION, 'game_id': manifest['game_id'], 'criteria': rows})
    write_json(sub / 'manifest.json', {**manifest, 'suite': 'stage3'})
    items = []
    for r in rows:
        a = r['asset_id']
        for kind, entry in (('VIEW', views['assets'].get(a)), ('SRCVIEW', src['assets'].get(a))):
            if entry and entry.get('ok') and entry.get('sheet'):
                items.append({'id': f'{kind}:{a}', 'path': entry['sheet']['path'], 'type': 'image',
                              'sha256': entry['sheet']['sha256'], 'lines': 0, 'check_ids': [r['id']]})
    for p in sorted((out / 'input' / 'references').glob('*')):
        items.append({'id': 'REF:' + p.name, 'path': str(p), 'type': 'image', 'sha256': sha256(p), 'lines': 0})
    mats = sub / 'materials.json'
    write_json(mats, {a: {'imported': (views['assets'].get(a) or {}).get('materials'),
                          'original': (src['assets'].get(a) or {}).get('materials')} for a in {r['asset_id'] for r in rows}})
    items.append({'id': 'MATERIALS', 'path': str(mats), 'type': 'channel', 'sha256': sha256(mats),
                  'lines': len(mats.read_text().splitlines())})
    evidence = {'version': VERSION, 'takes': [1], 'items': items, 'action_links': [], 'sheets': []}
    write_json(sub / 'evidence_tex.json', evidence)
    verdicts = judge.judge(sub, manifest, evidence, 'evidence', frozen, tag='_tex')
    result = pipeline.score(out)
    return {'texture': result['dimensions'].get('texture'), 'checks': len(verdicts)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--draft-standards', action='store_true')
    ap.add_argument('--approve')
    ap.add_argument('--reviewer', default='human')
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--suffix', default='_refine_eval_20261110')
    a = ap.parse_args()
    if a.draft_standards:
        draft_all()
    if a.approve:
        games = [p.name for p in (standards.BENCH_STANDARDS / 'stage3' / VERSION).iterdir()] if a.approve == 'all' else [a.approve]
        for g in games:
            print(g, standards.approve(bench_dir(g), a.reviewer)['metrics'])
    if a.run:
        for out in sorted(ROOT.glob(f'*/*/*{a.suffix}')):
            try:
                print(out.parents[1].name, out.parent.name[:4], run_one(out), flush=True)
            except Exception as exc:          # noqa: BLE001
                print(out.parents[1].name, out.parent.name[:4], 'ERROR', type(exc).__name__, exc, file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
