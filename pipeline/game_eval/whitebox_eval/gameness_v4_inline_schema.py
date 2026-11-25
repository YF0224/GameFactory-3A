"""Source-bound recovery for native images lost after schema-read compaction.

Retain the original failed call. Only inline the exact existing output schema;
all sources, native pixels, context, checks and validators remain unchanged.
"""
from pathlib import Path
import json
from . import mechanic_v3_runner as runner
from .protocol import sha

VERSION='gameness-v4-exact-inline-schema.v1'


def apply(root,name,prompt,schema):
    path=Path(root)/'engineering/gameness_inline_schema'/(name+'.json')
    if not path.exists():return prompt
    receipt=runner.read(path)
    if receipt['version']!=VERSION or receipt['task']!=name:
        raise ValueError('Invalid inline-schema authorization')
    for file,digest in receipt['source_bindings'].items():
        if sha(Path(file))!=digest:
            from .gameness_v4_preflight_recovery import verify_previous_binding
            if not verify_previous_binding(root,name,file,digest):
                raise ValueError('Inline-schema source binding changed: '+file)
    marker='EXACT SCHEMA FILE (only allowed read): '+str(Path(root)/'model_calls'/name/'schema.json')
    if prompt.count(marker)!=1:raise ValueError('Exact schema path missing or duplicated')
    wire=json.dumps(schema,ensure_ascii=False,separators=(',',':'))
    if json.loads(wire)!=schema:raise ValueError('Inline output schema is not equivalent')
    replacement=('EXACT INLINE OUTPUT SCHEMA (no filesystem reads are needed or allowed; '
        'inspect the native images attached to THIS request directly, not a textual summary; '
        'return only the schema-conforming JSON):\n'+wire)
    return prompt.replace(marker,replacement)


def admit(root,name):
    """Inline the schema on a genuinely new v4 invocation, never replace a call."""
    root=Path(root).resolve()
    path=root/'engineering/gameness_inline_schema'/(name+'.json')
    if path.exists():return runner.read(path)
    if (root/'model_calls'/name).exists():
        raise ValueError('Retained calls need explicit diagnosed transport recovery')
    files=[Path(__file__).resolve(),Path(__file__).with_name('gameness_v3_runtime.py').resolve(),
           root/'input_manifest.json',root/'source_qualification.json',root/'evidence_manifest.json']
    receipt=dict(version=VERSION,task=name,first_delivery=True,
        source_bindings={str(p):sha(p) for p in files},schema_equivalent=True,
        native_pixels_unchanged=True,source_context_unchanged=True)
    runner.exclusive_json(path,receipt)
    return receipt


def authorize(root,task,repair_path):
    from . import mechanic_v3_judge_transport as transport
    root=Path(root).resolve();folder=root/'model_calls'/task
    raw=runner.read(folder/'response.json')
    error=runner.read(folder/'validation_error.json')
    if (raw.get('runtime_delivery_status')!='MISSING_OR_UNREADABLE'
            or error.get('exception')!='HARNESS_ERROR: original Gameness native images missing or unreadable'
            or error.get('response_sha256')!=sha(folder/'response.json')):
        raise ValueError('Not the diagnosed missing-native-image response')
    events=(folder/'events.jsonl').read_text()
    if 'compactions' not in events or 'command_execution' not in events:
        raise ValueError('No preserved schema-read compaction evidence')
    actual=runner.read(root/'requests'/task/'actual_delivery.json')
    if (actual.get('scoring_protocol')!='whitebox-gameness10-50-100.v4'
            or actual.get('all_predeclared_frames_delivered') is not True):
        raise ValueError('Parent complete v4 delivery required')
    for item in actual['images']+actual['complete_author_sources']:
        if sha(root/item['path'])!=item['sha256']:raise ValueError('Parent source/image bytes changed')
    claim=transport.authorize(root,task,repair_path)
    path=root/'engineering/gameness_inline_schema'/(claim['recovery_task']+'.json')
    bindings=dict(claim['bindings'])
    bindings.update(runner.read(Path(repair_path))['after_source_bindings'])
    bindings[str(Path(__file__).resolve())]=sha(Path(__file__))
    receipt=dict(version=VERSION,task=claim['recovery_task'],parent_task=task,
        source_bindings=bindings,schema_equivalent=True,native_pixels_unchanged=True,
        source_context_unchanged=True,old_failure_preserved=True)
    runner.exclusive_json(path,receipt)
    return claim
