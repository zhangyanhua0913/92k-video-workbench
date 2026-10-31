"""Free behavioral checks; all generated projects live in disposable directories."""
import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/talking-edit/scripts'))
from core import Project, EditError, digest, atomic
from media import intervals,map_cues,parse_srt,srt_text
from web import Server
from cli import wait


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.p=Project.create(Path(self.tmp.name)/'project','免费测试')

    def tearDown(self):self.tmp.cleanup()

    def video_state(self):
        with self.p.db() as c:
            s=self.p.state(c);s.update(source={'file':'media/fake.mp4','sha256':'test'},duration=10,cues=[dict(id='a',start=1,end=3,text='测试')]);self.p._save(c,s)

    def test_persistence_and_export(self):
        p=Project(self.p.root);self.assertEqual(p.state()['title'],'免费测试');self.assertEqual(json.loads((p.root/'project.json').read_text(encoding='utf-8'))['revision'],1)

    def test_music_change_invalidates_packaging_not_roughcut(self):
        self.video_state();s=self.p.state();rough=self.p.fingerprint('roughcut');pack=self.p.fingerprint('packaging')
        self.p.update({'music':{'file':'media/music.wav','sha256':'abc','gain_db':-20}},s['revision'])
        self.assertEqual(rough,self.p.fingerprint('roughcut'));self.assertNotEqual(pack,self.p.fingerprint('packaging'))

    def test_remotion_plugin_can_be_selected_for_packaging(self):
        from registry import specs
        item=next(x for x in specs() if x['id']=='remotion-plugin')
        self.assertEqual((item['execution'],item['input'],item['output']),('agent','reviewed-timeline','remotion-clips'))
        s=self.p.state();workflow=dict(s['workflow'],packaging='remotion-plugin')
        self.p.update({'workflow':workflow},s['revision'])
        self.assertEqual(self.p.state()['workflow']['packaging'],'remotion-plugin')

    def test_evidence_style_selection_routes_to_bundled_guidance(self):
        from cli import agent_brief
        from unittest.mock import patch
        s=self.p.state();self.p.update({'workflow':dict(s['workflow'],packaging='remotion-evidence')},s['revision'])
        with patch('registry.status',return_value=[{'id':'remotion-evidence','ready':True,'reasons':[]}]):
            result=agent_brief(self.p,'packaging')
        self.assertTrue(Path(result['instructions']).is_file())
        self.assertEqual(Path(result['instructions']).name,'evidence-style.md')

    def test_bundled_styles_do_not_require_local_plugin_cache(self):
        from registry import status
        from unittest.mock import patch
        with patch.dict(os.environ,{'CODEX_HOME':str(Path(self.tmp.name)/'empty-codex'),'TALKING_EDIT_NODE':sys.executable}):
            items={x['id']:x for x in status()}
        self.assertTrue(items['remotion-gold']['ready'])
        self.assertTrue(items['remotion-evidence']['ready'])
        self.assertFalse(items['remotion-plugin']['ready'])

    def test_batch_projects_queue_and_interruption(self):
        from batch import Batch
        from unittest.mock import patch
        b=Batch(self.p);batch=b.create('两条口播','none',1.3)
        def fake_import(p,path,kind):
            with p.db() as c:
                s=p.state(c);s.update(source={'file':'media/fake.mp4','sha256':str(path)},duration=10);p._save(c,s)
        with patch('batch.import_file',side_effect=fake_import):
            a=b.add_file(batch['id'],'one.mp4','one.mp4');z=b.add_file(batch['id'],'two.mp4','two.mp4')
        self.assertNotEqual(a['project_id'],z['project_id']);self.assertEqual(a['speed'],1.3)
        first=b.enqueue(a['id'],'transcribe');self.assertEqual(first['id'],b.enqueue(a['id'],'transcribe')['id'])
        b.enqueue(z['id'],'transcribe')
        self.assertEqual(b.next()['status'],'running');self.assertEqual(b.next()['status'],'busy')
        with patch('batch.pid_alive',return_value=False):self.assertEqual(b.next()['status'],'interrupted')
        self.assertEqual(b.next()['item_id'],z['id'])
        self.assertEqual(len(b.list()[0]['items']),2)
        with self.assertRaises(EditError):b.enqueue(a['id'],'render')

    def test_batch_auto_is_opt_in_and_only_local_no_packaging(self):
        from batch import Batch
        from unittest.mock import patch
        b=Batch(self.p);manual=b.create('手动','none',1);auto=b.create('自动','none',1.3,'auto')
        with self.assertRaises(EditError):b.create('不支持','fredtalk-motion',1,'auto')
        def imported(p,path,kind):
            with p.db() as c:
                s=p.state(c);s.update(source={'file':'media/fake.mp4','sha256':'test'},duration=10,cues=[dict(id='a',start=1,end=2,text='测试')]);p._save(c,s)
        with patch('batch.import_file',side_effect=imported):
            a=b.add_file(auto['id'],'a.mp4','a.mp4');m=b.add_file(manual['id'],'b.mp4','b.mp4')
        with self.assertRaises(EditError):b.enqueue(m['id'],'auto')
        b.enqueue(a['id'],'auto')
        with patch('media.render',return_value={'file':'test'}):result=b.execute_next()
        self.assertEqual(result['status'],'done');self.assertEqual(b.item(a['id'])['status'],'awaiting_review')
        self.assertTrue(Project(a['project_path']).approved('roughcut'))
        self.assertFalse(Project(a['project_path']).approved('final'))

    def test_auto_gold_plan_uses_current_cues_and_avoids_cuts(self):
        from auto_gold import propose
        self.video_state();s=self.p.state();s['cues']=[dict(id='a',start=1,end=2,text='第一段测试内容'),dict(id='b',start=4,end=6,text='被剪部分')]
        s['cuts']=[dict(id='c',start=3,end=7,enabled=True)]
        scenes=propose(s);self.assertEqual(len(scenes),1);self.assertEqual(scenes[0]['title'],'第一段测试内容');self.assertEqual(scenes[0]['start'],1)

    def test_auto_gold_mode_and_weak_caption(self):
        from batch import Batch
        from auto_gold import propose
        from unittest.mock import patch
        with patch('batch.status',return_value=[{'id':'remotion-gold','stages':['packaging'],'ready':True}]):
            result=Batch(self.p).create('暗金','remotion-gold',1.3,'auto')
        self.assertEqual(result['mode'],'auto')
        self.video_state();s=self.p.state();s['cues']=[dict(id='a',start=1,end=2,text='最后啊')]
        with self.assertRaises(EditError):propose(s)

    def test_gold_style_select_restore_and_invalidate_packaging(self):
        from registry import specs
        from cli import agent_brief
        from unittest.mock import patch
        spec=next(x for x in specs() if x['id']=='remotion-gold')
        self.assertEqual((spec['execution'],spec['input'],spec['output']),('agent','reviewed-timeline','remotion-clips'))
        self.video_state();s=self.p.state();self.p.decide(self.p.open_review('packaging'),s['revision'],'confirm')
        self.assertTrue(self.p.approved('packaging'))
        self.p.update({'workflow':dict(s['workflow'],packaging='remotion-gold')},s['revision'])
        self.assertEqual(Project(self.p.root).state()['workflow']['packaging'],'remotion-gold')
        self.assertFalse(self.p.approved('packaging'))
        with patch('registry.status',return_value=[dict(spec,ready=True,reasons=[])]):
            brief=agent_brief(self.p,'packaging')
        self.assertTrue(Path(brief['instructions']).is_file())
        self.assertEqual(Path(brief['instructions']).name,'gold-style.md')

    def test_speed_advice_slow_fast_and_no_subtitles(self):
        from media import speed_advice
        self.assertFalse(speed_advice(self.p.state())['available'])
        self.video_state();s=self.p.state();s['cues'][0]['text']='一二三四五六七八九十'
        advice=speed_advice(s);self.assertEqual(advice['suggested'],1.25)
        s['cues'][0]['text']='快'*100;self.assertEqual(speed_advice(s)['suggested'],1)
        s['cues'][0]['text']='字'*40;s['cuts']=[dict(id='c',start=0,end=5,enabled=True)]
        self.assertEqual(speed_advice(s)['characters'],0)

    def test_music_and_layout_validation(self):
        self.video_state();s=self.p.state()
        with self.assertRaises(EditError):self.p.update({'music':{'file':'media/music.wav','sha256':'abc','gain_db':0}},s['revision'])
        with self.assertRaises(EditError):self.p.update({'scenes':[dict(id='bad',start=1,end=2,layout={'x':.9,'y':0,'width':.4})]},s['revision'])

    def test_selected_packaging_cannot_silently_export_plain_roughcut(self):
        from media import render
        self.video_state();self.p.decide(self.p.open_review('roughcut'),self.p.state()['revision'],'confirm','仅合成测试')
        with self.assertRaises(EditError) as error:render(self.p)
        self.assertEqual(error.exception.code,'packaging_incomplete')

    def test_stale_update(self):
        self.p.update({'title':'新标题'},1)
        with self.assertRaises(EditError):self.p.update({'title':'旧页面'},1)
        self.assertEqual(self.p.state()['title'],'新标题')

    def test_request_reused(self):
        self.assertEqual(self.p.open_review('workflow'),self.p.open_review('workflow'))

    def test_draft_does_not_approve(self):
        rid=self.p.open_review('workflow');self.p.decide(rid,1,'save_draft');self.assertFalse(self.p.approved('workflow'))

    def test_duplicate_decision_idempotent(self):
        rid=self.p.open_review('workflow');first=self.p.decide(rid,1,'confirm');self.assertEqual(first,self.p.decide(rid,1,'confirm'))
        with self.assertRaises(EditError):self.p.decide(rid,1,'pause')

    def test_old_request_cannot_confirm(self):
        rid=self.p.open_review('workflow');self.p.update({'title':'更改'},1)
        with self.assertRaises(EditError):self.p.decide(rid,1,'confirm')

    def test_scope_invalidation(self):
        self.video_state();s=self.p.state();rid=self.p.open_review('roughcut');self.p.decide(rid,s['revision'],'confirm');self.assertTrue(self.p.approved('roughcut'))
        self.p.update({'title':'只改标题'},s['revision']);self.assertTrue(self.p.approved('roughcut'))
        s=self.p.state();self.p.update({'speed':1.1},s['revision']);self.assertFalse(self.p.approved('roughcut'))

    def test_pause_blocks_claim(self):
        rid=self.p.open_review('workflow');self.p.decide(rid,1,'pause')
        with self.assertRaises(EditError):self.p.claim('render','x')
        self.p.recover(True);self.assertTrue(self.p.claim('render','x')[1])

    def test_unique_execution(self):
        task,_=self.p.claim('render','same')
        with self.assertRaises(EditError):self.p.claim('render','same')
        self.p.finish(task['id'],{'file':'result'});self.assertFalse(self.p.claim('render','same')[1])

    def test_unknown_never_reclaims(self):
        t,_=self.p.claim('transcribe','cloud');self.p.finish(t['id'],{'note':'unknown'},'unknown')
        with self.assertRaises(EditError):self.p.claim('transcribe','cloud')

    def test_range_validation(self):
        self.video_state();s=self.p.state()
        with self.assertRaises(EditError):self.p.update({'cuts':[dict(id='bad',start=1,end=99,enabled=True)]},s['revision'])

    def test_no_credentials_in_project(self):
        with self.assertRaises(EditError):self.p.update({'cues':[{'api_key':'test-secret-placeholder'}]},1)

    def test_traversal_blocked(self):
        for path in ('../secret.txt','.talking-edit/state.sqlite3','C:/Windows/win.ini'):
            with self.assertRaises(EditError):self.p.public_file(path)

    def test_time_mapping_overlaps_and_speed(self):
        m=intervals(10,[dict(start=2,end=4,enabled=True),dict(start=3,end=5,enabled=True)],1.25)
        self.assertEqual(len(m),2);self.assertAlmostEqual(m[-1]['output_end'],5.6)
        c,w=map_cues([dict(id='a',start=5,end=7,text='后段')],m,1.25);self.assertAlmostEqual(c[0]['start'],1.6);self.assertFalse(w)

    def test_partial_sentence_warns(self):
        c,w=map_cues([dict(id='a',start=1,end=8,text='需要校正')],intervals(10,[dict(start=2,end=3,enabled=True)]));self.assertEqual(len(c),1);self.assertEqual(w[0]['cue'],'a')

    def test_srt_roundtrip(self):
        rows=[dict(id='cue-1',start=.25,end=1.1,text='你好，世界')];parsed=parse_srt(srt_text(rows));self.assertEqual(parsed,rows)

    def test_rotated_display_geometry(self):
        from media import display_size
        self.assertEqual(display_size({'width':1080,'height':1920,'side_data_list':[{'rotation':90}]}),(1920,1080))
        self.assertEqual(display_size({'width':1080,'height':1920,'tags':{'rotate':'-90'}}),(1920,1080))
        self.assertEqual(display_size({'width':1080,'height':1920}),(1080,1920))

    def test_unsupported_skill_cannot_save(self):
        s=self.p.state();w=s['workflow'];w['render']='qwen-cloud'
        with self.assertRaises(EditError):self.p.update({'workflow':w},s['revision'])

    def test_cloud_no_price_closed(self):
        from providers import cloud_quote
        self.video_state()
        old=os.environ.get('TALKING_EDIT_HOME');os.environ['TALKING_EDIT_HOME']=self.tmp.name
        try:
            with self.assertRaises(EditError):cloud_quote(self.p)
        finally:
            if old is None:os.environ.pop('TALKING_EDIT_HOME')
            else:os.environ['TALKING_EDIT_HOME']=old

    def test_dpapi_roundtrip_only_mask_leaves_vault(self):
        if os.name!='nt':self.skipTest('Windows DPAPI')
        from vault import Vault
        v=Vault(Path(self.tmp.name)/'vault');secret='test-local-dpapi-credential-1234'
        result=v.put(secret);self.assertNotIn(secret,json.dumps(result));self.assertEqual(v.get(),secret)
        self.assertNotIn(secret,next(v.root.glob('*.dpapi')).read_bytes().decode('latin1'))

    def test_recover_dead_local_process(self):
        task,_=self.p.claim('render','interrupted')
        with self.p.db() as c:c.execute('UPDATE tasks SET pid=? WHERE id=?',(2147483000,task['id']))
        result=self.p.recover();self.assertEqual(result['tasks'][0]['status'],'failed')
        self.p.retry_local(task['id']);self.assertTrue(self.p.claim('render','interrupted')[1])

    def test_retry_local_rejects_cloud_unknown(self):
        t,_=self.p.claim('transcribe','cloud');self.p.finish(t['id'],{},'failed')
        (self.p.root/'work'/('qwen-'+t['id'])).mkdir()
        with self.assertRaises(EditError):self.p.retry_local(t['id'])

    def test_recover_cloud_without_receipt_unknown(self):
        t,_=self.p.claim('transcribe','cloud');(self.p.root/'work'/('qwen-'+t['id'])).mkdir()
        with self.p.db() as c:c.execute('UPDATE tasks SET pid=? WHERE id=?',(2147483000,t['id']))
        self.assertEqual(self.p.recover()['tasks'][0]['status'],'unknown')

    def test_concurrent_execution_claims_once(self):
        results=[]
        def claim():
            try:results.append(self.p.claim('render','concurrent')[1])
            except EditError:results.append(False)
        threads=[threading.Thread(target=claim) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual(results.count(True),1)

    def test_package_artifact_attachment_does_not_approve_new_direction(self):
        self.video_state();s=self.p.state();scene=dict(id='scene',start=4,end=6,componentPlan={'selected':'A'})
        self.p.update({'scenes':[scene]},s['revision']);s=self.p.state();r=self.p.open_review('packaging');self.p.decide(r,s['revision'],'confirm')
        scene.update(artifact='media/video.mp4',artifact_hash='test-hash',code='work/project',keyframe='media/frame.png')
        self.p.update({'scenes':[scene]},s['revision']);self.assertTrue(self.p.approved('packaging'))
        s=self.p.state();scene['componentPlan']['selected']='B';self.p.update({'scenes':[scene]},s['revision']);self.assertFalse(self.p.approved('packaging'))

    def test_unknown_capability_and_bad_speed(self):
        with self.assertRaises(EditError):self.p.update({'speed':True},1)
        with self.assertRaises(EditError):self.p.update({'speed':float('nan')},1)

    def test_speed_13_is_available_and_maps_time(self):
        self.p.update({'speed':1.3},1)
        self.assertEqual(self.p.state()['speed'],1.3)
        mapping=intervals(13,[],1.3)
        self.assertAlmostEqual(mapping[0]['output_end'],10)
        from media import speed_advice
        self.assertIn(1.3,[option['speed'] for option in speed_advice(dict(self.p.state(), source={'file':'sample.mp4'}, duration=13, cues=[dict(id='c',start=0,end=2,text='测试')], cuts=[]))['options']])

    def test_project_cookies_isolated(self):
        other=Project.create(Path(self.tmp.name)/'other','另一个项目')
        first,second=Server(self.p),Server(other)
        try:self.assertNotEqual(first.cookie_name,second.cookie_name)
        finally:first.server_close();second.server_close()

    def test_cloud_error_categories_do_not_echo_body(self):
        from providers import checked_response
        for upstream,expected in [('InvalidApiKey','key_invalid'),('ApiKeyExpired','key_expired'),('Arrearage','insufficient_balance'),('Throttling','rate_limited')]:
            response=type('Response',(),{'ok':False,'status_code':403,'json':lambda self:{'code':upstream,'message':'test-sensitive-body'}})()
            with self.assertRaises(EditError) as e:checked_response(response)
            self.assertEqual(e.exception.code,expected);self.assertNotIn('test-sensitive-body',str(e.exception))

    def test_http_auth_origin_and_wait_keepalive(self):
        srv=Server(self.p,idle=.5);t=threading.Thread(target=srv.serve_forever,daemon=True);t.start();atomic(self.p.meta/'session.json',srv.descriptor())
        def actual_idle_timeout():
            while time.monotonic()-srv.last_activity<srv.idle:time.sleep(.05)
            srv.shutdown()
        idle_thread=threading.Thread(target=actual_idle_timeout,daemon=True);idle_thread.start()
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def get(path,headers=None,body=None):return opener.open(urllib.request.Request(srv.origin+path,body,headers or {}),timeout=3)
            with self.assertRaises(urllib.error.HTTPError) as e:get('/api/state')
            self.assertEqual(e.exception.code,401)
            e.exception.close()
            headers={'X-Talking-Session':srv.session,'Content-Type':'application/json','Origin':'https://evil.example'}
            with self.assertRaises(urllib.error.HTTPError) as e:get('/api/heartbeat',headers,b'{}')
            self.assertEqual(e.exception.code,403)
            e.exception.close()
            rid=self.p.open_review('workflow');wait(self.p,rid,1.2)
            self.assertLess(time.monotonic()-srv.last_activity,.5)
            self.assertEqual(self.p.review(rid)['status'],'pending')
        finally:srv.shutdown();srv.server_close();t.join()


if __name__=='__main__':unittest.main()
