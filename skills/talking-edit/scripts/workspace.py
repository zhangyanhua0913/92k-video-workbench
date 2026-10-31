"""Navigation/catalog separation; choosing an area never approves or submits work."""
from pathlib import Path
import json,os,subprocess,sys
from core import check,atomic

AREAS={'talk':'口播视频剪辑','generate':'视频生成','hybrid':'真人混搭风格'}
BUILTIN={'fredtalk-motion':['talk'],'remotion-plugin':['talk','hybrid'],
         'narration-footage-v0-1':['talk','hybrid'],'remotion-gold':['talk'],'remotion-evidence':['talk','hybrid'],'none':['talk','hybrid']}

def categories(spec):
    if spec['id'] in BUILTIN:return BUILTIN[spec['id']]
    return spec.get('workspace_categories',[])

def choose(project,area):
    check(area in AREAS,'请选择有效功能区。')
    atomic(project.meta/'workspace.json',{'area':area})
    return {'area':area,'note':'仅切换功能入口，不修改制作方案或批准执行。'}

def open_generation(project):
    skill=Path(__file__).resolve().parents[2]/'92k-video-director/scripts/director.py'
    if not skill.is_file():
        skill=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))/'skills/92k-video-director/scripts/director.py'
    check(skill.is_file(),'未安装92k-video-director，请由Agent先安装。','dependency_missing')
    root=project.root/'generation';manifest=project.meta/'generation-entry.json'
    def call(args):
        r=subprocess.run([sys.executable,'-X','utf8',str(skill),'--project',str(root),*args],capture_output=True,encoding='utf-8',timeout=25)
        check(r.returncode==0,'视频生成工作区打开失败，请由Agent恢复原项目。')
        data=json.loads(r.stdout);check(data.get('ok'),'生成工作区暂不可用。');return data['result']
    # A single persisted child directory; never overwrite or replace an existing project.
    if not (root/'.director/state.sqlite3').exists():
        # Let the director's own existence check protect an existing project.
        probe=root/'project.json'
        if not probe.exists():
            atomic(manifest,{'title':project.state()['title']+' · 视频生成','script':'','shots':[]})
            call(['create','--input',str(manifest)])
    return call(['review','--stage','storyboard','--no-browser'])
