"""Measured stage disk admission/monitoring; never deletes evidence or caches."""
from pathlib import Path
import os
import shutil
import time
from .protocol import dump

GIB = 1024**3
VERSION = 'unity-measured-stage-disk-guard.v1'

class DiskSpaceRequired(RuntimeError):
    pass


def tree_bytes(path, *, source_only=False):
    path = Path(path)
    total = 0
    if not path.exists(): return 0
    if path.is_symlink(): raise ValueError('Cannot estimate a symlink project')
    if source_only:
        # Estimate the exact files the formal adapter will copy. Generated build
        # and recording trees excluded by its snapshot policy are not inputs to
        # the next import; all files it actually copies still count in full.
        from engine_adapters.unity3d.playtest.project_snapshot import snapshot_files
        return sum(source.stat().st_size for source in snapshot_files(path, []))
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(root)/d).is_symlink()]
        for name in files:
            p = Path(root)/name
            if not p.is_symlink(): total += p.stat().st_size
    return total


def estimate(stage, project=None, capture=None, *, duration=180, frames=500,
             width=1920, height=1080, source_bytes=None, cache_bytes=None):
    if min(duration,frames,width,height) < 0: raise ValueError('Negative disk estimate input')
    source = (tree_bytes(project,source_only=True) if project else 0) if source_bytes is None else source_bytes
    cache = (tree_bytes(Path(project)/'Library') if project else 0) if cache_bytes is None else cache_bytes
    if min(source,cache) < 0: raise ValueError('Negative project size')
    imported = source + max(4*GIB, 4*source, 2*cache)
    raw_frames = int(frames)*int(width)*int(height)*4
    capture_size = tree_bytes(capture) if capture else 0
    if stage in {'admission','native_acceptance'}:
        required = imported * (2 if stage == 'native_acceptance' else 1)
    elif stage == 'capture':
        required = imported + 2*raw_frames + int(duration)*2*1024**2 + GIB
    elif stage == 'evidence':
        required = max(2*GIB, 2*capture_size + raw_frames)
    else:
        required = 256*1024**2
    return {'stage':stage, 'source_bytes':source,'existing_library_bytes':cache,
            'existing_capture_bytes':capture_size,'duration_seconds':duration,
            'estimated_frames':frames,'frame_width':width,'frame_height':height,
            'estimated_next_stage_bytes':int(required),
            'method':'Source copy + conservative import/cache multiplier; raw RGBA frames x2, video 2MiB/s; evidence copies x2. No candidate cache counted as free.'}


def check(output,stage,project=None,capture=None,*,reserve_bytes=8*GIB,**kw):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if reserve_bytes < 0: raise ValueError('Negative reserve')
    row=estimate(stage,project,capture,**kw)
    free=shutil.disk_usage(output).free
    required=row['estimated_next_stage_bytes']+reserve_bytes
    row.update(version=VERSION,at=time.time(),free_bytes=free,reserve_bytes=reserve_bytes,
               required_bytes=required,shortfall_bytes=max(0,required-free),admitted=free>=required,
               project=str(project) if project else None,capture=str(capture) if capture else None,
               no_deletion_performed=True)
    path=output/('disk_gate_'+stage+'_'+str(time.time_ns())+'.json');dump(path,row)
    if not row['admitted']:
        dump(output/'disk_checkpoint.json',dict(row,gate_receipt=str(path),next_action='Safely reclaim scored per-case pure caches under seven locks, remeasure, or continue low-disk offline engineering. Preserve all evidence.'))
        raise DiskSpaceRequired('Stage '+stage+' needs '+str(required)+' bytes, available '+str(free)+', shortfall '+str(row['shortfall_bytes'])+'; checkpoint '+str(path))
    return row


def sample(output,stage,*,reserve_bytes=8*GIB):
    output=Path(output);free=shutil.disk_usage(output).free
    row={'version':VERSION,'at':time.time(),'stage':stage,'free_bytes':free,
         'reserve_bytes':reserve_bytes,'below_reserve':free<reserve_bytes,
         'action':'Checkpoint at next safe stage boundary; do not kill or delete evidence.' if free<reserve_bytes else 'MONITORING'}
    dump(output/'disk_monitor.json',row)
    with (output/'disk_samples.jsonl').open('a') as stream:
        import json
        stream.write(json.dumps(row)+'\n')
    return row
