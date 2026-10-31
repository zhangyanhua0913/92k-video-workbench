"""Persistent narration timeline; local media only, Agent owns search and semantic review."""
import contextlib
import hashlib
import json
import math
import os
import shutil
import sqlite3
import uuid
from pathlib import Path


def check(ok, message):
    if not ok: raise ValueError(message)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


class Project:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.dbfile = self.root / '.footage' / 'state.sqlite3'

    @contextlib.contextmanager
    def db(self):
        conn = sqlite3.connect(self.dbfile, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute('BEGIN IMMEDIATE')
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally: conn.close()

    def state(self, db=None):
        if db is None:
            with self.db() as db: return self.state(db)
        row = db.execute('SELECT * FROM state').fetchone()
        return {**json.loads(row['data']), 'revision': row['revision']}

    def show(self):
        with self.db() as db:
            return {'project': self.state(db), 'renders': [dict(x, result=json.loads(x['result'])) for x in db.execute('SELECT * FROM renders ORDER BY rowid DESC')],
                    'reviews': [dict(x) for x in db.execute('SELECT * FROM reviews ORDER BY rowid DESC')]}

    def inside(self, rel):
        check(isinstance(rel, str), '素材路径无效。')
        p = (self.root / rel).resolve()
        check(p.is_relative_to(self.root) and p.relative_to(self.root).parts[0] in ('media', 'exports'), '素材必须在项目内。')
        return p

    def update(self, patch, revision):
        check(set(patch) <= {'title', 'script', 'narration', 'narration_hash', 'shots', 'paused'}, '未知字段。')
        with self.db() as db:
            state = self.state(db)
            check(state['revision'] == revision, '工程版本已过期，请刷新。')
            check(not db.execute("SELECT 1 FROM renders WHERE status='running'").fetchone(), '正在合成，请稍后修改。')
            state.update(patch)
            check(isinstance(state['title'], str) and len(state['title']) <= 300, '标题无效。')
            check(isinstance(state['script'], str) and len(state['script']) <= 200000, '文案无效。')
            check(type(state['paused']) is bool, '暂停状态无效。')
            check(isinstance(state['shots'], list) and len(state['shots']) <= 2000, '镜头数量无效。')
            for shot in state['shots']:
                check(isinstance(shot, dict) and type(shot.get('duration')) in (int, float) and math.isfinite(shot['duration']) and 0 < shot['duration'] <= 3600, '镜头时长无效。')
                check(type(shot.get('source_in', 0)) in (int, float) and math.isfinite(shot.get('source_in', 0)) and shot.get('source_in', 0) >= 0, '素材入点无效。')
                if shot.get('asset'): self.inside(shot['asset'])
                check(isinstance(shot.get('line', ''), str) and len(shot.get('line', '')) <= 4000, '字幕过长。')
                for flag in ('usage_confirmed', 'visually_reviewed'):
                    check(type(shot.get(flag, False)) is bool, '许可和审看须为明确布尔选择。')
            if state.get('narration'): self.inside(state['narration'])
            state.pop('revision')
            db.execute('UPDATE state SET revision=revision+1,data=?', (json.dumps(state, ensure_ascii=False),))
        return self.state()

    def audit(self, state):
        from media import probe
        issues = []
        for index, shot in enumerate(state['shots']):
            if not all(shot.get(k) for k in ('asset', 'source_page', 'publisher', 'product', 'match_reason', 'usage_confirmed', 'visually_reviewed')):
                issues.append(f'镜头{index+1}缺少来源、版本、许可、画面审阅或匹配说明。')
                continue
            file = self.inside(shot['asset'])
            if not file.is_file() or digest(file) != shot.get('sha256'):
                issues.append(f'镜头{index+1}素材缺失或已变化。'); continue
            info = probe(file)
            if file.suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp') and float(info['format']['duration']) + .05 < shot.get('source_in', 0) + shot['duration']:
                issues.append(f'镜头{index+1}素材长度不足。')
        if not state['shots']: issues.append('尚无镜头。')
        if not state.get('narration') or not self.inside(state['narration']).is_file(): issues.append('请导入旁白。')
        else:
            info = probe(self.inside(state['narration']))
            if not any(x['codec_type'] == 'audio' for x in info['streams']): issues.append('旁白没有音轨。')
            if abs(float(info['format']['duration']) - sum(s['duration'] for s in state['shots'])) > .15: issues.append('旁白与镜头总时长须一致，不能截断旁白。')
            if digest(self.inside(state['narration'])) != state.get('narration_hash'): issues.append('旁白已变化，请重新导入。')
        return {'ok': not issues, 'issues': issues}

    def render(self):
        from media import binary, run, probe, srt_text
        with self.db() as db:
            s = self.state(db)
            check(not s['paused'], '项目已暂停。')
            check(db.execute("SELECT 1 FROM reviews WHERE revision=? AND stage='assets' AND action='confirm'", (s['revision'],)).fetchone(), '请先确认当前素材方案。')
            old = db.execute("SELECT * FROM renders WHERE revision=? AND status!='retry-approved' ORDER BY rowid DESC LIMIT 1", (s['revision'],)).fetchone()
            if old:
                value = json.loads(old['result'])
                check(old['status'] == 'done', '该版本已有执行或失败记录，请先核查原任务。')
                check(digest(self.inside(value['file'])) == value['sha256'], '原成片已变化。')
                return value
            check(self.audit(s)['ok'], '素材核验未通过，请查看核验结果。')
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO renders VALUES(?,?,?,?,?)', (rid, s['revision'], 'running', '{}', os.getpid()))
        folder = self.root / 'exports' / rid
        folder.mkdir(parents=True)
        try:
            cues, cursor = [], 0
            for index, shot in enumerate(s['shots']):
                file = self.inside(shot['asset'])
                still = file.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
                args = [binary('ffmpeg'), '-v', 'error', '-y']
                args += ['-loop', '1'] if still else ['-ss', str(shot.get('source_in', 0))]
                args += ['-protocol_whitelist', 'file,pipe', '-i', str(file), '-t', str(shot['duration']), '-an', '-vf',
                         'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1',
                         '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p', str(folder / f'{index}.mp4')]
                run(args)
                if shot.get('line'): cues.append({'start': cursor, 'end': cursor + shot['duration'], 'text': shot['line']})
                cursor += shot['duration']
            (folder / 'concat.txt').write_text('\n'.join(f"file '{i}.mp4'" for i in range(len(s['shots']))), encoding='utf-8')
            run([binary('ffmpeg'), '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', 'concat.txt', '-c', 'copy', 'picture.mp4'], cwd=folder)
            (folder / 'captions.srt').write_text(srt_text(cues), encoding='utf-8')
            args = [binary('ffmpeg'), '-v', 'error', '-y', '-i', 'picture.mp4', '-i', str(self.inside(s['narration'])), '-map', '0:v', '-map', '1:a', '-t', str(cursor)]
            if cues: args += ['-vf', 'subtitles=captions.srt', '-c:v', 'libx264', '-preset', 'fast']
            else: args += ['-c:v', 'copy']
            run(args + ['-c:a', 'aac', '-movflags', '+faststart', 'film.mp4'], cwd=folder)
            output = folder / 'film.mp4'
            run([binary('ffmpeg'), '-v', 'error', '-i', str(output), '-f', 'null', '-'])
            info = probe(output)
            check(abs(float(info['format']['duration']) - cursor) < .15, '输出时长不一致。')
            result = {'file': output.relative_to(self.root).as_posix(), 'subtitles': (folder / 'captions.srt').relative_to(self.root).as_posix(),
                      'sha256': digest(output), 'duration': cursor, 'revision': s['revision'], 'technicalPass': True, 'listeningReviewed': False}
            (folder / 'sources.json').write_text(json.dumps(s['shots'], ensure_ascii=False, indent=2), encoding='utf-8')
            with self.db() as db: db.execute("UPDATE renders SET status='done',result=? WHERE id=?", (json.dumps(result), rid))
            return result
        except BaseException:
            with self.db() as db: db.execute("UPDATE renders SET status='failed' WHERE id=?", (rid,))
            raise


def execute(root, action, data):
    p = Project(root)
    if action == 'create':
        p.dbfile.parent.mkdir(parents=True)
        check(not p.dbfile.exists(), '项目已存在。')
        (p.root / 'media').mkdir(exist_ok=True)
        with p.db() as db:
            db.executescript('CREATE TABLE state(revision INTEGER,data TEXT); CREATE TABLE reviews(id TEXT PRIMARY KEY,revision INTEGER,stage TEXT,action TEXT); CREATE TABLE renders(id TEXT PRIMARY KEY,revision INTEGER,status TEXT,result TEXT,pid INTEGER);')
            state = {'project_id': uuid.uuid4().hex, 'title': data['title'], 'script': '', 'shots': [], 'narration': None, 'paused': False}
            db.execute('INSERT INTO state VALUES(1,?)', (json.dumps(state),))
        return p.state()
    if action == 'show': return p.show()
    if action == 'update': return p.update(data['patch'], data['revision'])
    if action == 'doctor':
        from media import binary
        values = {}
        for name in ('ffmpeg', 'ffprobe'):
            try: values[name] = binary(name)
            except ValueError: values[name] = None
        return values
    if action == 'import':
        from media import probe
        src = Path(data['file']).resolve()
        check(src.is_file() and src.suffix.lower() in ('.mp4', '.mov', '.webm', '.png', '.jpg', '.jpeg', '.webp', '.wav', '.mp3', '.m4a', '.flac'), '素材不存在或类型不支持。')
        h = digest(src)
        dest = p.root / 'media' / (h + src.suffix.lower())
        if not dest.exists(): shutil.copyfile(src, dest)
        info = probe(dest)
        return {'file': dest.relative_to(p.root).as_posix(), 'sha256': h, 'duration': float(info.get('format', {}).get('duration', 0)), 'streams': info['streams']}
    if action == 'audit': return p.audit(p.state())
    if action == 'render': return p.render()
    if action == 'retry-local':
        from core import pid_alive
        with p.db() as db:
            old = db.execute('SELECT * FROM renders WHERE id=?', (data['task'],)).fetchone()
            check(old and old['status'] in ('failed', 'interrupted') and not pid_alive(old['pid']), '只允许原进程已退出且明确失败的本地合成重试。')
            db.execute("UPDATE renders SET status='retry-approved' WHERE id=?", (old['id'],))
        return {'retry_approved': old['id'], 'note': '原记录保留，可显式重新合成；未自动执行。'}
    if action == 'review':
        check(data['stage'] in ('assets', 'final'), '未知审阅阶段。')
        with p.db() as db:
            revision = p.state(db)['revision']
            old = db.execute("SELECT * FROM reviews WHERE revision=? AND stage=? AND action='pending'", (revision, data['stage'])).fetchone()
            if old: return dict(old)
            rid = uuid.uuid4().hex
            db.execute('INSERT INTO reviews VALUES(?,?,?,?)', (rid, revision, data['stage'], 'pending'))
        return {'id': rid, 'revision': revision, 'stage': data['stage'], 'action': 'pending'}
    if action == 'decide':
        with p.db() as db:
            s = p.state(db)
            r = db.execute('SELECT * FROM reviews WHERE id=?', (data['request_id'],)).fetchone()
            check(r and r['revision'] == data['revision'] == s['revision'], '审阅已过期。')
            check(data['action'] in ('confirm', 'revise', 'pause'), '未知决定。')
            if r['action'] != 'pending': return dict(r)
            if data['action'] == 'confirm':
                if r['stage'] == 'assets': check(p.audit(s)['ok'], '素材核验未通过。')
                else:
                    render = db.execute("SELECT result FROM renders WHERE revision=? AND status='done'", (s['revision'],)).fetchone()
                    check(render, '当前版本尚无成片。')
                    result = json.loads(render['result'])
                    check(digest(p.inside(result['file'])) == result['sha256'], '成片已变化。')
            db.execute('UPDATE reviews SET action=? WHERE id=?', (data['action'], r['id']))
            if data['action'] == 'pause':
                s['paused'] = True; s.pop('revision')
                db.execute('UPDATE state SET revision=revision+1,data=?', (json.dumps(s),))
        return {'action': data['action'], 'stage': r['stage']}
    if action == 'recover':
        from core import pid_alive
        with p.db() as db:
            for render in db.execute("SELECT * FROM renders WHERE status='running'").fetchall():
                if not pid_alive(render['pid']): db.execute("UPDATE renders SET status='interrupted' WHERE id=?", (render['id'],))
        if data.get('resume'): p.update({'paused': False}, p.state()['revision'])
        return p.show()
    raise ValueError('不支持的素材工程操作。')
