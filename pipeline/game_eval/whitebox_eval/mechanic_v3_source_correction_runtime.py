"""Complete-source correction using qualified native-format-aware preflight.

Preserve the original correction and every pending claim. Select the unchanged
native transport budget, follow explicit preflight generations, and validate the
full submitted source/frame/context packet before invoking any judge.
"""
from pathlib import Path
import argparse
import fcntl
import json

from . import mechanic_v3_source_correction as correction
from . import mechanic_v3_source_delivery as source
from . import mechanic_v3_source_admission as admission
from . import mechanic_v3_first_score as first
from . import mechanic_v3_execution as execution
from . import mechanic_v3_revision as revisions
from . import mechanic_v3_delivery_audit_v4 as audit
from .mechanic_v3_runner import read, exclusive_json, disk, configure_cli, stamp
from .protocol import sha, dump

VERSION = 'mechanic-source-correction-complete-preflight.v1'


def select_transport(root, task, protocol, manifest):
    """A wrong never-invoked native-JPEG claim gets an immutable continuation."""
    root = Path(root)
    name, parent, specs = source.selected_task(root, task)
    native, estimate = first.transport_budget(root, protocol, manifest, parent)
    claim = source.authorization(root, name)
    if claim is None:
        admission.authorize(root, name, parent, native_files=native)
        return (name, parent, specs), estimate
    image_claim = root/'engineering/judge_image_transport'/(name+'.json')
    if image_claim.exists() and not native:
        from .mechanic_v3_image_transport import NATIVE_VERSION
        value = read(image_claim)
        if value.get('version') == NATIVE_VERSION:
            if (root/'model_calls'/name).exists():
                raise ValueError('Attempted image delivery requires its diagnosed invocation recovery')
            folder = root/'engineering/source_correction_native_preflight'/name
            folder.mkdir(parents=True, exist_ok=True)
            repair = folder/'repair.json'
            files = [Path(__file__).resolve(), Path(first.__file__).resolve(), image_claim,
                     root/'runtime/frame_index.jsonl', root/'input_manifest.json',
                     root/'source_qualification.json', root/'evidence_manifest.json']
            record = dict(classification='NON_SCORING_SOURCE_PREFLIGHT',
                root_cause='Original native frames are not all JPEG or exceed the unchanged image cap; preserve pending JPEG-only admission and deliver every native frame in the existing full-resolution sheets.',
                no_model_invocation=True, previous_image_authorization=str(image_claim),
                native_files=False, estimated_bytes=estimate,
                scoring_semantics_unchanged=True, all_source_and_native_frames_preserved=True,
                before_snapshots={}, after_source_bindings={str(p.resolve()): sha(p) for p in files})
            if repair.exists():
                if read(repair) != record:
                    raise ValueError('Retained native preflight diagnosis changed')
            else:
                exclusive_json(repair, record)
            source.authorize_preflight(root, name, repair, native_files=False)
            return source.selected_task(root, task), estimate
    return (name, parent, specs), estimate


def prepare(workspace, identity):
    target, root = correction.prepare(workspace, identity)
    correction.verify_claim(read(correction.pointer(workspace, identity)))
    protocol = read(root/'input/pilot_rubric.json')
    manifest = read(root/'evidence_manifest.json')
    case = read(root/'input_manifest.json')['entry']['case_id']
    folder = revisions.contract_dir(target, case)
    contract, frozen = read(folder/'contract.json'), read(folder/'frozen.json')
    tasks = execution.partitions(protocol, manifest, prefix='mechanic_v3_of1_')
    selected = [select_transport(root, task, protocol, manifest) for task in tasks]
    disk(root, 'source_correction_complete_preflight', sum(size for _, size in selected))
    proofs = []
    for (name, parent, specs), _ in selected:
        subset, rules, images, schema, prompt = execution.request(
            root, protocol, manifest, contract, frozen, name, parent, specs)
        proof = first.validate_packet(root, manifest, parent, subset, prompt, images, name)
        proofs.append(dict(proof, task=name, parent=parent))
    receipt = dict(version=VERSION, identity=identity, root=str(root), tasks=proofs,
                   complete_sources=True, complete_native_frames=True,
                   original_claims_preserved=True, scoring_semantics_unchanged=True,
                   production_bindings={str(Path(__file__).resolve()): sha(Path(__file__))})
    path = root/'engineering/source_correction_complete_preflight.json'
    if path.exists() and read(path) != receipt:
        from . import mechanic_v3_empty_service_recovery as empty_service
        if not (root/empty_service.POINTER).exists():
            raise ValueError('Retained complete correction preflight changed')
        path=empty_service.continuation_preflight(root,receipt,path)
    if path.exists():
        if read(path) != receipt:
            raise ValueError('Retained complete correction preflight changed')
    else:
        exclusive_json(path, receipt)
    return target, root


def run(workspace, identity, *, prepare_only=False):
    workspace = Path(workspace).resolve()
    pointer = correction.pointer(workspace, identity)
    if pointer.exists():
        claim = correction.verify_claim(read(pointer))
        target = Path(claim['correction_workspace'])
        if (revisions.publication_dir(target)/(identity+'.json')).exists():
            checked = audit.publication(target, identity)
            if not checked['qualified']:
                raise ValueError('Retained correction requires separate diagnosed delivery recovery')
            return dict(identity=identity, status='SKIP_SCORED', audit=checked)
    target, root = prepare(workspace, identity)
    if prepare_only:
        return dict(identity=identity, status='PREPARED_NOT_SCORED', root=str(root))
    inventory = correction.scope.load(workspace)
    row = next(row for row in inventory['entries'] if row['entry']['id'] == identity)
    configure_cli(Path(row['source_batch']))
    result = execution.judge_and_publish(target, root, inventory)
    checked = audit.publication(target, identity)
    if not checked['qualified']:
        raise ValueError('Full correction delivery remains incomplete')
    claim = read(pointer)
    receipt = dict(version=VERSION, time=stamp(), status='ACCEPTED', score=result['score'],
                   original_publication=claim['original_publication'],
                   original_publication_sha256=claim['bindings'][claim['original_publication']],
                   correction_publication=checked['publication'],
                   correction_publication_sha256=checked['publication_sha256'], audit=checked,
                   complete_source_native_frames_and_runtime_metadata=True,
                   scoring_semantics_unchanged=True, original_claims_preserved=True,
                   production_bindings={str(Path(__file__).resolve()): sha(Path(__file__))})
    dest = root/'engineering/source_correction_complete_real_acceptance.json'
    if not dest.exists():
        exclusive_json(dest, receipt)
    return dict(identity=identity, status='SCORED_PENDING_AUDIT', score=result['score'],
                publication=checked['publication'], root=str(root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    locks = workspace/'locks'
    locks.mkdir(exist_ok=True)
    with (locks/('outcome_frame_v1_'+args.identity+'.lock')).open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run(workspace, args.identity, prepare_only=args.prepare_only)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
