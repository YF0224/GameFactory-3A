"""Drive one job's agent session for up to ``job.max_rounds`` rounds.

Round 1 sends the full task prompt and records the session id. Every later
round resumes that same session with a short follow-up. A round that was
started counts toward the budget even if it timed out or was interrupted;
re-running the scheduler continues with the next round of the same session.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .jobs import Job, check_disk, locked, now


def run(job: Job, agent, *, first_prompt: Callable[[], str], next_prompt: Callable[[int], str],
        finished: Callable[[int], bool], cwd: Path, env: dict, round_timeout: int,
        on_done: Callable[[], None] | None = None, dry_run: bool = False) -> Job:
    with locked(job):
        if job.status in ('done', 'failed'):
            return job
        if job.rounds and 'ended_at' not in job.rounds[-1]:
            job.rounds[-1].update(ended_at=None, interrupted=True)      # still counts
        if job.rounds and not job.session_id:
            job.status = 'failed'
            job.notes['error'] = 'round 1 was interrupted before a session id was recorded; cannot resume'
            job.save()
            return job
        job.status = 'running'
        job.save()
        for n in range(len(job.rounds) + 1, job.max_rounds + 1):
            check_disk(job.root)
            prompt = first_prompt() if n == 1 else next_prompt(n)
            folder = job.round_dir(n)
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
            if dry_run:
                job.status = 'prepared'
                job.save()
                return job
            record = {'round': n, 'started_at': now(), 'prompt': str(folder / 'prompt.txt')}
            job.rounds.append(record)
            job.save()
            if n == 1:
                result = agent.start(prompt, cwd=cwd, log_dir=folder, timeout=round_timeout, env=env)
            else:
                result = agent.resume(job.session_id, prompt, cwd=cwd, log_dir=folder,
                                      timeout=round_timeout, env=env)
            record.update(ended_at=now(), exit_code=result.exit_code, timed_out=result.timed_out,
                          session_id=result.session_id, error=result.error)
            if n == 1:
                job.session_id = result.session_id
            elif result.session_id and result.session_id != job.session_id:
                job.status = 'failed'
                job.notes['error'] = f'round {n} ran in session {result.session_id}, not {job.session_id}'
                job.save()
                return job
            job.save()
            if not job.session_id:
                job.status = 'failed'
                job.notes['error'] = f'no session id after round 1: {result.error or "see agent log"}'
                job.save()
                return job
            if finished(n):
                break
        if on_done:
            on_done()
        job.status = 'done'
        job.save()
        return job
