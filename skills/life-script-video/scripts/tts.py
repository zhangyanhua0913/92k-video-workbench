"""Generate through the authenticated local workbench; never read or print the 04 key."""
import argparse,json,os
from pathlib import Path
from urllib.request import Request,build_opener,ProxyHandler
from urllib.error import HTTPError
p=argparse.ArgumentParser();p.add_argument('--text-file',required=True);p.add_argument('--output',required=True);p.add_argument('--home');p.add_argument('--allow-paid',action='store_true');a=p.parse_args()
if not a.allow_paid:p.error('需要本次明确配音费用授权后使用--allow-paid')
out=Path(a.output).resolve()
if out.exists():p.error('输出已存在，请使用新版本文件名')
home=Path(a.home or os.environ.get('WORKBENCH_HOME',Path.home()/'.92k-video-workbench'))
d=json.loads((home/'session.json').read_text(encoding='utf-8'))
import re
if not re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}',d['origin']):p.error('工作台地址无效')
headers={'X-Workbench-Session':d['session'],'Origin':d['origin'],'Content-Type':'application/json'}
body=json.dumps({'text':Path(a.text_file).read_text(encoding='utf-8-sig'),'allow_paid':True},ensure_ascii=False).encode()
op=build_opener(ProxyHandler({}))
try:
 with op.open(Request(d['origin']+'/api/life-tts/synthesize',body,headers),timeout=90) as res:result=json.load(res)
 with op.open(Request(d['origin']+'/api/life-tts/audio?id='+result['id'],headers=headers),timeout=30) as res:raw=res.read()
except HTTPError as e:
 print(e.read().decode('utf-8',errors='replace'));raise SystemExit(1)
out.parent.mkdir(parents=True,exist_ok=True)
with out.open('xb') as f:f.write(raw)
print(json.dumps({'output':str(out),'bytes':len(raw),'speaker':'S_FwhCVmzP1'},ensure_ascii=False))
