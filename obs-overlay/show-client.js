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
  let segment = null, lastSchedule = {}, segmentOn = true;
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
  function render(s) {
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
      div(end,'show-small','SEYİR DEFTERİNDEN');
      (s.highlights || []).slice(-3).forEach(x=>div(end,'highlight','✦ '+x));
      if (!(s.highlights || []).length) div(end,'highlight','Öne çıkan anlar burada görünecek.');
    }
    if (spotlight) {
      spotlight.classList.toggle('active',!!s.spotlight);
      if(s.spotlight) {
        spotlight.dataset.platform=s.spotlight.platform;
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
    if(segment) { lastSchedule=s.schedule||{}; segmentOn=s.segmentVisible!==false; renderSegment(); }
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
  const demo={game:'Sisli Vadi',returnMessage:'5 dakika sonra tekrar güvertedeyiz',routes:['Ana göreve devam','Yan görev keşfi','Haritayı aç'],crew:[{platform:'twitch',name:'MaviKaptan',rank:'Lostromo'},{platform:'kick',name:'YesilLiman',rank:'Tayfa'},{platform:'twitch',name:'Denizci42',rank:'Miço'}],schedule:{'Açılış sohbet':'20:30','Tema bloğu':'21:00','Günlük sohbet':'23:00','Kapanış':'23:30'},rankUp:{platform:'twitch',name:'MaviKaptan',rank:'Lostromo',at:Date.now()},highlights:['İlk büyük zafer','Gizli liman bulundu'],spotlight:{platform:'twitch',name:'MaviKaptan',text:'Bu akşam rota nereye dönüyor kaptan?'},voteCounts:[8,5,3],matches:['L','W','L','W','W','W'],prediction:{status:'open',w:14,l:6},predictionHistory:[{right:9,total:12},{right:5,total:10}],stats:{twitch:{chat:143,follow:6,sub:2},kick:{chat:97,follow:4,sub:1}}};
  if(sample) render(demo); else render({routes:[],crew:[],stats:{}});
  function connect() {
    let ws;
    try { ws=new WebSocket('ws://127.0.0.1:8765/'); } catch(_) { setTimeout(connect,3000); return; }
    ws.addEventListener('message',e=>{try{const msg=JSON.parse(e.data);if(msg.type==='state') render(msg.state);}catch(_){}});
    ws.addEventListener('close',()=>setTimeout(connect,3000));
  }
  if(!sample) connect();
})();
