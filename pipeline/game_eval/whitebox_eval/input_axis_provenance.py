"""Independently verify runtime-only generated-axis correction and recovery."""
from pathlib import Path
from .protocol import sha
from . import batch


def audit_binding(root):
    from .recorded_import_review import reviewed_axis_paths
    root=Path(root).resolve();recorded=root
    provenance=root/'recorded_capture_provenance.json'
    if provenance.is_file():recorded=Path(batch.read(provenance)['source_attempt']).resolve()
    receipt=recorded/'input_axis_capture_recovery.json'
    if not receipt.exists():return {}
    value=batch.read(receipt);source=Path(value['source_attempt']).resolve()
    if value['version']!='unity-axis-capture-recovery.v1' or source==recorded or source.parent!=recorded.parent:
        raise ValueError('Axis recovery identity mismatch')
    if value['plan_model_calls_added']!=0 or value['physical_actions_changed'] is not False or value['frozen_source_changed'] is not False:
        raise ValueError('Axis recovery changed planning or frozen inputs')
    if not (source/'background_record/error.json').is_file() or (source/'scores.json').exists():
        raise ValueError('Axis recovery requires preserved failed harness capture')
    bindings={str(receipt):sha(receipt)}
    for name,digest in value['copied_files_sha256'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Invalid axis recovery path')
        if sha(source/relative)!=digest or sha(recorded/relative)!=digest:
            raise ValueError('Axis recovery preserved input changed: '+name)
        bindings[str(source/relative)]=digest;bindings[str(recorded/relative)]=digest
    acceptance=Path(value['editor_acceptance'])
    if sha(acceptance)!=value['editor_acceptance_sha256']:raise ValueError('Axis recovery acceptance changed')
    bindings[str(acceptance)]=sha(acceptance)
    accepted=batch.read(acceptance)
    from engine_adapters.unity3d.playtest.native_acceptance import verify
    verify(acceptance,Path(batch.read(recorded/'recorder_acceptance_binding.json')['adapter_root']),Path(accepted['editor']))
    for stage in accepted['stages']:
        for key in ('verification','runner_exit'):
            path=Path(stage[key]['path']);bindings[str(path)]=sha(path)
    if value.get('cleanup_reconciliation'):
        path=Path(value['cleanup_reconciliation'])
        if sha(path)!=value['cleanup_reconciliation_sha256']:raise ValueError('Cleanup reconciliation changed')
        bindings[str(path)]=sha(path)
    if not reviewed_axis_paths(recorded):raise ValueError('Axis recovery correction was not independently verified')
    for name in ['source_snapshot.json','verification.json','runner_exit.json']:
        path=recorded/'background_record'/name;bindings[str(path)]=sha(path)
    return bindings
