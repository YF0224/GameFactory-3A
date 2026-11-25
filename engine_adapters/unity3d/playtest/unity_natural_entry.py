"""Reviewed Stage1 contracts for three authored AfterSceneLoad entry points.

This module does not launch Unity, call a planner, create a scene, invoke an author
method, or qualify a score. Shared plan/record dispatch must opt in separately.
A saved contract is a source review, never proof that natural startup succeeded.
"""
from __future__ import annotations

from ..model_config import PLANNER_MODEL

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

from . import prepare
from .llm import HarnessError
from .paths import FRAMEWORK, read_json, sha256

VERSION = 'stage1-unity-natural-entry-contract.v1'
REL = Path('recovery/natural_entry_v1')
BENCH = FRAMEWORK.parent


@dataclass(frozen=True)
class Entry:
    project: str
    source: str
    source_sha256: str
    type: str
    method: str
    automation_source: str
    automation_sha256: str
    forbidden_argument: str


PROFILES = {
    'G039_sky_ring_flight': Entry(
        'G039_sky_ring_flight/gamefactory_G039_sky_ring_flight_20261016_220747/'
        'pipeline/G039_sky_ring_flight_whitebox/SkyRingFlight',
        'Assets/Assembly/SkyBootstrap.cs',
        'b0ab74b856d52cf22c2aec4dce16c427a85f273fd4d208b2ba955dce4f74b626',
        'SkyFlight.SkyBootstrap', 'Boot', 'Assets/Validation/FlightPlaytest.cs',
        'a43d27999becaa80d297301567cb8a4ce75e095986696ce2f4ee9120a3d22524', '--wb-output'),
    'G054_identity_trial': Entry(
        'G054_identity_trial/gamefactory_G054_identity_trial_20261017_081031/'
        'pipeline/G054_identity_trial_whitebox/project',
        'Assets/IdentityTrial/Scene/TrialHall.cs',
        '85880fdf7d322384fbe30cf6f00035b50a046b6e8505bcd2e1d66ec0bc29d7ec',
        'IdentityTrial.TrialHall', 'Bootstrap', 'Assets/IdentityTrial/Scene/TrialPlaytest.cs',
        '10cb800c307022e0571e96f8f6cb80f9aff789ba8ee234b98f19940cc4f136b9', '--g054-playtest'),
    'G059_observatory_pinball': Entry(
        'G059_observatory_pinball/gamefactory_G059_observatory_pinball_20261017_102834/'
        'pipeline/G059_observatory_pinball_whitebox/project',
        'Assets/Observatory/Presentation/ObservatoryView.cs',
        '37e1b75c6ca4144bddead331ef708258212f13699b33d966d0484e0d7ac000bb',
        'Observatory.ObservatoryView', 'Boot', 'Assets/Observatory/Validation/WhiteboxPlaytest.cs',
        'ba66d586eac659cc78b6b8f512ff1a4aef74511457724f87baa00cc61a2f1d68', '--whitebox-take'),
}


def require(condition, message):
    if not condition:
        raise HarnessError(message)


def reviewed(game_id):
    require(game_id in PROFILES, 'natural entry reviewed only for Astra G039/G054/G059')
    return PROFILES[game_id]


def resolve_target(game_id):
    """Use the parent's actual target table and runner path/client routing."""
    import sys
    scripts = str(BENCH / 'scripts_new')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import playable_retest as runner
    matches = [t for t in read_json(runner.TARGETS)['targets']
               if t['model'] == 'Astra' and t['game_id'] == game_id]
    require(len(matches) == 1, 'expected one frozen Astra target')
    target = matches[0]
    root = runner.BASE / 'stage1_playable_v1__plan-gpt-6-astra'
    return target, runner.result_dir(root, target).resolve()


def original_project(entry):
    return BENCH / 'test_data/outputs/initial_game_gen/gpt_astra6' / entry.project


def verify_reviewed_files(project, entry):
    project = Path(project)
    require((project / 'Assets').is_dir(), 'natural entry requires an authored Assets directory')
    require(not any(p.is_symlink() for p in (project / 'Assets').rglob('*'))
            and not (project / 'Assets').is_symlink(), 'symlinked author assets are not reviewed')
    require(not any((project / 'Assets').rglob('*.unity')), 'use the existing authored scene entry')
    for relative, expected in ((entry.source, entry.source_sha256),
                               (entry.automation_source, entry.automation_sha256)):
        path = project / relative
        require(path.is_file() and not path.is_symlink() and sha256(path) == expected,
                'reviewed entry or author automation source differs: ' + relative)


def review(out):
    """Return a deterministic source contract after checking frozen and original bytes.

    Read-only. Does not create a receipt or activate the optional entry contract.
    Library scenes are not authored scene entries; only Assets is inspected.
    The existing prepare digest still binds the complete frozen input inventory.
    """
    out = Path(out).resolve()
    manifest = prepare.verify(out)
    entry = reviewed(manifest['game_id'])
    target, expected_out = resolve_target(manifest['game_id'])
    require(target.get('required_real_clients', 1) == 1 and expected_out == out
            and target['engine'] == 'unity3d' and target['project'] == str(original_project(entry)),
            'natural entry requires the exact single-client target and runner result directory')
    require(manifest['engine'] == 'unity3d' and manifest['delivery']['model'] == 'astra'
            and manifest['models'] == {'planner': PLANNER_MODEL, 'judge': 'none'},
            'natural entry requires the reviewed Astra playable identity and model routing')
    original = Path(manifest['project_source'])
    require(original.is_absolute() and original == original_project(entry)
            and original.resolve() == original, 'natural entry original run/path differs')
    require(prepare.tree_digest(prepare.tree_hashes(original)) == manifest['project_digest'],
            'original project digest changed')
    for project in (original, out / 'input/project'):
        verify_reviewed_files(project, entry)
    return {
        'version': VERSION, 'out': str(out), 'game_id': manifest['game_id'],
        'manifest_sha256': sha256(out / 'manifest.json'),
        'project_source': str(original), 'project_digest': manifest['project_digest'],
        'snapshot_digest': manifest['snapshot_digest'],
        'entry_mode': 'runtime_initializer', 'launch_source': entry.source, 'launch_scene': '',
        'source_sha256': entry.source_sha256, 'type': entry.type, 'method': entry.method,
        'load_type': 'AfterSceneLoad', 'startup_scene': 'default_unsaved',
        'automation_source': entry.automation_source,
        'automation_sha256': entry.automation_sha256,
        'forbidden_argument': entry.forbidden_argument,
        'native_startup_observed': False,
    }


def context(out):
    """Optional exact source contract; absent means no C# fallback is authorized.

    Parent archives and bounded claims belong to the recovery dispatcher. This
    receipt alone never authorizes a model call or a native attempt.
    """
    path = Path(out) / REL / 'contract.json'
    if not path.is_file():
        return None
    expected = review(out)
    require(not path.is_symlink() and read_json(path) == expected,
            'natural entry contract differs from the frozen source review')
    return expected


def validate_plan(out, executable):
    value = context(out)
    require(value is not None, 'reviewed natural entry contract missing')
    require(executable.get('engine') == 'unity3d'
            and executable.get('launch_source') == value['launch_source']
            and executable.get('launch_scene') == '',
            'natural entry must use its exact original C# source and unsaved scene')
    return value


def verify_arguments(arguments):
    """Reject every reviewed author's automation switch, including --flag=value."""
    require(isinstance(arguments, (list, tuple)) and all(isinstance(x, str) for x in arguments),
            'native arguments must be an explicit token list')
    forbidden = {entry.forbidden_argument for entry in PROFILES.values()}
    require(all(token.split('=', 1)[0] not in forbidden for token in arguments),
            'author automation switch is forbidden for real player capture')


def verify_native_lifecycle(out, native):
    """Check the formal recorder's natural-startup proof, not overall qualification.

    Full runtime-copy provenance, accepted plan, duration, cleanup and evidence
    still require the recovery finalizer. This function cannot release a hold.
    """
    value = context(out)
    require(value is not None, 'reviewed natural entry contract missing')
    from engine_adapters.unity3d.playtest.runtime_initializer import verify_native
    binding = {'source': value['launch_source'], 'source_sha256': value['source_sha256'],
               'type': value['type'], 'method': value['method']}
    require(verify_native(binding, native), 'natural runtime lifecycle proof is invalid')
    return binding


RECORD_VERSION = 'stage1-unity-runtime-initializer-record-entry.v1'
RECORD_FIELDS = {'version', 'out', 'take', 'contract_sha256', 'manifest_sha256',
                 'plan_sha256', 'source', 'source_sha256', 'type', 'method',
                 'runtime_files_sha256', 'runtime_audit_sha256'}


def _inventory(project):
    """Content roots only; Unity caches are not source and never become entries."""
    project = Path(project)
    result = {}
    for name in ('Assets', 'Packages', 'ProjectSettings'):
        root = project / name
        require(root.is_dir() and not root.is_symlink(), 'missing or symlinked content root: ' + name)
        for path in sorted(root.rglob('*')):
            require(not path.is_symlink(), 'symlinked runtime content: ' + str(path))
            if path.is_file():
                result[str(path.relative_to(project))] = sha256(path)
    return result


def _verify_observer_installation(project, relative):
    """Accept only the adapter's exact observer ownership journal.

    The journal is generated by the official Unity recorder installer after its
    collision preflight. It is metadata for those seven fixed files, never an
    authorization for authored content or a project source change.
    """
    from engine_adapters.unity3d._internal.transport.unity_editor import playtest_recorder_files
    project = Path(project)
    journal = project / relative
    require(relative == 'Assets/GameFactory3AEvaluation/installation.json',
            'unexpected generated observer journal: ' + relative)
    value = read_json(journal)
    expected = {relative.as_posix(): sha256(source)
                for source, relative in playtest_recorder_files()}
    require(value == {'schema': 'unity-observer-installation.v1', 'files': expected},
            'generated observer installation journal differs from official files')
    for name, digest in expected.items():
        path = project / name
        require(path.is_file() and not path.is_symlink() and sha256(path) == digest,
                'generated observer file differs from installation journal: ' + name)
    return value


def _expected_runtime(out, record_dir):
    """Replay only the official input/observer transformations in a temporary copy.

    No Unity, model, author method or game is run here. The temporary copy is
    owned solely by this verification and removed on exit. Import serialization
    differences are not silently accepted; they require explicit review.
    """
    from . import unity_input
    from pipeline.game_eval.whitebox_eval import unity_runtime_dependencies
    out, record_dir = Path(out), Path(record_dir)
    editor = read_json(record_dir / 'unity_editor.json')['editor']['binary']
    actual_migration = read_json(record_dir / 'unity_input_migration.json')
    with tempfile.TemporaryDirectory(prefix='stage1-natural-entry-verify-') as temporary:
        root = Path(temporary)
        project = root / 'project'
        shutil.copytree(out / 'input/project', project, ignore=prepare.IGNORE)
        migration = unity_input.migrate(project, root / 'migration.json')
        # Project path is the sole location-dependent input-migration field.
        normalize = lambda value: {k: v for k, v in value.items() if k != 'project'}
        require(normalize(migration) == normalize(actual_migration),
                'input migration differs from deterministic official replay')
        observer = unity_runtime_dependencies.prepare(project, editor, root / 'observer.json')
        actual_observer = read_json(record_dir / 'observer_runtime_dependencies.json')
        # Existing takes may prepare an already Audio-enabled runtime copy.
        require(actual_observer['after_sha256'] == observer['after_sha256']
                and actual_observer['builtin_package_sha256'] == observer['builtin_package_sha256']
                and actual_observer['gameplay_changes'] == [],
                'observer dependency receipt differs from official replay')
        return _inventory(project)



def verify_generated_input_lock(out, record_dir):
    """Accept only resolver records forced by the proven harness Input System addition.

    No authored lock record may change. The local package and selected Editor's
    builtin metadata prove the exact two possible additions, including depth.
    This reads metadata only; it never resolves packages or rewrites the lock.
    """
    out, record_dir = Path(out), Path(record_dir)
    before_path = out / 'input/project/Packages/packages-lock.json'
    after_path = out / 'runtime/project/Packages/packages-lock.json'
    migration = read_json(record_dir / 'unity_input_migration.json')
    require(migration.get('migrated') is True
            and migration.get('input_system_package_origin') == 'harness_added',
            'unreviewed lock change without a harness-added input package')
    package = Path(migration['input_system_package'])
    package_manifest = package / 'package.json'
    require(package.is_absolute() and not package_manifest.is_symlink()
            and sha256(package_manifest) == migration['input_system_package_manifest_sha256'],
            'input package metadata changed')
    meta = read_json(package_manifest)
    input_name, ui_name = 'com.unity.inputsystem', 'com.unity.modules.uielements'
    require(meta.get('name') == input_name and meta.get('version') == '1.7.0'
            and meta.get('version') == migration['input_system_package_version']
            and meta.get('dependencies') == {ui_name: '1.0.0'}, 'unreviewed input dependency graph')
    editor = Path(read_json(record_dir / 'unity_editor.json')['editor']['binary'])
    builtin_path = editor.parent.parent / 'Resources/PackageManager/BuiltInPackages' / ui_name / 'package.json'
    builtin = read_json(builtin_path)
    require(not builtin_path.is_symlink() and builtin.get('name') == ui_name
            and builtin.get('version') == '1.0.0' and builtin.get('type') == 'module'
            and builtin.get('dependencies') == {'com.unity.modules.ui': '1.0.0',
                'com.unity.modules.imgui': '1.0.0', 'com.unity.modules.jsonserialize': '1.0.0'},
            'unreviewed builtin input dependency graph')
    before, after = read_json(before_path), read_json(after_path)
    require(set(before) == set(after) == {'dependencies'} and input_name not in before['dependencies'],
            'unreviewed authored lock record replacement')
    expected = dict(before['dependencies'])
    expected[input_name] = {'version': 'file:' + str(package), 'depth': 0,
                            'source': 'local', 'dependencies': meta['dependencies']}
    if ui_name not in expected:
        expected[ui_name] = {'version': '1.0.0', 'depth': 1, 'source': 'builtin',
                             'dependencies': builtin['dependencies']}
    for name in (ui_name, *builtin['dependencies']):
        row = expected.get(name, {})
        require(row.get('source') == 'builtin' and row.get('version') == '1.0.0',
                'unreviewed transitive input dependency: ' + name)
    require(after == {'dependencies': expected}
            and all(type(after['dependencies'][name].get('depth')) is int
                    for name in set(expected) - set(before['dependencies'])),
            'unreviewed package lock dependency changes')
    runtime_manifest = read_json(out / 'runtime/project/Packages/manifest.json')
    require(runtime_manifest['dependencies'].get(input_name) == 'file:' + str(package),
            'lock does not match the migrated input manifest')
    # Retain exact metadata bytes in the source audit, also after project cleanup.
    return {'version': 'stage1-unity-generated-input-lock.v1',
            'added': sorted(set(expected) - set(before['dependencies'])),
            'evidence': {str(path): {'sha256': sha256(path), 'text': path.read_text()}
                         for path in (before_path, after_path, package_manifest, builtin_path)}}


def verify_runtime(out, record_dir):
    """Verify the execution copy against original bytes and exact tool transforms."""
    from engine_adapters.unity3d._internal.transport.unity_editor import playtest_recorder_files
    out, record_dir = Path(out).resolve(), Path(record_dir).resolve()
    value = context(out)
    require(value is not None, 'natural entry source contract missing')
    project = out / 'runtime/project'
    expected = _expected_runtime(out, record_dir)
    current = _inventory(project)
    differences = [name for name, digest in expected.items() if current.get(name) != digest]
    if 'Packages/packages-lock.json' in differences:
        verify_generated_input_lock(out, record_dir)
        differences.remove('Packages/packages-lock.json')
    require(not differences, 'unreviewed runtime source/settings changes: ' + ', '.join(differences[:8]))
    instrumented = {relative.as_posix(): sha256(source) for source, relative in playtest_recorder_files()}
    for name in current.keys() - expected.keys():
        if name in instrumented:
            require(current[name] == instrumented[name], 'recorder instrumentation differs: ' + name)
        elif name.endswith('.meta') and name.startswith('Assets/'):
            # Unity may add metadata, but may not replace an authored .meta file.
            # This path is reached only for files absent from expected.
            target = project / name[:-5]
            require(target.exists(), 'orphan generated Unity metadata: ' + name)
        elif name == 'Assets/GameFactory3AEvaluation/installation.json':
            _verify_observer_installation(project, name)
        else:
            raise HarnessError('unreviewed runtime addition: ' + name)
    require(current.get(value['launch_source']) == value['source_sha256']
            and not any((project / 'Assets').rglob('*.unity')),
            'natural initializer source changed or a scene was created')
    return current


def record_binding(project, executable, record_dir):
    """Prepare the strict optional adapter binding; this does not record anything.

    Call only from the coordinated Unity dispatch after import. Native startup
    remains unproven until verify_native_lifecycle accepts the actual receipt.
    """
    from .paths import write_json
    project, record_dir = Path(project).resolve(), Path(record_dir).resolve()
    out = project.parent.parent
    value = validate_plan(out, executable)
    require(project == out / 'runtime/project', 'unexpected runtime project location')
    require(record_dir.parent.parent == out / 'takes' and record_dir.name == 'record'
            and record_dir.parent.name in ('1', '2'), 'unexpected natural record location/take')
    plan_path = record_dir.parent / 'plan.json'
    require(read_json(plan_path) == executable, 'recording plan differs from saved accepted plan')
    from .llm import accepted_response
    take = int(record_dir.parent.name)
    require(accepted_response(out / 'model_calls', f'plan_t{take}_natural_entry_v1') == executable,
            'natural recording requires the actual accepted corrected-contract plan')
    path = record_dir / 'runtime_initializer_entry.json'
    require(not path.exists(), 'natural binding already exists; inspect retained take, do not overwrite')
    inventory = verify_runtime(out, record_dir)
    audit = record_dir / 'runtime_entry_source_audit.json'
    require(not audit.exists(), 'runtime audit already exists')
    before_lock = out / 'input/project/Packages/packages-lock.json'
    after_lock = project / 'Packages/packages-lock.json'
    lock_proof = (verify_generated_input_lock(out, record_dir)
                  if before_lock.is_file() and after_lock.is_file()
                  and sha256(before_lock) != sha256(after_lock) else None)
    write_json(audit, {'version': RECORD_VERSION, 'project': str(project),
                      'contract_sha256': sha256(out / REL / 'contract.json'),
                      'generated_input_lock': lock_proof,
                      'runtime_files_sha256': inventory, 'native_startup_observed': False})
    binding = {'version': RECORD_VERSION, 'out': str(out), 'take': take,
               'contract_sha256': sha256(out / REL / 'contract.json'),
               'manifest_sha256': sha256(out / 'manifest.json'), 'plan_sha256': sha256(plan_path),
               'source': value['launch_source'], 'source_sha256': value['source_sha256'],
               'type': value['type'], 'method': value['method'],
               'runtime_files_sha256': inventory, 'runtime_audit_sha256': sha256(audit)}
    write_json(path, binding)
    return {'scene': '', 'runtime_entry': path}


def load_record_binding(path, project):
    """Stage1-only adapter branch. Legacy admission bindings stay separate."""
    path, project = Path(path).resolve(), Path(project).resolve()
    binding = read_json(path)
    require(isinstance(binding, dict) and set(binding) == RECORD_FIELDS
            and binding['version'] == RECORD_VERSION, 'unknown Stage1 runtime entry binding')
    out = Path(binding['out'])
    take = binding['take']
    require(type(take) is int and take in (1, 2) and out.is_absolute() and out.resolve() == out
            and project == out / 'runtime/project'
            and path == out / f'takes/{take}/record/runtime_initializer_entry.json',
            'runtime entry path/identity/take differs')
    value = context(out)
    require(value is not None, 'natural entry source contract missing')
    plan_path, audit_path = path.parent.parent / 'plan.json', path.parent / 'runtime_entry_source_audit.json'
    validate_plan(out, read_json(plan_path))
    from .llm import accepted_response
    require(accepted_response(out / 'model_calls', f'plan_t{take}_natural_entry_v1') == read_json(plan_path),
            'accepted corrected-contract plan differs')
    require(binding['contract_sha256'] == sha256(out / REL / 'contract.json')
            and binding['manifest_sha256'] == sha256(out / 'manifest.json')
            and binding['plan_sha256'] == sha256(plan_path)
            and binding['runtime_audit_sha256'] == sha256(audit_path),
            'runtime entry evidence binding changed')
    require(all(binding[k] == value['launch_source' if k == 'source' else k]
                for k in ('source', 'source_sha256', 'type', 'method')),
            'runtime entry method differs from reviewed original')
    inventory = verify_runtime(out, path.parent)
    require(inventory == binding['runtime_files_sha256']
            == read_json(audit_path)['runtime_files_sha256'], 'runtime bytes changed before adapter launch')
    return binding


def claim_plan(out, take):
    """The plan hook delegates bounded authorization to the recovery controller."""
    from ..repair.unity_natural_entry_recovery import claim_plan as claim
    return claim(out, take)
