"""Formal Gameness v4 entry; original checks are the sole rubric policy.

python -m pipeline.eval.stage1.gameness_v4_runtime --help
The shared runtime receives an explicit policy. No module globals are patched.
"""
from . import gameness_v4 as policy
from .gameness_v3_runtime import main as shared_main


def main(argv=None):
    import sys
    arguments = list(sys.argv[1:] if argv is None else argv)
    if any(arguments[n] == '--phase' and arguments[n+1] in {'unity-m-judge','unity-m-judge-prepare'} for n in range(len(arguments)-1)):
        from .unity_m_judge import main as unity_judge_main
        return unity_judge_main(arguments)
    if any(arguments[n] == '--phase' and arguments[n+1].startswith('unity-m-') for n in range(len(arguments)-1)):
        from .unity_m_runtime import main as unity_m_main
        return unity_m_main(arguments, column='Gameness')
    if any(arguments[n:n+2] == ['--phase', 'persistent-original-pixel-judge'] for n in range(len(arguments))):
        from .persistent_original_pixel_recovery import main as pixel_main
        return pixel_main(arguments)
    if any(arguments[n:n+2] == ['--phase', 'persistent-capacity-judge'] for n in range(len(arguments))):
        from .gameness_v4_persistent_capacity import main as capacity_main
        return capacity_main(arguments)
    if any(arguments[n:n+2] == ['--phase', 'persistent-judge'] for n in range(len(arguments))):
        from .gameness_v4_persistent_text import main as persistent_main
        return persistent_main(arguments)
    for index in range(len(arguments)-1):
        if arguments[index:index+2] == ['--phase', 'validator-correction']:
            from .gameness_v4_judge_correction import main as correction_main
            return correction_main(arguments[:index]+arguments[index+2:])
    return shared_main(arguments, scoring_policy=policy)


if __name__ == '__main__':
    raise SystemExit(main())
