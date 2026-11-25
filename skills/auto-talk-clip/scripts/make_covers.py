#!/usr/bin/env python3
"""Generate 4-ratio covers for auto-clipped videos.

Reads 封面文案清单.json (filled by the Agent with 标题/副标题 per video),
picks a portrait per video by deterministic rotation (same video -> same face),
cuts it out with rembg (cached), then calls footage-polish/make_cover.py --mode all
to emit horizontal / vertical / video-account 3:4 / video-account 4:3 covers
into each video's own folder.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image
from rembg import remove, new_session

MAKE_COVER = Path(r"E:\自媒体\skills\footage-polish\scripts\make_cover.py")
DEFAULT_PORTRAIT_DIR = Path(r"E:\自媒体\封面\个人头像")
DEFAULT_OUT = Path(r"E:\自媒体\剪辑后的成片")
SUFFIX = {
    "horizontal": "封面_横屏.png",
    "vertical": "封面_竖屏.png",
    "card_personal": "封面_视频号个人页3-4.png",
    "card_share": "封面_视频号分享4-3.png",
}


def pick_portrait(rel: str, portraits: list) -> Path:
    """Deterministic rotation: hash of the video path -> one of the portraits.
    Same video always gets the same person; different videos spread across the set."""
    n = int(hashlib.md5(rel.encode("utf-8")).hexdigest(), 16) % len(portraits)
    return portraits[n]


def cutout(portrait: Path, cache_dir: Path, session) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / (portrait.stem + "_cutout.png")
    if cached.is_file():
        return cached
    img = Image.open(portrait)
    out = remove(img.convert("RGB"), session=session, alpha_matting=False).convert("RGBA")
    out.save(cached)
    print(f"  抠图缓存 {portrait.name} -> {cached.name}")
    return cached


def main():
    ap = argparse.ArgumentParser(description="为自动剪辑的每条视频生成四比例封面")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--brief", default="", help="文案清单路径，默认 <out>/封面文案清单.json")
    ap.add_argument("--portrait-dir", default=str(DEFAULT_PORTRAIT_DIR))
    ap.add_argument("--only", default="", help="只处理相对路径包含该子串的视频")
    ap.add_argument("--force", action="store_true", help="已有的四张封面也重新生成")
    a = ap.parse_args()

    out = Path(a.out)
    brief_path = Path(a.brief) if a.brief else out / "封面文案清单.json"
    if not brief_path.is_file():
        raise SystemExit(f"找不到文案清单：{brief_path}")
    if not MAKE_COVER.is_file():
        raise SystemExit(f"找不到封面脚本：{MAKE_COVER}")
    brief = json.loads(brief_path.read_text(encoding="utf-8"))
    items = brief.get("条目", [])
    portrait_dir = Path(a.portrait_dir)
    portraits = sorted([p for p in portrait_dir.iterdir()
                        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}])
    if not portraits:
        raise SystemExit(f"人像目录没有照片：{portrait_dir}")

    session = new_session("u2netp")
    cache_dir = out / ".cover-cache"
    made, skipped = 0, 0
    for item in items:
        title, subtitle = item.get("标题", "").strip(), item.get("副标题", "").strip()
        folder_rel = item.get("文件夹", "")
        if not title or not subtitle:
            print(f"[跳过] {folder_rel}：标题/副标题未填写")
            skipped += 1
            continue
        if a.only and a.only not in item.get("相对路径", ""):
            continue
        folder = out / folder_rel
        if not folder.is_dir():
            print(f"[跳过] 找不到视频文件夹：{folder}")
            skipped += 1
            continue
        covers = [folder / s for s in SUFFIX.values()]
        if all(c.is_file() for c in covers) and not a.force:
            print(f"[跳过] {folder_rel}：四张封面已存在")
            skipped += 1
            continue
        portrait = pick_portrait(item.get("相对路径", folder_rel), portraits)
        print(f"[出图] {folder_rel}  人像={portrait.name}  标题={title} / {subtitle}")
        cut = cutout(portrait, cache_dir, session)
        tmp = folder / "封面_临时.png"
        proc = subprocess.run(
            [sys.executable, str(MAKE_COVER), "--portrait", str(cut),
             "--title", title, "--subtitle", subtitle, "--mode", "all",
             "--out", str(tmp), "--no-cutout"],
            capture_output=True, text=True,
        )
        if proc.returncode != 0 or "封面已生成" not in proc.stdout:
            print(f"[失败] make_cover 出错：{proc.stdout[-400:]} {proc.stderr[-400:]}")
            skipped += 1
            continue
        # make_cover writes _横/_竖/_个人主页卡片3-4/_分享卡片4-3 suffixes; rename to our standard names.
        mapping = {
            "封面_临时_横.png": SUFFIX["horizontal"],
            "封面_临时_竖.png": SUFFIX["vertical"],
            "封面_临时_个人主页卡片3-4.png": SUFFIX["card_personal"],
            "封面_临时_分享卡片4-3.png": SUFFIX["card_share"],
        }
        for src_name, dst_name in mapping.items():
            src = folder / src_name
            if src.is_file():
                src.replace(folder / dst_name)
        made += 1
    print(f"[汇总] 新出封面 {made} 条；跳过 {skipped} 条；成片根目录 {out}")


if __name__ == "__main__":
    main()
