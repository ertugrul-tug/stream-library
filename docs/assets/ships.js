/* Modern sailboats riding the waves: classic yacht, striped spinnaker yacht, catamaran, dinghy.
   Shared by the site's sea band (docs/index.html) and the OBS scenes (obs-overlay/sea.js).
   Every boat gets random colours, size, speed and heading, and is re-rolled each time it leaves
   the screen, so the sea never repeats. Flat shapes with straight-edged sails read at small sizes.
   Usage: const fleet = qedyFleet(ctx); each frame after drawing waves:
          fleet.draw({W, H, back: x => y, front: x => y})   // y of the wave surface at x */
(function () {
  'use strict';
  const rnd = Math.random, pick = a => a[Math.floor(rnd() * a.length)];
  const ACCENTS = ['34,174,240', '255,61,127', '255,176,59', '92,240,160', '255,94,77', '167,139,250', '250,204,21'];
  const SAILS = ['#fbfcfd', '#fbfcfd', '#f6efdf', '#eef3f7'];
  const STRIPES = ['#1f3a5c', '#0f2a44', '#8b1e2d', '#1d4d3a'];

  function style() {
    const a = pick(ACCENTS);
    let b = pick(ACCENTS);
    if (b === a) b = pick(ACCENTS);
    return { a, b, sail: pick(SAILS), stripe: rnd() < 0.5 ? pick(STRIPES) : `rgb(${a})` };
  }

  // Waterline at y=0, bow toward +x. Big boats ~66 units long and ~70 tall; the dinghy about half.
  function hull(ctx, c) {
    ctx.fillStyle = '#f3f6f9';
    ctx.beginPath();
    ctx.moveTo(-30, -9); ctx.lineTo(24, -9); ctx.lineTo(34, -7); ctx.lineTo(26, 0); ctx.lineTo(-26, 0); ctx.lineTo(-31, -4);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = c.stripe;
    ctx.beginPath(); ctx.moveTo(-30, -4.5); ctx.lineTo(30, -4.5); ctx.lineTo(26, -1.2); ctx.lineTo(-27, -1.2); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#e3e9ef'; ctx.fillRect(-16, -13, 20, 4);
    ctx.fillStyle = '#24344a'; ctx.fillRect(-13, -12, 14, 1.6);
  }
  function mast(ctx, x, bottom, top) {
    ctx.strokeStyle = '#8fa0b0'; ctx.lineWidth = 1.1;
    ctx.beginPath(); ctx.moveTo(x, bottom); ctx.lineTo(x, top); ctx.stroke();
  }

  function yacht(ctx, c) {
    mast(ctx, -2, -9, -66);
    ctx.fillStyle = c.sail;
    ctx.beginPath(); ctx.moveTo(-1, -64); ctx.lineTo(-1, -12); ctx.lineTo(-27, -12); ctx.closePath(); ctx.fill();
    ctx.fillStyle = 'rgba(160,178,196,.45)';
    ctx.beginPath(); ctx.moveTo(-1, -64); ctx.lineTo(-1, -12); ctx.lineTo(-7, -12); ctx.closePath(); ctx.fill();
    ctx.fillStyle = `rgb(${c.a})`; ctx.fillRect(-14, -24, 8, 3);
    ctx.fillStyle = '#e9eef3';
    ctx.beginPath(); ctx.moveTo(0, -58); ctx.lineTo(29, -9); ctx.lineTo(1, -11); ctx.closePath(); ctx.fill();
    ctx.strokeStyle = 'rgba(143,160,176,.8)'; ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.moveTo(-2, -66); ctx.lineTo(31, -8); ctx.stroke();
    hull(ctx, c);
    ctx.fillStyle = `rgb(${c.b})`;
    ctx.beginPath(); ctx.moveTo(-2, -66); ctx.lineTo(-11, -63.5); ctx.lineTo(-2, -61); ctx.closePath(); ctx.fill();
  }

  function spinnaker(ctx, c) {
    mast(ctx, -4, -9, -58);
    ctx.fillStyle = c.sail;
    ctx.beginPath(); ctx.moveTo(-3, -56); ctx.lineTo(-3, -12); ctx.lineTo(-25, -12); ctx.closePath(); ctx.fill();
    ctx.save();
    ctx.beginPath(); ctx.moveTo(-2, -57); ctx.quadraticCurveTo(52, -52, 34, -12); ctx.lineTo(4, -12); ctx.quadraticCurveTo(14, -34, -2, -57);
    ctx.closePath(); ctx.clip();
    [c.a, '255,255,255', c.b, '255,255,255', c.a].forEach((col, i) => { ctx.fillStyle = `rgb(${col})`; ctx.fillRect(-10, -60 + i * 10, 70, 10); });
    ctx.restore();
    ctx.strokeStyle = 'rgba(143,160,176,.7)'; ctx.lineWidth = 0.5;
    ctx.beginPath(); ctx.moveTo(34, -12); ctx.lineTo(30, -8); ctx.stroke();
    hull(ctx, c);
  }

  function catamaran(ctx, c) {
    mast(ctx, 0, -11, -70);
    ctx.fillStyle = c.sail;
    ctx.beginPath(); ctx.moveTo(1, -68); ctx.quadraticCurveTo(-18, -40, -28, -15); ctx.lineTo(1, -15); ctx.closePath(); ctx.fill();
    ctx.fillStyle = `rgb(${c.a})`;
    ctx.beginPath(); ctx.moveTo(1, -68); ctx.quadraticCurveTo(-4, -58, -7, -50); ctx.lineTo(1, -50); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#e9eef3';
    ctx.beginPath(); ctx.moveTo(2, -60); ctx.lineTo(24, -15); ctx.lineTo(2, -15); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#dfe6ec'; ctx.fillRect(-24, -15, 50, 4);
    ctx.fillStyle = '#f3f6f9';
    ctx.beginPath(); ctx.moveTo(-32, -11); ctx.lineTo(28, -11); ctx.lineTo(36, -8); ctx.lineTo(28, 0); ctx.lineTo(-29, 0); ctx.closePath(); ctx.fill();
    ctx.fillStyle = `rgb(${c.b})`; ctx.fillRect(-29, -4, 57, 2.2);
    ctx.fillStyle = '#24344a'; ctx.fillRect(-12, -9.5, 16, 1.8);
  }

  function dinghy(ctx, c) {                                   // small, quick, one bright sail
    mast(ctx, -1, -5, -40);
    ctx.fillStyle = `rgb(${c.a})`;
    ctx.beginPath(); ctx.moveTo(0, -39); ctx.lineTo(0, -7); ctx.lineTo(-17, -7); ctx.closePath(); ctx.fill();
    ctx.fillStyle = 'rgba(255,255,255,.35)';
    ctx.beginPath(); ctx.moveTo(0, -39); ctx.lineTo(0, -7); ctx.lineTo(-4, -7); ctx.closePath(); ctx.fill();
    ctx.fillStyle = '#f3f6f9';
    ctx.beginPath(); ctx.moveTo(-16, -5); ctx.lineTo(15, -5); ctx.lineTo(19, -3); ctx.lineTo(13, 0); ctx.lineTo(-14, 0); ctx.closePath(); ctx.fill();
    ctx.fillStyle = `rgb(${c.b})`; ctx.fillRect(-15, -2.6, 30, 1.6);
  }

  const TYPES = {
    front: [[spinnaker, 0.35], [catamaran, 0.25], [yacht, 0.25], [dinghy, 0.15]],
    back: [[yacht, 0.4], [dinghy, 0.25], [catamaran, 0.2], [spinnaker, 0.15]],
  };
  const SPEED = new Map([[yacht, 0.00008], [spinnaker, 0.00011], [catamaran, 0.0001], [dinghy, 0.00015]]);

  function roll(layer, x) {
    let r = rnd(), draw = TYPES[layer][0][0];
    for (const [fn, w] of TYPES[layer]) { if ((r -= w) < 0) { draw = fn; break; } }
    const dir = rnd() < 0.5 ? 1 : -1;
    return { draw, c: style(), dir, size: 0.8 + rnd() * 0.4, spd: SPEED.get(draw) * (0.7 + rnd() * 0.6),
             x: x !== undefined ? x : (dir > 0 ? -0.2 : 1.2) };
  }

  window.qedyFleet = function (ctx) {
    const spread = (n, layer) => Array.from({ length: n }, (_, i) => roll(layer, (i + rnd() * 0.8) / n));
    const front = spread(3, 'front'), back = spread(4, 'back');

    function sail(boats, count, layer, ride, s, W) {
      boats.slice(0, count).forEach((b, i) => {
        b.x += b.spd * b.dir;
        if (b.x > 1.2 || b.x < -0.2) { b = boats[i] = roll(layer); }   // left the screen: a new boat sails in
        const k = s * b.size, x = b.x * W, y = ride(x), span = 8 * k;
        const angle = Math.atan((ride(x + span) - ride(x - span)) / (2 * span)) * 0.5;
        ctx.save(); ctx.translate(x, y); ctx.rotate(angle); ctx.scale(b.dir * k, k); b.draw(ctx, b.c); ctx.restore();
      });
    }

    return {
      draw({ W, H, back: rideBack, front: rideFront }) {
        const s = Math.max(0.55, Math.min(H / 170, W / 480));   // ~1 on the site band, ~2.3 on the OBS canvas
        const phone = W < 700;                                   // short band: fewer boats
        ctx.globalAlpha = 0.8;                                   // back layer: smaller + fainter = farther away
        sail(back, phone ? 3 : back.length, 'back', rideBack, s * 0.68, W);
        ctx.globalAlpha = 1;
        sail(front, phone ? 2 : front.length, 'front', rideFront, s, W);
      },
    };
  };
})();
