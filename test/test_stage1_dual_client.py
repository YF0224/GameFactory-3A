"""Pair qualification must reject unrelated windows and client-side prediction."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from pipeline.eval.stage1 import dual_client as dual


def states(x=0):
    return {role: {'pid':100+i,'peer_id':1 if i == 0 else 77,'peers':[77] if i == 0 else [1],
                   'room':'YUN-421','unix':10+x,
                   'state':{'players':{'1':{'pos':[0,0]},'2':{'pos':[x,0]}}}}
            for i,role in enumerate(dual.ROLES)}


class PairProofTests(unittest.TestCase):
    def test_real_client_input_replicated_in_host(self):
        proof = dual.validate_interaction(states(),states(1),'client')
        self.assertEqual(proof['observer'],'host')
        self.assertEqual(proof['distance'],1)

    def test_two_windows_not_same_session(self):
        for field,value in [('room','different'),('peers',[]),('pid',100),('peer_id',1)]:
            with self.subTest(field=field):
                after = states(1);after['client'][field] = value
                with self.assertRaises(ValueError): dual.validate_interaction(states(),after,'client')

    def test_client_prediction_does_not_count(self):
        after = states(1);after['host']['state']['players']['2']['pos'] = [0,0]
        with self.assertRaises(ValueError): dual.validate_interaction(states(),after,'client')

    def test_stale_trace_does_not_count(self):
        after = states(1);after['client']['unix'] = 10
        with self.assertRaises(ValueError): dual.validate_interaction(states(),after,'client')

    def test_missing_position_does_not_count(self):
        after = states(1);del after['host']['state']['players']['2']
        with self.assertRaises(ValueError): dual.validate_interaction(states(),after,'client')

    def test_uncertain_pair_never_writes_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'project';(project/'game').mkdir(parents=True)
            (project/'game/main.gd').write_text('source')
            delivery={'engine':'godot','model':'opus','game_id':'G043_airship_kitchen','project_root':str(project)}
            (root/'delivery.json').write_text(json.dumps(delivery))
            with patch.object(dual,'record_pair',return_value={'qualified':False}), patch.object(dual,'profile_for',return_value='opus_g043'):
                with self.assertRaises(dual.HarnessError):dual.run_playable(root,root/'out',models={})
            self.assertFalse((root/'out/playable_score.json').exists())
            self.assertFalse(json.loads((root/'out/status.json').read_text())['complete'])

    def test_pair_lock_releases_partial_acquisition(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=root/'gamefactory-sol-whitebox-gui.lock'
            other=root/'gamefactory-sol-whitebox-gui.slot1.lock'
            with other.open('a') as held:
                fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(dual.tempfile,'gettempdir',return_value=directory),patch.dict(os.environ,{'A3GAME_GUI_SLOTS':'2'}):
                    with self.assertRaises(dual.HarnessError):
                        with dual.pair_slots(wait_s=0): self.fail('must not enter with one slot busy')
                with base.open('a') as probe:
                    fcntl.flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)

    def test_ordered_pair_reservation_retains_first_slot_until_second_releases(self):
        import fcntl
        import threading
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);base=root/'gamefactory-sol-whitebox-gui.lock'
            other=root/'gamefactory-sol-whitebox-gui.slot1.lock'
            waiting=threading.Event();entered=threading.Event();failures=[]
            real_flock=fcntl.flock
            def tracked(handle,flags):
                try:return real_flock(handle,flags)
                except BlockingIOError:
                    if str(getattr(handle,'name',''))==str(other):waiting.set()
                    raise
            def worker():
                try:
                    with dual.pair_slots(wait_s=3):entered.set()
                except Exception as exc:failures.append(exc)
            with other.open('a') as held:
                real_flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(dual.tempfile,'gettempdir',return_value=directory),patch.dict(os.environ,{'A3GAME_GUI_SLOTS':'2'}),patch.object(dual.fcntl,'flock',side_effect=tracked):
                    thread=threading.Thread(target=worker);thread.start()
                    try:
                        self.assertTrue(waiting.wait(1));self.assertFalse(entered.is_set())
                        with base.open('a') as probe:
                            with self.assertRaises(BlockingIOError):real_flock(probe,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    finally:
                        real_flock(held,fcntl.LOCK_UN);thread.join(4)
                    self.assertTrue(entered.is_set());self.assertFalse(failures)

    def test_no_gameplay_mutation_in_observer(self):
        source=dual.OBSERVER.read_text()
        for forbidden in ('.rpc(', '.rpc_id(', 'call("', 'set("', '.emit(', '--bot', 'Input.action_press'):
            self.assertNotIn(forbidden,source)
        self.assertIn('Input.parse_input_event',source)



class OrchestrationTests(unittest.TestCase):
    """Exercise scheduling and publication boundaries without launching engines."""
    def setup_run(self, stack, root, outcomes):
        from contextlib import ExitStack
        project=root/'project';project.mkdir();(project/'source.gd').write_text('original')
        (root/'delivery.json').write_text(json.dumps({'engine':'godot','model':'opus','game_id':'G043_airship_kitchen','project_root':str(project)}))
        stack.enter_context(patch.object(dual,'profile_for',return_value='opus_g043'))
        plans=[]; recordings=[]
        def plan(project,take,**kwargs):
            plans.append(kwargs)
            value={'protocol':dual.VERSION,'duration_s':75,'planner':'gpt-6-astra','feedback':kwargs['feedback']}
            dual.write_json(take/'plan.json',value)
            return value
        def record(project,out,**kwargs):
            self.assertTrue((out.parent/'plan.json').exists())
            recordings.append(out)
            result={'qualified':outcomes[len(recordings)-1][0],'required_real_clients':2,'version':dual.VERSION}
            dual.write_json(out/'pair_receipt.json',result)
            return result
        def rules(out,pairs):
            index=int(pairs[-1].parent.name[-2:])-1
            return {'play.import':'PASS','play.launch':'PASS','play.operate':outcomes[index][1]}, {'native':'test fixture'}
        stack.enter_context(patch.object(dual,'make_plan',side_effect=plan))
        stack.enter_context(patch.object(dual,'record_pair',side_effect=record))
        stack.enter_context(patch.object(dual,'verify_pair',side_effect=lambda p,project:dual.read_json(p/'pair_receipt.json')))
        stack.enter_context(patch.object(dual,'_rules',side_effect=rules))
        stack.enter_context(patch.object(dual,'cleanup_projects',return_value={'complete':True}))
        return plans, recordings

    def test_second_review_receives_feedback_and_resume_does_not_record(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory)
            plans,recordings=self.setup_run(stack,root,[(True,'UNVERIFIED'),(True,'PASS')])
            result=dual.run_playable(root,root/'out',models={'planner':'gpt-6-astra'})
            self.assertEqual(len(recordings),2)
            self.assertIsNone(plans[0]['feedback'])
            self.assertEqual(plans[1]['feedback']['checks']['play.operate'],'UNVERIFIED')
            from pipeline.eval.stage1.prepare import SAMPLES
            self.assertEqual(plans[0]['requirement'].read_bytes(),(SAMPLES/'G043_airship_kitchen/general_requirement.txt').read_bytes())
            self.assertEqual(result['checks']['play.operate'],'PASS')
            status=dual.read_json(root/'out/status.json')
            self.assertEqual(status['state'],'done');self.assertNotIn('status',status)
            again=dual.run_playable(root,root/'out',models={'planner':'gpt-6-astra'})
            self.assertEqual(again,result);self.assertEqual(len(recordings),2)

    def test_local_pass_without_peer_interaction_never_scores(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory)
            plans,recordings=self.setup_run(stack,root,[(False,'PASS'),(False,'PASS')])
            with self.assertRaises(dual.HarnessError):dual.run_playable(root,root/'out',models={'planner':'gpt-6-astra'})
            self.assertFalse((root/'out/playable_score.json').exists())
            self.assertEqual(len(recordings),2)
            self.assertTrue(all((p/'pair_receipt.json').exists() for p in recordings))

    def test_unrelated_second_world_cannot_upgrade_first_qualified_take(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory)
            self.setup_run(stack,root,[(True,'UNVERIFIED'),(False,'PASS')])
            result=dual.run_playable(root,root/'out',models={'planner':'gpt-6-astra'})
            self.assertEqual(result['checks']['play.operate'],'UNVERIFIED')
            self.assertIn('take_01',result['pair_evidence_receipt'])

    def test_interrupted_native_attempt_is_preserved(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root=Path(directory)
            plans,recordings=self.setup_run(stack,root,[(True,'PASS')])
            existing=root/'out/takes/take_01/pair';existing.mkdir(parents=True)
            (existing/'engine.log').write_text('partial evidence')
            with self.assertRaisesRegex(dual.HarnessError,'interrupted native attempt'):
                dual.run_playable(root,root/'out',models={'planner':'gpt-6-astra'})
            self.assertEqual(recordings,[])
            self.assertEqual((existing/'engine.log').read_text(),'partial evidence')


class CleanupTests(unittest.TestCase):
    def test_only_owned_qualified_copies_removed_and_receipt_resumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);out=root/'out';pair=out/'takes/take_01/pair'
            original=root/'original';original.mkdir();(original/'source.gd').write_text('original')
            launch={};cleanup={}
            for role in dual.ROLES:
                project=pair/'projects'/role;project.mkdir(parents=True)
                (project/'source.gd').write_text('original')
                launch[role]={'project':str(project),'pid':99999999}
                cleanup[role]={'process_cleanup':True}
            dual.write_json(out/'playable_score.json',{'complete':True,'required_real_clients':2})
            dual.write_json(pair/'pair_receipt.json',{'qualified':True,'cleanup':cleanup})
            dual.write_json(pair/'source_binding.json',{'project':str(original),'files':dual.source_hashes(original)})
            dual.write_json(pair/'launch.json',launch)
            (pair/'evidence.png').write_bytes(b'original pixels')
            with patch.object(dual.os,'kill',side_effect=ProcessLookupError):
                result=dual.cleanup_projects(out,[pair]);again=dual.cleanup_projects(out,[pair])
            self.assertEqual(result,again);self.assertEqual(result['deleted_bytes'],16)
            self.assertTrue((original/'source.gd').exists());self.assertTrue((pair/'evidence.png').exists())
            self.assertFalse((pair/'projects/host').exists());self.assertFalse((pair/'projects/client').exists())

class PlanTests(unittest.TestCase):
    def test_requirement_and_source_reach_astra_and_accepted_plan_resumes(self):
        from pipeline.eval.stage1 import dual_client_plan as planner
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);project=root/'original';project.mkdir()
            (project/'main.gd').write_text('host\njoin\nreplicate\n')
            requirement=root/'requirement.txt';requirement.write_text('Original case requirement SENTINEL')
            review={'duration_s':75,'entry_supported':True,'entry_review':'source host/join',
                    'replication_review':'source replicated state','product_limitations':[],
                    'source_references':[{'path':'main.gd','line':i,'finding':'source'} for i in (1,2,3)],
                    'actions':[{'role':r,'key':k,'duration_s':.8,'wait_s':.8,'purpose':'move'} for r in dual.ROLES for k in ('D','A')]}
            seen=[]
            def call(calls,**kwargs):
                seen.append(kwargs)
                kwargs['validator'](review)
                response=calls/'source_review/response.json'
                dual.write_json(response,review)
                dual.write_json(calls/'source_review/accepted_response.json',{'path':'response.json','sha256':dual.sha256(response),'attempt':1})
                return review
            profile={'fixture':{'reviewed_sha256':{'main.gd':dual.sha256(project/'main.gd')}}}
            original_read=planner.read_json
            def read(path):
                return profile if Path(path).name=='dual_client_profiles.json' else original_read(path)
            with patch.object(planner,'read_json',side_effect=read),patch.object(planner.llm,'call_model',side_effect=call):
                first=planner.make_plan(project,root/'take',profile='fixture',model='gpt-6-astra',requirement=requirement)
                second=planner.make_plan(project,root/'take',profile='fixture',model='gpt-6-astra',requirement=requirement)
                self.assertEqual(first,second);self.assertEqual(len(seen),1)
                self.assertIn('Original case requirement SENTINEL',seen[0]['prompt'])
                self.assertIn('1: host\n2: join\n3: replicate',seen[0]['prompt'])
                self.assertEqual(seen[0]['model'],'gpt-6-astra')
                requirement.write_text('changed')
                with self.assertRaisesRegex(dual.HarnessError,'binding differs'):
                    planner.make_plan(project,root/'take',profile='fixture',model='gpt-6-astra',requirement=requirement)


if __name__ == '__main__': unittest.main()
