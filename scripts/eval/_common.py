"""Shared bootstrap for scripts/eval: paths, imports, case selection."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent          # GameFactory-3A/
FRAMEWORK = REPO                   # pipeline/ lives directly under REPO
if str(FRAMEWORK) not in sys.path:
    sys.path.insert(0, str(FRAMEWORK))

from pipeline.eval.stage1 import paths as common  # noqa: E402

MODELS = json.loads((HERE / 'config' / 'models.json').read_text(encoding='utf-8'))
MODELS.pop('_comment', None)
