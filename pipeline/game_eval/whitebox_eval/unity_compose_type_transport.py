"""Exact type-name transport for an authored Assembly.GetType scene builder."""
from pathlib import Path
import copy,hashlib,json,re
from .protocol import dump,sha

FIND_TYPE = """    private static Type FindType(string fullName)
    {
        if (string.IsNullOrEmpty(fullName)) throw new ArgumentException("Component type is required");
        foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
        {
            Type type = assembly.GetType(fullName, false);
            if (type != null && typeof(Component).IsAssignableFrom(type)) return type;
        }
        throw new TypeLoadException("Unity component type was not found: " + fullName);
    }"""


def checked(root,relative,digest):
    root=Path(root).resolve();rel=Path(relative);path=root/rel
    if (rel.is_absolute() or '..' in rel.parts or not path.is_file() or path.is_symlink()
            or not path.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in path.parents if p!=root and root in p.parents) or sha(path)!=digest):
        raise ValueError('Reviewed component type source changed or escaped')
    return path


def review(entry,spec,root):
    config=entry['component_type_transport'];root=Path(root)
    builder=checked(root,entry['source'],entry['source_sha256'])
    if builder.read_text().count(FIND_TYPE)!=1:
        raise ValueError('Builder is not the exact reviewed Assembly.GetType resolver')
    for key in ('prior_receipt','editor_log'):
        if sha(Path(config[key]))!=config[key+'_sha256']:
            raise ValueError('Component type resolution failure changed')
    execution=json.loads(Path(config['prior_receipt']).read_text()).get('execution',{})
    if execution.get('owned_process_exited') is not True or execution.get('exit_code') in (None,0):
        raise ValueError('Component type transport requires completed failed native execution')
    log=Path(config['editor_log']).read_text(errors='replace')
    bindings=config.get('types',{})
    actual={item['type'] for obj in spec['objects'] for item in obj.get('components',[]) if ',' in item.get('type','')}
    if not actual or actual!=set(bindings):
        raise ValueError('Component type transport must cover exact authored qualified types')
    if any('error CS' in line for line in log.splitlines()):
        raise ValueError('Component type transport cannot conceal native compiler errors')
    if not any('Unity component type was not found: '+name in log for name in actual):
        raise ValueError('Native failure does not bind a reviewed qualified component type')
    files=config.get('asset_csharp_sources',{})
    present={str(p.relative_to(root)) for p in (root/'Assets').rglob('*.cs') if p.is_file()}
    if set(files)!=present:
        raise ValueError('Authored C# type inventory changed')
    sources={rel:checked(root,rel,digest).read_text() for rel,digest in files.items()}
    normalized=copy.deepcopy(spec);changes=[]
    for name,binding in bindings.items():
        match=re.fullmatch(r'([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+), ([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)',name)
        if not match:raise ValueError('Only exact simple assembly-qualified component names are supported')
        typename,assembly=match.groups();namespace,_,classname=typename.rpartition('.')
        source=checked(root,binding['source'],binding['source_sha256'])
        definition=checked(root,binding['asmdef'],binding['asmdef_sha256'])
        if json.loads(definition.read_text()).get('name')!=assembly:
            raise ValueError('Authored component assembly identity differs')
        # The nearest assembly definition in the ancestor chain must be the reviewed one.
        matched_scope=False
        for parent in source.parents:
            if parent==root.parent:break
            asmdefs=list(parent.glob('*.asmdef'))
            if asmdefs:
                if len(asmdefs)!=1 or asmdefs[0].resolve()!=definition.resolve():raise ValueError('Component has another assembly scope')
                matched_scope=True;break
        if not matched_scope:raise ValueError('Component has no reviewed assembly scope')
        declarations=[]
        for relative,text in sources.items():
            if re.search(r'\bnamespace '+re.escape(namespace)+r'\s*\{',text) and re.search(r'\bclass '+re.escape(classname)+r'\s*:',text):declarations.append(relative)
        if declarations!=[binding['source']]:
            raise ValueError('Component full name is missing or ambiguous in delivered source')
        text=sources[binding['source']]
        if (len(re.findall(r'\bnamespace\s+',text))!=1 or not re.search(r'public sealed class '+re.escape(classname)+r'\s*:\s*MonoBehaviour\b',text)):
            raise ValueError('Component must be the reviewed public sealed MonoBehaviour')
    for i,obj in enumerate(normalized['objects']):
        for j,component in enumerate(obj.get('components',[])):
            value=component.get('type','')
            if value in bindings:
                typename=value.split(', ',1)[0]
                component['type']=typename;changes.append({'object_index':i,'component_index':j,'before':value,'after':typename})
    inverse=copy.deepcopy(normalized)
    for item in changes:inverse['objects'][item['object_index']]['components'][item['component_index']]['type']=item['before']
    if inverse!=spec:raise ValueError('Component type transport is not exactly reversible')
    return normalized,changes



def snapshot_bindings(entry,sandbox,output):
    """Recompute the already authorized input migration; accept no other drift."""
    from .unity_input_migration import migrate_device_reads
    original=Path(entry['project']).resolve();sandbox=Path(sandbox).resolve()
    config=entry['component_type_transport'];changes={};assembly_changes={}
    # review() has already bound every original C# file and component assembly.
    # Recompute exact source bytes and the nearest assembly reference insertion.
    for relative,digest in config['asset_csharp_sources'].items():
        source=checked(original,relative,digest)
        if 'GameFactoryInput' in source.name:continue
        text=source.read_text();migrated=migrate_device_reads(text)
        if migrated==text:continue
        changes[relative]={'path':relative,'before_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'after_sha256':hashlib.sha256(migrated.encode()).hexdigest(),
            'kind':'native_input_device_reads_only'}
        parent=source.parent
        while parent!=original:
            definitions=list(parent.glob('*.asmdef'))
            if definitions:
                if len(definitions)!=1:raise ValueError('Ambiguous migrated component assembly')
                definition=definitions[0];rel=str(definition.relative_to(original))
                value=json.loads(definition.read_text());refs=value.setdefault('references',[])
                if 'GameFactoryInputMigration' not in refs:
                    refs.append('GameFactoryInputMigration')
                    assembly_changes[rel]=(json.dumps(value,indent=2)+'\n').encode()
                break
            parent=parent.parent
    transformed=[]
    for binding in config['types'].values():
        for key in ('source','asmdef'):
            relative=binding[key];digest=binding[key+'_sha256']
            source=checked(original,relative,digest)
            expected=source.read_bytes()
            if key=='source' and relative in changes:expected=migrate_device_reads(source.read_text()).encode()
            if key=='asmdef' and relative in assembly_changes:expected=assembly_changes[relative]
            expected_sha=hashlib.sha256(expected).hexdigest()
            target=checked(sandbox,relative,expected_sha)
            if expected!=source.read_bytes():transformed.append({'path':relative,'kind':key,'before_sha256':digest,'after_sha256':sha(target)})
    if transformed:
        receipt=Path(output)/'input_migration.json'
        if receipt.is_symlink() or not receipt.is_file():raise ValueError('Missing native input migration receipt')
        data=json.loads(receipt.read_text())
        if (data.get('version')!='unity-inputsystem-migration.v1' or data.get('user_authorized') is not True
                or Path(data.get('project','')).resolve()!=sandbox or data.get('gameplay_changes')!=[]
                or sorted(data.get('changes',[]),key=lambda item:item['path'])!=sorted(changes.values(),key=lambda item:item['path'])):
            raise ValueError('Component input migration receipt differs from exact recomputation')
        # Every migrated original source must still match the same recomputation.
        for relative,change in changes.items():checked(sandbox,relative,change['after_sha256'])
        return {'receipt':str(receipt),'receipt_sha256':sha(receipt),'recomputed_exact':True,'bindings':transformed}
    return {'receipt':None,'recomputed_exact':True,'bindings':[]}


def write(entry,spec,sandbox,output):
    normalized,changes=review(entry,spec,entry['project'])
    snapshot=snapshot_bindings(entry,sandbox,output)
    output=Path(output);original=output/'authored_compose_job.original.json';actual=output/'authored_compose_job.actual.json'
    original.write_bytes(Path(entry['job_source']).read_bytes());dump(actual,normalized)
    dump(output/'authored_compose_job.transport.json',{'version':'whitebox-compose-qualified-component-transport.v1','original_path':entry['job_source'],'original_sha256':sha(original),'actual_sha256':sha(actual),'changes':changes,'inverse_json_equal':True,'policy':entry['policy_path'],'policy_sha256':entry['policy_sha256'],'author_builder_unchanged':True,'snapshot_bindings':snapshot,'author_automation_flags_added':[],'scoring_semantics_changed':False})
    return actual
