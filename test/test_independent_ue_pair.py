import unittest
from pipeline.eval.stage1.independent_ue_pair import aggregate, validate_request, short_manifest, MODE
from pipeline.eval.stage1.llm import HarnessError
from pipeline.eval.stage1.playable_rules import IDS

class PairRulesTests(unittest.TestCase):
    def test_both_clients_must_pass(self):
        a = {k:'PASS' for k in IDS}
        b = {**a,'play.operate':'UNVERIFIED'}
        self.assertEqual(aggregate({'client_1':a,'client_2':b})['play.operate'],'UNVERIFIED')
        self.assertEqual(aggregate({'client_1':a,'client_2':{**b,'play.launch':'FAIL'}})['play.launch'],'FAIL')

    def test_missing_client_and_tool_failure_are_unscored(self):
        a = {k:'PASS' for k in IDS}
        with self.assertRaises(HarnessError):aggregate({'client_1':a})
        with self.assertRaises(HarnessError):aggregate({'client_1':a,'client_2':{**a,'play.import':'HARNESS_ERROR'}})
        with self.assertRaises(HarnessError):aggregate({'client_1':a,'client_2':{}})

    def test_independent_mode_requires_explicit_authorization(self):
        d = {'engine':'ue5','required_real_clients':2}
        auth = {'mode':MODE,'user_instruction':'双端可以启动两个独立的客户端','network_qualification':False}
        validate_request(d,auth)
        for bad in [{}, {**auth,'network_qualification':True}]:
            with self.assertRaises(HarnessError):validate_request(d,bad)
        with self.assertRaises(HarnessError):validate_request({**d,'engine':'godot'},auth)
        with self.assertRaises(HarnessError):validate_request({**d,'required_real_clients':1},auth)

    def test_preserves_formal_75_second_budget(self):
        m = {'budget':{'gameplay_ms':30000,'recording_ms':30000,'total_wall_clock_ms':120000,'engine_call_ms':100000}}
        s = short_manifest(m)
        self.assertEqual(s['budget']['gameplay_ms'],75000)
        self.assertEqual(s['budget']['recording_ms'],75000)
        self.assertEqual(m['budget']['gameplay_ms'],30000)
        self.assertGreaterEqual(s['budget']['engine_call_ms'],s['budget']['total_wall_clock_ms'])

if __name__=='__main__':unittest.main()
