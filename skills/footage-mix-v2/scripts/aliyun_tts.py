# -*- coding: utf-8 -*-
"""阿里云百炼配音（92K CLI 通道）——按 mix.py 的分块规则逐块生成。

用法：
    python scripts/aliyun_tts.py --script 文案.txt --out 项目目录 [--voice 音色id] [--force]

产物与 mix.py 期望一致：<项目>/配音/01.mp3 + 01.txt。
之后直接跑 mix.py 即可命中缓存（不再走火山通道）。

流程：quote（报价）→ create（确认）→ status（轮询 state/phase）→ result（下载 wav）→ 转 mp3。
注意：平台这条链路只接受 format=wav，传 mp3 会被 request_failed 拒掉。
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mix import split_blocks, strip_punct  # noqa: E402

CLI = r"C:\Users\Administrator\AppData\Local\92k\bin\92k.exe"
FFMPEG = r"C:\Users\Administrator\AppData\Local\Microsoft\WinGet\Links\ffmpeg.exe"
DEFAULT_VOICE = "cd105126e4254060a3ad75d70c8b374c"   # 张琰华的音色（已内置 1.2x 语速）


def run(args, timeout=120):
    r = subprocess.run([CLI, "--site", "cn"] + args,
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def parse_json(text):
    start = text.find("{")
    if start < 0:
        raise RuntimeError("输出无 JSON：" + text[:300])
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise RuntimeError("JSON 不完整：" + text[:300])


def synth(text, out_mp3, voice):
    with tempfile.TemporaryDirectory() as td:
        inp = Path(td) / "in.json"
        inp.write_text(json.dumps({"text": text, "voice_id": voice,
                                   "format": "wav"}, ensure_ascii=False),
                       encoding="utf-8")
        code, out = run(["speech", "quote", "--input", str(inp)])
        if code != 0:
            raise RuntimeError(f"quote 失败：{out[:300]}")
        data = parse_json(out).get("data", {})
        handle, review = data.get("quote_handle"), data.get("review_hash")
        if not handle or not review:
            raise RuntimeError("quote 缺 handle/review：" + json.dumps(data, ensure_ascii=False)[:300])
        print(f"    报价 {data.get('estimated_points')} 积分（上限 {data.get('max_charge_points')}）", flush=True)

        code, out = run(["speech", "create", "--quote", handle, "--confirm", review])
        if code != 0:
            raise RuntimeError(f"create 失败：{out[:300]}")

        for _ in range(60):
            time.sleep(4)
            code, out = run(["speech", "status", "--quote", handle])
            st = parse_json(out).get("data", parse_json(out))
            state = st.get("state") or st.get("phase")
            if state == "succeeded":
                break
            if state in ("failed", "cancelled", "error"):
                raise RuntimeError("生成失败：" + json.dumps(st, ensure_ascii=False)[:300])
        else:
            raise RuntimeError("轮询超时（句柄 %s 可手动 result 救回）" % handle)

        raw = Path(td) / "out.wav"
        code, out = run(["speech", "result", "--quote", handle, "--save", str(raw)])
        if code != 0:
            raise RuntimeError(f"下载失败：{out[:300]}")

        conv = subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(raw),
                               "-b:a", "160k", str(out_mp3)],
                              capture_output=True, text=True, timeout=120)
        if conv.returncode != 0:
            raise RuntimeError("转 mp3 失败：" + conv.stderr[:200])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", required=True, help="文案 txt")
    ap.add_argument("--out", required=True, help="项目目录")
    ap.add_argument("--voice", default=DEFAULT_VOICE, help="克隆音色 id")
    ap.add_argument("--force", action="store_true", help="已有配音也重做")
    a = ap.parse_args()

    text = Path(a.script).read_text(encoding="utf-8-sig").strip()
    out = Path(a.out)
    voice_dir = out / "配音"
    voice_dir.mkdir(parents=True, exist_ok=True)
    blocks = split_blocks(text)
    print(f"文案 {len(strip_punct(text))} 字 → {len(blocks)} 块配音（音色 {a.voice[:8]}…）")

    for i, blk in enumerate(blocks, 1):
        mp3 = voice_dir / f"{i:02}.mp3"
        (voice_dir / f"{i:02}.txt").write_text(blk, encoding="utf-8")
        if mp3.is_file() and not a.force:
            print(f"  [{i:02}] 已有，跳过")
            continue
        print(f"  [{i:02}] {len(strip_punct(blk))} 字：{blk[:18]}…", flush=True)
        synth(blk, mp3, a.voice)
        # 旧的 mp3→wav 转换结果必须一起清掉，否则 mix.py 会继续用旧时长
        wav = mp3.with_suffix(".wav")
        if wav.is_file():
            wav.unlink()
        print(f"  [{i:02}] 完成 {mp3.stat().st_size} 字节", flush=True)

    print("配音就绪，下一步：python scripts/mix.py --script … --tags … --out …")
    return 0


if __name__ == "__main__":
    sys.exit(main())
