// Negotiations page: every conflict and hospital-admission negotiation of one saved run.
// Python built the records (negotiations.py); this file lists them, filters them and shows one in detail.
(() => {
  "use strict";
  const { $, esc, ico } = UI;
  const D = JSON.parse($("data").textContent);
  const R = D.records;
  const TONE = { conflict: "var(--warn)", proposal: "var(--accent-hover)", counter: "var(--warn)", accept: "var(--ok)", reject: "var(--danger)",
    escalate: "var(--violet)", resolved: "var(--violet)", fallback: "var(--violet)", commit: "var(--violet)", info: "var(--text-3)" };
  const FILTERS = [["all", "All"], ["conflict", "Conflicts"], ["admission", "Admissions"], ["notable", "Notable"]];
  const NOTABLE = new Set(R.filter((r) => r.notable).map((r) => r.id));
  let filter = "all", selected = null;

  UI.mountRail("Negotiations"); UI.mountTooltips();
  $("runpill").innerHTML = UI.pillHtml([UI.SCENARIO_LABEL[D.sel.s] || D.sel.s, `Run ${D.sel.r}`, UI.SYSTEM_LABEL[D.sel.m] || D.sel.m, D.sel.v]);
  UI.runPicker({ pill: $("runpill"), pop: $("runpop"), catalog: D.catalog, sel: { ...D.sel }, page: "negotiations",
    fields: [["v", "Version"], ["s", "Scenario"], ["r", "Run"], ["m", "System"]],
    label: (s) => `${UI.SCENARIO_LABEL[s.s] || s.s} · run ${s.r} · ${UI.SYSTEM_LABEL[s.m]} · ${s.v}` });

  $("filter").innerHTML = FILTERS.map(([v, t]) => `<b data-v="${v}"${v === "all" ? ' class="on"' : ""}>${t}</b>`).join("");
  UI.segmented($("filter"), (v) => { filter = v; drawList(); });

  const shown = () => R.filter((r) => filter === "all" || (filter === "notable" ? NOTABLE.has(r.id) : r.kind === filter));
  function outcomeTone(r) { return r.method === "fallback" ? "var(--danger)" : r.method === "accepted" || r.method === "negotiation" ? "var(--ok)" : "var(--violet)"; }

  function drawList() {
    const rows = shown();
    $("count").textContent = `${rows.length} of ${R.length}`;
    if (!rows.length) { $("list").innerHTML = `<div class="empty-state" style="padding:24px 0">Nothing matches this filter.</div>`; }
    else $("list").innerHTML = rows.map((r) => {
      const tone = r.kind === "conflict" ? "var(--warn)" : "var(--info)";
      return `<button class="nc${r.id === selected ? " sel" : ""}" data-id="${esc(r.id)}" data-tip="${esc(r.id + "|" + r.type)}"><div class="min"><b>${r.t}</b><span>minute</span></div><div>` +
        `<div class="top"><span class="badge" style="--tone:${tone}"><i></i>${esc(r.type)}</span><span class="badge" style="--tone:${outcomeTone(r)}">${esc(r.outcome)}</span></div>` +
        `<div class="what">${esc(r.incidents_plain.join(", "))}</div><div class="meta">${esc(r.units_plain.join(", "))} · ${r.steps.length} steps · ${r.rounds} round${r.rounds === 1 ? "" : "s"}</div></div></button>`;
    }).join("");
    if (rows.length && !rows.some((r) => r.id === selected)) { selected = rows[0].id; drawList(); return; }
    drawDetail(R.find((r) => r.id === selected));
  }
  $("list").addEventListener("click", (e) => {
    const b = e.target.closest(".nc");
    if (b) { selected = b.dataset.id; document.querySelectorAll(".nc").forEach((o) => o.classList.toggle("sel", o === b)); drawDetail(R.find((r) => r.id === selected)); }
  });

  // JSON with a little colour, for the raw-message panels
  const pretty = (obj) => esc(JSON.stringify(obj, null, 2)).replace(/(&quot;[^&]*?&quot;)(\s*:)?|(-?\d+\.?\d*)/g, (m, str, colon, num) =>
    num !== undefined ? `<span class="n">${num}</span>` : colon ? `<span class="k">${str}</span>${colon}` : `<span class="s">${str}</span>`);

  function drawDetail(r) {
    if (!r) { $("detail").innerHTML = `<div class="empty-state"><div class="tile" style="--tone:var(--text-3)">${ico("messages-square", 24)}</div><h3>No negotiations in this run</h3>` +
      `The ${esc(UI.SYSTEM_LABEL[D.sel.m] || D.sel.m)} system had no conflicts or hospital negotiations here. Pick another system in the run selector.</div>`; return; }
    const tone = r.kind === "conflict" ? "var(--warn)" : "var(--info)";
    const steps = r.steps.map((s, i) => `<div class="step" style="--tone:${TONE[s.key] || "var(--text-3)"}"><div class="node">${ico(s.key === "conflict" ? "triangle-alert" : s.key === "accept" || s.key === "resolved" ? "circle-check" : s.key === "reject" ? "x" : "messages-square", 16)}</div>` +
      `<div class="box"><div class="row"><span class="badge" style="--tone:${TONE[s.key] || "var(--text-3)"}"><i></i>${esc(s.label)}</span><span class="who">${esc(s.from)}${s.to ? " → " + esc(s.to) : ""}</span><span class="at" data-tip="Message|${esc(s.id)}">minute ${s.t} · ${esc(s.id)}</span></div>` +
      `<div class="say">${esc(s.plain || s.text)}</div>${s.why ? `<div class="why">${esc(s.why)}</div>` : ""}` +
      `<button class="rawbtn" data-i="${i}" aria-expanded="false">${ico("code", 14)} Raw message ${ico("chevron-down", 14, "chev")}</button><pre class="code" hidden id="raw${i}">${pretty(s.raw)}</pre></div></div>`).join("");
    $("detail").innerHTML = `<div id="dhead"><h2>${esc(r.type)}<span class="badge" style="--tone:${outcomeTone(r)}">${esc(r.outcome)}</span><span class="mono">${esc(r.id)}</span></h2>` +
      `<div class="facts"><span>Minute <b>${r.t}</b></span><span>Incidents <b>${esc(r.incidents_plain.join(", "))}</b></span><span>${r.kind === "conflict" ? "Contested" : "Hospitals"} <b>${esc(r.units_plain.join(", "))}</b></span><span>Rounds <b>${r.rounds}</b></span></div></div>` +
      `<div id="body">${steps}<div class="allraw"><button class="rawbtn" id="allraw" aria-expanded="false">${ico("code", 14)} All ${r.steps.length} raw messages as JSON ${ico("chevron-down", 14, "chev")}</button>` +
      `<pre class="code" hidden id="rawall">${pretty(r.steps.map((s) => s.raw))}</pre></div></div>`;
  }
  $("detail").addEventListener("click", (e) => {
    const b = e.target.closest(".rawbtn");
    if (!b) return;
    const pre = b.id === "allraw" ? $("rawall") : $("raw" + b.dataset.i);
    pre.hidden = !pre.hidden; b.setAttribute("aria-expanded", String(!pre.hidden));
  });

  drawList();
  const openRaw = /[#&]raw=(\d+)/.exec(window.location.hash);        // page.html#raw=1 opens the second step's raw message (handy for screenshots)
  if (openRaw && $("raw" + openRaw[1])) document.querySelector(`.rawbtn[data-i="${openRaw[1]}"]`).click();
  window.__page = { select: (id) => { selected = id; drawList(); }, records: R };
})();
