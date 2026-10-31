"""Optional transcribers. Cloud submits only after current explicit versioned approval."""
import contextlib
import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from core import home, check, atomic, digest, EditError
from registry import config, fred_root, FRED_REVISION
from media import extract_audio, parse_srt
from vault import Vault

MODEL='qwen-audio-3.1-asr-flash-filetrans'
CURRENT_BILLING='tokens'


def checked_response(response):
    if not response.ok:
        try:code=response.json().get('code','')
        except Exception:code=''
        known={'InvalidApiKey':('key_invalid','Key 无效。'),'ApiKeyExpired':('key_expired','Key 已明确到期。'),
               'Arrearage':('insufficient_balance','服务商余额不足。'),'InsufficientBalance':('insufficient_balance','服务商余额不足。'),
               'Throttling':('rate_limited','服务商限流，请按原任务状态处理。'),'Throttling.RateQuota':('rate_limited','服务商限流。')}
        if code in known:
            error,message=known[code];raise EditError(message,error)
        if response.status_code==429:raise EditError('服务商限流。','rate_limited')
        if response.status_code==401:raise EditError('Key 无效或无访问权限。','key_invalid')
        raise EditError('服务商请求被拒绝，状态尚待核实。','upstream_http')
    return response.json()


def cloud_quote(project, state=None):
    s=state or project.state(); check(s['source'],'缺少视频。')
    check(CURRENT_BILLING=='seconds','官方当前按输入/输出 Token 计费，尚无可验证费用上界；云端新提交保持关闭。','price_unbounded')
    p=home()/'cloud-pricing.json'; check(p.exists(),'尚无已核验官方费率；云端转写保持关闭。','price_unknown')
    price=json.loads(p.read_text(encoding='utf-8'))
    check(price['model']==MODEL and 0 <= time.time()-price['verified_at'] < 86400,'费率已过期或不匹配。','price_stale')
    check(price['cny_per_second']>0 and price['round_seconds']>=1,'费率无效。')
    key=Vault().status(); check(key['configured'],'请在配置页填写 Key。','key_missing')
    seconds=math.ceil(s['duration']/price['round_seconds'])*price['round_seconds']
    return dict(model=MODEL,source=s['source']['sha256'],revision=s['revision'],key_id=key['active'],
        duration=s['duration'],billing_seconds=seconds,estimated_max_cny=round(seconds*price['cny_per_second'],6),
        pricing=price,scope='仅本项目源视频提取的单声道录音，一次转写；不上传视频画面或其他文件。')


def transcribe(project):
    s=project.state(); selected=s['workflow']['transcribe']
    audio=extract_audio(project)
    fingerprint=digest({'source':s['source'],'skill':selected,'model':MODEL if selected=='qwen-cloud' else 'small-cpu-int8-v1'})
    if selected=='qwen-cloud':
        return cloud_transcribe(project,s,audio,fingerprint)
    cfg=config();py=Path(cfg.get('whisper_python','missing'));model=Path(cfg.get('whisper_model','missing'))
    check(py.is_file() and (model/'model.bin').exists(),'请先 prepare-deps whisper --download-model。','dependency_missing')
    task,fresh=project.claim('transcribe',fingerprint)
    if not fresh:return json.loads(task['result'])
    out=project.root/'work'/('asr-'+task['id']+'.json')
    try:
        p=subprocess.run([str(py),str(Path(__file__).with_name('whisper_worker.py')),str(model),str(audio),str(out)],capture_output=True)
        check(p.returncode==0,'本地识别失败，检查隔离环境与模型。','asr_failed')
        result=json.loads(out.read_text(encoding='utf-8'))
        project.finish(task['id'],{'file':out.relative_to(project.root).as_posix(),'cue_count':len(result['cues']),'paid':False})
        project.update({'cues':result['cues']},s['revision'])
        return result
    except Exception:
        project.finish(task['id'],{'code':'asr_failed','note':'原任务保留，不自动重复运行。'},'failed')
        raise


def cloud_transcribe(project,s,audio,fingerprint):
    # Existing cloud tasks are resumed using their original stored pricing/key scope.
    old=next((t for t in project.tasks() if t['kind']=='transcribe' and t['fingerprint']==fingerprint),None)
    if old and old['status']=='done':return old['result']
    if not old:
        quote=cloud_quote(project)
        check(project.approved('transcribe-budget',s),'请在页面确认当前上传与费用上限。','review_required')
        task,_=project.claim('transcribe',fingerprint)
        root=project.root/'work'/('qwen-'+task['id']);root.mkdir()
        atomic(root/'authorization.json',quote)
    else:
        task=old; root=project.root/'work'/('qwen-'+task['id'])
        check(old['status']!='running','原转写进程可能仍在运行，请先 recover 核查。','busy')
    receipt=root/'asr-state.json'
    if old:
        check(receipt.exists(),'提交结果未知，请查主站控制台，禁止重提。','submit_unknown')
        state=json.loads(receipt.read_text(encoding='utf-8'))
        check(state.get('task_id'),'提交结果未知，请查原任务，禁止重提。','submit_unknown')
        check(state.get('status') not in ('FAILED','CANCELED','UNKNOWN'),'原任务终态需人工核查，不能自动重提。','upstream_failed')
        with project.db() as c:
            check(not c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(),'已有任务运行。','busy')
            c.execute("UPDATE tasks SET status='running',pid=? WHERE id=?",(os.getpid(),task['id']))
    saved=json.loads((root/'authorization.json').read_text(encoding='utf-8'))
    script=fred_root()/'skills/audio-subtitle-roughcut/scripts/qwen_asr.py'
    check(script.is_file(),'缺少 FredTalk 转写适配入口。','dependency_missing')
    spec=importlib.util.spec_from_file_location('fredtalk_qwen',script);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.credential=lambda:Vault().get(saved['key_id'])
    module.checked=checked_response
    # Upstream's file transcription transport/export is reused; current user's original-speed policy overrides Fred's preparation defaults.
    from media import binary
    previous=os.environ.get('PATH','');os.environ['PATH']=str(Path(binary('ffmpeg')).parent)+os.pathsep+previous
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            module.execute(SimpleNamespace(audio=audio,output=root,context=None,terms=None,polls=1,interval=0))
        cues=parse_srt((root/'source-asr.srt').read_text(encoding='utf-8'))
        result={'cue_count':len(cues),'file':(root/'source-asr.srt').relative_to(project.root).as_posix(),'paid':'账单以服务商原任务为准','listeningReviewed':False}
        project.finish(task['id'],result);project.update({'cues':cues},s['revision'])
        return result
    except Exception as e:
        state=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
        code=getattr(e,'code',None) or ('upstream_pending' if state.get('task_id') else 'submit_unknown')
        status='waiting' if state.get('task_id') else 'unknown'
        project.finish(task['id'],{'code':code,'task_id':state.get('task_id'),'note':'只续查本原任务，不重提、不猜测退款或账单。'},status)
        raise EditError('转写尚未完成或网络异常；请续查原任务。',code)
    finally:
        os.environ['PATH']=previous
