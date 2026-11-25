"""Verify UE recorder's actual cleanup schema without inventing Unity fields."""
from pathlib import Path
from .common import read,sha


def verify(folder):
    from engine_adapters.ue5.playtest.native_record import verify_pin
    folder=Path(folder);capture=folder/'background_record';take=capture/'take'
    admitted=read(folder/'native_admission.json');verify_pin(admitted)
    accepted=read(admitted['native_acceptance'])
    if (sha(admitted['native_acceptance'])!=admitted['native_acceptance_sha256']
        or accepted.get('ok') is not True or accepted['pin_sha256']!=sha(admitted['pin'])):
        raise ValueError('UE cleanup: native acceptance/pin mismatch')
    for path,digest in accepted['files'].items():
        if sha(path)!=digest:raise ValueError('UE cleanup: native acceptance evidence changed')
    cleanup=read(take/'cleanup.json');verification=read(take/'verification.json');exit=read(take/'runner_exit.json')
    for name in ('cleanup.json','verification.json','runner_exit.json'):
        if read(capture/name)!=read(take/name):raise ValueError('UE cleanup: copied recorder receipt differs')
    if (any(cleanup.get(k) is not True for k in ('input_cleanup_ok','view_cleanup_ok','process_cleanup_ok'))
        or cleanup.get('remaining_descendants')!=[] or verification.get('ok') is not True
        or verification.get('pin_sha256')!=sha(admitted['pin']) or exit.get('returncode')!=0):
        raise ValueError('UE cleanup: input/view/process or verified native exit uncertain')
    launch=read(take/'launch.json')
    if (launch.get('pid')!=cleanup.get('pid') or not isinstance(cleanup.get('pid'),int)
        or launch['command'][:2]!=[admitted['editor'],admitted['uproject']]):
        raise ValueError('UE cleanup: engine process identity differs')
    return {**{k:True for k in ('input_cleanup','view_cleanup','process_cleanup')},
        'schema':'UE native cleanup *_ok; verified actual receipts; originals unchanged',
        'cleanup_sha256':sha(take/'cleanup.json'),'verification_sha256':sha(take/'verification.json'),
        'runner_exit_sha256':sha(take/'runner_exit.json'),'launch_sha256':sha(take/'launch.json')}
