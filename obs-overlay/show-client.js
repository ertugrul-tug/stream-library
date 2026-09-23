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
  function tally(matches) {
    const m = matches || [], last = m[m.length-1];
    let streak = 0;
    for (let i = m.length-1; i >= 0 && m[i] === last; i--) streak++;
    return { m, wins: m.filter(x=>x==='W').length, losses: m.filter(x=>x==='L').length, last, streak };
  }
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
  function render(s) {
    if (crew) {
      crew.querySelectorAll('.crew-list,.show-small').forEach(n=>n.remove());
      const list=div(crew,'crew-list','');
      (s.crew || []).slice(-8).reverse().forEach(p=>{const n=div(list,'crew-person '+p.platform,p.name);});
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
      [['TWITCH MESAJ',t.chat],['KICK MESAJ',k.chat],['YENİ TAKİP',(t.follow||0)+(k.follow||0)],['ABONELİK',(t.sub||0)+(k.sub||0)]].forEach(([label,value])=>{
        const n=div(grid,'stat',''); const strong=document.createElement('strong'); strong.textContent='0'; n.append(strong); div(n,'',label); countUp(strong,value);
      });
      div(end,'show-small','SEYİR DEFTERİNDEN');
      (s.highlights || []).slice(-3).forEach(x=>div(end,'highlight','✦ '+x));
      if (!(s.highlights || []).length) div(end,'highlight','Öne çıkan anlar burada görünecek.');
    }
    if (spotlight) {
      spotlight.classList.toggle('active',!!s.spotlight);
      if(s.spotlight) {
        spotlight.dataset.platform=s.spotlight.platform;
        spotlight.querySelectorAll('.show-text,.show-author').forEach(n=>n.remove());
        div(spotlight,'show-text',s.spotlight.text);
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
  const demo={game:'Sisli Vadi',returnMessage:'5 dakika sonra tekrar güvertedeyiz',routes:['Ana göreve devam','Yan görev keşfi','Haritayı aç'],crew:[{platform:'twitch',name:'MaviKaptan'},{platform:'kick',name:'YesilLiman'},{platform:'twitch',name:'Denizci42'}],highlights:['İlk büyük zafer','Gizli liman bulundu'],spotlight:{platform:'twitch',name:'MaviKaptan',text:'Bu akşam rota nereye dönüyor kaptan?'},voteCounts:[8,5,3],matches:['L','W','L','W','W','W'],stats:{twitch:{chat:143,follow:6,sub:2},kick:{chat:97,follow:4,sub:1}}};
  if(sample) render(demo); else render({routes:[],crew:[],stats:{}});
  function connect() {
    let ws;
    try { ws=new WebSocket('ws://127.0.0.1:8765/'); } catch(_) { setTimeout(connect,3000); return; }
    ws.addEventListener('message',e=>{try{const msg=JSON.parse(e.data);if(msg.type==='state') render(msg.state);}catch(_){}});
    ws.addEventListener('close',()=>setTimeout(connect,3000));
  }
  if(!sample) connect();
})();
