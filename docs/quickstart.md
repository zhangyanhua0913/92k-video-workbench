# 三种使用方式

1. 只看V2原型：README中的clone和preview命令即可。不需要模型环境，没有真实上传/保存/付费。
2. Agent制作：先读根SKILL.md，选择子Skill；项目目录放仓库外，不把素材放进源码。下面仅是依赖诊断，不会提交付费任务：

```sh
python scripts/workbench.py skill talking-edit -- doctor
python scripts/workbench.py skill 92k-video-director -- doctor
python scripts/workbench.py skill narration-footage -- --help
```

实际命令以各子Skill的SKILL.md及references为准。narration-footage没有doctor，使用help了解discover/download/audit。付费任务仅在用户配置自己的Key并确认当前方案/预算后执行。根包装器不替代子工具自己的审阅与原单门禁。

完整仓库是一个总入口Skill，子Skill无需另外复制到宿主同名安装目录。若只取子Skill可单独运行，但不带根包装器的版本检查；不要据此承诺自动更新。

3. 真实统一工作台：`python scripts/workbench.py open`，打开输出完整URL。默认18737；四入口创建项目或登记旧工程，填写包外保存目录。口播/混搭同页显示成熟编辑器，生成同页显示director；素材解说有独立文案/素材/来源表和本地合成。

口播最短流程：检查依赖→导入含音轨视频→转写或导入SRT→保存字幕/剪切/语速→选择自然口播或暗金模板→打开粗剪审阅并确认→制作所需包装和审阅→导出→在成片审阅中实际听看后确认。已有SRT不必安装转写模型；新工程本地剪切不要求FredTalk。

素材解说：导入自己的旁白和有权使用的画面→逐镜填写来源/版本/匹配理由、时长与字幕→保存→核验→确认素材方案→合成→查看实际输出→最终审阅。旁白不由规则文案伪造，找素材仍由Agent完成。

需要继续时从“我的项目”进入；不要收藏子工具临时会话。多页面版本冲突须刷新核对，不强制覆盖。API和Agent接续见[统一接口](workspace-api.md)。源码更新前停止工作台，保留工程和原任务。
