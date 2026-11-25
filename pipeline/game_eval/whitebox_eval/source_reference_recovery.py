"""Source-bound continuation of one failed static output request after transport repair."""
import json
from pathlib import Path
from . import batch, source_reference_transport as transport
from .protocol import dump, sha

RECEIPT='static_source_reference_recovery.json'
VERSION='whitebox-static-source-reference-recovery.v1'


def _unaccepted_stream_closed(folder):
    """Distinct terminal stream failure, not reclassified as max_output_tokens."""
    from .static_existence import MODEL
    folder=Path(folder)
    inv=batch.read(folder/'invocation.json');cmd=inv.get('command',[])
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text().splitlines() if line.strip()]
    message='stream disconnected before completion: stream closed before response.completed'
    terminal=[e for e in events if e.get('type')=='turn.failed']
    truncation='stream disconnected before completion: Incomplete response returned, reason: max_output_tokens'
    import re
    notices=[e.get('message','') for e in events if e.get('type')=='error']
    reconnects=[s for s in notices if re.fullmatch(r'Reconnecting\.\.\. [1-5]/5 \('+re.escape(truncation)+r'\)',s)]
    allowed=lambda s:s==message or re.fullmatch(r'Reconnecting\.\.\. [1-5]/5 \('+re.escape(truncation)+r'\)',s) or re.fullmatch(r'Reconnecting\.\.\. [1-5]/5 \(stream disconnected before completion: stream closed before response\.completed\)',s)
    if (inv.get('exit_code') in (None,0) or inv.get('status')=='TIMEOUT'
            or inv.get('model_requested')!=MODEL or '--model' not in cmd or cmd[cmd.index('--model')+1]!=MODEL
            or any((folder/name).exists() for name in ('response.json','accepted_response.json'))
            or len(terminal)!=1 or terminal[0].get('error',{}).get('message')!=message
            or not reconnects or any(not allowed(s) for s in notices)):
        raise ValueError('No exact preserved terminal stream-close with truncation reconnect diagnostics')
    return 'HARNESS_ERROR_STREAM_CLOSED_WITH_TRUNCATION_RECONNECTS'


def _qualify_failure(folder,kind):
    if kind=='STREAM_CLOSED':return _unaccepted_stream_closed(folder)
    if kind!='OUTPUT_MAX_OUTPUT_TOKENS':raise ValueError('Unknown source transport failure classification')
    from .static_output_recovery import _unaccepted_max_output
    _unaccepted_max_output(folder)
    return 'OUTPUT_MAX_OUTPUT_TOKENS'


def prepare(root,failed_name, *, failure_kind='OUTPUT_MAX_OUTPUT_TOKENS'):
    from . import static_output_recovery as recovery
    root=Path(root).resolve()
    if (root/RECEIPT).exists():raise ValueError('Existing source reference recovery preserved')
    if not (root/recovery.RECEIPT).is_file() or batch.read(root/recovery.RECEIPT).get('complete'):
        raise ValueError('Expected incomplete static output recovery')
    receipt=batch.read(root/recovery.RECEIPT);source=Path(receipt['source_attempt'])
    specs=recovery._delivery_specs(root,receipt,(source/'model_calls/static_existence/prompt.txt').read_text(),batch.read(source/'model_calls/static_existence/schema.json'))
    matching=[packet for name,packet in specs if name==failed_name]
    if len(matching)!=1:raise ValueError('Failed source request is not an exact current output task')
    folder=root/'model_calls'/failed_name
    classification=_qualify_failure(folder,failure_kind)
    if not transport.applies(failed_name,matching[0]['schema']):raise ValueError('Failure lacks large closed source-reference enum')
    if not transport.delivery_matches(folder,matching[0]['prompt'],matching[0]['schema']):
        raise ValueError('Original failed request delivery changed')
    next_name=failed_name+'_reference_transport'
    if (root/'model_calls'/next_name).exists():raise ValueError('Source-bound continuation already attempted')
    bindings={str(p.relative_to(root)):sha(p) for p in folder.iterdir() if p.is_file()}
    for name in ['input_manifest.json','input/pilot_rubric.json',recovery.RECEIPT]:bindings[name]=sha(root/name)
    # The partition receipt is allowed only to append validated output rows, so bind its
    # immutable identity here and preserve its complete pre-call bytes independently.
    partition=bindings.pop(recovery.RECEIPT)
    archive=root/'static_source_reference_recovery/partition.before.json';archive.parent.mkdir(parents=True,exist_ok=True)
    archive.write_bytes((root/recovery.RECEIPT).read_bytes())
    events=(folder/'events.jsonl').read_text().splitlines()
    dump(root/RECEIPT,{'version':VERSION,'attempt':str(root),'failed_name':failed_name,'next_name':next_name,
        'preserved_bindings':bindings,'partition_before':str(archive.relative_to(root)),'partition_before_sha256':sha(archive),
        'original_partition_sha256':partition,'failure_lines':[i for i,line in enumerate(events,1) if 'max_output_tokens' in line],
        'cause':'Large closed SourceReference path/SHA enum has exact reversible ordinal transport. Original terminal failure and reconnect diagnostics separately classified and preserved; actual wire schema changes, not an identical retry or counter reset.',
        'semantics_changed':False, 'failure_kind':failure_kind, 'preserved_failure_classification':classification})
    return batch.read(root/RECEIPT)


def deliveries(root,specs):
    root=Path(root).resolve();path=root/RECEIPT
    if not path.exists():return specs
    r=batch.read(path)
    if (r.get('version')!=VERSION or r.get('attempt')!=str(root)
            or r.get('next_name')!=r['failed_name']+'_reference_transport'):
        raise ValueError('Source reference recovery lineage differs')
    for name,digest in r['preserved_bindings'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or sha(root/relative)!=digest:
            raise ValueError('Original source failure/frozen artifact differs: '+name)
    archive=root/r['partition_before']
    if sha(archive)!=r['partition_before_sha256'] or sha(archive)!=r['original_partition_sha256']:
        raise ValueError('Original partition checkpoint differs')
    from .static_output_recovery import RECEIPT as partition_name
    before=batch.read(archive);current=batch.read(root/partition_name)
    immutable=lambda value:{key:item for key,item in value.items() if key not in ('outputs','complete')}
    if immutable(before)!=immutable(current) or current['outputs'][:len(before['outputs'])]!=before['outputs']:
        raise ValueError('Static output partition identity or accepted prefix differs')
    _qualify_failure(root/'model_calls'/r['failed_name'],r.get('failure_kind','OUTPUT_MAX_OUTPUT_TOKENS'))
    selected=[(name,p) for name,p in specs if name==r['failed_name']]
    if len(selected)!=1 or not transport.applies(selected[0][0],selected[0][1]['schema']):
        raise ValueError('Source reference continuation no longer binds exact task')
    return [(r['next_name'] if name==r['failed_name'] else name,p) for name,p in specs]
