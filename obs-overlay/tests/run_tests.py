"""End-to-end tests for show-bridge.py.

Starts the bridge on spare ports with a temporary data folder and fake
Streamer.bot, OBS, LoL client and Discord webhook, then drives it the way
the control panel and chat would. Nothing reaches real chat, Discord or
your saved show data.

Run:  python obs-overlay/tests/run_tests.py
"""
import asyncio
import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

import websockets
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

HERE = Path(__file__).resolve().parent
OVERLAY = HERE.parent
WS, HTTP, SB, OBS, LOL, HOOK = 18765, 18766, 18080, 14455, 12999, 19999
PIN = "4321"


# ------------------------------------------------------------------ fakes --

class FakeStreamerBot:
    def __init__(self):
        self.conns, self.said, self.calls = [], [], []
        self.actions = {n: 1 for n in ("QedySayTwitch", "QedySayKick", "QedyStreamInfo", "QedyClip",
                                       "ModTimeoutTwitch", "ModBanTwitch", "ModTimeoutKick", "ModBanKick")}

    async def handler(self, ws):
        self.conns.append(ws)
        try:
            await self._serve(ws)
        except ConnectionClosed:
            pass  # the bridge is stopped at the end of the run

    async def _serve(self, ws):
        async for raw in ws:
            m = json.loads(raw)
            req = m.get("request")
            if req == "DoAction":
                name = m["action"]["name"]
                self.calls.append((name, m.get("args") or {}))
                if name.startswith("QedySay"):
                    self.said.append((name[7:].lower(), m["args"].get("message", "")))
                ok = name in self.actions
                await ws.send(json.dumps({"id": m["id"], "status": "ok"} if ok else
                                         {"id": m["id"], "status": "error", "error": f"The action '{name}' was not found"}))
            elif req == "GetActions":
                await ws.send(json.dumps({"id": m["id"], "status": "ok",
                                          "actions": [{"name": n, "enabled": True, "subaction_count": c} for n, c in self.actions.items()]}))
            elif req == "GetBroadcaster":
                await ws.send(json.dumps({"id": m["id"], "status": "ok", "platforms": {"twitch": {"broadcastUser": "KaptanQedy"}}}))
            elif m.get("id"):
                await ws.send(json.dumps({"id": m["id"], "status": "ok"}))

    async def chat(self, platform, name, text):
        await self.conns[-1].send(json.dumps({"event": {"source": platform.capitalize(), "type": "ChatMessage"},
                                              "data": {"user": {"name": name}, "text": text}}))

    async def event(self, platform, kind, data):
        await self.conns[-1].send(json.dumps({"event": {"source": platform.capitalize(), "type": kind}, "data": data}))

    def said_since(self, n):
        return [t for _, t in self.said[n:]]


class FakeOBS:
    def __init__(self):
        self.scene, self.live, self.muted, self.ws = "Sahne", False, False, None
        self.bytes = self.frames = 0

    async def handler(self, ws):
        await ws.send(json.dumps({"op": 0, "d": {"rpcVersion": 1}}))
        await ws.recv()
        await ws.send(json.dumps({"op": 2, "d": {"negotiatedRpcVersion": 1}}))
        self.ws = ws
        try:
            await self._serve(ws)
        except ConnectionClosed:
            pass

    async def _serve(self, ws):
        async for raw in ws:
            d = json.loads(raw)["d"]
            t = d["requestType"]
            if t == "GetStreamStatus":
                if self.live:
                    self.bytes += 2_000_000
                    self.frames += 180
                data = {"outputActive": self.live, "outputTimecode": "00:10:00.000", "outputBytes": self.bytes,
                        "outputTotalFrames": self.frames, "outputSkippedFrames": 0, "outputCongestion": 0}
            elif t == "GetSpecialInputs":
                data = {"mic1": "Mic/Aux"}
            elif t == "GetInputMute":
                data = {"inputMuted": self.muted}
            elif t == "GetCurrentProgramScene":
                data = {"currentProgramSceneName": self.scene}
            elif t == "SetCurrentProgramScene":
                await self._serve_hook(t, d)
                data = {}
            else:
                data = {}
            await ws.send(json.dumps({"op": 7, "d": {"requestType": t, "requestId": d["requestId"],
                                                     "requestStatus": {"result": True, "code": 100}, "responseData": data}}))

    async def _serve_hook(self, t, d):
        if t == "SetCurrentProgramScene":
            await self.set_scene(d.get("requestData", {}).get("sceneName"))

    async def set_scene(self, name):
        self.scene = name
        await self.ws.send(json.dumps({"op": 5, "d": {"eventType": "CurrentProgramSceneChanged", "eventData": {"sceneName": name}}}))


def serve_http(port, handler_cls):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


LOL_STATE = {"up": False, "time": 5.0, "end": None, "mode": "CLASSIC"}
HOOK_POSTS = []


class LolHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not LOL_STATE["up"]:
            return self._send(404, {"errorCode": "RESOURCE_NOT_FOUND"})
        path = self.path.rsplit("/", 1)[-1]
        if path == "gamestats":
            return self._send(200, {"gameMode": LOL_STATE["mode"], "gameTime": LOL_STATE["time"]})
        if path == "activeplayername":
            return self._send(200, "Qedy#TR1")
        events = [{"EventName": "GameStart"}] + ([{"EventName": "GameEnd", "Result": LOL_STATE["end"]}] if LOL_STATE["end"] else [])
        return self._send(200, {"Events": events})


class HookHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        HOOK_POSTS.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()


# ---------------------------------------------------------------- harness --

class Panel:
    """A control-panel connection to the bridge."""

    def __init__(self, ws):
        self.ws, self.state, self.notices, self.auth = ws, {}, [], []

    async def drain(self, seconds=0.6):
        try:
            while True:
                m = json.loads(await asyncio.wait_for(self.ws.recv(), seconds))
                if m["type"] == "state":
                    self.state = m["state"]
                elif m["type"] == "notice":
                    self.notices.append(m["text"])
                elif m["type"] == "auth":
                    self.auth.append(m)
        except asyncio.TimeoutError:
            pass

    async def act(self, action, wait=0.6, **fields):
        await self.ws.send(json.dumps({"action": action, **fields}))
        await self.drain(wait)
        return self.state


async def wait_until(check, timeout, step=0.3):
    end = time.time() + timeout
    while time.time() < end:
        if await check():
            return True
        await asyncio.sleep(step)
    return False


RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  {'✓' if ok else '✗'} {name}" + (f"  — {detail}" if detail and not ok else ""), flush=True)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


async def run(sb, obs, tmp):
    async with websockets.connect(f"ws://127.0.0.1:{WS}/") as ws:
        p = Panel(ws)
        await p.drain(1.5)
        state = lambda: p.state

        print("\nGüvenlik")
        check("bu bilgisayar PIN'siz yetkili", p.auth and p.auth[0]["ok"])
        codes = {}
        for name in ("kumanda.html", "show-config.local.json", ".show-state.json", "show-bridge.py", "backups/", "tests/run_tests.py"):
            try:
                codes[name] = urllib.request.urlopen(f"http://127.0.0.1:{HTTP}/{name}").status
            except urllib.error.HTTPError as e:
                codes[name] = e.code
        check("dosya sunucusu gizlileri vermiyor", codes == {"kumanda.html": 200, "show-config.local.json": 404, ".show-state.json": 404,
                                                            "show-bridge.py": 404, "backups/": 404, "tests/run_tests.py": 404}, str(codes))
        ip = lan_ip()
        if ip and ip != "127.0.0.1":
            async with websockets.connect(f"ws://{ip}:{WS}/") as lan:
                phone = Panel(lan)
                await phone.drain(1)
                await phone.act("predictOpen")
                await phone.act("auth", pin="0000")
                await phone.act("auth", pin=PIN)
                errors = [a.get("error") for a in phone.auth]
                check("telefon: PIN'siz işlem ve yanlış PIN reddedilir, doğru PIN kabul", errors[1:] == ["needed", "wrong", None], str(errors))

        print("\nYeni yayın · Streamer.bot · Discord")
        await p.act("startShow", wait=1.5, game="Minecraft", title="🔴 Test başlığı", updateInfo=True,
                    routes=["Madene inelim", "Üssü büyütelim", ""], note="Test notu", announce=True)
        check("yayın sıfırlandı, oyun/rotalar ayarlandı", state()["game"] == "Minecraft" and state()["routes"] == ["Madene inelim", "Üssü büyütelim"])
        info = [a for n, a in sb.calls if n == "QedyStreamInfo"]
        check("başlık/kategori Streamer.bot'a gitti", info and info[-1] == {"title": "🔴 Test başlığı", "game": "Minecraft"}, str(info[-1:]))
        live_post = HOOK_POSTS[-1]["content"] if HOOK_POSTS else ""
        check("Discord canlı duyurusu oyun ve notla gitti", "Bu akşam: Minecraft" in live_post and "Test notu" in live_post, live_post[:80])

        print("\nSohbet botu")
        n = len(sb.said)
        await sb.chat("kick", "Veli", "selam millet")
        await p.drain()
        check("ilk kez yazan ekranda işaretlenecek listede", "kick:veli" in state()["firstTimers"], str(state()["firstTimers"]))
        check("yeni izleyici karşılandı", any("Güverteye hoş geldin @Veli" in t for t in sb.said_since(n)), str(sb.said_since(n)))
        chat_before = state()["stats"]["kick"]["chat"]
        await sb.chat("kick", "KaptanQedy", sb.said[-1][1])
        await p.drain()
        check("botun kendi mesajı sayılmadı", state()["stats"]["kick"]["chat"] == chat_before)
        n = len(sb.said)
        await sb.chat("twitch", "Ali", "!rütbe")
        await p.drain()
        replies = [(pl, t) for pl, t in sb.said[n:] if "@Ali" in t]
        check("!rütbe sadece sorulan platformda cevaplandı", replies and all(pl == "twitch" for pl, _ in replies), str(replies))

        n = len(sb.said)
        await sb.chat("kick", "Veli", "!site")
        await sb.chat("kick", "Veli", "!discord")
        await p.drain()
        check("link komutu cevaplandı, boş link sessiz", sb.said_since(n) == [t for t in sb.said_since(n) if "stream-library" in t] and len(sb.said_since(n)) == 1, str(sb.said_since(n)))

        print("\nTahmin ve maç")
        await p.act("predictOpen")
        await sb.chat("twitch", "Ali", "!tahmin G")
        await sb.chat("kick", "Veli", "!tahmin m")
        await p.drain()
        check("tahmin oyları sayıldı", (state()["prediction"]["w"], state()["prediction"]["l"]) == (1, 1))
        n = len(sb.said)
        await p.act("predictLock")
        await p.act("addMatch", result="W")
        check("maç sonucu ve isabet duyuruldu", any("Galibiyet" in t and "%50'si" in t for t in sb.said_since(n)), str(sb.said_since(n)))

        print("\nOlta · market · soru")
        catches = len(state()["catches"])
        await sb.chat("twitch", "Ali", "!olta")
        await sb.chat("twitch", "Ali", "!olta")
        await p.drain()
        check("olta: ikinci atış bekleme süresine takıldı", len(state()["catches"]) == catches + 1)
        check("olta: ilk yakalama YENİ işaretli", state()["catches"][-1].get("new") is True)
        n = len(sb.said)
        await sb.chat("twitch", "Ali", "!koleksiyon")
        await p.drain()
        check("!koleksiyon 1/9 gösterdi", any("koleksiyon 1/9" in t for t in sb.said_since(n)), str(sb.said_since(n)))
        n = len(sb.said)
        loot_before = next((c["loot"] for c in state()["topLoot"] if c["name"] == "Ali"), 0)
        await p.act("giveLoot", platform="twitch", name="Ali")
        loot_after = next((c["loot"] for c in state()["topLoot"] if c["name"] == "Ali"), 0)
        check("kaptandan 🎁 10 ganimet", loot_after == loot_before + 10 and any("hediye etti" in t for t in sb.said_since(n)), f"{loot_before}->{loot_after}")
        await sb.chat("twitch", "Zengin", "!konfeti")
        await p.drain()
        check("market: yeterli ganimetle efekt oynadı", any(e["type"] == "konfeti" and e["name"] == "Zengin" for e in state()["effects"]))
        n = len(sb.said)
        await sb.chat("kick", "Veli", "!top")
        await p.drain()
        check("market: yetersiz bakiye bildirildi", any("ganimet lazım" in t for t in sb.said_since(n)), str(sb.said_since(n)))
        await p.act("giveLoot", platform="twitch", name="Zengin")
        n = len(sb.said)
        await sb.chat("twitch", "Zengin", "!düello @Ali 5")
        await p.drain()
        offer = any("düello teklif etti" in t for t in sb.said_since(n))
        await sb.chat("twitch", "Ali", "!kabul")
        await p.drain()
        result = [t for t in sb.said_since(n) if "kılıç çekti" in t]
        check("düello: teklif, kabul ve sonuç", offer and result and any(e["type"] == "duel" for e in state()["effects"]), str(sb.said_since(n)))
        n = len(sb.said)
        await sb.chat("kick", "Veli", "!düello @Zengin 100")
        await p.drain()
        check("düello: bakiye yetmeyen teklif edemedi", any("bakiyen yetmiyor" in t for t in sb.said_since(n)), str(sb.said_since(n)))
        n = len(sb.said)
        await sb.chat("kick", "Veli", "!kehanet bu akşam kazanır mıyız?")
        await sb.chat("kick", "Veli", "!kehanet tekrar soruyorum hemen")
        await p.drain()
        answers = [t for t in sb.said_since(n) if "🔮" in t]
        check("!kehanet cevap verdi, hemen tekrar bekleme süresine takıldı", len(answers) == 1 and answers[0].startswith("@Veli"), str(answers))
        n = len(sb.said)
        await sb.chat("twitch", "Ali", "!sezon")
        await p.drain()
        season = state().get("season") or {}
        check("sezon: sıralama ve !sezon cevabı", season.get("top") and any("sezonu:" in t and "@Ali bu ay" in t for t in sb.said_since(n)),
              f"{season} {sb.said_since(n)}")
        await sb.event("twitch", "RewardRedemption", {"user": {"name": "Puancı"}, "reward": {"title": "🎉 Konfeti"}})
        await sb.event("twitch", "RewardRedemption", {"user": {"name": "Puancı"}, "rewardName": "🎣 Olta"})
        await sb.event("twitch", "RewardRedemption", {"user": {"name": "Puancı"}, "rewardName": "🎣 Olta"})
        await sb.event("twitch", "RewardRedemption", {"user": {"name": "Puancı"}, "reward": {"title": "Bilinmeyen ödül"}})
        await p.drain()
        fx = [e for e in state()["effects"] if e["name"] == "Puancı"]
        casts = [c for c in state()["catches"] if c["name"] == "Puancı"]
        check("kanal puanı: konfeti efekti, olta bekleme süresiz (2 atış), bilinmeyen ödül yok sayıldı",
              [e["type"] for e in fx] == ["konfeti"] and len(casts) == 2, f"{fx} {len(casts)}")
        await sb.chat("twitch", "Ali", "!soru Bu akşam hangi dünyada oynuyoruz?")
        await p.drain()
        q = state()["questions"][-1] if state()["questions"] else {}
        await p.act("questionShow", id=q.get("id"))
        shown = (state()["spotlight"] or {}).get("kind") == "question"
        await p.act("questionDone", id=q.get("id"))
        check("soru kuyruğu: göster ve cevaplandı", shown and not state()["questions"] and state()["spotlight"] is None)

        print("\nBirlikte oyna sırası")
        n = len(sb.said)
        await sb.chat("twitch", "Ali", "!oyna")
        await p.drain()
        check("sıra kapalıyken !oyna reddedildi", not state()["playQueue"] and any("kapalı" in t for t in sb.said_since(n)))
        await p.act("queueToggle")
        await sb.chat("twitch", "Ali", "!oyna AliTR#123")
        await sb.chat("kick", "Veli", "!oyna")
        await sb.chat("twitch", "Ali", "!oyna")
        await p.drain()
        q = state()["playQueue"]
        check("sıraya iki kişi girdi, tekrar yazan çiftlenmedi", [x["name"] for x in q] == ["Ali", "Veli"] and q[0]["ign"] == "AliTR#123", str(q))
        n = len(sb.said)
        await p.act("queueNext")
        check("sıradaki çağrıldı ve bot duyurdu", [x["name"] for x in state()["playQueue"]] == ["Veli"]
              and any("@Ali sıra sende" in t and "AliTR#123" in t for t in sb.said_since(n)), str(sb.said_since(n)))
        await sb.chat("kick", "Veli", "!çık")
        await p.drain()
        await p.act("queueToggle")
        check("!çık ile sıradan çıkıldı, sıra kapandı", not state()["playQueue"] and not state()["playQueueOpen"])

        print("\nKraken · yarış · baskın")
        await p.act("krakenStart")
        hp = state()["kraken"]["max"]

        async def kraken_done():
            await sb.chat("twitch", "Ali", "!saldır")
            await sb.chat("kick", "Veli", "!vur")
            await p.drain(1.6)
            return state()["kraken"]["status"] != "active"
        await wait_until(kraken_done, 60)
        check(f"Kraken ({hp} can) yenildi", state()["kraken"]["status"] == "won", state()["kraken"]["status"])
        await p.act("raceStart")
        check("Kraken ekrandayken yarış engellendi", p.notices and "etkinlik" in p.notices[-1])
        await asyncio.sleep(10.5)
        await p.drain()
        await p.act("raceStart")
        await sb.chat("twitch", "Ali", "!katıl")
        await sb.chat("kick", "Veli", "!katil")
        await p.drain()

        async def race_done():
            await sb.chat("twitch", "Ali", "rüzgar!")
            await p.drain(1)
            return state()["race"] and state()["race"]["status"] == "done"
        await wait_until(race_done, 60)
        race = state()["race"] or {}
        check("yarış bitti, kürsü oluştu", race.get("status") == "done" and len(race.get("podium", [])) == 3, str(race.get("status")))
        await p.act("setGoal", target=2)
        n = len(sb.said)
        await sb.event("twitch", "Follow", {"user": {"name": "Takipci1"}})
        await sb.event("kick", "Follow", {"user": {"name": "Takipci2"}})
        await p.drain()
        await sb.event("twitch", "Sub", {"user": {"name": "Abone1"}})
        await asyncio.sleep(8.5)
        await p.drain()
        said = sb.said_since(n)
        check("destekçilere teşekkür: takip toplu, abone ayrı", any("Güverteye hoş geldin Takipci1" in t for t in said)
              and any("Güverteye hoş geldin Takipci2" in t for t in said) and any("Abone1 abone oldu" in t and "+50" in t for t in said), str(said))
        check("takip hedefi tuttu: ekran efekti ve bot", state()["goal"]["reached"] and any(e["type"] == "goal" for e in state()["effects"])
              and any("hedefimize ulaştık" in t for t in sb.said_since(n)))
        n = len(sb.said)
        await sb.event("twitch", "AdRun", {"length": 90})
        await sb.event("twitch", "HypeTrainStart", {"level": 1})
        await sb.event("twitch", "HypeTrainLevelUp", {"level": 2})
        await p.drain()
        ad_left = ((state()["adUntil"] or 0) / 1000) - time.time()
        said = sb.said_since(n)
        check("reklam arası duyuruldu ve süre kumandada", 80 < ad_left <= 90 and any("reklam arası" in t for t in said), f"{ad_left:.0f}")
        check("Hype Train kalktı, seviye 2 duyuruldu", (state()["hype"] or {}).get("level") == 2 and any("HYPE TRAIN KALKTI" in t for t in said)
              and any("seviye 2" in t for t in said), str(said))
        await sb.event("twitch", "HypeTrainEnd", {"level": 2})
        await p.drain()
        check("Hype Train bitti, teşekkür edildi", (state()["hype"] or {}).get("status") == "ended")
        n = len(sb.said)
        await sb.event("twitch", "Raid", {"user": {"name": "KorsanBey", "login": "korsanbey"}, "viewers": 7})
        await p.drain()
        check("baskın karşılandı", (state()["raid"] or {}).get("name") == "KorsanBey" and any("BASKIN" in t for t in sb.said_since(n)))

        print("\nOBS · LoL")
        n = len(sb.said)
        await obs.set_scene("Kısa Mola")
        await p.drain(1)
        check("molaya geçince bot duyurdu", state()["scene"] == "Kısa Mola" and any("Kısa mola" in t for t in sb.said_since(n)))
        await sb.chat("twitch", "Ali", "molada sohbet")
        await sb.chat("kick", "Veli", "ben de buradayım")
        await p.drain()
        n = len(sb.said)
        await obs.set_scene("Sahne")
        await p.drain(1)
        back = [t for t in sb.said_since(n) if "döndük" in t]
        check("moladan dönüşte mola özeti söylendi", back and "2 mesaj" in back[0], str(back))
        obs.live, obs.muted = True, True

        async def muted_seen():
            await p.drain(0.5)
            h = state().get("health") or {}
            return h.get("live") and h.get("micMuted")
        check("yayındayken mikrofon kapalı uyarısı", await wait_until(muted_seen, 10))
        clips_before = len([c for c in sb.calls if c[0] == "QedyClip"])
        await p.act("toggleAutoClip")
        for _ in range(3):
            await p.act("addMatch", result="W")
        await asyncio.sleep(1)
        await p.drain()
        auto = [m for m in state()["markers"] if m.get("auto")]
        clips = [c for c in sb.calls if c[0] == "QedyClip"][clips_before:]
        check("otomatik klip açıkken büyük an kliplendi", len(clips) == 1 and "galibiyet serisi" in clips[0][1].get("note", ""), str(clips))
        n = len(sb.said)
        await sb.chat("kick", "Veli", "!klip")
        await sb.chat("twitch", "Ali", "!klip")
        await p.drain()
        chat_clips = [c for c in sb.calls if c[0] == "QedyClip"][clips_before + 1:]
        check("!klip yayında çalıştı, 90 sn içinde ikincisi engellendi", len(chat_clips) == 1 and any("klipledi" in t for t in sb.said_since(n)), str(chat_clips))
        n = len(sb.said)
        await sb.chat("twitch", "Ali", "!skor")
        await sb.chat("kick", "Veli", "!süre")
        await p.drain()
        said = sb.said_since(n)
        n2 = len(sb.said)
        await sb.chat("twitch", "Ali", "!lurk")
        await sb.chat("twitch", "Ali", "!lurk")
        await sb.chat("kick", "Veli", "!hedef")
        await p.drain()
        said2 = sb.said_since(n2)
        n4 = len(sb.said)
        await sb.chat("twitch", "Ali", "!öner")
        await p.drain()
        check("!öner kütüphaneden oyun önerdi", any("oyunluk kütüphanesinden rastgele" in t for t in sb.said_since(n4)), str(sb.said_since(n4)))
        check("!lurk bir kez cevaplandı, !hedef çalıştı", sum("ambara indi" in t for t in said2) == 1 and any("🎯" in t for t in said2), str(said2))
        n3 = len(sb.said)
        await p.act("shoutout", platform="kick", name="Veli")
        await p.act("shoutout", platform="kick", name="Veli")
        shouts = [t for t in sb.said_since(n3) if "kick.com/veli" in t]
        check("kumandadan tanıtım iki sohbete bir kez gitti", len(shouts) == 2, str(sb.said_since(n3)))
        check("!skor ve !süre cevaplandı", any("G · " in t and "galibiyet serisi" in t for t in said) and any("güvertedeyiz" in t for t in said), str(said))
        await p.act("toggleAutoClip")
        check("yayındayken galibiyet serisi otomatik işaretlendi", any("galibiyet serisi" in m["note"] and m["vod"] for m in auto), str(auto))
        obs.live = obs.muted = False
        await p.act("predictClear")
        matches = len(state()["matches"])
        LOL_STATE.update(up=True, time=5.0, end=None)
        check("LoL: maç başında tahmin açıldı", await wait_until(lambda: _state_is(p, lambda s: s["prediction"]["status"] == "open"), 8))
        LOL_STATE["time"] = 190.0
        check("LoL: 3. dakikada kilitlendi", await wait_until(lambda: _state_is(p, lambda s: s["prediction"]["status"] == "locked"), 8))
        LOL_STATE["end"] = "Win"
        check("LoL: galibiyet kendiliğinden girildi", await wait_until(lambda: _state_is(p, lambda s: len(s["matches"]) == matches + 1 and s["matches"][-1] == "W"), 8))
        LOL_STATE["up"] = False

        print("\nYayın öncesi kontrol · prova")
        n = len(sb.said)
        await p.act("countdown", minutes=10)
        left = (state()["countdown"] or 0) / 1000 - time.time()
        check("geri sayım 10 dk kuruldu ve duyuruldu", 590 < left <= 600 and any("10 dakika sonra" in t for t in sb.said_since(n)), f"{left:.0f}")
        await p.act("countdown", minutes=0)
        check("geri sayım iptal edildi", state()["countdown"] is None)
        await obs.set_scene("Yayın Başlıyor")
        await p.drain()
        await p.act("countdown", minutes=0.05)
        switched = await wait_until(lambda: _state_is(p, lambda s: s["scene"] == "Sahne" and s["countdown"] is None), 10)
        check("sayaç bitince Yayın Başlıyor → Sahne geçildi", switched and obs.scene == "Sahne", f"{obs.scene} {state().get('scene')}")
        await ws.send(json.dumps({"action": "preflight"}))
        pre = None
        for _ in range(10):
            m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if m["type"] == "preflight":
                pre = m["items"]
                break
        labels = {label: ok for label, ok, _ in (pre or [])}
        check("ön kontrol: OBS, Streamer.bot, 8/8 action, webhook", labels.get("OBS bağlı") and labels.get("Streamer.bot bağlı")
              and labels.get("Streamer.bot action'ları (8/8)") and labels.get("Discord webhook"), str(pre))
        await asyncio.sleep(12)  # let the earlier Kraken/raid cards clear
        await p.drain()
        n = len(sb.said)
        await p.act("rehearsal")
        saw = await wait_until(lambda: _state_is(p, lambda s: (s["kraken"] or {}).get("status") == "won"), 40)
        check("prova ekranda oynadı, sohbete yazmadı", saw and len(sb.said) == n, f"bot mesajı: {sb.said_since(n)}")

        print("\nModerasyon · özet")
        del sb.actions["ModBanKick"]
        await p.act("modAction", platform="kick", name="Troll", type="ban")
        check("eksik moderasyon action'ı bildirildi", p.notices and "ModBanKick" in p.notices[-1], p.notices[-1:])
        await p.act("discordSummary", wait=1.5)
        summary = HOOK_POSTS[-1]["content"] if HOOK_POSTS else ""
        await p.act("startShow", wait=1, game="League of Legends", routes=[], announce=False, updateInfo=False)
        nights = state().get("nights") or []
        last = nights[-1] if nights else {}
        check("yeni yayında önceki gece arşivlendi", len(nights) == 1 and last.get("game") == "Minecraft" and last.get("follows") == 2
              and last.get("chat", 0) > 0 and (tmp / ".nights.jsonl").exists(), str(last))
        await ws.send(json.dumps({"action": "exportData"}))
        exported = None
        for _ in range(20):
            m = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if m["type"] == "export":
                exported = m["data"]
                break
        check("yedek indirme tüm tayfayı ve arşivi içeriyor", exported and "twitch:ali" in exported["crew"] and len(exported["nights"]) == 1)
        backups = sorted((tmp / "backups").glob("*.json"))
        check("açılışta ve yeni yayında otomatik yedek alındı", any("acilis" in b.name for b in backups) and any("yeni-yayin" in b.name for b in backups), str([b.name for b in backups]))
        shrunk = {"crew": {"kick:yeni": {"platform": "kick", "name": "Yeni", "points": 99, "streams": 1, "show": None, "last": 0}}, "nights": []}
        await p.act("importData", data=shrunk)
        restored = [c["name"] for c in state()["topCrew"]]
        await p.act("importData", data=exported)
        check("yedek geri yükleme veriyi değiştirir, önceki veri geri alınabilir", restored == ["Yeni"] and len(state()["topCrew"]) > 1
              and any("geri-yukleme-oncesi" in b.name for b in (tmp / "backups").glob("*.json")), str(restored))
        check("Discord özeti gece istatistikleriyle gitti", "sefer bitti" in summary and "Kraken 1/1" in summary and "Baskınlar" in summary, summary[:200])
        n = len(sb.said)
        for i in range(3):
            if i:
                await asyncio.sleep(1.1)  # show ids have one-second resolution
                await p.act("resetShow")
            await sb.chat("twitch", "Sadik", "selam kaptan")
            await p.drain()
        said = sb.said_since(n)
        check("3 yayın üst üste gelen sadakat ödülü aldı", any("3 yayındır üst üste" in t and "+15" in t for t in said)
              and crew_db_of(tmp).get("twitch:sadik", {}).get("loot", 0) >= 15, str(said))
        check("overlay'e sadakat serisi gidiyor", any(c["name"] == "Sadik" and c.get("streak") == 3 for c in state()["crew"]), str(state()["crew"][-3:]))
        check("yayın özetinde sadık mürettebat var", "Sadık mürettebat: Sadik (3 yayın" in (state().get("summaryText") or ""), (state().get("summaryText") or "")[-300:])


def crew_db_of(tmp):
    try:
        return json.loads((tmp / ".crew.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


async def _state_is(panel, predicate):
    await panel.drain(0.5)
    try:
        return predicate(panel.state)
    except (KeyError, TypeError, IndexError):
        return False


async def main():
    tmp = Path(tempfile.mkdtemp(prefix="qedy-test-"))
    config = json.loads((OVERLAY / "show-config.json").read_text(encoding="utf-8"))
    config["obs"] = {"url": f"ws://127.0.0.1:{OBS}/", "password": ""}
    config["lolAuto"] = {"url": f"http://127.0.0.1:{LOL}/liveclientdata/", "lockAfterSec": 180}
    config["games"] = {"fishCooldownSec": 60, "kraken": {"durationSec": 60, "randomMinMinutes": 999, "randomMaxMinutes": 999, "raidMinViewers": 99},
                       "race": {"joinSec": 2, "maxBoats": 8}}
    config["tips"] = {"everyMinutes": 999}
    config["chatLinks"] = {"!site": "⚓ https://ertugrul-tug.github.io/stream-library/", "!discord": ""}  # "" = unset link stays silent
    (tmp / "show-config.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    (tmp / "show-config.local.json").write_text(json.dumps({"pin": PIN, "discordWebhook": f"http://127.0.0.1:{HOOK}/"}), encoding="utf-8")
    (tmp / ".crew.json").write_text(json.dumps({"twitch:zengin": {"platform": "twitch", "name": "Zengin", "points": 0, "streams": 1,
                                                                   "show": None, "last": 0, "loot": 500}}), encoding="utf-8")
    (tmp / ".show-state.json").mkdir()  # the state file can never be written: the whole show must run anyway
    sb, obs = FakeStreamerBot(), FakeOBS()
    serve_http(LOL, LolHandler)
    serve_http(HOOK, HookHandler)
    env = {**os.environ, "QEDY_DATA_DIR": str(tmp), "QEDY_CONFIG": str(tmp / "show-config.json"),
           "QEDY_SB_URL": f"ws://127.0.0.1:{SB}/", "QEDY_WS_PORT": str(WS), "QEDY_HTTP_PORT": str(HTTP), "PYTHONIOENCODING": "utf-8"}
    log = open(tmp / "bridge.log", "w", encoding="utf-8")
    async with serve(sb.handler, "127.0.0.1", SB), serve(obs.handler, "127.0.0.1", OBS):
        bridge = subprocess.Popen([sys.executable, str(OVERLAY / "show-bridge.py")], env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            ready = await wait_until(_bridge_ready, 15)
            await wait_until(lambda: _true(bool(sb.conns and obs.ws)), 10)
            if not ready:
                print("Köprü açılmadı; bridge.log:", (tmp / "bridge.log").read_text(encoding="utf-8")[-2000:])
                return 1
            await run(sb, obs, tmp)
        except Exception:
            traceback.print_exc()
            RESULTS.append(("test çalıştırıcısı", False, "istisna"))
        finally:
            bridge.terminate()
            bridge.wait(5)
            log.close()
    bridge_log = (tmp / "bridge.log").read_text(encoding="utf-8")
    crashes = bridge_log.count("Traceback")
    check("kayıt dosyası yazılamazken yayın sürdü, uyarı bir kez", bridge_log.count("diske yazılamadı") == 1, str(bridge_log.count("diske yazılamadı")))
    check("köprü hiç hata dökümü basmadı", crashes == 0, f"{crashes} traceback · {tmp / 'bridge.log'}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} test geçti")
    if not failed:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if failed else 0


async def _bridge_ready():
    try:
        async with websockets.connect(f"ws://127.0.0.1:{WS}/", open_timeout=1):
            return True
    except OSError:
        return False


async def _true(value):
    return value


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
