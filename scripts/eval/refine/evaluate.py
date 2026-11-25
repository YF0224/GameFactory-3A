#!/usr/bin/env python3
"""Run only evaluation against a frozen Stage3 repair batch."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[2]
FRAMEWORK = BENCH / 'GameFactory-3A'
sys.path.insert(0, str(FRAMEWORK))
sys.path.insert(0, str(BENCH / 'scripts'))

from pipeline.eval.stage3 import selected as _stage3  # refine batch normalize, run, exclusive
from pipeline.eval.stage3 import criteria as _stage3  # refine common read


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True,
                        help='The exact frozen repair batch directory to evaluate')
    parser.add_argument('--mode', choices=('evaluate', 'static'), default='evaluate',
                        help='static is source-only diagnostics, not runtime evaluation')
    args = parser.parse_args(argv)
    config = normalize(read(args.config))
    output = args.output.expanduser().resolve()
    if not (output / 'configuration.json').is_file():
        parser.error('No frozen repair batch at --output; run the separate refine script first')
    with exclusive(output.parent / (output.name + '.batch.lock')):
        identity_path = output / 'stage3_prompt_identity.json'
        if (identity_path.is_file() and read(identity_path).get('interaction_policy')
                in ('agent_turn_1800s_10attempts.v1', 'fresh_session_1500s_work_300s_handoff_10attempts.v2')):
            from run_stage3_refine import _generation_config
            config = _generation_config(config)
            if read(identity_path)['interaction_policy'] == 'fresh_session_1500s_work_300s_handoff_10attempts.v2':
                config['interaction_policy'] = read(identity_path)['interaction_policy']
        result = run(config, output, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failed = {'ERROR', 'SAFETY_STOP', 'BLOCKED_NO_PROJECT', 'BLOCKED_RUNTIME'}
    return 2 if any(isinstance(value, dict) and value.get('status') in failed
                    for value in result.values()) else 0


if __name__ == '__main__':
    raise SystemExit(main())
