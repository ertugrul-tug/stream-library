"""Turn tonight's 🎬 markers into vertical 9:16 clips for Reels / Shorts / TikTok.

Run after the stream, before pressing "Yeni yayın" (that clears the markers):
    python obs-overlay/make-clips.py            # cut every marker from the newest recording
    python obs-overlay/make-clips.py --list     # just show the markers
    python obs-overlay/make-clips.py --only 2,5 --before 20 --after 15
    python obs-overlay/make-clips.py --preview  # one PNG of the layout, to tune the crops
    python obs-overlay/make-clips.py --reel     # the night's best 3 moments in one ~60 s vertical video
    python obs-overlay/make-clips.py --week     # 16:9 recap of the last 7 nights for YouTube + chapter list

Needs ffmpeg (winget install Gyan.FFmpeg) and OBS recording turned on while streaming.
Layout: webcam on top (1080x640), game below (1080x1280). The crop boxes are fractions of the
recorded frame and can be tuned in show-config.local.json:
    "clips": {"recordingDir": "D:/Kayitlar", "camera": [0.03, 0.56, 0.21, 0.36], "game": [0.26, 0.08, 0.48, 0.84]}

Every run saves the night's markers as klipler/<recording>/isaretler.json, because "Yeni yayın" clears
them: --week builds the recap from those files, so run the script once each night.
Each clip gets a series name from its marker ("Kraken Düştü", "Efsane Av", …) and klipler/.../aciklama.txt
holds a ready caption with hashtags for every clip.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("QEDY_DATA_DIR") or ROOT)
VIDEO_EXT = {".mkv", ".mp4", ".mov", ".flv"}
CAM_H, GAME_H, W = 640, 1280, 1080

# Marker note -> recurring series name, first match wins. Manual markers without a known word are "Güverteden".
SERIES = [
    (r"kraken", "Kraken Düştü"), (r"korsan", "Korsan Battı"), (r"halat", "Halat Çekme"),
    (r"turnuva", "Olta Turnuvası"), (r"💰|🦷|🧜|efsane|sandık|dişi|pulu", "Efsane Av"),
    (r"galibiyet serisi|seri", "Seri Ateşi"), (r"baskın|raid", "Baskın Geldi"), (r"hype", "Hype Treni"),
]
LINKS = "💜 twitch.tv/kaptanqedy · 💚 kick.com/kaptanqedy · ⚓ ertugrul-tug.github.io/stream-library"


def series_of(note):
    low = (note or "").casefold()
    return next((name for pattern, name in SERIES if re.search(pattern, low)), "Güverteden")


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
    """(index, seconds into the recording, note, auto) for markers that can be placed in the recording."""
    out = []
    for i, m in enumerate(markers, 1):
        if m.get("rec"):
            out.append((i, seconds(m["rec"]), m.get("note") or "", bool(m.get("auto"))))
        elif m.get("vod"):
            # Older markers only know the stream time: right when OBS starts recording together with the stream.
            print(f"  ! #{i} kayıt zamanı yok, yayın zamanı kullanılıyor ({m['vod']})")
            out.append((i, seconds(m["vod"]), m.get("note") or "", bool(m.get("auto"))))
    return out


def merge(times, before, after):
    """Markers closer than one clip window become one clip, so a burst of auto-markers isn't cut five times."""
    clips = []
    for i, t, note, auto in sorted(times, key=lambda x: x[1]):
        if clips and t - before <= clips[-1]["end"]:
            clips[-1]["end"] = t + after
            clips[-1]["ids"].append(i)
            clips[-1]["notes"].append(note)
            clips[-1]["auto"] = clips[-1]["auto"] and auto
        else:
            clips.append({"start": max(0, t - before), "end": t + after, "at": t, "ids": [i], "notes": [note], "auto": auto})
    for c in clips:
        c["note"] = next((x for x in c["notes"] if x), "")
        c["series"] = next((s for s in map(series_of, c["notes"]) if s != "Güverteden"), "Güverteden")
    return clips


def best(clips, count):
    """The captain's own 🎬 marks first, then the named auto moments, in stream order."""
    ranked = sorted(clips, key=lambda c: (c["auto"], c["series"] == "Güverteden", c["at"]))
    return sorted(ranked[:count], key=lambda c: c["at"])


def slug(text):
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE).strip()
    return re.sub(r"[\s_]+", "-", text)[:40] or "an"


def hms(s):
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def vertical(camera, game, src="0:v", out="v"):
    def box(b, h):
        x, y, w, hh = b
        return (f"crop=iw*{w}:ih*{hh}:iw*{x}:ih*{y},scale={W}:{h}:force_original_aspect_ratio=increase,"
                f"crop={W}:{h},setsar=1")
    tag = out
    return (f"[{src}]split[{tag}a][{tag}b];[{tag}a]{box(camera, CAM_H)}[{tag}cam];[{tag}b]{box(game, GAME_H)}[{tag}game];"
            f"[{tag}cam][{tag}game]vstack=inputs=2,fps=30,format=yuv420p[{out}]")


def layout_filter(camera, game):
    return vertical(camera, game)


def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        link = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links/ffmpeg.exe"
        exe = str(link) if link.exists() else None
    if not exe:
        sys.exit("ffmpeg bulunamadı · kur: winget install Gyan.FFmpeg")
    return exe


def has_audio(ffmpeg, video):
    probe = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)], capture_output=True, text=True, errors="replace")
    return "Audio:" in probe.stderr


def newest_recording(folder):
    files = [p for p in Path(folder).glob("*") if p.suffix.lower() in VIDEO_EXT]
    if not files:
        sys.exit(f"Kayıt bulunamadı: {folder} · --file ile ver ya da show-config.local.json > clips.recordingDir")
    return max(files, key=lambda p: p.stat().st_mtime)


def hashtags(game):
    return " ".join(["#kaptanqedy", "#twitch", "#kick", "#türkyayıncı"] + ([f"#{slug(game).replace('-', '').lower()}"] if game else []))


def caption(clip, game):
    return f"⚓ {clip['series']} · {clip['note'].strip() or 'Güverteden bir an'}\n{LINKS}\n{hashtags(game)}"


def concat(ffmpeg, parts, filters, out, audio):
    """parts: [(video, start, length)]; filters[i] turns input i into [v{i}]. Joins them in order."""
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    for video, start, length in parts:
        cmd += ["-ss", str(start), "-t", str(length), "-i", str(video)]
    n = len(parts)
    chain = ";".join(filters)
    if audio:
        chain += ";" + ";".join(f"[{i}:a]aresample=48000,asetpts=PTS-STARTPTS[a{i}]" for i in range(n))
        chain += ";" + "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        maps = ["-map", "[v]", "-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    else:
        chain += ";" + "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
        maps = ["-map", "[v]"]
    cmd += ["-filter_complex", chain] + maps + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                                                "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def save_markers(out_dir, video, clips, game):
    (out_dir / "isaretler.json").write_text(json.dumps({
        "video": str(video), "date": datetime.fromtimestamp(video.stat().st_mtime).strftime("%Y-%m-%d"), "game": game,
        "clips": [{k: c[k] for k in ("at", "note", "series", "auto")} for c in clips]}, ensure_ascii=False, indent=1),
        encoding="utf-8")


def week(ffmpeg, rec_dir, per_night):
    """16:9 recap from every isaretler.json of the last 7 days: best moments per night, 28 s each."""
    since = datetime.now() - timedelta(days=7)
    nights = []
    for f in sorted(Path(rec_dir, "klipler").glob("*/isaretler.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        video = Path(data.get("video") or "")
        if video.exists() and datetime.strptime(data["date"], "%Y-%m-%d") >= since and data.get("clips"):
            nights.append((data, video))
    if not nights:
        sys.exit("Son 7 günde isaretler.json yok · her yayından sonra make-clips.py'yi bir kez çalıştır.")
    parts, chapters, t = [], [], 0
    for data, video in sorted(nights, key=lambda x: x[0]["date"]):
        day = datetime.strptime(data["date"], "%Y-%m-%d").strftime("%d.%m")
        for c in best(data["clips"], per_night):
            start = max(0, c["at"] - 20)
            parts.append((video, start, 28))
            chapters.append(f"{hms(t)} {c['series']} · {day}" + (f" · {c['note']}" if c["note"] else ""))
            t += 28
    audio = all(has_audio(ffmpeg, v) for v in {v for v, _, _ in parts})
    filters = [f"[{i}:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
               f"setsar=1,fps=30,format=yuv420p[v{i}]" for i in range(len(parts))]
    stamp = datetime.now().strftime("%G-W%V")
    out = Path(rec_dir, "klipler", f"hafta-{stamp}.mp4")
    print(f"Haftalık özet: {len(nights)} gece, {len(parts)} an, ~{hms(t)}")
    concat(ffmpeg, parts, filters, out, audio)
    # YouTube wants the first chapter at 0:00 and at least 3 chapters of 10 s+; 28 s parts satisfy the rest.
    (out.with_suffix(".txt")).write_text("Bu haftanın en iyi anları ⚓\n\n" + "\n".join(chapters) + f"\n\n{LINKS}\n",
                                         encoding="utf-8")
    print(f"Video: {out}\nBölümler: {out.with_suffix('.txt')}")


def main():
    ap = argparse.ArgumentParser(description="🎬 işaretlerinden dikey klip çıkar")
    ap.add_argument("--file", help="kayıt dosyası (varsayılan: klasördeki en yeni kayıt)")
    ap.add_argument("--dir", help="kayıt klasörü (varsayılan: clips.recordingDir ya da ~/Videos)")
    ap.add_argument("--before", type=int, default=30, help="işaretten önce kaç saniye (30)")
    ap.add_argument("--after", type=int, default=10, help="işaretten sonra kaç saniye (10)")
    ap.add_argument("--only", help="sadece bu işaretler, örn. 2,5")
    ap.add_argument("--list", action="store_true", help="işaretleri listele, kesme")
    ap.add_argument("--preview", action="store_true", help="düzeni kontrol için tek kare PNG")
    ap.add_argument("--reel", action="store_true", help="gecenin en iyi 3 anı tek ~60 sn dikey video")
    ap.add_argument("--week", action="store_true", help="son 7 gecenin yatay özeti + YouTube bölümleri")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Turkish Windows consoles are cp1254

    cfg = load_config()
    if args.dir:
        cfg["dir"] = args.dir
    if args.week:
        week(find_ffmpeg(), cfg["dir"], 3)
        return
    try:
        saved = json.loads((DATA_DIR / ".show-state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    markers, game = saved.get("markers") or [], saved.get("game") or ""
    if not markers:
        sys.exit("İşaret yok. (\"Yeni yayın\" işaretleri sıfırlar — klipleri yayından hemen sonra çıkar.)")
    if args.list:
        for i, m in enumerate(markers, 1):
            print(f"  #{i}  kayıt {m.get('rec') or '—':>8}  yayın {m.get('vod') or '—':>8}  {series_of(m.get('note')):<15} {m.get('note') or 'işaret'}")
        return

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
    clips = merge(times, args.before, args.after)
    if not args.only:
        save_markers(out_dir, video, merge(marker_times(markers), 15, 5), game)  # 20 s moments for --week
    print(f"Kayıt: {video}\nÇıktı: {out_dir}")

    if args.preview:
        png = out_dir / "onizleme.png"
        subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", str(times[0][1]), "-i", str(video),
                        "-filter_complex", flt, "-map", "[v]", "-frames:v", "1", str(png)], check=True)
        print(f"Önizleme: {png}")
        return

    if args.reel:
        top = best(merge(times, 15, 5), 3)
        parts = [(video, max(0, c["at"] - 15), 20) for c in top]  # 3 × 20 s = one 60 s Reel
        filters = [vertical(cfg["camera"], cfg["game"], f"{i}:v", f"v{i}") for i in range(len(parts))]
        out = out_dir / f"reel-{video.stem}.mp4"
        print("  🎞 Reel: " + " + ".join(c["series"] for c in top))
        concat(ffmpeg, parts, filters, out, has_audio(ffmpeg, video))
        (out_dir / "reel-aciklama.txt").write_text(
            "⚓ Seyir Defteri · dün gecenin en iyileri\n" + "\n".join(f"• {c['series']}" + (f": {c['note']}" if c["note"] else "") for c in top)
            + f"\n\n{LINKS}\n{hashtags(game)}\n", encoding="utf-8")
        print(f"Bitti ✓  {out}")
        return

    notes = []
    for n, clip in enumerate(clips, 1):
        at = clip["at"]
        name = f"{n:02d}-{slug(clip['series'])}-{at // 3600:02d}h{at % 3600 // 60:02d}m{at % 60:02d}-{slug(clip['note'])}.mp4"
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-ss", str(clip["start"]), "-t", str(clip["end"] - clip["start"]),
               "-i", str(video), "-filter_complex", flt, "-map", "[v]", "-map", "0:a:0?",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
               "-movflags", "+faststart", str(out_dir / name)]
        print(f"  ✂ {name}  (işaret #{', #'.join(map(str, clip['ids']))})")
        subprocess.run(cmd, check=True)
        notes.append(f"── {name}\n{caption(clip, game)}\n")
    (out_dir / "aciklama.txt").write_text("\n".join(notes), encoding="utf-8")
    print(f"Açıklamalar: {out_dir / 'aciklama.txt'}\nBitti ✓")


if __name__ == "__main__":
    main()
