"""Exact bijection for large static source path/SHA closed reference sets."""
import copy
import hashlib
import json
import re
from pathlib import Path
from .protocol import dump, sha

VERSION='whitebox-source-reference-ordinals.v1'
MIN_VALUES=4096
FIELDS=('path','sha256')
TRANSFORM='source_reference_transform.json'
DECODE='source_reference_decode.json'


def encode(schema):
    result=copy.deepcopy(schema)
    reference=result.get('$defs',{}).get('SourceReference',{})
    properties=reference.get('properties',{})
    mapping={}
    for field in FIELDS:
        rule=properties.get(field,{})
        values=rule.get('enum',[])
        if not isinstance(values,list) or len(values)<MIN_VALUES:
            continue
        if (set(rule)!={'type','enum'} or rule['type']!='string'
                or any(not isinstance(v,str) for v in values)
                or len(set(values))!=len(values)
                or field not in reference.get('required',[])
                or field+'_ordinal' in properties):
            raise ValueError('Source ordinal transport requires an exact unique string enum')
        mapping[field]=values.copy()
        del properties[field]
        properties[field+'_ordinal']={'type':'integer','minimum':1,'maximum':len(values)}
        required=reference['required'];required[required.index(field)]=field+'_ordinal'
    if restore(result,mapping)!=schema:
        raise ValueError('Source reference schema inverse differs')
    return result,mapping


def restore(schema,mapping):
    result=copy.deepcopy(schema)
    for field,values in mapping.items():
        reference=result['$defs']['SourceReference'];properties=reference['properties']
        ordinal=field+'_ordinal'
        if (properties.get(ordinal)!={'type':'integer','minimum':1,'maximum':len(values)}
                or field in properties or ordinal not in reference['required']):
            raise ValueError('Source reference ordinal range differs')
        del properties[ordinal];properties[field]={'type':'string','enum':values.copy()}
        required=reference['required'];required[required.index(ordinal)]=field
    return result


def applies(name,schema):
    return bool(re.fullmatch(r'static_existence(?:_output_\d+(?:_single_\d+)?(?:_reference_transport)?(?:_reference_validation_v1|_source_delivery_v1)?)?(?:_cli_runtime_v1)?',name)
                and encode(schema)[1])


def book(mapping):
    return {'version':VERSION,'fields':{field:{'values':values,'count':len(values),
        'values_sha256':hashlib.sha256(json.dumps(values,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()}
        for field,values in mapping.items()}}


def write(folder,schema):
    from .judge_schema_transport import wire_schema
    folder=Path(folder);encoded,mapping=encode(schema)
    if not mapping:raise ValueError('No large source reference enum')
    submitted,ranges=wire_schema(encoded)
    dump(folder/'original_schema.json',schema);dump(folder/'source_reference_codebook.json',book(mapping))
    (folder/'schema.json').write_text(json.dumps(submitted,ensure_ascii=False,separators=(',',':'))+'\n')
    dump(folder/TRANSFORM,{'version':VERSION,'original_sha256':sha(folder/'original_schema.json'),
        'submitted_sha256':sha(folder/'schema.json'),'codebook_sha256':sha(folder/'source_reference_codebook.json'),
        'counts':{k:len(v) for k,v in mapping.items()},'wire_integer_enums':ranges,
        'original_bytes':(folder/'original_schema.json').stat().st_size,
        'submitted_bytes':(folder/'schema.json').stat().st_size,
        'proof':'Exact inverse restores every original allowed path and SHA string. Only wire representation changes; original source/context, physical lines and reference validation remain.'})
    return submitted


def verify(folder):
    from .judge_schema_transport import wire_schema
    folder=Path(folder);receipt=json.loads((folder/TRANSFORM).read_text())
    for field,name in [('original_sha256','original_schema.json'),('submitted_sha256','schema.json'),('codebook_sha256','source_reference_codebook.json')]:
        if receipt.get(field)!=sha(folder/name):raise ValueError('Source reference transport identity differs: '+name)
    original=json.loads((folder/'original_schema.json').read_text());encoded,mapping=encode(original)
    expected,ranges=wire_schema(encoded)
    if (receipt.get('version')!=VERSION or not mapping
            or json.loads((folder/'schema.json').read_text())!=expected
            or json.loads((folder/'source_reference_codebook.json').read_text())!=book(mapping)
            or receipt.get('counts')!={k:len(v) for k,v in mapping.items()}
            or receipt.get('wire_integer_enums')!=ranges):
        raise ValueError('Source reference transport inverse proof differs')
    return original,mapping


def suffix(folder):
    folder=Path(folder).resolve();path=folder/'source_reference_codebook.json'
    return ('\n\nSource-reference wire transport (reversible; source judgment and reference requirements unchanged):\n'
        'The output SourceReference uses path_ordinal and/or sha256_ordinal for large closed string enums. '
        'For each such field return the 1-based index in the exact codebook fields[FIELD].values array. '
        'Never use a line number as a path/SHA ordinal. All other fields, physical 1-based lines, roles, '
        'reasons and judgments keep their original meaning. The evaluator decodes the strings and strictly '
        'validates the unchanged original schema AND actual source path/SHA/physical-line bindings. '
        'The codebook contains every original permitted string, supplies no source observation or verdict, '
        'and does not replace reading the actual author sources. Exact codebook: '+str(path)+' (SHA256 '+sha(path)+'). '
        'Use a bounded read-only Python lookup for each actual path and SHA selected from the original input: '
        'load book["fields"][FIELD]["values"], require the exact original string in that list, then return '
        'values.index(original_string)+1. Print only the lookup result, never the entire inventory.\n')


def prepare_prompt(folder,prompt):
    folder=Path(folder);verify(folder)
    (folder/'original_prompt.txt').write_text(prompt);submitted=prompt+suffix(folder)
    (folder/'prompt.txt').write_text(submitted)
    dump(folder/'source_reference_prompt_transform.json',{'version':VERSION,
        'original_sha256':sha(folder/'original_prompt.txt'),'submitted_sha256':sha(folder/'prompt.txt'),
        'transform_sha256':sha(folder/TRANSFORM),'suffix_sha256':hashlib.sha256(suffix(folder).encode()).hexdigest()})
    return submitted


def verify_prompt(folder):
    folder=Path(folder);verify(folder)
    receipt=json.loads((folder/'source_reference_prompt_transform.json').read_text())
    original=(folder/'original_prompt.txt').read_text()
    if (receipt.get('version')!=VERSION or receipt.get('original_sha256')!=sha(folder/'original_prompt.txt')
            or receipt.get('submitted_sha256')!=sha(folder/'prompt.txt')
            or receipt.get('transform_sha256')!=sha(folder/TRANSFORM)
            or receipt.get('suffix_sha256')!=hashlib.sha256(suffix(folder).encode()).hexdigest()
            or (folder/'prompt.txt').read_text()!=original+suffix(folder)):
        raise ValueError('Source reference original prompt or suffix differs')
    return original


def delivery_matches(folder,prompt,schema):
    folder=Path(folder)
    if (folder/TRANSFORM).is_file():
        original,_=verify(folder)
        return verify_prompt(folder)==prompt and original==schema
    return (folder/'prompt.txt').read_text()==prompt and json.loads((folder/'schema.json').read_text())==schema


def decode(folder,value):
    from .codex import validate_schema
    folder=Path(folder);original,mapping=verify(folder)
    validate_schema(value,json.loads((folder/'schema.json').read_text()))
    references=[]
    def walk(item,node,path='$'):
        if '$ref' in node:
            target=node['$ref']
            if not target.startswith('#/$defs/'):raise ValueError('Unsupported source reference')
            if target=='#/$defs/SourceReference':
                result=copy.deepcopy(item)
                for field,values in mapping.items():
                    ordinal=result.pop(field+'_ordinal');result[field]=values[ordinal-1]
                    references.append({'response_path':path,'field':field,'ordinal':ordinal,'original_string':result[field]})
                return result
            return walk(item,original['$defs'][target[len('#/$defs/'):]],path)
        if node.get('type')=='object':return {key:walk(item[key],rule,path+'.'+key) for key,rule in node['properties'].items()}
        if node.get('type')=='array':return [walk(v,node['items'],path+'['+str(i)+']') for i,v in enumerate(item)]
        return copy.deepcopy(item)
    result=walk(value,original);validate_schema(result,original)
    return result,references


def save_decoded(folder,raw):
    folder=Path(folder);verify_prompt(folder);result,refs=decode(folder,raw)
    dump(folder/'source_reference_decoded_response.json',result)
    dump(folder/DECODE,{'version':VERSION,'raw_response_sha256':sha(folder/'response.json'),
        'decoded_response_sha256':sha(folder/'source_reference_decoded_response.json'),
        'transform_sha256':sha(folder/TRANSFORM),'prompt_transform_sha256':sha(folder/'source_reference_prompt_transform.json'),
        'references':refs,'original_schema_validated':True})
    return result


def verify_decoded(path,binding):
    from .codex import load_plan_json
    path=Path(path);folder=path.parent;verify_prompt(folder)
    receipt=json.loads((folder/DECODE).read_text())
    if (path.name!='source_reference_decoded_response.json' or receipt.get('version')!=VERSION
            or binding.get('source_reference_receipt_sha256')!=sha(folder/DECODE)
            or receipt.get('raw_response_sha256')!=sha(folder/'response.json')
            or receipt.get('decoded_response_sha256')!=sha(path)
            or receipt.get('transform_sha256')!=sha(folder/TRANSFORM)
            or receipt.get('prompt_transform_sha256')!=sha(folder/'source_reference_prompt_transform.json')
            or receipt.get('original_schema_validated') is not True):
        raise ValueError('Source reference accepted decode binding differs')
    expected,refs=decode(folder,load_plan_json(folder/'response.json'))
    if load_plan_json(path)!=expected or receipt.get('references')!=refs:
        raise ValueError('Source reference decode differs from raw response')
    return receipt
