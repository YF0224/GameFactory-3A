"""Preserved failure plus independently qualified completed native pair recording."""
from pathlib import Path
from . import batch,multiclient
from .protocol import sha
VERSION='unity-native-pair-postprocess-recovery.v1'

def verify_role(capture,role):
    if role not in multiclient.ROLES:raise ValueError('Unknown native recovery role')
    capture=Path(capture);folder=capture/'workers'/role
    proof=batch.read(folder/'recovery_binding.json')
    required={'original_verification_sha256':'verification.json','original_error_sha256':'error.json',
        'runner_exit_sha256':'runner_exit.json','native_result_sha256':'result.json',
        'foreground_sha256':'foreground.jsonl','recovered_verification_sha256':'recovered_verification.json'}
    if proof.get('schema')!='unity-owned-pair-postprocess-reverification.v1' or proof.get('recordings_added')!=0:
        raise ValueError('Unqualified native postprocess recovery')
    for key,name in required.items():
        if sha(folder/name)!=proof[key]:raise ValueError('Native role recovery binding changed: '+name)
    if sha(capture/('request_'+role+'.json'))!=proof['request_sha256']:
        raise ValueError('Native role request changed')
    original=batch.read(folder/'verification.json');error=original.get('error',{})
    recovered=batch.read(folder/'recovered_verification.json')
    if (original.get('ok') is not False or error.get('type')!='KeyboardInterrupt'
            or error.get('error')!='owned pair stop' or recovered.get('ok') is not True
            or not all(v is True for v in original['checks'].values())
            or not all(v is True for v in recovered['checks'].values())
            or batch.read(folder/'result.json').get('ok') is not True):
        raise ValueError('Native recovery is not completed recording/postprocess-only failure')
    return recovered

def verify(capture):
    capture=Path(capture);proof=batch.read(capture/'postprocess_recovery.json')
    if proof.get('schema')!=VERSION or proof.get('recordings_added')!=0:
        raise ValueError('Invalid native product recovery')
    for relative,digest in proof['bindings'].items():
        from .protocol import checked_path
        if sha(checked_path(capture,relative))!=digest:raise ValueError('Native product recovery material changed: '+relative)
    failed=batch.read(capture/'result.json')
    if (failed.get('ok') is not False or failed.get('status')!='HARNESS_ERROR'
            or failed.get('error',{}).get('error')!='Native Editor PID was reused or its project identity changed'):
        raise ValueError('Original native failure no longer preserved')
    for role in multiclient.ROLES:verify_role(capture,role)
    result=batch.read(capture/'recovered_result.json');verification=batch.read(capture/'recovered_verification.json')
    if (result.get('ok') is not True or result.get('status')!='NATIVE_PAIR_CAPTURE_VERIFIED'
            or result.get('project_reuse_sha256')!=sha(capture/'project_reuse.json')
            or result.get('source_binding_sha256')!=sha(capture/'source_binding.json')
            or not all(v is True for v in verification['checks'].values())
            or not all(batch.read(capture/'cleanup.json').get(k) is True for k in
                       ('input_cleanup','view_cleanup','process_cleanup','source_unchanged'))):
        raise ValueError('Recovered native product verification incomplete')
    multiclient.audit_capture(capture,batch.read(capture/'capture_schedule.json'))
    return result,verification
