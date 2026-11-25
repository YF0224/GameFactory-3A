"""Continue the same prepared sequential task after a proven zero-call defect.

This is not a model retry: every invocation directory must still be absent.
Immutable failure, prepared request, original context policy and precise before
and after production snapshots are bound before any invocation is allowed.
"""
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import gameness_v3_runtime as runtime
from .protocol import sha
VERSION='gameness-sequential-zero-invocation-continuation.v1'
RECEIPT='engineering/gameness_sequential_preinvoke_continuation.json'


def context_configuration(auth):
    value=auth.get('model_context_window')
    if value is not None and (type(value) is not int or value!=1050000):
        raise ValueError('Original scoped context policy changed')
    return value


def verify_command(inv,auth):
    command=inv['command'];expected=context_configuration(auth)
    actual=[x for x in command if x.startswith('model_context_window=')]
    if (inv.get('model_requested')!='gpt-6.1-sol' or inv.get('exit_code')!=0
            or inv.get('attempt')!=1 or '--ephemeral' in command
            or command.count('model_auto_compact_token_limit=100000000')!=1
            or actual!=([] if expected is None else ['model_context_window='+str(expected)])):
        raise ValueError('Inherited original context configuration or invocation changed')


def prepared_only(root,auth):
    call=root/'model_calls'/auth['task']
    files={str(p.relative_to(call)):sha(p) for p in call.rglob('*') if p.is_file()}
    if (set(files)!={'prompt.txt','schema.json'} or any(p.is_dir() for p in call.rglob('*'))
            or (root/'capacity_calls/gameness_sequential_complete_native_images').exists()
            or (root/'judgments'/(auth['task']+'.json')).exists()):
        raise ValueError('Only the exact prepared request with zero attempted invocations can continue')
    return files


def evidence(root,auth,repair):
    from . import gameness_v4_sequential_recovery as seq
    value=runner.read(repair);authorization=root/seq.AUTH
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('task')!=auth['task']
            or value.get('authorization')!=dict(path=str(authorization),sha256=sha(authorization))
            or value.get('maximum_new_source_conversations')!=1
            or value.get('same_prepared_task') is not True
            or value.get('scoring_and_limits_unchanged') is not True
            or value.get('context_policy')!='INHERIT_ORIGINAL_WITHOUT_OVERRIDE'):
        raise ValueError('Exact zero-invocation continuation authorization required')
    if context_configuration(auth) is not None:
        raise ValueError('This continuation repairs only a missing inherited default')
    failure=Path(value['failure']['path']).resolve()
    if (not failure.is_relative_to((root/'failures').resolve())
            or sha(failure)!=value['failure']['sha256']
            or runner.read(failure).get('error')!="KeyError('model_context_window')"):
        raise ValueError('Exact retained pre-invocation failure required')
    reg=Path(value['regression']['path'])
    if (sha(reg)!=value['regression']['sha256'] or runner.read(reg).get('exit_code')!=0
            or runner.read(reg).get('tests_passed',0)<1):
        raise ValueError('Passed corresponding continuation regression required')
    before=value['before_source_bindings'];archives=value['before_producer_archives']
    if set(before)!=set(archives) or any(sha(Path(archives[n]))!=h for n,h in before.items()):
        raise ValueError('Exact complete pre-defect producer bytes required')
    original=runner.read(Path(auth['repair']))
    if before!=original['after_source_bindings']:
        raise ValueError('Before production must match the exact failed sequential admission')
    after=value['after_source_bindings'];archives=value['after_producer_archives']
    if set(after)!=set(archives) or any(sha(Path(archives[n]))!=h for n,h in after.items()):
        raise ValueError('Exact complete corrected producer bytes required')
    files=value['prepared_files'];call=root/'model_calls'/auth['task']
    if set(files)!={'prompt.txt','schema.json'} or any(sha(call/n)!=h for n,h in files.items()):
        raise ValueError('Immutable prepared request changed')
    return value


def admit(root,auth,repair):
    repair=Path(repair).resolve();value=evidence(root,auth,repair)
    if value['after_source_bindings']!=runtime.production_bindings():
        raise ValueError('Current complete production differs from continuation')
    if prepared_only(root,auth)!=value['prepared_files']:
        raise ValueError('Prepared request changed')
    receipt=root/RECEIPT
    if receipt.exists():
        raise ValueError('One zero-invocation continuation already admitted; preserve all attempts')
    runner.exclusive_json(receipt,dict(version=VERSION,repair=dict(path=str(repair),sha256=sha(repair)),
        identity=root.name,task=auth['task'],maximum_new_source_conversations=1,
        original_authorization_preserved=True,zero_invocations_at_admission=True,
        prepared_files=value['prepared_files']))
    return value


def verify_saved(root,auth):
    receipt=root/RECEIPT
    if not receipt.exists():return None
    value=runner.read(receipt);repair=Path(value['repair']['path'])
    if (value.get('version')!=VERSION or value.get('identity')!=root.name
            or value.get('task')!=auth['task'] or value.get('zero_invocations_at_admission') is not True
            or sha(repair)!=value['repair']['sha256']):
        raise ValueError('Immutable zero-invocation continuation receipt changed')
    result=evidence(root,auth,repair)
    if result['prepared_files']!=value['prepared_files']:
        raise ValueError('Saved prepared request proof changed')
    return result
