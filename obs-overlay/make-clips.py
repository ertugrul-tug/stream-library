"""Turn tonight's 🎬 markers into vertical 9:16 clips for Reels / Shorts / TikTok.

Run after the stream, before pressing "Yeni yayın" (that clears the markers):
    python obs-overlay/make-clips.py            # cut every marker from the newest recording
    python obs-overlay/make-clips.py --list     # just show the markers
    python obs-overlay/make-clips.py --only 2,5 --before 20 --after 15
    python obs-overlay/make-clips.py --preview  # one PNG of the layout, to tune the crops

Needs ffmpeg (winget install Gyan.FFmpeg) and OBS recording turned on while streaming.
Layout: webcam on top (1080x640), game below (1080x1280). The crop boxes are fractions of the
recorded frame and can be tuned in show-config.local.json:
    "clips": {"recordingDir": "D:/Kayitlar", "camera": [0.03, 0.56, 0.21, 0.36], "game": [0.26, 0.08, 0.48, 0.84]}
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("QEDY_DATA_DIR") or ROOT)
VIDEO_EXT = {".mkv", ".mp4", ".mov", ".flv"}
CAM_H, GAME_H, W = 640, 1280, 1080


def load_config():
    cfg = {}
    for name in ("show-config.json", "show-config.local.json"):
        try:
            cfg.update(json.loads((ROOT / name).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    clips = cfg.get("clips") or {}
    return {"dir": clips.get("recordingDir") or str(Path.home() / "Videos"),
            "camera": clips.get("camera") or [0.03, 0.56, 0.21, 0.36],
            "game": clips.get("game") or [0.26, 0.08, 0.48, 0.84]}


def seconds(tc):
    h, m, s = (int(x) for x in tc.split(":"))
    return h * 3600 + m * 60 + s


def marker_times(markers):
    """(index, seconds into the recording, note) for markers that can be placed in the recording."""
    out = []
    for i, m in enumerate(markers, 1):
        if m.get("rec"):
            out.append((i, seconds(m["rec"]), m.get("note") or ""))
        elif m.get("vod"):
            # Older markers only know the stream time: right when OBS starts recording together with the stream.
            print(f"  ! #{i} kayıt zamanı yok, yayın zamanı kullanılıyor ({m['vod']})")
            out.append((i, seconds(m["vod"]), m.get("note") or ""))
    return out


def merge(times, before, after):
    """Markers closer than one clip window become one clip, so a burst of auto-markers isn't cut five times."""
    clips = []
    for i, t, note in sorted(times, key=lambda x: x[1]):
        if clips and t - before <= clips[-1]["end"]:
            clips[-1]["end"] = t + after
            clips[-1]["ids"].append(i)
            clips[-1]["notes"].append(note)
        else:
            clips.append({"start": max(0, t - before), "end": t + after, "at": t, "ids": [i], "notes": [note]})
    return clips


def slug(text):
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    return re.sub(r"[\s_]+", "-", text)[:40] or "an"


def layout_filter(camera, game):
    def box(b, h):
        x, y, w, hh = b
        return (f"crop=iw*{w}:ih*{hh}:iw*{x}:ih*{y},scale={W}:{h}:force_original_aspect_ratio=increase,"
                f"crop={W}:{h},setsar=1")
    return (f"[0:v]split[a][b];[a]{box(camera, CAM_H)}[cam];[b]{box(game, GAME_H)}[game];"
            f"[cam][game]vstack=inputs=2,format=yuv420p[v]")


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        link = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe"
        exe = str(link) if link.exists() else None
    if not exe:
        sys.exit("ffmpeg bulunamadı · kur: winget install Gyan.FFmpeg")
    return exe


def newest_recording(folder):
    files = [p for p in Path(folder).glob("*") if p.suffix.lower() in VIDEO_EXT]
    if not files:
        sys.exit(f"Kayıt bulunamadı: {folder} · --file ile ver ya da show-config.local.json > clips.recordingDir")
    return max(files, key=lambda p: p.stat().st_mtime)


def main():
    ap = argparse.ArgumentParser(description="🎬 işaretlerinden dikey klip çıkar")
    ap.add_argument("--file", help="kayıt dosyası (varsayılan: klasördeki en yeni kayıt)")
    ap.add_argument("--before", type=int, default=30, help="işaretten önce kaç saniye (30)")
    ap.add_argument("--after", type=int, default=10, help="işaretten sonra kaç saniye (10)")
    ap.add_argument("--only", help="sadece bu işaretler, örn. 2,5")
    ap.add_argument("--list", action="store_true", help="işaretleri listele, kesme")
    ap.add_argument("--preview", action="store_true", help="düzeni kontrol için tek kare PNG")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Turkish Windows consoles are cp1254

    try:
        markers = json.loads((DATA_DIR / ".show-state.json").read_text(encoding="utf-8")).get("markers") or []
    except (OSError, ValueError):
        markers = []
    if not markers:
        sys.exit("İşaret yok. (\"Yeni yayın\" işaretleri sıfırlar — klipleri yayından hemen sonra çıkar.)")
    if args.list:
        for i, m in enumerate(markers, 1):
            print(f"  #{i}  kayıt {m.get('rec') or '—':>8}  yayın {m.get('vod') or '—':>8}  {m.get('note') or 'işaret'}")
        return

    cfg = load_config()
    ffmpeg = find_ffmpeg()
    video = Path(args.file) if args.file else newest_recording(cfg["dir"])
    times = marker_times(markers)
    if args.only:
        keep = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
        times = [t for t in times if t[0] in keep]
    if not times:
        sys.exit("Kesilecek işaret yok (yayın/kayıt zamanı olmayan işaretler atlanır).")

    out_dir = video.parent / "klipler" / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    flt = layout_filter(cfg["camera"], cfg["game"])
    print(f"Kayıt: {video}\nÇıktı: {out_dir}")

    if args.preview:
        png = out_dir / "onizleme.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", str(times[0][1]), "-i", str(video),
                        "-filter_complex", flt, "-map", "[v]", "-frames:v", "1", str(png)], check=True)
        print(f"Önizleme: {png}")
        return

    for n, clip in enumerate(merge(times, args.before, args.after), 1):
        at = clip["at"]
        name = f"{n:02d}-{at // 3600:02d}h{at % 3600 // 60:02d}m{at % 60:02d}-{slug(next((x for x in clip['notes'] if x), ''))}.mp4"
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", str(clip["start"]), "-t", str(clip["end"] - clip["start"]),
               "-i", str(video), "-filter_complex", flt, "-map", "[v]", "-map", "0:a:0?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
               "-movflags", "+faststart", str(out_dir / name)]
        print(f"  ✂ {name}  (işaret #{', #'.join(map(str, clip['ids']))})")
        subprocess.run(cmd, check=True)
    print("Bitti ✓")


if __name__ == "__main__":
    main()
