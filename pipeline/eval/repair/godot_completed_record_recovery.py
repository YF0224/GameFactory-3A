"""Finish a dense Godot take after its recorder completed but the host stopped.

Native files stay untouched. Completion, frozen inputs, plan execution, image
integrity and current process absence are required; sampling gaps stay visible.
No engine or model is launched by recovery.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

from pipeline.eval.whitebox.core.paths import FRAMEWORK, read_json, sha256, write_json
from pipeline.eval.whitebox.core.llm import HarnessError

VERSION = 'stage1-godot-completed-record-recovery.v1'


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _process_audit(project, native):
    scan = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='],
                          capture_output=True, text=True, check=True)
    # Match the unique working project / output, never signal any process.
    matches = [line.strip() for line in scan.stdout.splitlines()
               if str(project) in line or str(native) in line]
    _require(not matches, 'a process still references this Godot take: ' + str(matches))
    return {'checked_at': datetime.now(timezone.utc).isoformat(),
            'command': ['ps', '-axo', 'pid=,ppid=,command='],
            'project': str(project), 'native': str(native), 'matching_processes': matches,
            'process_cleanup': True, 'view_cleanup': True,
            'basis': 'current process absence; original exit code and process group are unknown',
            'original_exit_code': None}


def recover(out: Path, manifest: dict, plan: dict, take: int):
    """Called with the take's postprocessing lock held by record.record."""
    from PIL import Image
    from pipeline.eval.whitebox.core import prepare
    from pipeline.eval.whitebox.record import record

    out = Path(out).resolve()
    runtime = out / 'takes' / str(take) / 'record'
    native = runtime / 'native'
    project = out / 'runtime/project'
    lineage = out / 'recovery/godot_completed_record_v1' / f'take_{take}'
    try:
        _require(manifest['engine'] == 'godot', 'not a Godot take')
        frozen = prepare.verify(out)
        _require({k: v for k, v in frozen.items() if k != 'budget'} ==
                 {k: v for k, v in manifest.items() if k != 'budget'}, 'manifest identity changed')
        _require(plan == read_json(runtime.parent / 'plan.json'), 'plan changed')
        source = prepare.tree_hashes(out / 'input/project')
        _require(all((project / rel).is_file() and sha256(project / rel) == digest
                     for rel, digest in source.items()), 'runtime source changed')
        budget = manifest['budget']['recording_ms']
        _require(read_json(runtime / 'recording_plan.json') == {**plan, 'recording_ms': budget},
                 'not the saved dense observation plan')
        _require(read_json(runtime / 'capture_mode.json')['mode'] == 'dense', 'not dense capture')
        _require(not (native / 'harness_error.json').exists(), 'native recorder reported failure')
        _require(not (runtime / 'record_error.json').exists() and
                 not (runtime / 'adapter_result.json').exists(), 'a different host failure needs inspection')
        launch = read_json(native / 'launch_diagnostics.json')
        _require(Path(launch['project_root']).resolve() == project and launch['classification'] == 'LAUNCHABLE',
                 'launch belongs to another project or failed')
        report = read_json(native / 'execution.json')
        _require(report['complete'] is True and report['status'] == 'CAPTURED' and
                 report['no_state_injection'] is True and report['clock'] == 'session_monotonic' and
                 not report['capture_errors'] and report['duration_ms'] >= budget,
                 'recorder did not complete the observation window')
        expected = [(p['id'], s['id'], s['kind']) for p in plan['probes'] for s in p['steps']]
        _require(all(kind in {'input', 'wait', 'wait_until'} for _, _, kind in expected),
                 'this recovery supports keyboard/wait plans only')
        actual = [(p['id'], s['id'], s['kind']) for p in report['probes'] for s in p['steps']]
        _require(expected == actual and all(p['status'] == 'EXECUTED' and p['preconditions_met'] is True
                                           for p in report['probes']), 'plan execution incomplete')
        _require(all(s.get('sent', True) is True for p in report['probes'] for s in p['steps']),
                 'input delivery failed')
        actions = _rows(native / 'actions.jsonl')
        _require(all(a.get('sent', True) is True for a in actions), 'native input delivery failed')
        for phase in ('start', 'end'):
            observed = [(a['probe_id'], a['step_id']) for a in actions
                        if a.get('kind') == 'observation' and a.get('phase') == phase]
            _require(observed == [(p, s) for p, s, _ in expected], 'action trace differs from plan')
        expected_inputs = [(p['id'] + '/' + s['id'], s['key'])
                           for p in plan['probes'] for s in p['steps'] if s['kind'] == 'input']
        _require([(a.get('action_id'), a.get('key')) for a in actions if a.get('kind') == 'press']
                 == expected_inputs, 'native keyboard inputs differ from plan')
        states = _rows(native / 'state_trace.jsonl')
        frames = _rows(native / 'frame_index.jsonl')
        _require(len(states) == report['states'] and states[-1]['t_ms'] >= budget and
                 len(frames) == report['frames'] and len(frames) >= 2,
                 'trace/frame counts or final state disagree with recorder')
        _require([r['t_ms'] for r in frames] == sorted(r['t_ms'] for r in frames),
                 'frame clock is not monotonic')
        for row in frames:
            path = (native / row['path']).resolve()
            _require(path.is_relative_to((native / 'frames').resolve()) and path.is_file(),
                     'missing frame or frame path escapes native directory')
            with Image.open(path) as image:
                _require(image.size == (row['viewport']['width'], row['viewport']['height']),
                         'frame dimensions disagree with native index')
                image.verify()
        marker = f"PILOT_COMPLETE frames={len(frames)} states={len(states)}"
        _require(marker in (native / 'engine.log').read_text(), 'missing recorder completion marker')
        inputs = read_json(native / 'input_view_cleanup.json')
        _require(inputs['input_cleanup'] is True and inputs['held_keys_after_release'] == 0 and
                 inputs['capture_callback_disconnected'] is True and inputs['process_exit_requested'] is True,
                 'native input/capture cleanup incomplete')
        native_hashes = prepare.tree_hashes(native)
        parent = {'manifest': sha256(out / 'manifest.json'),
                  'plan': sha256(runtime.parent / 'plan.json'), 'native_files': native_hashes}
        # Serialize against native engine launches while auditing process absence.
        with record.gui_slot() as slot:
            host = _process_audit(project, native)
            receipt_path = lineage / 'receipt.json'
            if receipt_path.exists():
                _require(read_json(receipt_path)['parent'] == parent, 'recovery parent drift')
            else:
                write_json(lineage / 'parent_status.json', read_json(out / 'status.json'))
                producer = {}
                for root in [FRAMEWORK / 'pipeline/eval/stage1', FRAMEWORK / 'engine_adapters/godot']:
                    for path in sorted(root.rglob('*')):
                        if path.is_file() and path.suffix in {'.py', '.gd'}:
                            producer[str(path.relative_to(FRAMEWORK))] = sha256(path)
                producer[str(Path(__file__).relative_to(FRAMEWORK))] = sha256(Path(__file__))
                write_json(receipt_path, {'version': VERSION, 'parent': parent, 'producer': producer,
                    'host_audit': host, 're_recorded': False, 'native_modified': False,
                    'first_frame_ms': frames[0]['t_ms'], 'last_frame_ms': frames[-1]['t_ms'],
                    'observation_duration_ms': report['duration_ms'],
                    'unobserved_tail_ms': max(0, budget - frames[-1]['t_ms']),
                    'note': 'Missing screenshots remain missing; original host exit code is unknown.'})
            # Canonical files may only be absent or exact copies on a recovery retry.
            for name in record.CHANNELS + record.EXTRA_FILES:
                dest, src = runtime / name, native / name
                if dest.exists():
                    _require((src.is_file() and sha256(dest) == sha256(src)) or
                             (not src.exists() and dest.stat().st_size == 0), 'canonical conflict: ' + name)
            for dest in (runtime / 'frames').glob('*'):
                _require(dest.is_file() and (native / 'frames' / dest.name).is_file() and
                         sha256(dest) == sha256(native / 'frames' / dest.name), 'canonical frame conflict')
            summary = record._collect(runtime, native)
            _require(not summary['failed_actions'], 'canonical input delivery failed')
            write_json(runtime / 'host_process_cleanup.json', host)
            summary['cleanup']['host_process_cleanup.json'] = host
            summary.update(version=record.VERSION, engine='godot', take=take,
                           elapsed_ms=None, gui_slot=str(slot),
                           plan_sha256=sha256(runtime.parent / 'plan.json'),
                           recorder=str(FRAMEWORK / 'engine_adapters/godot'),
                           recovery={'version': VERSION, 'receipt': str(receipt_path),
                                     're_recorded': False},
                           capture_observation={'last_frame_ms': frames[-1]['t_ms'],
                                                'duration_ms': report['duration_ms']})
            _require(prepare.tree_hashes(native) == native_hashes, 'native evidence changed during recovery')
            write_json(runtime / 'record_result.json', summary)
            return summary
    except (ValueError, KeyError, OSError, RuntimeError, subprocess.SubprocessError) as exc:
        raise HarnessError(f'Godot completed-take recovery refused: {exc}; preserve {native}') from exc
