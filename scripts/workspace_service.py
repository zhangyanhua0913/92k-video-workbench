"""Local workspace registry and authenticated adapters. Media and Skill databases stay in projects."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit, parse_qs, quote
import urllib.request
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
MODES = {'talk': '口播视频剪辑', 'footage': '素材解说成片', 'generate': 'AI 视频生成', 'hybrid': '真人混搭成片'}
ACTIONS = {
    'talk': {'show', 'doctor', 'import', 'update', 'review', 'decide', 'recover', 'retry-local', 'analyze', 'transcribe', 'render', 'roughcut', 'packaging', 'auto-gold', 'attach-source'},
    'generate': {'show', 'doctor', 'import', 'update', 'review', 'decide', 'recover', 'prepare', 'quote', 'submit', 'poll', 'download', 'render', 'retry-local'},
    'footage': {'show', 'doctor', 'import', 'update', 'review', 'decide', 'recover', 'audit', 'render', 'retry-local'},
}
ACTIONS['hybrid'] = ACTIONS['talk']
for mode in ('talk', 'hybrid'):
    ACTIONS[mode] = ACTIONS[mode] | {'adopt-style'}
READS = {'show', 'doctor', 'audit'}
LONG = {'analyze', 'transcribe', 'render', 'auto-gold', 'prepare', 'quote', 'submit', 'poll', 'download', 'attach-source'}


class WorkspaceError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def check(ok, message, status=400):
    if not ok: raise WorkspaceError(message, status)


def invoke(mode, root, action, data):
    result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/adapter_worker.py'), mode, str(root), action],
                            input=json.dumps(data, ensure_ascii=False), capture_output=True, encoding='utf-8',
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    try: value = json.loads(result.stdout)
    except ValueError: raise WorkspaceError('子工具未正常返回，请核对依赖与原项目。', 500) from None
    check(value.get('ok'), value.get('message', '子工具失败。'), value.get('status', 400))
    return value['result']


def state_from(root, mode):
    marker = {'talk': '.talking-edit', 'hybrid': '.talking-edit', 'generate': '.director', 'footage': '.footage'}[mode]
    file = root / marker / 'state.sqlite3'
    check(file.is_file(), '目录中没有对应的工程数据库。')
    try:
        with contextlib.closing(sqlite3.connect(file.as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT revision,data FROM state').fetchone()
        value = json.loads(row[1])
        check(isinstance(value.get('project_id'), str) and isinstance(value.get('title'), str), '工程格式不兼容。')
        return {**value, 'revision': row[0]}
    except (sqlite3.Error, ValueError, TypeError, IndexError):
        raise WorkspaceError('工程格式不兼容，请继续使用原工具打开；没有修改原文件。') from None


class Workspace:
    def __init__(self, home=None):
        self.home = Path(home or os.environ.get('WORKBENCH_HOME', Path.home() / '.92k-video-workbench')).resolve()
        check(not self.home.is_relative_to(ROOT), '工作台数据须放在仓库之外。')
        self.home.mkdir(parents=True, exist_ok=True)
        self.default_root = Path.home() / '92k-video-projects'
        self.dbfile = self.home / 'workspace.sqlite3'
        self.children = {}
        self.child_lock = threading.Lock()
        self.gates = {}
        self.gates_lock = threading.Lock()
        self.workers = []
        self.owner = uuid.uuid4().hex
        with self.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, root TEXT UNIQUE, mode TEXT, created REAL);
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, project_id TEXT, action TEXT, status TEXT, result TEXT, created REAL, owner TEXT);
              CREATE UNIQUE INDEX IF NOT EXISTS active_job ON jobs(project_id) WHERE status='running';''')
            db.execute('CREATE TABLE IF NOT EXISTS user_defaults(mode TEXT PRIMARY KEY, revision INTEGER, data TEXT)')

    def defaults(self, mode, patch=None, revision=None):
        """Explicit local new-project defaults, never approvals or existing-project edits."""
        check(mode in ('talk', 'hybrid'), '该入口暂无常用制作设置。')
        factory = {'speed': 1, 'subtitle_burn': True, 'transcribe_language': 'auto', 'packaging': 'none'}
        with self.db() as db:
            row = db.execute('SELECT revision,data FROM user_defaults WHERE mode=?', (mode,)).fetchone()
            rev, values = (row['revision'], json.loads(row['data'])) if row else (0, factory)
            if patch is not None:
                check(type(revision) is int and revision == rev, '另一页面已修改常用设置，请重新打开配置中心。', 409)
                check(isinstance(patch, dict) and set(patch) <= set(factory), '未知常用设置字段。')
                values = {**values, **patch}
                check(type(values['speed']) in (int, float) and values['speed'] in (1, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35, 1.5), '不支持的速度。')
                check(type(values['subtitle_burn']) is bool, '字幕设置无效。')
                check(values['transcribe_language'] in ('auto', 'zh', 'en', 'ja', 'ko'), '转写语言无效。')
                check(values['packaging'] in ('none', 'fredtalk-motion', 'remotion-gold', 'remotion-plugin', 'remotion-evidence', 'narration-footage-v0-1'), '风格无效。')
                rev += 1
                db.execute('INSERT OR REPLACE INTO user_defaults VALUES(?,?,?)', (mode, rev, json.dumps(values)))
            return {'mode': mode, 'revision': rev, 'values': values}

    @contextlib.contextmanager
    def db(self):
        c = sqlite3.connect(self.dbfile, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback(); raise
        finally: c.close()

    def gate(self, pid):
        with self.gates_lock: return self.gates.setdefault(pid, threading.RLock())

    def recover_jobs(self):
        # Called only by the single service holding the OS workspace lock.
        with self.db() as db:
            db.execute("UPDATE jobs SET status='interrupted',result=? WHERE status='running'", (json.dumps({'message': '工作台已重启；核查原任务后显式恢复，不自动重试。'}),))

    def safe_root(self, root):
        p = Path(root).expanduser()
        check(p.is_absolute(), '请提供工程绝对路径。')
        p = p.resolve()
        check(not p.is_relative_to(ROOT) and not ROOT.is_relative_to(p) and p != self.home and not p.is_relative_to(self.home), '工程须在源码和工作台私密目录之外。')
        return p

    def project(self, pid):
        with self.db() as db: row = db.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        check(row is not None, '工程未登记。', 404)
        root = self.safe_root(row['root'])
        s = state_from(root, row['mode'])
        check(s['project_id'] == pid, '工程已被替换，请重新登记。', 409)
        return dict(row), root, s

    def list(self):
        with self.db() as db: rows = [dict(x) for x in db.execute('SELECT * FROM projects ORDER BY created DESC')]
        output = []
        for row in rows:
            try:
                _, _, state = self.project(row['id'])
                output.append({**row, 'title': state['title'], 'revision': state['revision']})
            except ValueError as error: output.append({**row, 'title': '工程不可用', 'error': str(error)})
        return output

    def register(self, path, mode=None):
        root = self.safe_root(path)
        descriptor = root / 'workbench-project.json'
        modes = [m for m, marker in [('talk', '.talking-edit'), ('generate', '.director'), ('footage', '.footage')] if (root / marker / 'state.sqlite3').is_file()]
        check(len(modes) == 1, '未找到唯一兼容工程；请选择口播、生成或素材工程的实际目录。')
        found = modes[0]
        if descriptor.exists():
            declared = json.loads(descriptor.read_text(encoding='utf-8'))
            check(declared.get('schema') == 1, '统一项目版本暂不支持，请使用原工具。')
            found = declared['mode']
        mode = mode or found
        check(mode in MODES and (mode == found or {mode, found} <= {'talk', 'hybrid'}), '工程类型不匹配。')
        s = state_from(root, mode)
        with self.db() as db:
            old = db.execute('SELECT * FROM projects WHERE id=? OR root=?', (s['project_id'], str(root))).fetchone()
            if old:
                check(old['root'] == str(root) and old['id'] == s['project_id'] and old['mode'] == mode, '工程编号或路径已登记，请保留原登记。', 409)
            else: db.execute('INSERT INTO projects VALUES(?,?,?,?)', (s['project_id'], str(root), mode, time.time()))
        # Registration writes only the local index, never the original project.
        return {'id': s['project_id'], 'root': str(root), 'mode': mode, 'title': s['title']}

    def create(self, mode, title, parent=None):
        check(mode in MODES and isinstance(title, str) and 0 < len(title.strip()) <= 300, '工程类型或标题无效。')
        parent = self.safe_root(parent or str(self.default_root))
        root = parent / ('project-' + uuid.uuid4().hex[:12])
        state = invoke(mode, root, 'create', {'title': title.strip()})
        if mode in ('talk', 'hybrid'):
            defaults = self.defaults(mode)
            if defaults['revision']:
                values = defaults['values']
                state = invoke(mode, root, 'update', {'revision': state['revision'], 'patch': {
                    'speed': values['speed'], 'subtitle_burn': values['subtitle_burn'],
                    'transcribe_language': values['transcribe_language'],
                    'workflow': {**state['workflow'], 'packaging': values['packaging']}}})
        description = {'schema': 1, 'project_id': state['project_id'], 'mode': mode, 'engine_root': '.',
                       'package_version': (ROOT / 'VERSION').read_text().strip()}
        (root / 'workbench-project.json').write_text(json.dumps(description, ensure_ascii=False, indent=2), encoding='utf-8')
        if mode in ('talk', 'hybrid'):
            self.style_lock(root, mode, state, adopt=True)
        return self.register(str(root))

    def style_lock(self, root, mode, state, adopt=False):
        path = root / 'workbench-style.json'
        selection = state['workflow']['packaging']
        actual = invoke(mode, root, 'style-version', {'selection': selection})
        check(len(actual) == 1, '所选风格不可用，请核查安装。')
        if path.exists():
            old = json.loads(path.read_text(encoding='utf-8'))
            if old['selection'] == selection and not adopt:
                check(old['versions'] == actual, '风格源码版本已变化，原项目未自动升级；检查差异后显式采用当前风格版本。', 409)
                return old
        value = {'selection': selection, 'versions': actual, 'package_version': (ROOT / 'VERSION').read_text().strip()}
        # Written only after creating a new project or an explicit editing/execution action.
        tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8'); tmp.replace(path)
        return value

    def jobs(self, pid):
        with self.db() as db:
            return [dict(x, result=json.loads(x['result']) if x['result'] else None) for x in db.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY created DESC LIMIT 30', (pid,))]

    def call(self, pid, action, data=None, background=False):
        data = data or {}
        with self.gate(pid):
            row, root, state = self.project(pid)
            check(action in ACTIONS[row['mode']], '不支持该工程操作。')
            if action in READS: return invoke(row['mode'], root, action, data)
            active = next((j for j in self.jobs(pid) if j['status'] == 'running'), None)
            if active:
                if active['action'] == action and background: return {'job': active['id'], 'status': 'running', 'reused': True}
                raise WorkspaceError('本工程步骤执行中，请等待并查看原任务。', 409)
            if row['mode'] in ('talk', 'hybrid'):
                if action == 'adopt-style': return self.style_lock(root, row['mode'], state, adopt=True)
                if action in ('render', 'auto-gold', 'packaging'):
                    self.style_lock(root, row['mode'], state)
                if action == 'update' and data.get('patch', {}).get('workflow', state['workflow']) != state['workflow']:
                    result = invoke(row['mode'], root, action, data)
                    self.style_lock(root, row['mode'], result, adopt=True)
                    return result
            if not background: return invoke(row['mode'], root, action, data)
            jid = uuid.uuid4().hex
            with self.db() as db:
                db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)', (jid, pid, action, 'running', None, time.time(), self.owner))
            def work():
                try:
                    result = invoke(row['mode'], root, action, data)
                    status = 'done'
                except Exception as error:
                    result = {'message': str(error) if isinstance(error, ValueError) else '步骤失败，核查原项目。'}
                    status = 'failed'
                with self.db() as db:
                    db.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (status, json.dumps(result, ensure_ascii=False), jid))
            # A normal server close waits for executing steps, rather than orphaning them.
            worker = threading.Thread(target=work, daemon=False)
            self.workers.append(worker)
            worker.start()
            return {'job': jid, 'status': 'running'}

    def snapshot(self, pid):
        row, root, _ = self.project(pid)
        result = self.call(pid, 'show')
        jobs = self.jobs(pid)
        s = result['project']
        running = any(j['status'] == 'running' for j in jobs)
        reviews = result.get('reviews', [])
        rendered = [x for x in result.get('renders', result.get('tasks', [])) if x['status'] in ('done', 'succeeded') and (x.get('kind', 'render') == 'render') and x.get('result')]
        current = [x for x in rendered if x.get('revision', x['result'].get('revision')) == s['revision']]
        status = '待配置'
        if running or any(x['status'] == 'running' for x in result.get('tasks', [])): status = '执行中'
        elif s.get('paused'): status = '已暂停'
        elif any(x.get('status', x.get('action')) == 'pending' and x['revision'] == s['revision'] for x in reviews): status = '待审阅'
        elif current: status = '完成' if result.get('final_confirmed') or any(x.get('action') == 'confirm' and x.get('stage') == 'final' and x['revision'] == s['revision'] for x in reviews) else '待审阅'
        elif jobs and jobs[0]['status'] in ('failed', 'interrupted'): status = '失败' if jobs[0]['status'] == 'failed' else '待核查'
        elif jobs and jobs[0]['result'] and jobs[0]['result'].get('execution') == 'agent': status = '等待 Agent'
        elif s.get('source') or s.get('shots'): status = '可执行'
        elif s.get('script'): status = '等待 Agent'
        return {'entry': row, 'state': result, 'jobs': jobs, 'status': status, 'outputs': [x['result'] for x in rendered], 'preferences': self.preferences(pid)}

    def preferences(self, pid, patch=None, revision=None):
        """UI position and creative intent; never a second engine or financial ledger."""
        with self.gate(pid):
            row, root, state = self.project(pid)
            path = root / 'workbench-ui.json'
            value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema': 1, 'revision': 0, 'step': 0}
            check(value.get('schema') == 1, '界面记录版本暂不支持。')
            if patch is None: return value
            check(revision == value['revision'], '另一页面已更新制作步骤，请刷新。', 409)
            check(set(patch) <= {'step', 'style', 'feedback'}, '未知界面字段。')
            if 'step' in patch: check(type(patch['step']) is int and 0 <= patch['step'] <= 5, '步骤无效。')
            if 'style' in patch: check(patch['style'] in ({'footage', 'free'} if row['mode'] == 'footage' else {'director'} if row['mode'] == 'generate' else set()), '风格选择须使用原制作接口。')
            if 'feedback' in patch:
                check(isinstance(patch['feedback'], str) and len(patch['feedback']) <= 10000, '修改意见过长。')
                patch = {**patch, 'feedback_project_revision': state['revision']}
            value = {**value, **patch, 'revision': value['revision'] + 1}
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8'); temporary.replace(path)
            return value

    def child(self, pid):
        with self.child_lock:
            row, root, _ = self.project(pid)
            check(row['mode'] != 'footage', '素材工程不使用子工具页。')
            old = self.children.get(pid)
            if old and old[0].poll() is None: return old[1]
            proc = subprocess.Popen([sys.executable, '-X', 'utf8', str(ROOT / 'scripts/adapter_worker.py'), row['mode'], str(root), 'serve'],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            proc.stdin.write('{}'); proc.stdin.close()
            try:
                # Isolated child binds localhost before returning this single private descriptor.
                descriptor = json.loads(proc.stdout.readline())['result']
                check(descriptor['project_id'] == pid and re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', descriptor['origin']), '子工具绑定无效。')
            except Exception:
                proc.terminate(); proc.wait(); raise WorkspaceError('子工具未能启动。', 500) from None
            self.children[pid] = proc, descriptor
            return descriptor

    def close(self):
        # Keep the service/update leases until executing local adapters have returned.
        for worker in self.workers: worker.join()
        for proc, _ in self.children.values():
            if proc.poll() is None: proc.terminate()
            proc.wait(timeout=10)
            if proc.stdout: proc.stdout.close()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, workspace, port=0):
        self.workspace = workspace
        self.token = secrets.token_urlsafe(32)
        super().__init__(('127.0.0.1', port), Handler)
        self.origin = f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def common(self, embedded=False):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-src 'self'; frame-ancestors " + ("'self'" if embedded else "'none'") + "; base-uri 'none'; form-action 'self'")

    def reply(self, value, status=200, cookie=False):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status); self.common()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        if cookie: self.send_header('Set-Cookie', 'wb=' + self.server.token + '; HttpOnly; SameSite=Strict; Path=/')
        self.end_headers(); self.wfile.write(raw)

    def authorize(self, write=False):
        from http.cookies import SimpleCookie
        check(self.headers.get('Host') == self.server.origin.removeprefix('http://'), 'Host无效。', 403)
        cookies = SimpleCookie(); cookies.load(self.headers.get('Cookie', ''))
        token = self.headers.get('X-Workbench-Session') or (cookies['wb'].value if 'wb' in cookies else '')
        check(secrets.compare_digest(token, self.server.token), '会话已失效，请重新打开工作台。', 401)
        if write: check(self.headers.get('Origin') == self.server.origin, '拒绝跨站操作。', 403)

    def read_body(self, maximum=8*1024*1024):
        length = int(self.headers.get('Content-Length', '0'))
        check(not self.headers.get('Transfer-Encoding') and 0 < length <= maximum, '请求大小无效。')
        body = self.rfile.read(length)
        check(len(body) == length, '请求中断。')
        return body

    def do_GET(self): self.handle_request(False)
    def do_POST(self): self.handle_request(True)

    def handle_request(self, write):
        try:
            path = urlsplit(self.path).path
            ws = self.server.workspace
            if not write and path in ('/', '/app.js', '/style.css', '/hosted.js'):
                check(self.headers.get('Host') == self.server.origin.removeprefix('http://'), 'Host无效。', 403)
                file = ROOT / 'prototype' / 'live' / ('index.html' if path == '/' else path[1:])
                import mimetypes
                raw = file.read_bytes()
                self.send_response(200); self.common()
                self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] + '; charset=utf-8')
                self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw); return
            self.authorize(write)
            if write and path == '/api/upload': return self.upload()
            match = re.fullmatch(r'/tool/([a-f0-9-]+)/(.+)?', path)
            if match: return self.proxy(match[1], '/' + (match[2] or ''), write)
            if not write:
                if path == '/api/defaults': return self.reply(ws.defaults(parse_qs(urlsplit(self.path).query).get('mode', ['talk'])[0]))
                if path == '/api/projects': return self.reply({'projects': ws.list(), 'default_root': str(ws.default_root), 'version': (ROOT / 'VERSION').read_text().strip()})
                if path == '/api/project': return self.reply(ws.snapshot(parse_qs(urlsplit(self.path).query).get('id', [''])[0]))
                if path == '/media': return self.media()
                if path == '/api/health': return self.reply({'ok': True})
                raise WorkspaceError('地址不存在。', 404)
            data = json.loads(self.read_body())
            if path == '/api/bootstrap': return self.reply({'ok': True}, cookie=True)
            if path == '/api/create': return self.reply(ws.create(data['mode'], data['title'], data.get('parent')))
            if path == '/api/register': return self.reply(ws.register(data['root'], data.get('mode')))
            if path == '/api/preferences': return self.reply(ws.preferences(data['id'], data['patch'], data['revision']))
            if path == '/api/defaults': return self.reply(ws.defaults(data['mode'], data['patch'], data['revision']))
            if path == '/api/action':
                return self.reply(ws.call(data['id'], data['action'], data.get('data'), data['action'] in LONG))
            if path == '/api/tool':
                row, _, _ = ws.project(data['id']); ws.child(data['id'])
                query = '?review=' + quote(data['review'], safe='') if data.get('review') else ''
                return self.reply({'url': '/tool/' + data['id'] + '/' + query, 'mode': row['mode']})
            raise WorkspaceError('地址不存在。', 404)
        except WorkspaceError as error: self.reply({'message': str(error)}, error.status)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError): pass
        except (ValueError, KeyError, TypeError): self.reply({'message': '输入格式无效，请刷新后核对。'}, 400)
        except Exception: self.reply({'message': '本地操作失败，原项目保留，请核查依赖与目录。'}, 500)

    def upload(self):
        from urllib.parse import unquote
        ws = self.server.workspace
        pid = parse_qs(urlsplit(self.path).query).get('id', [''])[0]
        row, root, _ = ws.project(pid)
        suffix = Path(unquote(self.headers.get('X-Filename', ''))).suffix.lower()
        check(suffix in ('.mp4', '.mov', '.mkv', '.webm', '.png', '.jpg', '.jpeg', '.webp', '.wav', '.mp3', '.m4a', '.flac', '.srt', '.txt', '.md'), '不支持的文件类型。')
        length = int(self.headers.get('Content-Length', '0'))
        check(not self.headers.get('Transfer-Encoding') and 0 < length <= 2*1024**3, '请选择2GB以内素材。')
        tmpdir = ws.home / 'uploads'; tmpdir.mkdir(exist_ok=True)
        temp = tmpdir / (uuid.uuid4().hex + suffix)
        try:
            with temp.open('xb') as stream:
                remain = length
                while remain:
                    block = self.rfile.read(min(65536, remain)); check(block, '上传中断。')
                    stream.write(block); remain -= len(block)
            data = {'file': str(temp), 'kind': self.headers.get('X-File-Kind', 'artifact')}
            return self.reply(ws.call(pid, 'import', data))
        finally: temp.unlink(missing_ok=True)

    def media(self):
        params = parse_qs(urlsplit(self.path).query)
        row, root, _ = self.server.workspace.project(params.get('id', [''])[0])
        check(row['mode'] == 'footage', '请通过对应工具读取媒体。', 403)
        file = (root / params.get('file', [''])[0]).resolve()
        check(file.is_relative_to(root) and file.relative_to(root).parts[0] in ('media', 'exports') and file.suffix.lower() in ('.mp4', '.mov', '.webm', '.png', '.jpg', '.jpeg', '.webp', '.wav', '.mp3', '.m4a', '.flac', '.srt'), '媒体路径无效。', 403)
        check(file.is_file(), '媒体不存在。', 404)
        import mimetypes
        size = file.stat().st_size
        start, end = 0, size-1
        if self.headers.get('Range'):
            m = re.fullmatch(r'bytes=(\d+)-(\d*)', self.headers['Range'])
            check(m is not None, 'Range无效。', 416)
            start = int(m[1]); end = min(end, int(m[2])) if m[2] else end
            check(0 <= start <= end < size, 'Range越界。', 416)
        self.send_response(206 if self.headers.get('Range') else 200); self.common()
        self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes'); self.send_header('Content-Length', str(max(0, end-start+1)))
        if self.headers.get('Range'): self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with file.open('rb') as stream:
            stream.seek(start); remain = end-start+1
            while remain > 0:
                block = stream.read(min(remain, 65536))
                if not block: break
                self.wfile.write(block); remain -= len(block)

    def proxy(self, pid, path, write):
        ws = self.server.workspace
        row, _, _ = ws.project(pid)
        # Child processes are fixed adapters, never user-provided destinations.
        check(path in ('/', '/app.js', '/style.css', '/favicon.ico') or path.startswith(('/api/', '/media')), '工具路径不存在。', 404)
        descriptor = ws.child(pid)
        prefix = '/tool/' + pid
        target = descriptor['origin'] + path + ('?' + urlsplit(self.path).query if urlsplit(self.path).query else '')
        header = 'X-Director-Session' if row['mode'] == 'generate' else 'X-Talking-Session'
        headers = {header: descriptor['session'], 'Origin': descriptor['origin']}
        if row['mode'] in ('talk', 'hybrid') and path == '/media':
            # Talking media intentionally requires its own cookie, not an API header.
            # Bind only this authenticated project's ephemeral child cookie internally.
            headers['Cookie'] = 'talking_' + pid + '=' + descriptor['session']
        for key in ('Content-Type', 'Range', 'X-Filename', 'X-File-Name', 'X-File-Kind', 'X-Project-Revision', 'X-Director-Request'):
            if self.headers.get(key): headers[key] = self.headers[key]
        upload = write and path == '/api/import'
        length = int(self.headers.get('Content-Length', '0')) if upload else 0
        if upload: check(not self.headers.get('Transfer-Encoding') and 0 < length <= 2*1024**3, '请求大小无效。')
        body = self.read_body() if write and not upload else None
        if write and path == '/api/step' and row['mode'] != 'generate':
            data = json.loads(body)
            return self.reply(ws.call(pid, data['step'], {}, background=True))
        if write and path == '/api/update' and row['mode'] != 'generate':
            data = json.loads(body)
            return self.reply(ws.call(pid, 'update', data))
        # Unified jobs and child writes share one per-project gate. No edits during a job.
        with ws.gate(pid):
            if write:
                check(path in ('/api/heartbeat', '/api/bootstrap') or not any(j['status'] == 'running' for j in ws.jobs(pid)), '本工程正在执行，请等待原步骤。', 409)
                check(path not in ('/api/step', '/api/batch-start', '/api/stop', '/api/generation-open'), '请使用工作台执行入口；原独立工具仍可使用。')
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *args): return None
            if upload:
                import http.client
                connection = http.client.HTTPConnection('127.0.0.1', urlsplit(descriptor['origin']).port, timeout=120)
                connection.putrequest('POST', path)
                for key, value in headers.items(): connection.putheader(key, value)
                connection.putheader('Content-Length', str(length)); connection.endheaders()
                remaining = length
                while remaining:
                    block = self.rfile.read(min(65536, remaining)); check(block, '上传中断。')
                    connection.send(block); remaining -= len(block)
                response = connection.getresponse()
            else:
                request = urllib.request.Request(target, body, headers, method='POST' if write else 'GET')
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
                try: response = opener.open(request, timeout=120)
                except urllib.error.HTTPError as error: response = error
            with response:
                transformed = path in ('/', '/app.js', '/style.css') and response.status == 200
                raw = response.read(8*1024*1024) if transformed else None
                if transformed and path != '/style.css':
                    text = raw.decode('utf-8')
                    # Rewrite all same-origin API/media paths in the bundled static documents.
                    text = re.sub(r'([\'"`])/(api/|media|generation/|app\.js|style\.css)', lambda m: m[1] + prefix + '/' + m[2], text)
                    if path == '/app.js' and row['mode'] != 'generate':
                        text = text.replace("area=null,", "area='" + row['mode'] + "',").replace("tab='home'", "tab='project'")
                        text = text.replace("batch:'批量处理',", '').replace("button('选择功能'", "button('项目与素材'")
                    panel = parse_qs(urlsplit(self.path).query).get('panel', [''])[0]
                    if path == '/' and panel:
                        check(panel in ('project', 'roughcut', 'workflow', 'packaging', 'keyframes', 'final', 'config', 'storyboard', 'voices', 'budget', 'assets'), '未知编辑面板。')
                        text = text.replace('</body>', '<script src="/hosted.js?engine=' + row['mode'] + '&panel=' + panel + '"></script></body>')
                    raw = text.encode('utf-8')
                self.send_response(response.status); self.common(embedded=True)
                for key in ('Content-Type', 'Content-Range', 'Accept-Ranges'):
                    if response.headers.get(key): self.send_header(key, response.headers[key])
                if raw is not None: self.send_header('Content-Length', str(len(raw)))
                elif response.headers.get('Content-Length'): self.send_header('Content-Length', response.headers['Content-Length'])
                self.end_headers()
                if raw is not None: self.wfile.write(raw)
                else:
                    while True:
                        block = response.read(65536)
                        if not block: break
                        self.wfile.write(block)


def serve(home=None, port=18737):
    from versioning import Lock
    ws = Workspace(home)
    try: lock = Lock(ws.home / 'server.lock')
    except OSError:
        try:
            descriptor = json.loads((ws.home / 'session.json').read_text(encoding='utf-8'))
            check(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}', descriptor['origin']), '本地服务描述无效。')
            request = urllib.request.Request(descriptor['origin'] + '/api/health', headers={'X-Workbench-Session': descriptor['session']})
            with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=3) as response:
                check(json.load(response).get('ok'), '原服务暂不可用。')
            print(json.dumps({'url': descriptor['origin'] + '/#session=' + descriptor['session'], 'reused': True}), flush=True)
            return
        except Exception:
            raise WorkspaceError('同一工作台已有服务但暂不可连接，请核查原服务或选择其他home。', 409) from None
    ws.recover_jobs()
    server = None
    try:
        server = Server(ws, port)
        descriptor = {'origin': server.origin, 'session': server.token}
        (ws.home / 'session.json').write_text(json.dumps(descriptor), encoding='utf-8')
        print(json.dumps({'url': server.origin + '/#session=' + server.token}, ensure_ascii=False), flush=True)
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt: pass
    finally:
        if server: server.server_close()
        ws.close()
        (ws.home / 'session.json').unlink(missing_ok=True)
        lock.close()
