"""Versioned, transactional authority for talking-edit. No media or secrets in package."""
import contextlib
import copy
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from pathlib import Path

VERSION = '0.2.0'
STAGES = ('project', 'workflow', 'transcribe-budget', 'roughcut', 'packaging', 'keyframes', 'final')


class EditError(ValueError):
    def __init__(self, message, code='invalid', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def check(value, message, code='invalid', status=400):
    if not value:
        raise EditError(message, code, status)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dumps(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(dumps(value), encoding='utf-8')
    os.replace(temp, path)


def home():
    return Path(os.environ.get('TALKING_EDIT_HOME', Path.home() / '.talking-edit')).resolve()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def pid_alive(pid):
    if os.name=='nt':
        import ctypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];kernel.OpenProcess.restype=ctypes.c_void_p
        kernel.CloseHandle.argtypes=[ctypes.c_void_p]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:return ctypes.get_last_error()==5
        try:
            code=ctypes.c_ulong();kernel.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
            return bool(kernel.GetExitCodeProcess(handle,ctypes.byref(code))) and code.value==259
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def clean(value):
    if isinstance(value, dict):
        for k, v in value.items():
            check(k.lower() not in {'key', 'api_key', 'token', 'secret', 'password', 'authorization'}, '凭据不能进入项目。')
            clean(v)
    elif isinstance(value, list):
        for v in value:
            clean(v)
    elif isinstance(value, float):
        check(math.isfinite(value), '数值无效。')


def validate(s):
    clean(s)
    check(isinstance(s.get('title'), str) and len(s['title']) <= 300, '项目标题无效。')
    check(finite(s['speed']) and s['speed'] in (1, 1.1, 1.15, 1.2, 1.25, 1.3, 1.5), '不支持的速度。')
    check(set(s['workflow']) == {'transcribe', 'roughcut', 'packaging', 'render'}, '流程步骤无效。')
    check(all(isinstance(x, str) for x in s['workflow'].values()), 'Skill 标识无效。')
    from registry import validate_selection
    validate_selection(s['workflow'])
    duration = s.get('duration', 0)
    for items in (s['cues'], s['cuts'], s['scenes']):
        ids = set()
        check(isinstance(items, list) and len(items) <= 20000, '条目过多。')
        for item in items:
            check(isinstance(item.get('id'), str) and item['id'] not in ids, '条目编号重复或缺失。')
            ids.add(item['id'])
            a, b = item.get('start'), item.get('end')
            check(finite(a) and finite(b) and 0 <= a < b <= duration + .002, '时间必须在原视频范围内。')
    for cue in s['cues']:
        check(isinstance(cue.get('text'), str) and len(cue['text']) <= 4000, '字幕文字无效。')
    for previous,current in zip(s['cues'],s['cues'][1:]):
        check(previous['end'] <= current['start']+.002, '字幕时间不能倒序或重叠。')
    check(all(isinstance(c.get('enabled'), bool) for c in s['cuts']), '剪切启用状态无效。')
    music=s.get('music')
    if music:
        check(isinstance(music,dict) and isinstance(music.get('file'),str) and isinstance(music.get('sha256'),str),'音乐文件及摘要缺失。')
        check(finite(music.get('gain_db')) and -50<=music['gain_db']<=-6,'配乐音量须在 -50 至 -6 dB 范围。')
        check(finite(music.get('fade_seconds',2)) and 0<=music.get('fade_seconds',2)<=10,'音乐淡入淡出无效。')
    for scene in s['scenes']:
        if 'layout' in scene:
            box=scene['layout'];check(isinstance(box,dict) and all(finite(box.get(k)) for k in ('x','y','width')), '包装布局无效。')
            check(0<=box['x']<=1 and 0<=box['y']<=1 and 0<box['width']<=1 and box['x']+box['width']<=1,'包装布局超出画面。')
    return s


class Project:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.meta = self.root / '.talking-edit'
        self.dbfile = self.meta / 'state.sqlite3'

    @contextlib.contextmanager
    def db(self):
        c = sqlite3.connect(self.dbfile, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @classmethod
    def create(cls, root, title):
        p = cls(root)
        package = Path(__file__).resolve().parents[1]
        check(not p.root.is_relative_to(package), '业务项目必须在 Skill 安装目录之外。')
        p.root.mkdir(parents=True, exist_ok=True)
        p.meta.mkdir(exist_ok=True)
        check(not p.dbfile.exists(), '项目已存在，请 recover。', 'exists')
        for d in ('media', 'exports', 'work'):
            (p.root / d).mkdir(exist_ok=True)
        with p.db() as c:
            c.executescript('''CREATE TABLE state(id INTEGER PRIMARY KEY, revision INTEGER, data TEXT);
            CREATE TABLE history(revision INTEGER PRIMARY KEY,data TEXT);
            CREATE TABLE reviews(id TEXT PRIMARY KEY,stage TEXT,revision INTEGER,fingerprint TEXT,status TEXT,result TEXT,created REAL);
            CREATE TABLE tasks(id TEXT PRIMARY KEY,kind TEXT,fingerprint TEXT,status TEXT,result TEXT,pid INTEGER,created REAL, UNIQUE(kind,fingerprint));
            CREATE TABLE events(id INTEGER PRIMARY KEY,kind TEXT,data TEXT,created REAL);''')
            s = dict(project_id=uuid.uuid4().hex, title=title, source=None, duration=0, script='',
                     speed=1, workflow={'transcribe': 'whisper-local', 'roughcut': 'fredtalk-roughcut',
                     'packaging': 'fredtalk-motion', 'render': 'ffmpeg'}, cues=[], cuts=[], scenes=[],
                     subtitle_burn=True, paused=False)
            c.execute('INSERT INTO state VALUES(1,1,?)', (dumps(s),))
            c.execute('INSERT INTO history VALUES(1,?)', (dumps(s),))
        p.export()
        return p

    def state(self, c=None):
        if c is None:
            with self.db() as db:
                return self.state(db)
        row = c.execute('SELECT * FROM state WHERE id=1').fetchone()
        return dict(json.loads(row['data']), revision=row['revision'])

    def export(self):
        with self.db() as c:
            atomic(self.root / 'project.json', self.state(c))

    def event(self, c, kind, data):
        c.execute('INSERT INTO events(kind,data,created) VALUES(?,?,?)', (kind, dumps(data), time.time()))

    def update(self, patch, revision):
        allowed = {'title', 'script', 'speed', 'workflow', 'cues', 'cuts', 'scenes', 'subtitle_burn','music'}
        check(set(patch) <= allowed, '不能修改受保护的项目字段。')
        with self.db() as c:
            s = self.state(c)
            check(s['revision'] == revision, '页面版本已过期，请重新载入。', 'stale_revision', 409)
            check(not c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(), '任务执行中，稍后修改。', 'busy', 409)
            s.update(copy.deepcopy(patch))
            self._save(c, validate(s))
        self.export()
        return self.state()

    def _save(self, c, s):
        rev = s.pop('revision') + 1
        c.execute('UPDATE state SET revision=?,data=? WHERE id=1', (rev, dumps(s)))
        c.execute('INSERT INTO history VALUES(?,?)', (rev, dumps(s)))
        c.execute("UPDATE reviews SET status='stale' WHERE status='pending'")
        self.event(c, 'updated', {'revision': rev})

    def fingerprint(self, stage, s=None):
        s = s or self.state()
        base = {'source': s['source'], 'speed': s['speed']}
        if stage == 'transcribe-budget':
            from providers import cloud_quote
            return digest(cloud_quote(self, s))
        if stage in ('roughcut', 'packaging', 'keyframes', 'final'):
            base.update(cues=s['cues'], cuts=s['cuts'], roughcut=s['workflow']['roughcut'])
            from registry import specs
            used={'roughcut'}
            if stage in ('packaging','keyframes','final'):used.add('packaging')
            if stage=='final':used.add('render')
            selected={s['workflow'][x] for x in used}
            base['capability_versions']=[{k:x.get(k) for k in ('id','version','source_revision','instructions_hash')} for x in specs() if x['id'] in selected]
        if stage in ('packaging', 'keyframes', 'final'):
            scenes=s['scenes']
            if stage=='packaging':
                generated={'artifact','artifact_hash','artifact_speed','keyframe','reference_keyframe','code','code_hash','component','source_revision','timing_fingerprint'}
                scenes=[{k:v for k,v in scene.items() if k not in generated} for scene in scenes]
            base.update(scenes=scenes, packaging=s['workflow']['packaging'],music=s.get('music'))
        if stage == 'final':
            base.update(subtitle_burn=s['subtitle_burn'], render=s['workflow']['render'])
            base['media_engine']=VERSION
        if stage in ('project', 'workflow'):
            base = {k: v for k, v in s.items() if k not in ('revision', 'paused')}
        return digest(base)

    def retry_local(self, tid):
        """Explicit retry only after a terminal local failure, never an uncertain cloud submission."""
        with self.db() as c:
            row=c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
            check(row and row['status']=='failed','只允许明确失败的本地任务重试。')
            check(row['kind'] in ('render','scene') or (row['kind']=='transcribe' and not (self.root/'work'/('qwen-'+tid)).exists()),'云端任务不可用本地重试入口。')
            c.execute('UPDATE tasks SET fingerprint=? WHERE id=?',(row['fingerprint']+':failed-attempt:'+tid,tid))
            self.event(c,'explicit-local-retry',{'task_id':tid})
        return {'resolved':tid,'note':'保留原失败记录，现在可重新执行本地步骤。'}

    def open_review(self, stage):
        check(stage in STAGES, '未知审看阶段。')
        with self.db() as c:
            s = self.state(c)
            row = c.execute("SELECT id FROM reviews WHERE stage=? AND revision=? AND status='pending'", (stage, s['revision'])).fetchone()
            if row:
                return row['id']
            rid = uuid.uuid4().hex
            c.execute('INSERT INTO reviews VALUES(?,?,?,?,?,?,?)', (rid, stage, s['revision'], self.fingerprint(stage, s), 'pending', None, time.time()))
            return rid

    def review(self, rid):
        with self.db() as c:
            row = c.execute('SELECT * FROM reviews WHERE id=?', (rid,)).fetchone()
            check(row, '交互请求不存在。', 'not_found', 404)
            result = dict(row)
            result['result'] = json.loads(result['result']) if result['result'] else None
            return result

    def decide(self, rid, revision, action, note='', cap=None):
        check(action in ('save_draft', 'confirm', 'revise', 'pause'), '未知操作。')
        with self.db() as c:
            s = self.state(c)
            row = c.execute('SELECT * FROM reviews WHERE id=?', (rid,)).fetchone()
            check(row, '请求不存在。')
            if row['status'] == 'completed':
                old = json.loads(row['result'])
                check(old['action'] == action and old['revision'] == revision and old['note'] == note, '请求已被不同决定消费。', 'conflict', 409)
                return old
            check(row['status'] == 'pending' and row['revision'] == revision == s['revision'], '旧页面不能确认新版本。', 'stale_revision', 409)
            if action == 'confirm' and row['stage'] == 'roughcut':
                check(s['source'] and s['cues'], '请先导入视频及字幕。')
            if action == 'confirm' and row['stage'] == 'transcribe-budget':
                from providers import cloud_quote
                quote = cloud_quote(self, s)
                check(finite(cap) and quote['estimated_max_cny'] <= cap <= 10000, '请明确填写不低于报价的人民币上限。')
                check(row['fingerprint'] == digest(quote), '报价已变，请重新创建确认。', 'stale_quote', 409)
            if action == 'confirm' and row['stage'] == 'keyframes':
                for scene in s['scenes']:
                    check(scene.get('artifact') and scene.get('keyframe'), '包装片段尚无视频与关键帧。')
                    self.public_file(scene['artifact']); self.public_file(scene['keyframe'])
            if action == 'confirm' and row['stage'] == 'final':
                rendered=c.execute("SELECT result FROM tasks WHERE kind='render' AND fingerprint=? AND status='done'", (self.fingerprint('final', s),)).fetchone()
                check(rendered, '当前版本尚无成片。')
                final=json.loads(rendered['result'])
                check(file_hash(self.public_file(final['file']))==final['sha256'],'当前成片已被修改，不能确认旧输出。','artifact_changed')
            result = dict(project_id=s['project_id'], request_id=rid, revision=revision, stage=row['stage'], action=action, changes={}, note=str(note)[:5000])
            if row['stage']=='transcribe-budget':
                result['changes']={'cap_cny':cap}
            c.execute("UPDATE reviews SET status='completed',result=? WHERE id=?", (dumps(result), rid))
            if action == 'pause':
                s['paused'] = True
                self._save(c, s)
            self.event(c, 'decision', result)
        self.export()
        return result

    def approved(self, stage, s=None):
        s = s or self.state()
        with self.db() as c:
            return bool(c.execute("SELECT 1 FROM reviews WHERE stage=? AND fingerprint=? AND status='completed' AND json_extract(result,'$.action')='confirm'", (stage, self.fingerprint(stage, s))).fetchone())

    def public_file(self, relative):
        check(isinstance(relative, str), '文件路径无效。')
        p = (self.root / relative).resolve()
        check(p.is_relative_to(self.root) and p.relative_to(self.root).parts[0] in ('media', 'exports', 'work'), '文件不在可访问范围。', 'forbidden', 403)
        check(p.is_file() and p.suffix.lower() in ('.mp4', '.webm', '.mov', '.mkv', '.wav', '.mp3', '.png', '.jpg', '.jpeg', '.srt', '.json', '.txt', '.zip'), '文件类型或状态不允许。', 'forbidden', 403)
        return p

    def tasks(self):
        with self.db() as c:
            rows = c.execute('SELECT * FROM tasks ORDER BY created DESC').fetchall()
            return [dict(r, result=json.loads(r['result']) if r['result'] else None) for r in rows]

    def claim(self, kind, fingerprint):
        with self.db() as c:
            check(not self.state(c)['paused'], '项目已暂停，请 recover --resume。', 'paused')
            old = c.execute('SELECT * FROM tasks WHERE kind=? AND fingerprint=?', (kind, fingerprint)).fetchone()
            if old:
                if old['status'] == 'done':
                    return dict(old), False
                raise EditError('任务已经提交，请核查原任务；不会自动重复执行。', 'task_pending', 409)
            check(not c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(), '已有本地任务执行中。', 'busy', 409)
            tid = uuid.uuid4().hex
            c.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)', (tid, kind, fingerprint, 'running', None, os.getpid(), time.time()))
            return {'id': tid}, True

    def finish(self, tid, result, status='done'):
        clean(result)
        with self.db() as c:
            c.execute('UPDATE tasks SET status=?,result=? WHERE id=?', (status, dumps(result), tid))
        self.export()

    def recover(self, resume=False):
        with self.db() as c:
            for task in c.execute("SELECT * FROM tasks WHERE status='running'").fetchall():
                if pid_alive(task['pid']):continue
                receipt=self.root/'work'/('qwen-'+task['id'])/'asr-state.json'
                cloud=(self.root/'work'/('qwen-'+task['id'])).exists()
                if cloud:
                    raw=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
                    result={'task_id':raw.get('task_id'),'note':'原进程已结束；只续查原任务。'}
                    status='waiting' if raw.get('task_id') else 'unknown'
                else:
                    result={'note':'本地原进程已退出，保留中间产物；可显式 retry-local 后重跑。'};status='failed'
                c.execute('UPDATE tasks SET status=?,result=? WHERE id=?',(status,dumps(result),task['id']))
            if resume:
                s = self.state(c); s['paused'] = False; self._save(c, s)
            reviews = [dict(r) for r in c.execute('SELECT * FROM reviews ORDER BY created DESC LIMIT 20')]
        self.export()
        return {'project': self.state(), 'tasks': self.tasks(), 'reviews': reviews,
                'note': 'running/unknown 须核对原进程与产物；未自动重试任务。'}
