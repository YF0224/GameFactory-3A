"""
pipeline/data_collection/loader.py

Direct training-read contract (schema §10.3, collection plan §9.2).

The loader consumes ``collect.json`` + trajectory JSON and yields
request-scoped samples in memory — no second SFT JSONL is ever produced.
It never fabricates missing content, never pulls future verification results
into an earlier request's input, and never loads non-``agent_received``
blocks (schema §5 rule 1); their bytes stay unreferenced.

Tokenizer / chat template / tensorization belong to the training run config;
this loader stops at materialized input events + target assistant events.

Stdlib only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from pipeline.data_collection.paths import REPO_ROOT, TRAIN_DATA_ROOT

from ..core.event_writer import (
    TRAJECTORY_INDEX_SCHEMA_VERSION,
    TRAJECTORY_SCHEMA_VERSION,
    load_json,
)

_TEXTUAL_TYPES = ("text", "json")


class TrajectoryLoader:
    """Reads trajectories straight from ``train_data/`` for training batches."""

    def __init__(self, data_root: str | Path | None = None):
        self.data_root = Path(data_root) if data_root else Path(TRAIN_DATA_ROOT)

    # ── containers ─────────────────────────────────────────────────────────

    def load_index(self) -> dict:
        path = self.data_root / "collect.json"
        if not path.exists():
            raise FileNotFoundError(f"no collect.json under {self.data_root}")
        index = load_json(path)
        if index.get("schema_version") != TRAJECTORY_INDEX_SCHEMA_VERSION:
            raise ValueError(f"{path}: unexpected index schema_version")
        return index

    def load_trajectory(self, trajectory_id: str) -> dict:
        """Load one trajectory by id, via the index when available."""
        path = self.data_root / "trajectories" / f"{trajectory_id}.json"
        if not path.exists():
            for entry in self.load_index().get("trajectories") or []:
                if entry.get("trajectory_id") == trajectory_id:
                    candidate = Path(entry["trajectory_path"])
                    path = candidate if candidate.is_absolute() else REPO_ROOT / candidate
                    break
        trajectory = load_json(path)
        if trajectory.get("schema_version") != TRAJECTORY_SCHEMA_VERSION:
            raise ValueError(f"{path}: unexpected trajectory schema_version")
        return trajectory

    def iter_trajectories(
        self,
        *,
        status: str | None = "ready",
        split: str | None = None,
        session_view: str = "training",
    ) -> Iterator[tuple[str, dict]]:
        """Yield (trajectory_id, trajectory) filtered by the in-file training control.

        ``session_view="training"`` (default) keeps ONE view per underlying
        session so the same model call is never trained twice: a companion
        export or a rebuild supersedes the trajectory it was derived from
        (``predecessor_trajectory_id``, or a ``companion_export_trajectory``
        attachment on the live file). Among competing views the request view
        wins, then the newest created_at, then the stable id order.
        ``session_view="all"`` yields every indexed trajectory.
        """
        if session_view not in ("training", "all"):
            raise ValueError(f"unknown session_view {session_view!r}")
        matches: list[tuple[str, dict]] = []
        for entry in self.load_index().get("trajectories") or []:
            trajectory_id = entry.get("trajectory_id")
            if not trajectory_id:
                continue
            trajectory = self.load_trajectory(trajectory_id)
            training = trajectory.get("training") or {}
            if status is not None and training.get("status") != status:
                continue
            if split is not None and training.get("split") != split:
                continue
            matches.append((trajectory_id, trajectory))
        if session_view == "all":
            yield from matches
            return
        # superseded: this trajectory has a registered successor view
        successor: dict[str, str] = {}
        for trajectory_id, trajectory in matches:
            md = trajectory.get("metadata") or {}
            predecessor = md.get("predecessor_trajectory_id")
            if predecessor and predecessor != trajectory_id:
                successor[predecessor] = trajectory_id
            for attachment in trajectory.get("attachments") or []:
                if (
                    attachment.get("type") == "companion_export_trajectory"
                    and attachment.get("trajectory_id")
                    and attachment["trajectory_id"] != trajectory_id
                ):
                    successor[trajectory_id] = attachment["trajectory_id"]
        alive = [(tid, t) for tid, t in matches if tid not in successor]
        # surviving siblings of one session (e.g. export vs. its rebuild)
        # group under their shared predecessor
        groups: dict[str, list[tuple[str, dict]]] = {}
        for tid, trajectory in alive:
            key = (trajectory.get("metadata") or {}).get("predecessor_trajectory_id") or tid
            groups.setdefault(key, []).append((tid, trajectory))
        for members in groups.values():
            if len(members) > 1:
                members.sort(key=lambda m: m[0])  # stable id order
                members.sort(  # newest first (ISO-8601 sorts lexically)
                    key=lambda m: str((m[1].get("metadata") or {}).get("created_at") or ""),
                    reverse=True)
                members.sort(  # the request view is the trainable view
                    key=lambda m: len(m[1].get("requests") or []), reverse=True)
            yield members[0]

    def iter_episodes(
        self,
        *,
        status: str | None = "ready",
        split: str | None = None,
        session_view: str = "training",
    ) -> Iterator[tuple[str, list[tuple[str, dict]]]]:
        """Group the filtered trajectories into training episodes.

        Episode identity is ``metadata.episode_id``; a trajectory without one
        is its own single-member episode. Members are ordered by
        ``metadata.created_at`` (ISO-8601 sorts lexically, ties by id) — the
        long-chain order the aggregation unit is about — and episodes are
        yielded in first-member order. Grouping never changes which
        trajectories pass the training-control filters or the session-view
        supersession.
        """
        groups: dict[str, list[tuple[str, dict]]] = {}
        order: list[str] = []
        for trajectory_id, trajectory in self.iter_trajectories(
            status=status, split=split, session_view=session_view
        ):
            episode_id = (trajectory.get("metadata") or {}).get("episode_id") or trajectory_id
            if episode_id not in groups:
                groups[episode_id] = []
                order.append(episode_id)
            groups[episode_id].append((trajectory_id, trajectory))
        for episode_id in order:
            members = groups[episode_id]
            members.sort(key=lambda m: (str((m[1].get("metadata") or {}).get("created_at") or ""),
                                        m[0]))
            yield episode_id, members

    # ── materialization ────────────────────────────────────────────────────

    @staticmethod
    def materialize_block(block: dict, *, include_visible: bool = False,
                           include_collector_only: bool = False) -> dict:
        """Load one content block's bytes. ``agent_received`` always loads;
        ``agent_visible`` loads only in the explicitly requested history
        reconstruction view; ``collector_only`` loads only in the audit view.
        Visibility is never promoted in the data to make a block loadable."""
        block = dict(block)
        uri = block.get("uri")
        loadable = block.get("visibility") == "agent_received" or (
            include_visible and block.get("visibility") == "agent_visible") or (
            include_collector_only and block.get("visibility") == "collector_only")
        if not loadable or not uri:
            return block
        path = Path(uri)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            return block
        raw = path.read_bytes()
        if block.get("type") in _TEXTUAL_TYPES:
            block["data"] = raw.decode("utf-8", errors="replace")
        else:
            # Binary multimodal content: hand the bytes to the training side.
            block["bytes"] = raw
        return block

    def materialize_event(self, event: dict, *, request_input: bool = False,
                          include_visible: bool = False,
                          include_collector_only: bool = False) -> dict:
        """Materialize one event. ``request_input`` keeps only content the
        request view may load (schema §5 rules 1/4); ``include_visible``
        admits agent_visible blocks for the explicitly requested history
        reconstruction view; ``include_collector_only`` admits collector-only
        blocks for the audit view. Visibility is never promoted in the data
        to make it loadable here."""
        blocks = event.get("content") or []
        if request_input:
            if include_collector_only:
                pass  # audit view: every recorded block is reviewable
            elif include_visible:
                blocks = [b for b in blocks
                          if b.get("visibility") in ("agent_received", "agent_visible")]
            else:
                blocks = [b for b in blocks if b.get("visibility") == "agent_received"]
        materialized = dict(event)
        materialized["content"] = [
            self.materialize_block(block, include_visible=include_visible,
                                   include_collector_only=include_collector_only)
            for block in blocks
        ]
        return materialized

    # ── request-scoped samples ─────────────────────────────────────────────

    def iter_request_samples(self, trajectory: dict, *,
                             mode: str = "precise") -> Iterator[dict]:
        """Yield every request with its input/target boundary and learn flag.

        ``mode`` is explicit (schema §10.3): ``"precise"`` materializes only
        agent_received content — the exact-prompt claim; ``"reconstruction"``
        also materializes agent_visible content as the history reconstruction
        view; ``"audit"`` materializes every recorded block for review. Every
        sample carries a ``quality`` block with ``training_allowed``; visibility
        is never silently promoted in the data to fit a mode.
        """
        if mode not in ("precise", "reconstruction", "audit"):
            raise ValueError(f"unknown sample mode {mode!r}")
        events = {event.get("event_id"): event for event in trajectory.get("events") or []}
        tool_sets = trajectory.get("tool_sets") or {}
        default_tools = trajectory.get("tools") or []
        training_control = trajectory.get("training") or {}
        include_visible = mode in ("reconstruction", "audit")
        include_collector_only = mode == "audit"
        for request in trajectory.get("requests") or []:
            request_id = request.get("request_id")
            if not request_id:
                continue
            boundary = request.get("boundary", "unknown")
            context = request.get("context", "unknown")
            training_allowed = boundary == "observed" and context == "complete"
            quality = {
                "boundary": boundary,
                "context": context,
                "training_allowed": training_allowed,
                "reason": None if training_allowed else (
                    "request is not an observed, complete-context model call "
                    f"(boundary={boundary}, context={context})"),
            }
            input_events = [events[i] for i in request.get("input_event_ids") or [] if i in events]
            response_events = [
                events[i] for i in request.get("response_event_ids") or [] if i in events
            ]
            tool_set_id = request.get("tool_set_id")
            yield {
                "trajectory_id": (trajectory.get("metadata") or {}).get("trajectory_id"),
                "request_id": request_id,
                "mode": mode,
                "policy": training_control.get("policy"),
                "input": [self.materialize_event(event, request_input=True,
                                                 include_visible=include_visible,
                                                 include_collector_only=include_collector_only)
                          for event in input_events],
                "tools": tool_sets.get(tool_set_id, default_tools) if tool_set_id else default_tools,
                "target": [self.materialize_event(event) for event in response_events],
                "learn": bool((request.get("training") or {}).get("learn", False)),
                "reason": (request.get("training") or {}).get("reason"),
                "training": training_control,
                # Request quality markers travel with every sample (schema
                # §10.3): a consumer must always see what it is training on,
                # and under which policy the request was admitted.
                # Missing markers read as unknown — never as a pass.
                "boundary": boundary,
                "context": context,
                "response_status": request.get("response_status", "unknown"),
                "input_reconstruction": request.get("input_reconstruction"),
                "quality": quality,
            }

    def iter_training_samples(
        self,
        trajectory: dict,
        *,
        split: str | None = None,
        mode: str = "precise",
    ) -> Iterator[dict]:
        """Yield training-target requests (schema §10.3).

        ``mode="precise"`` (default) yields only exact request samples —
        ``boundary=observed`` + ``context=complete``, learn=true, status=ready —
        so reconstructed data never mixes into the formal SFT set, whatever
        policy marked it learnable. ``mode="reconstruction"`` is the explicit
        history-reconstruction view: requests admitted by the
        ``assistant_reconstructed_v1`` policy (reconstructed boundary, rebuilt
        partial context, provably finished response) land here with every
        quality marker on the sample. ``mode="audit"`` bypasses the
        training-control filters entirely and yields every request with its
        quality block, for capture review. training.status=ready and
        learn=true cannot bypass either training gate's labeling; the precise
        gate is enforced by the validator.
        """
        if mode not in ("precise", "reconstruction", "audit"):
            raise ValueError(f"unknown sample mode {mode!r}")
        if mode == "audit":
            yield from self.iter_request_samples(trajectory, mode="audit")
            return
        control = trajectory.get("training") or {}
        if control.get("status") != "ready":
            return
        if split is not None and control.get("split") != split:
            return
        for sample in self.iter_request_samples(trajectory, mode=mode):
            if not sample["learn"]:
                continue
            if mode == "precise" and not (
                sample["boundary"] == "observed" and sample["context"] == "complete"
            ):
                continue
            yield sample
