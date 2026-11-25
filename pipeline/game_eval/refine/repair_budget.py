"""Opt-in, source-bound repair accounting. Never edits an old claim or receipt.

Call mutation APIs only at a stopped dispatch boundary under the candidate lease.
Files are append-only and exclusive-created; competing writers fail closed. This
module performs no provider calls, process cleanup, dispatch, or evaluation.

Coordinator integration (runtime overlay; do not rewrite frozen config/pins)::

    config = {**original_config,
              'repair_budget_policy': SOL_POLICY,
              'provider_runtime_policy': {'codex_reasoning_effort': 'medium'}}
    create_revision(folder, config, authorization=old_authorization_path,
                    sources=[old_config_path, code_identity_path, repair_probe_path],
                    parent_failure=folder / 'repair_rounds/round_003')
    state = verify_recovery(folder, config)
    # Dispatch only with candidate lease, migration authorization and healthy route.
    # fresh_sessions.repair_project reuses the current candidate and old claims.

Sol G003: physical_attempt=3, effective_used=1, effective_remaining=9,
excluded_attempts=[2,3], recovery_target=3, next_physical_attempt=4. A diagnosed
first-attempt Sol failure yields 0 used / 10 remaining / physical attempt 2 next.
HTTP400 is never a Sol exclusion. PHYSICAL_POLICY permits an explicitly reviewed
non-Sol failed-claim recovery while still charging every physical attempt (max10).
It is not implicitly enabled for GLM or any other provider.

Sidecar: repair_rounds/budget_recovery/revision.json, events/NNNNNN.json,
checkpoints/*.json. Parent failures are path+SHA references to the old claim.
All source refs use {'path': absolute_path, 'sha256': digest}. Subsequent failures
require authorize_recovery with repair/probe sources. counts() is read-only;
verify_recovery additionally checks live candidate/original and dispatch readiness.
The matrix must use effective_remaining rather than directory number for the Sol
cap and must bypass its ERROR/unclosed guard only after verify_recovery succeeds.
Batch preparation must explicitly verify/allow these runtime keys via its migration
receipt. Summary consumers use rounds_attempted for physical history and
rounds_completed/effective_used for successful work/accounting; no eval is implied.
"""
from pathlib import Path
import json
import re
import os
import tempfile

from .common import read, sha
from .session import inventory

SOL_POLICY = 'sol_effective_success_10.v1'
PHYSICAL_POLICY = 'physical_attempt_10_recovery.v1'
POLICIES = {SOL_POLICY, PHYSICAL_POLICY}
DIRECTORY = 'repair_rounds/budget_recovery'
EXCLUDED = {'TIMEOUT', 'PROVIDER_AUTH_FAILURE', 'PROVIDER_CONNECTION_FAILURE'}


def selected(config):
    policy = config.get('repair_budget_policy')
    if policy is None:
        return False
    if policy not in POLICIES:
        raise ValueError('Unknown explicit repair budget policy')
    if policy == SOL_POLICY and (config.get('agent', {}).get('provider') != 'codex'
                                or config['agent'].get('model') != 'gpt-6.1-sol'):
        raise ValueError('Effective-success budget is authorized only for Sol')
    if config.get('interaction_policy') != 'fresh_session_multi_provider_1500s_work_300s_handoff_10attempts.v3':
        raise ValueError('Budget recovery requires the fresh multi-provider session policy')
    return True


def _ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha(path)}


def _verify(refs):
    for ref in refs:
        if sha(ref['path']) != ref['sha256']:
            raise ValueError('Budget evidence changed: ' + ref['path'])


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Link a fully flushed file into its final exclusive slot. A kill cannot
    # leave a half-written revision/event that looks like accepted accounting.
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                     prefix='.' + path.name + '.', delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink()



def _identity(folder, config):
    # Do not rewrite frozen config/pins to select this policy. Bind the original
    # experiment separately from this explicit accounting overlay.
    prior = config.get('explicit_restart', {}).get('prior_counted_attempts', 0)
    if type(prior) is not int or prior < 0:
        raise ValueError('Invalid prior cumulative budget')
    return {'folder': str(Path(folder).resolve()), 'agent': config['agent'],
            'explicit_restart': config.get('explicit_restart'),
            'repair_rounds': config.get('repair_rounds', 1), 'prior_counted_attempts': prior,
            'interaction_policy': config.get('interaction_policy'),
            'provider_runtime_policy': config.get('provider_runtime_policy'),
            'original': _ref(Path(folder) / 'original_project.json')}


def _roots(folder):
    roots = sorted(Path(folder).glob('repair_rounds/round_*'))
    for number, root in enumerate(roots, 1):
        if root.name != f'round_{number:03d}' or not (root / 'claim.json').is_file():
            raise ValueError('Physical attempt sequence has a gap or missing claim')
        if read(root / 'claim.json').get('round') != number:
            raise ValueError('Physical claim number changed')
    return roots


def _evidence(root):
    paths = [root / name for name in ('claim.json', 'closed.json', 'repaired_project.json',
                                      'AGENT.md', 'repair_status.json') if (root / name).is_file()]
    for phase in ('work', 'handoff'):
        receipt = root / phase / 'receipt.json'
        if receipt.is_file():
            paths.append(receipt)
        raw = root / phase / 'agent_session/raw'
        if raw.is_dir():
            paths.extend(sorted(p for p in raw.rglob('*') if p.is_file()))
    closed = root / 'closed.json'
    if closed.exists():
        refs = read(closed)['sources']
        _verify(refs)
        paths.extend(Path(ref['path']) for ref in refs)
    return [_ref(p) for p in sorted(set(paths))]


def _provider_failure(root):
    """Inspect only native failure fields/raw error events, never echoed prompts."""
    messages = []
    for phase in ('work', 'handoff'):
        receipt = root / phase / 'receipt.json'
        if receipt.is_file():
            value = read(receipt)
            messages.extend(str(x) for x in (value.get('error'), value.get('report', {}).get('error')) if x)
        raw = root / phase / 'agent_session/raw'
        for path in sorted(raw.glob('*.jsonl')):
            for line in path.read_text(errors='replace').splitlines():
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                typ = str(event.get('type', ''))
                if typ in ('error', 'turn.failed') or typ.endswith('.error'):
                    messages.append(json.dumps(event, ensure_ascii=False))
    text = '\n'.join(messages).lower()
    if re.search(r'\b401\b|\b403\b|invalid[ _-]?token|unauthorized|authentication failed', text):
        return 'PROVIDER_AUTH_FAILURE'
    if re.search(r'\b400\b|invalid_request', text):
        return 'PROVIDER_REQUEST_FAILURE'
    if re.search(r'error sending request|connection (?:reset|refused|closed)|network (?:error|failure)|'
                 r'failed to (?:connect|send request)|dns (?:error|failure)|connecterror', text):
        return 'PROVIDER_CONNECTION_FAILURE'
    return None


def _successful(receipt):
    report = receipt.get('report', {})
    return (report.get('status') == 'completed' and receipt.get('provider_completed') is True
            and not receipt.get('error') and not report.get('finalization_error')
            and report.get('ok', True) is not False and report.get('exit_code', 0) == 0)


def diagnose(root):
    """Return redacted facts + SHA references; no raw credentials in the result."""
    root = Path(root).resolve()
    receipts = [read(root / phase / 'receipt.json') for phase in ('work', 'handoff')
                if (root / phase / 'receipt.json').is_file()]
    work = read(root / 'work/receipt.json') if (root / 'work/receipt.json').is_file() else {}
    fault = _provider_failure(root)
    if (root / 'closed.json').is_file() and receipts and all(_successful(r) for r in receipts):
        outcome = 'SUCCESS'
    elif fault and not _successful(work):
        outcome = fault
    elif any(r.get('report', {}).get('status') == 'timeout' for r in receipts):
        outcome = 'TIMEOUT'
    else:
        # Successful work + failed handoff cannot silently become a free round.
        outcome = 'UNRESOLVED'
    return {'physical_attempt': read(root / 'claim.json')['round'], 'root': str(root),
            'outcome': outcome, 'provider_fault': fault, 'sources': _evidence(root)}


def provider_circuit_state(attempt_roots, *, connection_threshold=2):
    """Read-only scheduler API; auth/400 pauses immediately, repeated transport
    failures/timeouts pause after the threshold. Supply one provider route only,
    ordered by dispatch time. A verified success resets consecutive failures.
    """
    if type(connection_threshold) is not int or connection_threshold < 1:
        raise ValueError('Invalid provider circuit threshold')
    consecutive, paused, reason = 0, False, None
    sources, seen = [], set()
    for root in attempt_roots:
        root = Path(root).resolve()
        if root in seen:
            continue
        seen.add(root)
        fact = diagnose(root)
        if fact['outcome'] == 'SUCCESS':
            consecutive, paused, reason, sources = 0, False, None, []
        elif fact['provider_fault'] in ('PROVIDER_AUTH_FAILURE', 'PROVIDER_REQUEST_FAILURE'):
            consecutive += 1
            paused, reason = True, fact['provider_fault']
            sources.extend(fact['sources'])
        elif fact['provider_fault'] or fact['outcome'] == 'TIMEOUT':
            consecutive += 1
            sources.extend(fact['sources'])
            if not paused and consecutive >= connection_threshold:
                paused, reason = True, fact['provider_fault'] or fact['outcome']
        # Unknown failure cannot clear a tripped circuit or replace its cause.
    return {'pause_dispatch': paused, 'consecutive_failures': consecutive,
            'reason': reason, 'sources': sources,
            'recovery_condition': 'Explicit route/credential repair and source-bound successful probe' if paused else None}



class Budget:
    def __init__(self, folder, config):
        if not selected(config):
            raise ValueError('Budget policy must be explicitly selected')
        self.folder = Path(folder).resolve()
        self.config = config
        self.directory = self.folder / DIRECTORY
        self.revision = read(self.directory / 'revision.json')
        if (self.revision['policy'] != config['repair_budget_policy']
                or self.revision['identity'] != _identity(self.folder, config)):
            raise ValueError('Budget experiment/model/source identity changed')
        _verify(self.revision['sources'])
        self.events = []
        previous = sha(self.directory / 'revision.json')
        for n, path in enumerate(sorted((self.directory / 'events').glob('*.json')), 1):
            event = read(path)
            if path.name != f'{n:06d}.json' or event['previous_sha256'] != previous:
                raise ValueError('Budget journal lineage changed')
            _verify(event.get('sources', []))
            self.events.append(event)
            previous = sha(path)
        self.last_sha = previous
        self.records = {r['physical_attempt']: r for r in self.revision['history']}
        self.started = set(self.records)
        self.checkpoint = self.revision['checkpoint']
        self.parent_failure = self.revision['parent_failure']
        self.recovery_target = self.revision['recovery_target']
        self.needs_recovery = False
        for record in self.revision['history']:
            _verify(record['sources'])
        for event in self.events:
            if event['kind'] == 'started':
                n = event['physical_attempt']
                if n in self.started or n != len(self.started) + 1:
                    raise ValueError('Physical attempt was reused or skipped')
                claim = read(self.folder / 'repair_rounds' / f'round_{n:03d}' / 'claim.json')
                if (claim.get('previous_manifest_sha256') != self.checkpoint['sha256']
                        or claim.get('parent_failure') != self.parent_failure
                        or claim.get('budget_revision') != _ref(self.directory / 'revision.json')):
                    raise ValueError('Resumed physical claim source/recovery parent changed')
                self.started.add(n)
                self.needs_recovery = True
            elif event['kind'] == 'outcome':
                record = event['record']
                n = record['physical_attempt']
                if n not in self.started or n in self.records:
                    raise ValueError('Attempt outcome was replaced')
                self.records[n] = record
                self.checkpoint = event['checkpoint']
                self.needs_recovery = record['outcome'] != 'SUCCESS'
            elif event['kind'] == 'recovery':
                self.checkpoint = event['checkpoint']
                self.parent_failure = event['parent_failure']
                self.recovery_target = event['recovery_target']
                self.needs_recovery = False
            else:
                raise ValueError('Unknown budget event')
        # Every real claim must have been accounted for; never hide a directory.
        roots = _roots(self.folder)
        if len(roots) != len(self.started):
            raise ValueError('Unregistered physical attempt; source-bound recovery required')
        self._sessions()
        if self.counts()['effective_used'] > self.revision['limit']:
            raise ValueError('Cumulative repair budget exceeds its frozen limit')

    def _sessions(self):
        seen = set()
        for n in sorted(self.started):
            root = self.folder / 'repair_rounds' / f'round_{n:03d}'
            ids = set()
            for phase in ('work', 'handoff'):
                receipt = root / phase / 'receipt.json'
                if receipt.exists():
                    ids.update(read(receipt).get('session_ids', []))
            if seen & ids:
                raise ValueError('Work session reused across physical attempts')
            seen.update(ids)
            record = self.records.get(n)
            if record and record['outcome'] == 'SUCCESS':
                closed = read(root / 'closed.json')
                work = read(root / 'work/receipt.json')
                if (len(ids) != 1 or closed['session_ids'] != work['session_ids']
                        or set(closed['session_ids']) != ids
                        or closed['model'] != self.config['agent']['model']
                        or work['model'] != self.config['agent']['model']):
                    raise ValueError('Successful round lacks a verified fresh model/session')
        self.sessions = seen

    def counts(self):
        excluded = [n for n, r in sorted(self.records.items())
                    if self.revision['policy'] == SOL_POLICY and r['outcome'] in EXCLUDED]
        successes = sum(r['outcome'] == 'SUCCESS' for r in self.records.values())
        used = self.revision['identity']['prior_counted_attempts'] + (
            successes if self.revision['policy'] == SOL_POLICY else len(self.started))
        return {'repair_budget_policy': self.revision['policy'], 'physical_attempt': len(self.started),
                'rounds_attempted': len(self.started), 'rounds_completed': successes,
                'effective_used': used, 'effective_remaining': self.revision['limit'] - used,
                'effective_limit': self.revision['limit'], 'excluded_attempts': excluded,
                'excluded_reasons': {str(n): self.records[n]['outcome'] for n in excluded},
                'unresolved_attempts': sorted(self.started - self.records.keys()) + [
                    n for n, r in self.records.items() if r['outcome'] == 'UNRESOLVED'],
                'recovery_target': self.recovery_target, 'parent_failure': self.parent_failure,
                'recovery_required': self.needs_recovery,
                'budget_revision': _ref(self.directory / 'revision.json'),
                'budget_journal_sha256': self.last_sha}

    def append(self, event):
        event = {**event, 'previous_sha256': self.last_sha}
        _write_new(self.directory / 'events' / f'{len(self.events) + 1:06d}.json', event)
        return Budget(self.folder, self.config)

    def next_attempt(self):
        state = self.counts()
        if self.needs_recovery or state['unresolved_attempts']:
            raise ValueError('Unclosed failed attempt requires explicit source-bound recovery')
        if state['effective_remaining'] <= 0:
            raise ValueError('Effective repair budget exhausted')
        if inventory(self.folder / 'workspace/project') != read(self.checkpoint['path'])['files']:
            raise ValueError('Candidate changed after budget checkpoint; authorize source-bound recovery')
        return state['physical_attempt'] + 1

    def started_attempt(self, root):
        """Called after exclusive claim creation, before any provider call."""
        return self.append({'kind': 'started', 'physical_attempt': read(root / 'claim.json')['round'],
                            'sources': [_ref(root / 'claim.json')]})

    def record_attempt(self, root):
        record = diagnose(root)
        checkpoint = self.directory / 'checkpoints' / f'attempt_{record["physical_attempt"]:03d}.json'
        candidate = {'files': inventory(self.folder / 'workspace/project')}
        if checkpoint.exists():
            if read(checkpoint) != candidate:
                raise ValueError('Interrupted accounting checkpoint changed; preserve both sources')
        else:
            _write_new(checkpoint, candidate)
        return self.append({'kind': 'outcome', 'record': record, 'checkpoint': _ref(checkpoint),
                            'sources': record['sources'] + [_ref(checkpoint)]})


def create_revision(folder, config, *, authorization, sources, parent_failure):
    """Explicit migration, once per existing experiment. No new experiment/budget.

    ``authorization`` is the existing restart/user authorization, not a replacement.
    ``sources`` must bind coordinator identity/pins and failure/probe evidence.
    The caller must verify no worker can still modify this candidate.
    """
    if not selected(config) or not sources:
        raise ValueError('Explicit budget policy and source bindings required')
    folder = Path(folder).resolve()
    directory = folder / DIRECTORY
    if (directory / 'revision.json').exists():
        budget = Budget(folder, config)
        if (_ref(authorization) != budget.revision['authorization']
                or str(Path(parent_failure).resolve() / 'claim.json') != budget.revision['parent_failure']['path']):
            raise ValueError('Existing budget recovery identity cannot be replaced')
        return budget.counts()
    roots = _roots(folder)
    parent = Path(parent_failure).resolve()
    if not roots or parent != roots[-1].resolve():
        raise ValueError('Recovery parent must be the latest physical failure in this candidate')
    history = [diagnose(root) for root in roots]
    previous = None
    for root in roots:
        if read(root / 'claim.json').get('previous_manifest_sha256') != previous:
            raise ValueError('Historical claim source lineage changed')
        manifest = root / 'repaired_project.json'
        if manifest.exists():
            previous = sha(manifest)
    if history[-1]['outcome'] in ('SUCCESS', 'UNRESOLVED'):
        raise ValueError('Recovery requires diagnosed failure, not a success/unknown claim')
    if config['repair_budget_policy'] == SOL_POLICY and any(
            r['outcome'] not in EXCLUDED | {'SUCCESS'} for r in history):
        raise ValueError('Sol exclusion requires explicit timeout/network/auth failure evidence')
    from .rounds import validate_budget, verify_original
    limit = validate_budget(config)
    verify_original(folder)
    refs = [_ref(authorization), *[_ref(p) for p in sources], _ref(folder / 'original_project.json')]
    for record in history:
        refs.extend(record['sources'])
    # Preserve current authored bytes (including changes made in a timed-out turn).
    checkpoint = directory / 'checkpoints' / 'migration.json'
    _write_new(checkpoint, {'files': inventory(folder / 'workspace/project')})
    refs.append(_ref(checkpoint))
    summary = folder / 'repair_rounds/summary.json'
    if summary.exists():
        archived_summary = directory / 'previous_summary.json'
        _write_new(archived_summary, read(summary))
        refs.append(_ref(archived_summary))
    revision = {'policy': config['repair_budget_policy'], 'identity': _identity(folder, config),
                'limit': limit, 'authorization': _ref(authorization), 'sources': refs,
                'history': history, 'checkpoint': _ref(checkpoint),
                'parent_failure': _ref(parent / 'claim.json'), 'recovery_target': history[-1]['physical_attempt']}
    # Parent failure points to the claim, never to an overwritten round directory.
    _write_new(directory / 'revision.json', revision)
    return Budget(folder, config).counts()


def authorize_recovery(folder, config, *, parent_failure, sources):
    """Bind stopped candidate + diagnosed failure + external repair/probe receipts.

    Does not consume or replenish budget, and never retries the failed directory.
    Generic physical policy counts every old claim, including HTTP400 failures.
    """
    budget = Budget(folder, config)
    parent = Path(parent_failure).resolve()
    n = len(budget.started)
    if parent != budget.folder / 'repair_rounds' / f'round_{n:03d}' or not sources:
        raise ValueError('Recovery must bind latest failed physical attempt and repair/probe sources')
    record = diagnose(parent)
    if record['outcome'] in ('SUCCESS', 'UNRESOLVED'):
        raise ValueError('Recovery parent is not a diagnosed failure')
    if budget.revision['policy'] == SOL_POLICY and record['outcome'] not in EXCLUDED:
        raise ValueError('Failure is outside authorized Sol exclusions')
    if n not in budget.records:
        budget = budget.record_attempt(parent)
    checkpoint = budget.directory / 'checkpoints' / f'recovery_{len(budget.events) + 1:06d}.json'
    _write_new(checkpoint, {'files': inventory(budget.folder / 'workspace/project')})
    budget = budget.append({'kind': 'recovery', 'parent_failure': _ref(parent / 'claim.json'),
                            'recovery_target': n, 'checkpoint': _ref(checkpoint),
                            'sources': record['sources'] + [_ref(p) for p in sources] + [_ref(checkpoint)]})
    return budget.counts()


def counts(folder, config):
    """Scheduler/summary API: physical directories and effective budget are distinct."""
    return Budget(folder, config).counts()


def verify_recovery(folder, config):
    """Matrix guard: validates immutable lineage and live candidate before retry.

    Caller must still own the candidate/dispatch lease and check provider circuit
    + successful route probe. This function never starts a worker.
    """
    budget = Budget(folder, config)
    number = budget.next_attempt()
    from .rounds import verify_original
    verify_original(folder)
    return {**budget.counts(), 'ready': True, 'next_physical_attempt': number}
