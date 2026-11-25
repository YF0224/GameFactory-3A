"""Admit an actually completed recorded recovery across an exact gate delta.

Executed recovery dependencies remain historical and byte bound. New native
work must still pass its actual resource, editor, source and cleanup gates.
"""
from pathlib import Path
from . import batch
from .protocol import sha
from .mechanic_v3_runner import exclusive_json

VERSION = 'unity-m-completed-recorded-recovery.v1'
IDENTITY = 'Kimi__G013_wind_tower_grapple'
CLASSIFICATION = 'COMPLETED_RECORDED_RECOVERY_GATE_ONLY'
GATE_FILES = {'unity_m_admission.py', 'unity_m_incomplete_recovery.py',
              'unity_m_completed_recovery.py'}


def validate_process(workspace, repair, live, complete):
    required = ['--workspace', str(workspace), '--phase', 'unity-m-judge',
                '--ids', IDENTITY, '--column', 'Gameness', '--judge-repair', str(repair)]
    args = complete.get('args', [])
    marker = 'UNITY_M_COLUMN_PUBLISHED ' + IDENTITY + ' Gameness '
    if (complete.get('status') != 'COMPLETED' or complete.get('exit_code') != 0
            or not isinstance(live.get('pid'), int) or live.get('pid', 0) <= 0
            or complete.get('pid') != live.get('pid')
            or complete.get('tool_session') != live.get('tool_session')
            or live.get('status') != 'RUNNING_NOT_COMPLETE'
            or not live.get('ps_lstart') or not isinstance(live.get('ppid'), int)
            or args != live.get('args') or len(args) != 14
            or args[1:4] != ['-u', '-m', 'pipeline.eval.stage1.mechanic_v3_cli']
            or args[4:] != required
            or not (0 < complete.get('started', 0) <= live.get('observed_at', 0)
                    < complete.get('finished', 0))
            or not any(line.startswith(marker) and line.endswith(' SYNCED')
                       for line in complete.get('final_stdout', '').splitlines())):
        raise ValueError('Actual completed formal judge invocation and live provenance required')


def validate_gate_delta(before, after, archives):
    directory = Path(__file__).resolve().parent
    expected = {str(directory/name) for name in GATE_FILES}
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    if changed != expected or set(archives) != expected:
        raise ValueError('Only exact completed-recovery admission gate delta permitted')
    for name in changed:
        archive = archives[name]
        if name in before:
            if not archive or sha(Path(archive)) != before[name]:
                raise ValueError('Exact archived executed gate bytes required')
        elif archive is not None or Path(name).name != 'unity_m_completed_recovery.py':
            raise ValueError('Only the explicit new admission gate dependency is permitted')


def reference(spec):
    path = Path(spec['path'])
    if sha(path) != spec['sha256']:
        raise ValueError('Completed recovery immutable reference changed')
    return path, batch.read(path)


def verify(workspace, descriptor, *, expected_production=None):
    from . import unity_m_admission as admission, unity_m_incomplete_recovery as recovery
    from .unity_m_judge import publication_path
    workspace = Path(workspace).resolve()
    value = batch.read(descriptor)
    if (value.get('version') != VERSION or value.get('classification') != CLASSIFICATION
            or value.get('identity') != IDENTITY
            or value.get('model_recalled') is not False or value.get('score_changed') is not False):
        raise ValueError('Explicit complete recorded recovery qualification required')
    recovery_path, repair = reference(value['recorded_repair'])
    if recovery._reference(workspace) != (recovery_path, repair):
        raise ValueError('Exact current immutable recorded repair pointer required')
    executed = value['executed_producer']
    before = executed['production']
    current = admission.production() if expected_production is None else expected_production
    if (value.get('verification_production') != current or repair['after_production'] != before
            or executed.get('model') != 'gpt-6.1-sol'):
        raise ValueError('Actual executed and current verification producers must stay distinct')
    validate_gate_delta(before, current, value['changed_files'])
    # Historical validation returns only a restricted, zero-native capability.
    # The public live route always defaults to current production.
    restricted = recovery.require(workspace, IDENTITY, 'Gameness',
                                  expected_production=before)
    if restricted.get('new_native_calls') != 0 or restricted.get('restricted') is not True:
        raise ValueError('Original restricted recorded recovery required')
    judge_repair_path, judge_repair = reference(value['judge_repair'])
    if judge_repair.get('after_producer') != executed:
        raise ValueError('Actual completed judge continuation producer required')
    live_path, live = reference(value['live_process'])
    _, complete = reference(value['completed_process'])
    if complete.get('live_process') != {'path': str(live_path), 'sha256': sha(live_path)}:
        raise ValueError('Actual live-to-completed process provenance required')
    validate_process(workspace, judge_repair_path, live, complete)
    root, proof = admission.evidence(workspace, IDENTITY)
    if proof != value.get('e2e') or str(root) != repair['root']:
        raise ValueError('Both complete original source/pixel columns and real sync required')
    publication = batch.read(publication_path(workspace, IDENTITY, 'Gameness'))
    continuations = list((root/'unity_m_judge_continuations').glob('*.json'))
    continuations += [root/'unity_m_judge_continuation.json']
    matching = [p for p in continuations if p.is_file()
                and batch.read(p).get('after_producer') == executed
                and batch.read(p).get('repair_path') == str(judge_repair_path)
                and batch.read(p).get('repair_sha256') == sha(judge_repair_path)]
    if not matching or not any(publication['bindings'].get(str(p)) == sha(p) for p in matching):
        raise ValueError('Successful publication must bind the actual recovery continuation')
    admission._check_regression(value['regression'])
    return value


def create(workspace, descriptor):
    from . import unity_m_admission as admission
    change = verify(workspace, descriptor)
    value = dict(version=admission.VERSION,
        capability='UNITY_M_MECHANIC_V3_GAMENESS_V4_ORIGINAL_PIXELS',
        verification_production=admission.production(), executed_producer=change['executed_producer'],
        e2e=change['e2e'], completed_recorded_recovery=dict(
            path=str(Path(descriptor).resolve()), sha256=sha(Path(descriptor))),
        scoring_unchanged=True, model='gpt-6.1-sol')
    target = admission.admission_path(workspace, value['verification_production'])
    if target.exists():
        if batch.read(target) != value:
            raise ValueError('Immutable completed recovery admission changed')
    else:
        exclusive_json(target, value)
    return target, value
