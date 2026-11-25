"""Revalidate a saved v4 response rejected solely by the v3 contract dispatcher.

No retry or field edits. Original failure/response/request remain immutable.
This does not recover service errors, bad citations or unreadable images.
"""
from pathlib import Path
from .codex import validate_schema
from .protocol import sha
from . import mechanic_v3_runner as runner

VERSION = 'gameness-v4-contract-dispatch-revalidation.v1'


def recover(folder, *, policy, schema, submitted_prompt, evaluate_response, actual):
    folder = Path(folder)
    if policy.VERSION != 'whitebox-gameness10-50-100.v4':
        raise ValueError('Contract dispatch recovery is v4-only')
    if (folder/'accepted_response.json').exists():
        raise ValueError('Never replace an accepted response')
    error = runner.read(folder/'validation_error.json')
    response = folder/'response.json'
    supported = {'$.protocol: invalid enum value',
                 'Runtime author sources differ from first-stage source review'}
    if (error.get('phase') != 'response_plan_validation'
            or error.get('exception') not in supported
            or error.get('response_sha256') != sha(response)):
        raise ValueError('Not the exact saved contract dispatcher failure')
    if (runner.read(folder/'schema.json') != schema
            or (folder/'prompt.txt').read_text() != submitted_prompt):
        raise ValueError('Recovery must use the unchanged original request')
    invocation = runner.read(folder/'invocation.json')
    command = invocation.get('command', [])
    images = [str(Path(command[i+1]).resolve()) for i, arg in enumerate(command[:-1]) if arg == '--image']
    root = folder.parent.parent
    if (invocation.get('exit_code') != 0
            or '--model' not in command or command[command.index('--model')+1] != policy.MODEL
            or images != [str((root/i['path']).resolve()) for i in actual['images']]
            or actual.get('all_predeclared_frames_delivered') is not True
            or actual.get('scoring_protocol') != policy.VERSION
            or actual.get('prompt_sha256') != sha(folder/'prompt.txt')):
        raise ValueError('Original complete v4 invocation/delivery is not qualified')
    for item in actual['images'] + actual['complete_author_sources']:
        if sha(root/item['path']) != item['sha256']:
            raise ValueError('Original source/native image bytes changed')
    value = runner.read(response)
    validate_schema(value, schema)
    evaluate_response(value)  # All current native/source/citation/tier gates, unchanged.
    extra_bindings = {}
    if error['exception'] == 'Runtime author sources differ from first-stage source review':
        from .gameness_v4_source_consistency import PROOF, VERSION as SOURCE_VERSION
        proof_path = root/PROOF
        proof = runner.read(proof_path)
        if (proof.get('version') != SOURCE_VERSION
                or proof.get('complete_reviewed_authors_unchanged') is not True
                or proof.get('supplemental_bytes_still_delivered') is not True):
            raise ValueError('Original reviewed authors require exact generated-supplement proof')
        for name,digest in proof['source_bindings'].items():
            if sha(Path(name)) != digest:raise ValueError('Source consistency proof binding changed')
        extra_bindings = {str(proof_path):sha(proof_path)}
    names = ['response.json', 'schema.json', 'prompt.txt', 'validation_error.json', 'invocation.json']
    receipt = dict(version=VERSION, time=runner.stamp(), model_recalled=False,
        response_edited=False, parent_failure_preserved=True,
        root_cause=('v4 contract was incorrectly sent to default-v3 contract validator'
            if error['exception'] == '$.protocol: invalid enum value' else
            'Exact reviewed authors were unchanged; additional fully delivered generated files were incorrectly rejected'),
        source_consistency_bindings=extra_bindings,
        original_bindings={str(folder/name):sha(folder/name) for name in names},
        production_bindings={str(p):sha(p) for p in [Path(__file__).resolve(),
            Path(__file__).with_name('gameness_v3.py').resolve(),
            Path(__file__).with_name('gameness_v4.py').resolve(),
            Path(__file__).with_name('gameness_v3_static.py').resolve(),
            Path(__file__).with_name('gameness_v4_source_consistency.py').resolve()]})
    path = folder/'contract_dispatch_revalidation.json'
    if path.exists():
        old = runner.read(path)
        if old['original_bindings'] != receipt['original_bindings'] or old['production_bindings'] != receipt['production_bindings']:
            raise ValueError('Existing revalidation lineage changed')
    else:
        runner.exclusive_json(path, receipt)
    runner.exclusive_json(folder/'accepted_response.json', dict(path='response.json',
        sha256=sha(response), attempt=error['attempt'], revalidation=str(path),
        revalidation_sha256=sha(path), model_recalled=False))
    return value
