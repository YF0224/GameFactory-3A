"""Exact G020 remaining-take continuation. Engineering draft; install before use.

One retained diagnostic take; one remaining native claim. No take1 replay or
qualification, no fallback to the old score, and no implicit execute/resume.
Producer changes require exact reviewed byte manifests, never AST exceptions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import traceback

from . import ue_g020_admission_recovery as old
from pipeline.eval.whitebox.core import pipeline, plan, prepare, playable_rules
from pipeline.eval.whitebox.core.llm import accepted_response
from pipeline.eval.whitebox.core.paths import BENCH, read_json, sha256

VERSION = 'stage1-g020-ui-continuation.v1'
REL = old.REL / 'continuation_v1'
SELF = 'GameFactory-3A/pipeline/eval/stage1/ue_g020_capture_continuation.py'
LIMITS = {'consumed_native_takes': 1, 'remaining_native_takes': 1,
          'only_take': 2, 'recording_ms': 75000, 'max_plan2_responses': 2,
          'cache_policy': 'KEEP_PROJECTS', 'scoring_takes': [2]}
DIAGNOSTIC = {'take': 1, 'role': 'diagnostic_only', 'capture': 'world_only_UI_incomplete',
              'eligible_for_score': False, 'native_budget_consumed': True}
PINS = {
    'failure.json': '9a3be817636068e659efe176df036a7df84950c691848b3774c9bdbb6c00cf81',
    'activation.json': '91ce7a8701b5d0c4de446e1c42c01526aad816b711e33e410b09567c82cbef57',
    'native_dispatch.claim.json': '0be625471012dac9f9c6d5e152c990e199c7da5633a8c20e09175d6bb9d0da62',
    'producer_start.json': '1b45b0c399de5b7b2bcb8add3ef22a224388924028c7df7838bbe7236cc888f9',
    'producer_end.json': '1b45b0c399de5b7b2bcb8add3ef22a224388924028c7df7838bbe7236cc888f9',
    'qualification_hold.json': 'fa14863c33f350ff6941deab8f405f31f2b259802a5fd2b359e1a005d768a27d',
    'child/playable_score.json': '8482cdb3138dd67e0e6b523cdba77f69580d76bc23598c8ea7cf120213f405a0',
    'child/status.json': '530f523b8c693249d3b6a6d1c12fbda8e6fee4a5e964e83d0a27d036f597b346',
    'child/takes/1/record/record_result.json': '89eee3314b40949ca7405105f339b268eadff174a8d0da8a81bacf9dea0ba71b',
}
require, plain, exclusive = old.require, old.plain, old.exclusive


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def installed():
    require(Path(__file__).resolve() == BENCH / SELF, 'draft cannot dispatch evaluation')


def locations(out):
    out = plain(out)
    require(out == old.OUT, 'only exact frozen G020')
    return out / REL, out / REL / 'child'


def retained(out):
    """Old failed recovery stays immutable, including locks ignored by batch.files."""
    folder = out / old.REL
    result = old.tree(folder, skip=('continuation_v1',))
    for path in folder.rglob('*.lock'):
        if 'continuation_v1' not in path.relative_to(folder).parts:
            result[str(path.relative_to(folder))] = sha256(plain(path))
    return result


def review_failure(out):
    locations(out)
    proof, start = old.verify_activation(out)
    folder = out / old.REL
    for rel, value in PINS.items():
        require(sha256(plain(folder / rel)) == value, 'retained failure changed: ' + rel)
    require(read_json(folder / 'producer_end.json')['files'] == start, 'old producer drift')
    require(not (folder / 'second_plan.claim.json').exists(), 'old second take claimed')
    child = folder / 'child'
    require({p.name for p in (child / 'takes').iterdir()} == {'1'}, 'old extra take')
    require({p.name for p in (child / 'model_calls').iterdir()} == {'plan_t1'}, 'old extra model call')
    require(old.tree(child / 'model_calls') == old.tree(out / 'model_calls'), 'old accepted call differs')
    require(old.should_second(read_json(child / 'playable_score.json')), 'formal second take ineligible')
    native = old.native_proof(child, 1, expected_empty=('state_trace.jsonl', 'event_trace.jsonl'))
    return {'parent_proof': proof, 'retained_files': retained(out), 'diagnostic': DIAGNOSTIC,
            'diagnostic_native': native, 'limits': LIMITS}, start


def verify_fix(manifest, old_files, new_files):
    """Externally pinned manifest enumerates *all* actual old/new producer bytes."""
    require(manifest['version'] == 'g020-reviewed-producer-fix.v1', 'wrong fix schema')
    require(manifest['identity'] == old.IDENTITY and manifest['source'] ==
            read_json(old.OUT / '_kimi_batch/attempt.json')['source'], 'wrong fix source/identity')
    require(manifest['old_files_sha256'] == digest(old_files) and
            manifest['new_files_sha256'] == digest(new_files), 'producer map differs')
    actual = old.runner().producer_drift(old_files, new_files)
    rows = manifest['changes']
    require(len(rows) == len({r['path'] for r in rows}), 'duplicate fix path')
    require({r['path']: {'before': r['before_sha256'], 'after': r['after_sha256']} for r in rows}
            == actual, 'unreviewed producer delta')
    require(rows and any(r['purpose'] == 'ui_capture' for r in rows), 'missing actual capture fix')
    for row in rows:
        require(row['purpose'] in ('ui_capture', 'continuation', 'reviewed_concurrent_integration')
                and bool(row['review_reason'].strip()), 'unreviewed fix purpose')
        for side in ('before', 'after'):
            value = row[side + '_sha256']
            archive = row[side + '_archive']
            if value is None:
                require(archive is None, 'absent producer has archive')
            else:
                require(sha256(plain(Path(archive))) == value, 'fix archive changed')
    require(manifest['capture_policy'] == 'slate_window.v1'
            and manifest['native_acceptance'] == 'remaining_take2_then_review_no_extra_take'
            and manifest['author_source_changes'] == [] and manifest['gameplay_injection'] is False,
            'capture/acceptance contract differs')
    old.producer_archive(old_files)


def verify_base(out, *, current=False):
    folder, child = locations(out)
    activation = read_json(folder / 'activation.json')
    proof, previous = review_failure(out)
    require(activation['version'] == VERSION and activation['proof'] == proof
            and activation['limits'] == LIMITS, 'activation/retained lineage changed')
    fix = read_json(folder / 'reviewed_fix.json')
    require(sha256(folder / 'reviewed_fix.json') == activation['review_sha256'], 'reviewed fix changed')
    start = read_json(folder / 'producer_start.json')['files']
    require(digest(start) == activation['producer_sha256'], 'producer start changed')
    verify_fix(fix, previous, start)
    old.producer_archive(start)
    if current:
        require(old.runner().production() == start, 'producer drift after review')
    require(read_json(folder / 'qualification_hold.json') == {'version': VERSION, 'qualified': False},
            'hold changed')
    for rel, value in proof['retained_files'].items():
        require(sha256(plain(folder / 'failure_archive' / rel)) == value, 'failure archive changed')
    a, b = prepare.verify(out), prepare.verify(child)
    require(all(a[k] == b[k] for k in ('delivery', 'delivery_dir', 'project_source', 'project_digest',
            'snapshot_digest', 'input_hashes', 'criteria_sha256', 'models', 'suite', 'engine')), 'child source changed')
    require(old.tree(child / 'model_calls/plan_t1') == old.tree(out / 'model_calls/plan_t1')
            and old.tree(child / 'takes/1') == old.tree(out / 'takes/1', skip=('record',)),
            'accepted plan1 changed or replayed')
    require({p.name for p in (child / 'takes').iterdir()} <= {'1', '2'}, 'third take forbidden')
    require({p.name for p in (child / 'model_calls').iterdir()} <= {'plan_t1', 'plan_t2', 'plan_t2_002'},
            'excess model calls')
    return activation, start


def prepare_child(out, review, review_sha):
    installed()
    folder, child = locations(out)
    r = old.runner()
    with r.locked(old.ROOT / '_kimi_batch/locks/G020.lock'):
        require(not folder.exists(), 'continuation already claimed; retain partial state')
        require(sha256(plain(review)) == review_sha, 'review SHA differs')
        proof, previous = review_failure(out)
        start = r.production()
        fix = read_json(review)
        verify_fix(fix, previous, start)
        r.check_disk(old.ROOT, proof['parent_proof']['target'], proof['parent_proof']['source'])
        r.archive_producer(old.ROOT, start)
        folder.mkdir(exist_ok=False)
        exclusive(folder / 'qualification_hold.json', {'version': VERSION, 'qualified': False})
        shutil.copyfile(review, folder / 'reviewed_fix.json')
        exclusive(folder / 'producer_start.json', {'files': start})
        exclusive(folder / 'activation.json', {'version': VERSION, 'proof': proof, 'limits': LIMITS,
                  'review_sha256': review_sha, 'producer_sha256': digest(start)})
        for rel in proof['retained_files']:
            dst = folder / 'failure_archive' / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            with dst.open('xb') as f:
                f.write((out / old.REL / rel).read_bytes())
        parent = prepare.verify(out)
        prepare.prepare(Path(parent['delivery_dir']), child, models=old.MODELS, suite='stage1', playable_only=True)
        shutil.copytree(out / 'model_calls', child / 'model_calls')
        (child / 'takes/1').mkdir(parents=True)
        for name in ('plan.json', 'plan_coverage.json'):
            shutil.copyfile(out / 'takes/1' / name, child / 'takes/1' / name)
        verify_base(out, current=True)
        return {'prepared': str(child), 'native_dispatched': False, 'needs': 'bounded plan2 and reviewed input route'}


def feedback(out):
    return {'earlier_plans': [read_json(out / 'takes/1/plan.json')['summary']],
            'judge_reasons': {'play.operate': 'Take1 was wait-only, world-only, UI-incomplete diagnostic. '
             'Title is active. Viewport InputKey does not prove Slate button input. No authored keyboard '
             'Title branch/focus was found. The reviewed formal relay now supports exactly one normalized '
             'left mouse_click through the actual game window Slate hit path to an enabled SButton, '
             'then source-supported gameplay keys. Ground the StartButton position in authored layout; '
             'do not use arbitrary button targeting. A source-bound human review of the accepted click '
             'schedule is required before dispatch. Use only delivered source-supported controls; '
             'do not invent menu routing, mouse coordinates, focus or callbacks. If entry is unsupported, '
             'return the truthful partial plan; it will not automatically consume take2.'}}


def make_plan2(out):
    installed()
    folder, child = locations(out)
    with old.runner().locked(old.ROOT / '_kimi_batch/locks/G020.lock'):
        verify_base(out, current=True)
        require(not (folder / 'plan2.claim.json').exists(), 'plan2 already claimed; no retry/reset')
        exclusive(folder / 'plan2.claim.json', {'take': 2, 'max_responses': 2})
        return plan.make_plan(child, old.short_manifest(prepare.verify(child)), 2,
                              ['play.launch', 'play.operate'], feedback(out))


def verify_plan2(child):
    executable = read_json(child / 'takes/2/plan.json')
    require(accepted_response(child / 'model_calls', 'plan_t2') == executable, 'plan2 not accepted')
    pointer = read_json(child / 'model_calls/plan_t2/accepted_response.json')
    n = pointer['attempt']
    require(type(n) is int and n in (1, 2), 'plan2 response limit')
    names = {'plan_t1', 'plan_t2'} | ({'plan_t2_002'} if n == 2 else set())
    require({p.name for p in (child / 'model_calls').iterdir()} == names, 'extra/missing plan calls')
    for name in names - {'plan_t1'}:
        require(read_json(child / 'model_calls' / name / 'invocation.json')['model_requested'] == old.MODELS['planner'],
                'planner route changed')
    plan.validate(executable, old.short_manifest(prepare.verify(child)), child / 'input/project')
    return executable


def verify_input_review(child, review):
    """Human-reviewed source route is a required gate, not inferred from sent=True."""
    p = verify_plan2(child)
    require(review['version'] == 'g020-source-input-review.v1'
            and review['plan_sha256'] == sha256(child / 'takes/2/plan.json')
            and review['snapshot_digest'] == prepare.verify(child)['snapshot_digest'], 'input review binding')
    require(review['reviewer'].strip() and review['entry_reachable_from_title'] is True
            and review['requires_os_input'] is False
            and review['requires_gameplay_injection'] is False, 'unsupported menu/input route')
    from engine_adapters.ue5.playtest import native_client, native_record
    actions = plan.native_actions(p, 'ue5')
    normalized, end_ms = native_client.plan_actions(actions, {})
    require(end_ms <= 75000, 'input schedule exceeds take budget')
    keys = {a['key'] for a in actions if a['action'] == 'key'}
    clicks = [a for a in normalized if a['action'] == 'mouse_click']
    if review['transport'] == native_record.SLATE_MOUSE_SOURCE:
        require(review['requires_slate_dispatch'] is True and len(clicks) == 1
                and all(a['action'] in ('mouse_click', 'key', 'wait') for a in actions),
                'G020 Slate contract permits exactly one title button click')
        require(review['slate_policy'] == native_record.SLATE_MOUSE_POLICY
                and review['normalized_clicks'] == clicks, 'review does not cover exact click schedule')
        first = next(a for a in normalized if a['action'] != 'wait')
        require(first == clicks[0], 'title click must precede gameplay keys')
        required = {'Source/TidalGlyphs/UI/TidalScreens.cpp', 'Source/TidalGlyphs/UI/TidalUICommon.h',
                    'Source/TidalGlyphs/UI/TidalUIController.cpp', 'Source/TidalGlyphs/World/TidalGameMode.cpp'}
        require(required <= {c['path'] for c in review['source_evidence']}, 'title route citations incomplete')
        require(review['entry_route'] == 'Title.StartButton.OnClicked -> OnTitleStartClicked -> OnTitleStart -> BeginNewGame',
                'different title route needs separate review')
    else:
        require(review['transport'] == 'UGameViewportClient::InputKey'
                and review['requires_slate_dispatch'] is False and keys
                and all(a['action'] in ('key', 'wait') for a in actions), 'wait-only/unsupported input')
    require(set(review['keys']) == keys, 'review does not cover exact plan keys')
    require(review['entry_route'] and review['source_evidence'], 'missing grounded entry review')
    for cite in review['source_evidence']:
        rel = Path(cite['path'])
        require(not rel.is_absolute() and '..' not in rel.parts, 'external author citation')
        src = plain(child / 'input/project' / rel)
        lines = src.read_text().splitlines()
        require(sha256(src) == cite['sha256'] and type(cite['line']) is int and 1 <= cite['line'] <= len(lines)
                and lines[cite['line'] - 1] == cite['text'], 'author input citation changed')
    return p


def validate_resume(child, token, models, takes):
    folder, expected = locations(old.OUT)
    require(child == expected and models == old.MODELS and takes == 2, 'foreign/excess continuation')
    verify_base(old.OUT, current=True)
    require(token == sha256(folder / 'activation.json'), 'wrong activation token')
    require(not (folder / 'failure.json').exists(), 'failed continuation cannot replay')
    require(read_json(folder / 'native_dispatch.claim.json')['take'] == 2, 'missing take2 claim')
    require(not (child / 'takes/2/record').exists(), 'take2 already started; no replay')
    return 2, feedback(old.OUT)


def before_record(child, token, take, executable):
    folder, expected = locations(old.OUT)
    require(child == expected and take == 2 and token == sha256(folder / 'activation.json'), 'only take2')
    verify_base(old.OUT, current=True)
    claim = read_json(folder / 'native_dispatch.claim.json')
    require(sha256(folder / 'input_review.json') == claim['input_review_sha256'], 'input review changed')
    require(executable == verify_input_review(child, read_json(folder / 'input_review.json')), 'plan changed')
    require(not (child / 'takes/2/record').exists(), 'take2 replay prohibited')


def execute(out, input_review, input_sha):
    installed()
    folder, child = locations(out)
    with old.runner().locked(old.ROOT / '_kimi_batch/locks/G020.lock'):
        verify_base(out, current=True)
        require(not (folder / 'failure.json').exists() and not (folder / 'native_dispatch.claim.json').exists(),
                'continuation failed/claimed; no reset')
        require(sha256(plain(input_review)) == input_sha, 'input review SHA differs')
        verify_input_review(child, read_json(input_review))
        proof = read_json(folder / 'activation.json')['proof']['parent_proof']
        old.runner().check_disk(old.ROOT, proof['target'], proof['source'])
        shutil.copyfile(input_review, folder / 'input_review.json')
        exclusive(folder / 'native_dispatch.claim.json', {'take': 2, 'limits': LIMITS,
                  'input_review_sha256': input_sha, 'activation_sha256': sha256(folder / 'activation.json')})
        try:
            pipeline.run_playable(Path(prepare.verify(child)['delivery_dir']), child, models=old.MODELS,
                                  takes=2, continuation=sha256(folder / 'activation.json'))
            exclusive(folder / 'native_finished.json', native_proof(child))
            return {'qualified': False, 'needs': 'UI native acceptance review then explicit finalize'}
        except BaseException as exc:
            exclusive(folder / 'failure.json', {'type': type(exc).__name__, 'error': str(exc),
                                              'traceback': traceback.format_exc()})
            raise
        finally:
            end = old.runner().production()
            old.runner().archive_producer(old.ROOT, end)
            exclusive(folder / 'producer_end.json', {'files': end})


def native_proof(child):
    from engine_adapters.ue5.playtest import native_record
    executable = read_json(child / 'takes/2/plan.json')
    require(executable['state_channel'] == 'UNAVAILABLE_STATE_CHANNEL' and executable['watchers'] == [],
            'missing channels cannot be waived for expected instrumentation')
    proof = old.native_proof(child, 2, expected_empty=('state_trace.jsonl', 'event_trace.jsonl'), allow_slate=True)
    native = child / 'takes/2/record/native/take'
    ready = read_json(native / 'play_started.json')
    native_record._validate_capture_surface(ready)
    native_record._validate_ui_frame_sources(native)
    command = read_json(native / 'launch.json')['command']
    require('-RenderOffscreen' not in command and '-A3CaptureSurface=slate_window.v1' in command,
            'UI capture command not qualified')
    admission = read_json(child / 'runtime/ue_admission/admission.json')
    require(admission['project'] == str(child / 'runtime/project') and
            admission['source_project'] == str(child / 'input/project') and
            admission['pin'] == str(child / 'runtime/ue_admission/pin.json'), 'wrong admission copy')
    native_record.verify_pin(admission)
    require(read_json(child / 'runtime/ue_admission/build.json')['ok'] is True and
            read_json(Path(admission['pin']))['build_receipt_sha256'] ==
            sha256(child / 'runtime/ue_admission/build.json'), 'build/pin mismatch')
    old.verify_overlay(child)
    return {**proof, 'capture_policy': 'slate_window.v1', 'scoring_takes': [2]}


def verify_ui_acceptance(child, review):
    native = child / 'takes/2/record/native/take'
    require(review['version'] == 'g020-native-ui-acceptance.v1' and review['take'] == 2
            and review['reviewer'].strip() and review['ui_visible'] is True
            and review['native_proof_sha256'] == digest(native_proof(child)), 'UI acceptance not bound')
    frames = {r['path'] for r in old.rows(native / 'frame_index.jsonl')}
    require(review['frames'] and review['observations'].strip(), 'no reviewed UI pixels')
    for row in review['frames']:
        require(row['path'] in frames and sha256(plain(native / row['path'])) == row['sha256'], 'UI frame changed')


def final_payload(out):
    folder, child = locations(out)
    activation, start = verify_base(out)
    require(not (folder / 'failure.json').exists(), 'failed continuation cannot qualify')
    require(read_json(folder / 'producer_end.json')['files'] == start, 'producer drift during take2')
    old.producer_archive(start)
    claim = read_json(folder / 'native_dispatch.claim.json')
    require(claim == {'take': 2, 'limits': LIMITS, 'input_review_sha256': sha256(folder / 'input_review.json'),
                     'activation_sha256': sha256(folder / 'activation.json')}, 'native claim changed')
    verify_input_review(child, read_json(folder / 'input_review.json'))
    require(read_json(folder / 'plan2.claim.json') == {'take': 2, 'max_responses': 2}, 'plan claim changed')
    proof = native_proof(child)
    require(read_json(folder / 'native_finished.json') == proof, 'native finish changed')
    verify_ui_acceptance(child, read_json(folder / 'ui_acceptance.json'))
    status = read_json(child / 'status.json')
    require(status['state'] == 'done' and status['step'] == 'playable' and status['complete'] is True, 'not done')
    checks = old.rules(child, 2)
    require('HARNESS_ERROR' not in checks.values(), 'formal result incomplete; keep hold')
    score = read_json(child / 'playable_score.json')
    require(score == {'version': playable_rules.VERSION, 'game_id': old.IDENTITY['game_id'], 'engine': 'ue5',
            'planner': old.MODELS['planner'], 'checks': checks, 'takes': [{'take': 2, 'checks': checks}],
            'complete': True, 'playable': round(100 * sum(x == 'PASS' for x in checks.values()) / 3, 2)},
            'score differs from formal take2-only evaluation')
    return {'version': VERSION, 'qualified': True, 'score': score, 'native': proof,
            'diagnostic': DIAGNOSTIC, 'activation_sha256': sha256(folder / 'activation.json'),
            'input_review_sha256': sha256(folder / 'input_review.json'),
            'ui_acceptance_sha256': sha256(folder / 'ui_acceptance.json'),
            'child_evidence': old.evidence(child), 'cache_policy': 'KEEP_PROJECTS', 'freed_bytes': 0}


def verify_completion(out):
    folder, child = locations(out)
    result = final_payload(out)
    require(read_json(folder / 'completion.json') == result, 'completion changed')
    require(read_json(folder / 'replacement.json') == {'version': VERSION, 'child': 'child',
            'completion_sha256': sha256(folder / 'completion.json'),
            'score_sha256': sha256(child / 'playable_score.json')}, 'replacement changed')
    return result['score']


def finalize(out, acceptance, acceptance_sha):
    installed()
    folder, child = locations(out)
    with old.runner().locked(old.ROOT / '_kimi_batch/locks/G020.lock'):
        verify_base(out, current=True)
        require(not (folder / 'replacement.json').exists(), 'already sealed; verify only')
        require(sha256(plain(acceptance)) == acceptance_sha, 'acceptance review SHA differs')
        verify_ui_acceptance(child, read_json(acceptance))
        require(not (folder / 'ui_acceptance.json').exists(), 'acceptance already retained; no overwrite')
        shutil.copyfile(acceptance, folder / 'ui_acceptance.json')
        exclusive(folder / 'completion.json', final_payload(out))
        exclusive(folder / 'replacement.json', {'version': VERSION, 'child': 'child',
                  'completion_sha256': sha256(folder / 'completion.json'),
                  'score_sha256': sha256(child / 'playable_score.json')})
        return verify_completion(out)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--phase', choices=['prepare', 'plan2', 'execute', 'finalize', 'verify'], required=True)
    p.add_argument('--review', type=Path)
    p.add_argument('--review-sha256')
    args = p.parse_args()
    installed()
    if args.phase in ('prepare', 'execute', 'finalize'):
        require(args.review is not None and args.review_sha256 is not None, 'review and SHA required')
        fn = {'prepare': prepare_child, 'execute': execute, 'finalize': finalize}[args.phase]
        result = fn(args.out, args.review, args.review_sha256)
    else:
        result = {'plan2': make_plan2, 'verify': verify_completion}[args.phase](args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
