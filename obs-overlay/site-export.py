"""Write docs/data/seyir.json for the site: last stream's summary, the captain's note, chat's game picks.

Run on the streaming PC after the stream (it only reads the bridge's data files), then commit + push:
    python obs-overlay/site-export.py                       # refresh last stream + wishlist, keep the note
    python obs-overlay/site-export.py --not "Bu hafta ..."  # also set the captain's note
    python obs-overlay/site-export.py --not ""              # remove the note
The site hides any part that's missing, so an empty or old file never breaks the page.
Only public, already-on-stream facts go out (counts, game, loot king's name) — no crew database.
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("QEDY_DATA_DIR") or ROOT)
OUT = ROOT.parent / "docs" / "data" / "seyir.json"


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def last_night():
    try:
        lines = (DATA_DIR / ".nights.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            n = json.loads(line)
        except ValueError:
            continue
        return {k: n.get(k) for k in ("date", "game", "chat", "follows", "wins", "losses", "casts", "krakenWon", "king")}
    return None


def main():
    ap = argparse.ArgumentParser(description="Site için seyir.json yaz")
    ap.add_argument("--not", dest="note", help="kaptanın notu (boş = kaldır)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    out = read_json(OUT, {})
    if args.note is not None:
        out["note"] = {"text": args.note.strip()[:280], "date": datetime.now().strftime("%Y-%m-%d")} if args.note.strip() else None
    out["last"] = last_night() or out.get("last")
    wish = read_json(DATA_DIR / ".show-state.json", {}).get("wishlist") or []
    out["wishlist"] = [{"name": str(w["name"])[:80], "votes": int(w["votes"])} for w in wish if w.get("name")][:10]
    out["updated"] = datetime.now().isoformat(timespec="minutes")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"✓ {OUT}\n  son yayın: {(out['last'] or {}).get('date') or '—'} · not: {'var' if out.get('note') else 'yok'} · "
          f"istek listesi: {len(out['wishlist'])} oyun\n  Şimdi: git add docs/data/seyir.json && git commit -m \"Seyir defteri\" && git push")


if __name__ == "__main__":
    main()
