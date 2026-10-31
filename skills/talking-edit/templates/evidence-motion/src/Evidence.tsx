import React from 'react';
import {AbsoluteFill,OffthreadVideo,Img,staticFile,useCurrentFrame,useVideoConfig,interpolate,Easing} from 'remotion';
export type Scene={start:number;end:number;title:string;chapter:string;layout:'presenter'|'split'|'document';kind?:'flow'|'compare'|'reuse'|'loop'|'quote'|'network';items?:string[];note?:string;image?:string};
export type Props={source:string;scenes:Scene[];cues:{start:number;end:number;text:string}[];chapters:{at:number;title:string}[]};
const yellow='#f3c333',white='#f4f3ed',muted='#a4acb5',bg='#10151b';
const ease=Easing.bezier(.16,1,.3,1);
const progress=(t:number,delay=0)=>interpolate(t,[delay,delay+.55],[0,1],{easing:ease,extrapolateLeft:'clamp',extrapolateRight:'clamp'});
function Panel({scene,time}:{scene:Scene;time:number}){
 const items=scene.items||[];const visible=(i:number)=>progress(time,.35+i*.65);
 return <div style={{position:'absolute',inset:0,color:white}}>
  <div style={{height:35,borderBottom:'1px solid #ffffff1f',color:yellow,fontFamily:'Consolas',fontSize:15,padding:'8px 16px'}}>● ● ●　内容解读 / {scene.chapter}</div>
  <div style={{padding:'27px 28px',fontSize:32,fontWeight:800,lineHeight:1.3}}>{scene.title}</div>
  {scene.image?<Img src={staticFile(scene.image)} style={{position:'absolute',left:30,top:150,width:'90%',height:330,objectFit:'contain'}}/>:
  <div style={{position:'absolute',left:28,right:28,top:160,bottom:45}}>
   {scene.kind==='compare'?<div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:20}}>{items.map((x,i)=><div key={i} style={{opacity:visible(i),translate:`0 ${(1-visible(i))*18}px`,border:'1px solid '+(i%2?yellow:'#65717e'),borderRadius:10,padding:25,background:i%2?'#f3c33318':'#ffffff08',fontSize:25,lineHeight:1.5}}><div style={{fontSize:14,color:i%2?yellow:muted,marginBottom:15}}>{i%2?'可以尝试':'原有做法'}</div>{x}</div>)}</div>:
   scene.kind==='network'?<div style={{position:'relative',height:310}}><svg width="100%" height="100%" viewBox="0 0 700 300">{items.slice(1).map((_,i)=><path key={i} d={`M150 150 C300 150 360 ${45+i*85} 490 ${45+i*85}`} stroke={yellow} strokeWidth={3} fill="none" opacity={visible(i+1)}/>)}</svg><div style={{position:'absolute',left:15,top:120,padding:'20px 25px',background:yellow,color:bg,fontSize:25,borderRadius:8}}>{items[0]}</div>{items.slice(1).map((x,i)=><div key={i} style={{position:'absolute',left:'68%',top:20+i*85,width:190,padding:16,border:'1px solid '+yellow,borderRadius:8,fontSize:23,opacity:visible(i+1)}}>{x}</div>)}</div>:
   scene.kind==='quote'?<div style={{borderLeft:'5px solid '+yellow,padding:'15px 30px',fontSize:38,lineHeight:1.5,opacity:progress(time)}}>{items.map((x,i)=><div key={i} style={{opacity:visible(i)}}>{x}</div>)}</div>:
   scene.kind==='reuse'?<><div style={{padding:22,background:'#f4f3ed',color:bg,borderRadius:12,fontSize:28,width:'55%',opacity:visible(0)}}>{items[0]}</div><div style={{display:'flex',gap:20,marginTop:55}}>{items.slice(1).map((x,i)=><div key={i} style={{flex:1,padding:23,border:'1px solid '+yellow,borderRadius:10,fontSize:23,opacity:visible(i+1)}}>↳ {x}</div>)}</div></>:
   <div style={{display:'flex',flexDirection:'column',gap:18}}>{items.map((x,i)=><div key={i} style={{display:'flex',gap:20,alignItems:'center',opacity:visible(i),translate:`${(1-visible(i))*30}px 0`}}><span style={{width:42,height:42,borderRadius:7,background:yellow,color:bg,display:'grid',placeItems:'center',fontSize:22,fontWeight:900}}>{scene.kind==='loop'?'↻':i+1}</span><div style={{flex:1,fontSize:27,padding:'14px 18px',borderBottom:'1px solid #ffffff25'}}>{x}</div></div>)}</div>}
  </div>}
  <div style={{position:'absolute',bottom:14,left:28,fontSize:13,color:muted}}>{scene.note||'根据本段口述整理 · 示意图'}</div>
 </div>
}
export const Evidence:React.FC<Props>=({source,scenes,cues,chapters})=>{
 const frame=useCurrentFrame(),{fps,durationInFrames}=useVideoConfig();const now=frame/fps;const scene=scenes.find(s=>s.start<=now&&now<s.end);const mode=scene?.layout||'presenter';const cue=cues.find(c=>c.start<=now&&now<c.end);const chapter=Math.max(0,chapters.findLastIndex(c=>c.at<=now));
 const rect=mode==='presenter'?{left:0,top:44,width:1280,height:676,borderRadius:0}:mode==='split'?{left:30,top:94,width:370,height:500,borderRadius:16}:{left:25,top:500,width:145,height:145,borderRadius:90};
 return <AbsoluteFill style={{background:bg,fontFamily:'Microsoft YaHei, sans-serif',color:white}}>
  <div style={{position:'absolute',...rect,overflow:'hidden',border:mode==='presenter'?'none':'2px solid '+yellow}}><OffthreadVideo muted src={staticFile(source)} style={{width:'100%',height:'100%',objectFit:'cover',objectPosition:'50% 40%'}}/></div>
  {scene&&mode!=='presenter'&&<div style={{position:'absolute',left:mode==='split'?430:190,top:75,width:mode==='split'?820:1060,height:550,border:'1px solid #35404c',borderRadius:12,overflow:'hidden',background:'#131b23'}}><Panel scene={scene} time={now-scene.start}/></div>}
  {scene&&mode==='presenter'&&<div style={{position:'absolute',left:35,top:85,fontSize:23,padding:'12px 18px',background:'#111a22df',borderLeft:'4px solid '+yellow,maxWidth:430}}>{scene.title}</div>}
  <div style={{position:'absolute',top:0,left:0,right:0,height:44,background:'#080d12',display:'flex',gap:5,padding:'5px 12px',alignItems:'stretch'}}>{chapters.map((c,i)=><div key={i} style={{flex:1,fontSize:14,textAlign:'center',display:'grid',placeItems:'center',border:'1px solid #34404a',borderRadius:5,color:i===chapter?bg:muted,background:i===chapter?yellow:'transparent',fontWeight:i===chapter?900:500}}>{c.title}</div>)}</div>
  <div style={{position:'absolute',top:42,left:0,height:2,width:`${frame/durationInFrames*100}%`,background:yellow}}/>
  <div style={{position:'absolute',bottom:0,left:0,right:0,height:78,background:'linear-gradient(transparent,#080d12e6)'}}/>
  {cue&&<div style={{position:'absolute',bottom:22,left:170,right:100,textAlign:'center',fontSize:27,fontWeight:800,textShadow:'0 2px 4px #000,0 0 8px #000',lineHeight:1.4}}>{cue.text.split(/(一人公司|真实用户|反复使用|具体的问题|持续积累|不一定)/g).map((x,i)=><span key={i} style={{color:i%2?yellow:white}}>{x}</span>)}</div>}
 </AbsoluteFill>
};
