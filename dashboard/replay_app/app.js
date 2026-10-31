// Replay app: draws what Python computed (see src/erc/dashboard/export.py). No emergency logic lives here:
// only drawing, gliding between minutes, collision-free label placement, and the controls.
(() => {
  "use strict";
  const B = JSON.parse(document.getElementById("bundle").textContent);
  const CAT = JSON.parse(document.getElementById("catalog").textContent);
  const N = B.meta.last_minute, KM = B.meta.grid_km;
  const NS = "http://www.w3.org/2000/svg";
  const MAX_FRAME_MS = 500, FADE_MIN = 2.0, CALLOUT_MIN = 3;
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  // Density tier for the responsive CSS (same rule as dashboard/ui/base.js): lg = the 1920 x 1080 design, md and sm = smaller windows.
  // The two embedded Compare players and the What-if player use their own, narrower thresholds.
  const setDensity = () => {
    const w = innerWidth, h = innerHeight, c = document.body.className, mode = /mode-/.test(c);
    const [wl, wm] = /mode-compare/.test(c) ? [840, 700] : /mode-inline/.test(c) ? [1700, 1400] : [1780, 1480];
    document.body.dataset.d = (w >= wl && (h >= 960 || mode)) ? "lg" : (w >= wm && (h >= 760 || mode)) ? "md" : "sm";
  };
  setDensity(); addEventListener("resize", setDensity);
  const ico = (n, s = 16, extra = "") => `<svg class="i ${extra}" width="${s}" height="${s}"><use href="#i-${n}"/></svg>`;

  const TRIAGE = { 1: "var(--triage-immediate)", 2: "var(--triage-delayed)", 3: "var(--triage-minor)", 4: "var(--triage-expectant)", 5: "var(--triage-reached)" };
  const STATUS_COLOR = { available: "var(--text-3)", en_route: "var(--info)", on_scene: "var(--ok)", transporting: "var(--violet)" };
  const HOSPITAL_COLOR = { "Stable": "var(--ok)", "Moderate": "var(--moderate)", "Near capacity": "var(--danger)" };
  const TYPE_COLOR = { proposal: "var(--accent)", counter: "var(--warn)", accept: "var(--ok)", reject: "var(--danger)", conflict: "var(--warn)",
    executed: "var(--violet)", info: "var(--text-3)", escalate: "var(--warn)" };
  const STORY = new Set(["conflict", "counter", "accept", "reject", "escalate", "executed"]);
  const TEAM_ICON = { fire: "flame", rescue: "shield-check", medical: "activity" };
  const TEAM_LABEL = { fire: "Fire", rescue: "Rescue", medical: "Medical" };
  const SYSTEM_LABEL = { naive: "Naive", greedy: "Greedy", agents: "Agents", negotiation: "Negotiation", oracle: "Oracle" };
  const SCENARIO_LABEL = { normal: "Normal", surge: "Surge", bottleneck: "Bottleneck" };
  const DISTRICTS = [
    [[-6, 25], [6.5, 25], [7.5, 14], [-6, 13]], [[6.5, 25], [14, 25], [15.5, 15], [7.5, 14]], [[14, 25], [26, 25], [26, 12], [15.5, 15]],
    [[-6, 13], [7.5, 14], [8, 7], [-6, 6.5]], [[7.5, 14], [15.5, 15], [16.5, 8], [8, 7]], [[15.5, 15], [26, 12], [26, 5], [16.5, 8]],
    [[-6, 6.5], [8, 7], [9, -8], [-6, -8]], [[8, 7], [16.5, 8], [17, -8], [9, -8]], [[16.5, 8], [26, 5], [26, -8], [17, -8]]];
  const ARTERIALS = [[[-6, 12], [5, 15], [10, 11], [17, 12], [26, 9]], [[5, 15], [7.3, 18.5], [8, 25]], [[10, 11], [10, 4], [9, -8]], [[15, 13], [14, 6], [13, -8]]];

  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const useIcon = (parent, name, size, color) => {
    const s = el("svg", { class: "i", width: size, height: size, x: -size / 2, y: -size / 2 }, parent);
    s.style.color = color;
    el("use", { href: `#i-${name}` }, s);
    return s;
  };

  // ───────── Rail and top bar ─────────
  const NAV = [["Replay", "map", ""], ["Compare", "git-compare", "compare"], ["What-if", "sliders-horizontal", "whatif"],
    ["Results", "chart-column", "results"], ["Negotiations", "messages-square", "negotiations"]];
  const pageRoot = () => { try { return window.top.location.pathname.replace(/\/[^/]*$/, "/"); } catch (e) { return "/"; } };
  // The page sits in a sandboxed iframe that may not navigate its parent directly, so the address change is
  // handed to a tiny script that runs in the parent page itself.
  const goto = (path, query) => {
    const url = pageRoot() + path + (query ? "?" + query : "");
    try {
      const s = window.parent.document.createElement("script");
      s.textContent = `window.location.assign(${JSON.stringify(url)});`;
      window.parent.document.body.appendChild(s);
    } catch (e) { /* not embedded */ }
  };
  $("rail").innerHTML = `<div class="logo">${ico("siren", 18)}</div>` + NAV.map(([label, icon, path]) =>
    `<button class="rail-item${path === "" ? " active" : ""}" data-path="${path}">${ico(icon, 20)}<span>${label}</span></button>`).join("");
  $("rail").addEventListener("click", (e) => {
    const b = e.target.closest(".rail-item");
    if (b && !b.classList.contains("active")) goto(b.dataset.path);
  });
  $("tour").innerHTML = `${ico("flag", 16)} Tour`;
  const meta = B.meta;
  const runLabel = [SCENARIO_LABEL[meta.scenario] || meta.scenario, `Run ${meta.run_number}`, SYSTEM_LABEL[meta.mode] || meta.mode, meta.version];
  $("runpill").innerHTML = ico("activity", 16) + runLabel.map(esc).join('<span class="dot">&middot;</span>') + ico("chevron-down", 16);
  $("runpill").dataset.tip = `Run|${meta.version} / ${meta.scenario} / run ${meta.run_number} (seed ${meta.seed}) / ${meta.mode}`;

  // Run selector popover: staged choices, applied by reloading the page with the chosen run in its address.
  const sel = { v: meta.version, s: meta.scenario, r: String(meta.run_number), m: meta.mode };
  const pick = (obj, key, fallback) => (key in obj ? key : fallback in obj ? fallback : Object.keys(obj)[0]);
  function fixSel(changed) {
    sel.v = pick(CAT, sel.v, "v1");
    sel.s = pick(CAT[sel.v], sel.s, "normal");
    sel.r = pick(CAT[sel.v][sel.s], sel.r, "1");
    if (!CAT[sel.v][sel.s][sel.r].includes(sel.m)) sel.m = CAT[sel.v][sel.s][sel.r].includes("negotiation") ? "negotiation" : CAT[sel.v][sel.s][sel.r][0];
  }
  function drawPop() {
    const col = (title, key, items) => `<div class="pop-col"><h4>${title}</h4>` + items.map(([val, label, ok]) =>
      `<button class="opt${sel[key] === val ? " sel" : ""}" data-k="${key}" data-v="${esc(val)}"${ok ? "" : " disabled"}>${esc(label)}</button>`).join("") + "</div>";
    const vers = Object.keys(CAT), scen = Object.keys(CAT[sel.v]), runs = Object.keys(CAT[sel.v][sel.s]);
    const allModes = ["naive", "greedy", "agents", "negotiation", "oracle"];
    $("runpop").innerHTML = `<div class="pop-grid">` +
      col("Version", "v", vers.map((v) => [v, v, true])) +
      col("Scenario", "s", Object.keys(CAT[sel.v]).map((s) => [s, SCENARIO_LABEL[s] || s, true])) +
      col("Run", "r", runs.map((r) => [r, `Run ${r} (seed ${+r + 41})`, true])) +
      col("System", "m", allModes.map((m) => [m, SYSTEM_LABEL[m], CAT[sel.v][sel.s][sel.r].includes(m)])) +
      `</div><div class="pop-foot"><span>${SCENARIO_LABEL[sel.s] || sel.s} &middot; run ${sel.r} &middot; ${SYSTEM_LABEL[sel.m] || sel.m} &middot; ${sel.v}</span><button class="btn" id="popapply">Show this run</button></div>`;
  }
  $("runpill").addEventListener("click", () => {
    const open = $("runpop").hidden;
    $("runpop").hidden = !open; $("runpill").setAttribute("aria-expanded", String(open));
    if (open) drawPop();
  });
  $("runpop").addEventListener("click", (e) => {
    const o = e.target.closest(".opt");
    if (o && !o.disabled) { sel[o.dataset.k] = o.dataset.v; fixSel(); drawPop(); }
    if (e.target.closest("#popapply")) goto("", `v=${sel.v}&s=${sel.s}&r=${sel.r}&m=${sel.m}`);
  });
  document.addEventListener("click", (e) => {
    if (!$("runpop").hidden && !e.composedPath().includes($("runwrap"))) { $("runpop").hidden = true; $("runpill").setAttribute("aria-expanded", "false"); }
  });

  // ───────── Tooltips: any element with data-tip="Title|detail" ─────────
  const tip = $("tip");
  document.addEventListener("mouseover", (e) => {
    const t = e.target.closest && e.target.closest("[data-tip]");
    if (!t) { tip.hidden = true; return; }
    const [title, ...rest] = t.getAttribute("data-tip").split("|");
    tip.innerHTML = `<b>${esc(title)}</b>${rest.map(esc).join("<br>")}`;
    tip.hidden = false;
  });
  document.addEventListener("mousemove", (e) => {
    if (tip.hidden) return;
    tip.style.left = clamp(e.clientX + 16, 8, window.innerWidth - tip.offsetWidth - 8) + "px";
    tip.style.top = clamp(e.clientY + 16, 8, window.innerHeight - tip.offsetHeight - 8) + "px";
  });
  document.addEventListener("mouseleave", () => { tip.hidden = true; });

  // ───────── Map geometry ─────────
  const svg = $("mapsvg");
  let G, layers, hospitals, incidents, ambulances, responders, conflictLines = [], labelRefs = [];
  const where = {};
  const mapPos = (id) => where[id];
  B.hospitals.forEach((h) => (where[h.id] = [h.x, h.y]));
  B.incidents.forEach((i) => (where[i.id] = [i.map_x, i.map_y]));      // routes end at the marker, not the true spot
  const trips = {};
  B.trips.forEach((t) => (trips[t.unit] = trips[t.unit] || []).push(t));

  function geom() {
    const r = $("map").getBoundingClientRect(), W = r.width, H = r.height;
    const tight = document.body.classList.contains("mode-compare") && document.body.dataset.d !== "lg";   // laptop Compare: the playbar sits below the maps, so the city can use the whole box (the 1920 playbar floats over the bottom)
    const bottom = tight ? 30 : 90, top = tight ? 30 : 44, side = tight ? 36 : 80;
    const S = Math.min((H - bottom - top) / KM, (W - side) / KM);
    return { W, H, S, X0: (W - KM * S) / 2, bottom, X: (x) => (W - KM * S) / 2 + x * S, Y: (y) => H - bottom - y * S };
  }
  const DOCK_CLUSTER = [[-50, -16], [50, 16], [0, 46], [0, -46], [-56, 36], [56, -36]];
  const DOCK_INC = [[0, 66], [-74, 18], [74, 18], [0, -66], [-60, -52], [60, -52], [-60, 66], [60, 66]];
  const DOCK = [[70, 20], [-70, 20], [0, 70], [0, -70], [84, -34], [-84, -34], [58, 70], [-58, 70]];
  const rectAt = (cx, cy, w, h) => ({ x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 });
  const overlap = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;

  function build() {
    G = geom();
    svg.setAttribute("viewBox", `0 0 ${G.W} ${G.H}`);
    svg.innerHTML = "";
    const defs = el("defs", {}, svg);
    const grad = el("radialGradient", { id: "vignette", cx: "50%", cy: "45%", r: "75%" }, defs);
    el("stop", { offset: 0, "stop-color": "#0E1524" }, grad); el("stop", { offset: 1, "stop-color": "#080C14" }, grad);
    el("rect", { width: G.W, height: G.H, fill: "url(#vignette)" }, svg);
    DISTRICTS.forEach((poly, i) => el("polygon", { points: poly.map(([x, y]) => `${G.X(x).toFixed(0)},${G.Y(y).toFixed(0)}`).join(" "),
      fill: i % 2 ? "#0F1624" : "#111A2B", stroke: "rgba(148,163,184,.07)", "stroke-width": 1.5, "stroke-linejoin": "round" }, svg));
    for (let k = -8; k <= 28; k += 2) {
      el("line", { x1: G.X(k), y1: 0, x2: G.X(k), y2: G.H, stroke: "rgba(148,163,184,.045)" }, svg);
      el("line", { x1: 0, y1: G.Y(k), x2: G.W, y2: G.Y(k), stroke: "rgba(148,163,184,.045)" }, svg);
    }
    ARTERIALS.forEach((road) => el("polyline", { points: road.map(([x, y]) => `${G.X(x).toFixed(0)},${G.Y(y).toFixed(0)}`).join(" "), fill: "none",
      stroke: "rgba(148,163,184,.11)", "stroke-width": 3, "stroke-linecap": "round", "stroke-linejoin": "round" }, svg));
    layers = {};
    ["routes", "conflict", "hospitals", "incidents", "units", "labels"].forEach((n) => (layers[n] = el("g", {}, svg)));

    // Hospitals: glow, one ring arc per ER bed, icon tile
    hospitals = B.hospitals.map((h) => {
      const g = el("g", { transform: `translate(${G.X(h.x)},${G.Y(h.y)})`, "data-tip": "" }, layers.hospitals);
      const glow = el("circle", { r: 46, opacity: 0.1 }, g);
      el("circle", { r: 34, fill: "url(#vignette)" }, g);
      const segs = [], gap = 0.16, step = (2 * Math.PI) / h.er_capacity;
      for (let k = 0; k < h.er_capacity; k++) {
        const a0 = -Math.PI / 2 + k * step + gap / 2, a1 = -Math.PI / 2 + (k + 1) * step - gap / 2, r = 32;
        segs.push(el("path", { d: `M${(r * Math.cos(a0)).toFixed(1)},${(r * Math.sin(a0)).toFixed(1)} A${r},${r} 0 0 1 ${(r * Math.cos(a1)).toFixed(1)},${(r * Math.sin(a1)).toFixed(1)}`,
          fill: "none", "stroke-width": 5, "stroke-linecap": "round" }, g));
      }
      el("circle", { r: 24, fill: "#131B2C", stroke: "rgba(148,163,184,.25)" }, g);
      useIcon(g, "hospital", 24, "#E6EAF2");
      return { h, g, glow, segs, box: rectAt(G.X(h.x), G.Y(h.y), 92, 92) };
    });

    // Incidents: glow, ring, one dot per patient
    incidents = B.incidents.map((inc) => {
      const px = G.X(inc.map_x), py = G.Y(inc.map_y);
      const g = el("g", { transform: `translate(${px},${py})`, opacity: 0, "data-tip": "" }, layers.incidents);
      const g1 = el("circle", { r: 40, opacity: 0.13 }, g), g2 = el("circle", { r: 24, opacity: 0.12 }, g);
      const ring = el("circle", { r: 14, fill: "#0E1524", "stroke-width": 1.5 }, g);
      const mine = B.victims.map((v, i) => [v, i]).filter(([v]) => v.incident === inc.id);
      const dots = mine.map(([v, i], k) => {
        const ang = (2 * Math.PI * k) / mine.length - Math.PI / 2, rr = mine.length > 1 ? 7 : 0;
        const c = el("circle", { cx: Math.cos(ang) * rr, cy: Math.sin(ang) * rr, r: mine.length > 1 ? 4.2 : 5, stroke: "#0A0E17", "stroke-width": 1.2 }, g);
        return { v, i, c };
      });
      return { inc, g, g1, g2, ring, dots, resolved: false, px, py, label: null, spot: 0 };
    });

    // Units
    ambulances = B.ambulances.map((a, idx) => {
      const g = el("g", { "data-tip": "" }, layers.units);
      const pulse = el("circle", { r: 26, fill: "none", stroke: "var(--warn)", "stroke-width": 2, class: "pulse", opacity: 0 }, g);
      const w = a.als ? 68 : 44;
      const chip = el("rect", { x: -w / 2, y: -12, width: w, height: 24, rx: 12, fill: "#131B2C", "stroke-width": 1.5 }, g);
      const ic = el("svg", { class: "i", x: -w / 2 + 7, y: -7, width: 14, height: 14 }, g); el("use", { href: "#i-ambulance" }, ic);
      const t = el("text", { x: -w / 2 + 25, y: 4, "font-size": 12, "font-weight": 600, fill: "#E6EAF2" }, g);
      t.textContent = "A" + parseInt(a.id.split("-")[1], 10);
      if (a.als) { const als = el("text", { x: w / 2 - 24, y: 3.5, "font-size": 9.5, "font-weight": 700, "letter-spacing": ".06em", fill: "var(--accent-hover)" }, g); als.textContent = "ALS"; }
      const route = el("line", { stroke: "var(--info)", "stroke-opacity": 0.55, "stroke-width": 1.6, "stroke-dasharray": "3 7", "stroke-linecap": "round", class: "route", opacity: 0 }, layers.routes);
      return { a, idx, g, pulse, chip, ic, w, route, px: 0, py: 0, angle: 0 };
    });
    responders = B.responders.map((r, idx) => {
      const g = el("g", { "data-tip": "" }, layers.units);
      const c = el("circle", { r: 13, fill: "#131B2C", "stroke-width": 1.5 }, g);
      const ic = el("svg", { class: "i", x: -7, y: -7, width: 14, height: 14 }, g); el("use", { href: `#i-${TEAM_ICON[r.kind] || "users"}` }, ic);
      const route = el("line", { stroke: "var(--info)", "stroke-opacity": 0.5, "stroke-width": 1.4, "stroke-dasharray": "3 7", "stroke-linecap": "round", class: "route", opacity: 0 }, layers.routes);
      return { r, idx, g, c, ic, route, px: 0, py: 0 };
    });
    placeCorners();
    shownMinute = -1;
    render(tau);
  }

  // The tour card sits in whichever bottom corner has fewer incidents, hospitals and units.
  function placeCorners() {
    const tc = $("tourcard"), w = 460, h = 150, pad = 24, y1 = G.H - 112, y0 = y1 - h;
    const things = [...incidents.map((is) => rectAt(is.px, is.py, 84, 84)), ...hospitals.map((hs) => hs.box),
      ...hospitals.map((hs) => rectAt(G.X(hs.h.x), G.Y(hs.h.y) + 63, 120, 26)),
      ...B.frames[0].a.map((a) => rectAt(G.X(a[0]), G.Y(a[1]), 70, 30)), ...B.frames[0].r.map((r) => rectAt(G.X(r[0]), G.Y(r[1]), 120, 30))];
    const score = (x0) => things.filter((o) => overlap({ x0, y0, x1: x0 + w, y1 }, o)).length;
    const left = score(pad) < score(G.W - pad - w);
    tc.style.left = left ? pad + "px" : "auto"; tc.style.right = left ? "auto" : pad + "px";
  }

  // ───────── Gliding between minutes ─────────
  function position(unitId, t, frameXY) {
    const list = trips[unitId];
    if (list) for (const tr of list) {
      if (t >= tr.t0 && t <= tr.t1) {
        const f = tr.t1 === tr.t0 ? 1 : (t - tr.t0) / (tr.t1 - tr.t0);
        return { x: tr.x0 + (tr.x1 - tr.x0) * f, y: tr.y0 + (tr.y1 - tr.y0) * f, trip: tr };
      }
    }
    return { x: frameXY[0], y: frameXY[1], trip: null };
  }

  // ───────── Drawing one moment ─────────
  let tau = 0, shownMinute = -1;
  const unitName = (id) => (id.startsWith("AMB") ? "Ambulance " + parseInt(id.split("-")[1], 10) : id.replace("RESCUE-1", "Rescue team").replace("FIRE-1", "Fire team").replace("MED-1", "Medical team"));
  const incName = (id) => "Incident " + parseInt(id.split("-")[1], 10);

  function render(t) {
    if (!G) return;
    const m = Math.min(N, Math.floor(t)), frame = B.frames[m];

    hospitals.forEach((hs, i) => {
      const [er, , promised, status] = frame.h[i], cap = hs.h.er_capacity, color = HOSPITAL_COLOR[status];
      hs.glow.setAttribute("fill", color);
      hs.segs.forEach((s, k) => s.setAttribute("stroke", k < er ? color : k < er + promised ? "var(--info)" : "rgba(148,163,184,.22)"));
      hs.g.setAttribute("data-tip", `${hs.h.name}|${hs.h.id} - ${er} of ${cap} ER beds in use` + (promised ? `|${promised} more patient${promised > 1 ? "s" : ""} on the way` : "") + `|${status}`);
    });

    incidents.forEach((is) => {
      const arrived = m >= is.inc.arrival_min;
      let open = 0, worst = 9;
      is.dots.forEach(({ v, i, c }) => {
        const code = frame.v[i];
        if (code === 0) { c.setAttribute("opacity", 0); return; }
        if (code === 5) {
          const f = clamp(1 - (t - v.contact_min) / FADE_MIN, 0, 1);
          c.setAttribute("fill", "var(--triage-reached)"); c.setAttribute("opacity", f * 0.9); return;
        }
        open += 1; worst = Math.min(worst, code);
        c.setAttribute("fill", TRIAGE[code]); c.setAttribute("opacity", 1);
        c.setAttribute("stroke", code === 4 ? "#CBD5E1" : "#0A0E17");
      });
      is.resolved = arrived && open === 0;
      const lastContact = Math.max(-1, ...is.dots.map(({ v }) => (v.contact_min === null ? -1 : v.contact_min)));
      const gone = is.resolved ? clamp(1 - (t - lastContact) / FADE_MIN, 0, 1) : 1;            // a resolved incident fades out completely
      const color = TRIAGE[worst === 9 ? 5 : worst];
      [is.g1, is.g2].forEach((c) => c.setAttribute("fill", worst === 4 ? "#CBD5E1" : color));
      is.ring.setAttribute("stroke", color);
      is.g.setAttribute("opacity", arrived ? (open ? 1 : gone) : 0);
      is.g.setAttribute("data-tip", `${incName(is.inc.id)}|${is.inc.id} - ${open} patient${open === 1 ? "" : "s"} waiting`);
    });

    const taken = hospitals.map((hs) => hs.box);
    incidents.forEach((is) => { if (m >= is.inc.arrival_min && !is.resolved) taken.push(rectAt(is.px, is.py, 84, 84)); });
    const live = {};
    const everyone = [...ambulances, ...responders], posOf = new Map(), dock = new Map();
    everyone.forEach((u) => { const id = (u.a || u.r).id; posOf.set(u, position(id, t, (u.a ? frame.a : frame.r)[u.idx])); });
    hospitals.forEach((hs) => {                                                 // units parked at a hospital fan out beside it
      const dist = (u) => Math.hypot(posOf.get(u).x - hs.h.x, posOf.get(u).y - hs.h.y);
      everyone.filter((u) => dist(u) < 0.95).forEach((u, k) => {
        const wt = clamp((0.95 - dist(u)) / 0.4, 0, 1);                           // eases in and out as a unit arrives or leaves
        dock.set(u, DOCK[k % DOCK.length].map((v) => v * wt));
      });
    });
    incidents.filter((is) => m >= is.inc.arrival_min && !is.resolved).forEach((is) => {   // units at an incident fan out around its marker
      const dist = (u) => Math.hypot(posOf.get(u).x - is.inc.x, posOf.get(u).y - is.inc.y);
      const shift = [G.X(is.inc.map_x) - G.X(is.inc.x), G.Y(is.inc.map_y) - G.Y(is.inc.y)];      // from the true spot to the displayed marker
      everyone.filter((u) => !dock.has(u) && dist(u) < 0.95).sort((p, q) => (p.a ? p.a.id : p.r.id).localeCompare(q.a ? q.a.id : q.r.id)).forEach((u, k) => {
        const wt = clamp((0.95 - dist(u)) / 0.4, 0, 1);
        dock.set(u, [shift[0] + DOCK_INC[k % DOCK_INC.length][0], shift[1] + DOCK_INC[k % DOCK_INC.length][1]].map((v) => v * wt));
      });
    });
    const idOf = (u) => (u.a ? u.a.id : u.r.id);                                    // any other units on top of each other spread apart too
    const loose = everyone.filter((u) => !dock.has(u)).sort((p, q) => idOf(p).localeCompare(idOf(q))), seen = new Set();
    loose.forEach((u) => {
      if (seen.has(u)) return;
      const p = posOf.get(u), grp = loose.filter((v) => !seen.has(v) && Math.hypot(posOf.get(v).x - p.x, posOf.get(v).y - p.y) < 0.9);
      if (grp.length < 2) return;
      grp.forEach((v) => seen.add(v));
      const cx = grp.reduce((a, v) => a + posOf.get(v).x, 0) / grp.length, cy = grp.reduce((a, v) => a + posOf.get(v).y, 0) / grp.length;
      grp.forEach((v, k) => {
        const pv = posOf.get(v), wt = clamp((0.9 - Math.hypot(pv.x - cx, pv.y - cy)) / 0.4, 0, 1), slot = DOCK_CLUSTER[k % DOCK_CLUSTER.length];
        dock.set(v, [(G.X(cx) - G.X(pv.x) + slot[0]) * wt, (G.Y(cy) - G.Y(pv.y) + slot[1]) * wt]);
      });
    });
    const placeUnit = (u, pos, w, h) => {
      const off = dock.get(u) || [0, 0];
      u.px = clamp(G.X(pos.x) + off[0], 36, G.W - 36); u.py = clamp(G.Y(pos.y) + off[1], 22, G.H - Math.max(22, G.bottom - 14));        // never half off the map
      u.g.setAttribute("transform", `translate(${u.px},${u.py})`);
      taken.push(rectAt(u.px, u.py, w, h));
    };
    const conflictNow = [...B.conflicts].reverse().find((k) => k.t <= m && m < k.t + CALLOUT_MIN) || null;
    ambulances.forEach((u) => {
      const row = frame.a[u.idx], pos = position(u.a.id, t, row);
      const hot = conflictNow && conflictNow.resources.includes(u.a.id);
      placeUnit(u, pos, u.w + 24, hot ? 66 : 30);
      const color = STATUS_COLOR[row[2]] || STATUS_COLOR.available;
      u.chip.setAttribute("stroke", color); u.ic.style.color = color;
      u.pulse.style.display = hot ? "" : "none";                                // orange rings are only for units in an active conflict
      u.chip.setAttribute("stroke", hot ? "var(--warn)" : color);
      u.g.setAttribute("opacity", row[2] === "available" ? 0.8 : 1);
      u.g.setAttribute("data-tip", `${unitName(u.a.id)}|${u.a.id} - ${u.a.als ? "advanced" : "basic"} life support|${row[2].replace("_", " ")}` + (row[3] ? ` - ${row[3]}` : "") + (row[4] ? `|${row[4]} patient${row[4] > 1 ? "s" : ""} on board` : ""));
      const target = row[3] && mapPos(row[3]);
      if (row[2] === "en_route" && target || row[2] === "transporting" && target) {
        u.route.setAttribute("x1", u.px); u.route.setAttribute("y1", u.py); u.route.setAttribute("x2", G.X(target[0])); u.route.setAttribute("y2", G.Y(target[1]));
        u.route.setAttribute("stroke", row[2] === "transporting" ? "var(--violet)" : "var(--info)"); u.route.setAttribute("opacity", 1);
      } else u.route.setAttribute("opacity", 0);
      live[u.a.id] = [u.px, u.py];
    });
    responders.forEach((u) => {
      const row = frame.r[u.idx], pos = position(u.r.id, t, row), busy = row[2] !== "available";
      placeUnit(u, pos, 66, 30);
      const color = busy ? "var(--info)" : "var(--text-3)";
      u.c.setAttribute("stroke", color); u.ic.style.color = color; u.g.setAttribute("opacity", busy ? 1 : 0.75);
      u.g.setAttribute("data-tip", `${unitName(u.r.id)}|${u.r.id} - ${row[2].replace("_", " ")}` + (row[3] ? ` - ${row[3]}` : ""));
      const target = row[3] && mapPos(row[3]);
      if (row[2] === "en_route" && target) {
        u.route.setAttribute("x1", u.px); u.route.setAttribute("y1", u.py); u.route.setAttribute("x2", G.X(target[0])); u.route.setAttribute("y2", G.Y(target[1])); u.route.setAttribute("opacity", 1);
      } else u.route.setAttribute("opacity", 0);
      live[u.r.id] = [u.px, u.py];
    });

    drawLabels(m, taken);
    drawConflict(m, conflictNow, live);
    if (m !== shownMinute) { shownMinute = m; panels(m, frame); }
    $("min").textContent = String(m);
    scrub.value = t; scrub.style.setProperty("--p", (t / N) * 100 + "%");
  }

  // Labels last, each at the first free spot around its object (hospital names, incident names, team names)
  function drawLabels(m, taken) {
    layers.labels.innerHTML = "";
    // spots(w) lists offsets in order of preference, measured so a label never touches its own object
    const place = (cx, cy, text, spots, tone, bold) => {
      const LS = G.W < 700 ? 0.85 : 1;                                           // labels shrink a little on small maps (Compare on a laptop)
      const w = (8 + text.length * 6.6) * LS, list = spots(w), hh = 11 * LS;
      const inside = (x, y) => x - w / 2 >= 8 && x + w / 2 <= G.W - 8 && y - hh >= 8 && y + hh <= G.H - G.bottom - 10;
      const ring = [];                                                           // farther candidates, all around, for crowded spots
      for (const r of [48 * LS, 72 * LS, 96 * LS, 124 * LS]) for (let a = 0; a < 16; a++) ring.push([Math.cos((a * Math.PI) / 8) * (r + w / 3), Math.sin((a * Math.PI) / 8) * r]);
      const area = (a, b) => Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
      const cost = ([dx, dy]) => taken.reduce((sum, o) => sum + area(rectAt(cx + dx, cy + dy, w + 4, 26 * LS), o), 0);   // overlapped area, so the least-bad spot wins when none is free
      const all = [...list, ...ring].filter(([dx, dy]) => inside(cx + dx, cy + dy));
      const pick = all.find((p) => cost(p) === 0) || all.sort((p, q) => cost(p) - cost(q) || Math.hypot(p[0], p[1]) - Math.hypot(q[0], q[1]))[0] || list[0];
      const x = cx + pick[0], y = cy + pick[1];
      taken.push(rectAt(x, y, w, 22 * LS));
      const g = el("g", {}, layers.labels);
      el("rect", { x: x - w / 2, y: y - hh, width: w, height: 2 * hh, rx: hh, fill: "rgba(10,14,23,.78)", stroke: "rgba(148,163,184,.16)" }, g);
      const t = el("text", { x, y: y + 4 * LS, "text-anchor": "middle", "font-size": 12 * LS, "font-weight": bold ? 600 : 500, fill: tone }, g);
      t.textContent = text;
    };
    hospitals.forEach((hs) => place(G.X(hs.h.x), G.Y(hs.h.y), hs.h.name, (w) => [[0, 63], [0, -63], [w / 2 + 52, 0], [-(w / 2 + 52), 0]], "var(--text)", true));
    const shown = incidents.filter((is) => m >= is.inc.arrival_min && !is.resolved).sort((a, b) => a.py - b.py);
    shown.forEach((is, n) => place(is.px, is.py, incName(is.inc.id),
      (w) => { const side = w / 2 + 50; return (n % 2 === 0 ? [[-side, 0], [side, 0], [0, -56], [0, 56]] : [[side, 0], [-side, 0], [0, 56], [0, -56]]).concat([[side, -30], [-side, -30], [side, 30], [-side, 30]]); }, "var(--text-2)", false));
    responders.forEach((u) => place(u.px, u.py, TEAM_LABEL[u.r.kind], (w) => [[w / 2 + 42, 0], [-(w / 2 + 42), 0], [0, 32], [0, -32]], "var(--text-3)", false));
  }

  // Conflict: dashed lines from the contested unit to each incident, plus a card placed where it covers the least
  const callout = $("callout");
  function drawConflict(m, c, live) {
    layers.conflict.innerHTML = "";
    if (!c) { callout.hidden = true; return; }
    const unit = c.resources.map((id) => live[id]).find(Boolean);
    const pts = c.incidents.map((id) => mapPos(id)).filter(Boolean).map(([x, y]) => [G.X(x), G.Y(y)]);
    if (unit) pts.forEach(([x, y]) => el("line", { x1: unit[0], y1: unit[1], x2: x, y2: y, stroke: "var(--warn)", "stroke-width": 1.8,
      "stroke-dasharray": "6 6", "stroke-linecap": "round" }, layers.conflict));
    const stage = c.stages[2], settled = c.stages[1].ref === null ? `Settled by ${c.method === "negotiation" ? "agreement" : "the priority rule"}` :
      stage.label === "Accepted" ? "Counter-offer accepted" : stage.label === "Rejected" ? "Counter-offer rejected" : "Negotiating a counter-offer";
    callout.innerHTML = `<div class="tile">${ico("triangle-alert", 20)}</div><div><h3>Conflict at minute ${c.t}</h3><p>${esc(c.plain)}</p><div class="live"><i></i>${esc(settled)}</div></div>`;
    callout.hidden = false;
    const w = callout.offsetWidth, h = callout.offsetHeight, edge = 16;
    const involved = pts.map(([x, y]) => rectAt(x, y, 84, 84)); if (unit) involved.push(rectAt(unit[0], unit[1], 80, 66));
    const others = [...hospitals.map((hs) => hs.box), ...[...ambulances, ...responders].map((u) => rectAt(u.px, u.py, 60, 30))];
    const spots = { tr: [G.W - edge - w, edge], tl: [edge, edge], tc: [(G.W - w) / 2, edge] };
    let best = null;
    for (const [name, [x, y]] of Object.entries(spots)) {
      const box = { x0: x, y0: y, x1: x + w, y1: y + h };
      const score = 100 * involved.filter((o) => overlap(box, o)).length + others.filter((o) => overlap(box, o)).length;
      if (!best || score < best.score) best = { name, x, y, score };
    }
    callout.style.left = best.x + "px"; callout.style.top = best.y + "px";
  }

  // ───────── Side panels (rebuilt once per simulated minute) ─────────
  function spark(series, now, color, w = 112, h = 34) {
    const vals = series.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
    if (!vals.length) return "";
    const top = Math.max(...vals.map(([, v]) => v)) || 1;
    const pt = ([i, v]) => [(i / (series.length - 1)) * w, h - 3 - (v / top) * (h - 8)];
    const path = (pts) => pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const past = vals.filter(([i]) => i <= now).map(pt), future = vals.filter(([i]) => i >= now).map(pt), at = vals.find(([i]) => i === now);
    const nx = (now / (series.length - 1)) * w;
    return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
      (past.length > 1 ? `<polyline points="${path(past)}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>` : "") +
      (future.length > 1 ? `<polyline points="${path(future)}" fill="none" stroke="${color}" stroke-opacity=".35" stroke-width="1.4" stroke-dasharray="2 3"/>` : "") +
      `<line x1="${nx.toFixed(1)}" y1="2" x2="${nx.toFixed(1)}" y2="${h - 2}" stroke="rgba(148,163,184,.35)"/>` +
      (at ? `<circle cx="${pt(at)[0].toFixed(1)}" cy="${pt(at)[1].toFixed(1)}" r="3" fill="${color}"/>` : "") + "</svg>";
  }
  const SERIES = {};
  ["crit_ok", "reached", "expectant", "conflicts", "resp_avg"].forEach((k) => (SERIES[k] = B.frames.map((f) => f.k[k])));
  const kpi = (cls, icon, tone, label, val, of, note, series, now, tip) =>
    `<div class="card kpi ${cls}" data-tip="${esc(label + "|" + tip)}"><div class="kpi-top"><span class="tile" style="--tone:${tone}">${ico(icon, 16)}</span><span class="kpi-label">${label}</span></div>` +
    `<div class="kpi-mid"><div class="kpi-value">${val}${of !== null ? `<span class="kpi-of"> / ${of}</span>` : ""}</div>${spark(series, now, tone)}</div><div class="kpi-note">${esc(note)}</div></div>`;

  function panels(m, frame) {
    const k = frame.k, pct = k.crit_n ? Math.round((100 * k.crit_ok) / k.crit_n) + "%" : null;
    $("kpis").innerHTML =
      kpi("", "shield-check", "var(--ok)", "Critical in time", k.crit_ok, k.crit_n, pct ? `${pct} · ${k.crit_n} critical so far` : "none critical yet", SERIES.crit_ok, m,
        `${k.crit_ok} of the ${k.crit_n} critical patients who have arrived were reached within their deadline (${B.meta.critical_total} critical in the whole run).`) +
      kpi("", "users", "var(--info)", "Patients reached", k.reached, k.arrived, `of ${B.victims.length} in this run`, SERIES.reached, m,
        `${k.reached} of the ${k.arrived} patients who have arrived have had first medical contact.`) +
      kpi("", "heart-pulse", k.expectant ? "var(--text)" : "var(--text-2)", "Expectant", k.expectant, null, "missed deadline", SERIES.expectant, m,
        "Critical patients whose deadline passed without anyone reaching them in time (cumulative).") +
      kpi("w3", "git-compare", "var(--warn)", "Conflicts", k.conflicts, null, `${k.negotiated} settled by negotiation`, SERIES.conflicts, m,
        `${k.conflicts} times two agents wanted the same resource, ${k.negotiated} settled by negotiation.`) +
      kpi("w3", "clock", "var(--accent)", "Average response", k.resp_avg === null ? "–" : k.resp_avg, null, k.resp_avg === null ? "no patient reached yet" : "minutes to first contact", SERIES.resp_avg, m,
        "Average minutes from arrival to first medical contact, over patients reached so far.");

    const r = frame.res, amb = [["available", "free"], ["en_route", "en route"], ["on_scene", "on scene"], ["transporting", "transporting"]];
    $("resources").innerHTML =
      `<div class="res-group"><h4>Ambulances</h4><div class="chips">` + amb.map(([s, l]) =>
        `<span class="chip" style="--tone:${STATUS_COLOR[s]}" data-tip="Ambulances ${l}|${r.amb[s]} of ${B.ambulances.length}"><i></i><b>${r.amb[s]}</b><span>${l}</span></span>`).join("") + `</div></div>` +
      `<div class="res-group"><h4>Response teams</h4><div class="chips">` + r.teams.map(([kind, busy]) =>
        `<span class="chip ${busy ? "busy" : "free"}" style="--tone:${busy ? "var(--info)" : "var(--text-3)"}" data-tip="${TEAM_LABEL[kind]} team|${busy ? "busy" : "free"}"><i></i><span style="color:var(--text)">${TEAM_LABEL[kind]}</span><span>${busy ? "busy" : "free"}</span></span>`).join("") + `</div></div>`;

    $("hosps").innerHTML = B.hospitals.map((h, i) => {
      const [er, , promised, status] = frame.h[i], color = HOSPITAL_COLOR[status], cap = h.er_capacity;
      const occ = Math.min(er, cap), prom = Math.min(promised, Math.max(0, cap - er));
      const beds = Array.from({ length: cap }, (_, b) => `<i class="bed ${b < occ ? "occ" : b < occ + prom ? "prom" : ""}" style="--tone:${color}"></i>`).join("");
      const [dr, rn] = frame.s[i];
      return `<div class="card hosp" data-tip="${esc(h.name + "|" + h.id + " - " + er + " of " + cap + " ER beds in use" + (promised ? "|" + promised + " more on the way" : ""))}">` +
        `<div class="hosp-top"><span class="hosp-name">${esc(h.name)}</span><span class="status" style="--tone:${color}"><i></i>${status}</span></div>` +
        `<div class="beds">${beds}</div><div class="hosp-foot"><span>${er} of ${cap} beds in use${promised ? ` · +${promised} coming` : ""}</span><span>${h.doctors - dr} doctors, ${h.nurses - rn} nurses free</span></div></div>`;
    }).join("");

    renderTimeline(frame.n);
    renderSteps(m);
  }

  // Agent activity: items Python built (timeline.py); shown once all their messages have been seen
  let feedFilter = "all", shownItems = 0;
  document.querySelectorAll("#filter b").forEach((b) => b.addEventListener("click", () => {
    feedFilter = b.dataset.f;
    document.querySelectorAll("#filter b").forEach((o) => o.classList.toggle("on", o === b));
    renderTimeline(B.frames[shownMinute] ? B.frames[shownMinute].n : 0, true);
  }));
  function renderTimeline(n, keep) {
    const items = B.timeline.filter((x) => x.b < n && (feedFilter === "all" || STORY.has(x.type)));
    const fresh = keep ? 0 : Math.max(0, items.length - shownItems);
    shownItems = items.length;
    $("feedcount").textContent = items.length ? `${items.length} so far, newest first` : "";
    if (!items.length) { $("timeline").innerHTML = `<div class="empty">Nothing yet. Activity appears as the agents start working.</div>`; return; }
    $("timeline").innerHTML = items.slice(-60).reverse().map((x, i) => {
      const color = TYPE_COLOR[x.type] || "var(--text-3)";
      return `<div class="tl-item${i < fresh ? " new" : ""}" data-tip="${esc(x.tag + "|" + x.tip)}"><span class="tl-node" style="--tone:${color}">${ico(x.icon, 16)}</span>` +
        `<div class="tl-body"><div class="tl-text">${esc(x.text)}</div><div class="tl-meta"><span>${esc(x.who)}</span><span class="tl-tag" style="--tone:${color}">${esc(x.tag)}</span></div></div><span class="tl-time">Min ${x.t}</span></div>`;
    }).join("");
  }

  function renderSteps(m) {
    const c = [...B.conflicts].reverse().find((k) => k.t <= m);
    if (!c) {
      $("neg").innerHTML = `<div class="section-head"><h2>Latest negotiation</h2></div><div class="empty" style="padding:4px 0 8px">No conflict yet. When two agents want the same resource, the steps appear here.</div>`;
      return;
    }
    const idx = B.conflicts.indexOf(c) + 1;
    const stages = c.stages.map((st, i) => {
      const none = st.ref === null, done = !none && st.t <= m;
      const label = st.label === "Counter-offer" && none ? "Counter-offer" : st.label;
      return { st, cls: none ? "skip" : done ? "" : "todo", icon: none ? "x" : "circle-check", label, detail: none ? "not needed" : st.plain };
    });
    let last = -1; stages.forEach((s, i) => { if (s.cls === "") last = i; });
    const fill = last <= 0 ? 0 : (last / 3) * 75;
    $("neg").innerHTML = `<div class="section-head"><h2>Latest negotiation</h2><span class="sub">Conflict at minute ${c.t} · ${idx} of ${B.conflicts.length} in this run</span></div>` +
      `<div class="steps"><div class="fill" style="width:${fill}%"></div>` + stages.map((s) =>
        `<div class="step ${s.cls}" data-tip="${esc(s.label + "|" + (s.st.ref || "no message") + " - " + s.st.text)}"><span class="step-node">${ico(s.icon, s.cls === "skip" ? 12 : 18)}</span>` +
        `<div class="step-label">${esc(s.label)}</div><div class="step-detail">${esc(s.detail)}</div></div>`).join("") + `</div>`;
  }

  // ───────── Legend ─────────
  const dot = (c, extra) => `<i class="dot" style="background:${c};${extra || ""}"></i>`;
  $("legend").innerHTML =
    `<div class="row"><b>Patients</b><span>${dot("var(--triage-immediate)")}Immediate</span><span>${dot("var(--triage-delayed)")}Delayed</span><span>${dot("var(--triage-minor)")}Minor</span><span>${dot("var(--triage-expectant)", "box-shadow:0 0 0 1.5px #CBD5E1")}Expectant</span></div><i class="sep"></i>` +
    `<div class="row"><b>Units</b><span class="unit">${ico("ambulance", 16)}<em style="font-style:normal">Ambulance</em></span>` +
    `<span class="unit">${ico("ambulance", 16)}<em style="font-style:normal">ALS</em><span class="als-tag">ALS</span></span>` +
    `<span class="unit">${ico("users", 16)}<em style="font-style:normal">Response team</em></span>` +
    `<span class="unit" style="color:var(--text-2)">${ico("hospital", 16)}<em style="font-style:normal">Hospital</em></span></div>`;

  // On laptop widths the legend leaves the top bar and opens from a "Legend" button instead.
  $("legendbtn").innerHTML = `${ico("map", 16)} Legend`;
  const setLegend = (open) => { $("legend").classList.toggle("open", open); $("legendbtn").classList.toggle("on", open); $("legendbtn").setAttribute("aria-expanded", String(open)); };
  $("legendbtn").addEventListener("click", () => setLegend(!$("legend").classList.contains("open")));
  document.addEventListener("click", (e) => { if (!e.composedPath().some((n) => n === $("legend") || n === $("legendbtn"))) setLegend(false); });

  // ───────── Controls ─────────
  const scrub = $("scrub"), playBtn = $("play"), pauseBox = $("pausebox");
  let playing = false, speed = 1, last = null;
  scrub.max = N; $("last").textContent = String(N);
  function setPlaying(on) {
    playing = on; last = null;
    playBtn.innerHTML = ico(on ? "pause" : tau >= N ? "rotate-ccw" : "play", 20);
  }
  function jump(t) { tau = clamp(t, 0, N); render(tau); if (!playing) setPlaying(false); }
  function loop(now) {
    if (playing) {
      const before = tau;
      if (last !== null) tau += (Math.min(now - last, MAX_FRAME_MS) / 1000) * speed;
      last = now;
      const hit = pauseBox.checked && B.conflicts.find((c) => c.t > before && c.t <= tau);
      if (hit) { tau = hit.t; render(tau); setPlaying(false); }
      else if (tau >= N) { tau = N; render(tau); setPlaying(false); }
      else render(tau);
    }
    requestAnimationFrame(loop);
  }
  playBtn.addEventListener("click", () => { if (!playing && tau >= N) tau = 0; setPlaying(!playing); playBtn.blur(); });
  $("restart").innerHTML = ico("rotate-ccw", 16);
  $("restart").addEventListener("click", () => { tau = 0; render(tau); setPlaying(true); $("restart").blur(); });
  scrub.addEventListener("input", () => { tau = parseFloat(scrub.value); render(tau); if (!playing) setPlaying(false); });
  document.querySelectorAll("#speeds b").forEach((b) => b.addEventListener("click", () => {
    speed = parseFloat(b.dataset.speed);
    document.querySelectorAll("#speeds b").forEach((o) => o.classList.toggle("on", o === b));
  }));
  document.addEventListener("keydown", (e) => {
    if (e.target && (e.target.type === "checkbox" || e.target.tagName === "BUTTON" && e.code === "Space")) return;
    if (e.code === "Space") { e.preventDefault(); playBtn.click(); }
    else if (e.code === "ArrowRight") jump(Math.floor(tau) + 1);
    else if (e.code === "ArrowLeft") jump(Math.ceil(tau) - 1);
    else if (e.code === "KeyT") $("tour").click();
    else if (tourAt >= 0 && (e.code === "PageDown")) showTour(tourAt + 1);
    else if (tourAt >= 0 && (e.code === "PageUp")) showTour(tourAt - 1);
    else if (e.code === "Escape") { if (tourAt >= 0) endTour(); $("runpop").hidden = true; }
  });
  B.conflicts.forEach((c) => {
    const i = document.createElement("i");
    i.className = "cm"; i.style.left = `${(c.t / N) * 100}%`; i.innerHTML = ico("triangle-alert", 12);
    i.setAttribute("data-tip", `Conflict at minute ${c.t}|${c.plain}`);
    i.addEventListener("click", () => jump(c.t));
    $("cmarks").appendChild(i);
  });
  [...new Set(B.incidents.map((i) => i.arrival_min))].forEach((t) => {
    const i = document.createElement("i"); i.style.left = `${(t / N) * 100}%`; $("ticks").appendChild(i);
  });

  // ───────── Tour ─────────
  let tourAt = -1;
  function showTour(i) {
    const moments = B.tour || [];
    tourAt = clamp(i, 0, moments.length - 1);
    const mo = moments[tourAt];
    $("tour").classList.add("on");
    placeCorners();
    $("tourcard").hidden = false;
    $("tourcard").innerHTML = `<div class="step">Moment ${tourAt + 1} of ${moments.length} · minute ${mo.t}</div><h3>${esc(mo.title)}</h3><p>${esc(mo.caption)}</p>` +
      `<div class="nav"><button class="btn2" id="tback"${tourAt === 0 ? " disabled" : ""}>${ico("chevron-left", 16)}Back</button>` +
      `<button class="btn" id="tnext"${tourAt === moments.length - 1 ? " disabled" : ""}>Next${ico("chevron-right", 16)}</button><span class="spacer"></span>` +
      `<button class="btn2" id="tend">${ico("x", 16)}End tour</button></div>`;
    setPlaying(false); jump(mo.t);
  }
  function endTour() { tourAt = -1; $("tourcard").hidden = true; $("tour").classList.remove("on"); }
  $("tour").addEventListener("click", () => { if (tourAt < 0) showTour(0); else endTour(); $("tour").blur(); });
  $("tourcard").addEventListener("click", (e) => {
    if (e.target.closest("#tnext")) showTour(tourAt + 1);
    else if (e.target.closest("#tback")) showTour(tourAt - 1);
    else if (e.target.closest("#tend")) endTour();
  });
  if (!(B.tour && B.tour.length)) $("tour").hidden = true;

  // ───────── Start ─────────
  window.addEventListener("resize", () => { build(); });
  const startAt = /[#&]m=(\d+)/.exec(window.location.hash);          // page.html#m=6 opens at minute 6 (handy for screenshots)
  if (startAt) tau = clamp(parseInt(startAt[1], 10), 0, N);
  setPlaying(false);
  build();
  requestAnimationFrame(loop);
  window.__app = { jump, render: (t) => { tau = t; render(t); }, bundle: B, state: () => ({ tau, playing, speed, tourAt }), showTour, build };
})();
