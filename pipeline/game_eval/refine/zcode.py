"""ZCode relay adapter for the existing GameFactory AgentRunner.

The relay wrapper loads private settings without putting keys in argv or artifacts.
Event names/fields follow actual ZCode 0.16.9 stream-json sessions.
"""
from pathlib import Path
from pipeline.data_collection.adapters.base import AgentAdapter
from pipeline.data_collection.adapters.codex import CodexNormalizer
from pipeline.data_collection.core.collector import content_block


class ZCodeAdapter(AgentAdapter):
    provider = 'zcode'
    echoes_prompt = False

    def __init__(self, executable, extra_args=(), *, prompt_name="agent_input.txt"):
        if Path(prompt_name).name != prompt_name:
            raise ValueError("Prompt name must be a filename")
        self.prompt_name = prompt_name
        self.executable, self.extra_args = executable, list(extra_args)
        self.stream_normalizer = ZCodeNormalizer()

    def start(self, prompt, *, cwd, env=None):
        prompt_file = Path(cwd) / self.prompt_name
        with prompt_file.open('x', encoding='utf-8') as stream:
            stream.write(prompt)
        return self._spawn([self.executable, *self.extra_args,
                            '--prompt-file', str(prompt_file), '--cwd', str(cwd)], cwd, env)

    def normalizer(self):
        return self.stream_normalizer


class ZCodeNormalizer:
    def __init__(self):
        self.session_id = self.model = None
        self.session_ids = set()
        self.calls = set()
        self.results = set()
        self.completed = False
        self.final_response = None
        self.turn_completed = False

    def normalize(self, event):
        typ = event.get('type')
        payload = event.get('payload') or {}
        if event.get('sessionId'):
            self.session_id = event['sessionId']
            self.session_ids.add(self.session_id)
        if typ == 'session.updated' and payload.get('modelId'):
            self.model = payload['modelId']
        common = {'producer': 'zcode', 'provider_event': typ,
                  'session_id': self.session_id, 'model': self.model}
        # The lossless redacted raw archive already retains every streamed delta.
        # Expanding each token into a checkpointed trajectory made this real pilot
        # spend minutes draining and lose its terminal event at the drain bound.
        if typ == 'model.streaming':
            return []
        if typ == 'tool.updated':
            ident = payload.get('toolCallId')
            cid = f'zcode:{self.session_id}:{ident}' if ident else None
            if payload.get('kind') == 'scheduled' and ident not in self.calls:
                self.calls.add(ident)
                return [CodexNormalizer.call(cid, payload.get('toolName'), payload.get('input'), common)]
            if payload.get('kind') == 'result' and ident not in self.results:
                self.results.add(ident)
                result = payload.get('result', {})
                return [CodexNormalizer.result(cid, result,
                    'success' if result.get('success') is True else 'error' if result.get('success') is False else 'unknown', common)]
        if typ == 'turn.completed':
            self.turn_completed = True
        if typ == 'result':
            self.completed = self.turn_completed and event.get('projection', {}).get('status') == 'idle'
            self.final_response = event.get('response')
            if isinstance(self.final_response, str):
                return [dict(source='assistant', kind='message',
                    content=[content_block('text', data=self.final_response, visibility='collector_only')], **common)]
        # Raw provider events remain archived. Never turn reasoning deltas into visible text
        # or synthesize missing request boundaries/tool definitions.
        return [dict(source='system', kind='runtime',
                     content=[content_block('json', data=event, visibility='collector_only')], **common)]
