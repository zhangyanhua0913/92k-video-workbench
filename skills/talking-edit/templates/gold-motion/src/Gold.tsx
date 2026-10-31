import React from 'react';
import {AbsoluteFill,Easing,interpolate,spring,useCurrentFrame,useVideoConfig} from 'remotion';

// Reusable visuals only. The agent supplies current-project text and timing.
export type GoldSceneProps={title:string; eyebrow?:string; items?:string[]; variant?:'title'|'compare'|'chain'|'triangle'|'bars';};
export type GoldCue={start:number;end:number;text:string};
const gold='#ffc53d',cream='#fff4e0',red='#ff6868',cyan='#4cc9f0';
const clamp={extrapolateLeft:'clamp' as const,extrapolateRight:'clamp' as const};
export const GoldScene:React.FC<GoldSceneProps>=({title,eyebrow='',items=[],variant='title'})=>{
 const frame=useCurrentFrame(),{fps,width,height}=useVideoConfig();
 const time=frame/fps;const entry=(delay:number)=>spring({frame:frame-Math.round(delay*fps),fps,config:{damping:17,stiffness:120}});
 const line=interpolate(time,[0,.6],[0,1],{...clamp,easing:Easing.out(Easing.cubic)});
 const sizes=items.slice(0,4); const scale=width/1920;
 return <AbsoluteFill style={{background:'#0b0d12',fontFamily:'Microsoft YaHei, sans-serif',color:cream,overflow:'hidden'}}>
  <AbsoluteFill style={{opacity:.17,backgroundImage:`linear-gradient(${gold}44 1px,transparent 1px),linear-gradient(90deg,${gold}44 1px,transparent 1px)`,backgroundSize:`${76*scale}px ${76*scale}px`,transform:`perspective(900px) rotateX(58deg) translateY(${(frame*.3)%76}px) scale(1.8)`,transformOrigin:'center 70%'}}/>
  {[gold,cyan,red].map((color,i)=><div key={color} style={{position:'absolute',left:`${20+i*30+Math.sin(time*.6+i)*4}%`,top:`${20+i*16+Math.cos(time*.5+i)*5}%`,width:'38%',aspectRatio:'1',borderRadius:'50%',filter:`blur(${45*scale}px)`,background:`radial-gradient(circle,${color}50,transparent 70%)`,opacity:.55}}/>)}
  <div style={{position:'absolute',left:0,right:0,height:height*.18,top:(frame*4)%(height+350)-200,background:'linear-gradient(transparent,#ffc53d18,transparent)'}}/>
  <AbsoluteFill style={{background:'radial-gradient(ellipse at center,transparent 35%,#0009 100%)'}}/>
  <div style={{position:'absolute',top:'12%',left:'8%',right:'8%',textAlign:'center',color:gold,fontSize:30*scale,fontWeight:800,letterSpacing:3*scale,opacity:line}}>{eyebrow}</div>
  <div style={{position:'absolute',top:variant==='title'?'35%':'20%',left:'7%',right:'7%',textAlign:'center',fontSize:(variant==='title'?100:64)*scale,fontWeight:900,lineHeight:1.25,textShadow:'0 4px 24px #000',opacity:line}}>
   {Array.from(title).map((c,i)=>{const p=entry(.03*i);return <span key={i} style={{display:'inline-block',opacity:Math.min(1,p),transform:`scale(${.5+.5*p})`}}>{c===' '?'\u00a0':c}</span>})}
  </div>
  {variant==='chain'&&<div style={{position:'absolute',top:'43%',left:'7%',right:'7%',display:'flex',justifyContent:'center',alignItems:'center',gap:22*scale}}>{sizes.map((x,i)=><React.Fragment key={i}><div style={{minWidth:260*scale,padding:24*scale,textAlign:'center',border:`2px solid ${i===sizes.length-1?gold:'#ffffff55'}`,borderRadius:20*scale,background:i===sizes.length-1?'#ffc53d30':'#ffffff12',boxShadow:i===sizes.length-1?'0 0 35px #ffc53d55':'none',fontSize:34*scale,fontWeight:800,opacity:entry(.5+i*.45),transform:`translateY(${(1-entry(.5+i*.45))*30}px)`}}>{x}</div>{i<sizes.length-1&&<span style={{fontSize:48*scale,color:gold,opacity:entry(.8+i*.45)}}>→</span>}</React.Fragment>)}</div>}
  {variant==='compare'&&<div style={{position:'absolute',top:'40%',left:'24%',right:'24%',display:'flex',flexDirection:'column',gap:20*scale}}>{sizes.map((x,i)=><div key={i} style={{display:'flex',gap:30*scale,alignItems:'center',opacity:entry(.5+i*.35),fontSize:33*scale,fontWeight:800}}><span style={{color:red}}>✕</span><span style={{flex:1,borderBottom:`2px solid ${red}`}}>{x}</span><span style={{color:gold}}>→</span><span style={{color:cream}}>可重新思考</span></div>)}</div>}
  {variant==='triangle'&&<div style={{position:'absolute',left:'27%',right:'27%',top:'36%',height:'35%',display:'flex',alignItems:'center',justifyContent:'space-around'}}>{sizes.slice(0,3).map((x,i)=><div key={i} style={{width:190*scale,height:190*scale,borderRadius:'50%',display:'grid',placeItems:'center',border:`2px solid ${gold}`,background:'#ffc53d22',boxShadow:`0 0 ${25+10*Math.sin(time*2)}px #ffc53d66`,fontSize:29*scale,fontWeight:800,opacity:entry(.5+i*.35)}}>{x}</div>)}</div>}
  {variant==='bars'&&<div style={{position:'absolute',top:'40%',left:'25%',right:'25%'}}>{sizes.map((x,i)=><div key={i} style={{marginBottom:26*scale,fontSize:28*scale,fontWeight:800}}><div>{x}</div><div style={{height:18*scale,marginTop:8*scale,background:'#ffffff22',borderRadius:20}}><div style={{height:'100%',width:`${Math.min(1,entry(.5+i*.35))*100}%`,background:`linear-gradient(90deg,${cyan},${gold})`,borderRadius:20}}/></div></div>)}</div>}
 </AbsoluteFill>;
};

// Optional global layer. Cue-level timing is real; intra-cue highlights are an estimate.
export const GoldChrome:React.FC<{chapters?:{at:number;label:string}[];cues?:GoldCue[];watermark?:string;showEstimatedHighlight?:boolean}>=({chapters=[],cues=[],watermark='',showEstimatedHighlight=false})=>{
 const frame=useCurrentFrame(),{fps,width,durationInFrames}=useVideoConfig();const now=frame/fps,scale=width/1920;
 const chapter=chapters.filter(c=>c.at<=now).at(-1);const cue=cues.find(c=>c.start<=now&&now<c.end);
 const chars=Array.from(cue?.text||'');const fraction=cue?Math.max(0,Math.min(1,(now-cue.start)/(cue.end-cue.start))):0;
 return <AbsoluteFill style={{pointerEvents:'none',fontFamily:'Microsoft YaHei, sans-serif'}}>
  <div style={{position:'absolute',top:0,left:0,height:6*scale,width:`${100*frame/durationInFrames}%`,background:`linear-gradient(90deg,#ff9f1c,${gold})`,boxShadow:`0 0 14px ${gold}`}}/>
  {chapter&&<div style={{position:'absolute',top:40*scale,left:50*scale,color:cream,fontSize:27*scale,fontWeight:800,background:'#0b0d12b8',border:`1px solid ${gold}88`,borderRadius:10*scale,padding:`${8*scale}px ${16*scale}px`}}>{chapter.label}</div>}
  {cue&&<div style={{position:'absolute',left:'8%',right:'8%',bottom:38*scale,textAlign:'center',fontSize:44*scale,fontWeight:900,color:cream,textShadow:'0 2px 8px #000',background:'#07090cd9',borderRadius:12*scale,padding:10*scale}}>{chars.map((c,i)=><span key={i} style={{color:!showEstimatedHighlight||i<chars.length*fraction?cream:'#ffffff66',textShadow:showEstimatedHighlight&&i<chars.length*fraction?'0 0 14px #ffc53d99':'none'}}>{c}</span>)}</div>}
  {watermark&&<div style={{position:'absolute',right:48*scale,bottom:120*scale,color:cream,fontSize:22*scale,fontWeight:700,opacity:.8}}>{watermark}</div>}
 </AbsoluteFill>
};
