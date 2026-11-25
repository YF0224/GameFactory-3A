"""Explicit legacy protocol replay only. Never imported by vNext."""
import copy

def native_step_limit(engine: str, case_id: str) -> int:
    """Share the audited full-chart exception across planning and capture gates."""
    return 512 if engine == 'three_js' and case_id == 'G057_rhythm_machine_hall' else (96 if engine in {'godot', 'three_js'} else 24)

def validate_coverage_plan(plan: dict, budget: dict, expected_atom_ids=None) -> None:
    if not 1000 <= plan['max_duration_ms'] <= budget['gameplay_ms']:
        raise ValueError('plan gameplay duration exceeds preregistered tier budget')
    coverage = plan.get('coverage', [])
    if not coverage:
        raise ValueError('v4 plan must preregister atomic coverage windows')
    atom_ids = set()
    for row in coverage:
        if not row['atom_id'] or row['atom_id'] in atom_ids:
            raise ValueError('coverage atom IDs must be unique')
        atom_ids.add(row['atom_id'])
        if not 0 <= row['start_ms'] < row['end_ms'] <= plan['max_duration_ms']:
            raise ValueError('coverage window outside plan gameplay budget')
        if not row['stop_condition'].strip():
            raise ValueError('coverage window needs a stop condition')
    if expected_atom_ids is not None and atom_ids != set(expected_atom_ids):
        missing = sorted(set(expected_atom_ids) - atom_ids)
        extra = sorted(atom_ids - set(expected_atom_ids))
        raise ValueError(f'coverage atom IDs must match frozen rubric exactly; missing={missing}, extra={extra}')


def g057_chart_events() -> list[dict]:
    """Reproduce the delivered G057 chart generator, including seeded opening lanes."""
    state = 1057

    def random():
        nonlocal state
        state = (state * 1664525 + 1013904223) & 0xffffffff
        return state / 4294967296

    notes = []
    for i in range(12):
        notes.append({'time_ms': 2000 + i * 1000, 'lane': int(random() * 4), 'duration_ms': 0})
    for i in range(88):
        notes.append({'time_ms': 15500 + i * 625, 'lane': i % 4,
                      'duration_ms': 400 if i % 4 == 0 else 0})
    for i in range(60):
        time_ms = 70250 + i * 500
        lane = i % 4
        notes.append({'time_ms': time_ms, 'lane': lane, 'duration_ms': 0})
        if i % 5 == 0:
            notes.append({'time_ms': time_ms, 'lane': (lane + 2) % 4, 'duration_ms': 0})
    return sorted(notes, key=lambda note: (note['time_ms'], note['lane']))


def build_g057_complete_steps(project) -> list[dict]:
    """Build real key operations from the delivered chart, not model-sampled taps."""
    import json
    import re
    import subprocess
    from pathlib import Path

    # Callers may hand us a relative snapshot path. Node resolves imports from
    # the supplied path, while its cwd is the project root; normalize once so
    # the path cannot be prefixed with the project a second time.
    project = Path(project).resolve()
    if not project.is_dir():
        raise ValueError(f'G057 selected delivery is not a project directory: {project}')

    # Deliveries of the same frozen game have used more than one source layout.
    # Locate authored chart/input modules from the selected project, then execute
    # the exported chart generator in an isolated Node process.  This reads the
    # delivered implementation; it does not inject state or use a playtest bot.
    chart_candidates = [
        project / 'src/mechanics/chart.js',
        project / 'packages/rhythm-hall/src/chart.js',
        project / 'packages/rhythm-hall/src/mechanic.js',
    ]
    chart_path = next((path for path in chart_candidates if path.is_file()), None)
    if chart_path is None:
        discovered = sorted(project.glob('**/chart.js')) + sorted(project.glob('**/mechanic.js'))
        chart_path = next((path for path in discovered if path.is_file()), None)
    if chart_path is None:
        raise ValueError('G057 chart source is missing from the selected delivery')

    sources = []
    for path in sorted(project.glob('**/*')):
        if path.is_file() and path.suffix in {'.js', '.mjs', '.ts', '.tsx'}:
            try:
                sources.append((path, path.read_text(errors='replace')))
            except OSError:
                continue
    binding_text = '\n'.join(text for _, text in sources)
    binding_match = None
    for pattern in (
        r'(?:LANE_KEYS|keyCodes|KEY_CODES|laneKeys)\s*[:=]\s*\[([^\]]+)\]',
        r'(?:LANE_KEYS|keyCodes|KEY_CODES|laneKeys)\s*=\s*([^;\n]+)',
    ):
        binding_match = re.search(pattern, binding_text, re.I)
        if binding_match:
            break
    lane_keys = re.findall(r"['\"](Key[A-Za-z0-9]+)['\"]", binding_match.group(1)) if binding_match else []
    direct_title_start = False
    if not lane_keys:
        # The delivered GLM implementation maps KeyboardEvent.code to lane
        # numbers instead of storing a lane-key array. Accept only a complete,
        # unique 0..3 mapping used by its actual keyboard handler.
        mappings = []
        for path, text in sources:
            match = re.search(r"const\s+KEYMAP\s*=\s*\{([^}]+)\}", text)
            if not match:
                continue
            pairs = re.findall(r"\b(Key[A-Za-z0-9]+)\s*:\s*([0-3])\b", match.group(1))
            residue = re.sub(r"\bKey[A-Za-z0-9]+\s*:\s*[0-3]\b", '', match.group(1))
            if (residue.replace(',', '').strip() or len(pairs) != 4
                    or len({key for key, _ in pairs}) != 4
                    or {int(lane) for _, lane in pairs} != set(range(4))):
                raise ValueError('G057 KEYMAP is not an unambiguous four-lane mapping')
            required = ("window.addEventListener('keydown'", 'e.code in KEYMAP',
                        'KEYMAP[e.code]', "if (phase === 'title') startPlay()",
                        "e.code === 'Escape'", 'paused = !paused',
                        "phase = 'play'", 'songTime = 0',
                        'musicStart = performance.now()')
            if not all(fragment in text for fragment in required):
                raise ValueError('G057 KEYMAP flow lacks source-qualified native start/pause handling')
            mappings.append([key for key, lane in sorted(pairs, key=lambda pair: int(pair[1]))])
        if len(mappings) != 1:
            raise ValueError('G057 KEYMAP source is missing or ambiguous')
        lane_keys = mappings[0]
        direct_title_start = True
    if len(lane_keys) != 4 or len(set(lane_keys)) != 4:
        raise ValueError('G057 keyboard bindings are not source-derived or are not Key* codes')

    node_script = r'''
import { pathToFileURL } from 'node:url';
const mod = await import(pathToFileURL(process.argv[1]).href);
const fn = mod.generateChart || mod.buildChart || mod.createChart || mod.default;
if (typeof fn !== 'function') throw new Error('chart module exports no generator');
const chart = await fn();
process.stdout.write(JSON.stringify(chart));
'''
    try:
        completed = subprocess.run(
            ['node', '--input-type=module', '-e', node_script, str(chart_path)],
            cwd=str(project), capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f'could not execute delivered G057 chart generator: {exc}') from exc
    notes = None
    if completed.returncode == 0:
        try:
            generated = json.loads(completed.stdout)
            notes = generated.get('notes', generated) if isinstance(generated, dict) else generated
            if not isinstance(notes, list) or not notes:
                notes = None
        except (TypeError, ValueError, json.JSONDecodeError):
            notes = None
    if notes is None:
        # A historical G057 delivery exposes the chart as a small authored
        # ``add(...)`` routine without returning its local list.  Reconstruct
        # only that declared sequence from its source expressions; this keeps
        # compatibility with the delivery while still rejecting drift.
        source = chart_path.read_text(errors='replace')
        legacy_fragments = ('2000+i*1000', '15500+i*625', '70250+i*500', 'i%5===0')
        if not all(fragment in source.replace(' ', '') for fragment in legacy_fragments):
            detail = (completed.stderr or completed.stdout).strip()[-1000:]
            raise ValueError(f'delivered G057 chart generator failed: {detail}')
        notes = []
        for i in range(12):
            notes.append({'t': 2000 + i * 1000, 'lane': i % 4, 'dur': 0})
        for i in range(88):
            notes.append({'t': 15500 + i * 625, 'lane': i % 4,
                          'dur': 400 if i % 4 == 0 else 0})
        for i in range(60):
            t = 70250 + i * 500
            lane = i % 4
            notes.append({'t': t, 'lane': lane, 'dur': 0})
            if i % 5 == 0:
                notes.append({'t': t, 'lane': (lane + 2) % 4, 'dur': 0})

    steps = []
    elapsed = 1800  # native_actions inserts this real startup wait before the plan.

    def add(kind, duration, key='', purpose='', expected='', expected_observation=''):
        nonlocal elapsed
        ident = f'g057-op-{len(steps) + 1:03d}'
        steps.append({'id': ident, 'kind': kind, 'key': key, 'duration_ms': duration,
                      'timeout_ms': 0, 'purpose': purpose or 'Advance the delivered chart sequence.',
                      'expected_observation': expected_observation or expected or 'Observe the resulting game frame and runtime trace.',
                      'watch': '', 'op': 'eq', 'value': 0, 'target_watch': ''})
        elapsed += duration

    if direct_title_start:
        chart_zero = elapsed
        add('input', 100, 'Enter', 'Start using the delivered title keyboard handler.',
            'Observe actual play start; no cinematic is assumed.')
    else:
        add('input', 100, 'Enter', 'Start the title flow.', 'C01 opening cinematic becomes visible.')
        add('input', 100, 'Enter', 'Skip the opening cinematic using its documented key.',
            'Gameplay begins at chart time zero.')
        chart_zero = 1800 + 200
    # Normalize the authored chart's field names while preserving its actual
    # event times, lanes, holds and simultaneous notes.
    events_by_time = {}
    for note in notes:
        if not isinstance(note, dict):
            raise ValueError('delivered G057 chart contains a non-object note')
        time_ms = note.get('t', note.get('time_ms'))
        lane = note.get('lane')
        if type(time_ms) is not int or type(lane) is not int or lane < 0 or lane >= len(lane_keys):
            raise ValueError(f'delivered G057 chart note has invalid time/lane: {note}')
        duration_ms = note.get('dur', note.get('duration_ms', 0))
        if type(duration_ms) is not int or duration_ms < 0:
            raise ValueError(f'delivered G057 chart note has invalid duration: {note}')
        events_by_time.setdefault(time_ms, []).append({'time_ms': time_ms, 'lane': lane,
                                                        'duration_ms': duration_ms})
    events = [{'time_ms': time_ms, 'notes': sorted(rows, key=lambda row: row['lane'])}
              for time_ms, rows in sorted(events_by_time.items())]
    started_c02_skip = False
    for event in events:
        if not direct_title_start and event['time_ms'] >= 70000 and not started_c02_skip:
            target = 1800 + 200 + 70000
            wait = target - elapsed
            if wait < 0:
                raise ValueError('G057 plan timing overran the finale transition')
            if wait:
                add('wait', wait, purpose='Reach the documented C02 transition.',
                    expected_observation='Observe the finale cinematic before skipping it.')
            add('input', 100, 'Escape', 'Skip C02, which documents Escape as its skip key.',
                'Finale gameplay resumes without pausing the chart.')
            started_c02_skip = True

        target = chart_zero + event['time_ms']
        wait = target - elapsed
        if wait < 0:
            raise ValueError('G057 generated input sequence cannot meet chart timing')
        if wait:
            # Keep every wait within the native step ceiling; chart gaps are short.
            add('wait', wait, purpose=f'Wait for chart time {event["time_ms"]} ms.',
                expected='The next delivered note reaches the judgment line.')
        keys = '+'.join(re.sub(r'^Key', '', lane_keys[note['lane']]) for note in event['notes'])
        duration = max(100, max(note['duration_ms'] for note in event['notes']))
        kinds = {note['duration_ms'] for note in event['notes']}
        description = ' and '.join('hold' if note['duration_ms'] else 'tap' for note in event['notes'])
        add('input', duration, keys, f'Play {description} at chart time {event["time_ms"]} ms.',
            f'Observe judgment and lane feedback for chart time {event["time_ms"]} ms; input delivery alone is not a hit verdict.')

    settle_to = chart_zero + 115000
    remaining = settle_to - elapsed
    while remaining:
        duration = min(6000, remaining)
        add('wait', duration, purpose='Observe natural chart completion and result settlement.',
            expected='Capture the natural result screen and final HUD if reached.')
        remaining -= duration
    if len(steps) > 512:
        raise ValueError(f'G057 full chart needs {len(steps)} steps; native limit is 512')
    return steps


def complete_g057_plan(plan: dict, project) -> dict:
    """Replace only the model's sampled actions with a source-derived full chart."""
    result = copy.deepcopy(plan)
    if not result.get('probes'):
        raise ValueError('G057 model plan must provide a probe and frozen criterion IDs')
    criterion_ids = sorted({ident for probe in result['probes'] for ident in probe['criterion_ids']})
    if not criterion_ids:
        raise ValueError('G057 model plan has no declared criterion IDs')
    probe = copy.deepcopy(result['probes'][0])
    probe.update(id='g057-complete-delivered-chart', criterion_ids=criterion_ids,
                 preconditions=[], steps=build_g057_complete_steps(project))
    result['probes'] = [probe]
    return result


def validate_g057_chart_plan(plan: dict, gameplay_budget_ms: int = 300000, project=None) -> None:
    """Require the complete source-derived chart and natural settlement window."""
    if plan['max_duration_ms'] != gameplay_budget_ms:
        raise ValueError('G057 plan must use the full preregistered gameplay budget')
    if len(plan['probes']) != 1:
        raise ValueError('G057 complete chart must be one sequential probe')
    actual = plan['probes'][0]['steps']
    if project is None:
        raise ValueError('G057 chart validation requires the selected delivered project')
    expected = build_g057_complete_steps(project)
    if actual != expected:
        raise ValueError('G057 operation sequence does not exactly cover the delivered chart and settlement window')
    if sum(max(row['duration_ms'], 100) if row['kind'] == 'input' else row['duration_ms']
           for row in actual) + 2500 > gameplay_budget_ms:
        raise ValueError('G057 complete operation sequence exceeds preregistered gameplay budget')





def enabled(protocol):
    """Only explicitly versioned historical protocols can request chart replay."""
    return protocol.get('legacy_replay') is True or protocol.get('version') in {
        'whitebox-eightcol-sol-pilot.v1', 'whitebox-eightcol-batch-expanded.v3',
        'whitebox-eightcol-batch-expanded.v4'}
