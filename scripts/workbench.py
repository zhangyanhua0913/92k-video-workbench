"""Public entry point: version check, prototype, and bundled Skill CLIs."""
import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import sys
from versioning import session, update, version

ROOT = Path(__file__).resolve().parents[1]
ENTRY = {'talking-edit': 'cli.py', '92k-video-director': 'director.py', 'narration-footage': 'footage.py'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-update', action='store_true', help='Explicit offline/pinned run')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('version')
    sub.add_parser('check-update')
    preview = sub.add_parser('preview'); preview.add_argument('--port', type=int, default=18735)
    skill = sub.add_parser('skill'); skill.add_argument('name', choices=ENTRY); skill.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command == 'version':
        print(json.dumps({'version': version(ROOT)})); return
    if args.command == 'check-update':
        print(json.dumps(update(ROOT), ensure_ascii=False)); return
    with session(ROOT, not args.no_update) as result:
        print(json.dumps({'update': result}, ensure_ascii=False), file=sys.stderr, flush=True)
        if args.command == 'preview':
            # Serve only the prototype; runtime data and Git metadata are never in this root.
            handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / 'prototype'))
            with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
                print(json.dumps({'url': f'http://127.0.0.1:{server.server_port}/', 'version': version(ROOT)}), flush=True)
                try: server.serve_forever()
                except KeyboardInterrupt: pass
        else:
            child_args = args.args[1:] if args.args[:1] == ['--'] else args.args
            code = subprocess.call([sys.executable, str(ROOT/'skills'/args.name/'scripts'/ENTRY[args.name]), *child_args])
            raise SystemExit(code)


if __name__ == '__main__': main()
