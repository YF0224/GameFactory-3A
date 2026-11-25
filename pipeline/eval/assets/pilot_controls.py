"""Audit an existing G001 pilot and run controls; never re-call sol or rescore.

Scores are reused with per-file provenance. This is not full-stage acceptance:
missing image-mode deliveries leave the generated-asset negative control null.
"""
from __future__ import annotations
import argparse
from datetime import datetime
from pathlib import Path
import time
from .common import (BENCH, OUTPUTS, SAMPLES, check_environment, dump, read,
                     sha, validate_out)
from .inventory import inventory, tasks, style_context
from .resources import assert_metrics_idle, low_priority


def audit_evidence(score_file):
    """Check citations against actual manifest hashes and CLI --image arguments."""
    row = read(score_file)
    root = score_file.parent
    manifest = read(root / 'renders/manifest.json')
    views = {v['id']: v for v in manifest['views'] if v['id'].startswith('V')}
    invocation = read(root / 'model_calls/judge_rubric/invocation.json')
    command = invocation['command']
    sent = [str(Path(command[i + 1]).resolve()) for i, x in enumerate(command) if x == '--image']
    accepted = read(root / 'model_calls/judge_rubric/accepted_response.json')
    response_path = (root / 'model_calls/judge_rubric' / accepted['path']).resolve()
    if not response_path.is_relative_to((root / 'model_calls/judge_rubric').resolve()) or sha(response_path) != accepted['sha256']:
        raise ValueError('Accepted model response path/hash mismatch')
    response = read(response_path)
    refs = {v for checks in response['checks'].values() for c in checks.values() for v in c['evidence_views']}
    hashes_ok = all(Path(v['path']).is_file() and sha(Path(v['path'])) == v['sha256'] for v in views.values())
    sent_ok = len(sent) == 6 and set(sent) == {str(Path(v['judge_path']).resolve()) for v in views.values()}
    schema_complete = all(c['evidence_views'] and set(c['evidence_views']) <= set(views)
                          for checks in response['checks'].values() for c in checks.values())
    result = {'task_id': row['task_id'], 'provider': row['provider'],
              'source': str(score_file), 'source_sha256': sha(score_file),
              'cited_view_ids': sorted(refs), 'render_hashes_match': hashes_ok,
              'images_match_invocation': sent_ok, 'citations_valid': schema_complete,
              'passed_structural_check': len(views) == 6 and hashes_ok and sent_ok and schema_complete,
              'semantic_visual_audit': None,
              'note': 'Structural citation audit only; does not replace visual review or alter model judgments.'}
    return result, list(views.values())


def run(source_run, out=None):
    check_environment()
    low_priority()
    assert_metrics_idle()
    source_run = Path(source_run).resolve()
    if not source_run.is_relative_to(OUTPUTS.resolve()):
        raise ValueError('Only an existing asset_eval pilot may be audited')
    out = validate_out(out or OUTPUTS / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_G001_scoring_audit'))
    if any(out.iterdir()):
        raise ValueError('Audit directory must be empty')
    start = time.monotonic()
    source_files = sorted(source_run.glob('assets/**/score.json'))
    if not source_files:
        raise ValueError('No scores in source run')
    rows = [read(p) for p in source_files]
    if any(r['scope'] != 'obj' or not r['game'].startswith('G001_') for r in rows):
        raise ValueError('Controls currently audit the G001 object pilot only')
    for p, row in zip(source_files, rows):
        row['score_source'] = {'path': str(p), 'sha256': sha(p), 'policy': 'Original score reused without modification; model calls/renders remain in source run'}
        dump(out / 'assets' / row['game'] / row['task_id'] / row['provider'] / 'score.json', row)
    game = SAMPLES / rows[0]['game']
    game2 = next(p for p in SAMPLES.glob('G002_*') if p.is_dir())
    reference_task = next(t for t in tasks(game, 'obj') if t['task_id'] == 'G001_obj_001')
    negative_task = next(t for t in tasks(game2, 'obj') if t['task_id'] == 'G002_obj_001')
    if reference_task['role'] != negative_task['role']:
        raise ValueError('Negative reference must be the same explicit asset role')
    reference = (BENCH / reference_task['image_path']).resolve()
    negative = (BENCH / negative_task['image_path']).resolve()
    if not all(p.is_file() and p.is_relative_to(SAMPLES.resolve()) for p in (reference, negative)):
        raise ValueError('Missing/outside-samples reference image')
    controls = {'passed': False, 'self_dino': None, 'negative_reference_dino': None,
                'negative_generated_asset_dino': None, 'palette_control': None,
                'notes': ['Reference-vs-reference negative is a model sanity check, not the generated-asset negative required for full acceptance.',
                          'G001 image_to_3d GLBs are missing; full stage-1 pilot remains incomplete.']}
    try:
        assert_metrics_idle()
        import torch
        torch.set_num_threads(1)
        from .image_consistency import Dino
        dino = Dino(cache=str(OUTPUTS / '_cache/huggingface'))
        features = dino.encode([reference, reference, negative], batch_size=1)
        controls.update(self_dino=float(features[0] @ features[1]),
                        negative_reference_dino=float(features[0] @ features[2]),
                        reference_path=str(reference), negative_reference_path=str(negative),
                        negative_matching_rule='G001_obj_001 vs G002_obj_001; both have role=character')
        controls['self_control_passed'] = abs(controls['self_dino'] - 1) < 1e-5
        controls['reference_contrast_gap'] = controls['self_dino'] - controls['negative_reference_dino']
        dump(out / 'models.json', {'dino': dino.info()})
    except Exception as exc:
        from .resources import MetricsDeferred
        if isinstance(exc, MetricsDeferred):
            raise
        controls['notes'].append(f'DINO controls unavailable: {type(exc).__name__}: {exc}')
    try:
        assert_metrics_idle()
        from PIL import Image
        from .style import palette_metric
        palette = style_context(game)['palette_hex']
        if not palette:
            raise ValueError('No W06 hex palette')
        result = palette_metric([Image.new('RGBA', (32, 32), palette[0])], palette)
        controls['palette_control'] = {'hex': palette[0], **result}
        controls['palette_control_passed'] = result['weighted_mean_deltaE2000'] < 1e-6 and result['pixel_fraction_deltaE_lt10'] == 1
    except Exception as exc:
        from .resources import MetricsDeferred
        if isinstance(exc, MetricsDeferred):
            raise
        controls['notes'].append(f'Palette control unavailable: {type(exc).__name__}: {exc}')
    dump(out / 'controls_pending.json', controls)
    selected = next((p for p in source_files if p.parent.name == 'meshy' and p.parent.parent.name == 'G001_obj_005'), None)
    if selected:
        evidence, views = audit_evidence(selected)
        controls['text_sol_evidence_check'] = evidence
        from PIL import Image, ImageDraw
        sheet = Image.new('RGB', (960, 2 * 340), '#20242a')
        for i, v in enumerate(views):
            with Image.open(v['judge_path']) as im:
                im = im.convert('RGB'); im.thumbnail((320, 340))
                sheet.paste(im, ((i % 3) * 320, (i // 3) * 340))
        sheet.save(out / 'text_asset_evidence_contact_sheet.png')
    else:
        controls['text_sol_evidence_check'] = None
    dump(out / 'pilot_acceptance.json', controls)
    inv = inventory()
    dump(out / 'inventory.json', inv)
    from .run import environment_versions
    dump(out / 'environment.json', environment_versions())
    # Distinguish source model invocations from calls made by this audit (zero).
    calls = [p for p in source_run.glob('assets/**/model_calls/*/invocation.json') if read(p).get('command')]
    accepted = list(source_run.glob('assets/**/model_calls/*/accepted_response.json'))
    meta = {'status': 'prior_scores_reused_controls_attempted', 'mode': 'audit', 'scope': 'obj',
            'no_sol': True, 'api_calls': 0, 'source_sol_invocation_records': len(calls),
            'source_accepted_judgments': len(accepted), 'source_run': str(source_run),
            'elapsed_seconds': time.monotonic() - start, 'complete_pilot_passed': False,
            'notes': ['No new sol call; original score/model responses left unchanged.',
                      'Historical source pilot_summary incorrectly says no API calls; source invocation files show sol calls. This audit does not rewrite that history.']}
    from .report import write_reports
    write_reports(out, rows, inv, meta, [])
    lines = ['# G001 评分链路及对照测试', '',
             f'- 历史评分来源：`{source_run}`；本次不重新打分、不调用sol。',
             f'- 记录{len(rows)}条，已交付{sum(r["delivered"] for r in rows)}条；缺失资产不替换。',
             f'- 历史sol：{len(calls)}份CLI invocation、{len(accepted)}份accepted判词；并非无sol运行。',
             f'- 参考图与自身DINO cosine：{controls["self_dino"]}。',
             f'- 与G002同role参考图DINO cosine：{controls["negative_reference_dino"]}；注意这不是生成资产负对照。',
             f'- 纯色hex ΔE控制：{controls["palette_control"]}。',
             f'- text资产证据结构检查：{controls["text_sol_evidence_check"]}。',
             '- 完整试点仍未通过：image任务交付缺失、生成资产负对照尚未验证；不扩到全量。',
             f'- 本次耗时：{meta["elapsed_seconds"]:.2f}s。']
    (out / 'pilot_summary.md').write_text('\n'.join(lines) + '\n')
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run', required=True, type=Path)
    p.add_argument('--out', type=Path)
    args = p.parse_args()
    print(run(args.source_run, args.out))

if __name__ == '__main__':
    main()
