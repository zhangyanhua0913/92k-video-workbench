---
name: 92k-video-workbench
description: 使用92k视频创作工作台V2原型，或按口播剪辑、素材解说、AI生成、真人混搭四类需求调用随包制作Skill；启动前检查版本并保护用户本地改动。
---

# 92k 视频创作工作台

本目录是完整Git仓库。先运行 `python scripts/workbench.py check-update`，读取JSON结果，再重新读取更新后的本文件和所选子Skill指令。每个新制作会话检查一次；进行中的项目/审阅服务先结束或暂停再更新，不在单个项目每一步中反复升级。

`updated/unchanged` 可继续；`offline/archive_install/local_changes/local_history/custom_branch/different_remote/active_session` 说明没有升级，告诉用户当前版本及原因，保留原目录与任务，可以继续现有版本。禁止为更新运行reset --hard、clean、强制拉取、自动stash或覆盖用户改动。ZIP安装不支持Git自动更新；建议git clone。用户要固定版本或离线时用 `--no-update`。

预览：`python scripts/workbench.py preview --port 18735`，打开返回的回环URL。V2仍是交互原型，没有真实搜索、保存、报价或制作后台；内存草稿刷新会重置。不要把原型中的确认当作真实付费授权或项目审批。

制作按输入选择并读取对应指令：
- 已录真人视频 → [talking-edit](skills/talking-edit/SKILL.md)。
- 文案/旁白配真实素材 → [narration-footage](skills/narration-footage/SKILL.md)。
- 生成新画面/数字人 → [92k-video-director](skills/92k-video-director/SKILL.md)。
- 真人穿插资料 → talking-edit底座，结合narration-footage及资料讲解风格。

子工具统一入口：`python scripts/workbench.py skill SKILL_NAME -- 原CLI参数`。工具启动会检查更新，但活动的包装器会话会阻止其他包装器更换源码。若更新成功，执行前重新读取该子Skill。直接调用子CLI会绕过自动更新和会话保护，仅用于已固定版本的任务。

原口播六项风格保留在talking-edit包中，复杂包装需Agent；V2页面尚未接通这些子执行器。先doctor/核对依赖，缺依赖说明用途并在包外准备。项目、素材、Key和运行数据放仓库外；不复制作者路径、凭据或历史预算。使用者自行提供有权使用的素材与服务Key，付费遵循子Skill当前报价和明确授权，未知原单只查不重提。

普通用户只拉取更新，不启用 `install_author_watch.py` 或 `publish.py --enable-author`。自定义内容优先放Git忽略的user/目录或包外；若改了核心源码，更新冲突时保留修改并请用户决定合并。阅读[版本与更新](docs/updates.md)了解限制。
