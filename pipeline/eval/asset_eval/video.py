"""Stage-3 media helpers. Full judging intentionally gated behind stage-1/2.

No video evaluation has been executed or validated merely by importing this file.
"""
from __future__ import annotations
from pathlib import Path
import json
from .common import tool, dump


def probe_video(path):
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    d = json.loads(tool(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', path]).stdout)
    v = next(s for s in d['streams'] if s['codec_type'] == 'video')
    a, b = map(int, v.get('avg_frame_rate', '0/1').split('/'))
    return {'width': v['width'], 'height': v['height'], 'fps': a / b if b else None,
            'duration_sec': float(v.get('duration', d['format']['duration'])), 'raw': d}


def sample_frames(path, out, count=16):
    """Uniform 16 frames including true first frame (no midpoint substitution)."""
    from .common import validate_out
    from .resources import assert_metrics_idle
    if not 2 <= count <= 16:
        raise ValueError('Small pilot supports 2..16 frames')
    out = validate_out(out)
    info = probe_video(path)
    last = max(0., info['duration_sec'] - 1 / (info['fps'] or 25))
    frames = []
    for i in range(count):
        assert_metrics_idle()
        t = last * i / (count - 1)
        p = out / f'F{i + 1:02d}.png'
        tool(['ffmpeg', '-nostdin', '-v', 'error', '-y', '-threads', '1', '-ss', f'{t:.6f}', '-i', path,
              '-filter_threads', '1', '-threads', '1', '-frames:v', '1', '-vf', 'scale=960:960:force_original_aspect_ratio=decrease', p])
        if not p.exists():
            raise ValueError(f'Frame decode missing at {t}')
        frames.append({'id': f'F{i + 1:02d}', 'timestamp_sec': float(t), 'path': str(p.resolve())})
    dump(out / 'manifest.json', {'probe': info, 'frames': frames})
    return info, frames


def character_schema(frame_ids, reference_ids):
    from .rubric_judge import obj, evidence_schema
    bbox = {'type': 'array', 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'minItems': 4, 'maxItems': 4}
    return obj({'verdict': {'type': 'string', 'enum': ['YES', 'NO', 'UNVERIFIED']},
                'reference_id': {'type': ['string', 'null'], 'enum': reference_ids + [None]},
                'detections': {'type': 'array', 'items': obj({'frame_id': {'type': 'string', 'enum': frame_ids},
                    'bbox_xyxy_normalized': bbox, 'region_description': {'type': 'string'}})},
                'evidence_frames': evidence_schema(frame_ids), 'reason': {'type': 'string'}})


def validated_crop(frame, bbox, out):
    from .common import validate_out
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    out = Path(out)
    validate_out(out.parent)
    from PIL import Image
    x1, y1, x2, y2 = bbox
    if not 0 <= x1 < x2 <= 1 or not 0 <= y1 < y2 <= 1:
        raise ValueError('Invalid model bounding box; never repaired')
    im = Image.open(frame)
    bounds = (round(x1 * im.width), round(y1 * im.height), round(x2 * im.width), round(y2 * im.height))
    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
        raise ValueError('Empty model crop')
    im.crop(bounds).save(out)
    return out


STAGE_STATUS = 'G001 small-sample implementation; full expansion and full-stage acceptance disabled'


def labelled_frames(frames, out):
    """Attach stable IDs for sol; metric images remain the original frames."""
    from .common import validate_out, sha
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    from PIL import Image, ImageDraw
    out = validate_out(out)
    result = []
    for frame in frames:
        assert_metrics_idle()
        im = Image.open(frame['path']).convert('RGB')
        label = Image.new('RGB', (im.width, im.height + 32), '#20242a')
        label.paste(im, (0, 32))
        ImageDraw.Draw(label).text((10, 8), f"{frame['id']} | t={frame['timestamp_sec']:.3f}s", fill='white')
        dest = out / (frame['id'] + '_labelled.png'); label.save(dest)
        result.append(dict(frame, judge_path=str(dest), sha256=sha(frame['path'])))
    return result


def judge_input(root, task, frames, rubric=None):
    from .rubric_judge import invoke, obj, evidence_schema
    ids = [f['id'] for f in frames]
    verdict = obj({'verdict': {'type': 'string', 'enum': ['PASS', 'FAIL', 'UNVERIFIED']},
                   'evidence_frames': evidence_schema(ids), 'reason': {'type': 'string', 'minLength': 1}})
    dimensions = rubric.get('dimensions', []) if rubric else []
    requirements = next((d for d in dimensions if d['id'] == 'requirement_compliance'), None)
    if rubric is not None and not requirements:
        return {'score': None, 'failure_label': 'rubric_dimension_missing', 'model_output': None,
                'notes': ['Existing video rubric has no requirement_compliance dimension; no prompt-only fallback.']}
    if requirements:
        schema = obj({'checks': obj({c['id']: verdict for c in requirements['checks']}),
                      'limitations': {'type': 'array', 'items': {'type': 'string'}}})
        instruction = ('严格逐条判定requirement_compliance的每个check，以原check ID为键。'
                       '每个check的全部目标满足为PASS，至少一个目标被可见证据否定为FAIL，证据不足为UNVERIFIED。'
                       '不使用PARTIAL，不评G/Q维度，不将游戏风格或质量混入输入分。')
    else:
        schema = obj({'checks': {'type': 'array', 'minItems': 1, 'items': obj({
            'prompt_quote': {'type': 'string', 'minLength': 1}, **verdict['properties']})},
            'limitations': {'type': 'array', 'items': {'type': 'string'}}})
        instruction = ('把prompt中每条独立要求逐项判定，prompt_quote必须是prompt的连续原文，'
                       '不能连接多段或自行改写，不添加prompt没有的要求。')
    prompt = ('评估真实游戏CG与输入要求的一致性。输入为16张按时间均匀抽取的真实视频帧，编号在顶部。'
              '每项引用真实帧编号并说明可见证据；静帧不能证明音轨、交互、采样间的完整动作或精确时序，'
              '不可观察应UNVERIFIED，不能凭正常画面想象事件。' + instruction
              + '\n原任务：' + json.dumps(task, ensure_ascii=False)
              + '\n原始rubric：' + json.dumps(rubric, ensure_ascii=False)
              + '\n帧顺序：' + json.dumps(ids))
    result, error = invoke(root, 'judge_video_input_v2', prompt, schema, [f['judge_path'] for f in frames])
    if result is None:
        return {'score': None, 'failure_label': error.split(':')[0], 'notes': [error], 'model_output': None}
    if requirements:
        checks = list(result['checks'].values())
    else:
        checks = result['checks']; quotes = [c['prompt_quote'] for c in checks]
        if len(set(quotes)) != len(quotes) or any(q not in task.get('prompt', '') for q in quotes):
            return {'score': None, 'failure_label': 'sol_invalid_prompt_quotation', 'model_output': result,
                    'notes': ['Quote absent from prompt or duplicate check; no code repair.']}
    counts = {v: sum(c['verdict'] == v for c in checks) for v in ('PASS', 'FAIL', 'UNVERIFIED')}
    n = counts['PASS'] + counts['FAIL']
    return {'score': counts['PASS'] / n if n else None, 'counts': counts,
            'protocol': 'video_input/v2_fixed_rubric_ids', 'model_output': result, 'failure_label': None,
            'notes': result['limitations'], 'formula': 'requirement_compliance PASS/(PASS+FAIL); UNVERIFIED excluded; zero denominator -> null'}


def judge_character(root, task, frames, references, context):
    """Identity is selected by sol against explicit task-linked references."""
    from .rubric_judge import invoke
    from .resources import assert_metrics_idle
    from .common import validate_out
    assert_metrics_idle()
    from PIL import Image, ImageDraw
    ids = [f['id'] for f in frames]; refs = {r['task_id']: r for r in references}
    if not refs:
        raise ValueError('No explicit game character references; stop video pilot, never infer identity')
    folder = validate_out(root / 'character_references')
    images = [f['judge_path'] for f in frames]
    for ident, r in refs.items():
        im = Image.open(r['path']).convert('RGB'); im.thumbnail((768, 768))
        labelled = Image.new('RGB', (im.width, im.height + 32), '#20242a'); labelled.paste(im, (0, 32))
        ImageDraw.Draw(labelled).text((10, 8), ident + ' | reference', fill='white')
        p = folder / (ident + '.png'); labelled.save(p); images.append(str(p))
    prompt = ('评估真实视频主角是否与游戏输入角色参考图为同一形象。先看16帧再看带reference标签的角色图。'
              '在实际出现的角色中选择一个主要角色及最相关reference_id，不能按文件名猜角色。'
              '只框同一个主体；每个可见帧最多一个bbox，x1,y1,x2,y2均为0..1，坐标相对原视频画面，'
              '不含顶部32像素标签。尽量逐帧给出，遮挡/未出现/太小不可辨认的帧不输出框。'
              'verdict YES=可确认同一形象，NO=可见外观明确不匹配，UNVERIFIED=不能判断。'
              '找不到可靠对应时reference_id=null、detections=[]；不能凭文字描述补框。'
              '理由引用帧编号，比较服装、体型、轮廓和面部/头部。\n任务：'
              + json.dumps(task, ensure_ascii=False) + '\n角色映射：' + json.dumps(references, ensure_ascii=False)
              + '\n美术方向原文：' + context['art_direction_verbatim'] + '\n帧顺序：' + json.dumps(ids))
    result, error = invoke(root, 'judge_video_character', prompt, character_schema(ids, list(refs)), images)
    if result is None:
        return {'score': None, 'failure_label': error.split(':')[0], 'notes': [error], 'model_output': None}
    detections = result['detections']; unique = {d['frame_id'] for d in detections}
    if (len(unique) != len(detections) or (detections and result['reference_id'] is None)
            or (result['verdict'] != 'UNVERIFIED' and (not detections or result['reference_id'] is None))):
        return {'score': None, 'failure_label': 'sol_semantic_schema_failure', 'model_output': result,
                'notes': ['Duplicate frame or detections without reference; no repair of model output.']}
    lookup = {f['id']: f for f in frames}; crops = []; errors = []
    for d in detections:
        try:
            p = validated_crop(lookup[d['frame_id']]['path'], d['bbox_xyxy_normalized'], folder / (d['frame_id'] + '_crop.png'))
            crops.append({'id': d['frame_id'], 'path': str(p), 'bbox': d['bbox_xyxy_normalized']})
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        return {'score': None, 'failure_label': 'sol_invalid_bbox', 'model_output': result,
                'notes': errors, 'crops': [], 'reference': None}
    return {'score': None, 'failure_label': None, 'model_output': result, 'crops': crops,
            'reference': refs.get(result['reference_id']), 'notes': ['Identity crops are sol rectangles, not segmentation masks.']}


def specification(info, task):
    """Preset continuous duration tolerance; do not invent unspecified targets."""
    res = str(task.get('resolution', '')).split('x')
    resolution = float((info['width'], info['height']) == tuple(map(int, res))) if len(res) == 2 and all(x.isdigit() for x in res) else None
    fps = float(abs(info['fps'] - float(task['fps'])) <= .05) if task.get('fps') is not None and info.get('fps') is not None else None
    target = task.get('duration_sec')
    duration = max(0., 1 - abs(info['duration_sec'] - target) / target) if isinstance(target, (float, int)) and target > 0 else None
    values = [resolution, fps, duration]
    return {'score': sum(values) / 3 if all(v is not None for v in values) else None,
            'resolution_score': resolution, 'fps_score': fps, 'duration_score': duration,
            'expected': {k: task.get(k) for k in ('resolution', 'fps', 'duration_sec')},
            'formula': 'S=mean(exact_resolution_match, abs(fps-target)<=0.05, max(0,1-abs(duration-target)/target)); any missing -> null'}


def temporal_flicker(frames):
    """Conservative static-pixel proxy on uniform samples, not optical flow."""
    from .resources import assert_metrics_idle
    assert_metrics_idle()
    import numpy as np
    from PIL import Image
    arrays = [np.asarray(Image.open(f['path']).convert('RGB').resize((256, 144)), dtype=np.float32) / 255 for f in frames]
    x = np.stack(arrays); diff = np.abs(np.diff(x, axis=0)).mean(axis=3)
    # The time median tolerates isolated flashes; moving camera often yields no mask.
    mask = np.median(diff, axis=0) < .02
    coverage = float(mask.mean())
    value = float(np.abs(np.diff(x, n=2, axis=0)).mean(axis=3)[:, mask].mean() / 2) if coverage >= .05 else None
    return {'mean_second_difference': value, 'static_pixel_fraction': coverage,
            'normalized_quality': max(0., 1 - value / .10) if value is not None else None,
            'method': '256x144 RGB, median consecutive L1<0.02 static pixels; mean abs second temporal difference/2; <5% static -> null',
            'notes': ['Sparse uniform-frame proxy only; no camera compensation and not a full-frame-rate flicker benchmark.']}


VIDEO_QUALITY_FORMULA = ('Qv=100*(0.35*C+0.20*F+0.30*M+0.15*S); '
    'C=clip(mean(subject adjacent cosine, subject vs F01 cosine),0,1), all 16 subject crops required; '
    'F=max(0,1-static_second_difference/0.10); M=MUSIQ_mean/100; S=spec compliance; any missing -> null')


def quality_index(subject, flicker, musiq, spec):
    values = [subject, flicker, musiq / 100 if musiq is not None and 0 <= musiq <= 100 else None, spec]
    if any(v is None for v in values):
        return None
    # Only the index maps cosine to [0,1]; raw cosine is never clipped/replaced.
    c, f, m, s = values
    return 100 * (.35 * max(0., min(1., c)) + .20 * f + .30 * m + .15 * s)
