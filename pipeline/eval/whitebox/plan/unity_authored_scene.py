"""Exact Kimi G004 authored Tuanjie scene; no builder or scene generation."""
from pathlib import Path
import json
import re

from ..core import prepare
from ..core.llm import HarnessError
from ..core.paths import BENCH, read_json, sha256, write_json

VERSION = 'stage1-authored-tuanjie-scene.v1'
GAME = 'G004_desert_observatory'
SCENE = 'Assets/Scenes/Whitebox.scene'
SOURCE = BENCH / ('test_data/outputs/initial_game_gen/kimi-k3/' + GAME +
    '/gamefactory_G004_desert_observatory_20261018_193120/mechanic/' + GAME + '_whitebox/project')
SCOPE = BENCH / 'test_data/outputs/eval/whitebox/_playable_retest/engineering/kimi_all_20261109/full60_v1'
SELECTION_SHA = 'f05482b75078a1d4fe76481286adb7b4543d9ad6484abe837c9f1e8c2ac241cb'
SOURCE_MANIFEST_SHA = 'e12921d0a7bc21fff7f301cffc146d47f4386888c27cc413ea216959e71dfc25'
BOUND = {
    SCENE: '7cb74ebdff2f53b4959fd4e6379907d275847704fd248ab625c746208752d39a',
    SCENE + '.meta': 'ac657055f2acd6b1142f4b3f7aa8db466b27eb1d4b8e59a6721f7d84f88f991b',
    'ProjectSettings/EditorBuildSettings.asset': '4278461f65bceefdcbde5b3a3589fe0c32768bf165689ef1d0cc6c0fcc6831e3',
    'ProjectSettings/ProjectVersion.txt': 'add0609351955f044b19cd0883158510856e88ce16cae08997278e83f356505f',
}


def require(ok, message):
    if not ok:
        raise HarnessError(message)


def safe_file(root, relative):
    root, rel = Path(root).resolve(), Path(relative)
    require(not rel.is_absolute() and '..' not in rel.parts and rel.as_posix() == relative,
            'unsafe authored relative path')
    path = root / rel
    require(not any((root / Path(*rel.parts[:n])).is_symlink() for n in range(1, len(rel.parts) + 1)),
            'linked authored file/directory')
    require(path.is_file() and path.resolve().is_relative_to(root), 'missing authored file: ' + relative)
    return path


def context(out):
    out = Path(out).resolve()
    m = read_json(out / 'manifest.json')
    if m.get('game_id') != GAME or m.get('delivery', {}).get('model') != 'kimi':
        return None
    require(m.get('suite') == 'stage1' and m.get('engine') == 'unity3d'
            and m['delivery'].get('required_real_clients') == 1, 'wrong authored-scene identity')
    require(Path(m['project_source']).resolve() == SOURCE.resolve(), 'different original delivery')
    selection, source_manifest = SCOPE / 'selections/G004.json', SCOPE / 'source_manifests/G004.json'
    require(sha256(selection) == SELECTION_SHA and sha256(source_manifest) == SOURCE_MANIFEST_SHA,
            'frozen G004 selection/source manifest drift')
    selected = read_json(selection)
    require(Path(selected['target']['project']).resolve() == SOURCE.resolve()
            and selected['source_manifest']['sha256'] == SOURCE_MANIFEST_SHA, 'selection binding differs')
    full = read_json(source_manifest)
    for relative, digest in BOUND.items():
        require(full['files'].get(relative) == digest, 'source manifest entry differs')
        for project in (SOURCE, out / 'input/project'):
            require(sha256(safe_file(project, relative)) == digest, 'authored entry changed: ' + relative)
    return {'version': VERSION, 'entry_mode': 'authored_scene', 'engine_family': 'tuanjie',
            'requested_editor_version': '2022.3.62t13', 'launch_source': SCENE, 'launch_scene': SCENE,
            'scene_sha256': BOUND[SCENE], 'selection_sha256': SELECTION_SHA,
            'source_manifest_sha256': SOURCE_MANIFEST_SHA, 'builder_invoked': False}


def claim_plan(out, take):
    require(take in (1, 2), 'authored scene take limit exceeded')
    folder = Path(out) / 'authored_scene_plan_claims'
    folder.mkdir(exist_ok=True)
    with (folder / f'take{take}.json').open('x', encoding='utf-8') as stream:
        import json
        json.dump({'version': VERSION, 'take': take, 'max_model_calls': 1}, stream)


def validate_plan(out, executable):
    value = context(out)
    require(value is not None and executable.get('engine') == 'unity3d'
            and executable.get('launch_source') == SCENE and executable.get('launch_scene') == SCENE,
            'plan is not the source-bound authored .scene')
    return value


def verify_runtime(out, record_dir):
    """Permit only the formal device-read migration in authored Assets, never gameplay edits."""
    from .unity_input import migrate_device_reads
    out, record_dir = Path(out), Path(record_dir)
    migration = read_json(record_dir / 'unity_input_migration.json')
    changes = {r['path']: r for r in migration.get('changes', [])}
    require(migration.get('gameplay_changes') == [], 'input migration changed gameplay')
    assemblies = set()
    for rel in changes:
        source = safe_file(out / 'input/project', rel)
        require(source.suffix == '.cs', 'migration names a non-script')
        parent = source.parent
        while parent != out / 'input/project':
            definitions = list(parent.glob('*.asmdef'))
            if definitions:
                require(len(definitions) == 1, 'ambiguous authored assembly definition')
                assemblies.add(definitions[0].relative_to(out / 'input/project').as_posix())
                break
            parent = parent.parent
    for source in (out / 'input/project/Assets').rglob('*'):
        if not source.is_file():
            continue
        rel = source.relative_to(out / 'input/project').as_posix()
        actual = safe_file(out / 'runtime/project', rel)
        before = sha256(source)
        if sha256(actual) == before:
            require(rel not in changes, 'migration receipt contradicts unchanged source')
            continue
        if rel in assemblies:
            data = json.loads(source.read_text(encoding='utf-8'))
            refs = data.setdefault('references', [])
            require('GameFactoryInputMigration' not in refs, 'unexpected assembly rewrite')
            refs.append('GameFactoryInputMigration')
            require(actual.read_bytes() == (json.dumps(data, indent=2) + '\n').encode(),
                    'assembly changed beyond formal input shim reference')
            continue
        require(source.suffix == '.cs' and migration.get('migrated') is True, 'authored asset changed: ' + rel)
        transformed = migrate_device_reads(source.read_text(encoding='utf-8')).encode('utf-8')
        change = changes.get(rel, {})
        require(actual.read_bytes() == transformed and change.get('kind') == 'input_device_reads_only'
                and change.get('before_sha256') == before and change.get('after_sha256') == sha256(actual),
                'unreviewed authored code edit: ' + rel)
    for rel, digest in BOUND.items():
        require(sha256(safe_file(out / 'runtime/project', rel)) == digest, 'runtime entry changed')


def record_scene(project, executable, record_dir):
    project, record_dir = Path(project).resolve(), Path(record_dir).resolve()
    out = project.parent.parent
    value = validate_plan(out, executable)
    require(project == out / 'runtime/project' and record_dir.parent.parent == out / 'takes'
            and record_dir.name == 'record' and record_dir.parent.name in ('1', '2'), 'unexpected record location')
    choice = read_json(record_dir / 'unity_editor.json')
    # Keep ordinary choose() same-family/same-minor policy; never impose an exact-only editor gate.
    require(choice['delivery']['family'] == choice['editor']['family'] == 'tuanjie'
            and choice['delivery']['project_version'] == '2022.3.62t13'
            and re.fullmatch(r'2022\.3\.62t\d+', choice['editor']['version']) is not None
            and choice['version_gap'] == (choice['editor']['version'] != '2022.3.62t13'),
            'unbound Tuanjie editor choice')
    verify_runtime(out, record_dir)
    write_json(record_dir / 'authored_scene_entry.json', {
        **value, 'plan_sha256': sha256(record_dir.parent / 'plan.json'),
        'editor_choice_sha256': sha256(record_dir / 'unity_editor.json'),
        'requested_editor_version': '2022.3.62t13', 'actual_editor_version': choice['editor']['version'],
        'version_gap': choice['version_gap'], 'scene_argument': str(project / SCENE)})
    return SCENE
