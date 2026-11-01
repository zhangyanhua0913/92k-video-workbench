---
name: 92k-video-workbench
description: 打开92k视频工作台，统一管理本地工程，按口播剪辑、素材解说、AI生成、真人混搭四类需求调用随包制作工具；由Agent协作制作、页面编辑审看，保护本地项目和未知原任务。
---

# 92k 视频创作工作台

先遵守根AGENTS.md：原V2四入口各六步是用户已确认的流程。不得因技术接入或Agent操作改名、重排、合并步骤；确需改变时先说明并取得用户确认。真实页按步骤编辑，诊断/恢复/重试/接续在默认折叠的项目工具。api/preferences只保存UI位置/创意意向，不授权执行；Agent可读取当前步骤，不能把跳步或保存草稿当预算/素材/最终确认。

本目录是完整Git仓库。先运行 `python scripts/workbench.py check-update`，读取JSON结果，再重新读取更新后的本文件和所选子Skill指令。每个新制作会话检查一次；进行中的项目/审阅服务先结束或暂停再更新，不在单个项目每一步中反复升级。

`updated/unchanged` 可继续；`offline/archive_install/local_changes/local_history/custom_branch/different_remote/active_session` 说明没有升级，告诉用户当前版本及原因，保留原目录与任务，可以继续现有版本。禁止为更新运行reset --hard、clean、强制拉取、自动stash或覆盖用户改动。ZIP安装不支持Git自动更新；建议git clone。用户要固定版本或离线时用 `--no-update`。

真实制作：`python scripts/workbench.py open --port 18737`，打开返回的完整回环URL；同一home已有服务时使用其本机私密session描述，不重复启动。页面四入口创建/登记工程，项目存源码之外，默认用户目录的92k-video-projects。`preview --port 18735`仍只看原静态演示，不能把演示确认当作真实授权。

统一操作优先使用 `python scripts/workbench.py api --path /api/... --input ABS_JSON`，详见[统一API](docs/workspace-api.md)。先GET当前工程和原任务，再按明确动作修改或执行；同一接口供页面及Agent使用。调用返回job后持续查询原项目，不重复提交来猜执行结果。复杂创作的job可能只是Agent任务简报，不是成片。

完整独立组合审看片通过 `register-preview` 登记到对应工程，清单须绑定工程、基础版本及实际文件摘要；原步骤的成片审看/导出交付会显示，不能冒充内部渲染或用户已确认。具体输入和限制见统一API。

需要用户审阅时调用action=review，记录返回id；用tool接口获得该项目审阅页路径，工作台页面可直接点“审阅…”进入同一请求。保持当前Agent工作，分段查询同一project/reviews直至用户决定，不在等待时结束制作回合。未确认不是同意；不得代确认真实预算、素材或最终认可。素材工程assets/final审阅通过其自身接口完成。

制作按输入选择并读取对应指令：
- 已录真人视频 → [talking-edit](skills/talking-edit/SKILL.md)。
- 文案/旁白配真实素材 → [narration-footage](skills/narration-footage/SKILL.md)。
- 生成新画面/数字人 → [92k-video-director](skills/92k-video-director/SKILL.md)。
- 真人穿插资料 → talking-edit底座，结合narration-footage及资料讲解风格。

子工具统一入口：`python scripts/workbench.py skill SKILL_NAME -- 原CLI参数`。工具启动会检查更新，但活动的包装器会话会阻止其他包装器更换源码。若更新成功，执行前重新读取该子Skill。直接调用子CLI会绕过自动更新和会话保护，仅用于已固定版本的任务。

原口播六项风格保留。新口播默认local-cuts和none，避免基础导出强依赖FredTalk；粗剪审阅确认后才能导出。暗金按钮明确代表本地模板制作及技术审阅，不记最终听看。复杂风格需Agent，使用子Skill生成真实工程/片段并登记结果。风格版本变化阻止继续包装/导出，核对差异后显式adopt-style；没有自动保存旧执行器副本，需旧代码时用固定tag安装。

素材解说：通过统一工程保存script、narration及其hash、shots（素材相对路径及hash、入点/时长、字幕、原页面、发布者、产品版本、匹配理由、许可和实际审看）。Agent完成搜索和语义判断；本地导入不代表已采纳。先audit，再打开assets确认、render，最后final认可。当前合成固定横版720p，不允许旁白被截断。混搭可attach-source映射本地资料片段；复杂同屏继续用talking-edit的render-scene/attach-scene，局部替换后重新审阅。

先doctor/核对依赖，缺依赖说明用途并在包外准备。项目、素材、Key和运行数据放仓库外；不复制作者路径、凭据或历史预算。使用者自行提供有权使用的素材与服务Key，付费遵循子Skill当前报价和明确授权，未知原单只查不重提。直接调用旧CLI会绕过统一执行记录/风格锁；不要与工作台同时操作同一工程。

普通用户只拉取更新，不启用 `install_author_watch.py` 或 `publish.py --enable-author`。自定义内容优先放Git忽略的user/目录或包外；若改了核心源码，更新冲突时保留修改并请用户决定合并。阅读[版本与更新](docs/updates.md)了解限制。

常用参数：GET /api/defaults?mode=talk|hybrid 读取本机新项目默认；POST同地址用mode/revision/patch显式保存speed、subtitle_burn、transcribe_language、packaging。只影响后续创建的对应类型项目，不自动改旧工程、执行或批准任务。用户当前要求变速时另走项目update及原审阅/合成；可以只保存用户明确指定的默认字段，不能擅自把临时参数学成习惯。配置中心可保存、记住当前参数和恢复原始默认，六步不变。

用户本机可显式保存Agent创意偏好：制作前读取用户工作台目录 ~/.92k-video-workbench/agent-style-defaults.json（存在且schema=1时）；仅在对应mode和style匹配、用户未另指定时使用。它是创意方向，不替代项目参数或审阅授权；按当前素材重新规划内容和时码，不复制旧视频。文件留本机，不包含凭据。用户选择source_display时依源视频旋转后的实际画幅制作，不能把720p成片放大当原分辨率。
