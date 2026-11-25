"""Source-bound Editor-only ShaderGraph access compatibility; no method body changes."""
from pathlib import Path
import json
import re
from .protocol import sha

PACKAGE = 'com.unity.shadergraph'
SOURCE = 'Packages/'+PACKAGE+'/Editor/Drawing/Views/MaterialGraphView.cs'
PROPERTIES = ('canCutSelection', 'canCopySelection', 'canDeleteSelection')


def checked(root, relative, digest):
    root=Path(root).resolve();rel=Path(relative);path=root/rel
    if (rel.is_absolute() or '..' in rel.parts or not path.is_file()
            or not path.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in (path,*path.parents) if p != root and root in p.parents)
            or sha(path)!=digest):
        raise ValueError('Reviewed compatibility source missing, escaped, or changed')
    return path


def sources(entry, root):
    root=Path(root)
    if entry.get('package_source')!=SOURCE or tuple(entry.get('properties',()))!=PROPERTIES:
        raise ValueError('Only the three reviewed ShaderGraph Editor properties are supported')
    path=checked(root,SOURCE,entry['package_source_sha256'])
    definition=checked(root,'Packages/'+PACKAGE+'/package.json',entry['package_definition_sha256'])
    package=json.loads(definition.read_text())
    if package.get('name')!=PACKAGE or package.get('version')!=entry.get('package_version'):
        raise ValueError('Embedded ShaderGraph package definition mismatched')
    original=path.read_bytes();text=original.decode('utf-8');replacements=[]
    for prop in PROPERTIES:
        pattern=r'(?m)^([ \t]*)protected override bool '+prop+r'(?=\s*(?:\r?\n)?\s*\{)'
        matches=list(re.finditer(pattern,text))
        if len(matches)!=1:
            raise ValueError('Reviewed property declaration is missing or ambiguous')
        old=matches[0].group();new=old.replace('protected override','protected internal override',1)
        replacements.append({'property':prop,'before':old,'after':new,'source_line':text.count('\n',0,matches[0].start())+1})
        text=text[:matches[0].start()]+new+text[matches[0].end():]
    return path,original,text.encode('utf-8'),replacements


def editor_sources(entry, selected_editor):
    if str(Path(selected_editor).resolve())!=str(Path(entry['selected_editor']).resolve()):
        raise ValueError('Selected Editor differs from reviewed ShaderGraph API')
    root=Path(selected_editor).parent.parent/'Resources/PackageManager/BuiltInPackages'
    path=checked(root,PACKAGE+'/Editor/Drawing/Views/MaterialGraphView.cs',entry['editor_source_sha256'])
    definition=checked(root,PACKAGE+'/package.json',entry['editor_package_sha256'])
    value=json.loads(definition.read_text())
    if value.get('name')!=PACKAGE or value.get('version')!=entry['editor_package_version']:
        raise ValueError('Selected Editor ShaderGraph package definition mismatched')
    text=path.read_bytes().decode('utf-8')
    for prop in PROPERTIES:
        if len(re.findall(r'(?m)^\s*protected internal override bool '+prop+r'(?=\s*\{)',text))!=1:
            raise ValueError('Selected Editor does not establish reviewed property access')
    return {'source':str(path),'source_sha256':sha(path),'package':str(definition),'package_sha256':sha(definition)}


def review(entry, errors):
    from .unity_native_compile_recovery import reviewed_builtin_errors
    _,_,_,replacements=sources(entry,entry['project'])
    editor_sources(entry,entry['selected_editor'])
    module_errors={s for s in errors if 'error CS1069:' in s}
    reviewed_builtin_errors(entry,module_errors)
    seen=set();line_numbers={r['property']:r['source_line'] for r in replacements}
    for line in set(errors)-module_errors:
        match=re.fullmatch(re.escape(SOURCE)+r"\((\d+),\d+\): error CS0507: 'MaterialGraphView\.(\w+)': cannot change access modifiers when overriding 'protected internal' inherited member 'GraphView\.\2'",line)
        if not match or match[2] not in PROPERTIES or int(match[1])!=line_numbers[match[2]]:
            raise ValueError('Unexpected compiler error in ShaderGraph compatibility review')
        seen.add(match[2])
    if seen!=set(PROPERTIES):
        raise ValueError('ShaderGraph review must cover exactly all three access errors')
    dependencies=json.loads(checked(entry['project'],entry['source'],entry['source_sha256']).read_text()).get('dependencies')
    if not isinstance(dependencies,dict) or any(m in dependencies for m in entry['modules']):
        raise ValueError('Refuse to replace an existing built-in package pin')
    if 'popup_type_qualification' in entry:
        popup_sources(entry, entry['project'], entry['selected_editor'])
    if 'listview_type_qualification' in entry:
        from .unity_urp_listview_recovery import sources as listview_sources
        listview_sources(entry,entry['project'],entry['selected_editor'])
    return True


def apply_access(entry, candidate, sandbox):
    from .protocol import dump
    # Validate both sources, the Editor and all module definitions before mutation.
    sources(entry,entry['project'])
    path,before,after,replacements=sources(entry,sandbox)
    editor=editor_sources(entry,candidate['selected_editor']);packages=[]
    popups=popup_sources(entry,sandbox,candidate['selected_editor']) if 'popup_type_qualification' in entry else []
    listview=None
    if 'listview_type_qualification' in entry:
        from .unity_urp_listview_recovery import sources as listview_sources
        listview=listview_sources(entry,sandbox,candidate['selected_editor'])
    for relative,digest in entry['compiler_sources'].items():
        checked(sandbox,relative,digest)
    manifest_path=checked(sandbox,entry['source'],entry['source_sha256'])
    manifest_before=manifest_path.read_bytes();manifest=json.loads(manifest_before)
    for module in entry['modules']:
        package=Path(candidate['selected_editor']).parent.parent/'Resources/PackageManager/BuiltInPackages'/module/'package.json'
        definition=json.loads(package.read_text())
        if definition.get('name')!=module or definition.get('version')!='1.0.0' or definition.get('type')!='module' or module in manifest['dependencies']:
            raise ValueError('Reviewed built-in module definition or pin mismatched')
        packages.append({'name':module,'path':str(package),'sha256':sha(package),'version':'1.0.0'})
    for package in packages:manifest['dependencies'][package['name']]='1.0.0'
    path.write_bytes(after);dump(manifest_path,manifest)
    for popup in popups:
        (Path(sandbox)/popup['source']).write_bytes(popup['after_utf8'].encode('utf-8'))
    if listview:(Path(sandbox)/listview['source']).write_bytes(listview['after_utf8'].encode('utf-8'))
    return {'urp_listview_type_qualification':listview,'package_source':SOURCE,'package_before_utf8':before.decode('utf-8'),'package_after_utf8':after.decode('utf-8'),
            'package_before_sha256':entry['package_source_sha256'],'package_after_sha256':sha(path),
            'manifest_before_utf8':manifest_before.decode('utf-8'),'manifest_after_utf8':manifest_path.read_text(),
            'access_modifier_changes':replacements,'selected_editor_reference':editor,'builtin_packages':packages,
            'popup_type_qualifications':popups,'method_body_changes':[{'source':p['source'],'change':'Only qualify the existing PopupList constructor type in the Editor getter.'} for p in popups],'gameplay_changes':[],'compiler_sources_unchanged':entry['compiler_sources']}


POPUP_SOURCES = ('Editor/Data/Nodes/GeometryNode.cs', 'Editor/Data/Nodes/Input/Geometry/ViewVectorNode.cs')
POPUP_CONTROL = 'Editor/Drawing/Controls/PopupControl.cs'
POPUP_NAME = 'UnityEditor.ShaderGraph.Drawing.Controls.PopupList'


def popup_property(text, qualified):
    name = re.escape(POPUP_NAME) if qualified else 'PopupList'
    matches=list(re.finditer(r'(?m)^[ \t]*public '+name+r' spacePopup\s*\{',text))
    if len(matches)!=1:raise ValueError('Reviewed PopupList property missing or ambiguous')
    start=matches[0].start();brace=text.index('{',start);depth=0
    for end in range(brace,len(text)):
        depth+=(text[end]=='{')-(text[end]=='}')
        if depth==0:return text[start:end+1]
    raise ValueError('Unclosed reviewed PopupList property')


def popup_sources(entry, root, selected_editor):
    """Qualify only two exact Editor properties, against byte-identical target type."""
    from .batch import read
    review=entry['popup_type_qualification']
    if set(review.get('sources',{}))!=set(POPUP_SOURCES):
        raise ValueError('Only the two reviewed ShaderGraph PopupList files are supported')
    if str(Path(selected_editor).resolve())!=str(Path(entry['selected_editor']).resolve()):
        raise ValueError('PopupList Editor differs from reviewed source')
    editor_root=Path(selected_editor).parent.parent/'Resources/PackageManager/BuiltInPackages'
    package_root=Path(root)/'Packages'
    control=checked(package_root,PACKAGE+'/'+POPUP_CONTROL,review['control_sha256'])
    editor_control=checked(editor_root,PACKAGE+'/'+POPUP_CONTROL,review['editor_control_sha256'])
    if control.read_bytes()!=editor_control.read_bytes():
        raise ValueError('PopupList target definition differs from selected Editor')
    definition=control.read_text()
    signature=r'struct PopupList\s*\{\s*public int selectedEntry;\s*public string\[\] popupEntries;\s*public PopupList\(string\[\] entries, int defaultEntry\)\s*\{\s*popupEntries = entries;\s*selectedEntry = defaultEntry;\s*\}\s*\}'
    if ('namespace UnityEditor.ShaderGraph.Drawing.Controls' not in definition
            or len(re.findall(signature,definition))!=1):
        raise ValueError('PopupList target API is not the exact delivered definition')
    for key in ('prior_receipt','compiler_log'):
        if sha(Path(review[key]))!=review[key+'_sha256']:
            raise ValueError('PopupList failed native evidence changed')
    execution=read(Path(review['prior_receipt'])).get('execution',{})
    if execution.get('owned_process_exited') is not True or execution.get('exit_code') in (None,0):
        raise ValueError('PopupList review requires completed failed native execution')
    actual={line.strip() for line in Path(review['compiler_log']).read_text(errors='replace').splitlines() if 'error CS' in line}
    expected=set();changes=[]
    for relative in POPUP_SOURCES:
        binding=review['sources'][relative]
        path=checked(package_root,PACKAGE+'/'+relative,binding['source_sha256'])
        reference=checked(editor_root,PACKAGE+'/'+relative,binding['editor_sha256'])
        before=path.read_bytes().decode('utf-8');property=popup_property(before,False)
        if property.count('public PopupList spacePopup')!=1 or property.count('new PopupList(names, (int)m_Space)')!=1:
            raise ValueError('Reviewed PopupList declarations changed')
        qualified=property.replace('public PopupList spacePopup','public '+POPUP_NAME+' spacePopup',1).replace('new PopupList(names, (int)m_Space)','new '+POPUP_NAME+'(names, (int)m_Space)',1)
        if qualified.replace('\r\n','\n')!=popup_property(reference.read_bytes().decode('utf-8'),True).replace('\r\n','\n'):
            raise ValueError('Qualified property differs from selected Editor implementation')
        prefix='Packages/'+PACKAGE+'/'+relative
        constructor=[];members=[]
        for row,line in enumerate(before.splitlines(),1):
            if 'return new PopupList(names, (int)m_Space);' in line:
                constructor.append(row)
                expected.add(f"{prefix}({row},{line.index('names')+1}): error CS1503: Argument 1: cannot convert from 'string[]' to 'UnityEditor.PopupList.InputData'")
                expected.add(f"{prefix}({row},{line.index('(int)')+1}): error CS1503: Argument 2: cannot convert from 'int' to 'string'")
            if 'value.selectedEntry' in line:
                members.append(row)
                expected.add(f"{prefix}({row},{line.index('selectedEntry')+1}): error CS1061: 'PopupList' does not contain a definition for 'selectedEntry' and no accessible extension method 'selectedEntry' accepting a first argument of type 'PopupList' could be found (are you missing a using directive or an assembly reference?)")
        if len(constructor)!=1 or len(members)!=2:
            raise ValueError('PopupList error locations ambiguous')
        changes.append({'source':prefix,'before_utf8':before,'after_utf8':before.replace(property,qualified,1),'before_sha256':sha(path),'editor_source':str(reference),'editor_sha256':sha(reference),'control_sha256':sha(control),'identifier_qualifications':2})
    if actual!=expected:
        raise ValueError('PopupList review must exactly cover all eight actual native errors')
    return changes
