"""Snapshot-only bridge; SQLite stays authoritative and upstream server is never exposed."""
import json
import shutil
import sys
from core import atomic,digest,check
from registry import fred_root,FRED_REVISION
from media import binary,extract_audio,run,srt_text


def roughcut(project,state):
    upstream=fred_root()/'skills/audio-subtitle-roughcut/assets/review-app/server.py'
    check(upstream.is_file(),'请先准备固定版 FredTalk。','dependency_missing')
    identity=digest({'source':state['source'],'cues':state['cues'],'cuts':state['cuts'],'fred':FRED_REVISION,'clock':'video-duration-v3'})
    root=project.root/'work'/('fred-roughcut-'+identity)
    receipt=root/'bridge-result.json'
    if receipt.exists():return json.loads(receipt.read_text(encoding='utf-8'))
    root.mkdir(parents=True,exist_ok=True)
    source=extract_audio(project)
    normalized=project.root/'work'/('fred-source-video-clock-v3-'+state['source']['sha256'][:20]+'.wav')
    if not normalized.exists():
        # Full-band source, no gain or speed. The ASR 16k mono extraction is not used as delivery master.
        run([binary('ffmpeg'),'-v','error','-y','-i',str(project.public_file(state['source']['file'])),'-vn','-af',f"aresample=async=1:first_pts=0,apad=whole_dur={state['duration']},atrim=duration={state['duration']}",'-t',str(state['duration']),'-ar','48000','-ac','2','-c:a','pcm_s16le',str(normalized)])
    shutil.copyfile(upstream,root/'server.py')
    subs=root/'source.srt';subs.write_text(srt_text(state['cues']),encoding='utf-8')
    script=root/'script.md';script.write_text(state['script'],encoding='utf-8')
    atomic(root/'project.json',dict(episode=str(project.root),sourceAudio=str(normalized),sourceSubtitles=str(subs),script=str(script),title=state['title'],filenameStem='talking-edit',episodeKey=state['project_id']))
    atomic(root/'cuts.json',state['cuts'])
    for name in ('subtitle-corrections','subtitle-boundaries','subtitle-sentences'):
        atomic(root/(name+'.json'),[])
    for name in ('subtitle-edits','subtitle-sentence-edits','subtitle-joins'):
        atomic(root/(name+'.json'),{})
    import subprocess
    result=subprocess.run([sys.executable,'-X','utf8',str(__import__('pathlib').Path(__file__).with_name('fred_worker.py')),str(root)],capture_output=True)
    check(result.returncode==0,'FredTalk 粗剪执行失败，请检查输入与上游依赖。','fredtalk_failed')
    data=json.loads(result.stdout);atomic(receipt,data)
    return data
