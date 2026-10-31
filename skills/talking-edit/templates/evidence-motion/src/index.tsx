import React from 'react';
import {Composition,registerRoot} from 'remotion';
import {Evidence} from './Evidence';
const Root=()=> <Composition id="EvidenceExample" component={Evidence} durationInFrames={240} fps={30} width={1280} height={720} defaultProps={{source:'source.mp4',chapters:[{at:0,title:'本期主题'}],cues:[],scenes:[{start:0,end:8,title:'本段标题',chapter:'本期主题',layout:'split' as const,kind:'flow' as const,items:['第一步','第二步','第三步']}]}}/>;
registerRoot(Root);
