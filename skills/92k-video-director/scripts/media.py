"""Deterministic local editing: preserve speech, sentence captions, no cloud calls."""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from core import check, dump, DirectorError, shot_hash, digest


def executable(name):
    value = os.environ.get('DIRECTOR_' + name.upper()) or shutil.which(name)
    check(value and Path(value).is_file(), '缺少' + name + '；请安装并加入PATH，或设置DIRECTOR_' + name.upper() + '为可执行文件路径。', 'dependency_missing')
    return str(value)


def run(arguments, cwd=None, timeout=1800):
    try:
        result = subprocess.run(arguments, cwd=cwd, capture_output=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    except subprocess.TimeoutExpired:
        raise DirectorError('本地媒体处理超时，原素材保留。', 'render_timeout') from None
    check(result.returncode == 0, '本地媒体处理失败：' + result.stderr.decode('utf-8', errors='replace')[-1800:], 'media_failed')
    return result.stdout


def probe(path):
    raw = run([executable('ffprobe'), '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format', '-show_streams', '-of', 'json', str(path)], timeout=30)
    data = json.loads(raw)
    check(data.get('streams'), '素材没有可读取的媒体轨道。')
    return data


def doctor():
    results = {'python': sys.version.split()[0], 'supported_python': sys.version_info >= (3, 10), 'windows_dpapi': os.name == 'nt'}
    for name in ('ffmpeg', 'ffprobe'):
        try:
            path = executable(name)
            results[name] = {'available': True, 'path': path, 'version': run([path, '-version'], timeout=10).decode(errors='replace').splitlines()[0]}
        except DirectorError as error:
            results[name] = {'available': False, 'notice': str(error)}
    return results


def duration(data):
    return float(data.get('format', {}).get('duration') or max(float(s.get('duration', 0)) for s in data['streams']))


def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    h, remain = divmod(milliseconds, 3600000)
    m, remain = divmod(remain, 60000)
    s, ms = divmod(remain, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def caption_lines(text):
    """Keep Chinese punctuation at the end of a line instead of isolated at its start."""
    lines = []
    for paragraph in text.splitlines():
        while len(paragraph) > 12:
            stops = [i + 1 for i, char in enumerate(paragraph[:12]) if char in '，。！？；、' and i >= 4]
            stop = stops[-1] if stops else 12
            if len(paragraph) > stop and paragraph[stop] in '，。！？；、':
                stop += 1
            lines.append(paragraph[:stop])
            paragraph = paragraph[stop:].lstrip()
        if paragraph:
            lines.append(paragraph)
    return '\n'.join(lines)


def audio_for(project, shot, summary):
    if shot.get('audio'):
        return project.inside(shot['audio'])
    for op in reversed(summary['operations']):
        if op['shot_id'] != shot['id'] or op['purpose'] != 'audio' or not op['local_file']:
            continue
        fp = digest({'shot': shot_hash(shot), 'purpose': 'audio', 'request': op['request']})
        if fp == op['fingerprint']:
            return project.inside(op['local_file'])
    return None


def render(project, width=None, height=None):
    summary = project.summary()
    state = summary['project']
    check(state['shots'] and all(s.get('accepted') for s in state['shots']), '请先在素材审看页采纳每镜素材。', 'review_required')
    with project.db() as db:
        check(db.execute("SELECT 1 FROM reviews WHERE stage='assets' AND status='completed' AND json_extract(result,'$.action')='confirm' AND json_extract(result,'$.revision')=?", (state['revision'],)).fetchone(), '当前版本尚未通过素材审看。', 'review_required')
    width, height = (width, height) if width and height else ((1080, 1920) if state['format'] == '9:16' else (1920, 1080))
    check(width % 2 == height % 2 == 0 and 128 <= width <= 3840 and 128 <= height <= 3840, '导出尺寸无效。')
    rid = uuid.uuid4().hex
    folder = project.root / 'exports' / rid
    folder.mkdir(parents=True)
    ffmpeg = executable('ffmpeg')
    captions, timeline, warnings = [], [], []
    cursor = 0.0
    with project.db() as db:
        db.execute('INSERT INTO renders VALUES(?,?,?,?)', (rid, state['revision'], 'running', dump({'folder': str(folder.relative_to(project.root))})))
    try:
        for index, shot in enumerate(state['shots']):
            source = project.inside(shot['accepted'])
            check(source.is_file(), '已采纳素材不存在。')
            check(any(c['file'] == shot['accepted'] and c['fingerprint'] == shot_hash(shot) for c in shot['candidates']), '已采纳素材属于旧镜头版本。')
            metadata = probe(source)
            video = next((s for s in metadata['streams'] if s['codec_type'] == 'video'), None)
            check(video is not None, '镜头画面没有视频/图片轨道。')
            is_image = source.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp')
            has_sound = any(s['codec_type'] == 'audio' for s in metadata['streams'])
            talking = shot['method'] in ('avatar', 'lipsync') or shot.get('audio_mode') == 'source'
            narration = None if talking else audio_for(project, shot, summary)
            target = float(shot['duration'])
            start = float(shot.get('start', 0))
            check(start >= 0, '裁切起点不能为负数。')
            sound_seconds = None
            if narration:
                audio_info = probe(narration)
                check(any(s['codec_type'] == 'audio' for s in audio_info['streams']), '配音文件缺少声音轨道。')
                sound_seconds = duration(audio_info)
                check(sound_seconds <= target + 0.08, '镜头台词音频长于目标时长，请延长镜头、拆镜或修改台词。', 'speech_too_long')
            elif talking:
                check(has_sound and not is_image, '口播镜头必须包含原声音轨。', 'speech_missing')
                sound_seconds = duration(metadata)
                check(start == 0 and abs(sound_seconds - target) <= 0.15, '口播镜头按完整原声时长安排，请更新目标时长后重新审看，不可裁断讲话。', 'speech_duration_mismatch')
                target = sound_seconds
            elif has_sound and shot.get('audio_mode', 'source') == 'source':
                sound_seconds = max(0, duration(metadata) - start)
                check(target + 0.08 >= sound_seconds, '保留原声时不能截断；请调整镜头时长或明确选择静音。', 'speech_too_long')
            if video.get('width', width) < width or video.get('height', height) < height:
                warnings.append({'shot_id': shot['id'], 'notice': '源画面低于导出分辨率，已放大适配。'})
            args = [ffmpeg, '-v', 'error', '-y']
            if is_image:
                args += ['-loop', '1', '-framerate', '30']
            elif start:
                args += ['-ss', str(start)]
            args += ['-protocol_whitelist', 'file,pipe', '-i', str(source)]
            if narration:
                args += ['-protocol_whitelist', 'file,pipe', '-i', str(narration)]
                sound_map = '1:a:0'
            elif has_sound and shot.get('audio_mode', 'source') != 'mute':
                sound_map = '0:a:0'
            else:
                args += ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo']
                sound_map = '1:a:0'
            vf = f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps=30'
            if is_image and shot.get('motion', 'zoom') == 'zoom':
                vf += f",zoompan=z='min(zoom+0.0005,1.08)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={width}x{height}:fps=30"
            if not is_image:
                vf += ',tpad=stop_mode=clone:stop_duration=' + str(target)
            if shot.get('transition', 'cut') == 'fade':
                vf += f',fade=t=in:st=0:d=0.2,fade=t=out:st={max(0, target - .2)}:d=0.2'
            args += ['-vf', vf, '-map', '0:v:0', '-map', sound_map, '-af', 'apad,aresample=48000', '-t', str(target), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', f'{index:03d}.mp4']
            run(args, folder)
            if shot['line'].strip():
                # Strip ASS/HTML metacharacters from sentence subtitles.
                line = shot['line'].replace('\r', '').replace('-->', '→').replace('<', '＜').replace('>', '＞').replace('{', '｛').replace('}', '｝')
                line = caption_lines(line)
                captions.append(f'{len(captions)+1}\n{timestamp(cursor)} --> {timestamp(cursor + min(target, sound_seconds or target))}\n{line}\n')
            timeline.append({'shot_id': shot['id'], 'source': shot['accepted'], 'start': cursor, 'duration': target, 'audio': 'source' if talking else str(narration.relative_to(project.root)) if narration else 'source_or_silence'})
            cursor += target
        (folder / 'concat.txt').write_text(''.join(f"file '{i:03d}.mp4'\n" for i in range(len(timeline))), encoding='utf-8')
        (folder / 'captions.srt').write_text('\n'.join(captions), encoding='utf-8')
        run([ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '1', '-i', 'concat.txt', '-c', 'copy', 'joined.mp4'], folder)
        args = [ffmpeg, '-v', 'error', '-y', '-i', 'joined.mp4']
        if state.get('bgm'):
            args += ['-stream_loop', '-1', '-protocol_whitelist', 'file,pipe', '-i', str(project.inside(state['bgm']))]
            filters = '[0:a]asplit=2[voice][side];[1:a]volume=0.16[music];[music][side]sidechaincompress=threshold=0.02:ratio=8[duck];[voice][duck]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=11[a]'
            args += ['-filter_complex', filters, '-map', '0:v', '-map', '[a]']
        else:
            args += ['-map', '0:v', '-map', '0:a', '-af', 'loudnorm=I=-16:TP=-1.5:LRA=11']
        if captions:
            args += ['-vf', "subtitles=filename=captions.srt:force_style='FontName=Microsoft YaHei,FontSize=18,MarginV=28,Outline=1'"]
        args += ['-t', str(cursor), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', 'film.mp4']
        run(args, folder)
        output = probe(folder / 'film.mp4')
        run([ffmpeg, '-v', 'error', '-i', 'film.mp4', '-f', 'null', '-'], folder)
        check(abs(duration(output) - cursor) < .3, '成片时长不符，尚不可交付。')
        result = {'file': (folder / 'film.mp4').relative_to(project.root).as_posix(), 'subtitles': (folder / 'captions.srt').relative_to(project.root).as_posix(), 'duration': duration(output), 'width': width, 'height': height, 'warnings': warnings, 'timeline': timeline, 'revision': state['revision']}
        (folder / 'manifest.json').write_text(dump(result), encoding='utf-8')
        with project.db() as db:
            current = project.state(db)
            check(current['revision'] == state['revision'], '合成期间项目已修改，成片保留为旧版本。', 'stale_render')
            db.execute("UPDATE renders SET status='done',result=? WHERE id=?", (dump(result), rid))
        return result
    except BaseException:
        with project.db() as db:
            db.execute("UPDATE renders SET status='failed' WHERE id=?", (rid,))
        raise
