"""Workspace contracts and real local media acceptance, no external model calls."""
import hashlib
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from workspace_service import Workspace, WorkspaceError, Server, invoke, ROOT, serve


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ws = Workspace(self.root / 'index')
        self.entry = self.ws.create('talk', '合成测试', str(self.root / 'projects'))
        self.pid = self.entry['id']

    def tearDown(self):
        self.ws.close()
        self.tmp.cleanup()

    def test_persistent_creation_and_restore(self):
        s = self.ws.snapshot(self.pid)['state']['project']
        self.ws.call(self.pid, 'update', {'patch': {'script': '可恢复文案', 'workflow': {**s['workflow'], 'packaging': 'none'}}, 'revision': s['revision']})
        again = Workspace(self.ws.home)
        self.assertEqual(again.snapshot(self.pid)['state']['project']['script'], '可恢复文案')
        self.assertEqual(again.list()[0]['id'], self.pid)
        self.assertEqual(s['workflow']['roughcut'], 'local-cuts')

    def test_register_is_nonmutating_and_index_rebuild(self):
        root = Path(self.entry['root'])
        before = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        again = Workspace(self.root / 'new-index')
        again.register(str(root))
        after = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(len(again.list()), 1)

    def test_unknown_and_repo_paths_refused(self):
        for path in (str(ROOT), str(ROOT / 'projects'), str(ROOT.parent), str(self.ws.home)):
            with self.assertRaises(WorkspaceError): self.ws.register(path)
        with self.assertRaises(WorkspaceError): self.ws.register(str(self.root / 'missing'))
        with self.assertRaises(WorkspaceError): self.ws.call('other-project', 'show')

    def test_revision_conflict(self):
        s = self.ws.call(self.pid, 'show')['project']
        self.ws.call(self.pid, 'update', {'patch': {'script': 'first'}, 'revision': s['revision']})
        with self.assertRaises(WorkspaceError): self.ws.call(self.pid, 'update', {'patch': {'script': 'stale'}, 'revision': s['revision']})
        self.assertEqual(self.ws.call(self.pid, 'show')['project']['script'], 'first')

    def test_ui_preferences_do_not_approve_or_change_engine(self):
        original=self.ws.call(self.pid,'show')['project']
        prefs=self.ws.preferences(self.pid)
        self.ws.preferences(self.pid,{'step':3},prefs['revision'])
        self.assertEqual(Workspace(self.ws.home).snapshot(self.pid)['preferences']['step'],3)
        self.assertEqual(self.ws.call(self.pid,'show')['project'],original)
        self.assertEqual(self.ws.call(self.pid,'show')['reviews'],[])
        with self.assertRaises(WorkspaceError):self.ws.preferences(self.pid,{'step':4},prefs['revision'])
        with self.assertRaises(WorkspaceError):self.ws.preferences(self.pid,{'step':6},1)

    def test_style_upgrade_requires_explicit_adoption(self):
        path = Path(self.entry['root'])/'workbench-style.json'
        data = json.loads(path.read_text())
        data['versions'][0]['version'] = 'older-test-version'
        path.write_text(json.dumps(data))
        with self.assertRaises(WorkspaceError): self.ws.call(self.pid, 'packaging')
        self.ws.call(self.pid, 'adopt-style')
        self.assertNotEqual(json.loads(path.read_text())['versions'][0]['version'], 'older-test-version')

    def test_footage_refuses_missing_rights_stale_review_and_traversal(self):
        entry=self.ws.create('footage','边界验证',str(self.root/'projects')); pid=entry['id']
        review=self.ws.call(pid,'review',{'stage':'assets'})
        with self.assertRaises(WorkspaceError): self.ws.call(pid,'decide',{'request_id':review['id'],'revision':1,'action':'confirm'})
        self.ws.call(pid,'update',{'patch':{'script':'new revision'},'revision':1})
        with self.assertRaises(WorkspaceError): self.ws.call(pid,'decide',{'request_id':review['id'],'revision':1,'action':'confirm'})
        with self.assertRaises(WorkspaceError): self.ws.call(pid,'update',{'patch':{'narration':'../private.wav'},'revision':2})

    def test_job_dedup_and_edit_block(self):
        release = threading.Event()
        def slow(*args):
            release.wait(5)
            return {'complete': True}
        with patch('workspace_service.invoke', side_effect=slow):
            one = self.ws.call(self.pid, 'analyze', background=True)
            two = self.ws.call(self.pid, 'analyze', background=True)
            self.assertEqual(one['job'], two['job'])
            with self.assertRaises(WorkspaceError): self.ws.call(self.pid, 'update', {'patch': {}, 'revision': 2})
            closing=threading.Thread(target=self.ws.close);closing.start()
            time.sleep(.03);self.assertTrue(closing.is_alive())
            release.set()
            closing.join(timeout=5);self.assertFalse(closing.is_alive())
            for _ in range(100):
                if self.ws.jobs(self.pid)[0]['status'] != 'running': break
                time.sleep(.02)
        self.assertEqual(self.ws.jobs(self.pid)[0]['status'], 'done')

    def test_interrupted_not_replayed(self):
        with self.ws.db() as db:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', ('interrupted-test', self.pid, 'submit', 'running', None, time.time(), 'old-owner'))
        self.ws.recover_jobs()
        self.assertEqual(self.ws.jobs(self.pid)[0]['status'], 'interrupted')

    def test_footage_retry_keeps_original_record(self):
        entry=self.ws.create('footage','本地失败记录',str(self.root/'projects'))
        dbfile=Path(entry['root'])/'.footage/state.sqlite3'
        with sqlite3.connect(dbfile) as db:
            db.execute('INSERT INTO renders VALUES(?,?,?,?,?)',('failed-original',1,'failed','{}',99999999))
        db.close()
        result=self.ws.call(entry['id'],'retry-local',{'task':'failed-original'})
        self.assertEqual(result['retry_approved'],'failed-original')
        self.assertEqual(self.ws.call(entry['id'],'show')['renders'][0]['status'],'retry-approved')
        with self.assertRaises(WorkspaceError):self.ws.call(entry['id'],'retry-local',{'task':'failed-original'})

    def test_old_and_unknown_formats(self):
        root = Path(self.entry['root'])
        (root / 'workbench-project.json').unlink()
        other = Workspace(self.root / 'old-index')
        self.assertEqual(other.register(str(root))['id'], self.pid)
        bad = self.root / 'bad'; (bad / '.director').mkdir(parents=True)
        (bad / '.director/state.sqlite3').write_bytes(b'unknown format')
        with self.assertRaises(WorkspaceError): other.register(str(bad))

    def test_http_auth_proxy_and_isolation(self):
        server = Server(self.ws)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        client = build_opener(ProxyHandler({}))
        def request(path, body=None, auth=True, origin=True):
            headers = {'Content-Type': 'application/json'}
            if auth: headers['X-Workbench-Session'] = server.token
            if origin: headers['Origin'] = server.origin
            return client.open(Request(server.origin + path, json.dumps(body).encode() if body is not None else None, headers=headers))
        try:
            from versioning import Lock
            (self.ws.home/'session.json').write_text(json.dumps({'origin':server.origin,'session':server.token}))
            with Lock(self.ws.home/'server.lock'), contextlib.redirect_stdout(io.StringIO()) as output:
                serve(self.ws.home,0)
            self.assertTrue(json.loads(output.getvalue())['reused'])
            with self.assertRaises(HTTPError) as e: request('/api/projects', auth=False)
            self.assertEqual(e.exception.code, 401); e.exception.close()
            with self.assertRaises(HTTPError) as e: request('/api/create', {}, origin=False)
            self.assertEqual(e.exception.code, 403); e.exception.close()
            with request('/api/tool', {'id': self.pid}) as r: url = json.load(r)['url']
            with request(url+'app.js') as r:
                script = r.read().decode()
                self.assertIn('/tool/'+self.pid+'/api/', script)
                self.assertNotIn("fetch('/api/", script)
            with request(url+'api/state') as r: self.assertEqual(json.load(r)['project']['project_id'], self.pid)
            with self.assertRaises(HTTPError) as e: request('/tool/unknown/api/state')
            e.exception.close()
            g = self.ws.create('generate', '生成模拟', str(self.root / 'projects'))
            with request('/api/tool', {'id': g['id']}) as r: gurl = json.load(r)['url']
            with request(gurl+'app.js') as r: self.assertIn('/tool/'+g['id']+'/api/state', r.read().decode())
            with request(gurl+'api/state') as r: self.assertEqual(json.load(r)['project']['project_id'], g['id'])
        finally: server.shutdown(); server.server_close(); thread.join()

    @unittest.skipUnless(os.environ.get('TALKING_EDIT_FFMPEG') and os.environ.get('TALKING_EDIT_FFPROBE'), 'Set FFmpeg/ffprobe for actual media acceptance')
    def test_real_talk_footage_hybrid_exports(self):
        ff = os.environ['TALKING_EDIT_FFMPEG']
        video = self.root / 'original.mp4'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=30:d=3', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video)], check=True)
        narration = self.root / 'narration.wav'
        subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'sine=frequency=500:duration=3', str(narration)], check=True)
        self.ws.call(self.pid, 'import', {'file': str(video), 'kind': 'video'})
        # Actual native video URLs need the child's media cookie behind the parent proxy.
        server=Server(self.ws);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            source=self.ws.call(self.pid,'show')['project']['source']['file']
            url=server.origin+'/tool/'+self.pid+'/media?file='+source
            req=Request(url,headers={'X-Workbench-Session':server.token,'Range':'bytes=0-1023'})
            with build_opener(ProxyHandler({})).open(req) as response:
                self.assertEqual(response.status,206);self.assertEqual(len(response.read()),1024)
                self.assertTrue(response.headers['Content-Type'].startswith('video/mp4'))
            with self.assertRaises(HTTPError) as error:build_opener(ProxyHandler({})).open(Request(url))
            self.assertEqual(error.exception.code,401);error.exception.close()
        finally:server.shutdown();server.server_close();thread.join()
        s = self.ws.call(self.pid, 'show')['project']
        self.ws.call(self.pid, 'update', {'patch': {'cues': [{'id': 'line', 'start': 0, 'end': 3, 'text': 'Synthetic acceptance'}]}, 'revision': s['revision']})
        def confirm(pid, stage):
            r = self.ws.call(pid, 'review', {'stage': stage})
            return self.ws.call(pid, 'decide', {'request_id': r['id'], 'revision': r['revision'], 'action': 'confirm'})
        confirm(self.pid, 'roughcut')
        result = self.ws.call(self.pid, 'render')
        self.assertTrue(result['technicalPass'])
        self.assertFalse(self.ws.snapshot(self.pid)['state']['final_confirmed'])
        self.assertEqual(result['file'], self.ws.call(self.pid, 'render')['file'])
        confirm(self.pid, 'final')
        self.assertEqual(self.ws.snapshot(self.pid)['status'], '完成')
        # Add a real source clip, preserving audio and the existing roughcut confirmation.
        s = self.ws.call(self.pid, 'show')['project']
        self.ws.call(self.pid, 'attach-source', {'file': str(video), 'start': .5, 'end': 2, 'source_page': 'local:synthetic-original', 'match_reason': 'Original synthetic test clip', 'usage_confirmed': True, 'revision': s['revision']})
        confirm(self.pid, 'packaging'); confirm(self.pid, 'keyframes')
        hybrid = self.ws.call(self.pid, 'render')
        self.assertEqual(hybrid['animation_count'], 1)
        self.assertAlmostEqual(hybrid['duration'], 3, delta=.15)
        self.assertNotEqual(hybrid['file'], result['file'])
        # A separate narration project with explicit source provenance and permissions.
        f = self.ws.create('footage', '素材验收', str(self.root / 'projects')); fid = f['id']
        asset = self.ws.call(fid, 'import', {'file': str(video)})
        audio = self.ws.call(fid, 'import', {'file': str(narration)})
        shot = {'asset': asset['file'], 'sha256': asset['sha256'], 'duration': 3, 'source_in': 0, 'line': 'Synthetic narration', 'source_page': 'local:original', 'publisher': 'test-author', 'product': 'synthetic-v1', 'match_reason': 'Original synthetic visual', 'usage_confirmed': True, 'visually_reviewed': True}
        self.ws.call(fid, 'update', {'patch': {'script': 'Synthetic narration', 'narration': audio['file'], 'narration_hash': audio['sha256'], 'shots': [shot]}, 'revision': 1})
        self.assertTrue(self.ws.call(fid, 'audit')['ok'])
        confirm(fid, 'assets')
        output = self.ws.call(fid, 'render')
        self.assertTrue(output['technicalPass'])
        self.assertEqual(self.ws.call(fid, 'render')['file'], output['file'])
        confirm(fid, 'final')
        self.assertEqual(self.ws.snapshot(fid)['status'], '完成')
        for root, out in [(Path(self.entry['root']), result), (Path(self.entry['root']), hybrid), (Path(f['root']), output)]:
            subprocess.run([ff, '-v', 'error', '-i', str(root/out['file']), '-f', 'null', '-'], check=True)


if __name__ == '__main__': unittest.main()
