"""Delivery contract: the only interface between generation and evaluation.

Whoever generates (our scripts_new/generate.py or an external agent driven by
the public prompt) must leave, in the run directory:

    <run_root>/delivery.json

with the fields below. ``validate`` is what scripts_new/intake.py runs.
"""
from __future__ import annotations

from pathlib import Path

from .paths import DELIVERY_FILE, DELIVERY_SCHEMA, MODEL_DIRS, SAMPLES, read_json, sha256

ENGINES = {'godot', 'three_js', 'unity3d', 'ue5'}
REQUIRED = {
    'schema': str,          # == DELIVERY_SCHEMA
    'stage': str,           # stage1 | stage3
    'model': str,           # short id: sol / astra / opus / glm / kimi
    'game_id': str,         # e.g. G008_dock_beacon_cs
    'run_id': str,          # == run directory name
    'engine': str,          # must match the case requirement
    'project_root': str,    # relative to run dir
    'entry': str,           # real author entry: scene / main script / index.html
    'created_at': str,      # ISO8601
    'generator': dict,      # {"kind": "bench_script" | "external_agent", "agent": "...", "framework_used": true}
}
STAGE3_REQUIRED = {
    'source': dict,         # {"path": original whitebox run, "sha256_manifest": "..."}
    'rounds_used': int,
}


def case_engine(game_id: str) -> str | None:
    req = SAMPLES / game_id / 'general_requirement.txt'
    if not req.is_file():
        return None
    for line in req.read_text(encoding='utf-8', errors='replace').splitlines():
        key, _, value = line.partition(':')
        if key.strip().lower() == 'engine':
            return value.strip().lower()
    return None


def _authored_engine_deviation(d: dict, expected: str, run_dir: Path) -> bool:
    """Source-bound opt-in for playable measurement of the delivered engine.

    This does not certify that the delivery satisfied its required engine. The
    ordinary generation/eight-metric validation still rejects the deviation.
    """
    try:
        v = d['engine_deviation']
        if (v['policy'] != 'authored_engine_playable_only.v1'
                or d['stage'] != 'stage1' or d.get('legacy') is not True
                or v['expected'] != expected or v['actual'] != d['engine']):
            return False
        selection_path = Path(v['selection_path'])
        if not selection_path.is_absolute() or sha256(selection_path) != v['selection_sha256']:
            return False
        selected = read_json(selection_path)
        t = selected['target']
        project = (run_dir / d['project_root']).resolve()
        if (selected['schema'] != 'kimi-original-selection.v1'
                or selected['status'] != 'SELECTED_ORIGINAL_PROJECT'
                or d['model'] != 'kimi' or t['model'] != 'Kimi'
                or any(t[k] != d[k] for k in ('game_id', 'engine', 'entry'))
                or Path(t['project']).resolve() != project
                or t['source'] != str(selection_path)):
            return False
        bound = selected['source_manifest']
        if sha256(Path(bound['path'])) != bound['sha256']:
            return False
        manifest = read_json(Path(bound['path']))
        entry = Path(d['entry'])
        if (entry.is_absolute() or '..' in entry.parts
                or Path(manifest['project']).resolve() != project
                or manifest.get('exclusions') != [] or manifest.get('symlinks')
                or sha256(project / entry) != manifest['files'][entry.as_posix()]):
            return False
        # Current formal and original requirements remain unmodified and equal.
        current = selected['requirements']['current']
        original = selected['requirements']['original_case_input']
        required = SAMPLES / d['game_id'] / 'general_requirement.txt'
        if (Path(current['path']).resolve() != required.resolve()
                or sha256(required) != current['sha256']
                or sha256(Path(original['path'])) != original['sha256']
                or original['sha256'] != current['sha256']):
            return False
        # The admitted actual-engine marker is authored, not a renamed requirement.
        if d['engine'] != 'godot' or entry.as_posix() != 'project.godot':
            return False
        return '[application]' in (project / entry).read_text(encoding='utf-8')
    except (KeyError, TypeError, ValueError, OSError):
        return False


def validate(run_dir: Path, *, playable_only: bool = False) -> list[str]:
    """Return a list of problems; empty means the delivery is admissible."""
    run_dir = Path(run_dir)
    path = run_dir / DELIVERY_FILE
    if not path.is_file():
        return [f'missing {DELIVERY_FILE}']
    try:
        d = read_json(path)
    except ValueError as e:
        return [f'{DELIVERY_FILE} is not valid JSON: {e}']
    errors = []
    fields = dict(REQUIRED, **(STAGE3_REQUIRED if d.get('stage') == 'stage3' else {}))
    for key, typ in fields.items():
        if not isinstance(d.get(key), typ):
            errors.append(f'field {key!r} missing or not {typ.__name__}')
    if errors:
        return errors
    if d['schema'] != DELIVERY_SCHEMA:
        errors.append(f'schema must be {DELIVERY_SCHEMA}')
    if d['stage'] not in ('stage1', 'stage3'):
        errors.append('stage must be stage1 or stage3')
    if d['model'] not in MODEL_DIRS:
        errors.append(f'model must be one of {sorted(MODEL_DIRS)}')
    if d['run_id'] != run_dir.name:
        errors.append(f'run_id {d["run_id"]!r} != directory name {run_dir.name!r}')
    if d['game_id'] != run_dir.parent.name:
        errors.append(f'game_id {d["game_id"]!r} != directory {run_dir.parent.name!r}')
    if d['engine'] not in ENGINES:
        errors.append(f'engine must be one of {sorted(ENGINES)}')
    expected = case_engine(d['game_id'])
    if (expected and expected.replace('-', '_') != d['engine']
            and not (playable_only and _authored_engine_deviation(d, expected.replace('-', '_'), run_dir))):
        errors.append(f'engine {d["engine"]!r} != case requirement {expected!r}')
    project = run_dir / d['project_root']
    if not project.is_dir():
        errors.append(f'project_root {d["project_root"]!r} does not exist')
    elif not (project / d['entry']).exists():
        errors.append(f'entry {d["entry"]!r} not found under project_root')
    return errors
