#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
文案 → 配音 → 逐句时间轴 → 匹配素材 → timeline.json

两种模式：

  A. 语义配画面（推荐，要 --tags）
     Agent 先读文案、逐句打标签写成 tags.json，本脚本按标签筛素材。
     标签词表见 references/tagging.md，必须用词表里的原词。

  B. 空镜踩点（不要 --tags）
     不读语义，按句子时长 + 运动节奏平铺素材，适合纯空镜混剪。

    python scripts/mix.py --script 文案.txt --tags 文案标签.json --out 项目目录
    python scripts/mix.py --script 文案.txt --out 项目目录            # 模式 B

不切原片、不生成中间视频。只算时间轴，渲染交给 render.py。
"""
import argparse
import json
import os
import random
import re
import subprocess
import sys
import wave
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LIB = Path(r"E:\自媒体\原始素材库")
SRC_CONFIG = LIB / "工具" / "config.json"
TTS = Path(r"E:\n8n\92k-video-workbench\skills\life-script-video\scripts\tts.py")

# 标注维度的权重。人物在可公开池里几乎为空，权重给低，别让它主导。
DIM_WEIGHT = {"场景": 5, "情绪": 4, "动作": 3, "主题": 2, "人物": 2}
QUALITY_SCORE = {"A精选": 4.0, "B可用": 1.0, "C废片": -99}
MOTION_BONUS = {"high": 1.2, "mid": 0.8, "low": 0.3}
TOP_K = 12          # 每次在得分最高的 K 个里随机挑，避免整片重复


# ---------------------------------------------------------------- 文本

def strip_punct(s):
    return re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", s)


def split_sentences(text):
    raw = re.split(r"(?<=[。！？；!?;])", text)
    out = []
    for piece in raw:
        piece = piece.strip()
        if not piece:
            continue
        if len(strip_punct(piece)) <= 32:
            out.append(piece)
            continue
        for sub in re.split(r"(?<=[，,、])", piece):
            sub = sub.strip()
            if sub:
                out.append(sub)
    return out


def split_blocks(text, target_chars=120, max_chars=180):
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        paras = [text.strip()]
    blocks, cur = [], ""
    for para in paras:
        for s in split_sentences(para):
            if len(strip_punct(cur)) >= target_chars:
                blocks.append(cur.strip())
                cur = ""
            cur += s
            if len(strip_punct(cur)) >= max_chars:
                blocks.append(cur.strip())
                cur = ""
        if cur.strip():
            blocks.append(cur.strip())
        cur = ""
    if cur.strip():
        blocks.append(cur.strip())
    return [b for b in blocks if strip_punct(b)]


# ---------------------------------------------------------------- 配音

def synth_block(text, out_mp3):
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    txt = out_mp3.with_suffix(".txt")
    txt.write_text(text, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(TTS), "--text-file", str(txt),
         "--output", str(out_mp3), "--allow-paid"],
        capture_output=True, text=True)
    if proc.returncode:
        msg = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise RuntimeError(f"配音失败：{out_mp3.name}\n{msg}")
    return out_mp3


def mp3_to_wav(mp3_path, wav_path, ffmpeg):
    """TTS 的 mp3 有时带多个 ID3 头，按 ID3 切段分别解再拼。"""
    if wav_path.is_file():
        return wav_path
    data = mp3_path.read_bytes()
    sig = b"ID3\x04\x00\x00"
    idx, pos = [], 0
    while True:
        pos = data.find(sig, pos)
        if pos < 0:
            break
        idx.append(pos)
        pos += len(sig)
    if not idx or idx[0] != 0:
        idx = [0]
    idx.append(len(data))

    parts = []
    for i in range(len(idx) - 1):
        if idx[i + 1] <= idx[i]:
            continue
        chunk = wav_path.with_name(f"{wav_path.stem}-p{i+1}.bin")
        part = wav_path.with_name(f"{wav_path.stem}-p{i+1}.wav")
        chunk.write_bytes(data[idx[i]:idx[i + 1]])
        r = subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(chunk),
                            "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le",
                            str(part)], capture_output=True)
        if r.returncode:
            raise RuntimeError(f"解码失败 {mp3_path.name} 第 {i+1} 段")
        parts.append(part)

    with wave.open(str(wav_path), "wb") as dst:
        dst.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        for p in parts:
            with wave.open(str(p), "rb") as src:
                dst.writeframes(src.readframes(src.getnframes()))
    for p in parts:
        p.unlink(missing_ok=True)
        p.with_suffix(".bin").unlink(missing_ok=True)
    return wav_path


def wav_duration(path):
    with wave.open(str(path), "rb") as f:
        return f.getnframes() / f.getframerate()


def concat_wavs(paths, out):
    with wave.open(str(out), "wb") as dst:
        dst.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
        for p in paths:
            with wave.open(str(p), "rb") as src:
                dst.writeframes(src.readframes(src.getnframes()))
    return out


# ---------------------------------------------------------------- 匹配

class Matcher:
    def __init__(self, shots, videos, privacy="public", folders=None):
        self.videos = {v["id"]: v for v in videos}
        pool = []
        for s in shots:
            if not s.get("desc"):
                continue
            if (s.get("attr") or {}).get("质量") not in ("A精选", "B可用"):
                continue
            v = self.videos.get(s["video_id"])
            if not v:
                continue
            if privacy == "public" and v.get("privacy") != "可公开":
                continue
            if folders and not (set(folders) & set(s.get("folders") or [])):
                continue
            pool.append(s)
        self.pool = pool
        # 记录每个维度在池子里的可用取值，标注了但池里没有的值要降权处理
        self.avail = {}
        for d in DIM_WEIGHT:
            self.avail[d] = {(s.get("attr") or {}).get(d) for s in pool} - {None, ""}

    def score(self, shot, tags):
        """加权命中率：只在『标注过且池里存在该值』的维度上算分母。"""
        a = shot.get("attr") or {}
        got = tot = 0.0
        hit_dims = []
        for d, w in DIM_WEIGHT.items():
            want = tags.get(d)
            if not want:
                continue
            if isinstance(want, str):
                want = [want]
            want = [x for x in want if x in self.avail.get(d, set())]
            if not want:
                continue                      # 池里没有这个值，不参与评分
            tot += w
            if a.get(d) in want:
                got += w
                hit_dims.append(f"{d}={a.get(d)}")
        ratio = got / tot if tot else 0.0
        sc = ratio * 10 + QUALITY_SCORE.get(a.get("质量"), 0)
        sc += MOTION_BONUS.get(shot.get("motion"), 0)
        pref = tags.get("motion")
        if pref and shot.get("motion") == pref:
            sc += 1.5
        return sc, hit_dims

    def pick(self, tags, need, used_recent, max_shot, min_shot):
        def rank(exclude):
            cands = []
            for s in self.pool:
                if s["video_id"] in exclude:
                    continue
                sc, hits = self.score(s, tags)
                # 小幅随机扰动：分数接近的会打散，避免整片反复用同几条高分素材
                cands.append((sc + random.random() * 0.8, s, hits))
            cands.sort(key=lambda x: -x[0])
            return cands

        cands = rank(set(used_recent))
        if not cands:                           # 全被去重挡了，放开重排
            cands = rank(set())
        if not cands:
            return []

        out, got, local = [], 0.0, set()
        for sc, s, hits in cands:
            if got >= need - 0.05:
                break
            if s["video_id"] in local:          # 同一句内不重复同一条原片
                continue
            take = min(s["duration"], max_shot, need - got)
            if take < min(min_shot, need):
                continue
            out.append((s, round(take, 3), round(sc, 1), hits))
            local.add(s["video_id"])
            got += take

        # 池子太小凑不满，退回到允许同片多窗
        if got < need - 0.05:
            for sc, s, hits in cands:
                if got >= need - 0.05:
                    break
                if any(x[0] is s for x in out):
                    continue
                take = min(s["duration"], max_shot, need - got)
                if take < min(min_shot, need):
                    continue
                out.append((s, round(take, 3), round(sc, 1), hits))
                got += take
        return out

    def pick_motion(self, need, used_recent, max_shot, min_shot, motion_pref=None):
        """模式 B：不看语义，按运动节奏平铺。"""
        cands = [s for s in self.pool if s["video_id"] not in used_recent]
        if not cands:
            cands = list(self.pool)
        if not cands:
            return []
        if motion_pref:
            pref = [s for s in cands if s.get("motion") == motion_pref]
            cands = pref or cands
        cands = sorted(cands, key=lambda s: -QUALITY_SCORE.get(
            (s.get("attr") or {}).get("质量"), 0))
        head = cands[:TOP_K]
        random.shuffle(head)
        out, got, i = [], 0.0, 0
        while got < need - 0.05 and i < len(head):
            s = head[i]
            i += 1
            take = min(s["duration"], max_shot, need - got)
            if take < min(min_shot, need):
                continue
            out.append((s, round(take, 3), 0.0, ["节奏平铺"]))
            got += take
        return out


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="文案 txt")
    ap.add_argument("--tags", default="", help="逐句标签 json（Agent 生成，见 references/tagging.md）")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--privacy", default="public", choices=["public", "all"])
    ap.add_argument("--folders", default="", help="限定文件夹 rural,kids,family,talk,city,scenery,food")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="只切句不配音，输出 句子清单.txt 供 Agent 标注")
    ap.add_argument("--max-shot", type=float, default=4.5)
    ap.add_argument("--min-shot", type=float, default=1.5)
    a = ap.parse_args()

    cfg = json.loads(SRC_CONFIG.read_text(encoding="utf-8"))
    ffmpeg = cfg["ffmpeg"]["ffmpeg"]
    videos = json.loads((LIB / "索引" / "videos.json").read_text(encoding="utf-8"))["videos"]
    shots = json.loads((LIB / "索引" / "shots.json").read_text(encoding="utf-8"))["shots"]

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    text = Path(a.script).read_text(encoding="utf-8-sig").strip()
    (out / "文案.txt").write_text(text, encoding="utf-8")

    folders = [x.strip() for x in a.folders.split(",") if x.strip()]
    matcher = Matcher(shots, videos, a.privacy, folders or None)
    mode = "语义配画面" if a.tags else "空镜踩点"
    print(f"模式：{mode}")
    print(f"素材池：{len(matcher.pool)} 个单元（privacy={a.privacy}"
          f"{' folders=' + ','.join(folders) if folders else ''}）")
    if not matcher.pool:
        print("素材池是空的，放宽 --privacy 或去掉 --folders")
        return 1

    blocks = split_blocks(text)
    print(f"文案 {len(strip_punct(text))} 字 → {len(blocks)} 块配音")

    if a.dry_run:
        sents, k = [], 0
        for b in blocks:
            for s in split_sentences(b):
                sents.append({"i": k, "text": s})
                k += 1
        lines = [f"{x['i']:3d}  {x['text']}" for x in sents]
        (out / "句子清单.txt").write_text("\n".join(lines), encoding="utf-8")
        (out / "句子清单.json").write_text(
            json.dumps({"sentences": sents}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(f"共 {len(sents)} 句，已写到 {out / '句子清单.txt'}")
        print("下一步：照着句子清单逐句打标签 → 文案标签.json")
        return 0

    voice_dir = out / "配音"
    voice_dir.mkdir(exist_ok=True)
    wavs, block_info = [], []
    for i, blk in enumerate(blocks, 1):
        mp3 = voice_dir / f"{i:02}.mp3"
        wav = voice_dir / f"{i:02}.wav"
        if not (a.no_voice or mp3.is_file()):
            print(f"  配音 {i}/{len(blocks)}（{len(strip_punct(blk))} 字）...", flush=True)
            synth_block(blk, mp3)
        mp3_to_wav(mp3, wav, ffmpeg)
        d = wav_duration(wav)
        wavs.append(wav)
        block_info.append({"i": i, "text": blk, "duration": round(d, 3)})
        print(f"  块{i:02}  {d:6.2f}s  {len(strip_punct(blk)):3d}字", flush=True)

    voice = concat_wavs(wavs, out / "旁白.wav")
    total = wav_duration(voice)
    print(f"旁白合计 {total:.2f}s")

    # 块内按字数比例分句
    sentences, cursor = [], 0.0
    for b in block_info:
        sents = split_sentences(b["text"])
        chars = [len(strip_punct(s)) or 1 for s in sents]
        tot = sum(chars) or 1
        acc = 0.0
        for s, c in zip(sents, chars):
            dur = b["duration"] * c / tot
            sentences.append({"i": len(sentences), "block": b["i"], "text": s,
                              "start": round(cursor + acc, 3),
                              "end": round(cursor + acc + dur, 3),
                              "duration": round(dur, 3)})
            acc += dur
        cursor += b["duration"]

    # 外部标签
    tag_map = {}
    if a.tags:
        raw = json.loads(Path(a.tags).read_text(encoding="utf-8-sig"))
        items = raw["sentences"] if isinstance(raw, dict) else raw
        for it in items:
            tag_map[int(it["i"])] = it
        miss = [s["i"] for s in sentences if s["i"] not in tag_map]
        if miss:
            print(f"[WARN] {len(miss)} 句没拿到标签（{miss[:6]}），这些句用空镜垫")

    timeline, recent, report = [], [], []
    for s in sentences:
        tags = tag_map.get(s["i"], {})
        need = s["duration"]
        if a.tags:
            picked = matcher.pick(tags, need, recent, a.max_shot, a.min_shot)
        else:
            picked = matcher.pick_motion(need, recent, a.max_shot, a.min_shot,
                                         tags.get("motion"))
        if not picked:
            picked = matcher.pick_motion(need, [], a.max_shot, a.min_shot)

        t = s["start"]
        for shot, take, sc, hits in picked:
            timeline.append({
                "sentence": s["i"], "text": s["text"],
                "asset": shot["video_id"], "shot_id": shot["id"],
                "start": round(t, 3), "end": round(t + take, 3),
                "source_in": round(shot["start"], 3),
                "duration": round(take, 3), "score": sc,
                "reason": ",".join(hits)[:70],
                "desc": shot["desc"][:60],
            })
            t += take
            recent.append(shot["video_id"])
            # 整片内不重复用同一条原片；池子不够时 pick() 内部会自动放开


        report.append(f"[{s['start']:7.2f}-{s['end']:7.2f}] {s['text'][:30]}")
        if tags:
            tagged = " ".join(f"{k}={tags[k]}" for k in DIM_WEIGHT if tags.get(k))
            report.append(f"    标签：{tagged}")
        for it in timeline:
            if it["sentence"] == s["i"]:
                report.append(f"    {it['duration']:4.1f}s @{it['source_in']:6.1f} "
                              f"{it['asset'][:20]:20s} {it['reason'][:28]:28s} "
                              f"{it['desc'][:30]}")

    V = {v["id"]: v for v in videos}
    for it in timeline:
        it["relpath"] = V[it["asset"]]["relpath"]

    result = {
        "meta": {"generated": datetime.now().isoformat(" ", "seconds"),
                 "total": round(total, 3), "mode": mode, "privacy": a.privacy,
                 "folders": folders, "blocks": len(blocks),
                 "sentences": len(sentences), "clips": len(timeline),
                 "pool": len(matcher.pool),
                 "src_root": cfg["disks"]["E"]["src_root"]},
        "audio": str(voice),
        "sentences": sentences,
        "timeline": timeline,
    }
    (out / "timeline.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "匹配报告.txt").write_text("\n".join(report), encoding="utf-8")

    used = {t["asset"] for t in timeline}
    print(f"\n成片 {total:.1f}s / {len(timeline)} 个片段 / 用到 {len(used)} 条原片")
    print(f"  时间轴  {out / 'timeline.json'}")
    print(f"  报告    {out / '匹配报告.txt'}")
    print(f"\n下一步：python scripts/render.py --project \"{out}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
