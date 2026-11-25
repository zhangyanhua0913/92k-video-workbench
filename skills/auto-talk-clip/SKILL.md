---
name: auto-talk-clip
description: 批量自动剪辑草稿目录里的真人口播视频——扫描草稿文件夹，把没剪过的逐个走本地转写、烧字幕、暗金标题动画全自动出片，成片按原子目录落到成片目录并在 Excel 表登记去重。用户说「把草稿里的视频自动剪了」「批量剪口播」「跑一下自动剪辑」时使用。不用于数字人、多机位、需要删口误的精细粗剪、FredTalk 自由创意包装或自动发布；不改动口播工作台的六步流程和风格注册表。
---

# 草稿目录自动剪辑（auto-talk-clip）

把 `草稿待剪辑/` 里的口播视频批量自动剪成片，结果放到 `剪辑后的成片/`，并用 Excel 表按内容哈希记账，重复运行只剪新增的。

## 固定路径（可用命令行参数覆盖）

| 项 | 默认路径 |
|---|---|
| 草稿目录 | `E:\自媒体\草稿待剪辑` |
| 成片目录 | `E:\自媒体\剪辑后的成片` |
| 去重表 | `E:\自媒体\剪辑后的成片\剪辑记录.xlsx` |
| 锚工程 | `E:\自媒体\剪辑后的成片\.auto-clip-anchor` |
| talk CLI | `E:\n8n\92k-video-workbench\skills\talking-edit\scripts\cli.py` |

草稿目录支持子目录（如 `一人公司/`、`石头工具箱/`），成片按相同相对路径落位。视频后缀：mp4 / mov / webm / mkv。

## 能剪到什么程度（边界，必须对用户讲清）

全自动 = **本地 Whisper 转写 + 字幕烧进画面 + 暗金科技标题动画 + 导出**。
按工作台铁律：全自动**不删口误、不停顿、不做 FredTalk/自由创意包装**，成片标记为「未人工听看」。用户要精细粗剪或创意包装时，明确告知需走口播工作台逐条人工审看，本 skill 不代做。

## 执行步骤

1. **先 dry-run 看清单**（强烈建议，尤其第一次）：
   ```
   python "E:\自媒体\skills\auto-talk-clip\scripts\auto_clip.py" --dry-run
   ```
   输出扫描到几个视频、哪些判重跳过、哪些待剪。确认无误再实跑。

2. **正式剪辑**：
   ```
   python "E:\自媒体\skills\auto-talk-clip\scripts\auto_clip.py"
   ```
   常用参数：
   - `--limit 1`：先拿一条试跑，验证出片效果再放开全量。
   - `--force`：忽略去重表强制重剪（谨慎，会覆盖成片）。
   - `--draft PATH --out PATH`：换目录。
   - `--packaging none`：不要暗金标题，只烧字幕。
   - `--speed 1.0`：语速，默认原速。

3. **汇报结果**：告诉用户本次剪了几条、跳了几条、成片目录在哪，并提示成片尚未人工听看。

## 依赖与就绪检查

脚本每次先跑 `cli.py doctor` 自检：FFmpeg/ffprobe、whisper-local、remotion-gold 缺一即停并报具体原因，不静默降级、不联网上传、不产生云费用。
- Python 需 `openpyxl`（已装； `pip install openpyxl -i https://mirrors.aliyun.com/pypi/simple/`）。
- 暗金动画依赖 Node + 隔离目录 `~/.talking-edit/deps/gold-motion-v1`（已就绪）。
- 换机器时按 talk 的 SKILL.md 做 `prepare-deps whisper` / `configure-runtime`。

## 去重判定（Excel 表 `剪辑记录.xlsx`）

- 表头：源文件名 / 相对路径 / SHA256 / 源时长 / 状态 / 成片路径 / 动画段数 / 耗时 / 完成时间 / 备注。
- `done` 且成片文件仍然存在 → 判为已剪，跳过。
- `failed`、成片丢失 → 下次自动重试。
- 判重键是**相对路径 + SHA256**：同名但内容变了会重剪；改了名但内容一样视为新条目（因为相对路径变了）。
- 一条失败不影响其他视频，失败原因写进表。

## 边界与安全

- 不删除草稿、不删除成片、不改动口播工作台的六步流程和风格注册表。
- 成片写入是覆盖式（`copy2`）；`--force` 会覆盖已有成片，运行前确认。
- 锚工程放在成片目录下的 `.auto-clip-anchor`，不污染草稿目录；扫描时自动排除。
- 不把 Key、用户隐私写进仓库或提示词。

## 位置与同步

主副本：`E:\自媒体\skills\auto-talk-clip\`
工作台副本：`E:\n8n\92k-video-workbench\skills\auto-talk-clip\`
改动需同步两处，并跑 `python "D:\skills-backup\scripts\skill_backup.py" --push`。
