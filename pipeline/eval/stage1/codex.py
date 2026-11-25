"""Actual Codex CLI integration (no fake planner labels, no fallback model)."""
from __future__ import annotations

import json
import hashlib
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from .protocol import dump
from engine_adapters._mouse_plan import MOUSE_KINDS, UNITY_MOUSE_KINDS, mouse_step_schema
from engine_adapters._input_capabilities import MAX_PROBES, MAX_STEPS, MAX_STEP_MS, key_pattern


def obj(properties):
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def arr(items):
    return {'type': 'array', 'items': items}


S = {'type': 'string'}
N = {'type': 'number'}
I = {'type': 'integer'}
B = {'type': 'boolean'}
COND = obj({'watch': S, 'op': {'type': 'string', 'enum': ['eq', 'ne', 'lt', 'gt', 'distance_lt']}, 'value': N, 'target_watch': S})
STEP = obj({'id': S, 'kind': {'type': 'string', 'enum': ['input', 'wait', 'wait_until', 'move_until', 'look']},
            'key': S, 'duration_ms': I, 'watch': S,
            'op': {'type': 'string', 'enum': ['eq', 'ne', 'lt', 'gt', 'distance_lt']},
            'value': N, 'target_watch': S, 'timeout_ms': I})
PLAN_SCHEMA = obj({'summary': S, 'static_findings': S,
                   'launch_scene': S, 'launch_source': S,
                   'watchers': arr(obj({'id': S, 'script': S, 'index': I, 'property': S})),
                   'probes': arr(obj({'id': S, 'purpose': S, 'criterion_ids': arr(S), 'preconditions': arr(COND), 'steps': arr(STEP)})),
                   'max_duration_ms': I})
# Non-Godot collectors discover only their existing read-only channels. A plan
# must not invent a Godot watcher or an in-game callable observer for them.
import copy
NATIVE_PLAN_SCHEMA = copy.deepcopy(PLAN_SCHEMA)
NATIVE_PLAN_SCHEMA['properties'].update({
    'engine': S,
    'launch_scene': S,
    'launch_source': S,
    'state_channel': {'type': 'string', 'enum': ['adapter_discovery', 'UNAVAILABLE_STATE_CHANNEL']},
    'expected_observations': arr(S),
    'end_conditions': arr(S),
    'failure_conditions': arr(S),
})
NATIVE_PLAN_SCHEMA['required'] = list(NATIVE_PLAN_SCHEMA['properties'])
# Mirror the bounded executor in the model's output contract. Previously the
# schema accepted empty Godot plans that could never be executed. Native
# diagnostic-only plans may still have no probes when the delivered scene is
# absent; validate_native_plan checks that case against the actual files.
PLAN_SCHEMA['properties']['watchers'].update(minItems=1, maxItems=32)
PLAN_SCHEMA['properties']['probes'].update(minItems=1, maxItems=10)
NATIVE_PLAN_SCHEMA['properties']['watchers'].update(minItems=0, maxItems=0)
NATIVE_PLAN_SCHEMA['properties']['probes'].update(minItems=0, maxItems=10)
for _schema in (PLAN_SCHEMA, NATIVE_PLAN_SCHEMA):
    # Do not mutate the shared integer schema used by watcher indexes and
    # other integer fields when bounding the plan duration.
    _schema['properties']['max_duration_ms'] = {
        'type': 'integer',
        'minimum': 1000,
        'maximum': 75000,
    }
    _schema['properties']['probes']['items']['properties']['steps'].update(minItems=1, maxItems=24)
for _kind in ('purpose', 'expected_observation'):
    _step = NATIVE_PLAN_SCHEMA['properties']['probes']['items']['properties']['steps']['items']
    _step['properties'][_kind] = S
    _step['required'].append(_kind)

# Keep the planner's output contract consistent with the bounded executors.
# In particular, "look" is an actual mouse movement, not passive observation.
# Invalid model output must be rejected, never silently rewritten as a wait.
for _schema in (PLAN_SCHEMA, NATIVE_PLAN_SCHEMA):
    _step = _schema['properties']['probes']['items']['properties']['steps']['items']
    for _field in ('duration_ms', 'timeout_ms'):
        _step['properties'][_field] = {'type': 'integer', 'minimum': 0, 'maximum': 6000}
PLAN_SCHEMA['properties']['watchers']['items']['properties']['index'] = {
    'type': 'integer', 'minimum': 0, 'maximum': 16,
}
_godot_step = PLAN_SCHEMA['properties']['probes']['items']['properties']['steps']['items']
_non_look_step, _look_step = copy.deepcopy(_godot_step), copy.deepcopy(_godot_step)
_non_look_step['properties']['kind']['enum'] = ['input', 'wait', 'wait_until', 'move_until']
_look_step['properties']['kind']['enum'] = ['look']
_look_step['properties']['key'] = {'type': 'string', 'enum': ['Left', 'Right', 'Up', 'Down']}
_look_step['properties']['value'] = {'type': 'number', 'minimum': 0, 'maximum': 1000}
PLAN_SCHEMA['properties']['probes']['items']['properties']['steps']['items'] = {
    'anyOf': [_non_look_step, _look_step] + [mouse_step_schema(kind) for kind in sorted(MOUSE_KINDS)],
}
_native_step = NATIVE_PLAN_SCHEMA['properties']['probes']['items']['properties']['steps']['items']
_native_step['properties']['kind']['enum'] = ['input', 'wait']
_native_step['properties']['timeout_ms'] = {'type': 'integer', 'enum': [0]}

REF = obj({'id': S, 'line_start': I, 'line_end': I, 'observation': S})
CHECK = obj({'id': S, 'status': {'type': 'string', 'enum': ['PASS', 'FAIL', 'UNVERIFIED']},
             'reason': S, 'preconditions_met': B, 'observation_complete': B,
             'counterexample': S, 'evidence': arr(REF)})
JUDGE_SCHEMA = obj({'summary': S, 'limitations': arr(S), 'checks': arr(CHECK)})


def plan_schema_for_budget(engine: str, max_gameplay_ms: int, atom_ids=()):
    """Create a strict v4 planner schema without changing legacy v3 schemas."""
    schema = copy.deepcopy(PLAN_SCHEMA if engine == 'godot' else NATIVE_PLAN_SCHEMA)
    if engine in {'three_js', 'unity3d'}:
        steps = schema['properties']['probes']['items']['properties']['steps']
        steps['items'] = {'anyOf': [steps['items']] + [mouse_step_schema(kind, native=True) for kind in sorted(UNITY_MOUSE_KINDS if engine == 'unity3d' else MOUSE_KINDS)]}
    if engine in {'godot', 'three_js'}:
        schema['properties']['probes']['maxItems'] = MAX_PROBES
        schema['properties']['watchers']['minItems'] = 0
        steps = schema['properties']['probes']['items']['properties']['steps']
        steps['maxItems'] = MAX_STEPS
        for branch in steps['items'].get('anyOf', [steps['items']]):
            fields = branch['properties']
            if 'key' in fields and fields['kind'].get('enum') != ['look']:
                fields['key'] = {'type': 'string', 'pattern': key_pattern(mouse=engine == 'godot') + '|^$'}
            if fields['kind'].get('enum', [''])[0].startswith('mouse_'): continue
            for field in ('duration_ms', 'timeout_ms'):
                if field in fields and 'enum' not in fields[field]: fields[field]['maximum'] = MAX_STEP_MS
    schema['properties']['max_duration_ms']['maximum'] = max_gameplay_ms
    if atom_ids:
        schema['properties']['coverage'] = arr(obj({
            'atom_id': {'type': 'string', 'enum': list(atom_ids)},
            'start_ms': {'type': 'integer', 'minimum': 0},
            'end_ms': {'type': 'integer', 'minimum': 1},
            'expected_game_time_ms': {'type': 'integer', 'minimum': 0},
            'stop_condition': S,
        }))
        schema['properties']['coverage'].update(minItems=len(atom_ids), maxItems=len(atom_ids))
        schema['required'].append('coverage')
    return schema


def keyed_plan_schema_for_budget(engine: str, max_gameplay_ms: int, atom_ids=(), criterion_ids=(), *, max_steps_per_probe: int | None = None):
    """Keyed wire format prevents duplicate/omitted atomic coverage declarations."""
    schema = plan_schema_for_budget(engine, max_gameplay_ms, atom_ids)
    if max_steps_per_probe is not None:
        schema['properties']['probes']['items']['properties']['steps']['maxItems'] = max_steps_per_probe
    if criterion_ids:
        schema['properties']['probes']['items']['properties']['criterion_ids']['items'] = {
            'type': 'string', 'enum': list(criterion_ids)}
    if atom_ids:
        window = copy.deepcopy(schema['properties']['coverage']['items'])
        window['properties'].pop('atom_id')
        window['required'].remove('atom_id')
        schema['properties']['coverage'] = obj({ident: copy.deepcopy(window) for ident in atom_ids})
    return schema


def decode_plan_coverage(result: dict) -> dict:
    """Decode the declared wire representation; never deduplicate or invent rows.

    Raw model response remains in model_calls; semantic validation still runs on
    every decoded window and checks the exact frozen ID set.
    """
    result = copy.deepcopy(result)
    if isinstance(result.get('coverage'), dict):
        result['coverage'] = [dict(window, atom_id=ident) for ident, window in result['coverage'].items()]
    return result


def unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate JSON key: {key}')
        result[key] = value
    return result


def load_plan_json(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_json_object,
                      parse_constant=reject_json_constant)


def reject_json_constant(value):
    raise ValueError(f'non-finite JSON number: {value}')


def judge_schema(specs, evidence_ids=None, citation_rules=None):
    """Bind judge output to the frozen check set, without inventing verdicts.

    Exact cardinality plus the ID enum prevents short/unknown-ID responses.
    validate_judgments still rejects duplicate IDs (JSON Schema cannot express
    uniqueness of an object property across array entries).
    """
    ids = [spec['id'] for spec in specs]
    if any(not isinstance(ident, str) or not ident for ident in ids):
        raise ValueError('judge specs need nonempty string IDs')
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate judge spec IDs')
    schema = copy.deepcopy(JUDGE_SCHEMA)
    checks = schema['properties']['checks']
    checks.update(minItems=len(ids), maxItems=len(ids))
    checks['items']['properties']['id'] = {'type': 'string', 'enum': ids}
    if evidence_ids is not None:
        admissible=sorted(set(evidence_ids))
        if not admissible:raise ValueError('judge needs at least one delivered evidence ID')
        checks['items']['properties']['evidence']['items']['properties']['id']={'type':'string','enum':admissible}
    if citation_rules is not None:
        variants=[]
        for ident, rule in citation_rules.items():
            if evidence_ids is not None and ident not in evidence_ids:
                raise ValueError('citation rule for undelivered evidence ID')
            variant=copy.deepcopy(REF)
            variant['properties']['id']={'type':'string','enum':[ident]}
            for field in ('line_start','line_end'):
                variant['properties'][field]={'type':'integer',**rule}
            variants.append(variant)
        if not variants:
            raise ValueError('judge needs at least one admissible citation')
        # Keep the per-file bounds once rather than repeating them at every
        # frozen criterion key. The local checker resolves this same definition.
        schema['$defs']={'Citation':{'anyOf':variants}}
        checks['items']['properties']['evidence']['items']={'$ref':'#/$defs/Citation'}
    return schema


def keyed_judge_schema(specs, evidence_ids=None, citation_rules=None):
    """Require a verdict at every frozen key, so duplicate IDs cannot hide omissions.

    The model still supplies every judgment and citation. The keys identify checks;
    no evaluator creates a missing verdict or interprets an unknown check name.
    """
    schema = judge_schema(specs, evidence_ids=evidence_ids, citation_rules=citation_rules)
    template = copy.deepcopy(schema['properties']['checks']['items'])
    del template['properties']['id']
    template['required'].remove('id')
    schema['properties']['checks'] = obj({spec['id']: copy.deepcopy(template) for spec in specs})
    from .endpoint_sparse import execution_schema, VERSIONS as TIER_VERSIONS
    for spec in specs:
        if spec.get('execution_tiers') in TIER_VERSIONS:
            check = schema['properties']['checks']['properties'][spec['id']]
            check['properties']['execution'] = execution_schema()
            check['required'].append('execution')
            if spec.get('execution_tiers') != 'whitebox-mechanic10-50-100.v1':
                from .endpoint_sparse import endpoint_verification_schema
                check['properties']['endpoint_verification'] = endpoint_verification_schema()
                check['required'].append('endpoint_verification')
    return schema


def decode_keyed_judgment(raw, specs, evidence_ids=None, citation_rules=None):
    """Losslessly decode the closed model output into the existing audit format."""
    validate_schema(raw, keyed_judge_schema(specs, evidence_ids=evidence_ids, citation_rules=citation_rules))
    return {**raw, 'checks': [{'id': spec['id'], **copy.deepcopy(raw['checks'][spec['id']])}
                              for spec in specs]}


# Fixed across planning and judging; keep the actual submitted prompt auditable.
READ_ONLY_EVAL_INSTRUCTIONS = """Evaluation invocation constraints:
Use only read-only shell exec to inspect the supplied delivery and evidence files.
Do not invoke MCP tools, connectors, plugins, skills, subagents, or other tools.
Do not discover or read framework/plugin instructions or unrelated repositories.
Use bounded reads and searches within the supplied task paths; avoid repeated reads
and broad recursive listings. Do not write files or run games, builds, or installers.
Return only the JSON required by the supplied schema. Never invent observations,
evidence references, missing verdicts, or successful runtime behavior.

"""


RETRY_BUDGET_FRACTION = 0.5


def evaluation_executable(requested):
    """Use an explicitly qualified CLI runtime without changing the model."""
    if requested != 'codex' or not os.environ.get('A3GAME_CODEX_EXECUTABLE'):
        return requested, None
    path = Path(os.environ['A3GAME_CODEX_EXECUTABLE']).expanduser().resolve()
    expected = os.environ.get('A3GAME_CODEX_EXECUTABLE_SHA256', '')
    if not expected or not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError('Explicit evaluation CLI requires an executable and pinned SHA256')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError('Explicit evaluation CLI SHA256 changed')
    return str(path), {'path': str(path), 'sha256': digest,
                       'selection': 'explicit qualified CLI; requested model unchanged'}


def tool_transport_failure(folder):
    """Keep a CLI host outage separate from an accepted product judgment."""
    diagnostics = []
    patterns = ('timed out negotiating with the code-mode host',
                'code-mode host is disabled',
                'gRPC code-mode host timed out waiting for session opening response')
    for number, line in enumerate((folder / 'stderr.log').read_text().splitlines(), 1):
        if any(pattern in line for pattern in patterns):
            diagnostics.append({'path': 'stderr.log', 'line': number, 'text': line})
    if not diagnostics:
        return None
    return {'classification': 'HARNESS_ERROR', 'failure_layer': 'cli_tool_transport',
            'diagnostics': diagnostics, 'stderr_sha256': hashlib.sha256(
                (folder / 'stderr.log').read_bytes()).hexdigest(),
            'response_retained': (folder / 'response.json').is_file(),
            'policy': 'No automatic retry, model substitution, or product verdict; preserve raw output'}


def call_codex(root: Path, *, name: str, prompt: str, schema: dict,
               model: str, images=(), timeout: int = 480, executable: str = 'codex', max_attempts: int = 2, response_validator=None, explicit_stdin_separator: bool = False):
    from .runtime_budgets import model_call_budget
    protocol_path = root / 'input/pilot_rubric.json'
    runtime_budget = json.loads(protocol_path.read_text()).get('runtime_budget', {}) if protocol_path.is_file() else {}
    budget_record = model_call_budget(name, timeout, runtime_budget)
    timeout = budget_record['effective_timeout_seconds']
    base_prompt = READ_ONLY_EVAL_INSTRUCTIONS + prompt
    retry_suffix = (
        '\nYour previous response was not valid JSON. Return exactly one JSON object that '
        'matches the supplied output schema; do not include markdown fences, prose, or comments.'
    )
    retry_reason = None
    first_folder = None
    patch_base = None
    patch_feedback = None
    images = tuple(images)
    deadline = time.monotonic() + timeout
    if max_attempts not in (1,2):
        raise ValueError('max_attempts must be 1 or 2')
    for attempt in range(max_attempts):
        folder = root / 'model_calls' / name
        if folder.exists():
            n = 2
            while (root / "model_calls" / f"{name}_{n:03d}").exists():
                n += 1
            folder = root / "model_calls" / f"{name}_{n:03d}"
        folder.mkdir(parents=True, exist_ok=False)
        if first_folder is None:
            first_folder = folder
        if attempt:
            # Format retries share the original bounded outer deadline.
            dump(first_folder / 'retry_provenance.json', {
                'reason': retry_reason, 'attempts': 2,
                'first_attempt': str(first_folder), 'retry_attempt': str(folder),
                'first_response_sha256': hashlib.sha256((first_folder/'response.json').read_bytes()).hexdigest(),
                'retry_prompt_suffix_sha256': hashlib.sha256(retry_suffix.encode()).hexdigest(),
                'timeout_policy': 'one original deadline shared across format retries',
                'policy': 'retry once only; preserve both raw responses; malformed or schema-invalid output cannot become a verdict',
            })
        dump(folder / 'budget.json', dict(budget_record, attempt=attempt + 1,
            allocated_seconds=max(0, deadline - time.monotonic()),
            retry_budget_fraction=RETRY_BUDGET_FRACTION))
        from . import plan_patches
        active_schema = plan_patches.PATCH_SCHEMA if patch_base is not None else schema
        if name == 'plan' and patch_base is None:
            from .route_first_capture import submitted_plan_schema
            active_schema = submitted_plan_schema(root, schema)
            if active_schema != schema:
                dump(folder/'original_schema.json', schema)
                dump(folder/'schema_transform.json', {
                    'version':'whitebox-plan-shared-schema.v1',
                    'original_sha256':plan_patches.digest((folder/'original_schema.json').read_bytes()),
                    'template_sha256':plan_patches.digest((root/'planning_prompt_template.py').read_bytes()),
                    'semantics':'identical repeated schema nodes replaced with shared $defs references'})
        from . import source_reference_transport
        if source_reference_transport.applies(name, active_schema):
            active_schema = source_reference_transport.write(folder, active_schema)
        elif name.startswith('evidence_') or name == 'static' or re.fullmatch(r'static_\d{2,}', name):
            from .judge_schema_transport import write as write_judge_schema
            active_schema = write_judge_schema(folder, active_schema)
        else:
            dump(folder / 'schema.json', active_schema)
        if patch_feedback is not None:
            dump(folder/'repair_feedback.json', patch_feedback)
        submitted_prompt = (READ_ONLY_EVAL_INSTRUCTIONS + retry_suffix if patch_base is not None
                            else base_prompt if attempt == 0 else base_prompt + retry_suffix)
        if (folder/'schema_transform.json').is_file() and (
                'citation_line_transport' in json.loads((folder/'schema_transform.json').read_text())):
            from .judge_line_ordinals import prepare_prompt
            submitted_prompt = prepare_prompt(folder, submitted_prompt)
        if (folder/source_reference_transport.TRANSFORM).is_file():
            submitted_prompt = source_reference_transport.prepare_prompt(folder, submitted_prompt)
        # Some qualified CLI hosts do not expose --output-schema to the model.
        # Expose the exact submitted file as well; validation remains unchanged.
        if name in {'static_existence', 'static_existence_format_v1'}:
            submitted_prompt += ('\nEXACT OUTPUT CONTRACT: Before composing your final JSON, read '
                + str((folder/'schema.json').resolve())
                + '. This is the authoritative JSON Schema for this response. '
                'Use its property names and required keys literally, including nested keys; '
                'do not invent an alternate report structure. Return only a conforming JSON object.\n')
        (folder / 'prompt.txt').write_text(submitted_prompt)
        if name == 'static' or name.startswith('evidence_') or re.fullmatch(r'static_\d{2,}', name):
            from . import frame_budget
            frozen = json.loads(protocol_path.read_text()) if protocol_path.is_file() else {}
            if frame_budget.enabled(frozen):
                delivery = frame_budget.validate_request(root, name, frozen,
                    json.loads((root/'evidence_manifest.json').read_text()), images, submitted_prompt)
                dump(folder/'actual_delivery.json',delivery)
        output = folder / 'response.json'
        reasoning_effort = os.environ.get('A3GAME_SOL_REASONING_EFFORT', 'medium').strip() or 'medium'
        selected_executable, runtime_binding = evaluation_executable(executable)
        if runtime_binding is not None:
            dump(folder / 'cli_runtime.json', runtime_binding)
        cmd = [selected_executable, '--ask-for-approval', 'never', 'exec', '--model', model,
               '-c', 'model_reasoning_effort=' + json.dumps(reasoning_effort),
               '--sandbox', 'read-only', '--ephemeral', '--ignore-rules',
               '-C', str(root / 'input'), '--json', '--color', 'never',
               '--output-schema', str(folder / 'schema.json'), '-o', str(output), '-']
        # image options must precede stdin's positional '-' for some CLI versions.
        cmd = cmd[:-1]
        for image in images:
            cmd.extend(['--image', str(image)])
        if explicit_stdin_separator:
            cmd.append('--')
        cmd.append('-')
        started = time.monotonic()
        env = dict(os.environ)
        # Do not pass unrelated cloud-provider secrets into the judge process.
        for key in list(env):
            if any(word in key.upper() for word in ('DASHSCOPE', 'AWS_SECRET', 'ANTHROPIC_API', 'GEMINI_API')):
                env.pop(key, None)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            dump(folder / 'invocation.json', {'model_requested': model, 'status': 'TIMEOUT',
                'attempt': attempt + 1, 'reason': 'shared response deadline exhausted before launch'})
            raise RuntimeError(f'Codex timeout; see {folder}')
        with (folder / 'events.jsonl').open('w') as stdout, (folder / 'stderr.log').open('w') as stderr:
            proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                    text=True, env=env, start_new_session=True)
            try:
                proc.communicate(submitted_prompt, timeout=remaining)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
                dump(folder / 'invocation.json', {'model_requested': model, 'status': 'TIMEOUT', 'seconds': time.monotonic()-started})
                raise RuntimeError(f'Codex timeout; see {folder}')
        meta = {'model_requested': model, 'command': cmd, 'exit_code': proc.returncode,
                'seconds': round(time.monotonic()-started, 2), 'response_present': output.is_file(),
                'attempt': attempt + 1}
        if attempt:
            meta['retry_of'] = str(first_folder)
        if runtime_binding is not None:
            meta['cli_runtime'] = runtime_binding
        failure = tool_transport_failure(folder)
        if failure is not None:
            meta.update(status='HARNESS_ERROR', failure_layer='cli_tool_transport')
            dump(folder / 'tool_transport_error.json', failure)
        dump(folder / 'invocation.json', meta)
        if failure is not None:
            raise RuntimeError(f'Codex CLI tool transport unavailable; see {folder}/tool_transport_error.json')
        if proc.returncode != 0 or not output.is_file():
            raise RuntimeError(f'Codex failed (no model substitution); see {folder}/stderr.log')
        raw_response = output.read_bytes()
        try:
            result = json.loads(raw_response, **({'object_pairs_hook': unique_json_object,
                                                 'parse_constant': reject_json_constant}))
        except ValueError as exc:
            dump(folder / 'parse_error.json', {
                'phase': 'response_json_parse', 'response_path': str(output),
                'response_sha256': hashlib.sha256(raw_response).hexdigest(),
                'response_text': raw_response.decode('utf-8', errors='replace'),
                'exception': {'type': type(exc).__name__, 'message': str(exc),
                              'line': getattr(exc, 'lineno', None), 'column': getattr(exc, 'colno', None),
                              'position': getattr(exc, 'pos', None)},
                'retry_policy': 'one bounded format retry; malformed response never becomes a verdict',
                'attempt': attempt + 1,
            })
            if attempt + 1 < max_attempts:
                retry_reason = 'response_json_parse'
                retry_suffix = (
                    '\nYour previous response was not valid JSON: ' + str(exc)
                    + '\nThe original response is preserved at ' + str(output)
                    + '. Read it once to correct format without repeating source analysis. '
                    'Return exactly one complete JSON object matching the supplied schema, '
                    'including all closing array/object delimiters. Keep reasons and observations concise. '
                    'Do not invent missing verdicts or observations; no markdown or commentary.'
                )
                continue
            raise ValueError(f'model response is invalid JSON after one bounded retry; raw response preserved in {folder}/parse_error.json') from exc
        # Validate the closed schema without optional third-party dependencies.
        try:
            validate_schema(result, active_schema)
            if (folder/source_reference_transport.TRANSFORM).is_file():
                result = source_reference_transport.save_decoded(folder, result)
            if (folder/'citation_line_codebook.json').is_file():
                from .judge_line_ordinals import save_decoded
                result = save_decoded(folder, result)
            if patch_base is None and active_schema != schema:
                validate_schema(result, schema)
            if patch_base is not None:
                patch_result = result
                result = plan_patches.apply(patch_base.read_bytes(), patch_result)
                validate_schema(result, schema)
        except ValueError as exc:
            dump(folder/'schema_error.json', {'phase': 'response_schema_validation',
                'response_sha256': hashlib.sha256(raw_response).hexdigest(), 'exception': str(exc),
                'retry_policy': 'one bounded format retry; schema is never relaxed',
                'attempt': attempt + 1})
            if attempt + 1 < max_attempts and (name == 'plan' or name.startswith('judge_')):
                retry_reason = 'response_schema_validation'
                if name == 'plan':
                    patch_base = output
                    patch_feedback, retry_suffix = plan_patches.feedback(output, exc)
                    continue
                retry_suffix = (
                    '\nYour previous JSON failed the closed output schema: ' + str(exc)
                    + '\nYour previous response is included verbatim below. Copy every valid field from it unchanged; '
                    'only add the missing keys and drop the unexpected keys named above. Do not redo source analysis or the plan.'
                    '\nPREVIOUS_RESPONSE_BEGIN\n' + raw_response.decode('utf-8', errors='replace') + '\nPREVIOUS_RESPONSE_END'
                    '\nReturn a complete replacement JSON object, not a patch. Include every required '
                    'field, with no unexpected fields. Use the schema property names literally. Do not invent game observations or claim PASS. '
                    'Avoid repeating broad source analysis; use targeted reads only if needed. '
                    'Read the exact schema in the original prompt or the saved schema.json. '
                    'The previous raw response is preserved at ' + str(output) + '. '
                    'Use it for targeted format correction without repeating broad source analysis.'
                )
                continue
            raise
        if response_validator is not None:
            try:
                response_validator(result)
            except ValueError as exc:
                dump(folder/'validation_error.json', {'phase': 'response_plan_validation',
                    'response_sha256': hashlib.sha256(raw_response).hexdigest(), 'exception': str(exc),
                    'attempt': attempt + 1, 'retry_policy': 'one total correction shared with JSON/schema; original deadline'})
                if attempt + 1 < max_attempts:
                    retry_reason = 'response_plan_validation'
                    if name == 'plan':
                        patch_base = output
                        patch_feedback, retry_suffix = plan_patches.feedback(output, exc)
                        continue
                    retry_suffix = (
                        '\nThe generic validator rejected your plan: ' + str(exc)
                        + '\nThe original JSON is preserved at ' + str(output)
                        + '. Correct the diagnosed fields using targeted reads of this delivery only. '
                        'All source paths are relative to the project root, which is input/project; '
                        'do not include a project/ prefix. Return the entire schema-valid plan. '
                        'Do not weaken preconditions, fabricate binding evidence, or replace normal inputs '
                        'with game function calls. There is no further correction or deadline extension.'
                    )
                    continue
                raise
        selected = output
        extra = {}
        if (folder/source_reference_transport.DECODE).is_file():
            selected = folder/'source_reference_decoded_response.json'
            extra['source_reference_receipt_sha256'] = hashlib.sha256((folder/source_reference_transport.DECODE).read_bytes()).hexdigest()
        if (folder/'citation_line_decode.json').is_file():
            selected = folder/'decoded_response.json'
            extra['judge_line_receipt_sha256'] = hashlib.sha256((folder/'citation_line_decode.json').read_bytes()).hexdigest()
        if patch_base is not None:
            # Preserve the exact field-edit result, before any in-memory validation normalization.
            derived = plan_patches.apply(patch_base.read_bytes(), patch_result)
            selected = plan_patches.save_application(folder, patch_base, patch_result, derived)
            extra['patch_receipt_sha256'] = plan_patches.digest((folder/'patch_application.json').read_bytes())
        dump(first_folder/'accepted_response.json', {'path': os.path.relpath(selected, first_folder),
            'sha256': hashlib.sha256(selected.read_bytes()).hexdigest(), 'attempt': attempt + 1, **extra})
        return result
    raise AssertionError('unreachable')


def saved_model_response(root: Path, name: str):
    """Resolve a validated format retry without replacing the original reply."""
    folder = root/'model_calls'/name
    pointer = folder/'accepted_response.json'
    if not pointer.exists():
        return folder/'response.json'
    binding = json.loads(pointer.read_text())
    path = (folder/binding['path']).resolve()
    if not path.is_relative_to(folder.parent.resolve()) or not path.is_file():
        raise ValueError('accepted model response escapes model_calls or is missing')
    if hashlib.sha256(path.read_bytes()).hexdigest() != binding['sha256']:
        raise ValueError('accepted model response SHA256 mismatch')
    if 'source_reference_receipt_sha256' in binding:
        from .source_reference_transport import verify_decoded
        verify_decoded(path, binding)
    elif path.name == 'source_reference_decoded_response.json' or (path.parent/'source_reference_decode.json').is_file():
        raise ValueError('accepted source response is missing its exact decode binding')
    if 'judge_line_receipt_sha256' in binding:
        from .judge_line_ordinals import verify_decoded
        verify_decoded(path, binding)
    elif path.name == 'decoded_response.json' or (path.parent/'citation_line_decode.json').is_file():
        raise ValueError('accepted judge response is missing its citation decode binding')
    if 'patch_receipt_sha256' in binding:
        from .plan_patches import verify_application
        verify_application(path, binding)
    return path


def validate_schema(value, schema, path="$", _root=None):
    """Validate the exact closed JSON-schema subset emitted here."""
    _root=schema if _root is None else _root
    if '$ref' in schema:
        target=schema['$ref']
        if not target.startswith('#/$defs/'):
            raise ValueError(f'{path}: unsupported schema reference')
        return validate_schema(value,_root['$defs'][target[len('#/$defs/'):]],path,_root)
    if 'anyOf' in schema:
        for variant in schema['anyOf']:
            try:
                validate_schema(value,variant,path,_root)
                return
            except ValueError:
                pass
        raise ValueError(f'{path}: value does not match any allowed schema variant')
    typ = schema['type']
    if isinstance(typ, list):
        for variant in typ:
            try:
                validate_schema(value, dict(schema, type=variant), path, _root)
                return
            except ValueError:
                pass
        raise ValueError(f'{path}: value does not match allowed types {typ}')
    good = {'null': lambda: value is None, 'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
            'string': lambda: isinstance(value, str), 'boolean': lambda: isinstance(value, bool),
            'integer': lambda: isinstance(value, int) and not isinstance(value, bool),
            'number': lambda: isinstance(value, (int,float)) and not isinstance(value, bool)}
    if typ not in good:
        raise ValueError(f'{path}: unsupported schema type {typ}')
    if not good[typ]():
        raise ValueError(f'{path}: expected {typ}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: invalid enum value')
    if typ in {'integer','number'}:
        if 'minimum' in schema and value<schema['minimum']:raise ValueError(f'{path}: below minimum')
        if 'maximum' in schema and value>schema['maximum']:raise ValueError(f'{path}: above maximum')
    if typ == 'object':
        if set(value) != set(schema['properties']):
            missing = sorted(set(schema['properties']) - set(value))
            extra = sorted(set(value) - set(schema['properties']))
            raise ValueError(f'{path}: missing or unexpected keys; missing={missing}, unexpected={extra}')
        for key, child in schema['properties'].items():
            validate_schema(value[key], child, path+'.'+key,_root)
    if typ == 'array':
        if 'minItems' in schema and len(value) < schema['minItems']:
            raise ValueError(f'{path}: fewer than minItems {schema["minItems"]}')
        if 'maxItems' in schema and len(value) > schema['maxItems']:
            raise ValueError(f'{path}: more than maxItems {schema["maxItems"]}')
        for i, child in enumerate(value):
            validate_schema(child, schema['items'], f'{path}[{i}]',_root)
