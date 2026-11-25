---
name: auto-talk-clip
description: 批量自动剪辑草稿目录里的真人口播视频并配封面——扫描草稿文件夹，没剪过的逐个走本地转写、烧字幕、暗金标题动画全自动出片，每条视频独立文件夹放成片+字幕+四比例封面（横屏/竖屏/视频号3:4/视频号4:3），Excel 按哈希记账去重。用户说「把草稿里的视频自动剪了」「批量剪口播」「跑一下自动剪辑」「把封面配上」时使用。不用于数字人、多机位、需要删口误的精细粗剪、FredTalk 自由创意包装或自动发布；不改动口播工作台的六步流程和风格注册表。
---

# 草稿目录自动剪辑 + 封面（auto-talk-clip）

把 `草稿待剪辑/` 的口播视频批量剪成片、配封面，结果放 `剪辑后的成片/`，Excel 按哈希记账，重复运行只处理新增的。

## 目录结构（每条视频独立文件夹）

```
E:\自媒体\剪辑后的成片\
  石头工具箱\
    一天一个强大的网站介绍\          <- 视频独立文件夹（命名=视频文件名，规则待用户定）
      一天一个强大的网站介绍.mp4      <- 剪好的成片
      字幕.srt                       <- 烧进画面的同一份字幕
      封面_横屏.png                  <- 1920x1080
      封面_竖屏.png                  <- 1080x1920
      封面_视频号个人页3-4.png       <- 1080x1440（微信视频号个人主页卡片）
      封面_视频号分享4-3.png         <- 1440x1080（微信视频号分享卡片）
  剪辑记录.xlsx                      <- 去重记账表
  封面文案清单.json                  <- 封面标题/副标题（Agent 填写）
  .auto-clip-anchor\                 <- 批次锚工程（内部）
  .cover-cache\                      <- 抠图缓存（内部）
```

草稿支持子目录（如 `一人公司/`、`石头工具箱/`），成片保留相同相对路径。视频后缀：mp4/mov/webm/mkv。**微信视频号的两种卡片比例都出**：个人主页 3:4、分享 4:3，加上通用横屏 16:9、竖屏 9:16，一套四张全平台通用，不靠一张裁剪。

## 能剪到什么程度（边界，必须对用户讲清）

全自动 = **本地 Whisper 转写 + 字幕烧进画面 + 暗金科技标题动画 + 导出**。
按工作台铁律：全自动**不删口误、不停顿、不做 FredTalk/自由创意包装**，成片标记「未人工听看」。要精细粗剪或创意包装，明确告知需走口播工作台逐条人工审看。

## 执行流程：三段式（必须按顺序）

### 第 1 段 · 自动剪辑（脚本）
```
python "E:\自媒体\skills\auto-talk-clip\scripts\auto_clip.py" --dry-run   # 先看清单
python "E:\自媒体\skills\auto-talk-clip\scripts\auto_clip.py"              # 正式剪辑
```
扫描 → SHA256 查表判重 → 未剪的走 `batch-create(auto,remotion-gold)` → `batch-add` → `batch-enqueue auto` → `batch-run` → 成片+字幕落进各自独立文件夹 → Excel 追加行 → 写/更新 `封面文案清单.json`（新视频标题/副标题留空，附字幕预览）。
参数：`--limit 1` 试跑、`--force` 强制重剪、`--packaging none` 只烧字幕、`--draft/--out` 换目录。

### 第 2 段 · Agent 写封面文案（我来做）
读 `封面文案清单.json` 里每条的「字幕预览」或视频文件夹里的 `字幕.srt`，**根据视频内容判断**标题和副标题，填回去：
- `标题`：主标题，`|` 分行（如 `宅家也能|逛遍全世界?`），1~2 行、每行尽量 ≤8 字。
- `副标题`：黄条上的一句话（如 `一个网站 带你云开车看街景`），简短点题。
- 空白的条目会在第 3 段被跳过。标题风格参考 `E:\自媒体\封面\参考封面\`。

### 第 3 段 · 生成封面（脚本）
```
python "E:\自媒体\skills\auto-talk-clip\scripts\make_covers.py"
```
读填好的清单 → 按视频相对路径 hash **确定性轮换**选人像（同一视频每次同一张，不同视频分散到 11 张照片）→ rembg 抠图（缓存到 `.cover-cache`）→ 调 footage-polish 的 `make_cover.py --mode all` 出四比例 → 重命名落进各视频文件夹。
参数：`--only 关键字` 只处理某条、`--force` 重出已有封面、`--portrait-dir` 换人像目录。封面风格固定（用户 2026-11-22 定）：深蓝科技背景 + 完整抠图人像（contain，绝不裁胳膊）+ 白字描边标题 + 黄笔刷副标题，不加角落水印。

## 依赖与就绪检查

`auto_clip.py` 每次先跑 `cli.py doctor` 自检：FFmpeg/ffprobe、whisper-local、remotion-gold 缺一即停，不静默降级、不联网上传、不产生云费用。
- Python 依赖：`openpyxl`、`Pillow`、`rembg`、`onnxruntime`（均已装；pip 用阿里云源 `-i https://mirrors.aliyun.com/pypi/simple/`）。
- **关键坑**：build 暗金动画要用 powershell 建 node_modules junction，本机 PATH 只有 System32 没有 PowerShell 目录 → `auto_clip.py` 的 `child_env()` 已注入，勿删。
- 暗金动画依赖 Node + `~/.talking-edit/deps/gold-motion-v1`（已就绪）。
- rembg 首次用会下载 u2netp 模型（~4.7MB）到用户目录。

## 去重判定（Excel `剪辑记录.xlsx`）

- 表头：源文件名 / 相对路径 / SHA256 / 源时长 / 状态 / 成片路径 / 动画段数 / 耗时 / 完成时间 / 备注。
- `done` 且成片文件仍存在 → 跳过；`failed` 或成片丢失 → 自动重试。
- 判重键 = 相对路径 + SHA256：同名内容变了会重剪；改名视为新条目。
- 一条失败不影响其他，失败原因写进表。封面脚本不参与判重，封面缺失时可单独重跑第 3 段。

## 边界与安全

- 不删除草稿/成片/旧风格；不改动口播工作台六步流程和风格注册表。
- `--force` 会覆盖成片/封面，运行前确认。人像照片只读，抠图结果写缓存目录。
- 锚工程 `.auto-clip-anchor`、抠图缓存 `.cover-cache` 都在成片目录内，扫描时自动排除。
- 不把 Key、用户隐私写进仓库或提示词。

## 位置与同步

主副本：`E:\自媒体\skills\auto-talk-clip\`
工作台副本：`E:\n8n\92k-video-workbench\skills\auto-talk-clip\`
改动需同步两处，并跑 `python "D:\skills-backup\scripts\skill_backup.py" --push`。
