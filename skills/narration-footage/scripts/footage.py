"""Portable footage inventory and timeline checks. Search/semantic selection belongs to Agent."""
import argparse, gzip, hashlib, html, json, os, re, subprocess, urllib.parse, urllib.request
from pathlib import Path
from html.parser import HTMLParser

def save(p, value):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(p)
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def secure_url(u):
    x=urllib.parse.urlsplit(u)
    if x.scheme!='https' or not x.hostname or x.username or x.password:raise ValueError('Only public HTTPS URLs without credentials are accepted')
    import socket,ipaddress
    if any(not ipaddress.ip_address(a[4][0]).is_global for a in socket.getaddrinfo(x.hostname,x.port or 443,type=socket.SOCK_STREAM)):raise ValueError('Non-public destination rejected')
    return u
class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return super().redirect_request(req,fp,code,msg,headers,secure_url(newurl))
def fetch(u,limit):
    secure_url(u)
    with urllib.request.build_opener(Redirect()).open(urllib.request.Request(u,headers={'User-Agent':'NarrationFootage/0.1','Accept-Encoding':'identity'}),timeout=30) as r:
        length=int(r.headers.get('Content-Length',0))
        if length>limit:raise ValueError('Size limit exceeded')
        data=r.read(limit+1)
        if len(data)>limit:raise ValueError('Size limit exceeded')
        if data[:2]==b'\x1f\x8b':
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as z:data=z.read(limit+1)
            if len(data)>limit:raise ValueError('Expanded size limit exceeded')
        return data
class MediaParser(HTMLParser):
    def __init__(self,base):super().__init__();self.base=base;self.items=[]
    def handle_starttag(self,tag,attrs):
        d=dict(attrs)
        if tag in ('source','video') and d.get('src'):
            u=urllib.parse.urljoin(self.base,d['src'])
            if urllib.parse.urlsplit(u).scheme=='https':self.items.append({'url':u,'mime':d.get('type'),'stage':'discovered','visually_reviewed':False})
def probe(file):
    result=subprocess.run([os.environ.get('DIRECTOR_FFPROBE','ffprobe'),'-v','error','-show_entries','format=duration:stream=width,height,codec_type','-of','json',str(file)],capture_output=True,check=True)
    return json.loads(result.stdout)
def local(root,rel):
    p=(root/rel).resolve()
    if not p.is_relative_to(root.resolve()):raise ValueError('File escapes project')
    return p
def audit(root,plan):
    issues=[];timeline=plan.get('timeline',[])
    for s in timeline:
        tag=s.get('id','?');end=s.get('end',0);start=s.get('start',0)
        if end<=start:issues.append(tag+': invalid range')
        if s.get('kind')=='video':
            a=plan.get('assets',{}).get(s.get('asset'))
            if not a:issues.append(tag+': missing asset');continue
            p=local(root,a['file'])
            if not p.is_file():issues.append(tag+': missing local media');continue
            if hashlib.sha256(p.read_bytes()).hexdigest()!=a.get('sha256'):issues.append(tag+': changed media hash')
            if not a.get('source_page'):issues.append(tag+': missing source')
            if a.get('product')!=s.get('product'):issues.append(tag+': product/version mismatch')
            if not s.get('visually_reviewed'):issues.append(tag+': shot not visually reviewed')
            if not s.get('match_reason'):issues.append(tag+': no semantic match explanation')
            if s.get('source_in',0)<0 or s.get('source_in',0)+end-start>float(a.get('duration',0))+.05:issues.append(tag+': source too short')
    return {'ok':not issues,'issues':issues,'shots':len(timeline),'note':'Technical audit does not establish factual accuracy, usage permission or user approval.'}
def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);sub=p.add_subparsers(dest='cmd',required=True)
    d=sub.add_parser('discover');d.add_argument('--page',required=True)
    d=sub.add_parser('download');d.add_argument('--url',required=True);d.add_argument('--id',required=True);d.add_argument('--page',required=True);d.add_argument('--product',required=True);d.add_argument('--publisher',required=True);d.add_argument('--max-mb',type=int,default=30)
    d=sub.add_parser('audit');d.add_argument('--plan',required=True)
    a=p.parse_args();root=Path(a.project).resolve();root.mkdir(parents=True,exist_ok=True)
    if a.cmd=='discover':
        parser=MediaParser(a.page);parser.feed(fetch(a.page,8*1024*1024).decode('utf-8'));result={'page':a.page,'candidates':list({v['url']:v for v in parser.items}.values()),'note':'Candidates only; confirm actual content and usage rights before selecting.'};save(root/'discovery.json',result)
    elif a.cmd=='download':
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',a.id):raise ValueError('Invalid asset id')
        suffix=Path(urllib.parse.urlsplit(a.url).path).suffix.lower()
        if suffix not in ('.mp4','.webm','.mov'):raise ValueError('Unsupported media extension')
        file=root/'media'/(a.id+suffix);file.parent.mkdir(exist_ok=True)
        if file.exists():raise ValueError('Asset exists; reuse its record, do not overwrite')
        data=fetch(a.url,min(max(a.max_mb,1),200)*1024*1024);part=file.with_suffix('.part');part.write_bytes(data)
        try:info=probe(part)
        except Exception:part.unlink(missing_ok=True);raise ValueError('Downloaded data failed media probe')
        if not any(s['codec_type']=='video' for s in info['streams']):part.unlink();raise ValueError('Not a video')
        part.replace(file);result={'id':a.id,'file':file.relative_to(root).as_posix(),'sha256':hashlib.sha256(data).hexdigest(),'duration':float(info['format']['duration']),'product':a.product,'publisher':a.publisher,'source_page':a.page,'media_url':a.url,'usage':'unverified','visually_reviewed':False};save(root/'media'/(a.id+'.json'),result)
    else:result=audit(root,read(a.plan))
    print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
