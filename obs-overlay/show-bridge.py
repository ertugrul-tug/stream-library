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
static files (8766) on your home network. Anyone on the same wifi
could reach them and trigger these actions, including moderation.
No PIN gate yet — by choice, for now. Add one before relying on this
away from a trusted home network.
"""
import asyncio
import base64
import hashlib
import json
import os
import re
import socket
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
DISCORD_WEBHOOK = str(CONFIG.get("discordWebhook") or "").strip()
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
    top = sorted(crew_db.values(), key=lambda e: e["points"], reverse=True)[:10]
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


async def publish():
    STATE_FILE.write_text(json.dumps({k: v for k, v in state.items() if k not in ("connection", "obsConnection")}, ensure_ascii=False, indent=2), encoding="utf-8")
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
        await ws.send(json.dumps({"type": "notice", "ok": ok, "text": text}))
    except Exception:
        pass


# ---------------------------------------------------------- Streamer.bot --

async def sb_do_action(action_name, args):
    """Relay a named Action trigger to Streamer.bot. The Action itself (and
    whatever it does to Twitch/Kick) must already exist in Streamer.bot —
    this bridge never talks to Twitch/Kick directly."""
    ws = sb_conn.get("ws")
    if not ws:
        return False
    try:
        await ws.send(json.dumps({"request": "DoAction", "action": {"name": action_name}, "args": args}))
        return True
    except Exception:
        return False


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
                        event = payload.get("event") or {}
                        platform = clean(event.get("source"), 12).lower()
                        kind = event.get("type")
                        data = payload.get("data") or {}
                        if platform not in ("twitch", "kick") or not isinstance(data, dict):
                            continue
                        name = person(data)
                        if kind == "ChatMessage":
                            message = clean(data.get("text") or data.get("message"), 300)
                            if not name or not message:
                                continue
                            item = {"platform": platform, "name": name, "text": message, "parts": chat_parts(data, message),
                                    "id": f"{platform}-{datetime.now().timestamp()}"}
                            state["chat"] = (state["chat"] + [item])[-30:]
                            state["stats"][platform]["chat"] += 1
                            new_rank = award_chat(platform, name, state["started"])
                            if new_rank:
                                state["rankUp"] = {"platform": platform, "name": name, "rank": new_rank,
                                                   "at": int(time.time() * 1000)}
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


# --------------------------------------------------------------- clients --

async def client(ws):
    CLIENTS.add(ws)
    try:
        await ws.send(json.dumps({"type": "state", "state": snapshot()}, ensure_ascii=False))
        async for raw in ws:
            try:
                msg = json.loads(raw)
                action = msg.get("action")
                if action == "setDetails":
                    state["game"] = clean(msg.get("game"), 80)
                    state["returnMessage"] = clean(msg.get("returnMessage"), 100)
                elif action == "setRoutes":
                    routes = msg.get("routes")
                    if not isinstance(routes, list):
                        continue
                    state["routes"] = [clean(x, 65) for x in routes[:3] if clean(x, 65)]
                    state["votes"] = {}
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
                    await sb_do_action("QedyClip", {"note": note})
                elif action == "removeMarker":
                    index = int(msg.get("index", -1))
                    if 0 <= index < len(state["markers"]):
                        state["markers"].pop(index)
                elif action == "addMatch":
                    result = msg.get("result")
                    if result not in ("W", "L"):
                        continue
                    state["matches"] = (state["matches"] + [result])[-50:]
                    p = state["prediction"]
                    if p["status"] in ("open", "locked"):
                        p.update(status="done", result=result, matchCount=len(state["matches"]))
                        total = len(p["votes"])
                        if total:
                            right = sum(v == result for v in p["votes"].values())
                            state["predictionHistory"].append({"right": right, "total": total, "matchCount": len(state["matches"])})
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
                    state["prediction"] = {"status": "open", "votes": {}, "result": None, "matchCount": 0}
                elif action == "predictLock":
                    if state["prediction"]["status"] != "open":
                        continue
                    state["prediction"]["status"] = "locked"
                elif action == "predictClear":
                    state["prediction"]["status"] = "off"
                elif action == "resetMatches":
                    state["matches"] = []
                    state["predictionHistory"] = []
                elif action == "toggleScoreVisible":
                    state["scoreVisible"] = not state["scoreVisible"]
                elif action == "resetShow":
                    previous = {k: state[k] for k in ("game", "returnMessage", "routes", "connection", "obsConnection")}
                    state.clear()
                    state.update(defaults())
                    state.update(previous)
                elif action == "discordAnnounce":
                    text = clean(msg.get("text"), 500)
                    if text:
                        await notify_discord(ws, await post_discord(text), "Anons")
                    continue  # no state change to publish
                elif action == "discordGoLive":
                    content = DISCORD_LIVE_MESSAGE
                    if DISCORD_LIVE_ROLE:
                        content += f"\n\n<@&{DISCORD_LIVE_ROLE}>"
                    mentions = {"parse": [], "roles": [DISCORD_LIVE_ROLE] if DISCORD_LIVE_ROLE else []}
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
                        action_name = "ModTimeout" if kind == "timeout" else "ModBan"
                        await sb_do_action(action_name, {"platform": platform, "user": name})
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
        if not DISCORD_WEBHOOK:
            print("  Discord webhook ayarlı değil (show-config.json > discordWebhook)", flush=True)
        await asyncio.gather(streamer_bot(), obs_client())


if __name__ == "__main__":
    asyncio.run(main())
