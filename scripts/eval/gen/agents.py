"""Thin per-CLI agent adapters: start a session, resume the same session.

Every adapter runs the CLI in ``cwd`` (resume is cwd-scoped for codex and
kimi), streams its JSON events to ``<log_dir>/events.jsonl`` (stderr to
``stderr.log``), enforces the round timeout by killing the process group, and
returns the session id it observed. No retries and no model substitution: a
failed round is recorded and still counts toward the job's round budget.

Configured per model in ``scripts_new/config/models.json``::

    "cli": "codex" | "claude" | "zcode" | "kimi", "model": "<model id or alias>",
    "executable": optional path, "notes": [files appended to the round-1 prompt],
    "env": {extra environment}
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .paths import BENCH, models


@dataclass
class Result:
    session_id: str | None
    exit_code: int | None
    timed_out: bool
    completed: bool
    error: str = ''


def _events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(errors='replace').splitlines() if path.is_file() else []:
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


class Agent:
    """Base: subclasses define ``command(prompt, session)`` and ``parse(events)``."""
    stdin_prompt = False

    def __init__(self, model: str, executable: str | None = None, notes=(), env=None):
        self.model, self.executable = model, executable or self.default_executable()
        self.notes = [Path(BENCH / n).read_text(encoding='utf-8') for n in notes]
        self.env = dict(env or {})

    def default_executable(self) -> str:
        raise NotImplementedError

    def start(self, prompt, *, cwd, log_dir, timeout, env) -> Result:
        full = prompt + ''.join('\n\n' + n for n in self.notes)
        return self._run(full, None, cwd, log_dir, timeout, env)

    def resume(self, session_id, prompt, *, cwd, log_dir, timeout, env) -> Result:
        return self._run(prompt, session_id, cwd, log_dir, timeout, env)

    def _run(self, prompt, session, cwd, log_dir, timeout, env) -> Result:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        cmd = self.command(prompt, session, Path(cwd))
        (log_dir / 'command.json').write_text(json.dumps(
            [c if c != prompt else '<prompt.txt>' for c in cmd], ensure_ascii=False, indent=1))
        started, timed_out = time.monotonic(), False
        with (log_dir / 'events.jsonl').open('w') as out, (log_dir / 'stderr.log').open('w') as err:
            proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if self.stdin_prompt else subprocess.DEVNULL,
                                    stdout=out, stderr=err, text=True, start_new_session=True,
                                    env={**os.environ, **self.env, **env})
            try:
                proc.communicate(prompt if self.stdin_prompt else None, timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
        session_id, completed, error = self.parse(_events(log_dir / 'events.jsonl'), Path(cwd), started)
        result = Result(session_id or session, proc.returncode, timed_out, completed and not timed_out, error)
        (log_dir / 'result.json').write_text(json.dumps(result.__dict__ | {
            'seconds': round(time.monotonic() - started, 1)}, ensure_ascii=False, indent=1))
        return result


class Codex(Agent):
    stdin_prompt = True

    def default_executable(self):
        return shutil.which('codex') or 'codex'

    def command(self, prompt, session, cwd):
        base = [self.executable, 'exec'] + (['resume'] if session else [])
        base += ['--json', '-m', self.model, '--dangerously-bypass-approvals-and-sandbox', '--skip-git-repo-check']
        if not session:
            base += ['--cd', str(cwd), '--add-dir', str(BENCH)]
        return base + ([session] if session else []) + ['-']

    def parse(self, events, cwd, started):
        sid = next((e.get('thread_id') for e in events if e.get('type') == 'thread.started'), None)
        failed = [e for e in events if e.get('type') in ('turn.failed', 'error')]
        done = any(e.get('type') == 'turn.completed' for e in events) and not failed
        return sid, done, json.dumps(failed[-1], ensure_ascii=False)[:500] if failed else ''


class Claude(Agent):
    def default_executable(self):
        return shutil.which('claude') or str(Path.home() / '.local/bin/claude')

    def command(self, prompt, session, cwd):
        cmd = [self.executable, '-p', prompt, '--output-format', 'stream-json', '--verbose',
               '--dangerously-skip-permissions', '--model', self.model,
               '--settings', json.dumps({'sandbox': {'enabled': False}}), '--add-dir', str(BENCH)]
        return cmd + (['--resume', session] if session else [])

    def parse(self, events, cwd, started):
        top = [e for e in events if not e.get('parent_tool_use_id')]
        sid = next((e.get('session_id') for e in top if e.get('type') == 'system' and e.get('subtype') == 'init'), None)
        result = next((e for e in reversed(top) if e.get('type') == 'result'), None)
        sid = (result or {}).get('session_id') or sid
        ok = bool(result) and not result.get('is_error') and not str(result.get('subtype', '')).startswith('error') \
            and not result.get('permission_denials')
        return sid, ok, '' if ok else json.dumps(result or {'error': 'no result event'}, ensure_ascii=False)[:500]


class ZCode(Agent):
    def default_executable(self):
        configured = os.environ.get('A3GAME_ZCODE_BINARY')
        candidate = configured or shutil.which('zcode')
        if candidate:
            path = Path(candidate).expanduser()
            if path.is_file() and (path.suffix == '.cjs' or os.access(path, os.X_OK)):
                return str(path.resolve())
        raise FileNotFoundError('ZCode CLI not found. Install zcode on PATH or set '
                                'A3GAME_ZCODE_BINARY to its executable or .cjs entrypoint.')

    def command(self, prompt, session, cwd):
        exe = ['node', self.executable] if self.executable.endswith('.cjs') else [self.executable]
        cmd = exe + ['--cwd', str(cwd), '--mode', 'yolo', '--no-color', '--output-format', 'stream-json']
        return cmd + (['--resume', session] if session else []) + ['--prompt', prompt]

    def parse(self, events, cwd, started):
        sid = next((e.get('sessionId') for e in events if e.get('sessionId')), None)
        done = any(e.get('type') == 'turn.completed' and (e.get('projection') or {}).get('status') == 'idle'
                   for e in events)
        return sid, done, '' if done else 'no idle turn.completed event'


class Kimi(Agent):
    def default_executable(self):
        return shutil.which('kimi') or 'kimi'

    def command(self, prompt, session, cwd):
        cmd = [self.executable, '--model', self.model, '--output-format', 'stream-json', '--add-dir', str(BENCH)]
        return cmd + (['--session', session] if session else []) + ['--prompt', prompt]

    def parse(self, events, cwd, started):
        sid = next((e.get('session_id') for e in events if e.get('type') == 'session.resume_hint'), None)
        if not sid:       # hint is missing on failure / timeout: fall back to the session index for this cwd
            home = Path(self.env.get('KIMI_CODE_HOME') or os.environ.get('KIMI_CODE_HOME') or Path.home() / '.kimi-code')
            index = home / 'session_index.jsonl'
            rows = [r for r in _events(index) if Path(r.get('workDir', '')).resolve() == cwd.resolve()]
            sid = rows[-1].get('sessionId') if rows else None
        return sid, any(e.get('type') == 'session.resume_hint' for e in events), ''


CLIS = {'codex': Codex, 'claude': Claude, 'zcode': ZCode, 'kimi': Kimi}


def for_model(model: str) -> tuple[Agent, dict]:
    cfg = models()[model]
    cls = CLIS[cfg['cli']]
    return cls(cfg['model'], cfg.get('executable'), cfg.get('notes', ()), cfg.get('env')), {}
