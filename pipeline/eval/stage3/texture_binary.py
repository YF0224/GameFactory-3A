"""Texture = is each imported 3D asset visibly the same as its original? Binary 0 / 1 per asset.

For every required 3D object / scene that import_presence found in the project and that has both
renders (Unity, same editor / light rig / four angles):
  VIEW:<asset>    the asset as the game imported it
  SRCVIEW:<asset> the original asset file
one judge call per game answers, per asset, ``similar`` (true = same surface, colours, textures and
shape; false = missing / default / wrong textures, broken UVs or a different-looking asset) with a
short reason. S = 100 * similar / judged. Assets without both renders (e.g. UE, no renderer yet) are
listed as not measurable and excluded from S.
"""
from __future__ import annotations

from pathlib import Path

from ..stage1.llm import call_model
from ..stage1.paths import read_json, write_json

VERSION = 'stage3-texture-binary.v1'
PROMPT = '''For each ASSET below you get two four-view renders made with the same engine, lights and camera angles:
VIEW:<asset> is the asset as the game imported it, SRCVIEW:<asset> is the original asset file.
Decide only: does the imported asset look the same as the original (same surface textures, colours,
material look and overall shape)? similar=false if the import shows missing / default (grey, white,
pink) / wrong textures, broken UVs, missing parts, or looks like a different asset. Ignore background,
framing and small lighting differences. Images (in order): {order}. Return only the schema.'''


def evaluate(out: Path, model: str) -> dict:
    out = Path(out)
    pres = read_json(out / 'import_presence.json')
    views = out / 'asset_views' / 'asset_views.json'
    src = out / 'asset_views' / 'source' / 'source_views.json'
    va = read_json(views)['assets'] if views.is_file() else {}
    sa = read_json(src)['assets'] if src.is_file() else {}
    pairs, skipped = [], {}
    for a, v in pres['assets'].items():
        if v['kind'] not in ('3d_object', '3d_scene') or not v['present']:
            continue
        if (va.get(a) or {}).get('ok') and (sa.get(a) or {}).get('ok'):
            pairs.append(a)
        else:
            skipped[a] = 'no in-engine renders for this asset (engine without renderer, or render failed)'
    result = {'version': VERSION, 'game_id': pres['game_id'], 'judge': model, 'assets': {},
              'not_measurable': skipped}
    if pairs:
        images, order = [], []
        for a in pairs:
            images += [va[a]['sheet']['path'], sa[a]['sheet']['path']]
            order += [f'VIEW:{a}', f'SRCVIEW:{a}']
        item = {'type': 'object', 'additionalProperties': False, 'required': ['similar', 'reason'],
                'properties': {'similar': {'type': 'boolean'}, 'reason': {'type': 'string'}}}
        schema = {'type': 'object', 'additionalProperties': False, 'required': pairs,
                  'properties': {a: item for a in pairs}}
        reply = call_model(out / 'model_calls', name='texture_binary', prompt=PROMPT.format(order=', '.join(order)),
                           schema=schema, cwd=out / 'input', images=images, model=model, timeout=1800)
        result['assets'] = {a: reply[a] for a in pairs}
    judged = list(result['assets'].values())
    result['S'] = round(100 * sum(x['similar'] for x in judged) / len(judged), 2) if judged else None
    result['similar'] = f'{sum(x["similar"] for x in judged)}/{len(judged)}'
    write_json(out / 'texture_binary.json', result)
    return result
