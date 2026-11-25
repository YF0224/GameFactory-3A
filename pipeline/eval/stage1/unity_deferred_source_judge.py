"""Judge qualified native evidence independently of exhausted zero-weight diagnostics.

The supplemental review stays incomplete. All accepted source hypotheses and the
failure disclosure are delivered unchanged; mandatory mechanic/static evidence,
final rubric, judge budgets, validators, publication and audit remain unchanged.
"""
from pathlib import Path
import json
import shutil
import time

from . import batch, unity_deferred_source_capture as capture
from .protocol import dump, sha

VERSION = 'whitebox-unity-deferred-source-judge.v1'
RECEIPT = 'deferred_source_judge.json'
DISCLOSURE = 'supplemental_source_diagnostic.json'


def qualify(root):
    from . import source_score_output_recovery as columns
    from .unity_capture_policy import qualify as qualify_capture
    root = Path(root).resolve()
    authorization = capture.verify(root)
    qualify_capture(root)
    batch.validate_operation_plan(root, batch.read(root/'sol_plan.json'), 'unity3d')
    proof = authorization['qualification']
    responses = {}
    for name in proof['accepted_columns']:
        path = columns._response(root, name)
        responses[name] = {'path': str(path.relative_to(root)), 'sha256': sha(path)}
    names = ['deferred_source_capture.json', 'sol_plan.json',
             'recorder_acceptance_binding.json', 'background_record/verification.json',
             'background_record/runner_exit.json', 'background_record/actions_input.json',
             'background_record/source_snapshot.json']
    return {'attempt': str(root), 'capture_authorization_sha256': sha(root/capture.RECEIPT),
            'accepted_responses': responses, 'missing_columns': proof['missing_columns'],
            'bindings': {n: sha(root/n) for n in names},
            'supplemental_status': 'INCOMPLETE_TRANSPORT_TIMEOUT',
            'supplemental_extra_weight': 0, 'source_calls_added': 0,
            'source_budget_replenished': False, 'scoring_semantics_changed': False}


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    if (value.get('version') != VERSION or value.get('qualification') != qualify(root)
            or value.get('supplemental_complete') is not False
            or value.get('final_judge_independent') is not True):
        raise ValueError('Independent recorded judge authorization changed')
    return value


def prepare(root):
    from .unity_queue import published
    from .unity_recovery import attempts, saved_score
    root = Path(root).resolve()
    if (root/RECEIPT).exists():
        return verify(root)
    ident = batch.read(root/'input_manifest.json')['entry']['id']
    if published(root.parents[1], ident) or saved_score(attempts(root.parents[1], ident)):
        raise ValueError('Saved scores protected')
    if any((root/n).exists() for n in ('static_source_scores.json', 'scores.json',
                                     'active_background_judge_attempt.json')):
        raise ValueError('Only a new independent recorded judge may be authorized')
    value = {'version': VERSION, 'qualification': qualify(root),
             'authorized_unix': time.time(), 'supplemental_complete': False,
             'final_judge_independent': True,
             'reason': 'Mandatory static and real record qualify; initial source hypotheses have zero extra weight. Preserve incomplete diagnostic and all accepted contexts while final judge applies unchanged rubric independently.'}
    with (root/RECEIPT).open('x') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    return verify(root)


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha(source) != sha(destination):
            raise ValueError('Preserved diagnostic copy changed: '+str(destination))
    else:
        shutil.copy2(source, destination)


def install(recorded, judged, manifest):
    """Add the raw accepted diagnostics and explicit failure before judge packets."""
    recorded, judged = Path(recorded).resolve(), Path(judged).resolve()
    if not (recorded/RECEIPT).exists():
        if (recorded/capture.RECEIPT).exists():
            raise ValueError('Deferred capture needs explicit independent judge authorization')
        return manifest
    authorization = verify(recorded)
    rows = []
    for name, source in authorization['qualification']['accepted_responses'].items():
        relative = 'recovery_source/supplemental/'+name+'.json'
        _copy(recorded/source['path'], judged/relative)
        rows.append({'id': 'INITIAL_SOURCE_SCORES:'+name, 'path': relative,
                     'type': 'document', 'sha256': source['sha256']})
    _copy(recorded/RECEIPT, judged/'recovery_source'/RECEIPT)
    disclosure = {'version': VERSION, 'source_attempt': str(recorded),
                  'authorization_path': 'recovery_source/'+RECEIPT,
                  'authorization_sha256': sha(recorded/RECEIPT),
                  'supplemental_complete': False,
                  'status': 'INCOMPLETE_TRANSPORT_TIMEOUT',
                  'missing_columns': authorization['qualification']['missing_columns'],
                  'accepted_documents': rows, 'extra_weight': 0,
                  'source_calls_added': 0, 'source_budget_replenished': False,
                  'limits': 'Accepted initial SOURCE-CODE hypotheses are not runtime or visual PASS. Missing supplemental diagnostics have no invented value and are not product FAIL. Final judge must apply every unchanged frozen criterion to original source and native evidence independently. Original failures, requests, schemas, SHA bindings and budgets are preserved in the source authorization.'}
    path = judged/DISCLOSURE
    if path.exists() and batch.read(path) != disclosure:
        raise ValueError('Supplemental diagnostic disclosure changed')
    if not path.exists():
        dump(path, disclosure)
    rows += [{'id': 'SUPPLEMENTAL_SOURCE_DIAGNOSTIC_STATUS', 'path': DISCLOSURE,
              'type': 'document', 'sha256': sha(path)}]
    for row in rows:
        previous = [e for e in manifest['items'] if e['id'] == row['id']]
        if previous and previous != [row]:
            raise ValueError('Conflicting supplemental evidence ID')
        if not previous:
            manifest['items'].append(row)
    return manifest


def require_packet(judged, manifest, text):
    """Fail before any model call if a configured accepted context was omitted."""
    judged = Path(judged)
    path = judged/DISCLOSURE
    if not path.exists():
        return
    value = batch.read(path)
    required = value['accepted_documents'] + [{
        'id': 'SUPPLEMENTAL_SOURCE_DIAGNOSTIC_STATUS', 'path': DISCLOSURE}]
    for row in required:
        expected = [e for e in manifest['items'] if e['id'] == row['id']]
        if len(expected) != 1 or expected[0]['path'] != row['path']:
            raise ValueError('Supplemental context missing from task manifest')
        section = '\nEVIDENCE '+row['id']+'\n'+''.join(
            f'{n}: {line}\n' for n, line in enumerate((judged/row['path']).read_text().splitlines(), 1))
        from .document_wire import verify_section
        if section not in text and not verify_section(text,judged/row['path'],row['id']):
            raise ValueError('Full supplemental context not delivered: '+row['id'])


def disclosure(judged):
    """Revalidate source lineage, immutable copies and actual judge delivery."""
    judged = Path(judged).resolve()
    path = judged/DISCLOSURE
    if not path.exists():
        origin = judged/'recorded_capture_provenance.json'
        if origin.exists() and (Path(batch.read(origin)['source_attempt'])/RECEIPT).exists():
            raise ValueError('Supplemental failure disclosure missing')
        return None
    value = batch.read(path)
    recorded = Path(value['source_attempt'])
    if batch.read(judged/'recorded_capture_provenance.json')['source_attempt'] != str(recorded):
        raise ValueError('Supplemental disclosure source differs from native capture')
    authorization = verify(recorded)
    if (value.get('version') != VERSION or value.get('supplemental_complete') is not False
            or value.get('status') != 'INCOMPLETE_TRANSPORT_TIMEOUT'
            or value.get('extra_weight') != 0 or value.get('source_calls_added') != 0
            or value.get('source_budget_replenished') is not False
            or value.get('missing_columns') != authorization['qualification']['missing_columns']
            or value.get('authorization_path') != 'recovery_source/'+RECEIPT
            or value.get('authorization_sha256') != sha(recorded/RECEIPT)):
        raise ValueError('Supplemental disclosure contract changed')
    auth_copy = judged/'recovery_source'/RECEIPT
    if not auth_copy.is_file() or sha(auth_copy) != sha(recorded/RECEIPT):
        raise ValueError('Supplemental source authorization copy changed')
    expected = []
    for name, source in authorization['qualification']['accepted_responses'].items():
        row = {'id': 'INITIAL_SOURCE_SCORES:'+name,
               'path': 'recovery_source/supplemental/'+name+'.json',
               'type': 'document', 'sha256': source['sha256']}
        destination = judged/row['path']
        if not destination.is_file() or sha(destination) != sha(recorded/source['path']):
            raise ValueError('Preserved supplemental context missing or changed')
        expected.append(row)
    if value.get('accepted_documents') != expected:
        raise ValueError('Supplemental accepted document bindings changed')
    required = expected + [{'id': 'SUPPLEMENTAL_SOURCE_DIAGNOSTIC_STATUS',
                           'path': DISCLOSURE, 'type': 'document', 'sha256': sha(path)}]
    manifest = batch.read(judged/'evidence_manifest.json')
    for row in required:
        if [e for e in manifest['items'] if e['id'] == row['id']] != [row]:
            raise ValueError('Supplemental diagnostic documents missing from manifest')
    prompts = sorted((judged/'model_calls').glob('*/prompt.txt'))
    if not prompts:
        raise ValueError('No actual final judge delivery')
    for prompt in prompts:
        text = prompt.read_text()
        for row in required:
            section = '\nEVIDENCE '+row['id']+'\n'+''.join(
                f'{n}: {line}\n' for n, line in enumerate((judged/row['path']).read_text().splitlines(), 1))
            from .document_wire import verify_section
            if section not in text and not verify_section(text,judged/row['path'],row['id']):
                raise ValueError('Full supplemental context not delivered: '+str(prompt)+' '+row['id'])
    return {'status': value['status'], 'supplemental_complete': False,
            'missing_columns': value['missing_columns'], 'extra_weight': 0,
            'path': DISCLOSURE, 'sha256': sha(path),
            'authorization_sha256': sha(recorded/RECEIPT),
            'accepted_documents': value['accepted_documents'], 'actual_prompts_checked': len(prompts)}


def run(output, root):
    """Caller holds coordinator and preflights acceptance/disk; never re-record."""
    from . import unity_single
    output, root = Path(output).resolve(), Path(root).resolve()
    if batch.read(output/'configuration.json').get('save_source_code_scores') is not True:
        raise ValueError('Configured source diagnostics must remain enabled')
    if batch.read(output/'single_state.json')['attempt'] != str(root):
        raise ValueError('Saved capture identity changed')
    verify(root)
    return unity_single.complete_capture(output, root)
