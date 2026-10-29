// What-if page: steppers and segmented controls choose a scenario; Run reloads the page with those numbers in its address,
// Python builds the scenario in memory, runs naive and greedy, and this file shows the two results and the replay.
(() => {
  "use strict";
  const { $, esc, ico } = UI;
  const D = JSON.parse($("data").textContent);
  const P = D.params, LIM = D.limits;
  const state = { ...P };
  UI.mountRail("What-if"); UI.mountTooltips();

  function stepper(key, label, hint, lo, hi, step) {
    return `<div class="field"><label>${label}<small>${hint}</small></label><div class="stepper" data-k="${key}"><button data-d="-1" aria-label="less"${state[key] <= lo ? " disabled" : ""}>${ico("minus", 16)}</button><b>${state[key]}</b><button data-d="1" aria-label="more"${state[key] >= hi ? " disabled" : ""}>${ico("plus", 16)}</button></div></div>`;
  }
  const dirty = () => Object.keys(P).some((k) => P[k] !== state[k]);
  function drawControls() {
    const prof = Object.entries(D.profiles).map(([k, t]) => `<b data-v="${k}"${k === state.profile ? ' class="on"' : ""}>${esc(t)}</b>`).join("");
    $("controls").innerHTML = `<h2>Scenario</h2>` +
      `<div class="field"><label>Base profile<small>severity mix and arrival window</small></label><div class="seg" id="profile">${prof}</div></div>` +
      stepper("amb", "Ambulances", `${LIM.amb[0]} to ${LIM.amb[1]} available`, LIM.amb[0], LIM.amb[1]) +
      stepper("inc", "Incidents", `${LIM.inc[0]} to ${LIM.inc[1]} in total`, LIM.inc[0], LIM.inc[1]) +
      stepper("seed", "Seed", "same seed, same emergency", 0, 9999) +
      `<div class="runrow"><button class="runbtn${dirty() ? "" : " clean"}" id="run">${ico("flask-conical", 18)} Run</button><span class="hint">${dirty() ? "Settings changed. Press Run." : "Showing these settings."}</span></div>` +
      `<div><div class="systems">${["naive", "greedy"].map((m) => `<span class="sys live"><i></i>${UI.SYSTEM_LABEL[m]}</span>`).join("")}` +
      `${["agents", "negotiation", "oracle"].map((m) => `<span class="sys off" data-tip="${UI.SYSTEM_LABEL[m]}|Agent runs take minutes and use API calls. See the saved runs.">${ico("x", 12)}${UI.SYSTEM_LABEL[m]}</span>`).join("")}</div>` +
      `<p class="note" style="margin:8px 0 0">Agent runs take minutes and use API calls; see the saved runs on Replay, Compare and Results.</p></div>`;
  }
  $("controls").addEventListener("click", (e) => {
    const b = e.target.closest(".stepper button");
    if (b && !b.disabled) {
      const k = b.parentElement.dataset.k, [lo, hi] = k === "seed" ? [0, 9999] : LIM[k];
      state[k] = UI.clamp(state[k] + (+b.dataset.d), lo, hi); drawControls(); return;
    }
    const seg = e.target.closest("#profile b");
    if (seg) { state.profile = seg.dataset.v; drawControls(); return; }
    if (e.target.closest("#run") && dirty()) UI.goto("whatif", `amb=${state.amb}&inc=${state.inc}&seed=${state.seed}&p=${state.profile}`);
  });
  document.addEventListener("keydown", (e) => { if (e.code === "Enter" && dirty() && !e.target.closest("button")) $("run").click(); });

  const pct = (v) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(0)}%`);
  function drawResults() {
    const R = D.results, delta = D.delta;
    $("results").innerHTML = ["naive", "greedy"].map((m) => {
      const r = R[m].summary, best = m === "greedy" && delta !== null && delta > 0;
      return `<div class="card rcard ${m}${best ? " best" : ""}"><div class="sysname">${ico(m === "naive" ? "ambulance" : "sliders-horizontal", 16)} ${UI.SYSTEM_LABEL[m]}` +
        `${m === "greedy" && delta !== null ? `<span class="delta${delta < 0 ? " neg" : ""}">${delta >= 0 ? "+" : ""}${delta} pts vs naive</span>` : ""}</div>` +
        `<div class="big">${pct(r.csr)}<small>critical patients in time</small></div><div class="bar"><i style="width:${(r.csr || 0) * 100}%"></i></div><div class="note">${esc(r.served_note)}</div>` +
        `<div class="mini"><div><b>${pct(r.reached)}</b>patients reached</div><div><b>${r.response === null ? "n/a" : r.response.toFixed(1)}</b>avg minutes to contact</div><div><b>${r.never_reached}</b>critical never reached</div></div></div>`;
    }).join("");
  }
  // Replay below, in the same player; the segmented control switches system
  let system = "greedy";
  const setSystem = () => { $("player").srcdoc = D.results[system].html; $("rcsub").textContent = `${D.profiles[P.profile]} profile · ${P.amb} ambulances · ${P.inc} incidents · seed ${P.seed}`; };
  $("sysseg").innerHTML = ["naive", "greedy"].map((m) => `<b data-v="${m}"${m === system ? ' class="on"' : ""}>${UI.SYSTEM_LABEL[m]}</b>`).join("");
  UI.segmented($("sysseg"), (v) => { system = v; setSystem(); });

  const startAt = /[#&]m=(\d+)/.exec(window.location.hash);          // page.html#m=40 opens the replay at minute 40 (handy for screenshots)
  if (startAt) $("player").addEventListener("load", () => $("player").contentWindow.__app.jump(parseInt(startAt[1], 10)));
  drawControls(); drawResults(); setSystem();
  window.__page = { state, setSystem: (m) => { system = m; setSystem(); } };
})();
