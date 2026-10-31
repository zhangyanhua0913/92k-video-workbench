"""Opt-in installed-template acceptance; no model calls or dependency installation intended."""
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workspace_service import Workspace


@unittest.skipUnless(os.environ.get('WORKBENCH_GOLD_TEST')=='1','Opt-in existing Remotion environment acceptance')
class GoldMediaTests(unittest.TestCase):
    def test_real_template_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);ws=Workspace(root/'index')
            try:
                entry=ws.create('talk','Gold synthetic acceptance',str(root/'projects'));pid=entry['id']
                video=root/'test.mp4';ff=os.environ['TALKING_EDIT_FFMPEG']
                subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=30:d=3','-f','lavfi','-i','sine=frequency=440:duration=3','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(video)],check=True)
                ws.call(pid,'import',{'file':str(video),'kind':'video'})
                s=ws.call(pid,'show')['project']
                ws.call(pid,'update',{'revision':s['revision'],'patch':{'cues':[{'id':'cue','start':0,'end':3,'text':'Synthetic gold title'}],'workflow':{**s['workflow'],'packaging':'remotion-gold'}}})
                r=ws.call(pid,'review',{'stage':'roughcut'})
                ws.call(pid,'decide',{'request_id':r['id'],'revision':r['revision'],'action':'confirm'})
                result=ws.call(pid,'auto-gold');self.assertEqual(result['scene_count'],1)
                output=ws.call(pid,'render')
                self.assertTrue(output['technicalPass']);self.assertFalse(output['listeningReviewed'])
                self.assertEqual(output['animation_count'],1);self.assertAlmostEqual(output['duration'],3,delta=.15)
                self.assertFalse(ws.snapshot(pid)['state']['final_confirmed'])
                subprocess.run([ff,'-v','error','-i',str(Path(entry['root'])/output['file']),'-f','null','-'],check=True)
            finally:ws.close()


if __name__=='__main__':unittest.main()
