"""Self-contained evaluation for the three benchmark stages.

    stage1/   whitebox: all eight metrics in one run (prepare -> judge -> plan ->
              record -> evidence -> judge -> score); per-metric formats in stage1/metrics/
    stage3/   refine: reuses stage1 directly
    assets/   asset quality / usability

Engine adapters are shared. The assets bridge and sparse evidence helpers reuse
selected pipeline.game_eval modules; the separate eval-branch entrypoint is not required.
"""
