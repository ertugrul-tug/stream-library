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
import urllib.request
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".show-state.json"
CREW_FILE = ROOT / ".crew.json"  # points/ranks that survive between streams
CONFIG_FILE = ROOT / "show-config.json"
SB_URL = "ws://127.0.0.1:8080/"
WS_PORT = 8765
HTTP_PORT = 8766
CLIENTS = set()

CONFIG = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
LOCAL_CONFIG_FILE = ROOT / "show-config.local.json"
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
    before = rank_for(entry["points"])
    now = time.time()
    if entry["show"] != show_id:
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
        name = os.path.basename(self.translate_path(self.path).rstrip("\\/")).lower()
        if name.startswith(".") or name.endswith((".local.json", ".py", ".pyc")):
            self.send_error(404)
            return None
        return super().send_head()

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
        "markers": [], "rankUp": None,
        "matches": [], "scoreVisible": True,
        "prediction": {"status": "off", "votes": {}, "result": None, "matchCount": 0},
        "predictionHistory": [],
        "lolAuto": True, "lolGame": None, "title": "", "botChat": True,
        "catches": [], "kraken": None, "race": None, "krakenRandom": True,
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
    result["prediction"] = {"status": p["status"], "w": w, "l": l, "result": p["result"]}
    result["summaryText"] = summary_text()
    result["crew"] = [{**c, "rank": crew_rank(c["platform"], c["name"])} for c in state["crew"]]
    viewers = [e for e in crew_db.values() if e["platform"] in ("twitch", "kick")]
    top = sorted(viewers, key=lambda e: e["points"], reverse=True)[:10]
    result["topLoot"] = [{"platform": e["platform"], "name": e["name"], "loot": e.get("loot", 0), "best": e.get("best")}
                         for e in sorted(crew_db.values(), key=lambda e: e.get("loot", 0), reverse=True)[:5] if e.get("loot")]
    result["topCrew"] = [{"platform": e["platform"], "name": e["name"], "points": e["points"],
                          "streams": e["streams"], "rank": rank_for(e["points"])} for e in top]
    result["schedule"] = CONFIG.get("schedule") or {}
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


def reset_show():
    keep = {k: state[k] for k in ("game", "title", "returnMessage", "routes", "connection", "obsConnection", "lolAuto", "lolGame", "botChat", "krakenRandom")}
    state.clear()
    state.update(defaults())  # new "started" = new show id, so everyone's first-message bonus is available again
    state.update(keep)


# ------------------------------------------------------------- chat bot --
# Streamer.bot Actions "QedySayTwitch" / "QedySayKick" post %message% to that platform's chat.
# They post from the broadcaster account, so the same text comes back as a ChatMessage event:
# _said remembers what we sent for a minute so those echoes aren't counted as chat.

SAY_ACTIONS = {"twitch": "QedySayTwitch", "kick": "QedySayKick"}
HELP_TEXT = ("⚓ Komutlar: !olta (balık tut) · !ganimet · !rota 1/2/3 · !tahmin G / M (açıkken) · !rütbe"
             " · Kraken çıkınca !saldır · yelken yarışında !katıl")
_said, _cmd_last, _say_warned, _bot_tasks = {}, {}, set(), set()


async def _say(platform, text):
    result = await sb_do_action(SAY_ACTIONS[platform], {"message": text})
    if result != "ok" and (platform, result) not in _say_warned:
        _say_warned.add((platform, result))
        print(f"Sohbet botu ({platform}): {result} · Streamer.bot'ta {SAY_ACTIONS[platform]} action'ına bak", flush=True)


def say(text, platform=None):
    if not state.get("botChat", True) or not text:
        return
    text = text[:450]
    _said[clean(text, 300)] = time.time()
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
    m = state["matches"]
    streak = next((i for i, x in enumerate(reversed(m)) if x != result), len(m))
    fire = f" · 🔥 {streak} galibiyet serisi!" if result == "W" and streak >= 2 else ""
    head = "✅ Galibiyet!" if result == "W" else "❌ Mağlubiyet."
    say(f"{head} Bu akşam {m.count('W')}G {m.count('L')}M{fire}{guessed}")


def predict_open():
    state["prediction"] = {"status": "open", "votes": {}, "result": None, "matchCount": 0}
    say("🔮 Maç tahmini açıldı! Sonucu bil: !tahmin G (galibiyet) · !tahmin M (mağlubiyet)")


def predict_lock():
    p = state["prediction"]
    if p["status"] != "open":
        return False
    p["status"] = "locked"
    w = sum(v == "W" for v in p["votes"].values())
    say(f"🔒 Tahminler kapandı · {w} kişi galibiyet, {len(p['votes']) - w} kişi mağlubiyet dedi.")
    return True


def live_message(game, note=""):
    lines = DISCORD_LIVE_MESSAGE.split("\n") if DISCORD_LIVE_MESSAGE else []
    extra = ([f"🎮 Bu akşam: {game}"] if game else []) + ([note] if note else [])
    content = "\n".join(lines[:1] + extra + lines[1:])
    if DISCORD_LIVE_ROLE:
        content += f"\n\n<@&{DISCORD_LIVE_ROLE}>"
    return content, {"parse": [], "roles": [DISCORD_LIVE_ROLE] if DISCORD_LIVE_ROLE else []}


async def publish():
    STATE_FILE.write_text(json.dumps({k: v for k, v in state.items() if k not in ("connection", "obsConnection", "lolGame", "kraken", "race")}, ensure_ascii=False, indent=2), encoding="utf-8")
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
    urllib.request.urlopen(req, timeout=6).close()


async def post_discord(text, allowed_mentions=None):
    if not DISCORD_WEBHOOK or not text:
        return False
    try:
        await asyncio.to_thread(_post_discord_sync, DISCORD_WEBHOOK, text, allowed_mentions)
        return True
    except Exception as exc:
        print(f"Discord webhook hatası: {type(exc).__name__} {getattr(exc, 'code', '')}", flush=True)
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
    events = {"Twitch": ["ChatMessage", "Follow", "Sub", "ReSub", "GiftSub", "Cheer"],
              "Kick": ["ChatMessage", "Follow", "Subscription", "Resubscription", "GiftSubscription", "KicksGifted"]}
    while True:
        try:
            async with connect(SB_URL, open_timeout=3, max_size=2**20) as ws:
                sb_conn["ws"] = ws
                state["connection"] = "connected"
                await publish()
                await ws.send(json.dumps({"request": "Subscribe", "id": "qedy-show-bridge", "events": events}))
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
                        if kind == "ChatMessage":
                            message = clean(data.get("text") or data.get("message"), 300)
                            if not name or not message or is_own_echo(message):
                                continue
                            _active[f"{platform}:{name.casefold()}"] = time.time()
                            race_boost(platform, name)
                            item = {"platform": platform, "name": name, "text": message, "parts": chat_parts(data, message),
                                    "id": f"{platform}-{datetime.now().timestamp()}"}
                            state["chat"] = (state["chat"] + [item])[-30:]
                            state["stats"][platform]["chat"] += 1
                            new_rank = award_chat(platform, name, state["started"])
                            if new_rank:
                                state["rankUp"] = {"platform": platform, "name": name, "rank": new_rank,
                                                   "at": int(time.time() * 1000)}
                                say(f"🎖️ {name} rütbe atladı: artık {new_rank}!", platform)
                            if not any(x["platform"] == platform and x["name"].casefold() == name.casefold() for x in state["crew"]):
                                state["crew"] = (state["crew"] + [{"platform": platform, "name": name}])[-24:]
                            match = re.fullmatch(r"!rota\s+([1-3])", message, re.IGNORECASE)
                            if match:
                                index = int(match.group(1)) - 1
                                if index < len(state["routes"]):
                                    state["votes"][platform + ":" + name.casefold()] = index
                            guess = re.fullmatch(r"!tahmin\s+(\S+)", message, re.IGNORECASE)
                            if guess and state["prediction"]["status"] == "open":
                                pick = PREDICT_WORDS.get(guess.group(1).casefold())
                                if pick:
                                    state["prediction"]["votes"][platform + ":" + name.casefold()] = pick
                            command = message.split()[0].casefold()
                            if command in ("!rütbe", "!rutbe", "!rank") and cooldown(f"rank:{platform}:{name.casefold()}", 20):
                                say(rank_text(platform, name), platform)
                            elif command in ("!olta", "!balık", "!balik"):
                                cast_line(platform, name)
                            elif command == "!ganimet" and cooldown(f"loot:{platform}:{name.casefold()}", 20):
                                say(loot_text(platform, name), platform)
                            elif command in ("!saldır", "!saldir", "!vur"):
                                kraken_hit(platform, name)
                            elif command in ("!katıl", "!katil"):
                                race_join(platform, name)
                            elif command in ("!komutlar", "!komut", "!help") and cooldown(f"help:{platform}", 30):
                                say(HELP_TEXT, platform)
                        elif kind == "Follow":
                            state["stats"][platform]["follow"] += 1
                        elif kind in ("Sub", "ReSub", "GiftSub", "Subscription", "Resubscription", "GiftSubscription"):
                            state["stats"][platform]["sub"] += 1
                        elif kind == "Cheer" and platform == "twitch":
                            state["stats"][platform]["bits"] += int(data.get("bits") or 0)
                        elif kind == "KicksGifted" and platform == "kick":
                            amount = data.get("kicks") or {}
                            state["stats"][platform]["kicks"] += int((amount.get("amount") if isinstance(amount, dict) else None) or data.get("amount") or 0)
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


async def obs_request(request_type, timeout=2):
    """Send an obs-websocket request and wait for its response data (None if OBS is away)."""
    ws = obs_conn.get("ws")
    if not ws:
        return None
    rid = f"qedy-{time.time()}"
    future = asyncio.get_running_loop().create_future()
    obs_pending[rid] = future
    try:
        await ws.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": rid}}))
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
                identify = {"rpcVersion": d.get("rpcVersion", 1), "eventSubscriptions": 0}
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
                async for raw in ws:
                    try:
                        d = json.loads(raw).get("d") or {}
                    except ValueError:
                        continue
                    future = obs_pending.get(d.get("requestId"))
                    if future and not future.done():
                        future.set_result(d.get("responseData") or {})
        except (OSError, TimeoutError, Exception) as exc:
            obs_conn["ws"] = None
            if state["obsConnection"] != "waiting":
                state["obsConnection"] = "waiting"
                await publish()
            print(f"OBS bekleniyor: {type(exc).__name__}", flush=True)
            await asyncio.sleep(3)


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
    if best and best["points"] > (entry.get("best") or {}).get("points", -1):
        entry["best"] = best
    CREW_FILE.write_text(json.dumps(crew_db, ensure_ascii=False), encoding="utf-8")
    return entry["loot"]


def loot_text(platform, name):
    entry = crew_db.get(f"{platform}:{name.casefold()}") or {}
    best = entry.get("best")
    tail = f" · en iyi: {best['emoji']} {best['name']} ({best['points']})" if best else " · henüz bir şey yakalamadın, !olta yaz"
    return f"@{name} 🎣 ganimet: {entry.get('loot', 0)}{tail}"


def cast_line(platform, name):
    if not cooldown(f"fish:{platform}:{name.casefold()}", 5 if platform == "kaptan" else FISH_COOLDOWN):
        return False
    item, emoji, points, _ = random.choices(LOOT, weights=[x[3] for x in LOOT])[0]
    rarity = "efsane" if points >= 40 else "nadir" if points >= 15 else "sıradan"
    total = add_loot(platform, name, points, {"name": item, "emoji": emoji, "points": points})
    state["catches"] = (state["catches"] + [{"id": f"f{time.time()}", "platform": platform, "name": name,
                                             "item": item, "emoji": emoji, "points": points, "rarity": rarity}])[-12:]
    if points >= 25:
        async def brag():
            await asyncio.sleep(4)  # after the overlay's reveal, not before
            say(f"🎣 {name} {emoji} {item} yakaladı! +{points} ganimet (toplam {total})")
        _spawn(brag())
    return True


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
        say(f"🐙 KRAKEN YENİLDİ! Son vuruş: {k['killer']} (+25 bonus) · saldıran {len(k['hits'])} kişiye ganimet dağıtıldı!")
    else:
        say("🐙 Kraken geri çekildi." if retreat else "🐙 Kraken kaçtı… Bir dahaki sefere daha sert vurun!")
    _clear_later("kraken", k["id"], 10)


async def kraken_random():
    """While the stream is live, a Kraken shows up every randomMin–randomMax minutes on its own."""
    low, high = int(KRAKEN_CFG.get("randomMinMinutes") or 25), int(KRAKEN_CFG.get("randomMaxMinutes") or 50)
    while True:
        await asyncio.sleep(random.uniform(low, high) * 60)
        status = await obs_request("GetStreamStatus")
        if state["krakenRandom"] and status and status.get("outputActive") and recent_chatters() \
                and not state["kraken"] and not state["race"]:
            kraken_start()
            await publish()


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
        say("🏁 Yarış bitti! " + " · ".join(f"{medals[i]} {boats[k]['name']}" for i, k in enumerate(r["podium"][:3]))
            + " · ganimetler dağıtıldı!")
    _clear_later("race", r["id"], 12)


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
                    "done": False, "locked": gtime >= LOL_LOCK_AFTER}
            if not game["skip"] and gtime < LOL_LOCK_AFTER and state["prediction"]["status"] in ("off", "done"):
                predict_open()
            changed = True
        if not game["skip"]:
            end = next((e for e in events if e.get("EventName") == "GameEnd"), None)
            if end and not game["done"]:
                game["done"] = True
                result = {"Win": "W", "Lose": "L"}.get(end.get("Result"))
                if result and len(state["matches"]) == game["matchCount"]:  # skip if entered by hand already
                    add_match(result)
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
                    if state["kraken"] or state["race"]:
                        await send_notice(ws, False, "Önce süren etkinlik bitsin")
                        continue
                    kraken_start()
                elif action == "krakenStop":
                    if not state["kraken"] or state["kraken"]["status"] != "active":
                        continue
                    kraken_finish(False, retreat=True)
                elif action == "raceStart":
                    if state["kraken"] or state["race"]:
                        await send_notice(ws, False, "Önce süren etkinlik bitsin")
                        continue
                    race_start()
                elif action == "raceStop":
                    if not state["race"] or state["race"]["status"] not in ("join", "race"):
                        continue
                    race_end(cancelled=True)
                elif action == "toggleKrakenRandom":
                    state["krakenRandom"] = not state["krakenRandom"]
                elif action == "toggleBotChat":
                    state["botChat"] = not state["botChat"]
                elif action == "spotlight":
                    match = next((x for x in state["chat"] if x["id"] == msg.get("id")), None)
                    state["spotlight"] = match
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
                    status = await obs_request("GetStreamStatus")
                    vod = str(status.get("outputTimecode") or "").split(".")[0] if status and status.get("outputActive") else None
                    state["markers"] = (state["markers"] + [{"time": datetime.now().strftime("%H:%M"), "vod": vod, "note": note}])[-50:]
                    # Optional: a Streamer.bot Action named "QedyClip" (e.g. Twitch "Create Clip") fires too.
                    result = await sb_do_action("QedyClip", {"note": note or "Anı"})
                    clip = sb_action_notice("QedyClip", result, "klip isteği Streamer.bot'a gitti")
                    await send_notice(ws, result == "ok", f"İşaretlendi ✓ · {clip}", "marker")
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
                elif action == "toggleLolAuto":
                    state["lolAuto"] = not state["lolAuto"]
                elif action == "predictClear":
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
        pass  # phones drop the socket abruptly when the screen locks; the page reconnects on its own
    finally:
        CLIENTS.discard(ws)


async def main():
    start_static_server()
    async with serve(client, "0.0.0.0", WS_PORT, max_size=2**18):
        ip = lan_ip()
        print("Qedy Show Bridge hazır:", flush=True)
        print(f"  Bu bilgisayarda : http://127.0.0.1:{HTTP_PORT}/kumanda.html", flush=True)
        print(f"  Telefon/tablet  : http://{ip}:{HTTP_PORT}/kumanda.html  (aynı wifi'de olmalı)", flush=True)
        print(f"  Telefon PIN'i   : {PIN}   (show-config.local.json > pin ile değiştirilebilir)", flush=True)
        if not DISCORD_WEBHOOK:
            print("  Discord webhook ayarlı değil (show-config.json > discordWebhook)", flush=True)
        await asyncio.gather(streamer_bot(), obs_client(), lol_watcher(), kraken_random())


if __name__ == "__main__":
    asyncio.run(main())
