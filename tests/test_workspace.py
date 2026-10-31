import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/talking-edit/scripts'))
from workspace import categories,choose,AREAS
from core import Project,EditError
class AreasTest(unittest.TestCase):
 def test_fresh_install_has_bundled_narration_adapter(self):
  from unittest.mock import patch
  import os,hashlib
  from registry import specs
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'TALKING_EDIT_HOME':d}):
   item=next(x for x in specs() if x['id']=='narration-footage-v0-1')
   self.assertTrue(Path(item['instructions']).is_file())
   self.assertEqual(hashlib.sha256(Path(item['instructions']).read_bytes()).hexdigest(),item['instructions_hash'])
 def test_scoped(self):
  self.assertEqual(categories({'id':'fredtalk-motion'}),['talk'])
  self.assertEqual(categories({'id':'remotion-evidence'}),['talk','hybrid'])
  self.assertEqual(categories({'id':'narration-footage-v0-1'}),['talk','hybrid'])
  self.assertEqual(categories({'id':'unknown-style'}),[])
  self.assertEqual(categories({'id':'new','workspace_categories':['hybrid']}),['hybrid'])
 def test_original_talking_styles_retained(self):
  from registry import SPECS
  previous=['fredtalk-motion','remotion-plugin','remotion-gold','remotion-evidence','none','narration-footage-v0-1']
  for key in previous:self.assertIn('talk',categories({'id':key}),key)
  for key in ['remotion-plugin','remotion-evidence','narration-footage-v0-1']:self.assertIn('hybrid',categories({'id':key}),key)
 def test_no_project_approval(self):
  with tempfile.TemporaryDirectory() as d:
   p=Project.create(d,'test');before=p.state();choose(p,'hybrid');self.assertEqual(before,p.state());self.assertFalse(p.approved('final'));self.assertEqual(json.loads((p.meta/'workspace.json').read_text())['area'],'hybrid')
 def test_invalid_area(self):
  with tempfile.TemporaryDirectory() as d:
   p=Project.create(d,'test')
   with self.assertRaises(EditError):choose(p,'anything')
if __name__=='__main__':unittest.main()
