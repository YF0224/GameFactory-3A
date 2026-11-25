"""Evaluation pipeline for all benchmark stages.

stage1/       Whitebox preparation, runtime, verification, judging and scoring.
stage3/       Refinement criteria and metrics, reusing stage1.
assets/       Public asset evaluation bridge.
asset_eval/   Asset metric and rubric implementation.
refine/       Retained refinement runtime for legacy launchers.
preparation/  Shared requirement helpers.
priority_assets/ Renderer runtime dependencies.

Engine adapters are shared through engine_adapters. Evaluation implementation
and support modules live under this package.
"""
