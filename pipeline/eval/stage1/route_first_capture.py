"""Route-first planning guidance and explicitly unscored native startup observations."""
import re
import os
import hashlib
from pathlib import Path

from pipeline.eval.stage1 import batch, endpoint_sparse
from pipeline.eval.stage1.protocol import dump, load_lines, sha


PROMPT_POLICY = 'whitebox-route-first-prompt.v1'
COMPACT_PROMPT_POLICY = 'whitebox-route-first-prompt.v2'
LEAN_PROMPT_POLICY = 'whitebox-route-first-prompt.v3'


def install_compact_policy(root, *, version=None):
    from pipeline.eval.stage1.protocol import sha
    if (root/'sol_plan.json').exists() or (root/'model_calls/plan').exists():
        raise ValueError('Compact prompt requires a fresh unplanned attempt')
    path = root/'planning_prompt_policy.json'
    if version is None:
        version = batch.read(path)['version'] if path.exists() else LEAN_PROMPT_POLICY
    modules = {COMPACT_PROMPT_POLICY:'compact_unity_planning.py',
               LEAN_PROMPT_POLICY:'lean_unity_planning.py'}
    if version not in modules:
        raise ValueError('Unknown compact prompt version')
    source = Path(__file__).with_name(modules[version])
    record = {'version':version, 'scope':'new Unity closed-endpoint plans',
              'template_sha256':sha(source)}
    if path.exists() and batch.read(path) != record:
        raise ValueError('Existing prompt policy is immutable; use a new attempt')
    frozen = root/'planning_prompt_template.py'
    if frozen.exists() and sha(frozen) != record['template_sha256']:
        raise ValueError('Existing frozen prompt template differs')
    if not frozen.exists():
        import shutil
        shutil.copyfile(source, frozen)
    dump(path, record)


def submitted_plan_schema(root, schema):
    """Only fresh v3 attempts factor repeated nodes; frozen identity stays unchanged."""
    policy = root/'planning_prompt_policy.json'
    if not policy.is_file() or batch.read(policy).get('version') != LEAN_PROMPT_POLICY:
        return schema
    template = root/'planning_prompt_template.py'
    if not template.is_file() or batch.read(policy).get('template_sha256') != sha(template):
        raise ValueError('Frozen lean schema template changed')
    import importlib.util
    spec = importlib.util.spec_from_file_location('frozen_lean_schema', template)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compact_schema(schema)


def normalized_prompt(prompt):
    old = '''Opening menus, movement, resource acquisition, waiting, victory, failure, pause and restart are
included ONLY when a core target or its prerequisites requires them. There is no independent
outcome/restart sequence requirement. Use shared setup and continuous routes across targets;
do not force'''
    new = '''Mechanic actions cover only the frozen endpoints and their prerequisites. Plan independent
Gameness observations of stable menu/layout/HUD and necessary short windows around actual inputs,
animation and motion; these add no mechanism scoring targets. Use shared continuous routes;
do not force'''
    prompt = prompt.replace(old, new)
    prompt = prompt.replace('endings, boundary cases, recovery paths, visual checks or assets.',
                            'endings, boundary cases, recovery paths or asset objectives.')
    old_entry = '''For a genuinely missing configured Unity scene, keep its exact path and real launch_source,
probes=[]; if there is no scene/configuration at all use both paths="", probes=[].'''
    new_entry = '''When the first configured Unity scene is missing, inspect the other configured scenes and
use an actual delivered scene supported by the existing entry source. Preserve the stale entry
as a diagnostic. If no delivered scene can launch, preserve the actual missing entry and use
STARTUP_DIAGNOSTIC with no gameplay inputs; never invent a scene or repair game files.'''
    prompt = prompt.replace(old_entry, new_entry)
    return ('''ROUTE-FIRST PROMPT POLICY: whitebox-route-first-prompt.v1.
Choose summary prefix [NORMAL_GAMEPLAY] or [STARTUP_DIAGNOSTIC]. Normal gameplay needs real
actions and nonempty predeclared endpoint/Gameness captures. Diagnostic observations never
prove gameplay. GUID/meta textual differences alone are warnings, not unreachable evidence.
Plan legal inputs and observation opportunities; runtime determines completion. Preserve the
full frozen rubric and its visible and state/event conditions. Keep the route concise; do not
conduct another GUID audit. Use the existing schema, model, budgets and read-only tools.

''' + prompt)


def plan_with_route_policy(root, model, timeout, engine):
    policy = root/'planning_prompt_policy.json'
    if not policy.is_file():
        return batch.plan(root, model, timeout, engine)
    policy_record = batch.read(policy)
    version = policy_record.get('version')
    if version not in {PROMPT_POLICY, COMPACT_PROMPT_POLICY, LEAN_PROMPT_POLICY}:
        raise ValueError('Unknown route-first prompt policy')
    if version in {COMPACT_PROMPT_POLICY, LEAN_PROMPT_POLICY}:
        template = root/'planning_prompt_template.py'
        if not template.is_file() or policy_record.get('template_sha256') != sha(template):
            raise ValueError('Frozen compact prompt template changed; use its archived version')
    from pipeline.eval.stage1 import core12_planning
    original = core12_planning.prompt
    def build(protocol, selected_engine, identity):
        before = original(protocol, selected_engine, identity)
        if version in {COMPACT_PROMPT_POLICY, LEAN_PROMPT_POLICY}:
            if selected_engine != 'unity3d':
                raise ValueError('Compact native template is currently accepted only for Unity')
            import importlib.util
            spec = importlib.util.spec_from_file_location('compact_unity_planning',template)
            compact = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(compact)
            after = compact.compact_prompt(before, protocol)
        else:
            after = normalized_prompt(before)
        from pipeline.eval.stage1 import multiclient
        if multiclient.enabled(protocol):
            routing = multiclient.prompt(protocol)
            before += routing
            after += routing
        source_scores=root/'static_source_scores.json'
        if source_scores.is_file():
            from .unity_source_review import load
            load(root)
            after += '\nBefore planning read static_source_scores.json and static_code_scores.json. They contain initial source scores and limitations, not runtime proof. Reuse their source bindings; preserve all frozen endpoint obligations.\n'
        from .unity_native_entry import prompt_context
        after += prompt_context(root)
        dump(root/'planning_prompt_transform.json', {
            'version':version, 'original_prompt_sha256':hashlib.sha256(before.encode()).hexdigest(),
            'normalized_prompt_sha256':hashlib.sha256(after.encode()).hexdigest(),
            'original_characters':len(before), 'submitted_characters':len(after),
            'template_sha256':policy_record.get('template_sha256'),
            'frozen_identity_unchanged':True, 'scope':'explicit versioned new attempt'})
        return after
    core12_planning.prompt = build
    try:
        return batch.plan(root, model, timeout, engine)
    finally:
        core12_planning.prompt = original


def planning_feedback(attempt):
    if (attempt/'sol_plan.json').exists() or (attempt/'model_calls/plan').exists():
        return
    pause = attempt/'priority_retry_pause.json'
    if pause.is_file() and batch.read(pause).get('runner_pid') == os.getpid():
        dump(attempt/'priority_retry_pause_receipt.json',{
            'version':'whitebox-priority-retry-pause.v1','runner_pid':os.getpid(),
            'static_sha256':sha(attempt/'static_existence.json'),
            'plan_started':False,'record_started':False,'request':batch.read(pause)})
        raise KeyboardInterrupt('User-requested priority plan retry; accepted static preserved before planning')
    path = attempt/'planning_retry_feedback.json'
    previous = batch.read(path) if path.is_file() else {}
    policy = attempt/'planning_prompt_policy.json'
    if policy.is_file() and batch.read(policy).get('version') in {COMPACT_PROMPT_POLICY, LEAN_PROMPT_POLICY}:
        if previous.get('route_first_policy') == 'whitebox-route-first-plan.v4':
            return
        if previous:
            raise ValueError('Preserve existing retry diagnostic; compact guidance requires a fresh attempt')
        dump(path, {'route_first_policy':'whitebox-route-first-plan.v4',
                    'prompt_policy':batch.read(policy)['version'],
                    'instructions':['Follow the single versioned route-first prompt; no additional objectives.']})
        return
    if previous.get('route_first_policy') == 'whitebox-route-first-plan.v3':
        return
    dump(path, {'route_first_policy':'whitebox-route-first-plan.v3', 'previous_diagnostic':previous,
        'instructions':[
            'Explicitly choose capture mode by starting summary with [NORMAL_GAMEPLAY] or [STARTUP_DIAGNOSTIC]. '
            'Keep the existing JSON schema; do not add fields. NORMAL_GAMEPLAY requires nonempty real capture points. '
            'STARTUP_DIAGNOSTIC is observation only, with waits and no gameplay completion claims. '
            'Every Gameness item needs its own window mapping or a concrete reason it cannot be observed.',
            'GUID/meta text comparisons are diagnostic hints only. Tuanjie may store protected GUIDs. '
            'Never use a textual GUID mismatch alone to declare endpoints UNREACHABLE or omit gameplay inputs.',
            'Read executable source and plan legal player inputs for every reachable frozen endpoint. '
            'Keep last real action, settling wait, stable endpoint frame and original visible/state/event obligations. '
            'Runtime evidence determines whether the input actually triggers the feature.',
            'Choose an actual delivered scene. Prefer a configured scene that exists when an earlier configured entry is missing; '
            'retain the stale entry as a diagnostic. Do not repair or rewrite game files.',
            'Plan Gameness independently of Mechanic reachability. Stable layout/menu/HUD checks need settled real frames; '
            'input feedback, animation and motion need necessary short consecutive windows around real actions. '
            'Reuse suitable shared frames/windows. Even if no mechanism can execute, retain startup and settled observations '
            'for all observable Gameness checks instead of clearing every window. In the existing capture schema, a short '
            '200ms window can cover a stable scene. Do not invent motion, inputs, gameplay or runtime completion. '
            'Keep each actual judge request within 100 images.',
            'Keep the route and explanations concise. No separate GUID investigation, model call, objectives or budget increase. '
            'If no gameplay route exists, retain its concrete limitation; the runner will record two real startup observations '
            'under a separate diagnostic contract, without awarding gameplay credit.'
        ]})


def capture_route(protocol, plan, actions, *, root=None):
    schedule = endpoint_sparse.validate_plan(protocol, plan, 'unity3d')
    schedule['warmup_ms'] = 1000
    summary = plan.get('summary','')
    mode = ('NORMAL_GAMEPLAY' if summary.startswith('[NORMAL_GAMEPLAY]') else
            'STARTUP_DIAGNOSTIC' if summary.startswith('[STARTUP_DIAGNOSTIC]') else
            'PARTIAL_OBSERVATION' if summary.startswith('[PARTIAL_OBSERVATION]') else None)
    explicit = mode is not None
    if root is not None:
        feedback = root/'planning_retry_feedback.json'
        if feedback.is_file() and batch.read(feedback).get('route_first_policy') in {'whitebox-route-first-plan.v3','whitebox-route-first-plan.v4'} and not explicit:
            raise ValueError('Plan must explicitly choose NORMAL_GAMEPLAY or STARTUP_DIAGNOSTIC')
    gameness = plan.get('capture_plan',{}).get('gameness',{})
    for ident,row in gameness.items():
        if not row.get('window_ids') and not row.get('reason','').strip():
            raise ValueError('Gameness needs independent capture mapping or a concrete unobservable reason: '+ident)
    mode = mode or ('NORMAL_GAMEPLAY' if schedule['points'] else 'STARTUP_DIAGNOSTIC')
    if mode == 'NORMAL_GAMEPLAY' and not schedule['points']:
        raise ValueError('Normal gameplay plan cannot have zero capture points')
    if root is not None:
        dump(root/'capture_route_contract.json',{'version':'whitebox-capture-route.v1','mode':mode,
            'explicit_planner_choice':explicit,'legacy_inference':not explicit,
            'source_plan_sha256':sha(root/'sol_plan.json'),'gameness':gameness,
            'diagnostic_only':mode == 'STARTUP_DIAGNOSTIC'})
    if mode in {'NORMAL_GAMEPLAY', 'PARTIAL_OBSERVATION'}:
        if not schedule['points']:
            raise ValueError('Usable observation route needs actual predeclared capture points')
        return schedule, actions, None
    if any(row.get('action') != 'wait' for row in actions):
        raise ValueError('Startup diagnostic cannot execute gameplay input or masquerade as gameplay')
    elapsed = sum(row.get('duration_ms',100) for row in actions)
    settled = max(elapsed,2200)
    started = min(1800,settled-500)
    diagnostic = {'version':'whitebox-startup-diagnostic.v1',
        'reason':'Observe actual startup and the end of existing waits without inventing mechanism evidence.',
        'observations':[{'id':'diagnostic/started','at_ms':started},
                        {'id':'diagnostic/settled','at_ms':settled}],
        'original_wait_ms':elapsed,'capture_tail_ms':settled+500-elapsed,
        'observable_domains':['startup_layout','settled_layout','menu_or_hud_if_visible'],
        'unproved_domains':['mechanic_completion','input_feedback_without_input','animation_or_motion_without_observation'],
        'gameplay_credit':False, 'formal_publication':False}
    schedule.update(kind=diagnostic['version'], plan={'endpoints':{},'windows':[]},
        points=[{'at_ms':row['at_ms'],'capture_ids':[row['id']]} for row in diagnostic['observations']])
    return schedule, actions+[{'action':'wait','duration_ms':settled+500-elapsed}], diagnostic


def archive_diagnostic(attempt, contract):
    take = attempt/'background_record/take'
    observed = {ident:row for row in load_lines(take/'frame_index.jsonl')
                for ident in row.get('capture_ids',[]) if ident.startswith('diagnostic/')}
    if any(row['id'] not in observed for row in contract['observations']):
        raise ValueError('Startup diagnostic requires both actual predeclared observation frames')
    ordered = [observed[row['id']] for row in contract['observations']]
    if (len({row['path'] for row in ordered}) < 2
            or any(right['t_ms'] <= left['t_ms'] for left,right in zip(ordered,ordered[1:]))):
        raise ValueError('Startup diagnostic needs distinct physical observation frames and increasing timestamps')
    log = attempt/'background_record/project/Library/GameFactory3A/Editor.log'
    warnings = [{'line':number,'text':line} for number,line in enumerate(log.read_text(errors='replace').splitlines(),1)
                if re.search(r'referenced script.*missing|script.*could not be loaded|error CS\d+|missing.*behaviour',line,re.I)]
    report = {**contract,'status':'ENTRY_SCRIPT_ERROR_OBSERVED' if warnings else 'STARTED_OBSERVATIONS_RECORDED',
        'scene_observation':'REQUIRES_FRAME_REVIEW', 'attempt':str(attempt),
        'frames':{ident:{**row,'sha256':sha(take/row['path'])} for ident,row in observed.items()},
        'native_log':{'path':str(log),'sha256':sha(log),'script_errors':warnings},
        'state_trace':{'path':str(take/'state_trace.jsonl'),'sha256':sha(take/'state_trace.jsonl')},
        'cleanup':batch.read(attempt/'background_record/verification.json')['checks']}
    dump(attempt/'startup_diagnostic_report.json',report)
    return report


def validate_startup_correction(source):
    if any((source/name).exists() for name in ['scores.json','runtime_plan_correction.json']):
        raise ValueError('Startup correction cannot repeat or replace a score')
    schedule = batch.read(source/'capture_schedule.json')
    plan = batch.read(source/'sol_plan.json')
    if schedule['points'] or any(row['reachability'] != 'UNREACHABLE'
                                 for row in plan['capture_plan']['endpoints'].values()):
        raise ValueError('Startup correction requires a zero-sample, all-unreachable planning error')
    capture = source/'background_record'
    verification = batch.read(capture/'verification.json')
    receipt = batch.read(capture/'runner_exit.json')
    if (receipt.get('cleanup_verified') is not True or receipt.get('policy_violations')
            or any(verification['checks'].get(key) is not True
                   for key in ['input_cleanup','view_cleanup','process_cleanup','original_unchanged'])):
        raise ValueError('Startup correction requires certain cleanup and unchanged source')
    frames = load_lines(capture/'take/frame_index.jsonl')
    if len(frames) != 1 or frames[0].get('capture_ids') != ['readiness']:
        raise ValueError('Preserve gameplay recordings; correction only accepts a lone readiness frame')
    frame = capture/'take'/frames[0]['path']
    if not frame.is_file():
        raise ValueError('Startup observation frame is missing')
    states = load_lines(capture/'take/state_trace.jsonl')
    if not any(value is True and key.endswith('.isActiveAndEnabled')
               for row in states for key,value in row.get('state',{}).items()):
        raise ValueError('Startup correction requires an observed active runtime component')
    return {'version':'whitebox-runtime-entry-correction.v1',
        'source_attempt':str(source),'source_plan_sha256':sha(source/'sol_plan.json'),
        'observed_frame':{'path':str(frame),'sha256':sha(frame)},
        'state_trace':{'path':str(capture/'take/state_trace.jsonl'),'sha256':sha(capture/'take/state_trace.jsonl')},
        'verification_sha256':sha(capture/'verification.json'),'cleanup_sha256':sha(capture/'runner_exit.json'),
        'reason':'User-authorized route correction after native startup contradicted the all-unreachable static assumption.'}
