"""Local show state for Kaptan Qedy OBS browser sources.

Run: python show-bridge.py  (requires websockets>=14,<17)
Streamer.bot stays on ws://127.0.0.1:8080/; this server uses 8765.
"""
import asyncio
import json
import re
from collections import deque
from datetime import datetime
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / ".show-state.json"
CONFIG_FILE = ROOT / "show-config.json"
SB_URL = "ws://127.0.0.1:8080/"
CLIENTS = set()


def clean(value, limit=180):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or ""))[:limit].strip()


def defaults():
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    return {
        "game": clean(cfg.get("game"), 80),
        "returnMessage": clean(cfg.get("returnMessage"), 100),
        "routes": [clean(x, 65) for x in cfg.get("routes", [])][:3],
        "crew": [], "chat": [], "spotlight": None, "highlights": [],
        "votes": {}, "stats": {"twitch": {"chat": 0, "follow": 0, "sub": 0, "bits": 0},
                             "kick": {"chat": 0, "follow": 0, "sub": 0, "kicks": 0}},
        "started": datetime.now().isoformat(timespec="seconds"),
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
    STATE_FILE.write_text(json.dumps({k: v for k, v in state.items() if k != "connection"}, ensure_ascii=False, indent=2), encoding="utf-8")
    message = json.dumps({"type": "state", "state": snapshot()}, ensure_ascii=False)
    for ws in tuple(CLIENTS):
        try:
            await ws.send(message)
        except Exception:
            CLIENTS.discard(ws)


def person(data):
    user = data.get("user") or data.get("targetUser") or data.get("sender") or {}
    return clean(user.get("name") or user.get("login") or data.get("userName"), 32)


async def streamer_bot():
    events = {"Twitch": ["ChatMessage", "Follow", "Sub", "ReSub", "GiftSub", "Cheer"],
              "Kick": ["ChatMessage", "Follow", "Subscription", "Resubscription", "GiftSubscription", "KicksGifted"]}
    while True:
        try:
            async with connect(SB_URL, open_timeout=3, max_size=2**20) as ws:
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
            if state["connection"] != "waiting":
                state["connection"] = "waiting"
                await publish()
            print(f"Streamer.bot bekleniyor: {type(exc).__name__}", flush=True)
            await asyncio.sleep(3)


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
                    previous = {k: state[k] for k in ("game", "returnMessage", "routes", "connection")}
                    state.clear()
                    state.update(defaults())
                    state.update(previous)
                else:
                    continue
                await publish()
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
    finally:
        CLIENTS.discard(ws)


async def main():
    async with serve(client, "127.0.0.1", 8765, max_size=2**18, origins=[None, "null"]):
        print("Qedy Show Bridge: ws://127.0.0.1:8765 (yalnızca bu bilgisayar)", flush=True)
        await streamer_bot()


if __name__ == "__main__":
    asyncio.run(main())
