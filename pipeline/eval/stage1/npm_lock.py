"""Attest lock-only additions for inactive platform optional dependencies.

Existing packages, all root metadata, and package.json must remain identical.
An added optional record may only describe an exact dependency of an unchanged
installed parent, target another platform, and be absent from node_modules.
"""
import base64
import json
import platform
import re
from pathlib import Path

from .protocol import sha

VERSION='npm-inactive-platform-lock-additions.v1'


def inactive_optional_additions(root):
    root=Path(root);before=root/'input/project';after=root/'runtime/project'
    original=before/'package-lock.json';updated=after/'package-lock.json'
    if not original.is_file() or not updated.is_file():return None
    if sha(before/'package.json')!=sha(after/'package.json'):return None
    old=json.loads(original.read_text());new=json.loads(updated.read_text())
    if old.get('lockfileVersion')!=3 or new.get('lockfileVersion')!=3:return None
    if {k:v for k,v in old.items() if k!='packages'}!={k:v for k,v in new.items() if k!='packages'}:return None
    prior=old.get('packages');current=new.get('packages')
    if not isinstance(prior,dict) or not isinstance(current,dict):return None
    if any(current.get(k)!=v for k,v in prior.items()):return None
    added=sorted(current.keys()-prior.keys())
    if not added:return None
    host_os={'Darwin':'darwin','Linux':'linux','Windows':'win32'}.get(platform.system())
    host_cpu={'arm64':'arm64','aarch64':'arm64','x86_64':'x64','AMD64':'x64'}.get(platform.machine())
    if host_os is None or host_cpu is None:return None
    proofs=[]
    for name in added:
        if not re.fullmatch(r'node_modules/(?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+',name):return None
        record=current[name];package=name[len('node_modules/'):]
        allowed={'version','resolved','integrity','cpu','os','libc','dev','license','optional'}
        if not isinstance(record,dict) or set(record)-allowed or record.get('optional') is not True:return None
        version=record.get('version')
        if not isinstance(version,str) or not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?',version):return None
        tarball=package.split('/')[-1]
        if record.get('resolved')!=f'https://registry.npmjs.org/{package}/-/{tarball}-{version}.tgz':return None
        integrity=record.get('integrity','')
        if not isinstance(integrity,str) or not integrity.startswith('sha512-'):return None
        try:
            if len(base64.b64decode(integrity[7:],validate=True))!=64:return None
        except ValueError:return None
        oses=record.get('os',[]);cpus=record.get('cpu',[])
        if any(not isinstance(values,list) or not values or any(not isinstance(v,str) or v.startswith('!') for v in values) for values in (oses,cpus)):return None
        if host_os in oses and host_cpu in cpus:return None
        if (after/name).exists() or (after/name).is_symlink():return None
        parents=[]
        for parent,meta in prior.items():
            if not parent or meta.get('optionalDependencies',{}).get(package)!=version:continue
            manifest=after/parent/'package.json'
            if not manifest.is_file():continue
            installed=json.loads(manifest.read_text())
            if installed.get('version')!=meta.get('version') or installed.get('optionalDependencies',{}).get(package)!=version:continue
            parents.append({'path':parent,'version':meta['version'],'installed_manifest_sha256':sha(manifest)})
        if not parents:return None
        proofs.append({'package':package,'version':version,'record':record,'unchanged_optional_parents':parents})
    return {'version':VERSION,'before_sha256':sha(original),'after_sha256':sha(updated),
        'host':{'os':host_os,'cpu':host_cpu},'inactive_uninstalled_additions':proofs,
        'rule':'all existing lock records unchanged; added packages cannot execute on this host and are not installed'}
