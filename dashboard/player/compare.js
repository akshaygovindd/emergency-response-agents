// Compare page: two embedded players (same scenario and seed, different systems) driven by one clock.
// All numbers are drawn by the players from Python's bundles; this file only keeps the shared minute.
(() => {
  "use strict";
  const D = JSON.parse(document.getElementById("data").textContent);
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const N = Math.max(D.a.last, D.b.last), MAX_FRAME_MS = 500;
  const frames = [$("frameA"), $("frameB")], sides = [D.a, D.b];
  let loaded = 0, tau = 0, playing = false, speed = 1, last = null;

  $("labelA").innerHTML = `${esc(D.a.label)}<span>left</span>`;
  $("labelB").innerHTML = `${esc(D.b.label)}<span>right</span>`;
  $("last").textContent = String(N);
  const scrub = $("scrub"), playBtn = $("play");
  scrub.max = N;

  frames.forEach((f, i) => {
    f.addEventListener("load", () => { loaded += 1; if (loaded === 2) render(tau); });
    f.srcdoc = sides[i].html;
  });

  function render(t) {
    frames.forEach((f, i) => {
      const p = f.contentWindow && f.contentWindow.__player;
      if (p) p.render(Math.min(t, sides[i].last));
    });
    $("min").textContent = String(Math.min(N, Math.floor(t)));
    scrub.value = t;
  }
  function setPlaying(on) {
    playing = on; last = null;
    playBtn.innerHTML = on ? "&#10074;&#10074; Pause" : (tau >= N ? "&#8634; Replay" : "&#9654; Play");
  }
  function jump(t) { tau = clamp(t, 0, N); render(tau); setPlaying(false); }

  function loop(now) {
    if (playing) {
      if (last !== null) tau += (Math.min(now - last, MAX_FRAME_MS) / 1000) * speed;
      last = now;
      if (tau >= N) { tau = N; render(tau); setPlaying(false); } else render(tau);
    }
    requestAnimationFrame(loop);
  }
  playBtn.addEventListener("click", () => { if (!playing && tau >= N) tau = 0; setPlaying(!playing); playBtn.blur(); });
  $("restart").addEventListener("click", () => { tau = 0; render(tau); setPlaying(true); $("restart").blur(); });
  scrub.addEventListener("input", () => { tau = parseFloat(scrub.value); render(tau); setPlaying(false); });
  document.querySelectorAll("#speeds button").forEach((b) => b.addEventListener("click", () => {
    speed = parseFloat(b.dataset.speed);
    document.querySelectorAll("#speeds button").forEach((o) => o.classList.toggle("on", o === b));
    b.blur();
  }));
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space") { e.preventDefault(); playBtn.click(); }
    else if (e.code === "ArrowRight") jump(Math.floor(tau) + 1);
    else if (e.code === "ArrowLeft") jump(Math.ceil(tau) - 1);
  });

  // Markers above the scrubber: conflicts of either run (small red) and the first difference (yellow).
  const mark = (t, cls, title) => {
    const i = document.createElement("i");
    i.style.left = `${(t / N) * 100}%`; i.className = cls; i.title = title;
    i.addEventListener("click", () => jump(t));
    $("cmarks").appendChild(i);
  };
  sides.forEach((s) => s.conflicts.forEach((c) => mark(c.t, "small", `${s.label}, minute ${c.t}: ${c.text}`)));
  if (D.diff) mark(D.diff.t, "diff", `First difference, minute ${D.diff.t}`);
  $("jumpdiff").disabled = !D.diff;
  $("jumpdiff").addEventListener("click", () => { if (D.diff) jump(D.diff.t); $("jumpdiff").blur(); });
  $("diffnote").className = D.diff ? "" : "none";
  $("diffnote").innerHTML = D.diff ? `<b>FIRST DIFFERENCE</b>${esc(D.diff.text.replace(/^First difference at /, "At "))}`
    : "These two systems made exactly the same decisions in this run.";

  render(0); setPlaying(false);
  requestAnimationFrame(loop);
  window.__compare = { jump, render, state: () => ({ tau, playing, speed }), frames };
})();
