"""Regression tests for new pilot helpers; all fixtures stay in eval outputs."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from .common import OUTPUTS, sha
from .scene_bundle import extract_scene_glb
from .resources import MetricsDeferred


class AdditionalTests(unittest.TestCase):
    def test_media_imports_do_not_load_models_or_judge(self):
        code = '''import sys
from pipeline.eval.asset_eval import media_pilot, audio, video
for name in ('torch','numpy','transformers','pyiqa','trimesh','pipeline.eval.asset_eval.rubric_judge','pipeline.eval.stage1.codex'):
 assert name not in sys.modules, name
'''
        subprocess.run([sys.executable, '-B', '-c', code], check=True, timeout=30)

    def test_media_worker_defers_before_numpy_import(self):
        from .audio import signal_metrics
        with patch('pipeline.eval.asset_eval.resources.assert_metrics_idle', side_effect=MetricsDeferred('test')):
            with self.assertRaises(MetricsDeferred):
                signal_metrics('not-opened.wav')

    def test_media_pilot_defers_before_any_decode(self):
        from .media_pilot import run_pilot
        with patch('pipeline.eval.asset_eval.media_pilot.process_snapshot', return_value={'whitebox_batch':[1], 'sol':[]}), patch('pipeline.eval.asset_eval.media_pilot.low_priority'):
            with self.assertRaisesRegex(RuntimeError, 'deferred'):
                run_pilot()

    def test_scene_extraction_is_exact_and_readonly(self):
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=OUTPUTS) as tmp:
            root=Path(tmp); source=root/'input'; source.mkdir()
            archive=source/'scene.zip'
            with zipfile.ZipFile(archive,'w') as z:
                z.writestr('art/scene.glb', b'test GLB fixture')
                z.writestr('../../must_not_extract.txt', b'unsafe')
                z.writestr('project.godot', b'must not execute')
            digest=sha(archive)
            with patch('pipeline.eval.asset_eval.scene_bundle.ASSETS', source):
                extracted=extract_scene_glb(archive,root/'output',member='art/scene.glb')
                self.assertEqual(extracted.read_bytes(),b'test GLB fixture')
                self.assertEqual(sha(archive),digest)
                self.assertEqual(list((root/'output').iterdir()),[extracted])
                with self.assertRaises(FileExistsError):
                    extract_scene_glb(archive,root/'output',member='art/scene.glb')
                self.assertEqual(extracted.read_bytes(),b'test GLB fixture')
                with self.assertRaisesRegex(ValueError, 'exactly one'):
                    extract_scene_glb(archive,root/'missing',member='absent.glb')

    def test_scene_extraction_rejects_output_in_input(self):
        with self.assertRaises(ValueError):
            extract_scene_glb(Path('/tmp/not_asset.zip'),Path('/tmp/unsafe'),member='scene.glb')

    def test_audio_cer_does_not_mix_emotion_or_speaker_score(self):
        from .audio import cer
        self.assertEqual(cer('你好世界','你好世界'),0)
        self.assertEqual(cer('你好世界','你好世'),.25)
        self.assertIsNone(cer('','你好'))

    def test_video_frame_sampling_defers(self):
        from .video import sample_frames
        with tempfile.TemporaryDirectory(dir=OUTPUTS) as tmp:
            with patch('pipeline.eval.asset_eval.resources.assert_metrics_idle', side_effect=MetricsDeferred('test')):
                with self.assertRaises(MetricsDeferred):
                    sample_frames('not-opened.mp4',Path(tmp)/'frames')

    def test_scene_packages_have_user_provider_attribution(self):
        from .run import selected_games, make_row
        from .inventory import tasks, scene_bundles
        game=selected_games(['G001'])[0]
        task=tasks(game,'scene')[0]
        bundles=scene_bundles(game,task)
        self.assertTrue(bundles)
        self.assertTrue(all(b['provider'] == 'marble' for b in bundles))
        self.assertTrue(all(b['attribution']['attribution_source'] == 'user_confirmation' for b in bundles))
        row=make_row(game,task,'meshy','scene')
        self.assertFalse(row['delivered'])
        self.assertTrue(row['scene_packages'])
        marble_row=make_row(game,task,'marble','scene')
        self.assertTrue(marble_row['delivered'])
        self.assertIsNone(marble_row['asset_path'])
        self.assertTrue(marble_row['archive_source']['member'].endswith('scene.glb'))

    def test_video_quality_never_reweights_missing_component(self):
        from .video import quality_index
        self.assertIsNone(quality_index(None, 1, 100, 1))
        self.assertIsNone(quality_index(1, None, 100, 1))
        self.assertIsNone(quality_index(1, 1, None, 1))
        self.assertIsNone(quality_index(1, 1, 101, 1))
        self.assertEqual(quality_index(1, 1, 100, 1), 100)
        self.assertEqual(quality_index(0, 0, 0, 0), 0)

    def test_video_spec_has_actual_failure_and_missing_targets(self):
        from .video import specification
        actual={'width':1280, 'height':720, 'fps':24., 'duration_sec':8.}
        target={'resolution':'1280x720', 'fps':24, 'duration_sec':8}
        self.assertEqual(specification(actual, target)['score'], 1.)
        self.assertEqual(specification(actual, {**target, 'resolution':'1920x1080'})['resolution_score'], 0.)
        self.assertIsNone(specification(actual, {'fps':24})['score'])

    def test_clap_defers_before_torch_import(self):
        from .audio import Clap
        with patch('pipeline.eval.asset_eval.resources.assert_metrics_idle', side_effect=MetricsDeferred('test')):
            with self.assertRaises(MetricsDeferred):
                Clap()

    def test_video_rejects_model_invented_quote_without_repair(self):
        from .video import judge_input
        result={'checks':[{'prompt_quote':'invented clause', 'verdict':'PASS', 'evidence_frames':['F01'], 'reason':'invented'}], 'limitations':[]}
        with patch('pipeline.eval.asset_eval.rubric_judge.invoke', return_value=(result,None)):
            value=judge_input(OUTPUTS, {'prompt':'A real port'}, [{'id':'F01', 'judge_path':'not-opened.png'}])
        self.assertIsNone(value['score'])
        self.assertEqual(value['model_output'], result)
        self.assertEqual(value['failure_label'], 'sol_invalid_prompt_quotation')

    def test_video_partial_observability_counts_not_filled(self):
        from .video import judge_input
        result={'checks':[
            {'prompt_quote':'A port', 'verdict':'PASS', 'evidence_frames':['F01'], 'reason':'Visible'},
            {'prompt_quote':'two guards', 'verdict':'UNVERIFIED', 'evidence_frames':['F01'], 'reason':'Too small'},
            {'prompt_quote':'yellow light', 'verdict':'FAIL', 'evidence_frames':['F01'], 'reason':'Red'}], 'limitations':[]}
        with patch('pipeline.eval.asset_eval.rubric_judge.invoke', return_value=(result,None)):
            value=judge_input(OUTPUTS, {'prompt':'A port, two guards, yellow light'}, [{'id':'F01', 'judge_path':'not-opened.png'}])
        self.assertEqual(value['score'], .5)
        self.assertEqual(value['counts'], {'PASS':1, 'FAIL':1, 'UNVERIFIED':1})

    def test_media_scoring_import_is_lazy(self):
        code='''import sys
from pipeline.eval.asset_eval import media_scoring
for name in ('torch','numpy','transformers','pyiqa','trimesh','pipeline.eval.asset_eval.rubric_judge'):
 assert name not in sys.modules, name
'''
        subprocess.run([sys.executable, '-B', '-c', code], check=True, timeout=30)

    def test_video_existing_rubric_schema_has_exact_check_ids(self):
        from .video import judge_input
        rubric={'dimensions':[{'id':'requirement_compliance','checks':[{'id':'C01'}, {'id':'C02'}]},
                              {'id':'game_input_consistency','checks':[{'id':'G01'}]}]}
        result={'checks':{'C01':{'verdict':'PASS','evidence_frames':['F01'],'reason':'Visible'},
                          'C02':{'verdict':'UNVERIFIED','evidence_frames':['F01'],'reason':'Unobservable'}}, 'limitations':[]}
        with patch('pipeline.eval.asset_eval.rubric_judge.invoke', return_value=(result,None)) as invoke:
            value=judge_input(OUTPUTS, {'prompt':'Real scene'}, [{'id':'F01','judge_path':'not-opened.png'}], rubric)
            schema=invoke.call_args.args[3]
        self.assertEqual(set(schema['properties']['checks']['properties']), {'C01','C02'})
        self.assertFalse(schema['properties']['checks']['additionalProperties'])
        self.assertEqual(value['score'], 1.)
        self.assertEqual(value['counts']['UNVERIFIED'], 1)

    def test_reuse_rejects_outside_eval_source(self):
        from .media_scoring import reuse_character
        with self.assertRaisesRegex(ValueError, 'existing asset_eval run'):
            reuse_character(Path('/tmp'), {}, [], OUTPUTS)
