"""Persistent batch queue. Each item remains an ordinary isolated project."""
import contextlib, json, sqlite3, time, uuid
from pathlib import Path
from core import Project, check, EditError, atomic, pid_alive
from registry import status
from media import import_file

class Batch:
    def __init__(self, anchor):
        self.anchor=anchor
        self.root=anchor.root/'batches'
        self.dbfile=anchor.meta/'batches.sqlite3'
        self.root.mkdir(exist_ok=True)
        with self.db() as c:
            c.executescript('''CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,title TEXT,packaging TEXT,speed REAL,created REAL);
            CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY,batch_id TEXT NOT NULL,project_id TEXT NOT NULL,project_path TEXT NOT NULL,filename TEXT NOT NULL,status TEXT NOT NULL,error TEXT,created REAL,FOREIGN KEY(batch_id) REFERENCES batches(id));
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,item_id TEXT NOT NULL,step TEXT NOT NULL,status TEXT NOT NULL,pid INTEGER,error TEXT,created REAL,FOREIGN KEY(item_id) REFERENCES items(id));''')
            if 'mode' not in {r['name'] for r in c.execute('PRAGMA table_info(batches)')}:
                c.execute("ALTER TABLE batches ADD COLUMN mode TEXT NOT NULL DEFAULT 'manual'")

    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.dbfile,timeout=30);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()

    def create(self,title,packaging,speed,mode='manual'):
        check(isinstance(title,str) and 0<len(title)<=120,'批次名称无效。')
        options=[x for x in status() if x['id']==packaging and 'packaging' in x['stages']]
        check(options and options[0]['ready'],'所选包装能力未就绪。')
        check(type(speed) in (int,float) and speed in (1,1.1,1.15,1.2,1.25,1.3,1.5),'语速无效。')
        check(mode in ('manual','auto'),'运行模式无效。')
        check(mode!='auto' or packaging in ('none','remotion-gold'),'该包装方式需要 Agent 自由创作，请使用手动模式；全自动支持无包装或暗金模板。','automation_unavailable')
        ident=uuid.uuid4().hex
        with self.db() as c:c.execute('INSERT INTO batches(id,title,packaging,speed,created,mode) VALUES(?,?,?,?,?,?)',(ident,title,packaging,speed,time.time(),mode))
        return {'id':ident,'title':title,'packaging':packaging,'speed':speed,'mode':mode}

    def add_file(self,batch_id,path,filename):
        with self.db() as c: row=c.execute('SELECT * FROM batches WHERE id=?',(batch_id,)).fetchone()
        check(row,'批次不存在。','not_found',404)
        check(isinstance(filename,str) and len(filename)<=255,'文件名称无效。')
        ident=uuid.uuid4().hex; folder=self.root/batch_id/ident
        p=Project.create(folder,Path(filename).stem[:120] or '口播视频')
        try:
            import_file(p,path,'video');s=p.state()
            workflow=dict(s['workflow'],packaging=row['packaging'])
            p.update({'workflow':workflow,'speed':row['speed']},s['revision'])
        except Exception:
            # Keep the failed project for diagnosis and make its state visible.
            with self.db() as c:c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?,?)',(ident,batch_id,p.state()['project_id'],str(folder),filename,'import_failed','素材导入失败，请核对文件后重新添加。',time.time()))
            raise
        with self.db() as c:c.execute('INSERT INTO items VALUES(?,?,?,?,?,?,?,?)',(ident,batch_id,p.state()['project_id'],str(folder),filename,'awaiting_agent',None,time.time()))
        return self.item(ident)

    def item(self,ident):
        with self.db() as c:
            row=c.execute('SELECT * FROM items WHERE id=?',(ident,)).fetchone()
            check(row,'批次项目不存在。','not_found',404)
            jobs=[dict(x) for x in c.execute('SELECT * FROM jobs WHERE item_id=? ORDER BY created',(ident,))]
        item=dict(row);p=Project(item['project_path'])
        if p.dbfile.exists():
            s=p.state();item.update(revision=s['revision'],workflow=s['workflow'],speed=s['speed'],tasks=p.tasks(),final_confirmed=p.approved('final'))
        item['jobs']=jobs;return item

    def list(self):
        with self.db() as c:
            batches=[dict(x) for x in c.execute('SELECT * FROM batches ORDER BY created DESC')]
            items=[dict(x) for x in c.execute('SELECT id,batch_id FROM items ORDER BY created')]
        for b in batches:b['items']=[self.item(x['id']) for x in items if x['batch_id']==b['id']]
        return batches

    def enqueue(self,item_id,step):
        check(step in ('transcribe','analyze','render','auto'),'队列步骤无效。')
        item=self.item(item_id);p=Project(item['project_path']);s=p.state()
        if step=='auto':
            with self.db() as c: batch=c.execute('SELECT mode,packaging FROM batches WHERE id=?',(item['batch_id'],)).fetchone()
            check(batch['mode']=='auto' and batch['packaging'] in ('none','remotion-gold') and s['workflow']['packaging']==batch['packaging'] and s['speed']==self.batch_speed(item['batch_id']) and s['workflow']['transcribe']=='whisper-local','该项目未授权可执行的全自动范围。','review_required')
        if step=='transcribe':check(s['workflow']['transcribe']=='whisper-local','云端转写须逐项目明确授权，不能批量静默提交。')
        if step=='render':
            check(p.approved('roughcut',s),'请先确认当前视频的粗剪。','review_required')
            check(s['workflow']['packaging']=='none' or s['scenes'],'所选包装尚无动画方案。','packaging_incomplete')
            if s['scenes'] or s.get('music'):check(p.approved('packaging',s),'请先确认当前视频的包装方向。','review_required')
            if s['scenes']:check(p.approved('keyframes',s),'请先确认当前视频的关键帧。','review_required')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute("SELECT * FROM jobs WHERE item_id=? AND step=? AND status IN ('queued','running')",(item_id,step)).fetchone()
            if old:return dict(old)
            ident=uuid.uuid4().hex;c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?)',(ident,item_id,step,'queued',None,None,time.time()))
        return {'id':ident,'item_id':item_id,'step':step,'status':'queued'}

    def next(self):
        """Claim one queue slot; caller executes job and records outcome."""
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            running=c.execute("SELECT * FROM jobs WHERE status='running'").fetchone()
            if running:
                if not pid_alive(running['pid']):
                    c.execute("UPDATE jobs SET status='interrupted',error='执行中断；请先核查原项目任务。' WHERE id=?",(running['id'],))
                    return {'status':'interrupted','job_id':running['id']}
                return {'status':'busy','job_id':running['id']}
            row=c.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if not row:return {'status':'idle'}
            import os
            c.execute("UPDATE jobs SET status='running',pid=? WHERE id=?",(os.getpid(),row['id']))
            return dict(row,status='running',pid=os.getpid())

    def batch_speed(self,ident):
        with self.db() as c:return c.execute('SELECT speed FROM batches WHERE id=?',(ident,)).fetchone()['speed']

    def execute_next(self):
        job=self.next()
        if job['status']!='running':return job
        try:
            item=self.item(job['item_id']);p=Project(item['project_path'])
            if job['step']=='auto':
                from providers import transcribe
                from media import render
                with self.db() as c:scope=c.execute('SELECT * FROM batches WHERE id=?',(item['batch_id'],)).fetchone()
                s=p.state();check(scope['mode']=='auto' and s['workflow']['transcribe']=='whisper-local' and s['workflow']['packaging']==scope['packaging'] and s['speed']==scope['speed'] and not s.get('music'),'项目配置已改变，全自动任务停止。','review_required')
                if not s['cues']:transcribe(p)
                s=p.state();rid=p.open_review('roughcut');p.decide(rid,s['revision'],'confirm','用户选择全自动本地模式：保留原内容，不自动删除口误或停顿。')
                if s['workflow']['packaging']=='remotion-gold':
                    from auto_gold import build
                    build(p)
                result=render(p)
            elif job['step']=='transcribe':
                from providers import transcribe
                result=transcribe(p)
            elif job['step']=='analyze':
                from media import analyze
                result=analyze(p)
            else:
                from media import render
                result=render(p)
            with self.db() as c:
                c.execute("UPDATE jobs SET status='done' WHERE id=?",(job['id'],))
                c.execute("UPDATE items SET status=?,error=NULL WHERE id=?",('awaiting_review' if job['step']=='auto' else 'awaiting_agent',job['item_id']))
            return {'status':'done','job_id':job['id'],'result':result}
        except Exception as e:
            message=str(e) if isinstance(e,EditError) else '本地步骤失败，请检查项目依赖及原任务。'
            with self.db() as c:
                c.execute("UPDATE jobs SET status='failed',error=? WHERE id=?",(message,job['id']))
                c.execute("UPDATE items SET status='failed',error=? WHERE id=?",(message,job['item_id']))
            return {'status':'failed','job_id':job['id'],'message':message}
