"""Show saved judge scores immediately, explicitly pending independent audit.

These rows do not create a formal publication, effective result or verified audit.
The original judge files and cleanup receipts are retained without modification.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import copy
import fcntl
import json
import math
import os
import time

from .protocol import COLUMNS, dump, sha

VERSION = 'whitebox-pending-audit-publication.v1'
POLICY_VERSION = 'whitebox-deferred-audit-policy.v1'
STATUS = 'SCORED_PENDING_AUDIT'


def read(path):
    return json.loads(Path(path).read_text())


def cleanup_source(attempt):
    """Resolve the existing SHA-bound cleanup; never synthesize a receipt."""
    attempt = Path(attempt)
    canonical = attempt/'runtime/native_cleanup.json'
    required = ('input_cleanup', 'view_cleanup', 'process_cleanup')
    if canonical.is_file():
        cleanup = read(canonical)
        bindings = {'runtime/native_cleanup.json': sha(canonical)}
        origin = {'kind': 'canonical-native-cleanup', 'sources': bindings}
    elif (attempt/'runtime/multisession_sources.json').is_file():
        from . import unity_native_pair_sources, event_wire_recovery
        proof = unity_native_pair_sources.verify(attempt)
        if proof.get('valid') is not True or proof.get('roles') != ['A', 'B']:
            raise ValueError('Native pair cleanup requires fully verified original sources')
        source = Path(proof.get('recovery_source_attempt', str(attempt)))
        source_receipt = source/'runtime/multisession_sources.json'
        contract = read(source_receipt)
        cleanup_path = attempt/'runtime/cleanup.json'
        if sha(cleanup_path) != contract['product']['bindings']['cleanup.json']:
            raise ValueError('Native pair cleanup differs from frozen capture source')
        cleanup = read(cleanup_path)
        if cleanup.get('source_unchanged') is not True:
            raise ValueError('Native pair cleanup source changed')
        bindings = {name:sha(attempt/name) for name in
                    ('runtime/cleanup.json', 'runtime/multisession_sources.json')}
        if (attempt/event_wire_recovery.RECEIPT).is_file():
            bindings[event_wire_recovery.RECEIPT] = sha(attempt/event_wire_recovery.RECEIPT)
        origin = {'kind':'source-bound-native-pair-cleanup',
                  'sources':{**bindings, str(source_receipt):sha(source_receipt),
                             str(source/'runtime/cleanup.json'):sha(source/'runtime/cleanup.json')}}
    else:
        from . import native_clock_binding
        provenance_path = attempt/'recorded_capture_provenance.json'
        clock_path = attempt/native_clock_binding.RECEIPT
        if not provenance_path.is_file() or not clock_path.is_file():
            raise ValueError('Missing canonical cleanup or proven native capture cleanup source')
        # This rechecks reviewed recorder sources, immutable original channels,
        # native verification and the exact installed clock declaration.
        native_clock_binding.validate(attempt, read(attempt/'evidence_manifest.json'))
        provenance = read(provenance_path)
        source = Path(provenance['source_attempt']).resolve()/'background_record'
        verification, runner = source/'verification.json', source/'runner_exit.json'
        if (sha(verification) != provenance.get('capture_verification_sha256')
                or sha(runner) != provenance.get('cleanup_verification_sha256')):
            raise ValueError('Native capture cleanup source SHA changed')
        verdict, exit_receipt = read(verification), read(runner)
        if (verdict.get('ok') is not True
                or exit_receipt.get('cleanup_verified') is not True
                or exit_receipt.get('policy_violations') != []
                or exit_receipt.get('error') is not None):
            raise ValueError('Native capture source cleanup is not verified')
        cleanup = verdict.get('checks', {})
        bindings = {'recorded_capture_provenance.json': sha(provenance_path),
                    native_clock_binding.RECEIPT: sha(clock_path)}
        origin = {'kind': 'source-bound-native-capture-verification',
                  'sources': {**bindings, str(verification): sha(verification),
                              str(runner): sha(runner)}}
    if not all(cleanup.get(k) is True for k in required):
        raise ValueError('Pending score still requires complete owned-Unity cleanup')
    return bindings, origin


def deferred(config):
    path = Path(config['batch'])/'unity_audit_policy.json'
    if not path.is_file():
        return False
    policy = read(path)
    if policy.get('version') != POLICY_VERSION or policy.get('mode') not in {'deferred', 'inline'}:
        raise ValueError('Unknown explicit audit policy')
    return policy['mode'] == 'deferred'


def _registry(batch):
    path = batch/'pending_audits.json'
    return read(path) if path.is_file() else {'version':VERSION, 'entries':{}}


def _row(text, label):
    rows = [line for line in text.splitlines() if line.startswith('| '+label+' |')]
    if len(rows) != 1:
        raise ValueError('Expected exactly one pending-score row: '+label)
    return rows[0]


def _summary_label(method, policy, tier):
    return method+' / '+policy+' / '+tier+' / 未审计'


def summary_rows(text, registry, model, policy, tier):
    """Keep unaudited means apart from all formal-policy and historical means."""
    from .targeted_publication import upsert_policy_row
    selected = [(ident, row) for ident,row in registry['entries'].items()
                if row.get('status') == STATUS and row['scoring_protocol'] == policy and row['tier'] == tier]
    for method in (model, '全部'):
        label = _summary_label(method, policy, tier)
        group = [row for ident,row in selected if method == '全部' or ident.startswith(method+'__')]
        if group:
            values = [row['score'] for row in group]
            replacement = f'| {label} | — | — | {len(group)} | {sum(values)/len(values):.2f} | — | — |'
            text = upsert_policy_row(text, label, replacement, allow_missing=True)
        else:
            text = ''.join(line for line in text.splitlines(keepends=True) if not line.startswith('| '+label+' |'))
    return text


def authorized_pending(attempt, batch, score, entry):
    """Allow only an exact, SHA-bound pending row to be upgraded after real audit."""
    registry = _registry(batch)
    row = registry['entries'].get(entry['id'])
    if not row or row.get('status') != STATUS:
        return None
    if (row['attempt'] != str(attempt.relative_to(batch))
            or row['score_sha256'] != sha(attempt/'scores.json')
            or row['score'] != score['overall_score']):
        raise ValueError('Pending score source changed; do not replace the visible result')
    for name, expected in row['rows'].items():
        if _row((batch/name).read_text(), row['label']) != expected:
            raise ValueError('Pending row was changed independently: '+name)
    return row


def register_native_scope(batch, *, model, authorization):
    """Freeze explicit Opus/Astra S authorization against the full inventory.

    Does not authorize another model, engine, tier, or protocol. Existing frozen
    scope is immutable; caller must create a separate batch for another model.
    """
    from . import batch as evaluator, endpoint_sparse
    batch = Path(batch).resolve()
    if model not in {'Opus','Astra'} or not isinstance(authorization,str) or not authorization.strip():
        raise ValueError('Explicit authorized native model and user instruction required')
    with (batch/'.targeted_publication.lock').open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        inventory=batch/'inventory.json';entries=read(inventory)['entries']
        if not entries or len({e['id'] for e in entries}) != len(entries):
            raise ValueError('Native scope requires unique frozen inventory entries')
        protocols={}
        for entry in entries:
            if (entry['id'].split('__')[0] != model or entry.get('method') != model
                    or entry.get('tier') != 'S' or entry.get('actual_engine') not in {'godot','three_js',None}
                    or entry.get('planning_policy') != 'tiered-core-v1'
                    or entry.get('evaluation_policy') != endpoint_sparse.VERSION):
                raise ValueError('Frozen inventory is outside explicit native S scope')
            protocol=batch/'protocols'/entry['case_id']/'rubric.json'
            if evaluator.verify_protocol(batch,entry) != read(protocol):
                raise ValueError('Native authorization requires frozen baseline protocol')
            protocols[entry['case_id']]=sha(protocol)
        value={'version':'whitebox-native-pending-scope.v1','batch':str(batch),
               'inventory_sha256':sha(inventory),'authorization':authorization,
               'audit_status':'PENDING','model':model,'engines':['godot','three_js'],
               'tier':'S','protocol':endpoint_sparse.VERSION,'protocol_sha256':protocols}
        path=batch/'native_pending_scope.json'
        if path.exists():
            if read(path) != value:raise ValueError('Existing native authorization is immutable')
            return read(path)
        with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
        return value


def authorized_native_scope(batch, entry, proto, *, attempt=None):
    """Explicit immutable per-batch opt-in; no global engine/model expansion."""
    path = Path(batch)/'native_pending_scope.json'
    if not path.is_file():
        return None
    value = read(path)
    inventory = Path(batch)/'inventory.json'
    if (value.get('version') != 'whitebox-native-pending-scope.v1'
            or value.get('batch') != str(Path(batch).resolve())
            or value.get('inventory_sha256') != sha(inventory)
            or not value.get('authorization') or value.get('audit_status') != 'PENDING'
            or value.get('model') not in {'Opus', 'Astra'}
            or value.get('engines') != ['godot', 'three_js']
            or value.get('tier') != 'S'
            or value.get('protocol') != 'whitebox-mechanic10-50-100.v2'):
        raise ValueError('Invalid explicit native pending publication scope')
    originals = [row for row in read(inventory)['entries'] if row['id'] == entry['id']]
    if len(originals) == 1:
        frozen_entry = copy.deepcopy(originals[0])
        frozen_entry.setdefault('planning_policy', 'core12-v1' if frozen_entry.get('core12_plan_timeout_seconds') else 'tiered-core-v1')
        if frozen_entry['planning_policy'] == 'tiered-core-v1':
            from .asset_reservation import DEFAULT_VERSION
            frozen_entry.setdefault('asset_reservation_policy', DEFAULT_VERSION)
    if (len(originals) != 1 or frozen_entry != entry
            or entry['id'].split('__')[0] != value['model']
            or entry.get('actual_engine') not in value['engines']
            or entry.get('tier') != value['tier']
            or proto.get('planning_contract', {}).get('tier') != value['tier']):
        raise ValueError('Pending native entry differs from frozen authorized inventory')
    protocol = Path(batch)/'protocols'/entry['case_id']/'rubric.json'
    if value.get('protocol_sha256', {}).get(entry['case_id']) != sha(protocol):
        raise ValueError('Pending native baseline protocol differs from frozen authorization')
    from . import batch as evaluator, core12
    if evaluator.verify_protocol(Path(batch), entry) != read(protocol):
        raise ValueError('Pending native baseline derivation changed')
    if attempt is None:
        raise ValueError('Native publication requires a verified frozen attempt')
    attempt = Path(attempt).resolve()
    if attempt.parent.name not in {'runs', 'recovery_runs'} or attempt.parents[1] != Path(batch).resolve():
        raise ValueError('Native pending attempt belongs to another batch')
    if read(attempt/'input_manifest.json')['entry'] != entry:
        raise ValueError('Native pending manifest entry differs')
    evaluator.verify_inputs(attempt)
    if core12.verify_attempt(attempt, entry['actual_engine']) != proto:
        raise ValueError('Pending native derived attempt protocol changed')
    return {'path': str(path), 'sha256': sha(path), 'authorization':value['authorization']}


def publish(attempt):
    """Write one numeric result to the existing views, with 未审计 on every row."""
    from .targeted_publication import diagnostic, encoded, replace_case, protect_formal_row
    attempt = Path(attempt).resolve()
    batch = attempt.parents[1]
    if attempt.parent.name not in {'runs', 'recovery_runs'}:
        raise ValueError('Pending attempt must belong to the batch runs/recovery_runs')
    with (batch/'.targeted_publication.lock').open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest = read(attempt/'input_manifest.json')
        entry = manifest['entry']; score = read(attempt/'scores.json')
        proto = read(attempt/'input/pilot_rubric.json')
        ident = entry['id']; model = ident.split('__')[0]
        scope_authorization = None
        if entry.get('actual_engine') != 'unity3d' or model not in {'Astra','GLM','Sol'}:
            scope_authorization = authorized_native_scope(batch, entry, proto, attempt=attempt)
            if scope_authorization is None:
                raise ValueError('Deferred publication is outside the explicitly authorized scope')
        label = model+' / '+entry['case_id'].split('_')[0]
        values = [score.get('columns',{}).get(c,{}).get('score') for c in COLUMNS]
        numeric = lambda v: isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and 0 <= v <= 100
        if (score.get('valid') is not True or not all(numeric(v) for v in values)
                or not numeric(score.get('overall_score'))
                or abs(sum(values)/8-score['overall_score']) > .011):
            raise ValueError('No complete valid saved eight-column judge score')
        if read(attempt/'status.json').get('status') not in {'JUDGED','COMPLETE'}:
            raise ValueError('Judge has not completed')
        if (attempt/'take_invalidated.json').exists():
            raise ValueError('Invalidated capture cannot be shown as a scored result')
        cleanup_bindings, cleanup_origin = cleanup_source(attempt)
        from .unity_deferred_source_judge import disclosure as supplemental_disclosure
        supplemental = supplemental_disclosure(attempt)
        formal = batch/'versioned_publications.json'
        if formal.is_file() and ident in read(formal).get('entries',{}):
            raise ValueError('Existing formal publication protected')
        registry = _registry(batch)
        superseded = None
        previous = registry['entries'].get(ident)
        if previous and previous.get('attempt') != str(attempt.relative_to(batch)):
            from .native_slot_recovery import authorize_pending_replacement
            superseded = authorize_pending_replacement(attempt, previous)
            existing = None
        else:
            existing = authorized_pending(attempt,batch,score,entry)
        if existing:
            # An interrupted receipt write is recoverable without touching judge evidence.
            dump(attempt/'pending_publication_receipt.json', existing)
            return {'status':STATUS, 'score':existing['score'], 'attempt':str(attempt),
                    'valid':False, 'provisional':True, 'audit_status':'PENDING'}
        if superseded is None:
            for name in ('scores.md','score_new.md'):
                protect_formal_row((batch/name).read_text(),label)
        from .unity_delivery_disclosure import describe
        disclosure = describe(entry)
        policy=score['scoring_protocol']; tier=proto['planning_contract']['tier']
        status=f'{STATUS}（未审计；{policy}；tiered-core-v1；{tier}；已保存 judge，待后续独立审计）'
        if disclosure:
            status=status[:-1]+'；授权隔离修复交付）'
        if supplemental:
            status=status[:-1]+'；补充源码诊断未完成）'
        formal_cells=[f'{v:.2f}' for v in values]+[f"{score['overall_score']:.2f}"]
        diag_cols, diag_total, details = diagnostic(score,proto)
        diag_cells=['—' if diag_cols[c] is None else f'{diag_cols[c]:.2f}' for c in COLUMNS]
        diag_cells+=['—' if diag_total is None else f'{diag_total:.2f}']
        payloads={}; rows={}
        for name in ('scores.md','score_new.md','score_verify.md','final_report.md'):
            if not (batch/name).is_file():
                if name=='final_report.md': continue
                raise ValueError('Missing existing score view: '+name)
            before=(batch/name).read_text()
            text=replace_case(before,label,diag_cells if name=='score_verify.md' else formal_cells,
                              status+('；verified-only 诊断同样未审计' if name=='score_verify.md' else ''))
            rows[name]=_row(text,label)
            payloads[name]=text
        record={'status':STATUS, 'audit_status':'PENDING', 'label':label,
                'attempt':str(attempt.relative_to(batch)), 'score':score['overall_score'],
                'columns':copy.deepcopy(score['columns']), 'score_sha256':sha(attempt/'scores.json'),
                'scoring_protocol':policy, 'tier':tier, 'rows':rows,
                'diagnostic_columns':diag_cols, 'diagnostic_total':diag_total,
                'source_bindings':{name:sha(attempt/name) for name in (
                    'input_manifest.json','input/pilot_rubric.json','rubric_verdicts.json',
                    'evidence_manifest.json','status.json')} | cleanup_bindings,
                'cleanup_source': cleanup_origin,
                'at':time.time(), 'formal_effective_valid':False,
                'authorization':'User 2026-10-29: 先填上再说，未审计后面标一下，后面我们再审计'}
        if supplemental:
            record['supplemental_source_diagnostic'] = supplemental
            record['source_bindings'][supplemental['path']] = supplemental['sha256']
        if scope_authorization:
            record['scope_authorization'] = scope_authorization
            record['authorization'] = scope_authorization['authorization']
        if disclosure:
            record['delivery_disclosure'] = disclosure
        if superseded is not None:
            record['engineering_correction'] = superseded
        registry['entries'][ident]=record
        registry['updated_unix']=time.time()
        for name,text in payloads.items():
            payloads[name]=summary_rows(text,registry,model,policy,tier).encode()
        # Diagnostic arithmetic is visible but excluded from audited diagnostic aggregates.
        provenance_path=batch/'score_verify.provenance.json'
        if provenance_path.is_file():
            provenance=read(provenance_path)
            provenance.setdefault('pending_audit_entries',{})[label]={
                'attempt':str(attempt), 'score_sha256':record['score_sha256'],
                'columns':diag_cols, 'total':diag_total, 'audit_status':'PENDING',
                'formal_effective_valid':False, 'details':details}
            if disclosure:
                provenance['pending_audit_entries'][label]['delivery_disclosure'] = disclosure
            payloads['score_verify.provenance.json']=encoded(provenance)
        payloads['pending_audits.json']=encoded(registry)
        for name in ('scores.md',):
            lines=payloads[name].decode().splitlines()
            starts=[i for i,line in enumerate(lines) if line.startswith('|') and (i==0 or not lines[i-1].startswith('|'))]
            if len(starts)!=2: raise ValueError('scores.md must retain exactly two tables')
        revision=batch/'pending_score_revisions'/(ident+'_'+str(time.time_ns()))
        revision.mkdir(parents=True)
        before={name:sha(batch/name) if (batch/name).exists() else None for name in payloads}
        for name,body in payloads.items():
            if (batch/name).exists(): (revision/('before_'+name)).write_bytes((batch/name).read_bytes())
            (revision/name).write_bytes(body)
        dump(revision/'changes.json',{'scope':ident,'attempt':str(attempt),'audit_status':'PENDING',
            'before_sha256':before,'after_sha256':{name:sha(revision/name) for name in payloads}})
        for name,expected in before.items():
            if (sha(batch/name) if (batch/name).exists() else None)!=expected:
                raise ValueError('Concurrent pending publication changed '+name)
        for name,body in payloads.items():
            temp=batch/(name+'.pending.tmp'); temp.write_bytes(body); os.replace(temp,batch/name)
        dump(attempt/'pending_publication_receipt.json',record)
        return {'status':STATUS,'attempt':str(attempt),'score':score['overall_score'],
                'valid':False,'provisional':True,'audit_status':'PENDING','finished_unix':time.time()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt',type=Path,required=True)
    args=parser.parse_args(argv)
    print(json.dumps(publish(args.attempt),ensure_ascii=False))


if __name__=='__main__': main()
