"""Materialized SFT export packages (schema §10.3, training-export step).

The loader deliberately stops at in-memory samples; this module is the
explicit materialization step that writes a training package under
``exports/sft/<export_id>/``:

* ``samples.jsonl`` — one finalized, scrubbed sample per line;
* ``manifest.json``  — provenance, counts, episode grouping, file hashes.

Scrubbing happens ONLY in the exported package — recorded trajectories are
never rewritten:

* ``raw_reasoning`` is stripped from every exported event (policy
  ``retained_restricted_not_training_input``: reasoning bytes stay in the
  trajectory and raw archives, never in the training package);
* binary content blocks keep their content-addressed ``uri``+``sha256``
  but drop the in-memory ``bytes`` (JSONL cannot carry them; the blob store
  keeps the actual content);
* machine-absolute path prefixes inside tool-call arguments and content
  text are substituted with the stable ``$REPO_ROOT``/``$HOME`` prefixes
  (the validator's ``leak.abs_path`` cleanup; URI reference fields are
  deliberately NOT rewritten — they are made portable at capture time).

An export is refused when the export_id already exists or when the
filters produce zero samples — an empty package is almost always a
wrong-mode/wrong-policy mistake, and refusing keeps it loud.

Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import REPO_ROOT, TRAIN_DATA_ROOT

from ..core.event_writer import atomic_write_json, now_iso
from .loader import TrajectoryLoader


class _Scrubber:
    """Package-level cleanup with honest counts; never touches sources."""

    def __init__(self):
        self.repo = str(REPO_ROOT)
        self.home = str(Path.home())
        self.raw_reasoning_events = 0
        self.binary_blocks = 0
        self.path_fields = 0

    def _substitute(self, value: Any) -> Any:
        if isinstance(value, str):
            # most specific prefix first: the repo lives under $HOME
            out = value.replace(self.repo, "$REPO_ROOT").replace(self.home, "$HOME")
            if out != value:
                self.path_fields += 1
            return out
        if isinstance(value, dict):
            return {key: self._substitute(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._substitute(item) for item in value]
        return value

    def event(self, event: dict) -> None:
        # provider thinking is archived but is never training input
        if isinstance(event, dict) and event.pop("raw_reasoning", None) is not None:
            self.raw_reasoning_events += 1
        for call in (event.get("tool_calls") if isinstance(event, dict) else None) or []:
            if isinstance(call, dict) and call.get("arguments") is not None:
                call["arguments"] = self._substitute(call["arguments"])
        for block in (event.get("content") if isinstance(event, dict) else None) or []:
            if not isinstance(block, dict):
                continue
            if block.pop("bytes", None) is not None:
                self.binary_blocks += 1
            if block.get("data") is not None:
                block["data"] = self._substitute(block["data"])

    def sample(self, sample: dict) -> None:
        for event in (sample.get("input") or []) + (sample.get("target") or []):
            self.event(event)

    def report(self) -> dict[str, Any]:
        return {
            "raw_reasoning_events_stripped": self.raw_reasoning_events,
            "binary_bytes_blocks_dropped": self.binary_blocks,
            "abs_path_fields_substituted": self.path_fields,
            "policy": "scrubbed in the exported package only; recorded "
                      "trajectories keep their original bytes",
        }


def export_sft(
    *,
    mode: str = "precise",
    split: str | None = None,
    group_id: str | None = None,
    export_id: str | None = None,
    data_root: str | Path | None = None,
) -> dict[str, Any]:
    """Materialize one SFT package from the ready trajectories.

    Walks the loader's training view (session supersession applies: a
    companion export replaces the live view it was derived from), groups the
    surviving trajectories into episodes by ``metadata.episode_id``, and
    writes the package under ``<data_root>/exports/sft/<export_id>/``.
    Returns a report dict; ``ok=False`` reports a refusal and writes
    nothing.
    """
    if mode not in ("precise", "reconstruction"):
        raise ValueError(f"unknown export mode {mode!r}; expected precise or reconstruction")
    root = Path(data_root) if data_root else Path(TRAIN_DATA_ROOT)
    loader = TrajectoryLoader(data_root=root)
    export_id = export_id or f"sft_{mode}_{split or 'all'}_{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    out_dir = root / "exports" / "sft" / export_id
    if out_dir.exists():
        return {"ok": False, "refused": "export_id_exists", "path": str(out_dir),
                "export_id": export_id}

    scrubber = _Scrubber()
    samples: list[dict[str, Any]] = []
    episodes: list[dict[str, Any]] = []
    trajectories: list[dict[str, Any]] = []
    for episode_id, members in loader.iter_episodes(status="ready", split=split):
        row: dict[str, Any] = {"episode_id": episode_id, "trajectory_ids": [],
                               "samples": 0}
        for trajectory_id, trajectory in members:
            control = trajectory.get("training") or {}
            if group_id is not None and control.get("group_id") != group_id:
                continue
            metadata = trajectory.get("metadata") or {}
            member_samples = 0
            for sample in loader.iter_training_samples(trajectory, split=split, mode=mode):
                scrubber.sample(sample)
                sample["episode_id"] = episode_id
                samples.append(sample)
                member_samples += 1
            row["trajectory_ids"].append(trajectory_id)
            row["samples"] += member_samples
            trajectories.append({
                "trajectory_id": trajectory_id,
                "episode_id": episode_id,
                "policy": control.get("policy"),
                "group_id": control.get("group_id"),
                "samples": member_samples,
                "created_at": metadata.get("created_at"),
            })
        if row["trajectory_ids"]:
            episodes.append(row)

    if not samples:
        return {"ok": False, "refused": "no_samples",
                "reason": f"mode={mode!r} with the current filters yields zero samples; "
                          "check --mode/--split/--group-id and the finalize policy",
                "export_id": export_id}

    out_dir.mkdir(parents=True)
    payload = "".join(json.dumps(sample, ensure_ascii=False, default=str) + "\n"
                      for sample in samples)
    samples_path = out_dir / "samples.jsonl"
    samples_path.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(samples_path.read_bytes()).hexdigest()
    manifest = {
        "export_id": export_id,
        "created_at": now_iso(),
        "mode": mode,
        "split": split,
        "group_id": group_id,
        "policies": sorted({sample.get("policy") for sample in samples
                            if sample.get("policy")}),
        "sample_count": len(samples),
        "episode_count": len(episodes),
        "episodes": episodes,
        "trajectories": trajectories,
        "scrubbing": scrubber.report(),
        "files": {"samples.jsonl": {"sha256": digest,
                                     "size_bytes": len(payload.encode("utf-8")),
                                     "lines": len(samples)}},
        "blobs": "content-block uri fields are repo-relative and resolve against "
                 "the repository root (train_data/blobs/...); in-package bytes "
                 "are dropped, uri+sha256 stay",
    }
    atomic_write_json(out_dir / "manifest.json", manifest)
    return {"ok": True, "export_id": export_id, "path": str(out_dir),
            "sample_count": len(samples),
            "episode_count": len(episodes),
            "trajectory_count": len(trajectories),
            "scrubbing": scrubber.report()}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Materialize a training package from ready trajectories "
                    "(exports/sft/<export_id>/: samples.jsonl + manifest.json)")
    p.add_argument("--mode", choices=("precise", "reconstruction"), default="precise",
                   help="precise: formal exact-prompt set only; reconstruction: also "
                        "requests admitted by assistant_reconstructed_v1")
    p.add_argument("--split", choices=("train", "validation", "test"),
                   help="Restrict to one split (default: every ready split)")
    p.add_argument("--group-id", help="Restrict to one training group id")
    p.add_argument("--export-id", help="Package id (default: sft_<mode>_<split>_<utc>)")
    p.add_argument("--data-root", type=Path,
                   help="Override the train_data root (defaults to $AAAGF_TRAIN_DATA_ROOT)")
    a = p.parse_args(argv)
    result = export_sft(mode=a.mode, split=a.split, group_id=a.group_id,
                        export_id=a.export_id, data_root=a.data_root)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
