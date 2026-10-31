import React from 'react';
import {Composition,registerRoot} from 'remotion';
import {GoldScene} from './Gold';

const Root:React.FC=()=> <Composition id="GoldExample" component={GoldScene} durationInFrames={150} fps={30} width={1920} height={1080} defaultProps={{title:'这里填写本段标题',eyebrow:'本期主题',items:['步骤一','步骤二','步骤三'],variant:'chain' as const}}/>;
registerRoot(Root);
