"""Bind G039's unchanged authored Editor callback to its recorded settings.

This describes the actually recorded input version, including its rendering
settings; it does not claim equivalence to the pre-import rendering.
"""
from pathlib import Path
from . import batch
from .protocol import sha

CASE = 'Astra__G039_sky_ring_flight'
SCRIPT = 'Assets/Editor/SkyProjectSettings.cs'
SCRIPT_SHA = '212f53a068ebb487433d8b14df33dec842a786de4e6616112940177b8599e76b'
SETTINGS = 'ProjectSettings/ProjectSettings.asset'
FIELD = 'authored_editor_settings_import'
# Each complete serialization replacement is justified by the pinned authored
# Configure method. The generated bundle identifier follows its exact names.
CHANGES = (
    ('  companyName: DefaultCompany\n', '  companyName: Sky Post Studio\n', 'PlayerSettings.companyName="Sky Post Studio"'),
    ('  productName: SkyRingFlight\n', '  productName: Sky Ring Courier\n', 'PlayerSettings.productName="Sky Ring Courier"'),
    ('  expectedBundleIdentifier: \n', '  expectedBundleIdentifier: com.Sky-Post-Studio.Sky-Ring-Courier\n', 'PlayerSettings.companyName="Sky Post Studio";PlayerSettings.productName="Sky Ring Courier"'),
    ('  defaultScreenWidth: 1920\n', '  defaultScreenWidth: 1280\n', 'PlayerSettings.defaultScreenWidth=1280'),
    ('  defaultScreenHeight: 1080\n', '  defaultScreenHeight: 720\n', 'PlayerSettings.defaultScreenHeight=720'),
    ('  m_ActiveColorSpace: 0\n', '  m_ActiveColorSpace: 1\n', 'PlayerSettings.colorSpace=ColorSpace.Linear'),
    ('  resizableWindow: 0\n', '  resizableWindow: 1\n', 'PlayerSettings.resizableWindow=true'),
    ('  fullscreenMode: 1\n', '  fullscreenMode: 3\n', 'PlayerSettings.fullScreenMode=FullScreenMode.Windowed'),
    ('  platformArchitecture: {}\n', '  platformArchitecture:\n    Standalone: 2\n', 'PlayerSettings.SetArchitecture(BuildTargetGroup.Standalone,2)'),
    ('  scriptingBackend: {}\n', '  scriptingBackend:\n    Standalone: 0\n', 'PlayerSettings.SetScriptingBackend(BuildTargetGroup.Standalone,ScriptingImplementation.Mono2x)'),
)


def prove_text(before, after, script):
    """Require exactly the authored assignments and losslessly invert all edits."""
    if '[InitializeOnLoad]' not in script or 'EditorApplication.delayCall+=Configure;' not in script:
        raise ValueError('Authored Editor load callback missing')
    actual = before
    rows = []
    for old, new, statement in CHANGES:
        if script.count(statement) != 1 or actual.count(old) != 1:
            raise ValueError('Authored settings assignment or serialization is ambiguous')
        rows.append({'before':old, 'recorded':new, 'author_statement':statement,
                     'source_line':script[:script.index(statement)].count('\n')+1,
                     'original_line':before[:before.index(old)].count('\n')+1,
                     'recorded_line':after[:after.index(new)].count('\n')+1 if new in after else None})
        actual = actual.replace(old,new,1)
    if actual != after:
        raise ValueError('Unreviewed recorded ProjectSettings change')
    inverse = after
    for old,new,_ in reversed(CHANGES):
        if inverse.count(new) != 1:
            raise ValueError('Authored settings inverse is ambiguous')
        inverse = inverse.replace(new,old,1)
    if inverse != before:
        raise ValueError('Authored settings round-trip differs')
    return rows


def proof(recorded):
    recorded = Path(recorded).resolve()
    manifest = batch.read(recorded/'input_manifest.json')
    frozen, captured = recorded/'input/project', recorded/'background_record/project'
    original, observed = frozen/SETTINGS, captured/SETTINGS
    if not (original.is_file() and observed.is_file()) or sha(original) == sha(observed):
        return []
    if manifest['entry']['id'] != CASE:
        return []
    snapshot_path = recorded/'background_record/source_snapshot.json'
    snapshot = batch.read(snapshot_path)
    selected = Path(manifest['entry']['project']).resolve()
    if Path(snapshot['source']).resolve() != selected:
        raise ValueError('Authored settings source snapshot differs')
    expected = manifest['snapshot_hashes']
    for relative in (SCRIPT,SETTINGS):
        if (sha(frozen/relative) != expected.get(relative)
                or sha(selected/relative) != expected.get(relative)
                or snapshot['files_sha256'].get(relative) != expected.get(relative)):
            raise ValueError('Authored settings frozen or selected source changed')
    if expected.get(SCRIPT) != SCRIPT_SHA or sha(captured/SCRIPT) != SCRIPT_SHA:
        raise ValueError('Authored Editor source changed')
    verification_path = recorded/'background_record/verification.json'
    verification = batch.read(verification_path)
    if (verification.get('fixture_only') is not False
            or any(verification.get('checks',{}).get(k) is not True for k in (
                'adapter_success','real_frames_present','all_events_delivered',
                'input_cleanup','view_cleanup','process_cleanup','original_unchanged'))):
        raise ValueError('Authored settings require qualified real capture and cleanup')
    rows = prove_text(original.read_text(),observed.read_text(),(frozen/SCRIPT).read_text())
    # read_text normalizes newlines; require byte-identical reversible UTF-8 too.
    before, after = original.read_bytes(), observed.read_bytes()
    if before.decode() != original.read_text() or after.decode() != observed.read_text():
        raise ValueError('Unreviewed settings encoding/newline normalization')
    return [{'kind':'authored_editor_configure_settings.v1','path':SETTINGS,
        'before_sha256':sha(original),'recorded_sha256':sha(observed),
        'recorded_attempt':str(recorded),'author_script':SCRIPT,'author_script_sha256':SCRIPT_SHA,
        'source_manifest_sha256':sha(recorded/'input_manifest.json'),
        'source_snapshot_sha256':sha(snapshot_path),
        'capture_verification_sha256':sha(verification_path),'changes':rows,
        'round_trip_byte_equal':True,'new_native_capture':False,
        'policy':'Judge the actual captured settings as an explicit derived input; retain source, frames, plan, settings, failures and scoring rules. No rendering equivalence claimed.'}]


def plan_paths(root, source, before, after):
    root = Path(root)
    version = batch.read(root/'input_manifest.json')['entry'].get('recorded_source_version',{})
    rows = version.get(FIELD,[])
    expected = proof(source)
    if rows != expected:
        raise ValueError('Recorded plan authored settings provenance changed')
    for row in rows:
        if (before.get(row['path']) != row['before_sha256']
                or after.get(row['path']) != row['recorded_sha256']
                or sha(root/'input/project'/row['path']) != row['recorded_sha256']):
            raise ValueError('Recorded plan authored settings bytes differ')
    return {row['path'] for row in rows}
