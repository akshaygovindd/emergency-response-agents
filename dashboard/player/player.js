// Replay player: draws frames that Python precomputed (see src/erc/dashboard/export.py).
// No logic about the emergency lives here: only drawing, interpolation between minutes, and controls.
(() => {
  "use strict";
  const B = JSON.parse(document.getElementById("bundle").textContent);
  const N = B.meta.last_minute, KM = B.meta.grid_km;
  const S = 40, M = 40, W = 880;                       // svg units per km, margin, viewBox size
  const SECONDS_PER_MINUTE = 1.0;                      // at 1x one simulated minute takes one second
  const MAX_FRAME_MS = 500;                            // longest step one frame may advance (guards against a stalled tab)
  const FADE_MIN = 2.0;                                // a reached victim fades out over 2 minutes
  const NS = "http://www.w3.org/2000/svg";

  const PALETTE = {
    immediate: "#e4574f", delayed: "#ecc24a", minor: "#54b87a", expectant: "#06090d", reached: "#9db0c6",
    ring: "#4aa3a0", ringWarn: "#d9a441", ringFull: "#d9594c", promised: "#8fb8de",
    available: "#7f93aa", en_route: "#e0a64a", on_scene: "#5fb3a5", transporting: "#e07b54",
    fire: "#d98558", rescue: "#6c9bd1", medical: "#a78bd6", route: "#8fa6c2",
  };
  const CODE_COLOR = [null, PALETTE.immediate, PALETTE.delayed, PALETTE.minor, PALETTE.expectant, PALETTE.reached];
  const X = (x) => M + x * S, Y = (y) => M + (KM - y) * S;

  const el = (tag, attrs, parent) => {
    const e = document.createElementNS(NS, tag);
    for (const k in attrs || {}) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  };
  const text = (parent, str, x, y, size, fill, extra) => {
    const t = el("text", Object.assign({ x, y, "font-size": size, fill, "text-anchor": "middle",
      "font-family": "-apple-system, 'Segoe UI', system-ui, sans-serif" }, extra || {}), parent);
    t.textContent = str;
    return t;
  };

  // ───────── Static map ─────────
  const svg = document.getElementById("map");
  el("rect", { x: 0, y: 0, width: W, height: W, rx: 14, fill: "#0e1621" }, svg);
  const districts = el("g", {}, svg);
  const cell = (KM / 4) * S;                           // 5 km districts, alternating shade
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) {
    el("rect", { x: M + i * cell, y: M + j * cell, width: cell, height: cell,
      fill: (i + j) % 2 ? "#142030" : "#111b29" }, districts);
  }
  const grid = el("g", { stroke: "#1b293b", "stroke-width": 1 }, svg);
  for (let k = 0; k <= KM; k++) {
    const major = k % 5 === 0;
    const attrs = { stroke: major ? "#2a3b52" : "#16222f", "stroke-width": major ? 1.4 : 0.8 };
    el("line", Object.assign({ x1: M + k * S, y1: M, x2: M + k * S, y2: M + KM * S }, attrs), grid);
    el("line", Object.assign({ x1: M, y1: M + k * S, x2: M + KM * S, y2: M + k * S }, attrs), grid);
    if (major) {
      text(svg, String(k), M + k * S, M + KM * S + 22, 14, "#6f8196");
      text(svg, String(k), M - 14, M + (KM - k) * S + 5, 14, "#6f8196");
    }
  }
  text(svg, "km east", M + (KM * S) / 2, W - 6, 13, "#58697d");
  text(svg, "km north", 12, M + (KM * S) / 2, 13, "#58697d", { transform: `rotate(-90 12 ${M + (KM * S) / 2})` });

  const routeLayer = el("g", {}, svg), incidentLayer = el("g", {}, svg), hospitalLayer = el("g", {}, svg);
  const unitLayer = el("g", {}, svg), labelLayer = el("g", {}, svg);

  // ───────── Places ─────────
  const where = {};
  B.hospitals.forEach((h) => (where[h.id] = [h.x, h.y]));
  B.incidents.forEach((i) => (where[i.id] = [i.x, i.y]));

  const hospitals = B.hospitals.map((h) => {
    const g = el("g", { transform: `translate(${X(h.x)},${Y(h.y)})` }, hospitalLayer);
    const R = 36, C = 2 * Math.PI * R;
    el("circle", { r: R, fill: "none", stroke: "#1f2d40", "stroke-width": 8 }, g);
    const occ = el("circle", { r: R, fill: "none", "stroke-width": 8, transform: "rotate(-90)" }, g);
    const prom = el("circle", { r: R, fill: "none", stroke: PALETTE.promised, "stroke-width": 8,
      opacity: 0.55, transform: "rotate(-90)" }, g);
    el("rect", { x: -19, y: -19, width: 38, height: 38, rx: 8, fill: "#173149", stroke: "#365c82", "stroke-width": 1.5 }, g);
    el("path", { d: "M-3.5,-11 h7 v7.5 h7.5 v7 h-7.5 v7.5 h-7 v-7.5 h-7.5 v-7 h7.5 z", fill: "#e7eef7" }, g);
    const name = text(g, `${h.id}  ${h.label}`, 0, R + 24, 19, "#e3eaf3", { "font-weight": 700 });
    const load = text(g, "", 0, R + 44, 15, "#9fb1c6");
    return { h, C, occ, prom, load, name };
  });

  const incidents = B.incidents.map((inc) => {
    const g = el("g", { transform: `translate(${X(inc.x)},${Y(inc.y)})`, opacity: 0 }, incidentLayer);
    el("circle", { r: 24, fill: "none", stroke: "#3b4d66", "stroke-width": 1.5, "stroke-dasharray": "3 4" }, g);
    text(g, inc.id.replace("INC-", "INC "), 0, 41, 14, "#8a9bb0");
    const mine = B.victims.map((v, i) => [v, i]).filter(([v]) => v.incident === inc.id);
    const dots = mine.map(([v, i], k) => {
      const ang = (2 * Math.PI * k) / mine.length - Math.PI / 2, r = mine.length > 1 ? 11.5 : 0;
      const c = el("circle", { cx: Math.cos(ang) * r, cy: Math.sin(ang) * r, r: 6, "stroke-width": 1.6 }, g);
      return { v, i, c };
    });
    return { inc, g, dots };
  });

  // ───────── Units ─────────
  const trips = {};
  B.trips.forEach((t) => (trips[t.unit] = trips[t.unit] || []).push(t));
  const ambulances = B.ambulances.map((a, idx) => {
    const route = el("line", { stroke: PALETTE.route, "stroke-width": 2, "stroke-dasharray": "6 6", opacity: 0 }, routeLayer);
    const g = el("g", {}, unitLayer), body = el("g", {}, g);
    const shape = el("rect", { x: -17, y: -9, width: 34, height: 18, rx: 6, stroke: "#0b1118", "stroke-width": 1.5 }, body);
    const mark = el("path", { d: "M-2.5,-6 h5 v3.5 h3.5 v5 h-3.5 v3.5 h-5 v-3.5 h-3.5 v-5 h3.5 z", fill: "#0b1118", opacity: 0.8 }, body);
    const count = text(body, "", 0, 5, 14, "#0b1118", { "font-weight": 800 });
    const tag = el("g", {}, labelLayer);
    const name = text(tag, a.id.replace("AMB-", "A").replace(/^A0/, "A"), 0, 0, 13, "#cfd9e6", { "font-weight": 600 });
    let als = null;
    if (a.als) {
      als = el("g", {}, tag);
      el("rect", { x: -13, y: 5, width: 26, height: 13, rx: 6.5, fill: "#2b2412", stroke: "#c9a23c", "stroke-width": 1 }, als);
      text(als, "ALS", 0, 15, 10, "#e7c15a", { "font-weight": 700 });
    }
    return { a, idx, route, g, body, shape, mark, count, tag, angle: 0 };
  });
  const KIND_LETTER = { fire: "F", rescue: "R", medical: "M" };
  const responders = B.responders.map((r, idx) => {
    const route = el("line", { stroke: PALETTE[r.kind] || PALETTE.route, "stroke-width": 1.6, "stroke-dasharray": "3 6", opacity: 0 }, routeLayer);
    const g = el("g", {}, unitLayer);
    const shape = el("path", { d: "M0,-11 L11,0 L0,11 L-11,0 Z", fill: PALETTE[r.kind] || "#aaa", stroke: "#0b1118", "stroke-width": 1.5 }, g);
    text(g, KIND_LETTER[r.kind] || "?", 0, 4.5, 12, "#0b1118", { "font-weight": 800 });
    const tag = text(labelLayer, r.id.replace("-1", ""), 0, 0, 12, "#9fb1c6");
    return { r, idx, route, g, shape, tag };
  });

  // ───────── Interpolation ─────────
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  function position(unitId, tau, frameXY) {
    const list = trips[unitId];
    if (list) for (const t of list) {
      if (tau >= t.t0 && tau <= t.t1) {
        const f = t.t1 === t.t0 ? 1 : (tau - t.t0) / (t.t1 - t.t0);
        return { x: t.x0 + (t.x1 - t.x0) * f, y: t.y0 + (t.y1 - t.y0) * f, trip: t };
      }
    }
    return { x: frameXY[0], y: frameXY[1], trip: null };
  }

  // ───────── Drawing one moment ─────────
  function ringColor(frac) { return frac >= 0.85 ? PALETTE.ringFull : frac >= 0.6 ? PALETTE.ringWarn : PALETTE.ring; }

  function render(tau) {
    const m = Math.min(N, Math.floor(tau)), frame = B.frames[m];

    hospitals.forEach((hs, i) => {
      const [er, , promised] = frame.h[i], cap = hs.h.er_capacity;
      const occArc = Math.min(1, er / cap) * hs.C, promArc = Math.min(promised, cap - er) / cap * hs.C;
      hs.occ.setAttribute("stroke", ringColor((er + promised) / cap));
      hs.occ.setAttribute("stroke-dasharray", `${occArc} ${hs.C - occArc}`);
      hs.prom.setAttribute("stroke-dasharray", `${Math.max(0, promArc)} ${hs.C - Math.max(0, promArc)}`);
      hs.prom.setAttribute("stroke-dashoffset", -occArc);
      hs.load.textContent = `ER ${er}/${cap}` + (promised ? `  +${promised} on the way` : "");
    });

    incidents.forEach((is) => {
      const arrived = m >= is.inc.arrival_min;
      let anyOpen = false;
      is.dots.forEach(({ v, i, c }) => {
        const code = frame.v[i];
        if (code === 0) { c.setAttribute("opacity", 0); return; }
        if (code === 5) {
          const f = clamp(1 - (tau - v.contact_min) / FADE_MIN, 0, 1);
          c.setAttribute("fill", PALETTE.reached); c.setAttribute("stroke", "none");
          c.setAttribute("opacity", f * 0.9); c.setAttribute("r", 3 + 3 * f);
          return;
        }
        anyOpen = true;
        c.setAttribute("fill", CODE_COLOR[code]); c.setAttribute("r", 6);
        c.setAttribute("stroke", code === 4 ? "#e8edf3" : "#0b1118");
        c.setAttribute("opacity", 1);
      });
      is.g.setAttribute("opacity", arrived ? (anyOpen ? 1 : 0.35) : 0);
    });

    const place = (unit, xy, tagDy) => {
      const px = X(xy.x), py = Y(xy.y);
      unit.g.setAttribute("transform", `translate(${px},${py})`);
      return [px, py];
    };
    ambulances.forEach((u) => {
      const fa = frame.a[u.idx], pos = position(u.a.id, tau, fa);
      const [px, py] = place(u, pos);
      if (pos.trip) u.angle = (Math.atan2(-(pos.trip.y1 - pos.trip.y0), pos.trip.x1 - pos.trip.x0) * 180) / Math.PI;
      u.body.setAttribute("transform", `rotate(${(u.angle > 90 || u.angle < -90) ? u.angle + 180 : u.angle})`);
      u.shape.setAttribute("fill", PALETTE[fa[2]] || PALETTE.available);
      u.mark.setAttribute("opacity", fa[4] ? 0 : 0.8);
      u.count.textContent = fa[4] ? String(fa[4]) : "";
      u.tag.setAttribute("transform", `translate(${px},${py - 17})`);
      const target = fa[3] && where[fa[3]];
      const moving = fa[2] === "en_route" || fa[2] === "transporting";
      if (moving && target) {
        u.route.setAttribute("x1", px); u.route.setAttribute("y1", py);
        u.route.setAttribute("x2", X(target[0])); u.route.setAttribute("y2", Y(target[1]));
        u.route.setAttribute("stroke", PALETTE[fa[2]]); u.route.setAttribute("opacity", 0.55);
      } else u.route.setAttribute("opacity", 0);
    });
    responders.forEach((u) => {
      const fr = frame.r[u.idx], pos = position(u.r.id, tau, fr);
      const [px, py] = place(u, pos);
      u.g.setAttribute("opacity", fr[2] === "available" ? 0.6 : 1);
      u.tag.setAttribute("transform", `translate(${px},${py + 25})`);
      const target = fr[3] && where[fr[3]];
      if (fr[2] === "en_route" && target) {
        u.route.setAttribute("x1", px); u.route.setAttribute("y1", py);
        u.route.setAttribute("x2", X(target[0])); u.route.setAttribute("y2", Y(target[1]));
        u.route.setAttribute("opacity", 0.5);
      } else u.route.setAttribute("opacity", 0);
    });

    document.getElementById("min").textContent = String(m);
    scrub.value = tau;
  }

  // ───────── Controls ─────────
  const scrub = document.getElementById("scrub"), playBtn = document.getElementById("play");
  let tau = 0, playing = false, speed = 1, last = null;
  scrub.max = N;
  document.getElementById("last").textContent = String(N);
  const meta = B.meta;
  document.getElementById("runlabel").innerHTML =
    `${meta.scenario} &middot; run ${meta.run_number} (seed ${meta.seed})<br>${meta.mode} &middot; ${meta.version}`;

  function setPlaying(on) {
    playing = on; last = null;
    playBtn.innerHTML = on ? "&#10074;&#10074; Pause" : (tau >= N ? "&#8634; Replay" : "&#9654; Play");
  }
  function jump(t) { tau = clamp(t, 0, N); render(tau); if (!playing) setPlaying(false); }

  function loop(now) {
    if (playing) {
      if (last !== null) tau += (Math.min(now - last, MAX_FRAME_MS) / 1000) * speed / SECONDS_PER_MINUTE;   // no jumps after a stall
      last = now;
      if (tau >= N) { tau = N; render(tau); setPlaying(false); }
      else render(tau);
    }
    requestAnimationFrame(loop);
  }

  playBtn.addEventListener("click", () => {
    if (!playing && tau >= N) tau = 0;
    setPlaying(!playing);
  });
  document.getElementById("restart").addEventListener("click", () => { tau = 0; render(tau); setPlaying(true); });
  scrub.addEventListener("input", () => { tau = parseFloat(scrub.value); render(tau); if (!playing) setPlaying(false); });
  document.querySelectorAll("#speeds button").forEach((b) => b.addEventListener("click", () => {
    speed = parseFloat(b.dataset.speed);
    document.querySelectorAll("#speeds button").forEach((o) => o.classList.toggle("on", o === b));
  }));
  document.addEventListener("keydown", (e) => {
    if (e.code === "Space") { e.preventDefault(); playBtn.click(); }
    else if (e.code === "ArrowRight") jump(Math.floor(tau) + 1);
    else if (e.code === "ArrowLeft") jump(Math.ceil(tau) - 1);
  });

  // Incident arrival ticks under the scrubber
  const ticks = document.getElementById("ticks");
  [...new Set(B.incidents.map((i) => i.arrival_min))].forEach((t) => {
    const i = document.createElement("i");
    i.style.left = `${(t / N) * 100}%`;
    ticks.appendChild(i);
  });

  // ───────── Legend (same palette as the map) ─────────
  const legend = document.getElementById("legend");
  const sw = (inner) => `<svg viewBox="0 0 28 20">${inner}</svg>`;
  const dot = (fill, stroke) => sw(`<circle cx="14" cy="10" r="6" fill="${fill}" stroke="${stroke || "none"}" stroke-width="1.6"/>`);
  const row = (icon, label, sub) => `<div class="row">${icon}<span>${label}${sub ? ` <span class="sub">${sub}</span>` : ""}</span></div>`;
  legend.innerHTML =
    `<div><h4>Victim triage (START)</h4>` +
    row(dot(PALETTE.immediate), "Immediate", "severity 4-5") +
    row(dot(PALETTE.delayed), "Delayed", "severity 3") +
    row(dot(PALETTE.minor), "Minor", "severity 1-2") +
    row(dot(PALETTE.expectant, "#e8edf3"), "Expectant", "critical, deadline passed") +
    row(dot(PALETTE.reached), "Reached", "fades out") + `</div>` +
    `<div><h4>Units</h4>` +
    row(sw(`<rect x="-3" y="1" width="34" height="18" rx="6" fill="${PALETTE.en_route}"/><path d="M11.5,4 h5 v3.5 h3.5 v5 h-3.5 v3.5 h-5 v-3.5 h-3.5 v-5 h3.5 z" fill="#0b1118" opacity=".8"/>`), "Ambulance", "ALS tagged") +
    row(sw(`<path d="M14,0 L24,10 L14,20 L4,10 Z" fill="${PALETTE.fire}"/>`), "Fire / rescue / medical team", "F R M") +
    row(sw(`<line x1="0" y1="10" x2="28" y2="10" stroke="${PALETTE.route}" stroke-width="2" stroke-dasharray="6 6"/>`), "Route to target") + `</div>` +
    `<div><h4>Hospital ER load</h4>` +
    row(sw(`<circle cx="14" cy="10" r="8" fill="none" stroke="${PALETTE.ring}" stroke-width="4" stroke-dasharray="25 26" transform="rotate(-90 14 10)"/>`), "Occupied beds") +
    row(sw(`<circle cx="14" cy="10" r="8" fill="none" stroke="${PALETTE.promised}" stroke-width="4" opacity=".55" stroke-dasharray="12 39" transform="rotate(-90 14 10)"/>`), "Promised", "patient on the way") + `</div>`;

  render(0);
  setPlaying(false);
  requestAnimationFrame(loop);
  window.__player = { jump, render, bundle: B, state: () => ({ tau, playing, speed }) };   // handy for tests
})();
