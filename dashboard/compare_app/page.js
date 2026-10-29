// Compare page: two embedded Replay apps (same scenario and seed, different systems) driven by one clock.
// Python built both runs and the "first difference" card; this file only keeps the shared minute.
(() => {
  "use strict";
  const { $, esc, clamp, ico } = UI;
  const D = JSON.parse($("data").textContent);
  const N = Math.max(D.left.last, D.right.last), MAX_FRAME_MS = 500;
  const frames = [$("frameA"), $("frameB")], sides = [D.left, D.right];
  let loaded = 0, tau = 0, playing = false, speed = 1, last = null;

  UI.mountRail("Compare"); UI.mountTooltips();
  $("runpill").innerHTML = UI.pillHtml([UI.SCENARIO_LABEL[D.sel.s] || D.sel.s, `Run ${D.sel.r}`, `${UI.SYSTEM_LABEL[D.sel.m1]} vs ${UI.SYSTEM_LABEL[D.sel.m2]}`, D.sel.v]);
  UI.runPicker({ pill: $("runpill"), pop: $("runpop"), catalog: D.catalog, sel: { ...D.sel }, page: "compare",
    fields: [["v", "Version"], ["s", "Scenario"], ["r", "Run"], ["m1", "Left system"], ["m2", "Right system"]],
    label: (s) => `${UI.SCENARIO_LABEL[s.s] || s.s} · run ${s.r} · ${UI.SYSTEM_LABEL[s.m1]} vs ${UI.SYSTEM_LABEL[s.m2]} · ${s.v}` });

  // First difference card
  const diff = D.diff;
  if (diff) {
    $("diff").innerHTML = `<span class="tile" style="--tone:var(--accent)">${ico("flag", 18)}</span><div class="body"><h3>First difference · minute ${diff.t}</h3>` +
      `<div class="what"><b>${esc(D.left.label)}</b>${esc(diff.left.join("; ") || "made no different decision")}</div>` +
      `<div class="what"><b>${esc(D.right.label)}</b>${esc(diff.right.join("; ") || "made no different decision")}</div></div>` +
      `<button class="ghost small" id="jumpdiff">${ico("flag", 16)} Jump to minute ${diff.t}</button>`;
  } else {
    $("diff").className = "card diff none";
    $("diff").innerHTML = `<span class="tile" style="--tone:var(--text-3)">${ico("info", 18)}</span><div class="body"><div class="what">These two systems made exactly the same decisions in this run.</div></div>`;
  }
  $("nameA").textContent = D.left.label; $("nameB").textContent = D.right.label;
  $("subA").textContent = D.left.sub; $("subB").textContent = D.right.sub;

  const scrub = $("scrub"), playBtn = $("play"), pauseBox = $("pausebox");
  scrub.max = N; $("last").textContent = String(N);
  frames.forEach((f, i) => {
    f.addEventListener("load", () => { loaded += 1; if (loaded === 2) render(tau); });
    f.srcdoc = sides[i].html;
  });
  function render(t) {
    frames.forEach((f, i) => {
      const app = f.contentWindow && f.contentWindow.__app;
      if (app) app.render(Math.min(t, sides[i].last));
    });
    $("min").textContent = String(Math.min(N, Math.floor(t)));
    scrub.value = t; scrub.style.setProperty("--p", (t / N) * 100 + "%");
  }
  function setPlaying(on) { playing = on; last = null; playBtn.innerHTML = ico(on ? "pause" : tau >= N ? "rotate-ccw" : "play", 20); }
  function jump(t) { tau = clamp(t, 0, N); render(tau); setPlaying(false); }
  const conflictTimes = [...new Set([...D.left.conflicts, ...D.right.conflicts].map((c) => c.t))].sort((a, b) => a - b);
  function loop(now) {
    if (playing) {
      const before = tau;
      if (last !== null) tau += (Math.min(now - last, MAX_FRAME_MS) / 1000) * speed;
      last = now;
      const hit = pauseBox.checked && conflictTimes.find((c) => c > before && c <= tau);
      if (hit !== undefined) { tau = hit; render(tau); setPlaying(false); }
      else if (tau >= N) { tau = N; render(tau); setPlaying(false); }
      else render(tau);
    }
    requestAnimationFrame(loop);
  }
  playBtn.addEventListener("click", () => { if (!playing && tau >= N) tau = 0; setPlaying(!playing); playBtn.blur(); });
  $("restart").innerHTML = ico("rotate-ccw", 16);
  $("restart").addEventListener("click", () => { tau = 0; render(tau); setPlaying(true); $("restart").blur(); });
  scrub.addEventListener("input", () => { tau = parseFloat(scrub.value); render(tau); setPlaying(false); });
  document.querySelectorAll("#speeds b").forEach((b) => b.addEventListener("click", () => {
    speed = parseFloat(b.dataset.speed);
    document.querySelectorAll("#speeds b").forEach((o) => o.classList.toggle("on", o === b));
  }));
  document.addEventListener("keydown", (e) => {
    if (e.target && (e.target.type === "checkbox" || e.target.tagName === "BUTTON" && e.code === "Space")) return;
    if (e.code === "Space") { e.preventDefault(); playBtn.click(); }
    else if (e.code === "ArrowRight") jump(Math.floor(tau) + 1);
    else if (e.code === "ArrowLeft") jump(Math.ceil(tau) - 1);
  });
  const mark = (t, cls, tip, icon) => {
    const i = document.createElement("i");
    i.className = "cm " + cls; i.style.left = `${(t / N) * 100}%`; i.innerHTML = ico(icon, 12); i.setAttribute("data-tip", tip);
    i.addEventListener("click", () => jump(t)); $("cmarks").appendChild(i);
  };
  sides.forEach((s, k) => s.conflicts.forEach((c) => mark(c.t, k ? "" : "", `${s.label} · conflict at minute ${c.t}|${c.plain}`, "triangle-alert")));
  if (diff) { mark(diff.t, "diffmark", `First difference at minute ${diff.t}`, "flag"); $("jumpdiff").addEventListener("click", () => jump(diff.t)); }
  [...new Set(D.ticks)].forEach((t) => { const i = document.createElement("i"); i.style.left = `${(t / N) * 100}%`; $("ticks").appendChild(i); });

  const startAt = /[#&]m=(\d+)/.exec(window.location.hash);          // page.html#m=6 opens at minute 6 (handy for screenshots)
  if (startAt) tau = clamp(parseInt(startAt[1], 10), 0, N);
  setPlaying(false);
  requestAnimationFrame(loop);
  window.__compare = { jump, render, state: () => ({ tau, playing, speed }), frames };
})();
