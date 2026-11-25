"""Read-only projection of actually measured traditional quality metrics."""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

def _get(d, *keys):
    for key in keys:
        if not isinstance(d, dict): return None
        d = d.get(key)
    return d

def quality_row(path: Path) -> dict:
    d=json.loads(path.read_text()); q=_get(d,'columns','quality','metrics') or {}
    images=q.get('image_metrics') or {}; geometry=q.get('geometry') or {}; raw=geometry.get('raw') or {}
    signal=q.get('signal') or {}; flicker=q.get('flicker') or {}; spec=q.get('specification') or {}; subject=q.get('subject_consistency') or {}
    def im(name): return images.get(name) or q.get(name) or {}
    musiq=im('musiq'); brisque=im('brisque'); niqe=im('niqe')
    return {'game':d.get('game'),'task_id':d.get('task_id'),'provider':d.get('provider'),'scope':d.get('scope'),
      'quality_index_0_100':_get(d,'columns','quality','score'),'musiq_mean_0_100':musiq.get('mean'),
      'brisque_reference_mean':brisque.get('mean'),'niqe_reference_mean':niqe.get('mean'),
      'geometry_subscore_0_100':geometry.get('geometry_subscore'),'glb_load_ok':raw.get('load_ok'),
      'triangle_count':raw.get('triangles'),'degenerate_face_ratio':raw.get('degenerate_face_ratio'),
      'nonmanifold_edge_ratio':raw.get('nonmanifold_edge_ratio'),'triangle_target_deviation':raw.get('triangle_relative_deviation'),
      'texture_match_fraction':raw.get('texture_match_fraction'),'flicker_second_difference':flicker.get('mean_second_difference'),
      'static_pixel_fraction':flicker.get('static_pixel_fraction'),'video_spec_score':spec.get('score'),
      'video_subject_consistency':subject.get('score'),'audio_duration_sec':signal.get('duration_sec'),
      'audio_lufs':signal.get('integrated_lufs'),'audio_clipping_fraction':signal.get('clipping_sample_fraction'),
      'audio_silence_fraction':signal.get('silence_sample_fraction'),'failure_label':d.get('failure_label'),'score_json':str(path)}

def project(run_dirs, out_dir:Path|None=None):
    if isinstance(run_dirs, (str, Path)): run_dirs=[run_dirs]
    run_dirs=[Path(p).resolve() for p in run_dirs]
    paths=sorted({p for run_dir in run_dirs for p in (run_dir/'assets').rglob('score.json')})
    rows=[quality_row(p) for p in paths]
    if not rows: raise ValueError(f'No per-asset score.json files in {run_dirs}')
    out=Path(out_dir or run_dir).resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'traditional_quality_metrics.csv').open('w',newline='') as f:
      w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    cols=['task_id','provider','musiq_mean_0_100','brisque_reference_mean','niqe_reference_mean','geometry_subscore_0_100','degenerate_face_ratio','nonmanifold_edge_ratio','triangle_count','texture_match_fraction','flicker_second_difference','video_spec_score','audio_lufs','audio_clipping_fraction','audio_silence_fraction','quality_index_0_100']
    lines=['# 传统质量指标明细','','从逐资产 score.json 投影已实际计算的指标；不重算、不填补缺失项。质量指数缺少必需组件时仍为 null。','', '|资产|provider|MUSIQ均值|BRISQUE参考|NIQE参考|几何子分|退化面比例|非流形边比例|三角面数|贴图匹配率|闪烁代理|规格分|LUFS|削波比例|静音比例|质量指数|','|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows: lines.append('| '+' | '.join('null' if r.get(k) is None else str(r[k]) for k in cols)+' |')
    lines += ['', '## 口径','', '- 3D：MUSIQ六视角均值；BRISQUE/NIQE仅作自然图像参考。几何原始项来自trimesh/GLB检查，必需目标缺失则几何子分与质量指数null。','- CG：MUSIQ按16个均匀抽帧均值；闪烁为稀疏静态像素二阶差分代理，规格分对照任务。主体证据不全时质量指数null。','- Audio：LUFS、削波、静音比例为信号测量，不等价感知质量。DNSMOS、NISQAv2、Audiobox没有实际执行的分数记null。','- null表示未计算、任务不适用或必需输入缺失，不当作0。','']
    (out/'traditional_quality_metrics.md').write_text('\n'.join(lines));return out

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,nargs='+',required=True);p.add_argument('--out',type=Path);a=p.parse_args();print(project(a.run,a.out))
if __name__=='__main__':main()
