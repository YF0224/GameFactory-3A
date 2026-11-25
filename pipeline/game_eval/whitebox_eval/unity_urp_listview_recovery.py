"""Four exact Editor type qualifications, verified against the selected Editor."""
from pathlib import Path
import json,re
from .protocol import sha
from .unity_shadergraph_access_recovery import checked

PACKAGE='com.unity.render-pipelines.universal'
RELATIVE=PACKAGE+'/Editor/Converter/RenderPipelineConvertersEditor.cs'
SOURCE='Packages/'+RELATIVE
TYPE='UnityEngine.UIElements.ListView'
EDITOR_ONLY_ADDITION="""                // Skip abstract types that cannot be instantiated
                if (converterList[i].IsAbstract)
                    continue;

"""
LINES=(
 '                ListView listView = child.Q<ListView>("converterItems");',
 '                    m_ConverterSelectedVE.Q<ListView>("converterItems").Rebuild();',
 '            child.Q<ListView>("converterItems").Rebuild();')

def sources(entry,root,selected_editor):
    review=entry['listview_type_qualification']
    if str(Path(selected_editor).resolve())!=str(Path(entry['selected_editor']).resolve()):raise ValueError('ListView selected Editor changed')
    original=checked(entry['project'],SOURCE,review['source_sha256'])
    path=checked(root,SOURCE,review['source_sha256'])
    editor_root=Path(selected_editor).parent.parent/'Resources/PackageManager/BuiltInPackages'
    editor=checked(editor_root,RELATIVE,review['editor_source_sha256'])
    for package_root,key in [(Path(entry['project'])/'Packages','package_sha256'),(editor_root,'editor_package_sha256')]:
        definition=checked(package_root,PACKAGE+'/package.json',review[key]);value=json.loads(definition.read_text())
        if value.get('name')!=PACKAGE or value.get('version')!=review[key.replace('sha256','version')]:raise ValueError('ListView package identity changed')
    for key in ('prior_receipt','compiler_log'):
        if sha(Path(review[key]))!=review[key+'_sha256']:raise ValueError('ListView failure evidence changed')
    execution=json.loads(Path(review['prior_receipt']).read_text()).get('execution',{})
    if execution.get('owned_process_exited') is not True or execution.get('exit_code') in (None,0):raise ValueError('ListView requires completed native failure')
    before=path.read_bytes().decode('utf-8');after=before;expected=set();edits=[]
    lines=before.splitlines()
    for line in LINES:
        positions=[i+1 for i,value in enumerate(lines) if value==line]
        if len(positions)!=1:raise ValueError('Reviewed ListView statement is missing or ambiguous')
        row=positions[0];replacement=re.sub(r'\bListView\b',TYPE,line);after=after.replace(line,replacement,1)
        for match in re.finditer(r'\bListView\b',line):
            expected.add(f"{SOURCE}({row},{match.start()+1}): error CS0104: 'ListView' is an ambiguous reference between 'UnityEditor.Search.ListView' and 'UnityEngine.UIElements.ListView'")
        edits.append({'line':row,'before':line,'after':replacement})
    if len(expected)!=4:raise ValueError('ListView qualification count changed')
    reference=editor.read_bytes().decode('utf-8')
    if reference.count(EDITOR_ONLY_ADDITION)!=1 or reference.replace(EDITOR_ONLY_ADDITION,'',1)!=after:
        raise ValueError('Qualified ListView code does not equal the selected Editor implementation')
    actual={line.strip() for line in Path(review['compiler_log']).read_text(errors='replace').splitlines() if 'error CS' in line}
    if actual!=expected:raise ValueError('ListView review must cover exact four native compiler errors')
    inverse=after
    for edit in edits:inverse=inverse.replace(edit['after'],edit['before'],1)
    if inverse!=before:raise ValueError('ListView qualification is not exactly reversible')
    return {'source':SOURCE,'before_utf8':before,'after_utf8':after,'before_sha256':sha(original),'editor_source':str(editor),'editor_sha256':sha(editor),'identifier_qualifications':4,'edits':edits,'inverse_bytes_equal':True,'selected_editor_qualified_implementation_equal':True,'unrelated_editor_abstract_filter_not_applied':True,'gameplay_changes':[]}
