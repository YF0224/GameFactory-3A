"""Asset scoring bridge; argument parsing and scoring remain owned by asset_eval."""
from __future__ import annotations


def run(argv: list[str] | None = None) -> int:
    from pipeline.game_eval.asset_eval.run import main
    return main(argv)
