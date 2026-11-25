#!/usr/bin/env python3
"""Repository-relative launcher; all production implementation lives in pipeline.eval.refine."""
from pathlib import Path
import sys

FRAMEWORK = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(FRAMEWORK))
from pipeline.eval.refine.batch import main

if __name__ == '__main__':
    raise SystemExit(main())
