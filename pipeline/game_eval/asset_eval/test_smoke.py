"""Stdlib-only tests; safe to run without ML imports or an engine."""
from __future__ import annotations
import ast
import csv
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

from .common import OUTPUTS, dump, read, validate_out
from .inventory import inventory, object_delivery, tasks
from .preflight import glb_header
from .resources import MetricsDeferred, assert_metrics_idle, process_snapshot
from .run import make_row, metric_asset, selected_games


class SmokeTests(unittest.TestCase):
    def test_all_sources_parse_without_bytecode(self):
        files = list(Path(__file__).parent.glob('*.py'))
        self.assertGreaterEqual(len(files), 15)
        for p in files:
            ast.parse(p.read_text(), filename=str(p))

    def test_task_ids_match_long_delivery_ids(self):
        game = selected_games(['G001'])[0]
        task = next(t for t in tasks(game, 'obj') if t['task_id'] == 'G001_obj_005')
        delivery = object_delivery(game, task, 'obj', 'meshy')
        self.assertEqual(delivery.parent.name, 'G001_port_guard_arena_obj_005')
        self.assertTrue((delivery / 'model.glb').is_file())
        row = make_row(game, task, 'meshy', 'obj')
        self.assertTrue(row['delivered'])
        self.assertTrue(all(v['score'] is None for v in row['columns'].values()))

    def test_scene_is_dispatched_to_scene_renderer_and_has_image_adherence(self):
        from .render import standard_views
        scene = selected_games(['G001'])[0]
        task = tasks(scene, 'scene')[0]
        self.assertTrue(task['image_path'].endswith('/arena.jpg'))
        row = make_row(scene, task, 'meshy', 'scene')
        self.assertEqual(row['input_mode'], 'image_to_3d')
        from .render import STANDARD, RING, ring_views
        scene_manifest = {'views': [{'id': name} for name, _, _ in STANDARD + RING]}
        self.assertEqual(len(standard_views(scene_manifest, scope='scene')), 6)
        self.assertEqual(len(ring_views(scene_manifest)), 12)
        object_manifest = {'views': [{'id': 'V01_front'}, {'id': 'R01'}]}
        self.assertEqual([v['id'] for v in standard_views(object_manifest)], ['V01_front'])

    def test_renderer_adapter_has_same_18_views_for_scene_and_obj(self):
        from .render import configured_renderer
        with tempfile.TemporaryDirectory() as tmp:
            adapter = configured_renderer(Path(tmp), scope='scene')
            source = adapter.read_text()
            self.assertNotIn("const views=presetArg==='scene'?sceneViews:", source)
            self.assertIn('R12', source)
            self.assertIn('V06_three_quarter', source)
            self.assertIn("['global',45,30]", source)
            self.assertIn("['region_se',225,55,0.6,[0.25,0,0.25]]", source)
            self.assertIn("if(\"scene\"==='scene')object.traverse(o=>{if(o.isLight)o.intensity=0;});", source)
            provenance = read(Path(tmp) / 'provenance.json')
            self.assertTrue(provenance['source_sha256'])

    def test_scene_without_decimation_target_keeps_geometry_score_null(self):
        import inspect
        from .quality import geometry_quality
        source = inspect.getsource(geometry_quality)
        self.assertIn('triangle_relative_deviation', source)
        self.assertIn('if any(x is None for x in required)', source)

    def test_real_glb_header_is_not_a_quality_measurement(self):
        game = selected_games(['G001'])[0]
        task = next(t for t in tasks(game, 'obj') if t['task_id'] == 'G001_obj_005')
        result = glb_header(object_delivery(game, task, 'obj', 'meshy') / 'model.glb')
        self.assertTrue(result['header_ok'])
        self.assertLess(result['json_bytes_read'], result['file_bytes'])
        self.assertNotIn('geometry_subscore', result)
        self.assertNotIn('load_ok', result)

    def test_invalid_header_is_rejected(self):
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUTPUTS, prefix='_unit_') as tmp:
            p = Path(tmp) / 'synthetic_invalid.glb'
            p.write_bytes(b'not a real GLB')
            with self.assertRaisesRegex(ValueError, 'Truncated'):
                glb_header(p)

    def test_resource_gate_defers_whitebox_even_when_no_sol_is_visible(self):
        with patch('pipeline.game_eval.asset_eval.resources.process_snapshot',
                   return_value={'whitebox_batch': [{'pid': 123, 'ppid': 1}], 'sol': []}):
            with self.assertRaises(MetricsDeferred):
                assert_metrics_idle()

    def test_resource_gate_defers_orphan_sol(self):
        with patch('pipeline.game_eval.asset_eval.resources.process_snapshot',
                   return_value={'whitebox_batch': [], 'sol': [{'pid': 123, 'ppid': 1}]}):
            with self.assertRaises(MetricsDeferred):
                assert_metrics_idle()

    def test_metrics_guard_runs_before_any_optional_import(self):
        with patch('pipeline.game_eval.asset_eval.run.assert_metrics_idle', side_effect=MetricsDeferred('unit test')):
            with self.assertRaises(MetricsDeferred):
                metric_asset({}, {}, None, None, None, {}, True)
        for package in ('torch', 'numpy', 'pyiqa', 'trimesh', 'transformers'):
            self.assertNotIn(package, sys.modules)

    def test_process_parser_ignores_shell_command_text(self):
        # A shell whose -c string *mentions* the batch is not the batch itself.
        stdout = ('11 1 /bin/zsh -c "echo pipeline.game_eval.whitebox_eval.batch"\n'
                  '12 1 python -m pipeline.game_eval.whitebox_eval.batch --stage pipeline\n'
                  '13 12 codex exec --model gpt-6.1-sol -\n'
                  '14 13 /opt/bin/codex exec --model gpt-6.1-sol -\n')
        with patch('pipeline.game_eval.asset_eval.resources.subprocess.run') as p:
            p.return_value.stdout = stdout
            state = process_snapshot()
        self.assertEqual([x['pid'] for x in state['whitebox_batch']], [12])
        self.assertEqual([x['pid'] for x in state['sol']], [13])

    def test_output_write_guard_rejects_source_and_parent_directory(self):
        game = selected_games(['G001'])[0]
        for path in (game, OUTPUTS, Path(__file__).parent):
            with self.assertRaises(ValueError):
                validate_out(path)

    def test_non_finite_values_are_not_serialized(self):
        with tempfile.TemporaryDirectory(dir=OUTPUTS, prefix='_unit_') as tmp:
            p = Path(tmp) / 'synthetic.json'
            with self.assertRaises(ValueError):
                dump(p, {'score': float('nan')})
            self.assertFalse(p.exists())
            dump(p, {'score': None, 'notes': ['synthetic serialization test']})
            self.assertIsNone(read(p)['score'])

    def test_skip_rubric_content_is_explicit(self):
        inv = inventory(selected_games(['G001']), audit_rubric_content=False)
        self.assertFalse(inv['rubric_content_audited'])
        self.assertEqual(inv['coverage']['obj_tasks'], 6)
        self.assertEqual(inv['palette_games_count'], 1)

    def test_bounded_sampler_counts_only_owned_group(self):
        from .bounded import _usage, _seconds
        self.assertEqual(_seconds('1-02:03:04.5'), 93784.5)
        with patch('pipeline.game_eval.asset_eval.bounded.subprocess.run') as p:
            p.return_value.stdout = '777 1024 00:00.50\n888 9999 00:30.00\n777 512 00:00.25\n'
            self.assertEqual(_usage(777), (1536, .75, 2))

    def test_local_probe_requires_owned_bounded_launcher(self):
        from .local_probe import worker
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'bounded launcher'):
                worker(None)

    def test_bounded_rejects_large_cpu_target_before_launch(self):
        from .bounded import run_bounded
        with self.assertRaisesRegex(ValueError, '<=5%'):
            run_bounded('unused', [], OUTPUTS / '_should_not_exist', cpu_fraction=.5)

    def test_smoke_does_not_import_sol_judge(self):
        self.assertNotIn('pipeline.game_eval.asset_eval.rubric_judge', sys.modules)
        self.assertNotIn('pipeline.game_eval.whitebox_eval.codex', sys.modules)


if __name__ == '__main__':
    unittest.main()
