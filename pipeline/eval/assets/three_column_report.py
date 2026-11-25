"""Read-only projection of per-asset results into exactly three score columns."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

def _num(x): return x if isinstance(x,(int,float)) and not isinstance(x,bool) else None

def project_score(path):
 d=json.loads(path.read_text()); c=d.get('columns') or {}; i=c.get('input') or {}; s=c.get('style') or {}; q=c.get('quality') or {}; scope=d.get('scope'); iv=i.get('score'); sv=s.get('score'); qv=q.get('score'); details=[]
 if scope in ('obj','scene'):
  if d.get('input_mode') == 'image_to_3d':
   iv_raw=iv; iv=None
  elif _num(iv) is not None: iv=round(100*iv,4)
  if _num(sv) is not None: sv=round(25*sv,4)
  pal=s.get('palette') or {}
  if pal.get('weighted_mean_deltaE2000') is not None: details.append(f"色板ΔE2000={pal['weighted_mean_deltaE2000']:.3f}（越低越接近）")
  im=i.get('metrics') or {}
  if im.get('dinov2_cosine_max') is not None: details.append(f"参考图DINO余弦={im['dinov2_cosine_max']:.4f}，最佳视角={im.get('best_view')}")
  if d.get('input_mode') == 'image_to_3d' and _num(iv_raw) is not None: details.append('输入符合度分数留null：当前只有未校准DINO余弦，不能冒充百分制评分')
 elif scope=='video':
  if _num(iv) is not None: iv=round(100*iv,4)
  sm=s.get('metrics') or {}
  sv=None  # Current value is scene DINO, not a judged/calibrated game-style score.
  if sm.get('scene_dino_similarity') is not None:
   scene=sm['scene_dino_similarity']; cosine=scene.get('mean_cosine') if isinstance(scene,dict) else scene
   if cosine is not None: details.append(f"场景参考DINO均值余弦={cosine:.4f}（诊断值、未校准）")
  ch=sm.get('character_dino') or {}
  if ch.get('score') is not None: details.append(f"角色参考DINO余弦={ch['score']}，覆盖率={ch.get('crop_coverage')}")
 elif scope=='audio':
  sv=None; qv=None  # No evaluated game-style judge or perceptual audio quality score in this run.
  im=i.get('metrics') or {}
  if im.get('clap_cosine') is not None:
   details.append(f"CLAP文本-音频余弦={im['clap_cosine']:.4f}（诊断值、未校准）")
   iv=None
  sig=(q.get('metrics') or {}).get('signal') or {}
  if sig.get('integrated_lufs') is not None: details.append(f"LUFS={sig['integrated_lufs']}；削波={sig.get('clipping_sample_fraction')}；静音={sig.get('silence_sample_fraction')}")
 why=[]
 for label,val in [('输入符合度',iv),('游戏风格/输入一致性',sv),('传统质量',qv)]:
  if val is None: why.append(label+'=null（源结果无可验证分数/必需证据缺失）')
 if d.get('failure_label'): why.append('failure_label='+str(d['failure_label']))
 notes=details+why+[str(n) for n in d.get('notes',[]) if d.get('notes')]
 scale=('0–100（输入/风格/质量）' if scope in ('obj','scene') else '输入/质量0–100；风格为原始DINO余弦，未校准' if scope=='video' else '输入为原始CLAP余弦，未校准；风格/质量0–100' if scope=='audio' else '')
 return {'game':d.get('game'),'task_id':d.get('task_id'),'provider':d.get('provider'),'scope':scope,'input_mode':d.get('input_mode'),'delivered':d.get('delivered'),'input_adherence_score':iv,'game_style_input_consistency_score':sv,'traditional_quality_score':qv,'score_scale_note':scale,'notes':' | '.join(notes),'failure_label':d.get('failure_label'),'score_json':str(path)}

def build(run_dirs,out):
 paths=sorted({p for rd in map(Path,run_dirs) for p in (rd/'assets').rglob('score.json')})
 if not paths: raise ValueError('No score.json found')
 rows=[project_score(p) for p in paths];out=Path(out);out.mkdir(parents=True,exist_ok=True);fields=list(rows[0])
 with (out/'three_column_scores.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows([{k:('null' if v is None else v) for k,v in r.items()} for r in rows])
 labels=[('input_adherence_score','输入符合度'),('game_style_input_consistency_score','游戏风格/输入一致性'),('traditional_quality_score','传统质量')]
 fmt=lambda x:'null' if x is None else f'{x:.4f}' if isinstance(x,float) else str(x)
 lines=['# G001资产三列评分汇总','','每项资产仅三列评分。原始算法量仅作备注，不作为额外评分列。null表示源结果缺少可验证评分；不补分、不把null当0。','','|资产|provider|类型|输入符合度|游戏风格/输入一致性|传统质量|备注|','|---|---|---|---:|---:|---:|---|']
 for r in rows: lines.append('| '+' | '.join([str(r['task_id']),str(r['provider']),str(r['scope'])]+[fmt(r[x]) for x,_ in labels]+[r['notes'].replace('|','/')])+' |')
 lines+=['','## 口径与覆盖','', '- 3D：rubric通过率、0–4风格分映射到0–100；DINO余弦和色板ΔE保留在备注作为依据，非额外分列。','- CG：输入rubric通过率映射0–100；源风格值是场景参考DINO余弦，未经校准，不能解释为百分制风格分。','- 音频：CLAP为文本-音频余弦，不是百分制；目前没有经验证的风格判定及感知质量指数。信号值仅供备注。','- 覆盖：']
 for f,l in labels:
  n=sum(r[f] is not None for r in rows);lines.append(f'- {l}: {n}/{len(rows)} 有值，{len(rows)-n} null。')
 lines+=['','## 源运行','']+[f'- `{rd}`' for rd in run_dirs];(out/'three_column_scores.md').write_text('\n'.join(lines)+'\n');return len(rows)
def main():
 p=argparse.ArgumentParser();p.add_argument('--run',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();print(build(a.run,a.out))
if __name__=='__main__':main()
