"""Exact isolated use of the existing native input migration; originals immutable."""
from pathlib import Path
import hashlib
from . import batch, unity_m_scope, unity_input_migration
from .protocol import dump, sha


def prepare(root, output, acceptance):
    receipt=output/'native_project_override.json'
    if receipt.exists():return verify(root,output,acceptance)
    original=Path(batch.read(root/'input_manifest.json')['entry']['project']).resolve()
    sandbox=output/'isolated_inputsystem_project'
    if sandbox.exists():raise ValueError('Preserved partial input snapshot requires explicit recovery')
    from engine_adapters.unity3d.playtest import background_record, project_snapshot
    snapshot=background_record.snapshot_project(original,sandbox,Path(__file__).parent)
    dump(output/'original_project_snapshot.json',snapshot)
    package,_=project_snapshot.input_system_package()
    migration_path=output/'input_migration.json'
    migration=unity_input_migration.migrate_input(sandbox,migration_path,package_root=package)
    if migration['gameplay_changes']!=[]:raise ValueError('Gameplay changes forbidden')
    original_hashes=unity_m_scope.source_files(original)
    frozen=batch.read(root/'unity_m_source_binding.json')['source_hashes']
    if original_hashes!=frozen:raise ValueError('Original changed during migration')
    dump(receipt,{'version':'unity-m-isolated-native-project.v1','original':str(original),
        'original_source_hashes':original_hashes,'snapshot':str(sandbox),
        'snapshot_hashes':unity_m_scope.source_files(sandbox),
        'snapshot_receipt':str(output/'original_project_snapshot.json'),
        'snapshot_receipt_sha256':sha(output/'original_project_snapshot.json'),
        'migration':str(migration_path),'migration_sha256':sha(migration_path),
        'migration_changes':migration['changes'],'gameplay_changes':[],
        'migrator':str(Path(unity_input_migration.__file__).resolve()),
        'migrator_sha256':sha(Path(unity_input_migration.__file__)),
        'native_acceptance_sha256':sha(acceptance)})
    return verify(root,output,acceptance)


def verify(root,output,acceptance):
    b=batch.read(output/'native_project_override.json')
    original=Path(batch.read(root/'input_manifest.json')['entry']['project']).resolve()
    sandbox=(output/'isolated_inputsystem_project').resolve()
    if (b['version']!='unity-m-isolated-native-project.v1'
        or Path(b['original']).resolve()!=original or Path(b['snapshot']).resolve()!=sandbox
        or b['original_source_hashes']!=batch.read(root/'unity_m_source_binding.json')['source_hashes']
        or unity_m_scope.source_files(original)!=b['original_source_hashes']
        or unity_m_scope.source_files(sandbox)!=b['snapshot_hashes']
        or sha(Path(b['migration']))!=b['migration_sha256']
        or sha(Path(b['snapshot_receipt']))!=b['snapshot_receipt_sha256']
        or sha(Path(unity_input_migration.__file__))!=b['migrator_sha256']
        or sha(acceptance)!=b['native_acceptance_sha256'] or b['gameplay_changes']!=[]):
        raise ValueError('Isolated native input snapshot/source/migration/acceptance changed')
    m=batch.read(Path(b['migration']))
    if m['changes']!=b['migration_changes'] or m['gameplay_changes']!=[]:
        raise ValueError('Only existing native device-read migration allowed')
    for c in m['changes']:
        before=original/c['path'];after=sandbox/c['path']
        if (c['kind']!='native_input_device_reads_only' or hashlib.sha256(before.read_text().encode()).hexdigest()!=c['before_sha256']
            or sha(after)!=c['after_sha256']
            or unity_input_migration.migrate_device_reads(before.read_text())!=after.read_text()):
            raise ValueError('Author gameplay changed outside exact device-read translation')
    return sandbox


def materialization_proof(recorded):
    """Recompute every isolated edit; a hash receipt alone cannot permit gameplay edits."""
    import copy
    import json
    import re
    import yaml
    from engine_adapters.unity3d.playtest import project_snapshot
    from engine_adapters.unity3d.playtest.input_axis_serialization import canonical_axes
    recorded=Path(recorded).resolve()
    output=recorded/'unity_m_native_dispatch'
    native=batch.read(recorded/'recorder_acceptance_binding.json')
    sandbox=verify(recorded,output,Path(native['acceptance']))
    b=batch.read(output/'native_project_override.json')
    original=Path(b['original']);m=batch.read(Path(b['migration']))
    expected={c['path']:unity_input_migration.migrate_device_reads((original/c['path']).read_text()).encode() for c in m['changes']}
    for c in m['changes']:
        parent=(original/c['path']).parent
        while parent!=original:
            definitions=list(parent.glob('*.asmdef'))
            if definitions:
                if len(definitions)!=1:raise ValueError('Ambiguous original assembly')
                definition=definitions[0];name=str(definition.relative_to(original))
                doc=json.loads(definition.read_text());refs=doc.setdefault('references',[])
                if 'GameFactoryInputMigration' not in refs:
                    refs.append('GameFactoryInputMigration')
                    expected[name]=(json.dumps(doc,indent=2)+'\n').encode()
                break
            parent=parent.parent
    settings='ProjectSettings/ProjectSettings.asset'
    text=(original/settings).read_text()
    pattern=r'(?m)^([ \t]*)(m_ActiveInputHandler|activeInputHandler):[ \t]*(-?\d+)[ \t]*$'
    if len(list(re.finditer(pattern,text)))!=1:raise ValueError('Ambiguous original input setting')
    expected[settings]=re.sub(pattern,r'\g<1>activeInputHandler: 1',text).encode()
    manifest='Packages/manifest.json';doc=json.loads((original/manifest).read_text())
    doc['dependencies']['com.unity.inputsystem']='file:'+m['input_system_package']
    expected[manifest]=(json.dumps(doc,indent=2)+'\n').encode()
    shim=Path(project_snapshot.__file__).parent/'resources/GameFactoryInput.cs'
    expected['Assets/GameFactoryInputMigration/GameFactoryInput.cs']=shim.read_bytes()
    expected['Assets/GameFactoryInputMigration/GameFactoryInputMigration.asmdef']=(json.dumps({
        'name':'GameFactoryInputMigration','references':['Unity.InputSystem'],'autoReferenced':True},indent=2)+'\n').encode()
    text=(original/'ProjectSettings/InputManager.asset').read_text()
    text='\n'.join(line for line in text.splitlines() if not line.startswith('%'))
    axes=canonical_axes(yaml.safe_load(re.sub(r'--- !u!\d+ &\d+','---',text))['InputManager']['m_Axes'])
    expected['Assets/Resources/GameFactoryInputAxes.json']=(json.dumps({'axes':axes},ensure_ascii=False,indent=2)+'\n').encode()
    before=b['original_source_hashes'];after=b['snapshot_hashes']
    changed={name for name in before.keys()|after.keys() if before.get(name)!=after.get(name)}
    # Project snapshot policy omits editor-local settings. Verify the omission,
    # and require the actual recorded copy still be exactly the original bytes.
    excluded=[]
    for name in sorted(changed-set(expected)):
        if (name in {'UserSettings/EditorUserSettings.asset','UserSettings/Search.settings'}
                and 'UserSettings' in project_snapshot.EXCLUDED
                and name in before and name not in after
                and not (sandbox/name).exists()
                and (recorded/'background_record/project'/name).is_file()
                and sha(recorded/'background_record/project'/name)==before[name]):
            excluded.append(dict(path=name,original_sha256=before[name],isolated_absent=True,
                recorded_sha256=before[name],policy_module=str(Path(project_snapshot.__file__).resolve()),
                policy_module_sha256=sha(Path(project_snapshot.__file__))))
    name='UserSettings/EditorUserSettings.asset'
    captured_editor=recorded/'background_record/project'/name
    if (name in changed-set(expected)-{row['path'] for row in excluded}
            and 'UserSettings' in project_snapshot.EXCLUDED
            and name in before and name not in after
            and not (sandbox/name).exists() and not (sandbox/name).is_symlink()
            and (original/name).is_file() and not (original/name).is_symlink()
            and captured_editor.is_file() and not captured_editor.is_symlink()
            and sha(original/name)==before[name] and 'snapshot_receipt' in b):
        from .unity_native_import_metadata import editor_recent_scene
        receipt=Path(b['snapshot_receipt']);snapshot=batch.read(receipt)
        if (snapshot.get('policy')!=project_snapshot.SNAPSHOT_POLICY
                or Path(snapshot.get('source','')).resolve()!=original.resolve()
                or 'UserSettings' not in snapshot.get('excluded_artifacts',[])):
            raise ValueError('Unproven native Editor-local snapshot exclusion')
        transform=editor_recent_scene((original/name).read_bytes().decode('utf-8'),
                                     captured_editor.read_bytes().decode('utf-8'))
        excluded.append(dict(path=name,original_sha256=before[name],isolated_absent=True,
            recorded_sha256=sha(captured_editor),policy_module=str(Path(project_snapshot.__file__).resolve()),
            policy_module_sha256=sha(Path(project_snapshot.__file__)),
            snapshot_receipt=str(receipt),snapshot_receipt_sha256=sha(receipt),
            native_editor_transform=transform))
    # Build products are absent in both native snapshots by the explicit
    # recorded source-walker policy. Their original files remain immutable and
    # are retained in the derived author input, including every author header.
    build_excluded=[]
    for name in sorted(changed-set(expected)-{row['path'] for row in excluded}):
        if Path(name).parts[0] not in {'Build','Builds'}:
            continue
        receipt=Path(b['snapshot_receipt'])
        snapshot=batch.read(receipt)
        top=Path(name).parts[0]
        if (top not in project_snapshot.EXCLUDED
                or snapshot.get('policy')!=project_snapshot.SNAPSHOT_POLICY
                or Path(snapshot.get('source','')).resolve()!=original.resolve()
                or top not in snapshot.get('excluded_artifacts',[])
                or name in snapshot.get('files_sha256',{})
                or name not in before or name in after
                or not (original/name).is_file() or sha(original/name)!=before[name]
                or (sandbox/name).exists()
                or (recorded/'background_record/project'/name).exists()):
            raise ValueError('Unproven original build snapshot exclusion: '+name)
        build_excluded.append(dict(path=name,original_sha256=before[name],
            isolated_absent=True,recorded_absent=True,
            original_author_input_preserved=True,snapshot_receipt=str(receipt),
            snapshot_receipt_sha256=sha(receipt),
            policy_module=str(Path(project_snapshot.__file__).resolve()),
            policy_module_sha256=sha(Path(project_snapshot.__file__))))
    changed-= {row['path'] for row in excluded+build_excluded}
    if changed-set(expected):raise ValueError('Unreviewed isolated migration changes: '+str(sorted(changed-set(expected))))
    for name,data in expected.items():
        if (sandbox/name).read_bytes()!=data:raise ValueError('Isolated migration transform differs: '+name)
    captured=recorded/'background_record/project'
    rows=[]
    settings_import=None
    if (captured/settings).read_bytes()!=(sandbox/settings).read_bytes():
        from .unity_m_settings_import import proof as settings_proof
        settings_import=settings_proof(recorded,sandbox)
    for name in sorted(changed):
        if name not in ({'Packages/manifest.json',settings} if settings_import else {'Packages/manifest.json'}) and (captured/name).read_bytes()!=(sandbox/name).read_bytes():
            raise ValueError('Native capture changed input migration bytes: '+name)
        rows.append({'path':name,'original_sha256':before.get(name),'isolated_sha256':after[name],
                     'recorded_sha256':sha(captured/name),'added':name not in before})
    return {'version':'unity-m-exact-input-materialization.v1','override':str(output/'native_project_override.json'),
        'override_sha256':sha(output/'native_project_override.json'),'isolated_project':str(sandbox),
        'changes':rows,'gameplay_changes':[],'original_author_sources_required':True,
        **({'editor_local_snapshot_exclusions':excluded} if excluded else {}),
        **({'build_snapshot_exclusions':build_excluded} if build_excluded else {}),
        **({'native_settings_import':settings_import} if settings_import else {})}


def derive_endpoint_references(recorded, attempt, plan, proof):
    """Bind source references to the exact line-preserving device-read transform."""
    import copy
    result=copy.deepcopy(plan)
    changes={r['path']:r for r in proof['changes'] if not r['added']}
    for endpoint in result.get('capture_plan',{}).get('endpoints',{}).values():
        for ref in endpoint.get('source_evidence',[]):
            name=ref['path'];before=Path(recorded)/'input/project'/name;after=Path(attempt)/'input/project'/name
            if sha(before)!=ref['sha256']:
                raise ValueError('Original endpoint source reference changed')
            if sha(before)==sha(after):continue
            row=changes.get(name)
            if (not row or not name.endswith('.cs') or row['original_sha256']!=sha(before)
                    or row['recorded_sha256']!=sha(after)
                    or unity_input_migration.migrate_device_reads(before.read_text())!=after.read_text()
                    or len(before.read_text().splitlines())!=len(after.read_text().splitlines())):
                raise ValueError('Endpoint reference requires exact line-preserving device reads')
            ref['sha256']=sha(after)
    return result


def verify_derived_schedule(folder, frozen, derived):
    """The preserved native schedule may differ solely in proven source-reference SHA."""
    import copy
    root=Path(folder).parent
    provenance=batch.read(root/'recorded_capture_provenance.json')
    recorded=Path(provenance['source_attempt'])
    from .unity_m_evidence import qualify_recorded
    qualify_recorded(recorded)
    if sha(Path(folder)/'capture_schedule.json')!=sha(recorded/'background_record/take/capture_schedule.json'):
        raise ValueError('Preserved native schedule bytes changed')
    proof=materialization_proof(recorded)
    expected=copy.deepcopy(frozen)
    expected['plan']=derive_endpoint_references(recorded,root,{'capture_plan':frozen['plan']},proof)['capture_plan']
    if expected!=derived:
        raise ValueError('Derived schedule differs beyond exact source references')
    return True


def generated_migration_metadata(original, observed, relative):
    """Exact IDE-only regeneration accompanying an independently proven migration.

    Custom author assembly names are valid. All compile entries and all other
    XML bytes remain identical; editor solution selection is a single literal
    replacement backed by both real local solution files.
    """
    import json
    import re
    path = Path(relative)
    before, after = Path(original)/path, Path(observed)/path
    if before.is_symlink() or after.is_symlink():
        return None
    try:
        left = before.read_bytes().decode('utf-8-sig')
        right = after.read_bytes().decode('utf-8-sig')
        if len(path.parts) == 1 and path.suffix == '.csproj':
            pattern = r'<DefineConstants>([^<>]+)</DefineConstants>'
            a, b = re.findall(pattern, left), re.findall(pattern, right)
            if len(a) != 1 or len(b) != 1:
                return None
            parts = a[0].split(';')
            if parts.count('ENABLE_LEGACY_INPUT_MANAGER') != 1 or 'ENABLE_INPUT_SYSTEM' in parts:
                return None
            expected = ';'.join('ENABLE_INPUT_SYSTEM' if s == 'ENABLE_LEGACY_INPUT_MANAGER' else s for s in parts)
            if b[0] != expected:
                return None
            restored = right.replace('<DefineConstants>'+b[0]+'</DefineConstants>', '<DefineConstants>'+a[0]+'</DefineConstants>')
            from .unity_ide_metadata import INPUT_REFERENCES
            added = []
            for name in INPUT_REFERENCES:
                line = '    <ProjectReference Include="'+name+'.csproj" />'
                if line in left:
                    continue
                pattern = r'(?m)^'+re.escape(line)+r'\r?\n'
                count = len(re.findall(pattern, restored))
                if count > 1:
                    return None
                if count == 1:
                    restored = re.sub(pattern, '', restored)
                    added.append(name)
            if restored != left:
                return None
            detail = dict(define_before='ENABLE_LEGACY_INPUT_MANAGER', define_after='ENABLE_INPUT_SYSTEM', added_project_references=added)
        elif relative == '.vscode/settings.json':
            a, b = json.loads(left), json.loads(right)
            old, new = a.get('dotnet.defaultSolution'), b.get('dotnet.defaultSolution')
            if not isinstance(old, str) or new != 'project.sln' or old == new:
                return None
            if len(Path(old).parts) != 1 or Path(old).suffix not in {'.sln', '.slnx'}:
                return None
            if not (Path(original)/old).is_file() or not (Path(observed)/new).is_file():
                return None
            token = '"dotnet.defaultSolution": '+json.dumps(old)
            if left.count(token) != 1 or right != left.replace(token, '"dotnet.defaultSolution": '+json.dumps(new), 1):
                return None
            detail = dict(solution_before=old, solution_after=new)
        else:
            return None
        return dict(kind='unity_exact_input_migration_ide_metadata', path=relative,
                    before_sha256=sha(before), after_sha256=sha(after), changes=detail,
                    original_author_input_preserved=True, gameplay_changes=[])
    except (OSError, ValueError, UnicodeError):
        return None
