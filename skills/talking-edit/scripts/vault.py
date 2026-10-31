"""Windows user-bound DPAPI credentials, outside all projects and skill folders."""
import ctypes
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from core import check, EditError, atomic


class Blob(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(raw, decrypt=False):
    check(os.name == 'nt', '首版持久凭据使用Windows DPAPI；当前系统不支持。', 'unsupported_os')
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    check(function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)), '本机凭据加密/解密失败。', 'vault_error')
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        kernel.LocalFree(target.data)


class Vault:
    def __init__(self, root=None):
        self.root = Path(root or (Path(os.environ.get('TALKING_EDIT_HOME', Path.home() / '.talking-edit')) / 'credentials')).expanduser().resolve()

    def meta(self):
        path = self.root / 'index.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'active': None, 'entries': {}}

    def status(self):
        data = self.meta()
        return {'configured': bool(data['active']), 'active': data['active'], 'entries': [{'id': k, **v} for k, v in data['entries'].items()]}

    def put(self, secret):
        check(isinstance(secret, str) and 8 <= len(secret.strip()) <= 512 and not re.search(r'\s', secret.strip()), 'Key格式无效。')
        secret = secret.strip()
        identifier = hashlib.sha256(secret.encode()).hexdigest()[:24]
        encrypted = protect(secret.encode())
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (identifier + '.dpapi')
        tmp = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
        tmp.write_bytes(encrypted)
        os.replace(tmp, path)
        data = self.meta()
        data['entries'][identifier] = {'mask': '••••' + secret[-4:]}
        data['active'] = identifier
        atomic(self.root / 'index.json', data)
        return self.status()

    def get(self, identifier=None):
        data = self.meta()
        identifier = identifier or data['active']
        check(identifier in data['entries'], '请在配置页面填写Key；旧任务需要原Key。', 'key_missing')
        return protect((self.root / (identifier + '.dpapi')).read_bytes(), True).decode()

    def delete(self, identifier):
        data = self.meta()
        check(identifier in data['entries'], '凭据不存在。')
        (self.root / (identifier + '.dpapi')).unlink(missing_ok=True)
        del data['entries'][identifier]
        if data['active'] == identifier:
            data['active'] = None
        atomic(self.root / 'index.json', data)
        return self.status()

