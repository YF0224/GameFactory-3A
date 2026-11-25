"""Exact Vector3 float literal compatibility in an isolated authored copy."""
from pathlib import Path
import hashlib,json,re,struct
from .protocol import sha
SOURCE='Assets/Lightlane/Assembly/StreetWorld.cs'
CONSTRUCTORS=('new Vector3(1.7,.5f,3.5f)','new Vector3(1.7,1.5f,2)','new Vector3(1.6,1.1f,1.3f)','new Vector3(1.3,.5f,.03f)')

def checked(root,relative,digest):
    root=Path(root).resolve();rel=Path(relative);path=root/rel
    if (rel!=Path(SOURCE) or not path.is_file() or not path.resolve().is_relative_to(root/'Assets')
        or any(p.is_symlink() for p in (path,*path.parents) if p!=root and root in p.parents) or sha(path)!=digest):
        raise ValueError('Vector3 literal source changed or escaped')
    return path


def prepare(entry,root):
    config=entry['vector_float_literals'];path=checked(root,SOURCE,config['source_sha256'])
    before=path.read_bytes().decode('utf-8');after=before;edits=[]
    for constructor in CONSTRUCTORS:
        if before.count(constructor)!=1:raise ValueError('Vector3 literal call missing or ambiguous')
        start=before.index(constructor);literal=constructor[len('new Vector3('):].split(',')[0]
        row=before.count('\n',0,start)+1;column=start-before.rfind('\n',0,start)+len('new Vector3(')
        if row!=34:raise ValueError('Vector3 literal moved outside reviewed physical line')
        replacement=constructor.replace(literal,literal+'f',1);after=after.replace(constructor,replacement,1)
        edits.append({'physical_line':row,'argument_column':column,'before':constructor,'after':replacement,'numeric_lexeme':literal,'float32_hex':struct.pack('!f',float(literal)).hex()})
    if [x['argument_column'] for x in edits]!=[157,240,314,394]:raise ValueError('Vector3 literal physical columns differ')
    inverse=after
    for item in edits:inverse=inverse.replace(item['after'],item['before'],1)
    if inverse!=before:raise ValueError('Vector3 literal suffix mapping is not reversible')
    return {'source':SOURCE,'before_sha256':sha(path),'before_utf8':before,'after_utf8':after,'after_sha256':hashlib.sha256(after.encode('utf-8')).hexdigest(),'edits':edits,'inverse_bytes_equal':True,'numeric_lexemes_unchanged':True,'scope':'Add exactly four f suffixes to existing Vector3 first-argument decimal literals; no parameters, methods, control flow, or other tokens changed.'}


def review(entry):
    config=entry['vector_float_literals'];prepare(entry,entry['project'])
    for key in ('prior_receipt','compiler_log'):
        if sha(Path(config[key]))!=config[key+'_sha256']:raise ValueError('Vector3 literal native failure evidence changed')
    execution=json.loads(Path(config['prior_receipt']).read_text()).get('execution',{})
    if execution.get('owned_process_exited') is not True or execution.get('exit_code') in (None,0):raise ValueError('Vector3 literal requires completed failed native execution')
    expected={f"{SOURCE}(34,{column}): error CS1503: Argument 1: cannot convert from 'double' to 'float'" for column in (157,240,314,394)}
    actual={line.strip() for line in Path(config['compiler_log']).read_text(errors='replace').splitlines() if 'error CS' in line}
    if actual!=expected:raise ValueError('Vector3 literal review must match exact four compiler errors')
    return True
