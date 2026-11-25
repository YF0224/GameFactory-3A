"""Source-bound native component facts for planning, never gameplay credit."""
import json
from pathlib import Path

from . import batch
from .protocol import sha

VERSION = 'whitebox-native-scene-components.v1'
BINDING = 'native_entry_binding.json'


def load(root):
    root = Path(root)
    manifest = batch.read(root/'input_manifest.json')
    recovery = root/BINDING
    binding = batch.read(recovery) if recovery.exists() else manifest['entry'].get('native_open_admission')
    if not binding:
        return None
    path = Path(binding['receipt'])
    if sha(path) != binding['sha256']:
        raise ValueError('Native entry receipt SHA changed')
    receipt = batch.read(path)
    if receipt.get('opened_runtime_initializer'):
        from .unity_runtime_admission import frozen_facts
        return frozen_facts(root, manifest, binding, receipt)
    opened = receipt.get('opened_scene', {})
    if opened.get('inspection_version') != VERSION:
        # Legacy opening receipts do not establish component resolution.
        return None
    if (receipt.get('product_status') != 'OPENED' or opened.get('opened') is not True
            or receipt.get('execution', {}).get('exit_code') != 0
            or receipt.get('execution', {}).get('timed_out') is not False
            or receipt.get('execution', {}).get('owned_process_exited') is not True
            or receipt.get('source_unchanged', {}).get('ok') is not True
            or any(receipt.get('cleanup', {}).get(k) is not True
                   for k in ('input_cleanup', 'view_cleanup', 'process_cleanup'))):
        raise ValueError('Native component inspection has unverified execution/source/cleanup')
    expected = manifest['snapshot_hashes']
    if recovery.exists():
        snapshot = Path(receipt['source_snapshot'])
        if sha(snapshot) != binding['source_snapshot_sha256']:
            raise ValueError('Native entry snapshot receipt changed')
        source = batch.read(snapshot)
        if (Path(source['source']).resolve() != (root/'input/project').resolve()
                or source['files_sha256'] != expected):
            raise ValueError('Native entry inspection is for different frozen source')
    elif receipt.get('project_hashes') != expected:
        raise ValueError('Native component facts do not bind the frozen project')
    scene = opened['scene']
    if scene not in expected or binding.get('scene_sha256', expected[scene]) != expected[scene]:
        raise ValueError('Native entry scene does not bind the frozen input')
    if (type(opened.get('missing_script_count')) is not int or opened['missing_script_count'] < 0
            or not isinstance(opened.get('behaviours'), list)):
        raise ValueError('Native component inspection is incomplete')
    behaviours = []
    for row in opened['behaviours']:
        script = row.get('script_path', '')
        if script not in expected:
            # Package/helper components are not authored gameplay entry proof.
            continue
        behaviours.append({key:row[key] for key in
                           ('hierarchy','type','script_path','script_guid','enabled','active')})
        behaviours[-1]['source_sha256'] = expected[script]
    return {'receipt':str(path), 'receipt_sha256':sha(path), 'scene':scene,
            'scene_sha256':expected[scene], 'editor_version':opened['editor_version'],
            'missing_script_count':opened['missing_script_count'], 'behaviours':behaviours,
            'gameplay_executed':False}


def prompt_context(root):
    facts = load(root)
    if facts is None:
        return ''
    if facts.get('runtime_initializer_entry'):
        return ('\nVERIFIED NATURAL RUNTIME ENTRY (native startup diagnostic, not scoring evidence):\n'
                +json.dumps(facts,ensure_ascii=False,separators=(',', ':'))
                +'\nUnity naturally invoked the delivered AfterSceneLoad initializer in its own unsaved startup scene. '
                'For this explicitly admitted entry use launch_source=launch_scene='+facts['source']
                +'. This source path is a runtime-entry identifier, not a synthetic .unity scene. '
                'Derive physical inputs only from delivered gameplay source. Do not create a scene, attach components, '
                'invoke gameplay functions or infer success from this diagnostic. Real capture must establish behavior.\n')
    return ('\nVERIFIED NATIVE ENTRY FACTS (read-only Editor inspection, NOT gameplay evidence):\n'
            +json.dumps(facts, ensure_ascii=False, separators=(',', ':'))
            +'\nUse resolved component script_path/type to locate real input routes. '
            'Tuanjie may encode .meta GUIDs; textual GUID differences cannot negate native resolution. '
            'Scene opening/components do not establish playable state or rubric success. '
            'Static entry hypotheses may be stale; plan legal inputs for actual attached scripts, '
            'and let real capture establish behavior. Never attach scripts, rebuild scenes or invent actions.\n')


def audit_binding(root):
    """Keep the recovery/native facts auditable after recorded-judge packaging."""
    root=Path(root)
    provenance=root/'recorded_capture_provenance.json'
    recorded=Path(batch.read(provenance)['source_attempt']) if provenance.exists() else root
    if not (recorded/BINDING).exists():
        return {}
    from .unity_entry_recovery import RECEIPT, verify
    verify(recorded)
    facts=load(recorded)
    if facts is None:
        raise ValueError('Native entry recovery is missing component facts')
    recovery=batch.read(recorded/RECEIPT)
    source=Path(recovery['source_attempt'])
    native=Path(facts['receipt'])
    paths=[recorded/BINDING,recorded/RECEIPT,native,
           Path(batch.read(native)['source_snapshot']),source/'sol_plan.json',source/'input_manifest.json']
    paths.extend(source/name for name in recovery['copied_files_sha256'])
    return {str(path):sha(path) for path in paths}
