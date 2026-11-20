---
name: footage-mix
description: 用本地运动相机素材库（E:\自媒体\原始素材库）制作混剪视频：给一段文案，自动配音、按句匹配画面、烧字幕配乐，输出横屏 1080p 成片。适用于「用我的素材库剪一条视频」「这条文案帮我配上画面」「按文案做个混剪」这类需求。
agent_created: true
---

# 本地素材混剪

## 用途

一段文案 + 本地素材库 → 一条横屏成片。画面按文案**大致匹配**，不追求严格对应。

素材库已 100% 打标（5567 个单元，11 维中文标签 + 画面描述），**不要靠文件名猜内容，也不要抽帧试看**——直接读 `desc` 和 `attr` 就够。

## 核心分工（先记住这条）

**语义判断归 Agent，确定性计算归脚本。**

脚本不会猜「我妈端盆接漏水」该配什么画面——字面匹配在这套素材上已经验证失败（和任何 `desc` 都没有共同字符串）。所以流程里有一道**人工/AI 标注**，必须在配音之前做。

## 四步流程

### 1. 先切句（不花钱）

```bash
cd "E:/自媒体/skills/footage-mix"
python scripts/mix.py --script 文案.txt --out "项目目录" --dry-run
```

产出 `句子清单.txt`，带序号。**这个序号是后面所有对齐的基准**，不要自己数句。

### 2. Agent 逐句打标签 → `文案标签.json`

按 `references/tagging.md` 的受控词表标注。只标有把握的维度，留空不扣分。

```json
{"sentences": [
  {"i": 0, "text": "...", "场景": "室内", "情绪": "冷清", "motion": "low"}
]}
```

标完**把标注摘要给用户看一眼**，确认方向没错再往下——后面配音要花钱。

### 3. 算时间轴 + 配画面

```bash
python scripts/mix.py --script 文案.txt --tags 文案标签.json --out "项目目录" --privacy public
```

做的事：文案切块 → 逐块调配音 → 测实际时长 → 块内按字数分句对齐 → 每句按标签挑素材 → 写 `timeline.json`。

**这一步会真的调用付费配音**，跑之前确认用户授权。每块一次调用，不要自己决定批量付费。

### 4. 看报告，再渲染

```bash
cat "项目目录/匹配报告.txt"
```

每句配了哪段、取原片第几秒、命中哪些标签。**这是唯一能在花渲染时间前发现「文不对画」的地方。**

```bash
python scripts/render.py --project "项目目录" --bgm "音乐.wav"
python scripts/render.py --project "..." --no-subs      # 不要字幕
python scripts/render.py --project "..." --duck         # 旁白压 BGM（默认不压）
python scripts/render.py --project "..." --cpu          # NVENC 出问题时的退路
```

一次转码，不产生碎片文件。默认 1920×1080 / 30fps / h264_nvenc。

## 前置自检

```bash
python scripts/check.py
```

唯一允许的 WARN 是「配音服务没响应」，那就先起服务：

```bash
cd E:/n8n/92k-video-workbench && python scripts/workbench.py open --port 18737
```

## 参数速查

| 参数 | 作用 |
|---|---|
| `--privacy public` | **默认**，只用标「可公开」的 174 条原片 |
| `--privacy all` | 全部放开，含带娃/家人画面 |
| `--folders rural,food` | 限定题材：rural / kids / family / talk / city / scenery / food |
| `--max-shot 4.5` | 单个片段最长秒数，想更快就调小 |
| `--no-voice` | 跳过配音，用 `配音/*.mp3` 里已有的 |
| `--bgm-lufs -26` | BGM 响度，比人声低 8dB 左右；觉得音乐太小就调到 -22 |
| `--bgm-volume 1.0` | 归一化后再微调 |

## 硬约束

1. **原片只读**：不剪切、不转码落盘、不移动、不改名、不删除。取片段一律 `-ss/-t` 现取。
2. **不留图**：素材库不产生任何缩略图/预览图/图片缓存。
3. **隐私开关要问**：默认 `public`。放开到 `all` 必须用户明确说过——227 条原片标了「家庭不宜公开」。
   ⚠️ 隐私是**打标时判的**，不是人工逐条核过的。要发出去的成片，建议用户抽查几条。
4. **配音要授权**：`mix.py` 会真调付费接口。
5. **不覆盖**：`--out` 目录已存在就换个名字，别把上一版盖掉。

## 色彩：HDR 必须转 SDR（已内置）

素材库 382 条是 **HEVC 10bit / HLG（arib-std-b67）真 HDR**，27 条 h264 是 SDR。`render.py` 逐片 `ffprobe` 查 `color_transfer`，只对 HDR 片段插 tonemap，SDR 原样过，输出统一打 bt709 标记。

不转的后果（实测过）：8bit 直接截断，黄色标线发白、绿色车漆寡淡，整片发灰；发到手机端还可能整体偏亮。

## 已知精度限制（如实告诉用户）

- **字幕时间**按块内字数比例估，与真实语音有 0.5–1 秒级偏差。要精确得装 `faster_whisper` 做词级对齐（当前环境没装）。
- **`desc` 偶尔和画面有出入**（打标是模型看图写的）。关键镜头建议渲染后抽帧看一眼。
- **可公开池里「家人」只有 7 个**，讲家庭故事时画面基本靠「场景 + 情绪」贴，不是靠人物对应。

## 出问题怎么查

| 症状 | 原因 | 处理 |
|---|---|---|
| 素材池是空的 | privacy/folders 过滤太狠 | 去掉 `--folders`，或改 `--privacy all` |
| 配音失败 | 工作台没起 / 令牌失效 | 跑 `check.py` 看那两行 |
| 时间轴不连续 | timeline.json 被手改过 | 重跑 `mix.py` |
| 整片画面雷同 | 素材池小 / 标签标得太集中 | 标签加维度，或放开 privacy |
| `asplit ... unconnected` | 滤镜链分支没用上 | 已在脚本里修，别再手改 filter |
| BGM 听不见 | BGM 本身太安静 | 调 `--bgm-lufs -20`，或加 `--duck` |

## 细节文档

- 素材库字段与筛选口径 → `references/library.md`
- 逐句标注规范与词表 → `references/tagging.md`
- 配音接口调用 → `references/voice.md`
