"""Resume a negative record selection through an immutable prior capture proof.

This uses the existing judge-only historical validator. It never records a game,
changes the frozen candidate order or alters the original failed selection.
"""
from pathlib import Path
import os
import shutil
from . import qualified_history as history
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION = 'mechanic-v3-prior-capture-qualification-continuation.v1'


def recover(workspace, row, selection):
    workspace, selection = Path(workspace).resolve(), Path(selection).resolve()
    previous = runner.read(selection)
    candidates = row.get('record_candidates', [])
    if (previous.get('identity') != row['entry']['id'] or previous.get('qualified_source') is not None or
            [v['path'] for v in previous.get('candidates', [])] != candidates or
            any(v.get('qualified') for v in previous['candidates'])):
        raise ValueError('Only the unchanged negative frozen candidate selection may continue')
    attempts = []
    for candidate in candidates:
        source = Path(candidate).resolve()
        try:
            history.prior(source)
        except Exception as error:
            attempts.append(dict(source=str(source),prior_capture_qualified=False,error=repr(error)))
            continue
        # Full current input, source, pin, physical capture and cleanup gates run
        # inside prepare_view. A failed current gate is preserved and stops here.
        _complete_preinvocation_view(workspace,row,source,selection)
        root = history.prepare_view(workspace,row,source)
        attempts.append(dict(source=str(source),prior_capture_qualified=True,current_capture_qualified=True))
        proof = dict(version=VERSION,time=runner.stamp(),identity=row['entry']['id'],
            previous_selection=str(selection),previous_selection_sha256=sha(selection),
            selected_source=str(source),source_qualification_sha256=sha(source/'source_qualification.json'),
            view_qualification_sha256=sha(root/'source_qualification.json'),attempts=attempts,
            producer_bindings={str(Path(__file__).resolve()):sha(Path(__file__).resolve()),
                str(Path(history.__file__).resolve()):sha(Path(history.__file__).resolve())},
            original_selection_preserved=True,frozen_order_unchanged=True,
            native_execution_allowed=False,new_native_recording=False,old_verdict_reused=False)
        runner.exclusive_json(root/'engineering/historical_qualification_continuation.json',proof)
        return root
    return None


def _complete_preinvocation_view(workspace,row,source,selection):
    """Recover only exact copied evidence after the Python hardlink API failure."""
    root=workspace/'runs'/row['entry']['id']
    if not root.exists() or (root/history.FILE).exists():return
    if any((root/name).exists() for name in ('source_qualification.json','model_calls','requests','native_capture_admission.json')):
        raise ValueError('Partial historical view has attempted model/native work')
    failures=[]
    for path in (workspace/'failures').glob(row['entry']['id']+'_*.json'):
        value=runner.read(path)
        if (value.get('identity')==row['entry']['id'] and value.get('phase')=='qualify'
                and value.get('error')=="AttributeError(\"'PosixPath' object has no attribute 'hardlink_to'\")"
                and 'qualified_history.py' in value.get('traceback','')):
            failures.append(path)
    if not failures:raise ValueError('Partial view lacks the preserved exact preparation failure')
    history.prior(source)
    manifest=runner.read(source/'evidence_manifest.json')
    allowed=set(history.REQUIRED)|{'attempt_manifest.json'}
    allowed.update(v['path'] for v in manifest['delivery_sheets'])
    allowed.update(str(p.relative_to(source)) for name in ('input','runtime')
        for p in (source/name).rglob('*') if p.is_file())
    repair=root/'engineering/partial_historical_view_recovery.json'
    existing=[p for p in root.rglob('*') if p.is_file() and p!=repair]
    for path in existing:
        rel=str(path.relative_to(root))
        if rel not in allowed or not (source/rel).is_file() or sha(path)!=sha(source/rel):
            raise ValueError('Partial historical view is not exact original evidence: '+rel)
    proof=dict(version=VERSION,classification='NON_SCORING_PREINVOCATION_VIEW_COMPLETION',
        source=str(source),source_qualification_sha256=sha(source/'source_qualification.json'),
        negative_selection_sha256=sha(selection),parent_failures={str(p):sha(p) for p in failures},
        partial_file_bindings={str(p):sha(p) for p in existing},
        producer_sha256=sha(Path(__file__)),no_model_or_native_invocation=True)
    if repair.exists():
        old=runner.read(repair)
        if (old['source']!=str(source) or old['source_qualification_sha256']!=proof['source_qualification_sha256']
                or old['negative_selection_sha256']!=sha(selection) or old['producer_sha256']!=sha(Path(__file__))):
            raise ValueError('Partial view recovery lineage changed')
        for path,h in {**old['partial_file_bindings'],**old['parent_failures']}.items():
            if sha(Path(path))!=h:raise ValueError('Partial view recovery bytes changed')
    else:runner.exclusive_json(repair,proof)
    for item in manifest['delivery_sheets']:
        src=source/item['path'];dst=root/item['path'];dst.parent.mkdir(parents=True,exist_ok=True)
        if dst.exists():
            if sha(dst)!=sha(src):raise ValueError('Retained historical sheet changed')
        else:os.link(src,dst)
    dst=root/'evidence_manifest.json'
    if dst.exists():
        if sha(dst)!=sha(source/'evidence_manifest.json'):raise ValueError('Partial capture manifest changed')
    else:shutil.copy2(source/'evidence_manifest.json',dst)
    runner.exclusive_json(root/history.FILE,dict(version=history.VERSION,source=str(source),
        qualification_sha256=sha(source/'source_qualification.json'),execution_allowed=False,
        created=runner.stamp(),scoring_semantics_unchanged=True))
