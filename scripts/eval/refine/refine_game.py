#!/usr/bin/env python3
"""Start model-driven game refinement; formal evaluation is a separate command.

Examples:
  python scripts/refine_game.py --mode check
  python scripts/refine_game.py --mode repair
  python scripts/refine_game.py --models sol --mode repair
"""
from __future__ import annotations

import signal
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent))
from matrix import main as matrix_main


def main(argv=None):
    return matrix_main(argv)


if __name__ == '__main__':
    def stop(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Interrupted: dispatch claim and round counts preserved; inspect cleanup before recovery.',
              file=sys.stderr)
        raise SystemExit(130)
