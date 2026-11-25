"""Conservative, exact-path cache reclamation after persisted Unity scores.

Never removes project/Library wholesale. Call only under the production workflow
lease and all execution/publication locks, with a freshly checked idle process set.
The CLI defaults to preview; --apply is explicit. No scoring/evidence is changed.
"""
from pathlib import Path
import argparse
import datetime
import fcntl
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
from contextlib import ExitStack

CACHE_KINDS = frozenset({'Artifacts', 'ShaderCache', 'BurstCache', 'ScriptAssemblies'})
EVIDENCE_NAMES = frozenset({'editor.log', 'player.log', 'frame_index.json',
    'frame_index.jsonl', 'action_frame_links.json', 'state.jsonl', 'events.jsonl',
    'actions.jsonl', 'manifest.json', 'verification.json', 'runner_exit.json'})
PRUNE_NAMES = frozenset({'Library', 'Temp', 'obj', 'node_modules', '.git', '__pycache__'})
TEXT_EXTENSIONS = frozenset({'.json', '.jsonl', '.md', '.txt', '.yaml', '.yml', '.log', '.csv'})


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def scored_cases(batch):
    rows = {}
    for line in (batch / 'scores.md').read_text().splitlines():
        cells = [s.strip() for s in line.strip('|').split('|')]
        if (len(cells) == 11 and re.fullmatch(r'(Astra|GLM|Sol) / G\d{3}', cells[0])
                and all(re.fullmatch(r'\d+(?:\.\d+)?', v) for v in cells[1:10])):
            rows[tuple(cells[0].split(' / '))] = cells
    entries = json.loads((batch / 'inventory.json').read_text())['entries']
    return {e['id']: rows[(e['method'], e['case_id'][:4])] for e in entries
            if e['actual_engine'] == 'unity3d'
            and (e['method'], e['case_id'][:4]) in rows}


def persisted_sources(batch, scored):
    """Bind each scored row to its existing formal/pending/user-saved source."""
    from .protocol import COLUMNS
    catalogs = []
    for name in ('versioned_publications.json', 'pending_audits.json',
                 'supplemental_publications/index.json'):
        p = batch/name
        if p.is_file():
            catalogs.append((p, json.loads(p.read_text()).get('entries', {})))
    # Historical migrated results predate the publication registry. Bind only
    # their persisted verify provenance, with exact source SHA and eight-column
    # comparison below; this does not grant independent-audit status.
    provenance = batch/'score_verify.provenance.json'
    if provenance.is_file():
        legacy = {}
        for label, ref in json.loads(provenance.read_text()).get('entries', {}).items():
            if not ref.get('score_path') or not ref.get('score_sha256'):
                continue
            score_path = Path(ref['score_path']).resolve()
            if not score_path.is_relative_to(batch.resolve()):
                continue
            for case in scored:
                if label == case.split('__')[0]+' / '+case.split('__')[1][:4]:
                    legacy[case] = {'attempt': str(score_path.parent),
                                    'score_sha256': ref['score_sha256']}
        catalogs.append((provenance, legacy))
    proofs = {}
    for case, row in scored.items():
        errors = []
        for catalog, entries in catalogs:
            if case not in entries:
                continue
            ref = entries[case]
            try:
                attempt = batch/ref['attempt']
                score_path = attempt/'scores.json'
                score = json.loads(score_path.read_text())
                if ref.get('score_sha256') and ref['score_sha256'] != sha(score_path):
                    raise ValueError('score source SHA mismatch')
                if score.get('valid') is not True:
                    raise ValueError('raw score is not explicitly valid')
                actual = [score['columns'][c]['score'] for c in COLUMNS]
                actual.append(score['overall_score'])
                if any(type(value) not in (int, float) or not math.isfinite(value)
                       or not 0 <= value <= 100 for value in actual):
                    raise ValueError('incomplete or invalid numeric score source')
                if any(abs(v-float(w)) > 0.011 for v,w in zip(actual,row[1:10])):
                    raise ValueError('eight-column/total table source mismatch')
                proofs[case] = {'catalog': str(catalog), 'catalog_sha256': sha(catalog),
                    'attempt': str(attempt), 'score': str(score_path),
                    'score_sha256': sha(score_path), 'eight_columns_match': True}
                break
            except (KeyError, ValueError, OSError, TypeError) as exc:
                errors.append(str(exc))
        if case not in proofs:
            proofs[case] = {'error': 'no matching persisted complete source', 'details': errors}
    return proofs


def eligible_path(path, batch, case):
    """Only task-isolated admission/runtime copies, never frozen/author inputs."""
    path, batch = Path(path), Path(batch).resolve()
    if path.is_symlink() or path.resolve() != path.absolute():
        return False
    try:
        rel = path.relative_to(batch)
    except ValueError:
        return False
    parts = rel.parts
    known_cache = (path.parent.name == 'Library' and path.name in CACHE_KINDS)
    known_cache = known_cache or path.parts[-2:] == ('Temp', 'Burst')
    return (case in str(rel) and known_cache
            and ('input' not in parts and 'validation' not in parts)
            and any(s in rel.as_posix() for s in
                    ('/admission/native_admission/', '/background_record/project/', '/runtime/project/')))


def cache_files(path):
    """Refuse links and any recognisable evidence/diagnostic, even in a cache."""
    files = []
    burst = Path(path).parts[-2:] == ('Temp', 'Burst')
    for root, dirs, names in os.walk(path, followlinks=False):
        for name in dirs + names:
            p = Path(root) / name
            if p.is_symlink():
                raise ValueError('symlink inside cache: ' + str(p))
            if (name.lower() in EVIDENCE_NAMES or name.lower() == 'gamefactory3a'
                    or p.suffix.lower() in {'.log', '.jsonl', '.mp4', '.mov', '.webm'}):
                raise ValueError('potential evidence/diagnostic inside cache: ' + str(p))
        for name in names:
            p = Path(root) / name
            if burst and not re.fullmatch(r'burst-aot[^/]+/lib_burst_generated_part_[0-9a-f]+\.(?:gbc|o)', p.relative_to(path).as_posix()):
                raise ValueError('unclassified file in Temp/Burst: ' + str(p))
            st = p.stat()
            files.append({'path': str(p), 'bytes': st.st_size,
                          'allocated_bytes': st.st_blocks * 512, 'inode': st.st_ino})
    return files


def metadata_files(roots):
    for base in roots:
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs[:] = [d for d in dirs if d not in PRUNE_NAMES
                       and not (Path(root)/d).is_symlink()]
            for name in files:
                p = Path(root) / name
                if p.suffix.lower() in TEXT_EXTENSIONS and not p.is_symlink():
                    yield p


def cache_marker(path):
    path = Path(path)
    return 'Temp/Burst' if path.parts[-2:] == ('Temp', 'Burst') else 'Library/' + path.name


def reference_role(source, line, path, cache_receipt=False, *, tokens=None):
    """Distinguish generated-path enumeration from bindings to cache contents."""
    marker = cache_marker(path)
    # The reclamation receipt lists candidates, not inputs to a later stage.
    # Only its exact path field is exempt; embedded evidence references stay live.
    if cache_receipt and re.match(r'\s*"path"\s*:', line):
        return 'cache_candidate_enumeration'
    # Unity's build progress reports a historical output copy, without a digest
    # binding. Retain the entire log, while allowing the output to regenerate.
    if (source.suffix.lower() == '.log'
            and re.match(r'\s*\[\d+/\d+[^\]]*\]\s+CopyFiles\s+Library/', line)
            and not re.search(r'(?i)\b(?:sha(?:256)?|digest|evidence|manifest)\b', line)):
        return 'historical_build_output_copy'
    # An absolute cache path to another project cannot bind every same-kind
    # cache. Unresolvable relative paths continue to fail closed below.
    if tokens is None:
        tokens = re.findall(r'[^\s"\x27`{}\[\],]+', line)
    matches = [token for token in tokens if marker in token]
    if matches and all(token.startswith('/') for token in matches):
        if all(not (token.rstrip(':;') == str(path)
                    or token.startswith(str(path) + '/')) for token in matches):
            return 'absolute_path_to_other_project'
    if matches and all(token.startswith(('workspaces/', 'test_data/')) for token in matches):
        resolved = [(Path.cwd()/token.rstrip(':;')).resolve() for token in matches]
        if all(item != path and not item.is_relative_to(path) for item in resolved):
            return 'workspace_path_to_other_project'
    return 'possible_evidence_dependency'


def json_array_rows(path):
    """Validate generated JSON arrays in bounded memory, including trailing data."""
    decoder=json.JSONDecoder()
    with Path(path).open() as stream:
        buffer=''
        ended=False
        def fill():
            nonlocal buffer,ended
            chunk=stream.read(65536)
            if not chunk:
                ended=True
            buffer+=chunk
        def trim():
            nonlocal buffer
            buffer=buffer.lstrip()
            while not buffer and not ended:
                fill()
                buffer=buffer.lstrip()
        trim()
        if not buffer.startswith('['):
            raise ValueError('Expected generated classification array')
        buffer=buffer[1:]
        trim()
        if buffer.startswith(']'):
            buffer=buffer[1:]
        else:
            while True:
                trim()
                while True:
                    try:
                        value,end=decoder.raw_decode(buffer)
                        break
                    except json.JSONDecodeError:
                        if ended or len(buffer)>1048576:
                            raise ValueError('Invalid or oversized generated classification row')
                        fill()
                buffer=buffer[end:]
                yield value
                trim()
                if buffer.startswith(']'):
                    buffer=buffer[1:]
                    break
                if not buffer.startswith(','):
                    raise ValueError('Missing generated classification separator')
                buffer=buffer[1:]
        trim()
        if buffer:
            raise ValueError('Trailing generated classification data')


def candidate_enumeration_paths(source):
    """Recognize generated scan candidate labels, preserving real source references."""
    source = Path(source)
    from functools import lru_cache
    @lru_cache(maxsize=4096)
    def string_cache_path(value):
        return (Path(value).is_absolute() and Path(value).parent.name == 'Library'
                and Path(value).name in CACHE_KINDS)
    def cache_path(value):
        return isinstance(value, str) and string_cache_path(value)
    def reference(row, classified=False, temp_paths=frozenset()):
        required = {'source','physical_line','source_sha256','role'}
        if classified:
            required.add('candidate')
        return (isinstance(row,dict) and set(row) == required
                and isinstance(row['source'],str)
                and type(row['physical_line']) is int and row['physical_line'] > 0
                and re.fullmatch(r'[0-9a-f]{64}',row['source_sha256'])
                and isinstance(row['role'],str)
                and (not classified or cache_path(row['candidate'])
                     or row['candidate'] in temp_paths))
    if source.name == 'reference_classifications.json' and 'cache_reclamation' in source.parts:
        companion = source.parent/'receipt.json'
        if not companion.is_file():
            return set()
        receipt = json.loads(companion.read_text())
        if (receipt.get('version') != 'scored-unity-cache-reclamation.v1'
                or receipt.get('reference_classifications') != str(source)
                or receipt.get('reference_classifications_sha256') != sha(source)):
            return set()
        # A prior scan's exact candidate label is bookkeeping, not a read of
        # generated object contents. Temp candidates need the opt-in single-case
        # receipt and the same isolated-path eligibility as actual reclamation.
        # The source/physical-line fields remain active references below.
        temp_paths = set()
        case = receipt.get('requested_case_id')
        batch = source.parent.parent.parent
        if (receipt.get('include_temp_burst') is True
                and receipt.get('scope') == 'single-scored-case'
                and isinstance(case, str) and case):
            for item in receipt.get('results', []):
                if not isinstance(item, dict):
                    return set()
                value = item.get('path')
                if (isinstance(value, str) and Path(value).is_absolute()
                        and Path(value).parts[-2:] == ('Temp', 'Burst')
                        and item.get('case') == case
                        and eligible_path(Path(value), batch, case)):
                    temp_paths.add(value)
        paths=set()
        for row in json_array_rows(source):
            if not reference(row, True, temp_paths):
                return set()
            paths.add(row['candidate'])
        return paths
    if source.name == 'real_case_qualification.json' and 'unity_queue_runs' in source.parts:
        value = json.loads(source.read_text())
        if (isinstance(value,dict) and set(value) == {'at','mode','case','source_receipt',
                'source_receipt_sha256','hits','scan_errors','classifications'}
                and value['mode'] == 'READ_ONLY_NO_DELETIONS_NO_FORMAL_APPLICATION'
                and isinstance(value['source_receipt'],str)
                and Path(value['source_receipt']).is_absolute()
                and 'cache_reclamation' in Path(value['source_receipt']).parts
                and not Path(value['source_receipt']).is_symlink()
                and sha(Path(value['source_receipt'])) == value['source_receipt_sha256']
                and isinstance(value['hits'],dict) and isinstance(value['classifications'],list)
                and value['scan_errors'] == []
                and all(cache_path(k) and isinstance(v,list)
                        and all(reference(r) for r in v) for k,v in value['hits'].items())
                and all(reference(r,True) for r in value['classifications'])):
            receipt=json.loads(Path(value['source_receipt']).read_text())
            if (receipt.get('version') == 'scored-unity-cache-reclamation.v1'
                    and receipt.get('requested_case_id') == value['case']):
                return set(value['hits']) | {r['candidate'] for r in value['classifications']}
    if (source.name == 'provenance.json'
            and source.parent.name == 'g054_readonly_inventory_classification'
            and 'unity_queue_runs' in source.parts):
        # Only empty diagnostic-map labels are enumerations. The referenced
        # measured inventory must retain its exact SHA and strict cache schema.
        # Every other physical line in this provenance remains an active input.
        text = source.read_text()
        value = json.loads(text)
        if (text not in tuple(json.dumps(value,ensure_ascii=a,indent=2)+end
                              for a in (False,True) for end in ('','\n'))
                or not isinstance(value,dict)
                or set(value) != {'at','root_cause','semantics_unchanged',
                                  'changes','regression','actual_case','actual_deleted_bytes','applied_to_production'}
                or type(value.get('actual_deleted_bytes')) is not int
                or value['actual_deleted_bytes'] != 0
                or value.get('applied_to_production') is not False):
            return set()
        actual = value.get('actual_case')
        if (not isinstance(actual,dict) or set(actual) != {'case','inventory',
                'inventory_sha256','candidate_fields_recognized','scan_errors',
                'candidate_label_hits'}
                or actual.get('case') != 'GLM__G054_identity_trial'
                or actual.get('scan_errors') != []
                or type(actual.get('candidate_fields_recognized')) is not int
                or not isinstance(actual.get('candidate_label_hits'),dict)
                or not isinstance(actual.get('inventory'),str)):
            return set()
        inventory = Path(actual['inventory'])
        if (not inventory.is_absolute() or inventory.is_symlink()
                or inventory.name != 'g054_cache_inventory_readonly.json'
                or not inventory.is_file()
                or sha(inventory) != actual.get('inventory_sha256')):
            return set()
        classified = generated_inventory_lines(inventory)
        labels = actual['candidate_label_hits']
        measured = json.loads(inventory.read_text())
        if (not labels or not classified
                or actual['candidate_fields_recognized'] != len(classified)
                or set(labels) != {row['path'] for row in measured['candidates']}
                or any(not cache_path(path) or hits != [] for path,hits in labels.items())):
            return set()
        return set(labels)
    if source.name == 'cache_reference_diagnostic.json' and 'unity_queue_runs' in source.parts:
        value = json.loads(source.read_text())
        if (isinstance(value,dict) and set(value)=={'created','hits','errors','classifications'}
                and isinstance(value['hits'],dict) and isinstance(value['classifications'],list)
                and value['errors']==[]
                and all(cache_path(k) and isinstance(v,list)
                        and all(reference(r) for r in v) for k,v in value['hits'].items())
                and all(reference(r,True) for r in value['classifications'])):
            return set(value['hits']) | {r['candidate'] for r in value['classifications']}
    return set()


def receipt_bound_history_lines(source, roots=()):
    """Resolve only the exact historical cleanup-summary grammar, not prose scope.

    A bare cache kind in this generated summary belongs to the receipt's single
    deleted case. Never infer scope from a nearby heading, filename or case name.
    The source and referenced receipt stay intact; unknown prose fails closed.
    """
    source = Path(source)
    if source.suffix != '.md':
        return {}
    pattern = re.compile(
        r'G(?P<number>\d{3}) 出分后受控缓存回收已完成：`(?P<receipt>cache_reclamation/[^`]+/receipt\.json)`，'
        r'仅删除精确的 (?P<kinds>`Library/\w+`(?:、`Library/\w+`)*) 三个路径，'
        r'`deleted_allocated_bytes=(?P<deleted>[\d,]+)`；'
        r'`free_before=(?P<before>[\d,]+)`、`free_after=(?P<after>[\d,]+)`、'
        r'`scan_errors=\[\]`、`tables_unchanged=true`。'
        r'`Library/ShaderCache`、`Library/GameFactory3A` 及录像、原始帧、state/event/action/log、'
        r'请求/响应/schema、判词、来源、cleanup 回执和失败诊断均保留；'
        r'不删除 recovery_runs、admission、项目目录、共享/全局缓存、train_data 或历史 validation 证据。')
    result = {}
    # A batch root must be unambiguous and real. Never follow a receipt outside it.
    roots = list({Path(root).resolve() for root in (*source.parents, *roots)
                  if (Path(root)/'scores.md').is_file() and (Path(root)/'inventory.json').is_file()})
    if len(roots) != 1:
        return result
    root = roots[0].resolve()
    for number, line in enumerate(source.read_text().splitlines(), 1):
        match = pattern.fullmatch(line)
        if not match:
            continue
        receipt = root/match['receipt']
        if receipt.is_symlink() or not receipt.resolve().is_relative_to(root/'cache_reclamation'):
            continue
        try:
            value = json.loads(receipt.read_text())
            if (value.get('version') != 'scored-unity-cache-reclamation.v1'
                    or value.get('tables_unchanged') is not True
                    or value.get('scan_errors') != []
                    or any(value.get(key) != int(match[group].replace(',', ''))
                           for key, group in [('deleted_allocated_bytes','deleted'),
                                              ('free_bytes_before','before'),('free_bytes_after','after')])):
                continue
            deleted = [row for row in value['results'] if row.get('status') == 'DELETED']
            cases = {row['case'] for row in deleted}
            names = set(re.findall(r'`Library/(\w+)`', match['kinds']))
            if (len(cases) != 1 or len(names) != 3 or not names <= CACHE_KINDS
                    or {Path(row['path']).name for row in deleted} != names
                    or any(Path(row['path']).parent.name != 'Library'
                           or not Path(row['path']).is_absolute()
                           or not eligible_path(Path(row['path']), root, row['case'])
                           for row in deleted)
                    or sum(row['allocated_bytes'] for row in deleted) != value['deleted_allocated_bytes']):
                continue
            case = next(iter(cases))
            if (not re.fullmatch(r'(?:Astra|GLM|Sol)__G'+match['number']+r'_[A-Za-z0-9_]+', case)
                    or case not in receipt.parts):
                continue
            result[number] = case
        except (OSError, ValueError, KeyError, TypeError):
            # No exemption on missing, malformed or drifted recovery materials.
            continue
    return result


def historical_enumeration_lines(source):
    """Identify precise generated fields, never all references in an archive.

    Historical lsof snapshots describe past handles; run() independently checks
    current open handles twice before any deletion. All snapshots remain intact.
    """
    source=Path(source)
    if source.name == 'open_files.txt' and 'cache_reclamation' in source.parts:
        receipt=source.parent/'receipt.json'
        if receipt.is_file() and json.loads(receipt.read_text()).get('version') == 'scored-unity-cache-reclamation.v1':
            return {n: 'historical_open_file_snapshot' for n,line in enumerate(source.read_text().splitlines(),1)
                    if line.startswith('n/') and 'Library/' in line}
        return {}
    if source.name == 'scored_cache_prioritization.json' and 'unity_queue_runs' in source.parts:
        text = source.read_text()
        value = json.loads(text)
        if (not isinstance(value, dict) or set(value) != {'at','scope','disk','rows'}
                or value.get('scope') != 'read_only_39_persisted_unity_cases_not_bulk_deletion'
                or not isinstance(value.get('rows'), list)
                or text not in tuple(json.dumps(value, ensure_ascii=ascii_only, indent=2)+ending
                                     for ascii_only in (True,False) for ending in ('','\n'))):
            return {}
        result = {}
        for row in value['rows']:
            if (not isinstance(row, dict) or set(row) != {'case','source','prior_scoped_receipt',
                    'candidates','table_rows','allocated_bytes'} or not isinstance(row['candidates'], list)):
                return {}
            for candidate in row['candidates']:
                if (not isinstance(candidate, dict) or set(candidate) != {'path','allocated_bytes','files'}
                        or not isinstance(candidate['path'], str)
                        or not Path(candidate['path']).is_absolute()
                        or Path(candidate['path']).parent.name != 'Library'
                        or Path(candidate['path']).name not in CACHE_KINDS
                        or not any(part == row['case'] or part.startswith(row['case']+'__')
                                   for part in Path(candidate['path']).parts)
                        or type(candidate['allocated_bytes']) is not int or candidate['allocated_bytes'] < 0
                        or type(candidate['files']) is not int or candidate['files'] < 0):
                    return {}
                block='\n'.join(' '*8+line for line in json.dumps(candidate,ensure_ascii=False,indent=2).splitlines())
                if text.count(block) != 1:
                    continue
                label=' '*10+'"path": '+json.dumps(candidate['path'],ensure_ascii=False)
                offset=block.find(label)
                if offset >= 0:
                    result[text.count('\n',0,text.index(block)+offset)+1]='historical_cache_candidate_enumeration'
        return result
    if source.suffix != '.json' or not ('docs' in source.parts):
        return {}
    text=source.read_text()
    value=json.loads(text)
    if not isinstance(value,dict):
        return {}
    selected=[]
    if (value.get('schema') == 'whitebox-evaluation-cache-cleanup-review.v1'
            and value.get('mode') == 'READ_ONLY_PROPOSAL_NO_DELETIONS'):
        selected=[(row,4,{'path','absolute_path'}) for row in value.get('candidates',[]) if isinstance(row,dict)]
    elif (value.get('version') == 'whitebox-live-snapshot.v1'
            and isinstance(value.get('inherited_cache_receipt'),dict)
            and value['inherited_cache_receipt'].get('version') == 'scored-unity-cache-reclamation.v1'):
        selected=[(row,6,{'path'}) for row in value['inherited_cache_receipt'].get('results',[]) if isinstance(row,dict)]
    if not selected or text != json.dumps(value,ensure_ascii=False,indent=2)+'\n':
        return {}
    result={}
    for row,indent,keys in selected:
        block='\n'.join(' '*indent+line for line in json.dumps(row,ensure_ascii=False,indent=2).splitlines())
        # Exact canonical object identity binds the line to the selected tree,
        # including when unrelated protected evidence uses the same field name.
        if text.count(block) != 1:
            continue
        start=text.index(block)
        for key in keys:
            if not isinstance(row.get(key),str) or 'Library/' not in row[key]:
                continue
            label=' '*(indent+2)+json.dumps(key)+': '+json.dumps(row[key],ensure_ascii=False)
            offset=block.find(label)
            if offset>=0:
                result[text.count('\n',0,start+offset)+1]='historical_cache_candidate_enumeration'
    return result


def scoped_receipt_projection_lines(source):
    """Only exact candidate labels in a canonical SHA-bound scoped receipt projection.

    The referenced complete receipt and all its embedded evidence bindings are
    still scanned. A projection's reason/status lines are never exempted.
    """
    source = Path(source)
    if (source.suffix != '.json' or source.is_symlink()
            or 'unity_queue_runs' not in source.parts
            or source.parent.name != 'receipt_mirrors_scoped_cache_closure_v1'
            or not source.name.endswith('_summary.json')):
        return {}
    text = source.read_text()
    value = json.loads(text)
    fields = {'receipt','receipt_sha256','deleted_allocated_bytes','free_bytes_after',
              'tables_unchanged','scan_errors','results'}
    if (not isinstance(value,dict) or set(value) != fields
            or value['tables_unchanged'] is not True or value['scan_errors'] != []
            or not isinstance(value['receipt'],str)
            or text not in tuple(json.dumps(value,ensure_ascii=a,indent=2)+end
                                 for a in (False,True) for end in ('','\n'))):
        return {}
    batch = Path(*source.parts[:source.parts.index('unity_queue_runs')])
    receipt = Path(value['receipt'])
    if (not receipt.is_absolute() or receipt.name != 'receipt.json'
            or not receipt.is_file() or receipt.is_symlink()
            or not receipt.resolve().is_relative_to(batch/'cache_reclamation')
            or receipt.resolve() != receipt.absolute()
            or sha(receipt) != value['receipt_sha256']):
        return {}
    original = json.loads(receipt.read_text())
    case = original.get('requested_case_id')
    if (original.get('version') != 'scored-unity-cache-reclamation.v1'
            or original.get('scope') != 'single-scored-case'
            or not isinstance(case,str) or source.name != case+'_summary.json'
            or original.get('scored_cases_checked') != [case]
            or not isinstance(original.get('results'),list)
            or any(original.get(k) != value[k] for k in fields-{'receipt','receipt_sha256','results'})
            or value['results'] != [dict(path=row['path'],status=row['status'],reason=row.get('reason'))
                                    for row in original['results']]):
        return {}
    classified = Path(original['reference_classifications'])
    if (classified != receipt.parent/'reference_classifications.json'
            or classified.is_symlink() or not classified.is_file()
            or sha(classified) != original['reference_classifications_sha256']):
        return {}
    result = {}
    for row, full in zip(value['results'], original['results']):
        if (full.get('case') != case or not isinstance(row['path'],str)
                or not eligible_path(Path(row['path']),batch,case)):
            return {}
        for ascii_only in (False,True):
            block = '\n'.join(' '*4+line for line in json.dumps(row,ensure_ascii=ascii_only,indent=2).splitlines())
            if text.count(block) != 1:
                continue
            label = ' '*6+'"path": '+json.dumps(row['path'],ensure_ascii=ascii_only)
            offset = block.find(label)
            if offset >= 0:
                result[text.count('\n',0,text.index(block)+offset)+1] = 'sha_bound_formal_receipt_projection_candidate_label'
    return result


def copied_receipt_candidate_lines(source):
    """Only canonical, byte-identical copies of a persisted scoped receipt.

    The result path is a historical candidate label. All embedded references
    and every other physical line remain binding. Actual deletion still needs
    fresh formal locks, source, process, recovery and open-handle checks.
    """
    source = Path(source)
    if ('unity_queue_runs' not in source.parts or 'cache' not in source.name
            or source.suffix != '.json' or source.is_symlink()):
        return {}
    text = source.read_text()
    value = json.loads(text)
    fields = {'version','at','apply','locks','scored_cases_checked','requested_case_id',
              'scope','score_rows','score_sources','table_sha256','scan_errors',
              'free_bytes_before','results','preserved_libraries',
              'reference_classifications','reference_classifications_sha256',
              'free_bytes_after','free_bytes_delta','deleted_allocated_bytes',
              'cleaned_cases','table_sha256_after','tables_unchanged'}
    if (not isinstance(value,dict) or set(value) != fields
            or value.get('version') != 'scored-unity-cache-reclamation.v1'
            or value.get('tables_unchanged') is not True
            or value.get('scan_errors') != []
            or not isinstance(value.get('requested_case_id'),str)
            or value.get('scored_cases_checked') != [value['requested_case_id']]
            or not isinstance(value.get('results'),list)
            or not isinstance(value.get('reference_classifications'),str)
            or text not in tuple(json.dumps(value,ensure_ascii=a,indent=2)+end
                                 for a in (False,True) for end in ('','\n'))):
        return {}
    batch = Path(*source.parts[:source.parts.index('unity_queue_runs')])
    classified = Path(value['reference_classifications'])
    original = classified.parent/'receipt.json'
    if (not classified.is_absolute() or classified.name != 'reference_classifications.json'
            or not classified.resolve().is_relative_to(batch/'cache_reclamation')
            or classified.is_symlink() or original.is_symlink()
            or original.resolve().parent != classified.parent
            or original.read_text() != text or sha(original) != sha(source)
            or sha(classified) != value['reference_classifications_sha256']):
        return {}
    result = {}
    for row in value['results']:
        if (not isinstance(row,dict) or row.get('case') != value['requested_case_id']
                or not isinstance(row.get('path'),str)
                or not eligible_path(Path(row['path']),batch,value['requested_case_id'])):
            return {}
        for ascii_only in (False,True):
            block = '\n'.join(' '*4+line for line in json.dumps(row,ensure_ascii=ascii_only,indent=2).splitlines())
            if text.count(block) != 1:
                continue
            label=' '*6+'"path": '+json.dumps(row['path'],ensure_ascii=ascii_only)
            offset=block.find(label)
            if offset >= 0:
                result[text.count('\n',0,text.index(block)+offset)+1]='byte_identical_formal_receipt_candidate_label'
    return result


def generated_inventory_lines(source):
    """Classify only exact candidate path fields in canonical generated inventories.

    Return physical lines, never exempt a whole file or arbitrary path key.
    An embedded scored-cache receipt must equal its SHA-bound original byte for
    byte after canonical decoding. Evidence/reference fields are still scanned.
    """
    source = Path(source)
    if source.suffix != '.json':
        return {}
    if source.name not in {'scored_library_children.json', 'scored_library_children.initial.json',
                           'preserved_materials.json', 'two_scored_case_cache_summary.json',
                           'g054_cache_inventory_readonly.json'}:
        return scoped_receipt_projection_lines(source) or copied_receipt_candidate_lines(source)
    text = source.read_text()
    value = json.loads(text)
    if text not in tuple(json.dumps(value, ensure_ascii=a, indent=2)+end
                         for a in (False, True) for end in ('', '\n')):
        return {}
    selected = []
    def valid(row, retained=False):
        required = {'case','path','kind','du_kib'} | ({'retention_reason'} if retained else set())
        return (isinstance(row,dict) and set(row) == required
                and isinstance(row['case'],str)
                and re.fullmatch(r'(?:Astra|GLM|Sol)__G\d{3}_[A-Za-z0-9_]+', row['case'])
                and isinstance(row['path'],str) and Path(row['path']).is_absolute()
                and Path(row['path']).parent.name == 'Library'
                and Path(row['path']).name == row['kind'] and row['kind'] in CACHE_KINDS
                and any(part == row['case'] or part.startswith(row['case']+'__')
                        for part in Path(row['path']).parts)
                and type(row['du_kib']) is int and row['du_kib'] >= 0
                and (not retained or row['retention_reason'] ==
                     'Outside this duplicate compiler binary cleanup; retained'))
    if source.name.startswith('scored_library_children') and 'cache_reclamation' in source.parts:
        # The original inventory may also list non-cache Library children. Those
        # rows receive no exemption; valid cache-only rows are independent.
        if not isinstance(value,list):
            return {}
        selected = [(row,2) for row in value if valid(row)]
    elif source.name == 'preserved_materials.json' and 'cache_reclamation' in source.parts:
        if (not isinstance(value,dict) or set(value) != {'at','retained_always','cleanup_scope','other_library_children'}
                or value.get('cleanup_scope') != 'Only formally source-bound scored cases, exact local .Runtime binary paths after fresh lock and reference verification'
                or not isinstance(value.get('retained_always'),list)
                or not isinstance(value.get('other_library_children'),list)):
            return {}
        selected = [(row,4) for row in value['other_library_children'] if valid(row,True)]
    elif source.name == 'g054_cache_inventory_readonly.json' and 'unity_queue_runs' in source.parts:
        # A measured candidate label does not make regenerated bytes into an
        # input. Exempt only each canonical path field, never the source/audit
        # bindings or any unknown field, and never GameFactory3A.
        if (not isinstance(value,dict) or set(value) != {'at','case','score_sources',
                'candidates','candidate_allocated_bytes','preserved',
                'actual_deleted_bytes','free_bytes','read_only','not_deletion_authorization'}
                or value.get('case') != 'GLM__G054_identity_trial'
                or value.get('read_only') is not True
                or type(value.get('actual_deleted_bytes')) is not int or value['actual_deleted_bytes'] != 0
                or type(value.get('free_bytes')) is not int or value['free_bytes'] < 0
                or value.get('not_deletion_authorization') != 'Formal seven locks, full reference/recovery/occupation checks still required immediately before removal'
                or not isinstance(value.get('candidates'),list)
                or not isinstance(value.get('preserved'),list)
                or not isinstance(value.get('score_sources'),dict)
                or set(value['score_sources']) != {value['case']}):
            return {}
        total = 0
        seen = set()
        for row in value['candidates']:
            if (not isinstance(row,dict) or set(row) != {'path','files','allocated_bytes'}
                    or not isinstance(row.get('path'),str) or row['path'] in seen
                    or not eligible_path(Path(row['path']), Path(*source.parts[:source.parts.index('unity_queue_runs')]), value['case'])
                    or Path(row['path']).parent.name != 'Library'
                    or Path(row['path']).name not in CACHE_KINDS
                    or type(row.get('files')) is not int or row['files'] < 0
                    or type(row.get('allocated_bytes')) is not int or row['allocated_bytes'] < 0):
                return {}
            total += row['allocated_bytes'];seen.add(row['path'])
        if type(value.get('candidate_allocated_bytes')) is not int or total != value['candidate_allocated_bytes']:
            return {}
        selected = [(row,4) for row in value['candidates']]
    elif source.name == 'two_scored_case_cache_summary.json' and 'unity_queue_runs' in source.parts:
        if (not isinstance(value,dict) or set(value) != {'cases','actual_deleted_bytes','pending_audit_not_a_cache_blocker','references_preserved'}
                or not isinstance(value.get('cases'),list)
                or type(value.get('actual_deleted_bytes')) is not int
                or value.get('pending_audit_not_a_cache_blocker') is not True
                or value.get('references_preserved') is not True):
            return {}
        total = 0
        for item in value['cases']:
            if (not isinstance(item,dict) or set(item) != {'path','sha256','receipt'}
                    or not isinstance(item['path'],str)
                    or '..' in Path(item['path']).parts
                    or (not Path(item['path']).is_absolute() and not item['path'].startswith('test_data/outputs/eval/playtest/'))
                    or 'cache_reclamation' not in Path(item['path']).parts):
                return {}
            original = Path(item['path'])
            if original.is_symlink() or sha(original) != item['sha256']:
                return {}
            receipt = item['receipt']
            if (json.loads(original.read_text()) != receipt
                    or receipt.get('version') != 'scored-unity-cache-reclamation.v1'
                    or not isinstance(receipt.get('results'),list)
                    or type(receipt.get('deleted_allocated_bytes')) is not int):
                return {}
            total += receipt['deleted_allocated_bytes']
            for row in receipt['results']:
                path=Path(row.get('path',''))
                if (path.is_absolute() and path.parent.name == 'Library' and path.name in CACHE_KINDS
                        and isinstance(row.get('case'),str)
                        and any(part == row['case'] or part.startswith(row['case']+'__') for part in path.parts)):
                    selected.append((row,10))
        if total != value['actual_deleted_bytes']:
            return {}
    result = {}
    for row,indent in selected:
        for a in (False,True):
            block='\n'.join(' '*indent+line for line in json.dumps(row,ensure_ascii=a,indent=2).splitlines())
            if text.count(block) != 1:
                continue
            label=' '*(indent+2)+'"path": '+json.dumps(row['path'],ensure_ascii=a)
            offset=block.find(label)
            if offset >= 0:
                result[text.count('\n',0,text.index(block)+offset)+1]='historical_cache_candidate_enumeration'
    return result


def embedded_historical_build_output_lines(source):
    """Recognize only hash-bound historical CopyFiles text in JSON diagnostics.

    Keep the diagnostic and every other line under ordinary reference checks.
    A hash of a historical log string is not a hash of a generated DLL/cache.
    """
    source = Path(source)
    if source.suffix != '.json' or source.stat().st_size > 1048576:
        return {}
    text = source.read_text()
    if '"native_log_physical_lines"' not in text:
        return {}
    try:
        value = json.loads(text)
    except ValueError:
        return {}
    if (not isinstance(value, dict)
            or text not in tuple(json.dumps(value, ensure_ascii=a, indent=2)+end
                                 for a in (False, True) for end in ('', '\n'))):
        return {}
    rows = value.get('native_log_physical_lines')
    if not isinstance(rows, list) or not rows or len(rows) > 10000:
        return {}
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'line','text','sha256'}
                or type(row['line']) is not int or row['line'] < 1
                or row['line'] in seen or not isinstance(row['text'], str)
                or '\n' in row['text'] or '\r' in row['text']
                or hashlib.sha256(row['text'].encode()).hexdigest() != row['sha256']):
            return {}
        seen.add(row['line'])
    result = {}
    for row in rows:
        literal = row['text']
        if (not re.match(r'\s*\[\d+/\d+[^\]]*\]\s+CopyFiles\s+Library/', literal)
                or re.search(r'(?i)\b(?:sha(?:256)?|digest|evidence|manifest)\b', literal)):
            continue
        for ascii_mode in (False,True):
            block='\n'.join('    '+line for line in json.dumps(row,ensure_ascii=ascii_mode,indent=2).splitlines())
            if text.count(block) != 1:
                continue
            label='      "text": '+json.dumps(literal,ensure_ascii=ascii_mode)
            offset=block.find(label)
            if offset >= 0:
                result[text.count('\n',0,text.index(block)+offset)+1]='historical_build_output_copy_in_bound_json'
    return result



def receipt_bound_measurement_label_lines(source):
    """Historical measurement labels only, bound to an intact single-case receipt.

    Preserve the measurement verbatim. Its adjacent binding is not deletion
    authority: occupation, recovery, references and seven locks remain required.
    Unknown fields and every content reference still fail closed.
    """
    source = Path(source)
    binding = source.with_suffix('.binding.json')
    if (source.is_symlink() or source.name != 'readonly_candidate_sizes.json'
            or 'unity_queue_runs' not in source.parts
            or binding.is_symlink() or not binding.is_file()):
        return {}
    text = source.read_text()
    value = json.loads(text)
    bound = json.loads(binding.read_text())
    fields = {'version','measurement_sha256','receipt','receipt_sha256','case'}
    if (not isinstance(bound,dict) or set(bound) != fields
            or bound['version'] != 'scored-cache-measurement-label-binding.v1'
            or bound['measurement_sha256'] != sha(source)
            or not isinstance(value,dict) or set(value) != {'at','mode','results'}
            or value['mode'] != 'READ_ONLY_NOT_DELETION_AUTHORITY'
            or not isinstance(value['results'],list) or not value['results']
            or text != json.dumps(value,ensure_ascii=False,indent=2)+'\n'):
        return {}
    root = Path(*source.parts[:source.parts.index('unity_queue_runs')])
    receipt = Path(bound['receipt'])
    if (not receipt.is_absolute() or receipt.is_symlink() or not receipt.is_file()
            or receipt.resolve() != receipt.absolute() or receipt.name != 'receipt.json'
            or not receipt.is_relative_to(root/'cache_reclamation')
            or sha(receipt) != bound['receipt_sha256']):
        return {}
    saved = json.loads(receipt.read_text())
    case = bound['case']
    if (saved.get('version') != 'scored-unity-cache-reclamation.v1'
            or saved.get('scope') != 'single-scored-case'
            or saved.get('requested_case_id') != case
            or saved.get('scored_cases_checked') != [case]
            or saved.get('scan_errors') != [] or saved.get('tables_unchanged') is not True):
        return {}
    paths = {r['path'] for r in saved['results'] if r.get('case') == case}
    result,seen = {},set()
    for row in value['results']:
        if (not isinstance(row,dict) or set(row) != {'candidate','files','unqualified_allocated_bytes'}
                or not isinstance(row['candidate'],str) or row['candidate'] in seen
                or row['candidate'] not in paths
                or not eligible_path(Path(row['candidate']),root,case)
                or Path(row['candidate']).parent.name != 'Library'
                or Path(row['candidate']).name not in CACHE_KINDS
                or any(type(row[key]) is not int or row[key] < 0
                       for key in ('files','unqualified_allocated_bytes'))):
            return {}
        seen.add(row['candidate'])
        block = '\n'.join(' '*4+line for line in json.dumps(row,ensure_ascii=False,indent=2).splitlines())
        label = ' '*6+'"candidate": '+json.dumps(row['candidate'],ensure_ascii=False)
        if text.count(block) != 1:
            return {}
        result[text.count('\n',0,text.index(block)+block.index(label))+1] = 'sha_bound_readonly_cache_measurement_label'
    return result


def cache_validation_projection_lines(source):
    """Candidate labels in an exact SHA-bound full-result validation projection.

    The source diagnostics and reasons are still scanned as dependencies. A
    canonical copy of a prior deletion decision never reads cache contents.
    """
    source = Path(source)
    if (source.is_symlink() or source.name != 'real_case_validation.json'
            or 'unity_queue_runs' not in source.parts or 'cache' not in source.parent.name):
        return {}
    text = source.read_text()
    value = json.loads(text)
    fields = {'at','receipt','receipt_sha256','scan_errors','tables_unchanged',
              'deleted_allocated_bytes','free_bytes_before','free_bytes_after','results'}
    if (not isinstance(value,dict) or set(value) not in (fields, fields-{'at'})
            or value['scan_errors'] != [] or value['tables_unchanged'] is not True
            or text not in tuple(json.dumps(value,ensure_ascii=a,indent=2)+end
                                 for a in (False,True) for end in ('','\n'))):
        return {}
    root = Path(*source.parts[:source.parts.index('unity_queue_runs')])
    receipt = Path(value['receipt'])
    if (not receipt.is_absolute() or receipt.is_symlink() or not receipt.is_file()
            or receipt.resolve() != receipt.absolute() or receipt.name != 'receipt.json'
            or not receipt.is_relative_to(root/'cache_reclamation')
            or sha(receipt) != value['receipt_sha256']):
        return {}
    saved = json.loads(receipt.read_text())
    case = saved.get('requested_case_id')
    if (saved.get('version') != 'scored-unity-cache-reclamation.v1'
            or saved.get('scope') != 'single-scored-case' or not isinstance(case,str)
            or saved.get('scored_cases_checked') != [case]
            or any(value[k] != saved.get(k) for k in fields-{'at','receipt','receipt_sha256'})):
        return {}
    result = {}
    for row in saved['results']:
        if row.get('case') != case or not eligible_path(Path(row['path']),root,case):
            return {}
        for ascii_only in (False,True):
            block = '\n'.join(' '*4+line for line in json.dumps(row,ensure_ascii=ascii_only,indent=2).splitlines())
            if text.count(block) != 1:
                continue
            for index,line in enumerate(block.splitlines()):
                if line.startswith(' '*6+'"path":'):
                    number = text.count('\n',0,text.index(block))+index+1
                    result[number] = 'sha_bound_cache_validation_candidate_label'
    return result


def completion_retention_label_lines(source):
    """Only candidate labels copied from a SHA-bound successful cleanup receipt.

    Completion proofs retain evidence and report previous cache decisions. Their
    exact_preserved_paths labels do not consume cache contents. All other lines,
    including reasons and embedded source/digest bindings, remain live references.
    """
    source = Path(source)
    if (source.is_symlink() or 'unity_queue_runs' not in source.parts
            or not re.fullmatch(r'scored_post_cache_completion_verified_\d{8}_\d{6}\.json', source.name)):
        return {}
    text = source.read_text()
    value = json.loads(text)
    if (not isinstance(value, dict)
            or value.get('mode') != 'POST_SCOPED_CACHE_COMPLETION_AND_EVIDENCE_PRESERVATION_READ_ONLY'
            or value.get('all_raw_score_source_sha_and_eight_columns_intact') is not True
            or value.get('four_tables_unchanged_by_cleanup') is not True
            or value.get('no_deletion_or_scoring_calls') is not True
            or text not in tuple(json.dumps(value,ensure_ascii=a,indent=2)+end
                                 for a in (False, True) for end in ('','\n'))):
        return {}
    batch = Path(*source.parts[:source.parts.index('unity_queue_runs')])
    result = {}
    for section in value.values():
        if not isinstance(section,dict) or 'exact_preserved_paths' not in section:
            continue
        receipt = Path(section.get('cache_receipt', ''))
        if (not receipt.is_absolute() or receipt.is_symlink() or not receipt.is_file()
                or receipt.resolve() != receipt.absolute()
                or not receipt.is_relative_to(batch/'cache_reclamation')
                or receipt.name != 'receipt.json'
                or sha(receipt) != section.get('cache_receipt_sha256')):
            continue
        saved = json.loads(receipt.read_text())
        case = saved.get('requested_case_id')
        rows = saved.get('results', [])
        if (saved.get('version') != 'scored-unity-cache-reclamation.v1'
                or saved.get('scope') != 'single-scored-case'
                or saved.get('tables_unchanged') is not True or saved.get('scan_errors') != []
                or not isinstance(case,str) or saved.get('scored_cases_checked') != [case]
                or not isinstance(rows,list)
                or any(not isinstance(r,dict) or r.get('case') != case for r in rows)
                or section['exact_preserved_paths'] != [dict(path=r['path'],reason=r['reason'])
                    for r in rows if r.get('status') == 'PRESERVED']
                or section.get('exact_deleted_paths') != [r['path'] for r in rows if r.get('status') == 'DELETED']
                or section.get('deleted_allocated_bytes') != saved.get('deleted_allocated_bytes')):
            continue
        for row in section['exact_preserved_paths']:
            if not isinstance(row['path'],str) or not eligible_path(Path(row['path']),batch,case):
                continue
            for ascii_only in (False,True):
                block = '\n'.join(' '*6+line for line in json.dumps(row,ensure_ascii=ascii_only,indent=2).splitlines())
                if text.count(block) != 1:
                    continue
                label = ' '*8+'"path": '+json.dumps(row['path'],ensure_ascii=ascii_only)
                offset = block.find(label)
                if offset >= 0:
                    result[text.count('\n',0,text.index(block)+offset)+1] = 'sha_bound_completion_receipt_retention_candidate_label'
    return result


def reviewed_historical_scope_lines(source, roots=()):
    """Exact, reviewed historical paragraphs scoped by their unchanged receipts.

    No prose heuristic: source bytes, physical line and paragraph hash must all
    match the reviewed catalog. Missing/drifted receipts or unknown text retain
    their original dependency behavior. Same-case references remain protected.
    """
    source = Path(source)
    historical_md = source.suffix == '.md' and (source.name == 'current_plan.before.md' or source.name.startswith(
        ('current_plan.before_', 'whitebox_eval_current_plan.before_')))
    copied_review = bool(re.fullmatch(r'g\d{3}_remaining_reference_analysis_\d{8}_\d{4}\.json',source.name))
    if source.is_symlink() or not (historical_md or copied_review):
        return {}
    batches = {Path(r).resolve() for r in (*source.parents, *roots)
               if (Path(r)/'scores.md').is_file() and (Path(r)/'inventory.json').is_file()}
    if len(batches) != 1:
        return {}
    batch = next(iter(batches))
    if not source.resolve().is_relative_to(batch/'unity_queue_runs'):
        return {}
    catalog = Path(__file__).with_name('resources')/'cache_historical_scope_reviews.json'
    if not catalog.is_file() or catalog.is_symlink():
        return {}
    value = json.loads(catalog.read_text())
    if value.get('version') != 'unity-cache-reviewed-historical-scope.v1':
        return {}
    text = source.read_text().splitlines()
    digest = sha(source)
    result = {}
    for review in value['reviews']:
        matches = [r for r in review['sources']
                   if r['path'] == str(source.relative_to(batch)) and r['sha256'] == digest]
        for row in matches:
            number = row['physical_line']
            if (type(number) is not int or not 1 <= number <= len(text)
                    or hashlib.sha256(text[number-1].encode()).hexdigest() != review['line_sha256']):
                continue
            cases = set()
            valid = bool(review['receipts'])
            for binding in review['receipts']:
                receipt = batch/binding['path']
                if (receipt.is_symlink() or not receipt.is_file()
                        or receipt.resolve() != receipt.absolute()
                        or not receipt.is_relative_to(batch/'cache_reclamation')
                        or receipt.name != 'receipt.json' or sha(receipt) != binding['sha256']):
                    valid = False
                    break
                saved = json.loads(receipt.read_text())
                if (saved.get('version') != 'scored-unity-cache-reclamation.v1'
                        or saved.get('tables_unchanged') is not True or saved.get('scan_errors') != []):
                    valid = False
                    break
                checked = saved.get('scored_cases_checked', [])
                if (not checked or any(not re.fullmatch(r'(?:Astra|GLM|Sol)__G\d{3}_[A-Za-z0-9_]+', c) for c in checked)
                        or any(r.get('case') not in checked for r in saved.get('results', []))):
                    valid = False
                    break
                cases.update(checked)
            if valid and cases:
                result[number] = cases
    return result

def temp_burst_passive_reference_lines(source):
    """Recognize old stat-only census labels and bounded repair descriptions.

    These records describe prior inspections, not input dependencies. Only
    positive generated object filenames with no content digest are classified;
    evidence references, unknown schemas, hashes and sibling fields stay live.
    """
    source = Path(source)
    if source.is_symlink() or source.suffix != '.json':
        return {}
    if (source.name == 'design.json'
            and source.parent.name == 'scored_temp_burst_cache_repair_v1'
            and 'unity_queue_runs' in source.parts):
        text = source.read_text()
        value = json.loads(text)
        expected = {'cause','semantic_invariance','no_candidate_is_deletion_authority'}
        if (not isinstance(value,dict) or set(value) != expected
                or value['no_candidate_is_deletion_authority'] is not True
                or text != json.dumps(value,ensure_ascii=False,indent=2)+'\n'):
            return {}
        result = {}
        for key in ('cause','semantic_invariance'):
            message = value[key]
            # A bare cache type in an implementation description is a label.
            # A concrete path/file or a non-description schema remains binding.
            if (not isinstance(message,str) or '\n' in message or '\r' in message
                    or 'Temp/Burst' not in message
                    or re.search(r'Temp/Burst[/\\]|(?:test_data|workspaces|recovery_runs)/|(?:^|\s)/',message)):
                return {}
            label = '  '+json.dumps(key)+': '+json.dumps(message,ensure_ascii=False)
            result[text.count('\n',0,text.index(label))+1] = 'passive_cache_implementation_description'
        return result
    if (source.name != 'preserved_file_metadata_before.json'
            or not source.parent.name.startswith('whitebox_disk_cleanup_scored_')
            or 'docs' not in source.parts):
        return {}
    text = source.read_text()
    value = json.loads(text)
    if (not isinstance(value,dict)
            or text != json.dumps(value,ensure_ascii=False,indent=2)+'\n'
            or any(not isinstance(k,str) or not isinstance(item,list) or len(item)!=4
                   for k,item in value.items())):
        return {}
    result = {}
    # Traverse physical labels once; do not search the huge census per entry.
    for number,line in enumerate(text.splitlines(),1):
        if 'Temp/Burst/' not in line or not line.startswith('  "') or not line.endswith(': ['):
            continue
        key = json.loads(line[2:-3])
        stat = value[key]
        if (any(type(n) is not int or n < 0 for n in stat[:3])
                or stat[2] != 32768 or stat[3] is not None):
            continue
        match = re.fullmatch(
            r'(test_data/outputs/eval/playtest/[^/]+/.+/project)/Temp/Burst/'
            r'burst-aot[^/]+/lib_burst_generated_part_[0-9a-f]+\.(?:o|gbc)',key)
        if not match:
            continue
        path = Path.cwd()/match[1]/'Temp/Burst'
        names = re.findall(r'(?:Astra|GLM|Sol)__G\d{3}_[A-Za-z0-9_]+',key)
        root = Path.cwd()/Path(*Path(key).parts[:5])
        if names and eligible_path(path,root,names[0].split('__',2)[0]+'__'+names[0].split('__',2)[1]):
            result[number] = 'historical_stat_only_generated_cache_filename'
    return result


def temp_burst_validation_projection_lines(source):
    """SHA-bound single-case cache receipt projection; labels only, no reasons."""
    source = Path(source)
    if (source.is_symlink() or not source.name.endswith('.real_case_validation.json')
            or source.parent.name not in {'scored_temp_burst_cache_repair_v1',
                                          'scored_temp_burst_reference_roles_repair_v1'}
            or 'unity_queue_runs' not in source.parts):
        return {}
    text = source.read_text();value = json.loads(text)
    fields = {'case','receipt','receipt_sha256','deleted_allocated_bytes',
              'free_before','free_after','scan_errors','tables_unchanged','results'}
    if (not isinstance(value,dict) or set(value)!=fields
            or value['scan_errors']!=[] or value['tables_unchanged'] is not True
            or text!=json.dumps(value,ensure_ascii=False,indent=2)+'\n'):
        return {}
    root = Path(*source.parts[:source.parts.index('unity_queue_runs')])
    receipt = Path(value['receipt'])
    if (not receipt.is_absolute() or receipt.is_symlink() or not receipt.is_file()
            or receipt.resolve()!=receipt.absolute() or receipt.name!='receipt.json'
            or not receipt.is_relative_to(root/'cache_reclamation')
            or sha(receipt)!=value['receipt_sha256']):
        return {}
    saved=json.loads(receipt.read_text())
    if (saved.get('version')!='scored-unity-cache-reclamation.v1'
            or saved.get('requested_case_id')!=value['case']
            or saved.get('scope')!='single-scored-case'
            or saved.get('scan_errors')!=[] or saved.get('tables_unchanged') is not True
            or saved.get('include_temp_burst') is not True
            or any(saved.get(k)!=value[v] for k,v in [
                ('deleted_allocated_bytes','deleted_allocated_bytes'),
                ('free_bytes_before','free_before'),('free_bytes_after','free_after')])):
        return {}
    expected=[{k:row.get(k) for k in ('path','status','allocated_bytes','reason')}
              for row in saved['results']]
    if value['results']!=expected:
        return {}
    result={}
    for row in expected:
        path=Path(row['path'])
        if not eligible_path(path,root,value['case']):
            continue
        block='\n'.join('    '+x for x in json.dumps(row,ensure_ascii=False,indent=2).splitlines())
        label='      "path": '+json.dumps(row['path'],ensure_ascii=False)
        if text.count(block)==1:
            result[text.count('\n',0,text.index(block)+block.index(label))+1]='sha_bound_cache_validation_candidate_label'
    return result


def inspect_references(candidates, roots, excluded=(), classifications=None):
    """Fail closed on explicit cache references, retaining complete metadata files.

    Root project references alone do not make a regenerable cache into evidence;
    explicit Library/<kind> references do. Relative paths are matched with case
    identity of the referencing file; unscoped relative references protect all.
    """
    hits = {str(p): [] for _, p in candidates}
    errors = []
    # Candidate identity and marker are immutable during one locked scan.  Large
    # historical classification arrays can contain millions of physical lines;
    # rebuilding Path.parts for every line/candidate pair stalls live evaluation.
    # Preserve candidate order and every source/line/reference decision.
    candidate_rows = [(case, path, str(path), cache_marker(path))
                      for case, path in candidates]
    candidate_keys = {key for _, _, key, _ in candidate_rows}
    markers = {marker for _, _, _, marker in candidate_rows}
    for source in metadata_files(roots):
        if any(source.is_relative_to(x) for x in excluded):
            continue
        try:
            receipt = False
            if source.name == 'receipt.json' and 'cache_reclamation' in source.parts:
                receipt = json.loads(source.read_text()).get('version') == 'scored-unity-cache-reclamation.v1'
            historical = historical_enumeration_lines(source)
            historical.update(generated_inventory_lines(source))
            historical.update(completion_retention_label_lines(source))
            historical.update(cache_validation_projection_lines(source))
            historical.update(receipt_bound_measurement_label_lines(source))
            historical.update(embedded_historical_build_output_lines(source))
            if 'Temp/Burst' in markers:
                historical.update(temp_burst_passive_reference_lines(source))
                historical.update(temp_burst_validation_projection_lines(source))
            scoped_history = receipt_bound_history_lines(source, roots)
            reviewed_history = reviewed_historical_scope_lines(source, roots)
            enumeration = candidate_enumeration_paths(source)
            # A validated generated candidate label occupies the entire physical
            # line. Recognize it once, before the candidate cross-product. Other
            # lines (including every source reference) still use normal checks.
            enumeration_labels = {label:key for key in enumeration & candidate_keys
                for label in (json.dumps(key)+': [', json.dumps(key)+': []', '"candidate": '+json.dumps(key))}
            digest = None
            classified = set()
            # A repeated literal line is terminal only after every classification
            # is recorded and every dependency hit for that line is saturated.
            # Never reuse per-line history/receipt exemptions at another line.
            terminal_lines = set()
            known_cases = re.findall(r'(?:Astra|GLM|Sol)__G\d{3}_[A-Za-z0-9_]+', str(source))
            with source.open('r', errors='surrogateescape') as stream:
                for line_no, line in enumerate(stream, 1):
                    line = line.replace('\\/', '/')
                    if not any(marker in line for marker in markers):
                        continue
                    label = line.strip().rstrip(',')
                    generated = enumeration_labels.get(label)
                    if generated is not None:
                        role = 'generated_cache_candidate_enumeration'
                        if classifications is not None and (generated,role) not in classified:
                            classified.add((generated,role))
                            if digest is None:
                                digest = sha(source)
                            classifications.append({'source':str(source), 'physical_line':line_no,
                                'source_sha256':digest, 'candidate':generated, 'role':role})
                        continue
                    line_independent = (line_no not in historical and line_no not in scoped_history
                                        and line_no not in reviewed_history)
                    if line_independent and line in terminal_lines:
                        continue
                    terminal = True
                    tokens = re.findall(r'[^\s"\x27`{}\[\],]+', line)
                    for case, path, key, marker in candidate_rows:
                        if classifications is None and len(hits[key]) >= 20:
                            continue
                        if marker not in line:
                            continue
                        enumerated = key in enumeration and label in (
                            json.dumps(key)+': [', json.dumps(key)+': []', '"candidate": '+json.dumps(key))
                        reviewed_cases = reviewed_history.get(line_no)
                        reviewed_role = ('reviewed_receipt_bound_history_of_other_case'
                            if reviewed_cases and case not in reviewed_cases and key not in line else None)
                        other_history_case = scoped_history.get(line_no)
                        scoped_role = ('receipt_bound_history_of_other_case'
                            if other_history_case and other_history_case != case and key not in line else None)
                        role = ('generated_cache_candidate_enumeration' if enumerated
                                else historical.get(line_no) or scoped_role or reviewed_role or reference_role(source, line, path, receipt, tokens=tokens))
                        if role != 'possible_evidence_dependency':
                            if classifications is not None and (key,role) not in classified:
                                classified.add((key,role))
                                if digest is None:
                                    digest = sha(source)
                                classifications.append({'source':str(source), 'physical_line':line_no,
                                    'source_sha256':digest, 'candidate':key, 'role':role})
                            continue
                        if key in line or (case in str(source) or not known_cases):
                            if len(hits[key]) < 20:
                                if digest is None:
                                    digest = sha(source)
                                hits[key].append({'source': str(source), 'physical_line': line_no,
                                                  'source_sha256': digest, 'role':role})
                            if len(hits[key]) < 20:
                                terminal = False
                    if terminal and line_independent and len(line) <= 4096 and len(terminal_lines) < 8192:
                        terminal_lines.add(line)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append({'source': str(source), 'error': str(exc)})
    # An unreadable metadata source invalidates proof; no deletion is then allowed.
    return hits, errors


def idle_snapshot():
    process = subprocess.run(['ps', '-axo', 'pid=,ppid=,command='], capture_output=True,
                             text=True, check=True).stdout
    active = [line for line in process.splitlines() if any(t in line for t in
              ('/Unity.app/Contents/MacOS/Unity', '/Tuanjie.app/Contents/MacOS/',
               '-m pipeline.game_eval.whitebox_eval.unity_single',
               '-m pipeline.game_eval.whitebox_eval.unity_queue '))]
    if active:
        raise RuntimeError('Active evaluator/Unity processes: ' + '\n'.join(active))
    opened = subprocess.run(['lsof', '-nP', '-F', 'pn'], capture_output=True, text=True)
    if opened.returncode not in (0, 1) or not opened.stdout:
        raise RuntimeError('Cannot verify open file usage: ' + opened.stderr)
    return {'processes': process, 'open_files': opened.stdout,
            'open_file_warnings': opened.stderr}


def select_scored(scored, case_id=None):
    """Limit candidate generation to one persisted case, never weaken references."""
    if case_id is None:
        return scored
    if not isinstance(case_id, str) or case_id not in scored:
        raise ValueError('Requested cache case lacks a complete persisted score: '+str(case_id))
    return {case_id: scored[case_id]}


def deletion_pause(control, case_id=None):
    """A scoped bulk pause permits only an explicitly authorized scored case."""
    marker = Path(control)/'cache_deletion_paused.json'
    if not marker.exists():
        return None
    identity = {'path': str(marker), 'sha256': sha(marker)}
    try:
        value = json.loads(marker.read_text())
    except (OSError, ValueError):
        return dict(identity, reason='Unreadable cache deletion pause; fail closed')
    if not isinstance(value, dict):
        return dict(identity, reason='Invalid cache deletion pause; fail closed')
    authority = value.get('per_case_authorization', {})
    if not isinstance(authority, dict):
        return dict(identity, reason='Invalid per-case authorization; fail closed')
    if (value.get('schema') == 'whitebox-cache-deletion-scope.v1'
            and value.get('paused') is True and value.get('scope') == 'bulk_only'
            and isinstance(case_id, str) and case_id
            and authority.get('enabled') is True
            and authority.get('date') == '2026-10-31'
            and authority.get('source') == 'explicit_user_instruction'
            and authority.get('require_complete_score_and_sources') is True
            and authority.get('require_all_locks_and_reference_checks') is True):
        return None
    return dict(identity, reason='Explicit user cache deletion pause')


def run(batch, control, output, apply=False, *, case_id=None, include_temp_burst=False):
    if include_temp_burst and case_id is None:
        raise ValueError('Temp/Burst reclamation requires one exact scored case')
    batch, control, output = Path(batch).resolve(), Path(control).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    locks = [control/'whitebox_production_queue.lock',
             *[control/f'serial_{i}.lock' for i in range(3)],
             Path('/tmp/gamefactory-sol-whitebox-gui.lock'),
             Path('/tmp/gamefactory-native-playtest-gui.lock'), batch/'.targeted_publication.lock']
    with ExitStack() as stack:
        for p in locks:
            f = stack.enter_context(p.open('a+'))
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshot = idle_snapshot()
        (output/'processes.txt').write_text(snapshot.pop('processes'))
        (output/'open_files.txt').write_text(snapshot['open_files'])
        scored = select_scored(scored_cases(batch), case_id)
        sources = persisted_sources(batch, scored)
        table_shas = {n: sha(batch/n) for n in
                      ('scores.md', 'score_new.md', 'score_verify.md', 'final_report.md')}
        candidates, preserved_libraries = [], []
        for root, dirs, files in os.walk(batch, followlinks=False):
            if include_temp_burst and 'Temp' in dirs:
                extra = Path(root)/'Temp/Burst'
                if extra.is_dir() and eligible_path(extra, batch, case_id):
                    candidates.append((case_id, extra))
            dirs[:] = [d for d in dirs if d not in {'node_modules', '.git', 'Temp', 'obj'}
                       and not (Path(root)/d).is_symlink()]
            if 'Library' not in dirs:
                continue
            dirs.remove('Library')
            lib = Path(root)/'Library'
            case = next((c for c in scored if c in str(lib)), None)
            preserved_libraries.append({'path': str(lib), 'case': case,
                'reason': 'whole Library never deleted; GameFactory3A/logs/unclassified contents preserved'
                          if case else 'unscored/out-of-scope project; untouched'})
            if not case:
                continue
            for name in sorted(CACHE_KINDS):
                p = lib/name
                if p.is_dir() and eligible_path(p, batch, case):
                    candidates.append((case, p))
        classifications = []
        hits, scan_errors = inspect_references(candidates, [batch, control,
                Path.cwd()/'docs'], excluded=[output], classifications=classifications)
        before = shutil.disk_usage(batch).free
        receipt = {'version': 'scored-unity-cache-reclamation.v1',
            'at': datetime.datetime.now().astimezone().isoformat(), 'apply': apply,
            'locks': [str(p) for p in locks], 'scored_cases_checked': list(scored),
            'include_temp_burst': include_temp_burst,
            'requested_case_id': case_id, 'scope': 'single-scored-case' if case_id is not None else 'all-scored-cases',
            'score_rows': scored, 'score_sources': sources, 'table_sha256': table_shas, 'scan_errors': scan_errors,
            'free_bytes_before': before, 'results': [], 'preserved_libraries': preserved_libraries}
        classification_path = output/'reference_classifications.json'
        classification_path.write_text(json.dumps(classifications, ensure_ascii=False, indent=2)+'\n')
        receipt['reference_classifications'] = str(classification_path)
        receipt['reference_classifications_sha256'] = sha(classification_path)
        def save():
            (output/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
        save()
        for i, (case, path) in enumerate(candidates):
            result = {'case': case, 'path': str(path), 'status': 'PRESERVED'}
            receipt['results'].append(result)
            try:
                if 'error' in sources[case]:
                    raise ValueError(sources[case]['error'])
                if scan_errors:
                    raise ValueError('metadata scan incomplete')
                if hits[str(path)]:
                    result['references'] = hits[str(path)]
                    raise ValueError('explicit cache path reference; retain for audit/recovery')
                if str(path) in snapshot['open_files']:
                    raise ValueError('open file or cwd dependency')
                files = cache_files(path)
                result.update(file_count=len(files), bytes=sum(f['bytes'] for f in files),
                              allocated_bytes=sum(f['allocated_bytes'] for f in files))
                listing = output/f'candidate_{i:03d}.json'
                listing.write_text(json.dumps(files, ensure_ascii=False, indent=2)+'\n')
                result['file_list'] = str(listing)
                result['file_list_sha256'] = sha(listing)
                # Recheck scores and process state immediately before exact-path removal.
                if scored_cases(batch).get(case) != scored[case]:
                    raise ValueError('persisted complete score changed')
                fresh = idle_snapshot()
                if str(path) in fresh['open_files']:
                    raise ValueError('new open-file dependency')
                if not eligible_path(path, batch, case):
                    raise ValueError('path identity changed')
                result['status'] = 'SAFE_PREVIEW'
                save()
                pause = deletion_pause(control, case_id) if apply else None
                if pause:
                    result['status'] = 'PRESERVED_PAUSED'
                    result['reason'] = pause['reason']
                    receipt['deletion_pause'] = pause
                elif apply:
                    shutil.rmtree(path)
                    if path.exists():
                        raise RuntimeError('cache still present after removal')
                    result['status'] = 'DELETED'
            except Exception as exc:
                result['reason'] = str(exc)
                if result['status'] == 'SAFE_PREVIEW':
                    result['status'] = 'DELETE_FAILED'
            save()
        receipt['free_bytes_after'] = shutil.disk_usage(batch).free
        receipt['free_bytes_delta'] = receipt['free_bytes_after'] - before
        receipt['deleted_allocated_bytes'] = sum(r.get('allocated_bytes', 0) for r in receipt['results'] if r['status']=='DELETED')
        receipt['cleaned_cases'] = sorted({r['case'] for r in receipt['results'] if r['status']=='DELETED'})
        receipt['table_sha256_after'] = {n: sha(batch/n) for n in table_shas}
        receipt['tables_unchanged'] = receipt['table_sha256_after'] == table_shas
        save()
        return receipt


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch', required=True, type=Path)
    p.add_argument('--control-root', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--case-id', help='Exact scored identity; generate candidates only for this case')
    a = p.parse_args()
    r = run(a.batch, a.control_root, a.output, a.apply, case_id=a.case_id)
    print(json.dumps({k:r[k] for k in ['cleaned_cases','deleted_allocated_bytes',
          'free_bytes_after','free_bytes_delta','tables_unchanged']}, ensure_ascii=False))

if __name__ == '__main__':
    main()
