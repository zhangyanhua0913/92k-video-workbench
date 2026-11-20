# footage-mix：工作台适配 v0.1

本地自拍素材库混剪，从 `E:\自媒体\原始素材库` 读索引，按文案逐句配画面。**不联网搜素材**，与 `narration-footage`（网络素材）分工不同：讲自己拍的东西用本 Skill，讲别人的东西用 narration-footage。

## 当前接入状态（如实）

| 项 | 状态 |
|---|---|
| 独立 CLI 出片 | ✅ 可用，已跑通 60 秒成片 |
| 工作台路由登记 | ✅ 已写入主 SKILL.md |
| 工作台工程（project/assets/render） | ❌ 未接入，产物是独立目录，不建工作台工程 |
| 审阅页（action=review / register-preview） | ❌ 未接入，成片为本地 mp4，需人工打开看 |

也就是说：**本 Skill 目前是"旁挂工具"，不是工作台四入口的工程流程。** 交付物在项目目录里（`timeline.json` / `匹配报告.txt` / `成片.mp4`），不进 `92k-video-projects`。接入工程和审阅页需要另外做，不要声称已经能点"审阅…"。

## 调用

```bash
python "E:/n8n/92k-video-workbench/scripts/workbench.py" skill footage-mix -- <原CLI参数>
```

或直接跑子脚本（已固定版本的任务）：

```bash
python skills/footage-mix/scripts/mix.py --script 文案.txt --tags 文案标签.json --out 项目目录
python skills/footage-mix/scripts/render.py --project 项目目录 --bgm 音乐.mp3
```

## 必须遵守

- **原片只读**：`E:\原素材库` 下 410 条 4K 原片不切、不转码落盘、不移动、不改名、不删。取片段一律 `-ss/-t` 现取。
- **不留图**：素材库不产生缩略图/预览图。
- **隐私默认 public**：只用 174 条标「可公开」的原片。放开 `--privacy all` 必须用户明确说，227 条标了「家庭不宜公开」；隐私是打标时模型判的，未人工逐条核，发布前要抽查。
- **配音要授权**：`mix.py` 真调付费接口（火山 seed-icl-2.0，音色 `S_FwhCVmzP1`），每块一次调用。先 `--dry-run` 切句、确认标签，再跑配音。
- **不覆盖**：`--out` 换目录名，不盖上一版。

## 语义谁来做

脚本不做语义判断。字面匹配在这套素材上验证失败（文案与 `desc` 无共同字符串）。**Agent 必须先读文案逐句打标签**（`references/tagging.md` 受控词表），脚本只按标签筛。跳过标注直接跑，出来的是空镜踩点模式，画面与文案无关。

## 已知限制

- 字幕时间按块内字数比例估，与真实语音有 0.5–1 秒偏差；要精确得装 `faster_whisper` 做词级对齐。
- `desc` 是模型看图写的，偶尔与实际画面有出入；关键镜头渲染后抽帧核一眼。
- 可公开池里「家人」只有 7 个，讲家庭故事时画面靠「场景+情绪」烘托，不靠人物对应。
- 整片内每条原片只用一次，池子耗尽才回退允许复用。
