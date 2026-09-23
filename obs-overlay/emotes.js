(() => {
  'use strict';
  // Streamer.bot sends emotes either as `parts` ([{type:'emote', text, imageUrl}, ...]),
  // as an `emotes` list next to plain text, or (Kick) inline as [emote:ID:name].
  const KICK = /\[emote:(\d+):([^\]\s]{1,64})\]/g;
  const https = u => { try { const x = new URL(String(u)); return x.protocol === 'https:' ? x.href : ''; } catch (_) { return ''; } };

  function fromText(text) {
    text = String(text ?? '');
    const out = []; let last = 0;
    for (const m of text.matchAll(KICK)) {
      if (m.index > last) out.push({ t: text.slice(last, m.index) });
      out.push({ e: m[2], u: `https://files.kick.com/emotes/${m[1]}/fullsize` });
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push({ t: text.slice(last) });
    return out;
  }

  function parse(data, fallbackText) {
    data = data || {};
    if (Array.isArray(data.parts) && data.parts.length) {
      return data.parts.flatMap(p => {
        const u = https(p?.imageUrl);
        return u && p.type !== 'text' ? [{ e: String(p.text || p.name || ''), u }] : fromText(p?.text);
      });
    }
    const names = new Map();
    (Array.isArray(data.emotes) ? data.emotes : []).forEach(e => { const u = https(e?.imageUrl); if (u && e.name) names.set(String(e.name), u); });
    const out = [];
    for (const seg of fromText(fallbackText ?? data.text ?? data.message)) {
      if (seg.u || !names.size) { out.push(seg); continue; }
      seg.t.split(/(\s+)/).forEach(tok => {
        if (names.has(tok)) out.push({ e: tok, u: names.get(tok) });
        else if (tok) out.push({ t: tok });
      });
    }
    return out;
  }

  function render(el, parts, limit = 300) {
    el.replaceChildren();
    let chars = 0, emotes = 0;
    for (const p of parts || []) {
      if (p.u && emotes < 40) {
        emotes++;
        const img = new Image();
        img.className = 'emote'; img.src = p.u; img.alt = p.e; img.title = p.e;
        img.referrerPolicy = 'no-referrer'; img.decoding = 'async';
        img.onerror = () => img.replaceWith(document.createTextNode(p.e));
        el.append(img);
      } else if (p.t && chars < limit) {
        const t = p.t.slice(0, limit - chars); chars += t.length;
        el.append(document.createTextNode(t));
      }
    }
  }

  const hasContent = parts => (parts || []).some(p => p.u || (p.t && p.t.trim()));
  window.qedyEmotes = Object.freeze({ parse, render, hasContent });
})();
