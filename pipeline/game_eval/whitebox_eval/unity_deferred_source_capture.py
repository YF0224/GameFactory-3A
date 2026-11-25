"""Preserve failed supplementary diagnostics while mandatory-static gameplay advances.

This path ends at CAPTURE_QUALIFIED. Source diagnostics remain required by the
unchanged normal continuation; it never builds evidence, judges or publishes.
"""
from pathlib import Path
import time

from . import batch, core12, static_existence
from .protocol import dump, sha

VERSION = 'whitebox-unity-deferred-source-capture.v1'
RECEIPT = 'deferred_source_capture.json'


def qualify(root):
    from . import source_column_stream_transport_recovery as stream
    from . import source_score_output_recovery as columns
    root = Path(root).resolve()
    batch.verify_inputs(root)
    proto = core12.verify_attempt(root, 'unity3d')
    static_existence.load(root, proto)
    source = columns._lineage(root, batch.read(root/columns.RECEIPT))
    accepted, missing = [], []
    for index, delivery in enumerate(columns._inputs(source)):
        name = f'source_column_{index+1:02d}'
        if stream.registered(root, name):
            auth = stream.verify(root, name)
            folder = root/'model_calls'/auth['request_name']
            inv, budget = batch.read(folder/'invocation.json'), batch.read(folder/'budget.json')
            if (inv.get('status') != 'TIMEOUT'
                    or inv.get('model_requested') != static_existence.MODEL
                    or inv.get('seconds', 0) < budget.get('effective_timeout_seconds', float('inf'))
                    or budget.get('attempt') != 1 or budget.get('extension_seconds') != 0
                    or any((folder/n).exists() for n in ('response.json','accepted_response.json','schema_error.json'))
                    or time.time() < auth['qualification']['phase_deadline_unix']):
                raise ValueError('Only an exhausted, response-free supplemental transport continuation may defer')
            missing.append(name)
        else:
            path = columns._response(root, name)
            if not columns._actual_delivery(root, name, path, delivery):
                raise ValueError('Accepted sibling actual delivery changed')
            columns.validate_shard(root, batch.read(path), delivery)
            accepted.append(name)
    if len(missing) != 1 or not accepted:
        raise ValueError('Exactly one preserved missing source column required')
    paths = ['input_manifest.json','input/pilot_rubric.json','static_existence.json',columns.RECEIPT]
    paths += [str(p.relative_to(root)) for p in (root/'model_calls').rglob('*')
              if p.is_file() and p.relative_to(root/'model_calls').parts[0].startswith(('source_', 'static_existence'))]
    paths += [str(p.relative_to(root)) for p in (root/'source_column_stream_transport_recovery').glob('*.json')]
    return {'accepted_columns':accepted,'missing_columns':missing,
            'bindings':{n:sha(root/n) for n in sorted(paths)},
            'source_diagnostics_still_required':True,'scoring_semantics_changed':False}


def prepare(root):
    from .unity_recovery import attempts, saved_score
    from .unity_queue import published
    root = Path(root).resolve()
    ident = batch.read(root/'input_manifest.json')['entry']['id']
    if saved_score(attempts(root.parents[1], ident)) or published(root.parents[1], ident):
        raise ValueError('Saved score protected')
    if any((root/n).exists() for n in (RECEIPT,'sol_plan.json','background_record','static_source_scores.json','scores.json')):
        raise ValueError('Only one pre-plan deferred capture authorization permitted')
    proof = qualify(root)
    value = {'version':VERSION,'attempt':str(root),'qualification':proof,
             'authorized_unix':time.time(),'capture_only':True,
             'source_diagnostics_still_required':True,'scoring_semantics_changed':False}
    with (root/RECEIPT).open('x') as output:
        import json
        output.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    return verify(root)


def verify(root):
    root = Path(root).resolve()
    value = batch.read(root/RECEIPT)
    if (value.get('version') != VERSION or value.get('attempt') != str(root)
            or value.get('qualification') != qualify(root)
            or value.get('capture_only') is not True
            or value.get('source_diagnostics_still_required') is not True
            or value.get('scoring_semantics_changed') is not False):
        raise ValueError('Deferred source capture proof changed')
    return value


def run(output, root):
    """Caller must own the production coordinator and perform normal preflight."""
    from . import unity_single
    output, root = Path(output).resolve(), Path(root).resolve()
    config = batch.read(output/'configuration.json')
    if config.get('save_source_code_scores') is not True:
        raise ValueError('Supplementary diagnostics must remain enabled')
    if batch.read(output/'single_state.json')['attempt'] != str(root):
        raise ValueError('Saved attempt identity changed')
    authorization = verify(root)
    unity_single.phase(output,'SOURCE_DIAGNOSTIC_DEFERRED',attempt=str(root),
                       missing_columns=authorization['qualification']['missing_columns'])
    return unity_single.continue_plan_capture(output,root,capture_only=True)
