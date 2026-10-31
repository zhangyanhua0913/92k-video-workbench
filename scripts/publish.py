"""Opt-in author publishing: source-only scan, version bump, commit, verified push."""
import argparse
import hashlib
import json
from pathlib import Path
import re
from versioning import REMOTE, gate, git, state_dir, version

ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {'README.md','AGENTS.md','SKILL.md','LICENSE','THIRD_PARTY_NOTICES.md','CHANGELOG.md','CONTRIBUTING.md','VERSION','.gitignore','.gitattributes'}
TOP_DIRS = {'prototype','skills','docs','scripts','tests','agents','manifests','examples'}
SUFFIXES = {'.py','.md','.json','.yaml','.yml','.html','.css','.js','.ts','.tsx','.txt','.svg','.toml','.lock'}
BLOCK_PARTS = {'private','runtime','projects','exports','media','node_modules','__pycache__','.venv','user','local','reference-studies'}
VERSION = re.compile(r'^0\.1\.0-prototype\.(\d+)$')


def author_config(root):
    # Local Git metadata is not cloned or committed, and works across logon contexts.
    path=Path(git(root,'rev-parse','--git-path','info/92k-author.json').stdout.strip())
    return path if path.is_absolute() else Path(root)/path


def scan(root, staged=False):
    flags=['--cached'] if staged else ['--cached','--others','--exclude-standard']
    files = git(root, 'ls-files', *flags, '-z').stdout.split('\0')
    blocked = []
    for name in filter(None, files):
        rel = Path(name); path = Path(root)/rel
        if not path.exists(): continue  # Tracked deletions can be committed.
        if (rel.is_absolute() or '..' in rel.parts or path.is_symlink() or
            (hasattr(path, 'is_junction') and path.is_junction()) or
            any(part.lower() in BLOCK_PARTS for part in rel.parts) or
            (len(rel.parts)==1 and name not in TOP_FILES) or
            (len(rel.parts)>1 and rel.parts[0] not in TOP_DIRS) or
            (path.suffix not in SUFFIXES and path.name != 'LICENSE' and name not in TOP_FILES)):
            blocked.append({'path':name,'reason':'outside source allowlist'}); continue
        # Reject linked parents as well as linked files.
        if not path.resolve().is_relative_to(Path(root).resolve()):
            blocked.append({'path':name,'reason':'outside repository'}); continue
        if re.search(r'(?i)(credential|secret|session|token)[._-].*\.(json|txt)$', name):
            blocked.append({'path':name,'reason':'private-looking filename'}); continue
        try: text = git(root,'show',':'+name).stdout if staged else path.read_text(encoding='utf-8-sig')
        except (UnicodeError, OSError):
            blocked.append({'path':name,'reason':'not UTF-8 source'}); continue
        patterns = [r'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',
                    r'\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,})\b',
                    r'(?i)[?&](?:token|signature|api_key|x-amz-signature)=[A-Za-z0-9_%.-]{20,}',
                    r'(?i)\bBearer\s+[A-Za-z0-9_.-]{24,}']
        if any(re.search(pattern, text) for pattern in patterns):
            blocked.append({'path':name,'reason':'possible credential; inspect locally'}); continue
        assignments = re.finditer(r'''(?im)["']?(?:api_key|apikey|personal_token|password|secret|access_token)["']?\s*[:=]\s*["']([A-Za-z0-9_+/.=-]{16,})["']''', text)
        if any(not re.search(r'(?i)example|dummy|placeholder|your|test|fake', m.group(1)) for m in assignments):
            blocked.append({'path':name,'reason':'possible literal credential; inspect locally'})
    return blocked


def inventory(root):
    label='本地交互原型 · '+version(root)
    (Path(root)/'prototype').mkdir(exist_ok=True)
    (Path(root)/'prototype/version.js').write_text('document.getElementById("version").textContent='+json.dumps(label,ensure_ascii=False)+';\n',encoding='utf-8',newline='\n')
    files=git(root,'ls-files','--cached','--others','--exclude-standard','-z').stdout.split('\0')
    output={}
    for name in sorted(set(filter(None,files))):
        if name=='manifests/release-files.json':continue
        path=Path(root)/name
        if path.is_file():output[name]=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    destination=Path(root)/'manifests/release-files.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def next_version(current, previous):
    match = VERSION.fullmatch(current)
    if not match: raise ValueError('VERSION must use 0.1.0-prototype.N for this prototype channel')
    if previous and current != previous:
        old = VERSION.fullmatch(previous)
        if not old or int(match[1]) <= int(old[1]): raise ValueError('Explicit version must increase')
        return current
    return '0.1.0-prototype.' + str(int(match[1]) + 1) if previous else current


def publish(root=ROOT, message='Update workbench source', bump=True):
    root = Path(root).resolve()
    config = author_config(root)
    settings=json.loads(config.read_text(encoding='utf-8')) if config.exists() else {}
    if settings != {'root':str(root),'remote':REMOTE,'enabled':True}:
        return {'status':'disabled', 'root':str(root),'config':str(config),'config_exists':config.exists(),
                'root_matches':settings.get('root')==str(root),'remote_matches':settings.get('remote')==REMOTE,
                'enabled':settings.get('enabled') is True,'hint':'Author auto-publish is opt-in on this machine only'}
    with gate(root):
        if git(root,'remote','get-url','origin').stdout.strip() != REMOTE: raise ValueError('Unexpected remote')
        if git(root,'branch','--show-current').stdout.strip() != 'main': raise ValueError('Author publishing requires main')
        blocked = scan(root)
        if blocked: return {'status':'blocked','files':blocked}
        has_head = git(root,'rev-parse','--verify','HEAD',check=False).returncode == 0
        changed = bool(git(root,'status','--porcelain').stdout)
        if changed:
            previous = git(root,'show','HEAD:VERSION',check=False).stdout.strip() if has_head else ''
            if bump:
                (root/'VERSION').write_text(next_version(version(root), previous)+'\n',encoding='utf-8',newline='\n')
            inventory(root)
            git(root,'add','--all','--','.')
            # Scan again after staging, never silently omit a suspicious file.
            blocked = scan(root, staged=True)
            if blocked: return {'status':'blocked','files':blocked}
            git(root,'commit','-m',message+' ['+version(root)+']')
        commit = git(root,'rev-parse','HEAD').stdout.strip()
        pushed = git(root,'push','origin','HEAD:refs/heads/main',check=False,timeout=60)
        if pushed.returncode: return {'status':'push_failed','commit':commit,'hint':'Commit retained locally; no force push'}
        remote = git(root,'ls-remote','origin','refs/heads/main').stdout.split()
        if not remote or remote[0] != commit: raise RuntimeError('Remote verification failed')
        return {'status':'published','version':version(root),'commit':commit,'changed':changed}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan',action='store_true')
    parser.add_argument('--enable-author',action='store_true')
    parser.add_argument('--message',default='Update workbench source')
    args=parser.parse_args()
    if args.enable_author:
        config={'root':str(ROOT.resolve()),'remote':REMOTE,'enabled':True}
        destination=author_config(ROOT);destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(config),encoding='utf-8')
        result={'status':'enabled','root':str(ROOT)}
    elif args.scan:
        blocked=scan(ROOT); result={'status':'blocked' if blocked else 'scan_passed','files':blocked}
    else: result=publish(message=args.message)
    print(json.dumps(result,ensure_ascii=False))
    if result['status'] in {'blocked','push_failed'}: raise SystemExit(1)


if __name__=='__main__': main()
