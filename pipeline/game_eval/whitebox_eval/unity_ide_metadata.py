"""Narrow proof for Unity's regenerated IDE solution after recorder installation."""
from pathlib import Path
import re
from .protocol import sha

GUID = r'\{[0-9A-Fa-f-]{36}\}'
PROJECT = re.compile(r'Project\("('+GUID+r')"\) = "([A-Za-z0-9_.-]+)", "([A-Za-z0-9_.-]+\.csproj)", "('+GUID+r')"\nEndProject\n?')
TOOLING = {'Assembly-CSharp-Editor', 'GameFactory3A.Evaluation.Runtime', 'GameFactory3A.Evaluation.Editor'}
TOOL_COMPILE_PATHS = {'Assets/GameFactory3AEvaluation/Editor/WhiteboxNativeOpen.cs'}


def _parse(text, tooling=TOOLING):
    if 'Microsoft Visual Studio Solution File, Format Version 12.00' not in text:
        raise ValueError('Unknown solution header')
    rows = PROJECT.findall(text)
    if not rows or len({row[3] for row in rows}) != len(rows):
        raise ValueError('Invalid or duplicate solution project')
    entries = {guid: (kind, name, project) for kind, name, project, guid in rows}
    for kind, name, project in entries.values():
        if project != name+'.csproj':
            raise ValueError('Solution paths are not local generated projects')
    skeleton = PROJECT.sub('', text)
    # Preserve all non-tooling entries and configurations; only known evaluator
    # assembly entries and their Debug/Release Any CPU mappings can differ.
    for guid, (_, name, _) in entries.items():
        if name not in tooling:
            continue
        pattern = r'(?m)^\s*'+re.escape(guid)+r'\.(Debug|Release)\|Any CPU\.(ActiveCfg|Build\.0) = \1\|Any CPU\s*\n'
        skeleton = re.sub(pattern, '', skeleton)
    # Unity can reorder otherwise identical game-project configurations. Only
    # standard self-mappings within this exact section are order independent.
    section = re.compile(r'(?m)^(\tGlobalSection\(ProjectConfigurationPlatforms\) = postSolution\n)(.*?)(\tEndGlobalSection\n)', re.S)
    mapping = re.compile(r'\t\t('+GUID+r')\.(Debug|Release)\|Any CPU\.(ActiveCfg|Build\.0) = (Debug|Release)\|Any CPU\n')
    def canonical(match):
        lines = match[2].splitlines(keepends=True)
        valid = []
        for line in lines:
            row = mapping.fullmatch(line)
            if row is None or row[1] not in entries or row[2] != row[4]:
                raise ValueError('Nonstandard IDE project configuration')
            valid.append(line)
        if len(set(valid)) != len(valid):
            raise ValueError('Duplicate IDE project configuration')
        return match[1]+''.join(sorted(valid))+match[3]
    skeleton = section.sub(canonical, skeleton)
    return entries, skeleton


def _legacy_proof(original, observed, relative):
    path = Path(relative)
    if len(path.parts) != 1:
        return None
    before = Path(original)/path; after = Path(observed)/path
    try:
        if path.name == 'Assembly-CSharp-Editor.csproj':
            a = before.read_text(encoding='utf-8-sig')
            b = after.read_text(encoding='utf-8-sig')
            compile_line = re.compile(r'(?m)^[ \t]*<Compile Include="(Assets/[^"<>]+\.cs)" />[ \t]*\n?')
            def strip_compile(text):
                return compile_line.sub('', text)
            if strip_compile(a) != strip_compile(b):
                return None
            before_compile = compile_line.findall(a)
            after_compile = compile_line.findall(b)
            removed = sorted(set(before_compile) - set(after_compile))
            added = sorted(set(after_compile) - set(before_compile))
            # Unity may regenerate the editor compile index when evaluator
            # asmdefs are installed. This proof allows only Compile Include
            # index churn; all XML outside those exact lines stays byte-identical
            # and gameplay source integrity is checked separately by prepare().
            if not set(removed) | set(added) <= TOOL_COMPILE_PATHS:
                return None
            if not removed and not added:
                return None
            return {'kind': 'unity_generated_ide_compile_index', 'path': relative,
                'before_sha256': sha(before), 'after_sha256': sha(after),
                'removed_compile_paths': removed, 'added_compile_paths': added,
                'policy': 'Only the known evaluator Compile Include index may differ; other project XML is unchanged, and gameplay source integrity is checked separately.'}
        if path.suffix != '.sln':
            return None
        left, a = _parse(before.read_text(encoding='utf-8-sig'))
        right, b = _parse(after.read_text(encoding='utf-8-sig'))
        keep = lambda entries: {k:v for k,v in entries.items() if v[1] not in TOOLING}
        if keep(left) != keep(right) or a != b:
            return None
        return {'kind': 'unity_generated_ide_solution', 'path': relative,
            'before_sha256': sha(before), 'after_sha256': sha(after),
            'tooling_assemblies_before': sorted(v[1] for v in left.values() if v[1] in TOOLING),
            'tooling_assemblies_after': sorted(v[1] for v in right.values() if v[1] in TOOLING),
            'unchanged_game_projects': sorted(v[1] for v in keep(left).values()),
            'policy': 'Only known recorder/Editor assembly entries and their IDE configurations differ; original solution remains frozen in judge input.'}
    except (OSError, ValueError, UnicodeError):
        return None


INPUT_PROJECTS = {'Unity.InputSystem', 'Unity.InputSystem.ForUI',
                  'Unity.InputSystem.TestFramework', 'Unity.InputSystem.DocCodeSamples',
                  'GameFactoryInputMigration'}
INPUT_REFERENCES = ('Unity.InputSystem', 'Unity.InputSystem.ForUI', 'GameFactoryInputMigration')


def input_migration_proof(original, observed, relative):
    """Exact generated IDE indexing for the separately verified native migration.

    No author Compile Include, source, assembly definition or runtime setting is
    permitted here. This only recognizes input define/index regeneration.
    """
    path=Path(relative)
    if len(path.parts)!=1 or path.is_absolute():return None
    before=Path(original)/path;after=Path(observed)/path
    if before.is_symlink() or after.is_symlink():return None
    try:
        a=before.read_bytes().decode('utf-8-sig');b=after.read_bytes().decode('utf-8-sig')
        if path.name in {'Assembly-CSharp.csproj','Assembly-CSharp-Editor.csproj'}:
            pattern=r'<DefineConstants>([^<>]+)</DefineConstants>'
            left=re.findall(pattern,a);right=re.findall(pattern,b)
            if len(left)!=1 or len(right)!=1:return None
            parts=left[0].split(';')
            if parts.count('ENABLE_LEGACY_INPUT_MANAGER')!=1 or 'ENABLE_INPUT_SYSTEM' in parts:return None
            expected=';'.join('ENABLE_INPUT_SYSTEM' if s=='ENABLE_LEGACY_INPUT_MANAGER' else s for s in parts)
            if right[0]!=expected:return None
            restored=b.replace('<DefineConstants>'+right[0]+'</DefineConstants>', '<DefineConstants>'+left[0]+'</DefineConstants>')
            for name in INPUT_REFERENCES:
                line='    <ProjectReference Include="'+name+'.csproj" />'
                if line in a:return None
                pattern=r'(?m)^'+re.escape(line)+r'\r?\n'
                if len(re.findall(pattern,restored))!=1:return None
                restored=re.sub(pattern,'',restored)
            if restored!=a:return None
            changes={'define_before':'ENABLE_LEGACY_INPUT_MANAGER','define_after':'ENABLE_INPUT_SYSTEM',
                     'added_project_references':list(INPUT_REFERENCES)}
        elif path.suffix=='.sln':
            tooling=TOOLING|INPUT_PROJECTS
            left,a0=_parse(a.replace('\r\n','\n'),tooling)
            right,b0=_parse(b.replace('\r\n','\n'),tooling)
            keep=lambda rows:{k:v for k,v in rows.items() if v[1] not in tooling}
            old_inputs={v[1] for v in left.values()}&INPUT_PROJECTS
            new_inputs={v[1] for v in right.values()}&INPUT_PROJECTS
            if old_inputs or not {'Unity.InputSystem','GameFactoryInputMigration'}<=new_inputs:return None
            if keep(left)!=keep(right) or a0!=b0:return None
            changes={'added_input_projects':sorted(new_inputs),'unchanged_game_projects':keep(left)}
        else:return None
        return {'kind':'unity_generated_input_ide_metadata','path':relative,
                'before_sha256':sha(before),'after_sha256':sha(after),'changes':changes,
                'scope':'Generated IDE index only; native source/settings require separate exact migration proof.'}
    except (OSError,ValueError,UnicodeError):return None


def proof(original, observed, relative):
    from .unity_m_input_adapter import generated_migration_metadata
    return (_legacy_proof(original,observed,relative)
            or input_migration_proof(original,observed,relative)
            or generated_migration_metadata(original,observed,relative))
