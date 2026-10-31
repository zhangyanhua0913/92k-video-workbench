"""Temporary loopback UI; all edits pass the same revisioned project API."""
import json
import mimetypes
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from core import Project, EditError, check, atomic, home
from media import import_file, waveform, speed_advice
from registry import status
from vault import Vault

ASSETS=Path(__file__).resolve().parents[1]/'assets'


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,project,port=0,idle=1800):
        super().__init__(('127.0.0.1',port),Handler)
        self.project=project;self.session=secrets.token_urlsafe(32)
        self.origin='http://127.0.0.1:'+str(self.server_port)
        self.cookie_name='talking_'+project.state()['project_id']
        self.last_activity=time.monotonic();self.idle=idle

    def descriptor(self):
        return {'origin':self.origin,'session':self.session,'project_id':self.project.state()['project_id'],'heartbeat_seconds':max(.05,min(1,self.idle/3))}


class Handler(BaseHTTPRequestHandler):
    server_version='TalkingEdit'
    def log_message(self,*args):pass

    def headers_common(self):
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def reply(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(status);self.headers_common();self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

    def authorize(self,write=False):
        check(self.headers.get('Host')==self.server.origin.removeprefix('http://'),'Host 无效。','forbidden',403)
        # Media uses a strict same-site HttpOnly cookie; API uses explicit session header.
        token=self.headers.get('X-Talking-Session','')
        if not token or urlparse(self.path).path=='/media':
            import http.cookies
            cookies=http.cookies.SimpleCookie();cookies.load(self.headers.get('Cookie',''))
            token=cookies[self.server.cookie_name].value if self.server.cookie_name in cookies else ''
        check(secrets.compare_digest(token,self.server.session),'会话无效。','unauthorized',401)
        if write:
            check(self.headers.get('Origin')==self.server.origin,'请求来源无效。','forbidden',403)
        self.server.last_activity=time.monotonic()

    def do_GET(self):
        try:
            parsed=urlparse(self.path);path=parsed.path
            if path in ('/','/app.js','/style.css'):
                check(self.headers.get('Host')==self.server.origin.removeprefix('http://'),'Host 无效。','forbidden',403)
                return self.file(ASSETS/('index.html' if path=='/' else path[1:]))
            if path=='/favicon.ico':
                self.send_response(204);self.end_headers();return
            self.authorize()
            p=self.server.project
            if path.startswith('/generation/'):
                from generation_mount import forward
                return forward(self)
            if path=='/api/health':return self.reply({'project_id':p.state()['project_id']})
            if path=='/api/generation-current':
                from generation_mount import current_review
                return self.reply(current_review(p))
            if path=='/api/workspace':
                from workspace import AREAS,categories
                return self.reply({'areas':AREAS,'style_areas':{x['id']:categories(x) for x in status() if 'packaging' in x['stages']}})
            if path=='/api/state':
                with p.db() as c:
                    row=c.execute("SELECT id FROM reviews WHERE status='pending' ORDER BY created DESC LIMIT 1").fetchone()
                outcome=p.meta/'last-command.json'
                data={'project':p.state(),'skills':status(),'tasks':p.tasks(),'request':p.review(row['id']) if row else None,'credentials':Vault().status(),'final_confirmed':p.approved('final'),'last_command':json.loads(outcome.read_text(encoding='utf-8')) if outcome.exists() else None}
                raw=json.dumps(data,ensure_ascii=False).encode()
                self.send_response(200);self.headers_common();self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Set-Cookie',self.server.cookie_name+'='+self.server.session+'; HttpOnly; SameSite=Strict; Path=/');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            if path=='/api/waveform':return self.reply(waveform(p))
            if path=='/api/speed-advice':return self.reply(speed_advice(p.state()))
            if path=='/api/batches':
                from batch import Batch
                return self.reply({'batches':Batch(p).list()})
            if path=='/api/packaging-examples':
                examples=p.root/'work'/'packaging-examples.json'
                if not examples.is_file():return self.reply({'items':[]})
                value=json.loads(examples.read_text(encoding='utf-8'))
                check(isinstance(value.get('items'),list) and len(value['items'])<=12,'样片清单无效。')
                for item in value['items']:
                    check(isinstance(item.get('title'),str) and isinstance(item.get('description'),str),'样片说明无效。')
                    video=p.public_file(item.get('file'));check(video.suffix.lower()=='.mp4','样片格式无效。')
                return self.reply(value)
            if path=='/api/quote':
                from providers import cloud_quote
                return self.reply(cloud_quote(p))
            if path=='/media':
                rel=parse_qs(parsed.query).get('file',[''])[0]
                # Never serve cloud task files, receipts or private workflow state.
                file=p.public_file(rel)
                normalized=file.relative_to(p.root).as_posix()
                check(not normalized.startswith('work/qwen-') and not (normalized.startswith('work/') and file.suffix=='.json'),'不可访问任务私密数据。','forbidden',403)
                return self.file(file,ranges=True)
            raise EditError('地址不存在。','not_found',404)
        except EditError as e:self.reply({'error':e.code,'message':str(e)},e.status)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.reply({'error':'internal','message':'本地请求失败，请恢复项目并检查状态。'},500)

    def do_POST(self):
        try:
            self.authorize(write=True)
            path=urlparse(self.path).path;p=self.server.project
            length=int(self.headers.get('Content-Length','0'))
            if path.startswith('/generation/'):
                check(not self.headers.get('Transfer-Encoding') and 0<length<=101*1024**2,'生成请求大小无效。')
                raw=self.rfile.read(length);check(len(raw)==length,'生成请求中断。')
                from generation_mount import forward
                return forward(self,raw)
            if path=='/api/batch-upload':
                from batch import Batch
                check(0<length<=2*1024**3,'文件大小须在2GB以内。')
                name=Path(unquote(self.headers.get('X-File-Name',''))).name
                batch_id=self.headers.get('X-Batch-Id','')
                temp=p.meta/('upload-'+uuid.uuid4().hex+Path(name).suffix)
                try:
                    with temp.open('xb') as f:
                        remaining=length
                        while remaining:
                            block=self.rfile.read(min(1024*1024,remaining));check(block,'上传中断。');f.write(block);remaining-=len(block)
                    return self.reply(Batch(p).add_file(batch_id,temp,name))
                finally:temp.unlink(missing_ok=True)
            if path=='/api/import':
                check(0<length<=2*1024**3,'文件大小须在2GB以内。')
                name=Path(unquote(self.headers.get('X-File-Name',''))).name
                kind=self.headers.get('X-File-Kind','')
                temp=p.meta/('upload-'+uuid.uuid4().hex+Path(name).suffix)
                try:
                    with temp.open('xb') as f:
                        remaining=length
                        while remaining:
                            block=self.rfile.read(min(1024*1024,remaining));check(block,'上传中断。');f.write(block);remaining-=len(block)
                    return self.reply(import_file(p,temp,kind,int(self.headers.get('X-Project-Revision','-1'))))
                finally:temp.unlink(missing_ok=True)
            check(0<=length<=8*1024**2,'请求过大。')
            data=json.loads(self.rfile.read(length) or b'{}')
            if path=='/api/batch-create':
                from batch import Batch
                return self.reply(Batch(p).create(data['title'],data['packaging'],data['speed'],data.get('mode','manual')))
            if path=='/api/batch-enqueue':
                from batch import Batch
                return self.reply(Batch(p).enqueue(data['item_id'],data['step']))
            if path=='/api/batch-start':
                from cli import detached
                import sys
                detached([sys.executable,str(Path(__file__).with_name('cli.py')),'--project',str(p.root),'batch-run'])
                return self.reply({'started':True,'note':'队列串行执行；Agent 创作与用户审看仍需逐项目处理。'})
            if path=='/api/batch-open':
                from batch import Batch
                from cli import review
                item=Batch(p).item(data['item_id']);stage=data.get('stage','project')
                return self.reply(review(Project(item['project_path']),stage,False))
            if path=='/api/workspace-select':
                from workspace import choose
                return self.reply(choose(p,data.get('area')))
            if path=='/api/generation-open':
                from workspace import open_generation
                result=open_generation(p)
                from urllib.parse import urlsplit
                return self.reply({'url':'/generation/'+('?' + urlsplit(result['url']).query if urlsplit(result['url']).query else '')})
            if path=='/api/heartbeat':return self.reply({'alive':True})
            if path=='/api/update':return self.reply(p.update(data['patch'],data['revision']))
            if path=='/api/decide':return self.reply(p.decide(data['request_id'],data['revision'],data['action'],data.get('note',''),data.get('cap')))
            if path=='/api/credential':return self.reply(Vault().put(data['value']))
            if path=='/api/seam':
                from media import preview_seam
                return self.reply(preview_seam(p,data['cut_id'],data['revision']))
            if path=='/api/step':
                from cli import launch_step
                return self.reply(launch_step(p,data['step']))
            if path=='/api/stop':
                self.reply({'stopped':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            raise EditError('地址不存在。','not_found',404)
        except EditError as e:self.reply({'error':e.code,'message':str(e)},e.status)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.reply({'error':'invalid','message':'请求无效，未批准后续操作。'},400)

    def file(self,path,ranges=False):
        total=path.stat().st_size;a,b=0,total-1;partial=False
        if ranges and self.headers.get('Range'):
            import re
            m=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers['Range']);check(m,'Range 无效。','range',416)
            a=int(m[1]);b=min(total-1,int(m[2]) if m[2] else total-1);check(0<=a<=b<total,'Range 越界。','range',416);partial=True
        self.send_response(206 if partial else 200);self.headers_common()
        self.send_header('Content-Type',mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        self.send_header('Content-Length',str(b-a+1))
        if ranges:self.send_header('Accept-Ranges','bytes')
        if partial:self.send_header('Content-Range',f'bytes {a}-{b}/{total}')
        self.end_headers()
        with path.open('rb') as f:
            f.seek(a);left=b-a+1
            while left:
                raw=f.read(min(left,65536))
                if not raw:break
                self.wfile.write(raw);left-=len(raw)


def serve(project,idle=1800):
    srv=Server(project,idle=idle);descriptor=project.meta/'session.json';atomic(descriptor,srv.descriptor())
    def stop_idle():
        while time.monotonic()-srv.last_activity<idle:time.sleep(min(1,idle/3))
        srv.shutdown()
    threading.Thread(target=stop_idle,daemon=True).start()
    try:srv.serve_forever(poll_interval=.2)
    finally:
        srv.server_close()
        if descriptor.exists() and json.loads(descriptor.read_text())['session']==srv.session:descriptor.unlink()
