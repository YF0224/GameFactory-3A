"""Exact private method alpha rename for the reviewed class/type name collision."""
from pathlib import Path
import hashlib,json,re
from .protocol import sha
SOURCE='Assets/Scripts/SalvageGame.cs'
SIGNATURE='private void Part(string id, string label, string assetId, float depth, Vector3 position, Color color, string[] dependencies)'
TARGET='BuildSalvagePartRecord'


def checked(root,relative,digest):
    root=Path(root).resolve();rel=Path(relative);path=root/rel
    if (rel.is_absolute() or '..' in rel.parts or not path.is_file() or not path.resolve().is_relative_to(root/'Assets')
        or any(p.is_symlink() for p in (path,*path.parents) if p!=root and root in p.parents) or sha(path)!=digest):
        raise ValueError('Private method source changed or escaped')
    return path


def prepare(entry,root):
    config=entry['private_method_rename'];path=checked(root,SOURCE,config['source_sha256']);before=path.read_bytes().decode('utf-8')
    originals=Path(entry['project']).resolve();inventory=config['asset_csharp_sources']
    present={str(p.relative_to(originals)) for p in (originals/'Assets').rglob('*.cs') if p.is_file()}
    if set(inventory)!=present:raise ValueError('Private method original source inventory changed')
    for relative,digest in inventory.items():
        source=checked(originals,relative,digest);text=source.read_text()
        if TARGET in text or re.search(r'["\']Part["\']|nameof\s*\(\s*Part\s*\)',text):raise ValueError('Private method has dynamic or target-name references')
        if relative!=SOURCE and re.search(r'\bPart\s*\(',text):raise ValueError('Private method invocation outside reviewed type')
    if (before.count('public sealed class SalvageGame : MonoBehaviour')!=1 or before.count('private sealed class Part')!=1
            or before.count(SIGNATURE)!=1 or TARGET in before):raise ValueError('Private method/type declaration differs')
    positions=list(re.finditer(r'\bPart(?=\()',before));rows=[before.count('\n',0,m.start())+1 for m in positions]
    if rows!=[204,205,206,207,208,209,212]:raise ValueError('Private method must have exactly six direct calls and one declaration')
    lines=before.splitlines()
    if (lines[201].strip()!='private void BuildParts()' or lines[202].strip()!='{' or lines[209].strip()!='}'
            or any(not lines[i].strip().startswith(f'Part("P{i-202}", ') for i in range(203,209))):
        raise ValueError('Private method call scope differs')
    after=re.sub(r'\bPart(?=\()',TARGET,before)
    if after.replace(TARGET,'Part')!=before:raise ValueError('Private method rename not exactly reversible')
    return {'source':SOURCE,'before_utf8':before,'after_utf8':after,'before_sha256':sha(path),'after_sha256':hashlib.sha256(after.encode()).hexdigest(),'old_name':'Part','new_name':TARGET,'source_rows':rows,'direct_calls':6,'declarations':1,'inverse_bytes_equal':True,'method_body_and_arguments_unchanged':True,'nested_type_unchanged':True,'original_inventory_sha256':config['asset_csharp_sources'],'scope':'Only seven private method identifiers; the nested Part class, method body, arguments, lifecycle, control flow and all other source tokens remain unchanged.'}


def review(entry):
    config=entry['private_method_rename'];prepare(entry,entry['project'])
    for key in ('prior_receipt','compiler_log'):
        if sha(Path(config[key]))!=config[key+'_sha256']:raise ValueError('Private method native failure evidence changed')
    execution=json.loads(Path(config['prior_receipt']).read_text()).get('execution',{})
    if execution.get('owned_process_exited') is not True or execution.get('exit_code') in (None,0):raise ValueError('Private method requires completed native failure')
    expected={SOURCE+"(212,22): error CS0102: The type 'SalvageGame' already contains a definition for 'Part'"}
    actual={line.strip() for line in Path(config['compiler_log']).read_text(errors='replace').splitlines() if 'error CS' in line}
    if actual!=expected:raise ValueError('Private method review requires exact native collision error')
    return True
