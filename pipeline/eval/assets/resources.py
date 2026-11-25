"""Fail-closed CPU/API coexistence policy; never signal another process.

macOS nice/thread limits are not resource isolation. While an uncoordinated
whitebox batch (or one of its orphaned sol invocations) is alive, this module
refuses to start rendering, model imports, inference, or geometry computation.
"""
from __future__ import annotations
import os
from pathlib import Path
import shlex
import subprocess


class MetricsDeferred(RuntimeError):
    pass


def process_snapshot():
    result = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True, text=True, check=True)
    batches = []; sol = []
    for line in result.stdout.splitlines():
        try:
            pid, ppid, command = line.strip().split(None, 2)
            args = shlex.split(command)
        except ValueError:
            continue
        if 'pipeline.eval.whitebox.batch' in args or any(a.endswith('/whitebox_eval/batch.py') for a in args):
            batches.append({'pid': int(pid), 'ppid': int(ppid)})
        if ('exec' in args and '--model' in args and 'gpt-6.1-sol' in args
                and any('codex' in Path(a).name for a in args[:2])):
            # Do not persist command lines containing unrelated user prompts.
            sol.append({'pid': int(pid), 'ppid': int(ppid)})
    sol_pids = {x['pid'] for x in sol}
    return {'whitebox_batch': batches, 'sol': [x for x in sol if x['ppid'] not in sol_pids]}


def assert_metrics_idle():
    try:
        state = process_snapshot()
    except (OSError, subprocess.SubprocessError) as e:
        raise MetricsDeferred(f'process inspection unavailable; fail closed: {e}') from e
    if state['whitebox_batch'] or state['sol']:
        raise MetricsDeferred('whitebox batch / sol still active; no rendering, model loading, or metric CPU work started; snapshot=' + repr(state))
    return state


def low_priority():
    # Defense-in-depth only, NOT a claim of zero resource interference.
    os.nice(19)
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS',
                'RAYON_NUM_THREADS'):
        os.environ[key] = '1'
    os.environ['TOKENIZERS_PARALLELISM'] = 'false'
    return {'nice': os.getpriority(os.PRIO_PROCESS, 0),
            'threads': 1, 'heavy_work_policy': 'defer all heavy work while whitebox batch or sol is alive',
            'warning': 'Priority limits are not isolation; preflight is bounded, lightweight stdlib work only.'}
