"""Explicit Stage3 provider routes. No fallback, retries, or shared sessions."""
from pathlib import Path
import json
import os
import shutil
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.9/3.10
    import tomli as tomllib

from pipeline.data_collection.adapters.base import AgentAdapter
from pipeline.data_collection.adapters.codex import CodexNormalizer
from pipeline.data_collection.adapters.claude_code import ClaudeCodeNormalizer
from pipeline.data_collection.core.collector import content_block

POLICY = 'fresh_session_multi_provider_1500s_work_300s_handoff_10attempts.v3'
PROVIDERS = {'zcode', 'codex', 'claude', 'kimi'}


def validate(settings):
    provider = settings.get('provider')
    if provider not in PROVIDERS or not settings.get('executable'):
        raise ValueError('Explicit supported provider and executable required')
    if not isinstance(settings.get('model'), str) or not settings['model'].strip():
        raise ValueError('Exact model ID required; no default model')
    args = settings.get('args', [])
    if not isinstance(args, list) or any(not isinstance(x, str) for x in args):
        raise ValueError('agent.args must be a list of strings')
    # These are built here, not inherited from user/global command templates.
    if provider != 'zcode' and args:
        raise ValueError('Native provider args are fixed; model/session/fallback overrides are forbidden')
    if provider == 'zcode':
        from .session import validate_agent
        validate_agent(settings)
        if any(x == '--resume' or x.startswith('--resume=') for x in args):
            raise ValueError('Shared resume is forbidden')


def kimi_route(settings):
    home = Path(settings.get('home', '~/.kimi-code')).expanduser().resolve()
    try:
        config = tomllib.loads((home / 'config.toml').read_text())
    except tomllib.TOMLDecodeError:
        raise ValueError('Invalid Kimi configuration (contents withheld)') from None
    alias = settings.get('model_alias') or config.get('default_model')
    model = config.get('models', {}).get(alias, {})
    provider = config.get('providers', {}).get(model.get('provider'), {})
    if model.get('model') != settings['model'] or not provider:
        raise ValueError('Kimi configured alias does not match frozen model')
    if provider.get('api_key_env') and not os.environ.get(provider['api_key_env']):
        raise ValueError('Kimi credential environment variable is empty')
    if not any(provider.get(k) for k in ('api_key', 'api_key_env', 'oauth', 'env')):
        raise ValueError('Kimi credentials are not configured')
    return home, alias


def preflight(settings):
    validate(settings)
    executable = shutil.which(str(Path(settings['executable']).expanduser()))
    if not executable:
        raise ValueError('Provider executable unavailable: ' + settings['executable'])
    if settings['provider'] == 'kimi':
        kimi_route(settings)
    return executable


class IdentityStream:
    """Keep native events; distinguish stream identity from CLI-enforced routing."""
    def __init__(self, provider, model):
        self.provider = provider
        self.model = model if provider in ('codex', 'kimi') else None
        self.model_binding = 'explicit_cli' if provider == 'codex' else (
            'validated_config_alias' if provider == 'kimi' else 'provider_stream')
        self.session_ids = set()
        self.completed = False
        self.failed = False
        self.delegate = CodexNormalizer() if provider == 'codex' else ClaudeCodeNormalizer()

    def normalize(self, event):
        typ = event.get('type')
        if self.provider == 'codex':
            if typ == 'thread.started' and event.get('thread_id'):
                self.session_ids.add(event['thread_id'])
            if typ in ('turn.failed', 'error'):
                self.failed = True
            if typ == 'turn.completed':
                self.completed = not self.failed
        elif self.provider == 'claude':
            if event.get('parent_tool_use_id'):
                return self.delegate.normalize(event)
            if event.get('session_id'):
                self.session_ids.add(event['session_id'])
            if typ == 'system' and event.get('subtype') == 'init':
                self.model = event.get('model')
            if typ == 'result':
                self.completed = (event.get('subtype') == 'success'
                                  and not event.get('is_error')
                                  and not event.get('permission_denials'))
        else:
            # Kimi 2.2 prompt mode emits a resume hint only after a successful turn.
            if typ == 'session.resume_hint' and event.get('session_id'):
                self.session_ids.add(event['session_id'])
                self.completed = True
            return [dict(source='system', kind='runtime', producer='kimi',
                         content=[content_block('json', data=event, visibility='collector_only')])]
        return self.delegate.normalize(event)


class NativeAdapter(AgentAdapter):
    echoes_prompt = False

    def __init__(self, settings, session=None, runtime_policy=None):
        validate(settings)
        validate_runtime_policy(settings, runtime_policy)
        self.runtime_policy = runtime_policy
        self.settings = settings
        self.provider = settings['provider']
        self.session = session
        self.stream_normalizer = IdentityStream(self.provider, settings['model'])
        self.kimi_before = set()

    def normalizer(self):
        return self.stream_normalizer

    def kimi_sessions(self, cwd):
        home, _ = kimi_route(self.settings)
        index = home / 'session_index.jsonl'
        result = set()
        if index.exists():
            for line in index.read_text().splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue  # An in-progress last index record is not an identity.
                if row.get('workDir') and Path(row['workDir']).resolve() == Path(cwd).resolve():
                    if row.get('sessionId'):
                        result.add(row['sessionId'])
        return result

    def command(self, prompt):
        s = self.settings
        executable = str(Path(s['executable']).expanduser())
        if self.provider == 'codex':
            cmd = [executable, 'exec'] + (['resume'] if self.session else [])
            cmd += ['--json', '--model', s['model'], '--skip-git-repo-check',
                    '--dangerously-bypass-approvals-and-sandbox', *s.get('args', [])]
            if self.runtime_policy:
                cmd += ['-c', 'model_reasoning_effort=' + json.dumps(self.runtime_policy['codex_reasoning_effort'])]
            return cmd + ([self.session] if self.session else []) + [prompt]
        if self.provider == 'claude':
            return [executable, '-p', prompt, '--verbose', '--output-format', 'stream-json',
                    '--model', s['model'], '--dangerously-skip-permissions', *s.get('args', [])] + (
                        ['--resume', self.session] if self.session else [])
        _, alias = kimi_route(s)
        return [executable, '--model', alias, '--output-format', 'stream-json',
                *s.get('args', [])] + (['--session', self.session] if self.session else []) + ['--prompt', prompt]

    def start(self, prompt, *, cwd, env=None):
        if self.provider == 'kimi':
            home, _ = kimi_route(self.settings)
            env = {**(os.environ if env is None else env), 'KIMI_CODE_HOME': str(home)}
            self.kimi_before = self.kimi_sessions(cwd)
        return self._spawn(self.command(prompt), cwd, env)

    def finalize_identity(self, workspace):
        if self.provider == 'kimi' and not self.stream_normalizer.session_ids:
            # On timeout the terminal resume hint is absent. Recover only the unique
            # new session at this exact workspace, or the explicitly resumed one.
            now = self.kimi_sessions(workspace)
            found = ({self.session} & now) if self.session else now - self.kimi_before
            if len(found) == 1:
                self.stream_normalizer.session_ids.update(found)


def validate_runtime_policy(settings, policy):
    if policy is None:
        return
    if settings.get('provider') != 'codex' or policy != {'codex_reasoning_effort': 'medium'}:
        raise ValueError('Only the explicitly migrated Codex medium reasoning route is supported')


def adapter(settings, root, *, session=None, runtime_policy=None):
    validate(settings)
    validate_runtime_policy(settings, runtime_policy)
    if settings['provider'] == 'zcode':
        from .zcode import ZCodeAdapter
        args = list(settings.get('args', [])) + (['--resume', session] if session else [])
        return ZCodeAdapter(settings['executable'], args,
                            prompt_name=f'{root.parent.name}_{root.name}_prompt.txt')
    return NativeAdapter(settings, session, runtime_policy)
