import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from pipeline.eval.repair import ue_compile_compat as c
from pipeline.eval.stage1.llm import HarnessError

class AuthorizationTests(unittest.TestCase):
 def test_stage3_unchanged_and_other_suites_rejected(self):
  self.assertEqual(c._validate_identity(Path('/tmp/test'),{'suite':'stage3','engine':'ue5'},{}),20*2**30)
  for m in [{'suite':'stage1','engine':'ue5'},{'suite':'stage3','engine':'unity3d'},{'suite':'foreign','engine':'ue5'}]:
   with self.assertRaises(HarnessError):c._validate_identity(Path('/tmp/test'),m,{})
 def test_stage1_requires_exact_authorized_source_output_and_parent(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp).resolve();out=root/'runs/G035';parent=root/'parent.json';parent.write_text('{"state":"failed"}')
   m={'suite':'stage1','engine':'ue5','game_id':'G035_rift_expedition','delivery':{'model':'sol'},'snapshot_digest':'snapshot','project_source':'/original/sol/G035','project_digest':'source'}
   auth={'version':c.STAGE1_AUTHORIZATION,'user_instruction':'剩下几个都动态编译成ue5.4启动一下','cases':['G035'],'evaluation_directories':[str(out)],'source_bindings':{'G035':m['project_source']},'source_digests':{'G035':m['project_digest']},'target_engine':'5.4','reserve_bytes':8*2**30}
   path=root/'authorization.json';path.write_text(json.dumps(auth))
   entry={'snapshot_digest':'snapshot','stage1_authorization':{'path':str(path),'sha256':c.digest(path)},'parent_failure':{'path':str(parent),'sha256':c.digest(parent)}}
   with patch.object(c,'STAGE1_ROOT',root):
    self.assertEqual(c._validate_identity(out,m,entry),8*2**30)
    for bad in [{**m,'delivery':{'model':'kimi'}},{**m,'project_digest':'changed'},{**m,'game_id':'G040_other'}]:
     with self.assertRaises(HarnessError):c._validate_identity(out,bad,entry)
    with self.assertRaises(HarnessError):c._validate_identity(root/'foreign',m,entry)
    parent.write_text('changed')
    with self.assertRaises(HarnessError):c._validate_identity(out,m,entry)
if __name__=='__main__':unittest.main()
