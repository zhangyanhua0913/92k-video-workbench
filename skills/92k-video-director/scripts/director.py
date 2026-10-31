#!/usr/bin/env python3
"""Agent-facing commands. All output is JSON; user Keys are configured only in the UI."""
import argparse
import json
import os
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import Request, build_opener
from core import Project, DirectorError, check, dump, shot_hash, digest
from provider import Client, DEFAULTS, plan_operation, quote_operation, submit_operation, poll_operation, download_operation, redo_operation
from vault import Vault
from media import doctor, probe, render

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def session(project):
    try:
        data = load(project.root / '.director/session.json')
        check(data['origin'].startswith('http://127.0.0.1:') and data['project_id'] == project.state()['project_id'], '本机交互会话无效。')
        request = Request(data['origin'] + '/api/health', headers={'X-Director-Session': data['session']})
        with build_opener().open(request, timeout=2) as response:
            check(json.load(response)['project_id'] == data['project_id'], '交互服务不属于当前项目。')
        return data
    except Exception:
        return None


def open_review(project, stage, browser=True):
    data = session(project)
    if not data:
        arguments = [sys.executable, str(Path(__file__).resolve()), '--project', str(project.root), 'serve']
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
        subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != 'nt')
        for _ in range(60):
            time.sleep(.1)
            data = session(project)
            if data:
                break
        check(data, '辅助页面服务未启动，请运行serve检查。', 'ui_unavailable')
    rid = project.open_review(stage)
    url = data['origin'] + '/?review=' + rid + '#session=' + data['session']
    if browser:
        webbrowser.open(url)
    return {'request_id': rid, 'url': url, 'stage': stage, 'next': '用Codex浏览器面板打开url；等待本请求结果，不要结束当前回合或重复询问确认。'}


def prepare(project, client=None):
    client = client or Client()
    state = project.state()
    operations = []
    for shot in state['shots']:
        limits = shot.get('limits', {})
        audio_ref = 'file:' + shot['audio'] if shot.get('audio') else None
        source_sound = shot['method'] == 'local_video' and shot.get('audio_mode', 'source') == 'source'
        if shot['line'] and not audio_ref and not source_sound and shot.get('audio_mode') != 'mute':
            voice = shot['voice']
            clone = voice.get('clone_task_id')
            check(clone or voice.get('audioId'), '镜头' + shot['id'] + '需要实际audioId、本人克隆任务号或本地音频。', 'voice_missing')
            check('audio' in limits, '请为每笔配音任务填写limits.audio积分上限。')
            request = {'model_id': 'dreamface:tts-clone' if clone else 'dreamface:tts-common', 'parameters': {'text': shot['line'], 'lan': 'zh-CN', **({'clone_task_id': clone} if clone else {'audioId': voice['audioId']})}, 'assets': {}}
            op = plan_operation(project, shot['id'], 'audio', request, limits['audio'], client)
            operations.append(op)
            audio_ref = 'operation:' + op['id']
        if shot['method'].startswith('local_'):
            if shot.get('source'):
                project.add_candidate(shot['id'], shot['source'])
            continue
        check('visual' in limits, '请为每笔画面任务填写limits.visual积分上限。')
        method = shot['method']
        model = shot.get('model') or DEFAULTS[method]
        parameters = dict(shot.get('parameters', {}))
        assets = {}
        if method in ('image', 'image_edit'):
            parameters.setdefault('prompt', shot['prompt'] or shot['visual'])
            parameters.setdefault('width', 768 if state['format'] == '9:16' else 1344)
            parameters.setdefault('height', 1344 if state['format'] == '9:16' else 768)
            parameters.setdefault('num', 1)
            if method == 'image_edit':
                check(shot.get('reference'), '参考图编辑缺少reference。')
                assets['imageUrl'] = ['file:' + shot['reference']]
        elif method in ('video', 'image_video'):
            parameters.setdefault('prompt', shot['prompt'] or shot['visual'])
            parameters.setdefault('duration', int(shot['duration']))
            parameters.setdefault('resolution', '480P')
            parameters.setdefault('aspectRatio', state['format'])
            if method == 'image_video':
                check(shot.get('reference'), '图生视频缺少reference。')
                assets['images'] = ['file:' + shot['reference']]
        elif method in ('avatar', 'lipsync'):
            check(audio_ref, '口播镜头需要音频或配音任务。')
            check(shot.get('reference'), '口播镜头需要人物参考素材。')
            if method == 'avatar':
                assets = {'audio': [audio_ref], 'image': ['file:' + shot['reference']]}
                parameters.setdefault('prompt', shot['prompt'] or shot['visual'] or '自然说话，保持人物形象。')
                parameters.setdefault('resolution', '480p')
            else:
                assets = {'audioUrl': [audio_ref], 'srcVideoUrl': ['file:' + shot['reference']]}
        op = plan_operation(project, shot['id'], 'visual', {'model_id': model, 'parameters': parameters, 'assets': assets}, limits['visual'], client)
        operations.append(op)
    return {'operations': [{'id': op['id'], 'shot_id': op['shot_id'], 'purpose': op['purpose'], 'ceiling': op['ceiling'], 'status': op['status']} for op in operations], 'next': '查看报价/依赖状态，打开budget页面确认整轮积分上限。'}


def step(project, client=None):
    client = client or Client()
    summary = project.summary()
    shots = {s['id']: s for s in summary['project']['shots']}
    for op in summary['operations']:
        # Unresolved old tasks have priority over all new generation.
        if op['task_id'] and op['status'] not in ('succeeded', 'failed', 'expired'):
            return {'operation_id': op['id'], 'result': poll_operation(project, op['id'], client), 'next': '继续step查询原单；未知状态不得补生成。'}
    for op in summary['operations']:
        shot = shots.get(op['shot_id'])
        current = shot and digest({'shot': shot_hash(shot), 'purpose': op['purpose'], 'request': op['request']}) == op['fingerprint']
        if not current or not op['current']:
            continue
        if op['status'] == 'succeeded' and not op['local_file']:
            return {'operation_id': op['id'], 'result': download_operation(project, op['id'], client)}
        if op['status'] in ('failed', 'expired'):
            raise DirectorError('当前镜头原任务失败或过期，请审看后修改计划或替换素材；不会自动重做。', 'generation_failed')
        if op['status'] == 'planned':
            return {'operation_id': op['id'], 'result': submit_operation(project, op['id'], client)}
    return {'status': 'awaiting_assets_review', 'next': '所有当前任务已处理。核对每镜候选素材和真实音频时长，打开assets页面审看；不得自动采纳。'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', help='独立项目目录，不放在Skill目录内')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('doctor')
    create = commands.add_parser('create'); create.add_argument('--input', required=True)
    commands.add_parser('show')
    update = commands.add_parser('update'); update.add_argument('--input', required=True); update.add_argument('--revision', type=int, required=True)
    imp = commands.add_parser('import'); imp.add_argument('--file', required=True); imp.add_argument('--shot')
    commands.add_parser('serve')
    review = commands.add_parser('review'); review.add_argument('--stage', choices=['config', 'storyboard', 'budget', 'assets', 'final'], required=True); review.add_argument('--no-browser', action='store_true')
    wait = commands.add_parser('wait'); wait.add_argument('--request', required=True); wait.add_argument('--seconds', type=int, default=40)
    commands.add_parser('stop-server')
    commands.add_parser('models'); commands.add_parser('account'); commands.add_parser('prepare'); commands.add_parser('step'); commands.add_parser('recover')
    plan = commands.add_parser('plan-operation'); plan.add_argument('--shot', required=True); plan.add_argument('--purpose', choices=['audio', 'visual'], required=True); plan.add_argument('--request', required=True); plan.add_argument('--ceiling', required=True, type=int)
    for name in ('quote', 'submit', 'poll', 'download'):
        cmd = commands.add_parser(name); cmd.add_argument('--operation', required=True)
    redo = commands.add_parser('redo'); redo.add_argument('--operation', required=True); redo.add_argument('--review', required=True)
    probe_cmd = commands.add_parser('probe'); probe_cmd.add_argument('--file', required=True)
    commands.add_parser('render')
    args = parser.parse_args(argv)
    try:
        if args.command == 'doctor':
            result = doctor()
        elif args.command in ('models', 'account'):
            result = getattr(Client(), args.command)()
        else:
            check(args.project, '此命令需要--project目录。')
            project = Project(args.project)
            if args.command == 'create':
                result = Project.create(args.project, load(args.input)).state()
            else:
                check(project.dbfile.exists(), '项目不存在，请先create。')
                if args.command == 'show':
                    result = project.summary()
                elif args.command == 'update':
                    result = project.update(load(args.input), args.revision)
                elif args.command == 'import':
                    result = project.import_file(args.file)
                    if args.shot:
                        project.add_candidate(args.shot, result['file'])
                elif args.command == 'review':
                    result = open_review(project, args.stage, not args.no_browser)
                elif args.command == 'serve':
                    from web import serve
                    serve(project)
                    result = {'stopped': True}
                elif args.command == 'wait':
                    deadline = time.monotonic() + max(0, min(45, args.seconds))
                    while True:
                        result = project.review(args.request)
                        if result['status'] != 'pending' or time.monotonic() >= deadline:
                            break
                        time.sleep(.5)
                    if result['status'] == 'completed':
                        result['project'] = project.state()
                    else:
                        result['next'] = '保持当前任务，分段等待同一请求；未确认不是授权。'
                elif args.command == 'stop-server':
                    data = session(project)
                    if data:
                        request = Request(data['origin'] + '/api/stop', b'{}', headers={'X-Director-Session': data['session'], 'Content-Type': 'application/json'})
                        with build_opener().open(request, timeout=5) as response:
                            result = json.load(response)
                    else:
                        result = {'stopped': True}
                elif args.command == 'prepare':
                    result = prepare(project)
                elif args.command == 'plan-operation':
                    result = plan_operation(project, args.shot, args.purpose, load(args.request), args.ceiling)
                elif args.command == 'step':
                    result = step(project)
                elif args.command == 'redo':
                    result = redo_operation(project, args.operation, args.review)
                elif args.command == 'recover':
                    project.sync()
                    result = project.summary()
                    result['next'] = '先poll所有执行中/未知原单；复用已下载素材，读取已完成review，不补生成。'
                elif args.command in ('quote', 'submit', 'poll', 'download'):
                    result = {'quote': quote_operation, 'submit': submit_operation, 'poll': poll_operation, 'download': download_operation}[args.command](project, args.operation)
                elif args.command == 'probe':
                    result = probe(project.inside(args.file))
                elif args.command == 'render':
                    result = render(project)
                else:
                    raise DirectorError('未知命令。')
        print(dump({'ok': True, 'result': result}))
        return 0
    except DirectorError as error:
        print(dump({'ok': False, 'code': error.code, 'error': str(error)}))
        return 2
    except (OSError, ValueError, KeyError, TypeError):
        # Do not echo input bodies, credentials or arbitrary upstream errors.
        print(dump({'ok': False, 'code': 'invalid_or_unavailable', 'error': '输入或本机环境异常；请检查文件、版本与参数。原项目和任务保留。'}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
