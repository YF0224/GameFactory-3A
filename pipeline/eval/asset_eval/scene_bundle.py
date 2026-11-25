"""Bounded GLB-only extraction; never execute a project or modify its archive."""
from __future__ import annotations
import shutil
import zipfile
from pathlib import Path
from .common import ASSETS, validate_out


def extract_scene_glb(archive: Path, destination: Path, *, member: str) -> Path:
    """Extract one explicitly selected GLB into a fresh evaluation directory.

    This does not infer provider identity or award a scene score. Source archives
    must be under asset inputs; ZIP paths are never used as filesystem paths.
    """
    archive = Path(archive).resolve()
    if not archive.is_relative_to(ASSETS.resolve()):
        raise ValueError('Archive must be an existing asset input')
    if not archive.is_file():
        raise FileNotFoundError(archive)
    if not member.endswith('.glb'):
        raise ValueError('Only an explicitly selected GLB may be extracted')
    destination = validate_out(destination)
    target = destination / 'model.glb'
    if target.exists():
        raise FileExistsError(target)
    with zipfile.ZipFile(archive) as z:
        matches = [info for info in z.infolist() if info.filename == member]
        if len(matches) != 1:
            raise ValueError(f'Expected exactly one GLB member {member}, got {len(matches)}')
        info = matches[0]
        if info.file_size <= 0 or info.file_size > 512 * 1024 * 1024:
            raise ValueError('Scene GLB size outside safe bounds')
        # Establish ownership before cleanup: a concurrent pre-existing target
        # must not be deleted if exclusive creation fails.
        dst = target.open('xb')
        try:
            with dst, z.open(info) as src:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            if target.stat().st_size != info.file_size:
                raise ValueError('Truncated scene GLB member')
        except Exception:
            target.unlink(missing_ok=True)
            raise
    return target
