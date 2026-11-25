"""Read-only task, rubric, provider and generation-provenance inventory."""
from __future__ import annotations
from .common import resolve_input
from collections import Counter
from pathlib import Path
import re
from .common import SAMPLES, ASSETS, BENCH, read

KINDS = {'obj': ('3D_object', 'object_tasks.jsonl', '3d_object'),
         'scene': ('3D_scene', 'scene_tasks.jsonl', '3d_scene'),
         'video': ('cg_video', 'cg_tasks.jsonl', 'cg_video'),
         'audio': ('audio', 'audio_tasks.jsonl', 'audio')}
CLOSED = {'meshy', 'tripo', 'marble', 'minimax-h3/text-to-video', 'bytedance/seedance-2',
          'elevenlabs/sound-effects-v2', 'mirelo-ai/sfx-1.6/text-to-audio',
          'mirelo-ai/sfx-1.6/extend-audio', 'mirelo-ai/sfx-2.0/text-to-audio',
          'kie/google/gemini-3-1-flash-tts', 'sonilo/v1/text-to-sfx'}


def tasks(game, scope):
    sub, file, _ = KINDS[scope]
    p = game / sub / file
    if not p.exists():
        return []
    import json
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def task_suffix(task_id, scope):
    marker = {'obj': '_obj_', 'scene': '_scene_', 'video': '_cg_', 'audio': '_sfx_'}[scope]
    if marker not in task_id:
        # Dialogue IDs can use _dialogue_ rather than _sfx_.
        return task_id.split('_', 1)[-1]
    return marker.lstrip('_') + task_id.rsplit(marker, 1)[-1]


def rubric_path(game, task, scope):
    suffix = task_suffix(task['task_id'], scope)
    folder = game / 'rubric_assets/per_asset'
    candidates = [folder / f'{game.name}_{suffix}.json', folder / f'{game.name[:4]}_{suffix}.json']
    for p in candidates:
        if p.exists():
            return p
    return None


def style_context(game):
    text = (game / 'general_requirement.txt').read_text()
    lines = text.splitlines()
    # Retain original W01-W08 and explicit art/material paragraphs verbatim.
    selected = [line for line in lines if re.search(r'\bW0[1-8]\b', line)
                or any(k in line for k in ('美术方向', '美术风格', '材质基线', '视觉基线'))]
    w06 = [line for line in lines if re.search(r'\bW06\b', line)]
    palette = list(dict.fromkeys(re.findall(r'#[0-9a-fA-F]{6}\b', '\n'.join(w06))))
    return {'art_direction_verbatim': '\n'.join(selected), 'w06_verbatim': '\n'.join(w06),
            'palette_hex': palette, 'requirement_path': str(game / 'general_requirement.txt')}


def character_references(game):
    """Use explicit task image_path+role links, never filename/identity guessing."""
    refs = []
    allowed = {'character', 'player', 'enemy', 'npc', 'enemy_normal', 'enemy_boss', 'enemy_elite'}
    for t in tasks(game, 'obj'):
        if t.get('role') not in allowed or not t.get('image_path'):
            continue
        p = resolve_input(t['image_path'])
        if p.is_relative_to(SAMPLES.resolve()) and p.is_file():
            refs.append({'task_id': t['task_id'], 'asset_name': t.get('asset_name'),
                         'name_zh': t.get('name_zh'), 'role': t['role'], 'path': str(p),
                         'matching_rule': 'explicit object task role + image_path; video identity must be selected by sol, not filename heuristics'})
    return refs


def object_delivery(game, task, scope, provider):
    suffix = task_suffix(task['task_id'], scope)
    base = ASSETS / game.name / 'assets' / KINDS[scope][2]
    for ident in (f'{game.name}_{suffix}', task['task_id']):
        p = base / ident / provider
        if p.is_dir():
            return p
    return base / f'{game.name}_{suffix}' / provider


def scene_provider_override(game, task):
    overrides = read(Path(__file__).with_name('provider_overrides.json'))
    return overrides.get(f"{game.name}/{task['task_id']}")


def scene_bundles(game, task):
    """Keep provider attribution explicit; unknown packages remain excluded."""
    base = ASSETS / game.name / 'assets/3d_scene'
    suffix = task_suffix(task['task_id'], 'scene')
    result = []
    override = scene_provider_override(game, task)
    for ident in dict.fromkeys((task['task_id'], f'{game.name}_{suffix}')):
        folder = base / ident
        for archive in sorted(folder.glob('*.zip')):
            result.append({'task_id': task['task_id'], 'archive_path': str(archive),
                           'provider': override['provider'] if override else None,
                           'classification': provider_class(override['provider']) if override else 'unknown_excluded',
                           'attribution': override,
                           'reason': 'Provider recorded from explicit user confirmation; original input metadata unchanged.' if override else 'Package has no verified closed-generator attribution.'})
    return result


def provider_class(name):
    if name in CLOSED:
        return 'closed'
    if name.startswith(('local/', 'direct_', 'direct/')):
        return 'local_or_procedural_excluded'
    return 'unknown_excluded'


def inventory(selected_games=None, *, audit_rubric_content=True):
    games = sorted(p for p in SAMPLES.glob('G0*') if p.is_dir())
    if selected_games is not None:
        names = {g.name for g in selected_games}
        games = [g for g in games if g.name in names]
    coverage = Counter(); palette_games = []; no_palette = []; providers = Counter()
    bundles = []; refs = {}; mismatches = []; brief_prompts = Counter(); prompt_examples = {}
    for g in games:
        ctx = style_context(g)
        (palette_games if ctx['palette_hex'] else no_palette).append(g.name)
        refs[g.name] = character_references(g)
        for scope in KINDS:
            ts = tasks(g, scope)
            coverage[scope + '_tasks'] += len(ts)
            for t in ts:
                mode = t.get('input_mode', t.get('mode', t.get('audio_type', 'image_to_3d' if scope == 'scene' else 'unknown')))
                coverage[f'{scope}:{mode}'] += 1
                rp = rubric_path(g, t, scope)
                coverage[scope + '_with_rubric'] += rp is not None
                if scope == 'obj':
                    coverage['obj_text_with_rubric'] += rp is not None and mode == 'text_to_3d'
                    if audit_rubric_content and rp and read(rp).get('task_input', {}).get('prompt') != t.get('prompt'):
                        mismatches.append({'task_id': t['task_id'], 'rubric': str(rp), 'reason': 'rubric task_input prompt differs from base task; retained, not rewritten'})
                # Exact inclusion test only: do not infer semantic context from a short prompt.
                brief_prompts[f'{scope}:base_prompt_contains_full_brief'] += (g / 'general_requirement.txt').read_text().strip() in t.get('prompt', '')
        for scene_task in tasks(g, 'scene'):
            bundles.extend(scene_bundles(g, scene_task))
        for kind in ('3d_object', '3d_scene', 'cg_video', 'audio'):
            base = ASSETS / g.name / 'assets' / kind
            for td in sorted(base.glob('*')):
                if not td.is_dir():
                    continue
                if kind in ('3d_object', '3d_scene'):
                    for p in td.iterdir():
                        if p.is_dir():
                            providers[kind, p.name, provider_class(p.name)] += 1
                            mp = p / 'meta.json'
                            if mp.exists():
                                meta = read(mp); shared = meta.get('shared_prompt', '')
                                has = bool(meta.get('full_context', {}).get('context_excerpt'))
                                brief_prompts['obj:metadata_context_excerpt'] += has
                                brief_prompts['obj:shared_prompt_nonempty'] += bool(shared)
                                prompt_examples.setdefault('obj', {'path': str(mp), 'context_condition': meta.get('context_condition'),
                                                                  'shared_prompt_excerpt': str(shared)[:700]})
                elif kind == 'cg_video':
                    for mp in td.glob('meta*.json'):
                        meta = read(mp); pro = meta.get('provider', meta.get('model', 'unknown'))
                        providers[kind, pro, provider_class(pro)] += 1
                        sent = meta.get('request', {}).get('input', {}).get('prompt', '')
                        brief_prompts['video:request_with_GAME_CONTEXT'] += '[GAME CONTEXT]' in sent
                        prompt_examples.setdefault('video', {'path': str(mp), 'contains_GAME_CONTEXT': '[GAME CONTEXT]' in sent})
                else:
                    for mp in td.glob('meta*.json'):
                        for variant in read(mp).get('variants', []):
                            pro = variant.get('method', 'unknown')
                            providers[kind, pro, provider_class(pro)] += 1
    coverage['obj_rubric_coverage'] = coverage['obj_with_rubric'] / coverage['obj_tasks'] if coverage['obj_tasks'] else None
    coverage['obj_text_rubric_coverage'] = coverage['obj_text_with_rubric'] / coverage['obj:text_to_3d'] if coverage['obj:text_to_3d'] else None
    return {'scene_bundle_deliveries': bundles, 'games': len(games), 'rubric_content_audited': audit_rubric_content, 'coverage': dict(coverage), 'palette_games_count': len(palette_games),
            'no_palette_games': no_palette, 'providers': [dict(kind=k, provider=p, classification=c, deliveries=n)
                for (k, p, c), n in sorted(providers.items())], 'character_references': refs,
            'rubric_prompt_mismatches': mismatches, 'generation_context_audit': dict(brief_prompts),
            'generation_context_examples': prompt_examples,
            'provider_policy': 'Only allowlisted closed services; audio mixed/procedural packages are not assigned a single closed provider.',
            'scene_note': 'No 3d_scene delivery directories found' if not list(ASSETS.glob('G*/assets/3d_scene')) else None}
