"""Read-only three-column scoring CLI; all heavy work fails closed during whitebox.

Example (safe while whitebox is active):
  python -B -m pipeline.game_eval.asset_eval.run --scope obj --games G001 \
    --providers meshy tripo --no-sol --mode preflight
"""
from __future__ import annotations
from .common import resolve_input
import argparse
from datetime import datetime
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys
import time

from .common import (ENV, OUTPUTS, SAMPLES, check_environment, dump, read, sha,
                     validate_out)
from .inventory import (CLOSED, character_references, inventory, object_delivery,
                        rubric_path, scene_bundles, scene_provider_override, style_context, tasks)
from .preflight import glb_header
from .resources import MetricsDeferred, assert_metrics_idle, low_priority, process_snapshot

PINNED = {'torch': '2.5.1', 'torchvision': '0.20.1', 'transformers': '4.37.2',
          'pyiqa': '0.1.13', 'trimesh': '4.5.3', 'scikit-image': '0.24.0',
          'scikit-learn': '1.5.2', 'pillow': '10.4.0'}


def environment_versions():
    versions = {}; mismatches = []
    for package, wanted in PINNED.items():
        try:
            actual = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            actual = None
        versions[package] = actual
        if actual != wanted:
            mismatches.append(f'{package}: required={wanted}, installed={actual}')
    return {'python_executable': sys.executable, 'python_version': sys.version,
            'prefix': sys.prefix, 'package_versions': versions, 'version_mismatches': mismatches,
            'package_imports_verified': False,
            'note': 'Distribution metadata only; no torch/NumPy/model import in preflight.',
            'ffmpeg': shutil.which('ffmpeg'), 'ffprobe': shutil.which('ffprobe')}


def selected_games(names):
    available = sorted(g for g in SAMPLES.glob('G0*') if g.is_dir())
    if not names:
        return available
    selected = [g for g in available if any(g.name == n or g.name.split('_')[0] == n for n in names)]
    unmatched = [n for n in names if not any(g.name == n or g.name.split('_')[0] == n for g in available)]
    if unmatched:
        raise ValueError('Unknown game(s): ' + ', '.join(unmatched))
    return selected


def make_row(game, task, provider, scope):
    mode = task.get('input_mode', 'image_to_3d' if scope == 'scene' else None)
    base = object_delivery(game, task, scope, provider); asset = base / 'model.glb'
    row = {'schema_version': 'asset_eval/0.1', 'game': game.name, 'task_id': task['task_id'],
            'provider': provider, 'scope': scope, 'input_mode': mode,
            'source_task_path': str(game / ('3D_object/object_tasks.jsonl' if scope == 'obj' else '3D_scene/scene_tasks.jsonl')),
            'asset_path': str(asset), 'delivered': asset.is_file(),
            'columns': {'input': {'score': None, 'metrics': {}},
                        'style': {'score': None, 'palette': {'weighted_mean_deltaE2000': None, 'pixel_fraction_deltaE_lt10': None}},
                        'quality': {'score': None, 'metrics': {}}},
            'preflight': None, 'notes': [], 'failure_label': None, 'failures': [], 'style_embedding': None}
    if scope == 'scene':
        row['scene_packages'] = scene_bundles(game, task)
        attribution = scene_provider_override(game, task)
        row['provider_attribution'] = attribution
        if attribution and attribution['provider'] == provider:
            source = next((p for p in row['scene_packages'] if Path(p['archive_path']).name == attribution['archive_filename']), None)
            if source and not row['delivered']:
                row['archive_source'] = {'path': source['archive_path'], 'member': attribution['member']}
                row['asset_path'] = None
                row['delivered'] = True
            row['notes'].append('Scene provider attributed by user confirmation (mable -> marble); no edits to input archive/meta. Evaluation concerns packaged GLB, which may include downstream processing.')
        elif row['scene_packages']:
            row['notes'].append('Scene ZIP exists but is not attributed to the requested provider; no generator substitution.')
    return row


def failure(row, label, reason):
    row['failures'].append({'label': label, 'reason': str(reason)})
    row['failure_label'] = ';'.join(dict.fromkeys(f['label'] for f in row['failures']))
    row['notes'].append(str(reason))


def metric_asset(row, task, game, asset_out, adapter, models, no_sol):
    """Real computation path; never entered while whitebox is active."""
    assert_metrics_idle()
    from .quality import geometry_quality, ImageQuality
    from .render import render_glb, standard_views, ring_views
    from .image_consistency import Dino, image_consistency
    from .style import palette_metric
    import numpy as np
    import torch
    torch.set_num_threads(1)
    context = style_context(game)
    try:
        assert_metrics_idle()
        geometry = geometry_quality(Path(row['asset_path']), task)
        row['columns']['quality']['geometry'] = geometry
        row['notes'].extend(geometry['notes'])
        if geometry['geometry_subscore'] is None:
            failure(row, 'geometry_metric_unavailable', 'Geometry mandatory measurement unavailable; no score substituted.')
        elif not geometry['raw']['load_ok']:
            failure(row, 'glb_load_failed', 'trimesh could not load valid geometry; see raw notes.')
    except MetricsDeferred:
        raise
    except Exception as exc:
        geometry = {'geometry_subscore': None, 'raw': {}, 'notes': [str(exc)]}
        failure(row, 'geometry_exception', exc)
    assert_metrics_idle()
    try:
        manifest = render_glb(Path(row['asset_path']), asset_out / 'renders', adapter, scope=row['scope'])
    except Exception as exc:
        failure(row, 'render_failed', exc)
        return
    views = standard_views(manifest, scope=row['scope'])
    if len(views) != 6 or len(ring_views(manifest)) != 12:
        failure(row, 'render_view_protocol_failed', 'Expected 6 standard views and 12 ring views; no partial scoring.')
        return
    try:
        assert_metrics_idle()
        palette = palette_metric([v['path'] for v in views], context['palette_hex'])
        row['columns']['style']['palette'] = palette
        row['notes'].extend(palette['notes'])
    except MetricsDeferred:
        raise
    except Exception as exc:
        failure(row, 'palette_metric_unavailable', exc)
    try:
        assert_metrics_idle()
        if models.get('iqa') is None:
            models['iqa'] = ImageQuality()
        result = models['iqa'].evaluate(views, geometry)
        row['columns']['quality'].update(score=result['quality_index'], metrics=result)
        row['notes'].extend(result['notes'])
        if result['quality_index'] is None:
            failure(row, 'quality_index_unavailable', 'Quality index requires all six MUSIQ views and geometry subscore.')
    except MetricsDeferred:
        raise
    except Exception as exc:
        failure(row, 'quality_metric_unavailable', exc)
    try:
        assert_metrics_idle()
        if models.get('dino') is None:
            if 'dino_error' in models:
                raise RuntimeError(models['dino_error'])
            try:
                models['dino'] = Dino(cache=str(OUTPUTS / '_cache/huggingface'))
            except Exception as exc:
                models['dino_error'] = str(exc)
                raise
        dino = models['dino']
        features = dino.encode([v['path'] for v in views])
        mean = features.mean(axis=0); norm = np.linalg.norm(mean)
        if norm <= 0:
            raise ValueError('Zero mean DINO embedding')
        row['style_embedding'] = (mean / norm).tolist()
        if row['input_mode'] == 'image_to_3d' or row['scope'] == 'scene':
            from .common import BENCH
            reference = resolve_input(task['image_path'])
            if not reference.is_relative_to(SAMPLES.resolve()) or not reference.is_file():
                raise ValueError('Missing/outside-samples image reference')
            comparison_views = ring_views(manifest)
            result = image_consistency(dino, reference, comparison_views)
            row['columns']['input'].update(score=result['dinov2_cosine_max'], metrics=result)
    except MetricsDeferred:
        raise
    except Exception as exc:
        failure(row, 'dino_metric_unavailable', exc)
    if no_sol:
        row['notes'].append('sol_disabled: text rubric adherence and sol style score intentionally null; no API call.')
        if row['input_mode'] == 'text_to_3d':
            row['columns']['input']['notes'] = ['sol_disabled: no text adherence score without a rubric judge.']
    else:
        from .rubric_judge import judge_rubric, judge_style
        if row['input_mode'] == 'text_to_3d':
            rp = rubric_path(game, task, row['scope'])
            if rp is None:
                failure(row, 'rubric_missing', 'No per-asset rubric; text adherence null.')
            else:
                result = judge_rubric(asset_out, task, read(rp), views)
                row['columns']['input'].update(score=result['score'], metrics=result)
                if result.get('failure_label'):
                    failure(row, result['failure_label'], 'Rubric judge unavailable; see model_calls and metric notes.')
        result = judge_style(asset_out, context, views)
        row['columns']['style'].update(score=result['score'], sol=result)
        if result.get('failure_label'):
            failure(row, result['failure_label'], 'Style judge unavailable; see model_calls and metric notes.')


def execute(args):
    if args.scope in ('video', 'cg', 'audio'):
        if args.mode != 'metrics':
            raise ValueError('Media scoring pilot supports --mode metrics only; use media_pilot for local decoding probe.')
        if args.games != ['G001']:
            raise ValueError('Media expansion disabled: only the explicit G001 small pilot is authorized here.')
        if args.wait_whitebox:
            raise ValueError('Media pilot defers immediately while whitebox is active; rerun once idle.')
        from .media_scoring import run_pilot
        scope = 'video' if args.scope == 'cg' else args.scope
        path = run_pilot(args.out, scopes=(scope,), providers=args.providers, no_sol=args.no_sol, source_run=args.reuse_source_run)
        print(path)
        return 0
    args.providers = args.providers or (['marble'] if args.scope == 'scene' else ['meshy', 'tripo'])
    started = time.monotonic(); cpu_started = time.process_time(); check_environment(); priority = low_priority()
    out = validate_out(args.out or OUTPUTS / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + args.scope + ('_no_sol' if args.no_sol else '_scores')))
    if (out / 'run.json').exists() or (out / 'assets').exists():
        raise ValueError('Run directory already contains results; choose a new --out (no overwrite).')
    games = selected_games(args.games)
    if args.scope not in ('obj', 'scene'):
        raise ValueError('video/audio stages are deferred; this smoke runner supports obj/scene only')
    args.providers = ['marble' if p == 'mable' else p for p in args.providers]
    allowed = ('meshy', 'tripo') if args.scope == 'obj' else ('meshy', 'tripo', 'marble')
    if any(p not in CLOSED or p not in allowed for p in args.providers):
        raise ValueError(f'Closed provider allowlist for {args.scope}: {allowed}')
    # Full expansion remains gated even for no-sol runs. A G001 smoke is not the pilot.
    if args.mode == 'metrics' and any(g.name.split('_')[0] != 'G001' for g in games):
        raise ValueError('Full expansion disabled until complete G001 pilot acceptance.')
    env = environment_versions(); dump(out / 'environment.json', env)
    # Pure version metadata: do not import the installed ML distributions.
    lock = sorted(f'{d.metadata["Name"]}=={d.version}' for d in importlib.metadata.distributions() if d.metadata.get('Name'))
    (out / 'requirements.lock.txt').write_text('\n'.join(lock) + '\n')
    inv = inventory(games, audit_rubric_content=not args.no_sol)
    dump(out / 'inventory.json', inv)
    state = process_snapshot()
    blocked = bool(state['whitebox_batch'] or state['sol'])
    if args.wait_whitebox and args.mode == 'metrics':
        while blocked:
            dump(out / 'waiting.json', {'status': 'waiting_whitebox', 'process_snapshot': state,
                'next_check_seconds': args.poll_seconds, 'heavy_imports_started': False})
            time.sleep(args.poll_seconds)
            state = process_snapshot(); blocked = bool(state['whitebox_batch'] or state['sol'])
    can_compute = args.mode == 'metrics' and not blocked and not env['version_mismatches']
    adapter = None
    if can_compute:
        from .render import configured_renderer
        adapter = configured_renderer(out / '_renderer', scope=args.scope)
    rows = []; models = {}
    for game in games:
        for task in tasks(game, args.scope):
            for provider in args.providers:
                row = make_row(game, task, provider, args.scope)
                asset_out = out / 'assets' / game.name / task['task_id'] / provider
                asset_out.mkdir(parents=True, exist_ok=True)
                if args.no_sol:
                    row['notes'].append('sol_disabled: no rubric or model-based style judgment; corresponding scores remain null.')
                if not row['delivered']:
                    failure(row, 'asset_missing', 'Generated model.glb missing; no substitute asset or fabricated score.')
                else:
                    try:
                        if row.get('archive_source'):
                            from .scene_bundle import extract_scene_glb
                            source = row['archive_source']
                            row['asset_path'] = str(extract_scene_glb(Path(source['path']), asset_out / 'extracted', member=source['member']))
                            row['archive_source']['extracted_sha256'] = sha(Path(row['asset_path']))
                        row['preflight'] = glb_header(row['asset_path'])
                    except Exception as exc:
                        failure(row, 'glb_preflight_failed', exc)
                    if row['preflight'] is None:
                        pass  # Existing preflight failure already records the actual cause.
                    elif can_compute:
                        try:
                            metric_asset(row, task, game, asset_out, adapter, models, args.no_sol)
                        except MetricsDeferred as exc:
                            can_compute = False; blocked = True
                            failure(row, 'metrics_deferred_whitebox', exc)
                    else:
                        label = 'metrics_deferred_whitebox' if blocked else ('environment_version_mismatch' if env['version_mismatches'] else 'preflight_only')
                        failure(row, label, 'Only bounded stdlib metadata preflight performed; render/DINO/MUSIQ/palette/trimesh not executed.')
                dump(asset_out / 'score.json', row); rows.append(row)
    dispersion = []
    if any(row['style_embedding'] is not None for row in rows):
        from .style import game_dispersion
        dispersion = game_dispersion(rows)
    if models.get('dino'):
        dump(out / 'models.json', {'dino': models['dino'].info()})
    else:
        dump(out / 'models.json', {'dino': None, 'musiq': None, 'note': 'No model loaded/inferred in metadata-only preflight.'})
    imports = {name: any(m == name or m.startswith(name + '.') for m in sys.modules)
               for name in ('torch', 'numpy', 'transformers', 'pyiqa', 'trimesh', 'PIL', 'skimage', 'sklearn')}
    calls = []
    for invocation in out.glob('assets/**/model_calls/*/invocation.json'):
        item = read(invocation)
        if item.get('command'):
            calls.append(str(invocation.relative_to(out)))
    accepted = list(out.glob('assets/**/model_calls/*/accepted_response.json'))
    metadata = {'sol_invocation_attempts': len(calls), 'accepted_judgments': len(accepted),
                'invocation_paths': calls,
                'status': 'preflight_passed_metrics_deferred' if blocked else ('preflight_only' if args.mode == 'preflight' else 'metrics_attempted'),
                'mode': args.mode, 'scope': args.scope, 'games': [g.name for g in games],
                'no_sol': args.no_sol, 'api_calls': 0 if args.no_sol else None,
                'resource_policy': priority, 'process_snapshot': state,
                'heavy_imports': imports, 'elapsed_seconds': time.monotonic() - started,
                'cpu_seconds': time.process_time() - cpu_started,
                'sol_judge_imported': 'pipeline.game_eval.asset_eval.rubric_judge' in sys.modules,
                'complete_pilot_passed': False,
                'notes': ['Metadata checks and report serialization are not proof of render/inference/score correctness.',
                          'No background evaluator was signalled, modified, or stopped.']}
    from .report import write_reports
    write_reports(out, rows, inv, metadata, dispersion)
    dump(out / 'pilot_acceptance.json', {'passed': False, 'self_dino': None, 'negative_dino': None,
         'palette_control': None, 'text_sol_evidence_check': None,
         'reason': 'Smoke test only; missing delivered G001 image assets and no sol acceptance audit.'})
    passed = sum(bool(r['preflight'] and r['preflight']['header_ok']) for r in rows)
    body = ['# G001 资产评分链路试点', '',
            f'- 计划记录：{len(rows)}；找到 model.glb：{sum(r["delivered"] for r in rows)}；GLB header/JSON预检通过：{passed}。',
            '- 已验证：读取真实任务、短/长 task_id 映射、生成文件定位、GLB header/JSON、只读renderer配置适配、逐资产JSON、CSV、Markdown报告。',
            '- 未验证：真实渲染、DINO、MUSIQ、trimesh几何、色板计算和任何sol判定。' if not any(imports.values()) else '- 真实计算尝试详情见逐资产JSON，不能视为完整试点通过。',
            '- 所有未计算分数保持null，不把metadata声明当测量值。',
            f'- 白膜资源门控：{"仍在运行，重计算暂缓" if blocked else "未观察到活跃批次"}。',
            f'- sol调用记录：{len(calls)}次CLI invocation，{len(accepted)}份accepted判词；内部API请求数未独立测量。',
            '- 阶段1完整验收未通过，不扩量。',
            f'- 本次测试耗时：{metadata["elapsed_seconds"]:.3f}s。']
    (out / 'pilot_summary.md').write_text('\n'.join(body) + '\n')
    print(json.dumps({'out': str(out), 'records': len(rows), 'delivered': sum(r['delivered'] for r in rows),
                      'glb_header_pass': passed, 'status': metadata['status'], 'heavy_imports': imports,
                      'api_calls': metadata['api_calls']}, ensure_ascii=False))
    return 0 if passed > 0 else 2


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scope', choices=('obj', 'scene', 'video', 'cg', 'audio'), default='obj')
    p.add_argument('--games', nargs='+', default=['G001'])
    p.add_argument('--providers', nargs='+', help='Closed providers; defaults follow selected scope')
    p.add_argument('--out', type=Path)
    p.add_argument('--reuse-source-run', type=Path, help='Media only: verify and reuse prior sealed identity judgment; never patch model output')
    p.add_argument('--no-sol', action='store_true', help='Never import/call the sol judge; rubric/style scores remain null')
    p.add_argument('--mode', choices=('preflight', 'metrics'), default='metrics')
    p.add_argument('--wait-whitebox', action='store_true', help='Wait with stdlib-only polling before any heavy imports')
    p.add_argument('--poll-seconds', type=int, default=60)
    args = p.parse_args(argv)
    if args.poll_seconds < 30:
        p.error('--poll-seconds must be >=30 to avoid busy polling')
    return execute(args)


if __name__ == '__main__':
    raise SystemExit(main())
