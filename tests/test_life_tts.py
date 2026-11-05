import sys,tempfile,unittest,json,io
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from life_tts import LifeTTS,LifeTTSError,SPEAKER
class Tests(unittest.TestCase):
 def test_private_storage_and_paid_contract(self):
  with tempfile.TemporaryDirectory() as d:
   t=LifeTTS(d);key='sk-'+('offline'*5);status=t.configure({'key':key})
   self.assertNotIn(key,json.dumps(status));self.assertNotIn(key.encode(),t.keyfile.read_bytes());self.assertTrue(status['configured'])
   with self.assertRaises(LifeTTSError):t.synthesize({'text':'hello'})
   class Response:
    headers=type('Headers',(),{'get_content_type':lambda s:'audio/mpeg'})()
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def read(self,n):return b'ID3'+b'0'*256
   with patch('life_tts.build_opener') as op:
    op.return_value.open.return_value=Response();result=t.synthesize({'text':'hello','allow_paid':True})
    req=op.return_value.open.call_args.args[0];data=json.loads(req.data)
    self.assertEqual(data['speaker'],SPEAKER);self.assertEqual(data['resource_id'],'seed-icl-2.0');self.assertEqual(data['audio_params'],{'format':'mp3','sample_rate':24000});self.assertEqual(req.get_header('Authorization'),'Bearer '+key)
    self.assertNotIn(key,json.dumps(result));self.assertTrue(t.audio(result['id']).is_file());self.assertEqual(op.return_value.open.call_count,1)
   t.configure({'clear':True});self.assertFalse(t.status()['configured'])
 def test_error_body_not_exposed_no_retry(self):
  with tempfile.TemporaryDirectory() as d:
   t=LifeTTS(d);t.configure({'key':'sk-'+('offline'*5)})
   with patch('life_tts.build_opener') as op:
    op.return_value.open.side_effect=HTTPError('https://example.invalid',401,'bad',{},io.BytesIO(b'private reflected credential'))
    with self.assertRaises(LifeTTSError) as e:t.synthesize({'text':'hello','allow_paid':True})
    self.assertNotIn('private',str(e.exception));self.assertEqual(op.return_value.open.call_count,1)
   self.assertEqual(json.loads(next(t.root.glob('*.json')).read_text())['status'],'unknown')
if __name__=='__main__':unittest.main()
