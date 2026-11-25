"""Verify final artifacts of the retained timeout-recovery chain for evaluation.

The post-turn foreign-GUI safety failure remains an ERROR. Qualifying an already
completed final provider output never retries repair or rewrites that marker.
"""
from pathlib import Path
from .common import read, sha
from .session import inventory


def verify_recovery_pass(folder, previous_config):
    folder = Path(folder)
    limit = previous_config['repair_rounds']
    saved = read(folder/'timeout_recovery/summary.json')
    refs, previous, ids = [], None, None
    def bind(path):
        refs.append({'path': str(path), 'sha256': sha(path)})
    for n in range(1, limit+1):
        root = folder if n == 1 else folder/'repair_rounds'/f'round_{n:03d}'
        marker = folder/'stages'/('repair.json' if n == 1 else f'repair_round_{n:03d}.json')
        report, identity = read(root/'agent_report.json'), read(root/'agent_identity.json')
        bind(marker); bind(root/'agent_report.json'); bind(root/'agent_identity.json')
        if (len(identity['session_ids']) != 1 or identity['model'] != previous_config['agent']['model']
                or ids is not None and ids != identity['session_ids']):
            raise ValueError('Recovery model/session chain changed')
        ids = identity['session_ids']
        if n > 1:
            binding = read(root/'binding.json'); bind(root/'binding.json')
            if binding['previous_manifest_sha256'] != sha(previous):
                raise ValueError('Recovery source chain changed')
        if report['status'] == 'timeout':
            checkpoint = folder/'timeout_recovery'/f'round_{n:03d}'/'checkpoint.json'
            recovery = read(checkpoint); bind(checkpoint)
            for ref in recovery['sources']:
                if sha(ref['path']) != ref['sha256']:
                    raise ValueError('Retained timeout evidence changed')
            previous = Path(recovery['manifest'])
            if sha(previous) != recovery['manifest_sha256']:
                raise ValueError('Retained timeout manifest changed')
        else:
            if (report.get('status') != 'completed' or report.get('exit_code') != 0
                    or report.get('finalization_error') or not identity['provider_completed']):
                raise ValueError('Final provider transport is not complete')
            previous = root/'repaired_project.json'
            state = read(marker)
            if state['status'] != 'COMPLETE':
                # Scope the known post-provider failure narrowly, never ignore arbitrary errors.
                if (n != limit or state['status'] != 'ERROR' or not
                        state.get('error','').startswith('BlockingIOError: Active GUI engine:')):
                    raise ValueError('Unqualified failed repair stage')
        bind(previous)
    if inventory(folder/'workspace/project') != read(previous)['files']:
        raise ValueError('Final counted candidate changed')
    original = read(folder/'original_project.json')
    if inventory(original['root']) != original['files']:
        raise ValueError('Original author delivery changed')
    # Source batch lock is held by caller. Record exact final agent PID liveness.
    import os
    pid = read(root/'agent_session/run_meta.json')['pid']
    try: os.kill(pid, 0)
    except ProcessLookupError: pass
    else: raise BlockingIOError('Final provider still alive')
    return {'version': 'stage3.recovery-artifact-binding.v1', 'rounds_attempted': limit,
            'final_turn': str(root), 'final_manifest': str(previous), 'sources': refs,
            'previous_summary': saved, 'budget_reset': False, 'new_repair_calls': 0,
            'meaning': 'Final completed provider output qualified for eval; old safety ERROR retained.'}
