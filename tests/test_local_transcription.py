"""Opt-in installed offline Whisper acceptance with Windows synthetic speech."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workspace_service import Workspace


@unittest.skipUnless(os.environ.get('WORKBENCH_WHISPER_TEST')=='1' and os.name=='nt','Opt-in local speech environment')
class LocalSpeechTests(unittest.TestCase):
    def test_synthetic_speech_transcribe_edit_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);audio=root/'speech.wav';video=root/'speech.mp4'
            code="Add-Type -AssemblyName System.Speech; $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer; $speaker.SetOutputToWaveFile($env:WB_TEST_SPEECH); $speaker.Speak('This is a local video editing workbench. Please check the subtitles before exporting the video.'); $speaker.Dispose()"
            subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],env={**os.environ,'WB_TEST_SPEECH':str(audio)},check=True,capture_output=True)
            ff=os.environ['TALKING_EDIT_FFMPEG']
            subprocess.run([ff,'-v','error','-y','-f','lavfi','-i','color=c=green:s=320x180:r=30','-i',str(audio),'-shortest','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(video)],check=True)
            ws=Workspace(root/'index')
            try:
                entry=ws.create('talk','Offline speech acceptance',str(root/'projects'));pid=entry['id']
                ws.call(pid,'import',{'file':str(video),'kind':'video'})
                state=ws.call(pid,'show')['project']
                ws.call(pid,'update',{'patch':{'transcribe_language':'en'},'revision':state['revision']})
                result=ws.call(pid,'transcribe')
                self.assertTrue(result['cues']);self.assertFalse(result['listeningReviewed'])
                self.assertEqual(result['language'],'en')
                state=ws.call(pid,'show')['project'];cues=state['cues'];cues[0]['text']='Edited synthetic subtitle'
                ws.call(pid,'update',{'patch':{'cues':cues},'revision':state['revision']})
                request=ws.call(pid,'review',{'stage':'roughcut'})
                ws.call(pid,'decide',{'request_id':request['id'],'revision':request['revision'],'action':'confirm'})
                output=ws.call(pid,'render')
                self.assertTrue(output['technicalPass'])
                self.assertIn('Edited synthetic subtitle',(Path(entry['root'])/output['subtitles']).read_text(encoding='utf-8'))
            finally:ws.close()


if __name__=='__main__':unittest.main()
