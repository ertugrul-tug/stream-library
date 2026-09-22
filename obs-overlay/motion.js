(() => {
  'use strict';
  const scene = document.querySelector('.scene:not(.chat-scene)');
  if (!scene || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const canvas = document.createElement('canvas');
  canvas.className = 'atmosphere';
  canvas.setAttribute('aria-hidden', 'true');
  scene.insertBefore(canvas, scene.firstChild);
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;
  const accent = scene.classList.contains('break') ? [255,61,127] : scene.classList.contains('end') ? [83,252,24] : [34,174,240];
  const particles = Array.from({length:46}, () => ({
    x:Math.random(), y:Math.random(), radius:.5+Math.random()*1.4,
    speed:.000025+Math.random()*.00006, drift:(Math.random()-.5)*.000025,
    alpha:.1+Math.random()*.24, phase:Math.random()*Math.PI*2
  }));
  let width=0, height=0, frame=0, previous=0;
  const resize = () => {
    width=Math.max(1,Math.round(window.innerWidth));
    height=Math.max(1,Math.round(window.innerHeight));
    canvas.width=width; canvas.height=height;
  };
  resize();
  window.addEventListener('resize',resize,{passive:true});
  function tick(time) {
    frame=requestAnimationFrame(tick);
    if (document.hidden || time-previous<25) return;
    const delta=Math.min(60,time-previous || 25); previous=time;
    ctx.clearRect(0,0,width,height);
    for (const p of particles) {
      p.y-=p.speed*delta; p.x+=p.drift*delta;
      if(p.y<-.03){p.y=1.03;p.x=Math.random()}
      if(p.x<-.03)p.x=1.03; if(p.x>1.03)p.x=-.03;
      const x=p.x*width,y=p.y*height,r=p.radius*(width/1920);
      const a=p.alpha*(.7+.3*Math.sin(time*.0015+p.phase));
      ctx.fillStyle='rgba('+accent[0]+','+accent[1]+','+accent[2]+','+a+')';
      ctx.fillRect(x,y,Math.max(1,r),Math.max(2,r*3));
    }
  }
  frame=requestAnimationFrame(tick);
  window.addEventListener('pagehide',()=>cancelAnimationFrame(frame),{once:true});
})();
