import sys,unittest,tempfile,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/narration-footage/scripts'))
from footage import audit,MediaParser,secure_url,local
class Test(unittest.TestCase):
 def test_discovery(self):
  p=MediaParser('https://example.com/a/');p.feed('<video><source src=/clip.webm type=video/webm><source src="https://example.com/clip.mp4"></video>');self.assertEqual(len(p.items),2);self.assertEqual(p.items[0]['url'],'https://example.com/clip.webm')
 def test_private(self):
  for url in ['http://example.com','https://127.0.0.1/a','https://u:p@example.com/a']:
   with self.assertRaises(ValueError):secure_url(url)
 def test_escape(self):
  with self.assertRaises(ValueError):local(Path(tempfile.gettempdir())/'scope','../escape')
 def test_audit(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);(root/'a.mp4').write_bytes(b'fixture');a={'file':'a.mp4','sha256':hashlib.sha256(b'fixture').hexdigest(),'duration':4,'source_page':'https://example.com','product':'v4'};s={'id':'s','kind':'video','asset':'a','start':0,'end':3,'product':'v4','visually_reviewed':True,'match_reason':'matched action'};plan={'assets':{'a':a},'timeline':[s]};self.assertTrue(audit(root,plan)['ok']);s['product']='v3';self.assertFalse(audit(root,plan)['ok']);s['product']='v4';s['source_in']=3;self.assertFalse(audit(root,plan)['ok']);s['source_in']=0;(root/'a.mp4').write_bytes(b'changed');self.assertFalse(audit(root,plan)['ok'])
unittest.main()
