"""Bind existing agent output into a new evaluation identity without repairing it."""
from pathlib import Path
import os
from .common import read, dump, sha, resolve
from .session import inventory, snapshot


def attach(game, folder, config):
    from .batch import exclusive
    spec = config['repair_sources'][game['game_id']]
    output = resolve(config['bench_root'], spec['output'])
    folder = Path(folder).resolve()
    source = output / 'games' / game['game_id']
    if folder.is_relative_to(output) or output.is_relative_to(folder):
        raise ValueError('Existing repair must be bound into a separate evaluation output')
    with exclusive(output.parent / (output.name + '.batch.lock')):
        old_inventory = read(output / 'inventory.json')
        previous = next(g for g in old_inventory['games'] if g['game_id'] == game['game_id'])
        if previous != game:
            raise ValueError('Repair source tasks/project/payload identity differs from evaluation inventory')
        for ref in old_inventory['sources'].values():
            if sha(ref['path']) != ref['sha256']:
                raise ValueError('Repair source collect changed')
        continuation = spec.get('continuation')
        if continuation and (Path(continuation).is_absolute() or '..' in Path(continuation).parts or continuation == '.'):
            raise ValueError('Invalid continuation directory')
        turn = source / continuation if continuation else source
        if spec.get('recovery_pass'):
            from .repair_pass_binding import verify_recovery_pass
            recovery = verify_recovery_pass(source, previous_config=read(output / 'configuration.json'))
            if turn.resolve() != Path(recovery['final_turn']).resolve():
                raise ValueError('Evaluation did not select final counted recovery round')
            dump(folder / 'recovery_pass_binding.json', recovery)
        report = read(turn / 'agent_report.json')
        if report.get('status') != 'completed' or report.get('exit_code') != 0 or report.get('finalization_error'):
            raise ValueError('Agent transport did not complete; preserve separately from product failure')
        pid = report.get('pid')
        if pid:
            try:
                os.kill(int(pid), 0)
            except ProcessLookupError:
                pass
            else:
                raise BlockingIOError('Agent writer still alive; cannot freeze existing output')
        identity_path = turn / 'agent_identity.json'
        identity = read(identity_path) if identity_path.exists() else None
        previous_config = read(output / 'configuration.json')
        if previous_config.get('agent', {}).get('provider') == 'zcode':
            if (not identity or not identity.get('provider_completed') or len(identity.get('session_ids', [])) != 1
                    or identity.get('model') != previous_config['agent'].get('model')):
                raise ValueError('Existing output lacks actual single-session/model completion identity')
        original = read(source / 'original_project.json')
        if inventory(original['root']) != original['files']:
            raise ValueError('Original delivery changed')
        observed = inventory(source / 'workspace/project')
        saved_path = turn / 'repaired_project.json'
        if saved_path.exists() and read(saved_path)['files'] != observed:
            raise ValueError('Completed agent output changed after its saved manifest')
        copied = snapshot(source / 'workspace/project', folder / 'workspace/project')
        if copied != observed:
            raise ValueError('Existing output changed while freezing')
        dump(folder / 'original_project.json', original)
        payloads = {}
        for ident, item in read(source / 'payloads.json').items():
            if item['status'] != 'READY':
                payloads[ident] = item
                continue
            if sha(item['frozen_path']) != item['sha256']:
                raise ValueError('Existing pristine payload changed')
            # Existing immutable assets are explicit data dependencies; no extra payload copies.
            payloads[ident] = dict(item)
        dump(folder / 'payloads.json', payloads)
        dump(folder / 'repaired_project.json', {'files': copied, 'meaning': 'Agent output, not a quality assertion'})
        binding = {'version': 'refine.existing-agent-output.v1', 'source_output': str(output),
            'source_turn': str(turn), 'agent_report': str(turn / 'agent_report.json'),
            'agent_report_sha256': sha(turn / 'agent_report.json'), 'agent_identity': identity,
            'source_configuration_sha256': sha(output / 'configuration.json'),
            'source_implementation': read(output / 'code_identity.json'),
            'source_status': read(turn / 'status.json') if (turn / 'status.json').exists() else None,
            'source_manifest': copied, 'new_agent_session': False,
            'warnings': [] if (source / 'workspace/repair_report.md').is_file() else ['MISSING_AGENT_REPAIR_REPORT'],
            'note': 'Missing report, empty final text and poor code quality do not block evaluation of completed agent output.'}
        dump(folder / 'repair_artifact_binding.json', binding)
        return {'status': 'AGENT_OUTPUT_BOUND', 'binding': str(folder / 'repair_artifact_binding.json')}


def evaluation_stages(game, folder, config):
    """Reuse validated static/render evidence in a new tool-recovery identity only."""
    import shutil
    from .batch import exclusive
    from .evaluation import require_checks, STATIC
    folder = Path(folder).resolve()
    output = resolve(config['bench_root'], config['evaluation_sources'][game['game_id']]['output'])
    if folder.is_relative_to(output) or output.is_relative_to(folder):
        raise ValueError('Evaluation reuse requires a separate output')
    source = output / 'games' / game['game_id']
    with exclusive(output.parent / (output.name + '.batch.lock')):
        old_game = next(g for g in read(output / 'inventory.json')['games'] if g['game_id'] == game['game_id'])
        if old_game != game:
            raise ValueError('Evaluation reuse game/rubric/payload identity differs')
        for name in ('input/source_manifest.json', 'input/tasks.json', 'input/source_bundle.txt'):
            if sha(source / name) != sha(folder / name):
                raise ValueError('Evaluation reuse frozen source/tasks differ: ' + name)
        if inventory(source / 'input/project') != read(folder / 'input/source_manifest.json')['files']:
            raise ValueError('Prior evaluated source changed')
        old_sol = read(output / 'configuration.json').get('sol', {})
        if old_sol.get('model') != config.get('sol', {}).get('model'):
            raise ValueError('Evaluation reuse model differs')
        stage = read(source / 'stages/static.json')
        static = read(source / 'static.json')
        if stage.get('status') != 'COMPLETE' or stage.get('result') != static:
            raise ValueError('Prior static did not complete consistently')
        require_checks(static, read(folder / 'input/tasks.json'))
        call = source / 'model_calls/static'
        if read(call / 'response.json') != static or read(call / 'schema.json') != STATIC:
            raise ValueError('Prior raw static response/schema differs')
        invocation = read(call / 'invocation.json')
        if invocation.get('exit_code') != 0 or invocation.get('model_requested') != old_sol.get('model'):
            raise ValueError('Prior static invocation did not complete with the configured model')
        # Keep the actual request/response/budget/elapsed evidence, never manufacture a new invocation.
        bindings = {str(p.relative_to(source)): sha(p) for p in call.rglob('*') if p.is_file()}
        bindings['static.json'] = sha(source / 'static.json')
        shutil.copytree(call, folder / 'model_calls/static')
        dump(folder / 'static.json', static)
        dump(folder / 'stages/static.json', {**stage, 'reused_from': str(source / 'stages/static.json')})
        renderer = Path(__file__).resolve().parents[3] / 'pipeline/eval/priority_assets/renderer/render.mjs'
        reused = []
        for marker in sorted((source / 'stages').glob('render_*.json')):
            state = read(marker)
            if state.get('status') != 'COMPLETE':
                continue
            render = state['result']
            if (sha(render['source_path']) != render['source_sha256']
                    or sha(renderer) != render['renderer_sha256']
                    or sha(renderer.parent / 'package-lock.json') != render['renderer_lock_sha256']
                    or not render['views']
                    or any(sha(view['path']) != view['sha256'] for view in render['views'])):
                raise ValueError('Prior source render provenance changed')
            manifest = Path(render['views'][0]['path']).parent / 'render.json'
            if sha(manifest) != render['render_manifest_sha256']:
                raise ValueError('Prior render manifest changed')
            dump(folder / 'stages' / marker.name, {**state, 'reused_from': str(marker)})
            bindings[str(marker.relative_to(source))] = sha(marker)
            reused.append(marker.stem)
        binding = {'version': 'refine.evaluation-stage-reuse.v1', 'source_output': str(output),
            'source_files_sha256': bindings,
            'source_configuration_sha256': sha(output / 'configuration.json'), 'reused_stages': ['static', *reused],
            'new_model_calls': 0, 'new_agent_sessions': 0,
            'note': 'Only immutable static and original asset renders reused; failed native attempts stay preserved.'}
        dump(folder / 'evaluation_reuse_binding.json', binding)
        return binding
