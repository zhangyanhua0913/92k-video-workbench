# 素材库读取口径

库根：`E:\自媒体\原始素材库`　原片根：`E:\原素材库`（从 `tools/config.json` 的 `disks.E.src_root` 读，不要硬编码）

## 两个索引

| 文件 | 内容 |
|---|---|
| `索引/videos.json` | 410 条原片，`["videos"]` |
| `索引/shots.json` | 5567 个素材单元，`["shots"]` |

## 单元字段（`shots.json` 一行）

| 字段 | 说明 |
|---|---|
| `id` | `E:DJI_0006:w001` |
| `video_id` | 外键 → videos |
| `start` / `end` | 在原片里的秒数，左闭右开 |
| `duration` | 1.53 ~ 14.93 秒，中位 4.00 |
| `motion` | 片内相对运动：low / mid / high |
| `motion_abs` | 全库绝对运动：跨片可比 |
| `motion_score` | 数值，low < 16.93 / high > 37.85 |
| `desc` | 中文画面描述（混剪主要靠它） |
| `attr` | 11 维标签字典 |
| `tags` | attr 摊平后的词表 |
| `folders` | 虚拟分组 key 数组，可多归属 |
| `usable` | **全为 null**，尚未人工审校，不要依赖 |

`attr` 的 11 个键：`场景 / 动作 / 人物 / 景别 / 机位 / 时间 / 情绪 / 主题 / 可见度 / 质量`

## 原片字段（`videos.json` 一行）

| 字段 | 说明 |
|---|---|
| `relpath` | 相对原片根，正斜杠，用时换 `os.sep` |
| `privacy` | **`可公开` / `家庭不宜公开`**（9 条为 null，按不宜公开处理） |
| `shoot_date` | `YYYY-MM-DD` |
| `duration` / `width` / `height` / `fps` / `codec` | 规格 |
| `quality` | 视频级 A/B/C，单元级质量看 `attr.质量` |

## 质量与隐私分布（动手前心里有数）

| 项 | 数量 |
|---|---|
| A精选 | 745 |
| B可用 | 4244 |
| C废片 | 578（不可用） |
| 原片「可公开」 | 174 条 |
| 原片「家庭不宜公开」 | 227 条 |

## 七个虚拟分组

`rural` 农村生活 1073 / `kids` 带娃 1483 / `family` 家人 625 / `talk` 口播出镜 321 /
`city` 出行街景 2154 / `scenery` 风景空镜 516 / `food` 美食做饭 297

一条单元可同时属于多个（农村做饭 → 同时进 rural 和 food）。

## 取片段

```python
src = src_root / shot_relpath.replace("/", os.sep)
# ffmpeg -ss {start} -t {duration} -i src
```

**永远不切原片**。渲染时现取，`-ss` 放在 `-i` 前面走输入侧 seek，快。

## 匹配算法（`mix.py` 内实现）

不打向量库，就两层：

1. **标签命中**：句子是中文，标签词是中文词，直接 `if tag_word in sentence` 判命中，不需要分词。
   各维权重：主题 5 / 场景 4 / 动作 4 / 人物 3 / 情绪 3 / 时间 2 / 景别 1 / 机位 1 / 可见度 1
2. **描述兜底**：句子里的 2–4 字片段若出现在 `desc` 里，加 3 分

质量分 `A精选 +6 / B可用 +2`，运动量微调 `high +1.5 / mid +1.0 / low +0.3`，
快情绪词（跑/赶/急/忙）配 high，静情绪词（坐/等/安静）配 low。

连续 4 个片段不重复同一 `video_id`，避免连续画面跳回同一条原片。

想改匹配口味，改 `mix.py` 顶部的 `DIM_WEIGHT` / `FAST_WORDS` / `SLOW_WORDS`。
