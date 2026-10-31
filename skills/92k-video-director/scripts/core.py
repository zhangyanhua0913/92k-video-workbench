"""Private project state and revision-bound human decisions; standard library only."""
import contextlib
import copy
import hashlib
import json
import math
import os
import shutil
import sqlite3
import time
import uuid
from pathlib import Path

VERSION = '0.1.0'
METHODS = {'local_image', 'local_video', 'image', 'image_edit', 'video', 'image_video', 'avatar', 'lipsync'}
FORBIDDEN = {'key', 'api_key', 'user_key', 'authorization', 'password', 'token', 'secret'}


class DirectorError(ValueError):
    def __init__(self, message, code='invalid', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def check(condition, message, code='invalid', status=400):
    if not condition:
        raise DirectorError(message, code, status)


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def no_secrets(value):
    if isinstance(value, dict):
        for k, v in value.items():
            check(k.lower() not in FORBIDDEN, '项目数据不能包含密钥或凭据。')
            no_secrets(v)
    elif isinstance(value, list):
        for v in value:
            no_secrets(v)


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with tmp.open('x', encoding='utf-8') as stream:
        stream.write(dump(value))
    os.replace(tmp, path)


def shot_hash(shot):
    return digest({k: v for k, v in shot.items() if k not in ('accepted', 'candidates', 'feedback', 'limits')})


def normalize(data):
    no_secrets(data)
    result = copy.deepcopy(data)
    check(result.get('format', '9:16') in ('9:16', '16:9'), '首版支持9:16或16:9。')
    result.setdefault('format', '9:16')
    result.setdefault('title', '新视频')
    result.setdefault('script', '')
    result.setdefault('bgm', None)
    shots = result.setdefault('shots', [])
    check(isinstance(shots, list) and len(shots) <= 100, '分镜必须是最多100项的数组。')
    seen = set()
    for shot in shots:
        check(isinstance(shot, dict), '镜头必须为对象。')
        shot.setdefault('id', uuid.uuid4().hex)
        check(isinstance(shot['id'], str) and 1 <= len(shot['id']) <= 64 and shot['id'] not in seen, '镜头编号重复或无效。')
        seen.add(shot['id'])
        shot.setdefault('method', 'local_image')
        check(shot['method'] in METHODS, '不支持的镜头制作方式。')
        shot.setdefault('duration', 5.0)
        check(type(shot['duration']) in (int, float) and math.isfinite(shot['duration']) and 0.1 <= shot['duration'] <= 180, '镜头时长须在0.1到180秒之间。')
        for field in ('line', 'visual', 'prompt', 'feedback'):
            shot.setdefault(field, '')
            check(isinstance(shot[field], str) and len(shot[field]) <= 10000, '镜头文字过长或类型无效。')
        shot.setdefault('voice', {})
        shot['voice'].setdefault('audioId', '')
        shot['voice'].setdefault('clone_task_id', '')
        shot.setdefault('parameters', {})
        shot.setdefault('limits', {})
        for field in ('source', 'reference', 'audio', 'model'):
            shot.setdefault(field, '')
        shot.setdefault('audio_mode', 'source' if shot['method'] in ('local_video', 'avatar', 'lipsync') else 'narration')
        check(shot['audio_mode'] in ('source', 'narration', 'mute'), '声音模式须为source、narration或mute。')
        shot.setdefault('transition', 'cut')
        check(shot['transition'] in ('cut', 'fade'), '转场须为cut或fade。')
        shot.setdefault('candidates', [])
        shot.setdefault('accepted', None)
    return result


class Project:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.dbfile = self.root / '.director' / 'state.sqlite3'

    @classmethod
    def create(cls, root, data):
        obj = cls(root)
        check(not obj.dbfile.exists(), '项目已存在，请读取或继续原项目。', status=409)
        obj.dbfile.parent.mkdir(parents=True, exist_ok=True)
        for folder in ('media', 'exports', '.director/history'):
            (obj.root / folder).mkdir(parents=True, exist_ok=True)
        with obj.db() as db:
            db.executescript('''
            CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, data TEXT NOT NULL);
            CREATE TABLE reviews(id TEXT PRIMARY KEY, stage TEXT, revision INTEGER, status TEXT, result TEXT, created REAL);
            CREATE TABLE approvals(id TEXT PRIMARY KEY, revision INTEGER, cap INTEGER, scope TEXT, created REAL);
            CREATE TABLE operations(id TEXT PRIMARY KEY, shot_id TEXT, purpose TEXT, fingerprint TEXT, request TEXT,
              ceiling INTEGER, credential TEXT, status TEXT, quote TEXT, task_id TEXT UNIQUE, points INTEGER DEFAULT 0,
              response TEXT, local_file TEXT, created REAL, resolved TEXT);
            CREATE TABLE renders(id TEXT PRIMARY KEY, revision INTEGER, status TEXT, result TEXT);
            CREATE TABLE events(id INTEGER PRIMARY KEY, kind TEXT, data TEXT, created REAL);
            ''')
            data = normalize(data)
            data['project_id'] = uuid.uuid4().hex
            db.execute('INSERT INTO state VALUES(1,1,?)', (dump(data),))
        obj.sync()
        return obj

    @contextlib.contextmanager
    def db(self):
        conn = sqlite3.connect(self.dbfile, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('PRAGMA foreign_keys=ON')
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def state(self, db=None):
        if db is None:
            with self.db() as conn:
                return self.state(conn)
        row = db.execute('SELECT * FROM state WHERE id=1').fetchone()
        return {'revision': row['revision'], **json.loads(row['data'])}

    def sync(self):
        # SQLite is authoritative; this mirror is repairable after an interruption.
        with self.db() as db:
            state = self.state(db)
            atomic(self.root / 'project.json', state)
            atomic(self.root / '.director/history' / (str(state['revision']) + '.json'), state)

    def event(self, db, kind, data):
        no_secrets(data)
        db.execute('INSERT INTO events(kind,data,created) VALUES(?,?,?)', (kind, dump(data), time.time()))

    def _update(self, db, data, revision):
        old = self.state(db)
        check(old['revision'] == revision, '页面已过期，请重新载入后确认。', 'stale_revision', 409)
        new = normalize(data)
        check(new.get('project_id', old['project_id']) == old['project_id'], '项目编号不符。')
        new['project_id'] = old['project_id']
        new.pop('revision', None)
        oldshots = {s['id']: s for s in old['shots']}
        for shot in new['shots']:
            previous = oldshots.get(shot['id'])
            # Candidate acceptance is only changed through the review endpoint.
            shot['candidates'] = previous.get('candidates', []) if previous else []
            shot['accepted'] = previous.get('accepted') if previous and shot_hash(previous) == shot_hash(shot) else None
        db.execute('UPDATE state SET revision=revision+1,data=? WHERE id=1', (dump(new),))
        db.execute("UPDATE reviews SET status='stale' WHERE status='pending'")
        self.event(db, 'project.updated', {'revision': revision + 1})
        return revision + 1

    def update(self, data, revision):
        with self.db() as db:
            self._update(db, data, revision)
        self.sync()
        return self.state()

    def inside(self, relative):
        path = (self.root / str(relative)).resolve()
        check(path.is_relative_to(self.root) and path != self.root, '文件超出项目范围。', 'invalid_path', 403)
        return path

    def import_file(self, source):
        source = Path(source).expanduser().resolve()
        check(source.is_file() and 0 < source.stat().st_size <= 100 * 1024 * 1024, '素材必须是100MB以内的文件。')
        check(source.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.webm', '.mov', '.wav', '.mp3', '.m4a', '.flac', '.ogg'), '不支持的素材格式。')
        name = uuid.uuid4().hex + source.suffix.lower()
        target = self.root / 'media' / name
        shutil.copyfile(source, target)
        return {'file': 'media/' + name, 'name': source.name, 'bytes': target.stat().st_size}

    def open_review(self, stage):
        check(stage in ('config', 'storyboard', 'budget', 'assets', 'final'), '审阅阶段无效。')
        with self.db() as db:
            state = self.state(db)
            row = db.execute("SELECT id FROM reviews WHERE stage=? AND revision=? AND status='pending'", (stage, state['revision'])).fetchone()
            if row:
                return row['id']
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO reviews VALUES(?,?,?,\'pending\',NULL,?)', (rid, stage, state['revision'], time.time()))
            return rid

    def review(self, rid):
        with self.db() as db:
            row = db.execute('SELECT * FROM reviews WHERE id=?', (rid,)).fetchone()
            check(row is not None, '审阅请求不存在。', status=404)
            out = dict(row)
            out['result'] = json.loads(out['result']) if out['result'] else None
            return out

    def decide(self, rid, action, revision, data=None, cap=None, selections=None, note=''):
        check(action in ('confirm', 'revise', 'pause'), '决定无效。')
        with self.db() as db:
            review = db.execute('SELECT * FROM reviews WHERE id=?', (rid,)).fetchone()
            check(review is not None, '审阅请求不存在。', status=404)
            if review['status'] == 'completed':
                return json.loads(review['result'])
            state = self.state(db)
            check(review['status'] == 'pending' and review['revision'] == revision == state['revision'], '审阅版本已过期。', 'stale_revision', 409)
            check(isinstance(note, str) and len(note) <= 10000, '反馈无效。')
            if data is not None and review['stage'] == 'storyboard':
                self._update(db, data, revision)
                state = self.state(db)
            if action == 'confirm' and review['stage'] == 'budget':
                check(type(cap) is int and 0 <= cap <= 1000000000, '请填写整轮积分上限。')
                ops = [dict(r) for r in db.execute('SELECT * FROM operations')]
                ops = [o for o in ops if self.operation_current(o, state)]
                check(ops or all(s['method'].startswith('local_') for s in state['shots']), '请先由Agent准备任务与逐任务上限。')
                committed = self.exposure(db)
                remaining = sum(o['ceiling'] for o in ops if o['status'] == 'planned')
                check(cap >= committed + remaining, '整轮上限不足以覆盖已有占用与计划任务。', 'budget_exceeded')
                scope = {o['id']: {'fingerprint': o['fingerprint'], 'ceiling': o['ceiling'], 'credential': o['credential']} for o in ops}
                db.execute('INSERT INTO approvals VALUES(?,?,?,?,?)', (uuid.uuid4().hex, state['revision'], cap, dump(scope), time.time()))
            if action == 'confirm' and review['stage'] == 'assets':
                selections = selections or {}
                for shot in state['shots']:
                    selected = selections.get(shot['id'], shot.get('accepted'))
                    check(selected and any(c['file'] == selected and c.get('fingerprint') == shot_hash(shot) for c in shot['candidates']), '每镜须采纳一个当前版本的素材。')
                    shot['accepted'] = selected
                data = dict(state)
                data.pop('revision')
                db.execute('UPDATE state SET revision=revision+1,data=? WHERE id=1', (dump(data),))
                db.execute("UPDATE reviews SET status='stale' WHERE status='pending'")
                state = self.state(db)
            if action == 'confirm' and review['stage'] == 'final':
                check(db.execute("SELECT 1 FROM renders WHERE revision=? AND status='done'", (state['revision'],)).fetchone(), '当前版本尚无完整成片。')
            result = {'request_id': rid, 'project_id': state['project_id'], 'revision': state['revision'], 'action': action, 'stage': review['stage'], 'note': note}
            db.execute("UPDATE reviews SET status='completed',result=? WHERE id=?", (dump(result), rid))
            self.event(db, 'review.decided', result)
        self.sync()
        return result

    def add_candidate(self, shot_id, relative, fingerprint=None, source='local'):
        check(self.inside(relative).is_file() and str(relative).startswith('media/'), '素材必须先导入本项目media目录。')
        with self.db() as db:
            state = self.state(db)
            shot = next((s for s in state['shots'] if s['id'] == shot_id), None)
            check(shot is not None, '镜头不存在。')
            candidate = {'file': relative, 'fingerprint': fingerprint or shot_hash(shot), 'source': source}
            if candidate not in shot['candidates']:
                shot['candidates'].append(candidate)
            state.pop('revision')
            db.execute('UPDATE state SET data=? WHERE id=1', (dump(state),))
        self.sync()
        return candidate

    def accept_local(self, shot_id, relative):
        """Register an imported local candidate, without granting human acceptance."""
        return self.add_candidate(shot_id, relative)

    def exposure(self, db):
        # A failed generation does not imply a refund. Keep all charged/unknown amounts.
        return db.execute("SELECT COALESCE(SUM(points),0) FROM operations WHERE task_id IS NOT NULL").fetchone()[0]

    @staticmethod
    def operation_current(operation, state):
        shot = next((s for s in state['shots'] if s['id'] == operation['shot_id']), None)
        request = operation['request']
        if isinstance(request, str):
            request = json.loads(request)
        return bool(shot and digest({'shot': shot_hash(shot), 'purpose': operation['purpose'], 'request': request}) == operation['fingerprint'])

    def summary(self):
        with self.db() as db:
            state = self.state(db)
            ops = [dict(r) for r in db.execute('SELECT * FROM operations ORDER BY created')]
            latest = {(o['fingerprint'], o['credential']): o['id'] for o in ops}
            for op in ops:
                op['current'] = self.operation_current(op, state) and latest[(op['fingerprint'], op['credential'])] == op['id']
                op['request'] = json.loads(op['request'])
                op['quote'] = json.loads(op['quote']) if op['quote'] else None
                op['response'] = json.loads(op['response']) if op['response'] else None
            renders = [{**dict(r), 'result': json.loads(r['result'])} for r in db.execute('SELECT * FROM renders')]
            return {'project': state, 'shot_fingerprints': {s['id']: shot_hash(s) for s in state['shots']}, 'operations': ops, 'renders': renders, 'exposure_points': self.exposure(db)}
