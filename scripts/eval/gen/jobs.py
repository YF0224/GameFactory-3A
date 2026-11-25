"""One generation job = one (stage, model, game) = one agent session.

State lives in ``<run_root>/.generation/job.json``:

    {stage, model, game_id, run_id, run_root, session_id, status,
     rounds: [{round, started_at, ended_at, exit_code, timed_out, session_id, prompt}]}

A job holds an exclusive file lock while it runs, so two schedulers can never
drive the same session. The session id is recorded after round 1 and every
later round resumes exactly that session — never a silent replacement.
Interrupted / timed-out rounds still count toward the round budget.
"""
from __future__ import annotations

import fcntl
import json
import shutil
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

DISK_RESERVE = 8 * 1024 ** 3


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    stage: str
    model: str
    game_id: str
    run_id: str
    run_root: str
    max_rounds: int
    session_id: str | None = None
    status: str = 'pending'            # pending | running | done | failed | stopped
    rounds: list = field(default_factory=list)
    notes: dict = field(default_factory=dict)

    @property
    def root(self) -> Path:
        return Path(self.run_root)

    @property
    def control(self) -> Path:
        return self.root / '.generation'

    def save(self) -> None:
        self.control.mkdir(parents=True, exist_ok=True)
        tmp = self.control / 'job.json.tmp'
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        tmp.replace(self.control / 'job.json')

    @classmethod
    def load(cls, run_root: Path) -> 'Job | None':
        path = Path(run_root) / '.generation' / 'job.json'
        return cls(**json.loads(path.read_text(encoding='utf-8'))) if path.is_file() else None

    def round_dir(self, n: int) -> Path:
        return self.control / 'rounds' / f'round_{n:03d}'


@contextmanager
def locked(job: Job):
    job.control.mkdir(parents=True, exist_ok=True)
    with (job.control / '.lock').open('a') as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(f'{job.stage}/{job.model}/{job.game_id} is already running elsewhere')
        yield


def check_disk(path: Path, reserve: int = DISK_RESERVE) -> int:
    free = shutil.disk_usage(path).free
    if free < reserve:
        raise RuntimeError(f'only {free / 1024**3:.1f} GiB free; need {reserve / 1024**3:.0f} GiB reserve')
    return free
