/**
 * Kaptan Qedy — deniz/gemi canvas katmanı
 * Start/break/end sahnelerinin alt kısmında: dalgalar üzerinde süzülen
 * galeon, korvet ve sloop. Gemiler dalganın yerel eğimine göre yatar,
 * böylece gerçekten suyun üzerinde gibi görünürler (statik bir "bob"
 * animasyonu değil).
 */
(() => {
  'use strict';
  const scene = document.querySelector('.scene:not(.chat-scene)');
  if (!scene) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  const canvas = document.createElement('canvas');
  canvas.className = 'sea-canvas';
  canvas.setAttribute('aria-hidden', 'true');
  scene.appendChild(canvas);
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  function accentRGB() {
    const v = getComputedStyle(scene).getPropertyValue('--motion-accent').trim() || '#22aef0';
    const hex = v.replace('#', '');
    const n = parseInt(hex.length === 3 ? hex.split('').map(c => c + c).join('') : hex, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(',');
  }
  const rgb = accentRGB();

  let W = 0, H = 0, t = 0;
  const foam = [];

  function resize() {
    const r = canvas.getBoundingClientRect();
    W = canvas.width = Math.max(1, Math.round(r.width));
    H = canvas.height = Math.max(1, Math.round(r.height));
  }

  const waves = [
    { yR: .40, amp: .10, freq: .012, phase: 0.0, spd: .017, a: .22 },
    { yR: .58, amp: .075, freq: .016, phase: 2.1, spd: .013, a: .16 },
    { yR: .76, amp: .055, freq: .010, phase: 4.2, spd: .010, a: .11 },
  ];

  function wy(w, x) {
    return w.yR * H
      + Math.sin(x * w.freq + t * w.spd + w.phase) * w.amp * H
      + Math.sin(x * w.freq * 2.4 + t * w.spd * 1.6 + w.phase) * w.amp * H * .3;
  }

  function spawnFoam(x, y) {
    if (foam.length > 70 || Math.random() > .05) return;
    foam.push({
      x, y,
      vx: (Math.random() - .5) * .8,
      vy: -Math.random() * 1.1 - .3,
      r: Math.random() * 1.5 + .5,
      a: .55 + Math.random() * .25,
      decay: .018 + Math.random() * .018
    });
  }

  const fleet = window.qedyFleet ? window.qedyFleet(ctx) : null;  // ../docs/assets/ships.js

  function draw() {
    ctx.clearRect(0, 0, W, H);

    waves.forEach(w => {
      ctx.beginPath();
      ctx.moveTo(0, wy(w, 0));
      for (let x = 0; x <= W; x += 4) ctx.lineTo(x, wy(w, x));
      ctx.lineTo(W, H); ctx.lineTo(0, H);
      ctx.closePath();
      ctx.fillStyle = `rgba(${rgb},${w.a})`;
      ctx.fill();

      ctx.beginPath();
      for (let x = 0; x <= W; x += 4) {
        const y = wy(w, x);
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        if (x % 8 === 0) {
          const slope = Math.abs(wy(w, x + 6) - wy(w, x - 6));
          if (slope > 1.5) spawnFoam(x, y);
        }
      }
      ctx.strokeStyle = `rgba(${rgb},.32)`;
      ctx.lineWidth = 1.1;
      ctx.stroke();
    });

    for (let i = foam.length - 1; i >= 0; i--) {
      const p = foam[i];
      p.x += p.vx; p.y += p.vy; p.vy += .03; p.a -= p.decay;
      if (p.a <= 0) { foam.splice(i, 1); continue; }
      ctx.globalAlpha = Math.max(0, p.a);
      ctx.fillStyle = '#fff';
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;

    if (fleet) fleet.draw({ W, H, back: x => wy(waves[0], x), front: x => wy(waves[waves.length - 1], x) });

    t++;
    if (!reduced) requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener('resize', resize, { passive: true });
  draw();
})();
