import copy
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/92k-video-director/scripts'
sys.path.insert(0, str(SCRIPTS))
from core import Project, DirectorError, shot_hash, dump
from provider import plan_operation, quote_operation, submit_operation, poll_operation, download_operation, classify, Client, resolve_request, redo_operation
from vault import Vault
from web import ReviewServer


class FakeVault:
    def __init__(self):
        self.active = 'credential-example-a'
    def status(self):
        return {'active': self.active, 'configured': True, 'entries': []}
    def get(self, identifier=None):
        return 'dummy-example-key'


class FakeClient:
    def __init__(self):
        self.vault = FakeVault()
        self.posts = []
        self.points = 10
        self.lose_submit = False
        self.status = 'running'
        self.bill = 'paid'
        self.kind = 'video'
    def models(self):
        return {'models': [{'model_id': 'dreamface:dreamvideo', 'status': 'published', 'fields': {'images': {'kind': 'image'}}}, {'model_id': 'dreamface:tts-common', 'status': 'published', 'fields': {}}, {'model_id': 'dreamface:avatar', 'status': 'published', 'fields': {'image': {'kind':'image'}, 'audio': {'kind':'audio'}}}]}
    def request(self, path, body=None, credential=None, **kwargs):
        if path.endswith('/quotes'):
            return {'quote_id':'quote-example', 'points':self.points, 'expires':time.time()+600}
        if path.endswith('/tasks'):
            tid = kwargs['headers']['Idempotency-Key']
            self.posts.append((tid, credential))
            if self.lose_submit:
                raise DirectorError('模拟丢失回执', 'network_unknown')
            return {'task_id':tid, 'status':'created'}
        tid = path.rsplit('/', 1)[1]
        return {'task_id':tid,'status':self.status,'billing':{'status':self.bill},'result_ready':self.status=='succeeded','media_type':self.kind}
    def upload(self, path, kind, credential):
        return {'asset_id':'asset-example-'+kind}
    def download(self, tid, credential, target, kind):
        path = Path(str(target) + ('.wav' if kind=='audio' else '.mp4'))
        path.write_bytes(b'example-media')
        return path


def sample():
    return {'title':'测试作品','format':'9:16','script':'测试脚本','shots':[{'id':'shot-1','method':'video','visual':'场景','prompt':'场景','line':'','duration':5}]}


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Project.create(Path(self.tmp.name)/'project', sample())
        self.client = FakeClient()
    def tearDown(self):
        self.tmp.cleanup()
    def op(self, shot='shot-1', ceiling=10):
        return plan_operation(self.project, shot, 'visual', {'model_id':'dreamface:dreamvideo','parameters':{'prompt':'场景','duration':5},'assets':{}}, ceiling, self.client)
    def approve(self, cap=10):
        rid=self.project.open_review('budget')
        return self.project.decide(rid,'confirm',self.project.state()['revision'],cap=cap)
    def test_create_mirror(self):
        self.assertEqual(json.loads((self.project.root/'project.json').read_text(encoding='utf-8'))['revision'],1)
    def test_duplicate_create_refused(self):
        with self.assertRaises(DirectorError):Project.create(self.project.root,sample())
    def test_credentials_rejected(self):
        data=self.project.state();data['user_key']='dummy-example-key'
        with self.assertRaises(DirectorError):self.project.update(data,1)
    def test_unknown_method_rejected(self):
        data=self.project.state();data['shots'][0]['method']='anything'
        with self.assertRaises(DirectorError):self.project.update(data,1)
    def test_nonfinite_duration_rejected(self):
        data=self.project.state();data['shots'][0]['duration']=float('nan')
        with self.assertRaises(DirectorError):self.project.update(data,1)
    def test_duplicate_shot_rejected(self):
        data=self.project.state();data['shots']*=2
        with self.assertRaises(DirectorError):self.project.update(data,1)
    def test_traversal_refused(self):
        with self.assertRaises(DirectorError):self.project.inside('../outside')
    def test_review_reused(self):
        self.assertEqual(self.project.open_review('storyboard'),self.project.open_review('storyboard'))
    def test_stale_review_refused(self):
        rid=self.project.open_review('storyboard');self.project.update(self.project.state(),1)
        with self.assertRaises(DirectorError):self.project.decide(rid,'confirm',1)
    def test_duplicate_decision_returns_original(self):
        rid=self.project.open_review('storyboard');first=self.project.decide(rid,'confirm',1)
        self.assertEqual(first,self.project.decide(rid,'confirm',1))
    def test_storyboard_confirm_returns_edited_state(self):
        rid=self.project.open_review('storyboard');data=self.project.state();data['shots'][0]['line']='用户改写'
        result=self.project.decide(rid,'confirm',1,data=data)
        self.assertEqual(result['revision'],2);self.assertEqual(self.project.state()['shots'][0]['line'],'用户改写')
    def test_atomic_update_preserves_other_shot(self):
        data=self.project.state();data['shots'].append({'id':'shot-2','method':'local_image','duration':3});self.project.update(data,1)
        for s in self.project.state()['shots']:
            path=self.project.root/'media'/('example-'+s['id']+'.png');path.write_bytes(b'example')
            self.project.add_candidate(s['id'],path.relative_to(self.project.root).as_posix())
        state=self.project.state();rid=self.project.open_review('assets');picks={s['id']:s['candidates'][0]['file'] for s in state['shots']};self.project.decide(rid,'confirm',2,selections=picks)
        state=self.project.state();kept=state['shots'][1]['accepted'];state['shots'][0]['visual']='改场景';self.project.update(state,3)
        current=self.project.state();self.assertIsNone(current['shots'][0]['accepted']);self.assertEqual(current['shots'][1]['accepted'],kept)
    def test_unreviewed_candidates_not_accepted(self):
        path=self.project.root/'media/example.png';path.write_bytes(b'example');self.project.add_candidate('shot-1','media/example.png')
        self.assertIsNone(self.project.state()['shots'][0]['accepted'])
    def test_missing_candidate_cannot_accept(self):
        rid=self.project.open_review('assets')
        with self.assertRaises(DirectorError):self.project.decide(rid,'confirm',1,selections={'shot-1':'media/missing.png'})
    def test_old_candidate_cannot_accept(self):
        path=self.project.root/'media/example.png';path.write_bytes(b'example');self.project.add_candidate('shot-1','media/example.png')
        state=self.project.state();state['shots'][0]['visual']='改了';self.project.update(state,1);rid=self.project.open_review('assets')
        with self.assertRaises(DirectorError):self.project.decide(rid,'confirm',2,selections={'shot-1':'media/example.png'})
    def test_final_requires_render(self):
        rid=self.project.open_review('final')
        with self.assertRaises(DirectorError):self.project.decide(rid,'confirm',1)
    def test_planning_deduplicates(self):
        self.assertEqual(self.op()['id'],self.op()['id'])
    def test_unsupported_model_refused(self):
        with self.assertRaises(DirectorError):plan_operation(self.project,'shot-1','visual',{'model_id':'unsupported','parameters':{},'assets':{}},10,self.client)
    def test_zero_budget_no_implicit_spend(self):
        self.op()
        with self.assertRaises(DirectorError):self.approve(0)
    def test_no_approval_no_post(self):
        op=self.op()
        with self.assertRaises(DirectorError):submit_operation(self.project,op['id'],self.client)
        self.assertFalse(self.client.posts)
    def test_quote_increase_stops(self):
        op=self.op();self.approve();self.client.points=11
        with self.assertRaises(DirectorError):submit_operation(self.project,op['id'],self.client)
        self.assertFalse(self.client.posts)
    def test_submit_once(self):
        op=self.op();self.approve();submit_operation(self.project,op['id'],self.client);submit_operation(self.project,op['id'],self.client)
        self.assertEqual(len(self.client.posts),1)
    def test_lost_submit_durable_uuid(self):
        op=self.op();self.approve();self.client.lose_submit=True
        with self.assertRaises(DirectorError):submit_operation(self.project,op['id'],self.client)
        submit_operation(self.project,op['id'],self.client)
        self.assertEqual(len(self.client.posts),1)
        self.assertEqual(self.project.summary()['exposure_points'],10)
    def test_failed_keeps_cost(self):
        op=self.op();self.approve();submit_operation(self.project,op['id'],self.client);self.client.status='failed';poll_operation(self.project,op['id'],self.client)
        self.assertEqual(self.project.summary()['exposure_points'],10)
    def test_new_key_does_not_rebind_old_job(self):
        op=self.op();self.approve();self.client.vault.active='credential-example-b';submit_operation(self.project,op['id'],self.client)
        self.assertEqual(self.client.posts[0][1],'credential-example-a')
    def test_revision_requires_new_approval(self):
        op=self.op();self.approve();self.project.update(self.project.state(),1)
        with self.assertRaises(DirectorError):submit_operation(self.project,op['id'],self.client)
    def test_new_operation_requires_new_approval(self):
        op=self.op();self.approve();second=plan_operation(self.project,'shot-1','audio',{'model_id':'dreamface:tts-common','parameters':{'text':'新台词'},'assets':{}},2,self.client)
        with self.assertRaises(DirectorError):submit_operation(self.project,second['id'],self.client)
    def test_unknown_blocks_next(self):
        first=self.op();second=plan_operation(self.project,'shot-1','audio',{'model_id':'dreamface:tts-common','parameters':{'text':'台词'},'assets':{}},10,self.client);self.approve(20)
        submit_operation(self.project,first['id'],self.client)
        with self.assertRaises(DirectorError):submit_operation(self.project,second['id'],self.client)
    def test_pause_blocks_new_submit(self):
        op=self.op();self.approve();rid=self.project.open_review('storyboard');self.project.decide(rid,'pause',1)
        with self.assertRaises(DirectorError):submit_operation(self.project,op['id'],self.client)
    def test_unpaid_download_refused(self):
        op=self.op();self.approve();submit_operation(self.project,op['id'],self.client);self.client.status='succeeded';self.client.bill='unknown'
        with self.assertRaises(DirectorError):download_operation(self.project,op['id'],self.client)
    def test_audio_download_and_reuse(self):
        op=plan_operation(self.project,'shot-1','audio',{'model_id':'dreamface:tts-common','parameters':{'text':'台词'},'assets':{}},10,self.client);self.approve();submit_operation(self.project,op['id'],self.client);self.client.status='succeeded';self.client.kind='audio'
        result=download_operation(self.project,op['id'],self.client);self.assertTrue(result['file'].endswith('.wav'));self.assertTrue(download_operation(self.project,op['id'],self.client)['reused'])
    def test_visual_download_adds_candidate(self):
        op=self.op();self.approve();submit_operation(self.project,op['id'],self.client);self.client.status='succeeded';download_operation(self.project,op['id'],self.client)
        self.assertEqual(len(self.project.state()['shots'][0]['candidates']),1)
    def test_missing_dependency_prevents_generation(self):
        first=self.op();request={'model_id':'dreamface:avatar','parameters':{},'assets':{'audio':['operation:'+first['id']]}}
        op=plan_operation(self.project,'shot-1','visual',request,10,self.client)
        with self.assertRaises(DirectorError):quote_operation(self.project,op['id'],self.client)
        self.assertFalse(self.client.posts)
    def test_error_classes(self):
        for status,text,expected in [(400,'insufficient points','insufficient_points'),(400,'official points token requires its bound instance endpoint','bound_instance'),(401,'expired','key_expired'),(401,'bad','invalid_key'),(429,'busy','rate_limited'),(503,'down','api_rejected')]:
            with self.subTest(expected=expected):self.assertEqual(classify(status,text)[0],expected)
        self.assertEqual(classify(400,'报价已过期')[0],'quote_expired')
        self.assertNotEqual(classify(400,'余额验证失败')[0],'insufficient_points')
    def test_budget_change_preserves_visual_candidate(self):
        path=self.project.root/'media/example.png';path.write_bytes(b'example');self.project.add_candidate('shot-1','media/example.png')
        before=shot_hash(self.project.state()['shots'][0]);state=self.project.state();state['shots'][0]['limits']={'visual':99};self.project.update(state,1)
        self.assertEqual(before,shot_hash(self.project.state()['shots'][0]))
    def test_same_fields_roundtrip_does_not_invalidate_candidate(self):
        before=shot_hash(self.project.state()['shots'][0]);data=self.project.state();data['title']='另一个标题';self.project.update(data,1)
        self.assertEqual(before,shot_hash(self.project.state()['shots'][0]))
    def test_explicit_redo_deduplicated_and_requires_new_budget(self):
        op=self.op();self.approve();submit_operation(self.project,op['id'],self.client);self.client.status='succeeded';poll_operation(self.project,op['id'],self.client)
        review=self.project.open_review('assets');self.project.decide(review,'revise',1,note='重做这一个镜头')
        redo=redo_operation(self.project,op['id'],review);self.assertEqual(redo['id'],redo_operation(self.project,op['id'],review)['id'])
        self.assertNotEqual(redo['id'],op['id'])
        with self.assertRaises(DirectorError):submit_operation(self.project,redo['id'],self.client)
        self.approve(20);submit_operation(self.project,redo['id'],self.client);self.assertEqual(len(self.client.posts),2)
    def test_unknown_task_cannot_redo(self):
        op=self.op();self.approve();submit_operation(self.project,op['id'],self.client)
        review=self.project.open_review('assets');self.project.decide(review,'revise',1)
        with self.assertRaises(DirectorError):redo_operation(self.project,op['id'],review)
    def test_concurrent_submit_only_one_post(self):
        from concurrent.futures import ThreadPoolExecutor
        op=self.op();self.approve()
        def attempt():
            try:return submit_operation(self.project,op['id'],self.client)
            except DirectorError:return None
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(len(self.client.posts),1)
    def test_long_audio_blocks_visual_before_paid_submit(self):
        from unittest.mock import patch
        state=self.project.state();state['shots'][0]['audio']='media/example.wav';self.project.update(state,1)
        (self.project.root/'media/example.wav').write_bytes(b'example')
        op=self.op();self.approve()
        with patch('media.probe',return_value={'format':{'duration':'6'},'streams':[{'codec_type':'audio'}]}):
            with self.assertRaises(DirectorError) as error:submit_operation(self.project,op['id'],self.client)
        self.assertEqual(error.exception.code,'speech_too_long');self.assertFalse(self.client.posts)


class TransportTests(unittest.TestCase):
    class Response:
        def __init__(self,mime,body):
            import io
            self.headers={'Content-Type':mime};self.body=io.BytesIO(body)
        def read(self,*args):return self.body.read(*args)
        def __enter__(self):return self
        def __exit__(self,*args):self.body.close()
    class Opener:
        def __init__(self,response):self.response=response
        def open(self,*args,**kwargs):return self.response
    def test_real_download_adapter_accepts_each_media_class(self):
        import uuid
        for kind,mime,suffix in [('audio','audio/wav','.wav'),('audio','audio/mpeg','.mp3'),('video','video/mp4','.mp4'),('image','image/png','.png')]:
            with self.subTest(mime=mime),tempfile.TemporaryDirectory() as tmp:
                client=Client(FakeVault());client.opener=self.Opener(self.Response(mime,b'example-bytes'))
                path=client.download(str(uuid.uuid4()),'credential-example-a',Path(tmp)/'result',kind)
                self.assertEqual(path.suffix,suffix);self.assertEqual(path.read_bytes(),b'example-bytes')
    def test_download_rejects_html_or_wrong_kind(self):
        import uuid
        for mime in ('text/html','video/mp4'):
            with self.subTest(mime=mime),tempfile.TemporaryDirectory() as tmp:
                client=Client(FakeVault());client.opener=self.Opener(self.Response(mime,b'example'))
                with self.assertRaises(DirectorError):client.download(str(uuid.uuid4()),None,Path(tmp)/'result','audio')
    def test_sensitive_response_never_returned(self):
        client=Client(FakeVault());client.opener=self.Opener(self.Response('application/json',b'{"echo":"dummy-example-key"}'))
        with self.assertRaises(DirectorError) as error:client.request('/video-api/account',{})
        self.assertEqual(error.exception.code,'sensitive_response')


class WebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.project=Project.create(Path(self.tmp.name)/'project',sample());self.server=ReviewServer(self.project,FakeVault());self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start();self.base=self.server.origin
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def request(self,path,body=None,auth=True,origin=None,extra=None):
        headers={'X-Director-Session':self.server.session} if auth else {}
        if origin:headers['Origin']=origin
        headers.update(extra or {})
        data=dump(body).encode() if body is not None else None
        return build_opener().open(Request(self.base+path,data=data,headers=headers),timeout=3)
    def test_no_auth_no_state(self):
        with self.assertRaises(HTTPError) as error:self.request('/api/state',auth=False)
        self.assertEqual(error.exception.code,401)
    def test_cross_origin_rejected(self):
        with self.assertRaises(HTTPError) as error:self.request('/api/project',{},origin='https://example.com')
        self.assertEqual(error.exception.code,403)
    def test_cross_host_rejected(self):
        with self.assertRaises(HTTPError) as error:self.request('/api/state',extra={'Host':'example.com'})
        self.assertEqual(error.exception.code,403)
    def test_private_file_unavailable(self):
        with self.assertRaises(HTTPError):self.request('/media/.director/state.sqlite3')
    def test_media_traversal_refused(self):
        with self.assertRaises(HTTPError):self.request('/media/media/../../outside.txt')
    def test_media_range(self):
        (self.project.root/'media/example.mp4').write_bytes(b'0123456789')
        with self.request('/media/media/example.mp4',extra={'Range':'bytes=2-5'}) as r:
            self.assertEqual(r.status,206);self.assertEqual(r.read(),b'2345')
    def test_page_security_headers(self):
        with self.request('/',auth=False) as r:self.assertIn("frame-ancestors 'none'",r.headers['Content-Security-Policy']);self.assertEqual(r.headers['Referrer-Policy'],'no-referrer')
    def test_browser_confirmation_roundtrip(self):
        rid=self.project.open_review('storyboard');data=self.project.state();data['title']='页面回传作品'
        with self.request('/api/decision',{'request_id':rid,'action':'confirm','revision':1,'data':data}) as r:self.assertEqual(json.load(r)['revision'],2)
        self.assertEqual(self.project.review(rid)['status'],'completed');self.assertEqual(self.project.state()['title'],'页面回传作品')
    def test_draft_does_not_confirm(self):
        rid=self.project.open_review('storyboard')
        with self.request('/api/project',{'revision':1,'project':self.project.state()}):pass
        self.assertEqual(self.project.review(rid)['status'],'stale')
    def test_state_never_contains_key(self):
        with self.request('/api/state') as r:self.assertNotIn(b'dummy-example-key',r.read())


@unittest.skipUnless(os.name=='nt','Windows DPAPI only')
class VaultTests(unittest.TestCase):
    def test_encrypted_roundtrip_and_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault=Vault(tmp);first=vault.put('dummy-example-key-first')['active'];second=vault.put('dummy-example-key-second')['active']
            self.assertNotEqual(first,second);self.assertEqual(vault.get(first),'dummy-example-key-first')
            self.assertNotIn(b'dummy-example-key',Path(tmp,first+'.dpapi').read_bytes())
            vault.delete(second);self.assertFalse(vault.status()['configured']);self.assertEqual(vault.get(first),'dummy-example-key-first')


if __name__=='__main__':unittest.main()
