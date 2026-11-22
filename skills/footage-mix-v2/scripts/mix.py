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
import collections
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

# ---- 镜头节奏（2026-11-21 定）
# 一句一镜为主：句子合并成「镜头组」，一组一个镜头。
SHOT_TARGET = 6.5     # 目标镜头长度，短句往这个值并
SHOT_SOFT_MAX = 10.0  # 合并时的软上限，超过就不再并句
SHOT_HARD_MAX = 15.0  # 硬上限，单句超长按这个值拆镜
# ---- 画风一致性：同一章内只用同一个「风格族」
# 族粒度要粗。用原始标签值（场景×时间有 52 种）会把每族切到只剩几条原片，
# 结果全片反复用同 5 条素材，比跳变更难看。归并成「大环境 × 光线」后
# 城市/日间有 71 条原片、自然/日间 46 条，够铺满整片还不重复。
SCENE_BUCKET = {
    "户外": "自然", "田地": "自然", "河边": "自然", "院子": "自然",
    "街道": "城市", "车站": "城市", "商场": "城市", "集市": "城市",
    "室内": "室内", "餐厅": "室内", "厨房": "室内", "楼道": "室内",
    "车内": "车内", "车上": "车内",
}
LIGHT_BUCKET = {
    "白天": "日间", "上午": "日间", "下午": "日间", "中午": "日间", "清晨": "日间",
    "傍晚": "黄昏", "黄昏": "黄昏", "夜晚": "夜晚",
}
FAMILY_DIMS = ("场景", "时间")   # 族 = (大环境, 光线) 例如 (城市, 日间)


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


# ---------------------------------------------------------------- 镜头组

def fam_key(shot):
    """风格族 = (大环境, 光线)。同族意味着同一类环境和同一种光线，
    观感上不会从农村无人机一下跳到城市高楼。"""
    a = shot.get("attr") or {}
    scene = a.get("场景")
    light = a.get("时间")
    return (SCENE_BUCKET.get(scene, scene), LIGHT_BUCKET.get(light, light))


def build_groups(sentences, target=SHOT_TARGET, soft_max=SHOT_SOFT_MAX,
                 hard_max=SHOT_HARD_MAX):
    """把句子合并成镜头组：一组一个镜头，尽量让镜头跨完整句话。

    - 单句超过 hard_max：拆成等长的几镜
    - 短句往后并，直到 >= target；合并受 soft_max 约束
    - 优先在配音块（block）边界收尾，避免一句话被章节切开
    """
    groups, i, n = [], 0, len(sentences)
    while i < n:
        s = sentences[i]
        if s["duration"] > hard_max:
            k = int(-(-s["duration"] // hard_max))
            per = s["duration"] / k
            for j in range(k):
                groups.append({
                    "start": round(s["start"] + j * per, 3),
                    "end": round(s["start"] + (j + 1) * per, 3),
                    "duration": round(per, 3), "sents": [s["i"]],
                    "text": s["text"], "block": s["block"], "split": True})
            i += 1
            continue

        dur, sents, texts = s["duration"], [s["i"]], [s["text"]]
        blk, j = s["block"], i + 1
        while j < n and dur < target:
            nx = sentences[j]
            if dur + nx["duration"] > soft_max:
                break
            if nx["block"] != blk:
                break                       # 配音块边界一律断，章节结构别打乱
            dur += nx["duration"]
            sents.append(nx["i"]); texts.append(nx["text"])
            blk = nx["block"]; j += 1
        groups.append({
            "start": round(s["start"], 3), "end": round(s["start"] + dur, 3),
            "duration": round(dur, 3), "sents": sents,
            "text": " ".join(texts), "block": sentences[i]["block"],
            "split": False})
        i = j
    return groups


def choose_family(pool, groups, tag_map, prev_family, used_videos=None, whole=None):
    """给一个章节选风格族。

    原则：**整片一个视觉基调**比"每句都贴文案"重要得多——逐句标签里往往
    只有情绪没有场景，靠它投票会把片子选到只剩几条素材的偏门族上。
    所以首章按『能否撑满全片』挑素材最充裕、原片最多样的族，之后一路沿用。
    """
    used = used_videos or set()
    need = sum(g["duration"] for g in groups)
    whole_need, whole_clips = whole if whole else (need, len(groups))
    stat = collections.defaultdict(
        lambda: {"secs": 0.0, "free": 0.0, "vids": set(), "free_vids": set(),
                 "n": 0, "shot": None})
    for s in pool:
        k = fam_key(s)
        if None in k:
            continue
        d = stat[k]
        d["secs"] += s["duration"]
        d["vids"].add(s["video_id"])
        d["n"] += 1
        if s["video_id"] not in used:
            d["free"] += s["duration"]
            d["free_vids"].add(s["video_id"])
        if d["shot"] is None:
            d["shot"] = s

    # 1) 上一章的族还够铺满这一章 → 直接沿用，全片零风格跳变
    if prev_family in stat:
        d = stat[prev_family]
        if d["free"] >= need * 1.15 and len(d["free_vids"]) >= len(groups) + 2:
            return prev_family

    # 2) 首章 / 被迫换族：这一章文案想要的氛围（逐句投票，只做微调）
    vote = collections.Counter()
    for g in groups:
        for si in g["sents"]:
            t = tag_map.get(si, {})
            for dim in FAMILY_DIMS:
                v = t.get(dim)
                if v:
                    vote[(dim, v)] += 1

    best, best_sc = prev_family, -1e9
    for k, d in stat.items():
        # 底线：这一章要铺得满，未用原片至少比镜头数多 2 条
        if d["free"] < need * 1.15 or len(d["free_vids"]) < len(groups) + 2:
            continue
        if prev_family is None:
            # 首章要按全片口径把关，选能一路用到底的族
            if d["free"] < whole_need * 1.05 or len(d["free_vids"]) < whole_clips + 2:
                continue
            sc = (min(d["free"] / max(whole_need, 1.0), 8.0) * 1.5 +
                  min(len(d["free_vids"]) / max(whole_clips, 1), 6.0) * 2.0)
            sc += vote.get(("场景", k[0]), 0) * 0.4 + random.random() * 0.3
        else:
            sc = 0.0
            sc += vote.get(("场景", k[0]), 0) * 1.5
            sc += vote.get(("时间", k[1]), 0) * 1.0
            sc += min(d["free"] / max(need, 1.0), 6.0) * 0.8
            sc += min(len(d["free_vids"]) / max(len(groups), 1), 8.0) * 0.3
            sc += 5.0                                    # 勉强能沿用也优先沿用
            sc += random.random() * 0.6
        if sc > best_sc:
            best, best_sc = k, sc
    return best


# ---------------------------------------------------------------- 匹配

class Matcher:
    # 画面描述里出现这些词的单元不进池子——公开视频里的隐私/敏感画面
    SENSITIVE_WORDS = ("身份证", "证件", "银行卡", "合同", "车牌照", "手机支付")

    def __init__(self, shots, videos, privacy="public", folders=None):
        self.videos = {v["id"]: v for v in videos}
        pool = []
        for s in shots:
            if not s.get("desc"):
                continue
            if any(w in s["desc"] for w in self.SENSITIVE_WORDS):
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

    def pick(self, tags, need, used_recent, max_shot, min_shot, pool=None,
             stretch=False):
        """stretch=True 时允许一个镜头跨过描述窗口继续往前取（源片是连续视频），
        这样才有 6~15 秒的长镜头；默认 False 保持老行为。"""
        base = pool if pool is not None else self.pool

        def cap(s):
            if not stretch:
                return s["duration"]
            vlen = self.videos[s["video_id"]].get("duration")
            return min(vlen - s["start"], max_shot) if vlen else s["duration"]

        def rank(exclude):
            cands = []
            for s in base:
                if s["video_id"] in exclude:
                    continue
                sc, hits = self.score(s, tags)
                # 一镜到底优先：够长就能一个镜头说完一句话，不用在同一句里切刀
                if cap(s) >= need - 0.05:
                    sc += 2.5
                # 逆光/过曝的画面观感差，压一档（不排除，避免池子被抽干）
                d = s.get("desc") or ""
                if any(w in d for w in ("过曝", "烧成一片白", "逆光", "糊成", "模糊")):
                    sc -= 1.5
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
            take = min(cap(s), max_shot, need - got)
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
                take = min(cap(s), max_shot, need - got)
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
    ap.add_argument("--max-shot", type=float, default=SHOT_HARD_MAX,
                    help=f"单个镜头最长秒数，默认 {SHOT_HARD_MAX}")
    ap.add_argument("--min-shot", type=float, default=1.5)
    ap.add_argument("--target-shot", type=float, default=SHOT_TARGET,
                    help=f"目标镜头长度，短句往这个值合并，默认 {SHOT_TARGET}s")
    ap.add_argument("--soft-max", type=float, default=SHOT_SOFT_MAX,
                    help=f"合并句子的软上限，默认 {SHOT_SOFT_MAX}s")
    ap.add_argument("--no-family", action="store_true",
                    help="关闭画风一致性约束（默认按章节锁定同一个场景+时间风格族）")
    ap.add_argument("--old-cut", action="store_true",
                    help="回到旧的『按句铺片』行为（每句 1~2 个短片段）")
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

    if a.old_cut:
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

            report.append(f"[{s['start']:7.2f}-{s['end']:7.2f}] {s['text'][:30]}")
            if tags:
                tagged = " ".join(f"{k}={tags[k]}" for k in DIM_WEIGHT if tags.get(k))
                report.append(f"    标签：{tagged}")
            for it in timeline:
                if it["sentence"] == s["i"]:
                    report.append(f"    {it['duration']:4.1f}s @{it['source_in']:6.1f} "
                                  f"{it['asset'][:20]:20s} {it['reason'][:28]:28s} "
                                  f"{it['desc'][:30]}")
    else:
        # ---- 镜头组模式：一组一个长镜头 + 章节内锁定画风
        groups = build_groups(sentences, a.target_shot, a.soft_max, a.max_shot)
        print(f"句子 {len(sentences)} → 镜头组 {len(groups)}"
              f"（目标 {a.target_shot:.1f}s / 上限 {a.max_shot:.0f}s）")

        chapters = collections.OrderedDict()
        for g in groups:
            chapters.setdefault(g["block"], []).append(g)

        prev_family = None
        whole = (sum(g["duration"] for g in groups), len(groups))
        gi = 0
        for blk, gs in chapters.items():
            if a.no_family:
                family, fpool = None, matcher.pool
            else:
                family = choose_family(matcher.pool, gs, tag_map, prev_family,
                                       set(recent), whole)
                fpool = ([s for s in matcher.pool if fam_key(s) == family]
                         if family else matcher.pool)
                prev_family = family or prev_family
            label = "/".join(x or "?" for x in family) if family else "不限"
            print(f"  章节{blk}｜风格族 {label}｜{len(gs)} 镜 / "
                  f"{sum(g['duration'] for g in gs):.0f}s", flush=True)
            report.append(f"===== 章节 {blk}｜风格族 {label}｜{len(gs)} 镜｜"
                          f"{sum(g['duration'] for g in gs):.0f}s =====")

            for g in gs:
                # 组标签：组内各句标签合并，先出现的优先
                gtags = {}
                for si in g["sents"]:
                    for k, v in (tag_map.get(si) or {}).items():
                        if v and k not in gtags and k != "text":
                            gtags[k] = v
                need = g["duration"]
                min_s = min(a.min_shot, need)

                picked = []
                if a.tags:
                    picked = matcher.pick(gtags, need, recent, a.max_shot, min_s,
                                          pool=fpool, stretch=True)
                    if not picked and fpool is not matcher.pool:   # 族内耗尽，放开风格
                        picked = matcher.pick(gtags, need, recent, a.max_shot, min_s,
                                              stretch=True)
                if not picked:
                    picked = matcher.pick_motion(need, recent, a.max_shot, min_s)

                t = g["start"]
                for shot, take, sc, hits in picked:
                    timeline.append({
                        "sentence": g["sents"][0], "sentences": g["sents"],
                        "group": gi, "text": g["text"],
                        "asset": shot["video_id"], "shot_id": shot["id"],
                        "start": round(t, 3), "end": round(t + take, 3),
                        "source_in": round(shot["start"], 3),
                        "duration": round(take, 3), "score": sc,
                        "family": "/".join(x or "?" for x in family) if family else "",
                        "reason": ",".join(hits)[:70],
                        "desc": shot["desc"][:60],
                    })
                    t += take
                    recent.append(shot["video_id"])

                report.append(f"镜{gi:02d} [{g['start']:6.2f}-{g['end']:6.2f}] "
                              f"{need:4.1f}s  {g['text'][:34]}")
                for it in timeline:
                    if it["group"] == gi:
                        report.append(f"      {it['duration']:4.1f}s "
                                      f"@{it['source_in']:6.1f} "
                                      f"{it['asset'][:20]:20s} "
                                      f"[{it['family'][:9]:9s}] "
                                      f"{it['desc'][:34]}")
                gi += 1

    V = {v["id"]: v for v in videos}

    # 兜底：句尾剩余需求小于最小片段时长时会被 pick() 过滤，画面总长会短于旁白。
    # 第一步：从最后一段向前找有源片余量的片段延长，使片段时长总和 ≥ 旁白总长
    # （源片是连续视频，超出描述窗口几秒仍是同一画面，安全）
    if timeline:
        shortfall = round(total - sum(t["duration"] for t in timeline), 3)
        for t in reversed(timeline):
            if shortfall <= 0.05:
                break
            vlen = V[t["asset"]].get("duration")
            room = (max(0.0, vlen - t["source_in"] - t["duration"])
                    if vlen else 3.0)
            if room <= 0.05:
                continue
            ext = min(shortfall, room)
            t["duration"] = round(t["duration"] + ext, 3)
            t["end"] = round(t["start"] + t["duration"], 3)
            shortfall = round(shortfall - ext, 3)
    # 第二步：起点吸附，每段起点对齐前一段结束点，保证拼接连续
    for k in range(1, len(timeline)):
        pe = timeline[k - 1]["end"]
        if abs(timeline[k]["start"] - pe) > 0.001:
            timeline[k]["start"] = round(pe, 3)
            timeline[k]["end"] = round(pe + timeline[k]["duration"], 3)
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
