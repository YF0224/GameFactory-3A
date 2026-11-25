"""Normalize only citation boundary padding against exact frozen physical lines.

Raw model response and schema remain immutable. Interior text, path, SHA and line
are never repaired or guessed; every normalized quote still passes the original
strict reference validator. All edits have an explicit before/after receipt.
"""
import copy
from pathlib import Path
from .common import dump, sha
from .scoring import reference


def normalize(folder, stage, response):
    folder = Path(folder)
    result = copy.deepcopy(response)
    changes = []
    roots = {'implementation_refs': folder/'input', 'entry_refs': folder/'input',
             'state_event_refs': folder, 'log_refs': folder}
    for row in result.get('checks', []):
        for field, root in roots.items():
            for index, ref in enumerate(row.get(field, [])):
                if reference(root, ref): continue
                quote = ref.get('quote')
                if not isinstance(quote, str): continue
                fixed = {**ref, 'quote': quote.strip()}
                if fixed['quote'] == quote or not reference(root, fixed): continue
                changes.append({'task_id':row['task_id'], 'field':field, 'index':index,
                                'original':dict(ref), 'normalized':fixed})
                ref['quote'] = fixed['quote']
    raw = folder/(stage+'.json')
    dump(folder/(stage+'_reference_normalization.json'), {
        'version':'refine.exact-source-reference-padding.v1',
        'raw_result':str(raw),'raw_result_sha256':sha(raw), 'changes':changes,
        'semantics':'Boundary padding removed only after the same path/SHA/physical line verifies exact quoted text.'})
    return result
