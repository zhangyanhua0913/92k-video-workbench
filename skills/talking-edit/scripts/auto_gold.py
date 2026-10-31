"""Build a conservative gold-style proposal using only current cue timings."""
import re, json, shutil, subprocess, os
from pathlib import Path
from types import SimpleNamespace
from core import check, home, digest, atomic
from media import intervals

def propose(state):
    check(state.get('source') and state.get('cues'),'自动包装需要视频和字幕。')
    mapping=intervals(state['duration'],state['cuts'],state['speed'])
    proposals=[]
    for segment in mapping:
        cues=[c for c in state['cues'] if segment['source_start']<=c['start'] and c['end']<=segment['source_end'] and c['text'].strip()]
        last=-1e9
        for cue in cues:
            a,b=cue['start'],cue['end']
            if a-last<12*state['speed'] or b-a<.6:continue
            title=re.sub(r'\s+','',cue['text']).strip('，。！？,.!?')
            if len(title)<5 or re.fullmatch(r'(那么|然后|所以|最后|当然|其实|注意)[啊呢呀]*',title):continue
            proposals.append({'id':'auto-gold-'+str(len(proposals)+1),'start':a,'end':b,'mode':'fullscreen',
                'title':title[:30],'description':'根据本句字幕生成的标题动画，未做语义核验。',
                'componentPlan':{'query':title,'candidates':[],'selected':'gold-title-v1'}})
            last=b
    check(proposals,'没有适合生成动画的字幕段，请检查字幕时码。')
    return proposals

def dependencies():
    from registry import config
    cfg=config();node=cfg.get('node') or shutil.which('node');check(node,'缺少 Node.js。','dependency_missing')
    root=home()/'deps'/'gold-motion-v1';template=Path(__file__).resolve().parents[1]/'templates/gold-motion'
    root.mkdir(parents=True,exist_ok=True)
    for name in ('package.json','package-lock.json'):
        destination=root/name
        if destination.exists():check(destination.read_bytes()==(template/name).read_bytes(),'自动包装依赖版本已变，请先核查旧依赖目录。')
        else:shutil.copyfile(template/name,destination)
    cli=root/'node_modules/@remotion/cli/remotion-cli.js'
    if not cli.is_file():
        npm=Path(node).parent/'node_modules/npm/bin/npm-cli.js'
        check(npm.is_file(),'缺少 npm，请安装 Node.js/npm 后重试。','dependency_missing')
        proc=subprocess.run([node,str(npm),'ci','--no-audit','--no-fund'],cwd=root,capture_output=True)
        check(proc.returncode==0,'自动包装依赖安装失败，请检查网络和 npm。','dependency_missing')
    return root

def build(project):
    from cli import render_scene,attach_scene
    s=project.state();check(s['workflow']['packaging']=='remotion-gold','当前不是暗金模板。')
    check(all(x['id'].startswith('auto-gold-') for x in s['scenes']),'已有人工包装，请保留原项目并切换手动模式。','review_required')
    scenes=propose(s)
    dep=dependencies();template=Path(__file__).resolve().parents[1]/'templates/gold-motion'
    # Stable generated source lets completed scene tasks be reused after interruption.
    code=project.root/'work'/('auto-gold-'+digest({'source':s['source'],'cues':s['cues'],'cuts':s['cuts'],'speed':s['speed']})[:20])
    code.mkdir(exist_ok=True);(code/'src').mkdir(exist_ok=True)
    for name in ('package.json','package-lock.json'):shutil.copyfile(template/name,code/name)
    shutil.copyfile(template/'src/Gold.tsx',code/'src/Gold.tsx')
    link=code/'node_modules'
    if not link.exists():
        if os.name=='nt':
            import base64
            quoted=lambda p:"'"+str(p).replace("'","''")+"'"
            script='New-Item -ItemType Junction -Path '+quoted(link)+' -Target '+quoted(dep/'node_modules')+' -ErrorAction Stop | Out-Null'
            proc=subprocess.run(['powershell','-NoProfile','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()],capture_output=True)
            check(proc.returncode==0,'无法连接隔离依赖目录。')
        else:link.symlink_to(dep/'node_modules',target_is_directory=True)
    entries=[]
    for scene in scenes:
        frames=max(1,round((scene['end']-scene['start'])/s['speed']*30))
        props=json.dumps({'title':scene['title'],'eyebrow':'内容要点','variant':'title'},ensure_ascii=False)
        entries.append(f'<Composition id="{scene["id"]}" component={{GoldScene}} durationInFrames={{{frames}}} fps={{30}} width={{1280}} height={{720}} defaultProps={{{props}}}/>')
    (code/'src/index.tsx').write_text("import React from 'react';import {Composition,registerRoot} from 'remotion';import {GoldScene} from './Gold';const Root=()=> <>"+''.join(entries)+"</>;registerRoot(Root);",encoding='utf8')
    project.update({'scenes':scenes},s['revision'])
    def confirm(stage):
        state=project.state();project.decide(project.open_review(stage),state['revision'],'confirm','用户选择暗金模板全自动：本地生成与技术检查，不代表用户实际听看。')
    confirm('packaging')
    shells=list((dep/'node_modules/.remotion').rglob('chrome-headless-shell.exe')) if os.name=='nt' else []
    browser=str(shells[0]) if shells else None
    for scene in scenes:
        result=render_scene(project,SimpleNamespace(scene=scene['id'],code=str(code),entry='src/index.tsx',composition=scene['id'],manifest=None,browser=browser))
        attach_scene(project,SimpleNamespace(scene=scene['id'],code=str(code),entry='src/index.tsx',video=result['video'],keyframe=result['keyframe'],component='gold-template-title-v1',source_revision='gold-auto-v1',manifest=None))
    confirm('keyframes')
    return {'scene_count':len(scenes),'code':str(code)}
