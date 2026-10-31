#!/usr/bin/env python3
"""Machine-readable command entrypoint. No secret arguments or raw network errors."""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from core import Project, EditError, check, dumps, home, atomic, digest, file_hash,VERSION

if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')


def session(project):
    try:
        d=json.loads((project.meta/'session.json').read_text())
        check(d['origin'].startswith('http://127.0.0.1:') and d['project_id']==project.state()['project_id'],'会话不匹配。')
        req=urllib.request.Request(d['origin']+'/api/health',headers={'X-Talking-Session':d['session']})
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=2) as r:
            check(json.load(r)['project_id']==d['project_id'],'会话不匹配。')
        return d
    except Exception:return None


def detached(args, **kwargs):
    flags=(subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS) if os.name=='nt' else 0
    return subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=flags,start_new_session=os.name!='nt',**kwargs)


def review(project,stage,browser=True):
    d=session(project)
    if not d:
        detached([sys.executable,str(Path(__file__).resolve()),'--project',str(project.root),'serve'])
        for _ in range(100):
            time.sleep(.1);d=session(project)
            if d:break
        check(d,'辅助服务启动失败。','ui_unavailable')
    rid=project.open_review(stage)
    url=d['origin']+'/#session='+d['session']
    if browser:webbrowser.open(url)
    return {'request_id':rid,'stage':stage,'url':url,'revision':project.state()['revision']}


def wait(project,rid,seconds=40):
    deadline=time.monotonic()+min(40,max(0,seconds))
    while True:
        result=project.review(rid)
        # Health is an authenticated server touch, not just a SQLite poll.
        live=session(project)
        check(live,'页面服务已退出；重开同阶段 review 可恢复原请求。','ui_unavailable')
        if result['status']!='pending' or time.monotonic()>=deadline:
            return dict(result,project=project.state())
        time.sleep(min(live.get('heartbeat_seconds',1),max(0,deadline-time.monotonic())))


def launch_step(project,step):
    check(step in ('analyze','transcribe','render'),'未知执行步骤。')
    p=detached([sys.executable,str(Path(__file__).resolve()),'--project',str(project.root),'step',step])
    return {'accepted':True,'pid':p.pid,'note':'查看任务状态；Agent 类步骤需由当前 Agent 编排。'}


def agent_brief(project,step):
    from registry import fred_root,specs,status
    s=project.state();selection=s['workflow'][step];spec=next(x for x in specs() if x['id']==selection)
    availability=next(x for x in status() if x['id']==selection)
    check(availability['ready'],'；'.join(availability['reasons']),'dependency_missing')
    if selection.startswith('fredtalk'):
        instructions=fred_root()/'skills'/('audio-subtitle-roughcut' if step=='roughcut' else 'fred-remotion-output')/'SKILL.md'
    elif selection=='remotion-plugin':
        instructions=Path(__file__).resolve().parents[1]/'references/remotion-workflow.md'
    elif selection=='remotion-gold':
        instructions=Path(__file__).resolve().parents[1]/'references/gold-style.md'
    elif selection=='remotion-evidence':
        instructions=Path(__file__).resolve().parents[1]/'references/evidence-style.md'
    else:
        instructions=Path(spec['instructions']);check(file_hash(instructions)==spec['instructions_hash'],'第三方指令已变，请重新审阅注册。')
    return {'execution':'agent','instructions':str(instructions),'project':s,'source_revision':spec.get('source_revision'),
        'requirements':['当前用户原速、无额外增益、无 Fred 品牌及私人素材；用户要求优先。',
        '粗剪只提出候选并用 update 保存；页面确认前不执行。',
        '包装先提交候选和具体取舍；确认方向后制作真实 Remotion 片段及关键帧。',
        '每个片段用 attach-scene 导入工程/视频/关键帧，记录来源组件与实际验证；不冒称已听审。']}


def attach_scene(project,args):
    from media import import_file,probe,binary,run,display_size,overlay_geometry
    import shutil
    s=project.state();check(project.approved('packaging',s),'请先确认当前包装方向。','review_required')
    scene=next((x for x in s['scenes'] if x['id']==args.scene),None);check(scene,'场景不存在。')
    root=Path(args.code).resolve();check((root/'package.json').is_file() and (root/'package-lock.json').is_file(),'须提供锁定依赖的 Remotion 工程。')
    check((root/args.entry).resolve().is_relative_to(root) and (root/args.entry).is_file(),'工程入口无效。')
    check(args.component and args.source_revision,'缺少组件来源。')
    if s['workflow']['packaging']=='fredtalk-motion':
        check(args.manifest,'FredTalk 包装须提供实际通过门禁的 manifest。')
        report=fred_gate(args.manifest,'keyframes')
        check(report.get('status')=='PASS','FredTalk 关键帧门禁未通过。','gate_failed')
        manifest=json.loads(Path(args.manifest).read_text(encoding='utf-8'))
        check(any(p.get('stableId')==args.scene for p in manifest['pages']),'门禁范围未包含本场景。')
    output=import_file(project,args.video,'artifact');keyframe=import_file(project,args.keyframe,'keyframe')
    duration=float(probe(project.public_file(output['file']))['format']['duration'])
    check(abs(duration-(scene['end']-scene['start'])/s['speed'])<.15,'包装片段时长与场景不匹配。')
    permitted={'.tsx','.ts','.jsx','.js','.mjs','.cjs','.css','.json','.lock','.md','.html','.svg'}
    files=[]
    for f in root.rglob('*'):
        if any(part.startswith('.') or part in {'node_modules','out','private','data','credentials','models','deps','exports','media'} for part in f.relative_to(root).parts):continue
        if any((parent/'.talking-edit/state.sqlite3').exists() or (parent/'dependencies.json').exists() for parent in f.parents if parent!=root and parent.is_relative_to(root)):continue
        if f.is_file() and f.suffix in permitted:
            check(not f.is_symlink() and f.resolve().is_relative_to(root),'工程源码不能通过链接指向包外文件。')
            check(not any(x in f.name.lower() for x in ('credential','secret','session')),'工程含私密配置文件，拒绝导入。')
            text=f.read_text(encoding='utf-8-sig')
            import re
            check(not re.search(r'\b(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,})',text),'工程源码含疑似凭据，拒绝导入。')
            files.append((f,f.relative_to(root).as_posix(),file_hash(f)))
    code_hash=digest([(r,h) for _,r,h in files])
    code_dest=project.root/'work'/('remotion-'+digest([args.scene,code_hash])[:20])
    if not code_dest.exists():
        code_dest.mkdir()
        for f,rel,_ in files:
            dest=code_dest/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,dest)
    # User reviews an actual composition over their source, rather than an unrelated supplied poster.
    composite=project.root/'work'/('keyframe-'+digest([output['sha256'],scene,s['source']])[:24]+'.png')
    source=project.public_file(s['source']['file']);offset=min(.6,duration/2)
    info=next(x for x in probe(source)['streams'] if x['codec_type']=='video');w,h=display_size(info)
    scale=min(1,1920/max(w,h),1080/min(w,h));w=max(2,int(w*scale)//2*2);h=max(2,int(h*scale)//2*2)
    if scene.get('mode','overlay')=='fullscreen':
        run([binary('ffmpeg'),'-v','error','-y','-ss',str(offset),'-i',str(project.public_file(output['file'])),'-vf',f'scale={w}:{h}','-frames:v','1',str(composite)])
    else:
        sw,sh,x,y=overlay_geometry(scene,w,h)
        run([binary('ffmpeg'),'-v','error','-y','-ss',str(scene['start']+offset*s['speed']),'-i',str(source),'-ss',str(offset),'-i',str(project.public_file(output['file'])),'-filter_complex',f'[0:v]scale={w}:{h}[bg];[1:v]scale={sw}:{sh}[ov];[bg][ov]overlay={x}:{y}','-frames:v','1',str(composite)])
    scene.update(artifact=output['file'],artifact_hash=output['sha256'],artifact_speed=s['speed'],keyframe=composite.relative_to(project.root).as_posix(),reference_keyframe=keyframe['file'],
        code=code_dest.relative_to(project.root).as_posix(),code_hash=code_hash,component=args.component,source_revision=args.source_revision,
        timing_fingerprint=digest({'source':s['source'],'cuts':s['cuts'],'speed':s['speed']}))
    # Artifact attachment is implementation of already approved direction, not a change of direction.
    result=project.update({'scenes':s['scenes']},s['revision'])
    return result


def fred_gate(manifest,stage):
    from registry import fred_root,config
    script=fred_root()/'skills/fred-remotion-output/scripts/library_gate.py'
    check(script.is_file(),'缺少 FredTalk 门禁。')
    env=os.environ.copy()
    if config().get('node'):env['PATH']=str(Path(config()['node']).parent)+os.pathsep+env.get('PATH','')
    p=subprocess.run([sys.executable,'-X','utf8',str(script),'--manifest',str(Path(manifest).resolve()),'--stage',stage],cwd=fred_root(),capture_output=True,env=env)
    try:result=json.loads(p.stdout)
    except Exception:raise EditError('上游门禁无法执行；检查 Node 与组件依赖。','dependency_missing')
    check(p.returncode==0 and result.get('status')=='PASS','组件门禁未通过：'+'；'.join(result.get('errors',[])[:8]),'gate_failed')
    return result


def render_scene(project,args):
    from registry import config
    import shutil
    s=project.state();check(project.approved('packaging',s),'请先确认当前包装方向。','review_required')
    scene=next((x for x in s['scenes'] if x['id']==args.scene),None);check(scene,'场景不存在。')
    root=Path(args.code).resolve();package=root/'package.json';lock=root/'package-lock.json'
    check(package.is_file() and lock.is_file(),'需要已安装且锁定版本的 Remotion 工程。')
    dependencies=json.loads(package.read_text(encoding='utf-8-sig')).get('dependencies',{})
    import re
    version=dependencies.get('remotion','');check(re.fullmatch(r'\d+\.\d+\.\d+',version) and dependencies.get('@remotion/cli')==version,'Remotion 与 CLI 必须锁定同一精确版本。')
    node=os.environ.get('TALKING_EDIT_NODE') or config().get('node') or shutil.which('node');check(node,'缺少 Node.js。','dependency_missing')
    cli=root/'node_modules/@remotion/cli/remotion-cli.js';check(cli.is_file(),'请先安装本工程的锁定依赖。','dependency_missing')
    check((root/args.entry).is_file() and (root/args.entry).resolve().is_relative_to(root),'入口不在工程内。')
    if s['workflow']['packaging']=='fredtalk-motion':
        check(args.manifest,'FredTalk 渲染需当前建议门禁。');fred_gate(args.manifest,'suggestion')
    files=[]
    for f in root.rglob('*'):
        if not f.is_file() or f.is_symlink() or f.suffix not in {'.tsx','.ts','.jsx','.js','.json','.css'}:continue
        if any(x.startswith('.') or x in {'node_modules','out','private','data','credentials','models','deps','exports','media'} for x in f.relative_to(root).parts):continue
        if any((parent/'.talking-edit/state.sqlite3').exists() or (parent/'dependencies.json').exists() for parent in f.parents if parent!=root and parent.is_relative_to(root)):continue
        files.append((f.relative_to(root).as_posix(),file_hash(f)))
    generated={'artifact','artifact_hash','artifact_speed','keyframe','reference_keyframe','code','code_hash','component','source_revision','timing_fingerprint'}
    scene_plan={k:v for k,v in scene.items() if k not in generated}
    fp=digest({'scene':scene_plan,'files':files,'composition':args.composition,'timing':{'source':s['source'],'cuts':s['cuts'],'speed':s['speed']}})
    task,fresh=project.claim('scene',fp)
    if not fresh:return json.loads(task['result'])
    folder=project.root/'work'/('scene-'+task['id']);folder.mkdir()
    base=[str(node),str(cli)]
    browser=['--browser-executable='+args.browser] if args.browser else []
    try:
        from media import run
        run(base+['render',args.entry,args.composition,str(folder/'scene.mp4'),'--concurrency=1',*browser],cwd=root)
        run(base+['still',args.entry,args.composition,str(folder/'keyframe.png'),'--frame=1',*browser],cwd=root)
        result={'video':str(folder/'scene.mp4'),'keyframe':str(folder/'keyframe.png'),'code':str(root),'source_revision':version,'listeningReviewed':False}
        project.finish(task['id'],result);return result
    except Exception:
        project.finish(task['id'],{'note':'本地动态片段渲染失败，保留原任务及产物。'},'failed');raise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project')
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor');sub.add_parser('skills');sub.add_parser('show');sub.add_parser('stop-server');sub.add_parser('auto-gold-plan')
    p=sub.add_parser('create');p.add_argument('--title',default='口播剪辑项目')
    p=sub.add_parser('recover');p.add_argument('--resume',action='store_true')
    p=sub.add_parser('retry-local');p.add_argument('--task',required=True)
    p=sub.add_parser('update');p.add_argument('--input',required=True);p.add_argument('--revision',type=int,required=True)
    p=sub.add_parser('import');p.add_argument('--file',required=True);p.add_argument('--kind',required=True)
    p=sub.add_parser('review');p.add_argument('--stage',required=True);p.add_argument('--no-browser',action='store_true')
    p=sub.add_parser('wait');p.add_argument('--request',required=True);p.add_argument('--seconds',type=float,default=40)
    p=sub.add_parser('serve');p.add_argument('--idle-seconds',type=float,default=1800)
    p=sub.add_parser('step');p.add_argument('step',choices=['analyze','transcribe','render','roughcut','packaging'])
    sub.add_parser('batch-list');sub.add_parser('batch-run')
    p=sub.add_parser('batch-create');p.add_argument('--title',required=True);p.add_argument('--packaging',required=True);p.add_argument('--speed',type=float,default=1);p.add_argument('--mode',choices=['manual','auto'],default='manual')
    p=sub.add_parser('batch-add');p.add_argument('--batch',required=True);p.add_argument('--file',required=True)
    p=sub.add_parser('batch-enqueue');p.add_argument('--item',required=True);p.add_argument('--step',required=True,choices=['transcribe','analyze','render','auto'])
    p=sub.add_parser('batch-open');p.add_argument('--item',required=True);p.add_argument('--stage',default='project');p.add_argument('--no-browser',action='store_true')
    p=sub.add_parser('prepare-deps');p.add_argument('dependency',choices=['fredtalk','whisper']);p.add_argument('--download-model',action='store_true');p.add_argument('--path');p.add_argument('--python')
    p=sub.add_parser('register');p.add_argument('--input',required=True)
    p=sub.add_parser('configure-runtime');p.add_argument('--ffmpeg',required=True);p.add_argument('--ffprobe',required=True);p.add_argument('--node')
    p=sub.add_parser('catalog');p.add_argument('--query',required=True)
    p=sub.add_parser('fred-gate');p.add_argument('--manifest',required=True);p.add_argument('--stage',choices=['suggestion','keyframes'],required=True)
    p=sub.add_parser('render-scene');p.add_argument('--scene',required=True);p.add_argument('--code',required=True);p.add_argument('--entry',required=True);p.add_argument('--composition',required=True);p.add_argument('--manifest');p.add_argument('--browser')
    p=sub.add_parser('verify-price');p.add_argument('--input',required=True)
    p=sub.add_parser('attach-scene');p.add_argument('--scene',required=True);p.add_argument('--video',required=True);p.add_argument('--keyframe',required=True);p.add_argument('--code',required=True);p.add_argument('--entry',required=True);p.add_argument('--component',required=True);p.add_argument('--source-revision',required=True);p.add_argument('--manifest')
    a=parser.parse_args()
    try:
        from registry import status,prepare_fred,prepare_whisper,register,fred_root
        from media import binary,import_file,analyze,render
        if a.command=='doctor':
            result={'version':VERSION,'python':sys.version.split()[0],'home':str(home()),'skills':status()}
            for name in ('ffmpeg','ffprobe'):
                try:result[name]=binary(name)
                except EditError:result[name]=None
        elif a.command=='skills':result=status()
        elif a.command=='prepare-deps':result=prepare_fred(a.path) if a.dependency=='fredtalk' else prepare_whisper(a.download_model,a.python)
        elif a.command=='register':result=register(a.input)
        elif a.command=='fred-gate':result=fred_gate(a.manifest,a.stage)
        elif a.command=='configure-runtime':
            from registry import config
            data=config()
            for key in ('ffmpeg','ffprobe','node'):
                if not getattr(a,key):continue
                path=Path(getattr(a,key)).resolve();check(path.is_file(),'媒体程序不存在。');data[key]=str(path)
            atomic(home()/'dependencies.json',data);result={'configured':True}
        elif a.command=='verify-price':
            from providers import MODEL
            from urllib.parse import urlparse
            value=json.loads(Path(a.input).read_text(encoding='utf-8-sig'))
            check(value['model']==MODEL and value['cny_per_second']>0 and value['round_seconds']>=1,'价格字段无效。')
            check(urlparse(value['source_url']).hostname in ('help.aliyun.com','www.alibabacloud.com'),'须提供官方价格来源。')
            check(isinstance(value['verified_at'],(int,float)) and 0<=time.time()-value['verified_at']<86400,'核对时间无效。')
            atomic(home()/'cloud-pricing.json',value);result={'saved':True,'note':'须先实际核对该官方来源，不能把填写费率当作已核验。'}
        elif a.command=='catalog':
            script=fred_root()/'scripts/catalog.py';check(script.is_file(),'请先准备 FredTalk。')
            p=subprocess.run([sys.executable,'-X','utf8',str(script),'--query',a.query,'--limit','5'],cwd=fred_root(),capture_output=True)
            check(p.returncode==0,'组件检索失败。');result={'output':p.stdout.decode('utf-8',errors='replace'),'note':'候选仍须核对源码、素材和执行依赖。'}
        else:
            check(a.project,'请提供 --project 绝对路径。')
            project=Project.create(a.project,a.title) if a.command=='create' else Project(a.project)
            if a.command in ('show','create'):result=project.state()
            elif a.command=='auto-gold-plan':
                from auto_gold import propose
                result={'scenes':propose(project.state()),'note':'仅生成候选，不代表动画已制作或成片已完成。'}
            elif a.command=='recover':result=project.recover(a.resume)
            elif a.command=='retry-local':result=project.retry_local(a.task)
            elif a.command=='update':result=project.update(json.loads(Path(a.input).read_text(encoding='utf-8-sig')),a.revision)
            elif a.command=='import':result=import_file(project,a.file,a.kind)
            elif a.command=='review':result=review(project,a.stage,not a.no_browser)
            elif a.command=='wait':result=wait(project,a.request,a.seconds)
            elif a.command.startswith('batch-'):
                from batch import Batch
                b=Batch(project)
                if a.command=='batch-list':result=b.list()
                elif a.command=='batch-create':result=b.create(a.title,a.packaging,a.speed,a.mode)
                elif a.command=='batch-add':result=b.add_file(a.batch,a.file,Path(a.file).name)
                elif a.command=='batch-enqueue':result=b.enqueue(a.item,a.step)
                elif a.command=='batch-open':result=review(Project(b.item(a.item)['project_path']),a.stage,not a.no_browser)
                else:
                    completed=[]
                    while True:
                        x=b.execute_next()
                        if x['status'] in ('idle','busy','interrupted'):result={'jobs':completed,'state':x};break
                        completed.append({'job_id':x['job_id'],'status':x['status']})
            elif a.command=='serve':
                from web import serve
                serve(project,a.idle_seconds);result={'stopped':True}
            elif a.command=='step':
                if a.step=='analyze':result=analyze(project)
                elif a.step=='render':result=render(project)
                elif a.step=='transcribe':
                    from providers import transcribe
                    result=transcribe(project)
                else:result=agent_brief(project,a.step)
            elif a.command=='attach-scene':result=attach_scene(project,a)
            elif a.command=='render-scene':result=render_scene(project,a)
            elif a.command=='stop-server':
                d=session(project)
                if d:
                    req=urllib.request.Request(d['origin']+'/api/stop',b'{}',headers={'X-Talking-Session':d['session'],'Origin':d['origin'],'Content-Type':'application/json'})
                    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req,timeout=3) as r:json.load(r)
                result={'stopped':True}
        output={'ok':True,'result':result}
        if a.command=='step':atomic(project.meta/'last-command.json',output)
        print(dumps(output))
    except EditError as e:
        output={'ok':False,'error':e.code,'message':str(e)}
        if a.command=='step':atomic(project.meta/'last-command.json',output)
        print(dumps(output));sys.exit(1)
    except Exception:
        output={'ok':False,'error':'execution_failed','message':'执行失败；请核查依赖及原项目任务，不自动重试未知提交。'}
        if a.command=='step':atomic(project.meta/'last-command.json',output)
        print(dumps(output));sys.exit(1)


if __name__=='__main__':main()
