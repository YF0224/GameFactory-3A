"""Freeze original Kimi deliveries independently, retaining source blockers.

Discovery considers both published directory spellings and every original run.
An actual engine determines scope; missing remote proof blocks execution rather
than removing a target identity. No score or launch result selects a delivery.
"""
from pipeline.eval.stage1.paths import DATA_ROOT
from pathlib import Path
import copy,json,shutil
from . import inventory as deliveries,batch,mechanic_v3_full_scope as scope
from . import mechanic_v3_revision as revisions,mechanic_v3_runner as runner
from .protocol import sha,dump
VERSION='kimi-original-fixed-source-scope.v1'

def freeze(workspace,source_workspace,source_manifest):
 workspace,source_workspace,source_manifest=map(lambda p:Path(p).resolve(),(workspace,source_workspace,source_manifest))
 if (workspace/'full_s_scope.json').exists():return scope.load(workspace)
 if workspace.exists() and any(workspace.iterdir()):raise ValueError('Preserve partial Kimi freeze for explicit recovery')
 inventory=json.loads(source_manifest.read_bytes())
 if inventory.get('version')!='kimi-original-all-candidate-inventory.v1' or inventory.get('excluded_by_score_or_playability'):
  raise ValueError('Complete all-run original source inventory required')
 repo=Path(__file__).resolve().parents[3];framework=repo
 candidates=[r for r in inventory['rows'] if r['tier']=='S' and 1<=int(r['case_id'][1:4])<=60]
 cases=sorted({r['case_id'] for r in candidates})
 raw=deliveries.build_inventory(repo,framework,case_ids=cases,methods=['Kimi'])
 parents=scope.load(source_workspace);default_batch=next(r['source_batch'] for r in parents['entries'])
 download_receipt=source_manifest.parent/'download_verification_manifest.json'
 if not download_receipt.is_file():raise ValueError('Actual fixed remote download/verification receipt required')
 verified_download=runner.read(download_receipt)
 if verified_download.get('version')!='kimi-original-download-verification.v1' or any(verified_download[k]!=inventory['fixed_verified_remote'][k] for k in ('repository','revision')):raise ValueError('Fixed remote download receipt differs')
 bindings={str(source_manifest):sha(source_manifest),str(download_receipt):sha(download_receipt)};rows=[];facts=[]
 for found in raw['entries']:
  case=found['case_id'];runs=[r for r in candidates if r['case_id']==case]
  discovered=[]
  for d in ['kimi-k3','kimi_k3']:
   directory=DATA_ROOT/'outputs/initial_game_gen'/d/case
   selection=deliveries.delivery_selection(directory,found['expected_engine'])
   discovered.extend((x,d,selection) for x in selection['all_candidates'])
  ranked=sorted(discovered,key=lambda x:x[0]['marker'])
  ranked.sort(key=lambda x:Path(x[0]['generation_run']).name,reverse=True)
  ranked.sort(key=lambda x:deliveries.candidate_priority(x[0],found['expected_engine']))
  entry=copy.deepcopy(found)
  if ranked:
   selected,directory,selection=ranked[0];run=Path(selected['generation_run'])
   proofs=[r for r in runs if Path(r['run']).resolve()==run.resolve()]
   if len(proofs)!=1:raise ValueError('Chosen original must occur once in full source manifest')
   proof=proofs[0]
   entry.update(selection,method_directory=directory,generation_run=str(run),selected_candidate=selected,
     all_candidates=[x[0] for x in ranked],candidates=[x[0] for x in ranked],project=selected['project'],
     actual_engine=selected['engine'],project_marker=selected['marker'],marker_sha256=selected['marker_sha256'],
     delivery_stage=selected['stage'],status='PENDING',engine_mismatch=selected['engine']!=found['expected_engine'])
  else:
   if len(runs)!=1:raise ValueError('Missing original project must retain an unambiguous run')
   proof=runs[0];entry.update(method_directory=proof['method_directory'],generation_run=proof['run'])
  for f in proof['source_files']:
   path=Path(f['path'])
   if path.is_symlink():
    import hashlib,os
    digest=hashlib.sha256(os.readlink(path).encode()).hexdigest()
   else:digest=sha(path)
   if digest!=f['sha256']:raise ValueError('Original source inventory file changed: '+str(path))
   if not path.is_symlink():bindings[str(path.resolve())]=digest
  project=Path(entry['project']) if entry.get('project') else None
  hashes=batch.hashes(project) if project else {}
  bindings.update({str(project/n):d for n,d in hashes.items()})
  for field in ['requirement','frozen_rubric']:bindings[entry[field]]=sha(Path(entry[field]))
  eligible=entry.get('actual_engine') in {'godot','three_js'}
  # The complete source receipt, not a directory name, supplies provenance.
  verified=all(f.get('remote_verified') is True for f in proof['source_files'])
  state='FIXED_REMOTE_EXACT' if verified else 'SOURCE_PENDING_REMOTE_PROOF'
  rows.append(dict(entry=entry,source_batch=default_batch,in_scope=eligible,source_hashes=hashes,
    historical_attempts=[],record_candidates=[],preferred_record=None,
    initial_stage='NEEDS_ENTRY_PLAN_RECORD' if eligible and verified else state if eligible else 'UNRESOLVED_ORIGINAL_SOURCE_AND_ENGINE',
    source_provenance=dict(status=state,manifest=str(source_manifest),manifest_sha256=sha(source_manifest),
      repository=inventory['fixed_verified_remote']['repository'],revision=inventory['fixed_verified_remote']['revision'],
      original_run=proof['original_run_id'],no_cross_run_merging=True,download_receipt=dict(path=str(download_receipt),sha256=sha(download_receipt))),upload_provenance=None,
    exclusion_reason=None if eligible else 'SOURCE_AND_ENGINE_UNRESOLVED: local metadata only; remote original absence is not established; preserve candidate for source-bound scope revision'))
  facts.append(dict(case_id=case,original_runs=[r['run'] for r in runs],actual_engine=entry.get('actual_engine'),in_scope=eligible,source_status=state))
 workspace.mkdir(parents=True);runner.disk(workspace,'freeze_kimi_originals',128*1024**2)
 runner.exclusive_json(workspace/'inventory.json',dict(version=scope.VERSION,created=runner.stamp(),cases=cases,
   selection=deliveries.SELECTION,entries=rows,all_engines_enumerated_before_eligibility=True,independent_reassessment=True,
   discovery_differences=[],candidate_facts=facts,source_manifest=str(source_manifest)))
 shutil.copy2(source_workspace/'assessment_revision.json',workspace/'assessment_revision.json')
 bindings[str(source_workspace/'assessment_revision.json')]=sha(source_workspace/'assessment_revision.json')
 for case in cases:
  src=revisions.contract_dir(source_workspace,case);dst=revisions.contract_dir(workspace,case);dst.mkdir(parents=True)
  for name in ['contract.json','frozen.json','source_binding.json']:
   shutil.copy2(src/name,dst/name);bindings[str(src/name)]=sha(src/name);bindings[str(dst/name)]=sha(dst/name)
  if sha(dst/'contract.json')!=runner.read(dst/'frozen.json')['contract_sha256']:raise ValueError('Same-question frozen contract changed')
  for name,digest in runner.read(dst/'source_binding.json')['bindings'].items():
   if sha(Path(name))!=digest:raise ValueError('Frozen goal source changed')
  dump(dst/'contract_origin.json',dict(path=str(src),same_visible_goals_for_all_models=True,old_verdict_reused=False))
 from .mechanic_v3_native import configuration
 configuration(workspace,Path(default_batch))
 value=dict(version=scope.VERSION,revision='outcome_frame_v1',created=runner.stamp(),
  inventory_sha256=sha(workspace/'inventory.json'),bindings=bindings,
  selected_identities=[r['entry']['id'] for r in rows if r['in_scope']],all_discovered_identities=[r['entry']['id'] for r in rows],
  source_workspace=str(source_workspace),old_results_preserved=True,authorized_columns=['Mechanic','Gameness'],
  model='gpt-6.1-sol',authorized_models=['Kimi'],authorized_engines=['godot','three_js'],kimi_source_scope=VERSION,unresolved_original_candidates=[r['entry']['id'] for r in rows if not r['in_scope']],scope_inventory_complete=not any(not r['in_scope'] for r in rows))
 path=workspace/'scopes/all_s_original/scope.json';runner.exclusive_json(path,value)
 runner.exclusive_json(workspace/'full_s_scope.json',dict(version=scope.VERSION,scope_sha256=sha(path)))
 runner.exclusive_json(workspace/'columns_authorization_20261103.json',dict(authorized_columns=['Mechanic','Gameness'],scope_binding=dict(path=str(path),sha256=sha(path)),authorization='Root AGENTS 2026-11-05 and user actual execution; independent original Kimi scope'))
 from .two_column_sync import TARGET
 runner.exclusive_json(workspace/'two_column_sync.json',dict(target=str(TARGET),scope_workspace=str(workspace)))
 scope.bind_observation_conditions(workspace)
 return scope.load(workspace)


def raw_digest(path):
 import hashlib,os
 path=Path(path)
 raw=os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
 return hashlib.sha256(raw).hexdigest(),hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


def verify_sources(workspace,row):
 """Require the independent fixed source proof for any Kimi execution/sync."""
 if row['entry']['method']!='Kimi':return None
 workspace=Path(workspace).resolve();frozen=runner.read(workspace/'scopes/all_s_original/scope.json')
 if (frozen.get('kimi_source_scope')!=VERSION or frozen.get('authorized_models')!=['Kimi']
     or row['entry']['id'] not in frozen['selected_identities'] or not row['in_scope']):
  raise ValueError('Kimi requires its own explicitly frozen source scope')
 provenance=row['source_provenance'];manifest=Path(provenance['manifest'])
 if sha(manifest)!=provenance['manifest_sha256']:raise ValueError('Kimi all-candidate source manifest changed')
 inventory=runner.read(manifest);receipt=provenance['download_receipt'];download=Path(receipt['path'])
 if sha(download)!=receipt['sha256']:raise ValueError('Kimi fixed download verification receipt changed')
 remote=runner.read(download)
 if (remote.get('version')!='kimi-original-download-verification.v1'
     or remote.get('repository')!=provenance['repository'] or remote.get('revision')!=provenance['revision']):
  raise ValueError('Kimi fixed remote revision differs')
 matches=[r for r in inventory['rows'] if Path(r['run']).resolve()==Path(row['entry']['generation_run']).resolve()]
 if len(matches)!=1:raise ValueError('Kimi original run is ambiguous')
 original=matches[0]
 if (provenance['status']!='FIXED_REMOTE_EXACT' or not original['source_files']
     or not all(f.get('remote_verified') is True for f in original['source_files'])):
  return verify_local_original(workspace,row,original,manifest,download)
 verified_files={f['local_path']:f for f in remote['files']}
 for f in original['source_files']:
  digest,blob=raw_digest(f['path']);prior=verified_files.get(f['path'])
  if digest!=f['sha256'] or blob!=f.get('git_blob') or prior is None or prior.get('sha256')!=digest or prior.get('git_blob')!=blob:
   raise ValueError('Kimi original raw file/symlink or fixed remote proof differs: '+f['path'])
 if batch.hashes(Path(row['entry']['project']))!=row['source_hashes']:
  raise ValueError('Kimi frozen original project changed')
 return provenance


LOCAL_AUTH = 'kimi_local_original_source_authorization.json'
LOCAL_VERSION = 'kimi-user-authorized-local-original.v1'
LOCAL_STATUS = 'USER_AUTHORIZED_LOCAL_ORIGINAL_REMOTE_UNVERIFIED'


def verify_local_original(workspace,row,original,manifest,download):
 """Admit only an explicitly authorized, unchanged local original.

 The immutable remote inventory retains its original pending status. A complete
 fixed-remote proof is handled by verify_sources first and never downgraded.
 The separate receipt is copied into the new input entry so recorded evidence
 retains the exact authorization SHA; no frozen identity or old bytes change.
 """
 auth=Path(workspace)/LOCAL_AUTH
 if not auth.is_file():
  raise ValueError('Kimi original SOURCE_PENDING_REMOTE_PROOF; preserve identity and retrieve original fixed source')
 value=runner.read(auth);frozen=Path(workspace)/'scopes/all_s_original/scope.json'
 if (value.get('version')!=LOCAL_VERSION or value.get('remote_preferred') is not True
     or value.get('remote_verified') is not False
     or value.get('scope_binding')!={'path':str(frozen.resolve()),'sha256':sha(frozen)}
     or value.get('source_manifest_binding')!={'path':str(manifest.resolve()),'sha256':sha(manifest)}
     or value.get('download_receipt_binding')!={'path':str(download.resolve()),'sha256':sha(download)}):
  raise ValueError('Local original authorization scope/source binding differs')
 user=value.get('user_authorization',{})
 if (user.get('response')!='开始' or user.get('steering')!='有远端的用远端'
     or user.get('local_originals_authorized') is not True
     or user.get('preserve_remote_unverified_status') is not True):
  raise ValueError('Explicit local original user authorization required')
 if row['source_provenance']['status']!='SOURCE_PENDING_REMOTE_PROOF':
  raise ValueError('Local original route cannot replace fixed remote qualification')
 entries=value.get('entries',[]);matches=[v for v in entries if v.get('identity')==row['entry']['id']]
 if len(matches)!=1 or len({v['identity'] for v in entries})!=len(entries):
  raise ValueError('Local original authorization identity absent or ambiguous')
 proof=matches[0];entry=row['entry']
 expected={k:entry.get(k) for k in ('id','generation_run','project','actual_engine','project_marker','marker_sha256')}
 if (proof.get('original_entry')!=expected or proof.get('source_hashes')!=row['source_hashes']
     or entry.get('actual_engine') not in {'godot','three_js'}
     or Path(original['run']).resolve()!=Path(entry['generation_run']).resolve()):
  raise ValueError('Local original run/entry/frozen project differs')
 files=proof.get('files',[])
 expected_files={f['path']:f['sha256'] for f in original['source_files']}
 if (not expected_files or len(files)!=len(expected_files)
     or {f['path']:f['sha256'] for f in files}!=expected_files):
  raise ValueError('Every original local source/asset file must remain bound')
 for f in files:
  digest,blob=raw_digest(f['path'])
  if digest!=f['sha256'] or blob!=f['git_blob']:
   raise ValueError('Local original raw source/asset byte changed: '+f['path'])
 if (batch.hashes(Path(entry['project']))!=row['source_hashes']
     or sha(Path(entry['project_marker']))!=entry['marker_sha256']):
  raise ValueError('Local frozen original project changed')
 sessions=proof.get('original_sessions',[])
 if not sessions:raise ValueError('Original generation session proof required')
 for session in sessions:
  wire=Path(session['path'])
  if (sha(wire)!=session['sha256'] or Path(entry['generation_run']).name not in session['matched_original_runs']):
   raise ValueError('Original generation session binding differs')
 result=dict(status=LOCAL_STATUS,remote_verified=False,remote_preferred=True,
   original_run=entry['generation_run'],authorization=dict(path=str(auth.resolve()),sha256=sha(auth)),
   original_remote_status=row['source_provenance']['status'])
 entry['source_provenance_qualification']=result
 return result
