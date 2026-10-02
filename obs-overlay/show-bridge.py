"""Local show state for Kaptan Qedy OBS browser sources.

Run: python show-bridge.py  (requires websockets>=14,<17)
Streamer.bot stays on ws://127.0.0.1:8080/; this server uses 8765.

Also serves this folder over plain HTTP on port 8766, bound to the
whole LAN (not just this PC) — so kumanda.html can be opened from a
phone or tablet on the same wifi, not only from this computer.

Three optional integrations, all off until you fill in show-config.json:
  - discordWebhook: "Yayın başladı" button posts to a Discord channel.
  - obs.url / obs.password + obsScenes: scene-switch buttons via
    obs-websocket v5 (enable it in OBS: Tools > obs-websocket Settings).
  - Moderation buttons next to chat (timeout/ban) call DoAction on
    Streamer.bot with action name "ModTimeout" / "ModBan" and
    args {platform, user} — create matching Actions in Streamer.bot
    that actually perform the timeout/ban; this bridge only relays
    the request, it doesn't touch Twitch/Kick directly.

Security note: this puts the control panel's WebSocket (8765) and
static files (8766) on your home network. Anyone on the same wifi can
open the panel and watch the state, but actions (moderation, Discord,
scene switching...) need the PIN printed at startup unless the panel
is opened on this PC. Secrets and saved state are never served.
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import random
import secrets
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parent
# QEDY_* environment overrides exist for tests/run_tests.py; normal runs use the defaults.
DATA_DIR = Path(os.environ.get("QEDY_DATA_DIR") or ROOT)
STATE_FILE = DATA_DIR / ".show-state.json"
CREW_FILE = DATA_DIR / ".crew.json"  # points/ranks that survive between streams
EVENTS_FILE = DATA_DIR / ".events.jsonl"  # raw Streamer.bot payloads of rare events, to check field names after a real stream
NIGHTS_FILE = DATA_DIR / ".nights.jsonl"  # one summary line per past show, for the weekly metrics
BACKUP_DIR = DATA_DIR / "backups"  # rotating copies of crew + nights (gitignored, never served)
CONFIG_FILE = Path(os.environ.get("QEDY_CONFIG") or ROOT / "show-config.json")
SB_URL = os.environ.get("QEDY_SB_URL") or "ws://127.0.0.1:8080/"
WS_PORT = int(os.environ.get("QEDY_WS_PORT") or 8765)
HTTP_PORT = int(os.environ.get("QEDY_HTTP_PORT") or 8766)
CLIENTS = set()

CONFIG = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
LOCAL_CONFIG_FILE = DATA_DIR / "show-config.local.json"
if LOCAL_CONFIG_FILE.exists():
    # Real secrets (Discord webhook URL, OBS password) go here instead of
    # show-config.json, which is tracked in a public repo. Gitignored.
    CONFIG.update(json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")))

# Control-panel PIN for devices other than this PC. Generated once into the gitignored local config.
PIN = re.sub(r"\D", "", str(CONFIG.get("pin") or ""))
if not PIN:
    PIN = f"{secrets.randbelow(10000):04d}"
    _local = json.loads(LOCAL_CONFIG_FILE.read_text(encoding="utf-8")) if LOCAL_CONFIG_FILE.exists() else {}
    _local["pin"] = PIN
    LOCAL_CONFIG_FILE.write_text(json.dumps(_local, ensure_ascii=False, indent=2), encoding="utf-8")
TRUSTED_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
_pin_fails = {}  # ip -> [wrong attempts, blocked until]


def check_pin(ip, pin):
    now = time.time()
    count, until = _pin_fails.get(ip, [0, 0])
    if now < until:
        return "blocked"
    if hmac.compare_digest(pin.encode(), PIN.encode()):
        _pin_fails.pop(ip, None)
        return "ok"
    count += 1
    _pin_fails[ip] = [0, now + 60] if count >= 5 else [count, 0]
    return "wrong"


DISCORD_WEBHOOK =str(CONFIG.get("discordWebhook") or "").strip()
DISCORD_LIVE = CONFIG.get("discordLive") or {}
DISCORD_LIVE_MESSAGE = str(DISCORD_LIVE.get("message") or "").strip()
DISCORD_LIVE_ROLE = re.sub(r"\D", "", str(DISCORD_LIVE.get("roleId") or ""))
OBS_URL = str((CONFIG.get("obs") or {}).get("url") or "ws://127.0.0.1:4455")
OBS_PASSWORD = str((CONFIG.get("obs") or {}).get("password") or "")

# When OBS is on this Windows PC, reuse its local WebSocket password in
# memory. This keeps the secret out of the repo and makes scene buttons
# work without copying the password into show-config.local.json.
if not OBS_PASSWORD and OBS_URL in ("ws://127.0.0.1:4455", "ws://localhost:4455"):
    try:
        obs_config_path = Path(os.environ["APPDATA"]) / "obs-studio/plugin_config/obs-websocket/config.json"
        obs_config = json.loads(obs_config_path.read_text(encoding="utf-8"))
        if obs_config.get("auth_required"):
            OBS_PASSWORD = str(obs_config.get("server_password") or "")
    except (KeyError, OSError, ValueError):
        pass

sb_conn = {"ws": None}
obs_conn = {"ws": None}
obs_pending = {}

# ------------------------------------------------------------ crew ranks --
# +10 the first time someone chats in a show, +1 per message (30 s cooldown so
# spamming doesn't farm points). Keyed by platform:name, stored in CREW_FILE.
RANKS = [(0, "Miço"), (20, "Tayfa"), (60, "Usta Gemici"), (150, "Lostromo"), (350, "Dümenci"), (800, "İkinci Kaptan")]

try:
    crew_db = json.loads(CREW_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    crew_db = {}


def rank_for(points):
    return next(name for floor, name in reversed(RANKS) if points >= floor)


def award_chat(platform, name, show_id):
    """Returns the new rank name if this message pushed the member up a rank, else None."""
    entry = crew_db.setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "points": 0, "streams": 0, "show": None, "last": 0})
    entry["name"] = name
    entry.setdefault("first", show_id[:10])
    before = rank_for(entry["points"])
    now = time.time()
    if entry["show"] != show_id:
        prev = state.get("prevShow")
        entry["streak"] = entry.get("streak", 0) + 1 if prev and entry["show"] == prev else 1
        entry["show"] = show_id
        entry["streams"] += 1
        entry["points"] += 10
    if now - entry["last"] >= 30:
        entry["points"] += 1
        entry["last"] = now
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    after = rank_for(entry["points"])
    return after if after != before else None


def crew_rank(platform, name):
    entry = crew_db.get(f"{platform}:{name.casefold()}")
    return rank_for(entry["points"]) if entry else RANKS[0][1]


def lan_ip():
    """Best-effort LAN IP for printing a phone-friendly URL. Never actually sends data."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class StaticHandler(SimpleHTTPRequestHandler):
    # Served to the whole LAN: never expose secrets (show-config.local.json) or saved state (.show-state.json).
    def send_head(self):
        local = os.path.normcase(os.path.abspath(self.translate_path(self.path)))
        root = os.path.normcase(str(ROOT))
        name = os.path.basename(local.rstrip("\\/"))
        rel = os.path.relpath(local, root) if local.startswith(root) else ".."
        private = rel.startswith("..") or any(part in ("backups", "tests", "__pycache__") for part in Path(rel).parts)
        if private or name.startswith(".") or name.endswith((".local.json", ".py", ".pyc")):
            self.send_error(404)
            return None
        return super().send_head()

    def do_GET(self):
        path, _, query = self.path.partition("?")
        if path in ("/spotify-login", "/spotify-callback"):
            if self.client_address[0] != "127.0.0.1" or not SPOTIFY_ID:
                self.send_error(404)
                return
            if path == "/spotify-login":
                self.send_response(302)
                self.send_header("Location", spotify_login_url())
                self.end_headers()
                return
            try:
                ok = spotify_callback(query)
            except Exception as exc:
                print(f"Spotify girişi başarısız: {type(exc).__name__}", flush=True)
                ok = False
            body = ("<h2>🎵 Spotify bağlandı, bu sekmeyi kapatabilirsin.</h2>" if ok else
                    "<h2>Spotify bağlanamadı · kumandadan tekrar dene.</h2>").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def start_static_server():
    handler = partial(StaticHandler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def clean(value, limit=180):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or ""))[:limit].strip()


def defaults():
    return {
        "game": clean(CONFIG.get("game"), 80),
        "returnMessage": clean(CONFIG.get("returnMessage"), 100),
        "routes": [clean(x, 65) for x in CONFIG.get("routes", [])][:3],
        "routesVisible": True, "segmentVisible": True,
        "markers": [], "rankUp": None, "crewCard": None,
        "matches": [], "scoreVisible": True,
        "prediction": {"status": "off", "votes": {}, "result": None, "matchCount": 0},
        "predictionHistory": [],
        "lolAuto": True, "lolScenes": True, "lolGame": None, "title": "", "botChat": True,
        "catches": [], "kraken": None, "race": None, "pirate": None, "tug": None, "fishCup": None, "guess": None, "guest": None, "krakenRandom": True, "sfx": True,
        "night": {"casts": 0, "krakenWon": 0, "krakenLost": 0, "races": 0, "loot": {}, "raids": []}, "health": None, "raid": None, "questions": [], "scene": "", "effects": [], "market": True, "goal": {"target": 0, "reached": False}, "playQueue": [], "playQueueOpen": False, "playCalled": None, "firstTimers": [], "countdown": None, "cdAutoScene": True, "autoClip": False, "adUntil": None, "hype": None, "wishlist": [], "alerts": True, "weekAwarded": None, "weekChamps": None, "testNotes": [], "music": None, "musicRequests": [], "musicOpen": False, "musicVisible": True, "musicAuto": False, "musicExplicit": True, "kickChat": None, "wheel": None, "wheelLast": None, "deaths": 0, "deathAt": 0, "deathsVisible": True,
        "crew": [], "chat": [], "spotlight": None, "highlights": [],
        "votes": {}, "stats": {"twitch": {"chat": 0, "follow": 0, "sub": 0, "bits": 0},
                             "kick": {"chat": 0, "follow": 0, "sub": 0, "kicks": 0}},
        "started": datetime.now().isoformat(timespec="seconds"),
        "obsConnection": "waiting",
    }


state = defaults()
if STATE_FILE.exists():
    try:
        saved = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state.update({k: saved[k] for k in state.keys() & saved.keys()})
    except (OSError, ValueError):
        pass
state["connection"] = "waiting"


def snapshot():
    result = dict(state)
    result["voteCounts"] = [sum(v == i for v in state["votes"].values()) for i in range(len(state["routes"]))]
    result.pop("votes", None)
    p = state["prediction"]
    w = sum(v == "W" for v in p["votes"].values())
    l = sum(v == "L" for v in p["votes"].values())
    result["prediction"] = {"status": p["status"], "w": w, "l": l, "result": p["result"], "pot": sum((p.get("stakes") or {}).values())}
    result["summaryText"] = summary_text()
    result["activeChatters"] = recent_chatters()
    result["botSaid"] = [re.sub(r"\s+", "", t) for t, at in _said.items() if time.time() - at < 60][-20:]  # echoes of our own lines (any account) are hidden on screen
    result["broadcasters"] = sorted(BROADCASTERS)  # the on-screen chat boxes hide the captain's own messages
    result["nextShow"] = schedule_text(next_only=True)
    result["deathTotal"] = death_total()
    result["crew"] = [{**c, "rank": crew_rank(c["platform"], c["name"]),
                       "streak": (crew_db.get(f"{c['platform']}:{c['name'].casefold()}") or {}).get("streak", 0)} for c in state["crew"]]
    viewers = [e for e in crew_db.values() if e["platform"] in ("twitch", "kick")]
    top = sorted(viewers, key=lambda e: e["points"], reverse=True)[:10]
    result["topLoot"] = [{"platform": e["platform"], "name": e["name"], "loot": e.get("loot", 0), "best": e.get("best")}
                         for e in sorted(crew_db.values(), key=lambda e: e.get("loot", 0), reverse=True)[:5] if e.get("loot")]
    result["topCrew"] = [{"platform": e["platform"], "name": e["name"], "points": e["points"],
                          "streams": e["streams"], "rank": rank_for(e["points"])} for e in top]
    result["schedule"] = CONFIG.get("schedule") or {}
    result["lootKing"] = loot_king()
    result["nights"] = NIGHTS[-10:]
    result["season"] = {"name": season_name(), "top": season_top(5)}
    result["week"] = week_top(3)
    champs = state.get("weekChamps")
    result["weekChamps"] = champs if champs and champs.get("week") == week_id(datetime.now() - timedelta(days=7)) else None
    return result


def best_streak(matches):
    best = run = 0
    for m in matches:
        run = run + 1 if m == "W" else 0
        best = max(best, run)
    return best


def summary_text():
    lines = ["⚓ Bu akşamki sefer bitti, teşekkürler mürettebat!"]
    if state["game"]:
        lines.append(f"🎮 {state['game']}")
    m = state["matches"]
    if m:
        wins = m.count("W")
        line = f"🏆 {wins}G · {len(m) - wins}M"
        if best_streak(m) >= 2:
            line += f" · en uzun seri {best_streak(m)}🔥"
        lines.append(line)
    history = state["predictionHistory"]
    total = sum(h["total"] for h in history)
    if total:
        right = sum(h["right"] for h in history)
        lines.append(f"🔮 Sohbet tahminleri: %{round(100 * right / total)} isabet ({len(history)} maç, {total} tahmin)")
    n = state["night"]
    games = ([f"🎣 {n['casts']} olta"] if n["casts"] else []) \
        + ([f"🐙 Kraken {n['krakenWon']}/{n['krakenWon'] + n['krakenLost']}"] if n["krakenWon"] + n["krakenLost"] else []) \
        + ([f"⛵ {n['races']} yarış"] if n["races"] else [])
    if games:
        lines.append(" · ".join(games))
    raids = state["night"].get("raids") or []
    if raids:
        lines.append("🏴‍☠️ Baskınlar: " + ", ".join(f"{r['name']} ({r['viewers']})" for r in raids))
    leader = (season_top(1) or [None])[0]
    if leader:
        lines.append(f"🏅 {season_name()} sezonu lideri: {leader['name']} ({leader['loot']})")
    king = loot_king()
    if king:
        lines.append(f"👑 Gecenin ganimet kralı: {king['name']} ({king['loot']})")
    loyal = sorted((e for e in crew_db.values() if e.get("show") == state["started"] and e.get("streak", 0) >= 3
                    and str(e.get("name", "")).casefold() not in BROADCASTERS), key=lambda e: -e["streak"])[:3]
    if loyal:
        lines.append("🔥 Sadık mürettebat: " + ", ".join(f"{e['name']} ({e['streak']} yayın üst üste)" for e in loyal))
    goal = state["goal"]
    if goal["target"]:
        lines.append(f"🎯 Takip hedefi: {follows_tonight()}/{goal['target']}" + (" ✅" if goal["reached"] else ""))
    t, k = state["stats"]["twitch"], state["stats"]["kick"]
    lines.append(f"💬 {t['chat'] + k['chat']} mesaj · 👋 {t['follow'] + k['follow']} yeni takipçi · ⭐ {t['sub'] + k['sub']} abonelik")
    if state["highlights"]:
        lines.append("")
        lines.extend(f"✦ {h}" for h in state["highlights"])
    if state["markers"]:
        lines += ["", "🎬 Yayından anlar:"]
        lines.extend(f"  {m['vod'] or m['time']} — {m['note'] or 'işaret'}" for m in state["markers"])
    lines += ["", "Bir sonraki seferde görüşürüz! 🐾"]
    return "\n".join(lines)


PREDICT_WORDS = {"g": "W", "w": "W", "kazan": "W", "kazanır": "W", "kazanir": "W",
                 "m": "L", "l": "L", "kaybet": "L", "kaybeder": "L"}
STAKE_MAX = int((CONFIG.get("games") or {}).get("stakeMax") or 500)


def load_nights():
    try:
        return [json.loads(line) for line in NIGHTS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        return []


NIGHTS = load_nights()


def archive_night():
    """Before a reset, keep a one-line summary of the show that just ended (skipped if nothing happened)."""
    t, k = state["stats"]["twitch"], state["stats"]["kick"]
    if not (t["chat"] + k["chat"] or state["matches"]):
        return
    n, m, king = state["night"], state["matches"], loot_king()
    night = {"date": str(state.get("started", ""))[:10], "game": state["game"],
             "chat": t["chat"] + k["chat"], "follows": t["follow"] + k["follow"], "subs": t["sub"] + k["sub"],
             "raids": len(n.get("raids") or []), "wins": m.count("W"), "losses": m.count("L"),
             "casts": n["casts"], "krakenWon": n["krakenWon"], "races": n["races"],
             "king": king["name"] if king else "", "markers": len(state["markers"])}
    NIGHTS.append(night)
    with NIGHTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(night, ensure_ascii=False) + "\n")


def backup_data(reason):
    """Keep the last 10 copies of the crew and show-archive files; never let a backup problem stop the show."""
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        payload = {"reason": reason, "crew": crew_db, "nights": NIGHTS}
        (BACKUP_DIR / f"{stamp}_{reason}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        for old in sorted(BACKUP_DIR.glob("*.json"))[:-10]:
            old.unlink()
    except OSError as exc:
        print(f"Yedek alınamadı ({type(exc).__name__})", flush=True)


def import_data(payload):
    """Replace crew + show archive with an exported backup (the current data is backed up first)."""
    global crew_db
    crew, nights = payload.get("crew"), payload.get("nights")
    if not isinstance(crew, dict) or not isinstance(nights, list):
        return False
    backup_data("geri-yukleme-oncesi")
    crew_db.clear()
    crew_db.update({k: v for k, v in crew.items() if isinstance(v, dict) and v.get("platform") and v.get("name")})
    NIGHTS[:] = [n for n in nights if isinstance(n, dict)]
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    NIGHTS_FILE.write_text("".join(json.dumps(n, ensure_ascii=False) + "\n" for n in NIGHTS), encoding="utf-8")
    return True


def reset_show():
    refund_stakes()
    archive_night()
    backup_data("yeni-yayin")
    prev_show = state["started"]
    keep = {k: state[k] for k in ("game", "title", "returnMessage", "routes", "connection", "obsConnection", "lolAuto", "lolScenes", "lolGame", "botChat", "krakenRandom", "sfx", "health", "scene", "market", "goal", "playQueue", "playQueueOpen", "cdAutoScene", "autoClip", "wishlist", "alerts", "weekAwarded", "weekChamps", "testNotes", "music", "musicOpen", "musicVisible", "musicAuto", "musicExplicit", "kickChat", "wheelLast", "deathsVisible")}
    state.clear()
    state.update(defaults())  # new "started" = new show id, so everyone's first-message bonus is available again
    state.update(keep)
    state["prevShow"] = prev_show  # for loyalty streaks: came to the last show too?
    award_last_week(prev_show)


# ------------------------------------------------------------- chat bot --
# Streamer.bot Actions "QedySayTwitch" / "QedySayKick" post %message% to that platform's chat.
# They post from the broadcaster account, so the same text comes back as a ChatMessage event:
# _said remembers what we sent for a minute so those echoes aren't counted as chat.

SAY_ACTIONS = {"twitch": "QedySayTwitch", "kick": "QedySayKick"}
CHAT_LINKS = {k.casefold(): str(v) for k, v in (CONFIG.get("chatLinks") or {}).items() if v}
HELP_TEXT = ("⚓ Komutlar · 🎣 Oyun: !olta !koleksiyon !ganimet !market !düello !hafta !sezon"
             " · 🗣️ Sohbet: !soru !kehanet !rütbe !kart !oyna !klip !süre !skor !hedef !lurk !öner !çark !ölüm !program !şarkı · 🎯 Yayında: !tahmin G/M/sayı !rota 1-3 !saldır !katıl !ateş · 🔗 !site")
_said, _cmd_last, _say_warned, _bot_tasks = {}, {}, set(), set()
_rehearsing = [False]  # the pre-show rehearsal plays on screen only


async def _say(platform, text):
    result = await sb_do_action(SAY_ACTIONS[platform], {"message": text})
    if result != "ok" and (platform, result) not in _say_warned:
        _say_warned.add((platform, result))
        print(f"Sohbet botu ({platform}): {result} · Streamer.bot'ta {SAY_ACTIONS[platform]} action'ına bak", flush=True)


def say(text, platform=None):
    if not state.get("botChat", True) or not text or _rehearsing[0]:
        return
    text = text[:450]
    _said[clean(text, 300)] = time.time()
    _spawn(publish())  # the chat boxes learn the line before its echo arrives
    for p in ([platform] if platform else SAY_ACTIONS):
        task = asyncio.get_running_loop().create_task(_say(p, text))
        _bot_tasks.add(task)
        task.add_done_callback(_bot_tasks.discard)


def is_own_echo(message):
    now = time.time()
    for text, at in list(_said.items()):
        if now - at > 60:
            _said.pop(text, None)
    return message in _said


def pct_tr(n):
    """'%50'si', '%70'i', '%30'u' — the possessive suffix follows how the number is read aloud."""
    n = int(n)
    if n == 100:
        return "%100'ü"
    tens = {0: "ı", 10: "u", 20: "si", 30: "u", 40: "ı", 50: "si", 60: "ı", 70: "i", 80: "i", 90: "ı"}
    ones = {1: "i", 2: "si", 3: "ü", 4: "ü", 5: "i", 6: "sı", 7: "si", 8: "i", 9: "u"}
    return f"%{n}'{ones[n % 10] if n % 10 else tens[n]}"



# ------------------------------------------------------------- hosting --
# Welcome people on their first message of the show and drop a rotating tip while chat is active.

QUIET_NAMES = {"nightbot", "streamelements", "moobot", "soundalerts", "streamlabs", "fossabot", "wizebot", "botrix", "kickbot", "sery_bot"}
BROADCASTERS = set()  # this channel's own account names, filled from Streamer.bot
_greet_times, _chat_since_tip = [], [0]
TIPS = [
    "🎣 Canın sıkıldı mı? !olta yaz, bakalım denizden ne çıkacak. Altın sandık seni bekliyor!",
    "🎖️ Sohbette yazdıkça rütben yükselir: Miço → Tayfa → … → İkinci Kaptan. Nerede olduğunu !rütbe ile gör.",
    "🛒 Ganimetin birikti mi? !market ile bak: 🕊️ !martı · 🎉 !konfeti · 💥 !top — ekranda patlasın!",
    HELP_TEXT,
]


async def load_broadcasters():
    reply = await sb_request({"request": "GetBroadcaster"}) or {}
    for info in (reply.get("platforms") or {}).values():
        for key in ("broadcastUser", "broadcastUserName", "broadcasterLogin", "broadcasterUserName"):
            if info.get(key):
                BROADCASTERS.add(str(info[key]).casefold())


def greet(platform, name, is_new):
    lowered = name.casefold()
    if lowered in QUIET_NAMES or lowered in BROADCASTERS:
        return
    now = time.time()
    _greet_times[:] = [t for t in _greet_times if now - t < 60]
    if len(_greet_times) >= 6:  # a raid shouldn't turn into a wall of greetings
        return
    _greet_times.append(now)
    entry = crew_db.get(f"{platform}:{lowered}") or {}
    if is_new:
        say(f"⚓ Güverteye hoş geldin @{name}! İlk seferin 🎉 Neler yapabileceğini görmek için !komutlar yaz.", platform)
    else:
        streak = entry.get("streak", 1)
        text = f"⚓ Tekrar hoş geldin @{name} · {rank_for(entry.get('points', 0))} · {entry.get('streams', 1)}. seferin!"
        if streak in (3, 5) or (streak >= 10 and streak % 5 == 0):
            bonus = streak * 5
            add_loot(platform, name, bonus)
            text += f" 🔥 {streak} yayındır üst üste güvertedesin, sadakat ödülü +{bonus} 🪙"
        elif streak >= 2:
            text += f" 🔥 {streak} yayın üst üste"
        say(text, platform)


async def tips_loop():
    every = float((CONFIG.get("tips") or {}).get("everyMinutes") or 15)
    turn = 0
    while True:
        await asyncio.sleep(every * 60)
        if _chat_since_tip[0] >= 3:
            say(TIPS[turn % len(TIPS)])
            turn += 1
        _chat_since_tip[0] = 0


def is_viewer(name):
    """Leaderboards and prizes are for the crew: not this channel's own accounts or chat bots."""
    lowered = str(name or "").casefold()
    return lowered not in BROADCASTERS and lowered not in QUIET_NAMES


def loot_king():
    return max((x for x in state["night"]["loot"].values() if is_viewer(x["name"])), key=lambda x: x["loot"], default=None)


def ask_question(platform, name, text):
    """!soru: queue a question for the host; the panel shows it on screen when picked."""
    text = clean(text, 200)
    if len(text) < 5 or not cooldown(f"soru:{platform}:{name.casefold()}", 60):
        return
    state["questions"] = (state["questions"] + [{"id": f"q{time.time()}", "platform": platform, "name": name,
                                                   "text": text, "parts": text_parts(text)}])[-30:]
    say(f"❓ @{name} sorun kaptana iletildi ({len(state['questions'])}. sırada).", platform)


def cooldown(key, seconds):
    now = time.time()
    if now - _cmd_last.get(key, 0) < seconds:
        return False
    _cmd_last[key] = now
    return True


def rank_text(platform, name):
    entry = crew_db.get(f"{platform}:{name.casefold()}") or {"points": 0, "streams": 0}
    points = entry["points"]
    upcoming = next(((floor, rank) for floor, rank in RANKS if floor > points), None)
    tail = f" · {upcoming[1]} için {upcoming[0] - points} puan kaldı" if upcoming else " · en yüksek rütbe!"
    return f"@{name} ⚓ {rank_for(points)} · {points} puan · {entry['streams']} yayın{tail}"


def announce_routes():
    if state["routes"] and state["routesVisible"]:
        say("🧭 Sonraki rotayı sen seç: " + " · ".join(f"!rota {i + 1} {r}" for i, r in enumerate(state["routes"])))


def add_match(result):
    state["matches"] = (state["matches"] + [result])[-50:]
    p = state["prediction"]
    guessed = ""
    if p["status"] in ("open", "locked"):
        p.update(status="done", result=result, matchCount=len(state["matches"]))
        total = len(p["votes"])
        if total:
            right = sum(v == result for v in p["votes"].values())
            state["predictionHistory"].append({"right": right, "total": total, "matchCount": len(state["matches"])})
            guessed = f" · 🔮 Sohbetin {pct_tr(round(100 * right / total))} bildi ({right}/{total})"
        guessed += settle_stakes(result)
    m = state["matches"]
    streak = next((i for i, x in enumerate(reversed(m)) if x != result), len(m))
    fire = f" · 🔥 {streak} galibiyet serisi!" if result == "W" and streak >= 2 else ""
    if result == "W" and streak >= 3:
        auto_marker(f"🔥 {streak} galibiyet serisi")
    head = "✅ Galibiyet!" if result == "W" else "❌ Mağlubiyet."
    say(f"{head} Bu akşam {m.count('W')}G {m.count('L')}M{fire}{guessed}")


def predict_vote(platform, name, pick, stake_arg):
    """!tahmin G [miktar]: optional loot stake, taken from the balance now and paid back on a right guess."""
    p, key = state["prediction"], f"{platform}:{name.casefold()}"
    stakes = p.setdefault("stakes", {})
    entry = crew_db.get(key)
    if entry and key in stakes:  # changed their mind: the old stake comes back first
        entry["spent"] = entry.get("spent", 0) - stakes.pop(key)
    p["votes"][key] = pick
    if not stake_arg or not stake_arg.isdigit() or not entry:
        return
    amount = min(int(stake_arg), balance(entry), STAKE_MAX)
    if amount <= 0:
        say(f"@{name} yatıracak ganimetin yok, önce !olta at 🎣", platform)
        return
    entry["spent"] = entry.get("spent", 0) + amount
    stakes[key] = amount
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")


def refund_stakes():
    """Prediction cancelled or replaced before a result: everyone gets their stake back."""
    p = state["prediction"]
    if p["status"] == "done":
        return
    for key, amount in (p.get("stakes") or {}).items():
        if key in crew_db:
            crew_db[key]["spent"] = crew_db[key].get("spent", 0) - amount
    p["stakes"] = {}
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")


def settle_stakes(result):
    """Right guessers get their stake back plus a share of the wrong side's stakes, by stake size."""
    p = state["prediction"]
    stakes = p.get("stakes") or {}
    won = {k: v for k, v in stakes.items() if p["votes"].get(k) == result and k in crew_db}
    lost_pot = sum(v for k, v in stakes.items() if k not in won)
    p["paid"] = {}
    for key, amount in won.items():
        profit = lost_pot * amount // sum(won.values())
        e = crew_db[key]
        e["spent"] = e.get("spent", 0) - amount
        add_loot(e["platform"], e["name"], profit)
        p["paid"][key] = [amount, profit]
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    if not stakes:
        return ""
    if not won:
        return f" · 💰 {sum(stakes.values())} ganimetlik kasa denize gömüldü"
    best = max(p["paid"], key=lambda k: p["paid"][k][1])
    return f" · 💰 {len(won)} kişi kasadan pay aldı, en büyük vurgun {crew_db[best]['name']} +{p['paid'][best][1]}"


def unsettle_stakes():
    """undoMatch after a settled prediction: take the payouts back, stakes are on the table again."""
    p = state["prediction"]
    for key, (amount, profit) in (p.pop("paid", None) or {}).items():
        e = crew_db.get(key)
        if e:
            e["spent"] = e.get("spent", 0) + amount
            add_loot(e["platform"], e["name"], -profit)


def guess_open(question):
    """Number prediction ("Kaç kez öleceğim?"): chat answers !tahmin 5, the closest guess wins when the host enters the answer."""
    state["guess"] = {"id": f"g{time.time()}", "status": "open", "question": question or "Kaç?", "votes": {}, "answer": None, "winners": []}
    say(f"🔢 SAYI TAHMİNİ: {state['guess']['question']} · cevabını yaz: !tahmin 5 · en yakın tahmin ganimeti alır!")


def guess_vote(platform, name, n):
    g = state["guess"]
    if g and g["status"] == "open" and 0 <= n <= 9999:
        g["votes"][f"{platform}:{name.casefold()}"] = {"platform": platform, "name": name, "n": n}


def guess_answer(answer):
    g = state["guess"]
    g.update(status="done", answer=answer)
    votes = list(g["votes"].values())
    if not votes:
        say(f"🔢 Cevap: {answer} · kimse tahmin etmemişti.")
    else:
        best = min(abs(v["n"] - answer) for v in votes)
        winners = [v for v in votes if abs(v["n"] - answer) == best]
        for v in winners:
            add_loot(v["platform"], v["name"], 30 + (20 if best == 0 else 0))
        g["winners"] = [v["name"] for v in winners]
        hit = "tam isabet! +50" if best == 0 else f"{best} farkla en yakın, +30"
        say(f"🔢 Cevap: {answer}! {', '.join(g['winners'])} · {hit} ganimet ({len(votes)} tahmin)")
    _clear_later("guess", g["id"], 20)


def predict_open():
    refund_stakes()
    state["prediction"] = {"status": "open", "votes": {}, "result": None, "matchCount": 0, "stakes": {}}
    say("🔮 Maç tahmini açıldı! Sonucu bil: !tahmin G · !tahmin M · ganimet yatırmak için: !tahmin G 50")


def predict_lock():
    p = state["prediction"]
    if p["status"] != "open":
        return False
    p["status"] = "locked"
    w = sum(v == "W" for v in p["votes"].values())
    pot = sum((p.get("stakes") or {}).values())
    say(f"🔒 Tahminler kapandı · {w} kişi galibiyet, {len(p['votes']) - w} kişi mağlubiyet dedi." + (f" 💰 Kasada {pot} ganimet var." if pot else ""))
    return True


def live_message(game, note=""):
    lines = DISCORD_LIVE_MESSAGE.split("\n") if DISCORD_LIVE_MESSAGE else []
    extra = ([f"🎮 Bu akşam: {game}"] if game else []) + ([note] if note else [])
    content = "\n".join(lines[:1] + extra + lines[1:])
    if DISCORD_LIVE_ROLE:
        content += f"\n\n<@&{DISCORD_LIVE_ROLE}>"
    return content, {"parse": [], "roles": [DISCORD_LIVE_ROLE] if DISCORD_LIVE_ROLE else []}


_save_warned = [False]


async def publish():
    deaths_sync()
    try:
        STATE_FILE.write_text(json.dumps({k: v for k, v in state.items() if k not in ("connection", "obsConnection", "lolGame", "kraken", "race", "pirate", "tug", "fishCup", "health", "scene")}, ensure_ascii=False, indent=2), encoding="utf-8")
        _save_warned[0] = False
    except OSError as exc:  # a locked/synced file must not stop the show; the overlays still update
        if not _save_warned[0]:
            _save_warned[0] = True
            print(f"Yayın durumu diske yazılamadı ({type(exc).__name__}); yayın devam ediyor.", flush=True)
    message = json.dumps({"type": "state", "state": snapshot()}, ensure_ascii=False)
    for ws in tuple(CLIENTS):
        try:
            await ws.send(message)
        except Exception:
            CLIENTS.discard(ws)


KICK_EMOTE = re.compile(r"\[emote:(\d+):([^\]\s]{1,64})\]")


def https_url(value):
    value = str(value or "")
    return value if value.startswith("https://") and len(value) < 400 else ""


def text_parts(text):
    out, last = [], 0
    for m in KICK_EMOTE.finditer(text):
        if m.start() > last:
            out.append({"t": text[last:m.start()]})
        out.append({"e": m.group(2), "u": f"https://files.kick.com/emotes/{m.group(1)}/fullsize"})
        last = m.end()
    if last < len(text):
        out.append({"t": text[last:]})
    return out


def chat_parts(data, text):
    """Mirror of emotes.js parse(): Streamer.bot `parts`, else `emotes` names, else Kick inline tokens."""
    parts = data.get("parts")
    if isinstance(parts, list) and parts:
        out = []
        for p in parts:
            if not isinstance(p, dict):
                continue
            url = https_url(p.get("imageUrl"))
            if url and p.get("type") != "text":
                out.append({"e": clean(p.get("text") or p.get("name"), 64), "u": url})
            else:
                out.extend(text_parts(re.sub(r"[\x00-\x1f\x7f]", "", str(p.get("text") or ""))[:300]))
        return out[:60]
    names = {}
    for e in data.get("emotes") or []:
        if isinstance(e, dict) and e.get("name") and https_url(e.get("imageUrl")):
            names[str(e["name"])] = https_url(e["imageUrl"])
    out = []
    for seg in text_parts(text):
        if "u" in seg or not names:
            out.append(seg)
            continue
        for tok in re.split(r"(\s+)", seg["t"]):
            if tok in names:
                out.append({"e": tok, "u": names[tok]})
            elif tok:
                out.append({"t": tok})
    return out[:60]


def person(data):
    user = data.get("user") or data.get("targetUser") or data.get("sender") or {}
    return clean(user.get("name") or user.get("login") or data.get("userName"), 32)


# ---------------------------------------------------------------- Discord --

def _post_discord_sync(url, content, allowed_mentions=None):
    payload = {"content": content}
    if allowed_mentions is not None:
        payload["allowed_mentions"] = allowed_mentions
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        # Discord's Cloudflare rejects urllib's default User-Agent with 403 / error 1010.
        headers={"Content-Type": "application/json",
                 "User-Agent": "DiscordBot (https://github.com/ertugrul-tug/stream-library, 1.0)"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=15).close()


def _discord_retry_after(exc):
    """Seconds to wait before another try, or None when retrying could double-post or can't help."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 429:
            try:
                return min(10.0, float(json.loads(exc.read() or b"{}").get("retry_after") or 2))
            except (ValueError, OSError):
                return 2.0
        return 2.0 if exc.code >= 500 else None
    if isinstance(exc, urllib.error.URLError) and not isinstance(getattr(exc, "reason", None), TimeoutError):
        return 2.0  # never connected (DNS, refused, network blip): nothing was posted
    return None  # a timeout after sending may still have posted: don't risk a double announcement


async def post_discord(text, allowed_mentions=None):
    if not DISCORD_WEBHOOK or not text:
        return False
    for attempt in range(3):
        try:
            await asyncio.to_thread(_post_discord_sync, DISCORD_WEBHOOK, text, allowed_mentions)
            return True
        except Exception as exc:
            print(f"Discord webhook hatası: {type(exc).__name__} {getattr(exc, 'code', '')} (deneme {attempt + 1}/3)", flush=True)
            wait = _discord_retry_after(exc)
            if wait is None or attempt == 2:
                return False
            await asyncio.sleep(wait)
    return False


async def notify_discord(ws, ok, what):
    if ok:
        text = f"{what} Discord'a gönderildi ✓"
    elif not DISCORD_WEBHOOK:
        text = "Discord webhook ayarlı değil · show-config.local.json > discordWebhook"
    else:
        text = f"{what} gönderilemedi · köprü penceresine bak"
    try:
        await ws.send(json.dumps({"type": "notice", "ok": ok, "text": text, "scope": "discord"}))
    except Exception:
        pass


# ---------------------------------------------------------- Streamer.bot --

sb_pending = {}


async def sb_request(payload, timeout=3):
    """Send a Streamer.bot WebSocket request and wait for its reply (None if Streamer.bot is away)."""
    ws = sb_conn.get("ws")
    if not ws:
        return None
    rid = f"qedy-{time.time()}"
    future = asyncio.get_running_loop().create_future()
    sb_pending[rid] = future
    try:
        await ws.send(json.dumps({**payload, "id": rid}))
        return await asyncio.wait_for(future, timeout)
    except Exception:
        return None
    finally:
        sb_pending.pop(rid, None)


async def sb_do_action(action_name, args):
    """Relay a named Action trigger to Streamer.bot. The Action itself (and
    whatever it does to Twitch/Kick) must already exist in Streamer.bot —
    this bridge never talks to Twitch/Kick directly.
    Returns "ok", "missing" (no such Action), "offline" or "error"."""
    reply = await sb_request({"request": "DoAction", "action": {"name": action_name}, "args": args})
    if reply is None:
        return "offline"
    if reply.get("status") == "ok":
        return "ok"
    return "missing" if "not found" in str(reply.get("error", "")).lower() else "error"


def sb_action_notice(action_name, result, ok_text):
    return {"ok": ok_text,
            "missing": f"Streamer.bot'ta '{action_name}' action'ı yok · kurulum gerekli",
            "offline": "Streamer.bot bağlı değil",
            "empty": f"Streamer.bot'taki '{action_name}' action'ı boş · içine adım ekle",
            }.get(result, f"Streamer.bot '{action_name}' çalıştırılamadı")


async def send_notice(ws, ok, text, scope=None):
    try:
        await ws.send(json.dumps({"type": "notice", "ok": ok, "text": text, "scope": scope}))
    except Exception:
        pass


async def streamer_bot():
    events = {"Twitch": ["ChatMessage", "Follow", "Sub", "ReSub", "GiftSub", "Cheer", "Raid", "RewardRedemption", "AdRun", "HypeTrainStart", "HypeTrainLevelUp", "HypeTrainEnd"],
              "Kick": ["ChatMessage", "Follow", "Subscription", "Resubscription", "GiftSubscription", "KicksGifted"]}
    while True:
        try:
            async with connect(SB_URL, open_timeout=3, max_size=2**20) as ws:
                sb_conn["ws"] = ws
                state["connection"] = "connected"
                await publish()
                await ws.send(json.dumps({"request": "Subscribe", "id": "qedy-show-bridge", "events": events}))
                _spawn(load_broadcasters())
                async for raw in ws:
                    try:
                        payload = json.loads(raw)
                        future = sb_pending.get(payload.get("id"))
                        if future and not future.done():
                            future.set_result(payload)
                            continue
                        event = payload.get("event") or {}
                        platform = clean(event.get("source"), 12).lower()
                        kind = event.get("type")
                        data = payload.get("data") or {}
                        if platform not in ("twitch", "kick") or not isinstance(data, dict):
                            continue
                        name = person(data)
                        if kind != "ChatMessage":
                            log_event(platform, kind, data)
                        if kind == "ChatMessage":
                            message = clean(data.get("text") or data.get("message"), 300)
                            if not name or not message or is_own_echo(message):
                                continue
                            _active[f"{platform}:{name.casefold()}"] = time.time()
                            race_boost(platform, name)
                            tug_pull(platform, name)
                            item = {"platform": platform, "name": name, "text": message, "parts": chat_parts(data, message),
                                    "id": f"{platform}-{datetime.now().timestamp()}"}
                            state["chat"] = (state["chat"] + [item])[-30:]
                            state["stats"][platform]["chat"] += 1
                            previous = crew_db.get(f"{platform}:{name.casefold()}")
                            first_today = not previous or previous.get("show") != state["started"]
                            new_rank = award_chat(platform, name, state["started"])
                            _chat_since_tip[0] += 1
                            if previous is None and name.casefold() not in BROADCASTERS:
                                state["firstTimers"] = (state["firstTimers"] + [f"{platform}:{name.casefold()}"])[-30:]
                            if first_today and not message.startswith("!"):
                                greet(platform, name, previous is None)
                            if new_rank:
                                state["rankUp"] = {"platform": platform, "name": name, "rank": new_rank,
                                                   "at": int(time.time() * 1000)}
                                say(f"🎖️ {name} rütbe atladı: artık {new_rank}!", platform)
                            if name.casefold() not in BROADCASTERS and not any(x["platform"] == platform and x["name"].casefold() == name.casefold() for x in state["crew"]):
                                state["crew"] = (state["crew"] + [{"platform": platform, "name": name}])[-24:]
                            if "🔥" in message and _suggestion and time.time() < _suggestion["until"] and name.casefold() not in BROADCASTERS:
                                _suggestion["fans"].add(f"{platform}:{name.casefold()}")
                            match = re.fullmatch(r"!rota\s+([1-3])", message, re.IGNORECASE)
                            if match:
                                index = int(match.group(1)) - 1
                                if index < len(state["routes"]):
                                    state["votes"][platform + ":" + name.casefold()] = index
                            guess = re.fullmatch(r"!tahmin\s+(\S+)(?:\s+(\S+))?", message, re.IGNORECASE)
                            if guess and guess.group(1).isdigit() and not guess.group(2):
                                guess_vote(platform, name, int(guess.group(1)))
                            elif guess and guess.group(1).casefold() in PREDICT_WORDS:
                                if state["prediction"]["status"] == "open":
                                    predict_vote(platform, name, PREDICT_WORDS[guess.group(1).casefold()], guess.group(2))
                                elif cooldown(f"predclosed:{platform}:{name.casefold()}", 60):
                                    locked = state["prediction"]["status"] == "locked"
                                    say(f"🔒 @{name} " + ("tahminler kilitlendi, sonucu bekliyoruz!" if locked else "maç tahmini şu an kapalı, maç başlayınca açılır!"), platform)
                            command = message.split()[0].casefold()
                            if command in ("!rütbe", "!rutbe", "!rank") and cooldown(f"rank:{platform}:{name.casefold()}", 20):
                                say(rank_text(platform, name), platform)
                            elif command in ("!kart", "!kimlik"):
                                show_card(platform, name)
                            elif command in ("!olta", "!balık", "!balik"):
                                cast_line(platform, name)
                            elif command in CHAT_LINKS and cooldown(f"link:{platform}:{command}", 30):
                                say(CHAT_LINKS[command], platform)
                            elif command == "!kehanet" and len(message) > 12 and cooldown(f"oracle:{platform}:{name.casefold()}", 20):
                                say(f"@{name} {random.choice(ORACLE)}", platform)
                            elif command == "!klip":
                                viewer_clip(platform, name)
                            elif command in ("!süre", "!sure", "!uptime") and cooldown("uptime", 30):
                                say(uptime_text(), platform)
                            elif command in ("!program", "!takvim") and cooldown("schedule", 30):
                                say(schedule_text(), platform)
                            elif command in ("!ölüm", "!olum", "!ölümler", "!deaths") and cooldown("deaths", 20):
                                say(deaths_text(), platform)
                            elif command in ("!çark", "!cark") and cooldown("wheel", 20):
                                last = state.get("wheelLast")
                                say(f"🎡 Çarkın son seçimi: {last}" if last else "🎡 Kütüphane çarkı bu akşam henüz dönmedi · kaptan çevirince burada!", platform)
                            elif command in ("!öner", "!oner") and cooldown("suggest", 30):
                                say(suggest_game(), platform)
                            elif command == "!hedef" and cooldown("goal", 30):
                                say(goal_text(), platform)
                            elif command in ("!lurk", "!afk") and cooldown(f"lurk:{platform}:{name.casefold()}", 600):
                                say(f"💤 {name} ambara indi, sessizce dinliyor. Hamakta iyi dinlemeler! ⚓", platform)
                            elif command == "!skor" and cooldown("score", 30):
                                say(score_text(), platform)
                            elif command == "!hafta" and cooldown("week", 20):
                                say(week_text(), platform)
                            elif command == "!sezon" and cooldown(f"season:{platform}:{name.casefold()}", 20):
                                say(season_text(platform, name), platform)
                            elif command in ("!düello", "!duello"):
                                duel_challenge(platform, name, message.split()[1:])
                            elif command == "!kabul":
                                duel_answer(platform, name, True)
                            elif command == "!red":
                                duel_answer(platform, name, False)
                            elif command in MARKET_ALIASES:
                                buy(platform, name, MARKET_ALIASES[command])
                            elif command == "!market" and cooldown(f"market:{platform}:{name.casefold()}", 20):
                                say(market_text(platform, name), platform)
                            elif command == "!oyna":
                                queue_join(platform, name, message.split(None, 1)[1] if " " in message else "")
                            elif command in ("!sıram", "!siram") and cooldown(f"sira:{platform}:{name.casefold()}", 15):
                                say(queue_position_text(platform, name), platform)
                            elif command in ("!çık", "!cik", "!çik"):
                                queue_leave(platform, name)
                            elif command in ("!şarkı", "!sarki", "!sr", "!çalan", "!calan"):
                                query = message.split(None, 1)[1].strip() if " " in message and command in ("!şarkı", "!sarki", "!sr") else ""
                                _spawn(song_request(platform, name, query))
                            elif command == "!soru":
                                ask_question(platform, name, message.split(None, 1)[1] if " " in message else "")
                            elif command in ("!koleksiyon", "!kolleksiyon") and cooldown(f"coll:{platform}:{name.casefold()}", 20):
                                say(collection_text(platform, name), platform)
                            elif command == "!ganimet" and cooldown(f"loot:{platform}:{name.casefold()}", 20):
                                say(loot_text(platform, name), platform)
                            elif command in ("!saldır", "!saldir", "!vur"):
                                kraken_hit(platform, name)
                            elif command in ("!katıl", "!katil"):
                                race_join(platform, name)
                            elif command in ("!ateş", "!ates", "!ateş!", "!fire"):
                                pirate_fire(platform, name)
                            elif command in ("!komutlar", "!komut", "!help") and cooldown(f"help:{platform}", 30):
                                say(HELP_TEXT, platform)
                        elif kind == "AdRun":
                            on_ad(data)
                        elif kind in ("HypeTrainStart", "HypeTrainLevelUp", "HypeTrainEnd"):
                            on_hype(kind, data)
                        elif kind == "RewardRedemption":
                            on_reward(platform, name, data)
                        elif kind == "Raid":
                            on_raid(platform, data)
                        elif kind == "Follow":
                            state["stats"][platform]["follow"] += 1
                            check_goal()
                            follower = data.get("targetUser") if platform == "twitch" and isinstance(data.get("targetUser"), dict) else None
                            thank_supporter(platform, clean((follower or {}).get("name") or (follower or {}).get("login"), 32) or name, "follow")
                        elif kind in ("Sub", "ReSub", "GiftSub", "Subscription", "Resubscription", "GiftSubscription"):
                            state["stats"][platform]["sub"] += 1
                            thank_supporter(platform, name, "gift" if "Gift" in kind else "sub")
                        elif kind == "Cheer" and platform == "twitch":
                            bits = int(data.get("bits") or 0)
                            state["stats"][platform]["bits"] += bits
                            thank_supporter(platform, name, "bits", bits)
                        elif kind == "KicksGifted" and platform == "kick":
                            amount = data.get("kicks") or {}
                            kicks = int((amount.get("amount") if isinstance(amount, dict) else None) or data.get("amount") or 0)
                            state["stats"][platform]["kicks"] += kicks
                            thank_supporter(platform, name, "kicks", kicks)
                        else:
                            continue
                        await publish()
                    except (ValueError, TypeError, KeyError):
                        continue
        except (OSError, TimeoutError, Exception) as exc:
            sb_conn["ws"] = None
            if state["connection"] != "waiting":
                state["connection"] = "waiting"
                await publish()
            print(f"Streamer.bot bekleniyor: {type(exc).__name__}", flush=True)
            await asyncio.sleep(3)


# ------------------------------------------------------------------- OBS --

def obs_auth_string(password, salt, challenge):
    """obs-websocket v5 auth: base64(sha256(base64(sha256(password+salt)) + challenge))."""
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest()).decode("utf-8")
    return base64.b64encode(hashlib.sha256((secret + challenge).encode("utf-8")).digest()).decode("utf-8")


async def obs_request(request_type, data=None, timeout=2):
    """Send an obs-websocket request and wait for its response data (None if OBS is away)."""
    ws = obs_conn.get("ws")
    if not ws:
        return None
    rid = f"qedy-{time.time()}"
    future = asyncio.get_running_loop().create_future()
    obs_pending[rid] = future
    try:
        await ws.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": rid, "requestData": data or {}}}))
        return await asyncio.wait_for(future, timeout)
    except Exception:
        return None
    finally:
        obs_pending.pop(rid, None)


async def obs_set_scene(name):
    ws = obs_conn.get("ws")
    if not ws or not name:
        return False
    try:
        await ws.send(json.dumps({
            "op": 6,
            "d": {"requestType": "SetCurrentProgramScene", "requestId": f"qedy-{datetime.now().timestamp()}",
                  "requestData": {"sceneName": name}},
        }))
        return True
    except Exception:
        return False


async def obs_client():
    while True:
        try:
            async with connect(OBS_URL, open_timeout=3, max_size=2**20) as ws:
                hello = json.loads(await ws.recv())
                d = hello.get("d", {})
                identify = {"rpcVersion": d.get("rpcVersion", 1), "eventSubscriptions": 1 << 2}  # Scenes events
                auth = d.get("authentication")
                if auth:
                    identify["authentication"] = obs_auth_string(OBS_PASSWORD, auth["salt"], auth["challenge"])
                await ws.send(json.dumps({"op": 1, "d": identify}))
                identified = json.loads(await ws.recv())
                if identified.get("op") != 2:
                    raise ConnectionError("OBS identify reddedildi (şifreyi kontrol et)")
                obs_conn["ws"] = ws
                state["obsConnection"] = "connected"
                await publish()
                _spawn(load_current_scene())
                async for raw in ws:
                    try:
                        d = json.loads(raw).get("d") or {}
                    except ValueError:
                        continue
                    if d.get("eventType") == "CurrentProgramSceneChanged":
                        on_scene((d.get("eventData") or {}).get("sceneName"))
                        await publish()
                        continue
                    future = obs_pending.get(d.get("requestId"))
                    if future and not future.done():
                        ok = (d.get("requestStatus") or {}).get("result", True)
                        future.set_result((d.get("responseData") or {}) if ok else None)  # failed request = no answer
        except (OSError, TimeoutError, Exception) as exc:
            obs_conn["ws"] = None
            if state["obsConnection"] != "waiting":
                state["obsConnection"] = "waiting"
                await publish()
            print(f"OBS bekleniyor: {type(exc).__name__}", flush=True)
            await asyncio.sleep(3)



async def load_current_scene():
    reply = await obs_request("GetCurrentProgramScene") or {}
    name = reply.get("currentProgramSceneName") or reply.get("sceneName")
    if name:
        state["scene"] = name  # just remember it; no chat line for the scene we connected into
        await publish()


_break_mark = []  # [chat count, casts] when the break started


def on_scene(name):
    """Scene-aware host lines: break, back on deck, starting soon, goodbye."""
    if not name or name == state["scene"]:
        return
    previous, state["scene"] = state["scene"], name
    lowered = name.casefold()
    kind = "mola" if "mola" in lowered else "bitti" if "bitti" in lowered else "basliyor" if "başlıyor" in lowered else "oyun"
    chat_now = state["stats"]["twitch"]["chat"] + state["stats"]["kick"]["chat"]
    if kind == "mola":
        _break_mark[:] = [chat_now, state["night"]["casts"]]
    if kind == "oyun" and "mola" not in previous.casefold():
        return  # only "back from break" is worth saying among in-show switches
    if not cooldown(f"scene:{kind}", 120):
        return
    if kind == "mola":
        say("⏸️ Kısa mola! Birazdan güvertedeyiz — bu arada !olta atıp ganimet toplayın 🎣")
    elif kind == "basliyor":
        say("▶️ Yayın birazdan başlıyor! Beklerken !olta ile ısının, yelkenler fora 🎣")
    elif kind == "oyun":
        chat, casts = (chat_now - _break_mark[0], state["night"]["casts"] - _break_mark[1]) if _break_mark else (0, 0)
        while_away = " · ".join(([f"💬 {chat} mesaj"] if chat else []) + ([f"🎣 {casts} olta"] if casts else []))
        say("⚓ Güverteye döndük! Kaldığımız yerden devam." + (f" Molada siz boş durmamışsınız: {while_away} 👏" if while_away else ""))
        _break_mark.clear()
    else:
        king = loot_king()
        crown = f" 👑 Gecenin ganimet kralı: {king['name']} ({king['loot']})." if king else ""
        nxt = schedule_text(next_only=True)
        say(f"⏹️ Bu akşamlık bu kadar, teşekkürler mürettebat!{crown} " + (f"Bir sonraki sefer {nxt}'da, görüşürüz 🐾" if nxt else "Bir sonraki seferde görüşürüz 🐾"))

# ------------------------------------------------------------ mini games --
# Olta (!olta), Kraken (!saldır) and Yelken yarışı (!katıl). The bridge owns the rules; the overlay only draws state.
# Loot points ("ganimet") live in crew_db next to rank points but don't change ranks.

GAMES = CONFIG.get("games") or {}
FISH_COOLDOWN = int(GAMES.get("fishCooldownSec") or 60)
KRAKEN_CFG = GAMES.get("kraken") or {}
RACE_CFG = GAMES.get("race") or {}
LOOT = [  # name, emoji, points, weight (out of 1000)
    ("Hamsi", "🐟", 3, 380), ("Levrek", "🐠", 5, 240), ("Eski çizme", "🥾", 1, 120),
    ("Balon balığı", "🐡", 10, 100), ("Ahtapot", "🐙", 15, 70), ("Köpek balığı", "🦈", 25, 45),
    ("Deniz kızı pulu", "🧜", 40, 25), ("Altın sandık", "💰", 60, 15), ("Kraken dişi", "🦷", 100, 5),
]
_active = {}  # platform:name -> last chat time


def _spawn(coro):
    task = asyncio.get_running_loop().create_task(coro)
    _bot_tasks.add(task)
    task.add_done_callback(_bot_tasks.discard)


def _clear_later(key, event_id, seconds):
    """Drop a finished Kraken/race from the screen after its result has been shown."""
    async def run():
        await asyncio.sleep(seconds)
        if state[key] and state[key]["id"] == event_id:
            state[key] = None
            await publish()
    _spawn(run())


def add_loot(platform, name, points, best=None):
    entry = crew_db.setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "points": 0, "streams": 0, "show": None, "last": 0})
    entry["name"] = name
    entry["loot"] = entry.get("loot", 0) + points
    if platform in ("twitch", "kick"):
        season = entry.get("season") or {}
        if season.get("id") != season_id():
            season = {"id": season_id(), "loot": 0}
        season["loot"] += points
        entry["season"] = season
        week = entry.get("week") or {}
        if week.get("id") != week_id():
            week = {"id": week_id(), "loot": 0}
        week["loot"] += points
        entry["week"] = week
    if platform in ("twitch", "kick"):
        night = state["night"]["loot"].setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "name": name, "loot": 0})
        night["loot"] += points
    if best and best["points"] > (entry.get("best") or {}).get("points", -1):
        entry["best"] = best
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    return entry["loot"]


def loot_text(platform, name):
    entry = crew_db.get(f"{platform}:{name.casefold()}") or {}
    best = entry.get("best")
    tail = f" · en iyi: {best['emoji']} {best['name']} ({best['points']})" if best         else "" if entry.get("loot") else " · henüz bir şey yakalamadın, !olta yaz"
    return f"@{name} 🎣 ganimet: {balance(entry)} (toplam kazanılan {entry.get('loot', 0)}){tail}"


CUP_CFG = GAMES.get("fishCup") or {}
CUP_PRIZES = [50, 30, 15]


def cup_start():
    minutes = float(CUP_CFG.get("minutes") or 5)
    cid = f"c{time.time()}"
    state["fishCup"] = {"id": cid, "status": "active", "endsAt": int((time.time() + minutes * 60) * 1000), "best": {}}
    say(f"🏆 OLTA TURNUVASI BAŞLADI! {minutes:g} dakika boyunca !olta at, en değerli avı çıkaran kazanır · "
        f"ödüller {' / '.join(f'+{x}' for x in CUP_PRIZES)} ganimet · turnuvada olta beklemesi {CUP_COOLDOWN} sn")

    async def timer():
        await asyncio.sleep(minutes * 60)
        c = state["fishCup"]
        if c and c["id"] == cid and c["status"] == "active":
            cup_finish()
            await publish()
    _spawn(timer())


def cup_top(limit=3):
    return sorted(state["fishCup"]["best"].values(), key=lambda b: (-b["points"], b["at"]))[:limit]


def cup_finish(cancelled=False):
    c = state["fishCup"]
    c["status"] = "done"
    top = [] if cancelled else cup_top()
    for prize, b in zip(CUP_PRIZES, top):
        add_loot(b["platform"], b["name"], prize)
    c["podium"] = top
    if cancelled:
        say("🏆 Olta turnuvası iptal edildi.")
    elif not top:
        say("🏆 Olta turnuvası bitti ama kimse olta atmadı 🎣")
    else:
        medals = " · ".join(f"{m} {b['name']} {b['emoji']} {b['item']} (+{p})" for m, b, p in zip("🥇🥈🥉", top, CUP_PRIZES))
        auto_marker(f"🏆 Olta turnuvası: {top[0]['name']}")
        say(f"🏆 OLTA TURNUVASI BİTTİ! {medals}")
    _clear_later("fishCup", c["id"], 15)


CUP_COOLDOWN = int(CUP_CFG.get("cooldownSec") or 30)


def cast_line(platform, name):
    cup = state["fishCup"] if state["fishCup"] and state["fishCup"]["status"] == "active" else None
    if not cooldown(f"fish:{platform}:{name.casefold()}", 5 if platform == "kaptan" else CUP_COOLDOWN if cup else FISH_COOLDOWN):
        return False
    item, emoji, points, _ = random.choices(LOOT, weights=[x[3] for x in LOOT])[0]
    rarity = "efsane" if points >= 40 else "nadir" if points >= 15 else "sıradan"
    entry = crew_db.setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "points": 0, "streams": 0, "show": None, "last": 0})
    caught = entry.setdefault("caught", [])
    new = item not in caught
    if new:
        caught.append(item)
    complete = new and len(caught) == len(LOOT)
    total = add_loot(platform, name, points + (100 if complete else 0), {"name": item, "emoji": emoji, "points": points})
    state["night"]["casts"] += 1
    if cup and platform in ("twitch", "kick"):
        key = f"{platform}:{name.casefold()}"
        if points > (cup["best"].get(key) or {}).get("points", -1):
            cup["best"][key] = {"platform": platform, "name": name, "points": points, "item": item, "emoji": emoji, "at": time.time()}
    state["catches"] = (state["catches"] + [{"id": f"f{time.time()}", "platform": platform, "name": name,
                                             "item": item, "emoji": emoji, "points": points, "rarity": rarity, "new": new}])[-12:]
    if complete:
        async def crown():
            await asyncio.sleep(4)
            say(f"🏆 {name} olta koleksiyonunu tamamladı! 9/9 ganimet · +100 bonus · artık bir Balıkçı Reisi 🎣")
        _spawn(crown())
    if points >= 60:
        auto_marker(f"{emoji} {name}: {item}")
    if points >= 25:
        async def brag():
            await asyncio.sleep(4)  # after the overlay's reveal, not before
            say(f"🎣 {name} {emoji} {item} yakaladı! +{points} ganimet (toplam {total})")
        _spawn(brag())
    return True


# Market: spend loot on screen effects. Earned total (leaderboard) stays; "spent" is tracked beside it.
MARKET = {"martı": ("🕊️", 15), "konfeti": ("🎉", 20), "top": ("💥", 40)}
MARKET_ALIASES = {"!martı": "martı", "!marti": "martı", "!konfeti": "konfeti", "!top": "top"}


def balance(entry):
    return entry.get("loot", 0) - entry.get("spent", 0)


def market_text(platform, name):
    entry = crew_db.get(f"{platform}:{name.casefold()}") or {}
    items = " · ".join(f"{emoji} !{item} {price}" for item, (emoji, price) in MARKET.items())
    return f"🛒 Market: {items} · @{name} sende {balance(entry)} ganimet var"


def buy(platform, name, item):
    key = f"{platform}:{name.casefold()}"
    emoji, price = MARKET[item]
    if not state["market"] or not cooldown(f"buy:{key}", 10):
        return
    entry = crew_db.get(key) or {}
    if balance(entry) < price:
        if cooldown(f"poor:{key}", 30):
            say(f"@{name} {emoji} !{item} için {price} ganimet lazım, sende {balance(entry)} var — !olta ile topla 🎣", platform)
        return
    now = time.time()
    if now - _cmd_last.get(f"effect:{item}", 0) < 8:  # same effect again too soon: don't charge
        return
    _cmd_last[f"effect:{item}"] = now
    entry["spent"] = entry.get("spent", 0) + price
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    state["effects"] = (state["effects"] + [{"id": f"e{now}", "type": item, "name": name, "platform": platform}])[-10:]


def collection_text(platform, name):
    entry = crew_db.get(f"{platform}:{name.casefold()}") or {}
    caught = set(entry.get("caught") or [])
    shelf = " ".join(emoji if item in caught else "❔" for item, emoji, _, _ in LOOT)
    tail = " · 🏆 Balıkçı Reisi!" if len(caught) == len(LOOT) else " · tamamlayana +100 ganimet"
    return f"@{name} 🎣 koleksiyon {len(caught)}/{len(LOOT)}: {shelf}{tail}"


def show_card(platform, name):
    """!kart: the member's crew card on screen for a few seconds, plus the same facts in chat."""
    if not cooldown(f"card:{platform}:{name.casefold()}", 60) or not cooldown("card", 12):
        return False
    entry = crew_db.get(f"{platform}:{name.casefold()}") or {}
    state["crewCard"] = {"platform": platform, "name": name, "rank": rank_for(entry.get("points", 0)),
                         "points": entry.get("points", 0), "loot": balance(entry), "streams": entry.get("streams", 0),
                         "streak": entry.get("streak", 0), "first": entry.get("first"), "best": entry.get("best"),
                         "at": int(time.time() * 1000)}
    say(rank_text(platform, name), platform)
    return True


def follows_tonight():
    return state["stats"]["twitch"]["follow"] + state["stats"]["kick"]["follow"]


def check_goal():
    """Tonight's follow goal: celebrate once on screen and in chat when it's reached."""
    goal = state["goal"]
    if goal["target"] and not goal["reached"] and follows_tonight() >= goal["target"]:
        goal["reached"] = True
        auto_marker(f"🎯 Takip hedefi ({goal['target']})")
        state["effects"] = (state["effects"] + [{"id": f"g{time.time()}", "type": "goal", "name": str(goal["target"]), "platform": ""}])[-10:]
        say(f"🎯 Bu akşamki {goal['target']} takipçi hedefimize ulaştık! Teşekkürler mürettebat, yelkenler dolu ⚓")


REQUIRED_ACTIONS = ["QedyStreamInfo", "QedyClip", "QedySayTwitch", "QedySayKick",
                    "ModTimeoutTwitch", "ModBanTwitch", "ModTimeoutKick", "ModBanKick"]


async def preflight():
    """Pre-show checklist for the panel: [label, ok, detail]."""
    items = [["OBS bağlı", bool(obs_conn.get("ws")), ""],
             ["Streamer.bot bağlı", bool(sb_conn.get("ws")), ""]]
    listing = await sb_request({"request": "GetActions"}) if sb_conn.get("ws") else None
    if listing is not None:
        have = {a.get("name"): a.get("subaction_count", 0) for a in listing.get("actions") or []}
        missing = [n for n in REQUIRED_ACTIONS if not have.get(n)]
        items.append([f"Streamer.bot action'ları ({len(REQUIRED_ACTIONS) - len(missing)}/{len(REQUIRED_ACTIONS)})", not missing,
                      "eksik/boş: " + ", ".join(missing) if missing else ""])
    items.append(["Discord webhook", bool(DISCORD_WEBHOOK), "" if DISCORD_WEBHOOK else "show-config.local.json > discordWebhook"])
    health = state.get("health") or {}
    if health:
        items.append(["Mikrofon açık", not health.get("micMuted"), health.get("mic", "")])
    bot_on = state.get("botChat", True)
    items.append(["Bot sohbette konuşuyor", bot_on, "" if bot_on else "kapalıyken oyun duyuruları gitmez"])
    return items


async def rehearsal():
    """~25 s on-screen demo (raid, catch, confetti, Kraken) with the bot silenced and no stats or loot touched."""
    _rehearsing[0] = True
    try:
        now = time.time()
        state["raid"] = {"id": f"prova{now}", "platform": "twitch", "name": "Prova Korsanı", "viewers": 12}
        await publish()
        await asyncio.sleep(5)
        state["raid"] = None
        fake = {"id": f"fprova{now}", "platform": "twitch", "name": "Prova", "item": "Altın sandık", "emoji": "💰",
                "points": 60, "rarity": "efsane", "new": True}
        state["catches"] = state["catches"] + [fake]
        await publish()
        await asyncio.sleep(6.5)
        state["catches"] = [c for c in state["catches"] if c["id"] != fake["id"]]
        state["effects"] = (state["effects"] + [{"id": f"eprova{now}", "type": "konfeti", "name": "Prova", "platform": "twitch"}])[-10:]
        await publish()
        await asyncio.sleep(3)
        kid = f"kprova{now}"
        state["kraken"] = {"id": kid, "status": "active", "hp": 30, "max": 30, "endsAt": int((time.time() + 12) * 1000),
                           "hits": {}, "last": [], "killer": None}
        await publish()
        for dmg, who in ((6, "Prova −6"), (9, "Prova −9 💥"), (8, "Prova −8"), (7, "Prova −7")):
            await asyncio.sleep(1.4)
            k = state["kraken"]
            if not k or k["id"] != kid:
                return
            k["hp"] = max(0, k["hp"] - dmg)
            k["last"] = ([who] + k["last"])[:4]
            await publish()
        state["kraken"].update(status="won", killer="Prova")
        await publish()
        await asyncio.sleep(4)
        if state["kraken"] and state["kraken"]["id"] == kid:
            state["kraken"] = None
            await publish()
    finally:
        _rehearsing[0] = False


async def mark(note, auto=False, live_only=False):
    """Store a highlight with the stream time (VOD/YouTube list) and the local recording time
    (make-clips.py cuts from the recording, which may have started at a different moment)."""
    stream = await obs_request("GetStreamStatus") or {}
    record = await obs_request("GetRecordStatus") or {}
    if live_only and not stream.get("outputActive"):
        return False
    tc = lambda s: str(s.get("outputTimecode") or "").split(".")[0] if s.get("outputActive") else None
    marker = {"time": datetime.now().strftime("%H:%M"), "vod": tc(stream), "rec": tc(record), "note": note}
    if auto:
        marker["auto"] = True
    state["markers"] = (state["markers"] + [marker])[-50:]
    return True


def auto_marker(note):
    """Mark a highlight's VOD time for the YouTube edit (only while live, not during the rehearsal)."""
    if _rehearsing[0]:
        return

    async def run():
        if not await mark(note, auto=True, live_only=True):
            return
        if state["autoClip"] and cooldown("clip:any", 120):
            await sb_do_action("QedyClip", {"note": note})
        await publish()
    _spawn(run())


# !oyna: viewers queue up to play with the host (community nights); the panel calls them one by one.

def _queue_index(platform, name):
    key = f"{platform}:{name.casefold()}"
    return next((i for i, x in enumerate(state["playQueue"]) if f"{x['platform']}:{x['name'].casefold()}" == key), -1)


def queue_join(platform, name, ign):
    key = f"{platform}:{name.casefold()}"
    if not state["playQueueOpen"]:
        if cooldown(f"qclosed:{key}", 60):
            say(f"@{name} birlikte oynama sırası şu an kapalı, açılınca duyuracağız ⚓", platform)
        return
    at = _queue_index(platform, name)
    if at >= 0:
        if cooldown(f"qdup:{key}", 20):
            say(f"@{name} zaten sıradasın ({at + 1}. sıra).", platform)
        return
    if len(state["playQueue"]) >= 30:
        return
    state["playQueue"].append({"id": f"p{time.time()}", "platform": platform, "name": name, "ign": clean(ign, 40)})
    say(f"🎮 @{name} sıraya girdin ({len(state['playQueue'])}. sıra). Çıkmak için !çık", platform)


def queue_position_text(platform, name):
    at = _queue_index(platform, name)
    return f"@{name} {at + 1}. sıradasın, önünde {at} kişi var." if at >= 0 else f"@{name} sırada değilsin." + (" !oyna ile girebilirsin." if state["playQueueOpen"] else "")


def queue_leave(platform, name):
    at = _queue_index(platform, name)
    if at >= 0:
        state["playQueue"].pop(at)


def queue_call(entry_id):
    entry = next((x for x in state["playQueue"] if x["id"] == entry_id), None)
    if not entry:
        return
    state["playQueue"].remove(entry)
    state["playCalled"] = {**entry, "at": int(time.time() * 1000)}
    ign = f" (oyun içi: {entry['ign']})" if entry["ign"] else ""
    say(f"🎮 @{entry['name']} sıra sende{ign}! Lobiye gel, kaptan seni bekliyor ⚓", entry["platform"])


# Supporters: a chat thank-you plus loot, so support also feeds the mini-game economy.
_follow_batch = {}  # platform -> names waiting for one grouped welcome


def support_alert(platform, text, big=False):
    """On-screen thank-you banner for follows, subs, bits and Kicks (every scene with the show layer)."""
    if not state["alerts"]:
        return
    state["effects"] = (state["effects"] + [{"id": f"s{time.time()}", "type": "support", "name": text, "platform": platform, "big": big}])[-10:]


def thank_supporter(platform, name, kind, amount=0):
    if not name or _rehearsing[0]:
        return
    if kind == "follow":
        add_loot(platform, name, 10)
        waiting = _follow_batch.setdefault(platform, [])
        if name not in waiting:
            waiting.append(name)
        if len(waiting) == 1:  # first in a burst: welcome everyone together a few seconds later

            async def flush():
                await asyncio.sleep(8)
                names = _follow_batch.pop(platform, [])
                if names:
                    shown = ", ".join(names[:3]) + (f" ve {len(names) - 3} kişi daha" if len(names) > 3 else "")
                    say(f"👋 Güverteye hoş geldin{'iz' if len(names) > 1 else ''} {shown}! Takip için teşekkürler, +10 ganimet 🎣", platform)
                    support_alert(platform, f"👋 {shown} güverteye katıldı!")
                    await publish()
            _spawn(flush())
    elif kind in ("sub", "gift"):
        add_loot(platform, name, 50)
        what = "abonelik hediye etti" if kind == "gift" else "abone oldu"
        say(f"⭐ {name} {what}, çok teşekkürler! +50 ganimet 🎉", platform)
        support_alert(platform, f"⭐ {name} {what}!", big=True)
    elif amount > 0:
        loot = max(1, amount // 10)
        add_loot(platform, name, loot)
        unit = "bit" if kind == "bits" else "Kicks"
        say(f"💎 {name} {amount} {unit} gönderdi, teşekkürler! +{loot} ganimet", platform)
        support_alert(platform, f"💎 {name} {amount} {unit} gönderdi!", big=amount >= 500)


# !düello @isim [miktar]: a loot wager between two viewers (any platform). 50/50, the winner takes the stake.
_duels = {}  # target name (casefold) -> pending challenge


def _entry(platform, name):
    return crew_db.get(f"{platform}:{name.casefold()}") or {}


def duel_challenge(platform, name, args):
    target = next((a.lstrip("@") for a in args if not a.isdigit()), "")
    amount = next((int(a) for a in args if a.isdigit()), 10)
    if not target or target.casefold() == name.casefold() or not cooldown(f"duel:{platform}:{name.casefold()}", 30):
        return
    amount = max(5, min(100, amount))
    if balance(_entry(platform, name)) < amount:
        say(f"@{name} ⚔️ {amount} ganimetlik düello için bakiyen yetmiyor ({balance(_entry(platform, name))}).", platform)
        return
    _duels[target.casefold()] = {"platform": platform, "name": name, "target": target, "amount": amount, "at": time.time()}
    say(f"⚔️ {name}, {target}'e {amount} ganimetine düello teklif etti! @{target} 30 sn içinde !kabul ya da !red yaz.")


def duel_answer(platform, name, accept):
    duel = _duels.get(name.casefold())
    if not duel or time.time() - duel["at"] > 30:
        _duels.pop(name.casefold(), None)
        return
    del _duels[name.casefold()]
    if not accept:
        say(f"🏳️ {name} düelloyu reddetti. {duel['name']} kılıcını kınına soktu.")
        return
    amount = duel["amount"]
    if balance(_entry(platform, name)) < amount:
        say(f"@{name} ⚔️ bu düello için {amount} ganimet lazım, bakiyen {balance(_entry(platform, name))}.", platform)
        return
    if balance(_entry(duel["platform"], duel["name"])) < amount:
        return  # the challenger spent it meanwhile
    challenger = (duel["platform"], duel["name"])
    fighters = [challenger, (platform, name)]
    winner = random.choice(fighters)
    loser = fighters[1] if winner == fighters[0] else fighters[0]
    add_loot(winner[0], winner[1], amount)
    lost = crew_db.setdefault(f"{loser[0]}:{loser[1].casefold()}", {"platform": loser[0], "points": 0, "streams": 0, "show": None, "last": 0})
    lost["spent"] = lost.get("spent", 0) + amount
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    state["effects"] = (state["effects"] + [{"id": f"d{time.time()}", "type": "duel", "name": f"{winner[1]}|{loser[1]}", "platform": winner[0]}])[-10:]
    say(f"⚔️ {duel['name']} ile {name} kılıç çekti… kazanan {winner[1]}! +{amount} ganimet 🏆")


AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def season_id():
    return datetime.now().strftime("%Y-%m")


def season_name():
    return AYLAR[datetime.now().month - 1]


def season_top(limit):
    rows = [{"platform": e["platform"], "name": e["name"], "loot": (e.get("season") or {}).get("loot", 0)}
            for e in crew_db.values() if (e.get("season") or {}).get("id") == season_id() and e["platform"] in ("twitch", "kick") and is_viewer(e.get("name"))]
    return sorted([r for r in rows if r["loot"]], key=lambda r: r["loot"], reverse=True)[:limit]


def week_id(when=None):
    year, week, _ = (when or datetime.now()).isocalendar()
    return f"{year}-W{week:02d}"


def week_top(limit, wid=None):
    wid = wid or week_id()
    rows = [{"platform": e["platform"], "name": e["name"], "loot": (e.get("week") or {}).get("loot", 0)}
            for e in crew_db.values() if (e.get("week") or {}).get("id") == wid and e["platform"] in ("twitch", "kick") and is_viewer(e.get("name"))]
    return sorted([r for r in rows if r["loot"]], key=lambda r: r["loot"], reverse=True)[:limit]


WEEK_BONUS = [100, 50, 25]


def award_last_week(prev_show):
    """First show of a new week: last week's top three loot hunters get a bonus and a shout."""
    try:
        last = week_id(datetime.fromisoformat(str(prev_show)))
    except ValueError:
        return
    if last == week_id() or state.get("weekAwarded") == last:
        return
    state["weekAwarded"] = last
    top = week_top(3, last)
    if not top:
        return
    for row, bonus in zip(top, WEEK_BONUS):
        row["bonus"] = bonus
        entry = crew_db.get(f"{row['platform']}:{row['name'].casefold()}")
        if entry:
            entry["loot"] = entry.get("loot", 0) + bonus
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    state["weekChamps"] = {"week": last, "top": top}
    medals = ["🥇", "🥈", "🥉"]
    say("🏆 Geçen haftanın mürettebatı: " + " · ".join(f"{medals[i]} {r['name']} (+{r['bonus']})" for i, r in enumerate(top))
        + " · Yeni hafta başladı, ganimet sıfırdan! 🎣")


def week_text():
    top = week_top(3)
    if not top:
        return "🗓️ Bu hafta henüz ganimet yok · !olta ile ilk sen başla! Haftanın ilk 3'üne pazartesi +100/+50/+25 🎁"
    medals = ["🥇", "🥈", "🥉"]
    return "🗓️ Haftanın mürettebatı: " + " · ".join(f"{medals[i]} {r['name']} {r['loot']}" for i, r in enumerate(top))         + " · Hafta sonunda ilk 3'e +100/+50/+25 🎁"


def season_text(platform, name):
    top = season_top(3)
    medals = ["🥇", "🥈", "🥉"]
    podium = " · ".join(f"{medals[i]} {r['name']} {r['loot']}" for i, r in enumerate(top)) or "henüz kimse yok"
    mine = (_entry(platform, name).get("season") or {})
    mine_loot = mine.get("loot", 0) if mine.get("id") == season_id() else 0
    return f"🏅 {season_name()} sezonu: {podium} · @{name} bu ay {mine_loot} ganimet"


ORACLE = [
    "🔮 Rüzgâr lehine esiyor: evet!", "🔮 Pusula titriyor… şimdilik hayır.", "🔮 Kraken bile bilmiyor, bir daha sor.",
    "🔮 Yıldızlar açık: kesinlikle evet.", "🔮 Sisli sular… bundan emin değilim.", "🔮 Martılar hayır diyor.",
    "🔮 Hazine haritası evet'i gösteriyor.", "🔮 Kaptan böyle emretti: evet!", "🔮 Fırtına yaklaşıyor, hayır.",
    "🔮 Belki… ama önce bir olta at.", "🔮 Ay dolunay: büyük ihtimalle evet.", "🔮 Denizkızları gülüyor, bu bir hayır.",
]
NUDGES = [
    "🌊 Güverte sessiz… !olta atan ilk kişi ne yakalayacak? 🎣",
    "🧭 Sohbet dümeni kimde? Kaptana aklındakini sor: !soru",
    "⚔️ Sessizlik mi? Bir tayfayı düelloya çağır: !düello @isim 10",
    "🏅 Bu ayın ganimet yarışı sürüyor, nerede olduğunu gör: !sezon",
]


async def quiet_deck():
    """While live, nudge a silent chat now and then (at most 3 times a show, 20 min apart)."""
    after = float((CONFIG.get("quietNudge") or {}).get("afterMinutes") or 12) * 60
    last_nudge, count, show = 0.0, 0, None
    while True:
        await asyncio.sleep(min(60, after / 2))
        try:
            if show != state.get("started"):
                show, count = state.get("started"), 0
            live = (state.get("health") or {}).get("live")
            last_chat = max(_active.values(), default=0)
            now = time.time()
            if live and count < 3 and now - last_chat > after and now - last_nudge > max(after, 20 * 60):
                say(NUDGES[count % len(NUDGES)])
                last_nudge, count = now, count + 1
        except Exception as exc:  # never let a nudge take the bridge down
            print(f"Sessiz güverte: {type(exc).__name__}", flush=True)


# Twitch channel points: rewards whose title is listed in show-config.json > channelPoints trigger a game effect.
REWARDS = {str(k).casefold(): v for k, v in (CONFIG.get("channelPoints") or {}).items()}


def on_reward(platform, name, data):
    reward = data.get("reward") if isinstance(data.get("reward"), dict) else {}
    title = clean(reward.get("title") or reward.get("name") or data.get("rewardName") or data.get("title"), 60)
    what = REWARDS.get(title.casefold())
    if not what or not name:
        return
    if what in MARKET:
        state["effects"] = (state["effects"] + [{"id": f"cp{time.time()}", "type": what, "name": name, "platform": platform}])[-10:]
    elif what == "olta":
        _cmd_last.pop(f"fish:{platform}:{name.casefold()}", None)  # paid with points: skip the cooldown
        cast_line(platform, name)
    elif what == "kraken":
        if event_busy():
            say(f"@{name} 🐙 şu an başka bir etkinlik sürüyor, Kraken birazdan! (kanal puanı iadesi için kaptana yaz)", platform)
            return
        say(f"🐙 {name} kanal puanıyla Krakeni uyandırdı!")
        kraken_start()


def game_scene():
    """The on-air game scene from obsScenes: the one that isn't start/break/end/chat."""
    for name in CONFIG.get("obsScenes") or []:
        lowered = name.casefold()
        if not any(word in lowered for word in ("başlıyor", "mola", "bitti", "sohbet")):
            return name
    return None


async def countdown_done(end_ms):
    """When the panel's countdown runs out on the starting/break screen, cut to the game scene."""
    await asyncio.sleep(max(0, end_ms / 1000 - time.time()))
    if state["countdown"] != end_ms:
        return  # cancelled or replaced
    state["countdown"] = None
    lowered = (state.get("scene") or "").casefold()
    target = game_scene()
    if state["cdAutoScene"] and target and ("başlıyor" in lowered or "mola" in lowered):
        await obs_set_scene(target)
    await publish()


def viewer_clip(platform, name):
    """!klip: chat can clip the moment (live only, one clip per 90 s for the whole chat)."""
    if not (state.get("health") or {}).get("live"):
        return
    if not cooldown("clip:chat", 90):
        return
    note = f"Sohbetten klip: {name}"

    async def run():
        await mark(note, auto=True)
        await publish()
    _spawn(run())
    _spawn(sb_do_action("QedyClip", {"note": note}))
    say(f"🎬 {name} bu anı klipledi! Link birazdan sohbette.", platform)


def _number(data, *keys):
    for key in keys:
        try:
            value = int(float(data.get(key)))
            if value > 0:
                return value
        except (TypeError, ValueError):
            continue
    return 0


def on_ad(data):
    """Twitch ad break: tell chat why the picture stopped, and show the panel how long it lasts."""
    seconds = _number(data, "length", "lengthSeconds", "duration", "durationSeconds", "length_seconds") or 90
    state["adUntil"] = int((time.time() + seconds) * 1000)
    say(f"📺 {seconds} saniyelik reklam arası, birazdan döneriz! Beklerken !olta 🎣", "twitch")


def on_hype(kind, data):
    """Twitch Hype Train: a card in the event lane, confetti, and chat call-outs per level."""
    level = _number(data, "level", "currentLevel") or 1
    if kind == "HypeTrainEnd":
        if state["hype"]:
            state["hype"] = {**state["hype"], "status": "ended", "level": max(level, state["hype"]["level"])}
            say(f"🚂 Hype Train seviye {state['hype']['level']}'de durdu. Muhteşemdiniz mürettebat, teşekkürler! 💜", "twitch")
            _clear_later("hype", state["hype"]["id"], 12)
        return
    if not state["hype"] or state["hype"].get("status") == "ended":
        state["hype"] = {"id": f"h{time.time()}", "status": "active", "level": level}
        say("🚂 HYPE TRAIN KALKTI! Abone, bit ve hediyelerle vagonları doldurun! 💜", "twitch")
    elif level > state["hype"]["level"]:
        state["hype"]["level"] = level
        say(f"🚂 Hype Train seviye {level}! Devam, devam! 💜", "twitch")
    state["effects"] = (state["effects"] + [{"id": f"hy{time.time()}", "type": "konfeti", "name": f"Hype Train {level}", "platform": "twitch"}])[-10:]


def uptime_text():
    health = state.get("health") or {}
    if not health.get("live") or not health.get("time"):
        return "⚓ Şu an yayında değiliz, Discord'dan haber veririz!"
    h, m, _ = (int(x) for x in health["time"].split(":"))
    spent = f"{h} saattir" if h and not m else f"{h} saat {m} dakikadır" if h else f"{max(m, 1)} dakikadır"
    return f"⏱ {spent} güvertedeyiz" + (f" · 🎮 {state['game']}" if state["game"] else "")


def shoutout(platform, name):
    """Panel's 📣: promote a chatter's own channel in both chats (once a minute per person)."""
    slug = re.sub(r"[^A-Za-z0-9_]", "", name)
    if platform not in ("twitch", "kick") or not slug or not cooldown(f"shout:{slug.casefold()}", 60):
        return
    url = f"https://twitch.tv/{slug}" if platform == "twitch" else f"https://kick.com/{slug.lower()}"
    say(f"📣 Mürettebattan {name} da yayıncı! Kanalına uğrayıp takip edin: {url} ⚓")


DAYS_TR = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def schedule_text(now=None, next_only=False):
    """!program: the weekly slot from show-config "weekly" (default Mon–Fri 20:30) and the next one."""
    weekly = CONFIG.get("weekly") or {}
    days = sorted(set(int(d) for d in weekly.get("days", [0, 1, 2, 3, 4]) if 0 <= int(d) <= 6)) or [0, 1, 2, 3, 4]
    hh, mm = (int(x) for x in str(weekly.get("time") or "20:30").split(":"))
    span = f"{DAYS_TR[days[0]]}–{DAYS_TR[days[-1]]}" if days == list(range(days[0], days[-1] + 1)) and len(days) > 1         else ", ".join(DAYS_TR[d] for d in days)
    base = f"📅 {span} her akşam {hh:02d}:{mm:02d}"
    themes = {int(k): v for k, v in (weekly.get("themes") or {}).items() if str(k).isdigit()}
    if not next_only and (state.get("health") or {}).get("live"):
        today = themes.get((now or datetime.now()).weekday())
        return f"{base} · şu an zaten güvertedeyiz!" + (f" Bugünün teması: 🎭 {today}" if today else "") + " ⚓"
    now = now or datetime.now()
    for ahead in range(8):
        day = now + timedelta(days=ahead)
        slot = day.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if day.weekday() in days and slot > now:
            left = int((slot - now).total_seconds() // 60)
            if next_only:
                return f"{DAYS_TR[day.weekday()]} {hh:02d}:{mm:02d}"
            when = "bugün" if ahead == 0 else "yarın" if ahead == 1 else DAYS_TR[day.weekday()]
            wait = f"{left // 60} saat {left % 60} dk sonra" if left >= 60 else f"{left} dk sonra"
            theme = f" · 🎭 {themes[day.weekday()]}" if day.weekday() in themes else ""
            return f"{base} · sıradaki sefer {when} {hh:02d}:{mm:02d}" + (f" ({wait})" if left < 24 * 60 else "") + theme + " 🐾"
    return "" if next_only else base


_library, _suggestion = [], {}
SUGGEST_SECONDS = float(os.environ.get("QEDY_SUGGEST_SEC") or 60)  # how long 🔥 votes count after !öner


async def suggestion_tally(name):
    """A minute after !öner: count the 🔥 replies and keep liked games on the panel's wishlist."""
    await asyncio.sleep(SUGGEST_SECONDS)
    if _suggestion.get("name") != name:
        return
    fans = len(_suggestion["fans"])
    _suggestion.clear()
    if not fans:
        return
    wish = next((w for w in state["wishlist"] if w["name"] == name), None)
    if wish:
        wish["votes"] += fans
    else:
        state["wishlist"].append({"name": name, "votes": fans})
    state["wishlist"] = sorted(state["wishlist"], key=lambda w: -w["votes"])[:10]
    say(f"🔥 {name} {fans} oy aldı, kaptanın listesine eklendi!")
    await publish()


# ------------------------------------------------------------ library wheel --
# "Kütüphane çarkı": 12 games from the captain's own library (chat's 🔥 picks guaranteed a slot) spin
# on screen; the winner is played next. The bridge picks the winner up front, so every screen lands on it.
WHEEL_MS = int(os.environ.get("QEDY_WHEEL_MS") or 7000)
NOT_GAMES = ("soundtrack", "dedicated server", "sdk", "overlay", "wallpaper", "demo", "playtest", "benchmark",
             "editor", "tool", "deathmatch", "multiplayer", "vr edition", "artbook", "bonus content")


def load_library():
    if not _library:
        try:
            _library.extend(g for g in json.loads((ROOT / "steam-library.json").read_text(encoding="utf-8")) if g.get("name"))
        except (OSError, ValueError):
            pass
    return _library


def steam_link(name):
    game = next((g for g in load_library() if g["name"] == name), {})
    return f"https://store.steampowered.com/app/{game['appid']}" if game.get("appid") else ""


async def wheel_spin():
    wheel = state.get("wheel") or {}
    if wheel.get("status") == "spinning":
        return False
    playing = str(state.get("game") or "").casefold()
    wish = [w["name"] for w in state["wishlist"] if w["name"].casefold() != playing][:4]
    pool = sorted({g["name"] for g in load_library() if g["name"] not in wish and g["name"].casefold() != playing
                   and not any(word in g["name"].casefold() for word in NOT_GAMES)})
    if len(pool) + len(wish) < 2:
        return False
    options = wish + random.sample(pool, min(len(pool), 12 - len(wish)))
    random.shuffle(options)
    index = random.randrange(len(options))
    wid = f"w{time.time()}"
    state["wheel"] = {"id": wid, "status": "spinning", "options": options, "index": index, "winner": options[index],
                      "wish": wish, "at": int(time.time() * 1000), "durationMs": WHEEL_MS}
    say(f"🎡 Kütüphane çarkı dönüyor! {len(load_library())} oyunluk kütüphaneden sıradaki oyun geliyor...")
    await publish()
    await asyncio.sleep(WHEEL_MS / 1000)
    if (state.get("wheel") or {}).get("id") != wid:
        return True
    winner = options[index]
    state["wheel"]["status"] = "done"
    state["wheelLast"] = winner
    link = steam_link(winner)
    say(f"🎡 Çark durdu: {winner}!" + (" 🔥 Sohbetin isteğiydi!" if winner in wish else "") + (f" · {link}" if link else ""))
    auto_marker(f"🎡 Çark: {winner}")
    await publish()
    _clear_later("wheel", wid, 30)
    return True


def suggest_game():
    """!öner: a random pick from the streamer's own game library (steam-library.json)."""
    picks = [g for g in load_library() if g["name"].casefold() != str(state.get("game") or "").casefold()]
    if not picks:
        return "🎲 Kütüphane şu an açılamadı, bir dahaki sefere!"
    game = random.choice(picks)
    _suggestion.clear()
    _suggestion.update({"name": game["name"], "until": time.time() + SUGGEST_SECONDS, "fans": set()})
    _spawn(suggestion_tally(game["name"]))
    link = f" · https://store.steampowered.com/app/{game['appid']}" if game.get("appid") else ""
    return f"🎲 Kaptanın {len(_library)} oyunluk kütüphanesinden rastgele: {game['name']}{link} · Bir dahaki yayına bu olsun mu? Beğenen 🔥 yazsın!"


def goal_text():
    goal, got = state["goal"], follows_tonight()
    if not goal["target"]:
        return f"🎯 Bu akşam {got} yeni takipçi geldi, hepinize hoş geldiniz!" if got else "🎯 Bu akşam henüz takip hedefi yok, ilk takip senden olsun!"
    if goal["reached"] or got >= goal["target"]:
        return f"🎯 {goal['target']} takipçi hedefine ulaştık ({got})! Yelkenler dolu ⚓"
    left = goal["target"] - got
    bar = "▰" * round(10 * got / goal["target"]) + "▱" * (10 - round(10 * got / goal["target"]))
    return f"🎯 Takip hedefi {got}/{goal['target']} {bar} · {left} kaldı!"


def score_text():
    m = state["matches"]
    if not m:
        return "🏆 Bu akşam henüz maç sonucu yok, ilk zafer yolda!"
    wins, streak = m.count("W"), 0
    for r in reversed(m):
        if r != m[-1]:
            break
        streak += 1
    tail = f" · {streak} maçlık {'galibiyet serisi 🔥' if m[-1] == 'W' else 'mağlubiyet serisi'}" if streak >= 2 else ""
    return f"🏆 Bu akşam {wins}G · {len(m) - wins}M" + tail


def log_event(platform, kind, data):
    """Keep the raw payload of every non-chat event (follows, subs, raids, Hype Train, ads...) in .events.jsonl."""
    try:
        line = json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "platform": platform, "type": kind, "data": data},
                          ensure_ascii=False, default=str)
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(line[:20000] + "\n")
        if EVENTS_FILE.stat().st_size > 2_000_000:  # keep the newest half
            lines = EVENTS_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
            EVENTS_FILE.write_text("".join(lines[len(lines) // 2:]), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- spotify --
# Now playing, playback control from the panel and chat song requests (!şarkı). Login once on this PC:
# panel "Spotify'a bağlan" → /spotify-login → Spotify → /spotify-callback (PKCE, no client secret).
# The refresh token lives in .spotify.json (gitignored, never served over HTTP).
SPOTIFY_ID = str((CONFIG.get("spotify") or {}).get("clientId") or "").strip()
SPOTIFY_ACCOUNTS = os.environ.get("QEDY_SPOTIFY_ACCOUNTS") or "https://accounts.spotify.com"
SPOTIFY_API = os.environ.get("QEDY_SPOTIFY_API") or "https://api.spotify.com/v1"
SPOTIFY_SEC = float(os.environ.get("QEDY_SPOTIFY_SEC") or 5)
SPOTIFY_FILE = DATA_DIR / ".spotify.json"
SPOTIFY_REDIRECT = f"http://127.0.0.1:{HTTP_PORT}/spotify-callback"
SPOTIFY_SCOPES = "user-read-currently-playing user-read-playback-state user-modify-playback-state"
SONG_MAX_MS = 7 * 60 * 1000
_spotify_verifier, _spotify_token, _requested = {}, {}, {}  # PKCE by state key · access token · track uri → requester
_spotify_lock = threading.Lock()  # token refreshes (loop, chat and panel calls run in threads)
_spotify_fails = [0]  # now-playing reads failed in a row


def spotify_login_url():
    verifier = secrets.token_urlsafe(72)[:96]
    key = secrets.token_urlsafe(16)
    _spotify_verifier.clear()
    _spotify_verifier[key] = verifier
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return f"{SPOTIFY_ACCOUNTS}/authorize?" + urllib.parse.urlencode({
        "client_id": SPOTIFY_ID, "response_type": "code", "redirect_uri": SPOTIFY_REDIRECT, "scope": SPOTIFY_SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": key})


def _spotify_token_request(fields):
    body = urllib.parse.urlencode({"client_id": SPOTIFY_ID, **fields}).encode()
    req = urllib.request.Request(f"{SPOTIFY_ACCOUNTS}/api/token", data=body,
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _spotify_keep(tok):
    if tok.get("refresh_token"):
        SPOTIFY_FILE.write_text(json.dumps({"refresh_token": tok["refresh_token"]}), encoding="utf-8")
    # update() swaps both keys at once, so a call in another thread never sees the token half-cleared
    _spotify_token.update(access_token=tok["access_token"], expires_at=time.time() + int(tok.get("expires_in") or 3600) - 60)


def _spotify_valid():
    return bool(_spotify_token.get("access_token")) and time.time() < _spotify_token.get("expires_at", 0)


def _spotify_renew():
    """One refresh at a time: Spotify may rotate the refresh token, so a second parallel refresh with the old one
    would be refused. A refused refresh (revoked, password changed) unlinks, so the panel shows 'bağlan' again."""
    with _spotify_lock:
        if _spotify_valid():
            return True  # another thread renewed it while we waited
        try:
            saved = json.loads(SPOTIFY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        try:
            _spotify_keep(_spotify_token_request({"grant_type": "refresh_token", "refresh_token": saved["refresh_token"]}))
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401):
                SPOTIFY_FILE.unlink(missing_ok=True)
                _spotify_token.clear()
                print("Spotify bağlantısı reddedildi · kumandadan 🔗 Spotify'a bağlan", flush=True)
                return False
            raise
        return True


def spotify_callback(query):
    """Runs in the HTTP thread: swap the login code for tokens."""
    params = urllib.parse.parse_qs(query)
    verifier = _spotify_verifier.pop((params.get("state") or [""])[0], None)
    code = (params.get("code") or [""])[0]
    if not code or not verifier:
        return False
    _spotify_keep(_spotify_token_request({"grant_type": "authorization_code", "code": code,
                                          "redirect_uri": SPOTIFY_REDIRECT, "code_verifier": verifier}))
    return True


def _spotify_sync(method, path, params=None):
    if not _spotify_valid() and not _spotify_renew():
        return None
    token = _spotify_token.get("access_token")
    if not token:
        return None
    url = SPOTIFY_API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, headers={"Authorization": f"Bearer {token}"},
                                 data=b"" if method in ("POST", "PUT") else None)
    with urllib.request.urlopen(req, timeout=8) as r:
        raw = r.read()
    try:
        return json.loads(raw) if raw.strip() else {}
    except ValueError:
        return {}  # some player endpoints answer 200 with a non-JSON body: the call still worked


async def spotify(method, path, params=None):
    """Spotify Web API call; None when not connected or it failed (the reason goes to the bridge window)."""
    if not SPOTIFY_ID:
        return None
    try:
        return await asyncio.to_thread(_spotify_sync, method, path, params)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            _spotify_token.clear()
        print(f"Spotify {method} {path}: HTTP {exc.code}", flush=True)
    except Exception as exc:
        print(f"Spotify hatası: {type(exc).__name__}", flush=True)
    return None


def spotify_linked():
    return bool(SPOTIFY_ID) and SPOTIFY_FILE.exists()


def track_info(t):
    images = (t.get("album") or {}).get("images") or []
    return {"uri": t.get("uri"), "title": clean(t.get("name"), 90), "artist": clean(", ".join(a.get("name", "") for a in t.get("artists") or []), 90),
            "art": images[-1]["url"] if images else "", "ms": int(t.get("duration_ms") or 0), "explicit": bool(t.get("explicit"))}


async def spotify_refresh():
    data = await spotify("GET", "/me/player/currently-playing")
    if data is None:
        # 3 failed reads in a row (~15 s): the song on screen is probably stale, so stop showing it as playing
        _spotify_fails[0] += 1
        m = state.get("music") or {}
        if _spotify_fails[0] >= 3 and m.get("playing"):
            state["music"] = {**m, "playing": False}
            await publish()
        return
    _spotify_fails[0] = 0
    item = data.get("item") if isinstance(data, dict) else None
    now = {"linked": True, "playing": bool(data.get("is_playing")) and bool(item), **(track_info(item) if item else {"title": ""})}
    upcoming = await spotify("GET", "/me/player/queue")
    old = state.get("music") or {}  # read after the last await: nothing below yields, so parallel refreshes can't interleave
    # A request is credited while it plays, then forgotten, so the same song from a playlist later isn't "istek: X" again.
    now["by"] = old.get("by") if now.get("uri") and now.get("uri") == old.get("uri") else _requested.pop(now.get("uri"), None)
    now["next"] = [{**{k: v for k, v in track_info(t).items() if k in ("title", "artist")}, "by": (_requested.get(t.get("uri")) or {}).get("name")}
                   for t in ((upcoming or {}).get("queue") or [])[:5] if t]
    if now.get("uri") and now["uri"] != old.get("uri") and now["by"] and now["playing"]:
        say(f"🎵 Şimdi çalıyor: {now['title']} — {now['artist']} · istek: {now['by']['name']}")
    if now != old:
        state["music"] = now
        await publish()


async def spotify_loop():
    while True:
        await asyncio.sleep(SPOTIFY_SEC)
        if spotify_linked():
            await spotify_refresh()
        elif state.get("music") != ({"linked": False} if SPOTIFY_ID else None):
            state["music"] = {"linked": False} if SPOTIFY_ID else None
            await publish()


def music_now_text():
    m = state.get("music") or {}
    if not m.get("playing") or not m.get("title"):
        return "🎵 Şu an müzik çalmıyor."
    return f"🎵 Şu an çalıyor: {m['title']} — {m['artist']}" + (f" · istek: {m['by']['name']}" if m.get("by") else "")


async def song_request(platform, name, query):
    """!şarkı <isim>: search, then wait for the captain's ✓ in the panel (nothing plays without approval)."""
    if not query:
        if cooldown("song:now", 15):
            say(music_now_text(), platform)
        return
    if not spotify_linked() or not state["musicOpen"]:
        if cooldown(f"song:closed:{platform}", 60):
            say("🎵 Şarkı istekleri şu an kapalı.", platform)
        return
    if len(state["musicRequests"]) >= 10:
        if cooldown("song:full", 30):
            say("🎵 İstek listesi dolu, kaptan biraz eritsin!", platform)
        return
    key = f"song:{platform}:{name.casefold()}"
    # Claimed before the search: requests run as parallel tasks, so two quick !şarkı would both pass a later check.
    # Every "didn't take" answer below gives the claim back.
    if not cooldown(key, 300):
        return
    found = await spotify("GET", "/search", {"q": query[:100], "type": "track", "limit": 1})
    items = ((found or {}).get("tracks") or {}).get("items") or []
    t = track_info(items[0]) if items else None
    reason = (f"🎵 @{name} bulamadım, sanatçıyla birlikte yazmayı dene." if not t else
              f"🎵 @{name} küfürlü şarkılar şu an kapalı, başka bir tane dene." if t["explicit"] and not state["musicExplicit"] else
              f"🎵 @{name} 7 dakikadan uzun şarkılar alınmıyor." if t["ms"] > SONG_MAX_MS else
              f"🎵 {t['title']} zaten listede." if any(r["uri"] == t["uri"] for r in state["musicRequests"]) else
              "🎵 İstek listesi dolu, kaptan biraz eritsin!" if len(state["musicRequests"]) >= 10 else None)
    if reason:
        _cmd_last.pop(key, None)
        say(reason, platform)
        return
    req = {**t, "id": f"s{time.time()}", "platform": platform, "name": name}
    if state["musicAuto"]:
        if await queue_track(req):
            say(f"✅ {t['title']} — {t['artist']} sıraya girdi, @{name}!", platform)
        else:
            _cmd_last.pop(key, None)
            say(f"🎵 @{name} şu an sıraya eklenemedi, birazdan tekrar dene.", platform)
    else:
        state["musicRequests"].append(req)
        say(f"🎵 {t['title']} — {t['artist']} kaptanın onayına gitti, @{name}!", platform)
    await publish()


async def queue_track(req):
    if await spotify("POST", "/me/player/queue", {"uri": req["uri"]}) is None:
        return False
    if req.get("name"):
        _requested[req["uri"]] = {"name": req["name"], "platform": req["platform"]}
    await spotify_refresh()
    return True


async def music_action(action, msg):
    if action == "musicApprove":
        req = next((r for r in state["musicRequests"] if r["id"] == msg.get("id")), None)
        if req and await queue_track(req):
            state["musicRequests"].remove(req)
            say(f"✅ {req['title']} sıraya girdi · istek: {req['name']}", req["platform"])
            return True
        return False
    if action == "musicAdd":  # the captain's own pick from the panel: no filters, straight into the queue
        found = await spotify("GET", "/search", {"q": clean(msg.get("query"), 100), "type": "track", "limit": 1})
        items = ((found or {}).get("tracks") or {}).get("items") or []
        return bool(items) and await queue_track(track_info(items[0]))
    if action == "musicReject":
        state["musicRequests"] = [r for r in state["musicRequests"] if r["id"] != msg.get("id")]
        return True
    paths = {"musicPlay": ("PUT", "/me/player/play"), "musicPause": ("PUT", "/me/player/pause"),
             "musicNext": ("POST", "/me/player/next"), "musicPrev": ("POST", "/me/player/previous")}
    ok = await spotify(*paths[action]) is not None
    await asyncio.sleep(0.4)
    await spotify_refresh()
    return ok


# ------------------------------------------------------- Streamer.bot log --
# Streamer.bot can say "Kick connected" while its Kick chat client is down (seen on the first real
# stream: 40 minutes of Kick chat lost). Its own log is the only honest signal, so we read the tail.
SB_LOG_DIR = Path(os.environ.get("QEDY_SB_LOGS") or CONFIG.get("streamerbotLogs") or
                  Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft/WinGet/Packages/streamerbot.streamerbot_Microsoft.Winget.Source_8wekyb3d8bbwe/logs")
KICK_DOWN = "KickService :: Disconnected from Broadcaster Chat Client"
KICK_UP = "KickService :: Connected to Broadcaster Chat Client"


def kick_chat_status():
    """'down' if the newest Kick chat line in today's Streamer.bot log is a disconnect older than 30 s, else 'ok' (None if no log)."""
    try:
        log = max(SB_LOG_DIR.glob("log_*.log"), key=lambda f: f.stat().st_mtime)
        with log.open("rb") as f:
            f.seek(max(0, log.stat().st_size - 400_000))
            tail = f.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return None
    down, up = tail.rfind(KICK_DOWN), tail.rfind(KICK_UP)
    if down <= up:
        return "ok"
    stamp = re.search(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)", tail[tail.rfind("\n", 0, down) + 1:down + 1])
    try:
        age = time.time() - datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    except (AttributeError, ValueError):
        age = 999
    return "down" if age > 30 else "ok"


async def sb_log_watch():
    warned = False
    while True:
        await asyncio.sleep(float(os.environ.get("QEDY_SB_LOG_SEC") or 20))
        status = await asyncio.to_thread(kick_chat_status)
        if status != state.get("kickChat"):
            state["kickChat"] = status
            if status == "down" and not warned:
                print("⚠ Streamer.bot Kick sohbet bağlantısı kopuk: Platforms → Kick → Disconnect / Connect", flush=True)
            warned = status == "down"
            await publish()


# ----------------------------------------------------------- death counter --
# 💀 for the hard-mode runs: tonight's count on screen plus a per-game total across shows (.deaths.json).
# +1 from the panel, chat can ask with !ölüm, and a global chord (default AltGr + . + ,) so the captain
# never has to leave the game.
DEATHS_FILE = DATA_DIR / ".deaths.json"
try:
    DEATH_TOTALS = json.loads(DEATHS_FILE.read_text(encoding="utf-8"))
except (OSError, ValueError):
    DEATH_TOTALS = {}
# competitive games never count; deathStart seeds a game's total once (e.g. the run so far)
DEATH_EXCLUDE = set(CONFIG.get("deathExclude") or [])
for _g in DEATH_EXCLUDE:
    DEATH_TOTALS.pop(_g, None)
for _g, _n in (CONFIG.get("deathStart") or {}).items():
    DEATH_TOTALS.setdefault(_g, int(_n))
_deaths_game = [None]
DEATH_LINES = {
    1: "💀 İlk ölüm geldi! Isınma turu sayılır ⚓",
    10: "💀 10 ölüm! Kaptan ölümden korkmuyor 😅",
    25: "💀 25 ölüm! Mezarlık güverteden kalabalık oldu.",
    50: "💀 50 ölüm! Kaptan artık ölümle kanka.",
    100: "💀 100 ÖLÜM! Efsane seviyesi, alkışlar mürettebata değil ölümlere 👏",
}


def deaths_sync():
    """Tonight's count belongs to one game: switching games starts that game's night at 0."""
    if _deaths_game[0] not in (None, state["game"]):
        state["deaths"] = 0
    _deaths_game[0] = state["game"]


def death_counts():
    return (state["game"] or "?") not in DEATH_EXCLUDE


def death_total():
    return int(DEATH_TOTALS.get(state["game"] or "?", 0))


def add_death(delta):
    deaths_sync()
    if not death_counts():
        return
    delta = 1 if delta > 0 else -1
    if delta < 0 and state["deaths"] <= 0:
        return
    state["deaths"] += delta
    game = state["game"] or "?"
    DEATH_TOTALS[game] = max(0, int(DEATH_TOTALS.get(game, 0)) + delta)
    try:
        DEATHS_FILE.write_text(json.dumps(DEATH_TOTALS, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    if delta > 0:
        state["deathAt"] = int(time.time() * 1000)
        line = DEATH_LINES.get(state["deaths"])
        if line and cooldown(f"death:{state['deaths']}", 60):
            say(line)


def deaths_text():
    deaths_sync()
    if not death_counts():
        return "💀 Bu oyunda ölüm sayılmıyor, rekabetçi gece ⚔️"
    n, total = state["deaths"], death_total()
    if not n and not total:
        return "💀 Bu akşam henüz ölüm yok, kaptan ayakta! ⚓"
    game = state["game"] or "bu oyun"
    return f"💀 Bu akşam {n} ölüm" + (f" · {game} toplamı {total}" if total > n else "")


def start_hotkeys(loop):
    """Global chord for +1 death while the game has focus: AltGr + . + , by default (polled, no extra packages).
    Keys are resolved from the active keyboard layout, so the chord follows the printed characters."""
    spec = CONFIG.get("deathHotkey", "altgr+.+,")
    if os.name != "nt" or not spec or os.environ.get("QEDY_HOTKEYS") == "0":
        return
    parts = [x for x in str(spec).lower().replace(" ", "").replace("++", "+plus").split("+") if x]
    chars = [("+" if x == "plus" else x) for x in parts if len(x) == 1 or x == "plus"]
    altgr = "altgr" in parts

    def run():
        import ctypes
        user32 = ctypes.windll.user32
        vks = [user32.VkKeyScanW(ord(c)) & 0xFF for c in chars]
        if not vks or 0xFF in vks:
            print(f"Ölüm kısayolu anlaşılamadı: {spec}", flush=True)
            return
        print(f"  Ölüm sayacı kısayolu: {spec}", flush=True)
        down = lambda vk: user32.GetAsyncKeyState(vk) & 0x8000
        held = False
        while True:
            now = (not altgr or (down(0xA5) or (down(0xA2) and down(0xA4)))) and all(down(vk) for vk in vks)
            if now and not held:
                loop.call_soon_threadsafe(_death_from_hotkey)
            held = now
            time.sleep(0.03)

    threading.Thread(target=run, daemon=True, name="hotkeys").start()


def _death_from_hotkey():
    add_death(1)
    _spawn(publish())


def recent_chatters(minutes=10):
    cutoff = time.time() - minutes * 60
    return sum(1 for t in _active.values() if t >= cutoff)


def kraken_start():
    duration = int(KRAKEN_CFG.get("durationSec") or 90)
    hp = min(300, max(40, 30 * recent_chatters()))  # ~30-40 s of !saldır for a small chat, well inside the 90 s window
    kid = f"k{time.time()}"
    state["kraken"] = {"id": kid, "status": "active", "hp": hp, "max": hp, "endsAt": int((time.time() + duration) * 1000),
                       "hits": {}, "last": [], "killer": None}
    say(f"🐙 KRAKEN SALDIRIYOR! Gemiyi kurtarmak için !saldır yaz · {duration} saniyen var!")

    async def timer():
        await asyncio.sleep(duration)
        k = state["kraken"]
        if k and k["id"] == kid and k["status"] == "active":
            kraken_finish(False)
            await publish()
    _spawn(timer())


def kraken_hit(platform, name):
    k = state["kraken"]
    if not k or k["status"] != "active" or not cooldown(f"hit:{platform}:{name.casefold()}", 1.5):
        return
    crit = random.random() < 0.08
    dmg = random.randint(1, 3) * (3 if crit else 1)
    k["hp"] = max(0, k["hp"] - dmg)
    hit = k["hits"].setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "name": name, "dmg": 0})
    hit["dmg"] += dmg
    k["last"] = ([f"{name} −{dmg}{' 💥' if crit else ''}"] + k["last"])[:4]
    if k["hp"] == 0:
        k["killer"] = name
        kraken_finish(True)


def kraken_finish(won, retreat=False):
    k = state["kraken"]
    k["status"] = "won" if won else "lost"
    if won:
        for h in k["hits"].values():
            add_loot(h["platform"], h["name"], min(40, 10 + h["dmg"]) + (25 if h["name"] == k["killer"] else 0))
        state["night"]["krakenWon"] += 1
        auto_marker(f"🐙 Kraken yenildi · son vuruş {k['killer']}")
        say(f"🐙 KRAKEN YENİLDİ! Son vuruş: {k['killer']} (+25 bonus) · saldıran {len(k['hits'])} kişiye ganimet dağıtıldı!")
    else:
        if not retreat:
            state["night"]["krakenLost"] += 1
        say("🐙 Kraken geri çekildi." if retreat else "🐙 Kraken kaçtı… Bir dahaki sefere daha sert vurun!")
    _clear_later("kraken", k["id"], 10)


async def kraken_random():
    """While the stream is live, a Kraken shows up every randomMin–randomMax minutes on its own."""
    low, high = int(KRAKEN_CFG.get("randomMinMinutes") or 25), int(KRAKEN_CFG.get("randomMaxMinutes") or 50)
    while True:
        await asyncio.sleep(random.uniform(low, high) * 60)
        status = await obs_request("GetStreamStatus")
        if state["krakenRandom"] and status and status.get("outputActive") and recent_chatters() \
                and not event_busy():
            kraken_start()
            await publish()


def event_busy():
    return state["kraken"] or state["race"] or state["pirate"] or state["tug"]


# Tug of war, Twitch vs Kick: every chat message pulls the rope toward its platform for durationSec.
TUG_CFG = GAMES.get("tug") or {}


def tug_start():
    duration = int(TUG_CFG.get("durationSec") or 60)
    tid = f"t{time.time()}"
    state["tug"] = {"id": tid, "status": "active", "endsAt": int((time.time() + duration) * 1000),
                    "twitch": 0, "kick": 0, "pullers": {}, "winner": None, "top": None}
    say(f"🪢 HALAT ÇEKME: TWITCH vs KICK! {duration} saniye boyunca yazdığın her mesaj halatı kendi tarafına çeker. Kazanan sohbete ganimet!")

    async def timer():
        await asyncio.sleep(duration)
        t = state["tug"]
        if t and t["id"] == tid and t["status"] == "active":
            tug_finish()
            await publish()
    _spawn(timer())


def tug_pull(platform, name):
    t = state["tug"]
    if not t or t["status"] != "active" or name.casefold() in BROADCASTERS or not cooldown(f"tug:{platform}:{name.casefold()}", 1):
        return
    t[platform] += 1
    p = t["pullers"].setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "name": name, "pulls": 0})
    p["pulls"] += 1


def tug_finish(cancelled=False):
    t = state["tug"]
    t["status"] = "done"
    if cancelled:
        say("🪢 Halat çekme iptal edildi.")
    elif t["twitch"] == t["kick"]:
        t["winner"] = "draw"
        say(f"🪢 Berabere! {t['twitch']} – {t['kick']} · halat ortada kaldı, iki sohbet de güçlü 💪")
    else:
        win = "twitch" if t["twitch"] > t["kick"] else "kick"
        t["winner"] = win
        side = [p for p in t["pullers"].values() if p["platform"] == win]
        top = max(side, key=lambda p: p["pulls"])
        t["top"] = top["name"]
        for p in side:
            add_loot(p["platform"], p["name"], 10 + (10 if p is top else 0))
        auto_marker(f"🪢 Halat çekmeyi {win.title()} kazandı")
        say(f"🪢 {win.upper()} KAZANDI! {t['twitch']} – {t['kick']} · {len(side)} kişiye +10 ganimet, en güçlü kol {top['name']} (+10)")
    _clear_later("tug", t["id"], 10)


# Pirate ship: crosses the screen in durationSec; every !ateş is a cannonball that hits ~45% of the time.
PIRATE_CFG = GAMES.get("pirate") or {}


def pirate_start():
    duration = int(PIRATE_CFG.get("durationSec") or 45)
    hp = min(40, 6 + 4 * recent_chatters())
    pid = f"p{time.time()}"
    state["pirate"] = {"id": pid, "status": "active", "hp": hp, "max": hp, "endsAt": int((time.time() + duration) * 1000),
                       "startedAt": int(time.time() * 1000), "hits": {}, "shots": [], "sinker": None}
    say(f"🏴‍☠️ DÜŞMAN GEMİSİ UFUKTA! !ateş yazıp top atın, {duration} saniyede batırın!")

    async def timer():
        await asyncio.sleep(duration)
        s = state["pirate"]
        if s and s["id"] == pid and s["status"] == "active":
            pirate_finish(False)
            await publish()
    _spawn(timer())


def pirate_fire(platform, name):
    s = state["pirate"]
    if not s or s["status"] != "active" or not cooldown(f"fire:{platform}:{name.casefold()}", 3):
        return
    hit = random.random() < float(PIRATE_CFG.get("hitChance") or 0.45)
    s["shots"] = (s["shots"] + [{"id": f"{time.time()}", "name": name, "platform": platform, "hit": hit}])[-8:]
    if not hit:
        return
    s["hp"] -= 1
    gunner = s["hits"].setdefault(f"{platform}:{name.casefold()}", {"platform": platform, "name": name, "hits": 0})
    gunner["hits"] += 1
    if s["hp"] <= 0:
        s["sinker"] = name
        pirate_finish(True)


def pirate_finish(sunk, retreat=False):
    s = state["pirate"]
    s["status"] = "sunk" if sunk else "escaped"
    if sunk:
        top = max(s["hits"].values(), key=lambda h: h["hits"])
        for h in s["hits"].values():
            add_loot(h["platform"], h["name"], min(30, 5 + 2 * h["hits"]) + (20 if h is top else 0) + (15 if h["name"] == s["sinker"] else 0))
        s["top"] = top["name"]
        auto_marker(f"🏴‍☠️ Korsan gemisi battı · son top {s['sinker']}")
        say(f"🏴‍☠️ KORSAN GEMİSİ BATTI! Son top: {s['sinker']} (+15) · en iyi topçu: {top['name']} ({top['hits']} isabet, +20) · "
            f"ateş eden {len(s['hits'])} kişiye ganimet!")
    else:
        say("🏴‍☠️ Korsanlar geri çekildi." if retreat else "🏴‍☠️ Korsan gemisi kaçtı… Toplar daha hızlı ateşlenmeli!")
    _clear_later("pirate", s["id"], 10)


def race_start():
    join = int(RACE_CFG.get("joinSec") or 45)
    rid = f"r{time.time()}"
    state["race"] = {"id": rid, "status": "join", "endsAt": int((time.time() + join) * 1000), "podium": [],
                     "boats": [{"key": "kaptan:kaptan", "platform": "kaptan", "name": "Kaptan", "pos": 0.0, "wind": 0}]}
    say(f"⛵ YELKEN YARIŞI! {join} saniye içinde !katıl yaz, gemin denize insin. Yarışta yazdığın her mesaj yelkenine rüzgâr!")

    async def run():
        await asyncio.sleep(join)
        r = state["race"]
        if not r or r["id"] != rid or r["status"] != "join":
            return
        if len(r["boats"]) < 2:
            race_end(cancelled=True, reason="⛵ Kimse katılmadı, yarış iptal.")
            await publish()
            return
        r["status"] = "race"
        say("⛵ Yarış başladı! Yazdıkça hızlan!")
        await publish()
        while r["status"] == "race" and state["race"] is r:
            await asyncio.sleep(1)
            for b in r["boats"]:
                if b["key"] in r["podium"]:
                    continue
                b["pos"] = min(100.0, b["pos"] + random.uniform(1.5, 3.5) + min(b["wind"], 3) * 2.5)
                b["wind"] = 0
                if b["pos"] >= 100:
                    r["podium"].append(b["key"])
            if len(r["podium"]) >= min(3, len(r["boats"])):
                race_end()
            await publish()
    _spawn(run())


def race_join(platform, name):
    r = state["race"]
    key = f"{platform}:{name.casefold()}"
    if r and r["status"] == "join" and len(r["boats"]) < int(RACE_CFG.get("maxBoats") or 8) \
            and all(b["key"] != key for b in r["boats"]):
        r["boats"].append({"key": key, "platform": platform, "name": name, "pos": 0.0, "wind": 0})


def race_boost(platform, name):
    r = state["race"]
    if r and r["status"] == "race":
        key = f"{platform}:{name.casefold()}"
        for b in r["boats"]:
            if b["key"] == key:
                b["wind"] += 1


def race_end(cancelled=False, reason=""):
    r = state["race"]
    if cancelled:
        r["status"] = "cancelled"
        say(reason or "⛵ Yarış iptal edildi.")
    else:
        r["status"] = "done"
        boats = {b["key"]: b for b in r["boats"]}
        medals = ["🥇", "🥈", "🥉"]
        for i, key in enumerate(r["podium"][:3]):
            add_loot(boats[key]["platform"], boats[key]["name"], [50, 25, 10][i])
        state["night"]["races"] += 1
        auto_marker(f"⛵ Yarış: 🥇 {boats[r['podium'][0]]['name']}")
        say("🏁 Yarış bitti! " + " · ".join(f"{medals[i]} {boats[k]['name']}" for i, k in enumerate(r["podium"][:3]))
            + " · ganimetler dağıtıldı!")
    _clear_later("race", r["id"], 12)



def on_raid(platform, data):
    """Big welcome for an incoming raid; a Kraken shows up shortly after so the raiders have something to do."""
    frm = data.get("from") if isinstance(data.get("from"), dict) else {}
    name = person(data) or clean(data.get("from_broadcaster_user_name") or data.get("fromBroadcasterUserName")
                                 or frm.get("name") or data.get("userName"), 32)
    login = clean((data.get("user") or {}).get("login") or data.get("from_broadcaster_user_login") or frm.get("login") or name, 32).lower()
    viewers = int(data.get("viewers") or data.get("viewerCount") or data.get("viewer_count") or 0)
    if not name:
        return
    state["raid"] = {"id": f"raid{time.time()}", "platform": platform, "name": name, "viewers": viewers}
    state["night"].setdefault("raids", []).append({"name": name, "viewers": viewers})
    auto_marker(f"🏴‍☠️ Baskın: {name} ({viewers})")
    say(f"🏴‍☠️ BASKIN! {name} {viewers} kişilik tayfasıyla güverteye çıktı! Hoş geldiniz korsanlar ⚓ !komutlar ile neler yapabileceğinizi görün.")

    async def follow_up():
        await asyncio.sleep(6)
        if platform == "twitch" and login:
            say(f"📣 {name} harika bir yayıncı, kanalına bir takip bırakın: twitch.tv/{login}")
        await asyncio.sleep(14)
        if viewers >= int(KRAKEN_CFG.get("raidMinViewers") or 3) and not event_busy():
            kraken_start()
        await publish()
    _spawn(follow_up())
    _clear_later("raid", state["raid"]["id"], 12)

# ------------------------------------------------------ League of Legends --
# Riot's Live Client Data API runs on this PC only while a game is loaded (no API key).
# It uses a self-signed certificate, so verification is off for this localhost call only.

LOL_CONFIG = CONFIG.get("lolAuto") or {}
LOL_URL = str(LOL_CONFIG.get("url") or "https://127.0.0.1:2999/liveclientdata/")
LOL_LOCK_AFTER = int(LOL_CONFIG.get("lockAfterSec") or 180)
# TFT reports through the same API but ends in a placement (1-8), not a win/loss.
LOL_SKIP_MODES = {"TFT", "PRACTICETOOL", "TUTORIAL", "TUTORIAL_MODULE_1", "TUTORIAL_MODULE_2", "TUTORIAL_MODULE_3"}
_lol_ssl = ssl.create_default_context()
_lol_ssl.check_hostname = False
_lol_ssl.verify_mode = ssl.CERT_NONE


def _lol_get(path):
    with urllib.request.urlopen(LOL_URL + path, timeout=1.5, context=_lol_ssl) as r:
        return json.loads(r.read().decode("utf-8"))


# The League client (not the game) has its own local API; its port and password are in the lockfile
# ("LeagueClient:pid:port:password:https") while the client is open. Used only to open the prediction
# at champion select, a few minutes before the game (and the Live Client Data API above) exists.
LCU_LOCKFILE = Path(LOL_CONFIG.get("lockfile") or "C:/Riot Games/League of Legends/lockfile")
LCU_SKIP_MODES = {"TFT", "PRACTICETOOL", "TUTORIAL"}


def _lcu_get(path):
    _, _, port, password, protocol = LCU_LOCKFILE.read_text(encoding="utf-8").strip().split(":")
    req = urllib.request.Request(f"{protocol}://127.0.0.1:{port}{path}", headers={
        "Authorization": "Basic " + base64.b64encode(f"riot:{password}".encode()).decode()})
    with urllib.request.urlopen(req, timeout=1.5, context=_lol_ssl) as r:
        return json.loads(r.read().decode("utf-8"))


async def lcu_watcher():
    """Champion select opens the match prediction; a dodge (back to lobby before the game) cancels it with refunds."""
    phase, opened = None, False
    while True:
        await asyncio.sleep(2)
        if not state["lolAuto"] or not LCU_LOCKFILE.exists():
            phase, opened = None, False
            continue
        try:
            now = await asyncio.to_thread(_lcu_get, "/lol-gameflow/v1/gameflow-phase")
        except Exception:
            continue  # client starting/closing, or the lockfile is stale
        if now == phase:
            continue
        before, phase = phase, now
        if now == "ChampSelect" and state["prediction"]["status"] in ("off", "done"):
            try:
                mode = str(((await asyncio.to_thread(_lcu_get, "/lol-gameflow/v1/session")).get("gameData") or {})
                           .get("queue", {}).get("gameMode") or "")
            except Exception:
                mode = ""
            if mode not in LCU_SKIP_MODES:
                predict_open()
                opened = True
                await publish()
        elif before == "ChampSelect" and now in ("None", "Lobby", "Matchmaking", "ReadyCheck") and opened:
            opened = False
            if state["prediction"]["status"] == "open":
                refund_stakes()
                state["prediction"]["status"] = "off"
                say("🔮 Şampiyon seçimi dağıldı, tahminler iade edildi. Sıradaki maçta tekrar açılır.")
                await publish()
        elif now in ("GameStart", "InProgress"):
            opened = False  # the game is on: lol_watcher locks the prediction at lockAfterSec as before


async def lol_watcher():
    game = None  # the game currently loaded in the client, or None
    while True:
        await asyncio.sleep(2)
        if not state["lolAuto"]:
            game = None
            if state["lolGame"]:
                state["lolGame"] = None
                await publish()
            continue
        try:
            stats = await asyncio.to_thread(_lol_get, "gamestats")
            if "gameTime" not in stats:
                raise ValueError("loading")
            events = (await asyncio.to_thread(_lol_get, "eventdata")).get("Events") or []
        except Exception:
            if game is not None or state["lolGame"]:
                game = None
                state["lolGame"] = None
                await publish()
            continue
        mode, gtime, changed = str(stats.get("gameMode") or ""), float(stats.get("gameTime") or 0), False
        if game is None:
            try:
                player = await asyncio.to_thread(_lol_get, "activeplayername")
            except Exception:
                player = ""
            if not player and gtime < 30:
                continue  # may just not be ready yet during load; decide once the game is clearly running
            # Spectator/replay has no active player; practice tool isn't a real match.
            game = {"skip": not player or mode in LOL_SKIP_MODES, "matchCount": len(state["matches"]),
                    "done": False, "locked": gtime >= LOL_LOCK_AFTER, "me": {_lol_name(player)} if player else set(),
                    "teams": {}, "team": None, "deaths": 0 if gtime < 30 else None,
                    "seen": max((int(e.get("EventID", -1)) for e in events), default=-1) if gtime >= 30 else -1}
            if not game["skip"] and gtime < LOL_LOCK_AFTER and state["prediction"]["status"] in ("off", "done"):
                predict_open()
            if not game["skip"]:
                await lol_scene("sohbet", game_scene())
            changed = True
        if not game["skip"] and not game["done"]:
            try:
                changed = lol_players(game, await asyncio.to_thread(_lol_get, "playerlist")) or changed
            except Exception:
                pass
            changed = lol_events(game, events) or changed
        if not game["skip"]:
            end = next((e for e in events if e.get("EventName") == "GameEnd"), None)
            if end and not game["done"]:
                game["done"] = True
                result = {"Win": "W", "Lose": "L"}.get(end.get("Result"))
                kda = game.get("kda") or {}
                print(f"LoL maç bitti: {end.get('Result')} · K/D/A {kda.get('kills', '?')}/{kda.get('deaths', '?')}/{kda.get('assists', '?')}"
                      f" · 💀 sayacı bu gece {state['deaths']}", flush=True)
                if result and len(state["matches"]) == game["matchCount"]:  # skip if entered by hand already
                    add_match(result)
                _spawn(lol_scene_later(game_scene(), chat_scene(), 12))  # a moment on the end screen first
                changed = True
            elif not game["locked"] and gtime >= LOL_LOCK_AFTER:
                game["locked"] = True
                changed = predict_lock() or changed
        info = {"mode": mode, "minute": int(gtime // 60), "done": game["done"], "skip": game["skip"]}
        if info != state["lolGame"]:
            state["lolGame"] = info
            changed = True
        if changed:
            await publish()



# LoL moments from the Live Client event feed: first blood, multikills, aces and objectives our team
# takes (or steals) become on-screen banners, clip markers and, for the big ones, a chat shout.
MULTIKILL = {2: "DOUBLE KILL", 3: "TRIPLE KILL", 4: "QUADRA KILL", 5: "PENTAKILL"}
OBJECTIVES = {"DragonKill": "EJDER", "BaronKill": "BARON", "HeraldKill": "HERALD"}


def _lol_name(name):
    return str(name or "").split("#")[0].strip().casefold()


def lol_moment(text, big=False, marker=False, shout=False):
    state["effects"] = (state["effects"] + [{"id": f"l{time.time()}{random.random()}", "type": "lol", "name": text, "big": big, "platform": ""}])[-10:]
    if marker:
        auto_marker(text)
    if shout and cooldown(f"lolshout:{text}", 20):
        say(f"{text} 🔥")


def lol_events(game, events):
    """Handle only events newer than the last one seen (a bridge restart mid-game doesn't replay old ones)."""
    new = [e for e in events if int(e.get("EventID", -1)) > game["seen"]]
    if not new:
        return False
    game["seen"] = max(int(e.get("EventID", -1)) for e in new)
    me, teams, team = game["me"], game["teams"], game.get("team")
    best_multi = max((int(e.get("KillStreak") or 0) for e in new
                      if e.get("EventName") == "Multikill" and _lol_name(e.get("KillerName")) in me), default=0)
    if best_multi in MULTIKILL:
        label = MULTIKILL[best_multi]
        lol_moment(f"⚔️ {label}!", big=best_multi >= 4, marker=best_multi >= 3, shout=best_multi >= 3)
    for e in new:
        kind = e.get("EventName")
        if kind == "FirstBlood" and _lol_name(e.get("Recipient")) in me:
            lol_moment("🩸 İLK KAN!")
        elif kind == "Ace" and team and e.get("AcingTeam") == team:
            lol_moment("💥 ACE!", marker=True)
        elif kind in OBJECTIVES and team and teams.get(_lol_name(e.get("KillerName"))) == team:
            what = "YAŞLI EJDER" if kind == "DragonKill" and e.get("DragonType") == "Elder" else OBJECTIVES[kind]
            if str(e.get("Stolen")).lower() == "true":
                lol_moment(f"🐉 {what} ÇALINDI!", big=True, marker=True, shout=True)
            elif kind == "BaronKill" or what == "YAŞLI EJDER":
                lol_moment(f"👑 {what} BİZİM!")
    return True


def lol_players(game, players):
    """Team map from the player list, and our deaths into the 💀 counter (no hotkey needed in LoL)."""
    mine = None
    for p in players or []:
        for key in ("riotId", "riotIdGameName", "summonerName"):
            if p.get(key):
                game["teams"][_lol_name(p[key])] = p.get("team")
        if any(_lol_name(p.get(k)) in game["me"] for k in ("riotId", "riotIdGameName", "summonerName")):
            mine = p
    if not mine:
        return False
    game["team"] = mine.get("team")
    game["kda"] = {k: int((mine.get("scores") or {}).get(k) or 0) for k in ("kills", "deaths", "assists")}
    deaths = int((mine.get("scores") or {}).get("deaths") or 0)
    if game["deaths"] is None:
        game["deaths"] = deaths  # joined mid-game: count only from here
    changed = deaths > game["deaths"]
    for _ in range(max(0, deaths - game["deaths"])):
        add_death(1)
    game["deaths"] = max(game["deaths"], deaths)
    return changed


def chat_scene():
    return next((n for n in CONFIG.get("obsScenes") or [] if "sohbet" in n.casefold()), None)


async def lol_scene(from_word, to):
    """Match start/end: switch scenes, but only away from the scene we expect (never off a break or start screen)."""
    current = (state.get("scene") or "").casefold()
    if state["lolScenes"] and to and from_word and from_word.casefold() in current and current != to.casefold():
        if await obs_set_scene(to):
            on_scene(to)


async def lol_scene_later(from_name, to, seconds):
    await asyncio.sleep(seconds)
    await lol_scene(from_name, to)
    await publish()


async def obs_health():
    """Every 3 s: live time, bitrate (last ~15 s), dropped frames (last ~60 s) and whether the mic is muted."""
    samples = []  # (time, bytes, skipped, total) while live
    rec_tried = False  # auto-record once per live session, so a manual stop mid-stream is respected
    while True:
        await asyncio.sleep(3)
        if not obs_conn.get("ws"):
            samples.clear()
            if state["health"]:
                state["health"] = None
                await publish()
            continue
        st = await obs_request("GetStreamStatus") or {}
        special = await obs_request("GetSpecialInputs") or {}
        mics = [name for key, name in special.items() if key.startswith("mic") and name]
        muted = []
        for mic in mics:
            reply = await obs_request("GetInputMute", {"inputName": mic})
            if reply is not None:
                muted.append(bool(reply.get("inputMuted")))
        live = bool(st.get("outputActive"))
        rec = bool((await obs_request("GetRecordStatus") or {}).get("outputActive"))
        if not live:
            rec_tried = False
        elif not rec and not rec_tried and CONFIG.get("autoRecord", True):
            rec_tried = True  # clips (make-clips.py) need the local recording
            if await obs_request("StartRecord") is not None:
                rec = True
                print("OBS kaydı başlatıldı (yayın açık, kayıt kapalıydı)")
        if live:
            samples.append((time.time(), st.get("outputBytes", 0), st.get("outputSkippedFrames", 0), st.get("outputTotalFrames", 0)))
            del samples[:-21]
        else:
            samples.clear()
        kbps = drop = None
        if len(samples) >= 2:
            a, b = samples[-min(6, len(samples))], samples[-1]
            kbps = round((b[1] - a[1]) * 8 / 1000 / max(0.1, b[0] - a[0]))
            first = samples[0]
            frames = b[3] - first[3]
            drop = round(100 * (b[2] - first[2]) / frames, 1) if frames > 0 else 0.0
        health = {"live": live, "time": str(st.get("outputTimecode") or "").split(".")[0] if live else "",
                  "kbps": kbps, "drop": drop, "congestion": round(st.get("outputCongestion") or 0, 2) if live else 0,
                  "micMuted": bool(muted) and all(muted), "mic": mics[0] if mics else "", "rec": rec}
        if health != state["health"]:
            state["health"] = health
            await publish()


# --------------------------------------------------------------- clients --

async def client(ws):
    CLIENTS.add(ws)
    # Anyone may watch the state (the OBS overlay pages do), but only this PC or a PIN holder may act.
    ip = (ws.remote_address or ("",))[0]
    authed = ip in TRUSTED_HOSTS
    try:
        await ws.send(json.dumps({"type": "auth", "ok": authed, "required": not authed, "length": len(PIN)}))
        await ws.send(json.dumps({"type": "state", "state": snapshot()}, ensure_ascii=False))
        async for raw in ws:
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "auth":
                    result = "ok" if authed else check_pin(ip, re.sub(r"\D", "", str(msg.get("pin") or ""))[:12])
                    authed = result == "ok"
                    await ws.send(json.dumps({"type": "auth", "ok": authed, "required": not authed, "error": None if authed else result, "length": len(PIN)}))
                    continue
                if not authed:
                    await ws.send(json.dumps({"type": "auth", "ok": False, "required": True, "error": "needed", "length": len(PIN)}))
                    continue
                if action == "setDetails":
                    state["game"] = clean(msg.get("game"), 80)
                    state["returnMessage"] = clean(msg.get("returnMessage"), 100)
                elif action == "setRoutes":
                    routes = msg.get("routes")
                    if not isinstance(routes, list):
                        continue
                    state["routes"] = [clean(x, 65) for x in routes[:3] if clean(x, 65)]
                    state["votes"] = {}
                    announce_routes()
                elif action == "announceRoutes":
                    announce_routes()
                    continue
                elif action == "fishCast":
                    if not cast_line("kaptan", "Kaptan"):
                        continue
                elif action == "krakenStart":
                    if event_busy():
                        await send_notice(ws, False, "Önce süren etkinlik bitsin")
                        continue
                    kraken_start()
                elif action == "krakenStop":
                    if not state["kraken"] or state["kraken"]["status"] != "active":
                        continue
                    kraken_finish(False, retreat=True)
                elif action == "guestSet":
                    guest = clean(msg.get("name"), 40)
                    if guest and guest != state["guest"]:
                        say(f"🎙️ Bu akşam güvertede bir misafir kaptanımız var: {guest}! Hoş geldin ⚓")
                    state["guest"] = guest or None
                elif action == "guessOpen":
                    guess_open(clean(msg.get("question"), 80))
                elif action == "guessLock":
                    if not state["guess"] or state["guess"]["status"] != "open":
                        continue
                    state["guess"]["status"] = "locked"
                    say(f"🔒 Sayı tahminleri kapandı · {len(state['guess']['votes'])} tahmin")
                elif action == "guessAnswer":
                    answer = msg.get("answer")
                    if not state["guess"] or state["guess"]["status"] == "done" or not isinstance(answer, int) or answer < 0:
                        continue
                    guess_answer(answer)
                elif action == "guessClear":
                    state["guess"] = None
                elif action == "cupStart":
                    if state["fishCup"] and state["fishCup"]["status"] == "active":
                        continue
                    cup_start()
                elif action == "cupStop":
                    if not state["fishCup"] or state["fishCup"]["status"] != "active":
                        continue
                    cup_finish(cancelled=bool(msg.get("cancel")))
                elif action == "tugStart":
                    if event_busy():
                        await send_notice(ws, False, "Önce süren etkinlik bitsin")
                        continue
                    tug_start()
                elif action == "tugStop":
                    if not state["tug"] or state["tug"]["status"] != "active":
                        continue
                    tug_finish(cancelled=True)
                elif action == "pirateStart":
                    if event_busy():
                        await send_notice(ws, False, "Önce süren etkinlik bitsin")
                        continue
                    pirate_start()
                elif action == "pirateStop":
                    if not state["pirate"] or state["pirate"]["status"] != "active":
                        continue
                    pirate_finish(False, retreat=True)
                elif action == "raceStart":
                    if event_busy():
                        await send_notice(ws, False, "Önce süren etkinlik bitsin")
                        continue
                    race_start()
                elif action == "raceStop":
                    if not state["race"] or state["race"]["status"] not in ("join", "race"):
                        continue
                    race_end(cancelled=True)
                elif action == "toggleSfx":
                    state["sfx"] = not state["sfx"]
                elif action == "wishRemove":
                    state["wishlist"] = [w for w in state["wishlist"] if w["name"] != msg.get("name")]
                elif action == "shoutout":
                    shoutout(str(msg.get("platform") or ""), str(msg.get("name") or "")[:40])
                elif action == "giveLoot":
                    platform = clean(msg.get("platform"), 12).lower()
                    name = clean(msg.get("name"), 32)
                    if platform not in ("twitch", "kick") or not name:
                        continue
                    amount = 10
                    add_loot(platform, name, amount)
                    say(f"🎁 Kaptan @{name} tayfasına {amount} ganimet hediye etti!", platform)
                    await send_notice(ws, True, f"🎁 {name} +{amount} ganimet")
                elif action == "setGoal":
                    target = max(0, min(999, int(msg.get("target") or 0)))
                    state["goal"] = {"target": target, "reached": False}
                    check_goal()
                elif action == "preflight":
                    await ws.send(json.dumps({"type": "preflight", "items": await preflight()}, ensure_ascii=False))
                    continue
                elif action == "rehearsal":
                    if _rehearsing[0] or event_busy():
                        await send_notice(ws, False, "Prova şu an başlatılamaz (süren etkinlik var)")
                        continue
                    _spawn(rehearsal())
                    await send_notice(ws, True, "🎬 Prova başladı · ~25 sn, sohbete bir şey yazılmaz")
                    continue
                elif action == "queueToggle":
                    state["playQueueOpen"] = not state["playQueueOpen"]
                    say("🎮 Birlikte oynama sırası açıldı! Sıraya girmek için !oyna OyunİçiAdın yaz" if state["playQueueOpen"]
                        else "🎮 Oynama sırası kapandı, sıradakiler bekliyor olmaya devam ediyor.")
                elif action == "queueNext":
                    if not state["playQueue"]:
                        continue
                    queue_call(state["playQueue"][0]["id"])
                elif action == "queueCall":
                    queue_call(msg.get("id"))
                elif action == "queueRemove":
                    state["playQueue"] = [x for x in state["playQueue"] if x["id"] != msg.get("id")]
                elif action == "queueClear":
                    state["playQueue"], state["playCalled"] = [], None
                elif action == "exportData":
                    await ws.send(json.dumps({"type": "export", "data": {"crew": crew_db, "nights": NIGHTS,
                                                                     "exported": datetime.now().isoformat(timespec="seconds")}}, ensure_ascii=False))
                    continue
                elif action == "importData":
                    ok = import_data(msg.get("data") or {})
                    await send_notice(ws, ok, f"📂 Yedek yüklendi · {len(crew_db)} tayfa, {len(NIGHTS)} yayın" if ok else "📂 Bu dosya bir kumanda yedeği değil")
                    if not ok:
                        continue
                elif action == "countdown":
                    minutes = max(0.0, min(60.0, float(msg.get("minutes") or 0)))
                    state["countdown"] = int((time.time() + minutes * 60) * 1000) if minutes else None
                    if minutes:
                        say(f"⏰ {round(minutes)} dakika sonra güvertedeyiz! Beklerken !olta atıp ısının 🎣")
                        _spawn(countdown_done(state["countdown"]))
                elif action == "toggleAlerts":
                    state["alerts"] = not state["alerts"]
                elif action == "toggleAutoClip":
                    state["autoClip"] = not state["autoClip"]
                elif action == "toggleCdAutoScene":
                    state["cdAutoScene"] = not state["cdAutoScene"]
                elif action == "toggleMarket":
                    state["market"] = not state["market"]
                elif action == "toggleKrakenRandom":
                    state["krakenRandom"] = not state["krakenRandom"]
                elif action == "toggleBotChat":
                    state["botChat"] = not state["botChat"]
                elif action == "spotlight":
                    match = next((x for x in state["chat"] if x["id"] == msg.get("id")), None)
                    state["spotlight"] = match
                elif action == "questionShow":
                    q = next((x for x in state["questions"] if x["id"] == msg.get("id")), None)
                    if not q:
                        continue
                    state["spotlight"] = {**q, "kind": "question"}
                elif action == "questionDone":
                    state["questions"] = [x for x in state["questions"] if x["id"] != msg.get("id")]
                    if state["spotlight"] and state["spotlight"].get("id") == msg.get("id"):
                        state["spotlight"] = None
                elif action == "clearSpotlight":
                    state["spotlight"] = None
                elif action == "addHighlight":
                    title = clean(msg.get("title"), 100)
                    if title:
                        state["highlights"] = (state["highlights"] + [title])[-5:]
                elif action == "removeHighlight":
                    index = int(msg.get("index", -1))
                    if 0 <= index < len(state["highlights"]):
                        state["highlights"].pop(index)
                elif action == "resetVotes":
                    state["votes"] = {}
                elif action == "toggleRoutesVisible":
                    state["routesVisible"] = not state["routesVisible"]
                elif action == "toggleSegmentVisible":
                    state["segmentVisible"] = not state["segmentVisible"]
                elif action == "addMarker":
                    note = clean(msg.get("note"), 80)
                    await mark(note)
                    # Optional: a Streamer.bot Action named "QedyClip" (e.g. Twitch "Create Clip") fires too.
                    result = await sb_do_action("QedyClip", {"note": note or "Anı"})
                    clip = sb_action_notice("QedyClip", result, "klip isteği Streamer.bot'a gitti")
                    await send_notice(ws, result == "ok", f"İşaretlendi ✓ · {clip}", "marker")
                elif action in ("musicPlay", "musicPause", "musicNext", "musicPrev", "musicApprove", "musicReject", "musicAdd"):
                    ok = await music_action(action, msg)
                    if not ok:
                        await send_notice(ws, False, "Şarkı bulunamadı ya da Spotify cevap vermedi · Spotify bir cihazda açık mı?"
                                          if action == "musicAdd" else "Spotify isteği olmadı · Spotify açık ve bir cihazda çalıyor mu?")
                    elif action == "musicAdd":
                        await send_notice(ws, True, "🎵 Sıraya eklendi")
                elif action == "death":
                    add_death(int(msg.get("delta") or 1))
                elif action == "deathReset":
                    state["deaths"] = 0
                elif action == "toggleDeathsVisible":
                    state["deathsVisible"] = not state["deathsVisible"]
                elif action == "streamInfo":
                    # Mid-show game switch: title/category on Twitch + Kick without resetting the show.
                    game = clean(msg.get("game"), 80) or state["game"]
                    title = clean(msg.get("title"), 140)
                    if not game or not title:
                        continue
                    state["game"], state["title"] = game, title
                    await publish()
                    result = await sb_do_action("QedyStreamInfo", {"title": title, "game": game})
                    await send_notice(ws, result == "ok", sb_action_notice("QedyStreamInfo", result, f"{game} · Twitch/Kick başlık ve kategori güncellendi ✓"))
                    continue
                elif action == "wheelSpin":
                    if (state.get("wheel") or {}).get("status") == "spinning":
                        continue
                    _spawn(wheel_spin())
                    continue
                elif action == "wheelClose":
                    state["wheel"] = None
                elif action == "wheelPlay":
                    game = state.get("wheelLast")
                    if not game:
                        continue
                    state["game"] = game
                    preset = (CONFIG.get("routePresets") or {}).get(game)
                    if preset:
                        state["routes"] = [clean(x, 65) for x in preset[:3]]
                    state["title"] = f"🎡 Kütüphane Çarkı: {game} · Kaptan Qedy"[:140]
                    say(f"🎮 Çarkın seçimi açılıyor: {game}! İlk izlenimler geliyor ⚓")
                    await publish()
                    if msg.get("updateInfo"):
                        result = await sb_do_action("QedyStreamInfo", {"title": state["title"], "game": game})
                        await send_notice(ws, result == "ok", sb_action_notice("QedyStreamInfo", result, f"{game} · başlık/kategori güncellendi ✓"))
                    continue
                elif action == "toggleMusicExplicit":
                    state["musicExplicit"] = not state["musicExplicit"]
                elif action == "toggleMusicAuto":
                    state["musicAuto"] = not state["musicAuto"]
                elif action == "toggleMusicOpen":
                    state["musicOpen"] = not state["musicOpen"]
                    say("🎵 Şarkı istekleri açıldı! !şarkı <şarkı adı> · kaptan onaylayınca sıraya girer" if state["musicOpen"] else "🎵 Şarkı istekleri kapandı.")
                elif action == "toggleMusicVisible":
                    state["musicVisible"] = not state["musicVisible"]
                elif action == "testNote":
                    text = clean(msg.get("text"), 200)
                    if text:
                        h = state.get("health") or {}
                        note = {"at": datetime.now().strftime("%d.%m %H:%M"), "vod": h.get("time") or "", "scene": state.get("scene") or "", "text": text}
                        state["testNotes"] = (state["testNotes"] + [note])[-50:]
                        try:
                            with (DATA_DIR / ".test-notes.md").open("a", encoding="utf-8") as f:
                                f.write(f"- {note['at']} · {note['vod'] or '—'} · {note['scene'] or '—'} · {text}" + chr(10))
                        except OSError:
                            pass
                elif action == "testNoteRemove":
                    index = int(msg.get("index", -1))
                    if 0 <= index < len(state["testNotes"]):
                        state["testNotes"].pop(index)
                elif action == "removeMarker":
                    index = int(msg.get("index", -1))
                    if 0 <= index < len(state["markers"]):
                        state["markers"].pop(index)
                elif action == "addMatch":
                    result = msg.get("result")
                    if result not in ("W", "L"):
                        continue
                    add_match(result)
                elif action == "undoMatch":
                    if not state["matches"]:
                        continue
                    p = state["prediction"]
                    if p["status"] == "done" and p["matchCount"] == len(state["matches"]):
                        unsettle_stakes()
                        p.update(status="locked", result=None)
                    history = state["predictionHistory"]
                    if history and history[-1]["matchCount"] == len(state["matches"]):
                        history.pop()
                    state["matches"] = state["matches"][:-1]
                elif action == "predictOpen":
                    predict_open()
                elif action == "predictLock":
                    if not predict_lock():
                        continue
                elif action == "toggleLolScenes":
                    state["lolScenes"] = not state["lolScenes"]
                elif action == "toggleLolAuto":
                    state["lolAuto"] = not state["lolAuto"]
                elif action == "predictClear":
                    refund_stakes()
                    state["prediction"]["status"] = "off"
                elif action == "resetMatches":
                    state["matches"] = []
                    state["predictionHistory"] = []
                elif action == "toggleScoreVisible":
                    state["scoreVisible"] = not state["scoreVisible"]
                elif action == "resetShow":
                    reset_show()
                elif action == "startShow":
                    game = clean(msg.get("game"), 80)
                    if not game:
                        continue
                    routes = msg.get("routes") if isinstance(msg.get("routes"), list) else []
                    reset_show()
                    state["game"] = game
                    state["title"] = clean(msg.get("title"), 140)
                    state["returnMessage"] = clean(msg.get("returnMessage"), 100) or state["returnMessage"]
                    state["routes"] = [clean(x, 65) for x in routes[:3] if clean(x, 65)]
                    await publish()
                    parts, ok = ["Yeni yayın hazır ✓"], True
                    if msg.get("updateInfo") and state["title"]:
                        # Streamer.bot Action "QedyStreamInfo" sets title/category on Twitch + Kick from %title% / %game%.
                        result = await sb_do_action("QedyStreamInfo", {"title": state["title"], "game": game})
                        parts.append(sb_action_notice("QedyStreamInfo", result, "başlık/kategori güncellendi ✓"))
                        ok = ok and result == "ok"
                    if msg.get("announce"):
                        content, mentions = live_message(game, clean(msg.get("note"), 200))
                        sent = await post_discord(content, mentions)
                        parts.append("Discord duyurusu gönderildi ✓" if sent else "Discord duyurusu gönderilemedi")
                        ok = ok and sent
                    await send_notice(ws, ok, " · ".join(parts))
                    continue
                elif action == "discordAnnounce":
                    text = clean(msg.get("text"), 500)
                    if text:
                        await notify_discord(ws, await post_discord(text), "Anons")
                    continue  # no state change to publish
                elif action == "discordGoLive":
                    content, mentions = live_message(state["game"])
                    await notify_discord(ws, await post_discord(content, mentions), "Canlı duyurusu")
                    continue
                elif action == "discordSummary":
                    await notify_discord(ws, await post_discord(summary_text(), {"parse": []}), "Yayın özeti")
                    continue
                elif action == "obsSetScene":
                    await obs_set_scene(clean(msg.get("scene"), 80))
                    continue
                elif action == "modAction":
                    platform = clean(msg.get("platform"), 12).lower()
                    name = clean(msg.get("name"), 32)
                    kind = msg.get("type")
                    if platform in ("twitch", "kick") and name and kind in ("timeout", "ban"):
                        action_name = ("ModTimeout" if kind == "timeout" else "ModBan") + platform.capitalize()
                        # An Action with no sub-actions still answers "ok", so check it actually does something.
                        listing = await sb_request({"request": "GetActions"}) or {}
                        found = next((a for a in listing.get("actions") or [] if a.get("name") == action_name), None)
                        if found and not found.get("subaction_count"):
                            result = "empty"
                        else:
                            result = await sb_do_action(action_name, {"platform": platform, "user": name,
                                                                      "duration": 600, "reason": "Kaptan Qedy kumandası"})
                        await send_notice(ws, result == "ok", sb_action_notice(action_name, result, f"{name} · {kind} gönderildi ✓"))
                    continue
                else:
                    continue
                await publish()
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
            except ConnectionClosed:
                raise
            except Exception as exc:  # one bad action must not drop the panel's connection
                print(f"Kumanda işlemi atlandı ({msg.get('action') if isinstance(msg, dict) else '?'}): {type(exc).__name__}: {exc}", flush=True)
                continue
    except ConnectionClosed:
        pass  # phones drop the socket abruptly when the screen locks; the page reconnects on its own
    finally:
        CLIENTS.discard(ws)


async def supervised(name, loop_fn):
    """Restart a background loop if it ever raises, so one failure can't stop the whole bridge."""
    while True:
        try:
            await loop_fn()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"{name} döngüsü hata verdi, 3 sn sonra yeniden başlıyor: {type(exc).__name__}: {exc}", flush=True)
            await asyncio.sleep(3)


async def main():
    start_static_server()
    start_hotkeys(asyncio.get_running_loop())
    backup_data("acilis")
    async with serve(client, "0.0.0.0", WS_PORT, max_size=2**22):  # room for a backup upload
        ip = lan_ip()
        print("Qedy Show Bridge hazır:", flush=True)
        print(f"  Bu bilgisayarda : http://127.0.0.1:{HTTP_PORT}/kumanda.html", flush=True)
        print(f"  Telefon/tablet  : http://{ip}:{HTTP_PORT}/kumanda.html  (aynı wifi'de olmalı)", flush=True)
        print(f"  Telefon PIN'i   : {PIN}   (show-config.local.json > pin ile değiştirilebilir)", flush=True)
        if not DISCORD_WEBHOOK:
            print("  Discord webhook ayarlı değil (show-config.json > discordWebhook)", flush=True)
        loops = {"Streamer.bot": streamer_bot, "OBS": obs_client, "LoL": lol_watcher, "LoL istemci": lcu_watcher, "Kraken": kraken_random,
                 "İpuçları": tips_loop, "Sağlık": obs_health, "Sessiz güverte": quiet_deck, "Spotify": spotify_loop, "SB günlüğü": sb_log_watch}
        await asyncio.gather(*(supervised(name, fn) for name, fn in loops.items()))


class _Tee:
    """Bridge output goes to the window and to .bridge.log (so a crash can be read after the window is gone)."""
    def __init__(self, stream, file):
        self.stream, self.file, self.fresh = stream, file, True

    def write(self, text):
        try:
            self.stream.write(text)
        except Exception:
            pass
        try:
            for part in text.splitlines(keepends=True):
                if self.fresh:
                    self.file.write(datetime.now().strftime("[%m-%d %H:%M:%S] "))
                self.file.write(part)
                self.fresh = part.endswith("\n")
            self.file.flush()
        except Exception:
            pass
        return len(text)

    def flush(self):
        for s in (self.stream, self.file):
            try:
                s.flush()
            except Exception:
                pass

    def __getattr__(self, name):
        return getattr(self.stream, name)


def start_log():
    import sys
    path = DATA_DIR / ".bridge.log"
    try:
        if path.exists() and path.stat().st_size > 5_000_000:
            path.replace(DATA_DIR / ".bridge.old.log")
        file = path.open("a", encoding="utf-8")
    except OSError:
        return
    sys.stdout, sys.stderr = _Tee(sys.stdout, file), _Tee(sys.stderr, file)
    print(f"--- köprü başladı {datetime.now():%Y-%m-%d %H:%M:%S} ---", flush=True)


if __name__ == "__main__":
    start_log()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except BaseException:
        import traceback
        print("KÖPRÜ ÇÖKTÜ:", flush=True)
        traceback.print_exc()
        raise
