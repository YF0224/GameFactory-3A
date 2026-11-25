"""Read-only reuse of a qualified baseline's exact source-only v4 findings.

The frozen evaluator profile supplies the parent. Runtime judgments and scores
are never supplied to the new judge. Original accepted calls stay at their paths.
"""
from pathlib import Path
import hashlib
import json
from . import evaluation_model_profile as models
from . import gameness_v4 as policy, gameness_v3_static as static
from . import gameness_v3_runtime as runtime, mechanic_v3_runner as runner
from .codex import READ_ONLY_EVAL_INSTRUCTIONS, saved_model_response
from .protocol import sha


def validate_review(review_path, protocol, contract, frozen, files, project, identity):
    """Rebuild and validate the actual original static requests without writes."""
    root = review_path.parent
    review = runner.read(review_path)
    binding = runner.read(root / 'source_binding.json')
    expected_sources = {str(p): sha(p) for p in files}
    expected_ids = {'SRC:' + str(p.relative_to(project)): sha(p) for p in files}
    if (review.get('identity') != identity or review.get('source_binding') != binding
            or binding.get('identity') != identity
            or binding.get('author_sources') != expected_sources
            or binding.get('source_sha256_by_id') != expected_ids
            or binding.get('contract_sha256') != frozen['contract_sha256']
            or binding.get('scoring_protocol') != policy.VERSION):
        raise ValueError('Reused static review original/source/contract differs')
    manifest = runner.read(root / 'source_manifest.json')
    if {i['id']: i['sha256'] for i in manifest['items']} != expected_ids:
        raise ValueError('Reused static source manifest incomplete')
    body, rules, sources = static.source_packet(root, manifest)
    if runner.read(root / 'citation_rules.json') != rules:
        raise ValueError('Reused static citation rules differ')
    # Corrected static calls require their own explicit recovery validator.
    if review.get('source_review_recoveries'):
        raise ValueError('Reused corrected static review needs recovery qualification')
    checks = {}
    specs = policy.criteria(protocol)
    for start in range(0, len(specs), 10):
        chunk = specs[start:start + 10]
        name = f'gameness_source_v1_{start // 10 + 1:02d}'
        call = root / 'model_calls' / name
        actual = runner.read(root / 'requests' / name / 'actual_delivery.json')
        prompt = (static.PROMPT + '\nEXACT SCHEMA FILE: ' + str(call / 'schema.json')
                  + '\nFROZEN CONTRACT:\n' + json.dumps(contract, ensure_ascii=False)
                  + '\nCOMPLETE AUTHOR SOURCES:\n' + body
                  + '\nCHECKS:\n' + json.dumps(chunk, ensure_ascii=False))
        submitted = (READ_ONLY_EVAL_INSTRUCTIONS + prompt).encode()
        schema, _ = static.group(static.schema(chunk, rules))
        invocation = runner.read(call / 'invocation.json')
        command = invocation['command']
        if (not (call / 'accepted_response.json').is_file()
                or invocation.get('exit_code') != 0 or '--model' not in command
                or command[command.index('--model') + 1] != models.DEFAULT
                or '--image' in command or actual.get('images') != []
                or (call / 'prompt.txt').read_bytes() != submitted
                or actual.get('prompt_sha256') != hashlib.sha256(submitted).hexdigest()
                or runner.read(call / 'schema.json') != schema
                or actual.get('complete_author_sources') != sources
                or actual.get('criterion_ids') != [s['id'] for s in chunk]
                or actual.get('contract_sha256') != frozen['contract_sha256']
                or actual.get('source_binding_sha256') != sha(root / 'source_binding.json')
                or actual.get('all_author_sources_delivered') is not True
                or actual.get('runtime_evidence_supplied') is not False
                or actual.get('old_scores_supplied') is not False):
            raise ValueError('Reused static actual delivery differs: ' + name)
        raw = runner.read(saved_model_response(root, name))
        static.validate(root, manifest, rules, contract, chunk, raw)
        checks.update(raw['checks'])
    if checks != review['checks']:
        raise ValueError('Reused static findings differ from accepted calls')
    return review


def prepare(workspace, row):
    identity = row['entry']['id']
    profile = models.publication_profile(workspace / 'runs' / identity, 'Gameness')
    if profile is None:
        return None
    if runtime.workspace_policy(workspace).VERSION != policy.VERSION:
        raise ValueError('Reassessment source reuse requires original-check v4')
    from .two_column_sync import verified
    from .mechanic_v3_full_scope import same_original
    from .gameness_v4_saved_publication import revalidate
    baseline = profile['baseline']
    parent = Path(baseline['workspace'])
    _, selected, _ = verified(parent, identity, 'Gameness')
    selected = selected['columns']['Gameness']
    if any(selected[k] != baseline[k] for k in ('score', 'protocol', 'revision', 'status', 'publication', 'publication_sha256', 'workspace')):
        raise ValueError('Reassessment baseline publication differs')
    parent_inventory = runtime.load(parent)
    parent_row = next(r for r in parent_inventory['entries'] if r['entry']['id'] == identity)
    if not parent_row['in_scope'] or not same_original(row['entry'], parent_row['entry']):
        raise ValueError('Reassessment source identity differs')
    parent_root, _ = revalidate(parent, parent_row)
    case = row['entry']['case_id']
    folder = runtime.contract_dir(parent, case)
    contract = runtime.freeze(parent, case, parent_inventory)
    frozen = runner.read(folder / 'frozen.json')
    protocol, _ = runtime.source_protocol(row, workspace)
    policy.validate_contract(protocol, contract)
    parent_protocol, _ = runtime.source_protocol(parent_row, parent)
    if policy.criteria(protocol) != policy.criteria(parent_protocol):
        raise ValueError('Reassessment original criteria differ')
    bound = runner.read(parent_root / 'gameness_source_review_binding.json')
    review_path = Path(bound['path'])
    project = Path(row['entry']['project']).resolve()
    review = validate_review(review_path, protocol, contract, frozen,
                             runtime.source_files(project), project, identity)
    dest = runtime.contract_dir(workspace, case)
    dest.mkdir(parents=True, exist_ok=True)
    bindings = {str(Path(baseline['publication'])): baseline['publication_sha256'],
                **models.binding(workspace / 'runs' / identity)}
    for name in ('contract.json', 'frozen.json', 'source_binding.json', 'frozen_protocol.json'):
        source = folder / name
        target = dest / name
        data = source.read_bytes()
        if target.exists():
            if target.read_bytes() != data:
                raise ValueError('Retained reassessment common contract differs')
        else:
            with target.open('xb') as handle:
                handle.write(data)
        bindings[str(source)] = sha(source)
    receipt = dict(version='gameness-v4-reassessment-source-reuse.v1',
                   identity=identity, source_review=str(review_path), source_review_sha256=sha(review_path),
                   parent_workspace=str(parent), bindings=bindings,
                   new_static_call=False, runtime_scores_supplied=False, contract_changed=False)
    path = dest / 'source_reuse.json'
    if path.exists():
        if runner.read(path) != receipt:
            raise ValueError('Retained reassessment source reuse differs')
    else:
        runner.exclusive_json(path, receipt)
    return review, review_path, {**bindings, str(path): sha(path)}
