"""Fast-forward updates with Git's local-change protection and active-session leases."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

REMOTE = 'https://github.com/zhangyanhua0913/92k-video-workbench.git'


def git(root, *args, check=True, timeout=30):
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                            encoding='utf-8', errors='replace', env=env, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError('Git operation failed: ' + args[0])
    return result


def state_dir(root):
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share')))
    target = base / '92k-video-workbench' / hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:16]
    target.mkdir(parents=True, exist_ok=True)
    return target


class Lock:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        self.file.seek(0, 2)
        if not self.file.tell():
            self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise

    def close(self):
        self.file.close()  # OS releases the lock, including after a crash.

    def __enter__(self): return self
    def __exit__(self, *args): self.close()


@contextlib.contextmanager
def gate(root):
    deadline = time.monotonic() + 35
    while True:
        try:
            lock = Lock(state_dir(root) / 'update.lock')
            break
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError('Another update/publish operation is still active')
            time.sleep(.1)
    try: yield
    finally: lock.close()


def active(root):
    busy = False
    for path in state_dir(root).glob('session-*.lock'):
        try:
            with Lock(path): pass
            path.unlink(missing_ok=True)
        except OSError:
            busy = True
    return busy


def version(root):
    path = Path(root) / 'VERSION'
    return path.read_text(encoding='utf-8').strip() if path.is_file() else 'unknown'


def update_unlocked(root, expected_remote=REMOTE):
    result = {'version': version(root), 'status': 'unchanged'}
    if active(root): return {**result, 'status': 'active_session'}
    if not (Path(root) / '.git').exists(): return {**result, 'status': 'archive_install', 'hint': 'Use a git clone for automatic updates'}
    if git(root, 'remote', 'get-url', 'origin').stdout.strip().removesuffix('.git') != expected_remote.removesuffix('.git'):
        return {**result, 'status': 'different_remote'}
    if git(root, 'branch', '--show-current').stdout.strip() != 'main':
        return {**result, 'status': 'custom_branch'}
    if git(root, 'rev-parse', '--verify', 'HEAD', check=False).returncode:
        return {**result, 'status': 'no_commit'}
    if git(root, 'rev-parse', '-q', '--verify', 'MERGE_HEAD', check=False).returncode == 0:
        return {**result, 'status': 'merge_in_progress'}
    try:
        fetch = git(root, 'fetch', '--quiet', 'origin', 'refs/heads/main', check=False, timeout=20)
    except subprocess.TimeoutExpired:
        return {**result, 'status': 'offline'}
    if fetch.returncode: return {**result, 'status': 'offline'}
    target = git(root, 'rev-parse', 'FETCH_HEAD').stdout.strip()
    current = git(root, 'rev-parse', 'HEAD').stdout.strip()
    if target == current: return {**result, 'commit': current}
    if git(root, 'merge-base', '--is-ancestor', current, target, check=False).returncode:
        return {**result, 'status': 'local_history', 'hint': 'Local history retained; no reset/rebase was performed'}
    # Git refuses overwritten local edits and untracked-file collisions. Never stash/reset/clean.
    merged = git(root, 'merge', '--ff-only', '--no-edit', target, check=False)
    if merged.returncode:
        return {**result, 'status': 'local_changes', 'hint': 'Keep local work; reconcile the conflicting files explicitly'}
    return {'version': version(root), 'status': 'updated', 'commit': target}


def update(root, expected_remote=REMOTE):
    with gate(root): return update_unlocked(root, expected_remote)


@contextlib.contextmanager
def session(root, auto_update=True):
    with gate(root):
        result = update_unlocked(root) if auto_update else {'status': 'check_skipped', 'version': version(root)}
        path = state_dir(root) / ('session-' + uuid.uuid4().hex + '.lock')
        lease = Lock(path)
    try: yield result
    finally:
        lease.close()
        path.unlink(missing_ok=True)
