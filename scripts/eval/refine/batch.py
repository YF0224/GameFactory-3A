#!/usr/bin/env python3
"""Refine batch runner — matrix-driven, reads scripts/eval/refine/matrix.json."""
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from scripts.eval.refine.matrix import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
