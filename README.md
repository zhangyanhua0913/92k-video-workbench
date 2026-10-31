# 92k 视频创作工作台

**V2 交互原型 · Windows + Agent 源码试用版**

当前版本见仓库根目录VERSION，原型页面右上角也会显示发行版本。

口播剪辑、素材解说、AI视频生成、真人混搭四个入口。提供可点击原型及三个相关Skill的源码。

**V2页面尚未接通制作执行器。** 草稿只在页面内存，刷新重置；素材卡、播放器、报价和交付均为示例。附带Skill可通过Agent及自己的CLI/工具页使用，不能把原型演示当作真实成片功能。

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

> 读取这个仓库根目录的SKILL.md，先检查更新，再根据我的输入选择制作流程。V2页面按原型使用；真实制作读取对应子Skill并核对依赖。先用本地免费能力，不擅自调用付费服务。

本仓库无需再单独安装三个同名Skill。总入口按需读取内嵌的子包，避免覆盖用户原有的独立Skill。

## 范围

| 入口 | 随包能力 | 当前边界 |
|---|---|---|
| 口播剪辑 | talking-edit，字幕/剪切/变速/包装/导出 | 需依赖；复杂包装由Agent制作 |
| 素材解说 | narration-footage，发现/下载登记/来源核验 | 搜索与画面判断由Agent完成；无独立自动搜索选段服务 |
| AI生成 | 92k-video-director，脚本分镜/接口编排/审阅/合成 | 需用户自己的92k服务Key及实际预算授权 |
| 真人混搭 | talking-edit + 素材与资料讲解适配 | Agent编排，不承诺全自动 |

详见[快速开始](docs/quickstart.md)、[依赖与许可](docs/dependencies.md)、[版本与更新](docs/updates.md)、[验证范围](docs/validation.md)、[交互设计](docs/interaction-design.md)。

## 更新与本地改动

启动预览/子工具前检查官方main。能快进且不会覆盖本地改动时更新；冲突、分叉、离线、活动会话或自定义分支时保留原版。不会reset、clean或自动stash。`VERSION`与Git提交一起发布，可用 `python scripts/workbench.py version` 查看。检查是否同版以提交为准，避免仅比较版本文字漏掉修订。

显式离线/固定版本：`python scripts/workbench.py --no-update preview`。ZIP下载不具备Git更新能力；有本地改动时不保证自动跟上远端，见[更新说明](docs/updates.md)。

## 开源范围

仅含本工作台、三个相关Skill及必要模板、说明和测试。不含n8n/ComfyUI安装、模型、服务端、私有部署、用户数据、研究素材或Key。FFmpeg、Whisper、FredTalk、Remotion等按需另装，遵守各自许可。自有代码MIT；外部服务可能收费，开源客户端不提供免费模型额度。
