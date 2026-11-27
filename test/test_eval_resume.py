"""Offline regression checks for migrated eval imports and interrupted-call reuse."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch

from pipeline.eval.whitebox.core import llm, suites
from pipeline.eval.whitebox.record import record
from pipeline.eval.repair import godot_completed_record_recovery


class EvalResumeTests(unittest.TestCase):
    def test_whitebox_alias(self):
        self.assertEqual(suites.get('stage1'), suites.get('whitebox'))

    def test_migrated_godot_imports(self):
        self.assertTrue(callable(record.record))
        self.assertTrue(callable(godot_completed_record_recovery.recover))

    def test_retry_cache_is_bound_and_sha_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base, retry = root / 'evidence_t1_01', root / 'evidence_t1_01_002'
            base.mkdir()
            retry.mkdir()
            for folder in (base, retry):
                for name in ('prompt.txt', 'schema.json', 'images.json'):
                    (folder / name).write_text('{}')
                (folder / 'invocation.json').write_text(json.dumps({'model_requested': 'gpt-6.1-sol'}))
            raw = b'{"checks": {}}'
            (retry / 'response.json').write_bytes(raw)
            (retry / 'accepted_response.json').write_text(json.dumps({
                'path': 'response.json', 'sha256': hashlib.sha256(raw).hexdigest(), 'attempt': 1}))
            self.assertEqual(llm.accepted_response(root, base.name), {'checks': {}})
            for name in ('prompt.txt', 'schema.json', 'images.json', 'invocation.json'):
                previous = (retry / name).read_text()
                (retry / name).write_text('{"model_requested":"other"}')
                self.assertIsNone(llm.accepted_response(root, base.name))
                (retry / name).write_text(previous)
            (retry / 'response.json').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                llm.accepted_response(root, base.name)

    def test_whitebox_does_not_enter_refinement_playable_branch(self):
        from pipeline.eval.whitebox.core import pipeline
        for name in ('stage1', 'whitebox'):
            with self.subTest(suite=name), tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
                manifest = {'suite': name, 'game_id': 'fixture'}
                stack.enter_context(patch.object(pipeline.prepare, 'prepare', return_value=manifest))
                stack.enter_context(patch.object(pipeline.prepare, 'verify'))
                stack.enter_context(patch.object(pipeline.judge, 'judge'))
                stack.enter_context(patch.object(pipeline.standards, 'load', return_value={}))
                stack.enter_context(patch.object(pipeline.evidence, 'build_static', return_value={}))
                stack.enter_context(patch.object(pipeline, 'read_json', return_value={
                    'criteria': [], 'version': 'fixture'}))
                stack.enter_context(patch.object(pipeline.plan, 'MAX_TAKES', 0))
                stack.enter_context(patch.object(pipeline, 'score', return_value={'complete': True}))
                stack.enter_context(patch.object(pipeline, '_status'))
                playable = stack.enter_context(patch.object(pipeline.playable_rules, 'evaluate'))
                result = pipeline.run(Path(tmp), Path(tmp), standards_root=Path(tmp), suite=name)
                self.assertTrue(result['complete'])
                playable.assert_not_called()

    def test_unaccepted_retry_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / 'call_002').mkdir()
            self.assertIsNone(llm.accepted_response(Path(tmp), 'call'))


if __name__ == '__main__':
    unittest.main()
