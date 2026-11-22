#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
自检：素材库能不能读、原片在不在、ffmpeg / 配音服务通不通。

    python scripts/check.py

全绿才往下走。缺什么会直接说缺什么、怎么补。
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LIB = Path(r"E:\自媒体\原始素材库")
CONFIG = LIB / "工具" / "config.json"
VIDEOS = LIB / "索引" / "videos.json"
SHOTS = LIB / "索引" / "shots.json"

OK, BAD, WARN = "[OK]  ", "[FAIL]", "[WARN]"


def load_cfg():
    if not CONFIG.is_file():
        return None
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def check_library(cfg):
    problems = 0
    for p in (VIDEOS, SHOTS):
        if p.is_file():
            print(f"{OK} {p.name}  {p.stat().st_size/1024:.0f} KB")
        else:
            print(f"{BAD} 缺少 {p}")
            problems += 1
    if problems:
        return None, None

    videos = json.loads(VIDEOS.read_text(encoding="utf-8"))["videos"]
    shots = json.loads(SHOTS.read_text(encoding="utf-8"))["shots"]

    tagged = sum(1 for s in shots if s.get("desc"))
    usable = sum(1 for s in shots
                 if (s.get("attr") or {}).get("质量") in ("A精选", "B可用"))
    print(f"{OK} 原片 {len(videos)} 条 / 素材单元 {len(shots)} 个")
    print(f"{OK} 已打标 {tagged} ({tagged/max(len(shots),1)*100:.1f}%) / 可用 {usable}")

    if tagged < len(shots):
        print(f"{WARN} 有 {len(shots)-tagged} 个单元还没打标，这些不会被选中")

    return videos, shots


def check_source(cfg, videos):
    root = Path(cfg["disks"]["E"]["src_root"])
    if not root.is_dir():
        print(f"{BAD} 原片目录不存在：{root}")
        print("      改 config.json 的 disks.E.src_root，或把盘挂回来")
        return 0
    missing = 0
    for v in videos[:20]:                     # 抽 20 条探路，不全盘 stat
        if not (root / v["relpath"].replace("/", os.sep)).is_file():
            missing += 1
    if missing:
        print(f"{BAD} 抽检 20 条里有 {missing} 条找不到原片")
        return len(videos) - missing
    print(f"{OK} 原片目录可读：{root}（抽检 20 条全在）")
    return len(videos)


def check_ffmpeg(cfg):
    ff = Path(cfg["ffmpeg"]["ffmpeg"])
    fp = Path(cfg["ffmpeg"]["ffprobe"])
    if not ff.is_file():
        print(f"{BAD} 找不到 ffmpeg：{ff}")
        return False
    try:
        ver = subprocess.run([str(ff), "-version"], capture_output=True,
                             text=True, timeout=15).stdout.split("\n")[0]
        print(f"{OK} ffmpeg  {ver[:60]}")
    except Exception as e:
        print(f"{BAD} ffmpeg 跑不起来：{e}")
        return False

    print(f"{OK if fp.is_file() else BAD} ffprobe {'在' if fp.is_file() else '缺失：' + str(fp)}")

    enc = subprocess.run([str(ff), "-hide_banner", "-encoders"],
                         capture_output=True, text=True, timeout=30).stdout
    if "h264_nvenc" in enc:
        print(f"{OK} h264_nvenc 可用（硬件编码，渲染快）")
    else:
        print(f"{WARN} 没有 h264_nvenc，回退 libx264（慢但能跑）")
    return True


def check_voice():
    """配音走本机工作台，需要服务在跑 + 令牌已配。"""
    home = Path(os.environ.get("WORKBENCH_HOME", Path.home() / ".92k-video-workbench"))
    sess = home / "session.json"
    if not sess.is_file():
        print(f"{BAD} 找不到工作台会话 {sess}")
        return False
    d = json.loads(sess.read_text(encoding="utf-8"))
    origin = d.get("origin", "")

    token = home / "life-tts" / "04-market.dpapi"
    if token.is_file():
        print(f"{OK} 配音令牌已配置（DPAPI 加密）")
    else:
        print(f"{BAD} 配音令牌未配置，去工作台「配置中心 → 04 接口市场」填一次")
        return False

    try:
        from urllib.request import Request, build_opener, ProxyHandler
        req = Request(origin + "/api/life-tts/config",
                      headers={"X-Workbench-Session": d["session"],
                               "Origin": origin})
        with build_opener(ProxyHandler({})).open(req, timeout=5) as r:
            print(f"{OK} 配音服务在线 {origin}  {r.read().decode()[:60]}")
        return True
    except Exception as e:
        print(f"{WARN} 配音服务没响应（{type(e).__name__}）")
        print(f"      起服务：cd E:/n8n/92k-video-workbench && "
              f"python scripts/workbench.py open --port 18737")
        print(f"      或者先用 --no-voice 拿现成音频跑流程")
        return False


def check_matcher(cfg, shots):
    """匹配器要用到的标签词表，看看覆盖多少个。"""
    dims = ["场景", "动作", "人物", "景别", "机位", "时间", "情绪", "主题", "可见度"]
    counts = {}
    for d in dims:
        counts[d] = len({(s.get("attr") or {}).get(d) for s in shots} - {None, ""})
    print(f"{OK} 标签维度：" + " / ".join(f"{k}{v}" for k, v in counts.items()))
    total = sum(counts.values())
    if total < 50:
        print(f"{WARN} 标签种类偏少（{total}），匹配可能不够细")
    return total


def main():
    print("=" * 58)
    print("本地素材混剪 · 环境自检")
    print("=" * 58)

    cfg = load_cfg()
    if not cfg:
        print(f"{BAD} 缺 config.json：{CONFIG}")
        return 1
    print(f"{OK} config.json 已读")

    videos, shots = check_library(cfg)
    if videos is None:
        return 1
    check_source(cfg, videos)
    check_ffmpeg(cfg)
    check_matcher(cfg, shots)
    print("-" * 58)
    check_voice()

    print("=" * 58)
    print("说明：配音不通也能跑，只是要自己把配音音频垫进去。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
