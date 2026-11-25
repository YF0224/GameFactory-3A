"""Duty-cycle only a newly created, owned worker group; never signal existing jobs.

This is a limited local-algorithm smoke harness, not hard resource isolation.
The normal full-metrics whitebox gate remains unchanged.
"""
from __future__ import annotations
import os
import resource
from pathlib import Path
import signal
import subprocess
import sys
import time

from .common import dump


def _seconds(value):
    day, value = value.split('-', 1) if '-' in value else ('0', value)
    parts = value.split(':')
    return int(day) * 86400 + sum(float(x) * 60 ** i for i, x in enumerate(reversed(parts)))


def _usage(group):
    result = subprocess.run(['ps', '-axo', 'pgid=,rss=,time='], capture_output=True, text=True, check=True)
    rows = [line.split() for line in result.stdout.splitlines()]
    rows = [r for r in rows if len(r) == 3 and r[0] == str(group)]
    return sum(int(r[1]) for r in rows), sum(_seconds(r[2]) for r in rows), len(rows)


def run_bounded(module, args, folder, *, cpu_fraction=.05, cpu_budget=20, wall_budget=600, rss_limit_mb=1000):
    """5% of one core average target; brief bursts remain possible. Logs actual use.

    Child self-stops before numerical imports. Every later signal targets only its
    freshly created session/process group. No shared whitebox process is touched.
    Children with their own process groups are not supported by this harness.
    """
    if not 0 < cpu_fraction <= .05:
        raise ValueError('Local smoke target must be <=5% of one CPU core')
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                'VECLIB_MAXIMUM_THREADS', 'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS', 'RAYON_NUM_THREADS'):
        env[key] = '1'
    env.update(PYTHONDONTWRITEBYTECODE='1', ASSET_EVAL_BOUNDED_CHILD='1')
    own_start_cpu = time.process_time()
    child_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    start = time.monotonic(); reason = None; peak_rss = 0; measured_cpu = 0.; duty = .003
    with (folder / 'worker.log').open('w') as log:
        proc = subprocess.Popen([sys.executable, '-B', '-m', module, *map(str, args)],
                                stdout=log, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        group = proc.pid
        # start_new_session guarantees a distinct group, never the caller's.
        if group == os.getpgrp():
            raise RuntimeError('Refusing to signal caller process group')
        def send(sig):
            try:
                os.killpg(group, sig)
            except ProcessLookupError:
                pass
            except PermissionError:
                # Darwin may report EPERM for an exited/zombie empty group.
                # Reap leader and confirm there is no live owned group; do NOT
                # ignore permission failures on active work.
                if proc.poll() is None or _usage(group)[2]:
                    raise
        try:
            # Child announces self-stop through waitpid: avoid a CONT-before-STOP race.
            _, status = os.waitpid(proc.pid, os.WUNTRACED)
            if not os.WIFSTOPPED(status):
                proc.returncode = os.waitstatus_to_exitcode(status)
                reason = 'worker exited before self-stop'
            else:
                last_sample = start
                while proc.poll() is None:
                    elapsed = time.monotonic() - start
                    if elapsed > wall_budget:
                        reason = 'wall budget exceeded'; break
                    if time.monotonic() - last_sample >= 1:
                        rss, cpu, count = _usage(group)
                        peak_rss = max(peak_rss, rss); measured_cpu = max(measured_cpu, cpu)
                        last_sample = time.monotonic()
                        if rss > rss_limit_mb * 1024:
                            reason = 'own worker RSS budget exceeded'; break
                        if cpu > cpu_budget:
                            reason = 'own worker CPU budget exceeded'; break
                        # Repaid startup/burst debt before allowing further work.
                        if cpu > cpu_fraction * elapsed:
                            time.sleep(min(1., cpu / cpu_fraction - elapsed)); continue
                    send(signal.SIGCONT); time.sleep(duty); send(signal.SIGSTOP)
                    time.sleep(.197)
        finally:
            # Take a final snapshot even if the leader exited before the next tick.
            rss, cpu, _ = _usage(group)
            peak_rss = max(peak_rss, rss); measured_cpu = max(measured_cpu, cpu)
            # Kill only owned unfinished work, including its renderer children.
            send(signal.SIGTERM); send(signal.SIGCONT)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                send(signal.SIGKILL); proc.wait()
    elapsed = time.monotonic() - start
    child_end = resource.getrusage(resource.RUSAGE_CHILDREN)
    child_cpu = child_end.ru_utime + child_end.ru_stime - child_start.ru_utime - child_start.ru_stime
    result = {'supervisor_cpu_seconds': time.process_time() - own_start_cpu,
              'reaped_children_and_monitor_cpu_seconds': child_cpu,
              'reaped_children_and_monitor_average_core_fraction': child_cpu / elapsed,
              'returncode': proc.returncode, 'failure_reason': reason,
              'wall_seconds': elapsed, 'sampled_worker_cpu_seconds': measured_cpu,
              'sampled_peak_worker_rss_mb': peak_rss / 1024,
              'average_cpu_core_fraction': measured_cpu / elapsed,
              'target_cpu_core_fraction': cpu_fraction, 'cpu_budget_seconds': cpu_budget,
              'threads_per_numeric_library': 1, 'own_process_group': group,
              'api_calls': 0, 'warning': 'Duty cycling is not hard isolation or a zero-interference guarantee; sampling can miss short-lived children.'}
    dump(folder / 'resources.json', result)
    return result
