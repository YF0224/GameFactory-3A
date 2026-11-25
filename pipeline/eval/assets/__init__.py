"""Asset evaluation (3D objects, scenes, CG, audio, video).

Entry point: pipeline.eval.assets.run.main
Called from scripts/eval/evaluate.py with --stage assets.
"""
from .run import main  # noqa: F401
