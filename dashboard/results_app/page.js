// Results page: charts drawn as plain SVG from the tables Python computed (results_view.py). Thin CI lines, one accent colour.
(() => {
  "use strict";
  const { $, esc, ico } = UI;
  const D = JSON.parse($("data").textContent);
  const NS = "http://www.w3.org/2000/svg";
  const SYSTEMS = ["naive", "greedy", "agents", "negotiation", "oracle"];
  const COLOR = { naive: "#53627A", greedy: "#94A3B8", agents: "#8B8EF6", negotiation: "#6366F1", oracle: "#A78BFA" };
  const NAME = UI.SYSTEM_LABEL, SC = UI.SCENARIO_LABEL;
  const SCENARIOS = ["normal", "surge", "bottleneck"];
  const TRIAGE_COLOR = { Immediate: "#EF4444", Delayed: "#FACC15", Minor: "#22C55E" };
  const TABS = [["csr", "Service rate"], ["rq1", "RQ1 · vs greedy"], ["rq2", "RQ2 · negotiation vs agents"], ["oracle", "Oracle ablation"], ["triage", "Triage colour"], ["cost", "RQ4 · cost"]];
  let version = D.initial, tab = "csr";

  UI.mountRail("Results"); UI.mountTooltips();
  $("versions").innerHTML = Object.keys(D.versions).map((v) => `<b data-v="${v}"${v === version ? ' class="on"' : ""}>${v}</b>`).join("");
  UI.segmented($("versions"), (v) => { version = v; draw(); });
  $("tabs").innerHTML = TABS.map(([k, t]) => `<b data-v="${k}"${k === tab ? ' class="on"' : ""}>${t}</b>`).join("");
  UI.segmented($("tabs"), (k) => { tab = k; draw(); });

  const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs || {}) e.setAttribute(k, attrs[k]); if (parent) parent.appendChild(e); return e; };
  const txt = (parent, s, attrs) => { const t = el("text", attrs, parent); t.textContent = s; return t; };
  const pct = (v) => `${(v * 100).toFixed(1)}%`, pts = (v) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)} pts`;
  const ticks = (lo, hi, n) => { const raw = (hi - lo) / n, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw); const out = []; for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10)); return out; };

  // Grouped bars. panels: [{title, color?, cats:[{key,label,sub}], series:[{name,color,vals:[{v,lo,hi,tip}|null]}]}]
  function bars(panels, { fmt, max, ci }) {
    const box = $("chart"), W = box.clientWidth, H = box.clientHeight, svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
    const left = 56, right = 16, top = 24, bottom = 54, gap = 40, pw = (W - left - right - gap * (panels.length - 1)) / panels.length, ph = H - top - bottom;
    const yMax = max || Math.max(...panels.flatMap((p) => p.series.flatMap((s) => s.vals.filter(Boolean).map((v) => (ci ? v.hi : v.v))))) * 1.15;
    const y = (v) => top + ph - (v / yMax) * ph;
    panels.forEach((p, pi) => {
      const x0 = left + pi * (pw + gap), g = el("g", {}, svg), grid = el("g", { class: "grid" }, g), axis = el("g", { class: "axis" }, g);
      ticks(0, yMax, 5).forEach((t) => { el("line", { x1: x0, x2: x0 + pw, y1: y(t), y2: y(t), class: t === 0 ? "zero" : "" }, grid); if (pi === 0) txt(axis, fmt(t, true), { x: x0 - 10, y: y(t) + 4, "text-anchor": "end" }); });
      if (panels.length > 1) { el("circle", { cx: x0 + 6, cy: top - 14, r: 5, fill: p.color || "none" }, g); txt(g, p.title, { x: x0 + 18, y: top - 9, class: "panel-title" }); }
      const placed = [], cw = pw / p.cats.length, n = p.series.length, bw = Math.min(30, (cw * 0.78) / n), used = bw * n + 4 * (n - 1);
      p.cats.forEach((c, ci2) => {
        const cx = x0 + cw * ci2 + cw / 2;
        txt(axis, c.label, { x: cx, y: top + ph + 24, "text-anchor": "middle", class: "cat" });
        if (c.sub) txt(axis, c.sub, { x: cx, y: top + ph + 42, "text-anchor": "middle" });
        p.series.forEach((s, k) => {
          let v = s.vals[ci2]; if (!v) return;
          const bx = cx - used / 2 + k * (bw + 4), by = y(v.v);
          const hit = el("g", { "data-tip": v.tip }, g);
          el("rect", { x: cx - cw / 2 + 4, y: top, width: cw - 8, height: ph, fill: "transparent", class: "hit" }, hit);
          el("rect", { x: bx, y: by, width: bw, height: Math.max(0, top + ph - by), rx: 4, fill: s.color, class: "bar", opacity: 0.92 }, hit);
          if (ci && v.hi !== undefined) {
            const mx = bx + bw / 2;
            v = { ...v, lo: Math.max(0, v.lo), hi: Math.min(yMax, v.hi) };                  // a rate cannot go below 0 or above 100%
            el("line", { x1: mx, x2: mx, y1: y(v.lo), y2: y(v.hi), stroke: "#E6EAF2", "stroke-width": 1.4, "stroke-linecap": "round", opacity: 0.85 }, hit);
            [v.lo, v.hi].forEach((e) => el("line", { x1: mx - 4, x2: mx + 4, y1: y(e), y2: y(e), stroke: "#E6EAF2", "stroke-width": 1.4, "stroke-linecap": "round", opacity: 0.85 }, hit));
          } else {                                                                                  // value label: lifted until it clears every label already placed in this group
            const label = fmt(v.v), lw = label.length * 6.8; let ly = by - 6; const lx = bx + bw / 2;
            while (placed.some((q) => Math.abs(q.x - lx) < (q.w + lw) / 2 + 2 && Math.abs(q.y - ly) < 13)) ly -= 13;
            placed.push({ x: lx, y: ly, w: lw }); txt(hit, label, { x: lx, y: ly, "text-anchor": "middle", class: "val" });
          }
        });
      });
    });
    box.innerHTML = ""; box.appendChild(svg);
  }

  // Dot and whisker: paired differences with their 95% interval as a thin line; zero line emphasised
  function dots(series, cats) {
    const box = $("chart"), W = box.clientWidth, H = box.clientHeight, svg = el("svg", { viewBox: `0 0 ${W} ${H}` });
    const left = 72, right = 24, top = 24, bottom = 54, pw = W - left - right, ph = H - top - bottom;
    const all = series.flatMap((s) => s.vals.filter(Boolean).flatMap((v) => [v.lo, v.hi, v.v, 0]));
    const lo = Math.min(...all), hi = Math.max(...all), padv = (hi - lo) * 0.12 || 0.05, a = lo - padv, b = hi + padv;
    const y = (v) => top + ph - ((v - a) / (b - a)) * ph;
    const g = el("g", {}, svg), grid = el("g", { class: "grid" }, g), axis = el("g", { class: "axis" }, g);
    ticks(a, b, 6).forEach((t) => { el("line", { x1: left, x2: left + pw, y1: y(t), y2: y(t), class: Math.abs(t) < 1e-9 ? "zero" : "" }, grid); txt(axis, `${t > 0 ? "+" : ""}${Math.round(t * 100)}`, { x: left - 10, y: y(t) + 4, "text-anchor": "end" }); });
    txt(axis, "difference in critical service rate, points", { x: 0, y: 0, transform: `translate(16 ${top + ph / 2}) rotate(-90)`, "text-anchor": "middle" });
    const cw = pw / cats.length, n = series.length, step = Math.min(70, cw / (n + 1));
    cats.forEach((c, ci) => {
      const cx = left + cw * ci + cw / 2;
      txt(axis, c.label, { x: cx, y: top + ph + 24, "text-anchor": "middle", class: "cat" }); if (c.sub) txt(axis, c.sub, { x: cx, y: top + ph + 42, "text-anchor": "middle" });
      series.forEach((s, k) => {
        const v = s.vals[ci]; if (!v) return;
        const x = cx + (k - (n - 1) / 2) * step, hit = el("g", { "data-tip": v.tip }, g);
        el("rect", { x: x - step / 2, y: top, width: step, height: ph, fill: "transparent", class: "hit" }, hit);
        el("line", { x1: x, x2: x, y1: y(v.lo), y2: y(v.hi), stroke: s.color, "stroke-width": 2, "stroke-linecap": "round", opacity: 0.9 }, hit);
        [v.lo, v.hi].forEach((e) => el("line", { x1: x - 5, x2: x + 5, y1: y(e), y2: y(e), stroke: s.color, "stroke-width": 2, "stroke-linecap": "round" }, hit));
        el("circle", { cx: x, cy: y(v.v), r: 6, fill: s.color, stroke: "#101624", "stroke-width": 2 }, hit);
        txt(hit, pts(v.v).replace(" pts", ""), { x: x + 12, y: y(v.v) + 4, class: "val" });
      });
    });
    box.innerHTML = ""; box.appendChild(svg);
  }

  const seedsOf = (P, sc) => { const r = P.csr.find((x) => x.scenario === sc && x.mode === "greedy") || P.csr.find((x) => x.scenario === sc); return r ? `${r.n} seeds` : ""; };
  const scenarioCats = (P) => SCENARIOS.filter((s) => P.csr.some((r) => r.scenario === s)).map((s) => ({ key: s, label: SC[s], sub: seedsOf(P, s) }));
  const legend = (items) => ($("legend").innerHTML = items.map(([n, c]) => `<span><i style="background:${c}"></i>${esc(n)}</span>`).join(""));

  function pairedSeries(rows, mode, vs) {
    const cats = SCENARIOS;
    return { name: `${NAME[mode]} minus ${NAME[vs]}`, color: COLOR[mode], vals: cats.map((s) => { const r = rows.find((x) => x.scenario === s); return r && { v: r.mean_diff, lo: r.ci_low, hi: r.ci_high,
      tip: `${NAME[mode]} minus ${NAME[vs]}, ${SC[s]}|${pts(r.mean_diff)} (95% CI ${pts(r.ci_low)} to ${pts(r.ci_high)})|wins/losses/ties ${r.wins}/${r.losses}/${r.ties} over ${r.n} seeds${r.significant ? "|Interval excludes zero" : "|Interval includes zero"}` }; }) };
  }

  function draw() {
    const P = D.versions[version], T = P.takeaways;
    $("vlabel").textContent = P.label;
    $("source").textContent = `Computed from ${P.source} · ${P.runs} runs · version ${version} only`;
    const cats = scenarioCats(P);
    let title, sub, take;
    if (tab === "csr") {
      title = "Critical patients served in time"; sub = `Mean per scenario with its 95% interval · version ${version}`; take = T.csr;
      const series = SYSTEMS.filter((m) => P.csr.some((r) => r.mode === m)).map((m) => ({ name: NAME[m] + (m === "oracle" ? " (3 seeds)" : ""), color: COLOR[m], vals: cats.map((c) => { const r = P.csr.find((x) => x.scenario === c.key && x.mode === m);
        return r && { v: r.mean, lo: r.ci_low, hi: r.ci_high, tip: `${NAME[m]}, ${c.label}|${pct(r.mean)} (95% CI ${pct(r.ci_low)} to ${pct(r.ci_high)})|${r.n} seeds` }; }) }));
      legend(series.map((s) => [s.name, s.color])); bars([{ cats, series }], { fmt: (v, axis) => (axis ? `${Math.round(v * 100)}%` : pct(v)), max: 1, ci: true });
    } else if (tab === "rq1") {
      title = "Paired difference versus greedy (RQ1)"; sub = `Same seeds for both systems; dot = mean difference, line = 95% interval · version ${version}`; take = T.rq1;
      const series = ["naive", "agents", "negotiation"].map((m) => pairedSeries(P.vs_greedy[m], m, "greedy")); legend(series.map((s) => [s.name, s.color])); dots(series, cats);
    } else if (tab === "rq2") {
      title = "Negotiation versus agents without negotiation (RQ2)"; sub = `Paired by seed · version ${version}`; take = T.rq2;
      const series = [pairedSeries(P.rq2, "negotiation", "agents")]; legend(series.map((s) => [s.name, s.color])); dots(series, cats);
    } else if (tab === "oracle") {
      title = "Information ablation: oracle versus negotiation"; sub = `Does perfect incident information help? · version ${version}`; take = T.oracle;
      if (!P.oracle.length) { legend([]); $("chart").innerHTML = `<div class="empty-chart"><div><div class="tile" style="--tone:var(--text-3);width:48px;height:48px;border-radius:14px;margin:0 auto 12px">${ico("info", 24)}</div>The oracle ablation was run in v1 only.<br>There are no oracle runs in ${version}.</div></div>`; }
      else { const series = [pairedSeries(P.oracle, "oracle", "negotiation")]; legend(series.map((s) => [s.name, s.color])); dots(series, cats.filter((c) => P.oracle.some((r) => r.scenario === c.key)).map((c) => ({ ...c, sub: `${(P.oracle.find((r) => r.scenario === c.key) || {}).n} seeds` }))); }
    } else if (tab === "triage") {
      title = "Patients served in time, by triage colour"; sub = `Share of patients reached within their deadline · version ${version}`; take = T.triage;
      const modes = SYSTEMS.filter((m) => P.triage.some((r) => r.mode === m));
      const panels = ["Immediate", "Delayed", "Minor"].map((color) => ({ title: color, color: TRIAGE_COLOR[color], cats: cats.map((c) => ({ key: c.key, label: c.label })), series: modes.map((m) => ({ name: NAME[m], color: COLOR[m],
        vals: cats.map((c) => { const r = P.triage.find((x) => x.scenario === c.key && x.mode === m && x.color === color); return r && { v: r.rate, tip: `${NAME[m]}, ${c.label}, ${color}|${pct(r.rate)} served in time|mean of ${r.n} runs` }; }) })) }));
      legend(modes.map((m) => [NAME[m], COLOR[m]])); bars(panels, { fmt: (v) => `${Math.round(v * 100)}%`, max: 1, ci: false });
    } else {
      title = "Cost per run at list price (RQ4)"; sub = `Mean per run; naive and greedy make no model calls and cost nothing · version ${version}`; take = T.cost;
      const modes = ["agents", "negotiation", "oracle"].filter((m) => P.cost.some((r) => r.mode === m));
      const series = modes.map((m) => ({ name: NAME[m], color: COLOR[m], vals: cats.map((c) => { const r = P.cost.find((x) => x.scenario === c.key && x.mode === m);
        return r && { v: r.cost_usd, tip: `${NAME[m]}, ${c.label}|$${r.cost_usd.toFixed(3)} per run|${Math.round(r.tokens).toLocaleString()} tokens, ${Math.round(r.calls)} model calls, ${Math.round(r.latency_s)} s of model time` }; }) }));
      legend(series.map((s) => [s.name, s.color])); bars([{ cats, series }], { fmt: (v, axis) => (axis ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`), ci: false });
    }
    $("ctitle").textContent = title; $("csub").textContent = sub;
    $("takeaway").innerHTML = `<span class="tile" style="--tone:var(--accent)">${ico("info", 18)}</span><div><b>Takeaway</b>${esc(take)}</div>`;
  }
  window.addEventListener("resize", draw);
  const wanted = /[#&]tab=(\w+)/.exec(window.location.hash);            // page.html#tab=triage opens that tab (handy for screenshots)
  if (wanted && TABS.some(([k]) => k === wanted[1])) { tab = wanted[1]; $("tabs").querySelectorAll("b").forEach((b) => b.classList.toggle("on", b.dataset.v === tab)); }
  draw();
  window.__page = { draw, setTab: (k) => { tab = k; draw(); }, setVersion: (v) => { version = v; draw(); } };
})();
