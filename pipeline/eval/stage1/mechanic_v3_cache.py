"""Exact native-cache reclamation qualified by a real Mechanic-only publication.

Uses the existing production regeneration, process and reference checks. It
never fabricates eight columns or invokes the old eight-column score gate.
"""
from pipeline.eval.stage1.paths import DATA_ROOT
from contextlib import ExitStack
from pathlib import Path
import fcntl
import os
import shutil
import time
from . import native_scored_cache as safety
from .protocol import dump,sha
from .mechanic_v3_runner import read
from . import mechanic_v3_revision as revisions

VERSION='whitebox-mechanic-only-native-cache.v1'
TABLES=('mechanic_scores.md','mechanic_comparison.md')


def qualify(workspace,root):
    from .mechanic_v3_execution import verify_publication
    from . import batch,sparse_native
    from .pending_publication import cleanup_source
    p=verify_publication(workspace,root.name)
    q=read(root/'source_qualification.json')
    batch.verify_inputs(root)
    cleanup,origin=cleanup_source(Path(q['source']))
    if not cleanup:raise ValueError('Actual native cleanup required')
    for name,digest in q['source_bindings'].items():
        if sha(Path(name))!=digest:raise ValueError('Native source binding changed')
    sparse_native.verify_acceptance(workspace,p['engine'])
    for table in revisions.tables(workspace):
        if root.name not in (workspace/table).read_text():raise ValueError('Independent Mechanic tables missing identity')
    return dict(engine=p['engine'],case=p['case_id'],publication_sha256=sha(revisions.publication_dir(workspace)/(root.name+'.json')),
        table_sha256={name:sha(workspace/name) for name in revisions.tables(workspace)},cleanup_origin=origin,
        qualification='Mechanic-only valid score; other columns not required or fabricated')


def run(workspace,root,*,publication_guard=None):
    workspace,root=workspace.resolve(),root.resolve()
    output=workspace/'native_cache_reclamation'/(root.name+'_'+str(time.time_ns()));output.mkdir(parents=True)
    receipt=dict(version=VERSION,identity=root.name,status='PRECHECK',time=time.time(),results=[],
        actual_deleted_bytes=0,available_bytes_before=shutil.disk_usage(workspace).free,deleted_paths=[],failed_deletions=[])
    def save():dump(output/'receipt.json',receipt)
    save()
    try:
        control,locks=safety.locks(workspace)
        with ExitStack() as stack:
            if publication_guard is None:
                publication=stack.enter_context((workspace/'.publication.lock').open('a+'))
                fcntl.flock(publication,fcntl.LOCK_EX|fcntl.LOCK_NB)
            else:
                if (publication_guard.get('pid')!=os.getpid() or not publication_guard.get('active')
                        or publication_guard['workspace']!=str(workspace)
                        or publication_guard['publication_handle'].closed):
                    raise ValueError('Invalid live publication guard')
            for path in locks:
                if path.is_symlink():raise ValueError('Linked native lock file')
                handle=stack.enter_context(path.open('a+'));fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
            receipt['locks']=list(map(str,locks))+[str(workspace/'.publication.lock')]
            source=qualify(workspace,root);receipt['source']=source
            snapshot=safety.idle_snapshot(root)
            (output/'processes.txt').write_text(snapshot['processes']);(output/'open_files.txt').write_text(snapshot['open_files'])
            paths=safety.candidate_paths(root,source['engine']);remaining=list(paths)
            repo=Path(__file__).resolve().parents[3]
            roots=[workspace.parent,DATA_ROOT/'outputs/eval/playtest',control,repo/'docs']
            refs=safety.reference_scan(paths,roots,output);dump(output/'reference_scan.json',refs)
            for i,path in enumerate(paths):
                row=dict(path=str(path),status='PRESERVED',actual_deleted_bytes=0);receipt['results'].append(row)
                files=[];started=False
                try:
                    if refs['errors'] or refs['hits'][str(path)]:raise ValueError('Unresolved reference/recovery/shared dependency; see reference scan')
                    if str(path) in snapshot['open_files']:raise ValueError('Open-file/cwd dependency')
                    row['regeneration_proof']=safety.regeneration_proof(root,path,source['engine'])
                    identity=(path.stat().st_dev,path.stat().st_ino);files=safety.file_inventory(path)
                    listing=output/f'files_{i:03d}.json';dump(listing,files);row['inventory_sha256']=sha(listing)
                    if qualify(workspace,root)!=source:raise ValueError('Published source/table changed')
                    if safety.candidate_paths(root,source['engine'])!=remaining:raise ValueError('Cache candidate changed')
                    if (path.stat().st_dev,path.stat().st_ino)!=identity or safety.file_inventory(path)!=files:raise ValueError('Cache changed after inventory')
                    refs,trace=safety.stable_reference_recheck(paths,roots,output,refs,path);row['reference_recheck_sha256']=sha(trace)
                    if qualify(workspace,root)!=source:raise ValueError('Source changed during reference audit')
                    fresh=safety.idle_snapshot(root)
                    if str(path) in fresh['open_files'] or safety.file_inventory(path)!=files:raise ValueError('New process/file dependency')
                    if safety.regeneration_proof(root,path,source['engine'])!=row['regeneration_proof']:raise ValueError('Regeneration proof changed')
                    from .unity_scored_cache import deletion_pause
                    pause=deletion_pause(control,source['case'])
                    if pause:raise ValueError(pause['reason'])
                    started=True;shutil.rmtree(path)
                    if path.exists():raise RuntimeError('Cache remains after deletion')
                    remaining.remove(path);row['status']='DELETED'
                    row['actual_deleted_bytes']=sum(f['allocated_bytes'] for f in files)
                    receipt['deleted_paths'].append(str(path))
                except Exception as error:
                    row['reason']=repr(error)
                    if started:
                        row['status']='DELETE_FAILED'
                        removed=[f for f in files if not f['directory'] and not os.path.lexists(f['path'])]
                        row['deleted_file_paths']=[f['path'] for f in removed]
                        row['actual_deleted_bytes']=sum(f['allocated_bytes'] for f in removed)
                        receipt['failed_deletions'].append(dict(path=str(path),error=repr(error)))
                receipt['actual_deleted_bytes']+=row['actual_deleted_bytes'];save()
            receipt['status']='COMPLETE'
            receipt['tables_unchanged']={name:sha(workspace/name) for name in revisions.tables(workspace)}==source['table_sha256']
    except Exception as error:
        receipt.update(status='BLOCKED_LOCK' if isinstance(error,BlockingIOError) else 'FAILED',error=repr(error),
            next_action='Retain every cache; recheck formal lock ownership and recorded dependencies before exact-path recovery')
    finally:
        receipt['available_bytes_after']=shutil.disk_usage(workspace).free
        receipt['receipt_path']=str(output/'receipt.json');save()
    return receipt
