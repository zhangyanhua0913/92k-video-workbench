"""Life-script 04 TTS; credentials and outputs stay outside the source checkout."""
import ctypes,json,os,re,uuid,threading
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler
from urllib.error import HTTPError,URLError
BASE='https://a.92k.fun/api/api-market/invoke/'
SPEAKER='S_FwhCVmzP1'
class LifeTTSError(ValueError):
    def __init__(self,message,status=400):super().__init__(message);self.status=status
def require(ok,message):
    if not ok:raise LifeTTSError(message)
class Blob(ctypes.Structure):
    _fields_ = [('length', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(raw, decrypt=False):
    require(os.name == 'nt', '令牌保存需要Windows DPAPI。')
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
    require(function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)), '本机凭据加密/解密失败。')
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        kernel.LocalFree(target.data)

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
class LifeTTS:
    def __init__(self,home):
        self.root=Path(home)/'life-tts';self.keyfile=self.root/'04-market.dpapi';self.lock=threading.Lock()
    def status(self):return {'configured':self.keyfile.is_file(),'speaker':SPEAKER,'voice_name':'人生剧本角色','resource_id':'seed-icl-2.0'}
    def configure(self,data):
        with self.lock:
            if data.get('clear') is True:self.keyfile.unlink(missing_ok=True);return self.status()
            key=data.get('key','').strip()
            require(re.fullmatch(r'sk-[A-Za-z0-9_./+=-]{6,}',key) is not None,'请输入完整04接口令牌，保留sk-前缀。')
            self.root.mkdir(parents=True,exist_ok=True);tmp=self.root/(uuid.uuid4().hex+'.tmp');tmp.write_bytes(protect(key.encode()));os.replace(tmp,self.keyfile)
        return self.status()
    def synthesize(self,data):
        require(data.get('allow_paid') is True,'请明确勾选本次接口配音可能产生费用。')
        text=data.get('text');require(isinstance(text,str) and 0<len(text.strip())<=10000,'请输入1至10000字配音文字（本地限制）。')
        require(self.keyfile.is_file(),'请先在工作台填写04接口令牌。')
        if not self.lock.acquire(blocking=False):raise LifeTTSError('已有配音请求执行中，请等待原请求。',409)
        ident=uuid.uuid4().hex;record=self.root/(ident+'.json')
        try:
            key=protect(self.keyfile.read_bytes(),True).decode()
            payload={'text':text.strip(),'speaker':SPEAKER,'resource_id':'seed-icl-2.0','audio_params':{'format':'mp3','sample_rate':24000}}
            request=Request(BASE+'volc-tts-stream?site_code=api-market',json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
            record.write_text(json.dumps({'id':ident,'status':'unknown','speaker':SPEAKER}),encoding='utf-8')
            try:
                with build_opener(ProxyHandler({}),NoRedirect()).open(request,timeout=75) as response:
                    require(response.headers.get_content_type()=='audio/mpeg','接口未返回MP3；本次结果需核查，不自动重试。')
                    raw=response.read(64*1024*1024+1)
            except HTTPError as error:
                raise LifeTTSError('配音接口HTTP '+str(error.code)+'，请核对令牌/权限；不自动重试。',502) from None
            except (URLError,TimeoutError,OSError):raise LifeTTSError('配音连接中断或超时，结果未知；请核查原请求，不要直接重复扣费调用。',502) from None
            require(128<len(raw)<=64*1024*1024 and (raw.startswith(b'ID3') or raw[0]==255 and raw[1]&224==224),'音频响应无效；本次结果需核查，不自动重试。')
            audio=self.root/(ident+'.mp3');audio.write_bytes(raw)
            record.write_text(json.dumps({'id':ident,'status':'completed','speaker':SPEAKER,'bytes':len(raw)}),encoding='utf-8')
            return {'id':ident,'url':'/api/life-tts/audio?id='+ident,'bytes':len(raw),'speaker':SPEAKER}
        finally:self.lock.release()
    def audio(self,ident):
        require(re.fullmatch('[a-f0-9]{32}',ident or '') is not None,'音频编号无效。')
        file=self.root/(ident+'.mp3');require(file.is_file(),'音频不存在。');return file
