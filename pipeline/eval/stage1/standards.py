"""Per-case frozen outcome standards for the tiered metrics (Mechanic v3, Gameness v4).

Before any runtime judge, each tiered criterion gets a source-only standard:
visible goal, result frame, correct target, necessary context, representative
basic function, basic-function bugs and permitted trigger modes. It is frozen
ONCE per case and metric and shared by every model's delivery of that case, so
all models are judged against the same goal. It is never derived from a
recording, a verdict or a score, and is never rewritten afterwards.

Stored at ``<eval root>/_standards/<VERSION>/<judge model>/<GameID>/<metric>.json`` together
with the deliveries whose sources were consulted.
"""
from __future__ import annotations

import fcntl
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import shutil
from pathlib import Path

from .llm import S, arr, call_model, enum, obj, validate_schema
from . import suites
from .metrics._formats import TRIGGER_MODES
from .paths import read_json, sha256, write_json

VERSION = 'outcome_frame_v1'
DIAGNOSTIC = ('exact_timing', 'exact_space_motion', 'exact_numeric_formula', 'exhaustive_branches_boundaries')


def root(eval_root: Path, game_id: str, model: str) -> Path:
    """Standards are frozen per judge model: the judge never uses another model's standard."""
    return Path(eval_root) / '_standards' / VERSION / model / game_id


def schema(metric: str, rows: list[dict], metrics: dict) -> dict:
    fields = {f: S for f in metrics[metric].STANDARD_FIELDS}
    fields.update(basic_function_bugs=arr(S, minItems=1, maxItems=limits(metric)[0]),
                  permitted_trigger_modes=arr(enum(*TRIGGER_MODES), minItems=1),
                  original_requirement_diagnostic_only=S)
    return obj({'revision': enum(VERSION), 'summary': S,
                'diagnostic_only_categories': arr(enum(*DIAGNOSTIC), minItems=4, maxItems=4),
                'checks': obj({r['id']: obj(dict(fields)) for r in rows})})


# Fields a judge must verify from frames: they may not carry measured quantities (distances,
# durations, angles, rates, ...) that a screenshot cannot establish. Such numbers stay in the
# original requirement and are only checked in source (the 10% tier).
VISIBLE_FIELDS = ('visible_goal', 'result_frame_description', 'correct_target', 'correct_target_and_information',
                  'necessary_context', 'representative_basic_function')
MEASURE = re.compile(r'\d+(?:\.\d+)?\s*(?:m|cm|km|米|厘米|公里|s|sec|秒|ms|毫秒|分钟|min|°|度|%|fps|帧|hz|m/s|units?)(?![a-zA-Z])',
                     re.IGNORECASE)


import os as _os
#: Optional named standard set (e.g. 'lean'): a separate approved folder, same checks, leaner rubric.
STANDARD_SET = _os.environ.get('A3GAME_STANDARD_SET', '')
LEAN = STANDARD_SET == 'lean'
LEAN_METRICS = ('mechanic', 'gamefeel')          # the lean set rewrites only these
MAX_BUGS = 3                 # only the few basic bugs that matter most
MAX_FIELD_CHARS = 240        # one core outcome per check, not a list of sub-conditions


def limits(metric: str) -> tuple[int, int]:
    """(max basic bugs, max chars per visible field) for a metric under the active standard set."""
    return (2, 140) if LEAN and metric in LEAN_METRICS else (MAX_BUGS, MAX_FIELD_CHARS)


def overlong_fields(value: dict, max_chars: int = MAX_FIELD_CHARS) -> list[str]:
    return [f'{cid}.{f} ({len(c[f])} chars)' for cid, c in value.get('checks', {}).items()
            for f in VISIBLE_FIELDS if isinstance(c.get(f), str) and len(c[f]) > max_chars]


def measured_quantities(value: dict) -> list[str]:
    hits = []
    for cid, check in value.get('checks', {}).items():
        for field in VISIBLE_FIELDS:
            text = check.get(field)
            if isinstance(text, str):
                hits += [f'{cid}.{field}: "{m.group(0)}"' for m in MEASURE.finditer(text)]
    return hits


def validate(metric: str, rows: list[dict], value: dict, metrics: dict) -> None:
    validate_schema(value, schema(metric, rows, metrics))
    long = overlong_fields(value, limits(metric)[1])
    if long:
        raise ValueError(f'each check needs ONE core visible outcome in at most {limits(metric)[1]} characters per '
                         'field (no lists of sub-conditions, branches or edge cases): ' + '; '.join(long[:12]))
    hits = measured_quantities(value)
    if hits:
        raise ValueError('visible standard fields must not contain measured quantities a screenshot cannot '
                         'verify (keep them only in the original requirement, judged in source): '
                         + '; '.join(hits[:12]))
    if set(value['diagnostic_only_categories']) != set(DIAGNOSTIC):
        raise ValueError('all four diagnostic-only categories must be declared')
    for r in rows:
        row = value['checks'][r['id']]
        if row['original_requirement_diagnostic_only'] != r['requirement']:
            raise ValueError(f'{r["id"]}: original requirement must be copied byte-for-byte')
        if any(isinstance(v, str) and not v.strip() for v in row.values()):
            raise ValueError(f'{r["id"]}: empty standard field')


def freeze(eval_root: Path, game_id: str, rows: list[dict], deliveries: list[Path], *,
           model: str, timeout: int, suite: str = 'stage1') -> dict:
    """Return {metric: standard} for this case, freezing missing ones exactly once.

    ``deliveries`` are the prepared eval run dirs of every model of this case
    available at freeze time; their ``input/project`` snapshots are read-only
    source context. Concurrent runs of the same case wait on a lock and reuse.
    """
    folder = root(eval_root, game_id, model)
    folder.mkdir(parents=True, exist_ok=True)
    out = {}
    with (folder / '.freeze.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        metrics = suites.get(suite).metrics
        missing = {}
        for metric in suites.tiered(suites.get(suite)):
            mine = [r for r in rows if r['metric'] == metric]
            if not mine:
                continue
            target = folder / f'{metric}.json'
            if target.is_file():
                frozen = read_json(target)
                validate(metric, mine, frozen['standard'], metrics)
                out[metric] = frozen['standard']
            else:
                missing[metric] = mine
        if not missing:
            return out
        sources = [{'run': str(d), 'project': str(Path(d) / 'input' / 'project'),
                    'snapshot_digest': read_json(Path(d) / 'manifest.json')['snapshot_digest']}
                   for d in sorted(deliveries)]
        work = folder / 'input'
        work.mkdir(exist_ok=True)
        (work / 'requirement.txt').write_bytes((Path(deliveries[0]) / 'input' / 'requirement.txt').read_bytes())
        write_json(work / 'deliveries.json', sources)

        def freeze_one(metric, mine):
            checks = [{'id': r['id'], 'group': r['group'], 'requirement': r['requirement']} for r in mine]
            prompt = (metrics[metric].STANDARD_PROMPT
                      + '\n\nDELIVERIES (read-only author sources, one per model): '
                      + json.dumps(sources, ensure_ascii=False)
                      + '\nREQUIREMENT: requirement.txt\nCHECKS\n' + json.dumps(checks, ensure_ascii=False))
            standard = call_model(folder / 'model_calls', name=metric, prompt=prompt,
                                  schema=schema(metric, mine, metrics), cwd=work, model=model, timeout=timeout,
                                  read_dirs=[folder, *(Path(d) / 'input' for d in deliveries)],
                                  validator=lambda v: validate(metric, mine, v, metrics))
            write_json(folder / f'{metric}.json', {
                'version': VERSION, 'metric': metric, 'game_id': game_id, 'model': model, 'deliveries': sources,
                'criteria_ids': [r['id'] for r in mine], 'requirement_sha256': sha256(work / 'requirement.txt'),
                'standard': standard})
            return standard

        # Each metric's standard is an independent call: freeze them concurrently (still under
        # the lock, so other runs of this case wait and then reuse). A failed metric does not
        # stop the others; it is re-frozen on the next run.
        failures = []
        with ThreadPoolExecutor(max_workers=len(missing)) as pool:
            futures = {pool.submit(freeze_one, m, mine): m for m, mine in missing.items()}
            for future in as_completed(futures):
                try:
                    out[futures[future]] = future.result()
                except Exception as exc:          # noqa: BLE001 - raised after all metrics finish
                    failures.append(exc)
        if failures:
            raise failures[0]
    return out


# --- benchmark standards: frozen once, model-independent, human-approved ----------------
#
# Layout: test_data/bench_standards/<suite>/<criteria version>/<GameID>/
#     <metric>.json      draft standard (generated once; may be edited by the reviewer)
#     review.md          readable sheet for human review
#     approved.json      {metric: sha256 of <metric>.json, approved_at, reviewer} — the only thing
#                        evaluation trusts; a later edit invalidates the approval
# Inputs are model-independent only: the case requirement, the criteria / task texts and,
# for stage3, the shared baseline project every model starts from. No candidate is consulted.

from datetime import datetime, timezone

from .paths import BENCH

BENCH_STANDARDS = BENCH / 'test_data' / 'bench_standards'
BENCH_NOTE = ('\n\nBENCHMARK STANDARD: no candidate deliveries are given. Use only the case requirement, the CHECKS '
              'and, if listed, the shared BASELINE project (the common starting point of every model; read-only). '
              'Ignore any instruction above about reading deliveries. The standard must be implementation-neutral: '
              'describe the intended visible outcome and correct target in terms of the requirement, so that it '
              'applies equally to every model and to models evaluated later. Write visible_goal, result_frame_description, '
              'correct_target(_and_information), necessary_context and representative_basic_function ONLY in terms a '
              'screenshot can show (which object, what visibly happens, what the screen shows). Never put distances, '
              'durations, delays, angles, speeds, percentages or exact trigger moments in those fields: such numbers '
              'cannot be verified from frames and are checked only in source code (10% tier). '
              'Every CHECK is tested, so keep each one focused: define exactly ONE principal visible outcome (the core '
              'of the task) in one or two sentences per field; do not turn its acceptance bullets, branches, '
              'concurrency, pause/restart or edge cases into extra conditions (they stay in the original requirement '
              f'as diagnostics); list at most {MAX_BUGS} basic_function_bugs, the most important ones.')


LEAN_NOTE = (' LEAN RUBRIC: every check is kept, but its rubric is minimal. visible_goal and '
             'result_frame_description name only the single core effect a player would see (what changes on '
             'which object) - never a specific message text, label, count, item quantity or exact value, and never '
             'require that a particular UI panel is opened unless the task itself is about that panel. Any frame in '
             'which that core effect is visibly present suffices. necessary_context: at most one short clause. '
             'representative_basic_function: the feature visibly responds on the right object. List at most 2 basic '
             'bugs, the obvious functional failures only.')


def bench_dir(suite: str, criteria_version: str, game_id: str) -> Path:
    return BENCH_STANDARDS / suite / (criteria_version + (f'+{STANDARD_SET}' if STANDARD_SET else '')) / game_id


def draft(game_id: str, rows: list[dict], *, suite: str, criteria_version: str, requirement: Path,
          model: str, timeout: int = 1800, baseline: Path | None = None) -> dict:
    """Generate missing draft standards for every tiered metric of a case (concurrently)."""
    folder = bench_dir(suite, criteria_version, game_id)
    folder.mkdir(parents=True, exist_ok=True)
    metrics = suites.get(suite).metrics
    work = folder / 'input'
    work.mkdir(exist_ok=True)
    (work / 'requirement.txt').write_bytes(Path(requirement).read_bytes())
    context = {'requirement': 'requirement.txt', 'baseline_project': str(baseline) if baseline else None}
    write_json(work / 'context.json', context)
    todo = {m: [r for r in rows if r['metric'] == m] for m in suites.tiered(suites.get(suite))}
    if LEAN:       # lean set rewrites only mechanic / gamefeel; other metrics reuse the base approved files
        base = BENCH_STANDARDS / suite / criteria_version / game_id
        for m in list(todo):
            if m not in ('mechanic', 'gamefeel') and (base / f'{m}.json').is_file() and not (folder / f'{m}.json').is_file():
                shutil.copy2(base / f'{m}.json', folder / f'{m}.json')
    todo = {m: rs for m, rs in todo.items() if rs and not (folder / f'{m}.json').is_file()}

    def one(metric, mine):
        checks = [{'id': r['id'], 'group': r['group'], 'requirement': r['requirement']} for r in mine]
        prompt = (metrics[metric].STANDARD_PROMPT + BENCH_NOTE + (LEAN_NOTE if LEAN and metric in LEAN_METRICS else '')
                  + ('\nBASELINE (read-only shared starting point): ' + str(baseline) if baseline else '')
                  + '\nREQUIREMENT: requirement.txt\nCHECKS\n' + json.dumps(checks, ensure_ascii=False))
        standard = call_model(folder / 'model_calls', name=metric, prompt=prompt, schema=schema(metric, mine, metrics),
                              cwd=work, model=model, timeout=timeout,
                              read_dirs=[folder, *([Path(baseline)] if baseline else [])],
                              validator=lambda v: validate(metric, mine, v, metrics))
        write_json(folder / f'{metric}.json', {
            'version': VERSION, 'suite': suite, 'criteria_version': criteria_version, 'metric': metric,
            'game_id': game_id, 'model': model, 'inputs': context,
            'requirement_sha256': sha256(work / 'requirement.txt'),
            'criteria_ids': [r['id'] for r in mine], 'standard': standard})

    failures = []
    if todo:
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            futures = {pool.submit(one, m, rs): m for m, rs in todo.items()}
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as exc:   # noqa: BLE001 - reported after all metrics finish
                    failures.append(f'{futures[f]}: {exc}')
    write_review(folder, rows, suite)
    return {'game_id': game_id, 'generated': sorted(set(todo) - {x.split(':')[0] for x in failures}),
            'failed': failures}


def write_review(folder: Path, rows: list[dict], suite: str) -> Path:
    """Readable review sheet of every drafted metric of one case."""
    req = {r['id']: r for r in rows}
    lines = [f'# Benchmark standard review — {folder.name}', '',
             f'Directory: `{folder}`', '',
             'Edit `<metric>.json` if needed, then approve with '
             f'`python scripts_new/freeze_standards.py --stage {suite[-1]} --approve {folder.name}`.', '']
    for f in sorted(folder.glob('*.json')):
        if f.name in ('approved.json',):
            continue
        data = read_json(f)
        if 'standard' not in data:
            continue
        std = data['standard']
        lines += [f'## {data["metric"]} ({len(std["checks"])} checks)', '', std.get('summary', ''), '']
        for cid, c in std['checks'].items():
            group = req.get(cid, {}).get('group', '')
            lines += [f'### `{cid}` {group}', '',
                      f'- **Requirement**: {c["original_requirement_diagnostic_only"][:400]}',
                      f'- **Visible goal**: {c["visible_goal"]}',
                      f'- **Result frame (100%)**: {c["result_frame_description"]}',
                      f'- **Correct target**: {c.get("correct_target") or c.get("correct_target_and_information")}',
                      f'- **Necessary context**: {c["necessary_context"]}',
                      f'- **Basic function (50%)**: {c["representative_basic_function"]}',
                      f'- **Basic bugs**: ' + '; '.join(c['basic_function_bugs']),
                      f'- **Trigger modes**: ' + ', '.join(c['permitted_trigger_modes']), '']
    path = folder / 'review.md'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


def approve(folder: Path, reviewer: str) -> dict:
    files = {f.stem: sha256(f) for f in sorted(folder.glob('*.json'))
             if f.name != 'approved.json' and 'standard' in read_json(f)}
    if not files:
        raise ValueError(f'{folder}: nothing to approve')
    data = {'approved_at': datetime.now(timezone.utc).isoformat(), 'reviewer': reviewer, 'metrics': files}
    write_json(folder / 'approved.json', data)
    write_review(folder, [], folder.parts[-3])
    return data


def load(suite: str, criteria_version: str, game_id: str, rows: list[dict]) -> dict:
    """Approved benchmark standards for a case; refuses missing, unapproved or edited-after-approval ones."""
    folder = bench_dir(suite, criteria_version, game_id)
    approved = folder / 'approved.json'
    if not approved.is_file():
        raise ValueError(f'no approved benchmark standard for {game_id} ({suite}/{criteria_version}); '
                         f'run scripts_new/freeze_standards.py and approve it first')
    shas = read_json(approved)['metrics']
    metrics, out = suites.get(suite).metrics, {}
    for metric in suites.tiered(suites.get(suite)):
        mine = [r for r in rows if r['metric'] == metric]
        if not mine:
            continue
        path = folder / f'{metric}.json'
        if metric not in shas or not path.is_file() or sha256(path) != shas[metric]:
            raise ValueError(f'{game_id}/{metric}: benchmark standard missing or changed after approval')
        data = read_json(path)
        validate(metric, mine, data['standard'], metrics)
        out[metric] = data['standard']
    return out
