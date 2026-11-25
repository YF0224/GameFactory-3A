"""Opt-in, SHA-bound UE compile compatibility, retaining the authored source.

A reviewed plan is supplied by the queue with its SHA256. Native admission still
requires an exact independent source copy: its effective reference is derived
from the frozen author snapshot by ONLY the listed compile/config patches.
Both that derivation and the author snapshot remain available to the audit.
No code generation, model requests, builds, scoring or deletion occurs here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

from ..stage1.llm import HarnessError
from ..stage1.paths import read_json, write_json

VERSION = "stage3-ue-compile-compat.v1"
ENV = "A3GAME_UE_COMPILE_COMPAT_PLAN"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def selection(out):
    value = os.environ.get(ENV)
    if not value:
        return None
    path = Path(value).resolve(strict=True)
    expected = os.environ.get(ENV + "_SHA256", "")
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if len(expected) != 64 or actual != expected:
        raise HarnessError("UE compile compatibility plan SHA mismatch")
    plan = json.loads(raw)
    if plan.get("version") != VERSION:
        raise HarnessError("Unknown UE compile compatibility plan")
    entry = plan.get("entries", {}).get(str(Path(out).resolve()))
    if entry is None:
        return None
    return {"path": str(path), "sha256": actual, "entry": entry}


# Stage1 opt-in is a separate, user-authorized Sol13 repair experiment.  It
# does not change Stage3 eligibility or any authored input / scoring rule.
STAGE1_AUTHORIZATION = "stage1-sol-init-ue54-compat.v1"
STAGE1_ROOT = Path(__file__).resolve().parents[3] / "workspaces/init_game_playable_audit_20261115/ue54_compat"
STAGE1_CASES = frozenset(("G003", "G008", "G020", "G025", "G030", "G035", "G055", "G060"))


def _validate_identity(out, manifest, entry):
    if manifest.get("engine") != "ue5":
        raise HarnessError("Compile compatibility requires a UE identity")
    if manifest.get("suite") == "stage3":
        return 20 * 2**30
    if manifest.get("suite") != "stage1":
        raise HarnessError("Compile compatibility requires an explicitly authorized suite")
    binding = entry.get("stage1_authorization", {})
    path = Path(binding.get("path", "/missing-stage1-authorization"))
    if not path.is_file() or digest(path) != binding.get("sha256"):
        raise HarnessError("Stage1 UE54 repair authorization missing or changed")
    auth = read_json(path)
    out = Path(out).resolve()
    case = manifest.get("game_id", "")[:4]
    allowed = STAGE1_ROOT.resolve()
    if (auth.get("version") != STAGE1_AUTHORIZATION
            or auth.get("user_instruction") != "剩下几个都动态编译成ue5.4启动一下"
            or case not in STAGE1_CASES or case not in auth.get("cases", [])
            or not out.is_relative_to(allowed)
            or str(out) not in auth.get("evaluation_directories", [])
            or manifest.get("delivery", {}).get("model") != "sol"
            or entry.get("snapshot_digest") != manifest.get("snapshot_digest")
            or auth.get("source_bindings", {}).get(case) != manifest.get("project_source")
            or auth.get("source_digests", {}).get(case) != manifest.get("project_digest")
            or auth.get("target_engine") != "5.4"
            or auth.get("reserve_bytes") != 8 * 2**30):
        raise HarnessError("Stage1 UE54 repair identity/authorization mismatch")
    parent = entry.get("parent_failure", {})
    parent_path = Path(parent.get("path", "/missing-parent-failure"))
    if not parent_path.is_file() or digest(parent_path) != parent.get("sha256"):
        raise HarnessError("Stage1 UE54 repair parent failure missing or changed")
    return auth["reserve_bytes"]


def _relative(value):
    p = Path(value)
    if p.is_absolute() or not p.parts or any(x in ("..", ".") for x in p.parts):
        raise HarnessError("Unsafe UE compile patch path: " + str(value))
    if p.parts[0] not in ("Source", "Plugins", "Config") and p.suffix != ".uproject":
        raise HarnessError("UE compile patch outside source/config: " + str(value))
    if any(x in p.parts for x in ("A3GamePlayable", "Intermediate", "Binaries", "Content")):
        raise HarnessError("UE compile patch cannot touch recorder, cache or assets")
    if p.suffix not in (".cpp", ".h", ".cs", ".ini", ".uproject", ".uplugin"):
        raise HarnessError("UE compile patch is not a code/config file")
    return p


def prepare(out, project, selected):
    """Return (effective_validation_source, provenance), or unchanged input by default."""
    out, project = Path(out).resolve(), Path(project).resolve()
    source = out / "input" / "project"
    if project != out / "runtime" / "project":
        raise HarnessError("Compile compatibility may only modify this evaluation runtime/project")
    if selected is None:
        return source, None
    from ..stage1 import prepare as frozen
    from engine_adapters.ue5.playtest.native_admission import source_manifest
    manifest = frozen.verify(out)
    entry = selected["entry"]
    reserve_bytes = _validate_identity(out, manifest, entry)
    if manifest["snapshot_digest"] != entry["snapshot_digest"]:
        raise HarnessError("UE compile patch is bound to a different frozen snapshot")
    if not entry.get("parent_failure") or not entry.get("reviewed_changes"):
        raise HarnessError("UE compile patch needs its parent failure and reviewed scope")
    original = source_manifest(source)
    _recover_interrupted(out, project, selected, original)
    if source_manifest(project) != original:
        raise HarnessError("Runtime must match frozen authored input before compile compatibility")
    patches, expected, seen = [], dict(original), set()
    for item in entry["files"]:
        rel, target = _relative(item["from"]), _relative(item.get("to", item["from"]))
        if str(rel) in seen or str(target) in seen:
            raise HarnessError("Overlapping UE compile patch paths")
        seen.update((str(rel), str(target)))
        if item.get("kind") not in ("config", "compile_compat"):
            raise HarnessError("UE compile patch is not reviewed config/compatibility")
        if original.get(str(rel)) != item["before_sha256"]:
            raise HarnessError("UE compile patch original SHA mismatch: " + str(rel))
        if rel != target and (not rel.name.endswith(".Target.cs") or target != Path("Source") / rel.name
                              or str(target) in original):
            raise HarnessError("Only non-destructive Target.cs relocation to Source/ is allowed")
        overlay = Path(selected["path"]).parent / item["overlay"]
        if overlay.is_symlink() or not overlay.resolve().is_relative_to(Path(selected["path"]).parent):
            raise HarnessError("UE compile overlay must be an independent local file")
        data = overlay.read_bytes()
        if hashlib.sha256(data).hexdigest() != item["after_sha256"]:
            raise HarnessError("UE compile overlay SHA mismatch: " + str(rel))
        if digest(source / rel) != item["before_sha256"]:
            raise HarnessError("Frozen UE input changed during preparation")
        expected.pop(str(rel))
        expected[str(target)] = item["after_sha256"]
        patches.append((rel, target, data, item))
    if not patches:
        raise HarnessError("Empty UE compile compatibility plan")
    repair = out / "runtime" / "launch_repair" / ("ue_compat_" + selected["sha256"][:20])
    reference = repair / "validation_source"
    reference_receipt = repair / "reference.json"
    if reference.exists():
        if not reference_receipt.is_file() or source_manifest(reference) != expected:
            raise HarnessError("Incomplete/drifted compile reference; preserve it for diagnosis")
    else:
        size = sum(p.stat().st_size for p in source.rglob("*") if p.is_file())
        if shutil.disk_usage(out).free < reserve_bytes + size:
            raise HarnessError("Compile reference creation would violate the authorized disk reserve")
        repair.mkdir(parents=True, exist_ok=True)
        _transaction(out, selected, "reference_build")
        shutil.copytree(source, reference, ignore=frozen.IGNORE)
        for rel, target, data, item in patches:
            backup = repair / "backup" / rel
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, backup)
            if rel != target:
                (reference / rel).rename(reference / target)
            (reference / target).write_bytes(data)
        if source_manifest(reference) != expected or source_manifest(source) != original:
            raise HarnessError("Compile reference changed files beyond its allowlisted patch set")
        write_json(reference_receipt, {"version": VERSION, "plan_sha256": selected["sha256"],
                                     "source": str(source), "reference": str(reference),
                                     "authored_files": original, "effective_files": expected})
    # All validation is complete before changing runtime. Keep each old file in backup.
    for rel, target, data, item in patches:
        old = project / rel
        if old.is_symlink() or old.stat().st_nlink > 1 or old.samefile(source / rel):
            raise HarnessError("Runtime compile target must be an independent regular file")
    _transaction(out, selected, "applying")
    for rel, target, data, item in patches:
        if rel != target:
            (project / rel).rename(project / target)
        (project / target).write_bytes(data)
    if source_manifest(project) != expected or source_manifest(source) != original:
        raise HarnessError("Runtime compile compatibility failed exact manifest validation")
    receipt = {"version": VERSION, "applied": True, "accepted": True,
               "plan": selected["path"], "plan_sha256": selected["sha256"],
               "original_source": str(source), "effective_validation_source": str(reference),
               "snapshot_digest": manifest["snapshot_digest"], "parent_failure": entry["parent_failure"],
               "reviewed_changes": entry["reviewed_changes"], "files": entry["files"],
               "reference_receipt": str(reference_receipt),
               "reference_receipt_sha256": digest(reference_receipt),
               "note": "compile/config compatibility only; original input retained unchanged"}
    write_json(repair / "receipt.json", receipt)
    _transaction(out, selected, "applied")
    return reference, receipt


def _transaction(out, selected, state):
    write_json(Path(out) / "runtime" / "ue_compile_compat_transaction.json",
               {"version": VERSION, "plan_sha256": selected["sha256"],
                "eval_dir": str(Path(out).resolve()), "snapshot_digest": selected["entry"]["snapshot_digest"],
                "state": state})


def _archive(path, reason):
    n = 1
    while path.with_name(path.name + "_interrupted_%03d" % n).exists():
        n += 1
    target = path.with_name(path.name + "_interrupted_%03d" % n)
    path.rename(target)
    write_json(target / "interruption.json", reason)
    return target


def _recover_interrupted(out, project, selected, original):
    """Recover only our journalled partial apply; retain every interrupted byte."""
    from ..stage1.prepare import IGNORE
    from engine_adapters.ue5.playtest.native_admission import source_manifest
    journal = out / "runtime" / "ue_compile_compat_transaction.json"
    if not journal.is_file():
        return
    state = read_json(journal)
    if (state.get("version") != VERSION or state.get("eval_dir") != str(out)
            or state.get("snapshot_digest") != selected["entry"]["snapshot_digest"]
            or state.get("plan_sha256") != selected["sha256"]):
        raise HarnessError("Compile transaction identity changed; preserve for diagnosis")
    if state.get("state") == "admitted":
        return
    if state.get("state") not in ("reference_build", "applying", "applied"):
        raise HarnessError("Unknown compile compatibility transaction state")
    if (out / "runtime" / "ue_admission").exists():
        raise HarnessError("Archive unfinished native admission before compile recovery")
    if not project.exists() or source_manifest(project) != original:
        if project.exists():
            _archive(project, state)
        shutil.copytree(out / "input" / "project", project, ignore=IGNORE)
    repair = out / "runtime" / "launch_repair" / ("ue_compat_" + selected["sha256"][:20])
    if state["state"] == "reference_build" and repair.exists() and not (repair / "reference.json").is_file():
        _archive(repair, state)
    # Keep the transaction until reference and runtime have both been verified.


def validate_receipt(out, receipt, selected=None):
    """Verify the frozen input, pinned plan, receipt and independent reference."""
    from ..stage1 import prepare as frozen
    from engine_adapters.ue5.playtest.native_admission import source_manifest
    out = Path(out).resolve()
    try:
        path = Path(receipt["plan"]).resolve(strict=True)
        raw = path.read_bytes()
        plan_sha = hashlib.sha256(raw).hexdigest()
        plan = json.loads(raw)
        entry = plan["entries"][str(out)]
        if plan.get("version") != VERSION or plan_sha != receipt["plan_sha256"]:
            raise ValueError("plan version/SHA mismatch")
        if selected is not None and (selected["sha256"] != plan_sha or selected["entry"] != entry):
            raise ValueError("requested compatibility selection changed")
        manifest = frozen.verify(out)
        source = out / "input" / "project"
        original = source_manifest(source)
        _validate_identity(out, manifest, entry)
        if manifest["snapshot_digest"] != entry["snapshot_digest"] or receipt["snapshot_digest"] != entry["snapshot_digest"]:
            raise ValueError("original snapshot mismatch")
        for key in ("files", "parent_failure", "reviewed_changes"):
            if receipt[key] != entry[key] or not entry[key]:
                raise ValueError("reviewed compatibility scope mismatch: " + key)
        expected = dict(original)
        for item in entry["files"]:
            rel, target = _relative(item["from"]), _relative(item.get("to", item["from"]))
            if expected.pop(str(rel)) != item["before_sha256"]:
                raise ValueError("original patch file SHA mismatch")
            overlay = path.parent / item["overlay"]
            if overlay.is_symlink() or not overlay.resolve().is_relative_to(path.parent) or digest(overlay) != item["after_sha256"]:
                raise ValueError("reviewed overlay changed")
            expected[str(target)] = item["after_sha256"]
        repair = out / "runtime" / "launch_repair" / ("ue_compat_" + plan_sha[:20])
        reference = repair / "validation_source"
        ref_receipt = repair / "reference.json"
        if receipt.get("version") != VERSION or receipt.get("applied") is not True or receipt.get("accepted") is not True:
            raise ValueError("compatibility was not accepted")
        if receipt["original_source"] != str(source) or receipt["effective_validation_source"] != str(reference):
            raise ValueError("compatibility reference path changed")
        if receipt["reference_receipt"] != str(ref_receipt) or digest(ref_receipt) != receipt["reference_receipt_sha256"]:
            raise ValueError("reference receipt SHA mismatch")
        ref = read_json(ref_receipt)
        if ref != {"version": VERSION, "plan_sha256": plan_sha, "source": str(source),
                   "reference": str(reference), "authored_files": original, "effective_files": expected}:
            raise ValueError("reference manifest provenance mismatch")
        if source_manifest(reference) != expected:
            raise ValueError("effective reference files changed")
        for rel in expected:
            p = reference / rel
            if p.is_symlink() or p.stat().st_nlink != 1 or (source / rel).exists() and p.samefile(source / rel):
                raise ValueError("effective reference must be an independent copy")
        receipt_path = repair / "receipt.json"
        if read_json(receipt_path) != receipt:
            raise ValueError("compatibility receipt missing/changed")
        return {"receipt": str(receipt_path), "receipt_sha256": digest(receipt_path), "plan_sha256": plan_sha}
    except (KeyError, ValueError, OSError, RuntimeError) as exc:
        raise HarnessError("UE compile compatibility provenance invalid: " + str(exc)) from exc


def mark_admitted(out, selected):
    if selected is not None:
        _transaction(Path(out).resolve(), selected, "admitted")


def bind_record(out, record, admitted):
    """Persist the admission used by THIS take before starting native recording."""
    receipt = (admitted or {}).get("compile_compatibility")
    if receipt is None:
        return None
    marker = validate_receipt(out, receipt)
    bound = Path(record) / "ue_admission_bound.json"
    if bound.exists():
        raise HarnessError("Take already has an admission binding; preserve before retry")
    write_json(bound, admitted)
    marker.update(version=VERSION, admission_sha256=digest(bound))
    write_json(Path(record) / "launch_repair_binding.json", marker)
    return marker


def validate_record(out, record, result):
    """Never substitute the current admission for a historical recording."""
    record = Path(record)
    marker = result.get("compile_compatibility")
    binding = record / "launch_repair_binding.json"
    if marker is None:
        if binding.exists() or selection(out) is not None:
            raise HarnessError("Recorded take is missing its compile compatibility provenance")
        return None
    try:
        if read_json(binding) != marker:
            raise ValueError("take compatibility binding changed")
        bound = record / "ue_admission_bound.json"
        if digest(bound) != marker["admission_sha256"]:
            raise ValueError("take admission snapshot SHA changed")
        admitted = read_json(bound)
        provenance = validate_receipt(out, admitted["compile_compatibility"])
        if any(marker[k] != v for k, v in provenance.items()):
            raise ValueError("take compatibility receipt changed")
        return marker
    except (KeyError, ValueError, OSError) as exc:
        raise HarnessError("Recorded compile compatibility provenance invalid: " + str(exc)) from exc


def score_provenance(out):
    out = Path(out).resolve()
    records = out / "takes"
    # Do not impose new provenance requirements on unrelated historical runs.
    active = (selection(out) is not None
              or (out / "runtime/ue_compile_compat_transaction.json").is_file()
              or any(records.glob("*/record/launch_repair_binding.json")))
    if not active:
        return None
    # A binding is written before recording starts; failed optional takes retain it.
    # Only takes actually supplying judgments/results belong to score provenance.
    required = set()
    # A missing record result cannot make a take that supplied judgment disappear.
    for verdict in out.glob("verdicts_evidence_*.json"):
        match = re.fullmatch(r"verdicts_evidence_[tds](\d+)\.json", verdict.name)
        if match is None or int(match[1]) == 0:
            continue
        evidence = out / ("evidence_t" + match[1] + ".json")
        if not evidence.is_file():
            raise HarnessError("Judged repaired take is missing evidence manifest: " + str(evidence))
        takes = read_json(evidence).get("takes")
        if not isinstance(takes, list) or not takes or any(type(t) is not int or t < 1 for t in takes):
            raise HarnessError("Invalid take set in repaired judgment evidence: " + str(evidence))
        required.update(map(str, takes))
    for name in ("direct_trigger.json", "state_conditioned.json", "takes.json"):
        path = out / name
        if path.is_file():
            book = read_json(path)
            for take in book.get("takes", book.get("history", [])):
                if take.get("calls_result") or take.get("verdicts"):
                    required.add(str(take["take"]))
    entries = []
    for take in sorted(required):
        record = records / take / "record"
        result_path = record / "record_result.json"
        if not result_path.is_file():
            raise HarnessError("Scored repaired take is missing record_result.json: " + str(result_path))
        marker = validate_record(out, record, read_json(result_path))
        if marker is None:
            raise HarnessError("Scored repaired take is missing compatibility provenance: " + take)
        entries.append({"take": take, **marker})
    return {"version": VERSION, "takes": entries} if entries else None


def begin_rebuild(out, selected, archive):
    out = Path(out).resolve()
    journal = out / "runtime/ue_compile_compat_transaction.json"
    previous = None
    if journal.is_file():
        raw = journal.read_bytes()
        state = json.loads(raw)
        if (state.get("version") != VERSION or state.get("eval_dir") != str(out)
                or state.get("snapshot_digest") != selected["entry"]["snapshot_digest"]
                or state.get("state") not in ("reference_build", "applying", "applied", "admitted")):
            raise HarnessError("Cannot renew a foreign/unknown compile transaction")
        n = 1
        while journal.with_name("ue_compile_compat_transaction_history_%03d.json" % n).exists():
            n += 1
        history = journal.with_name("ue_compile_compat_transaction_history_%03d.json" % n)
        with history.open("xb") as stream:
            stream.write(raw)
        previous = {"path": str(history), "sha256": hashlib.sha256(raw).hexdigest()}
    write_json(out / "runtime/ue_compile_compat_rebuild.json",
               {"version": VERSION, "eval_dir": str(out),
                "snapshot_digest": selected["entry"]["snapshot_digest"],
                "plan_sha256": selected["sha256"], "archive_admission": str(archive),
                "previous_transaction": previous, "state": "pending"})
    # A new explicit plan owns this rebuild; the previous journal is immutable above.
    # Write after the rebuild intent, so interruption still has a recovery parent.
    _transaction(out, selected, "reference_build")


def finish_rebuild(out):
    path = Path(out) / "runtime/ue_compile_compat_rebuild.json"
    if path.is_file():
        state = read_json(path)
        state["state"] = "done"
        write_json(path, state)


def recover_before_client(out, project, selected):
    """Restore an interrupted source copy before a UE client resolves its entry."""
    if selected is None:
        return
    from ..stage1 import prepare as frozen
    from engine_adapters.ue5.playtest.native_admission import source_manifest
    out, project = Path(out).resolve(), Path(project).resolve()
    if (out / "runtime/ue_admission").exists():
        return  # Normal stale-admission handling owns this directory.
    manifest = frozen.verify(out)
    if manifest["snapshot_digest"] != selected["entry"]["snapshot_digest"]:
        raise HarnessError("Compile recovery frozen snapshot changed")
    path = out / "runtime/ue_compile_compat_rebuild.json"
    if path.is_file():
        state = read_json(path)
        if (state.get("version") != VERSION or state.get("eval_dir") != str(out)
                or state.get("plan_sha256") != selected["sha256"]
                or state.get("snapshot_digest") != manifest["snapshot_digest"]):
            raise HarnessError("Compile source rebuild identity changed")
        if state.get("state") == "pending":
            archive = Path(state["archive_admission"])
            if archive.parent != out / "runtime" or not archive.name.startswith("ue_admission_stale_") or not archive.is_dir():
                raise HarnessError("Interrupted rebuild admission archive is missing")
            original = source_manifest(out / "input/project")
            if not project.exists() or source_manifest(project) != original:
                if project.exists():
                    _archive(project, state)
                shutil.copytree(out / "input/project", project, ignore=frozen.IGNORE)
            finish_rebuild(out)
    _recover_interrupted(out, project, selected, source_manifest(out / "input/project"))


def recover_unstarted_native(out, record):
    """Only archive an empty native directory left before recording ever began."""
    out, record = Path(out).resolve(), Path(record)
    native = record / "native"
    selected = selection(out)
    if selected is None or not native.is_dir() or any(native.iterdir()) or (record / "launch_repair_binding.json").exists():
        return
    transaction = out / "runtime/ue_compile_compat_transaction.json"
    rebuild = out / "runtime/ue_compile_compat_rebuild.json"
    candidates = [read_json(p) for p in (transaction, rebuild) if p.is_file()]
    pending = [s for s in candidates if s.get("state") in ("reference_build", "applying", "applied", "pending")]
    if not pending:
        return
    for state in pending:
        if (state.get("version") != VERSION or state.get("eval_dir") != str(out)
                or state.get("plan_sha256") != selected["sha256"]
                or state.get("snapshot_digest") != selected["entry"]["snapshot_digest"]):
            raise HarnessError("Unstarted native recovery transaction identity mismatch")
    _archive(native, {"reason": "empty native folder; no engine take started", "transactions": pending})
