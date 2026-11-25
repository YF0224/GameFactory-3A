"""
pipeline/data_collection/artifact_store.py

Content-addressed blob store for trajectory attachments
(collection plan §5 rule 5, schema §2 attachments).

Large payloads (raw provider dumps, file versions, screenshots, logs) are
written once under a sha256-derived name and referenced by repo-relative URI +
hash + size; a blob is never duplicated. The canonical on-disk name is the
digest without a filename extension, so the same bytes cannot be duplicated
just because one caller knows a MIME type. When ``AAAGF_TRAIN_DATA_ROOT`` points
outside the repo the URI stays a stable absolute path (schema §2.3: no
machine-private paths inside the payload, but the store root is configurable).

Stdlib only.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from pipeline.data_collection.paths import REPO_ROOT, rel_to_repo


class ArtifactStore:
    """``put`` returns ``{uri, sha256, size_bytes, mime_type}`` references."""

    def __init__(self, root: str | Path | None = None):
        from pipeline.data_collection.paths import TRAIN_DATA_ROOT

        self.root = Path(root) if root else Path(TRAIN_DATA_ROOT) / "blobs"

    # ── writing ───────────────────────────────────────────────────────────

    def put(
        self,
        data: bytes | str,
        *,
        ext: str = "",
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Store bytes once, content-addressed; return the stable reference."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        digest = hashlib.sha256(data).hexdigest()
        destination = self.root / digest[:2] / digest
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Publish only complete, durable bytes before an event can reference them.
            fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".blob-")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {
            "uri": rel_to_repo(destination),
            "sha256": digest,
            "size_bytes": len(data),
            "mime_type": mime_type,
        }

    def put_file(
        self,
        src_path: str | Path,
        *,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Store an existing file's bytes; extension is derived from the source."""
        src_path = Path(src_path)
        return self.put(
            src_path.read_bytes(),
            ext=src_path.suffix or "",
            mime_type=mime_type,
        )

    # ── reading ────────────────────────────────────────────────────────────

    def resolve(self, uri: str) -> Path:
        """Resolve a repo-relative (or absolute) stored URI to a real path."""
        if str(uri).startswith("$EXTERNAL/"):
            name = Path(str(uri)).name
            matches = list(self.root.glob(f"*/{name}"))
            if matches:
                return matches[0]
            return self.root / name[:2] / name
        path = Path(uri)
        return path if path.is_absolute() else REPO_ROOT / path

    def get(self, uri: str) -> bytes:
        return self.resolve(uri).read_bytes()
