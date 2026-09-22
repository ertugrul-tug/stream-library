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
import re
import socket
import threading
import urllib.request
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".show-state.json"
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
OBS_URL = str((CONFIG.get("obs") or {}).get("url") or "ws://127.0.0.1:4455")
OBS_PASSWORD = str((CONFIG.get("obs") or {}).get("password") or "")

sb_conn = {"ws": None}
obs_conn = {"ws": None}


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


def start_static_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def clean(value, limit=180):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or ""))[:limit].strip()


def defaults():
    return {
        "game": clean(CONFIG.get("game"), 80),
        "returnMessage": clean(CONFIG.get("returnMessage"), 100),
        "routes": [clean(x, 65) for x in CONFIG.get("routes", [])][:3],
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
    return result


async def publish():
    STATE_FILE.write_text(json.dumps({k: v for k, v in state.items() if k not in ("connection", "obsConnection")}, ensure_ascii=False, indent=2), encoding="utf-8")
    message = json.dumps({"type": "state", "state": snapshot()}, ensure_ascii=False)
    for ws in tuple(CLIENTS):
        try:
            await ws.send(message)
        except Exception:
            CLIENTS.discard(ws)


def person(data):
    user = data.get("user") or data.get("targetUser") or data.get("sender") or {}
    return clean(user.get("name") or user.get("login") or data.get("userName"), 32)


# ---------------------------------------------------------------- Discord --

def _post_discord_sync(url, content):
    req = urllib.request.Request(
        url,
        data=json.dumps({"content": content}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=6).close()


async def post_discord(text):
    if not DISCORD_WEBHOOK or not text:
        return False
    try:
        await asyncio.to_thread(_post_discord_sync, DISCORD_WEBHOOK, text)
        return True
    except Exception as exc:
        print(f"Discord webhook hatası: {type(exc).__name__}", flush=True)
        return False


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
                            item = {"platform": platform, "name": name, "text": message, "id": f"{platform}-{datetime.now().timestamp()}"}
                            state["chat"] = (state["chat"] + [item])[-30:]
                            state["stats"][platform]["chat"] += 1
                            if not any(x["platform"] == platform and x["name"].casefold() == name.casefold() for x in state["crew"]):
                                state["crew"] = (state["crew"] + [{"platform": platform, "name": name}])[-24:]
                            match = re.fullmatch(r"!rota\s+([1-3])", message, re.IGNORECASE)
                            if match:
                                index = int(match.group(1)) - 1
                                if index < len(state["routes"]):
                                    state["votes"][platform + ":" + name.casefold()] = index
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
                async for _raw in ws:
                    pass  # scene switching is fire-and-forget; no responses needed here
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
    await ws.send(json.dumps({"type": "state", "state": snapshot()}, ensure_ascii=False))
    try:
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
                elif action == "resetShow":
                    previous = {k: state[k] for k in ("game", "returnMessage", "routes", "connection", "obsConnection")}
                    state.clear()
                    state.update(defaults())
                    state.update(previous)
                elif action == "discordAnnounce":
                    text = clean(msg.get("text"), 500)
                    if text:
                        await post_discord(text)
                    continue  # no state change to publish
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
