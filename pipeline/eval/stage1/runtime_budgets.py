"""Protocol-level wall-clock budgets for expanded whitebox runs."""
from __future__ import annotations

import copy
import re

VERSION = 'whitebox-runtime-budgets.v1'


# Tiers retain the harness's existing 75 s S smoke envelope as the gameplay
# default. Larger tiers add time for longer authored flows, not idle waiting.
_TIERS = {
    'S': {'engine_startup_ms': 90000, 'menu_prepare_ms': 15000,
          'gameplay_ms': 75000, 'capture_tail_ms': 10000,
          'single_step_ms': 30000, 'engine_call_ms': 210000},
    'M': {'engine_startup_ms': 180000, 'menu_prepare_ms': 30000,
          'gameplay_ms': 180000, 'capture_tail_ms': 15000,
          'single_step_ms': 60000, 'engine_call_ms': 450000},
    'L': {'engine_startup_ms': 300000, 'menu_prepare_ms': 45000,
          'gameplay_ms': 300000, 'capture_tail_ms': 20000,
          'single_step_ms': 60000, 'engine_call_ms': 720000},
}


def budget_for(case_id: str, tier: str = 'S') -> dict:
    # Normalize compound tier names like 'L-Regular' or 'S-Lite' to their base letter.
    canonical = tier.split('-')[0].upper() if tier else 'S'
    if canonical not in _TIERS:
        raise ValueError(f'unknown complexity tier: {tier}')
    row = copy.deepcopy(_TIERS[canonical])
    rationale = f'{canonical} tier default; gameplay uses the existing bounded S smoke window and scales for longer tiers.'
    if case_id == 'G057_rhythm_machine_hall':
        # Frozen flow: warmup 0-15 s, middle 15-70 s, finale from 70 s to
        # chart end, followed by a result/settlement observation.
        row.update(gameplay_ms=125000, engine_startup_ms=90000,
                   menu_prepare_ms=15000, capture_tail_ms=12000,
                   engine_call_ms=270000, single_step_ms=60000)
        rationale = ('Versioned recovery budget: 125 s gameplay to cover the approximately 100 s chart, finale, and settlement window. Not adjusted from model results.')
    row['total_wall_clock_ms'] = (row['engine_startup_ms'] + row['menu_prepare_ms']
                                  + row['gameplay_ms'] + row['capture_tail_ms'])
    if row['total_wall_clock_ms'] > row['engine_call_ms']:
        raise ValueError('engine call cap does not cover component budgets')
    row.update(tier=canonical, version=VERSION, rationale=rationale)
    return row



# New attempts pin their own budget; historical batch pointers stay immutable.
RECOVERY_VERSION = 'whitebox-runtime-budgets.v2.godot-threejs.s300-m600'
MODEL_BUDGET_VERSION = 'whitebox-model-budgets.v2.plus900'
RECOVERY_ENGINES = frozenset({'godot', 'three_js'})
UNITY_LEGACY_VERSION = 'whitebox-runtime-budgets.v1.unity.plan1800-exec1800'
UNITY_LEGACY_MODEL_BUDGET_VERSION = 'whitebox-model-budgets.v1.unity.plan1800'
UNITY_VERSION = 'whitebox-runtime-budgets.v2.unity.plan2700-exec1800'
UNITY_MODEL_BUDGET_VERSION = 'whitebox-model-budgets.v2.unity.plan2700'
UNITY_CORE12_VERSION = 'whitebox-runtime-budgets.v3.unity.core12-plan900-exec1800'
UNITY_CORE12_MODEL_BUDGET_VERSION = 'whitebox-model-budgets.v3.unity.core12-plan900'
UNITY_VERSIONS = frozenset({UNITY_VERSION, UNITY_LEGACY_VERSION, UNITY_CORE12_VERSION})
UNITY_CORE12_PLAN_SECONDS = 900
UNITY_PLAN_SECONDS = 2700
UNITY_EXECUTION_SECONDS = 1800
MODEL_EXTENSION_SECONDS = 900
TIERED_VERSION = 'whitebox-runtime-budgets.v4.tiered-core'
TIERED_MODEL_VERSION = 'whitebox-model-budgets.v4.tiered-core'


PLAN_OVERRIDE_VERSION = 'whitebox-explicit-plan-timeout.v1'


def validate_plan_override(override):
    if (not isinstance(override, dict)
            or set(override) != {'version', 'seconds', 'authorization'}
            or override.get('version') != PLAN_OVERRIDE_VERSION
            or type(override.get('seconds')) is not int
            or override['seconds'] != 1800
            or not isinstance(override.get('authorization'), str)
            or not override['authorization'].strip()):
        raise ValueError('explicit plan timeout requires authorized 1800-second policy')
    return override['seconds']


def tiered_budget(source, engine, tier, *, plan_override=None):
    from .tiered_core import PLAN_SECONDS
    if tier not in PLAN_SECONDS or engine not in {'godot', 'three_js', 'unity3d', 'ue5'}:
        raise ValueError('invalid tiered planner engine/tier')
    result = copy.deepcopy(source)
    result.update(version=TIERED_VERSION, engine=engine, tier=tier,
                  model_budget_policy=TIERED_MODEL_VERSION, plan_timeout_seconds=PLAN_SECONDS[tier],
                  previous_budget=copy.deepcopy(source))
    if plan_override is not None:
        if engine != 'unity3d':
            raise ValueError('explicit plan timeout is scoped to Unity')
        result['plan_timeout_seconds'] = validate_plan_override(plan_override)
        result['plan_timeout_override'] = copy.deepcopy(plan_override)
    gameplay = 1800000 if engine == 'unity3d' else {'S': 300000, 'M': 600000}.get(
        tier, source.get('recording_ms', source.get('gameplay_ms')))
    result.update(gameplay_ms=gameplay, recording_ms=gameplay,
                  finalize_ms=source.get('finalize_ms', 30000),
                  rationale='Canonical tier caps Sol planning only. Native route, waits and final observation determine actual recording length.')
    result['total_wall_clock_ms'] = sum(result[key] for key in (
        'import_build_ms', 'launch_wait_ms', 'recording_ms', 'capture_tail_ms', 'finalize_ms'))
    result['engine_call_ms'] = max(source.get('engine_call_ms', 0), result['total_wall_clock_ms'])
    result['total_ms'] = result['engine_call_ms']
    validate_tiered_budget(result)
    return result


def validate_tiered_budget(budget):
    from .tiered_core import PLAN_SECONDS
    expected_plan = PLAN_SECONDS.get(budget.get('tier'))
    if 'plan_timeout_override' in budget:
        if budget.get('engine') != 'unity3d':
            raise ValueError('explicit plan timeout is scoped to Unity')
        expected_plan = validate_plan_override(budget['plan_timeout_override'])
    if (budget.get('version') != TIERED_VERSION or budget.get('tier') not in PLAN_SECONDS
            or budget.get('engine') not in {'godot', 'three_js', 'unity3d', 'ue5'}
            or budget.get('plan_timeout_seconds') != expected_plan
            or budget.get('model_budget_policy') != TIERED_MODEL_VERSION):
        raise ValueError('tiered planner budget identity/tier mismatch')
    components = ('import_build_ms', 'launch_wait_ms', 'recording_ms', 'capture_tail_ms', 'finalize_ms')
    if (any(type(budget.get(key)) is not int or budget[key] < 0 for key in components)
            or budget.get('gameplay_ms', 0) <= 0 or budget['gameplay_ms'] != budget['recording_ms']
            or budget.get('total_wall_clock_ms') != sum(budget[key] for key in components)
            or budget.get('engine_call_ms', 0) < budget['total_wall_clock_ms']
            or budget.get('total_ms') != budget['engine_call_ms']):
        raise ValueError('tiered execution deadline does not cover native route budget')
    if budget['engine'] == 'unity3d' and budget['recording_ms'] != 1800000:
        raise ValueError('tiered Unity recording ceiling must preserve the separate 1800s policy')


def new_attempt_budget(source: dict, *, engine: str, tier: str, core12_plan_seconds=None) -> dict:
    """Apply the user-selected tier policy after reading the legacy protocol.

    New Godot/Three.js attempts use tier policy; Unity opts into the separate
    plan 2700 s/execution 1800 s policy. Historical attempts keep frozen budgets.
    """
    canonical = tier.split('-')[0].upper() if tier else 'S'
    if core12_plan_seconds is not None and (
            engine != 'unity3d' or type(core12_plan_seconds) is not int
            or core12_plan_seconds != UNITY_CORE12_PLAN_SECONDS):
        raise ValueError('core12 Unity planner policy requires exactly 900 seconds')
    if engine == 'unity3d':
        if source.get('version') in UNITY_VERSIONS:
            if source.get('engine') != engine or source.get('tier') != canonical:
                raise ValueError('pinned Unity budget engine/tier mismatch')
            validate_pinned_budget(source)
            if core12_plan_seconds is not None and source['version'] != UNITY_CORE12_VERSION:
                raise ValueError('cannot change a frozen Unity planner policy')
            return copy.deepcopy(source)
        result = copy.deepcopy(source)
        original = copy.deepcopy(source)
        execution_ms = UNITY_EXECUTION_SECONDS * 1000
        result.update(version=UNITY_VERSION, engine=engine, tier=canonical,
                      gameplay_ms=execution_ms, recording_ms=execution_ms,
                      import_build_ms=source.get('import_build_ms', source.get('engine_startup_ms', 90000)),
                      launch_wait_ms=source.get('launch_wait_ms', source.get('menu_prepare_ms', 15000)),
                      capture_tail_ms=source.get('capture_tail_ms', 10000),
                      finalize_ms=source.get('finalize_ms', 30000),
                      model_budget_policy=UNITY_MODEL_BUDGET_VERSION,
                      previous_budget=original,
                      rationale='User policy 2026-10-26: Unity plan ceiling 2700 s; real execution ceiling remains 1800 s.')
        if core12_plan_seconds is not None:
            result.update(version=UNITY_CORE12_VERSION,
                          model_budget_policy=UNITY_CORE12_MODEL_BUDGET_VERSION,
                          rationale='User core12 single-case trial 2026-10-26: Unity plan ceiling 900 s; execution ceiling remains 1800 s.')
        result['total_wall_clock_ms'] = sum(result[key] for key in (
            'import_build_ms', 'launch_wait_ms', 'recording_ms', 'capture_tail_ms', 'finalize_ms'))
        result['engine_call_ms'] = max(source.get('engine_call_ms', 0), result['total_wall_clock_ms'])
        result['total_ms'] = result['engine_call_ms']
        validate_pinned_budget(result)
        return result
    if engine not in RECOVERY_ENGINES:
        return copy.deepcopy(source)

    if canonical not in _TIERS:
        raise ValueError(f'unknown complexity tier: {tier}')
    if source.get('version') == RECOVERY_VERSION:
        if source.get('engine') != engine or source.get('tier') != canonical:
            raise ValueError('pinned recovery budget engine/tier mismatch')
        validate_pinned_budget(source)
        return copy.deepcopy(source)
    result = copy.deepcopy(source)
    original = copy.deepcopy(source)
    gameplay = {'S': 300000, 'M': 600000}.get(
        canonical, source.get('recording_ms', source.get('gameplay_ms')))
    if type(gameplay) is not int or gameplay <= 0:
        raise ValueError('new attempt requires a positive gameplay budget')
    result.update(version=RECOVERY_VERSION, engine=engine, tier=canonical,
                  gameplay_ms=gameplay, recording_ms=gameplay,
                  import_build_ms=source.get('import_build_ms', source.get('engine_startup_ms', 90000)),
                  launch_wait_ms=source.get('launch_wait_ms', source.get('menu_prepare_ms', 15000)),
                  capture_tail_ms=source.get('capture_tail_ms', 10000),
                  finalize_ms=source.get('finalize_ms', 30000),
                  model_budget_policy=MODEL_BUDGET_VERSION,
                  previous_budget=original,
                  rationale='User policy 2026-10-24: S 5 min, M 10 min; L unchanged. '
                            'Import, startup, capture tail and finalization are separate from gameplay.')
    for key in ('import_build_ms', 'launch_wait_ms', 'capture_tail_ms', 'finalize_ms'):
        if type(result[key]) is not int or result[key] < 0:
            raise ValueError(f'invalid new-attempt budget: {key}')
    result['total_wall_clock_ms'] = sum(result[key] for key in (
        'import_build_ms', 'launch_wait_ms', 'recording_ms', 'capture_tail_ms', 'finalize_ms'))
    engine_call = source.get('engine_call_ms', 0)
    if type(engine_call) is not int or engine_call < 0:
        raise ValueError('invalid new-attempt budget: engine_call_ms')
    result['engine_call_ms'] = max(engine_call, result['total_wall_clock_ms'])
    result['total_ms'] = result['engine_call_ms']
    validate_pinned_budget(result)
    return result


def validate_pinned_budget(budget: dict) -> None:
    """Reject contradictory or corrupt new-attempt budgets before planning/capture."""
    if budget.get('version') == TIERED_VERSION:
        return validate_tiered_budget(budget)
    if budget.get('engine') not in (RECOVERY_ENGINES | {'unity3d'}) or budget.get('tier') not in _TIERS:
        raise ValueError('invalid pinned recovery engine/tier')
    components = ('import_build_ms', 'launch_wait_ms', 'recording_ms',
                  'capture_tail_ms', 'finalize_ms')
    for key in components + ('gameplay_ms', 'engine_call_ms', 'total_ms', 'total_wall_clock_ms'):
        if type(budget.get(key)) is not int or budget[key] < 0:
            raise ValueError(f'invalid pinned recovery budget: {key}')
    if budget['gameplay_ms'] <= 0 or budget['gameplay_ms'] != budget['recording_ms']:
        raise ValueError('pinned gameplay and recording budgets must agree')
    if budget.get('version') in UNITY_VERSIONS:
        if budget['engine'] != 'unity3d' or budget['gameplay_ms'] != UNITY_EXECUTION_SECONDS * 1000:
            raise ValueError('pinned Unity execution budget differs from policy')
        expected_model_policy = {UNITY_VERSION: UNITY_MODEL_BUDGET_VERSION,
                                 UNITY_LEGACY_VERSION: UNITY_LEGACY_MODEL_BUDGET_VERSION,
                                 UNITY_CORE12_VERSION: UNITY_CORE12_MODEL_BUDGET_VERSION}[budget['version']]
        if budget.get('model_budget_policy') != expected_model_policy:
            raise ValueError('pinned Unity model budget policy mismatch')
    else:
        selected = {'S': 300000, 'M': 600000}.get(budget['tier'])
        if selected is not None and budget['gameplay_ms'] != selected:
            raise ValueError('pinned gameplay budget differs from selected tier policy')
    if (budget['total_wall_clock_ms'] != sum(budget[key] for key in components)
            or budget['engine_call_ms'] < budget['total_wall_clock_ms']
            or budget['total_ms'] != budget['engine_call_ms']):
        raise ValueError('pinned outer deadline does not cover component budgets')
    if budget.get('version') not in UNITY_VERSIONS and budget.get('model_budget_policy') != MODEL_BUDGET_VERSION:
        raise ValueError('pinned model budget policy mismatch')


def budget_for_attempt(batch, entry: dict) -> dict:
    """Select and hash-check the old protocol, then pin the policy for a new attempt."""
    import json
    from pathlib import Path
    from .protocol import sha
    batch = Path(batch)
    budget = budget_for(entry['case_id'], entry.get('tier', 'S'))
    pointer = batch / 'recording_protocols/active.json'
    if pointer.is_file():
        selected = json.loads(pointer.read_text())
        path = batch / 'recording_protocols' / selected['protocol']
        if path.resolve().parent != (batch / 'recording_protocols').resolve():
            raise ValueError('active recording protocol must be a direct batch child')
        digest = sha(path)
        if selected.get('sha256') != digest:
            raise ValueError('active recording protocol hash mismatch')
        recording = json.loads(path.read_text())['cases'].get(entry['case_id'])
        if recording:
            if recording['engine'] != entry['actual_engine']:
                raise ValueError('recording protocol engine differs from selected delivery')
            budget.update(recording['budget'])
            budget.update(engine=recording['engine'], rationale=recording['rationale'],
                          recording_protocol=str(path), recording_protocol_sha256=digest)
            budget['gameplay_ms'] = budget.get('recording_ms', budget['gameplay_ms'])
    elif entry['case_id'] == 'G057_rhythm_machine_hall':
        budget.update(engine='three_js', import_build_ms=180000,
                      launch_wait_ms=45000, gameplay_ms=125000, recording_ms=125000,
                      total_ms=365000,
                      rationale='125 s chart/finale observation plus Vite build/startup and capture tail.')
    budget.setdefault('engine', entry['actual_engine'])
    budget.setdefault('import_build_ms', budget['engine_startup_ms'])
    budget.setdefault('launch_wait_ms', budget['menu_prepare_ms'])
    budget.setdefault('recording_ms', budget['gameplay_ms'])
    budget['total_wall_clock_ms'] = sum(budget[key] for key in
        ('import_build_ms', 'launch_wait_ms', 'recording_ms', 'capture_tail_ms'))
    budget['total_ms'] = max(budget.get('engine_call_ms', 0), budget['total_wall_clock_ms'])
    if entry.get('planning_policy') == 'tiered-core-v1':
        from .tiered_core import canonical_tier
        tier = canonical_tier(Path(entry['requirement']).read_text())
        return tiered_budget(budget, entry['actual_engine'], tier,
                             plan_override=entry.get('plan_timeout_override'))
    return new_attempt_budget(budget, engine=entry['actual_engine'], tier=entry.get('tier', 'S'),
                              core12_plan_seconds=entry.get('core12_plan_timeout_seconds'))


def model_call_budget(name: str, timeout: int, runtime_budget: dict) -> dict:
    """Extend plan/judge calls once, only in explicitly versioned new attempts."""
    judge_call = (name.startswith(('judge_', 'evidence_')) or name in {'static', 'expanded_judge'}
                  or re.fullmatch(r'static_\d{2,}', name))
    phase = 'plan' if name == 'plan' else 'judge' if judge_call else name
    if runtime_budget.get('version') == TIERED_VERSION:
        validate_tiered_budget(runtime_budget)
        return {'version': TIERED_MODEL_VERSION, 'phase': phase, 'base_timeout_seconds': timeout,
                'extension_seconds': 0, 'effective_timeout_seconds': runtime_budget['plan_timeout_seconds'] if phase == 'plan' else timeout}
    if runtime_budget.get('version') == UNITY_CORE12_VERSION:
        validate_pinned_budget(runtime_budget)
        if phase == 'plan':
            return {'version': UNITY_CORE12_MODEL_BUDGET_VERSION, 'phase': phase,
                    'base_timeout_seconds': timeout, 'extension_seconds': 0,
                    'effective_timeout_seconds': UNITY_CORE12_PLAN_SECONDS}
    if runtime_budget.get('version') in {UNITY_VERSION, UNITY_LEGACY_VERSION} and phase == 'plan':
        current = runtime_budget['version'] == UNITY_VERSION
        seconds = UNITY_PLAN_SECONDS if current else UNITY_EXECUTION_SECONDS
        return {'version': UNITY_MODEL_BUDGET_VERSION if current else UNITY_LEGACY_MODEL_BUDGET_VERSION,
                'phase': phase, 'base_timeout_seconds': timeout,
                'extension_seconds': max(0, seconds - timeout),
                'effective_timeout_seconds': seconds}
    extension = MODEL_EXTENSION_SECONDS if (
        runtime_budget.get('version') == RECOVERY_VERSION
        and runtime_budget.get('engine') in RECOVERY_ENGINES
        and phase in {'plan', 'judge'}) else 0
    return {'version': MODEL_BUDGET_VERSION if extension else 'whitebox-model-budgets.legacy',
            'phase': phase, 'base_timeout_seconds': timeout,
            'extension_seconds': extension, 'effective_timeout_seconds': timeout + extension}

def resolve_recording_budget(root, source: dict) -> dict:
    """Resolve a versioned, shared observation extension without changing inputs."""
    import json
    from pathlib import Path
    from .protocol import sha
    root = Path(root)
    effective = copy.deepcopy(source)
    if effective.get('version') == TIERED_VERSION:
        validate_tiered_budget(effective)
        return effective
    # A new attempt's immutable pilot protocol wins over later batch pointer changes.
    if effective.get('version') in UNITY_VERSIONS | {RECOVERY_VERSION}:
        return new_attempt_budget(effective, engine=effective['engine'], tier=effective['tier'])
    batch = root.parents[1]
    pointer = batch / 'recording_protocols/active.json'
    if pointer.is_file():
        protocol_name = json.loads(pointer.read_text())['protocol']
        path = batch / 'recording_protocols' / protocol_name
        if path.resolve().parent != (batch / 'recording_protocols').resolve():
            raise ValueError('active recording protocol must be a direct batch child')
    else:
        path = batch / 'recording_protocols/root-relative-recovery.v3.json'
    if path.is_file():
        record = json.loads(path.read_text())
        case = json.loads((root/'input/pilot_rubric.json').read_text())['case_id']
        case_record = record['cases'][case]
        effective.update(case_record['budget'])
        effective['rationale'] = case_record['rationale']
        effective.update(recording_protocol=str(path), recording_protocol_sha256=sha(path))
    effective.setdefault('import_build_ms', effective.get('engine_startup_ms', 90000))
    effective.setdefault('launch_wait_ms', effective.get('menu_prepare_ms', 15000))
    effective.setdefault('recording_ms', effective.get('gameplay_ms', 75000))
    effective.setdefault('capture_tail_ms', 10000)
    effective['gameplay_ms'] = effective['recording_ms']
    effective['total_wall_clock_ms'] = sum(effective[key] for key in
        ('import_build_ms','launch_wait_ms','recording_ms','capture_tail_ms'))
    total = effective['total_wall_clock_ms']
    effective['engine_call_ms'] = max(effective.get('engine_call_ms', 0), total)
    effective['total_ms'] = effective['engine_call_ms']
    for key in ('engine_call_ms','import_build_ms','launch_wait_ms','recording_ms'):
        if not isinstance(effective[key], int) or effective[key] <= 0:
            raise ValueError(f'invalid recording budget: {key}')
    return effective
