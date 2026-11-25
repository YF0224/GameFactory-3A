"""Continue an unrecorded author-entry plan through existing tool-SHA recovery.

Both immutable parent claims remain intact. The existing identity continuation
changes only constraints_sha256 and runs the full current operation validator.
"""
from pathlib import Path
from types import SimpleNamespace
from . import batch, core12, engine_scoped_capture
from . import mechanic_v3_author_entry_recovery as author_entry
from . import mechanic_v3_prerecord_identity as identity
from . import mechanic_v3_outcome_native as native
from . import mechanic_v3_record_completion as completion
from .mechanic_v3_runner import read, exclusive_json, disk, qualify_source
from .protocol import sha


def locate(source):
    root = author_entry.verify(source)
    if (root/identity.CLAIM).exists():
        root = identity.verify(root)
    return root


def prepare(workspace, row):
    source = Path(workspace)/'runs'/row['entry']['id']
    if not (source/author_entry.CLAIM).exists():
        return author_entry.prepare(workspace, row)
    original = author_entry.verify(source)
    root = locate(source)
    proto = core12.verify_attempt(root, row['entry']['actual_engine'])
    operation = read(root/'sol_plan.json')
    current = core12.plan_identity(root, proto, row['entry']['actual_engine'])
    if operation['planning_identity'] != current:
        root = identity.recover(workspace, row, original)
        operation = read(root/'sol_plan.json')
    return root, batch.validate_operation_plan(root, operation, row['entry']['actual_engine'])


def record(workspace, row):
    root, operation = prepare(workspace, row)
    if (root/'source_qualification.json').exists():
        return root
    completion.freeze(root, operation)
    native.prepare_runtime_snapshot(root)
    if (root/'native_capture_admission.json').exists():
        raise ValueError('Retained attempted author-entry continuation requires diagnosis')
    disk(root, 'author_entry_identity_native_record', 2*1024**3)
    engine_scoped_capture.capture(workspace, root, operation,
        SimpleNamespace(godot=Path.home()/'.local/bin/godot4'), row['entry'])
    qualification = qualify_source(root, workspace=workspace)
    source = Path(workspace)/'runs'/row['entry']['id']
    qualification.update(new_recording=True, raw_record_reused=False,
        notice='作者原始声明入口及未录制计划工具身份续接后新增真实原生录制',
        author_entry_claim_sha256=sha(source/author_entry.CLAIM),
        view_manifest_sha256=sha(root/'evidence_manifest.json'))
    exclusive_json(root/'source_qualification.json', qualification)
    return root
