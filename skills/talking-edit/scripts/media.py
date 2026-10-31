"""FFmpeg execution and one source-to-output clock shared by sound, image and cues."""
import array
import json
import math
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path
from core import Project, EditError, check, digest, file_hash, atomic,validate


def binary(name):
    from registry import config
    p = os.environ.get('TALKING_EDIT_' + name.upper()) or config().get(name) or shutil.which(name)
    check(p and Path(p).is_file(), '缺少 ' + name + '；请设置 TALKING_EDIT_' + name.upper(), 'dependency_missing')
    return str(p)


def run(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    check(p.returncode == 0, '媒体执行失败，请核对输入格式和依赖。', 'media_failed')
    return p.stdout


def probe(path):
    return json.loads(run([binary('ffprobe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)]))


def display_size(stream):
    rotation=next((x['rotation'] for x in stream.get('side_data_list',[]) if 'rotation' in x),stream.get('tags',{}).get('rotate',0))
    w,h=stream['width'],stream['height']
    if round(float(rotation)/90)%2:w,h=h,w
    return w,h


def parse_srt(text):
    result = []
    for block in re.split(r'\r?\n\s*\r?\n', text.strip().lstrip('\ufeff')):
        lines = block.splitlines()
        at = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if at is None:
            continue
        matches = re.findall(r'(\d{2,}):(\d{2}):(\d{2})[,.](\d{3})', lines[at])
        check(len(matches) == 2, 'SRT 时间格式无效。')
        times = [int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000 for h,m,s,ms in matches]
        result.append(dict(id='cue-' + str(len(result)+1), start=times[0], end=times[1], text='\n'.join(lines[at+1:])))
    check(result, '没有找到有效字幕。')
    return result


def stamp(t):
    n = round(t * 1000)
    return f'{n//3600000:02}:{n//60000%60:02}:{n//1000%60:02},{n%1000:03}'


def srt_text(cues):
    return '\n\n'.join(f'{i}\n{stamp(c["start"])} --> {stamp(c["end"])}\n{c["text"]}' for i,c in enumerate(cues,1)) + '\n'


def intervals(duration, cuts, speed=1):
    merged = []
    for a,b in sorted((c['start'], c['end']) for c in cuts if c['enabled']):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a,b])
    kept, last, out = [], 0, 0
    for a,b in merged + [[duration,duration]]:
        if a > last + .00001:
            length = (a-last)/speed
            kept.append(dict(source_start=last, source_end=a, output_start=out, output_end=out+length))
            out += length
        last = max(last,b)
    check(kept, '不能删除全部内容。')
    return kept


def map_cues(cues, mapping, speed=1):
    result, warnings = [], []
    for cue in cues:
        pieces = []
        for segment in mapping:
            a = max(cue['start'], segment['source_start']); b = min(cue['end'], segment['source_end'])
            if b > a + .001:
                pieces.append(dict(id=cue['id'], text=cue['text'],
                    start=segment['output_start']+(a-segment['source_start'])/speed,
                    end=segment['output_start']+(b-segment['source_start'])/speed))
        if pieces:
            # A partial sentence needs text review; never invent a word-level cut.
            if sum((p['end']-p['start'])*speed for p in pieces) < cue['end']-cue['start']-.01:
                warnings.append({'cue': cue['id'], 'reason': '句内剪切：请核对剩余字幕文字与字头尾音。'})
            result.append(dict(pieces[0], end=pieces[-1]['end']))
    return result, warnings


def import_file(project, path, kind, revision=None):
    src = Path(path).resolve()
    check(src.is_file() and kind in ('video','subtitles','script','image','artifact','keyframe','music'), '导入文件不存在或类型无效。')
    if kind in ('subtitles','script'):check(src.stat().st_size<=8*1024**2,'文稿或字幕不能超过8MB。')
    permitted = {'video': ('.mp4','.mov','.webm','.mkv'), 'subtitles': ('.srt',), 'script': ('.txt','.md'),
                 'image': ('.png','.jpg','.jpeg'), 'artifact': ('.mp4','.webm'), 'keyframe': ('.png','.jpg'),'music':('.wav','.mp3','.m4a','.flac')}
    check(src.suffix.lower() in permitted[kind], '文件扩展名与类型不符。')
    h = file_hash(src)
    dest = project.root / 'media' / (h[:20] + src.suffix.lower())
    if not dest.exists():
        shutil.copyfile(src, dest)
    if kind in ('artifact','keyframe','image','music'):
        if kind=='music':check(any(x['codec_type']=='audio' for x in probe(dest)['streams']),'配乐文件须含有效音轨。')
        return {'file': dest.relative_to(project.root).as_posix(), 'sha256': h}
    with project.db() as c:
        s = project.state(c)
        check(revision is None or revision==s['revision'],'上传期间项目版本已变，请重新导入。','stale_revision',409)
        check(not c.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(), '任务运行中。', 'busy', 409)
        if kind == 'video':
            info = probe(dest)
            check(any(x['codec_type']=='video' for x in info['streams']) and any(x['codec_type']=='audio' for x in info['streams']), '口播视频须含视频及音轨。')
            check(not s['source'] or s['source']['sha256'] == h, '首版更换源视频请创建新项目，保护原剪辑。')
            s['source'] = {'file': dest.relative_to(project.root).as_posix(), 'sha256': h}
            s['duration'] = float(info['format']['duration'])
        elif kind == 'subtitles':
            check(s['source'], '请先导入视频。')
            s['cues'] = parse_srt(src.read_text(encoding='utf-8-sig'))
            check(all(0 <= x['start'] < x['end'] <= s['duration']+.002 for x in s['cues']), '字幕超出源视频时长。')
        else:
            s['script'] = src.read_text(encoding='utf-8-sig')
        project._save(c, validate(s))
    project.export()
    return project.state()


def extract_audio(project):
    s = project.state(); check(s['source'], '请导入视频。')
    source = project.public_file(s['source']['file'])
    check(file_hash(source) == s['source']['sha256'], '源视频已被外部修改。', 'source_changed')
    out = project.root / 'work' / (s['source']['sha256'][:20] + '-source-clock-v3.wav')
    if not out.exists():
        temp = out.with_suffix('.'+uuid.uuid4().hex+'.tmp.wav')
        run([binary('ffmpeg'),'-v','error','-y','-i',str(source),'-vn','-af',f"aresample=async=1:first_pts=0,apad=whole_dur={s['duration']},atrim=duration={s['duration']}",'-t',str(s['duration']),'-ac','1','-ar','16000','-c:a','pcm_s16le',str(temp)])
        os.replace(temp,out)
    return out


def waveform(project):
    import wave
    src = extract_audio(project)
    with wave.open(str(src),'rb') as w:
        data = array.array('h',w.readframes(w.getnframes()))
        rate = w.getframerate()
    size = max(1,math.ceil(len(data)/1200))
    peaks = [max(abs(x) for x in data[i:i+size])/32768 for i in range(0,len(data),size)]
    return {'duration': len(data)/rate, 'peaks': peaks}


def speed_advice(state):
    """Transparent local heuristic over retained captions, never an automatic edit."""
    if not state.get('source') or not state.get('cues'):
        return {'available':False,'reason':'请先导入视频及字幕，再估算建议语速。'}
    mapping=intervals(state['duration'],state['cuts'],1)
    cues,_=map_cues(state['cues'],mapping,1)
    duration=mapping[-1]['output_end']
    characters=sum(len(re.findall(r'[\u4e00-\u9fff]|[A-Za-z0-9]+',x['text'])) for x in cues)
    coverage=sum(x['end']-x['start'] for x in cues)
    rate=characters/max(duration,.01)
    # Product heuristic, not a claim about a universal ideal speaking rate.
    target=5.5
    desired=max(1,min(1.25,target/max(rate,.01)))
    options=[1,1.1,1.15,1.2,1.25,1.3,1.5]
    suggested=min(options[:-1],key=lambda v:abs(v-desired))
    return {'available':True,'suggested':suggested,'characters':characters,'retained_seconds':round(duration,3),
        'characters_per_minute':round(rate*60),'caption_gap_ratio':round(max(0,1-coverage/max(duration,.01)),3),
        'options':[{'speed':v,'seconds':round(duration/v,1)} for v in options],
        'reason':f'按保留字幕约 {characters} 个中文字符/英文词、原速约 {rate*60:.0f} 字词/分钟估算；以5.5字词/秒作为本工具可试听的节奏目标，自动建议最高1.25倍。',
        'limitations':'字幕字数和时间间隙只是估算，不等于声学停顿识别；漏字、字幕时码及语言会影响结果。最终按试听选择，不自动改速。'}


def analyze(project):
    """Agent still judges semantic mistakes; deterministic tools only suggest pauses/repeats."""
    s = project.state(); audio = extract_audio(project)
    p = subprocess.run([binary('ffmpeg'),'-hide_banner','-i',str(audio),'-af','silencedetect=noise=-38dB:d=0.9','-f','null','-'], capture_output=True)
    check(p.returncode == 0, '停顿检测失败。', 'media_failed')
    text = p.stderr.decode('utf-8',errors='replace')
    starts = re.findall(r'silence_start: ([\d.]+)',text); ends = re.findall(r'silence_end: ([\d.]+)',text)
    candidates = []
    for a,b in zip(starts,ends):
        a,b=float(a)+.15,float(b)-.15
        if b>a:
            candidates.append(dict(id='pause-'+digest([a,b])[:12],start=a,end=b, enabled=False, reason='长低电平区候选，须试听，不能据此判断没有语音。', reviewed=False))
    for prev,cur in zip(s['cues'],s['cues'][1:]):
        if prev['text'].strip() == cur['text'].strip():
            candidates.append(dict(id='repeat-'+prev['id'],start=prev['start'],end=prev['end'],enabled=False,reason='相邻字幕重复，可能是识别错误；须核对实际声音。',reviewed=False))
    existing = {x['id'] for x in s['cuts']}
    return project.update({'cuts': s['cuts']+[x for x in candidates if x['id'] not in existing]}, s['revision'])


def preview_seam(project, cut_id, revision):
    s=project.state();check(s['revision']==revision,'页面已过期。','stale_revision',409)
    cut=next((x for x in s['cuts'] if x['id']==cut_id),None);check(cut,'剪切不存在，请先保存候选。')
    source=project.public_file(s['source']['file'])
    a,b=max(0,cut['start']-.8),min(s['duration'],cut['end']+.8)
    check(cut['start']>a and b>cut['end'],'片头或片尾剪切请用原片试听。')
    out=project.root/'work'/('seam-'+digest([s['source'],cut])[:24]+'.mp4')
    if not out.exists():
        run([binary('ffmpeg'),'-v','error','-y','-i',str(source),'-filter_complex',
            f"[0:v]trim=start={a}:end={cut['start']},setpts=PTS-STARTPTS[v0];[0:a]atrim=start={a}:end={cut['start']},asetpts=PTS-STARTPTS[a0];[0:v]trim=start={cut['end']}:end={b},setpts=PTS-STARTPTS[v1];[0:a]atrim=start={cut['end']}:end={b},asetpts=PTS-STARTPTS[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
            '-map','[v]','-map','[a]','-c:v','libx264','-preset','fast','-c:a','aac',str(out)])
    return {'file':out.relative_to(project.root).as_posix(),'note':'实际剪去区间后的接缝预览；确认仍由用户完成。'}


def overlay_geometry(scene,w,h):
    if scene.get('mode','overlay')=='fullscreen':return w,h,0,0
    box=scene.get('layout',{'x':.49,'y':.02,'width':.5})
    return max(2,int(w*box['width'])//2*2),-2,round(w*box['x']),round(h*box['y'])


def render(project):
    s = project.state(); check(s['source'], '缺少视频。')
    check(project.approved('roughcut',s), '请在页面确认当前粗剪方案。', 'review_required')
    check(s['workflow']['packaging']=='none' or s['scenes'], '已选择动态包装，但尚无动画方案；请完成包装，或在流程配置明确选择不添加动态包装。', 'packaging_incomplete')
    if s['scenes'] or s.get('music'):
        check(project.approved('packaging',s), '请确认当前动画与配乐方向。', 'review_required')
    if s['scenes']:
        check(project.approved('keyframes',s), '请确认实际关键帧。', 'review_required')
    source = project.public_file(s['source']['file'])
    check(file_hash(source)==s['source']['sha256'], '源视频已改变。')
    fingerprint = project.fingerprint('final',s)
    task, fresh = project.claim('render', fingerprint)
    if not fresh:
        previous=json.loads(task['result'])
        check(file_hash(project.public_file(previous['file']))==previous['sha256'],'原成片已变化，不能复用旧验收。','artifact_changed')
        return previous
    folder = project.root / 'exports' / task['id']; folder.mkdir()
    try:
        mapping = intervals(s['duration'],s['cuts'],s['speed'])
        fred_result=None
        if s['workflow']['roughcut']=='fredtalk-roughcut':
            from fred_bridge import roughcut
            fred_result=roughcut(project,s)
            # The upstream sample-rounded spans become the same clock for video and subtitles.
            mapping=[];offset=0
            for a,b in fred_result['retained_spans']:
                length=(b-a)/s['speed'];mapping.append(dict(source_start=a,source_end=b,output_start=offset,output_end=offset+length));offset+=length
        cues, warnings = map_cues(s['cues'],mapping,s['speed'])
        (folder/'captions.srt').write_text(srt_text(cues),encoding='utf-8')
        info = probe(source); video=next(x for x in info['streams'] if x['codec_type']=='video')
        w,h=display_size(video); scale=min(1,1920/max(w,h),1080/min(w,h)); w=max(2,int(w*scale)//2*2); h=max(2,int(h*scale)//2*2)
        num,den=map(int,video.get('avg_frame_rate','30/1').split('/')); fps=min(30,num/den if den else 30)
        rough=folder/'rough.mp4'
        videoid=digest({'source':s['source'],'mapping':mapping,'speed':s['speed'],'size':[w,h],'fps':fps,'engine':'source-clock-video-v3','audio':not bool(fred_result)})
        cached=project.root/'work'/('rough-'+videoid+'.mp4');cachemeta=cached.with_suffix('.json')
        if cached.exists() and cachemeta.exists() and file_hash(cached)==json.loads(cachemeta.read_text())['sha256']:
            shutil.copyfile(cached,rough)
        if not rough.exists() and fred_result:
            # Map each original video timestamp directly; avoid accumulating per-segment AAC/frame padding.
            removed=[];end=0
            for m in mapping:
                if m['source_start']>end:removed.append((end,m['source_start']))
                end=m['source_end']
            if end<s['duration']:removed.append((end,s['duration']))
            excluded='+'.join(f'(gte(t,{a})*lt(t,{b}))' for a,b in removed) or '0'
            elapsed='+'.join(f'(gte(PTS*TB,{b})*{b-a})' for a,b in removed) or '0'
            vf=f"select='not({excluded})',setpts='(PTS-({elapsed})/TB)/{s['speed']}',scale={w}:{h},fps={fps}:start_time=0,setsar=1"
            run([binary('ffmpeg'),'-v','error','-y','-i',str(source),'-vf',vf,'-an','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p',str(rough)])
        elif not rough.exists():
            segments=[]
            for i,m in enumerate(mapping):
                segment=folder/f'part-{i}.mp4'
                run([binary('ffmpeg'),'-v','error','-y','-i',str(source),'-filter_complex',
                    f"[0:v]trim=start={m['source_start']}:end={m['source_end']},setpts=(PTS-STARTPTS)/{s['speed']},scale={w}:{h},fps={fps},setsar=1[v];[0:a]atrim=start={m['source_start']}:end={m['source_end']},asetpts=PTS-STARTPTS,atempo={s['speed']}[a]",
                    '-map','[v]','-map','[a]','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-ar','48000',str(segment)])
                segments.append(segment)
            (folder/'concat.txt').write_text('\n'.join("file '"+p.name+"'" for p in segments),encoding='utf-8')
            run([binary('ffmpeg'),'-v','error','-y','-f','concat','-safe','1','-i','concat.txt','-c','copy','rough.mp4'],cwd=folder)
        if not cached.exists():
            shutil.copyfile(rough,cached);atomic(cachemeta,{'sha256':file_hash(cached),'video_fingerprint':videoid})
        current=rough
        scene_args=[];filters=[];last='0:v'
        for idx,scene in enumerate(s['scenes']):
            check(scene.get('artifact') and scene.get('artifact_hash'), '动态片段缺少实际产物。')
            artifact=project.public_file(scene['artifact'])
            check(file_hash(artifact)==scene['artifact_hash'], '包装视频发生变化，请重新采纳。')
            artifact_speed=scene.get('artifact_speed',1)
            check(scene.get('timing_fingerprint') == digest({'source':s['source'],'cuts':s['cuts'],'speed':artifact_speed}), '剪切已变，包装需重新对齐。')
            # Scene clocks are source clocks; only uncut, contiguous scenes can be overlaid.
            containing=next((m for m in mapping if m['source_start']<=scene['start'] and scene['end']<=m['source_end']),None)
            check(containing, '包装跨越剪切点，请先拆为连续片段。')
            start=containing['output_start']+(scene['start']-containing['source_start'])/s['speed']
            end=start+(scene['end']-scene['start'])/s['speed']
            mode=scene.get('mode','overlay')
            check(mode in ('overlay','fullscreen'),'包装模式无效。')
            sw,sh,x,y=overlay_geometry(scene,w,h)
            scene_args+=['-i',str(artifact)]
            # Every animation is processed in one pass; fades avoid rectangular flashes at entrances.
            length=end-start;fade=min(.22,length/4)
            filters.append(f"[{idx+1}:v]scale={sw}:{sh},format=rgba,setpts=(PTS-STARTPTS)*{artifact_speed/s['speed']},fade=t=in:st=0:d={fade}:alpha=1,fade=t=out:st={length-fade}:d={fade}:alpha=1,setpts=PTS+{start}/TB[ov{idx}]")
            filters.append(f"[{last}][ov{idx}]overlay=x={x}:y={y}:eof_action=pass:enable='between(t,{start},{end})'[p{idx}]")
            last=f'p{idx}'
        if filters:
            current=folder/'packed.mp4'
            run([binary('ffmpeg'),'-v','error','-y','-filter_complex_threads','1','-i',str(rough),*scene_args,'-filter_complex',';'.join(filters),'-map',f'[{last}]','-map','0:a?','-c:v','libx264','-preset','fast','-crf','20','-c:a','copy',str(current)])
        output=folder/'film.mp4'
        args=[binary('ffmpeg'),'-v','error','-y','-i',str(current)]
        music=s.get('music');audio_index=1 if fred_result else 0
        if fred_result:
            master=Path(fred_result['path'])/'review-cut.wav'
            args+=['-i',str(master)]
        if music:
            musicfile=project.public_file(music['file']);check(file_hash(musicfile)==music['sha256'],'配乐文件已变，请重新采纳。')
            total=mapping[-1]['output_end'];fade=music.get('fade_seconds',2)
            args+=['-stream_loop','-1','-i',str(musicfile)]
            voice=f'[{audio_index}:a]'+('atempo='+str(s['speed'])+',' if fred_result else '')+'aresample=48000,asplit=2[voice][side]'
            graph=f"{voice};[{audio_index+1}:a]aresample=48000,atrim=duration={total},asetpts=PTS-STARTPTS,volume={music['gain_db']}dB,afade=t=in:d={fade},afade=t=out:st={max(0,total-fade)}:d={fade}[bgm];[bgm][side]sidechaincompress=threshold=0.025:ratio=5:attack=30:release=500[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95:level=0[mix]"
            args+=['-filter_complex',graph,'-map','0:v','-map','[mix]']
        elif fred_result:
            args+=['-map','0:v','-map','1:a','-af','atempo='+str(s['speed'])]
        if s['subtitle_burn'] and cues:
            args += ['-vf',"subtitles=captions.srt:force_style='FontName=Microsoft YaHei,FontSize=20,Outline=1,MarginV=24'",'-c:v','libx264','-preset','fast','-crf','20']
        else:
            args += ['-c:v','copy']
        run(args+['-c:a','aac' if fred_result or music else 'copy','-movflags','+faststart','film.mp4'],cwd=folder)
        run([binary('ffmpeg'),'-v','error','-i',str(output),'-f','null','-'])
        final_info=probe(output); duration=float(final_info['format']['duration'])
        check(abs(duration-mapping[-1]['output_end'])<.15, '导出时长与时间映射不一致。')
        check(all(0<=x['start']<x['end']<=duration+.03 for x in cues), '导出字幕越界。')
        result=dict(file=output.relative_to(project.root).as_posix(), subtitles=(folder/'captions.srt').relative_to(project.root).as_posix(),
            duration=duration, width=w,height=h,fps=fps,speed=s['speed'], mapping=mapping, warnings=warnings, technicalPass=True,
            listeningReviewed=False, userConfirmedAtRender=False, revision=s['revision'], sha256=file_hash(output),manifest=(folder/'manifest.json').relative_to(project.root).as_posix(),music=music,animation_count=len(s['scenes']))
        atomic(folder/'manifest.json',result)
        # Preserve shared audio independently; subtitle-only changes reuse the same PCM file.
        audioid=digest({'source':s['source'],'cuts':s['cuts'],'speed':s['speed'],'engine':'video-clock-fred-pcm-v2'})
        audio=project.root/'work'/('edited-'+audioid+'.wav')
        if not audio.exists():
            if fred_result and s['speed']==1:
                shutil.copyfile(Path(fred_result['path'])/'review-cut.wav',audio)
            elif fred_result:
                run([binary('ffmpeg'),'-v','error','-y','-i',str(Path(fred_result['path'])/'review-cut.wav'),'-af','atempo='+str(s['speed']),'-c:a','pcm_s16le',str(audio)])
            else:
                run([binary('ffmpeg'),'-v','error','-y','-i',str(rough),'-vn','-c:a','pcm_s16le',str(audio)])
        result['audio']=audio.relative_to(project.root).as_posix(); result['audio_sha256']=file_hash(audio)
        result['source_packages']=[]
        for scene in s['scenes']:
            code=(project.root/scene['code']).resolve()
            check(code.is_relative_to(project.root/'work') and code.is_dir(),'包装工程目录无效。')
            archive=folder/('remotion-'+digest(scene['id'])[:12])
            shutil.make_archive(str(archive),'zip',code)
            result['source_packages'].append(archive.with_suffix('.zip').relative_to(project.root).as_posix())
        atomic(folder/'manifest.json',result)
        project.finish(task['id'],result)
        return result
    except Exception as e:
        project.finish(task['id'],{'code':getattr(e,'code','execution_failed'),'note':'保留中间产物；核查后显式处理原任务。'},'failed')
        raise
