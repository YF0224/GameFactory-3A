"""Opt-in first Mechanic score with complete source/window admission.

Uses the existing qualified native record, frozen contract, judgment, publication
and cache implementations. Retained failed invocations require explicit recovery;
this entry never starts an engine, changes an identity, or retries an old score.
"""
from pathlib import Path
from . import evaluation_model_profile as eval_models
import argparse
import fcntl
import hashlib
import json
from PIL import Image
from . import mechanic_v3_outcome_runner as outcome_runner
from . import mechanic_v3_execution as execution, mechanic_v3_revision as revisions
from . import mechanic_v3_outcome_evidence as evidence
from . import mechanic_v3_source_admission as admission, mechanic_v3_source_delivery as source
from . import mechanic_v3_delivery_audit_v4 as audit
from . import frame_budget, document_wire
from .state_packet import DESCRIPTION
from .protocol import sha, dump, load_lines, checked_path
from .action_links import frame_id
from .mechanic_v3_runner import read, stamp, disk, exclusive_json, configure_cli
from .codex import READ_ONLY_EVAL_INSTRUCTIONS

VERSION = 'mechanic-first-score-complete-delivery.v1'


def validate_packet(root, manifest, parent, selected, prompt, images, task):
    """Fail before a model request if source, decoder or native pixels are missing."""
    root = Path(root)
    from . import mechanic_v3_exact_evidence
    submitted_prompt = prompt
    prompt = mechanic_v3_exact_evidence.expanded(root, task, prompt)
    expected = {v['id']: v for v in manifest['items'] if v['type'] == 'source'}
    sources = {v['id']: v for v in selected['items'] if v['type'] == 'source'}
    if not sources or set(sources) != set(expected):
        raise ValueError('First score requires every author source')
    for ident, item in sources.items():
        path = checked_path(root, item['path'])
        if item != expected[ident] or sha(path) != item['sha256']:
            raise ValueError('First score source identity changed')
        full = '\nEVIDENCE '+ident+'\n'+''.join(
            f'{n}: {line}\n' for n, line in enumerate(path.read_text().splitlines(), 1))
        if full not in prompt and document_wire.section(path, ident) not in prompt:
            raise ValueError('First score source bytes are incomplete: '+ident)
    if ('\n'+DESCRIPTION+'\n' not in prompt or
            '\nSTATE CITATION WHITELIST (original raw line numbers, exhaustive):\n' not in prompt):
        raise ValueError('First score runtime decoder/whitelist missing')
    wanted = evidence.selected_ids(manifest, parent)
    subset = selected['evidence_sets'][parent]
    if set(subset['frames']) != wanted:
        raise ValueError('First score requires every predeclared native frame')
    indexed = {frame_id(row, index): row for index, row in enumerate(
        load_lines(root/'runtime/frame_index.jsonl'), 1)}
    submitted = [dict(path=str(Path(p).relative_to(root)), sha256=sha(Path(p))) for p in images]
    audit.native.validate_native_delivery(root, subset, indexed, wanted, submitted)
    actual = read(root/'requests'/task/'actual_delivery.json')
    if actual['prompt_sha256'] != hashlib.sha256((READ_ONLY_EVAL_INSTRUCTIONS+submitted_prompt).encode()).hexdigest():
        raise ValueError('Persisted actual-delivery prompt differs before first score')
    expected_images = [dict(path=str(Path(p).relative_to(root)), sha256=sha(Path(p))) for p in images]
    if actual['images'] != expected_images:
        raise ValueError('Persisted actual-delivery image list differs before first score')
    return dict(source_count=len(sources), frame_count=len(wanted), image_count=len(images),
                complete_sources=True, complete_native_frames=True, runtime_metadata=True)


def transport_budget(root, protocol, manifest, parent):
    """Choose original JPEG only when all frames fit the unchanged image limit."""
    root = Path(root)
    wanted = evidence.selected_ids(manifest, parent)
    if not wanted:
        raise ValueError('No qualified native frames for first score')
    frame_rows = load_lines(root/'runtime/frame_index.jsonl')
    indexed = {frame_id(row, index): row for index, row in enumerate(frame_rows, 1)}
    jpeg = True; sheet_bytes = 0; block = []
    for index, row in enumerate(frame_rows, 1):
        ident = frame_id(row, index)
        if ident not in wanted:continue
        path = checked_path(root/'runtime', row['path'])
        with Image.open(path) as image:
            jpeg = jpeg and image.format == 'JPEG'
            block.append(image.size)
        if len(block)==4:
            sheet_bytes += 4*max(w for w,_ in block)*(max(h for _,h in block)+26)*3
            block=[]
    if block:
        sheet_bytes += 4*max(w for w,_ in block)*(max(h for _,h in block)+26)*3
    subset = manifest['evidence_sets'][parent]
    refs = 0 if subset.get('include_references') is False else sum(
        v['type'] == 'reference' for v in manifest['items'])
    maximum = frame_budget.request_transport(protocol)['maximum_images']
    native = jpeg and len(wanted)+refs <= maximum
    count = len(wanted) if native else (len(wanted)+3)//4
    if count+refs > maximum:
        raise ValueError('Complete native windows exceed unchanged image limit; diagnosed transport recovery required')
    # Includes native-pixel sheet construction, its duplicate per-task views and requests.
    # Exact RGB allocation for every 2x2 evidence sheet, plus per-shard
    # duplicate-view/journal headroom; evidence preparation happens pre-judge.
    return native, sheet_bytes+512*1024**2


def prepare(workspace, identity, inventory):
    workspace = Path(workspace).resolve()
    root = outcome_runner.locate_qualified(workspace, identity)
    retained_admission = root/'engineering/first_score_complete_delivery.json'
    if retained_admission.exists():
        for name, digest in read(retained_admission)['bindings'].items():
            if sha(Path(name)) != digest:
                raise ValueError('Preserved first-score claim changed; explicit recovery required: '+name)
    if revisions.revision(workspace) != 'outcome_frame_v1':
        raise ValueError('First score requires explicit outcome revision')
    protocol = read(root/'input/pilot_rubric.json'); manifest = read(root/'evidence_manifest.json')
    entry = read(root/'input_manifest.json')['entry']
    if entry['id'] != identity:
        raise ValueError('Qualified record identity differs')
    folder = revisions.contract_dir(workspace, entry['case_id'])
    frozen = read(folder/'frozen.json'); contract = read(folder/'contract.json')
    if sha(folder/'contract.json') != frozen['contract_sha256']:
        raise ValueError('Frozen contract changed')
    for bindings in (read(folder/'source_binding.json')['bindings'],
                     read(root/'source_qualification.json')['source_bindings']):
        for name, digest in bindings.items():
            if sha(Path(name)) != digest:
                raise ValueError('Qualified original/contract binding changed: '+name)
    tasks = [source.selected_task(root, task) for task in
             execution.partitions(protocol, manifest, prefix=revisions.task_prefix(workspace))]
    # Check the whole case before writing any new admission claim.
    modes = {}
    for task, parent, _ in tasks:
        if (root/'model_calls'/task).exists():
            if not (root/'model_calls'/task/'accepted_response.json').exists():
                raise ValueError('Retained incomplete invocation requires diagnosed recovery')
            claim = source.authorization(root, task)
            if not claim or claim.get('first_delivery') is not True:
                raise ValueError('Retained invocation requires diagnosed recovery')
        modes[task] = transport_budget(root, protocol, manifest, parent)
    disk(root, 'first_score_complete_evidence', sum(v[1] for v in modes.values()))
    evidence.freeze(root, frozen['contract_sha256'])
    proofs = []
    for task, parent, specs in tasks:
        if not (root/'model_calls'/task).exists() and source.authorization(root,task) is None:
            admission.authorize(root, task, parent, native_files=modes[task][0])
        selected, rules, images, schema, prompt = execution.request(
            root, protocol, manifest, contract, frozen, task, parent, specs)
        context = read(root/'requests'/task/'context_binding.json')
        source_ids={item['id'] for item in manifest['items'] if item['type']=='source'}
        if any(item['id'] in source_ids for item in context['omitted_source_ranges']):
            raise ValueError('First score cannot omit source ranges')
        proof = validate_packet(root, manifest, parent, selected, prompt, images, task)
        proofs.append(dict(proof, task=task, parent=parent,
            selected_manifest_sha256=sha(root/'requests'/task/'selected_manifest.json')))
    path = root/'engineering/first_score_complete_delivery.json'
    bindings = {str(Path(p).resolve()): sha(Path(p)) for p in (
        __file__, evidence.__file__, frame_budget.__file__, admission.__file__,
        execution.__file__, source.__file__, root/'source_qualification.json', folder/'contract.json',
        root/evidence.POLICY_FILE)}
    receipt = dict(version=VERSION, identity=identity, root=str(root), bindings=bindings,
                   tasks=proofs, scoring_semantics_unchanged=True, model=eval_models.model_for(root,'judge'))
    if path.exists():
        old = read(path)
        if old.get('identity') != identity or old.get('root') != str(root) or old.get('bindings') != bindings or old.get('tasks') != proofs:
            raise ValueError('First-score admission changed; preserve claim and diagnose')
        receipt = old
    else:
        exclusive_json(path, receipt)
    return root


def run(workspace, identity, inventory, *, prepare_only=False):
    workspace = Path(workspace)
    pub = revisions.publication_dir(workspace)/(identity+'.json')
    if pub.exists():
        checked = audit.publication(workspace, identity)
        if not checked['qualified']:
            raise ValueError('Existing publication needs explicit delivery recovery, not first-score retry')
        return dict(identity=identity, status='SKIP_SCORED', score=checked['mechanic_score'])
    root = prepare(workspace, identity, inventory)
    if prepare_only:
        return dict(identity=identity, status='PREPARED_NOT_SCORED', root=str(root))
    result = execution.judge_and_publish(workspace, root, inventory)
    checked = audit.publication(workspace, identity)
    if not checked['qualified']:
        raise ValueError('Published delivery failed complete-source/native-frame qualification')
    dest = root/'engineering/first_score_real_delivery_acceptance.json'
    receipt = dict(version=VERSION, status='ACCEPTED', time=stamp(), audit=checked,
                   complete_judgment=True, score=result['score'], real_record_source=str(root),
                   scoring_semantics_unchanged=True)
    if not dest.exists():
        exclusive_json(dest, receipt)
    return dict(identity=identity, status='SCORED_PENDING_AUDIT', score=result['score'], root=str(root))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args(argv); workspace = args.workspace.resolve()
    from .mechanic_v3_scope import load_inventory, allowed_identities
    inventory = load_inventory(workspace)
    if args.identity not in allowed_identities(inventory, 'judge'):
        raise ValueError('Not a frozen identity')
    entry = next(r for r in inventory['entries'] if r['entry']['id'] == args.identity)
    configure_cli(Path(entry['source_batch']))
    lockdir = workspace/'locks'; lockdir.mkdir(exist_ok=True)
    with (lockdir/('outcome_frame_v1_'+args.identity+'.lock')).open('a+') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX|fcntl.LOCK_NB)
        result = run(workspace, args.identity, inventory, prepare_only=args.prepare_only)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
