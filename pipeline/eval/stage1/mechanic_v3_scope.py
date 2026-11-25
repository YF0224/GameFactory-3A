"""Explicit, SHA-bound supplemental selection for the outcome Mechanic revision.

The original paired inventory is never rewritten. A separately frozen selection
can add original deliveries and restrict future work without discarding results.
"""
from pathlib import Path
import copy
from .protocol import sha
from .codex import load_plan_json

SCOPE_VERSION = 'mechanic-v3-opus-uploader-scope.v1'


def load_inventory(workspace):
    workspace = Path(workspace).resolve()
    if (workspace/'full_s_scope.json').exists():
        from .mechanic_v3_full_scope import load
        return load(workspace)
    original = load_plan_json(workspace/'inventory.json')
    pointer = workspace/'active_scope.json'
    if not pointer.exists():
        return load_diagnostics(workspace, original)
    active = load_plan_json(pointer)
    if active.get('version') != SCOPE_VERSION:
        raise ValueError('Unknown Mechanic selection version')
    path = Path(active['inventory'])
    if not path.is_absolute() or not path.resolve().is_relative_to(workspace/'scopes'):
        raise ValueError('Scoped inventory must be retained inside workspace/scopes')
    if sha(path) != active['sha256']:
        raise ValueError('Frozen scoped inventory changed')
    scope = load_plan_json(path)
    if scope.get('version') != SCOPE_VERSION:
        raise ValueError('Unknown frozen selection version')
    for name, digest in scope['bindings'].items():
        if sha(Path(name)) != digest:
            raise ValueError('Frozen scope source changed: '+name)
    if scope['original_inventory_sha256'] != sha(workspace/'inventory.json'):
        raise ValueError('Original paired inventory changed')
    selected = scope['selected_identities']
    if not selected or len(selected) != len(set(selected)):
        raise ValueError('Selection requires unique explicit identities')
    result = copy.deepcopy(original)
    entries = {row['entry']['id']: row for row in result['entries']}
    extra = scope['supplemental_entries']
    if len(extra) != len({row['entry']['id'] for row in extra}):
        raise ValueError('Duplicate supplemental identity')
    for row in extra:
        entry = row['entry']
        if entry['id'] in entries:
            raise ValueError('Supplement cannot replace a frozen original identity')
        if (entry['method'] != 'Opus' or entry['tier'] != 'M'
                or entry['actual_engine'] not in {'godot', 'three_js'}
                or not row['in_scope'] or not entry.get('project')):
            raise ValueError('Supplement requires explicitly selected original Opus M delivery')
        entries[entry['id']] = row
        result['entries'].append(row)
    for identity in selected:
        if identity not in entries:
            raise ValueError('Selected identity has no frozen original delivery')
        entry = entries[identity]['entry']
        if (entry['method'] != 'Opus' or entry['actual_engine'] not in {'godot', 'three_js'}
                or entry['case_id'] not in scope['uploaded_case_ids']):
            raise ValueError('Selection is outside the uploader/engine scope')
    if set(row['entry']['id'] for row in extra) - set(selected):
        raise ValueError('Supplemental original must be in explicit active selection')
    result['active_selection'] = selected
    result['single_model_contract_cases'] = [row['entry']['case_id'] for row in extra]
    result['scope_binding'] = {'path': str(path), 'sha256': sha(path)}
    result['primary_selection'] = selected.copy()
    return load_diagnostics(workspace, result)



def load_diagnostics(workspace, inventory):
    """Load separately authorized matched samples, preserving each frozen scope."""
    result = _load_matched_diagnostic(workspace, inventory,
        pointer_name='active_diagnostics.json',
        version='mechanic-v3-matched-glm-diagnostics.v1', method='GLM')
    return _load_matched_diagnostic(workspace, result,
        pointer_name='active_sol_diagnostics.json',
        version='mechanic-v3-matched-sol-diagnostics.v1', method='Sol')


def _load_matched_diagnostic(workspace, inventory, *, pointer_name, version, method):
    """Require the same pre-frozen pair, requirement, rubric and author binding."""
    pointer=Path(workspace)/pointer_name
    if not pointer.exists():return inventory
    from . import mechanic_v3_revision as revisions
    active=load_plan_json(pointer)
    if active.get('version')!=version:raise ValueError('Unknown diagnostic selection')
    path=Path(active['inventory'])
    if not path.is_absolute() or not path.resolve().is_relative_to(Path(workspace)/'scopes'):
        raise ValueError('Diagnostic scope must be retained inside workspace/scopes')
    if sha(path)!=active['sha256']:raise ValueError('Diagnostic scope changed')
    config=load_plan_json(path)
    if config.get('version')!=version or config.get('revision')!='outcome_frame_v1':
        raise ValueError('Explicit outcome diagnostic authorization required')
    if config['original_inventory_sha256']!=sha(Path(workspace)/'inventory.json'):
        raise ValueError('Original paired diagnostic inventory changed')
    for name,digest in config['bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Diagnostic source binding changed: '+name)
    result=copy.deepcopy(inventory)
    existing={row['entry']['id']:row for row in result['entries']}
    diagnostic=[]
    for row in config['entries']:
        entry=row['entry'];case=entry['case_id'];identity=entry['id']
        if (identity in existing or identity in diagnostic or entry['method']!=method
                or entry['tier']!='S' or entry['actual_engine'] not in {'godot','three_js'}
                or not row['in_scope'] or not entry.get('project')):
            raise ValueError('Diagnostic requires unique original matched '+method+' S delivery')
        pair=[r['entry'] for r in result['entries'] if r['entry']['case_id']==case
              and r['entry']['method'] in {'Astra','Opus'}]
        if len(pair)!=2 or {e['method'] for e in pair}!={'Astra','Opus'}:
            raise ValueError('Diagnostic requires both frozen comparison identities')
        for e in pair:
            if any(entry[k]!=e[k] for k in ('requirement_sha256','frozen_sha256','tier')):
                raise ValueError('Diagnostic must share the frozen requirement and rubric')
        folder=revisions.contract_dir(Path(workspace),case)
        for name in ('contract.json','frozen.json'):
            file=folder/name
            if config['bindings'].get(str(file.resolve()))!=sha(file):
                raise ValueError('Diagnostic requires the same bound outcome contract')
        for key in ('requirement','frozen_rubric','project_marker'):
            file=Path(entry[key])
            if config['bindings'].get(str(file.resolve()))!=sha(file):
                raise ValueError('Diagnostic original source must be bound: '+key)
        diagnostic.append(identity);result['entries'].append(row)
    if not diagnostic:raise ValueError('Diagnostic selection cannot be empty')
    selected=result.get('active_selection',[r['entry']['id'] for r in inventory['entries']])
    result['active_selection']=selected+diagnostic
    result['diagnostic_selection']=result.get('diagnostic_selection',[])+diagnostic
    result.setdefault('diagnostic_bindings',{})[method]={'path':str(path),'sha256':sha(path)}
    if method=='GLM':result['diagnostic_binding']={'path':str(path),'sha256':sha(path)}
    return result


def allowed_identities(inventory, phase):
    selected = inventory.get('active_selection')
    rows = inventory['entries']
    if selected is not None:
        rows = [row for row in rows if row['entry']['id'] in selected]
    return {row['entry']['case_id' if phase == 'freeze' else 'id'] for row in rows}


def single_model_authorized(inventory, case, rows):
    return (case in inventory.get('single_model_contract_cases', [])
            and bool(inventory.get('scope_binding')) and len(rows) == 1
            and rows[0]['entry']['method'] == 'Opus'
            and rows[0]['entry']['tier'] == 'M'
            and rows[0]['entry']['id'] in inventory.get('active_selection', []))


def rebuild_score_table(workspace):
    """Publish a selected single-column view, retaining all historic publications."""
    from . import mechanic_v3_revision as revisions
    from .protocol import dump
    import os
    workspace=Path(workspace)
    if not (workspace/'active_scope.json').exists():
        return
    inventory=load_inventory(workspace)
    selected=set(inventory.get('primary_selection',inventory['active_selection']))
    lines=['# Opus zengbohan 上传组 Mechanic v3', '',
        '范围：G020–G060 中已核上传者的实际 Godot / Three.js 原始交付，共21项（S12 / M9）。',
        '修订 outcome_frame_v1；仅Mechanic。已发布结果均 SCORED_PENDING_AUDIT（未审计）；未测项目不补零。', '',
        '| 身份 | 等级 | 实际引擎 | Mechanic | 状态 | 实录 |', '|---|---|---|---:|---|---|']
    scores=[]
    for row in inventory['entries']:
        e=row['entry']
        if e['id'] not in selected:continue
        path=revisions.publication_dir(workspace)/(e['id']+'.json')
        if path.exists():
            value=load_plan_json(path)
            scores.append(value['mechanic_score'])
            lines.append(f"| {e['id']} | {e['tier']} | {e['actual_engine']} | {value['mechanic_score']:.2f} | SCORED_PENDING_AUDIT（未审计） | {value['recording_notice']} |")
        else:
            lines.append(f"| {e['id']} | {e['tier']} | {e['actual_engine']} | — | 尚未出分 | — |")
    if scores:
        lines+=['',f'已有有效成绩 {len(scores)}/{len(selected)}；已出分样本均分 {sum(scores)/len(scores):.2f}。其余未测，不计入分母。']
    target=workspace/'mechanic_scores_opus_zengbohan_outcome_frame_v1.md'
    tmp=target.with_suffix('.tmp');tmp.write_text('\n'.join(lines)+'\n');os.replace(tmp,target)
