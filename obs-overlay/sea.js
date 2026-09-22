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

  const ships = [
    { type: 'galleon', x: -.2, spd: .000075, dir: 1, wave: 0, scale: 1.15, yOff: -.05 },
    { type: 'corvette', x: 1.15, spd: .00012, dir: -1, wave: 1, scale: .85, yOff: -.01 },
    { type: 'sloop', x: -.35, spd: .00018, dir: 1, wave: 2, scale: .62, yOff: .015 },
  ];

  const RIG = {
    galleon: { masts: [-13, 2, 17], heights: [23, 29, 23], main: 1 },
    corvette: { masts: [-8, 11], heights: [25, 20], main: 0 },
    sloop: { masts: [3], heights: [24], main: 0 },
  };

  // Solid, distinct colors per part (hull / trim / cabin / window / sail) read far more
  // clearly at a glance than a single monochrome fill — same lesson as any flat-design
  // vehicle icon: contrast between parts, not glow, is what makes the shape legible.
  const PALETTE = {
    galleon: { hull: '58,36,24', trim: '184,138,86', cabin: '230,214,172', win: '108,188,232' },
    corvette: { hull: '34,46,64', trim: '132,156,182', cabin: '214,220,228', win: '108,188,232' },
    sloop: { hull: '64,50,36', trim: '150,118,84', cabin: null, win: null },
  };
  const RIGGING_DARK = 'rgba(28,19,13,.92)';

  function drawShip(ship, x, y, angle) {
    const rig = RIG[ship.type];
    const pal = PALETTE[ship.type];
    const glow = `rgba(${rgb},.85)`;
    ctx.save();
    ctx.translate(x, y);
    ctx.rotate(angle);
    ctx.scale(ship.dir * ship.scale * 1.5, ship.scale * 1.5);

    // hull: smooth belly (bottom half of an ellipse) + pointed bow, solid wood/steel color
    ctx.fillStyle = `rgba(${pal.hull},.97)`;
    ctx.beginPath();
    ctx.ellipse(0, 9, 30, 8, 0, 0, Math.PI, false);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(-29, 9); ctx.lineTo(-38, 3); ctx.lineTo(-25, 6);
    ctx.closePath();
    ctx.fill();

    // waterline trim stripe
    ctx.fillStyle = `rgba(${pal.trim},.92)`;
    ctx.fillRect(-27, 7.4, 50, 1.8);

    // small cabin block with a window (galleon/corvette only)
    if (pal.cabin) {
      ctx.fillStyle = `rgba(${pal.cabin},.96)`;
      ctx.fillRect(16, 0, 11, 9);
      ctx.fillStyle = `rgba(${pal.win},.95)`;
      ctx.beginPath();
      ctx.arc(21.5, 4.2, 1.3, 0, Math.PI * 2);
      ctx.fill();
    }

    // thin brand-accent rim on the hull — the one place the scene color shows through
    ctx.strokeStyle = glow;
    ctx.lineWidth = .7;
    ctx.beginPath();
    ctx.ellipse(0, 9, 30, 8, 0, 0, Math.PI, false);
    ctx.stroke();

    // rigging: dark masts, cream sails, a bright flag on the main mast
    rig.masts.forEach((mx, i) => {
      const top = 6 - rig.heights[i];
      ctx.strokeStyle = RIGGING_DARK;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(mx, 6);
      ctx.lineTo(mx, top);
      ctx.stroke();

      const bulge = (i % 2 === 0 ? -1 : 1) * 11;
      ctx.fillStyle = `rgba(${pal.sail || '238,232,214'},.94)`;
      ctx.strokeStyle = 'rgba(28,19,13,.4)';
      ctx.lineWidth = .5;
      ctx.beginPath();
      ctx.moveTo(mx, top + 4);
      ctx.lineTo(mx, 5);
      ctx.quadraticCurveTo(mx + bulge, (top + 9) / 1.3, mx, top + 4);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      if (i === rig.main) {
        ctx.beginPath();
        ctx.moveTo(mx, top + 4);
        ctx.lineTo(mx, 5);
        ctx.quadraticCurveTo(mx - bulge, (top + 9) / 1.3, mx, top + 4);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.moveTo(mx, top);
        ctx.lineTo(mx + 7, top + 3);
        ctx.lineTo(mx, top + 5.5);
        ctx.closePath();
        ctx.fill();
      }
    });

    ctx.restore();
  }

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

    ships.forEach(s => {
      s.x += s.spd * s.dir;
      if (s.x > 1.3) s.x = -.3;
      if (s.x < -.3) s.x = 1.3;
      const w = waves[s.wave];
      const sx = s.x * W;
      const sy = wy(w, sx) + s.yOff * H;
      const slope = (wy(w, sx + 9) - wy(w, sx - 9)) / 18;
      const angle = Math.atan(slope) * .5;
      drawShip(s, sx, sy, angle);
    });

    t++;
    if (!reduced) requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener('resize', resize, { passive: true });
  draw();
})();
