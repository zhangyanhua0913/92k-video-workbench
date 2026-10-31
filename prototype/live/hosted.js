'use strict';
// Presentation only; standalone editors and approval gates remain authoritative.
(()=>{
 const query=new URL(document.currentScript.src).searchParams,engine=query.get('engine'),panel=query.get('panel');
 const css=document.createElement('link');css.rel='stylesheet';css.href='/style.css';document.head.append(css);
 document.body.classList.add('hosted-editor');
 const notify=type=>parent.postMessage({type},location.origin);let dirty=false;
 const endpoint=()=>location.pathname.replace(/\/$/,'')+'/api/project';
 function captureBudget(){document.querySelectorAll('[data-budget-shot]').forEach(row=>{const shot=state.shots[Number(row.dataset.budgetShot)];shot.model=row.querySelector('[data-model]').value;shot.parameters=JSON.parse(row.querySelector('[data-parameters]').value||'{}');shot.limits={...(shot.limits||{})};for(const kind of ['visual','audio']){const value=row.querySelector('[data-limit='+kind+']').value;if(value==='')delete shot.limits[kind];else shot.limits[kind]=Number(value);}});}
 document.addEventListener('input',e=>{if(e.target.id==='note')return;dirty=true;notify('wb-dirty');});
 document.addEventListener('change',e=>{if(e.target.type==='file'||e.target.id==='note')return;dirty=true;notify('wb-dirty');});
 if(engine==='generate'){
  const original=draw;
  draw=function(){current=panel==='voices'?'storyboard':panel;original();
   if(panel==='storyboard'){
    const later=['audioId','clone_task_id','audio_mode','reference','audio','audioLimit','visualLimit','model','parameters'];
    document.querySelectorAll('[data-shot] label').forEach(l=>{const i=l.querySelector('[data-field]');if(i&&later.includes(i.dataset.field))l.hidden=true;const u=l.querySelector('[data-upload]');if(u&&['reference','audio'].includes(u.dataset.upload))l.hidden=true;});
    document.querySelectorAll('#content>.card').forEach(c=>{if(c.querySelector('[data-upload=bgm]'))c.hidden=true;});
   }
   if(panel==='budget'){
    const card=document.createElement('section');card.className='card';card.innerHTML='<h2>模型与逐项上限</h2><p>修改后保存，再准备任务和审阅预算；不会自动提交付费任务。</p>'+state.shots.map((s,i)=>'<div class="card" data-budget-shot="'+i+'"><h3>镜头 '+(i+1)+'</h3><label>模型 ID<input data-model value="'+esc(s.model||'')+'"></label><label>模型参数 JSON<textarea data-parameters>'+esc(JSON.stringify(s.parameters||{}))+'</textarea></label><label>画面最高积分<input type="number" data-limit="visual" value="'+esc(s.limits?.visual??'')+'"></label><label>配音最高积分<input type="number" data-limit="audio" value="'+esc(s.limits?.audio??'')+'"></label></div>').join('');
    const b=document.createElement('button');b.textContent='保存模型与逐项上限';b.onclick=guard(async()=>{captureBudget();await api(endpoint(),{project:state,revision:state.revision});await refresh();dirty=false;draw();notice('模型与上限已保存，需重新准备任务及审阅预算。');});card.append(b);document.getElementById('content').prepend(card);
   }
   if(panel==='voices'){
    document.querySelectorAll('#content > .card').forEach(c=>{if(c.querySelector('#script-text'))c.hidden=true;});
    const allowed=['audioId','clone_task_id','audio_mode','reference','audio'];
    document.querySelectorAll('[data-shot] label').forEach(l=>{const i=l.querySelector('[data-field]');if(i)l.hidden=!allowed.includes(i.dataset.field);const u=l.querySelector('[data-upload]');if(u)l.hidden=!['reference','audio'].includes(u.dataset.upload);});
    document.querySelectorAll('[data-shot] details').forEach(d=>d.open=true);
   }notify('wb-ready');
  };
 }else{
  const original=render;
  render=function(){tab=panel;original();const r=snapshot?.request;document.querySelector('footer').hidden=!r||!(r.stage===panel||(panel==='keyframes'&&r.stage==='final'));notify('wb-ready');};
 }
 window.addEventListener('message',async e=>{
  if(e.origin!==location.origin||e.source!==parent||e.data?.type!=='wb-save')return;
  try{if(dirty){if(engine==='generate'){if(panel==='budget')captureBudget();else capture();await api(endpoint(),{project:state,revision:state.revision});await refresh();draw();}else await save();}dirty=false;parent.postMessage({type:'wb-saved',id:e.data.id,ok:true},location.origin);}
  catch(error){parent.postMessage({type:'wb-saved',id:e.data.id,ok:false,message:error.message},location.origin);}
 });
})();
