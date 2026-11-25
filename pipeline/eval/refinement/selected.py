"""Run selected Stage3 dimensions through the production planner/recorder/judge.

Criteria and approved standards stay frozen. Unrequested dimensions are absent
from the score, and are never dispatched to a judge. Historical plans are reused
only with identical source, snapshot and criteria bindings. Published prior
scores remain at their original paths.
"""
from __future__ import annotations

import copy
import fcntl
import shutil
import time
from pathlib import Path

from ..stage1 import budgets, evidence, judge, plan, prepare, standards
from ..stage1 import pipeline, record, suites
from ..whitebox.llm import HarnessError
from ..whitebox.paths import read_json, sha256, write_json

ALLOWED = ('mechanic', 'gamefeel')


def final_verdicts(out: Path, upto: int = plan.MAX_TAKES) -> dict:
    """Apply a source-bound original-pixel rejudge only after full publication."""
    result = pipeline.final_verdicts(out, upto=upto)
    receipt = out / 'original_image_recovery.json'
    if receipt.is_file():
        binding = read_json(receipt)
        if binding['manifest_sha256'] != sha256(out / 'manifest.json'):
            raise HarnessError('Original image recovery source binding changed')
        target = out / binding['verdicts']
        if (binding['version'] != 'stage3-original-image-rejudge.v1'
                or target.parent != out or sha256(target) != binding['verdicts_sha256']):
            raise HarnessError('Original image recovery verdict binding changed')
        # The manifest alone does not bind the recording or the accepted model
        # input. Recheck the immutable parents and the delivery receipts before
        # allowing the overlay to replace historical verdicts.
        parent = read_json(out / binding['old_materials'] / 'parent.json')
        for relative, digest in parent['bindings'].items():
            if relative == 'status.json':  # stage metadata may advance after publication
                continue
            source = out / relative
            if source.resolve().is_relative_to(out.resolve()) is False or sha256(source) != digest:
                raise HarnessError('Original image recovery parent binding changed')
        for item in binding['actual_deliveries']:
            actual = out / item['actual_delivery']
            if (not actual.resolve().is_relative_to(out.resolve())
                    or sha256(actual) != item['actual_delivery_sha256']):
                raise HarnessError('Original image recovery delivery binding changed')
            proof = read_json(actual)
            if (proof.get('all_original_pixels_delivered') is not True
                    or not all(image.get('pixel_equal') is True for image in proof['images'])):
                raise HarnessError('Original image recovery lacks complete pixel proof')
        if not binding['actual_deliveries']:
            raise HarnessError('Original image recovery lacks delivery receipts')
        if binding['last_take'] <= upto:
            result.update(read_json(target))
    return result


def eligible_prior(out: Path, dimensions: tuple[str, ...]) -> bool:
    """Require every applicable check, validated credit and an evidence verdict."""
    try:
        manifest = read_json(out / 'manifest.json')
        criteria = read_json(out / 'input/criteria.json')
        if manifest.get('suite') != 'stage3' or manifest['criteria_sha256'] != sha256(out / 'input/criteria.json'):
            return False
        if not (out / 'score.json').is_file():
            return False
        verdicts = final_verdicts(out)
        rows = [r for r in criteria['criteria'] if r['metric'] in dimensions]
        calculated = suites.get('stage3').score(rows, verdicts)
        saved = read_json(out / 'score.json')
        if (saved.get('provisional') is True or saved.get('complete') is not True
                or read_json(out / 'status.json').get('state') != 'done'):
            return False
        for key, value in calculated['dimensions'].items():
            prior = saved['dimensions'].get(key, {})
            if not value['published'] or value['Cov'] != 1 or prior.get('S') != value['S'] or prior.get('Cov') != 1:
                return False
        return bool(rows) and bool(list(out.glob('verdicts_evidence_t[1-9]*.json')))
    except (OSError, KeyError, ValueError):
        return False


def selected_score(out: Path, dimensions: tuple[str, ...], *, provisional: bool) -> dict:
    rows = [r for r in read_json(out / 'input/criteria.json')['criteria'] if r['metric'] in dimensions]
    result = suites.get('stage3').score(rows, final_verdicts(out))
    manifest = read_json(out / 'manifest.json')
    result.update(game_id=manifest['game_id'], suite='stage3', measured_metrics=list(dimensions),
                  status='SCORED_PENDING_AUDIT', models=manifest['models'], provisional=provisional,
                  scope_note='Only the requested dimensions; this is not a complete five-dimension evaluation.')
    write_json(out / 'score.json', result)
    return result


def reuse_plan(root: Path | None, out: Path, manifest: dict, take: int) -> bool:
    if root is None:
        return False
    binding_file = out / 'plan_source.json'
    if binding_file.is_file():
        parents = [Path(read_json(binding_file)['run'])]
    else:
        parents = sorted((root / out.parents[1].name / manifest['game_id']).glob('*'), reverse=True)
    for parent in parents:
        src = parent / 'takes' / str(take) / 'plan.json'
        if not src.is_file() or not (parent / 'manifest.json').is_file():
            continue
        old = read_json(parent / 'manifest.json')
        if any(old.get(k) != manifest.get(k) for k in ('project_digest', 'snapshot_digest', 'criteria_sha256', 'engine', 'entry')):
            continue
        candidate = read_json(src)
        validated = copy.deepcopy(candidate)
        plan.validate(validated, manifest, out / 'input/project')
        if validated != candidate:
            raise HarnessError('Historical plan needs normalization; refusing to relabel it unchanged')
        if old.get('models', {}).get('planner') != manifest['models']['planner']:
            continue
        write_json(binding_file, {'run': str(parent.resolve()), 'manifest_sha256': sha256(parent / 'manifest.json')})
        coverage = src.with_name('plan_coverage.json')
        if not coverage.is_file():
            raise HarnessError(f'Historical plan is missing coverage metadata: {coverage}')
        plan.take_dir(out, take).mkdir(parents=True, exist_ok=True)
        shutil.copyfile(coverage, plan.take_dir(out, take) / 'plan_coverage.json')
        write_json(plan.take_dir(out, take) / 'plan.json', candidate)
        write_json(plan.take_dir(out, take) / 'plan_reuse.json', {
            'source': str(src), 'sha256': sha256(src), 'models': old['models'],
            'binding': {k: old[k] for k in ('project_digest', 'snapshot_digest', 'criteria_sha256')}})
        return True
    return False


def run(delivery: Path, out: Path, *, models: dict, dimensions: tuple[str, ...], reuse_root: Path | None = None, replay_plans: bool = False) -> dict:
    if not dimensions or set(dimensions) - set(ALLOWED):
        raise ValueError(f'Selected Stage3 currently supports {ALLOWED}')
    if replay_plans and reuse_root is None:
        raise ValueError('Plan replay requires a historical root')
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.selected_eval.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HarnessError(f'Another evaluator owns {out}') from exc
        return _run(delivery, out, models, dimensions, reuse_root, replay_plans)


def _run(delivery, out, models, dimensions, reuse_root, replay_plans=False):
    step = 'prepare'
    started = time.monotonic()
    try:
        if not (out / 'manifest.json').is_file():
            contract = read_json(delivery / 'delivery.json')
            project = (delivery / contract['project_root']).resolve()
            hashes = prepare.tree_hashes(project)
            estimate = 2 * sum((project / name).stat().st_size for name in hashes)
            free = shutil.disk_usage(out).free
            write_json(out / 'disk_preflight.json', {'free_bytes': free, 'copy_estimate_bytes': estimate, 'reserve_bytes': 8 * 1024**3})
            if free < estimate + 8 * 1024**3:
                raise HarnessError('Insufficient space for both snapshots plus the 8 GiB reserve')
        manifest = prepare.prepare(delivery, out, models=models, suite='stage3')
        if manifest['models'] != models:
            raise HarnessError('Existing run uses different planner/judge models')
        request = {'dimensions': list(dimensions), 'models': models, 'standard_set': standards.STANDARD_SET
                   if hasattr(standards, 'STANDARD_SET') else 'original'}
        if replay_plans:
            request['plan_policy'] = 'replay_existing_only'
        request_file = out / 'selected_request.json'
        if request_file.is_file() and read_json(request_file) != request:
            raise HarnessError('Existing selected request differs; refusing to mix results')
        if (out / 'status.json').is_file() and read_json(out / 'status.json').get('state') == 'done' and eligible_prior(out, dimensions):
            return read_json(out / 'score.json')
        write_json(request_file, request)
        prepare.verify(out)
        criteria = read_json(out / 'input/criteria.json')
        rows = [r for r in criteria['criteria'] if r['metric'] in dimensions]
        step = 'standards'
        frozen = standards.load('stage3', criteria['version'], manifest['game_id'], rows)
        ids = [r['id'] for r in rows if r['mode'] != 'static']
        history, pending, feedback, take_secs = [], ids, None, []
        for take in range(1, plan.MAX_TAKES + 1):
            if take_secs and pipeline.PROJECT_BUDGET_S - (time.monotonic() - started) < sum(take_secs) / len(take_secs):
                break
            clock = time.monotonic()
            take_manifest = {**manifest, 'budget': budgets.for_take(manifest['budget'], take)}
            step = f'plan_t{take}'
            pipeline._status(out, step, 'running', measured_metrics=list(dimensions))
            if not (plan.take_dir(out, take) / 'plan.json').is_file():
                reused = reuse_plan(reuse_root, out, take_manifest, take)
                if replay_plans and not reused:
                    if take == 1:
                        raise HarnessError('No source-bound historical take-1 plan; replay cannot request a new plan')
                    write_json(out / 'plan_replay_exhausted.json', {'next_take': take, 'reason': 'No further validated plan in the bound historical run'})
                    break
            if replay_plans and not (plan.take_dir(out, take) / 'plan_reuse.json').is_file():
                raise HarnessError('Replay take lacks historical plan provenance')
            executable = plan.make_plan(out, take_manifest, take, pending, feedback)
            step = f'record_t{take}'
            pipeline._status(out, step, 'running', measured_metrics=list(dimensions))
            prepare.verify(out)
            record.record(out, take_manifest, executable, take)
            step = f'evidence_t{take}'
            ev = evidence.build(out, list(range(1, take + 1)))
            step = f'evidence_judge_t{take}'
            pipeline._status(out, step, 'running', measured_metrics=list(dimensions))
            judge.judge(out, manifest, ev, 'evidence', frozen, only_ids=pending, tag=f'_t{take}')
            verdicts = final_verdicts(out, upto=take)
            remaining = pipeline.unresolved(rows, verdicts, suites.get('stage3').metrics)
            resolved = len(pending) - len(remaining)
            history.append({'take': take, 'targets': len(pending), 'remaining': len(remaining), 'resolved': resolved})
            take_secs.append(time.monotonic() - clock)
            write_json(out / 'takes.json', {'max_takes': plan.MAX_TAKES, 'history': history, 'remaining': remaining,
                                           'budget_s': pipeline.PROJECT_BUDGET_S, 'take_seconds': take_secs})
            selected_score(out, dimensions, provisional=True)
            if not remaining or (take > 1 and resolved == 0):
                break
            pending, feedback = remaining, pipeline._feedback(out, take + 1, remaining, verdicts)
        result = selected_score(out, dimensions, provisional=False)
        pipeline._status(out, 'score', 'done', complete=result['complete'], measured_metrics=list(dimensions))
        return result
    except Exception as exc:
        pipeline._status(out, step, 'HARNESS_ERROR', error=f'{type(exc).__name__}: {exc}', measured_metrics=list(dimensions))
        if (out / 'input/criteria.json').is_file():
            selected_score(out, dimensions, provisional=True)
        raise
