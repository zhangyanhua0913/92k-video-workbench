"""Authenticated same-origin mount of the fixed child director. No arbitrary proxy targets."""
import json,re,urllib.request,urllib.error
from urllib.parse import urlsplit
from core import check

PREFIX='/generation'

def current_review(project):
    import sqlite3
    from contextlib import closing
    db=project.root/'generation/.director/state.sqlite3'
    if not db.exists():return {'url':None}
    with closing(sqlite3.connect(db.as_uri()+'?mode=ro',uri=True)) as conn:
        row=conn.execute("SELECT id FROM reviews WHERE status='pending' ORDER BY created DESC LIMIT 1").fetchone()
    if not row:return {'url':None}
    from urllib.parse import quote
    return {'url':PREFIX+'/?review='+quote(row[0],safe='')}

def binding(project):
    root=project.root/'generation'
    descriptor=json.loads((root/'.director/session.json').read_text(encoding='utf-8'))
    state=json.loads((root/'project.json').read_text(encoding='utf-8'))
    check(re.fullmatch(r'http://127\.0\.0\.1:[1-9][0-9]{0,4}',descriptor['origin']) is not None,'生成服务地址无效。')
    check(descriptor['project_id']==state['project_id'],'生成工作区不匹配。')
    return descriptor

def rewrite(path,data):
    text=data.decode('utf-8')
    if path=='/':
        text=text.replace('href="/','href="/generation/').replace('src="/','src="/generation/')
    elif path=='/app.js':
        # All director API/upload/media links stay in its namespace.
        text=text.replace("'/api/","'/generation/api/").replace("'/media/","'/generation/media/").replace('href="/media/','href="/generation/media/')
    elif path=='/style.css':
        text+='\n:root{--ink:#e4eaf4;--muted:#a6b3c6;--paper:#0f1b2b;--line:#304158;--green:#337d6c}aside{position:sticky;top:0;width:100%;padding:10px;z-index:10;background:#17283a}aside .brand,aside .aside-label,aside .aside-bottom{display:none}nav{display:flex;flex-wrap:wrap;gap:5px}nav button{padding:9px;color:#c0cfdf}main{margin:0;padding:20px 18px 160px}footer{left:0;background:#152437;color:#dce7f7}.card{background:#152437;color:#e4eaf4}input,textarea,select{background:#0e1c2d;color:#e4eaf4;border-color:#364b64}.badge{background:#1a3a37;color:#d1e6e0}.card label{color:#b8c8da}\n'
    return text.encode('utf-8')

def forward(handler,body=None):
    descriptor=binding(handler.server.project)
    parts=urlsplit(handler.path)
    path=parts.path.removeprefix(PREFIX) or '/'
    check(path in ('/','/app.js','/style.css','/favicon.ico') or path.startswith(('/api/','/media/')),'生成页面地址无效。','not_found',404)
    check(not parts.fragment,'生成请求无效。')
    target=descriptor['origin']+path+('?' + parts.query if parts.query else '')
    headers={'X-Director-Session':descriptor['session']}
    for key in ('Content-Type','X-Filename','X-Director-Request','Range'):
        if handler.headers.get(key):headers[key]=handler.headers[key]
    if body is not None:headers['Origin']=descriptor['origin']
    request=urllib.request.Request(target,data=body,headers=headers,method='POST' if body is not None else 'GET')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*args):return None
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    try:response=opener.open(request,timeout=45)
    except urllib.error.HTTPError as error:response=error
    with response:
        transformed=path in ('/','/app.js','/style.css') and response.status==200
        content=rewrite(path,response.read(8*1024*1024)) if transformed else None
        handler.send_response(response.status)
        handler.send_header('Cache-Control','no-store')
        handler.send_header('Referrer-Policy','no-referrer')
        handler.send_header('X-Content-Type-Options','nosniff')
        handler.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'")
        for key in ('Content-Type','Content-Range','Accept-Ranges'):
            if response.headers.get(key):handler.send_header(key,response.headers[key])
        if content is not None:handler.send_header('Content-Length',str(len(content)))
        elif response.headers.get('Content-Length'):handler.send_header('Content-Length',response.headers['Content-Length'])
        # Upstream session cookies are intentionally not forwarded; parent authentication is required.
        handler.end_headers()
        if content is not None:handler.wfile.write(content)
        else:
            while True:
                chunk=response.read(65536)
                if not chunk:break
                handler.wfile.write(chunk)
