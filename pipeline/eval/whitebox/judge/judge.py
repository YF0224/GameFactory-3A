"""Judge every criterion of every metric in one pass.

Two kinds of calls, both mixing all metrics:

* ``static_NN``   static rows (story / asset_slot / code ...), source + documents only, no images
* ``evidence_NN`` all other rows, source + runtime channels + frame sheets + reference images

Rows are sharded by verdict format (``SHARD_SIZE``) only to bound one reply's length; every shard sees the
same complete evidence packet. Source and documents are delivered complete by
read access to the run's frozen ``input/`` snapshot (an index with line counts and
SHA256 is in the prompt); runtime channels are inlined with line numbers. The reply is keyed by criterion id and each
value follows its own metric's ``item_schema()``.

After the model replies, citations are checked against what was actually
delivered. An unsupported claim is downgraded (binary -> UNVERIFIED; tiered ->
the unsupported tier is withdrawn), never silently accepted; the reason is
kept in ``validation_issues``.
"""
from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ..core.llm import S, accepted_response, arr, call_model, obj
from ..core.paths import read_json, write_json
from ..core import suites

VERSION = 'stage1-judge.v1'
SHARD_SIZE = {'binary': 40, 'tiered': 8}   # rows per call; tiered verdicts are long (output-token bound)
JUDGE_PARALLEL = int(os.environ.get('A3GAME_JUDGE_PARALLEL', '4'))   # concurrent shard calls
MAX_IMAGES = int(os.environ.get('A3GAME_MAX_IMAGES', 24))
# per model call. 2026-11-11: with 50-100 images (+ source reads) the Codex CLI compacted the conversation and
# the judge only saw a text summary of the images ("continued context only has an earlier model's summary");
# ~20 images per call were seen. Own frames that do not fit are regridded denser, never dropped.
MAX_IMAGE_BYTES = int(os.environ.get('A3GAME_MAX_IMAGE_BYTES', 30 * 1024 * 1024))   # raw PNG bytes per call (~41 MB encoded)
FILE_CHARS = 90_000
CHANNEL_CHARS = 120_000
RUNTIME_TYPES = {'channel', 'frame'}


def _numbered(path: Path, keep=None, limit=FILE_CHARS) -> tuple[str, int]:
    """'n: text' lines; returns (text, last delivered line number)."""
    out, size, last = [], 0, 0
    for n, line in enumerate(Path(path).read_text(errors='replace').splitlines(), 1):
        if keep is not None and n not in keep:
            continue
        row = f'{n}: {line}\n'
        if size + len(row) > limit:
            break
        out.append(row)
        size += len(row)
        last = n
    return ''.join(out), last


def _relative(path: str, manifest: dict) -> str:
    """Path as seen from the judge's working directory (the run's input/)."""
    root = Path(manifest['_root']) / 'input'
    try:
        return str(Path(path).resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def packet(manifest: dict, kind: str) -> tuple[str, dict, list[str]]:
    """Build the text packet; return (text, delivered {id: allowed lines | 'image'}, image paths)."""
    parts, delivered, images = [], {}, []
    files = []
    for it in manifest['items']:
        if it['type'] == 'requirement':
            text, _ = _numbered(Path(it['path']))
            parts.append(f'REQUIREMENT CONTEXT (not admissible as proof)\n{text}')
            delivered[it['id']] = range(1, it['lines'] + 1)
        elif it['type'] in ('source', 'document'):
            # Complete files are delivered by read access to the frozen snapshot (never
            # truncated inline); every physical line of the file is citable.
            files.append({'id': it['id'], 'path': _relative(it['path'], manifest), 'lines': it['lines'],
                          'sha256': it['sha256']})
            delivered[it['id']] = range(1, it['lines'] + 1)
    parts.append('SOURCE AND DOCUMENT FILES (complete, read-only, paths relative to your working directory '
                 'input/; read them yourself and cite the evidence id with real 1-based line numbers; '
                 'DOC: files are declarations, not implementation proof)\n'
                 + json.dumps(files, ensure_ascii=False))
    if kind == 'evidence':
        channel_budget = CHANNEL_CHARS
        # Stage3 per-asset event channels (small) go first so the shared channel budget never drops them.
        ordered = sorted(manifest['items'], key=lambda it: not (str(it.get('id', '')).startswith('ASSET_EVENT:')
                          or str(it.get('id', '')).endswith(':asset_events')))
        for it in ordered:
            if it['type'] == 'channel' and channel_budget > 0:
                keep = set(it['state_lines']) if 'state_lines' in it else None
                text, last = _numbered(Path(it['path']), keep=keep, limit=channel_budget)
                channel_budget -= len(text)
                parts.append(f'EVIDENCE {it["id"]}\n{text}')
                delivered[it['id']] = ({n for n in keep if n <= last} if keep is not None else range(1, last + 1))
            elif it['type'] == 'image':
                delivered[it['id']] = 'image'
                images.append(it['path'])
            elif it['type'] == 'frame':
                delivered[it['id']] = 'image'
        parts.append('ACTION / PROBE INDEX\n' + json.dumps(
            [{k: l.get(k) for k in ('take', 'action_line', 'action_id', 'criterion_ids', 't_ms', 'frames')}
             for l in manifest['action_links']], ensure_ascii=False))
        parts.append('VIDEO ENDPOINT INDEX\n' + json.dumps(
            [{'id': it['id'], 't_ms': it['t_ms'], 'endpoints': it['video_endpoints']}
             for it in manifest['items'] if it['type'] == 'frame' and it.get('video_endpoints')],
            ensure_ascii=False))
        parts.append('IMAGE ID MAP\n' + json.dumps(
            [{'id': it['id'], 't_ms': it['t_ms'], 'sheet': it['sheet']} for it in manifest['items']
             if it['type'] == 'frame'] + [dict({'id': it['id'], 'path': Path(it['path']).name},
                    **{k: it[k] for k in ('recording_origin', 'asset_event_id', 'owner', 'playback_window_ms', 'frames') if k in it})
                                          for it in manifest['items'] if it['type'] == 'image'],
            ensure_ascii=False))
        images += [str(Path(manifest['_root']) / 'delivery' / s) for s in manifest['sheets']]
    return '\n\n'.join(parts), delivered, images


INSTRUCTIONS = """You judge a delivered whitebox game against frozen CHECKS. Judge each check independently.
Cite evidence as {id, line_start, line_end, observation}: text evidence uses the real 1-based line
numbers shown; FRAME:/REF:/VIEW: images use line_start = line_end = 0 and the FRAME/REF/VIEW id (never the sheet).
SRCVIEW:<asset> is the same render of the ORIGINAL asset file (texture baseline). VIEW:<asset> is an in-engine render of the imported asset alone (empty scene, neutral light rig, asset-embedded lights and scripts off) from front / right / back / three-quarter-top; it shows the imported geometry and materials, not where the game uses the asset. A VIEW whose loader says "in-game recorder shot" is instead the asset photographed INSIDE the running game (game lighting, real placement) at the end of a take: use it with SRCVIEW to judge whether the imported asset keeps its original look in the game.
LOG:T<k>:asset_events preserves the complete raw asset observation trace, including renamed clips not bound to a canonical asset id. Its paths alone do not prove which required asset was used; establish identity from author sources or import provenance and the native gameplay frames.
ASSET_EVENT:T<k>:<asset> lists what the game's own recorder saw for one imported asset during take k: when its motion / audio / video started and ended (or was interrupted / stopped early), on which owner, with the take time; use it with the ACTION index and frames to judge whether the asset was triggered at the declared moment. Lines of kind level are map loads (context). When detail.observation_source is author_game_log, the transition is reported by the delivered script at detail.call_site, not independently observed in an Animator; cross-check its source, trigger and native frames.
For cg_video import, compare only the first observed gameplay frame and the last frame before a natural end. If ACTION plus game/source evidence proves an intentional user skip, compare only the first frame. stop_early alone never proves a skip; playback errors and unexplained interruption remain unverified or a demonstrated bug. Endpoint samples are approximate recorded frames (within 500 ms), not exact decoded frame zero/final; a blank or unavailable endpoint is insufficient visual proof. Use ASSET_EVENT for identity and trigger timing.
MOTION:T<k>:<asset> contains unmodified native gameplay frames from take k, captured while the recorder observed that asset playing naturally. Captions give the original FRAME ids and take times (cite MOTION with line 0). It is not a separate model preview or an animation forced by the recorder. Use it with ASSET_EVENT to check the actual game character and visible motion for deformation (stretched / torn limbs, T-pose, detached parts). Cross-check asset identity and natural playback with ASSET_EVENT and the gameplay frames. For deformation, record no obvious deformation when none is observed; judge deformation only when an obvious defect is actually visible. Do not mark the deformation criterion unverified solely because the character is small, the lighting is dim or the character is partly occluded. Do not require a particular prop or detailed action beyond the frozen check.
REQUIREMENTS is context only, never proof. DOC: files are declarations; implementation needs SRC:.
Binary checks: PASS only with sufficient cited evidence; FAIL only with an observed counterexample;
otherwise UNVERIFIED. Tiered checks: fill source_existence / basic_function / result_outcome
independently; claim only what the cited evidence shows; exact timings, distances and numbers are
diagnostics, not gates. Use HARNESS_ERROR only for tool failures. Never invent observations.
"""


def _check_refs(row: dict, refs: list[dict], delivered: dict, part: str | None = None, log_ok: bool = False) -> list[str]:
    issues = []
    for r in refs:
        allowed = delivered.get(r['id'])
        if allowed is None:
            issues.append(f'cites undelivered evidence {r["id"]}')
        elif allowed == 'image':
            if r['line_start'] != 0 or r['line_end'] != 0:
                issues.append(f'{r["id"]}: image citations use line 0')
        elif not (r['line_start'] <= r['line_end'] and r['line_start'] in allowed and r['line_end'] in allowed):
            issues.append(f'{r["id"]}: lines {r["line_start"]}-{r["line_end"]} were not delivered')
    ids = {r['id'] for r in refs if delivered.get(r['id']) is not None}
    if row.get('metric') == 'import' and row.get('asset_id'):
        asset = row['asset_id']
        for ident in ids:
            if ident.startswith(('ASSET_EVENT:', 'MOTION:')) and ident.rsplit(':', 1)[-1] != asset:
                issues.append(f'{ident}: evidence belongs to a different asset than {asset}')
    for ident in ids:
        if ident.startswith('MOTION:') and not re.fullmatch(r'MOTION:T[0-9]+:[^:]+', ident):
            issues.append(f'{ident}: staged motion previews are not native gameplay evidence')
    motion_takes = {i.split(':')[1] for i in ids if i.startswith('MOTION:T')}
    event_takes = {i.split(':')[1] for i in ids if i.startswith('ASSET_EVENT:T')}
    if motion_takes and event_takes and not motion_takes <= event_takes:
        issues.append('motion gameplay frames and asset events must come from the same take')
    has = lambda *prefixes: any(i.startswith(prefixes) for i in ids)
    mode = row['mode']
    # Import's 50 tier concerns a confirmed slot replacement, which can also be
    # established by actual authored assignments / serialized bindings before playback.
    binding_source = (row.get('metric') == 'import' and part == 'basic_function' and has('SRC:'))
    if mode == 'static' and not has('SRC:', 'DOC:'):
        issues.append('static check needs a SRC:/DOC: citation')
    if row['metric'] in ('asset_slot', 'code') and not has('SRC:'):
        issues.append('asset/code check needs an authored SRC: citation')
    timed = row.get('metric') == 'import' and row.get('asset_kind') in ('motion', 'audio', 'cg_video')
    if mode in ('visual', 'reference') and not (binding_source or has('FRAME:') or (row.get('asset_id') and has('VIEW:'))
                                               or (timed and has('ASSET_EVENT:'))
                                               or (timed and row.get('asset_kind') == 'audio' and has('AUDIO:'))
                                               or (timed and row.get('asset_kind') == 'motion' and has('MOTION:'))):
        issues.append('visual check needs a FRAME (or, for an imported asset, VIEW or timed asset evidence) citation')
    if part == 'result_outcome' and timed and row.get('asset_kind') == 'motion' and has('ASSET_EVENT:') and not has('MOTION:', 'FRAME:'):
        issues.append('motion result needs native gameplay MOTION frames (or FRAME) to assess playback and any obvious deformation')
    if mode == 'reference' and not binding_source and not has('REF:'):
        issues.append('reference check needs a REF: citation')
    if mode == 'runtime':
        if row['id'] == 'play.launch':
            if not (has('STATE', 'FRAME:') and has('LOG')):
                issues.append('launch check needs STATE or FRAME plus LOG evidence')
        # An ACTION citation is never a precondition: frames are already captured around the actions.
        elif part == 'result_outcome':
            # Stage3 import of a timed asset (motion / audio / cg_video): the recorder's own event for that asset
            # (ASSET_EVENT) is the result evidence for "triggered at the right time"; motion also needs native gameplay MOTION frames.
            if not (has('FRAME:') or (row.get('asset_id') and has('VIEW:', 'MOTION:')) or (timed and has('ASSET_EVENT'))
                      or (log_ok and has('EVENT', 'LOG', 'STATE', 'AUDIO', 'ASSET_EVENT'))):
                issues.append('result tier needs a real FRAME (or VIEW, or for binary checks a game log/state postcondition) citation')
        elif not binding_source and not has('STATE', 'FRAME:', 'EVENT', 'LOG', 'ASSET_EVENT'):
            issues.append('runtime check needs observed STATE, FRAME, EVENT or LOG evidence')
    if mode == 'import' and not binding_source and not has('IMPORT', 'LOG'):
        issues.append('import check needs an import/engine log citation')
    return issues


def enforce(row: dict, verdict: dict, delivered: dict, standard: dict | None = None, *, metrics: dict) -> dict:
    """Downgrade claims whose citations (or frozen trigger modes) do not hold; keep the reasons."""
    verdict = json.loads(json.dumps(verdict))
    if metrics[row['metric']].FORMAT == 'binary':
        issues = _check_refs(row, verdict['evidence'], delivered) if verdict['status'] != 'UNVERIFIED' else []
        if verdict['status'] == 'FAIL' and not verdict['counterexample'].strip():
            issues.append('FAIL without counterexample')
        if row['mode'] == 'runtime' and verdict['status'] == 'PASS' and not (
                verdict['preconditions_met'] and verdict['observation_complete']):
            issues.append('runtime PASS without met preconditions / complete observation')
        if issues:
            verdict['status'] = 'UNVERIFIED'
    else:
        issues = []
        withdraw = {'source_existence': 'UNVERIFIED', 'basic_function': 'UNOBSERVED', 'result_outcome': 'NOT_PROVEN'}
        static_like = dict(row, mode='static')
        for part, fallback in withdraw.items():
            body = verdict[part]
            if body['status'] in ('EXISTS', 'NORMAL', 'ACHIEVED'):
                bad = _check_refs(static_like if part == 'source_existence' else row, body['evidence'], delivered, part,
                                  log_ok=getattr(metrics[row['metric']], 'RESULT_FROM_LOG', False))
                if bad:
                    issues += [f'{part}: {b}' for b in bad]
                    body['status'] = fallback
        permitted = (standard or {}).get('permitted_trigger_modes')
        if permitted and verdict['basic_function']['trigger_mode'] not in permitted:
            issues.append(f'trigger_mode {verdict["basic_function"]["trigger_mode"]} not in frozen {permitted}')
            for part in ('basic_function', 'result_outcome'):
                if verdict[part]['status'] in ('NORMAL', 'ACHIEVED'):
                    verdict[part]['status'] = withdraw[part]
    verdict['validation_issues'] = issues
    return verdict


OWN_SHARE = 0.6        # share of a multi-check call's image bytes reserved for the checks' own action frames


def _own_sheets(evidence: dict, ids: set) -> list:
    sheet_of = {it['id']: it['sheet'] for it in evidence['items'] if it['type'] == 'frame'}
    return list(dict.fromkeys(sheet_of[f] for l in evidence['action_links'] if ids & set(l['criterion_ids'])
                              for role in ('during', 'after', 'before') for f in l['frames'][role] if f in sheet_of))


def _sheet_bytes(root: Path, sheets) -> int:
    return sum((Path(root) / 'delivery' / s).stat().st_size for s in sheets if (Path(root) / 'delivery' / s).exists())


def size_shards(rows: list, max_rows: int, evidence: dict, root: Path) -> list:
    """Group checks so every check's own action-frame sheets fit into its call (never resizing images):
    a group grows while its checks' own sheets fit in OWN_SHARE of the per-call byte budget; a check whose
    own sheets alone are larger is judged alone (it may then use the whole budget)."""
    refs = [it for it in evidence['items'] if it['type'] == 'image' and not it['id'].startswith(('VIEW:', 'SRCVIEW:', 'MOTION:'))]
    budget = MAX_IMAGE_BYTES - sum(os.path.getsize(r['path']) for r in refs if os.path.exists(r['path']))
    n_refs = len(refs)
    shards, cur = [], []
    for r in rows:
        trial = cur + [r]
        own = _own_sheets(evidence, {x['id'] for x in trial})
        need = _sheet_bytes(root, own)
        if cur and (len(trial) > max_rows or need > OWN_SHARE * budget
                    or len(own) > OWN_SHARE * (MAX_IMAGES - n_refs)):
            shards.append(cur)
            cur = [r]
        else:
            cur = trial
    if cur:
        shards.append(cur)
    return shards


def shard_images(evidence: dict, root: Path, shard_ids: set, delivered: dict):
    """Images for one call: reference images, then sheets holding this shard's action frames,
    then other sheets, up to MAX_IMAGES. Frames on unsent sheets become uncitable."""
    # Reference images, plus only this shard's asset views.
    refs = [it for it in evidence['items'] if it['type'] == 'image'
            and (not it['id'].startswith(('VIEW:', 'SRCVIEW:', 'MOTION:')) or shard_ids & set(it.get('check_ids', [])))]
    sheet_of = {it['id']: it['sheet'] for it in evidence['items'] if it['type'] == 'frame'}
    own = [sheet_of[f] for l in evidence['action_links'] if shard_ids & set(l['criterion_ids'])
           for role in ('during', 'after', 'before') for f in l['frames'][role] if f in sheet_of]
    own = [it['sheet'] for it in evidence['items'] if it['type'] == 'frame'
           and any(shard_ids & set(ep['check_ids']) for ep in it.get('video_endpoints', []))] + own
    # this shard's action frames, then frames right after the game's own logged events, then the rest
    order = list(dict.fromkeys(own + list(evidence.get('event_sheets', [])) + list(evidence['sheets'])))
    refs = refs[:MAX_IMAGES]
    # Byte budget per request (encoded images must stay under the provider's request limit):
    # images keep their native pixels; lower-priority sheets are left out instead.
    import os
    budget = MAX_IMAGE_BYTES - sum(os.path.getsize(r['path']) for r in refs if os.path.exists(r['path']))
    size = lambda sh: (Path(root) / 'delivery' / sh).stat().st_size if (Path(root) / 'delivery' / sh).exists() else 0
    own_sheets = list(dict.fromkeys(own))
    events_first = [x for x in dict.fromkeys(evidence.get('event_sheets', [])) if x not in own_sheets]
    rest = [x for x in order if x not in own_sheets and x not in events_first]
    sheets, cap = [], MAX_IMAGES - len(refs)
    def fill(candidates, limit):
        nonlocal budget
        for sheet in candidates:
            if len(sheets) + len(extra_paths) >= cap or sheet in sheets:
                continue
            b = size(sheet)
            if sheets and (b > budget or b > limit[0]):
                continue
            sheets.append(sheet); budget -= b; limit[0] -= b
    extra_paths = []
    own_limit = budget if len(shard_ids) == 1 else OWN_SHARE * budget
    own_count = cap if len(shard_ids) == 1 else max(1, int(OWN_SHARE * cap))
    regridded = set()
    if sum(size(x) for x in own_sheets) <= own_limit and len(own_sheets) <= own_count:
        fill(own_sheets, [own_limit])
    else:
        # Own frames do not fit natively: keep native 2x2 sheets while the rest still fits as compact 3x3
        # grids (tiles downscaled, raw frames kept on disk) - every own frame reaches the judge.
        from ..evidence.evidence import _grid_sheets
        import hashlib
        frame_items = {it['id']: it for it in evidence['items'] if it['type'] == 'frame'}
        frames_of = {sh: [i for i, it in frame_items.items() if it['sheet'] == sh] for sh in own_sheets}
        tag = hashlib.sha1(','.join(sorted(shard_ids)).encode()).hexdigest()[:10]
        folder = Path(root) / 'delivery' / f'ondemand_{tag}'
        probe_dir = folder / 'probe'
        probe_dir.mkdir(parents=True, exist_ok=True)
        allf = [f for sh in own_sheets for f in frames_of[sh]]
        as_rows = lambda ids: [{'id': f, 't_ms': frame_items[f].get('t_ms', 0), 'path': Path(frame_items[f]['path'])} for f in ids]
        probe = _grid_sheets(as_rows(allf), allf, probe_dir, 0)
        per_frame = sum((probe_dir / n).stat().st_size for n in {t['sheet'] for t in probe}) / max(1, len(allf))
        import math
        def grids_needed(n, g=3):
            return math.ceil(n / (g * g)) if n else 0
        keep, used = [], 0
        for sh in own_sheets:
            n_left = sum(len(frames_of[x]) for x in own_sheets if x not in keep and x != sh)
            if (used + size(sh) + per_frame * n_left * 1.15 <= own_limit
                    and len(keep) + 1 + grids_needed(n_left) <= own_count):
                keep.append(sh); used += size(sh)
        fill(keep, [own_limit])
        regrid = [f for sh in own_sheets if sh not in keep for f in frames_of[sh]]
        room = max(1, own_count - len(keep))
        g = next((g for g in (3, 4, 5, 6) if grids_needed(len(regrid), g) <= room), 6)   # denser only if needed
        tiles = _grid_sheets(as_rows(regrid), regrid, folder, 0, grid=g)
        for name in dict.fromkeys(t['sheet'] for t in tiles):
            p_ = folder / name
            if len(sheets) + len(extra_paths) >= cap or (extra_paths and p_.stat().st_size > budget):
                break
            extra_paths.append(str(p_)); budget -= p_.stat().st_size
            regridded |= {t['id'] for t in tiles if t['sheet'] == name}
    fill(events_first, [budget])                # then the game's logged-event frames (compact grids)
    fill(own_sheets + rest, [budget])           # then whatever still fits
    sent = set(sheets)
    allowed = {k: v for k, v in delivered.items()
               if not (k in sheet_of and sheet_of[k] not in sent and k not in regridded)
               and not (k.startswith(('REF:', 'VIEW:', 'SRCVIEW:', 'MOTION:')) and k not in {r['id'] for r in refs})}
    paths = [r['path'] for r in refs] + [str(Path(root) / 'delivery' / s) for s in sheets] + extra_paths
    note = (f'\nIMAGES SENT IN THIS CALL: {len(refs)} reference image(s), sheets {sheets}'
            + (f' and compact grids {[Path(p).name for p in extra_paths]} (downscaled tiles of this check\'s own '
               'frames that did not fit natively)' if extra_paths else '')
            + '. Only frames on these images can be cited.\n') if (len(order) > len(sheets) or extra_paths) else ''
    return paths, allowed, note


def _shard_index(text: str, evidence: dict, shard_ids: set, allowed: dict, call_images) -> str:
    """Per-call ACTION / PROBE INDEX and IMAGE ID MAP: only this call's checks' actions and the frames / images
    actually sent in this call (whole-run indexes grew with every take and pushed the CLI into compacting the
    conversation, which drops the attached images - 2026-11-11). Channel text and source access unchanged."""
    head = text.split('\n\nACTION / PROBE INDEX\n', 1)[0]
    sent = {Path(p).name for p in call_images}
    links = []
    for l in evidence['action_links']:
        if not shard_ids & set(l['criterion_ids']):
            continue
        frames = {role: [f for f in ids if f in allowed] for role, ids in (l.get('frames') or {}).items()}
        links.append({k: l.get(k) for k in ('take', 'action_line', 'action_id', 'criterion_ids', 't_ms')} | {'frames': frames})
    imap = []
    for it in evidence['items']:
        if it['type'] == 'frame' and it['id'] in allowed:
            imap.append({'id': it['id'], 't_ms': it['t_ms'],
                         'sheet': it['sheet'] if it['sheet'] in sent else 'compact grid (find the id in the tile label)'})
        elif it['type'] == 'image' and it['id'] in allowed and Path(it['path']).name in sent:
            imap.append({'id': it['id'], 'path': Path(it['path']).name})
    return (head + '\n\nACTION / PROBE INDEX (this call\'s checks)\n' + json.dumps(links, ensure_ascii=False)
            + '\n\nIMAGE ID MAP (images sent in this call)\n' + json.dumps(imap, ensure_ascii=False))


def _consistent(reply: dict, rows: list[dict], metrics: dict) -> None:
    """Reject self-contradictory tiered verdicts (e.g. BUG without a counterexample) so the
    model gets its one bounded correction; scoring rules are unchanged."""
    problems = []
    for r in rows:
        m = metrics[r['metric']]
        if m.FORMAT != 'tiered':
            continue
        try:
            m.credit(r, reply['checks'][r['id']])
        except ValueError as exc:
            problems.append(f'{r["id"]}: {exc}')
    if problems:
        raise ValueError('self-contradictory verdicts: ' + '; '.join(problems))


def _schema(rows: list[dict], metrics: dict) -> dict:
    return obj({'summary': S, 'limitations': arr(S),
                'checks': obj({r['id']: metrics[r['metric']].item_schema() for r in rows})})


def judge(out: Path, manifest: dict, evidence: dict, kind: str, standards: dict | None = None,
          only_ids=None, tag: str = '') -> dict:
    """Judge all rows of ``kind`` ('static' or 'evidence'), or just ``only_ids``; reuse accepted shards.

    ``standards`` = {metric: frozen standard} for tiered metrics (required when
    such rows are judged). ``tag`` names this pass (e.g. ``_t2``) so every pass
    keeps its own model calls and verdict file."""
    standards = standards or {}
    metrics = suites.get(manifest.get('suite', 'stage1')).metrics
    out = Path(out)
    target = out / f'verdicts_{kind}{tag}.json'
    if target.is_file():
        return read_json(target)
    rows = [r for r in read_json(out / 'input' / 'criteria.json')['criteria']
            if (r['mode'] == 'static') == (kind == 'static')]
    if only_ids is not None:
        wanted = set(only_ids)
        rows = [r for r in rows if r['id'] in wanted]
    rows = [r for r in rows if not getattr(metrics[r['metric']], 'RULE_BASED', False)]   # decided by rules
    if not rows:
        write_json(target, {})
        return {}
    text, delivered, images = packet({**evidence, '_root': str(out)}, kind)
    verdicts = {}
    shards = []
    for fmt in ('binary', 'tiered'):                 # never mix formats; size each by its verdict length
        same = [r for r in rows if metrics[r['metric']].FORMAT == fmt]
        if kind == 'evidence' and evidence.get('takes'):
            shards += size_shards(same, SHARD_SIZE[fmt], evidence, out)
        else:
            shards += [same[i:i + SHARD_SIZE[fmt]] for i in range(0, len(same), SHARD_SIZE[fmt])]
    def run_shard(n: int, shard: list):
        checks = []
        for r in shard:
            check = {'id': r['id'], 'metric': r['metric'], 'format': metrics[r['metric']].FORMAT,
                     'mode': r['mode'], 'group': r['group'], 'requirement': r['requirement']}
            if manifest.get('suite') == 'stage3' and r['metric'] == 'import':
                check.update(asset_id=r.get('asset_id'), asset_kind=r.get('asset_kind'),
                             current_scoring_policy='2026-11-24: code=10; confirmed slot replacement=50; '
                             'type-specific real gameplay result=100. basic_function judges replacement; '
                             'result_outcome judges gameplay. Current import rules override conflicting old '
                             'tier gates, whole-scene appearance requirements and audio caps in frozen_standard.')
            if metrics[r['metric']].FORMAT == 'tiered':
                if r['metric'] not in standards:
                    raise ValueError(f'{r["id"]}: tiered metric judged without its frozen standard')
                check['frozen_standard'] = standards[r['metric']]['checks'][r['id']]
            checks.append(check)
        rules = '\n'.join(metrics[m].JUDGE_RULES for m in dict.fromkeys(r['metric'] for r in shard)
                          if hasattr(metrics[m], 'JUDGE_RULES'))
        name = f'{kind}{tag}_{n:02d}'
        call_text = text
        if kind == 'evidence':
            call_images, allowed, note = shard_images(evidence, out, {r['id'] for r in shard}, delivered)
            call_text = _shard_index(text, evidence, {r['id'] for r in shard}, allowed, call_images)
        else:
            call_images, allowed, note = (), delivered, ''
        if kind == 'evidence' and evidence.get('direct_trigger'):
            dt = evidence['direct_trigger']
            note += ('\nDIRECT TRIGGER TAKE: the evaluator started these features by calling the game\'s own functions '
                     '(input handler first, then the feature entry; setup via the game\'s save / load): '
                     + json.dumps(dt.get('calls'), ensure_ascii=False)[:3000] + ' Engine results: '
                     + json.dumps(dt.get('results'), ensure_ascii=False)[:1500] + ' Expected postconditions: '
                     + json.dumps(dt.get('postconditions'), ensure_ascii=False)[:2000]
                     + '. Judge whether the game itself then produced each check\'s frozen target outcome: ACHIEVED only '
                       'with a result FRAME or the game\'s own log / state line proving the postcondition (cite it); '
                       'a wrong result, error or crash is BUG / CONTRADICTED; the calls alone prove nothing.\n')
        if kind == 'evidence' and evidence.get('state_entry'):
            se = evidence['state_entry']
            note += ('\nSTATE-CONDITIONED TAKE: before any player input the evaluator put the game into "'
                     + str(se.get('target_state')) + '" by calling the game\'s own existing members: '
                     + json.dumps(se.get('calls'), ensure_ascii=False) + f' (state reached: {se.get("state_reached")}). '
                     'Progress the entry does not recreate (earlier scores, history) is absent: do not report its '
                     'absence as a bug. Judge only what the player input after the entry produced; the entry '
                     'calls themselves are not evidence that the tested behaviour works.\n')
        if kind == 'evidence' and not evidence.get('takes'):
            note += ('\nSOURCE-ONLY CALL: no runtime evidence exists (nothing was played or recorded). '
                     'Judge source_existence; for import also judge confirmed slot replacement from authored binding evidence, '
                     'without claiming playback. For other tiered checks set basic_function.status=UNOBSERVED '
                     'and result_outcome.status=NOT_PROVEN (frame_assessment=no_frame); binary runtime/visual '
                     'checks are UNVERIFIED. Never report BUG/CONTRADICTED/FAIL without an observed counterexample.\n')
        reply = accepted_response(out / 'model_calls', name) or call_model(out / 'model_calls', name=name,
                           prompt=f'{INSTRUCTIONS}\n{rules}\nCHECKS (input list only; output checks MUST be an object keyed by id, not an array)\n{json.dumps(checks, ensure_ascii=False)}\n{note}\n{call_text}',
                           schema=_schema(shard, metrics), cwd=out / 'input', images=call_images,
                           validator=lambda reply, rows=shard: _consistent(reply, rows, metrics),
                           model=manifest['models']['judge'], timeout=manifest['budget']['judge_timeout_s'])
        return {r['id']: enforce(r, reply['checks'][r['id']], allowed,
                                 standards.get(r['metric'], {}).get('checks', {}).get(r['id']), metrics=metrics)
                for r in shard}

    # Shards are independent model calls: run them concurrently. A failed shard does not
    # stop the others, so their accepted replies are kept and a rerun only redoes the failure.
    failures = []
    with ThreadPoolExecutor(max_workers=max(1, JUDGE_PARALLEL)) as pool:
        futures = {pool.submit(run_shard, n, shard): n for n, shard in enumerate(shards, 1)}
        for future in as_completed(futures):
            try:
                verdicts.update(future.result())
            except Exception as exc:          # noqa: BLE001 - reported after all shards finish
                failures.append((futures[future], exc))
    if failures:
        n, exc = min(failures, key=lambda f: f[0])
        raise exc
    write_json(target, verdicts)
    return verdicts