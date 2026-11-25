"""Independent, source-only Unity M inventory. Never widens the legacy S scope.

Existing original identities win over discovery ranking. New identities use only
run/stage/path ordering, never launch success or scores. Fixed remote originals
are verified in full; changed/missing local bytes are retained and a distinct
immutable remote tree is materialized when needed.
"""
from pathlib import Path
import copy
import hashlib
import json
import os
import subprocess
from collections import Counter
from . import batch, inventory as discovery, mechanic_v3_runner as runner
from . import mechanic_v3_revision as revisions
from .protocol import sha

VERSION = 'unity-m-original-five-model-scope.v1'
MODELS = ('GLM', 'Astra', 'Opus', 'Sol', 'Kimi')
FIELDS = ('id', 'method', 'case_id', 'tier', 'actual_engine', 'project',
          'requirement_sha256', 'frozen_sha256', 'marker_sha256')
# These exact paths are outputs of the delivered diagnostic launch_session.py.
# They remain on disk and are not evidence selected for this evaluation.
DIAGNOSTIC_FRAMES = {'validation/playtest/session01/frames_A',
                     'validation/playtest/session01/frames_B'}


def select(found, previous, alternate):
    """Preserve a previous delivered original even if it is now missing."""
    if previous and previous.get('project'):
        return copy.deepcopy(previous), 'PRESERVED_ORIGINAL_IDENTITY'
    candidates = list(found.get('all_candidates', [])) + list(alternate)
    # No engine/launch/score preference: select the original run then its stage.
    candidates.sort(key=lambda c: (Path(c['generation_run']).name,
        c['stage'] != 'pipeline', c['depth'], c['marker']))
    row = copy.deepcopy(found)
    if not candidates:
        return row, 'NO_DELIVERED_PROJECT'
    c = candidates[0]
    row.update(project=c['project'], actual_engine=c['engine'],
        project_marker=c['marker'], marker_sha256=c['marker_sha256'],
        generation_run=c['generation_run'], delivery_stage=c['stage'],
        selected_candidate=c, all_candidates=candidates,
        engine_mismatch=c['engine'] != row['expected_engine'])
    row['method_directory'] = Path(c['generation_run']).parent.parent.name
    return row, 'ORIGINAL_RUN_STAGE_PATH_ORDER_NO_LAUNCH_OR_SCORE'


def tree_rows(data):
    result = {}
    for record in data.split(b'\0'):
        if not record:
            continue
        meta, name = record.split(b'\t', 1)
        mode, kind, blob = meta.decode().split()
        if kind == 'blob':
            result[os.fsdecode(name)] = dict(mode=mode, blob=blob)
    return result


def raw(path):
    return os.readlink(path).encode() if path.is_symlink() else path.read_bytes()


def blob_digest(data):
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()


def source_files(project):
    if not project.is_dir():
        return {}
    result = {}
    for folder, dirs, files in os.walk(project, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in (discovery.SKIP-{'eval'})
                         and d not in {'.cache','.vite','.import'}
                         and (Path(folder)/d).relative_to(project).as_posix() not in DIAGNOSTIC_FRAMES)
        for name in sorted(files):
            path = Path(folder)/name
            if path.is_symlink():
                raise ValueError('Source symlink needs explicit target provenance: '+str(path))
            result[path.relative_to(project).as_posix()] = sha(path)
        for name in dirs:
            if (Path(folder)/name).is_symlink():
                raise ValueError('Source directory symlink needs explicit provenance: '+str(Path(folder)/name))
    return result


def verify_original(repo, workspace, entry, tree, revision, repository):
    project = Path(entry['project'])
    relative = project.relative_to(repo).as_posix()
    prefixes = [relative]
    if entry['method'] == 'Astra' and '/gpt_astra6/' in relative:
        prefixes.append(relative.replace('/gpt_astra6/', '/gpt_astra/', 1))
    prefix = next((p for p in prefixes if p+'/ProjectSettings/ProjectVersion.txt' in tree), None)
    local = source_files(project)
    receipt = dict(repository=repository, revision=revision, original_run=entry['generation_run'],
        original_project=str(project), remote_project=prefix, local_file_count=len(local),
        original_local_sha256=local, downloaded_files=[], copied_verified_files=[], files=[])
    receipt['preserved_diagnostic_frames_not_author_assets'] = [
        str(project/p) for p in sorted(DIAGNOSTIC_FRAMES) if (project/p).is_dir()]
    if prefix is None:
        receipt.update(status='LOCAL_ORIGINAL_REMOTE_UNVERIFIED', source_hashes=local,
            actual_download_bytes=0, source_project=str(project))
        return entry, receipt
    tracked = {p[len(prefix)+1:]:v for p,v in tree.items() if p.startswith(prefix+'/')}
    if any(v['mode'] not in {'100644','100755'} for v in tracked.values()):
        raise ValueError('Remote project contains a non-regular original file; explicit source review required')
    exact = set(local) == set(tracked) and all(
        blob_digest(raw(project/p)) == v['blob'] for p,v in tracked.items())
    destination = project if exact else workspace/'sources'/revision/prefix
    hashes = {}
    for rel, meta in sorted(tracked.items()):
        source = project/rel
        matching = source.is_file() and not source.is_symlink() and blob_digest(raw(source)) == meta['blob']
        content = raw(source) if matching else subprocess.check_output(
            ['git','-C',str(repo),'cat-file','blob',meta['blob']])
        if blob_digest(content) != meta['blob']:
            raise ValueError('Fixed remote Git object mismatch: '+rel)
        target = destination/rel
        if not exact:
            target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if raw(target) != content:raise ValueError('Preserved remote original changed: '+str(target))
            else:
                with target.open('xb') as stream:stream.write(content)
                target.chmod(0o755 if meta['mode']=='100755' else 0o644)
        digest = hashlib.sha256(content).hexdigest(); hashes[rel] = digest
        row = dict(remote_path=prefix+'/'+rel, git_blob=meta['blob'], sha256=digest,
                   path=str(target), bytes=len(content), action='LOCAL_EXACT_REUSE' if exact else
                   'VERIFIED_LOCAL_COPY' if matching else 'FIXED_GIT_OBJECT_DOWNLOAD')
        receipt['files'].append(row)
        if not matching:receipt['downloaded_files'].append(row)
        elif not exact:receipt['copied_verified_files'].append(row)
    changed = copy.deepcopy(entry)
    changed.update(project=str(destination), project_marker=str(destination/'ProjectSettings/ProjectVersion.txt'),
                   marker_sha256=hashes['ProjectSettings/ProjectVersion.txt'])
    receipt.update(status='FIXED_REMOTE_EXACT', source_hashes=hashes, source_project=str(destination),
        actual_download_bytes=sum(x['bytes'] for x in receipt['downloaded_files']),
        local_extra_paths=sorted(set(local)-set(tracked)), local_original_unchanged=True)
    return changed, receipt


def load(workspace):
    workspace = Path(workspace).resolve()
    pointer = runner.read(workspace/'unity_m_scope.json')
    path = workspace/'scopes/unity_m_original/scope.json'
    if pointer.get('version') != VERSION or pointer['sha256'] != sha(path):
        raise ValueError('Unity M independent scope changed')
    scope = runner.read(path)
    if (scope['version'] != VERSION or scope['revision'] != 'outcome_frame_v1'
            or scope['models'] != list(MODELS) or scope['columns'] != ['Mechanic','Gameness']
            or scope['model'] != 'gpt-6.1-sol'):
        raise ValueError('Unity M scope authorization differs')
    for name, digest in scope['bindings'].items():
        if sha(Path(name)) != digest:raise ValueError('Unity M source binding changed: '+name)
    inv = runner.read(workspace/'inventory.json')
    if sha(workspace/'inventory.json') != scope['inventory_sha256']:
        raise ValueError('Unity M inventory changed')
    identities = []
    for row in inv['entries']:
        e = row['entry']
        if e['method'] not in MODELS or e['tier'] != 'M' or not 1 <= int(e['case_id'][1:4]) <= 60:
            raise ValueError('Out-of-range identity')
        if row['in_scope']:
            if e['actual_engine'] != 'unity3d':raise ValueError('Non-Unity target')
            identities.append(e['id'])
    if identities != scope['selected_identities'] or len(identities) != len(set(identities)):
        raise ValueError('Frozen identity set differs')
    inv.update(active_selection=identities, full_scope_binding=dict(path=str(path),sha256=sha(path)),
               unity_m_scope=True)
    return inv


def freeze(workspace, discovery_path, legacy_path, alternate_path, tree_path, revision, recovery=None):
    workspace = Path(workspace).resolve()
    if (workspace/'unity_m_scope.json').exists():return load(workspace)
    inputs={str(Path(p).resolve()):sha(Path(p)) for p in (discovery_path,legacy_path,alternate_path,tree_path)}
    retained={}
    if workspace.exists() and any(workspace.iterdir()):
        if recovery is None:raise ValueError('Preserve partial source freeze for explicit recovery')
        repair=runner.read(Path(recovery))
        if (repair.get('workspace')!=str(workspace) or repair.get('inputs')!=inputs
                or repair.get('revision')!=revision or repair.get('model_calls')!=0
                or repair.get('source_files_deleted')!=0):
            raise ValueError('Exact partial source-freeze recovery required')
        for name,digest in repair['retained_receipts'].items():
            path=Path(name)
            if path.parent!=workspace/'source_receipts' or sha(path)!=digest:
                raise ValueError('Original source receipt changed')
            retained[path.stem]=runner.read(path)
        if (workspace/'inventory.json').exists():raise ValueError('Completed inventory cannot be replaced')
    workspace.mkdir(parents=True,exist_ok=True)
    runner.disk(workspace,'unity_m_source_freeze',4*1024**3)
    repo=Path(__file__).resolve().parents[3]
    resolved=subprocess.check_output(['git','-C',str(repo),'rev-parse',revision],text=True).strip()
    if revision != resolved:raise ValueError('Full immutable remote revision required')
    actual=subprocess.check_output(['git','-C',str(repo),'ls-tree','-r','-z',revision,'--','test_data/outputs/initial_game_gen'])
    if actual != Path(tree_path).read_bytes():raise ValueError('Fixed remote tree differs')
    repository=subprocess.check_output(['git','-C',str(repo),'remote','get-url','origin'],text=True).strip()
    found=runner.read(Path(discovery_path)); legacy=runner.read(Path(legacy_path))
    old={e['id']:e for e in legacy['entries']}
    alternate={x['case']:x['selection']['all_candidates'] for x in runner.read(Path(alternate_path))}
    bindings=inputs
    if recovery is not None:bindings[str(Path(recovery).resolve())]=sha(Path(recovery))
    tree=tree_rows(actual); rows=[]
    for item in found['entries']:
        entry, selection=select(item,old.get(item['id']),alternate.get(item['case_id'],[]) if item['method']=='Kimi' else [])
        in_scope=entry['actual_engine']=='unity3d'
        provenance=None;hashes={};blocker=None
        if in_scope and entry.get('project'):
            if entry['id'] in retained:
                provenance=retained[entry['id']]
                if (provenance['original_project']!=entry['project'] or provenance['revision']!=revision
                        or provenance['original_run']!=entry['generation_run']):
                    raise ValueError('Retained original identity changed')
                marker=Path(entry['project_marker']).relative_to(Path(entry['project']))
                entry['project']=provenance['source_project']
                entry['project_marker']=str(Path(entry['project'])/marker)
                if marker.as_posix() in provenance['source_hashes']:
                    entry['marker_sha256']=provenance['source_hashes'][marker.as_posix()]
                enumerated=source_files(Path(entry['project']))
                if enumerated!=provenance['source_hashes']:
                    raise ValueError('Retained source enumeration changed; explicit receipt amendment required: '+entry['id'])
                for rel,digest in provenance['source_hashes'].items():
                    if sha(Path(entry['project'])/rel)!=digest:raise ValueError('Retained original changed: '+rel)
            else:entry, provenance=verify_original(repo,workspace,entry,tree,revision,repository)
            hashes=provenance['source_hashes']
            if not hashes:blocker='MISSING_ORIGINAL_PROJECT'
            elif not (Path(entry['project'])/'Assets').is_dir():blocker='MISSING_AUTHOR_ASSETS_ENTRY'
            proof=workspace/'source_receipts'/(entry['id']+'.json')
            if not proof.exists():runner.exclusive_json(proof,provenance)
            bindings[str(proof)]=sha(proof)
            for name,digest in hashes.items():bindings[str(Path(entry['project'])/name)]=digest
        for key in ('requirement','frozen_rubric'):
            bindings[entry[key]]=sha(Path(entry[key]))
        rows.append(dict(entry=entry,in_scope=in_scope,source_batch=str(Path(legacy_path).resolve().parent),
            selection=selection,discovered=item,source_hashes=hashes,source_provenance=provenance,
            source_blocker=blocker,historical_attempts=[],record_candidates=[],preferred_record=None))
        print(entry['id'], 'UNITY_M' if in_scope else 'OUTSIDE_ACTUAL_UNITY',
              provenance['status'] if provenance else '',blocker or '',flush=True)
    inv=dict(version=VERSION,entries=rows,created=runner.stamp(),selection='Preserve frozen original; new run/stage/path ordering; no launch/score preference')
    runner.exclusive_json(workspace/'inventory.json',inv)
    runner.exclusive_json(workspace/'assessment_revision.json',dict(revision='outcome_frame_v1',uniform_outcome_blind_correction=True,
        authorization='AGENTS.md 2026-11-06 and explicit five-model Unity M execution',model='gpt-6.1-sol'))
    scope=dict(version=VERSION,revision='outcome_frame_v1',models=list(MODELS),columns=['Mechanic','Gameness'],model='gpt-6.1-sol',
        source_workspace=str(workspace),bindings=bindings,inventory_sha256=sha(workspace/'inventory.json'),
        selected_identities=[r['entry']['id'] for r in rows if r['in_scope']],
        denominators=dict(Counter(r['entry']['method'] for r in rows if r['in_scope'])),
        remote_revision=revision,repository=repository,old_s_scope_unchanged=True)
    target=workspace/'scopes/unity_m_original/scope.json';runner.exclusive_json(target,scope)
    runner.exclusive_json(workspace/'unity_m_scope.json',dict(version=VERSION,sha256=sha(target)))
    return load(workspace)
