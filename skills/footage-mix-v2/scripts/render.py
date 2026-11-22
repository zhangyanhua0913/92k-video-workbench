#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
timeline.json → 成片。一次转码，不产生碎片中间文件。

    python scripts/render.py --project E:\\自媒体\\混剪\\我的片子
    python scripts/render.py --project ... --bgm 音乐.wav
    python scripts/render.py --project ... --no-subs

原片只被读，永远不写。输出落在项目目录里。
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# 素材库里混着 HDR(HLG) 与 SDR；HDR 必须先 tonemap 到 bt709，否则 8bit 截断会发灰发白
HDR_TRC = {"arib-std-b67", "smpte2084", "smpte-st-2084"}
HDR_TO_SDR = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
              "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def probe_trc(ffprobe, path, cache):
    """读视频流的 color_transfer，判断是不是 HDR。结果缓存，同一条原片只查一次。"""
    key = str(path)
    if key in cache:
        return cache[key]
    trc = ""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=color_transfer",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=25)
        trc = (r.stdout or "").strip().lower()
    except Exception:
        trc = ""
    cache[key] = trc
    return trc


def load_vlen():
    """原片总时长，用来判断取片段时有没有余量（转场需要在头部多取半秒）。"""
    try:
        vids = json.loads((LIB / "索引" / "videos.json").read_text(
            encoding="utf-8"))["videos"]
        return {v["id"]: v.get("duration") for v in vids if v.get("duration")}
    except Exception:
        return {}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LIB = Path(r"E:\自媒体\原始素材库")
CONFIG = LIB / "工具" / "config.json"

SUB_STYLE = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,52,&H0000FFFF,&H0000FFFF,&H00000000,&HA0000000,-1,0,0,0,100,100,1,0,1,3,2,2,90,90,66,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ass_time(t):
    n = round(t * 100)
    h, n = divmod(n, 360000)
    m, n = divmod(n, 6000)
    s, n = divmod(n, 100)
    return f"{h}:{m:02}:{s:02}.{n:02}"


def build_ass(sentences, path):
    lines = [SUB_STYLE]
    for s in sentences:
        txt = (s["text"].replace("\n", " ")
               .replace("{", "(").replace("}", ")"))
        lines.append(f"Dialogue: 0,{ass_time(s['start'])},{ass_time(s['end'])},"
                     f"Default,,0,0,0,,{txt}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def check_contiguous(clips):
    """时间轴必须首尾相接，否则成片会有空档或黑帧。"""
    issues, cursor = [], 0.0
    for i, c in enumerate(clips):
        if abs(c["start"] - cursor) > 0.02:
            issues.append(f"片段{i} @ {c['start']:.2f}s 与上一段结束 {cursor:.2f}s 差 "
                          f"{c['start']-cursor:+.2f}s")
        cursor = c["end"]
    return issues, cursor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="mix.py 的输出目录")
    ap.add_argument("--bgm", default="", help="背景音乐文件；不给就只有旁白")
    ap.add_argument("--bgm-lufs", type=float, default=-26,
                    help="BGM 归一化目标响度（LUFS），越大越响；默认 -26 比人声低约 8dB")
    ap.add_argument("--bgm-volume", type=float, default=1.0,
                    help="归一化之后再乘的系数，微调用")
    ap.add_argument("--duck", action="store_true",
                    help="旁白开口时自动压低 BGM（默认不压，BGM 恒定音量）")
    ap.add_argument("--name", default="成片", help="成片文件名（不含扩展名）")
    ap.add_argument("--no-subs", action="store_true", help="不烧字幕")
    ap.add_argument("--res", default="1920x1080", help="输出分辨率")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--crf", type=int, default=20)
    ap.add_argument("--cpu", action="store_true", help="强制用 CPU 编码（libx264）")
    ap.add_argument("--transition", default="fade",
                    choices=["fade", "dissolve", "wipeleft", "wiperight",
                             "slideleft", "circleopen", "none"],
                    help="镜头间转场，默认 fade（叠化）；none = 硬切")
    ap.add_argument("--transition-duration", type=float, default=0.6,
                    help="转场时长秒数，版本2 默认 0.6（版本1 是 0.4）")
    # ---- 版本2 新增：长镜头缓慢推近
    ap.add_argument("--no-zoom", action="store_true",
                    help="关闭缓慢推近（版本2 默认每个镜头 1.0→1.04 轻微推近）")
    ap.add_argument("--zoom-to", type=float, default=1.04,
                    help="推近终点倍率，默认 1.04（轻微）；越大推得越明显")
    a = ap.parse_args()

    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    ffmpeg = cfg["ffmpeg"]["ffmpeg"]
    proj = Path(a.project).resolve()
    data = json.loads((proj / "timeline.json").read_text(encoding="utf-8"))
    clips = sorted(data["timeline"], key=lambda c: c["start"])
    sentences = data["sentences"]
    voice = Path(data["audio"])
    src_root = Path(data["meta"]["src_root"])

    if not voice.is_file():
        print(f"旁白不存在：{voice}")
        return 1
    if not clips:
        print("timeline 是空的")
        return 1

    issues, total = check_contiguous(clips)
    if issues:
        print("时间轴不连续：")
        for x in issues[:8]:
            print("  " + x)
        print("先重跑 mix.py，或手工修 timeline.json")
        return 1
    print(f"片段 {len(clips)} 个 / 总长 {total:.2f}s")

    w, h = (int(x) for x in a.res.lower().split("x"))

    # ---- 输入与视频滤镜
    ffprobe = str(Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
    trc_cache = {}
    vlen = load_vlen()
    T = 0.0 if a.transition == "none" else max(0.0, a.transition_duration)
    args, filters, labels, takes = ["-y"], [], [], []
    for i, c in enumerate(clips):
        src = src_root / c["relpath"].replace("/", os.sep)
        if not src.is_file():
            print(f"原片缺失：{src}")
            return 1
        # 转场要在每段尾部多备 T 秒——xfade 是把两段重叠 T 秒，
        # 不多取的话每切一次画面就短 T 秒，几十个镜头下来音画会彻底对不上。
        extra = T if (T > 0 and i < len(clips) - 1) else 0.0
        take = c["duration"] + extra
        sin = float(c["source_in"])
        vl = vlen.get(c["asset"])
        if vl and sin + take > vl:                 # 余量不够，往前挪入点
            sin = max(0.0, min(sin, vl - take))
            if sin + take > vl:
                take = max(0.05, vl - sin)
        args += ["-ss", f"{sin:.3f}", "-t", f"{take:.3f}", "-i", str(src)]
        takes.append(take)
        # 素材是大疆 HLG 10bit HDR；不转 SDR 直接 8bit 截断会让黄线发白、绿色寡淡，
        # 手机上还容易偏亮发灰。只对 HDR 片段插 tonemap，SDR 片段原样过。
        pre = ""
        if probe_trc(ffprobe, src, trc_cache) in HDR_TRC:
            pre = HDR_TO_SDR + ","
        # ---- 版本2 新增：长镜头轻微缓慢推近（版本1 无此效果）
        # 每个镜头独立从 1.0 推到 zoom_to，推进量按本段实际取用时长 take 分摊，
        # 所以长短镜头都在结尾刚好到终点倍率。用 zoom var 逐帧累加，不用 t，
        # 实测帧数与不推近时完全一致（3s@30fps 都是 90 帧），不破坏音画同步。
        # d=1 保证一进一出；zoompan 后由链尾统一的 setsar/format/setpts 归零，
        # 各段 PTS 仍从 0 起，xfade 输入一致。
        if a.no_zoom:
            zoom_filter = ""
        else:
            nframes = max(1, round(take * a.fps))
            step = (a.zoom_to - 1.0) / nframes
            zoom_filter = (
                f",zoompan=z='min(zoom+{step:.8f},{a.zoom_to:.4f})':d=1:"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"s={w}x{h}:fps={a.fps}")
        # format=yuv420p 显式统一像素格式：xfade 要求两路输入完全一致
        filters.append(
            f"[{i}:v]{pre}scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps={a.fps}{zoom_filter},setsar=1,format=yuv420p,"
            f"setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")

    vi = len(clips)
    args += ["-i", str(voice)]
    ai = vi
    bi = None
    if a.bgm:
        src_bgm = Path(a.bgm)
        if not src_bgm.is_file():
            print(f"BGM 不存在：{src_bgm}")
            return 1
        # 先归一化：不同来源的 BGM 响度差极大（实测这首原始均值只有 -29.7dB），
        # 直接乘系数会被旁白彻底盖住。归一化后再进混音链。
        # 归一化到系统临时目录，不留在项目里
        import tempfile
        norm = Path(tempfile.gettempdir()) / f"footage_bgm_norm_{os.getpid()}.wav"
        print(f"归一化 BGM → {a.bgm_lufs} LUFS ...")
        rn = subprocess.run(
            [ffmpeg, "-v", "error", "-y", "-i", str(src_bgm), "-af",
             f"loudnorm=I={a.bgm_lufs}:TP=-2:LRA=11",
             "-ar", "48000", "-ac", "2", str(norm)],
            capture_output=True, text=True, encoding="utf-8", errors="replace")
        if rn.returncode:
            print("BGM 归一化失败：\n" + (rn.stderr or "")[-600:])
            return 1
        args += ["-stream_loop", "-1", "-i", str(norm)]
        bi = vi + 1

    # ---- 拼接：有转场就链式 xfade，没有就 concat
    if T > 0 and len(clips) > 1:
        prev, acc = labels[0], takes[0]
        for i in range(1, len(clips)):
            off = max(0.0, acc - T)
            tag = f"[x{i}]"
            filters.append(f"{prev}{labels[i]}xfade=transition={a.transition}:"
                           f"duration={T:.3f}:offset={off:.3f}{tag}")
            acc = acc + takes[i] - T
            prev = tag
        filters.append(f"{prev}null[vcat]")
        print(f"转场：{a.transition} {T:.2f}s × {len(clips)-1} 处")
    else:
        filters.append(f"{''.join(labels)}concat=n={len(clips)}:v=1:a=0[vcat]")

    # ---- 字幕
    if a.no_subs:
        filters.append("[vcat]null[vout]")
    else:
        build_ass(sentences, proj / "字幕.ass")
        filters.append("[vcat]ass=字幕.ass[vout]")

    # ---- 音频
    ACH = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
    if bi is not None:
        if a.duck:
            filters.append(f"[{ai}:a]{ACH},asplit=2[vo][vsc]")
        else:
            filters.append(f"[{ai}:a]{ACH},anull[vo]")
        filters.append(
            f"[{bi}:a]{ACH},volume={a.bgm_volume},"
            f"atrim=0:{total:.3f},asetpts=PTS-STARTPTS[bg]")
        if a.duck:
            # 旁白开口时把 BGM 压下去。阈值按旁白实测均值(~-17dB≈0.135)取 0.06，
            # 太低(如 0.035)会连正常说话都一直在压，等于 BGM 消失。
            filters.append("[bg][vsc]sidechaincompress=threshold=0.06:ratio=3:"
                           "attack=15:release=400:makeup=1.6[bgm]")
        else:
            filters.append("[bg]anull[bgm]")
        filters.append("[vo][bgm]amix=inputs=2:duration=first:normalize=0,"
                       "alimiter=limit=0.92[aout]")
    else:
        filters.append(f"[{ai}:a]{ACH},alimiter=limit=0.92[aout]")

    fscript = proj / "_filter.txt"
    fscript.write_text(";\n".join(filters), encoding="utf-8")

    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", str(a.crf)]
    if not a.cpu:
        enc = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", str(a.crf), "-b:v", "0"]

    out = proj / f"{a.name}.mp4"
    cmd = ([ffmpeg, "-hide_banner"] + args +
           ["-filter_complex_script", str(fscript),
            "-map", "[vout]", "-map", "[aout]"] + enc +
           ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-movflags", "+faststart", "-t", f"{total:.3f}", str(out)])

    print(f"渲染中… ({'CPU' if a.cpu else 'NVENC'}) 输出 {out.name}")
    r = subprocess.run(cmd, cwd=str(proj), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        tail = (r.stderr or "")[-1500:]
        print("渲染失败，ffmpeg 最后输出：\n" + tail)
        return 1

    size = out.stat().st_size / 1024 / 1024
    print(f"\n完成：{out}")
    print(f"  {total:.1f}s / {size:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
