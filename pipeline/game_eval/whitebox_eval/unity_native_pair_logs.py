"""Preserve independent native Editor logs after verified process cleanup."""
from pathlib import Path
import shutil
from . import batch
from .protocol import dump,sha

def preserve(capture,project_root,*,verification_name='verification.json'):
    """Copy the exact per-role -logFile source; no global-log fallback."""
    from .unity_native_pair_record import process_identities
    capture,project_root=Path(capture).resolve(),Path(project_root).resolve()
    if verification_name not in {'verification.json','recovered_verification.json'}:
        raise ValueError('Unknown native log verification source')
    if not all(batch.read(capture/'cleanup.json').get(k) is True for k in
               ('input_cleanup','view_cleanup','process_cleanup','source_unchanged')):
        raise ValueError('Native logs require completed input/view/process cleanup')
    table=process_identities();planned=[]
    for role in ('A','B'):
        verification=capture/'workers'/role/verification_name
        if verification_name == 'recovered_verification.json':
            from .unity_native_pair_recovery import verify_role
            verify_role(capture,role)
        value=batch.read(verification)
        if value.get('ok') is not True or not all(value['checks'].values()):
            raise ValueError('Native client verification incomplete: '+role)
        process=value['process_cleanup'];command=process['command']
        project=project_root/('project_'+role);take=capture/'sessions'/role
        log=project/'Library/GameFactory3A/Editor.log'
        expected={'-projectPath':str(project),'-logFile':str(log),'--ww-client':role,
                  '--gamefactory-evaluation-output':str(take)}
        if any(command.count(flag)!=1 or command.index(flag)+1>=len(command)
               or command[command.index(flag)+1]!=arg for flag,arg in expected.items()):
            raise ValueError('Native log launch binding differs: '+role)
        if (process.get('ok') is not True or process.get('process_exit_verified') is not True
                or process.get('group_exit_verified') is not True
                or any(pid==process['pid'] or row['pgid']==process['owned_pgid']
                       or str(project) in row['command'] for pid,row in table.items())):
            raise ValueError('Native log writer still occupied: '+role)
        if any(p.is_symlink() for p in (project,project/'Library',log.parent,log)) or not log.is_file():
            raise ValueError('Missing or unsafe owned native Editor log: '+role)
        destination=take/'player.log';provenance=take/'native_log_binding.json'
        if destination.exists() or provenance.exists():
            raise ValueError('Preserve existing native log binding: '+role)
        planned.append((role,log,destination,provenance,verification,sha(log)))
    result={}
    for role,log,destination,provenance,verification,digest in planned:
        shutil.copy2(log,destination)
        if sha(destination)!=digest or sha(log)!=digest:
            raise ValueError('Native log changed during handoff: '+role)
        binding={'schema':'unity-stopped-owned-editor-log-copy.v1','role':role,
                 'source':str(log),'destination':str(destination),'sha256':digest,
                 'verification':str(verification),'verification_sha256':sha(verification),
                 'cleanup_sha256':sha(capture/'cleanup.json'),
                 'bytes':destination.stat().st_size,'physical_lines':len(destination.read_bytes().splitlines()),
                 'method':'Exact byte copy of verified exited role Editor -logFile; errors/warnings/stacks retained.'}
        dump(provenance,binding);result[role]=binding
    return result
