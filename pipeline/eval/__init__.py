"""Self-contained evaluation for the three benchmark stages.

    stage1/   whitebox: all eight metrics in one run (prepare -> judge -> plan ->
              record -> evidence -> judge -> score); per-metric formats in stage1/metrics/
    stage3/   refine: reuses stage1 directly
    assets/   asset quality / usability

Engine adapters (``engine_adapters``) are used as-is. Nothing here imports
``pipeline.eval``; stage1 (whitebox), stage3 (refine), assets.
"""
