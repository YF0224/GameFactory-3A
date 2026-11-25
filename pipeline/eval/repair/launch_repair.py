"""Automatic launch repair for Stage3 recordings (opt-in: A3GAME_LAUNCH_REPAIR=1).

When a take fails before the game can be recorded because the delivered project does not build / import /
start (UE build errors, Unity compiler errors, missing modules or plugins, engine-version API changes), Sol
(the configured launch-repair model through the Codex CLI, write access limited to ``runtime/project``) gets the failure, the log
paths and the skill ``agent_skills/eval/stage3-launch-repair/SKILL.md``, and may change **only** environment
configuration and behaviour-preserving compile compatibility in the eval copy. Then:

  * the change set is measured against a snapshot (every file under runtime/project, caches excluded);
    deleted author files, changed scene / asset files, changes to injected adapter files or outside the
    allowed kinds are rejected mechanically;
  * a second, read-only Sol call reviews the unified diff hunk by hunk and rejects any behaviour change;
  * a rejected repair is rolled back completely (backup of every touched file);
  * an accepted repair is kept as an overlay (re-applied whenever the runtime copy is rebuilt from the
    frozen input snapshot) and listed in score.json['launch_repairs'].

Evaluation-tool failures (capture slots, input delivery, locks, plan / budget errors) are never sent to Sol.
The original delivery and the frozen input snapshot are never touched.
"""
from __future__ import annotations

from ..model_config import LAUNCH_REPAIR_MODEL

import difflib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import time
from pathlib import Path

from ..stage1.llm import HarnessError, call_model
from ..stage1.paths import read_json, write_json

ENABLED = os.environ.get('A3GAME_LAUNCH_REPAIR') == '1'
MAX_REPAIRS = int(os.environ.get('A3GAME_LAUNCH_REPAIRS', '2'))
MODEL = LAUNCH_REPAIR_MODEL
TIMEOUT_S = int(os.environ.get('A3GAME_LAUNCH_REPAIR_TIMEOUT_S', '1500'))
SKILL = Path(__file__).resolve().parents[3] / 'agent_skills' / 'eval' / 'stage3-launch-repair' / 'SKILL.md'

CACHE_DIRS = {'.git', '.godot', '.import', 'Library', 'Temp', 'obj', 'Logs', 'node_modules', 'dist',
              'Intermediate', 'Saved', 'DerivedDataCache', 'Binaries', '__pycache__', 'Build', 'Builds', 'UserSettings'}
CONFIG_SUFFIXES = {'.uproject', '.uplugin', '.ini', '.asmdef', '.asmref', '.rsp'}
CONFIG_NAMES = {'manifest.json', 'packages-lock.json'}
CODE_SUFFIXES = {'.cs', '.cpp', '.h', '.hpp', '.inl', '.c', '.cc'}
# files injected by the evaluator (recorder / input driver / audio observer): never the subject of a repair
INJECTED_MARKERS = ('A3GamePlayable', 'GameFactory3A', 'gamefactory3a', 'GameFactoryInput')

# failure text of the evaluation tool itself: not a project launch problem
TOOL_FAILURES = ('missed its predeclared capture slot', 'GUI recording slot', 'unfinished take',
                 'did not deliver actions', 'plan needs', 'recording budget', 'capture slots missing',
                 'already active for this take', 'model call', 'took no frames', 'produced no frames',
                 'adapter recorder file collides', 'native receipt', 'pointer', 'Unity metadata')
LAUNCH_FAILURES = ('UE native admission failed', 'Unity compile errors', 'Unity import failed',
                   'Unity import timed out', 'compile', 'build', 'Build', 'startup', 'readiness', 'not ready',
                   'scene', 'map', 'launch', 'module', 'plugin', 'did not start', 'exited')

RESULT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['status', 'root_cause', 'changes', 'not_fixed'],
    'properties': {
        'status': {'type': 'string', 'enum': ['repaired', 'not_repairable']},
        'root_cause': {'type': 'string'},
        'changes': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['file', 'kind', 'why_no_behaviour_change'],
            'properties': {'file': {'type': 'string'},
                           'kind': {'type': 'string', 'enum': ['config', 'compile_compat', 'new_stub']},
                           'why_no_behaviour_change': {'type': 'string'}}}},
        'not_fixed': {'type': 'string'}}}

REVIEW_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['verdict', 'hunks', 'summary'],
    'properties': {
        'verdict': {'type': 'string', 'enum': ['accept', 'reject']},
        'summary': {'type': 'string'},
        'hunks': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['file', 'category', 'changes_game_behaviour', 'reason'],
            'properties': {'file': {'type': 'string'},
                           'category': {'type': 'string', 'enum': ['config', 'compile_compat', 'new_stub', 'gameplay', 'removed_code', 'other']},
                           'changes_game_behaviour': {'type': 'boolean'},
                           'reason': {'type': 'string'}}}}}}

REVIEW_PROMPT = """You review a change made to the evaluation copy of a delivered game so that it builds / starts.
Rules (the same rules the repairing agent got) are below. Judge EVERY hunk of the unified diff:
category = config | compile_compat | new_stub | gameplay | removed_code | other, and whether it can change
what the game does for the same player input (gameplay, rules, numbers, win/lose, input mapping, AI, level flow,
UI text or behaviour, removed / commented-out / emptied author code, swallowed errors).
verdict = "accept" only if no hunk changes game behaviour and every hunk is config, compile_compat or new_stub.
When in doubt, reject.

RULES:
{skill}

FAILURE THE CHANGE WAS MEANT TO FIX:
{failure}

UNIFIED DIFF (eval copy, before -> after):
{diff}
"""


def repairable(message: str) -> bool:
    """Project launch problem (build / import / compile / start), not a failure of the evaluation tool."""
    if not ENABLED:
        return False
    if any(t in message for t in TOOL_FAILURES):
        return False
    return any(t in message for t in LAUNCH_FAILURES)


def _files(project: Path) -> dict[str, str]:
    result = {}
    for root, dirs, names in os.walk(project):
        dirs[:] = [d for d in dirs if d not in CACHE_DIRS]
        for n in names:
            p = Path(root) / n
            if p.is_file() and not p.is_symlink():
                h = hashlib.sha256()
                with p.open('rb') as f:
                    for chunk in iter(lambda: f.read(1 << 20), b''):
                        h.update(chunk)
                result[p.relative_to(project).as_posix()] = h.hexdigest()
    return result


def _kind(rel: str) -> str:
    p = Path(rel)
    if any(m in rel for m in INJECTED_MARKERS):
        return 'injected'
    if p.suffix in CONFIG_SUFFIXES or p.name in CONFIG_NAMES or p.name.endswith(('.Build.cs', '.Target.cs')) \
            or rel.startswith('ProjectSettings/') or '/Config/' in f'/{rel}':
        return 'config'
    if p.suffix in CODE_SUFFIXES:
        return 'code'
    return 'asset'


def _text(path: Path) -> list[str]:
    try:
        return path.read_text(encoding='utf-8', errors='replace').splitlines(keepends=True)
    except OSError:
        return []


def _logs(out: Path, take_record: Path) -> list[str]:
    """Log files that explain the failure (newest attempt first)."""
    names = ('import.log', 'import_console.log', 'Editor.log', 'unreal.log', 'engine.log', 'record_error.json',
             'build.json', 'admission.json', 'UnrealBuildTool.log', 'Log.txt', 'startup_readiness.json',
             'runner_exit.json', 'launch.json', '_editor_report.json')
    found = []
    for root in (take_record, out / 'runtime' / 'ue_admission', out / 'runtime'):
        if not root.exists():
            continue
        for p in sorted(root.rglob('*'), key=lambda q: -q.stat().st_mtime if q.exists() else 0):
            if p.is_file() and (p.name in names or p.suffix == '.log') and 'launch_repair' not in p.parts:
                found.append(str(p))
            if len(found) >= 25:
                break
    return found


def _codex(folder: Path, project: Path, prompt: str) -> dict:
    executable = os.environ.get('A3GAME_CODEX_EXECUTABLE') or 'codex'
    write_json(folder / 'schema.json', RESULT_SCHEMA)
    (folder / 'prompt.txt').write_text(prompt, encoding='utf-8')
    output = folder / 'response.json'
    effort = os.environ.get('A3GAME_SOL_REASONING_EFFORT', 'medium').strip() or 'medium'
    cmd = [executable, '--ask-for-approval', 'never', 'exec', '--model', MODEL,
           '-c', 'model_reasoning_effort=' + json.dumps(effort),
           '--sandbox', 'workspace-write', '--ephemeral', '--ignore-rules',
           '-C', str(project), '--json', '--color', 'never', '-o', str(output),
           '--output-schema', str(folder / 'schema.json'), '--', '-']
    env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ('ANTHROPIC', 'CLAUDE', 'AWS_', 'HF_'))}
    started = time.monotonic()
    with (folder / 'events.jsonl').open('w') as so, (folder / 'stderr.log').open('w') as se:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=so, stderr=se, cwd=project, text=True,
                                env=env, start_new_session=True)
        try:
            proc.communicate(prompt, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=10)
            write_json(folder / 'invocation.json', {'model': MODEL, 'status': 'TIMEOUT', 'seconds': TIMEOUT_S})
            return {'status': 'not_repairable', 'root_cause': 'repair call timed out', 'changes': [], 'not_fixed': ''}
    write_json(folder / 'invocation.json', {'model': MODEL, 'exit_code': proc.returncode, 'sandbox': 'workspace-write',
                                            'cwd': str(project), 'seconds': round(time.monotonic() - started, 1),
                                            'command': cmd})
    try:
        return json.loads(output.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'status': 'not_repairable', 'root_cause': f'no valid response (exit {proc.returncode})',
                'changes': [], 'not_fixed': ''}


def _restore(project: Path, backup: Path, before: dict, after: dict) -> None:
    for rel in set(before) | set(after):
        if before.get(rel) == after.get(rel):
            continue
        dest = project / rel
        if rel in before:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup / rel, dest)
        elif dest.exists():
            dest.unlink()


def attempt(out: Path, manifest: dict, failure: str, take_record: Path) -> dict:
    """One repair attempt on runtime/project. Returns the receipt (receipt['accepted'] tells whether it holds)."""
    out = Path(out)
    project = (out / 'runtime' / 'project').resolve()
    root = out / 'runtime' / 'launch_repair'
    n = 1
    while (root / f'{n:02d}').exists():
        n += 1
    folder = root / f'{n:02d}'
    folder.mkdir(parents=True)
    before = _files(project)
    backup = folder / 'backup'
    for rel in before:                       # full backup of everything a repair may touch (code + config)
        if _kind(rel) in ('config', 'code'):
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(project / rel, backup / rel)
    logs = _logs(out, take_record)
    skill = SKILL.read_text(encoding='utf-8')
    prompt = (f'{skill}\n\n---\nENGINE: {manifest.get("engine")}\nGAME: {manifest.get("game_id")}\n'
              f'WORKING DIRECTORY (eval copy, the only place you may write): {project}\n'
              f'FAILURE (from the evaluator):\n{failure[:4000]}\n\nLOG FILES (read them; newest first):\n'
              + '\n'.join(logs) + '\n')
    receipt = {'attempt': n, 'model': MODEL, 'engine': manifest.get('engine'), 'failure': failure[:4000],
               'logs': logs, 'skill_sha256': hashlib.sha256(skill.encode()).hexdigest(),
               'started': time.strftime('%Y-%m-%dT%H:%M:%S')}
    result = _codex(folder, project, prompt)
    after = _files(project)
    changed = sorted(r for r in set(before) | set(after) if before.get(r) != after.get(r))
    receipt.update(response=result, changed_files=[{'file': r, 'kind': _kind(r),
                                                    'change': 'added' if r not in before else
                                                    'deleted' if r not in after else 'modified'} for r in changed])
    problems = []
    for c in receipt['changed_files']:
        if c['change'] == 'deleted':
            problems.append(f'deleted author file {c["file"]}')
        elif c['kind'] in ('asset', 'injected'):
            problems.append(f'changed {c["kind"]} file {c["file"]}')
        elif c['kind'] == 'code' and c['change'] == 'added' and Path(c['file']).suffix == '.cs':
            problems.append(f'new game script {c["file"]}')
    diff = []
    for r in changed:
        if _kind(r) in ('config', 'code'):
            old = _text(backup / r) if r in before else []
            new = _text(project / r) if r in after else []
            diff += difflib.unified_diff(old, new, f'a/{r}', f'b/{r}', n=3)
    diff_text = ''.join(diff)
    (folder / 'change.diff').write_text(diff_text, encoding='utf-8')
    review = None
    if not changed:
        problems.append(f'no change ({result.get("status")}: {result.get("root_cause", "")[:300]})')
    elif not problems:
        if len(diff_text) > 400_000:
            problems.append(f'diff too large to review ({len(diff_text)} chars)')
        else:
            try:
                review = call_model(folder / 'review', name='launch_repair_review', schema=REVIEW_SCHEMA,
                                    prompt=REVIEW_PROMPT.format(skill=skill, failure=failure[:4000], diff=diff_text),
                                    cwd=folder, model=MODEL, timeout=900, max_attempts=2)
            except HarnessError as exc:
                problems.append(f'review call failed: {exc}')
            else:
                bad = [h for h in review['hunks'] if h['changes_game_behaviour']
                       or h['category'] not in ('config', 'compile_compat', 'new_stub')]
                if review['verdict'] != 'accept' or bad:
                    problems.append('review rejected: ' + '; '.join(f'{h["file"]}: {h["reason"][:200]}' for h in bad[:6])
                                    + ('' if bad else review['summary'][:300]))
    accepted = bool(changed) and not problems
    if not accepted:
        _restore(project, backup, before, after)
        receipt['restored'] = _files(project) == before
    else:
        overlay = root / 'overlay'
        for r in changed:
            if r in after:
                (overlay / r).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(project / r, overlay / r)
    receipt.update(accepted=accepted, problems=problems, review=review,
                   diff_sha256=hashlib.sha256(diff_text.encode()).hexdigest(),
                   finished=time.strftime('%Y-%m-%dT%H:%M:%S'))
    write_json(folder / 'receipt.json', receipt)
    summary = read_json(root / 'summary.json') if (root / 'summary.json').is_file() else {'attempts': []}
    summary['attempts'].append({'attempt': n, 'accepted': accepted, 'failure': failure[:300],
                                'files': [c['file'] for c in receipt['changed_files']],
                                'problems': problems[:5], 'receipt': str(folder / 'receipt.json')})
    summary['accepted_files'] = sorted({f for a in summary['attempts'] if a['accepted'] for f in a['files']})
    write_json(root / 'summary.json', summary)
    return receipt


def reapply(out: Path, project: Path) -> list[str]:
    """Re-apply accepted repairs after runtime/project was rebuilt from the frozen input snapshot."""
    overlay = Path(out) / 'runtime' / 'launch_repair' / 'overlay'
    if not overlay.is_dir():
        return []
    done = []
    for p in overlay.rglob('*'):
        if p.is_file():
            rel = p.relative_to(overlay)
            (Path(project) / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, Path(project) / rel)
            done.append(rel.as_posix())
    return done


def summary(out: Path) -> dict | None:
    p = Path(out) / 'runtime' / 'launch_repair' / 'summary.json'
    if not p.is_file():
        return None
    s = read_json(p)
    return {'attempts': len(s['attempts']), 'accepted': sum(a['accepted'] for a in s['attempts']),
            'files': s.get('accepted_files', []), 'detail': 'runtime/launch_repair/summary.json',
            'note': 'the eval copy was changed (environment / compile compatibility only) so the delivered game could start'}
