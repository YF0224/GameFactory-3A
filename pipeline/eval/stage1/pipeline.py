"""Stage1 evaluation of one delivery: every metric in a single run.

    prepare -> static judge -> approved benchmark standards (frozen ahead of time, model-independent)
    -> take 1..MAX_TAKES: plan -> native record -> evidence (union of takes) -> evidence judge
    -> score

Take 1 plans every runtime criterion. A later take re-plans only criteria that
still have no runtime evidence (tiered credit <= 10% without an observed bug,
binary UNVERIFIED), with the earlier plans and judge reasons as feedback, and
re-judges only those criteria on the union of all takes. It stops after
MAX_TAKES takes, or as soon as a take resolves nothing new. The same take limit
applies to every model. Each criterion's final verdict is its latest judgment.

Each step persists its result and is skipped when that result already exists,
so an interrupted run resumes from its last finished step without repeating
model calls or recordings. A tool failure (``HarnessError``) stops the run and
is written to ``status.json``; it is never turned into a product score.
Rows without a verdict leave their metric unscored (``None``), never zero.
"""
from __future__ import annotations

import json
import os
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import asset_views, budgets, evidence, playable_rules, judge, plan, prepare, record, standards, state_entry
from .llm import HarnessError
from ..model_config import EVALUATION_PLANNER_MODEL, JUDGE_MODEL
from . import suites
from .paths import read_json, write_json

VERSION = 'stage1-pipeline.v1'
STEPS = ('prepare', 'static_judge', 'standards', 'plan_tN', 'record_tN', 'evidence_tN', 'evidence_judge_tN', 'score')
DEFAULT_MODELS = {'planner': EVALUATION_PLANNER_MODEL, 'judge': JUDGE_MODEL}


PROJECT_BUDGET_S = float(os.environ.get('A3GAME_PROJECT_BUDGET_S', 3600))
BATCH = int(os.environ.get('A3GAME_PLAN_BATCH', 12))          # stage3: checks per take (full-coverage batches)
BATCH_MAX_TAKES = int(os.environ.get('A3GAME_MAX_TAKES', 12))
BATCH_TAKE_BUDGET_S = float(os.environ.get('A3GAME_TAKE_BUDGET_S', 1200))


def _status(out: Path, step: str, state: str, **extra) -> None:
    write_json(out / 'status.json', {'version': VERSION, 'step': step, 'state': state,
                                     'updated_at': datetime.now(timezone.utc).isoformat(), **extra})


def final_verdicts(out: Path, upto: int = plan.MAX_TAKES) -> dict:
    """Latest judgment of every criterion: static, then evidence takes 1..upto in order."""
    verdicts = {}
    found = sorted(int(p.stem.rsplit('_t', 1)[1]) for p in out.glob('verdicts_evidence_t[0-9]*.json')
                   if p.stem.rsplit('_t', 1)[1].isdigit())
    names = (['verdicts_static.json', 'verdicts_evidence_t0.json']
             + [f'verdicts_evidence_t{k}.json' for k in found if 0 < k <= max(upto, BATCH_MAX_TAKES)])
    # texture_src/: texture re-judged against the original asset render (overrides the take verdicts)
    # verdicts_evidence_lean.json: mechanic / gamefeel re-judged on the same evidence under the lean
    # rubric; texture_src/: texture against the original-asset render. Both override the take verdicts.
    for name in names + ['verdicts_playable_rules.json', 'verdicts_evidence_lean.json',
                         'texture_src/verdicts_evidence_tex.json']:
        if (out / name).is_file():
            verdicts.update(read_json(out / name))
    return verdicts


def unresolved(rows: list[dict], verdicts: dict, metrics: dict) -> list[str]:
    """Runtime criteria never observed at runtime (source tier at most, no observed product bug)."""
    ids = []
    for r in rows:
        if r['mode'] == 'static' or r['id'] not in verdicts:
            continue
        v, metric = verdicts[r['id']], metrics[r['metric']]
        if metric.FORMAT == 'binary':
            if v['status'] == 'UNVERIFIED':
                ids.append(r['id'])
            continue
        if v['basic_function']['status'] == 'BUG' or v['result_outcome']['status'] == 'CONTRADICTED':
            continue                          # a product problem was observed; another take cannot change it
        try:
            c = metric.credit(r, v)             # binary: None = UNVERIFIED (another take may decide it)
            low = c is None or c <= 0.1
        except ValueError:
            low = True
        if low:
            ids.append(r['id'])
    return ids


def _feedback(out: Path, take: int, ids: list[str], verdicts: dict) -> dict:
    earlier = []
    for k in range(1, take):
        folder = plan.take_dir(out, k)
        if not (folder / 'plan.json').is_file():      # a take whose plan was never accepted (recorded as failed)
            continue
        p = read_json(folder / 'plan.json')
        earlier.append({'take': k, 'summary': p['summary'],
                        'probes': [{'id': x['id'], 'purpose': x['purpose'], 'criterion_ids': x['criterion_ids']}
                                   for x in p['probes']]})
    reasons = {}
    for i in ids:
        v = verdicts.get(i, {})
        reasons[i] = (v.get('reason') or ' | '.join(v[part]['reason'] for part in ('basic_function', 'result_outcome')
                                                    if part in v))[:400]
    fb = {'earlier_plans': earlier, 'judge_reasons': reasons}
    tele = game_telemetry(out, take)
    if tele:
        fb['game_log_from_earlier_takes'] = tele
    sig = signal_results(out, take, ids)
    if sig:
        fb['trigger_signals'] = sig
    return fb


TELEMETRY_CHARS = int(os.environ.get('A3GAME_TELEMETRY_CHARS', 14000))
SEED_PLANS = os.environ.get('A3GAME_SEED_PLANS') == '1'
SEED_CHARS = int(os.environ.get('A3GAME_SEED_CHARS', 30000))


def seed_run(out: Path) -> Path | None:
    """The most recent earlier eval dir of the same game (same model folder) that has planned takes."""
    cands = [d for d in Path(out).parent.iterdir() if d.is_dir() and d.resolve() != Path(out).resolve()
             and ('_refine_eval_' in d.name or '_opus_plan_' in d.name) and any(d.glob('takes/*/plan.json'))
             and any(d.glob('verdicts_evidence_t[0-9]*.json'))]          # real evaluation runs, not test copies
    return max(cands, key=lambda d: max(p.stat().st_mtime for p in d.glob('takes/*/plan.json'))) if cands else None


def seed_feedback(out: Path, ids: list) -> dict | None:
    """Previous run's plans for these checks, the outcome of each, its game log and Direct Trigger calls, so the
    planner repairs earlier plans instead of starting blind (A3GAME_SEED_PLANS=1). Data only."""
    if not SEED_PLANS:
        return None
    src = seed_run(out)
    if src is None:
        return None
    want = set(ids)
    probes, outcomes = [], {}
    takes = sorted(int(p.parent.name) for p in src.glob('takes/*/plan.json') if p.parent.name.isdigit())
    for k in takes:
        p = read_json(src / 'takes' / str(k) / 'plan.json')
        for pr in p.get('probes', []):
            if want & set(pr.get('criterion_ids', [])):
                probes.append({'take': k, 'id': pr['id'], 'criterion_ids': [c for c in pr['criterion_ids'] if c in want],
                               'purpose': pr.get('purpose'), 'steps': pr.get('steps')})
        if p.get('state_entry'):
            se = p['state_entry']
            if want & set(se.get('applies_to') or []):
                probes.append({'take': k, 'direct_or_state_entry_calls': se.get('calls'),
                               'applies_to': [c for c in se.get('applies_to') or [] if c in want]})
    verdicts = {}
    for f in sorted(src.glob('verdicts_evidence_[td]*.json')):
        try:
            verdicts.update({i: v for i, v in read_json(f).items() if i in want})
        except (OSError, ValueError):
            pass
    for i, v in verdicts.items():
        if isinstance(v, dict) and 'basic_function' in v:
            outcomes[i] = {'basic': v['basic_function'].get('status'), 'result': v['result_outcome'].get('status'),
                           'reason': (v['result_outcome'].get('reason') or v['basic_function'].get('reason') or '')[:300]}
    tele = game_telemetry(src, (max(takes) + 1) if takes else 1)
    seed = {'run': src.name, 'probes': probes, 'outcomes': outcomes, 'game_log': tele}
    text = json.dumps(seed, ensure_ascii=False)
    while len(text) > SEED_CHARS and seed['game_log']:
        seed['game_log'] = seed['game_log'][:-1]                # oldest takes' logs go first
        text = json.dumps(seed, ensure_ascii=False)
    while len(text) > SEED_CHARS and len(seed['probes']) > 1:
        seed['probes'] = seed['probes'][-max(1, len(seed['probes']) * 2 // 3):]   # keep the latest plans
        text = json.dumps(seed, ensure_ascii=False)
    return seed


def game_telemetry(out: Path, take: int) -> list:
    """What the game itself logged in the last earlier takes (event_trace.jsonl): repeated lines collapsed with a
    count and first / last time, newest take first, so a retry plan can correct its route / aim from real positions,
    focus, traces and state changes instead of only the judge's verdict."""
    result, budget = [], TELEMETRY_CHARS
    for k in range(take - 1, 0, -1):
        f = plan.take_dir(out, k) / 'record' / 'event_trace.jsonl'
        if not f.is_file() or budget <= 0:
            continue
        groups = {}
        for line in f.read_text(errors='replace').splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            msg = str(e.get('message', ''))[:220]
            key = ' '.join(w for w in msg.split() if not any(ch.isdigit() for ch in w))[:90] or msg[:90]
            g = groups.setdefault(key, {'n': 0, 'first_ms': e.get('t_ms'), 'rows': []})
            g['n'] += 1
            g['rows'].append((e.get('t_ms') or 0, msg))
        lines = []
        for g in sorted(groups.values(), key=lambda g: g['first_ms'] or 0):
            rows = g['rows']
            if len(rows) <= 15:            # rare lines (traces, interactions, state changes): every one, with time
                lines += [f"t={round(t)}ms {m}"[:400] for t, m in rows]
            else:                          # frequent lines (pose / view ticks): first, 5 samples, last
                idx = sorted({0, len(rows) - 1, *[round(i * (len(rows) - 1) / 6) for i in range(1, 6)]})
                lines.append(f"[{len(rows)} lines like this, sampled]")
                lines += [f"t={round(rows[i][0])}ms {rows[i][1]}"[:400] for i in idx]
        text = '\n'.join(lines)
        if len(text) > budget:
            text = text[:budget] + '\n...(truncated)'
        budget -= len(text)
        result.append({'take': k, 'game_log': text})
    return result


def signal_results(out: Path, take: int, ids: list) -> dict:
    """Per check: the trigger log signal the planner declared and whether the game printed it in each take."""
    res = {}
    for k in range(1, take):
        f = plan.take_dir(out, k) / 'trigger_signals.json'
        if not f.is_file():
            continue
        for i, r in read_json(f).get('signals', {}).items():
            if i in ids:
                res.setdefault(i, []).append({'take': k, **r})
    return res


def check_trigger_signals(out: Path, take: int) -> dict:
    """After a take: which declared trigger log lines the game actually printed (no model call)."""
    folder = plan.take_dir(out, take)
    p = read_json(folder / 'plan.json') if (folder / 'plan.json').is_file() else {}
    ev = folder / 'record' / 'event_trace.jsonl'
    text = ev.read_text(errors='replace') if ev.is_file() else ''
    lines = text.splitlines()
    signals = {}
    for sgl in p.get('trigger_signals', []) or []:
        sub = (sgl.get('log_substring') or '').strip()
        if not sub:
            continue
        hits = [l for l in lines if sub in l]
        for cid in sgl.get('criterion_ids') or []:
            signals[cid] = {'log_substring': sub, 'seen': bool(hits), 'times_seen': len(hits),
                            'first': json.loads(hits[0]).get('t_ms') if hits else None}
    result = {'take': take, 'signals': signals, 'seen': sorted(i for i, r in signals.items() if r['seen'])}
    write_json(folder / 'trigger_signals.json', result)
    return result


def score(out: Path, provisional: bool = False) -> dict:
    rows = read_json(out / 'input' / 'criteria.json')['criteria']
    verdicts = final_verdicts(out)
    manifest = read_json(out / 'manifest.json')
    if manifest.get('suite') == 'stage3':
        # declared trigger log lines the game printed in any normal take (pipeline.check_trigger_signals)
        seen = set()
        for f in out.glob('takes/*/trigger_signals.json'):
            if f.parent.name.isdigit():
                seen |= set(read_json(f).get('seen', []))
        verdicts = {i: ({**v, '_trigger_signal_seen': True} if i in seen and isinstance(v, dict) else v)
                    for i, v in verdicts.items()}
    tracks = None
    if manifest.get('suite') == 'stage3' and (out / 'direct_trigger.json').is_file():
        metrics_ = suites.get('stage3').metrics
        direct = direct_verdicts(out, rows, metrics_)
        tracks = {'normal': {}, 'direct': {}, 'used_direct': []}
        for r in rows:
            i = r['id']
            if r['mode'] == 'static' or metrics_[r['metric']].FORMAT != 'tiered':
                continue
            try:
                nc = metrics_[r['metric']].credit(r, verdicts[i]) if i in verdicts else None
            except ValueError:
                nc = None
            tracks['normal'][i] = nc
            if i in direct:
                tracks['direct'][i] = direct[i][0]
                if nc is None:                    # Direct only fills UNVERIFIED; a normal FAIL stays 0
                    verdicts = {**verdicts, i: direct[i][1]}
                    tracks['used_direct'].append(i)
    clean_direct = {}
    if manifest.get('suite') == 'stage3' and (out / 'direct_trigger.json').is_file():
        # user decision 2026-11-11: Direct Trigger ran the game's own functions and that take's game log is clean
        # (no error / exception lines, no crash) but no frame proves the result -> 50%
        metrics_ = suites.get('stage3').metrics
        clean = direct_clean_runs(out)
        for r in rows:
            i = r['id']
            if r['mode'] == 'static' or metrics_[r['metric']].FORMAT != 'tiered' or i not in verdicts or i not in clean:
                continue
            try:
                c = metrics_[r['metric']].credit(r, verdicts[i])
            except ValueError:
                continue
            if c is None:
                verdicts = {**verdicts, i: {**verdicts[i], '_direct_clean_run': True}}
                clean_direct[i] = clean[i]
    absent = {}
    if manifest.get('suite') == 'stage3' and _direct_book(out / 'direct_trigger.json').get('complete'):
        # Absence = FAIL, only once normal play and all Direct Trigger rounds are done.
        metrics_ = suites.get('stage3').metrics
        tried = tried_checks(out)
        for r in rows:
            i = r['id']
            if r['mode'] == 'static' or metrics_[r['metric']].FORMAT != 'tiered' or i not in verdicts:
                continue
            v = verdicts[i]
            if any(v[x]['status'] == 'HARNESS_ERROR' for x in ('source_existence', 'basic_function', 'result_outcome')):
                continue                                   # tool fault: UNVERIFIED
            try:
                c = metrics_[r['metric']].credit(r, v)
            except ValueError:
                continue
            if c is None and i in tried and not v.get('_direct_clean_run'):
                verdicts = {**verdicts, i: {**v, '_not_observed_fail': True}}
                absent[i] = tried[i]
    result = suites.get(manifest.get('suite', 'stage1')).score(rows, verdicts)
    if clean_direct:
        result['direct_clean_run_50'] = {
            'note': 'Direct Trigger ran the game\'s own functions, the take\'s game log has no error / exception / crash, '
                    'but no frame proved the result: 50%', 'checks': clean_direct}
    if absent:
        result['fail_not_observed'] = {
            'note': 'tried (normal-play input sent or Direct Trigger call ran) but the expected behaviour never appeared '
                    'in any event frame or game log, after normal play and all Direct Trigger rounds',
            'checks': absent}
    if tracks is not None:
        vals = lambda d: [v for v in d.values() if v is not None]
        result['tracks'] = {
            'note': 'binary PASS 1 / FAIL 0 / UNVERIFIED; Direct Trigger fills only checks normal play left UNVERIFIED',
            'normal_play': {'decided': len(vals(tracks['normal'])), 'pass': sum(1 for v in vals(tracks['normal']) if v == 1.0)},
            'direct_trigger': {'decided': len(vals(tracks['direct'])), 'pass': sum(1 for v in vals(tracks['direct']) if v == 1.0)},
            'checks_decided_by_direct_trigger': tracks['used_direct'], 'per_check': {
                i: {'normal': tracks['normal'].get(i), 'direct': tracks['direct'].get(i)} for i in tracks['normal']}}
        result['tracks'].update(direct_coverage(out, tracks))
    result.update(game_id=manifest['game_id'], suite=manifest.get('suite', 'stage1'), status='SCORED_PENDING_AUDIT'
                  if result['complete'] else 'INCOMPLETE', audit_status='未审计')
    # stage3: import = assets that got into the project (rules); texture = imported 3D assets that look
    # like the originals (0/1 per asset). They replace the judged versions, kept under 'judged_*'.
    if manifest.get('suite') == 'stage3':
        dims = result.get('dimensions', {})
        tex = 'texture_ingame.json'
        if not (out / tex).is_file():
            # Texture is defined only by the in-game comparison (mean 0/1). Without it the dimension is
            # unscored with its reason - never the per-check judged rows (10/50/100) or older methods.
            if 'texture' in dims:
                dims['judged_texture'] = dims.pop('texture')
            err = out / 'texture_ingame_error.json'
            dims['texture'] = {'name': 'Texture', 'S': None, 'Cov': 0.0, 'published': False, 'checks': 0,
                               'source': 'texture_ingame.json (missing)',
                               'not_scored_reason': read_json(err)['error'][:400] if err.is_file()
                               else 'no in-game asset shots / texture comparison not run'}
        for key, file in (('import', 'import_presence.json'), ('texture', tex)):
            if (out / file).is_file():
                d = read_json(out / file)
                if key in dims:
                    dims[f'judged_{key}'] = dims.pop(key)
                n = d.get('required') if key == 'import' else d.get('N', len(d.get('assets', {})))
                dims[key] = {'name': key.capitalize(), 'S': d['S'], 'Cov': 1.0 if d['S'] is not None else 0.0,
                             'published': d['S'] is not None, 'checks': n,
                             'basis': d.get('by_kind') if key == 'import' else
                             {'similar': d.get('similar'), 'availability': d.get('availability'),
                              'coverage': d.get('coverage'), 'F_by_view': d.get('F_by_view'),
                              'not_evaluable': len(d.get('not_evaluable', d.get('not_measurable', [])))},
                             'source': file}
    rules = out / 'playable_rules.json'
    if manifest.get('suite', 'stage1') != 'stage1' and rules.is_file():
        checks = read_json(out / 'verdicts_playable_rules.json') if (out / 'verdicts_playable_rules.json').is_file() else {}
        status = {i: checks[i]['status'] if i in checks else 'HARNESS_ERROR' for i in playable_rules.IDS}
        result['playable'] = {'checks': status, 'score': round(100 * sum(v == 'PASS' for v in status.values()) / 3, 2)
                              if 'HARNESS_ERROR' not in status.values() else None,
                              'note': 'rules only; reported beside the dimensions, not part of them'}
    if provisional:
        result['provisional'] = 'scored after a take; more takes may follow'
    sc = state_summary(out, rows) if manifest.get('suite') == 'stage3' else None
    if sc:
        result['state_conditioned'] = sc
    from ..repair import ue_compile_compat
    repairs = ue_compile_compat.score_provenance(out)
    if repairs:
        result['launch_repairs'] = repairs  # per-take provenance only; no score/check changes
    write_json(out / 'score.json', result)
    return result


def _asset_views(out: Path, manifest: dict, rows: list[dict], peers) -> None:
    """In-engine four-view renders of imported 3D assets (after take 1: the working copy is imported).
    A failed render is recorded and leaves those checks on gameplay frames; it never stops the run."""
    if not asset_views.targets(rows):
        return
    try:
        if manifest['engine'] == 'unity3d':
            binary = read_json(plan.take_dir(out, 1) / 'record' / 'unity_editor.json')['editor']['binary']
            asset_views.render_unity(out, binary, rows, peers=peers)
            asset_views.render_source_unity(out, binary)       # original asset files: texture baseline
        else:
            write_json(out / 'asset_views' / 'asset_views.json',
                       {'version': asset_views.VERSION, 'engine': manifest['engine'], 'assets': {},
                        'skipped': 'no in-engine view renderer for this engine yet'})
    except Exception as exc:      # recorded harness gap, not a product fault
        (out / 'asset_views').mkdir(exist_ok=True)
        write_json(out / 'asset_views' / 'asset_views_error.json', {'error': f'{type(exc).__name__}: {exc}'})


STATE_ENTRY = os.environ.get('A3GAME_STATE_ENTRY', '1') != '0'
STATE_PLAN_TIMEOUT_S = int(os.environ.get('A3GAME_STATE_PLAN_TIMEOUT_S', 3000))


from .paths import write_json as _write_json


def _state_book(path: Path) -> dict:
    """state_conditioned.json: {version, takes: [one entry per state-entry take], checks: best per check}.
    An older single-take file is read as one entry."""
    if not path.is_file():
        return {'version': state_entry.VERSION, 'takes': [], 'checks': {}}
    data = read_json(path)
    if 'takes' in data:
        return data
    return {'version': state_entry.VERSION, 'takes': [data], 'checks': {i: {**c, 'take': data.get('take')}
                                                                     for i, c in (data.get('checks') or {}).items()}}


def state_summary(out: Path, rows: list) -> dict | None:
    """Separate state-conditioned track for score.json (never changes the main S)."""
    path = out / 'state_conditioned.json'
    if not path.is_file():
        return None
    book = _state_book(path)
    metric_of = {r['id']: r['metric'] for r in rows}
    by = {}
    for i, c in book['checks'].items():
        d = by.setdefault(metric_of.get(i, '?'), {'n': 0, 'normal': 0.0, 'state': 0.0})
        d['n'] += 1
        d['normal'] += c.get('normal_play_credit') or 0
        d['state'] += c.get('state_conditioned_credit') or 0
    return {'note': 'checks normal play did not reach, re-tested from a game state set through the game\'s own '
                    'save/load or methods; reported beside, never inside, the main score',
            'takes': [{k: t.get(k) for k in ('take', 'targets', 'skipped', 'error')} | {
                'state_reached': (t.get('verification') or {}).get('state_reached')} for t in book['takes']],
            'checks': book['checks'],
            'by_dimension': {m: {'n': d['n'], 'normal_mean': round(100 * d['normal'] / d['n'], 2),
                                 'state_conditioned_mean': round(100 * d['state'] / d['n'], 2)} for m, d in by.items()}}


DIRECT = os.environ.get('A3GAME_DIRECT_TRIGGER', '1') != '0'


def _direct_book(path: Path) -> dict:
    return read_json(path) if path.is_file() else {'version': 'stage3-direct-trigger.v1', 'takes': []}


def _direct_take(out: Path, manifest: dict, rows: list, metrics: dict, frozen: dict, ids: list, take: int,
                 feedback: dict | None = None) -> dict:
    """Direct Trigger take (user decision 2026-11-11): for checks normal play left UNVERIFIED, the game's own
    functions (input handler first, then the feature entry, setup via save / load) are called in a recorded take;
    the judge decides PASS / FAIL / UNVERIFIED from the postcondition. Verdicts -> verdicts_evidence_d<take>.json.
    A normal-play FAIL is never overridden (see score())."""
    path = out / 'direct_trigger.json'
    book = _direct_book(path)
    if any(t.get('take') == take and t.get('done') for t in book['takes']):
        return book
    entry = {'take': take, 'targets': ids, 'done': False}
    try:
        _status(out, f'direct_plan_t{take}', 'running')
        if feedback is None:
            feedback = _feedback(out, take, ids, final_verdicts(out, upto=BATCH_MAX_TAKES))
        sb = budgets.for_take(manifest['budget'], 1)
        sb = {**sb, 'plan_timeout_s': max(sb.get('plan_timeout_s', 1500), STATE_PLAN_TIMEOUT_S)}
        p = plan.make_plan(out, {**manifest, 'budget': sb}, take, ids, feedback, direct=True)
        se = p.get('state_entry') or {}
        entry['plan'] = {k: se.get(k) for k in ('target_state', 'calls', 'postconditions', 'applies_to')}
        applies = [i for i in ids if i in (se.get('applies_to') or [])]
        if not se.get('calls') or not applies:
            entry['skipped'] = 'no game function found to start these features'
        else:
            _status(out, f'direct_record_t{take}', 'running')
            prepare.verify(out)
            record.record(out, {**manifest, 'budget': budgets.for_take(manifest['budget'], 1)}, p, take)
            check = state_entry.verify(plan.take_dir(out, take) / 'record', p)
            entry['calls_result'] = check.get('calls')
            entry['failed_calls'] = [c for c in check.get('calls') or [] if not c.get('ok')]
            if not any(c.get('ok') for c in check.get('calls') or []):
                entry['skipped'] = 'no direct call ran in the engine - checks stay UNVERIFIED'
            else:
                # judged per check even if some calls failed: the judge is told which ones (a check that depends
                # on a failed call stays UNVERIFIED)
                _status(out, f'direct_judge_t{take}', 'running')
                ev = dict(evidence.build(out, [take]))
                ev['direct_trigger'] = {'calls': se.get('calls'), 'postconditions': se.get('postconditions'),
                                        'results': check.get('calls'), 'round': entry.get('round', 1)}
                judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=applies, tag=f'_d{take}')
                entry['verdicts'] = f'verdicts_evidence_d{take}.json'
                entry['applies_to'] = applies
    except HarnessError as exc:
        entry['error'] = f'HarnessError: {str(exc)[:800]}'
    entry['done'] = True
    book['takes'] = [t for t in book['takes'] if t.get('take') != take] + [entry]
    write_json(path, book)
    return book


DIRECT_ROUNDS = int(os.environ.get('A3GAME_DIRECT_ROUNDS', 3))
MAX_RETRY_TAKES = int(os.environ.get('A3GAME_MAX_RETRY_TAKES', 99))   # normal-play retry takes (0 = fast mode)


def direct_feedback(out: Path, take: int, ids: list, rows: list, metrics: dict) -> dict:
    """Feedback for a Direct Trigger round: earlier plans / judge reasons / game log (normal takes and earlier
    direct takes), plus every earlier direct attempt at these checks: calls, engine results, postconditions and the
    judge's reason why it stayed UNVERIFIED."""
    fb = _feedback(out, take, ids, final_verdicts(out, upto=BATCH_MAX_TAKES))
    attempts = {}
    for t in _direct_book(out / 'direct_trigger.json')['takes']:
        if not set(t.get('targets') or []) & set(ids):
            continue
        vf = out / (t.get('verdicts') or '')
        verd = read_json(vf) if t.get('verdicts') and vf.is_file() else {}
        for i in ids:
            if i not in (t.get('targets') or []):
                continue
            v = verd.get(i, {})
            attempts.setdefault(i, []).append({
                'take': t['take'], 'calls': (t.get('plan') or {}).get('calls'),
                'engine_results': [{k: c.get(k) for k in ('member', 'ok', 'error', 't_ms')} for c in t.get('calls_result') or []],
                'in_applies_to': i in (t.get('applies_to') or []), 'skipped': t.get('skipped'), 'error': t.get('error'),
                'judge_reason': ' | '.join(v[x].get('reason', '') for x in ('basic_function', 'result_outcome') if x in v)[:600]})
    fb['earlier_direct_attempts'] = attempts
    return fb


def direct_rounds(out: Path, manifest: dict, rows: list, metrics: dict, frozen: dict, first_take: int,
                  rounds: int = DIRECT_ROUNDS) -> int:
    """Direct Trigger rounds over the checks normal play left UNVERIFIED: each round targets the checks still
    undecided (normal None, no direct PASS / FAIL), batches of BATCH, with feedback from the earlier attempts; stops
    after `rounds` rounds or when a round decides nothing new. Never touches normal-play takes / verdicts.
    Returns the next free take number."""
    final = final_verdicts(out, upto=BATCH_MAX_TAKES)
    def normal_credit(r):
        if r['mode'] == 'static' or metrics[r['metric']].FORMAT != 'tiered' or r['id'] not in final:
            return 'n/a'
        try:
            return metrics[r['metric']].credit(r, final[r['id']])
        except ValueError:
            return None
    pool = [r['id'] for r in plan.targets(rows) if normal_credit(r) is None]
    take = first_take
    done_rounds = {t.get('round') for t in _direct_book(out / 'direct_trigger.json')['takes']}
    for rnd in range(1, rounds + 1):
        decided = set(direct_verdicts(out, rows, metrics))
        todo = [i for i in pool if i not in decided]
        if not todo:
            break
        before = len(decided)
        for start in range(0, len(todo), BATCH):
            batch = todo[start:start + BATCH]
            fb = direct_feedback(out, take, batch, rows, metrics)
            seed = seed_feedback(out, batch)
            if seed:
                fb['previous_run'] = seed
            book = _direct_take(out, manifest, rows, metrics, frozen, batch, take, feedback=fb)
            for t in book['takes']:
                if t.get('take') == take:
                    t['round'] = rnd
            write_json(out / 'direct_trigger.json', book)
            take += 1
        if len(set(direct_verdicts(out, rows, metrics))) == before:
            break                                     # this round decided nothing new
    book = _direct_book(out / 'direct_trigger.json')
    book['complete'] = True                           # all rounds done: absence may now count as FAIL
    write_json(out / 'direct_trigger.json', book)
    return take


_ERROR_LEVELS = ('error', 'fatal', 'exception', 'assert', 'critical')


def direct_clean_runs(out: Path) -> dict:
    """Checks a Direct Trigger take actually ran (all of its calls OK in the engine) whose take log is clean:
    no game error / exception / fatal line and no game crash. Value = the take(s)."""
    clean = {}
    for t in _direct_book(out / 'direct_trigger.json')['takes']:
        calls = t.get('calls_result') or []
        if not calls or not all(c.get('ok') for c in calls):
            continue
        rec = plan.take_dir(out, t['take']) / 'record'
        if (rec / 'game_crash.json').is_file():
            continue
        bad = False
        ev = rec / 'event_trace.jsonl'
        for line in (ev.read_text(errors='replace').splitlines() if ev.is_file() else []):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            lvl = str(e.get('level', '')).lower()
            msg = str(e.get('message', ''))
            if lvl in _ERROR_LEVELS or 'Exception' in msg or 'GAME CRASH' in msg:
                bad = True
                break
        if bad:
            continue
        for i in t.get('applies_to') or []:
            clean.setdefault(i, []).append(t['take'])
    return clean


def tried_checks(out: Path) -> dict:
    """Checks really tried: an input naming the check was delivered in a normal take, or a Direct Trigger take that
    included it ran at least one call in the engine. Value = how ({'normal_takes': n, 'direct_takes': n})."""
    tried = {}
    cov = out / 'coverage.json'
    for i in (read_json(cov).get('attempted', []) if cov.is_file() else []):
        tried.setdefault(i, {'normal_takes': 0, 'direct_takes': 0})['normal_takes'] += 1
    for t in _direct_book(out / 'direct_trigger.json')['takes']:
        if any(c.get('ok') for c in t.get('calls_result') or []):
            for i in t.get('applies_to') or []:
                tried.setdefault(i, {'normal_takes': 0, 'direct_takes': 0})['direct_takes'] += 1
    return tried


def direct_coverage(out: Path, tracks: dict) -> dict:
    """Planning / execution / verification coverage of the Direct Trigger track over the checks normal play left
    UNVERIFIED, and a reason for every check that is still UNVERIFIED."""
    book = _direct_book(out / 'direct_trigger.json')
    pool = [i for i, c in tracks['normal'].items() if c is None]
    planned, executed, reasons = set(), set(), {}
    for t in book['takes']:
        applies = set(t.get('applies_to') or (t.get('plan') or {}).get('applies_to') or [])
        planned |= applies
        if t.get('calls_result') and not t.get('failed_calls') and not t.get('skipped') and not t.get('error'):
            executed |= applies
    for i in pool:
        if tracks['direct'].get(i) is not None:
            continue
        ts = [t for t in book['takes'] if i in (t.get('targets') or [])]
        if not ts:
            reasons[i] = 'not targeted by a Direct Trigger take yet'
        elif i not in planned:
            reasons[i] = 'no game entry function found by the planner'
        elif i not in executed:
            reasons[i] = 'its direct calls failed / take skipped: ' + '; '.join(
                str(t.get('skipped') or t.get('error') or [c.get('error') for c in t.get('failed_calls') or []])[:200] for t in ts)
        else:
            vf = [out / t['verdicts'] for t in ts if t.get('verdicts') and (out / t['verdicts']).is_file()]
            why = ''
            for f in vf:
                v = read_json(f).get(i)
                if v:
                    why = v['result_outcome'].get('reason') or v['basic_function'].get('reason') or ''
            reasons[i] = 'ran, but no postcondition seen: ' + why[:300]
    n = len(pool) or 1
    return {'direct_coverage': {
                'unverified_after_normal_play': len(pool),
                'planning': round(len(planned & set(pool)) / n, 3),
                'execution': round(len(executed & set(pool)) / n, 3),
                'verification': round(sum(1 for i in pool if tracks['direct'].get(i) is not None) / n, 3)},
            'unverified_reasons': reasons}


def direct_verdicts(out: Path, rows: list, metrics: dict) -> dict:
    """Per check, the Direct Trigger result over all direct takes: FAIL if any take observed a wrong result,
    else PASS if any take proved it, else nothing."""
    book = _direct_book(out / 'direct_trigger.json')
    by_id = {r['id']: r for r in rows}
    best = {}
    for t in book['takes']:
        f = out / (t.get('verdicts') or '')
        if not t.get('verdicts') or not f.is_file():
            continue
        for i, v in read_json(f).items():
            r = by_id.get(i)
            if r is None:
                continue
            try:
                c = metrics[r['metric']].credit(r, v)
            except ValueError:
                c = None
            if c is None:
                continue
            if i not in best or c < best[i][0]:
                best[i] = (c, v, t['take'])
    return best


def _state_take(out: Path, manifest: dict, rows: list, metrics: dict, frozen: dict, deep: list, take: int,
                feedback: dict | None = None) -> None:
    """One take that starts from a deeper state via the game's own members (state_entry.py), for checks
    normal play never reached. Verdicts -> verdicts_evidence_s<take>.json, summary -> state_conditioned.json;
    the normal-play score is untouched. A failure here is recorded, never fails the game."""
    path = out / 'state_conditioned.json'
    book = _state_book(path)
    if any(t.get('take') == take and t.get('done') for t in book['takes']):
        return
    result = {'version': state_entry.VERSION, 'take': take, 'targets': deep, 'done': False}
    def write_json(_path, res):                  # noqa: F811 - each state take is appended to the book
        book['takes'] = [t for t in book['takes'] if t.get('take') != res['take']] + [res]
        merged = {}
        for t in book['takes']:
            for i, c in (t.get('checks') or {}).items():
                prev = merged.get(i)
                if prev is None or (c.get('state_conditioned_credit') or 0) > (prev.get('state_conditioned_credit') or 0):
                    merged[i] = {**c, 'take': t['take']}
        book.update(checks=merged, done=all(t.get('done') for t in book['takes']))
        _write_json(_path, book)
    try:
        _status(out, f'state_plan_t{take}', 'running')
        if feedback is None:                  # earlier plans + judge reasons, incl. earlier state-entry takes
            feedback = _feedback(out, take, deep, final_verdicts(out, upto=BATCH_MAX_TAKES))
            for t in _state_book(path)['takes']:
                vf = out / f'verdicts_evidence_s{t.get("take")}.json'
                sv = read_json(vf) if vf.is_file() else {}
                for i in deep:
                    if i in sv:
                        feedback['judge_reasons'][i] = ('STATE-ENTRY TAKE ' + str(t.get('take')) + ' (entry: '
                            + str((t.get('state_entry') or {}).get('target_state'))[:300] + ') -> '
                            + ' | '.join(sv[i][x].get('reason', '') for x in ('basic_function', 'result_outcome')))[:700]
        sb = budgets.for_take(manifest['budget'], 1)
        sb = {**sb, 'plan_timeout_s': max(sb.get('plan_timeout_s', 1500), STATE_PLAN_TIMEOUT_S)}
        for attempt in (1, 2):                # state plans read more source: longer limit, one retry on timeout
            try:
                p = plan.make_plan(out, {**manifest, 'budget': sb}, take, deep, feedback, state_conditioned=True)
                break
            except HarnessError as exc:
                if attempt == 2 or 'timeout' not in str(exc).lower():
                    raise
                arch = plan.take_dir(out, take)
                for d in (out / 'model_calls').glob(f'plan_t{take}*'):
                    d.rename(d.with_name(d.name + f'_timeout{attempt}'))
        result['state_entry'] = p.get('state_entry')
        if not (p.get('state_entry') or {}).get('calls'):
            result['skipped'] = 'no state entry available: ' + str((p.get('state_entry') or {}).get('target_state'))
            result['done'] = True
            write_json(path, result)
            return
        _status(out, f'state_record_t{take}', 'running')
        prepare.verify(out)
        record.record(out, {**manifest, 'budget': budgets.for_take(manifest['budget'], 1)}, p, take)
        check = state_entry.verify(plan.take_dir(out, take) / 'record', p)
        result['verification'] = check
        applies = [i for i in deep if i in (p['state_entry'].get('applies_to') or [])]
        if check['state_reached'] in (True, 'unverified') and applies:
            _status(out, f'state_judge_t{take}', 'running')
            ev = dict(evidence.build(out, [take]))
            ev['state_entry'] = {**p['state_entry'], 'state_reached': check['state_reached']}
            v = judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=applies, tag=f'_s{take}')
            normal = final_verdicts(out, upto=BATCH_MAX_TAKES)
            def credit(i, verdicts):
                r = next(x for x in rows if x['id'] == i)
                try:
                    return metrics[r['metric']].credit(r, verdicts[i]) if i in verdicts else None
                except ValueError:
                    return None
            result['checks'] = {i: {'normal_play_credit': credit(i, normal), 'state_conditioned_credit': credit(i, v),
                                    'reached_by_normal_play': False} for i in applies}
        else:
            result['skipped'] = ('state not reached' if check['state_reached'] is False
                                 else 'planner marked no target as valid for this state')
    except Exception as exc:                     # noqa: BLE001 - separate track; recorded, not raised
        result['error'] = f'{type(exc).__name__}: {str(exc)[:800]}'
    result['done'] = True
    write_json(path, result)


def _batched_takes(out: Path, manifest: dict, rows: list, metrics: dict, frozen: dict, peers, started: float) -> None:
    """Stage3 coverage loop: every take plans a batch of BATCH checks never attempted before (the planner must
    put each in a probe or declare it unreachable with a reason); once every check was attempted, takes go to
    still-unresolved checks. Budget = max(PROJECT_BUDGET_S, batches * BATCH_TAKE_BUDGET_S). Checks never
    reached by any take are judged on source only at the end, so every check gets a verdict."""
    import math
    runtime = [r['id'] for r in plan.targets(rows)]
    n_batches = math.ceil(len(runtime) / BATCH) if runtime else 0
    budget_s = max(PROJECT_BUDGET_S, n_batches * BATCH_TAKE_BUDGET_S)
    max_takes = min(BATCH_MAX_TAKES, n_batches + 2)
    attempted, unreachable, history, feedback, take_secs = [], {}, [], None, []
    signals_seen, stale_retries = set(), 0
    omitted, set_aside = {}, []                            # planner omissions per check; set aside after 2
    state = out / 'coverage.json'
    if state.is_file():                                   # resume
        prev = read_json(state)
        attempted, history = prev.get('attempted', []), prev.get('history', [])
        unreachable = prev.get('declared_unreachable', {})
        omitted, set_aside = prev.get('planner_omissions', {}), prev.get('planner_set_aside', [])
    for take in range(1, max_takes + 1):
        if take <= len(history):
            continue                                       # finished take (resumed run)
        never = [i for i in runtime if i not in attempted and i not in unreachable and i not in set_aside]
        verdicts = final_verdicts(out, upto=BATCH_MAX_TAKES)
        remaining = [i for i in unresolved(rows, verdicts, metrics) if i in attempted]
        retry = not never
        pending = never[:BATCH] if never else remaining[:BATCH]
        if not pending:
            break
        if retry and sum(1 for h in history if h.get('kind') == 'retry') >= MAX_RETRY_TAKES:
            history[-1]['stopped'] = f'normal-play retry limit ({MAX_RETRY_TAKES}) - remaining checks go to Direct Trigger'
            write_json(state, {**read_json(state), 'history': history})
            break
        if take > 1:
            left = budget_s - (record.busy_clock() - started)
            if take_secs and left < sum(take_secs) / len(take_secs):
                history[-1]['stopped'] = f'project budget: {left:.0f}s left < one take'
                break
        t0 = record.busy_clock()
        _status(out, f'plan_t{take}', 'running')
        take_manifest = {**manifest, 'budget': budgets.for_take(manifest['budget'], 1)}
        if retry:
            feedback = _feedback(out, take, pending, verdicts)
        fb = feedback if retry else None
        seed = seed_feedback(out, pending) if not (plan.take_dir(out, take) / 'plan.json').is_file() else None
        if seed:
            fb = {**(fb or {}), 'previous_run': seed}
        executable = plan.make_plan(out, take_manifest, take, pending, fb)
        prepare.verify(out)
        _status(out, f'record_t{take}', 'running')
        record.record(out, take_manifest, executable, take)
        if take == 1:
            _asset_views(out, manifest, rows, peers)
        _status(out, f'evidence_judge_t{take}', 'running')
        ev = evidence.build(out, list(range(1, take + 1)))
        judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=pending, tag=f'_t{take}')
        before = len(remaining) if retry else None
        cov = read_json(plan.take_dir(out, take) / 'plan_coverage.json')
        # Attempted = a probe naming the check was actually delivered in THIS recording (input sent);
        # planned-but-not-executed checks stay "never attempted" and are batched again.
        acts = plan.take_dir(out, take) / 'record' / 'actions.jsonl'
        executed = set()
        for line in (acts.read_text(errors='replace').splitlines() if acts.is_file() else []):
            try:
                a = json.loads(line)
            except ValueError:
                continue
            if a.get('sent') is not False and a.get('ok') is not False:
                executed.update(a.get('criterion_ids') or [])
        for i, why in cov.get('declared_unreachable', {}).items():
            if i in pending and i not in executed:
                unreachable[i] = why
        for i in cov.get('unplanned', []):
            if i in pending and i not in executed:
                omitted[i] = omitted.get(i, 0) + 1
                if omitted[i] >= 2 and i not in set_aside:
                    set_aside.append(i)
        attempted += [i for i in pending if i in executed and i not in attempted]
        verdicts = final_verdicts(out, upto=BATCH_MAX_TAKES)
        still = [i for i in unresolved(rows, verdicts, metrics) if i in attempted]
        def credit(i):
            r = next(x for x in rows if x['id'] == i)
            try:
                return metrics[r['metric']].credit(r, verdicts[i]) if i in verdicts else None
            except ValueError:
                return None
        evidenced = [i for i in pending if i in executed and (credit(i) or 0) >= 0.5]
        history.append({'take': take, 'kind': 'retry' if retry else 'new', 'targets': len(pending),
                        'planned': len(set(cov['planned']) & set(pending)),
                        'declared_unreachable': len([i for i in pending if i in unreachable]),
                        'executed': len([i for i in pending if i in executed]),
                        'evidenced_50_plus': len(evidenced),
                        'not_executed': [i for i in pending if i not in executed and i not in unreachable],
                        'seconds': None, 'unresolved_after': len(still)})
        take_secs.append(record.busy_clock() - t0)
        history[-1]['seconds'] = round(take_secs[-1])
        n = len(runtime) or 1
        write_json(state, {'batch': BATCH, 'runtime_checks': len(runtime), 'attempted': attempted,
                           'declared_unreachable': unreachable,
                           'planner_omissions': omitted, 'planner_set_aside': set_aside,
                           'never_attempted': [i for i in runtime if i not in attempted and i not in unreachable],
                           'plan_coverage': round(len(set(attempted) | set(unreachable)) / n, 3),
                           'attempt_coverage': round(len(attempted) / n, 3),
                           'evidence_coverage': round(sum(1 for i in attempted if (credit(i) or 0) >= 0.5) / n, 3),
                           'history': history, 'budget_s': budget_s, 'take_seconds': [round(x) for x in take_secs]})
        write_json(out / 'takes.json', {'max_takes': max_takes, 'history': history, 'remaining': still})
        # a batch whose probes mostly never ran is a planning/execution problem - stop and surface it
        # a batch whose planned probes mostly never ran is a planning/execution problem - stop and surface it
        # (checks the planner declared unreachable with a reason are not part of this rate)
        runnable = len(pending) - history[-1]['declared_unreachable']
        if not retry and runnable >= 4 and history[-1]['executed'] < 0.3 * runnable:
            history[-1]['stopped'] = f"low attempt rate: {history[-1]['executed']}/{runnable} executed"
            write_json(state, {**read_json(state), 'history': history})
            break
        score(out, provisional=True)
        sig = check_trigger_signals(out, take)
        new_signals = [i for i in sig['seen'] if i not in signals_seen]
        signals_seen.update(sig['seen'])
        history[-1]['trigger_signals_seen'] = len(sig['seen'])
        history[-1]['new_trigger_signals'] = len(new_signals)
        if retry and before is not None and len(still) >= before:
            # progress = a check resolved, or the game newly printed a declared trigger signal
            if new_signals and stale_retries < 1:
                stale_retries += 1
            else:
                history[-1]['stopped'] = 'retry take resolved nothing and reached no new trigger signal'
                write_json(state, {**read_json(state), 'history': history})
                break
        elif retry:
            stale_retries = 0
    verdicts = final_verdicts(out, upto=BATCH_MAX_TAKES)
    missing = [i for i in runtime if i not in verdicts]
    if missing:                                           # never attempted (budget): source-only verdicts
        judge.judge(out, manifest, evidence.build_static(out), 'evidence', frozen, only_ids=missing, tag='_t0')
    # State-conditioned take (separate track): checks normal play could not reach.
    # Deep checks: declared unreachable / set aside, or attempted but never seen to trigger (e.g. behind
    # progression the route never reached). They get state-entry takes (game's own save/load or methods).
    final = final_verdicts(out, upto=BATCH_MAX_TAKES)
    never_seen = [i for i in unresolved(rows, final, metrics) if i in attempted
                  and not (final.get(i, {}).get('basic_function') or {}).get('triggered_observed')]
    deep = [i for i in runtime if ((i in unreachable or i in set_aside) and i not in attempted) or i in never_seen]
    done_state = set(_state_book(out / 'state_conditioned.json')['checks'])
    deep = [i for i in deep if i not in done_state]
    if deep and STATE_ENTRY and not DIRECT and manifest['engine'] in state_entry.ENV:
        nxt = max([len(history)] + [int(p.name) for p in (out / 'takes').iterdir() if p.name.isdigit()]) + 1
        for n, start in enumerate(range(0, len(deep), BATCH)):
            _state_take(out, manifest, rows, metrics, frozen, deep[start:start + BATCH], nxt + n)
    # Direct Trigger track: every tiered check normal play left UNVERIFIED (never a normal-play FAIL).
    if DIRECT and manifest['engine'] in state_entry.ENV:
        final = final_verdicts(out, upto=BATCH_MAX_TAKES)
        def normal_credit(i):
            r = next(x for x in rows if x['id'] == i)
            if metrics[r['metric']].FORMAT != 'tiered' or i not in final:
                return 'n/a'
            try:
                return metrics[r['metric']].credit(r, final[i])
            except ValueError:
                return None
        nxt = max([len(history)] + [int(p.name) for p in (out / 'takes').iterdir() if p.name.isdigit()]) + 1
        direct_rounds(out, manifest, rows, metrics, frozen, nxt)


def run(delivery_dir: Path, out: Path, *, standards_root: Path, peers=(), models: dict | None = None,
        stop_after: str | None = None, suite: str = 'stage1') -> dict:
    """Evaluate one delivery directory (with delivery.json) into eval dir ``out``.

    ``standards_root``: eval root holding ``_standards/``; ``peers``: prepared eval
    dirs of the other models' deliveries of the same case (source context for
    freezing the shared standards — prepare every delivery of a case first)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    step = 'prepare'
    started = record.busy_clock()            # the project budget counts the whole run (static judge included)
    try:
        manifest = prepare.prepare(delivery_dir, out, models=models or DEFAULT_MODELS, suite=suite)
        if manifest.get('suite', 'stage1') != suite:
            raise ValueError(f'{out} was prepared for suite {manifest.get("suite")}, not {suite}')
        metrics = suites.get(suite).metrics
        prepare.verify(out)
        step = 'static_judge'
        judge.judge(out, manifest, evidence.build_static(out), 'static')
        if stop_after != 'static_judge':
            step = 'standards'
            rows = read_json(out / 'input' / 'criteria.json')['criteria']
            # Benchmark standards are frozen and human-approved ahead of time (model-independent);
            # evaluation only loads them and refuses to run without an approved version.
            criteria_version = read_json(out / 'input' / 'criteria.json')['version']
            try:
                frozen = standards.load(suite, criteria_version, manifest['game_id'], rows)
            except ValueError as exc:
                raise HarnessError(str(exc)) from exc
        if stop_after == 'plan_only':
            # Plan the first take (validated, executable) but record nothing; then judge on source only.
            step = 'plan_t1'
            plan.make_plan(out, manifest, 1)
        if stop_after in ('source_only', 'plan_only'):
            # No plan / engine: judge every runtime criterion on source evidence alone
            # (tiered metrics can reach the 10% source tier; nothing runtime can pass).
            step = 'evidence_judge_t0'
            judge.judge(out, manifest, evidence.build_static(out), 'evidence', frozen, tag='_t0')
        elif stop_after != 'static_judge':
            history, pending, feedback = [], None, None
            take_secs = []
            if suite == 'stage3' and BATCH > 0:
                step = 'batched_takes'           # the take / stage is written to status.json as it runs
                _batched_takes(out, manifest, rows, metrics, frozen, peers, started)
            for take in (range(1, plan.MAX_TAKES + 1) if not (suite == 'stage3' and BATCH > 0) else ()):
                if take > 1:
                    # Per-project wall-clock budget: start another take only if one more average take fits.
                    left = PROJECT_BUDGET_S - (record.busy_clock() - started)
                    if left < sum(take_secs) / len(take_secs):
                        history[-1]['stopped'] = f'project budget: {left:.0f}s left < one take'
                        break
                take_started = record.busy_clock()
                _status(out, f'take_{take}', 'running')
                step = f'plan_t{take}'
                take_manifest = {**manifest, 'budget': budgets.for_take(manifest['budget'], take)}
                executable = plan.make_plan(out, take_manifest, take, pending, feedback)
                step = f'record_t{take}'
                prepare.verify(out)
                record.record(out, take_manifest, executable, take)
                if take == 1:
                    step = 'asset_views'
                    _asset_views(out, manifest, rows, peers)
                step = f'evidence_t{take}'
                ev = evidence.build(out, list(range(1, take + 1)))
                step = f'evidence_judge_t{take}'
                judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=pending, tag=f'_t{take}')
                verdicts = final_verdicts(out, upto=take)   # stable when resuming
                remaining = unresolved(rows, verdicts, metrics)
                resolved = len(pending) - len(remaining) if pending is not None else None
                history.append({'take': take, 'targets': len(pending) if pending is not None else None,
                                'resolved': resolved, 'remaining': len(remaining)})
                take_secs.append(record.busy_clock() - take_started)
                write_json(out / 'takes.json', {'max_takes': plan.MAX_TAKES, 'history': history,
                                                'remaining': remaining, 'budget_s': PROJECT_BUDGET_S,
                                                'take_seconds': [round(x) for x in take_secs]})
                score(out, provisional=True)          # a score after every take, not only at the end
                if not remaining:
                    break
                if resolved == 0:
                    history[-1]['stopped'] = 'no check newly observed in this take'
                    break
                pending, feedback = remaining, _feedback(out, take + 1, remaining, verdicts)
        all_rows = read_json(out / 'input' / 'criteria.json')['criteria']
        if stop_after is None and suite == 'stage3':
            step = 'import_texture'
            from ..stage3 import import_presence, texture_ingame
            import_presence.evaluate(out)
            # Texture: imported 3D assets photographed inside the running game at the end of each take
            # (UE / Unity recorders) vs the original asset (reference loader); mean F, availability, coverage.
            if texture_ingame.latest_shots(out) is not None:
                for attempt in (1, 2):            # one more try after a transient service failure
                    try:
                        texture_ingame.evaluate(out, manifest['models']['judge'])
                        (out / 'texture_ingame_error.json').unlink(missing_ok=True)
                        break
                    except Exception as exc:      # recorded; texture stays unscored, never 0
                        write_json(out / 'texture_ingame_error.json', {'error': f'{type(exc).__name__}: {exc}',
                                                                       'attempt': attempt})
                        if attempt == 1:
                            time.sleep(60)
        if stop_after is None and suite != 'stage1':
            # Suites without Playable rows still report it (import / launch / operate, by rules)
            # from their own recordings; reported beside the dimensions, never mixed into them.
            step = 'playable_rules'
            playable_rules.evaluate(out, manifest, BATCH_MAX_TAKES)
        if stop_after != 'static_judge' and any(getattr(metrics[r['metric']], 'RULE_BASED', False) for r in all_rows):
            step = 'playable_rules'
            playable_rules.evaluate(out, manifest, BATCH_MAX_TAKES)
        step = 'score'
        result = score(out)
        _status(out, 'score', 'done', complete=result['complete'])
        return result
    except HarnessError as exc:
        _status(out, step, 'HARNESS_ERROR', error=str(exc))
        if (out / 'manifest.json').is_file() and (out / 'input' / 'criteria.json').is_file():
            score(out)                       # keep partial scores; failed metrics stay unscored
        raise
    except Exception as exc:
        _status(out, step, 'ERROR', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        raise


PLAYABLE_GAMEPLAY_MS = 75000
PLAYABLE_TAKES = 2


def run_playable(delivery_dir: Path, out: Path, *, models: dict, takes: int = PLAYABLE_TAKES,
                 continuation: str | None = None) -> dict:
    """Playable only (stage1 rows play.*): short entry + operate takes, decided by playable_rules.

    No static judge, no standards, no judge model: the planner writes each take, the engine import
    and the recordings decide. A second take runs only while operate is not yet PASS."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    step = 'prepare'
    try:
        manifest = prepare.prepare(delivery_dir, out, models=models, suite='stage1', playable_only=True)
        prepare.verify(out)
        budget = dict(manifest['budget'])
        extra = PLAYABLE_GAMEPLAY_MS - budget['gameplay_ms']
        for key in ('gameplay_ms', 'recording_ms', 'total_wall_clock_ms'):
            budget[key] += extra
        budget['engine_call_ms'] = max(budget['engine_call_ms'] + extra, budget['total_wall_clock_ms'])
        short = {**manifest, 'budget': budget}
        ids = ['play.launch', 'play.operate']
        verdicts, feedback, history = {}, None, []
        first_take = 1
        if continuation is not None:
            from ..repair import ue_g020_capture_continuation
            first_take, feedback = ue_g020_capture_continuation.validate_resume(out, continuation, models, takes)
        for take in range(first_take, takes + 1):
            step = f'plan_t{take}'
            executable = plan.make_plan(out, short, take, ids, feedback)
            step = f'record_t{take}'
            if continuation is not None:
                ue_g020_capture_continuation.before_record(out, continuation, take, executable)
            record.record(out, short, executable, take)
            step = f'playable_rules_t{take}'
            verdicts = playable_rules.evaluate(out, manifest, take)
            op = verdicts.get('play.operate', {}).get('status')
            history.append({'take': take, 'checks': {k: v['status'] for k, v in verdicts.items()}})
            if op == 'PASS' or verdicts.get('play.launch', {}).get('status') == 'FAIL':
                break
            feedback = {'earlier_plans': [read_json(plan.take_dir(out, k) / 'plan.json')['summary']
                                          for k in range(1, take + 1)],
                        'judge_reasons': {'play.operate': (verdicts.get('play.operate') or {}).get(
                            'reason', 'no checkable input in the recording')}}
        checks = {i: (verdicts[i]['status'] if i in verdicts else 'HARNESS_ERROR') for i in playable_rules.IDS}
        complete = 'HARNESS_ERROR' not in checks.values()
        result = {'version': playable_rules.VERSION, 'game_id': manifest['game_id'], 'engine': manifest['engine'],
                  'planner': models.get('planner'), 'checks': checks, 'takes': history, 'complete': complete,
                  'playable': round(100 * sum(v == 'PASS' for v in checks.values()) / 3, 2) if complete else None}
        write_json(out / 'playable_score.json', result)
        _status(out, 'playable', 'done', complete=complete)
        return result
    except HarnessError as exc:
        _status(out, step, 'HARNESS_ERROR', error=str(exc))
        raise
    except Exception as exc:
        _status(out, step, 'ERROR', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        raise
