"""One audited restart after a successful Sol service probe; preserve failed calls."""
from pathlib import Path
import json
import shutil
import time

from . import batch, static_existence, unity_safety
from .protocol import dump, sha

VERSION = 'whitebox-unity-service-recovery.v1'


def service_failures(attempt):
    """Return actual failed 503 calls, not a guessed classification from stderr."""
    found = []
    for folder in sorted((Path(attempt)/'model_calls').glob('*')):
        if not folder.is_dir() or not (folder/'invocation.json').is_file():
            continue
        invocation = batch.read(folder/'invocation.json')
        events = folder/'events.jsonl'
        if (invocation.get('exit_code') in (None, 0) or not events.is_file()
                or invocation.get('model_requested') != static_existence.MODEL):
            continue
        errors = []
        for line in events.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get('type') == 'turn.failed':
                message = row.get('error', {}).get('message', '')
                if '503' in message and 'Service Unavailable' in message:
                    errors.append(message)
        if errors:
            found.append({'stage':folder.name, 'errors':errors,
                'files':{str(p.relative_to(attempt)):sha(p) for p in folder.iterdir() if p.is_file()}})
    return found


def verify_probe(output, probe):
    return _verify_probe_at(output, probe, time.time())


def _verify_probe_at(output, probe, checked_unix):
    output, probe = Path(output).resolve(), Path(probe).resolve()
    if not probe.is_relative_to(output/'service_recovery'):
        raise ValueError('Service probe must belong to this queue')
    folder = probe/'model_calls/service_probe'
    invocation = batch.read(folder/'invocation.json')
    command = invocation.get('command', [])
    if (invocation.get('exit_code') != 0 or invocation.get('model_requested') != static_existence.MODEL
            or '--model' not in command or command[command.index('--model')+1] != static_existence.MODEL
            or batch.read(folder/'response.json') != {'status':'READY'}
            or not 0 <= checked_unix-(folder/'invocation.json').stat().st_mtime <= 900
            or not 0 < invocation.get('seconds', 0) <= 90
            or batch.read(folder/'budget.json').get('effective_timeout_seconds') != 90):
        raise ValueError('No recent successful bounded Sol service probe')
    if any((probe/'model_calls').glob('service_probe_*')):
        raise ValueError('Service probe must be one bounded invocation')
    return {str(p.relative_to(probe)):sha(p) for p in folder.iterdir() if p.is_file()}


def prepare_attempt(source, failures):
    """New invocation identity; copy only validated completed static work verbatim."""
    source = Path(source).resolve()
    batch.verify_inputs(source)
    entry = batch.read(source/'input_manifest.json')['entry']
    protocol = batch.read(source/'input/pilot_rubric.json')
    if any((source/n).exists() for n in ('sol_plan.json', 'background_record', 'scores.json')):
        raise ValueError('Service retry is limited to unfinished pre-plan source work')
    root = source.parent/(entry['id']+'__service_recovery_v1_'+str(time.time_ns()))
    batch.prepare(source.parents[1], entry, root, previous_attempt=source)
    if (static_existence.identity(root, batch.read(root/'input/pilot_rubric.json'))
            != static_existence.identity(source, protocol)):
        raise ValueError('Service recovery changed frozen identity')
    copied = []
    if (source/'static_existence.json').is_file():
        static_existence.load(source, protocol)
        copied.append('static_existence.json')
        shutil.copy2(source/'static_existence.json', root/'static_existence.json')
        from .partial_static_existence import RECEIPT as partial_static_receipt
        if (source/partial_static_receipt).is_file():
            shutil.copy2(source/partial_static_receipt, root/partial_static_receipt)
            copied.append(partial_static_receipt)
        for folder in (source/'model_calls').glob('static_existence*'):
            if folder.is_dir():
                shutil.copytree(folder, root/'model_calls'/folder.name)
                copied.extend(str(p.relative_to(source)) for p in folder.rglob('*') if p.is_file())
        static_existence.load(root, protocol)
    from .route_first_capture import install_compact_policy
    install_compact_policy(root)
    dump(root/'service_recovery.json', {'version':VERSION, 'source_attempt':str(source),
        'failures':failures, 'copied_bindings':{n:sha(source/n) for n in copied},
        'frozen_source_and_rubric_identity_unchanged':True, 'maximum_service_recoveries':1,
        'reason':'Successful bounded service probe after actual provider 503; keep every old invocation'})
    return root


def authorize(output, config, state, probe):
    """Called under the production coordinator before reopening a stopped queue."""
    output = Path(output)
    if not probe:
        raise ValueError('Environment stop requires --service-recovery-probe; no implicit restart')
    bindings = verify_probe(output, probe)
    if state.get('service_recovery_history'):
        raise ValueError('One service recovery already used; preserve the new stop')
    failed = []
    for ident, case in state['cases'].items():
        if case.get('status') != 'BOUNDED_FAILURE' or not case.get('recorded_attempt'):
            continue
        source = Path(case['recorded_attempt'])
        failures = service_failures(source)
        if failures:
            failed.append((ident, case, source, failures))
    if not failed:
        raise ValueError('No actual failed Sol service invocation supports this recovery')
    safety = unity_safety.check(config)
    # Do not authorize an environment restart over unresolved capture cleanup.
    for case in state['cases'].values():
        if case.get('recorded_attempt'):
            capture = Path(case['recorded_attempt'])/'background_record'
            if capture.exists():
                unity_safety.capture_cleanup(capture)
    old_ledger = output/'service_recovery'/('stopped_queue_'+str(time.time_ns())+'.json')
    dump(old_ledger, state)
    retried = []
    for ident, case, source, failures in failed:
        if case.get('service_recovery_count'):
            continue
        case_output = output/'cases'/ident
        saved_path = case_output/'single_state.json'
        saved = batch.read(saved_path)
        if Path(saved['attempt']).resolve() != source.resolve():
            raise ValueError('Failed service attempt pointer changed')
        new_attempt = prepare_attempt(source, failures)
        history = case_output/'state_history'/('before_service_recovery_'+str(time.time_ns())+'.json')
        dump(history, saved)
        dump(saved_path, {'attempt':str(new_attempt), 'phase':'service_recovery_prepared',
            'previous_attempt':str(source), 'started_unix':time.time()})
        case.setdefault('failure_history', []).append({k:v for k,v in case.items()
            if k not in ('entry','failure_history')})
        case.update(status='PENDING', service_recovery_count=1, recorded_attempt=str(new_attempt),
            recovery_reason='One provider-503 recovery; successful source stage reused verbatim')
        retried.append(ident)
    receipt = {'version':VERSION, 'probe':str(Path(probe).resolve()), 'probe_bindings':bindings,
        'prior_ledger':str(old_ledger), 'prior_ledger_sha256':sha(old_ledger),
        'prior_consecutive_environment_failures':state['consecutive_environment_failures'],
        'threshold_unchanged':config.get('environment_failure_stop_threshold',3),
        'cleanup':safety, 'retried_cases':retried, 'authorized_unix':time.time()}
    dump(output/'service_recovery/authorization.json', receipt)
    state.setdefault('service_recovery_history', []).append(receipt)
    state['consecutive_environment_failures'] = 0
