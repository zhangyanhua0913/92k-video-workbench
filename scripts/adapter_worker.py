"""Isolated, JSON-only adapters. Never import multiple Skill module trees in one process."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def execute(engine, root, action, data):
    package = '92k-video-director' if engine == 'generate' else 'talking-edit'
    sys.path.insert(0, str(ROOT / 'skills' / package / 'scripts'))
    if engine == 'footage':
        from footage_project import execute as footage
        return footage(root, action, data)
    from core import Project
    if action == 'style-version':
        from registry import specs
        selection = data.get('selection')
        return [{k: x.get(k) for k in ('id', 'version', 'source_revision', 'instructions_hash')} for x in specs() if x['id'] == selection]
    if action == 'create':
        if engine == 'generate':
            return Project.create(root, {'title': data['title'], 'script': '', 'shots': []}).state()
        p = Project.create(root, data['title'])
        s = p.state()
        # A clean install must not require FredTalk for a plain local export.
        p.update({'workflow': {**s['workflow'], 'roughcut': 'local-cuts', 'packaging': 'none'}}, s['revision'])
        return p.state()
    p = Project(root)
    if action == 'serve':
        if engine == 'generate':
            from web import ReviewServer
            server = ReviewServer(p)
        else:
            from web import Server
            server = Server(p)
        print(json.dumps({'ok': True, 'result': server.descriptor()}), flush=True)
        try: server.serve_forever(poll_interval=.2)
        finally: server.server_close()
        return None
    if action == 'show':
        if engine == 'generate':
            result = p.summary()
            with p.db() as db:
                result['reviews'] = [dict(r) for r in db.execute('SELECT * FROM reviews ORDER BY created DESC LIMIT 30')]
            result['final_confirmed'] = any(r['stage'] == 'final' and r['status'] == 'completed' and r['revision'] == result['project']['revision'] and json.loads(r['result'])['action'] == 'confirm' for r in result['reviews'])
            return result
        with p.db() as db:
            reviews = [dict(r) for r in db.execute('SELECT * FROM reviews ORDER BY created DESC LIMIT 30')]
        return {'project': p.state(), 'tasks': p.tasks(), 'reviews': reviews, 'independent_previews': independent_previews(p),
                'final_confirmed': p.approved('final')}
    if action == 'doctor':
        if engine == 'generate':
            from media import doctor
            return doctor()
        from registry import status
        from media import binary
        values = {'skills': status()}
        for name in ('ffmpeg', 'ffprobe'):
            try: values[name] = binary(name)
            except ValueError: values[name] = None
        return values
    if action == 'update': return p.update(data['patch'], data['revision'])
    if action == 'review':
        rid = p.open_review(data['stage'])
        return p.review(rid)
    if action == 'decide':
        if engine == 'generate':
            return p.decide(data['request_id'], data['action'], data['revision'],
                            data=data.get('data'), cap=data.get('cap'), selections=data.get('selections'), note=data.get('note', ''))
        return p.decide(data['request_id'], data['revision'], data['action'], data.get('note', ''), data.get('cap'))
    if engine == 'generate':
        from provider import quote_operation, submit_operation, poll_operation, download_operation
        if action == 'retry-local':
            from core import check
            with p.db() as db:
                old = db.execute('SELECT * FROM renders WHERE id=?', (data['task'],)).fetchone()
                check(old and old['status'] == 'failed', '只允许明确失败的本地合成重试，不能重提云任务。')
                db.execute("UPDATE renders SET status='retry-approved' WHERE id=?", (old['id'],))
            return {'retry_approved': old['id']}
        if action == 'prepare':
            from director import prepare
            return prepare(p)
        if action in ('quote', 'submit', 'poll', 'download'):
            return {'quote': quote_operation, 'submit': submit_operation, 'poll': poll_operation,
                    'download': download_operation}[action](p, data['operation'])
        if action == 'render':
            from media import render
            from core import check
            summary = p.summary()
            old = [r for r in summary['renders'] if r['revision'] == summary['project']['revision'] and r['status'] != 'retry-approved']
            if old:
                previous = old[-1]
                check(previous['status'] == 'done', '该版本已有合成记录，请先核查原任务。', 'original_only')
                result = previous['result']
                import hashlib
                file = p.inside(result['file'])
                check(file.is_file(), '原成片缺失，核查原任务后再处理。')
                if result.get('workbench_sha256'):
                    check(hashlib.sha256(file.read_bytes()).hexdigest() == result['workbench_sha256'], '原成片已变化。')
                return result
            result = render(p)
            import hashlib
            result['workbench_sha256'] = hashlib.sha256(p.inside(result['file']).read_bytes()).hexdigest()
            with p.db() as db:
                db.execute("UPDATE renders SET result=? WHERE revision=? AND status='done'", (json.dumps(result), summary['project']['revision']))
            return result
        if action == 'recover':
            p.sync()
            return p.summary()
        if action == 'import': return p.import_file(data['file'])
    else:
        from media import import_file, analyze, render
        if action == 'register-preview': return register_preview(p, data)
        if action == 'import': return import_file(p, data['file'], data['kind'], data.get('revision'))
        if action == 'recover': return p.recover(data.get('resume', False))
        if action == 'retry-local': return p.retry_local(data['task'])
        if action == 'analyze': return analyze(p)
        if action == 'transcribe':
            from providers import transcribe
            return transcribe(p)
        if action == 'render': return render(p)
        if action in ('roughcut', 'packaging'):
            if p.state()['workflow'][action] in ('local-cuts', 'none'):
                return {'execution': 'agent', 'project': p.state(), 'instructions': '提出剪切与字幕建议，保存后打开 roughcut 审阅；无包装无需创作动画。'}
            from cli import agent_brief
            return agent_brief(p, action)
        if action == 'auto-gold':
            from auto_gold import build
            return build(p)
        if action == 'attach-source':
            return attach_source(p, data)
    raise ValueError('不支持的执行操作。')


def independent_previews(p):
    from core import file_hash
    with p.db() as db:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='independent_previews'").fetchone()
        rows = [dict(r) for r in db.execute('SELECT * FROM independent_previews ORDER BY created DESC')] if exists else []
    for row in rows:
        try:
            path = p.public_file(row['file'])
            row['available'] = path.is_file() and file_hash(path) == row['sha256']
        except (ValueError, OSError):
            row['available'] = False
    return rows


def register_preview(p, data):
    """Register an existing independent composition without creating a render or approval."""
    from core import check, file_hash
    import time
    rel = Path(data['file'])
    check(not rel.is_absolute() and rel.parts and rel.parts[0] == 'exports' and rel.suffix.lower() == '.mp4', '审看片须在本工程 exports 内。')
    video = p.public_file(rel.as_posix())
    check(video.is_relative_to((p.root / 'exports').resolve()), '审看片须在本工程 exports 内。')
    manifest = video.parent / 'manifest.json'
    check(manifest.is_file() and manifest.resolve().is_relative_to((p.root / 'exports').resolve()), '缺少本工程制作清单。')
    m = json.loads(manifest.read_text(encoding='utf-8'))
    sha = file_hash(video)
    check(m.get('type') == 'independent-composition-preview' and m.get('project_id') == p.state()['project_id'] and m.get('sha256') == sha and m.get('technicalPass') is True, '清单、工程或文件校验不匹配。')
    subtitles = video.parent / 'captions.srt'
    subtitle_rel = subtitles.relative_to(p.root).as_posix() if subtitles.is_file() and subtitles.resolve().is_relative_to((p.root / 'exports').resolve()) else None
    with p.db() as db:
        state = p.state(db)
        check(type(data.get('revision')) is int and data['revision'] == state['revision'] == m.get('base_revision'), '工程版本已改变，不能作为当前审看片登记。', 'stale_revision', 409)
        check(not db.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(), '工程任务运行中。', 'busy', 409)
        db.execute('CREATE TABLE IF NOT EXISTS independent_previews (file TEXT PRIMARY KEY, revision INTEGER NOT NULL, sha256 TEXT NOT NULL, subtitles TEXT, created REAL NOT NULL)')
        existing = db.execute('SELECT * FROM independent_previews WHERE file=?', (rel.as_posix(),)).fetchone()
        if existing:
            check(existing['sha256'] == sha and existing['revision'] == state['revision'], '已有不同登记，保留原记录。', 'conflict', 409)
        else:
            db.execute('INSERT INTO independent_previews VALUES(?,?,?,?,?)', (rel.as_posix(), state['revision'], sha, subtitle_rel, time.time()))
            p.event(db, 'independent_preview_registered', {'file': rel.as_posix(), 'revision': state['revision'], 'sha256': sha})
    return {'file': rel.as_posix(), 'revision': state['revision'], 'sha256': sha, 'subtitles': subtitle_rel, 'kind': 'independent-preview', 'available': True}


def attach_source(p, data):
    """A rights-reviewed local clip is an actual scene, retaining source provenance."""
    from core import check, digest, file_hash, atomic
    from media import import_file, run, binary
    import uuid
    s = p.state()
    check(data['revision'] == s['revision'], '工程已变化，请刷新。', 'stale_revision', 409)
    check(data.get('usage_confirmed') is True and data.get('source_page') and data.get('match_reason'),
          '须填写来源、匹配原因并确认使用许可。')
    start, end = float(data['start']), float(data['end'])
    check(0 <= start < end <= s['duration'], '资料映射时间无效。')
    imported = import_file(p, data['file'], 'artifact')
    from media import probe
    info = probe(p.root / imported['file'])
    seconds = (end - start) / s['speed']
    check(float(info['format']['duration']) >= seconds - .05, '资料片段短于映射时长。')
    sid = data.get('scene_id') or uuid.uuid4().hex
    check(isinstance(sid, str) and sid.replace('-', '').isalnum(), '资料编号无效。')
    code = p.root / 'work' / ('source-' + sid + '-' + uuid.uuid4().hex[:8])
    code.mkdir()
    atomic(code / 'provenance.json', {k: data[k] for k in ('source_page', 'match_reason', 'usage_confirmed')})
    frame = code / 'keyframe.jpg'
    run([binary('ffmpeg'), '-v', 'error', '-y', '-i', str(p.root / imported['file']), '-frames:v', '1', str(frame)])
    scene = {'id': sid, 'start': start, 'end': end, 'title': data.get('title', '资料画面'),
             'mode': data.get('mode', 'fullscreen'), 'artifact': imported['file'], 'artifact_hash': imported['sha256'],
             'artifact_speed': s['speed'], 'keyframe': frame.relative_to(p.root).as_posix(),
             'code': code.relative_to(p.root).as_posix(), 'component': 'local-source-clip',
             'source_revision': file_hash(code / 'provenance.json'),
             'timing_fingerprint': digest({'source': s['source'], 'cuts': s['cuts'], 'speed': s['speed']}),
             'source_page': data['source_page'], 'match_reason': data['match_reason']}
    return p.update({'scenes': [x for x in s['scenes'] if x['id'] != sid] + [scene]}, s['revision'])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('engine', choices=['talk', 'hybrid', 'footage', 'generate'])
    parser.add_argument('root')
    parser.add_argument('action')
    a = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    try:
        result = execute(a.engine, Path(a.root).resolve(), a.action, json.load(sys.stdin))
        print(json.dumps({'ok': True, 'result': result}, ensure_ascii=False))
    except Exception as error:
        # Expected errors are user-safe Skill validation errors; no request bodies or traceback.
        safe = isinstance(error, ValueError)
        print(json.dumps({'ok': False, 'error': getattr(error, 'code', 'execution_failed'),
                          'message': str(error) if safe else '执行失败，请核对依赖和原项目。',
                          'status': getattr(error, 'status', 400)}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == '__main__': main()
