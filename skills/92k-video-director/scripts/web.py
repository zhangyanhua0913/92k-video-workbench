"""Ephemeral loopback review server, with authenticated media and no request logging."""
import hmac
import json
import mimetypes
import secrets
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote
from core import check, DirectorError, dump, atomic
from provider import Client
from vault import Vault
from media import doctor

UI = Path(__file__).resolve().parent.parent / 'assets' / 'ui'


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, project, vault=None, port=0):
        self.project, self.vault = project, vault or Vault()
        self.session = secrets.token_urlsafe(32)
        self.cookie_name = 'director_' + project.state()['project_id'][:16]
        self.last_activity = time.monotonic()
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)

    def descriptor(self):
        return {'origin': self.origin, 'session': self.session, 'project_id': self.project.state()['project_id']}


class Handler(BaseHTTPRequestHandler):
    server_version = 'Director/0.1'

    def log_message(self, *args):
        pass

    def headers_common(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def respond(self, value, status=200, cookie=False):
        data = dump(value).encode()
        self.send_response(status)
        self.headers_common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        if cookie:
            self.send_header('Set-Cookie', self.server.cookie_name + '=' + self.server.session + '; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers()
        self.wfile.write(data)

    def authorize(self, post=False):
        check(self.headers.get('Host') == self.server.origin.removeprefix('http://'), '无效的本机Host。', 'forbidden', 403)
        supplied = self.headers.get('X-Director-Session', '')
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie', ''))
        except Exception:
            pass
        cookie_value = cookie.get(self.server.cookie_name)
        valid_header = hmac.compare_digest(supplied, self.server.session)
        valid_cookie = cookie_value and hmac.compare_digest(cookie_value.value, self.server.session)
        check(valid_header or valid_cookie, '会话已失效，请由Agent重新打开页面。', 'unauthorized', 401)
        if post:
            origin = self.headers.get('Origin')
            check(origin == self.server.origin or (not origin and valid_header), '拒绝跨站请求。', 'forbidden', 403)
            check(valid_header or self.headers.get('X-Director-Request') == '1', '缺少交互请求标识。', 'forbidden', 403)
        self.server.last_activity = time.monotonic()

    def do_GET(self):
        try:
            parts = urlsplit(self.path)
            if parts.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            if parts.path in ('/', '/app.js', '/style.css'):
                check(self.headers.get('Host') == self.server.origin.removeprefix('http://'), '无效Host。', status=403)
                filename = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[parts.path]
                return self.file(UI / filename)
            self.authorize()
            if parts.path == '/api/state':
                return self.respond(self.server.project.summary())
            if parts.path == '/api/config':
                return self.respond(self.server.vault.status())
            if parts.path == '/api/doctor':
                return self.respond(doctor())
            if parts.path == '/api/review':
                return self.respond(self.server.project.review(parse_qs(parts.query).get('id', [''])[0]))
            if parts.path == '/api/health':
                return self.respond({'project_id': self.server.project.state()['project_id']})
            if parts.path.startswith('/media/'):
                relative = unquote(parts.path.removeprefix('/media/'))
                check(relative.startswith(('media/', 'exports/')), '只提供项目媒体和成片。', status=403)
                return self.file(self.server.project.inside(relative))
            raise DirectorError('页面不存在。', status=404)
        except DirectorError as error:
            self.respond({'error': str(error), 'code': error.code}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond({'error': '读取失败，请重新打开页面。', 'code': 'internal'}, 500)

    def do_POST(self):
        try:
            self.authorize(True)
            path = urlsplit(self.path).path
            length = int(self.headers.get('Content-Length', '0'))
            check(not self.headers.get('Transfer-Encoding') and 0 < length <= 101 * 1024 * 1024, '请求大小或编码无效。')
            if path == '/api/import':
                name = unquote(self.headers.get('X-Filename', ''))
                suffix = Path(name).suffix.lower()
                check(suffix in ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.webm', '.mov', '.wav', '.mp3', '.m4a', '.flac', '.ogg') and length <= 100 * 1024 * 1024, '请选择100MB以内的支持素材。')
                import uuid
                relative = 'media/' + uuid.uuid4().hex + suffix
                with self.server.project.inside(relative).open('xb') as stream:
                    remain = length
                    while remain:
                        chunk = self.rfile.read(min(65536, remain))
                        check(chunk, '上传中断。')
                        stream.write(chunk)
                        remain -= len(chunk)
                return self.respond({'file': relative, 'name': name})
            check(length <= 2 * 1024 * 1024, 'JSON请求过大。')
            data = json.loads(self.rfile.read(length).decode('utf-8'))
            if path == '/api/bootstrap':
                return self.respond({'connected': True}, cookie=True)
            if path == '/api/key':
                result = self.server.vault.put(data.get('key'))
                return self.respond(result)
            if path == '/api/key/delete':
                return self.respond(self.server.vault.delete(data.get('id')))
            if path == '/api/account':
                return self.respond(Client(self.server.vault).account())
            if path == '/api/project':
                return self.respond(self.server.project.update(data['project'], data['revision']))
            if path == '/api/candidate':
                return self.respond(self.server.project.add_candidate(data['shot_id'], data['file']))
            if path == '/api/decision':
                allowed = ('action', 'revision', 'data', 'cap', 'selections', 'note')
                return self.respond(self.server.project.decide(data['request_id'], **{k: data[k] for k in allowed if k in data}))
            if path == '/api/stop':
                self.respond({'stopping': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            raise DirectorError('接口不存在。', status=404)
        except DirectorError as error:
            self.respond({'error': str(error), 'code': error.code}, error.status)
        except (KeyError, ValueError, TypeError):
            self.respond({'error': '输入格式无效，请检查后重试。', 'code': 'invalid'}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.respond({'error': '操作失败，原项目保留；请交给Agent检查。', 'code': 'internal'}, 500)

    def file(self, path):
        check(path.is_file(), '文件不存在。', status=404)
        size = path.stat().st_size
        start, end = 0, size - 1
        range_header = self.headers.get('Range')
        if range_header:
            import re
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
            check(match is not None, 'Range无效。', status=416)
            if match[1]:
                start = int(match[1])
                end = min(end, int(match[2])) if match[2] else end
            else:
                check(match[2], 'Range无效。', status=416)
                start = max(0, size - int(match[2]))
            check(0 <= start <= end < size, 'Range超出范围。', status=416)
        self.send_response(206 if range_header else 200)
        self.headers_common()
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        if range_header:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(max(0, end - start + 1)))
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = stream.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)


def serve(project, vault=None):
    server = ReviewServer(project, vault)
    descriptor = project.root / '.director' / 'session.json'
    atomic(descriptor, server.descriptor())

    def idle_stop():
        while time.monotonic() - server.last_activity < 1800:
            time.sleep(10)
        server.shutdown()

    threading.Thread(target=idle_stop, daemon=True).start()
    try:
        server.serve_forever(poll_interval=.25)
    finally:
        server.server_close()
        # Do not remove the descriptor of a replacement server.
        if descriptor.exists() and json.loads(descriptor.read_text(encoding='utf-8')).get('session') == server.session:
            descriptor.unlink()
