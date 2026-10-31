# 92k 视频创作工作台

**V2 本地制作预览版 · Windows + Agent 协作**

当前版本见仓库根目录VERSION，原型页面右上角也会显示发行版本。

口播剪辑、素材解说、AI视频生成、真人混搭四个入口，统一登记项目、保存进度并调用随包制作工具。

`open` 启动真实本地工作台；`preview` 保留原静态演示，两者明确分开。口播与生成复用原工具编辑页并嵌入工作台，字幕、预算和任务仍由原工程保存。复杂包装、搜索选段及生成编排需要 Agent；不是独立全自动剪辑软件。云服务须配置自己的 Key，并确认实际预算，未做本轮真实云付费验收。

真实工作台沿用原V2四入口各自六步：当前步骤编辑、右侧方案、底部保存/上一步/下一步。口播为“导入视频→字幕与粗剪→选择风格 Skill→包装与配乐→成片审看→导出交付”。恢复/重试/任务详情和Agent接续默认折叠。刷新及重新进入恢复已保存的步骤；进入下一步只保存草稿，不授权制作或付费。步骤或主要交互的后续变动须先说明并取得用户确认，见[维护约定](AGENTS.md)。

## 开始真实制作

```sh
python scripts/workbench.py open
```

打开命令返回的完整本机 URL。默认端口18737，`--port`可更改；地址中的临时会话不要分享。四入口可创建工程或手动登记旧工程。默认工程目录为用户目录下 `92k-video-projects`，可以创建时指定其他绝对路径。

工程与素材在源码之外；最近项目索引和临时会话默认在 `~/.92k-video-workbench`，可用 `open --home ABS_DIRECTORY` 或 `WORKBENCH_HOME` 更改。同一数据目录只允许一个服务。关闭页面不取消任务；Ctrl+C停止服务并等待已启动的本地步骤，不删除项目。

自然口播导出需要 FFmpeg/ffprobe，有字幕可直接导入 SRT；本地转写另需 Whisper 环境。暗金模板另需 Node/Remotion；复杂风格由 Agent 交付真实片段。素材解说支持本地音频、图片及视频，当前固定1280×720，旁白与镜头总时长须一致。首次依赖配置见[依赖说明](docs/dependencies.md)。

## 快速预览

Python 3.10+、Git：

```sh
git clone https://github.com/zhangyanhua0913/92k-video-workbench.git
cd 92k-video-workbench
python scripts/workbench.py preview
```

打开输出的本地URL。默认端口18735；占用时加 `--port 18736`。只绑定127.0.0.1并服务prototype目录。Ctrl+C停止，不删除数据。看原型无需Key、FFmpeg、Node、n8n或ComfyUI。

## 让Agent使用

可把整个仓库clone到你的Agent Skill安装目录，文件夹名保留 `92k-video-workbench`，重启/刷新Agent技能发现。Codex常用目录为用户目录下 `.codex/skills/92k-video-workbench`；其他宿主请按各自机制安装，尚未逐一验收。

也可直接告诉Agent：

> 读取这个仓库根目录的SKILL.md，先检查更新，打开真实工作台，根据我的输入选择制作流程。读取对应子Skill并核对依赖，用统一API保存方案和打开审阅。先用本地免费能力，不擅自调用付费服务。

本仓库无需再单独安装三个同名Skill。总入口按需读取内嵌的子包，避免覆盖用户原有的独立Skill。

## 范围

| 入口 | 随包能力 | 当前边界 |
|---|---|---|
| 口播剪辑 | 字幕/剪切/变速/包装/MP4和SRT | 本地无包装及暗金模板；复杂包装由Agent制作 |
| 素材解说 | 持久化文案/旁白/镜头/来源、许可记录和本地合成 | 搜索与画面判断由Agent完成；不内置自动搜片服务 |
| AI生成 | 分镜/人物声音/报价预算/原任务查询/素材采纳/合成 | 需自己的92k服务Key及实际预算授权；本轮仅免费模拟验证 |
| 真人混搭 | 真人底座＋资料映射、片段替换及包装审阅 | 本地资料片段可直接登记；复杂同屏仍由Agent制作 |

详见[快速开始](docs/quickstart.md)、[统一API与Agent接续](docs/workspace-api.md)、[依赖与许可](docs/dependencies.md)、[版本与更新](docs/updates.md)、[验证范围](docs/validation.md)、[交互设计](docs/interaction-design.md)。

## 更新与本地改动

启动预览/子工具前检查官方main。能快进且不会覆盖本地改动时更新；冲突、分叉、离线、活动会话或自定义分支时保留原版。不会reset、clean或自动stash。`VERSION`与Git提交一起发布，可用 `python scripts/workbench.py version` 查看。检查是否同版以提交为准，避免仅比较版本文字漏掉修订。

显式离线/固定版本：`python scripts/workbench.py --no-update preview`。ZIP下载不具备Git更新能力；有本地改动时不保证自动跟上远端，见[更新说明](docs/updates.md)。

## 开源范围

仅含本工作台、三个相关Skill及必要模板、说明和测试。不含n8n/ComfyUI安装、模型、服务端、私有部署、用户数据、研究素材或Key。FFmpeg、Whisper、FredTalk、Remotion等按需另装，遵守各自许可。自有代码MIT；外部服务可能收费，开源客户端不提供免费模型额度。
