(() => {
  const timer = document.getElementById('timer');
  const minutes = Number(new URLSearchParams(location.search).get('minutes'));
  if (!timer || !Number.isFinite(minutes) || minutes <= 0 || minutes > 240) return;
  let left = Math.round(minutes * 60);
  timer.classList.add('active');
  const draw = () => {
    if (timer.dataset.remote) return;  // the control panel's countdown (show-client.js) has taken over
    timer.textContent = String(Math.floor(left / 60)).padStart(2, '0') + ':' + String(left % 60).padStart(2, '0');
    if (left > 0) left -= 1;
  };
  draw();
  setInterval(draw, 1000);
})();
