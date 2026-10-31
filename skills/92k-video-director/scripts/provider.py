"""92K Dreamface adapter. No generation POST retries. Local authorization is not a wallet hold."""
import json
import mimetypes
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from core import check, DirectorError, dump, digest, shot_hash, no_secrets
from vault import Vault

BASE = 'https://api1.92k.store'
PREFIX = '/video-api/dreamface'
SUPPORTED = {'dreamface:flux-text', 'dreamface:flux-image', 'dreamface:seedream-4.5', 'dreamface:dreamvideo', 'dreamface:avatar', 'dreamface:lipsync', 'dreamface:lipsync-2', 'dreamface:tts-common', 'dreamface:tts-pro', 'dreamface:tts-clone'}
DEFAULTS = {'image': 'dreamface:flux-text', 'image_edit': 'dreamface:flux-image', 'video': 'dreamface:dreamvideo', 'image_video': 'dreamface:dreamvideo', 'avatar': 'dreamface:avatar', 'lipsync': 'dreamface:lipsync-2'}
MIMES = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp', 'video/mp4': '.mp4', 'video/webm': '.webm', 'audio/mpeg': '.mp3', 'audio/mp3': '.mp3', 'audio/wav': '.wav', 'audio/x-wav': '.wav', 'audio/mp4': '.m4a', 'audio/flac': '.flac', 'audio/ogg': '.ogg'}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def classify(status, message):
    text = str(message).lower()
    if 'bound instance' in text or '绑定' in text:
        return 'bound_instance', '此Key绑定其他入口，请使用适用于92k公开接口的积分Key。'
    if ('quote' in text or '报价' in text) and any(w in text for w in ('expired', '过期')):
        return 'quote_expired', '报价已过期，请刷新同一制作参数的报价后继续核对预算。'
    if any(w in text for w in ('expired', '到期', '过期')):
        return 'key_expired', 'Key已到期或失效，请更换后重新验证。'
    if any(w in text for w in ('insufficient', '余额不足', '积分不足', 'not enough')):
        return 'insufficient_points', '积分不足，请补充积分或调整制作计划。'
    return {401: ('invalid_key', 'Key无效，请更换或检查。'), 403: ('forbidden', '无权访问该任务或素材，请检查原Key。'), 429: ('rate_limited', '接口繁忙或限流，保留原计划，稍后重试。')}.get(status, ('api_rejected', '接口拒绝请求，请检查参数、模型状态及原任务。'))


class Client:
    def __init__(self, vault=None):
        self.vault = vault or Vault()
        self.opener = build_opener(NoRedirect())

    def request(self, path, body=None, credential=None, binary=False, headers=None):
        check(path.startswith((PREFIX + '/', '/video-api/account')) and '://' not in path and '\r' not in path and '\n' not in path, '接口路径无效。')
        public = path == PREFIX + '/models'
        secret = None if public else self.vault.get(credential)
        fields = {'Accept': 'application/json', **(headers or {})}
        if secret:
            fields['Authorization'] = 'Bearer ' + secret
        if body is not None and not binary:
            fields['Content-Type'] = 'application/json'
        data = body if binary else dump(body).encode() if body is not None else None
        try:
            with self.opener.open(Request(BASE + path, data=data, headers=fields), timeout=60) as response:
                value = json.load(response)
        except HTTPError as error:
            try:
                raw = json.load(error)
            except Exception:
                raw = {}
            code, message = classify(error.code, raw.get('error', ''))
            raise DirectorError(message, code, error.code) from None
        except (URLError, TimeoutError, OSError):
            raise DirectorError('连接未确认；已提交的任务只能查询原单，不能重新生成。', 'network_unknown', 503) from None
        check(not secret or secret not in dump(value), '响应包含凭据，已停止展示。', 'sensitive_response')
        return value

    def account(self):
        raw = self.request('/video-api/account', {})
        return {k: raw.get(k) for k in ('valid', 'type', 'remaining_points', 'expire_at')} | {'notice': '到期信息为空时表示接口未提供，不能推断永久有效。'}

    def models(self):
        return self.request(PREFIX + '/models')

    def upload(self, path, kind, credential):
        path = Path(path)
        check(kind in ('image', 'audio', 'video') and path.is_file() and 0 < path.stat().st_size <= 100 * 1024 * 1024, '上传素材类型或大小无效。')
        return self.request(PREFIX + '/assets/' + kind, path.read_bytes(), credential, True, {'Content-Type': 'application/octet-stream', 'X-Filename': quote(path.name, safe='')})

    def download(self, task_id, credential, target_base, kind):
        # Credentials are sent only to the fixed 92K origin; no redirects followed.
        secret = self.vault.get(credential)
        url = BASE + PREFIX + '/tasks/' + str(uuid.UUID(task_id)) + '/result?download=1&index=0'
        try:
            with self.opener.open(Request(url, headers={'Authorization': 'Bearer ' + secret}), timeout=90) as response:
                mime = response.headers.get('Content-Type', '').split(';')[0].lower()
                check(mime in MIMES and mime.startswith(kind + '/'), '结果媒体类型与任务不符，下载已拒绝。', 'invalid_media')
                target = Path(str(target_base) + MIMES[mime])
                part = target.with_name(target.name + '.' + uuid.uuid4().hex + '.part')
                size = 0
                with part.open('xb') as stream:
                    while True:
                        chunk = response.read(65536)
                        if not chunk:
                            break
                        size += len(chunk)
                        check(size <= 512 * 1024 * 1024, '结果超出512MB限制。')
                        stream.write(chunk)
                check(size > 0, '结果为空。')
                os.replace(part, target)
                return target
        except (HTTPError, URLError, TimeoutError, OSError):
            raise DirectorError('下载未完成，请重试原任务下载；不会重新生成。', 'download_failed') from None


def row_operation(project, oid, db=None):
    if db is None:
        with project.db() as conn:
            return row_operation(project, oid, conn)
    row = db.execute('SELECT * FROM operations WHERE id=?', (oid,)).fetchone()
    check(row is not None, '制作任务不存在。', status=404)
    return dict(row)


def plan_operation(project, shot_id, purpose, request, ceiling, client=None):
    client = client or Client()
    no_secrets(request)
    check(purpose in ('visual', 'audio') and type(ceiling) is int and 0 <= ceiling <= 1000000000, '任务类型或积分上限无效。')
    check(set(request) == {'model_id', 'parameters', 'assets'} and request['model_id'] in SUPPORTED, '模型尚未适配，或请求结构无效。')
    state = project.state()
    shot = next((s for s in state['shots'] if s['id'] == shot_id), None)
    check(shot is not None, '镜头不存在。')
    credential = client.vault.status()['active']
    check(credential, '请先配置Key。', 'key_missing')
    fp = digest({'shot': shot_hash(shot), 'purpose': purpose, 'request': request})
    with project.db() as db:
        existing = db.execute('SELECT id FROM operations WHERE fingerprint=? AND credential=? ORDER BY created DESC LIMIT 1', (fp, credential)).fetchone()
        if existing:
            db.execute("UPDATE operations SET ceiling=? WHERE id=? AND task_id IS NULL", (ceiling, existing['id']))
            return row_operation(project, existing['id'], db)
        oid = uuid.uuid4().hex
        db.execute('INSERT INTO operations(id,shot_id,purpose,fingerprint,request,ceiling,credential,status,created) VALUES(?,?,?,?,?,?,?,\'planned\',?)', (oid, shot_id, purpose, fp, dump(request), ceiling, credential, time.time()))
        project.event(db, 'operation.planned', {'id': oid, 'shot_id': shot_id})
    return row_operation(project, oid)


def redo_operation(project, oid, review_id):
    """One human revision request creates at most one explicit replacement operation."""
    decision = project.review(review_id)
    check(decision['status'] == 'completed' and decision['result']['action'] == 'revise' and decision['stage'] in ('assets', 'final'), '需要素材/成片审看中用户的重做意见。', 'review_required')
    with project.db() as db:
        op = row_operation(project, oid, db)
        check(op['task_id'] and op['status'] in ('succeeded', 'failed', 'expired'), '原单未明确结束，只能查询原单。', 'original_only')
        check(project.operation_current(op, project.state(db)), '原任务已不属于当前镜头参数，请重新准备计划。', 'stale_operation')
        new_id = digest({'original': oid, 'review': review_id})[:32]
        existing = db.execute('SELECT id FROM operations WHERE id=?', (new_id,)).fetchone()
        if not existing:
            db.execute("INSERT INTO operations(id,shot_id,purpose,fingerprint,request,ceiling,credential,status,created) VALUES(?,?,?,?,?,?,?,'planned',?)", (new_id, op['shot_id'], op['purpose'], op['fingerprint'], op['request'], op['ceiling'], op['credential'], time.time()))
            project.event(db, 'operation.explicit_redo', {'original': oid, 'new': new_id, 'review_id': review_id})
    return row_operation(project, new_id)


def authorized(project, db, op):
    state = project.state(db)
    approval = db.execute('SELECT * FROM approvals WHERE revision=? ORDER BY created DESC LIMIT 1', (state['revision'],)).fetchone()
    check(approval is not None, '当前版本尚未确认整轮预算。', 'approval_required')
    scope = json.loads(approval['scope']).get(op['id'])
    check(scope and scope['fingerprint'] == op['fingerprint'] and scope['credential'] == op['credential'], '任务不在本轮批准范围内。', 'approval_required')
    # A changed project must never use an old operation with a new approval.
    shot = next((s for s in state['shots'] if s['id'] == op['shot_id']), None)
    check(shot is not None and digest({'shot': shot_hash(shot), 'purpose': op['purpose'], 'request': json.loads(op['request'])}) == op['fingerprint'], '镜头已改变，请重新准备任务。', 'stale_operation')
    return approval, scope


def quote_operation(project, oid, client=None):
    client = client or Client()
    op = row_operation(project, oid)
    check(op['task_id'] is None, '已提交任务只能查询原单。', 'original_only')
    check_audio_timing(project, op)
    models = client.models()
    model = next((m for m in models.get('models', []) if m.get('model_id') == json.loads(op['request'])['model_id']), None)
    check(model is not None and model.get('available', True) is not False and model.get('status') not in ('unavailable', 'paused', 'source_stale'), '当前模型不可用，请交给Agent调整。', 'model_unavailable')
    resolved = json.loads(op['resolved']) if op.get('resolved') else resolve_request(project, op, client)
    value = client.request(PREFIX + '/quotes', resolved, op['credential'])
    check(type(value.get('points')) is int and value['points'] >= 0 and value.get('quote_id') and isinstance(value.get('expires'), (int, float)), '报价返回不完整。')
    check(value['points'] <= op['ceiling'], '实时报价高于此任务批准上限，请重新确认预算。', 'price_increased')
    with project.db() as db:
        current = row_operation(project, oid, db)
        check(current['task_id'] is None, '任务已被其他调用提交。', 'original_only')
        db.execute('UPDATE operations SET quote=?,resolved=? WHERE id=?', (dump(value), dump(resolved), oid))
    return value


def check_audio_timing(project, op):
    if op['purpose'] != 'visual':
        return
    summary = project.summary()
    shot = next((s for s in summary['project']['shots'] if s['id'] == op['shot_id']), None)
    check(shot, '镜头已删除。', 'stale_operation')
    from media import audio_for, probe, duration
    sound = audio_for(project, shot, summary)
    if sound:
        check(duration(probe(sound)) <= float(shot['duration']) + .08, '配音长于目标镜头。先调整脚本/镜头并确认，再继续画面生成；已有配音可直接复用。', 'speech_too_long')


def resolve_request(project, op, client):
    request = json.loads(op['request'])
    models = client.models()
    model = next((m for m in models.get('models', []) if m.get('model_id') == request['model_id']), None)
    check(model is not None, '模型不存在。', 'model_unavailable')
    fields = model.get('fields', {})
    for field, refs in request['assets'].items():
        check(isinstance(refs, list), 'assets字段必须为数组。')
        converted = []
        for ref in refs:
            check(isinstance(ref, str), '素材引用无效。')
            if ref.startswith('file:'):
                relative = ref[5:]
            elif ref.startswith('operation:'):
                dependency = row_operation(project, ref[10:])
                check(dependency['credential'] == op['credential'], '依赖素材与任务必须使用同一Key。')
                check(dependency['status'] == 'succeeded' and dependency['local_file'], '先完成并下载依赖任务。', 'dependency_pending')
                relative = dependency['local_file']
            else:
                converted.append(ref)
                continue
            path = project.inside(relative)
            kind = fields.get(field, {}).get('kind')
            check(kind in ('image', 'audio', 'video'), '无法从模型目录确认素材类型。')
            uploaded = client.upload(path, kind, op['credential'])
            check(uploaded.get('asset_id'), '上传回执缺少asset_id。')
            converted.append(uploaded['asset_id'])
        request['assets'][field] = converted
    return request


def submit_operation(project, oid, client=None):
    client = client or Client()
    op = row_operation(project, oid)
    if op['task_id']:
        return poll_operation(project, oid, client)
    check_audio_timing(project, op)
    if not op['quote'] or json.loads(op['quote'])['expires'] <= time.time():
        quote_operation(project, oid, client)
    with project.db() as db:
        op = row_operation(project, oid, db)
        check(op['status'] == 'planned' and not op['task_id'], '任务已提交或停止，请查询原单。', 'original_only')
        approval, scope = authorized(project, db, op)
        # A paused interaction blocks new submissions but never blocks read-only recovery.
        latest = db.execute("SELECT result FROM reviews WHERE status='completed' ORDER BY created DESC LIMIT 1").fetchone()
        check(not latest or json.loads(latest['result'])['action'] != 'pause', '项目已暂停，请重新确认后继续。', 'paused')
        check(not db.execute("SELECT 1 FROM operations WHERE task_id IS NOT NULL AND status NOT IN ('succeeded','failed','expired')").fetchone(), '存在执行中或未知原单，先查询原单。', 'busy')
        value = json.loads(op['quote'])
        check(value['expires'] > time.time(), '报价已过期，请刷新。', 'quote_expired')
        check(value['points'] <= scope['ceiling'] and project.exposure(db) + value['points'] <= approval['cap'], '超出本轮积分上限。', 'budget_exceeded')
        tid = str(uuid.uuid4())
        db.execute("UPDATE operations SET task_id=?,points=?,status='submission_unconfirmed' WHERE id=?", (tid, value['points'], oid))
        project.event(db, 'operation.submit_intent', {'id': oid, 'task_id': tid, 'points': value['points']})
    # Durable UUID and budget occupancy are committed before this sole POST.
    try:
        response = client.request(PREFIX + '/tasks', {'quote_id': value['quote_id']}, op['credential'], headers={'Idempotency-Key': tid})
        check(response.get('task_id') == tid, '回执任务编号不符，保留原单核查。', 'receipt_mismatch')
    except BaseException:
        # Even HTTP errors remain conservative until an authoritative original-task query.
        raise
    with project.db() as db:
        db.execute('UPDATE operations SET status=?,response=? WHERE id=?', (response.get('status', 'created'), dump(response), oid))
    return response


def poll_operation(project, oid, client=None):
    client = client or Client()
    op = row_operation(project, oid)
    check(op['task_id'], '任务还未提交。')
    response = client.request(PREFIX + '/tasks/' + op['task_id'], credential=op['credential'])
    check(response.get('task_id') == op['task_id'], '原任务回执编号不符。', 'receipt_mismatch')
    billing = response.get('billing') or {}
    status = response.get('status', 'unknown')
    if billing.get('status') in ('deducting', 'unknown'):
        status = 'payment_unknown'
    with project.db() as db:
        db.execute('UPDATE operations SET status=?,response=? WHERE id=?', (status, dump(response), oid))
    return response


def download_operation(project, oid, client=None):
    client = client or Client()
    op = row_operation(project, oid)
    if op['local_file'] and project.inside(op['local_file']).is_file():
        return {'file': op['local_file'], 'reused': True}
    response = poll_operation(project, oid, client)
    check(response.get('status') == 'succeeded' and response.get('result_ready') and (response.get('billing') or {}).get('status') == 'paid', '成品尚未就绪或付款未确认，不可下载。', 'not_ready')
    kind = response.get('media_type')
    check(kind in ('image', 'video', 'audio'), '结果类型尚未适配。')
    target = client.download(op['task_id'], op['credential'], project.root / 'media' / oid, kind)
    relative = target.relative_to(project.root).as_posix()
    with project.db() as db:
        db.execute('UPDATE operations SET local_file=? WHERE id=?', (relative, oid))
    # Only visual results are candidates. Audio is attached through a revision update by the agent.
    if op['purpose'] == 'visual':
        shot = next((s for s in project.state()['shots'] if s['id'] == op['shot_id']), None)
        if shot:
            fp = digest({'shot': shot_hash(shot), 'purpose': op['purpose'], 'request': json.loads(op['request'])})
            if fp == op['fingerprint']:
                project.add_candidate(op['shot_id'], relative, shot_hash(shot), '92k')
    return {'file': relative, 'media_type': kind, 'next': '音频请测量时长后更新对应镜头；画面请交给用户审看采纳。'}
