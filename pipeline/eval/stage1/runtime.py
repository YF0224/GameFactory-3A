"""Trusted recorder launch, bounded plan validation and evidence catalog creation."""
from __future__ import annotations

import json
import fcntl
import time
import tempfile
import math
import os
import re
import signal
import subprocess
import shutil
import contextlib
from pathlib import Path

from .protocol import dump, load_lines, sha
from engine_adapters._mouse_plan import MOUSE_KINDS, UNITY_MOUSE_KINDS, validate_mouse_step
from engine_adapters._input_capabilities import (canonical_chord, MAX_PROBES, MAX_STEPS, MAX_STEP_MS)

KEYS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') | {'B', 'Enter', 'Return', 'Escape', 'Esc', 'Space', 'W', 'A', 'S', 'D', 'J', 'K', 'U', 'H', 'LMB', 'RMB', 'Tab', 'R', 'T', 'E', 'F', 'C', 'Shift', 'Left', 'Right', 'Up', 'Down'}
ERROR = re.compile(r'SCRIPT ERROR:|Parse Error:|error CS\d|PILOT_PRODUCT_ERROR|Failed to load script', re.I)


def validate_plan(plan: dict, project: Path, *, max_duration_ms=75000):
    if not 1000 <= plan['max_duration_ms'] <= max_duration_ms:
        raise ValueError(f'runtime budget must be 1..{max_duration_ms} ms')
    if not 0 <= len(plan['watchers']) <= 32 or not 1 <= len(plan['probes']) <= MAX_PROBES:
        raise ValueError('unbounded watcher/probe count')
    ids = set()
    for w in plan['watchers']:
        if w['id'] in ids or not w['id']:
            raise ValueError('duplicate/empty watcher ID')
        ids.add(w['id'])
        path = w['script']
        target = (project / path.removeprefix('res://')).resolve()
        if not path.startswith('res://') or not target.is_relative_to(project.resolve()) or not target.is_file() or target.suffix != '.gd':
            raise ValueError(f'invalid watcher script: {path}')
        selector = (r'[A-Za-z_][A-Za-z_0-9]*(?:\[[0-9]{1,3}\])?'
                    r'(?:\.(?:[A-Za-z_][A-Za-z_0-9]*(?:\[[0-9]{1,3}\])?|[0-9]{1,3})){0,5}')
        if not 0 <= w['index'] <= 16 or not re.fullmatch(selector, w['property']):
            raise ValueError('invalid watcher selector')
    # Catch provably incompatible observer predicates before opening an engine.
    # Unknown/dynamic types remain a runtime observer responsibility.
    string_watchers = set()
    property_types = {}
    for w in plan['watchers']:
        if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', w['property']):
            continue
        text = (project / w['script'].removeprefix('res://')).read_text(errors='replace')
        declaration = re.search(r'(?m)^\s*(?:@export\s+)?var\s+' + re.escape(w['property'])
            + r'\s*(?::\s*(StringName|String)\b|(?::=|=)\s*&?[\'\"])', text)
        if declaration:
            string_watchers.add(w['id'])
        declared = re.search(r'(?m)^\s*(?:@export\s+)?var\s+' + re.escape(w['property'])
            + r'\s*:\s*(bool|int|float|Vector2|Vector3)\b', text)
        if declared:
            property_types[w['id']] = declared.group(1)

    probe_ids, step_ids = set(), set()
    total = 0
    for probe in plan['probes']:
        if probe['id'] in probe_ids:
            raise ValueError('duplicate probe')
        probe_ids.add(probe['id'])
        if not 1 <= len(probe['steps']) <= MAX_STEPS:
            raise ValueError('invalid step count')
        for condition in probe['preconditions']:
            _validate_condition(condition, ids)
            _validate_property_condition(condition, property_types)
            if condition['watch'] in string_watchers:
                raise ValueError('observer condition compares a String property with a numeric value')
        for step in probe['steps']:
            if step['id'] in step_ids:
                raise ValueError('step IDs must be globally unique')
            step_ids.add(step['id'])
            if step['kind'] in MOUSE_KINDS:
                validate_mouse_step(step)
                total += step['duration_ms']
                continue
            if step['kind'] not in {'input', 'wait', 'wait_until', 'move_until', 'look'}:
                raise ValueError('unknown action')
            if step['kind'] in {'input', 'move_until'}:
                canonical_chord(step['key'], mouse=True)
            if step['kind'] == 'look' and (step['key'] not in {'Left','Right','Up','Down'} or not 0 <= step['value'] <= 1000):
                raise ValueError('invalid bounded mouse motion')
            if not 0 <= step['duration_ms'] <= MAX_STEP_MS or not 0 <= step['timeout_ms'] <= MAX_STEP_MS:
                raise ValueError('unbounded step')
            if step['kind'] in {'wait_until', 'move_until'}:
                _validate_condition(step, ids)
                _validate_property_condition(step, property_types)
                if step['watch'] in string_watchers:
                    raise ValueError('observer condition compares a String property with a numeric value')
            total += step['duration_ms'] if step['kind'] in {'input','wait','look'} else step['timeout_ms']
    if total > plan['max_duration_ms'] - 2000:
        raise ValueError('sum of worst-case steps exceeds run budget')
    return plan


def _validate_property_condition(condition, types):
    kind = types.get(condition['watch'])
    op = condition['op']
    if kind == 'bool' and (op not in {'eq', 'ne'} or condition['value'] not in (0, 1)):
        raise ValueError('observer bool property requires eq/ne with 0 or 1')
    if kind in {'Vector2', 'Vector3'} and op != 'distance_lt':
        raise ValueError('observer vector property requires distance_lt')
    if op == 'distance_lt':
        target = types.get(condition.get('target_watch'))
        if kind in {'bool', 'int', 'float'} or (kind and target and kind != target):
            raise ValueError('observer distance_lt requires compatible vector properties')


# Native adapters own input delivery. Only their physical-key vocabulary is
# accepted; state-dependent steps must never be silently converted into waits.
NATIVE_KEYS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789') | {'Enter','Return','Escape','Esc','Space','Tab','Shift','Left','Right','Up','Down'}


def normalize_native_plan_paths(plan: dict, project: Path, engine: str, *, audit_path=None):
    """Normalize only the known, unambiguous Three.js extra project/ prefix.

    The raw planner response remains in model_calls; this records the exact
    correction separately. No other malformed or missing path is rewritten.
    """
    from .protocol import dump
    engine = str(engine).lower()
    if engine not in {'three_js', 'threejs', 'three'}:
        return []
    changes = []
    project = Path(project).resolve()
    for field in ('launch_source', 'launch_scene'):
        value = plan.get(field, '')
        if not isinstance(value, str) or not value.startswith('project/'):
            continue
        # A valid nested entry is intentional, even if root index.html also exists.
        # Only a missing original and an existing contained candidate are unambiguous.
        if (project / value).exists():
            continue
        corrected = value[len('project/'):]
        candidate = (project / corrected).resolve()
        if (Path(value).is_absolute() or '..' in Path(corrected).parts
                or not candidate.is_relative_to(project) or not candidate.is_file()):
            continue
        plan[field] = corrected
        changes.append({'field': field, 'original': value, 'normalized': corrected,
                        'reason': 'unique extra project/ prefix; corrected path exists under project root'})
    if changes and audit_path is not None:
        audit_path = Path(audit_path)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_path.open('a') as stream:
            stream.write(json.dumps({'engine': 'three_js', 'changes': changes}, ensure_ascii=False) + '\n')
    return changes


class NativePlanValidationError(ValueError):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__('native physical key not supported: ' + '; '.join(
            f"{row['path']} probe={row['probe_id']} step={row['step_id']} current={row['value']!r}: {row['reason']}"
            for row in diagnostics))


def native_key_diagnostics(plan):
    errors = []
    for i, probe in enumerate(plan['probes']):
        for j, step in enumerate(probe['steps']):
            if step['kind'] != 'input':
                continue
            key = step['key']
            if not (1 <= len(key.split('+')) <= 3 and all(part in NATIVE_KEYS for part in key.split('+'))):
                errors.append({'path': f'/probes/{i}/steps/{j}/key', 'probe_id': probe['id'],
                    'step_id': step['id'], 'value': key,
                    'reason': 'empty input key' if not key else 'unsupported physical key',
                    'supported_keys': sorted(NATIVE_KEYS),
                    'hint': 'Use source-bound legal keyboard or explicit mouse action; never invent a substitute.'})
    return errors


def validate_native_plan(plan: dict, project: Path, engine: str, *, max_duration_ms=75000, max_steps_per_probe=None):
    from pipeline.code_gen.playtest.engine_dispatch import resolve_engine
    engine = resolve_engine(engine)
    if max_steps_per_probe is None:
        max_steps_per_probe = MAX_STEPS if engine == 'three_js' else 24
    if resolve_engine(plan['engine']) != engine:
        raise ValueError('native plan engine differs from original delivery')
    if plan['watchers'] or not 1000 <= plan['max_duration_ms'] <= max_duration_ms:
        raise ValueError('native observer/budget invalid')
    missing_startup = (engine == 'unity3d' and not plan['launch_source'] and not plan['launch_scene']
        and not any((project/'Assets').rglob('*.unity'))
        and not (project/'ProjectSettings/EditorBuildSettings.asset').exists())
    missing_configured_scene = (engine == 'unity3d'
        and plan['launch_source']=='ProjectSettings/EditorBuildSettings.asset'
        and (project/plan['launch_source']).is_file() and bool(plan['launch_scene'])
        and plan['launch_scene'] in (project/plan['launch_source']).read_text()
        and not (project/plan['launch_scene']).is_file())
    source = (project / plan['launch_source']).resolve()
    if not missing_startup and (not plan['launch_source'] or Path(plan['launch_source']).is_absolute()
            or not source.is_relative_to(project.resolve()) or not source.is_file()):
        raise ValueError('launch_source must be an existing original project file')
    scene = plan['launch_scene']
    version_file=project/'ProjectSettings/ProjectVersion.txt'
    tuanjie=version_file.is_file() and bool(re.search(r'\d+t\d+|Tuanjie', version_file.read_text(), re.I))
    scene_suffixes={'.unity','.scene'} if tuanjie else {'.unity'}
    if engine == 'unity3d' and scene:
        target = (project / scene).resolve()
        if not scene.startswith('Assets/') or target.suffix not in scene_suffixes or not target.is_relative_to(project.resolve()) or (not target.is_file() and not missing_configured_scene):
            raise ValueError('Unity launch scene is not an existing delivered scene')
    if engine == 'ue5' and scene:
        target = project / 'Content' / (scene.removeprefix('/Game/').split('.')[0]+'.umap')
        if not scene.startswith('/Game/') or '..' in scene or not target.is_file():
            raise ValueError('UE launch map is not an existing delivered map')
    if engine == 'three_js':
        from engine_adapters.three_js.playtest.launch import resolve_launch
        resolve_launch(project)
        if not plan['launch_source'] or Path(plan['launch_source']).is_absolute():
            raise ValueError('Three.js launch_source must be project-relative')
        entry = (project / plan['launch_source']).resolve()
        if not entry.is_relative_to(project.resolve()) or not entry.is_file():
            raise ValueError('Three.js launch_source is not an existing project-relative file')
        if scene:
            scene_path = Path(scene)
            resolved_scene = (project / scene_path).resolve()
            if (' -> ' in scene or scene_path.is_absolute() or not resolved_scene.is_relative_to(project.resolve())
                    or not resolved_scene.is_file()):
                raise ValueError('Three.js launch_scene is not an existing project-relative file')
    if not (0 if missing_startup or missing_configured_scene else 1) <= len(plan['probes']) <= (MAX_PROBES if engine == 'three_js' else 10):
        raise ValueError('invalid native probe count')
    if (missing_startup or missing_configured_scene) and plan['probes']:
        raise ValueError('missing-startup diagnostic must not claim executable gameplay')
    if engine != 'three_js':
        diagnostics = native_key_diagnostics(plan)
        if diagnostics:
            raise NativePlanValidationError(diagnostics)
    total = 2500
    ids = set()
    for probe in plan['probes']:
        if probe['id'] in ids or probe['preconditions']:
            raise ValueError('native probes cannot rely on unsupported state predicates')
        ids.add(probe['id'])
        if not 1 <= len(probe['steps']) <= max_steps_per_probe:
            raise ValueError(f'invalid native step count (limit {max_steps_per_probe})')
        for step in probe['steps']:
            allowed_kinds = {'input', 'wait'} | (MOUSE_KINDS if engine == 'three_js' else UNITY_MOUSE_KINDS if engine == 'unity3d' else set())
            if step['id'] in ids:
                raise ValueError('native step ID must be globally unique across probes: '+probe['id']+'/'+step['id'])
            if step['kind'] not in allowed_kinds:
                raise ValueError('native adapter supports explicit physical input/wait only')
            ids.add(step['id'])
            if step['kind'] in MOUSE_KINDS:
                validate_mouse_step(step)
                if not step.get('purpose') or not step.get('expected_observation'):
                    raise ValueError('native mouse steps need purpose and observable expectation')
                total += step['duration_ms']
                continue
            if not 0 <= step['duration_ms'] <= (MAX_STEP_MS if engine == 'three_js' else 6000) or step['timeout_ms'] != 0:
                raise ValueError('invalid native action budget')
            if step['kind'] == 'input':
                if engine == 'three_js': canonical_chord(step['key'])
                elif not (1 <= len(step['key'].split('+')) <= 3 and all(k in NATIVE_KEYS for k in step['key'].split('+'))):
                    raise ValueError('native physical key not supported')
            if not step['purpose'] or not step['expected_observation']:
                raise ValueError('native steps need purpose and observable expectation')
            total += max(step['duration_ms'], 100) if step['kind']=='input' else step['duration_ms']
    if total > plan['max_duration_ms']:
        raise ValueError(f"native worst-case steps exceed budget: effective_steps_ms={total-2500}, "
                         f"startup_safety_ms=2500, required_ms={total}, "
                         f"max_duration_ms={plan['max_duration_ms']}")
    return plan


def native_actions(plan):
    aliases={'Space':'space','Enter':'enter','Return':'return','Escape':'escape','Esc':'escape','Shift':'leftshift','Tab':'tab','Left':'left_arrow','Right':'right_arrow','Up':'up_arrow','Down':'down_arrow'}
    actions=[{'action':'wait','duration_ms':1800}]
    for probe in plan['probes']:
        for step in probe['steps']:
            if step['kind'] in MOUSE_KINDS:
                validate_mouse_step(step)
                row = {k: v for k, v in step.items() if k in {'id', 'duration_ms', 'x', 'y', 'to_x', 'to_y', 'button', 'delta_x', 'delta_y'}}
                actions.append(dict(row, action=step['kind'], **step_metadata(probe, step)))
                continue
            row={'action':'wait' if step['kind'] in {'wait', 'wait_until'} else 'key',
                 'duration_ms':step.get('timeout_ms', 100) if step['kind'] in {'wait_until','move_until'} else step.get('duration_ms', 100)}
            if step['kind'] in {'input','move_until'}:
                row['key'] = ('+'.join(canonical_chord(step['key'])) if plan.get('engine') in {'three_js', 'threejs', 'three'}
                              else '+'.join(aliases.get(k,k.lower()) for k in step['key'].split('+')))
            actions.append(dict(row, **step_metadata(probe, step)))
    from engine_adapters.action_provenance import action_duration_ms
    actions[0].update(action_id='system/startup', probe_id='system', step_id='startup',
        criterion_ids=[], purpose='Allow native startup', expected_observation='First usable game frame')
    elapsed=0
    identities=set()
    for action in actions:
        if action['action_id'] in identities:
            raise ValueError('duplicate action identity: '+action['action_id'])
        identities.add(action['action_id'])
        action['planned_t_ms']=elapsed
        elapsed+=action_duration_ms(action)
        action['planned_end_t_ms']=elapsed
    return actions


def step_metadata(probe, step):
    return {**({'client_role':step['client_role']} if 'client_role' in step else {}),
        'action_id':str(probe['id'])+'/'+str(step['id']), 'probe_id':probe['id'],
        'step_id':step['id'], 'criterion_ids':list(probe.get('criterion_ids', [])),
        'purpose':step.get('purpose') or probe.get('purpose', ''),
        'expected_observation':step.get('expected_observation', '')}


@contextlib.contextmanager
def engine_environment(project: Path, engine: str, godot=None):
    """Select installed matching editor, without rewriting a game or global config."""
    updates={}
    if engine=='godot' and godot:
        updates['A3GAME_GODOT_EXECUTABLE']=str(godot)
    elif engine=='unity3d':
        version_file=project/'ProjectSettings/ProjectVersion.txt'
        version=version_file.read_text() if version_file.exists() else ''
        tuanjie=bool(re.search(r'\d+t\d+|Tuanjie', version, re.I))
        binary=Path('/Applications/Tuanjie/Hub/Editor/2022.3.62t13/Tuanjie.app/Contents/MacOS/Tuanjie' if tuanjie else '/Applications/Unity/Hub/Editor/2022.3.62f3c1/Unity.app/Contents/MacOS/Unity')
        if binary.exists(): updates['A3GAME_UNITY_ROOT']=str(binary)
    elif engine=='ue5':
        markers=list(project.glob('*.uproject'))
        assoc=json.loads(markers[0].read_text()).get('EngineAssociation','') if markers else ''
        version=next((v for v in ('5.8','5.4') if str(assoc).startswith(v)),'5.8')
        # Blank associations use the installed generation default. An unavailable
        # exact version remains explicitly recorded; never rewrite .uproject.
        directory=Path('/Users/Shared/Epic Games')/('UE_'+version)
        if directory.exists():updates['A3GAME_UE_ROOT']=str(directory)
    previous={k:os.environ.get(k) for k in updates}
    os.environ.update(updates)
    try:yield
    finally:
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value


def _native_run(root, plan, engine, godot, *, deadline=None, budget=None):
    from pipeline.code_gen.playtest.engine_dispatch import record_playtest, ENGINE_CLIENTS, resolve_engine
    from . import core12
    from .legacy_g057 import native_step_limit
    project=root/'runtime/project'; folder=root/'runtime'
    budget=budget or {}
    rubric_path=root/'input/pilot_rubric.json'
    proto=json.loads(rubric_path.read_text()) if rubric_path.is_file() else {}
    case_id=proto.get('case_id','')
    step_limit = (96 if engine == 'three_js' else 24) if core12.enabled(proto) else native_step_limit(engine, case_id)
    validate_native_plan(plan,project,engine,max_duration_ms=int(budget.get('gameplay_ms',75000)),
        max_steps_per_probe=step_limit)
    from .legacy_g057 import enabled as legacy_enabled
    if not core12.enabled(proto) and legacy_enabled(proto) and case_id=='G057_rhythm_machine_hall' and resolve_engine(engine)=='three_js':
        from .legacy_g057 import validate_g057_chart_plan
        validate_g057_chart_plan(plan,int(budget.get('gameplay_ms',300000)),root/'input/project')
    extra={}
    if engine=='unity3d' and plan['launch_scene'] and (project/plan['launch_scene']).is_file():
        from engine_adapters.unity3d._internal.transport.unity_editor import playtest_recorder_files
        additions=[]
        for adapter,relative_path in playtest_recorder_files():
            relative=relative_path.as_posix();destination=project/relative
            if destination.exists() and sha(destination)!=sha(adapter):
                raise RuntimeError('adapter recorder name collides with delivered game source; refusing overwrite')
            additions.append({'path':relative,'sha256':sha(adapter),'source':str(adapter)})
        dump(folder/'instrumentation_manifest.json',{'added_files':additions})
    if engine=='unity3d':
        extra['scene']=plan['launch_scene']
        extra['missing_scene_diagnostic']=not plan['launch_scene'] or not (project/plan['launch_scene']).is_file()
    elif engine=='ue5':extra['map_path']=plan['launch_scene']
    elif engine=='three_js':extra.update(clock='realtime',warmup=0,look='off',
        import_build_timeout=budget.get('import_build_ms',180000)/1000,
        launch_timeout=budget.get('launch_wait_ms',45000)/1000,
        evidence_log_dir=folder)
    from . import endpoint_sparse
    if engine == 'three_js' and endpoint_sparse.enabled(proto):
        schedule = endpoint_sparse.validate_plan(proto, plan, engine, root=root)
        schedule['warmup_ms'] = 0
        dump(folder/'capture_schedule.json', schedule)
        extra['capture_schedule'] = folder/'capture_schedule.json'
    translated_actions=native_actions(plan)
    dump(folder/'action_schedule.json',{'version':'whitebox-action-provenance.v1','actions':translated_actions})
    with engine_environment(project,engine,godot):
        # UE source deliveries need the real editor target compiled first.
        # Build through the existing UEClient; never install/repair game plugins.
        if engine=='ue5' and ((project/'Source').exists() or (project/'Plugins').exists()):
            client=ENGINE_CLIENTS[engine](project)
            # An unrelated build must not consume this case's whole budget.
            # Leave its native mutex alone and let the queue run other engines.
            assert_unreal_build_available(root)
            # The existing adapter still owns serialization and the native
            # mutex for races after the read-only occupancy check.
            build=client.build.project(timeout=1800,wait_mutex=True)
            dump(folder/'build_result.json',build)
            payload=build.get('payload',{}) or {}
            (folder/'build.log').write_text(payload.get('stdout','')+'\n'+payload.get('stderr',''))
            if not build.get('ok'):
                # Missing SDK, timeout, compiler process crash and global build
                # mutex are evaluator/environment errors, not product verdicts.
                text=(folder/'build.log').read_text()
                errors=bool(re.search(r':\d+(?::\d+)?: (?:fatal )?error:|error C\d+',text))
                if not errors:
                    dump(folder/'engine_result.json',{'engine':engine,'phase':'build','product_errors':False,'adapter_result':build})
                    raise RuntimeError('UE build not completed; inspect runtime/build_result.json (not a game score)')
                result={'engine':engine,'product_errors':True,'phase':'build','adapter_result':build,'exit_code':payload.get('returncode')}
                dump(folder/'import_result.json',result);shutil.copyfile(folder/'build.log',folder/'import.log')
                dump(folder/'engine_result.json',result)
                dump(folder/'execution.json',{'status':'PRODUCT_BUILD_FAILED','inputs_sent':False,'no_state_injection':True})
                normalize_channels(root,engine)
                return result
        remaining=max(.1, deadline-time.monotonic()) if deadline else 180
        dispatched=record_playtest(engine=engine,project_path=project,output_dir=folder/'native',
            action_plan=translated_actions,duration=budget.get('recording_ms',plan['max_duration_ms'])/1000,fps=10,
            timeout=remaining,extra_engine_kwargs=extra,evidence_channels=['actions','states','events','frames'])
    dump(folder/'dispatch_result.json',dispatched)
    envelope=dispatched.get('envelope',{})
    dump(folder/'engine_result.json',{'engine':engine,'adapter_result':envelope,'product_errors':False})
    native=folder/'native'; native.mkdir(exist_ok=True)
    payload=envelope.get('payload',{}) or {}
    if engine=='three_js' and payload.get('take_dir'):
        take=Path(payload['take_dir']).resolve()
        if not take.is_relative_to(native.resolve()) or not take.is_dir():
            raise RuntimeError('Three.js recorder returned a take outside this attempt')
        native=take
    # All native bytes retained in place; canonical traces are identical copies.
    for name in ('actions.jsonl','state_trace.jsonl','event_trace.jsonl','frame_index.jsonl','video.mp4',
                 'play_started.json','input_view_cleanup.json','browser_cleanup.json'):
        if (native/name).is_file():shutil.copyfile(native/name,folder/name)
    if (native/'frames').is_dir():shutil.copytree(native/'frames',folder/'frames',dirs_exist_ok=True)
    logs=[]
    command=payload.get('command',{})
    if engine=='three_js' and isinstance(command,dict):
        for stream in ('stdout','stderr'):
            if isinstance(command.get(stream),str):
                log=folder/('recorder_'+stream+'.log'); log.write_text(command[stream]);logs.append(log)
    for candidate in [project/'Library/GameFactory3A/Editor.log',*native.glob('*.log')]:
        if candidate.is_file():
            dest=folder/('unity_editor.log' if candidate.name=='Editor.log' else candidate.name)
            shutil.copyfile(candidate,dest); logs.append(dest)
    if logs:
        # Do not infer import success from this concatenation: exact logs remain.
        (folder/'engine.log').write_text('\n'.join('=== '+x.name+' ===\n'+x.read_text(errors='replace') for x in logs))
    elif not (folder/'engine.log').exists():
        (folder/'engine.log').write_text(json.dumps(envelope,ensure_ascii=False,indent=2))
    text=(folder/'engine.log').read_text(errors='replace')
    payload=envelope.get('payload',{}) or {}
    # A compile fault in the added recorder belongs to the harness even when
    # the engine prints the same CS error format used for game scripts.
    from engine_adapters.unity3d._internal.transport.unity_editor import has_injected_compilation_error
    if engine == 'unity3d' and has_injected_compilation_error(text):
        raise RuntimeError('injected Unity recorder failed compilation; not a product verdict')
    compile_errors=bool(re.search(r'error CS\d+|SCRIPT ERROR:|Parse Error:|Failed to load script',text))
    startup_missing=payload.get('confirmed_missing_startup') is True
    product_errors=compile_errors or startup_missing
    result={'engine':engine,'adapter_result':envelope,'product_errors':product_errors,'native_evidence':'native'}
    dump(folder/'engine_result.json',result)
    if (folder/'engine.log').exists():shutil.copyfile(folder/'engine.log',folder/'import.log')
    dump(folder/'import_result.json',{'engine':engine,'product_errors':compile_errors,'completed':bool(envelope.get('ok')) or (startup_missing and payload.get('editor_exit_code')==0),'note':'Import/compile/load occurred inside dedicated editor launch; see exact native logs.'})
    actions=load_lines(folder/'actions.jsonl')
    if any(a.get('sent') is False or a.get('ok') is False for a in actions):
        raise RuntimeError('native adapter input delivery failure; not a product verdict')
    if not envelope.get('ok') and not product_errors:
        raise RuntimeError('native adapter failed without established product fault: '+json.dumps(envelope.get('errors',envelope),ensure_ascii=False)[:800])
    if not product_errors and (not actions or not load_lines(folder/'frame_index.jsonl')):
        raise RuntimeError('native recorder did not capture actual input and indexed frames')
    dump(folder/'execution.json',{'engine':engine,'status':'PRODUCT_ERROR' if product_errors else 'CAPTURED',
        'action_rows':len(actions),'no_state_injection':True,'declarative_plan_sha256':sha(root/'sol_plan.json'),
        'note':'CAPTURED does not claim a mechanism passed; judge raw evidence.'})
    normalize_channels(root,engine)
    return result


def normalize_channels(root,engine):
    folder=root/'runtime'; (folder/'frames').mkdir(exist_ok=True)
    channels={}
    for name,unavailable in [('state_trace.jsonl','UNAVAILABLE_STATE_CHANNEL'),('event_trace.jsonl','UNAVAILABLE_EVENT_CHANNEL')]:
        path=folder/name
        rows=load_lines(path)
        channels[name]='AVAILABLE' if rows else unavailable
        # Empty canonical files mean unavailable, not observed empty game state.
        if not path.exists():path.touch()
    for name in ['actions.jsonl','frame_index.jsonl']:
        if not (folder/name).exists():(folder/name).touch()
    dump(folder/'channels.json',{'engine':engine,**channels,'note':'Only raw captured rows count; unavailable channels never prove PASS.'})
    from .action_links import write_links
    write_links(folder)
    if (folder/'engine_result.json').exists():
        shutil.copyfile(folder/'engine_result.json',root/'engine_result.json')


def _validate_condition(c, ids):
    if c['watch'] not in ids or c['op'] not in {'eq', 'ne', 'gt', 'lt', 'distance_lt'} or not math.isfinite(c['value']):
        raise ValueError('invalid observation condition')
    if c['op'] == 'distance_lt' and c['target_watch'] not in ids:
        raise ValueError('distance target missing')


def run_process(cmd, log: Path, *, timeout: float):
    with log.open('w') as f:
        proc = subprocess.Popen([str(c) for c in cmd], stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
            return {'exit_code': proc.returncode, 'timeout': True, 'command': [str(c) for c in cmd]}
    return {'exit_code': code, 'timeout': False, 'command': [str(c) for c in cmd]}



def active_unreal_builds():
    """Find actual UBT commands, excluding searches, shells and editor hubs."""
    import shlex
    result = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True,
                            text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('HARNESS_ERROR: cannot inspect Unreal build occupancy')
    occupied = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        try:
            pid = int(fields[0])
            argv = shlex.split(fields[1])
        except ValueError:
            continue
        if not argv or pid == os.getpid():
            continue
        executable = Path(argv[0]).name.lower()
        if (executable in {'dotnet', 'dotnet.exe'} and len(argv)>1
                and Path(argv[1]).name.lower() == 'unrealbuildtool.dll') or executable in {'unrealbuildtool','unrealbuildtool.exe'}:
            occupied.append({'pid':pid, 'command':fields[1]})
    return occupied


def assert_unreal_build_available(root):
    started = time.monotonic()
    occupied = active_unreal_builds()
    if occupied:
        dump(Path(root)/'runtime/build_blocker.json', {
            'status':'HARNESS_ERROR', 'reason':'external UnrealBuildTool active',
            'processes':occupied, 'checked_unix':time.time(),
            'check_duration_ms':(time.monotonic()-started)*1000,
            'action':'defer this case; preserve external process and native build mutex'})
        raise RuntimeError('HARNESS_ERROR: external UnrealBuildTool active; '
                           'see runtime/build_blocker.json')


def active_gui_engines():
    """Read-only occupancy check for native editors outside our flock protocol."""
    result = subprocess.run(['ps', '-axo', 'pid=,command='], capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('HARNESS_ERROR: cannot inspect external GUI engine occupancy')
    occupied = []
    for line in result.stdout.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) != 2:
            continue
        pid, command = fields
        if not command.startswith('/'):
            continue
        executable = command.partition(' -')[0]
        native = (executable.endswith(('.app/Contents/MacOS/Unity',
                     '.app/Contents/MacOS/Tuanjie', '.app/Contents/MacOS/UnrealEditor'))
                  or Path(executable).name in {'godot','godot4'})
        # A Hub command line can retain a completed project's arguments for
        # days. Only a live editor executable is an engine input target.
        headless = any(flag in command.split() for flag in ('-batchmode','--headless','-nullrhi','-NullRHI'))
        if native and not headless:
            occupied.append({'pid':int(pid),'command':command,'kind':'editor'})
    return occupied


def console_capability_probe(*, require_desktop_capture=True):
    """Verify console/focus access, optionally testing desktop screenshots.

    Client viewport capture is checked from actual recorder frames, not from a
    screenshot of the unrelated application foregrounded before game launch.
    """
    try:
        import Quartz as Q
        import AppKit
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        pid = int(app.processIdentifier()) if app else None
        session = dict(Q.CGSessionCopyCurrentDictionary() or {})
        windows = Q.CGWindowListCopyWindowInfo(
            Q.kCGWindowListOptionOnScreenOnly | Q.kCGWindowListExcludeDesktopElements,
            Q.kCGNullWindowID) or []
        targets = [dict(w) for w in windows if w.get('kCGWindowOwnerPID') == pid
                   and w.get('kCGWindowLayer') == 0 and w.get('kCGWindowAlpha', 0) > 0]
        result = {'session': session, 'frontmost_pid': pid,
                  'visible_window_ids': [int(w['kCGWindowNumber']) for w in targets],
                  'screen_capture_permission': bool(Q.CGPreflightScreenCaptureAccess()),
                  'usable': False}
        if not session.get('kCGSSessionOnConsoleKey') or not session.get('kCGSessionLoginDoneKey'):
            result['reason'] = 'no_logged_in_console'; return result
        if session.get('CGSSessionScreenIsLocked') is True:
            result['reason'] = 'locked'; return result
        if not targets or (require_desktop_capture and not result['screen_capture_permission']):
            # When capture_backend is client_viewport, no frontmost window is
            # required before the engine launches: the recorder opens its own
            # window and acquires focus independently.
            if not require_desktop_capture:
                result.update(usable=True, reason='console_focus_verified_no_window',
                              capture_method='client_viewport', capture_verified=False)
                return result
            result['reason'] = 'no_capturable_frontmost_window'; return result
        # Read the AX focus owner/window independently from WindowServer.
        ax = subprocess.run(['osascript', '-e',
            'tell application "System Events" to tell first application process whose frontmost is true '
            'to return {unix id, exists value of attribute "AXFocusedWindow"}'],
            capture_output=True, text=True, timeout=10)
        result['ax_focus_response'] = ax.stdout.strip()
        result['ax_focus_error'] = ax.stderr.strip()
        if ax.returncode or ax.stdout.strip() != f'{pid}, true':
            result['reason'] = 'focused_window_unverified'; return result
        if not require_desktop_capture:
            result.update(usable=True, reason='console_focus_verified_capture_pending',
                          capture_method='client_viewport', capture_verified=False)
            return result
        from PIL import Image
        import threading
        with tempfile.TemporaryDirectory(prefix='a3-console-probe-') as tmp:
            image = Path(tmp)/'window.png'
            window_id = str(targets[0]['kCGWindowNumber'])
            cap_result: dict = {}
            def _cap():
                try:
                    r = subprocess.run(
                        ['screencapture', '-x', '-l', window_id, str(image)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE, text=True, timeout=4)
                    cap_result['ok'] = r.returncode == 0
                    cap_result['stderr'] = r.stderr.strip()
                except subprocess.TimeoutExpired:
                    cap_result['timeout'] = True
                except Exception as e:
                    cap_result['error'] = str(e)
            t = threading.Thread(target=_cap, daemon=True)
            t.start(); t.join(timeout=5)
            if cap_result.get('ok') and image.is_file() and image.stat().st_size > 0:
                with Image.open(image) as im:
                    im.load(); result['captured_size'] = list(im.size)
                    result['usable'] = im.width > 32 and im.height > 32
                result['capture_method'] = 'window_screenshot'
            else:
                # A successful session/focus query does not establish capture.
                # Standalone adapter diagnostics may test viewport capture, but
                # this generic screenshot gate must remain fail-closed.
                result['capture_method'] = 'screenshot_probe_failed'
                result['capture_note'] = cap_result
                result['usable'] = False
        result['reason'] = 'observed_focused_capturable_window' if result['usable'] else 'window_too_small'
        return result
    except Exception as exc:
        return {'usable': False, 'reason': 'capability_probe_failed', 'error': str(exc)}


def console_gui_status(*, capture_backend='desktop'):
    """Four-state preflight; viewport availability remains pending until capture."""
    import sys
    if sys.platform != 'darwin':
        return {'available': True, 'screen_locked': False, 'status': 'AVAILABLE', 'source': 'non_macos'}
    # Engine clients (Godot, Unity, UE5) open and focus their own window during
    # launch; the desktop does not need a capturable frontmost window beforehand.
    # Only check that a live, unlocked console session exists.
    if capture_backend == 'client_viewport':
        command = ['ioreg', '-n', 'Root', '-d1']
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {'available': False, 'screen_locked': None, 'status': 'UNKNOWN',
                    'source': 'ioreg', 'error': str(exc)}
        locked_match = re.search(r'"CGSSessionScreenIsLocked"\s*=\s*(Yes|No)', result.stdout)
        locked = locked_match.group(1) == 'Yes' if locked_match else None
        if locked is True:
            return {'available': False, 'screen_locked': True, 'status': 'LOCKED',
                    'source': 'ioreg', 'capture_backend': capture_backend}
        on_console = bool(re.search(r'"kCGSSessionOnConsoleKey"\s*=\s*Yes', result.stdout))
        login_done = bool(re.search(r'"kCGSessionLoginDoneKey"\s*=\s*Yes', result.stdout))
        if not on_console or not login_done:
            return {'available': False, 'screen_locked': locked, 'status': 'NO_CONSOLE',
                    'source': 'ioreg', 'capture_backend': capture_backend}
        return {'available': True, 'screen_locked': False, 'status': 'AVAILABLE',
                'source': 'ioreg_session_only', 'capture_backend': capture_backend,
                'note': 'Engine client opens its own window; desktop frontmost window not required'}
    command = ['ioreg', '-n', 'Root', '-d1']
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'available': False, 'screen_locked': None, 'status': 'UNKNOWN', 'source': 'ioreg', 'error': str(exc)}
    match = re.search(r'"CGSSessionScreenIsLocked"\s*=\s*(Yes|No)', result.stdout)
    locked = match.group(1) == 'Yes' if match else None
    record = next((line.strip() for line in result.stdout.splitlines() if 'IOConsoleUsers' in line), '')
    status = 'LOCKED' if locked is True else 'UNKNOWN'
    probe = None
    if result.returncode == 0 and locked is not True:
        probe = (console_capability_probe(require_desktop_capture=False)
                 if capture_backend == 'client_viewport' else console_capability_probe())
        if probe.get('reason') == 'locked':
            locked = True; status = 'LOCKED'
        elif probe.get('reason') == 'no_logged_in_console':
            status = 'NO_CONSOLE'
        elif probe.get('usable') is True:
            status = 'AVAILABLE'
    return {'available': status == 'AVAILABLE', 'screen_locked': locked,
            'status': status, 'source': 'ioreg+windowserver+AX' if probe else 'ioreg',
            'command': command, 'checked_unix': time.time(), 'console_record': record,
            'capability_probe': probe, 'error': result.stderr.strip() if result.returncode else None}


def collector_failure_status(reason):
    """Distinguish an unavailable collector from a failed evaluation environment.

    Recognize only known historical preflight messages. Summary may reclassify
    their effective status, but must retain their original status/log bytes.
    An unknown genuinely blocked collector remains blocked, without a score.
    """
    prefix = 'BLOCKED_ENGINE_COLLECTOR:'
    message = str(reason)
    if not message.startswith(prefix):
        return 'HARNESS_ERROR'
    detail = message[len(prefix):].lstrip()
    environment_reasons = (
        'macOS console screen is locked',
        'cannot verify interactive console availability',
        'external GUI engine active:',
        'global GUI recording lock occupied',
        'cannot inspect external GUI engine occupancy',
        'external UnrealBuildTool active;',
        'cannot inspect Unreal build occupancy',
    )
    return 'HARNESS_ERROR' if detail.startswith(environment_reasons) else 'BLOCKED_ENGINE_COLLECTOR'


def assert_gui_available(root, *, capture_backend='desktop'):
    console = (console_gui_status(capture_backend=capture_backend)
               if capture_backend != 'desktop' else console_gui_status())
    if not console['available']:
        dump(Path(root)/'gui_session_blocker.json', console)
        reason = ('macOS console screen is locked' if console['screen_locked'] is True
                  else 'console GUI availability is unknown' if console.get('status') == 'UNKNOWN'
                  else 'no usable console GUI session')
        raise RuntimeError('HARNESS_ERROR: ' + reason + '; see gui_session_blocker.json')
    occupied = active_gui_engines()
    if occupied:
        dump(Path(root)/'gui_occupancy.json', {'checked_unix':time.time(), 'blocked_by':occupied,
             'policy':'do not terminate unrelated processes or compete for GUI focus'})
        raise RuntimeError('HARNESS_ERROR: external GUI engine active: '+
                           ', '.join(str(p['pid']) for p in occupied))


def run_engine(root: Path, plan: dict, godot: Path, *, engine="godot"):
    from . import core12
    protocol_path=root/'input/pilot_rubric.json'
    if protocol_path.is_file() and ('planning_contract' in json.loads(protocol_path.read_text())
                                   or 'planning_identity' in plan):
        from .batch import validate_operation_plan
        plan=validate_operation_plan(root,plan,engine)
    # One GUI take at a time, including independent/resumed batch invocations.
    lock=Path(tempfile.gettempdir())/'gamefactory-sol-whitebox-gui.lock'
    with lock.open('a') as held:
        proto_path=root/'input/pilot_rubric.json'
        proto=json.loads(proto_path.read_text()) if proto_path.is_file() else {}
        from .runtime_budgets import resolve_recording_budget
        budget=resolve_recording_budget(root,proto.get('runtime_budget',{}))
        if (root/'native_record_completion_policy.json').exists():
            from .mechanic_v3_record_completion import effective_budget
            budget=effective_budget(root,proto,plan,budget)
        started=time.monotonic()
        dump(root/'runtime/budget_resolution.json', {'effective_budget':budget,'plan_max_duration_ms':plan.get('max_duration_ms'),
            'passive_observation_extension_ms':max(0,budget['recording_ms']-plan.get('max_duration_ms',budget['recording_ms'])),
            'source_protocol_sha256':sha(proto_path) if proto_path.is_file() else None})
        dump(root/'runtime/preflight.json',{'checked_unix':time.time(),'pid':os.getpid(),
            'engine':engine,'lock_path':str(lock),'external_gui_engines':active_gui_engines(),
            'target':str(root/'runtime/project'),'policy':'serial recorder; no unrelated process terminated'})
        call_deadline=started+budget['engine_call_ms']*.001
        lock_deadline=min(call_deadline,time.monotonic()+15)
        while True:
            try:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=lock_deadline:
                    raise RuntimeError('HARNESS_ERROR: global GUI recording lock occupied')
                time.sleep(.1)
        try:
            if engine != 'godot':
                from pipeline.code_gen.playtest.engine_dispatch import resolve_engine
                return _native_run(root,plan,resolve_engine(engine),godot,deadline=call_deadline,budget=budget)
            return _run_engine_unlocked(root,plan,godot,deadline=call_deadline,budget=budget)
        except Exception as exc:
            if not (root/'runtime/engine_result.json').exists():
                dump(root/'runtime/engine_result.json',{'engine':engine,'status':'HARNESS_ERROR','error':str(exc),'product_errors':False})
            raise
        finally:
            # Preserve the primary collection failure if a killed process also
            # left an incomplete JSONL tail. Raw bytes are never repaired.
            dump(root/'runtime/timing.json',{'engine':engine,'elapsed_ms':round((time.monotonic()-started)*1000),
                'budget':budget,'timeout':time.monotonic()>call_deadline,
                'timeout_reason':'engine_call deadline exceeded' if time.monotonic()>call_deadline else None})
            import sys
            primary_error = sys.exc_info()[1]
            try:
                normalize_channels(root,engine)
            except Exception as normalization_error:
                if primary_error is None:
                    raise
                dump(root/'runtime/channel_normalization_error.json', {
                    'status': 'HARNESS_ERROR', 'error': str(normalization_error),
                    'primary_error': str(primary_error), 'raw_evidence_preserved': True})


def _run_engine_unlocked(root: Path, plan: dict, godot: Path, *, deadline=None, budget=None):
    project = root / 'runtime' / 'project'
    folder = root / 'runtime'
    deadline=deadline or time.monotonic()+180
    budget=budget or {}
    dump(folder/'action_schedule.json',{'version':'whitebox-action-provenance.v1','actions':native_actions(plan)})
    startup=float(budget.get('import_build_ms',budget.get('engine_startup_ms',90000)))/1000
    imp = run_process([godot, '--headless', '--path', project, '--editor', '--import'], folder / 'import.log', timeout=min(startup,max(.1,deadline-time.monotonic())))
    imp['product_errors'] = bool(ERROR.search((folder / 'import.log').read_text(errors='replace')))
    dump(folder / 'import_result.json', imp)
    recorder = Path(__file__).resolve().parents[3] / 'engine_adapters/godot/playtest/bounded_recorder.gd'
    observation_plan = root/'sol_plan.json'
    from .runtime_budgets import RECOVERY_VERSION
    from . import endpoint_sparse
    proto_path = root/'input/pilot_rubric.json'
    sparse = proto_path.is_file() and endpoint_sparse.enabled(proto := json.loads(proto_path.read_text()))
    if sparse:
        schedule = endpoint_sparse.validate_plan(proto, plan, 'godot', root=root)
        schedule['warmup_ms'] = 0
        observation_plan = folder/'recording_plan.json'
        dump(observation_plan, {**plan, 'recording_ms': budget['recording_ms'], 'native_capture_schedule': schedule})
    elif budget.get('version') == RECOVERY_VERSION:
        # Keep the executable action plan immutable; pin only passive capture length.
        observation_plan = folder/'recording_plan.json'
        dump(observation_plan, {**plan, 'recording_ms': budget['recording_ms']})
    dump(folder / 'execution_inputs.json', {'plan_sha256':sha(root/'sol_plan.json'),
        'recording_plan_path':str(observation_plan), 'recording_plan_sha256':sha(observation_plan),
        'observer_sha256':sha(recorder), 'observer_path':str(recorder)})
    # Parse our observer separately: observer bugs must never become product failures.
    check = run_process([godot, '--headless', '--path', project, '--script', recorder, '--check-only'], folder / 'observer_check.log', timeout=min(20,max(.1,deadline-time.monotonic())))
    if check['exit_code'] != 0:
        raise RuntimeError('observer compile error; see runtime/observer_check.log')
    if imp['timeout']:
        raise RuntimeError('engine import timed out (environment/runner unresolved)')
    if imp['exit_code'] and not imp['product_errors']:
        raise RuntimeError('engine import failed without a diagnosed product error')
    from pipeline.code_gen.playtest.engine_dispatch import record_playtest
    with engine_environment(project,'godot',godot):
        dispatched=record_playtest(engine='godot',project_path=project,output_dir=folder,
            action_plan=[],duration=budget.get('recording_ms',plan['max_duration_ms'])/1000,fps=10,
            timeout=max(.1,deadline-time.monotonic()),
            extra_engine_kwargs={'observation_plan':observation_plan,'width':960,'height':540})
    dump(folder/'dispatch_result.json',dispatched)
    envelope=dispatched.get('envelope',{})
    run=dict(envelope.get('payload',{}))
    run['adapter_result']=envelope
    if not (folder/'engine.log').exists():
        raise RuntimeError('Godot adapter failed before recording: '+json.dumps(envelope)[:800])
    text = (folder / 'engine.log').read_text(errors='replace')
    run['product_errors'] = bool(ERROR.search(text))
    run['observer_errors'] = 'PILOT_HARNESS_ERROR' in text or bool(re.search(r'SCRIPT ERROR:[^\n]*\n[^\n]*at:[^\n]*\(' + re.escape(str(recorder)) + r':', text))
    dump(folder / 'engine_result.json', run)
    if any(a.get('sent') is False for a in load_lines(folder/'actions.jsonl')):
        raise RuntimeError('observer input delivery failure; not a product verdict')
    if run['observer_errors'] or run.get('timeout'):
        raise RuntimeError('observer/runtime harness error; inspect engine.log')
    if not (folder / 'execution.json').is_file() and not run['product_errors']:
        raise RuntimeError('recorder did not complete and product failure is not established')
    return {'import': imp, 'runtime': run}


def is_input_action(action):
    """Recognize native recorder input rows, excluding waits and failed sends."""
    if action.get('sent') is False:
        return False
    return (action.get('kind') == 'press' or action.get('phase') == 'down'
            or (action.get('sent') is True and bool(action.get('keys') or action.get('taps'))))


def create_manifest(root: Path):
    items = []
    def add(ident, path, typ, **kw):
        if path.is_file():
            items.append({'id': ident, 'path': str(path.relative_to(root)), 'type': typ, 'sha256': sha(path), **kw})
    for p in sorted((root / 'input' / 'project').rglob('*')):
        if p.is_file() and p.suffix.lower() in {'.gd','.tscn','.json','.md','.godot','.cfg','.txt','.cs','.unity','.scene','.prefab','.asset','.cpp','.h','.hpp','.ini','.uproject','.uplugin','.js','.ts','.html','.css'}:
            add('SRC:' + str(p.relative_to(root / 'input' / 'project')), p, 'source' if p.suffix in {'.gd','.tscn','.godot','.cs','.unity','.scene','.prefab','.asset','.cpp','.h','.hpp','.ini','.uproject','.uplugin','.js','.ts','.html','.css'} else 'document')
    add('REQUIREMENTS', root / 'input' / 'requirement.txt', 'document')
    add('IMPORT', root / 'runtime' / 'import.log', 'log')
    add('IMPORT_RESULT', root / 'runtime' / 'import_result.json', 'log')
    add('ENGINE', root / 'runtime' / 'engine.log', 'log')
    add('STATE', root / 'runtime' / 'state_trace.jsonl', 'state')
    add('ACTION', root / 'runtime' / 'actions.jsonl', 'action')
    add('EVENT', root / 'runtime' / 'event_trace.jsonl', 'event')
    for ident,name in [('BUILD','build.log'),('BUILD_RESULT','build_result.json'),('EXECUTION','execution.json'),('CHANNELS','channels.json'),('ENGINE_RESULT','engine_result.json')]:
        add(ident,root/'runtime'/name,'log')
    for p in sorted((root / 'input' / 'references').glob('*')):
        add('REF:' + p.name, p, 'reference')
    frames = load_lines(root / 'runtime' / 'frame_index.jsonl')
    from .action_links import write_links, select_frames
    links=write_links(root/'runtime')
    indices,selection=select_frames(frames,links,30)
    for ix in indices:
        row = frames[ix]
        frame_id=row.get('frame_id') or row.get('id') or f'FRAME:{ix+1:05d}'
        add(frame_id, root / 'runtime' / row['path'], 'frame', t_ms=row.get('t_ms',row.get('timestamp_ms')),
            probe=row.get('probe'), step=row.get('step'), frame_id=frame_id, delivered_to_judge=True)
    multisession=(root/'runtime/multisession_index.json').is_file()
    if multisession:
        for ident,name,typ in [('NATIVE_SESSIONS','multisession_index.json','log'),
                               ('NATIVE_LOG_INDEX','log_index.jsonl','log'),
                               ('HOST_ENGINE','sessions/host/Editor.log','log')]:
            if ident == 'HOST_ENGINE' and not (root/'runtime'/name).is_file():
                name='sessions/host/player.log'
            add(ident,root/'runtime'/name,typ)
        from .prepare_unity_recorded_judge import NATIVE_OBSERVER_METADATA, OPTIONAL_OBSERVER_METADATA
        for role in ('A','B'):
            for ident,name in {**NATIVE_OBSERVER_METADATA,**OPTIONAL_OBSERVER_METADATA}.items():
                add(ident+':'+role,root/'runtime/sessions'/role/name,'log')
    result = {'version': 'sol-pilot-evidence.v1',
              'clock': 'independent_role_local_monotonic' if multisession else 'session_monotonic', 'items': items,
              'raw_frame_count': len(frames), 'delivered_frame_count': len(indices),
              'action_frame_links': {'path':'runtime/action_frame_links.json','sha256':sha(root/'runtime/action_frame_links.json')},
              'frame_selection':selection}
    from .native_clock_binding import RECEIPT as clock_receipt, apply as apply_clock
    if (root/clock_receipt).is_file():
        result = apply_clock(root, result)
    dump(root / 'evidence_manifest.json', result)
    return result


def trace_summary(root: Path):
    """Exact line-numbered observations, not synthetic success events."""
    rows = load_lines(root / 'runtime' / 'state_trace.jsonl')
    actions = load_lines(root / 'runtime' / 'actions.jsonl')
    ix = set()
    if rows:
        ix.update([0, len(rows)-1])
        for action in actions:
            for offset in [-100, 0, 100, 300, 600, 1100]:
                target = action['t_ms'] + offset
                candidates=[i for i,row in enumerate(rows) if not action.get('session_id')
                            or row.get('session_id')==action['session_id']]
                if candidates:ix.add(min(candidates,key=lambda i: abs(rows[i]['t_ms']-target)))
        # Include every value transition for scalar fields to expose unexpected changes.
        last = None
        for i, row in enumerate(rows):
            scalar = {k:v for k,v in row.get('values',row.get('state',{})).items() if not isinstance(v, (dict,list))}
            if scalar != last:
                # Stamina/timer may change each frame: action samples already cover them.
                important = {k:v for k,v in scalar.items() if not any(s in k.lower() for s in ['timer','stamina','time'])}
                old = {k:v for k,v in (last or {}).items() if not any(s in k.lower() for s in ['timer','stamina','time'])}
                if important != old:
                    ix.add(i)
                last = scalar
    from .action_links import physical_rows
    physical=physical_rows(root/'runtime/state_trace.jsonl')
    link_path=root/'runtime/action_frame_links.json'
    linked=set()
    if link_path.is_file():
        linked={line for link in json.loads(link_path.read_text())['links'] for line in link['states']}
    if len(ix) > 160:
        ordered = sorted(ix)
        ix = {ordered[round(i*(len(ordered)-1)/159)] for i in range(160)}
    result = {'state_line_count': len(rows), 'actions': [{'line':i+1, **a} for i,a in enumerate(actions)],
              'state_samples': [{'line':line, **row} for pos,(line,row) in enumerate(physical) if pos in ix or line in linked],
              'note': 'All samples are exact raw rows; STATE evidence citations must use original line numbers.'}
    from .event_observation import validate_event_snapshot_rows
    event_observation = validate_event_snapshot_rows(load_lines(root / 'runtime' / 'event_trace.jsonl'))
    if event_observation is not None:
        result['event_observation'] = event_observation
    dump(root / 'trace_summary.json', result)
    return result
