"""Source-bound repair of redundant pre-record references, never gameplay.

An empty probe target list can be recovered only from the same original plan's
explicit coverage references. Existing endpoint source paths/line ranges/reasons
stay unchanged; their SHA is derived from the immutable qualified source bytes.
The unchanged complete schema/native/capture validators must still pass.
"""
from pathlib import Path
import argparse
import copy
import fcntl
import json
from .protocol import checked_path, sha
from .mechanic_v3_runner import read, exclusive_json, stamp

VERSION = "mechanic-prerecord-reference-metadata.v1"
CLASSIFICATION = "NON_SCORING_PRERECORD_REFERENCE_METADATA"


def derive(operation, project, *, empty_probe_assignments=False, endpoint_source_shas=False):
    value=copy.deepcopy(operation);changes=[]
    if empty_probe_assignments:
        probes={p["id"]:p for p in value["probes"]}
        if len(probes)!=len(value["probes"]):raise ValueError("Duplicate original probe")
        coverage=value["coverage"]
        windows=([dict(v,atom_id=k) for k,v in coverage.items()] if isinstance(coverage,dict) else coverage)
        referenced={ident:[] for ident in probes}
        for window in windows:
            for ident in window["probe_ids"]:
                if ident not in probes:raise ValueError("Original coverage references unknown probe")
                if window["status"]!="PLANNED":raise ValueError("Unverified coverage cannot supply probe assignments")
                if window["atom_id"] not in referenced[ident]:referenced[ident].append(window["atom_id"])
        for ident,targets in referenced.items():
            before=probes[ident]["criterion_ids"]
            if not set(targets)<=set(before):
                if before:raise ValueError("Conflicting nonempty probe assignment needs independent planner correction")
                probes[ident]["criterion_ids"]=targets
                changes.append(dict(probe=ident,field="criterion_ids",before=[],after=targets,
                    basis="Only explicit references in this exact original coverage"))
    if endpoint_source_shas:
        for ident,endpoint in value["capture_plan"]["endpoints"].items():
            for index,reference in enumerate(endpoint["source_evidence"]):
                try:
                    path=checked_path(Path(project),reference["path"])
                except ValueError as error:
                    raise ValueError("Original endpoint source path is invalid") from error
                if not path.is_file():raise ValueError("Original endpoint source path is absent")
                if (not reference["reason"].strip() or not
                        1<=reference["line_start"]<=reference["line_end"]<=len(path.read_text().splitlines())):
                    raise ValueError("Original endpoint physical source reference is invalid")
                digest=sha(path)
                if digest!=reference["sha256"]:
                    changes.append(dict(endpoint=ident,reference=index,field="sha256",
                        before=reference["sha256"],after=digest,path=reference["path"],
                        line_start=reference["line_start"],line_end=reference["line_end"]))
                    reference["sha256"]=digest
    if not changes:raise ValueError("No diagnosed reference metadata changed")
    return value,changes


def apply(operation, repair_path, response_path, project):
    repair=read(repair_path)
    if (repair.get("classification")!=CLASSIFICATION or not repair.get("root_cause","").strip()
            or repair.get("response_sha256")!=sha(response_path)):
        raise ValueError("Reference repair diagnosis/parent response binding differs")
    return derive(operation,project,empty_probe_assignments=repair.get("empty_probe_assignments") is True,
        endpoint_source_shas=repair.get("endpoint_source_shas") is True)


def recover(workspace, identity):
    from . import mechanic_v3_full_scope as scope, mechanic_v3_prerecord_recovery as recovery
    from .mechanic_v3_plan_recovery import recording_started
    workspace=Path(workspace).resolve();inventory=scope.load(workspace)
    rows=[r for r in inventory["entries"] if r["entry"]["id"]==identity and r["in_scope"]]
    if len(rows)!=1:raise ValueError("Not one frozen original identity")
    row=rows[0];root=workspace/"runs"/identity
    if (root/recovery.CLAIM).exists():return recovery.verify(workspace,row)
    if recording_started(root) or (root/"sol_plan.json").exists():raise ValueError("Reference repair is pre-record only")
    failed=root/"model_calls/plan_v3_outcome_frame_v1";error=read(failed/"validation_error.json")
    if (error.get("response_sha256")!=sha(failed/"response.json")
            or (failed/"accepted_response.json").exists()):raise ValueError("Original failed response binding changed")
    kind=error.get("exception","")
    empty=kind=="core12 coverage is unrelated to its referenced probe"
    source=("endpoint must follow its actual last input" in kind or
        kind=="endpoint route/source evidence differs from frozen source")
    if not (empty or source):raise ValueError("Different failure needs its own diagnosis")
    path=workspace/"engineering/reference_metadata_repairs"/(identity+".json")
    diagnosis=dict(version=VERSION,classification=CLASSIFICATION,response_sha256=sha(failed/"response.json"),
        failure_sha256=sha(failed/"validation_error.json"),root_cause=kind,
        empty_probe_assignments=empty,endpoint_source_shas=source,
        original_response_preserved=True,gameplay_inputs_unchanged=True,
        implementation_bindings={str(Path(__file__).resolve()):sha(Path(__file__))})
    if path.exists():
        if read(path)!=diagnosis:raise ValueError("Preserved reference repair changed")
    else:exclusive_json(path,diagnosis)
    return recovery.recover_rejected(workspace,row,reference_repair=path)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--workspace",type=Path,required=True)
    parser.add_argument("--identity",required=True);args=parser.parse_args(argv);ws=args.workspace.resolve()
    path=ws/"locks"/("outcome_frame_v1_"+args.identity+".lock");path.parent.mkdir(exist_ok=True)
    with path.open("a+") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);root=recover(ws,args.identity)
    print(json.dumps(dict(identity=args.identity,stage="EXECUTABLE_NATIVE_PLAN",root=str(root),model_recalled=False)),flush=True)
    return 0

if __name__=="__main__":raise SystemExit(main())
