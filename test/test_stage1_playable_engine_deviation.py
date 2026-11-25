"""Playable-only authored-engine deviation must retain the source/requirement binding."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.eval.stage1 import delivery
from pipeline.eval.stage1.paths import sha256


class DeviationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.game = 'G010_orbital_extraction'
        self.run = root / self.game / 'run'
        self.run.mkdir(parents=True)
        self.project = root / 'project'
        self.project.mkdir()
        (self.project / 'project.godot').write_text('[application]\nrun/main_scene="res://main.tscn"\n')
        self.samples = root / 'samples'
        req = self.samples / self.game / 'general_requirement.txt'
        req.parent.mkdir(parents=True)
        req.write_text('engine: unity3d\nrequired_real_clients: 1\n')
        orig = root / 'original_requirement.txt'
        orig.write_bytes(req.read_bytes())
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({'project': str(self.project), 'exclusions': [], 'symlinks': [],
            'files': {'project.godot': sha256(self.project / 'project.godot')}}))
        self.selection = root / 'selection.json'
        self.selected = {'schema': 'kimi-original-selection.v1', 'status': 'SELECTED_ORIGINAL_PROJECT',
            'target': {'model': 'Kimi', 'game_id': self.game, 'engine': 'godot', 'entry': 'project.godot',
                       'project': str(self.project), 'source': str(self.selection)},
            'source_manifest': {'path': str(manifest), 'sha256': sha256(manifest)},
            'requirements': {'current': {'path': str(req), 'sha256': sha256(req)},
                             'original_case_input': {'path': str(orig), 'sha256': sha256(orig)}}}
        self.selection.write_text(json.dumps(self.selected))
        self.data = {'schema': 'bench.delivery.v1', 'stage': 'stage1', 'model': 'kimi', 'game_id': self.game,
            'run_id': 'run', 'engine': 'godot', 'project_root': str(self.project), 'entry': 'project.godot',
            'created_at': '2026-11-09', 'generator': {}, 'legacy': True,
            'engine_deviation': {'policy': 'authored_engine_playable_only.v1', 'expected': 'unity3d',
                'actual': 'godot', 'selection_path': str(self.selection), 'selection_sha256': sha256(self.selection)}}
        self.patcher = patch.object(delivery, 'SAMPLES', self.samples)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def validate(self, data=None, playable=True):
        (self.run / 'delivery.json').write_text(json.dumps(self.data if data is None else data))
        return delivery.validate(self.run, playable_only=playable)

    def test_opt_in_accepts_source_bound_actual_engine_only(self):
        self.assertEqual([], self.validate())
        self.assertTrue(self.validate(playable=False))

    def test_ordinary_same_engine_still_accepted(self):
        data = copy.deepcopy(self.data)
        data['engine'] = 'unity3d'
        data.pop('engine_deviation')
        self.assertEqual([], self.validate(data, playable=False))

    def test_mismatch_without_explicit_record_rejected(self):
        self.data.pop('engine_deviation')
        self.assertTrue(self.validate())

    def test_wrong_selection_sha_rejected(self):
        self.data['engine_deviation']['selection_sha256'] = '0' * 64
        self.assertTrue(self.validate())

    def test_authored_entry_drift_rejected(self):
        (self.project / 'project.godot').write_text('[application]\nchanged=true')
        self.assertTrue(self.validate())

    def test_original_requirement_drift_rejected(self):
        Path(self.selected['requirements']['original_case_input']['path']).write_text('engine: godot\n')
        self.assertTrue(self.validate())

    def test_stage3_not_covered(self):
        self.data.update(stage='stage3', source={}, rounds_used=0)
        self.assertTrue(self.validate())

    def test_wrong_model_not_covered(self):
        self.data['model'] = 'sol'
        self.assertTrue(self.validate())

    def test_actual_engine_marker_cannot_be_missing(self):
        (self.project / 'project.godot').unlink()
        self.assertTrue(self.validate())


if __name__ == '__main__':
    unittest.main()
