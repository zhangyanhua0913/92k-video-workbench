"""Capability registry. Plugins are reviewed adapters, never executable URLs from the UI."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from core import home, check, atomic, file_hash

FRED_REVISION = 'eec77dcfa99318f565c391bf557f5d43042ec061'
SPECS = [
    dict(id='whisper-local', name='本地 Whisper', stages=['transcribe'], execution='script', input='video', output='word-cues', version='1', dependency='whisper'),
    dict(id='qwen-cloud', name='千问云端识别', stages=['transcribe'], execution='script', input='video', output='word-cues', version='1', dependency='fredtalk'),
    dict(id='fredtalk-roughcut', name='FredTalk 字幕与粗剪', stages=['roughcut'], execution='agent', input='source-cues', output='reviewed-cuts', version='2.5', dependency='fredtalk', source_revision=FRED_REVISION),
    dict(id='fredtalk-motion', name='FredTalk 动态包装', stages=['packaging'], execution='agent', input='reviewed-timeline', output='remotion-clips', version='2.5', dependency='fredtalk', source_revision=FRED_REVISION),
    dict(id='remotion-plugin', name='Remotion 插件 · 自由创意包装', stages=['packaging'], execution='agent', input='reviewed-timeline', output='remotion-clips', version='1', dependency='remotion', source_revision='remotion-plugin-4.0.534'),
    dict(id='remotion-gold', name='Remotion · 暗金科技动态包装', stages=['packaging'], execution='agent', input='reviewed-timeline', output='remotion-clips', version='1', dependency='remotion', source_revision='talking-edit-gold-style-v1'),
    dict(id='remotion-evidence', name='Remotion · 资料讲解与人物同屏', stages=['packaging'], execution='agent', input='reviewed-timeline', output='remotion-clips', version='2', dependency='remotion', source_revision='talking-edit-evidence-v2'),
    dict(id='none', name='不添加动态包装', stages=['packaging'], execution='script', input='reviewed-timeline', output='video', version='1', dependency=None),
    dict(id='ffmpeg', name='本地 FFmpeg', stages=['render'], execution='script', input='timeline', output='mp4-srt', version='1', dependency='ffmpeg')]


def config():
    p=home()/'dependencies.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {}


def fred_root():
    return Path(config().get('fredtalk', home()/'deps'/'FredTalk')).resolve()


def specs():
    extra=home()/'adapters.json'
    extensions=json.loads(extra.read_text(encoding='utf-8')) if extra.exists() else []
    # Preserve explicitly installed adapters; fresh bundle installs get the reviewed sibling.
    bundled=[]
    root=Path(__file__).resolve().parents[3]
    manifest=root/'manifests/bundled-skills.json'
    instructions=root/'skills/narration-footage/references/workbench-adapter.md'
    if manifest.is_file() and instructions.is_file() and not any(x['id']=='narration-footage-v0-1' for x in extensions):
        sha=json.loads(manifest.read_text(encoding='utf-8'))['narration-footage']['adapter_sha256']
        bundled=[dict(id='narration-footage-v0-1',name='网络素材解说 · v0.1（Agent制作）',stages=['packaging'],
            execution='agent',input='reviewed-timeline',output='remotion-clips',version='0.1.0',dependency=None,
            instructions=str(instructions),instructions_hash=sha,source_revision=sha)]
    return SPECS + bundled + extensions


def validate_selection(selection):
    byid={x['id']:x for x in specs()}
    for stage,skill in selection.items():
        check(skill in byid and stage in byid[skill]['stages'], 'Skill 不支持该流程步骤：'+str(skill))


def status():
    from vault import Vault
    cfg=config(); fred=fred_root(); installed=(fred/'.talking-edit-revision').exists() and (fred/'.talking-edit-revision').read_text().strip()==FRED_REVISION
    if installed:
        try:
            manifest=json.loads((fred/'.talking-edit-integrity.json').read_text(encoding='utf-8'))
            installed=all((fred/name).is_file() and file_hash(fred/name)==sha for name,sha in manifest.items() if name.endswith('.py'))
        except Exception:installed=False
    py=Path(cfg.get('whisper_python','missing'))
    model=Path(cfg.get('whisper_model','missing'))
    out=[]
    for x in specs():
        reason=[]
        if x['dependency']=='fredtalk' and not installed:
            reason.append('需要准备固定版本 FredTalk')
        if x['dependency']=='whisper' and (not py.is_file() or not (model/'model.bin').is_file()):
            reason.append('需要隔离环境及 small 模型')
        if x['dependency']=='ffmpeg' and not (os.environ.get('TALKING_EDIT_FFMPEG') or cfg.get('ffmpeg') or shutil.which('ffmpeg')):
            reason.append('缺少 FFmpeg')
        if x['dependency']=='remotion':
            node=os.environ.get('TALKING_EDIT_NODE') or cfg.get('node') or shutil.which('node')
            if not node or not Path(node).is_file():reason.append('缺少 Node.js')
            if x['id']=='remotion-plugin':
                plugin=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'plugins/cache/openai-curated-remote/remotion'
                if not any(plugin.glob('*/skills/remotion-best-practices/SKILL.md')):reason.append('需要安装 Remotion 插件并重启 Agent 会话')
            template={'remotion-gold':('gold-motion','Gold.tsx'),'remotion-evidence':('evidence-motion','Evidence.tsx')}.get(x['id'])
            if template and not (Path(__file__).resolve().parents[1]/'templates'/template[0]/'src'/template[1]).is_file():reason.append('内置风格模板缺失，请重新安装 Skill')
        if x['id']=='qwen-cloud':
            if not Vault().status()['configured']:reason.append('请在页面配置 Key')
            if not (home()/'cloud-pricing.json').exists():reason.append('官方费率尚未核验')
            reason.append('当前 Token 计费尚无可验证费用上界，新提交关闭')
        out.append(dict(x,ready=not reason,reasons=reason))
    return out


def prepare_fred(path=None):
    target=Path(path or home()/'deps'/'FredTalk').resolve()
    if (target/'.talking-edit-revision').exists():
        check((target/'.talking-edit-revision').read_text().strip()==FRED_REVISION,'已有不同 FredTalk 版本，不覆盖。')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        archive=target.parent/('FredTalk-'+FRED_REVISION+'.zip')
        if not target.exists():
            if not archive.exists():
                tmp=archive.with_suffix('.part')
                with urllib.request.urlopen('https://codeload.github.com/njrhts2kvv-star/FredTalk/zip/'+FRED_REVISION,timeout=120) as r, tmp.open('wb') as f:
                    shutil.copyfileobj(r,f)
                os.replace(tmp,archive)
            with zipfile.ZipFile(archive) as z:
                for name in z.namelist():
                    check(not Path(name).is_absolute() and '..' not in Path(name).parts,'非法归档路径。')
                z.extractall(target.parent)
            (target.parent/('FredTalk-'+FRED_REVISION)).rename(target)
        required=['LICENSE','THIRD_PARTY_NOTICES.md','library/catalog.json','library/routes.json','library/media-manifest.json',
                  'skills/audio-subtitle-roughcut/assets/review-app/server.py','skills/audio-subtitle-roughcut/scripts/qwen_asr.py',
                  'skills/fred-remotion-output/scripts/library_gate.py','skills/fred-remotion-output/SKILL.md']
        check(all((target/name).is_file() for name in required),'FredTalk 目录不完整。')
        if (target/'.git').exists():
            revision=subprocess.run(['git','-C',str(target),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip()
            check(revision==FRED_REVISION,'FredTalk 提交与固定版本不匹配。')
        else:
            # Compare critical execution files with the pinned upstream commit before importing Python.
            import hashlib
            for name in (required[5],required[6],required[7]):
                with urllib.request.urlopen('https://raw.githubusercontent.com/njrhts2kvv-star/FredTalk/'+FRED_REVISION+'/'+name,timeout=30) as r:
                    expected=hashlib.sha256(r.read()).hexdigest()
                check(file_hash(target/name)==expected,'FredTalk 关键脚本与固定提交不一致。')
        (target/'.talking-edit-revision').write_text(FRED_REVISION)
        atomic(target/'.talking-edit-integrity.json',{name:file_hash(target/name) for name in required})
    data=config(); data['fredtalk']=str(target); atomic(home()/'dependencies.json',data)
    return {'installed':str(target),'revision':FRED_REVISION}


def prepare_whisper(download=False, base_python=None):
    root=home()/'deps'/'whisper'; py=root/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    if not py.exists():
        subprocess.run([base_python or sys.executable,'-m','venv',str(root)],check=True,stdout=subprocess.DEVNULL)
    requirements=Path(__file__).resolve().parents[1]/'references/whisper-requirements.txt'
    subprocess.run([str(py),'-m','pip','install','-r',str(requirements)],check=True,stdout=subprocess.DEVNULL)
    model=home()/'models'/'small'
    if download and not (model/'model.bin').exists():
        subprocess.run([str(py),'-c','from faster_whisper.utils import download_model; import sys; download_model("small", output_dir=sys.argv[1])',str(model)],check=True,stdout=subprocess.DEVNULL)
    data=config();data.update(whisper_python=str(py),whisper_model=str(model));atomic(home()/'dependencies.json',data)
    return {'python':str(py),'model':str(model),'model_ready':(model/'model.bin').exists()}


def register(path):
    """Agent adapters only in v1; no arbitrary subprocess from manifest."""
    item=json.loads(Path(path).read_text(encoding='utf-8'))
    check(set(item)>= {'id','name','stages','execution','input','output','version','dependency','instructions','source_revision'},'适配器字段不完整。')
    check(item['execution']=='agent' and item['dependency'] is None,'第三方首版仅注册经审阅的 Agent 适配器。')
    check(set(item['stages']) <= {'roughcut','packaging'},'第三方首版支持粗剪和包装步骤。')
    check(item['id'] not in {x['id'] for x in specs()},'适配器已注册。')
    instructions=Path(item['instructions']).resolve();check(instructions.is_file(),'指令文件不存在。')
    item['instructions']=str(instructions);item['instructions_hash']=file_hash(instructions)
    p=home()/'adapters.json';old=json.loads(p.read_text(encoding='utf-8')) if p.exists() else [];atomic(p,old+[item])
    return item
