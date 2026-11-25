"""Bounded one-asset local geometry/palette smoke; no ML models and no sol."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import signal
import sys


def worker(args):
    # Handshake before importing numerical libraries. Only the parent resumes us.
    if os.environ.get('ASSET_EVAL_BOUNDED_CHILD') != '1':
        raise RuntimeError('Worker requires bounded launcher')
    os.nice(19)
    os.kill(os.getpid(), signal.SIGSTOP)
    from .common import SAMPLES, ASSETS, check_environment, dump, read
    check_environment()
    import time
    start_cpu = time.process_time()
    game = 'G001_port_guard_arena'; task_id = 'G001_obj_005'
    import json, re
    task = next(t for t in map(json.loads, (SAMPLES / game / '3D_object/object_tasks.jsonl').read_text().splitlines()) if t['task_id'] == task_id)
    delivery = ASSETS / game / 'assets/3d_object' / f'{game}_obj_005' / 'tripo'
    context = (SAMPLES / game / 'general_requirement.txt').read_text()
    w06 = next(line for line in context.splitlines() if 'W06' in line)
    palette = re.findall(r'#[0-9a-fA-F]{6}\b', w06)
    out = Path(args.out)
    if args.phase == 'geometry':
        from .quality import geometry_quality
        result = geometry_quality(delivery / 'model.glb', task)
        from PIL import Image
        with Image.open(delivery / 'preview.png') as image:
            extrema = image.convert('RGBA').getchannel('A').getextrema()
        dump(out / 'geometry.json', {'task_id': task_id, 'provider': 'tripo', 'glb': str(delivery / 'model.glb'),
                                    **result, 'preview_alpha_extrema': extrema})
    elif args.phase == 'render':
        from .render import configured_renderer, render_glb, STANDARD
        from .common import sha
        adapter = configured_renderer(out / '_renderer')
        text = adapter.read_text()
        # Same native renderer; only six standard cameras and thread configuration.
        from .render import RING
        text = text.replace('const views=' + json.dumps(STANDARD + RING) + ';', 'const views=' + json.dumps(STANDARD) + ';')
        old = "args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']"
        new = "args:['--use-angle=swiftshader','--enable-unsafe-swiftshader','--num-raster-threads=1','--renderer-process-limit=1','--disable-threaded-animation','--disable-threaded-scrolling']"
        if text.count(old) != 1:
            raise RuntimeError('Renderer launch configuration changed')
        text = text.replace(old, new)
        adapter.write_text(text)
        provenance = read(adapter.parent / 'provenance.json')
        provenance['local_smoke_overrides'] = {'views': STANDARD, 'extra_browser_args': new,
                                              'resolution': [768, 768], 'no_material_or_lighting_changes': True}
        provenance['adapter_sha256'] = sha(adapter)
        dump(adapter.parent / 'provenance.json', provenance)
        render_glb(delivery / 'model.glb', out / 'renders', adapter, scope='obj')
    elif args.phase == 'palette':
        from PIL import Image
        from .style import palette_metric
        views = read(out / 'renders/manifest.json')['views']
        result = palette_metric([v['path'] for v in views], palette)
        control = palette_metric([Image.new('RGBA', (32, 32), palette[0])], palette)
        dump(out / 'palette.json', {'task_id': task_id, 'provider': 'tripo', **result,
                                    'views': [v['id'] for v in views], 'w06': w06,
                                    'pure_hex_control': {'hex': palette[0], **control}})
    else:
        raise ValueError(args.phase)
    dump(out / f'{args.phase}_worker.json', {'phase': args.phase, 'process_cpu_seconds': time.process_time() - start_cpu,
          'models_loaded': [], 'api_calls': 0, 'forbidden_imports': {p: p in sys.modules for p in ('torch', 'transformers', 'pyiqa', 'pipeline.eval.stage1.codex')}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--phase', choices=['geometry', 'render', 'palette'], required=True)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args); return
    from .common import check_environment, validate_out
    from .bounded import run_bounded
    check_environment(); out = validate_out(args.out)
    result = run_bounded('pipeline.eval.asset_eval.local_probe',
                         ['--worker', '--phase', args.phase, '--out', out], out / f'{args.phase}_process',
                         cpu_budget=25 if args.phase == 'render' else 15,
                         wall_budget=600, rss_limit_mb=1200)
    print(__import__('json').dumps(result, indent=2))
    if result['returncode']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
