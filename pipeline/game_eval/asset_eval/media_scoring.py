"""Explicitly bounded G001 CG/SFX scoring pilot, separate from full expansion."""
from __future__ import annotations
from .common import resolve_input
import csv
import gc
import json
import time
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict
from .common import OUTPUTS, SAMPLES, ASSETS, BENCH, dump, read, sha, validate_out, check_environment
from .inventory import tasks, CLOSED, character_references, style_context, rubric_path
from .resources import assert_metrics_idle, MetricsDeferred, low_priority

# G001 media inventory. Only existing generated files with closed-provider
# provenance are scored; no assets are downloaded or substituted.
def discover_selections(game, scopes=('video', 'audio')):
    found = []
    from .inventory import tasks as load_tasks
    for scope in scopes:
        kind = 'video' if scope in ('video', 'cg') else scope
        folder = 'cg_video' if kind == 'video' else 'audio'
        for task in load_tasks(game, kind):
            base = ASSETS / game.name / 'assets' / folder / task['task_id']
            names = ('video.mp4', 'video_seedance.mp4') if kind == 'video' else ('audio.wav',)
            for filename in names:
                src = base / filename
                if not src.is_file():
                    continue
                evidence = provider_from_meta(base, kind, filename)
                provider = evidence['declared_provider']
                if provider in CLOSED:
                    found.append((kind, task['task_id'], provider, filename))
    return found


def fail(row, label, reason):
    row['failures'].append({'label': label, 'reason': str(reason)})
    row['failure_label'] = ';'.join(dict.fromkeys(x['label'] for x in row['failures']))
    row['notes'].append(str(reason))


def release_models():
    import sys
    gc.collect()
    torch = sys.modules.get('torch')
    if torch is not None and torch.backends.mps.is_available():
        torch.mps.empty_cache()


def provider_from_meta(base, scope, filename):
    path = base / ('meta_seedance.json' if filename == 'video_seedance.mp4' else 'meta.json')
    meta = read(path) if path.is_file() else {}
    if scope == 'video':
        provider = meta.get('provider', meta.get('model'))
    else:
        methods = {v.get('method') for v in meta.get('variants', [])}
        family = meta.get('generation', {}).get('method_family')
        provider = next(iter(methods)) if len(methods) == 1 else ('elevenlabs/sound-effects-v2' if not methods and family == 'elevenlabs_sfx_v2' else None)
    return {'metadata': str(path), 'declared_provider': provider,
            'rule': 'video provider/model, unique audio variant method, or explicit elevenlabs_sfx_v2 family'}


def _record_judge_error(row, result):
    if result.get('failure_label'):
        fail(row, result['failure_label'], ' | '.join(result.get('notes', [])))


def reuse_character(source_run, row, frames, dest):
    """Reuse only a sealed, matching judgment; crop raw model boxes anew."""
    if source_run is None:
        return None
    source = Path(source_run).resolve()
    if not source.is_relative_to(OUTPUTS.resolve()) or source == OUTPUTS.resolve() or not source.is_dir():
        raise ValueError('Reuse source must be an existing asset_eval run')
    base = source / 'assets' / row['game'] / row['task_id'] / row['provider']
    score_path = base / 'score.json'
    if not score_path.is_file():
        return None
    prior = read(score_path)
    result = prior['columns']['style'].get('metrics', {}).get('identity')
    if not result or result.get('failure_label') or not result.get('model_output'):
        return None
    if prior.get('asset_sha256') != row.get('asset_sha256'):
        raise ValueError('Reuse source media SHA differs; refuse cached judgment')
    call = base / 'model_calls/judge_video_character'
    accepted = read(call / 'accepted_response.json')
    response = (call / accepted['path']).resolve()
    if not response.is_relative_to(call.resolve()) or sha(response) != accepted['sha256']:
        raise ValueError('Prior accepted response hash mismatch')
    if read(response) != result['model_output']:
        raise ValueError('Prior metric/model response mismatch')
    manifest = read(base / 'evidence_manifest.json')
    old = {f['id']: f['sha256'] for f in manifest['frames']}
    if old != {f['id']: f['sha256'] for f in frames}:
        raise ValueError('Decoded frame hashes differ; do not reuse model observations')
    from .video import validated_crop
    result = read(score_path)['columns']['style']['metrics']['identity']
    crops = []; mapping = {f['id']: f for f in frames}
    folder = validate_out(dest / 'character_references')
    for d in result['model_output']['detections']:
        path = validated_crop(mapping[d['frame_id']]['path'], d['bbox_xyxy_normalized'], folder / (d['frame_id'] + '_crop.png'))
        crops.append({'id': d['frame_id'], 'path': str(path), 'bbox': d['bbox_xyxy_normalized']})
    result['crops'] = crops
    result['notes'].append('Reused sealed prior identity model output; frame/media SHA verified, raw boxes recropped; no new sol identity call.')
    dump(dest / 'model_calls/judge_video_character_reused/provenance.json', {
        'source_score': str(score_path), 'source_score_sha256': sha(score_path),
        'accepted_response': str(response), 'accepted_response_sha256': sha(response),
        'source_prompt': str(call / 'prompt.txt'), 'source_invocation': str(call / 'invocation.json'),
        'frame_hashes_verified': True, 'new_api_invocation': False})
    return result


def score_video(row, task, game, dest, no_sol, source_run=None):
    from . import video
    refs = character_references(game)
    if not refs:
        raise ValueError('Character reference mapping missing; stop pilot rather than guess')
    row['character_references'] = refs
    info, frames = video.sample_frames(row['asset_path'], dest / 'frames', 16)
    frames = video.labelled_frames(frames, dest / 'labelled_frames')
    dump(dest / 'evidence_manifest.json', {'frames': frames, 'character_references': refs})
    quality = row['columns']['quality']['metrics']
    quality['probe'] = info; quality['specification'] = video.specification(info, task)
    source_rubric = rubric_path(game, task, 'video')
    mode = task.get('mode')
    if mode == 'text_to_video' and not no_sol:
        result = video.judge_input(dest, task, frames, read(source_rubric) if source_rubric else None)
        row['columns']['input'].update(score=result['score'], metrics=result)
        _record_judge_error(row, result)
    identity = None
    if not no_sol:
        identity = reuse_character(source_run, row, frames, dest)
        if identity is None:
            identity = video.judge_character(dest, task, frames, refs, style_context(game))
        row['columns']['style']['metrics']['identity'] = identity
        _record_judge_error(row, identity)
    else:
        fail(row, 'sol_disabled', 'No sol prompt or character judgment requested; no inferred boxes or model verdicts.')
    dump(dest / 'score.json', row)
    assert_metrics_idle()
    from .image_consistency import Dino
    import torch
    import numpy as np
    torch.set_num_threads(1)
    dino = None
    try:
        dino = Dino(cache=str(OUTPUTS / '_cache/huggingface'))
        full = dino.encode([f['path'] for f in frames], batch_size=2)
        # Scene input is explicitly linked from the game's scene task; never
        # infer the reference from a filename or CG prompt.
        scene_tasks = tasks(game, 'scene')
        scene_refs = [t for t in scene_tasks if t.get('image_path')]
        if len(scene_refs) == 1:
            scene_path = resolve_input(scene_refs[0]['image_path'])
            if not scene_path.is_relative_to(SAMPLES.resolve()) or not scene_path.is_file():
                raise ValueError('Scene reference missing/outside test_samples')
            scene_feat = dino.encode([str(scene_path)], batch_size=1)[0]
            sims = full @ scene_feat
            best = int(np.argmax(sims))
            row['columns']['style']['metrics']['scene_dino_similarity'] = {
                'reference_path': str(scene_path), 'reference_task_id': scene_refs[0]['task_id'],
                'mean_cosine': float(sims.mean()), 'per_frame': {f['id']: float(v) for f, v in zip(frames, sims)},
                'best_frame': frames[best]['id'], 'best_cosine': float(sims[best]),
                'frames_compared': len(frames),
                'note': 'Whole-frame DINO CLS cosine to the explicitly linked game scene reference; camera/background included. Separate diagnostic, not merged into character score or style column.'}
        elif len(scene_refs) == 0:
            row['columns']['style']['metrics']['scene_dino_similarity'] = {
                'mean_cosine': None, 'note': 'No scene task with an explicit image_path; no reference guessed.'}
        else:
            row['columns']['style']['metrics']['scene_dino_similarity'] = {
                'mean_cosine': None, 'note': f'{len(scene_refs)} candidate scene references; ambiguous, no automatic selection.'}
        quality['global_frame_dino_diagnostic'] = {
            'adjacent_cosine': float(np.sum(full[:-1] * full[1:], axis=1).mean()),
            'vs_first_cosine': float((full[1:] @ full[0]).mean()),
            'note': 'Whole-frame diagnostic includes camera/background; does not substitute for subject consistency.'}
        if mode == 'image_to_video':
            path = resolve_input(task['image_path'])
            if not path.is_relative_to(SAMPLES.resolve()) or not path.is_file():
                raise ValueError('Image-video reference missing/outside samples')
            feat = dino.encode([str(path), frames[0]['path']], batch_size=2)
            row['columns']['input'].update(score=float(feat[0] @ feat[1]), metrics={
                'dinov2_first_frame_cosine': float(feat[0] @ feat[1]), 'reference_path': str(path), 'frame': 'F01'})
        subject = {'score': None, 'adjacent_cosine': None, 'vs_first_cosine': None, 'observed_frames': 0, 'required_frames': 16}
        if identity and identity.get('crops') and identity.get('reference'):
            crops = identity['crops']
            feat = dino.encode([identity['reference']['path']] + [c['path'] for c in crops], batch_size=2)
            similarity = feat[1:] @ feat[0]
            row['columns']['style']['score'] = float(similarity.mean())
            row['columns']['style']['metrics']['character_dino'] = {
                'mean_cosine': float(similarity.mean()), 'per_frame': {c['id']: float(v) for c, v in zip(crops, similarity)},
                'reference': identity['reference'], 'crop_coverage': len(crops) / 16,
                'note': 'Mean over sol-detected visible subject crops, not best-match selection; bbox includes possible background.'}
            by_id = {c['id']: f for c, f in zip(crops, feat[1:])}
            adjacent = [float(by_id[a['id']] @ by_id[b['id']]) for a, b in zip(frames[:-1], frames[1:]) if a['id'] in by_id and b['id'] in by_id]
            first = [float(f @ by_id['F01']) for key, f in by_id.items() if key != 'F01'] if 'F01' in by_id else []
            subject.update(adjacent_cosine=float(np.mean(adjacent)) if adjacent else None,
                vs_first_cosine=float(np.mean(first)) if first else None,
                observed_frames=len(crops), adjacent_pairs=len(adjacent), first_frame_pairs=len(first))
            if len(crops) == 16 and adjacent and first:
                subject['score'] = (subject['adjacent_cosine'] + subject['vs_first_cosine']) / 2
        if subject['score'] is None:
            fail(row, 'subject_consistency_incomplete', 'All 16 reliable same-subject detections including F01 are required for video quality; partial crops are reported only.')
        quality['subject_consistency'] = subject
        dump(dest / 'dino_model.json', dino.info())
    except MetricsDeferred:
        raise
    except Exception as exc:
        fail(row, 'dino_metric_unavailable', exc)
    finally:
        del dino
        release_models()
    assert_metrics_idle()
    try:
        from .style import palette_metric
        from PIL import Image
        context = style_context(game)
        # JPEG/RGB frames and rectangular boxes do not supply foreground masks.
        row['columns']['style']['palette'] = {'weighted_mean_deltaE2000': None, 'pixel_fraction_deltaE_lt10': None,
            'notes': ['No reliable foreground segmentation masks; rectangular sol boxes are not masks.']}
        row['columns']['style']['metrics']['whole_frame_palette_diagnostic'] = palette_metric(
            [Image.open(f['path']).convert('RGB').resize((256, 144)) for f in frames], context['palette_hex'], all_pixels=True)
        row['notes'].append('Video foreground palette is null; 256x144 whole-frame palette is a separately labeled diagnostic.')
        quality['flicker'] = video.temporal_flicker(frames)
    except MetricsDeferred:
        raise
    except Exception as exc:
        fail(row, 'video_local_metric_unavailable', exc)
    assert_metrics_idle()
    from .quality import ImageQuality
    iqa = ImageQuality()
    scores = []
    try:
        for frame in frames:
            try:
                scores.append(iqa.score('musiq', frame['path']))
            except MetricsDeferred:
                raise
            except Exception as exc:
                scores.append(None); fail(row, 'musiq_frame_unavailable', str(frame['id']) + ': ' + str(exc))
        known = [v for v in scores if v is not None]
        mean = sum(known) / 16 if len(known) == 16 else None
        quality['musiq'] = {'per_frame': {f['id']: v for f, v in zip(frames, scores)}, 'mean': mean,
                            'known_frames': len(known), 'required_frames': 16, 'cpu_fallbacks': iqa.fallbacks}
        row['columns']['quality']['score'] = video.quality_index(quality.get('subject_consistency', {}).get('score'),
            quality.get('flicker', {}).get('normalized_quality'), mean, quality['specification']['score'])
        quality['formula'] = video.VIDEO_QUALITY_FORMULA
        if row['columns']['quality']['score'] is None:
            fail(row, 'quality_index_unavailable', 'Video quality requires complete subject, static-flicker, MUSIQ and specification components; no weight redistribution.')
    finally:
        del iqa
        release_models()


def score_audio(row, task, dest):
    from .audio import signal_metrics, waveform_48k, Clap
    row['columns']['quality']['metrics']['signal'] = signal_metrics(row['asset_path'])
    is_dialogue = task.get('audio_type') in ('dialogue', 'speech', '对话') or 'text' in task
    if is_dialogue:
        fail(row, 'dialogue_models_unavailable', 'ASR/emotion/ECAPA/perceptual speech quality not implemented/validated in this small SFX pilot; no SFX score applied.')
        return
    assert_metrics_idle()
    import torch
    torch.set_num_threads(1)
    clap = None
    try:
        clap = Clap(cache=str(OUTPUTS / '_cache/huggingface'))
        value = clap.similarity(waveform_48k(row['asset_path']), task['prompt'])
        row['columns']['input'].update(score=value, metrics={'clap_cosine': value, 'prompt': task['prompt'],
            'model': clap.info(), 'sampling_rate': 48000, 'channel_handling': 'ffmpeg mono downmix',
            'note': 'Official CLAP feature extraction/crop/padding; cosine not calibrated to a 0..100 score.'})
    except MetricsDeferred:
        raise
    except Exception as exc:
        fail(row, 'clap_metric_unavailable', exc)
    finally:
        del clap
        release_models()
    fail(row, 'audio_style_unverified', 'call_codex exposes text/images, no verified audio listening channel; textual sound prompt is not evidence of the actual sound. Style remains null.')
    fail(row, 'audio_perceptual_quality_unavailable', 'Audiobox/UTMOS/DNSMOS not run; LUFS/clipping alone cannot replace the requested perceptual quality index. Quality remains null.')


def run_pilot(out=None, *, scopes=('video', 'audio'), providers=None, no_sol=False, source_run=None):
    started = time.monotonic(); cpu = time.process_time()
    check_environment(); priority = low_priority(); state = assert_metrics_idle()
    from .run import environment_versions
    env = environment_versions()
    if env['version_mismatches']:
        raise RuntimeError('Pinned dependency mismatch: ' + '; '.join(env['version_mismatches']))
    game = next(p for p in SAMPLES.glob('G001_*') if p.is_dir())
    selections = [s for s in discover_selections(game, scopes) if (providers is None or s[2] in providers)]
    if not selections:
        raise ValueError('No supported small-pilot selection for these scopes/providers')
    if 'video' in scopes and not character_references(game):
        raise ValueError('No explicit game character references; stop before any evaluation')
    out = validate_out(out or OUTPUTS / (datetime.now().strftime('%Y%m%d_%H%M%S') + '_G001_media_scores'))
    if any(out.iterdir()):
        raise ValueError('Output directory must be empty; never overwrite results')
    dump(out / 'environment.json', env)
    code = {p.name: sha(p) for p in Path(__file__).parent.glob('*.py')}
    dump(out / 'implementation_sha256.json', code)
    rows = []
    for scope, tid, provider, filename in selections:
        task = next(t for t in tasks(game, scope) if t['task_id'] == tid)
        base = ASSETS / game.name / 'assets' / ('cg_video' if scope == 'video' else 'audio') / tid
        src = base / filename
        dest = out / 'assets' / game.name / tid / provider
        dest.mkdir(parents=True, exist_ok=True)
        row = {'schema_version': 'asset_eval/0.2', 'game': game.name, 'scope': scope, 'task_id': tid,
            'provider': provider, 'input_mode': task.get('mode', task.get('audio_type')), 'asset_path': str(src),
            'source_task': task, 'delivered': src.is_file(), 'provider_evidence': provider_from_meta(base, scope, filename),
            'columns': {k: {'score': None, 'metrics': {}} for k in ('input', 'style', 'quality')},
            'notes': [], 'failure_label': None, 'failures': []}
        t0 = time.monotonic()
        if not row['delivered']:
            fail(row, 'asset_missing', 'Expected pilot file missing; no alternative asset substituted.')
        elif row['provider_evidence']['declared_provider'] != provider or provider not in CLOSED:
            fail(row, 'provider_unverified_or_excluded', 'No matching closed provider identity; no scoring.')
        else:
            try:
                assert_metrics_idle()
                row['asset_sha256'] = sha(src)
                print(json.dumps({'event': 'asset_start', 'scope': scope, 'task': tid, 'provider': provider}), flush=True)
                if scope == 'video':
                    score_video(row, task, game, dest, no_sol, source_run=source_run)
                else:
                    score_audio(row, task, dest)
            except MetricsDeferred as exc:
                fail(row, 'metrics_deferred_whitebox', exc)
            except Exception as exc:
                fail(row, 'media_metric_exception', f'{type(exc).__name__}: {exc}')
        row['elapsed_seconds'] = time.monotonic() - t0
        dump(dest / 'score.json', row); rows.append(row)
        print(json.dumps({'event': 'asset_done', 'task': tid, 'provider': provider,
            'scores': {k: v['score'] for k, v in row['columns'].items()}, 'failure_label': row['failure_label']}), flush=True)
        write_reports(out, rows, {'status': 'running', 'elapsed_seconds': time.monotonic() - started})
    meta = {'status': 'small_pilot_complete', 'full_stage_accepted': False, 'no_sol': no_sol,
            'source_run': str(source_run) if source_run else None,
            'records': len(rows), 'elapsed_seconds': time.monotonic() - started, 'cpu_seconds': time.process_time() - cpu,
            'resource_policy': priority, 'process_snapshot_before': state}
    dump(out / 'run.json', meta); write_reports(out, rows, meta)
    return out


def write_reports(out, rows, meta):
    fields = ['game', 'task_id', 'provider', 'scope', 'input_score', 'style_score', 'character_dino_mean', 'scene_dino_mean', 'quality_score', 'failure_label', 'notes']
    with (out / 'scores.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for r in rows:
            writer.writerow(dict({k: r[k] for k in ('game', 'task_id', 'provider', 'scope')},
                **{k + '_score': r['columns'][k]['score'] if r['columns'][k]['score'] is not None else 'null' for k in ('input', 'style', 'quality')},
                character_dino_mean=(r['columns']['style']['metrics'].get('character_dino') or {}).get('mean_cosine', 'null'),
                scene_dino_mean=(r['columns']['style']['metrics'].get('scene_dino_similarity') or {}).get('mean_cosine', 'null'),
                failure_label=r['failure_label'], notes=' | '.join(r['notes'])))
    body = ['# G001 CG/音效小样本评分', '', f"状态：{meta['status']}；{len(rows)}条记录；耗时{meta['elapsed_seconds']:.2f}s。", '',
        '三列分别报告，不合并总分。video输入=prompt PASS率（image模式为首帧DINO）；video第二列主分=检测主体与选定角色参考图的平均DINO余弦。另列场景参考图逐帧DINO均值，仅作场景相似度诊断，不并入三列分数。',
        'audio第一列=CLAP余弦；未完成听音/感知质量时后两列为null。各列单位不同，不跨类型平均。', '',
        '|任务|provider|输入符合度|游戏形象一致|传统质量0–100|', '|---|---|---:|---:|---:|']
    for r in rows:
        body.append('| ' + ' | '.join([r['task_id'], r['provider']] + ['null' if r['columns'][k]['score'] is None else f"{r['columns'][k]['score']:.5f}" for k in ('input', 'style', 'quality')]) + ' |')
    groups = defaultdict(list)
    for r in rows:
        groups[(r['game'], r['provider'], r['scope'])].append(r)
    body += ['', '## 按游戏/provider汇总与覆盖率', '']
    for (game, provider, scope), group in groups.items():
        for column in ('input', 'style', 'quality'):
            known = [r['columns'][column]['score'] for r in group if r['columns'][column]['score'] is not None]
            body.append(f'- {game} / {provider} / {scope} / {column}：均值={sum(known)/len(known) if known else None}；有分{len(known)}/{len(group)}；null={len(group)-len(known)}。')
    body += ['', '## null与限制', '']
    body += [f'- {label}: {n}条。' for label, n in Counter(f['label'] for r in rows for f in r['failures']).items()]
    body += ['', '未扩全量；未改输入/白膜/旧评测/引擎适配器；未启动GUI引擎。nice和线程限制不是零影响保证。']
    (out / 'report.md').write_text('\n'.join(body) + '\n')
    from .video import VIDEO_QUALITY_FORMULA
    from .constants import VABENCH
    appendix = ['# 指标、来源与失败附录', '', VIDEO_QUALITY_FORMULA,
        '- 视频规格：分辨率完全一致、fps误差<=0.05、max(0,1-相对时长误差)三者均值；任一目标缺失则null。',
        '- static flicker是16张均匀帧的静态像素二阶差分代理，无相机补偿，不是逐帧VBench实现；静态像素少于5%时null。',
        '- 主体质量需要16帧都有同一主体可靠框（包括F01）；全帧DINO仅诊断，不冒充主体一致性。场景相似度另将全部抽帧与唯一明确scene task的image_path计算DINO CLS余弦均值、逐帧值和最佳帧；参考缺失或多候选均null，不猜测，不合并角色分。',
        '- 矩形裁剪不是前景掩码；视频前景色板两项为null。另报256x144全帧kmeans/ΔE诊断，不替换前景指标。',
        '- 音效CLAP：laion/clap-htsat-unfused，官方Transformers特征提取，48kHz单声道，输出归一化embedding余弦；模型版本见逐资产JSON。',
        '- 音频LUFS/削波/静音只记原始信号值；缺Audiobox/UTMOS/DNSMOS不编质量指数；call_codex无经验证听音通道，不凭prompt给真实音频打风格分。',
        '- 模型串行加载，DINO/pyiqa/CLAP不同时驻留；算子优先MPS、异常回退CPU；各资产/模型/批次前检查白膜/sol并暂缓。',
        '- VABench：' + VABENCH['alignment_status'], '', '## 游戏角色输入与规则', '']
    for r in rows:
        for ref in r.get('character_references', []):
            line = f"- {ref['task_id']}：`{ref['path']}`；{ref['matching_rule']}。"
            if line not in appendix:
                appendix.append(line)
    appendix += ['', '## 失败清单', '']
    for r in rows:
        for failure in r['failures']:
            appendix.append(f"- {r['task_id']} / {r['provider']} / {failure['label']}：{failure['reason']}")
    (out / 'appendix.md').write_text('\n'.join(appendix) + '\n')
