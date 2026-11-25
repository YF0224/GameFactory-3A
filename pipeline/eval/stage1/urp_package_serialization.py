"""Strict source-bound URP package-field serialization, never authored changes.

Accept only a vendor YAML namespace header and absent package resource fields
whose exact Reload declarations and target assets exist in the captured package.
Original lines, order and every pre-existing non-null reference must be intact.
"""
from pathlib import Path
import re
from .protocol import sha

VERSION='unity-recorded-package-resource-serialization.v1'


def class_body(text,name):
    matches=list(re.finditer(r'\bpublic sealed class '+re.escape(name)+r'\s*\{',text))
    if len(matches)!=1:raise ValueError('Package resource class is not unique')
    start=matches[0].end();depth=1
    for i in range(start,len(text)):
        if text[i]=='{':depth+=1
        elif text[i]=='}':depth-=1
        if depth==0:return text[start:i],start
    raise ValueError('Unclosed package resource class')


def package_fields(cache):
    cache=Path(cache).resolve()
    renderers=list(cache.glob('com.unity.render-pipelines.universal@*/Runtime/UniversalRendererData.cs'))
    if len(renderers)!=1:raise ValueError('Captured URP renderer package is not unique')
    renderer=renderers[0];package=renderer.parent.parent
    fields={}
    for section,name,classname in [('shaders','UniversalRendererData.cs','ShaderResources'),
                                   ('debugShaders','ScriptableRendererData.cs','DebugShaderResources')]:
        source=renderer.parent/name
        if source.is_symlink() or not source.resolve().is_relative_to(cache):raise ValueError('Package source escaped')
        text=source.read_text()
        if not re.search(r'public '+classname+r'\s+'+section+r'\s*(?:=[^;]+)?;',text):
            raise ValueError('Package section is not declared with resource class')
        body,offset=class_body(text,classname)
        pattern=r'\[Reload\("([^"\n]+)"\)\]\s+public (Shader|ComputeShader) ([A-Za-z_]\w*);'
        for match in re.finditer(pattern,body):
            relative,kind,field=match.groups();asset=package/relative
            if (Path(relative).is_absolute() or '..' in Path(relative).parts or asset.is_symlink()
                    or not asset.resolve().is_relative_to(package.resolve())
                    or asset.suffix!=('.shader' if kind=='Shader' else '.compute') or not asset.is_file()):
                raise ValueError('Package Reload target missing or escaped')
            meta=Path(str(asset)+'.meta')
            if meta.is_symlink():raise ValueError('Package resource metadata symlink')
            guids=re.findall(r'(?m)^guid: ([0-9a-f]{32})$',meta.read_text())
            if len(guids)!=1:raise ValueError('Package Reload target GUID not unique')
            key=section+'.'+field
            if key in fields:raise ValueError('Duplicate package resource field')
            fields[key]={'field':key,'file_id':4800000 if kind=='Shader' else 7200000,
                'guid':guids[0],'declaration_source':str(source.resolve()),
                'declaration_source_sha256':sha(source),'declaration_line':text.count('\n',0,offset+match.start())+1,
                'resource_source':str(asset.resolve()),'resource_source_sha256':sha(asset),
                'resource_metadata':str(meta.resolve()),'resource_metadata_sha256':sha(meta)}
    return fields


def resource_rows(lines):
    section=None;rows={}
    for index,line in enumerate(lines):
        heading=re.fullmatch(r'  ([A-Za-z_]\w*):.*',line)
        if heading:section=heading[1]
        match=re.fullmatch(r'    ([A-Za-z_]\w*): \{fileID: (0|4800000|7200000)(?:, guid: ([0-9a-f]{32}), type: 3)?\}',line)
        if section in {'shaders','debugShaders'} and match:
            key=section+'.'+match[1]
            if key in rows:raise ValueError('Duplicate serialized resource field')
            rows[key]=(index,int(match[2]),match[3])
    return rows


def review(before,after,cache):
    original=before.splitlines();recorded=after.splitlines()
    old=resource_rows(original);new=resource_rows(recorded)
    fields=package_fields(cache);allowed_indices=set();changes=[]
    for key,(index,file_id,guid) in new.items():
        previous=old.get(key)
        if previous and (previous[1],previous[2])==(file_id,guid):continue
        if previous and previous[1:]!=(0,None):raise ValueError('Existing package resource changed')
        proof=fields.get(key)
        if not proof or (file_id,guid)!=(proof['file_id'],proof['guid']):
            raise ValueError('Resource differs from exact captured package Reload default')
        allowed_indices.add(index)
        changes.append(dict(proof,kind='added_package_resource' if previous is None else 'null_to_package_resource',
                            recorded_physical_line=index+1))
    # Reconstruct the original byte-line sequence by deleting only proven added
    # fields and substituting only proven prior null fields. No generic YAML load.
    normalized=[]
    for index,line in enumerate(recorded):
        if index in allowed_indices:
            key=next(k for k,row in new.items() if row[0]==index)
            if key in old:normalized.append(original[old[key][0]])
        else:normalized.append(line)
    header=None
    if (len(original)>1 and len(normalized)>1
            and original[1]=='%TAG !u! tag:unity3d.com,2011:'
            and normalized[1]=='%TAG !u! tag:yousandi.cn,2023:'):
        normalized[1]=original[1]
        header={'physical_line':2,'before':original[1],'after':recorded[1]}
    if normalized!=original:raise ValueError('Renderer import has unexplained structure, parameter, removal or order change')
    if not changes and header is None:raise ValueError('Package serialization review has no changes')
    return {'version':VERSION,'yaml_tag_change':header,'package_resource_changes':changes}
