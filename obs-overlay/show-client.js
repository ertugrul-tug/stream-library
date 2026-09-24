(() => {
  'use strict';
  const root = document.querySelector('.overlay,.scene');
  if (!root) return;
  const kind = root.classList.contains('start') ? 'start' : root.classList.contains('break') ? 'break' : root.classList.contains('end') ? 'end' : root.classList.contains('chat-scene') ? 'chat' : 'overlay';
  const sample = new URLSearchParams(location.search).has('sample');
  const card = (className, label) => {
    const node = document.createElement('section'); node.className = 'show-card ' + className;
    const title = document.createElement('div'); title.className = 'show-label'; title.textContent = label; node.append(title); root.append(node); return node;
  };
  const crew = kind === 'start' ? card('show-crew','RADAR · MÜRETTEBAT') : null;
  const log = kind === 'break' ? card('show-log','SEYİR DEFTERİ') : null;
  const end = kind === 'end' ? card('show-end','BU SEFERİN ÖZETİ') : null;
  const spotlight = kind === 'chat' || kind === 'overlay' ? card('show-spotlight','KAPTANIN ANONSU') : null;
  const vote = kind === 'overlay' ? card('show-vote','SONRAKİ ROTA') : null;
  const score = kind === 'overlay' ? card('show-score','BU AKŞAMKİ SERİ') : null;
  let scoreSig = null;
  const predict = kind === 'overlay' ? card('show-predict','MAÇ TAHMİNİ') : null;
  let predictDoneSig = null, predictDoneAt = 0;
  const rankUp = kind === 'overlay' ? card('show-rankup','RÜTBE ATLADI') : null;
  let rankUpShown = 0;
  // Mini games (game scene only): one centered event lane under the segment strip, rank-up toast at its end.
  let games = null;
  if (kind !== 'end') {  // game scene, chat scene, and the start/break screens (viewers fish and race while waiting)
    const lane = document.createElement('div'); lane.className = 'show-events'; root.append(lane);
    games = { raid: card('show-raid','BASKIN'), kraken: card('show-kraken','KRAKEN'), race: card('show-race','YELKEN YARIŞI'), fish: card('show-fish','OLTA') };
    lane.append(games.raid, games.kraken, games.race, games.fish);
    if (rankUp) lane.append(rankUp);
  }
  let krakenId = null, krakenHp = null, krakenState = null, krakenStatus = null, raceId = null, raceState = null, raceStatus = null;
  let fishSeen = null, fishQueue = [], fishBusy = false, raidId = null, fxSeen = null;
  let segment = null, lastSchedule = {}, segmentOn = true, goalInfo = null;
  if (kind === 'overlay') { segment = document.createElement('div'); segment.className = 'show-segment'; root.append(segment); }
  function renderSegment() {
    const rows = Object.entries(lastSchedule).map(([label, t]) => { const [h, m] = String(t).split(':').map(Number); return [label, t, h * 60 + m]; }).sort((a, b) => a[2] - b[2]);
    const now = new Date(); let mins = now.getHours() * 60 + now.getMinutes();
    if (mins < 300) mins += 1440; // after midnight still belongs to tonight's show
    const cur = rows.filter(r => r[2] <= mins).pop(), next = rows.find(r => r[2] > mins);
    segment.classList.toggle('active', segmentOn && rows.length > 0);
    segment.replaceChildren();
    const part = (cls, label, value) => { const s = document.createElement('span'); s.className = cls; s.textContent = label + ' · '; const b = document.createElement('b'); b.textContent = value; s.append(b); segment.append(s); };
    if (cur) part('now', 'ŞİMDİ', cur[0]);
    if (next) part('next', 'SIRADAKİ', next[0] + ' ' + next[1]);
    if (goalInfo && goalInfo.target) {
      const g = document.createElement('span'); g.className = 'goal' + (goalInfo.reached ? ' done' : '');
      g.textContent = `🎯 ${Math.min(goalInfo.count, goalInfo.target)}/${goalInfo.target} takipçi`;
      const bar = document.createElement('i'); const fill = document.createElement('i');
      fill.style.width = Math.min(100, 100 * goalInfo.count / goalInfo.target) + '%'; bar.append(fill); g.append(bar);
      segment.append(g);
      segment.classList.add('active');
    }
  }
  if (segment) setInterval(renderSegment, 30000);
  function tally(matches) {
    const m = matches || [], last = m[m.length-1];
    let streak = 0;
    for (let i = m.length-1; i >= 0 && m[i] === last; i--) streak++;
    return { m, wins: m.filter(x=>x==='W').length, losses: m.filter(x=>x==='L').length, last, streak };
  }
  // '%50'si', '%70'i', '%30'u' — same rule as pct_tr() in show-bridge.py
  const pctTr = n => n === 100 ? "%100'ü" : `%${n}'${n % 10 ? {1:'i',2:'si',3:'ü',4:'ü',5:'i',6:'sı',7:'si',8:'i',9:'u'}[n % 10] : {0:'ı',10:'u',20:'si',30:'u',40:'ı',50:'si',60:'ı',70:'i',80:'i',90:'ı'}[n]}`;
  const div = (parent, cls, content) => { const e=document.createElement('div'); e.className=cls; e.textContent=content; parent.append(e); return e; };
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function countUp(el, target) {
    target = Number(target) || 0;
    if (reduceMotion) { el.textContent = String(target); return; }
    const duration = 900, start = performance.now();
    (function tick(now) {
      const p = Math.min(1, (now - start) / duration);
      el.textContent = String(Math.round(target * (1 - Math.pow(1 - p, 3))));
      if (p < 1) requestAnimationFrame(tick);
    })(start);
  }
  // Mini-game sounds, synthesized (no audio files). OBS only mixes the scene that is on air, so pages don't overlap.
  let audioCtx = null, sfxEnabled = true, lastHitSound = 0;
  function tone(freq, dur, opt = {}) {
    if (!sfxEnabled || sample) return;
    try {
      audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
      if (audioCtx.state === 'suspended') audioCtx.resume();
      const t = audioCtx.currentTime + (opt.delay || 0), osc = audioCtx.createOscillator(), g = audioCtx.createGain();
      osc.type = opt.type || 'sine';
      osc.frequency.setValueAtTime(freq, t);
      if (opt.to) osc.frequency.exponentialRampToValueAtTime(opt.to, t + dur);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(opt.gain || 0.1, t + Math.min(0.03, dur / 3));
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      let node = osc;
      if (opt.lowpass) { const f = audioCtx.createBiquadFilter(); f.type = 'lowpass'; f.frequency.value = opt.lowpass; osc.connect(f); node = f; }
      node.connect(g); g.connect(audioCtx.destination);
      osc.start(t); osc.stop(t + dur + 0.05);
    } catch (_) {}
  }
  const arp = (notes, step, opt) => notes.forEach((f, i) => tone(f, opt.dur || 0.25, { ...opt, delay: i * step }));
  const sfx = {
    krakenStart() { tone(70, 1.4, { type: 'sawtooth', to: 38, gain: 0.16, lowpass: 380 }); tone(105, 1.1, { type: 'sawtooth', to: 52, gain: 0.08, lowpass: 300, delay: 0.15 }); },
    hit() { const now = Date.now(); if (now - lastHitSound < 220) return; lastHitSound = now; tone(150, 0.14, { type: 'triangle', to: 55, gain: 0.12 }); },
    win() { arp([523, 659, 784, 1047], 0.11, { type: 'triangle', gain: 0.1, dur: 0.3 }); },
    lose() { tone(330, 0.9, { type: 'triangle', to: 110, gain: 0.08 }); },
    fish(rarity) {
      tone(620, 0.18, { to: 180, gain: 0.09 });
      if (rarity === 'nadir') arp([1319, 1568, 1760], 0.07, { gain: 0.05, dur: 0.18, delay: 0 });
      if (rarity === 'efsane') arp([784, 988, 1175, 1568, 1976], 0.09, { type: 'triangle', gain: 0.08, dur: 0.35 });
    },
    horn() { tone(196, 0.45, { type: 'square', gain: 0.05, lowpass: 900 }); tone(247, 0.6, { type: 'square', gain: 0.05, lowpass: 900, delay: 0.45 }); },
    bell() { arp([1047, 1319, 1568], 0.16, { gain: 0.08, dur: 0.8 }); },
  };
  const secsLeft = at => Math.max(0, Math.ceil((at - Date.now()) / 1000));
  function renderKraken(k) {
    const c = games.kraken;
    c.classList.toggle('active', !!k);
    krakenState = k;
    if (!k) { krakenId = null; return; }
    if (k.id !== krakenId) {
      krakenId = k.id; krakenHp = k.max; krakenStatus = null;
      c.querySelectorAll('.kr-body').forEach(n => n.remove());
      const body = div(c, 'kr-body', ''); div(body, 'kr-emoji', '🐙');
      const info = div(body, 'kr-info', ''); div(info, 'kr-title', '');
      div(info, 'kr-bar', '').append(document.createElement('i')); div(info, 'kr-line', ''); div(info, 'kr-hits', '');
    }
    c.dataset.status = k.status;
    c.querySelector('.kr-title').textContent = k.status === 'active' ? 'KRAKEN SALDIRIYOR!' : k.status === 'won' ? 'KRAKEN YENİLDİ!' : 'KRAKEN KAÇTI…';
    c.querySelector('.kr-bar i').style.width = (100 * k.hp / k.max) + '%';
    c.querySelector('.kr-hits').textContent = (k.last || []).join('   ·   ');
    if (k.hp < krakenHp) { sfx.hit(); if (!reduceMotion) { c.classList.remove('hit'); void c.offsetWidth; c.classList.add('hit'); } }
    if (k.status !== krakenStatus) { ({ active: sfx.krakenStart, won: sfx.win, lost: sfx.lose })[k.status]?.(); krakenStatus = k.status; }
    krakenHp = k.hp;
    tickKraken();
  }
  function tickKraken() {
    const k = krakenState, line = games && games.kraken.querySelector('.kr-line');
    if (!k || !line) return;
    line.textContent = k.status === 'active' ? `!saldır yaz · ${secsLeft(k.endsAt)} sn · ${k.hp}/${k.max} can`
      : k.status === 'won' ? `Son vuruş: ${k.killer} · saldıran herkese ganimet` : 'Bir dahaki sefere daha sert vurun!';
  }
  function renderRace(r) {
    const c = games.race;
    c.classList.toggle('active', !!r);
    raceState = r;
    if (!r) { raceId = null; return; }
    if (r.id !== raceId) { raceStatus = null; raceId = r.id; c.querySelectorAll('.race-body').forEach(n => n.remove()); div(c, 'race-body', ''); }
    c.dataset.status = r.status;
    if (r.status !== raceStatus) { if (r.status === 'join' || r.status === 'race') sfx.horn(); else if (r.status === 'done') sfx.bell(); raceStatus = r.status; }
    const body = c.querySelector('.race-body'), medals = ['🥇','🥈','🥉'];
    if (r.status === 'join') {
      body.replaceChildren(); div(body, 'race-line', '');
      const chips = div(body, 'race-chips', '');
      r.boats.forEach(b => div(chips, 'chip ' + b.platform, '⛵ ' + b.name));
      tickRace();
    } else if (r.status === 'race') {
      let lanes = body.querySelector('.race-lanes');
      if (!lanes || lanes.childElementCount !== r.boats.length) {
        body.replaceChildren(); div(body, 'race-line', 'Yazdıkça hızlan! 💨');
        lanes = div(body, 'race-lanes', '');
        r.boats.forEach(b => { const row = div(lanes, 'lane ' + b.platform, ''); div(row, 'lane-name', b.name); div(div(row, 'lane-track', ''), 'boat', '⛵'); });
      }
      r.boats.forEach((b, i) => {
        const row = lanes.children[i], place = r.podium.indexOf(b.key);
        row.querySelector('.boat').style.left = `calc(${b.pos}% - ${b.pos / 100 * 1.4}vw)`;
        row.classList.toggle('finished', place >= 0);
        row.querySelector('.lane-name').textContent = (place >= 0 ? medals[place] + ' ' : '') + b.name;
      });
    } else {
      body.replaceChildren();
      if (r.status === 'done') {
        const byKey = Object.fromEntries(r.boats.map(b => [b.key, b])), pod = div(body, 'race-podium', '');
        r.podium.slice(0, 3).forEach((k, i) => div(pod, 'podium-' + i, medals[i] + ' ' + byKey[k].name));
      } else div(body, 'race-line', 'Yarış iptal edildi');
    }
  }
  function tickRace() {
    const r = raceState, line = games && games.race.querySelector('.race-line');
    if (r && r.status === 'join' && line) line.textContent = `!katıl yaz · ${secsLeft(r.endsAt)} sn · ${r.boats.length} gemi`;
  }
  if (games) setInterval(() => { tickKraken(); tickRace(); }, 500);
  function renderRaid(r) {
    const c = games.raid;
    c.classList.toggle('active', !!r);
    if (!r || r.id === raidId) return;
    raidId = r.id;
    c.querySelectorAll('.raid-body').forEach(n => n.remove());
    c.dataset.platform = r.platform;
    const body = div(c, 'raid-body', ''); div(body, 'raid-flag', '🏴‍☠️');
    const info = div(body, 'raid-info', ''); div(info, 'raid-name', r.name); div(info, 'raid-count', `${r.viewers} kişilik tayfasıyla güverteye çıktı!`);
    sfx.horn(); setTimeout(sfx.win, 700);
  }
  // Market effects (!martı, !konfeti, !top) play across the whole scene.
  function renderEffects(list) {
    list = list || [];
    if (fxSeen === null) { fxSeen = new Set(list.map(x => x.id)); return; }
    list.forEach(x => { if (!fxSeen.has(x.id)) { fxSeen.add(x.id); playEffect(x); } });
  }
  function banner(text, platform) {
    const b = document.createElement('div'); b.className = 'fx-banner ' + (platform || ''); b.textContent = text;
    b.style.bottom = (17 + 5 * root.querySelectorAll('.fx-banner').length) + '%';  // stack when effects overlap
    root.append(b); setTimeout(() => b.remove(), 3600);
  }
  function confetti() {
      const colors = ['#22aef0', '#ff3d7f', '#ffce54', '#5cf0a0', '#9146ff', '#53fc18'];
      for (let i = 0; i < (reduceMotion ? 0 : 90); i++) {
        const c = document.createElement('i'); c.className = 'fx-confetti';
        c.style.left = Math.random() * 100 + '%'; c.style.background = colors[i % colors.length];
        c.style.animationDelay = Math.random() * 0.8 + 's'; c.style.animationDuration = 2.4 + Math.random() * 1.6 + 's';
        c.style.setProperty('--drift', (Math.random() * 16 - 8) + 'vw'); c.style.setProperty('--spin', (Math.random() * 900 - 450) + 'deg');
        root.append(c); setTimeout(() => c.remove(), 5000);
      }
  }
  function playEffect(x) {
    if (x.type === 'martı') {
      const g = document.createElement('div'); g.className = 'fx-gull';
      const bird = document.createElement('span'); bird.textContent = '🕊️';
      const tag = document.createElement('small'); tag.textContent = x.name;
      g.append(bird, tag); root.append(g); setTimeout(() => g.remove(), 6000);
      tone(1400, 0.18, { to: 900, type: 'triangle', gain: 0.05 }); tone(1500, 0.22, { to: 850, type: 'triangle', gain: 0.05, delay: 0.3 });
    } else if (x.type === 'konfeti') {
      confetti();
      banner(`🎉 ${x.name} konfeti patlattı!`, x.platform);
      arp([784, 988, 1175], 0.06, { type: 'triangle', gain: 0.06, dur: 0.2 });
    } else if (x.type === 'goal') {
      confetti();
      banner(`🎯 ${x.name} takipçi hedefi tamam!`, '');
      sfx.win();
    } else if (x.type === 'top') {
      const f = document.createElement('div'); f.className = 'fx-flash'; root.append(f); setTimeout(() => f.remove(), 700);
      if (!reduceMotion) { root.classList.remove('fx-shake'); void root.offsetWidth; root.classList.add('fx-shake'); setTimeout(() => root.classList.remove('fx-shake'), 700); }
      banner(`💥 ${x.name} top ateşledi!`, x.platform);
      tone(60, 0.9, { type: 'sawtooth', to: 30, gain: 0.2, lowpass: 240 }); tone(95, 0.5, { type: 'square', to: 40, gain: 0.08, lowpass: 400 });
    }
  }
  function renderFish(list) {
    list = list || [];
    if (fishSeen === null) { fishSeen = new Set(list.map(x => x.id)); return; }  // don't replay old catches on page load
    list.forEach(x => { if (!fishSeen.has(x.id)) { fishSeen.add(x.id); fishQueue.push(x); } });
    fishQueue = fishQueue.slice(-4);
    playFish();
  }
  function playFish() {
    if (fishBusy || !fishQueue.length) return;
    fishBusy = true;
    const x = fishQueue.shift(), c = games.fish;
    c.querySelectorAll('.fish-body').forEach(n => n.remove());
    c.dataset.rarity = ''; c.dataset.platform = x.platform;
    const body = div(c, 'fish-body', ''); div(body, 'fish-who', x.name);
    const got = div(body, 'fish-catch bobbing', '🎣'), note = div(body, 'fish-note', 'olta attı…');
    c.classList.add('active');
    setTimeout(() => { got.classList.remove('bobbing'); got.textContent = x.emoji; sfx.fish(x.rarity); c.dataset.rarity = x.rarity; note.textContent = `${x.item} · +${x.points}`; if (x.new) div(body, 'fish-new', 'YENİ!'); }, reduceMotion ? 300 : 2600);
    setTimeout(() => { c.classList.remove('active'); setTimeout(() => { fishBusy = false; playFish(); }, 400); }, reduceMotion ? 3500 : 6200);
  }
  function render(s) {
    // Share ranks with the chat boxes on this page (they read chat straight from Streamer.bot).
    const ranks = new Map();
    [...(s.topCrew || []), ...(s.crew || [])].forEach(c => { if (c.rank && c.rank !== 'Miço') ranks.set(`${c.platform}:${String(c.name).toLocaleLowerCase('tr-TR')}`, c.rank); });
    window.qedyRanks = ranks;
    sfxEnabled = s.sfx !== false;
    if (games) renderEffects(s.effects);
    if (games) { renderRaid(s.raid); renderKraken(s.kraken); renderRace(s.race); renderFish(s.catches); }
    if (crew) {
      crew.querySelectorAll('.crew-list,.show-small').forEach(n=>n.remove());
      const list=div(crew,'crew-list','');
      (s.crew || []).slice(-8).reverse().forEach(p=>{const n=div(list,'crew-person '+p.platform,p.name);if(p.rank){const r=document.createElement('small');r.className='rank';r.textContent=p.rank;n.append(r);}});
      if (!list.childElementCount) div(crew,'show-small','Sohbete yazanlar burada görünecek.');
    }
    if (log) {
      log.querySelectorAll('.show-value,.show-small').forEach(n=>n.remove());
      div(log,'show-small','ŞİMDİ OYNANIYOR'); div(log,'show-value',s.game || 'Oyun bilgisi bekleniyor');
      div(log,'show-small','DÖNÜŞ NOTU'); div(log,'show-value',s.returnMessage || 'Birazdan dönüyoruz');
      const t=tally(s.matches);
      if(t.m.length) { div(log,'show-small','BU AKŞAMKİ SERİ'); div(log,'show-value',`${t.wins}G · ${t.losses}M`); }
      const highlights=(s.highlights || []).slice(-2);
      if(highlights.length) { div(log,'show-small','BUGÜNDEN NOTLAR'); highlights.forEach(x=>div(log,'show-value',x)); }
    }
    if (end) {
      end.querySelectorAll('.stat-grid,.show-small,.highlight').forEach(n=>n.remove());
      const stats=s.stats || {}, t=stats.twitch || {}, k=stats.kick || {};
      const grid=div(end,'stat-grid','');
      const rows=[['TWITCH MESAJ',t.chat],['KICK MESAJ',k.chat],['YENİ TAKİP',(t.follow||0)+(k.follow||0)],['ABONELİK',(t.sub||0)+(k.sub||0)]];
      const m=s.matches||[];
      if(m.length) {
        let best=0,run=0; m.forEach(x=>{run=x==='W'?run+1:0;best=Math.max(best,run)});
        const w=m.filter(x=>x==='W').length;
        rows.push(['SKOR',`${w}-${m.length-w}`,'score'],['REKOR SERİ',best>=2?`${best}🔥`:String(best),'streak']);
        grid.classList.add('six');
      }
      rows.forEach(([label,value,cls])=>{
        const n=div(grid,'stat '+(cls||''),''); const strong=document.createElement('strong'); n.append(strong); div(n,'',label);
        if(cls) strong.textContent=value; else { strong.textContent='0'; countUp(strong,value); }
      });
      const hist=s.predictionHistory||[], total=hist.reduce((a,h)=>a+h.total,0);
      if(total) div(end,'show-small end-predict',`🔮 SOHBET TAHMİNİ · %${Math.round(100*hist.reduce((a,h)=>a+h.right,0)/total)} İSABET · ${total} TAHMİN`);
      if(s.lootKing) div(end,'show-small end-predict end-king',`👑 GANİMET KRALI · ${s.lootKing.name} · ${s.lootKing.loot}`);
      div(end,'show-small','SEYİR DEFTERİNDEN');
      (s.highlights || []).slice(-3).forEach(x=>div(end,'highlight','✦ '+x));
      if (!(s.highlights || []).length) div(end,'highlight','Öne çıkan anlar burada görünecek.');
    }
    if (spotlight) {
      spotlight.classList.toggle('active',!!s.spotlight);
      if(s.spotlight) {
        spotlight.dataset.platform=s.spotlight.platform;
        spotlight.dataset.kind=s.spotlight.kind||'';
        spotlight.querySelector('.show-label').textContent=s.spotlight.kind==='question'?'❓ SOHBETTEN SORU':'KAPTANIN ANONSU';
        spotlight.querySelectorAll('.show-text,.show-author').forEach(n=>n.remove());
        const said=div(spotlight,'show-text',s.spotlight.text);
        if(window.qedyEmotes && s.spotlight.parts) qedyEmotes.render(said,s.spotlight.parts,300);
        div(spotlight,'show-author',s.spotlight.platform.toUpperCase()+' · '+s.spotlight.name);
      }
    }
    if(vote) {
      vote.querySelectorAll('.vote-row,.show-small').forEach(n=>n.remove());
      const routes=s.routes || [], counts=s.voteCounts || [], total=counts.reduce((a,b)=>a+b,0);
      vote.classList.toggle('active',routes.length>0 && s.routesVisible!==false);
      routes.forEach((route,i)=>{
        const row=div(vote,'vote-row',''); const number=document.createElement('b'); number.textContent=String(i+1); row.append(number);
        const name=document.createElement('span'); name.textContent=route; row.append(name);
        const count=document.createElement('span'); count.textContent=String(counts[i]||0); row.append(count);
        const track=div(row,'vote-track',''); const fill=document.createElement('i'); fill.style.width=(total?100*(counts[i]||0)/total:0)+'%'; track.append(fill);
      });
      div(vote,'show-small','TWITCH + KICK · !rota 1 / 2 / 3');
    }
    if(predict) {
      const p=s.prediction || {status:'off'}, w=p.w||0, l=p.l||0, total=w+l;
      if(p.status==='done') {
        const sig=[p.result,w,l].join(':');
        if(sig!==predictDoneSig){ predictDoneSig=sig; predictDoneAt=Date.now(); setTimeout(()=>predict.classList.remove('active'),30000); }
      } else predictDoneSig=null;
      const expired = p.status==='done' && Date.now()-predictDoneAt>=30000;
      predict.classList.toggle('active', p.status!=='off' && !expired && !(p.status==='done' && !total));
      predict.dataset.status=p.status;
      predict.querySelectorAll('.predict-bar,.predict-legend,.show-small,.predict-result').forEach(n=>n.remove());
      if(p.status==='done' && total) {
        const right=p.result==='W'?w:l, pct=Math.round(100*right/total);
        div(predict,'predict-result',(pct>=50?'✅ ':'❌ ')+`Sohbetin ${pctTr(pct)} bildi`);
      }
      const bar=div(predict,'predict-bar','');
      const wi=document.createElement('i'); wi.className='w'; wi.style.width=(total?100*w/total:50)+'%';
      const li=document.createElement('i'); li.className='l'; li.style.width=(total?100*l/total:50)+'%';
      bar.append(wi,li);
      const legend=div(predict,'predict-legend','');
      const lw=document.createElement('span'); lw.className='w'; lw.textContent=`GALİBİYET ${total?Math.round(100*w/total):0}%`;
      const ll=document.createElement('span'); ll.className='l'; ll.textContent=`${total?Math.round(100*l/total):0}% MAĞLUBİYET`;
      legend.append(lw,ll);
      div(predict,'show-small', p.status==='open' ? `!tahmin G  ·  !tahmin M   —   ${total} tahmin` : p.status==='locked' ? `🔒 Tahminler kilitlendi · ${total} tahmin` : `Maç sonucu: ${p.result==='W'?'GALİBİYET':'MAĞLUBİYET'}`);
    }
    if(segment) { lastSchedule=s.schedule||{}; segmentOn=s.segmentVisible!==false; const st=s.stats||{}; goalInfo=s.goal&&s.goal.target?{target:s.goal.target,reached:s.goal.reached,count:((st.twitch||{}).follow||0)+((st.kick||{}).follow||0)}:null; renderSegment(); }
    if(rankUp && s.rankUp && s.rankUp.at!==rankUpShown && Date.now()-s.rankUp.at<10000) {
      rankUpShown=s.rankUp.at;
      rankUp.querySelectorAll('.rank-name,.rank-title').forEach(n=>n.remove());
      rankUp.dataset.platform=s.rankUp.platform;
      div(rankUp,'rank-name',s.rankUp.name);
      div(rankUp,'rank-title','⚓ '+s.rankUp.rank);
      rankUp.classList.remove('active'); void rankUp.offsetWidth; rankUp.classList.add('active');
      clearTimeout(rankUp._t); rankUp._t=setTimeout(()=>rankUp.classList.remove('active'),6000);
    }
    if(score) {
      const t=tally(s.matches);
      score.classList.toggle('active', t.m.length>0 && s.scoreVisible!==false);
      const sig=t.m.join('');
      if(sig!==scoreSig) {
        const grew = scoreSig!==null && sig.length>scoreSig.length;
        scoreSig=sig;
        score.querySelectorAll('.score-line,.score-dots,.score-streak').forEach(n=>n.remove());
        const line=div(score,'score-line','');
        [['w',t.wins,'G'],['l',t.losses,'M']].forEach(([cls,n,unit])=>{
          const b=document.createElement('b'); b.className=cls; b.textContent=String(n); line.append(b);
          const u=document.createElement('small'); u.textContent=unit; line.append(u);
        });
        const dots=div(score,'score-dots',''), recent=t.m.slice(-5);
        for(let i=0;i<5;i++){
          const d=document.createElement('i'), r=recent[i-(5-recent.length)];
          if(r) d.className=r==='W'?'w':'l';
          if(grew && i===4) d.classList.add('new');
          dots.append(d);
        }
        const onFire=t.last==='W' && t.streak>=2;
        score.classList.toggle('fire',onFire);
        score.style.setProperty('--heat', onFire ? String(Math.min(2, 0.5+t.streak*0.25)) : '0');
        let text='';
        if(onFire) text=`🔥 ${t.streak} GALİBİYET SERİSİ`;
        else if(t.last==='L' && t.streak>=2) text=`${t.streak} MAĞLUBİYET · TOPARLANIYORUZ`;
        else if(t.last) text=t.last==='W'?'SON MAÇ · GALİBİYET':'SON MAÇ · MAĞLUBİYET';
        div(score,'score-streak',text);
        if(grew && !reduceMotion){ score.classList.remove('bump'); void score.offsetWidth; score.classList.add('bump'); }
      }
    }
  }
  const demo={game:'Sisli Vadi',returnMessage:'5 dakika sonra tekrar güvertedeyiz',routes:['Ana göreve devam','Yan görev keşfi','Haritayı aç'],crew:[{platform:'twitch',name:'MaviKaptan',rank:'Lostromo'},{platform:'kick',name:'YesilLiman',rank:'Tayfa'},{platform:'twitch',name:'Denizci42',rank:'Miço'}],schedule:{'Açılış sohbet':'20:30','Tema bloğu':'21:00','Günlük sohbet':'23:00','Kapanış':'23:30'},rankUp:{platform:'twitch',name:'MaviKaptan',rank:'Lostromo',at:Date.now()},highlights:['İlk büyük zafer','Gizli liman bulundu'],spotlight:{platform:'twitch',name:'MaviKaptan',text:'Bu akşam rota nereye dönüyor kaptan?'},voteCounts:[8,5,3],matches:['L','W','L','W','W','W'],prediction:{status:'open',w:14,l:6},predictionHistory:[{right:9,total:12},{right:5,total:10}],stats:{twitch:{chat:143,follow:6,sub:2},kick:{chat:97,follow:4,sub:1}},lootKing:{platform:'kick',name:'YesilLiman',loot:128},goal:{target:12,reached:false},raid:location.search.includes('raid')?{id:'raid1',platform:'twitch',name:'KorsanBey',viewers:23}:null,kraken:location.search.includes('race')?null:{id:'k1',status:'active',hp:23,max:48,endsAt:Date.now()+57000,last:['MaviKaptan −3','YesilLiman −9 💥','Denizci42 −2'],killer:null},race:location.search.includes('race')?{id:'r1',status:'race',endsAt:0,podium:['twitch:mavikaptan'],boats:[{key:'kaptan:kaptan',platform:'kaptan',name:'Kaptan',pos:64},{key:'twitch:mavikaptan',platform:'twitch',name:'MaviKaptan',pos:100},{key:'kick:yesilliman',platform:'kick',name:'YesilLiman',pos:81},{key:'twitch:denizci42',platform:'twitch',name:'Denizci42',pos:37}]}:null,catches:[{id:'f1',platform:'kick',name:'YesilLiman',item:'Altın sandık',emoji:'💰',points:60,rarity:'efsane'}]};
  if(sample) { fishSeen=new Set(); if(location.search.includes('fx')) { fxSeen=new Set(); demo.effects=[{id:'e1',type:'top',name:'MaviKaptan',platform:'twitch'},{id:'e2',type:'konfeti',name:'YesilLiman',platform:'kick'},{id:'e3',type:'martı',name:'Denizci42',platform:'twitch'}]; } render(demo); } else render({routes:[],crew:[],stats:{}});
  function connect() {
    let ws;
    try { ws=new WebSocket('ws://127.0.0.1:8765/'); } catch(_) { setTimeout(connect,3000); return; }
    ws.addEventListener('message',e=>{try{const msg=JSON.parse(e.data);if(msg.type==='state') render(msg.state);}catch(_){}});
    ws.addEventListener('close',()=>setTimeout(connect,3000));
  }
  if(!sample) connect();
})();
