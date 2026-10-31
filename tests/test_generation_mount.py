import sys,tempfile,unittest,json,threading,urllib.request,urllib.error
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/talking-edit/scripts'))
from core import Project
from web import Server
from generation_mount import rewrite,binding,current_review
class Child(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.headers.get('X-Director-Session')!='child-secret':self.send_response(401);self.end_headers();return
  raw=(b'<script src="/app.js"></script>' if self.path=='/' else b'abcdef')
  self.send_response(206 if self.headers.get('Range') else 200);self.send_header('Content-Length',str(len(raw)));self.send_header('Content-Type','text/html' if self.path=='/' else 'video/mp4');self.send_header('Set-Cookie','director=should-not-leak');self.end_headers();self.wfile.write(raw)
 def do_POST(self):
  raw=self.rfile.read(int(self.headers['Content-Length']));ok=self.headers.get('X-Director-Session')=='child-secret' and self.headers.get('Origin')==f'http://127.0.0.1:{self.server.server_port}'
  self.send_response(200 if ok else 403);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(raw)
class MountTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Project.create(Path(self.tmp.name)/'p','mount test');self.child=ThreadingHTTPServer(('127.0.0.1',0),Child);threading.Thread(target=self.child.serve_forever,daemon=True).start()
  root=self.p.root/'generation';(root/'.director').mkdir(parents=True);(root/'project.json').write_text(json.dumps({'project_id':'child-id'}));(root/'.director/session.json').write_text(json.dumps({'origin':f'http://127.0.0.1:{self.child.server_port}','project_id':'child-id','session':'child-secret'}))
  self.server=Server(self.p);threading.Thread(target=self.server.serve_forever,daemon=True).start();self.op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 def tearDown(self):
  for srv in [self.server,self.child]:srv.shutdown();srv.server_close()
  self.tmp.cleanup()
 def request(self,path,body=None,auth=True):
  h={'Origin':self.server.origin}
  if auth:h['X-Talking-Session']=self.server.session
  return self.op.open(urllib.request.Request(self.server.origin+path,data=body,headers=h))
 def test_requires_parent_auth(self):
  with self.assertRaises(urllib.error.HTTPError) as e:self.request('/generation/',auth=False)
  self.assertEqual(e.exception.code,401);e.exception.close()
 def test_scoped_html_and_no_child_cookie(self):
  with self.request('/generation/') as r:
   self.assertIn(b'/generation/app.js',r.read());self.assertNotIn('Set-Cookie',r.headers);self.assertIn("frame-ancestors 'self'",r.headers['Content-Security-Policy'])
 def test_post_and_range(self):
  with self.request('/generation/api/project',b'{"draft":"test"}') as r:self.assertEqual(json.loads(r.read())['draft'],'test')
  with self.op.open(urllib.request.Request(self.server.origin+'/generation/media/a.mp4',headers={'X-Talking-Session':self.server.session,'Range':'bytes=0-5'})) as r:self.assertEqual(r.status,206);self.assertEqual(r.read(),b'abcdef')
 def test_follow_latest_pending_review(self):
  import sqlite3
  db=self.p.root/'generation/.director/state.sqlite3'
  with sqlite3.connect(db) as c:
   c.execute('CREATE TABLE reviews(id TEXT,status TEXT,created REAL)');c.executemany('INSERT INTO reviews VALUES(?,?,?)',[('old','completed',1),('next','pending',2)])
  c.close()
  self.assertEqual(current_review(self.p)['url'],'/generation/?review=next')
 def test_rewrite_media_and_upload(self):
  self.assertIn(b"'/generation/api/import'",rewrite('/app.js',b"fetch('/api/import');const path='/media/a.mp4';"))
if __name__=='__main__':unittest.main()
