"""Add scene-reference similarity to an existing small CG pilot, without re-judging.

The source run, media, frames, and task references are read-only. Results go to a
new asset_eval run directory. This diagnostic is not folded into the three
scoring columns or confused with character-reference similarity.
"""
from __future__ import annotations
from .common import resolve_input
import argparse
import csv
from datetime import datetime
from pathlib import Path
from .common import OUTPUTS, SAMPLES, BENCH, dump, read, sha, validate_out, check_environment
from .inventory import tasks
from .resources import low_priority, assert_metrics_idle


def score_source(source_run: Path, out: Path | None = None) -> Path:
    check_environment(); policy = low_priority(); state = assert_metrics_idle()
    source_run = Path(source_run).resolve()
    if not source_run.is_relative_to(OUTPUTS.resolve()) or source_run == OUTPUTS.resolve() or not source_run.is_dir():
        raise ValueError('Source must be an existing asset_eval run')
    out = validate_out(out or OUTPUTS / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_G001_scene_similarity'))
    if any(out.iterdir()):
        raise ValueError('Output must be empty; source runs are never overwritten')
    rows = []
    game = next(p for p in SAMPLES.glob('G001_*') if p.is_dir())
    scene_tasks = [t for t in tasks(game, 'scene') if t.get('image_path')]
    if len(scene_tasks) != 1:
        raise ValueError(f'Expected exactly one explicitly linked G001 scene reference, found {len(scene_tasks)}')
    scene_task = scene_tasks[0]
    reference = resolve_input(scene_task['image_path'])
    if not reference.is_relative_to(SAMPLES.resolve()) or not reference.is_file():
        raise ValueError('Scene reference missing/outside test_samples')
    # Provider identifiers may contain slashes (e.g.
    # ``minimax-h3/text-to-video``), so glob's single ``*`` misses the
    # nested score.json. Walk the task subtree, then validate its path.
    task_root = source_run / 'assets' / game.name / 'G001_cg_001'
    candidates = sorted(task_root.rglob('score.json')) if task_root.is_dir() else []
    if not candidates:
        raise ValueError('No G001_cg_001 scores in source run')
    sources = []
    for score_path in candidates:
        score = read(score_path); provider = score['provider']
        asset = Path(score['asset_path']).resolve()
        if not asset.is_file() or sha(asset) != score.get('asset_sha256'):
            raise ValueError(f'Media missing or hash mismatch: {asset}')
        manifest_path = score_path.parent / 'evidence_manifest.json'
        manifest = read(manifest_path)
        frames = manifest.get('frames', [])
        if len(frames) != 16:
            raise ValueError(f'Expected 16 source frames, found {len(frames)}: {manifest_path}')
        for frame in frames:
            path = Path(frame['path']).resolve()
            if not path.is_relative_to(source_run) or not path.is_file() or sha(path) != frame['sha256']:
                raise ValueError(f'Frame missing, outside source run, or hash mismatch: {path}')
        sources.append((score, score_path, frames))
    assert_metrics_idle()
    import torch
    torch.set_num_threads(1)
    from .image_consistency import Dino
    dino = Dino(cache=str(OUTPUTS / '_cache/huggingface'))
    reference_vector = dino.encode([str(reference)], batch_size=1)[0]
    for score, score_path, frames in sources:
        assert_metrics_idle()
        vectors = dino.encode([f['path'] for f in frames], batch_size=2)
        similarities = vectors @ reference_vector
        best = int(similarities.argmax())
        result = {
            'schema_version': 'asset_eval/scene_similarity/1.0',
            'game': score['game'], 'task_id': score['task_id'], 'provider': score['provider'],
            'source_run': str(source_run), 'source_score': str(score_path),
            'source_score_sha256': sha(score_path), 'media_path': str(Path(score['asset_path']).resolve()),
            'media_sha256': score['asset_sha256'], 'reference_task_id': scene_task['task_id'],
            'reference_path': str(reference), 'reference_sha256': sha(reference),
            'method': 'facebook/dinov2-base last_hidden_state CLS; L2 normalized; cosine for each of 16 uniformly sampled frames; full-frame comparison includes camera/background',
            'mean_cosine': float(similarities.mean()),
            'per_frame': {f['id']: float(value) for f, value in zip(frames, similarities)},
            'best_frame': frames[best]['id'], 'best_cosine': float(similarities[best]),
            'frames_compared': len(frames), 'character_similarity_is_separate': True,
            'not_a_three_column_score': True,
        }
        dest = out / 'assets' / score['game'] / score['task_id'] / score['provider']
        dump(dest / 'scene_similarity.json', result)
        rows.append(result)
    dump(out / 'model.json', dino.info())
    with (out / 'scene_similarity.csv').open('w', newline='') as f:
        fields = ['game', 'task_id', 'provider', 'scene_reference_task', 'frames_compared', 'mean_cosine', 'best_frame', 'best_cosine', 'media_sha256', 'reference_sha256']
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for r in rows:
            writer.writerow({'game': r['game'], 'task_id': r['task_id'], 'provider': r['provider'],
                'scene_reference_task': r['reference_task_id'], 'frames_compared': r['frames_compared'],
                'mean_cosine': r['mean_cosine'], 'best_frame': r['best_frame'], 'best_cosine': r['best_cosine'],
                'media_sha256': r['media_sha256'], 'reference_sha256': r['reference_sha256']})
    body = ['# G001 CG 场景相似度补充指标', '',
        '此项为独立的 DINOv2 场景参考相似度诊断，不合并进 rubric 输入符合度、角色一致性或质量指数。',
        '使用任务显式链接的唯一场景参考图；每段视频 16 张均匀抽帧逐帧比较，显示均值、最佳帧和最佳余弦。全帧含摄影机/背景影响。', '',
        '|任务|Provider|场景参考|帧数|平均DINO余弦|最佳帧|最佳余弦|', '|---|---|---|---:|---:|---|---:|']
    for r in rows:
        body.append(f"|{r['task_id']}|{r['provider']}|{r['reference_task_id']}|{r['frames_compared']}|{r['mean_cosine']:.6f}|{r['best_frame']}|{r['best_cosine']:.6f}|")
    body += ['', f"- 参考图：`{reference}`", '- 匹配规则：G001 的 scene_tasks.jsonl 中唯一带 image_path 的任务，非按文件名或内容猜测。',
        '- 比较值是图文/全帧视觉余弦相似度，不是概率，不设置通过阈值；不同视角、构图会影响结果。',
        '- 原始媒体、抽帧及历史 sol 判词均未改写或重跑。',
        f"- 运行前资源检查：`{state}`；nice={policy['nice']}、线程上限1不是零干扰保证。"]
    (out / 'report.md').write_text('\n'.join(body) + '\n')
    dump(out / 'run.json', {'status': 'scene_similarity_complete', 'source_run': str(source_run),
        'records': len(rows), 'sol_calls': 0, 'process_snapshot_before': state, 'resource_policy': policy,
        'reference_path': str(reference), 'method': '16-frame DINOv2 CLS cosine; independent diagnostic, not a three-column score'})
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-run', type=Path, required=True)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    print(score_source(args.source_run, args.out))


if __name__ == '__main__':
    main()
