"""Explicit contract-semantic revisions; preserve prior requests and publications."""
from pathlib import Path
import json
import datetime

REVISION='representative_basic_v2'
OUTCOME_REVISION='outcome_frame_v1'

def revision(workspace):
    path=Path(workspace)/'assessment_revision.json'
    if not path.exists():return None
    value=json.loads(path.read_text())
    if value['revision'] not in {REVISION,OUTCOME_REVISION} or not value.get('uniform_outcome_blind_correction'):
        raise ValueError('Unknown or unbound Mechanic contract revision')
    return value['revision']


def contract_dir(workspace,case):
    folder=Path(workspace)/'contracts'/case
    active=revision(workspace)
    folder=folder/'revisions'/active if active else folder
    recovery=folder/'source_protocol_recovery.json'
    if recovery.exists():
        from .protocol import sha
        value=json.loads(recovery.read_text())
        if (active!=OUTCOME_REVISION or value.get('version')!='mechanic-source-protocol-recovery.v1'
                or value.get('case_id')!=case or (folder/'frozen.json').exists()
                or value.get('target')!='canonical_source_recovery'):
            raise ValueError('Invalid source protocol recovery; finalized contracts cannot be replaced')
        for name,digest in value['preserved_bindings'].items():
            if sha(Path(name))!=digest:raise ValueError('Preserved contract failure changed')
        return folder/value['target']
    return folder


def result_path(workspace,root):
    return Path(root)/('mechanic_score_'+revision(workspace)+'.json' if revision(workspace) else 'mechanic_score.json')


def publication_dir(workspace):
    return Path(workspace)/'publications'/revision(workspace) if revision(workspace) else Path(workspace)/'publications'


def tables(workspace):
    suffix='_'+revision(workspace) if revision(workspace) else ''
    return ('mechanic_scores'+suffix+'.md','mechanic_comparison'+suffix+'.md')


def task_prefix(workspace):
    value=revision(workspace)
    return 'mechanic_v3_of1_' if value==OUTCOME_REVISION else 'mechanic_v3_rb2_' if value else 'mechanic_v3_'


def fresh_under_contract(qualification,frozen):
    # A new capture in this task may become historical relative to a later
    # corrected contract. Never claim that correction preceded such capture.
    if not qualification.get('new_recording'):return False
    admission=Path(qualification['source'])/'native_capture_admission.json'
    if not admission.is_file():return False
    started=json.loads(admission.read_text())['time']
    return datetime.datetime.fromisoformat(frozen['created']).timestamp() <= started
