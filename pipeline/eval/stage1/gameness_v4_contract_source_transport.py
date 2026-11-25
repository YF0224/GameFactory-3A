"""Measured, source-only, complete contract packet recovery for v4.

Author source bytes, original physical lines and all model deliveries are kept.
The synthetic ID is a container, never an admissible source citation.
"""
import json
from pathlib import Path
from . import mechanic_v3_runner as runner
from . import shared_document_wire as shared
from .protocol import sha

VERSION='gameness-v4-complete-contract-source-transport.v1'
IDENTS={'GAMENESS_COMMON_AUTHOR_SOURCE_CONTAINER','GAMENESS_COMPLETE_CONTRACT_SOURCE'}
AUTH='engineering/complete_contract_source_transport/authorization.json'
NOTICE=('COMPLETE ORIGINAL AUTHOR SOURCE CONTAINER: concatenate every exact literal using its dictionary. '
        'The container ID is NOT evidence and MUST NOT be cited. Retain all original AUTHOR/model/path/SHA headers, '
        'every original numbered source line, every repeated occurrence, and all original requirements. '
        'Use only original model/source paths and original physical source lines in the contract. '
        'This is source-only evidence; it supplies no runtime observation, old verdict or success claim.\n')


def packet_bytes(packet):
    if not packet.startswith(shared.TABLE_MARKER) or packet.count(shared.TABLE_MARKER)!=1:
        raise ValueError('One exact complete source table required')
    head,section=packet[len(shared.TABLE_MARKER):].split('\nEVIDENCE ',1)
    label,doc_text=section.split(' (exact document shared text):\n',1)
    if label not in IDENTS:raise ValueError('Unknown contract source container')
    table=json.loads(head);doc=json.loads(doc_text)
    if doc.get('evidence_id')!=label:raise ValueError('Contract source container identity differs')
    raw=shared.decode(table,doc)
    if shared._render(table['dictionary'],[doc])[0]!=packet:
        raise ValueError('Noncanonical contract source container')
    return raw


def candidate(prompt,text,packet):
    if packet_bytes(packet)!=text.encode():raise ValueError('Complete original contract source bytes differ')
    marker='\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '
    if prompt.count(marker)!=1:raise ValueError('Original complete contract source boundary differs')
    return prompt.replace(marker,'\nAUTHOR SOURCES\n'+NOTICE+packet+'\nEXACT SCHEMA FILE ',1)


def authorize(workspace,case,packet_path):
    from . import gameness_v3_runtime as runtime
    from . import gameness_v3_independent as independent
    workspace=Path(workspace).resolve();folder=runtime.contract_dir(workspace,case)
    policy=runtime.workspace_policy(workspace)
    if not policy.VERSION.endswith('.v4'):raise ValueError('Only explicit v4 original-check policy may opt in')
    if (folder/'frozen.json').exists() or list((folder/'model_calls').glob('*')):
        raise ValueError('Cannot replace an actual source contract invocation')
    proto=runner.read(folder/'frozen_protocol.json')
    if independent.active(proto):raise ValueError('Independent reduced contracts cannot opt in')
    source=folder/'author_sources.txt';text=source.read_bytes().decode()
    schema_path=folder/'planned_schema.json'
    if runner.read(schema_path)!=policy.contract_schema(proto):raise ValueError('Original complete contract schema differs')
    prompt=(policy.CONTRACT_PROMPT+'\nCHECKS\n'+json.dumps(policy.criteria(proto),ensure_ascii=False)
        +'\nAUTHOR SOURCES\n'+text+'\nEXACT SCHEMA FILE '+str(schema_path))
    if len(prompt.encode())<=1000000:raise ValueError('No measured full-source cap failure')
    packet_path=Path(packet_path).resolve();packet=packet_path.read_bytes().decode();wire=candidate(prompt,text,packet)
    if len(wire.encode())>1000000:raise ValueError('Complete source still exceeds original unchanged cap')
    source_binding=runner.read(folder/'source_binding.json')
    for file,digest in source_binding['bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Original author source binding changed: '+file)
    files=[source,schema_path,folder/'source_binding.json',folder/'frozen_protocol.json',packet_path,
           Path(__file__).resolve(),Path(runtime.__file__).resolve(),Path(policy.__file__).resolve(),Path(shared.__file__).resolve()]
    out=folder/'engineering/complete_contract_source_transport';out.mkdir(parents=True,exist_ok=True)
    for name,data in [('original_prompt.txt',prompt),('submitted_prompt.txt',wire)]:
        p=out/name
        if p.exists() and p.read_bytes()!=data.encode():raise ValueError('Preserved source transport prompt differs')
        if not p.exists():p.write_bytes(data.encode())
        files.append(p)
    value=dict(version=VERSION,classification='NON_SCORING_TOOL_TRANSPORT',
        original_prompt_bytes=len(prompt.encode()),submitted_prompt_bytes=len(wire.encode()),maximum_prompt_bytes=1000000,
        packet_path=str(packet_path),source_path=str(source),no_invocation_at_authorization=True,
        original_author_sources_complete=True,original_physical_lines=True,source_only=True,
        synthetic_id_is_citable=False,model_recalled=False,bindings={str(p):sha(p) for p in files},
        original_source_bindings=source_binding['bindings'])
    p=folder/AUTH
    if p.exists():
        if runner.read(p)!=value:raise ValueError('Existing contract source authorization differs')
    else:runner.exclusive_json(p,value)
    return value


def apply(folder,prompt,text):
    folder=Path(folder);path=folder/AUTH
    if not path.exists():return prompt,None
    value=runner.read(path)
    if value.get('version')!=VERSION or value.get('no_invocation_at_authorization') is not True:
        raise ValueError('Invalid complete source transport authorization')
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(path,value['bindings'])
    for file,digest in value['original_source_bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Complete source transport binding changed: '+file)
    if prompt.encode()!=(path.parent/'original_prompt.txt').read_bytes():raise ValueError('Original source request differs')
    wire=candidate(prompt,text,Path(value['packet_path']).read_bytes().decode())
    if wire.encode()!=(path.parent/'submitted_prompt.txt').read_bytes() or len(wire.encode())>1000000:
        raise ValueError('Complete source request or frozen cap differs')
    return wire,dict(path=str(path),sha256=sha(path),original_author_sources_complete=True,original_physical_lines=True)


def verify(reference):
    """Recheck immutable accepted data without requiring historical code SHA."""
    path=Path(reference['path'])
    if sha(path)!=reference['sha256']:raise ValueError('Frozen source transport authorization changed')
    value=runner.read(path)
    if value.get('version')!=VERSION:raise ValueError('Frozen source transport version changed')
    for file,digest in value['original_source_bindings'].items():
        if sha(Path(file))!=digest:raise ValueError('Frozen original source binding changed: '+file)
    code=Path(__file__).parent.resolve()
    for file,digest in value['bindings'].items():
        p=Path(file)
        if p.parent.resolve()!=code and sha(p)!=digest:
            raise ValueError('Frozen source transport data changed: '+file)
    text=Path(value['source_path']).read_bytes().decode()
    original=(path.parent/'original_prompt.txt').read_bytes().decode()
    wire=candidate(original,text,Path(value['packet_path']).read_bytes().decode())
    if wire.encode()!=(path.parent/'submitted_prompt.txt').read_bytes() or len(wire.encode())>1000000:
        raise ValueError('Frozen complete source request differs')
    return value


PRIOR_AUTH='engineering/complete_contract_source_transport/prior_runtime_continuation.json'


def authorize_prior_recovery(folder,before_directory):
    """Bind an existing accepted contract to this runtime-only transport patch."""
    folder=Path(folder).resolve();before=Path(before_directory).resolve()
    frozen=folder/'frozen.json';recovery=runner.read(frozen)['contract_metadata_recovery']
    code=Path(__file__).with_name('gameness_v3_runtime.py').resolve()
    if sha(Path(recovery['path']))!=recovery['sha256']:
        raise ValueError('Retained recovery receipt differs')
    bindings={str(frozen):sha(frozen)}
    for file,digest in recovery['bindings'].items():
        if sha(Path(file))!=digest:
            if Path(file).resolve()!=code or sha(before/code.name)!=digest:
                raise ValueError('Unrelated retained contract binding drift: '+file)
            bindings[str(before/code.name)]=digest
        else:bindings[file]=digest
    bindings[str(code)]=sha(code)
    value=dict(version=VERSION,classification='NON_SCORING_RUNTIME_CONTINUATION',
        original_recovery=recovery,bindings=bindings,contract_unchanged=True,model_recalled=False,
        source_frames_checks_and_scoring_unchanged=True)
    path=folder/PRIOR_AUTH
    if path.exists():
        if runner.read(path)!=value:raise ValueError('Retained runtime continuation differs')
    else:runner.exclusive_json(path,value)
    return value


def verify_prior_recovery(folder,recovery):
    if sha(Path(recovery['path']))!=recovery['sha256']:
        raise ValueError('Retained recovery receipt differs')
    path=Path(folder)/PRIOR_AUTH
    if not path.exists():
        from .gameness_v3_contract_metadata import verify as original_verify
        return original_verify(recovery)
    value=runner.read(path)
    if value.get('version')!=VERSION or value['original_recovery']!=recovery:
        raise ValueError('Retained runtime recovery identity differs')
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(path,value['bindings'])
    return value


def publication_recovery_bindings(folder,recovery):
    """Preserve accepted recovery data; bind historical bytes and current producer."""
    value=verify_prior_recovery(folder,recovery)
    path=Path(folder)/PRIOR_AUTH
    if not path.exists():
        return {**recovery['bindings'],recovery['path']:recovery['sha256']}
    from .gameness_v4_production_continuation import verified_bindings
    resolved=verified_bindings(path,value['bindings'])
    return {**resolved,str(path):sha(path),recovery['path']:recovery['sha256']}


def verify_publication_bindings(folder,bindings,publication=None):
    """Verify exact contract-era or explicitly continued publication producers."""
    drift={p:d for p,d in bindings.items() if sha(Path(p))!=d}
    if not drift:return
    runtime=str(Path(__file__).with_name('gameness_v3_runtime.py').resolve())
    recovery=runner.read(Path(folder)/'frozen.json').get('contract_metadata_recovery')
    if recovery and drift=={runtime:recovery['bindings'].get(runtime)}:
        publication_recovery_bindings(folder,recovery)
        return
    if publication is None or runner.read(Path(publication)).get('bindings')!=bindings:
        raise ValueError('Unrelated Gameness publication binding changed')
    # Later publications may bind a different legitimate producer than the
    # contract. Only an immutable receipt for this exact publication may bridge
    # it; the continuation verifier keeps all non-producer evidence strict.
    from .gameness_v4_production_continuation import verified_bindings
    verified_bindings(Path(publication),bindings)
