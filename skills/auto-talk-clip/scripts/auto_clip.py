#!/usr/bin/env python3
"""Auto-talk-clip: scan a draft folder and batch-cut every uncut talking-head video.

Pipeline (per video, fully automatic, no human review):
  talking-edit CLI -> batch-create(mode=auto, packaging=remotion-gold)
                   -> batch-add -> batch-enqueue(step=auto) -> batch-run
                   -> copy exports/<task>/film.mp4 to the output tree
                   -> append a row to the Excel ledger (dedupe by SHA-256)

Dedupe rule: a source whose SHA-256 is already in the ledger with status=done
and whose exported film still exists is skipped. Failed/interrupted rows are retried.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv"}
HEADERS = ["源文件名", "相对路径", "SHA256", "源时长(秒)", "状态", "成片路径",
           "动画段数", "耗时(秒)", "完成时间", "备注"]
STATUSES = {"done", "failed", "skipped"}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_duration(path: Path, ffprobe: str) -> float:
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60,
        )
        return round(float(out.stdout.strip()), 2)
    except Exception:
        return 0.0


def ledger_load(path: Path):
    """Return (workbook, sheet, rows-by-source-path). Creates the file if absent."""
    if path.exists():
        wb = load_workbook(path)
        ws = wb.active
        # Backfill headers if an older sheet was created with a different layout.
        current = [c.value for c in ws[1]]
        if current != HEADERS:
            raise SystemExit(f"去重表表头不匹配：{path}，请人工核对后再运行。")
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "剪辑记录"
        ws.append(HEADERS)
        for cell in ws[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="305496")
            cell.alignment = Alignment(horizontal="center")
        widths = [34, 30, 66, 14, 12, 40, 12, 12, 22, 44]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
        ws.freeze_panes = "A2"
        wb.save(path)
    by_path = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or not row[1]:
            continue
        by_path.setdefault(row[1], []).append(row)
    return wb, ws, by_path


def is_cut(rows, out_root: Path, film_for) -> bool:
    """A source is done only if a successful row exists AND its film still exists."""
    for r in rows:
        if r[4] == "done" and r[2]:  # status, sha256
            if film_for(r):
                return True
    return False


def cli_json(cli: Path, args: list, timeout: int = 3600) -> dict:
    proc = subprocess.run([sys.executable, str(cli)] + args, capture_output=True,
                          text=True, timeout=timeout)
    out = proc.stdout.strip()
    try:
        data = json.loads(out)
    except Exception:
        raise RuntimeError(f"CLI 返回非 JSON（exit={proc.returncode}）：{out[:500]} / {proc.stderr[:500]}")
    if not data.get("ok"):
        raise RuntimeError(f"CLI 失败：{data.get('error')} - {data.get('message')}")
    return data["result"]


def newest_film(project_dir: Path) -> Path | None:
    exports = project_dir / "exports"
    if not exports.is_dir():
        return None
    films = list(exports.glob("*/film.mp4"))
    if not films:
        return None
    return max(films, key=lambda p: p.stat().st_mtime)


def main():
    ap = argparse.ArgumentParser(description="自动剪辑草稿目录里的口播视频（字幕+暗金标题，全自动）")
    ap.add_argument("--draft", default=r"E:\自媒体\草稿待剪辑")
    ap.add_argument("--out", default=r"E:\自媒体\剪辑后的成片")
    ap.add_argument("--ledger", default="", help="Excel 路径，默认 <out>/剪辑记录.xlsx")
    ap.add_argument("--cli", default=r"E:\n8n\92k-video-workbench\skills\talking-edit\scripts\cli.py")
    ap.add_argument("--anchor", default="", help="批次锚项目绝对路径，默认 <out>/.auto-clip-anchor")
    ap.add_argument("--packaging", default="remotion-gold", choices=["remotion-gold", "none"])
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--dry-run", action="store_true", help="只扫描和判重，不实际剪辑")
    ap.add_argument("--force", action="store_true", help="忽略去重表，强制重剪所有视频")
    ap.add_argument("--limit", type=int, default=0, help="最多处理 N 条，0=不限")
    args = ap.parse_args()

    draft, out = Path(args.draft), Path(args.out)
    cli = Path(args.cli)
    ledger_path = Path(args.ledger) if args.ledger else out / "剪辑记录.xlsx"
    anchor = Path(args.anchor) if args.anchor else out / ".auto-clip-anchor"

    if not draft.is_dir():
        raise SystemExit(f"草稿目录不存在：{draft}")
    if not cli.is_file():
        raise SystemExit(f"找不到 talking-edit CLI：{cli}")
    out.mkdir(parents=True, exist_ok=True)

    doctor = cli_json(cli, ["--project", str(anchor), "doctor"])
    ffprobe = doctor.get("ffprobe")
    if not ffprobe:
        raise SystemExit("FFmpeg/ffprobe 未就绪，请先在 talk 里 configure-runtime。")
    packs = {s["id"]: s for s in doctor["skills"]}
    pack = packs.get(args.packaging)
    if not pack or not pack["ready"]:
        raise SystemExit(f"包装风格 {args.packaging} 未就绪：{pack.get('reasons') if pack else '不存在'}")
    if not packs.get("whisper-local", {}).get("ready"):
        raise SystemExit("whisper-local 未就绪，请先 prepare-deps whisper。")

    wb, ws, by_path = ledger_load(ledger_path)

    def film_for(row) -> Path | None:
        rel = row[5]
        if not rel:
            return None
        p = out / rel
        return p if p.is_file() and p.stat().st_size > 0 else None

    videos = sorted(p for p in draft.rglob("*")
                    if p.is_file() and p.suffix.lower() in VIDEO_EXTS
                    and ".auto-clip-anchor" not in p.parts)
    print(f"[扫描] 草稿目录 {draft}，发现 {len(videos)} 个视频；成片目录 {out}")

    pending, skipped = [], []
    for v in videos:
        rel = v.relative_to(draft).as_posix()
        rows = by_path.get(rel, [])
        if not args.force and is_cut(rows, out, film_for):
            skipped.append((rel, "已完成且成片存在"))
            continue
        pending.append((v, rel))

    print(f"[判重] 待剪辑 {len(pending)} 个；跳过 {len(skipped)} 个")
    for rel, why in skipped:
        print(f"   跳过 {rel}（{why}）")
    if args.limit:
        pending = pending[: args.limit]
        print(f"[限制] 本次最多处理 {len(pending)} 条")
    if args.dry_run:
        for v, rel in pending:
            print(f"   待剪 {rel}")
        print("[dry-run] 未执行剪辑。")
        return

    # Anchor project hosts the batch queue; each video becomes its own sub-project.
    if not (anchor / ".talking-edit" / "state.sqlite3").exists():
        cli_json(cli, ["--project", str(anchor), "create", "--title", "自动剪辑锚工程"])
        print(f"[初始化] 锚工程 {anchor}")
    batch = cli_json(cli, ["--project", str(anchor), "batch-create",
                           "--title", f"自动剪辑 {datetime.now():%Y%m%d-%H%M%S}",
                           "--packaging", args.packaging, "--speed", str(args.speed),
                           "--mode", "auto"])
    print(f"[批次] {batch['id']}  packaging={batch['packaging']} speed={batch['speed']}")

    added = []
    for v, rel in pending:
        try:
            item = cli_json(cli, ["--project", str(anchor), "batch-add",
                                  "--batch", batch["id"], "--file", str(v)])
            added.append((v, rel, item))
        except Exception as e:
            print(f"[加入失败] {rel}: {e}")
            ws.append([v.name, rel, "", 0.0, "failed", "", 0, 0,
                       datetime.now().isoformat(timespec="seconds"), f"加入批次失败：{e}"[:200]])
            wb.save(ledger_path)

    for v, rel, item in added:
        started = time.time()
        sha, duration, scenes, film_rel, status, note = "", 0.0, 0, "", "failed", ""
        try:
            sha = sha256_file(v)
            duration = probe_duration(v, ffprobe)
            item_id = item["id"]
            cli_json(cli, ["--project", str(anchor), "batch-enqueue",
                           "--item", item_id, "--step", "auto"])
            print(f"[剪辑] {rel} ...")
            run = cli_json(cli, ["--project", str(anchor), "batch-run"], timeout=7200)
            jobs = run.get("jobs", [])
            job_fail = [j for j in jobs if j.get("status") == "failed"]
            if job_fail:
                raise RuntimeError("自动任务失败：" + ";".join(j.get("job_id", "") for j in job_fail))
            project_dir = Path(item["project_path"])
            film = newest_film(project_dir)
            if not film or not film.is_file():
                raise RuntimeError("未找到导出成片 film.mp4")
            target = out / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(film, target)
            film_rel = target.relative_to(out).as_posix()
            # The manifest records how many gold-title animations were rendered.
            manifests = list((project_dir / "exports").glob("*/manifest.json"))
            if manifests:
                try:
                    info = json.loads(max(manifests, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8"))
                    scenes = int(info.get("animation_count", 0))
                except Exception:
                    scenes = 0
            status = "done"
            note = "全自动：本地转写+烧字幕+暗金标题；未人工听看"
            print(f"[完成] {rel} -> {target}")
        except Exception as e:
            status, note = "failed", (str(e))[:200]
            print(f"[失败] {rel}: {note}")
        finally:
            ws.append([v.name, rel, sha, duration, status, film_rel, scenes,
                       round(time.time() - started, 1),
                       datetime.now().isoformat(timespec="seconds"), note])
            wb.save(ledger_path)

    ok = sum(1 for row in ws.iter_rows(min_row=2, values_only=True) if row[4] == "done")
    bad = sum(1 for row in ws.iter_rows(min_row=2, values_only=True) if row[4] == "failed")
    print(f"[汇总] 本次加入 {len(added)} 条；去重表累计成功 {ok} / 失败 {bad}；表：{ledger_path}")


if __name__ == "__main__":
    main()
