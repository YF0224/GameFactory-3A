"""Small, bounded, local-only media pilot; no sol or perceptual-model calls."""
from __future__ import annotations
import argparse, csv, time
from datetime import datetime
from pathlib import Path
from .common import OUTPUTS, SAMPLES, ASSETS, dump, read, validate_out, check_environment, sha
from .inventory import tasks, CLOSED
from .resources import process_snapshot, low_priority, assert_metrics_idle, MetricsDeferred
from .video import probe_video, sample_frames
from .audio import signal_metrics


def _task(game, scope, task_id):
    return next((t for t in tasks(game, scope) if t['task_id'] == task_id), None)


def run_pilot(out=None):
    start=time.monotonic(); check_environment(); low_priority()
    # Guard before ffmpeg/decoding work. This intentionally makes no sol calls.
    state=process_snapshot()
    if state['whitebox_batch'] or state['sol']:
        raise RuntimeError('whitebox batch/sol is active; media pilot deferred before decode')
    game=next(p for p in SAMPLES.glob('G001_*') if p.is_dir())
    out=validate_out(out or OUTPUTS/(datetime.now().strftime('%Y%m%d_%H%M%S')+'_G001_media_local_pilot'))
    if any(out.iterdir()):
        raise ValueError("Run directory must be empty; results are never overwritten")
    rows=[]
    # One sample per closed video generator, plus two closed audio samples.
    selections=[('video','G001_cg_001','minimax-h3/text-to-video','video.mp4'),
                ('video','G001_cg_001','bytedance/seedance-2','video_seedance.mp4'),
                ('audio','G001_sfx_001','elevenlabs/sound-effects-v2','audio.wav'),
                ('audio','G001_sfx_002','elevenlabs/sound-effects-v2','audio.wav')]
    for scope,tid,provider,filename in selections:
        t=_task(game,scope,tid)
        if t is None:
            raise ValueError(f'Frozen task missing: {tid}')
        assert_metrics_idle()
        row={'game':game.name,'task_id':tid,'provider':provider,'scope':scope,
             'columns':{'input':{'score':None,'metrics':{}},'style':{'score':None,'metrics':{}},
                        'quality':{'score':None,'metrics':{}}},'notes':[],'failure_label':None}
        base=ASSETS/game.name/'assets'/('cg_video' if scope=='video' else 'audio')/tid
        src=base/filename; row['asset_path']=str(src); row['delivered']=src.is_file()
        dest=out/'assets'/tid/provider; dest.mkdir(parents=True,exist_ok=True)
        row['source_task']=t
        meta_path=base/('meta_seedance.json' if filename=='video_seedance.mp4' else 'meta.json')
        meta=read(meta_path) if meta_path.is_file() else {}
        if scope=='video':
            actual_provider=meta.get('provider',meta.get('model'))
        else:
            methods={v.get('method') for v in meta.get('variants', [])}
            family=meta.get('generation',{}).get('method_family')
            actual_provider=next(iter(methods)) if len(methods)==1 else ('elevenlabs/sound-effects-v2' if not methods and family=='elevenlabs_sfx_v2' else None)
        row['provider_evidence']={'metadata':str(meta_path),'declared_provider':actual_provider,
            'rule':'video provider/model, unique audio variant method, or explicit elevenlabs_sfx_v2 family'}
        if actual_provider!=provider or actual_provider not in CLOSED:
            row['failure_label']='provider_unverified_or_excluded'
            row['notes'].append('No closed-provider identity established; no evaluation performed.')
        elif not row['delivered']:
            row.update(failure_label='asset_missing'); row['notes'].append('Expected media file missing; no score substituted.')
        elif scope=='video':
            try:
                info=probe_video(src)
                # Actual specification compliance, not a perceptual quality score.
                expected=t or {}; expected_res=expected.get('resolution','').split('x')
                spec={'resolution_match': (info['width'],info['height'])==tuple(map(int,expected_res)) if len(expected_res)==2 else None,
                      'fps_match': abs(info['fps']-float(expected['fps']))<0.05 if expected.get('fps') is not None and info.get('fps') is not None else None,
                      'duration_error_sec': abs(info['duration_sec']-float(expected['duration_sec'])) if expected.get('duration_sec') is not None else None}
                info['spec_compliance']=spec
                info['frames_sampled']=16
                _,frames=sample_frames(src,dest/'frames',16)
                info['frame_ids']=[x['id'] for x in frames]
                row['columns']['quality']['metrics']['specification']=info
                row['notes'] += ['16 uniform frames decoded. Sol prompt/character judgment, DINO, MUSIQ and temporal flicker are not run in local-only mode.',
                                 'No quality composite: requested perceptual components unavailable.']
                row['failure_label']='sol_deferred;perceptual_metrics_deferred'
            except MetricsDeferred:
                raise
            except Exception as e:
                row['failure_label']='video_probe_failed'; row['notes'].append(f'{type(e).__name__}: {e}')
        else:
            try:
                metrics=signal_metrics(src)
                row['columns']['quality']['metrics']['signal']=metrics
                row['notes'] += ['Local decode/LUFS/clipping/silence measured. CLAP, sol scene judgment and perceptual audio quality not run.',
                                 'No quality composite: requested perceptual components unavailable.']
                row['failure_label']='clap_deferred;sol_deferred;perceptual_metrics_deferred'
            except MetricsDeferred:
                raise
            except Exception as e:
                row['failure_label']='audio_probe_failed'; row['notes'].append(f'{type(e).__name__}: {e}')
        if row['delivered']:
            row['asset_sha256']=sha(src)
        row['input_mode']=t.get('mode',t.get('audio_type'))
        dump(dest/'score.json',row); rows.append(row)
    fields=['game','task_id','provider','scope','delivered','input_score','style_score','quality_score','failure_label','notes']
    with (out/'scores.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            w.writerow({'game':r['game'],'task_id':r['task_id'],'provider':r['provider'],'scope':r['scope'],
                'delivered':r['delivered'],'input_score':'null','style_score':'null','quality_score':'null',
                'failure_label':r['failure_label'],'notes':' | '.join(r['notes'])})
    summary=['# G001 视频/音频本地链路试点','',f'- 记录 {len(rows)}；交付 {sum(r["delivered"] for r in rows)}。',
      '- 本地实际测量：视频容器规格与16帧解码；音频LUFS、削波样本占比、静音样本占比。',
      '- 本地运行没有调用sol、CLAP、DINO、MUSIQ或音频感知模型；需要这些项的三列分数保持null。',
      '- 白膜/sol资源检查：开始前未检测到活动进程；nice=19/线程=1仅降低影响，不能保证零资源竞争。',
      f'- 用时 {time.monotonic()-start:.2f}s。']
    summary += ['', '| 任务 | provider | 规格/信号实测 |', '|---|---|---|']
    for r in rows:
        metrics=r['columns']['quality']['metrics']
        signal=metrics.get('signal')
        spec=metrics.get('specification')
        if signal:
            detail=f"LUFS={signal['integrated_lufs']}; clipping={signal['clipping_sample_fraction']:.6f}; silence={signal['silence_sample_fraction']:.6f}"
        elif spec:
            detail=f"{spec['width']}x{spec['height']}, {spec['fps']}fps, {spec['duration_sec']:.3f}s; frames={spec['frames_sampled']}"
        else:
            detail='null; '+str(r['failure_label'])
        summary.append(f"| {r['task_id']} | {r['provider']} | {detail} |")
    summary += ['', '## 三列覆盖率（每个游戏×provider）']
    for provider in sorted({r['provider'] for r in rows}):
        n=sum(r['provider']==provider for r in rows)
        summary.append(f'- {game.name} / {provider}：三列各0/{n}有分、{n}个null；未运行对应的感知/模型指标。')
    (out/'appendix.md').write_text(
        '# 本地链路方法\n\n不合并、不生成替代分。\n'
        '- LUFS：ffmpeg ebur128最终Summary中的integrated loudness；非有限/静音时null。\n'
        '- 削波比例：解码float PCM中abs(sample)>=0.999的样本占比。\n'
        '- 静音比例：abs(sample)<10^(-60/20)的样本占比；不是VAD。\n'
        '- 视频规格误差：实际与原任务分辨率、fps、时长对比；16帧包含首帧与最后有效帧。\n'
        '- ffmpeg线程上限1；音频最多120秒/64MiB PCM；无新增依赖。\n'
        '- 不使用转写或文字描述冒充sol听音。\n'
        '- VABench：已阅读arXiv:2512.09299v2的3.3.1；CLAP余弦、DNSMOS OVRL、NISQAv2、Audiobox定义已记录，但本轮未与实现对齐。\n')
    (out/'report.md').write_text('\n'.join(summary)+'\n')
    dump(out/'run.json',{'status':'local_probe_only','scope':['video','audio'],'records':len(rows),
         'elapsed_seconds':time.monotonic()-start,'process_snapshot_before':state,'sol_calls':0,
         'score_policy':'unavailable requested perceptual/model components remain null'})
    return out


def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',type=Path)
    p.add_argument('--metrics', action='store_true', help='Run bounded CG/SFX real scoring, including sol and local models')
    p.add_argument('--no-sol', action='store_true')
    p.add_argument('--reuse-source-run', type=Path); a=p.parse_args()
    if a.metrics:
        from .media_scoring import run_pilot as score_pilot
        print(score_pilot(a.out, no_sol=a.no_sol, source_run=a.reuse_source_run))
    else:
        print(run_pilot(a.out))
if __name__=='__main__': main()
