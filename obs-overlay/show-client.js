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
  }
  const demo={game:'Sisli Vadi',returnMessage:'5 dakika sonra tekrar güvertedeyiz',routes:['Ana göreve devam','Yan görev keşfi','Haritayı aç'],crew:[{platform:'twitch',name:'MaviKaptan'},{platform:'kick',name:'YesilLiman'},{platform:'twitch',name:'Denizci42'}],highlights:['İlk büyük zafer','Gizli liman bulundu'],spotlight:{platform:'twitch',name:'MaviKaptan',text:'Bu akşam rota nereye dönüyor kaptan?'},voteCounts:[8,5,3],stats:{twitch:{chat:143,follow:6,sub:2},kick:{chat:97,follow:4,sub:1}}};
  if(sample) render(demo); else render({routes:[],crew:[],stats:{}});
  function connect() {
    let ws;
    try { ws=new WebSocket('ws://127.0.0.1:8765/'); } catch(_) { setTimeout(connect,3000); return; }
    ws.addEventListener('message',e=>{try{const msg=JSON.parse(e.data);if(msg.type==='state') render(msg.state);}catch(_){}});
    ws.addEventListener('close',()=>setTimeout(connect,3000));
  }
  if(!sample) connect();
})();
