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
  const STATUS_COLOR = { "Stable": "#4aa3a0", "Moderate": "#d9a441", "Near capacity": "#d9594c" };
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
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
    t.style.paintOrder = "stroke"; t.style.stroke = "#0e1621"; t.style.strokeWidth = "4px"; t.style.strokeLinejoin = "round";   // halo keeps labels readable
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
  text(svg, "km east", M + KM * S * 0.625, W - 6, 13, "#58697d");     // between two tick numbers, so it never sits on one
  text(svg, "km north", 12, M + KM * S * 0.125, 13, "#58697d", { transform: `rotate(-90 12 ${M + KM * S * 0.125})` });

  const routeLayer = el("g", {}, svg), incidentLayer = el("g", {}, svg), hospitalLayer = el("g", {}, svg);
  const conflictLayer = el("g", {}, svg), unitLayer = el("g", {}, svg), labelLayer = el("g", {}, svg);

  // ───────── Label placement (keeps unit tags off other labels) ─────────
  function rectAt(cx, cy, w, h) { return { x0: cx - w / 2, y0: cy - h / 2, x1: cx + w / 2, y1: cy + h / 2 }; }
  const overlap = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
  const TAG_SPOTS = [[0, -19], [0, 31], [0, -36], [0, 47], [46, 5], [-46, 5]];   // tag offsets tried in order

  // Incident labels try below, above, right, left of their ring; a label never sits on another label or ring.
  const LABEL_SPOTS = [[0, 41], [0, -31], [52, 5], [-52, 5]];
  function placeIncidentLabels(m, taken) {
    const live = incidents.filter((is) => m >= is.inc.arrival_min && !is.resolved);
    const placed = [];
    live.forEach((is) => {
      const cx = X(is.inc.x), cy = Y(is.inc.y);
      const others = [...hospitals.flatMap((hs) => hs.box), ...placed,
        ...live.filter((o) => o !== is).map((o) => rectAt(X(o.inc.x), Y(o.inc.y), 54, 54))];
      const order = LABEL_SPOTS.map((_, k) => (is.spot + k) % LABEL_SPOTS.length);   // last spot first: no flicker
      const fits = (k) => !others.some((o) => overlap(rectAt(cx + LABEL_SPOTS[k][0], cy + LABEL_SPOTS[k][1] - 5, 54, 16), o));
      const pick = order.find(fits);
      is.spot = pick === undefined ? is.spot : pick;
      const [dx, dy] = LABEL_SPOTS[is.spot];
      is.label.setAttribute("x", dx); is.label.setAttribute("y", dy);
      is.box = rectAt(cx + dx, cy + dy - 5, 54, 16);
      placed.push(is.box);
    });
    placed.forEach((b) => taken.push(b));
  }

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
    const above = Y(h.y) + R + 52 > W;                 // keep the labels on the map near the bottom edge
    const nameY = above ? -R - 30 : R + 24, loadY = above ? -R - 10 : R + 44;
    const name = text(g, `${h.id}  ${h.label}`, 0, nameY, 19, "#e3eaf3", { "font-weight": 700 });
    const load = text(g, "", 0, loadY, 15, "#9fb1c6");
    const px = X(h.x), py = Y(h.y);
    const labels = el("g", { transform: `translate(${px},${py})` }, labelLayer);   // above the units, so parked ones never hide the name
    labels.appendChild(name); labels.appendChild(load);
    const box = [rectAt(px, py + nameY - 6, 12 + h.id.length * 11 + h.label.length * 10.5, 22),
                 rectAt(px, py + loadY - 5, 150, 18)];
    return { h, C, occ, prom, load, name, box };
  });

  const incidents = B.incidents.map((inc) => {
    const g = el("g", { transform: `translate(${X(inc.x)},${Y(inc.y)})`, opacity: 0 }, incidentLayer);
    el("circle", { r: 24, fill: "none", stroke: "#3b4d66", "stroke-width": 1.5, "stroke-dasharray": "3 4" }, g);
    const label = text(g, inc.id.replace("INC-", "INC "), 0, 41, 14, "#8a9bb0");
    const mine = B.victims.map((v, i) => [v, i]).filter(([v]) => v.incident === inc.id);
    const dots = mine.map(([v, i], k) => {
      const ang = (2 * Math.PI * k) / mine.length - Math.PI / 2, r = mine.length > 1 ? 11.5 : 0;
      const c = el("circle", { cx: Math.cos(ang) * r, cy: Math.sin(ang) * r, r: 6, "stroke-width": 1.6 }, g);
      return { v, i, c };
    });
    return { inc, g, dots, label, resolved: false, spot: 0, box: rectAt(X(inc.x), Y(inc.y) + 36, 54, 16) };
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
    const tag = text(labelLayer, a.id.replace("AMB-", "A").replace(/^A0/, "A"), 0, 0, 13, "#cfd9e6", { "font-weight": 600 });
    if (a.als) {
      const als = el("tspan", { fill: "#e7c15a", "font-weight": 700, "font-size": 10.5, dx: 4 }, tag);
      als.textContent = "ALS";
    }
    return { a, idx, route, g, body, shape, mark, count, tag, size: a.als ? [46, 15] : [22, 15], spot: 0, angle: 0 };
  });
  const KIND_LETTER = { fire: "F", rescue: "R", medical: "M" };
  const responders = B.responders.map((r, idx) => {
    const route = el("line", { stroke: PALETTE[r.kind] || PALETTE.route, "stroke-width": 1.6, "stroke-dasharray": "3 6", opacity: 0 }, routeLayer);
    const g = el("g", {}, unitLayer);
    const shape = el("path", { d: "M0,-11 L11,0 L0,11 L-11,0 Z", fill: PALETTE[r.kind] || "#aaa", stroke: "#0b1118", "stroke-width": 1.5 }, g);
    text(g, KIND_LETTER[r.kind] || "?", 0, 4.5, 12, "#0b1118", { "font-weight": 800 });
    const tag = text(labelLayer, r.id.replace("-1", ""), 0, 0, 12, "#9fb1c6");
    return { r, idx, route, g, shape, tag, size: [r.id.length * 7, 14], spot: 1 };
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

  function render(tau) {
    const m = Math.min(N, Math.floor(tau)), frame = B.frames[m];

    hospitals.forEach((hs, i) => {
      const [er, , promised, status] = frame.h[i], cap = hs.h.er_capacity;
      const occArc = Math.min(1, er / cap) * hs.C, promArc = Math.min(promised, cap - er) / cap * hs.C;
      hs.occ.setAttribute("stroke", STATUS_COLOR[status]);
      hs.occ.setAttribute("stroke-dasharray", `${occArc} ${hs.C - occArc}`);
      hs.prom.setAttribute("stroke-dasharray", `${Math.max(0, promArc)} ${hs.C - Math.max(0, promArc)}`);
      hs.prom.setAttribute("stroke-dashoffset", -occArc);
      hs.load.textContent = `ER ${er}/${cap}` + (promised ? `  +${promised} coming` : "");
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
      is.resolved = arrived && !anyOpen;                // fully resolved: no label, strongly faded
      is.label.setAttribute("opacity", is.resolved ? 0 : 1);
      is.g.setAttribute("opacity", arrived ? (anyOpen ? 1 : 0.16) : 0);
    });

    const taken = [];                                  // label boxes tags must stay clear of
    hospitals.forEach((hs) => hs.box.forEach((b) => taken.push(b)));
    placeIncidentLabels(m, taken);
    const place = (unit, xy) => {
      const px = X(xy.x), py = Y(xy.y);
      unit.g.setAttribute("transform", `translate(${px},${py})`);
      unit.px = px; unit.py = py;
      taken.push(rectAt(px, py, unit.a ? 38 : 26, 22));
      return [px, py];
    };
    ambulances.forEach((u) => {
      const fa = frame.a[u.idx], pos = position(u.a.id, tau, fa);
      const [px, py] = place(u, pos);
      if (pos.trip) u.angle = (Math.atan2(-(pos.trip.y1 - pos.trip.y0), pos.trip.x1 - pos.trip.x0) * 180) / Math.PI;
      u.body.setAttribute("transform", `rotate(${(u.angle > 90 || u.angle < -90) ? u.angle + 180 : u.angle})`);
      u.shape.setAttribute("fill", PALETTE[fa[2]] || PALETTE.available);
      u.mark.setAttribute("opacity", fa[4] ? 0 : 0.8);
      u.g.setAttribute("opacity", fa[2] === "available" ? 0.7 : 1);
      u.tag.setAttribute("opacity", fa[2] === "available" ? 0.6 : 1);
      u.count.textContent = fa[4] ? String(fa[4]) : "";
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
      u.tag.setAttribute("opacity", fr[2] === "available" ? 0.55 : 1);
      const target = fr[3] && where[fr[3]];
      if (fr[2] === "en_route" && target) {
        u.route.setAttribute("x1", px); u.route.setAttribute("y1", py);
        u.route.setAttribute("x2", X(target[0])); u.route.setAttribute("y2", Y(target[1]));
        u.route.setAttribute("opacity", 0.5);
      } else u.route.setAttribute("opacity", 0);
    });
    // Tags last, so each one can steer clear of hospital and incident labels, unit bodies, and earlier tags.
    const fixed = taken.slice();
    [...ambulances, ...responders].forEach((u) => {
      const [w, h] = u.size;
      const order = TAG_SPOTS.map((_, k) => (u.spot + k) % TAG_SPOTS.length);     // try last spot first: no flicker
      let pick = order.find((k) => {
        const box = rectAt(u.px + TAG_SPOTS[k][0], u.py + TAG_SPOTS[k][1] - 4, w, h);
        return !fixed.some((o) => overlap(box, o));
      });
      if (pick === undefined) pick = u.spot;
      u.spot = pick;
      const box = rectAt(u.px + TAG_SPOTS[pick][0], u.py + TAG_SPOTS[pick][1] - 4, w, h);
      fixed.push(box);
      u.tag.setAttribute("transform", `translate(${u.px + TAG_SPOTS[pick][0]},${u.py + TAG_SPOTS[pick][1]})`);
    });
    drawConflict(m);
    if (m !== shownMinute) { shownMinute = m; panels(m, frame); }

    $("min").textContent = String(m);
    scrub.value = tau;
  }

  // ───────── Conflict callout on the map ─────────
  // The callout sits on the top or bottom edge, whichever leaves the involved incidents and unit clear.
  // The callout goes where it covers the least: bottom or top edge first, then the four corners. Involved incidents and
  // the contested unit count most; hospital rings and labels, other units and other incidents count too.
  function placeCallout(c, m) {
    const k = W / $("mapwrap").clientWidth, w = callout.offsetWidth * k, h = callout.offsetHeight * k, edge = 8 * k, low = 44 * k;
    const involved = c.incidents.map((id) => where[id]).filter(Boolean).map((a) => rectAt(X(a[0]), Y(a[1]), 70, 70));
    const unit = [...ambulances, ...responders].find((u) => c.resources.includes((u.a || u.r).id));
    if (unit) involved.push(rectAt(unit.px, unit.py, 60, 50));
    const others = [...hospitals.flatMap((hs) => [...hs.box, rectAt(X(hs.h.x), Y(hs.h.y), 84, 84)]),
      ...[...ambulances, ...responders].map((u) => rectAt(u.px, u.py, 44, 30)),
      ...incidents.filter((is) => m >= is.inc.arrival_min && !is.resolved).flatMap((is) => [is.box, rectAt(X(is.inc.x), Y(is.inc.y), 54, 54)])];
    const cx0 = (W - w) / 2, right = W - edge - w;
    const spots = [["bottom", cx0, W - low - h], ["top", cx0, edge], ["bl", edge, W - low - h], ["br", right, W - low - h],
                   ["tl", edge, edge], ["tr", right, edge]];
    let best = null;
    spots.forEach(([name, x, y]) => {
      const box = { x0: x, y0: y, x1: x + w, y1: y + h };
      const score = 100 * involved.filter((o) => overlap(box, o)).length + others.filter((o) => overlap(box, o)).length;
      if (!best || score < best.score) best = { name, score };
    });
    const at = best.name, v = at[0] === "t" || at === "top" ? "top" : "bottom";
    callout.style.top = v === "top" ? "8px" : "auto"; callout.style.bottom = v === "top" ? "auto" : "44px";
    const side = at === "top" || at === "bottom" ? "center" : at[1] === "l" ? "left" : "right";
    callout.style.left = side === "center" ? "50%" : side === "left" ? "8px" : "auto";
    callout.style.right = side === "right" ? "8px" : "auto";
    callout.style.transform = side === "center" ? "translateX(-50%)" : "none";
  }
  const CALLOUT_MIN = 3;                               // a conflict stays on the map for 3 simulated minutes
  const callout = $("callout");
  const lines = [];
  function drawConflict(m) {
    const c = [...B.conflicts].reverse().find((k) => k.t <= m && m < k.t + CALLOUT_MIN);
    while (lines.length) conflictLayer.removeChild(lines.pop());
    if (!c) { callout.hidden = true; return; }
    callout.hidden = false;
    callout.innerHTML = `<b>CONFLICT</b>&middot; ${esc(c.text)}`;
    placeCallout(c, m);
    const unit = [...ambulances, ...responders].find((u) => c.resources.includes((u.a || u.r).id));
    const hosp = hospitals.find((hs) => c.resources.includes(hs.h.id));
    const from = unit ? [unit.px, unit.py] : hosp ? [X(hosp.h.x), Y(hosp.h.y)] : null;
    if (!from) return;
    c.incidents.forEach((id) => {
      const at = where[id];
      if (at) lines.push(el("line", { x1: from[0], y1: from[1], x2: X(at[0]), y2: Y(at[1]), stroke: "#e4574f",
        "stroke-width": 2.2, "stroke-dasharray": "7 5", class: "pulse" }, conflictLayer));
    });
    lines.push(el("circle", { cx: from[0], cy: from[1], r: 26, fill: "none", stroke: "#e4574f", "stroke-width": 2.5, class: "pulse" }, conflictLayer));
  }

  // ───────── Side panels (rebuilt once per simulated minute) ─────────
  let shownMinute = -1, shownMessages = 0;
  const AMB_LABEL = { available: "available", en_route: "en route", on_scene: "on scene", transporting: "transporting" };
  const fmt = (v, unit) => (v === null || v === undefined ? "n/a" : v + (unit || ""));

  function kpiCard(cls, cap, val, of, note, tip) {
    return `<div class="kpi ${cls}" title="${esc(tip || "")}"><div class="cap">${cap}</div><div class="val">${val}${of ? `<span class="of"> / ${of}</span>` : ""}</div><div class="note">${note}</div></div>`;
  }
  function panels(m, frame) {
    const k = frame.k;
    const pct = k.crit_n ? Math.round((100 * k.crit_ok) / k.crit_n) + "%" : null;
    $("kpis").innerHTML =
      kpiCard("wide", "Critical in time", k.crit_ok, k.crit_n, pct ? `${pct} &middot; ${k.crit_n} critical` : "none critical yet",
        `${k.crit_ok} of the ${k.crit_n} critical victims who have arrived were reached within their deadline (${B.meta.critical_total} critical in the whole run).`) +
      kpiCard("wide", "Reached", k.reached, k.arrived, `of ${B.victims.length} in run`,
        `${k.reached} of the ${k.arrived} victims who have arrived have had first medical contact (${B.victims.length} victims in the whole run).`) +
      kpiCard(k.expectant ? "bad" : "", "Expectant", k.expectant, null, "missed deadline",
        "Critical victims whose deadline passed without first medical contact in time (cumulative).") +
      kpiCard("", "Conflicts", k.conflicts, null, `${k.negotiated} negotiated`,
        `${k.conflicts} resource conflicts detected so far, ${k.negotiated} settled by negotiation.`) +
      kpiCard("", "Avg response", fmt(k.resp_avg, " min"), null, "to first contact",
        "Average minutes from arrival to first medical contact, over victims reached so far.");

    $("hospitals").innerHTML = B.hospitals.map((h, i) => {
      const [er, , promised, status] = frame.h[i], cap = h.er_capacity, prom = Math.min(promised, Math.max(0, cap - er));
      const occ = Math.min(er, cap);
      const beds = Array.from({ length: cap }, (_, b) =>
        `<i class="bed ${b < occ ? "occ" : b < occ + prom ? "prom" : ""}" ${b < occ ? `style="background:${STATUS_COLOR[status]}"` : ""}></i>`).join("");
      return `<div class="hcard" title="${esc(h.id + " " + h.label)}"><div class="name">${esc(h.id)}<span>${esc(h.label)}</span></div>` +
        `<div class="state" style="color:${STATUS_COLOR[status]}"><i style="background:${STATUS_COLOR[status]}"></i>${status}</div>` +
        `<div class="beds" title="occupied / promised / free ER beds">${beds}</div>` +
        `<div class="meta" title="${esc(`ER ${er} of ${cap} beds occupied` + (promised ? `, ${promised} more patients on the way` : ""))}">ER ${er}/${cap}${promised ? ` &middot; +${promised} coming` : ""}</div></div>`;
    }).join("");

    const r = frame.res, ambChips = Object.entries(r.amb).map(([state, n]) =>
      `<span class="chip"><i style="background:${PALETTE[state]}"></i>${AMB_LABEL[state]} <b>${n}</b></span>`).join("");
    const teamChips = r.teams.map(([kind, busy]) =>
      `<span class="chip team ${busy ? "" : "free"}" style="border:1px solid ${PALETTE[kind]}"><i style="background:${PALETTE[kind]}"></i>${kind}${busy ? " busy" : " free"}</span>`).join("");
    const staff = B.hospitals.map((h, i) =>
      `<div><b>${esc(h.id)}</b>Dr ${frame.s[i][0]}/${h.doctors} &middot; RN ${frame.s[i][1]}/${h.nurses}</div>`).join("");
    $("resources").innerHTML = `<h3>Resources in use</h3>` +
      `<span class="lab">Ambulances</span><div class="chips">${ambChips}</div>` +
      `<span class="lab">Teams</span><div class="chips">${teamChips}<span class="lab">${r.teams_busy} busy &middot; ${r.teams_free} free</span></div>` +
      `<span class="lab">Staff</span><div class="staff">${staff}</div>`;

    renderFeed(frame.n);
    renderStrip(m);
  }

  const STORY = new Set(["conflict", "counter", "accept", "reject", "escalate", "executed"]);
  let feedFilter = "all";
  document.querySelectorAll("#filter button").forEach((b) => b.addEventListener("click", () => {
    feedFilter = b.dataset.f;
    document.querySelectorAll("#filter button").forEach((o) => o.classList.toggle("on", o === b));
    renderFeed(shownMessages, true); b.blur();
  }));
  function renderFeed(n, keepOld) {
    const old = keepOld ? n : shownMessages;
    shownMessages = n;
    $("feedcount").textContent = n ? `${n} so far` : "";
    if (!n) { $("feed").innerHTML = `<div class="empty">No messages yet. They appear as the agents start working.</div>`; return; }
    const rows = [];
    for (let i = n - 1; i >= 0 && rows.length < 60; i--) {
      const x = B.messages[i];
      if (feedFilter === "story" && !STORY.has(x.type)) continue;
      rows.push(`<div class="msg ${x.type}${i >= old && old > 0 ? " new" : ""}" title="${esc(x.id + " · " + x.why)}">` +
        `<span class="t">${x.t}</span><span class="badge">${x.badge}</span>${x.adm ? '<span class="adm">ADM</span>' : ""}` +
        `<span class="who">${esc(x.from)}${x.to ? " &rarr; " + esc(x.to) : ""}</span><span class="what">${esc(x.text)}</span></div>`);
    }
    $("feed").innerHTML = rows.join("");
  }

  function renderStrip(m) {
    const c = [...B.conflicts].reverse().find((k) => k.t <= m);
    if (!c) {
      $("strip").innerHTML = `<div class="head">Negotiation<b>No conflict yet</b></div>` +
        `<div class="empty" style="align-self:center">When two agents want the same resource, the steps of the negotiation appear here: conflict, counter-offer, accepted or rejected, executed.</div>`;
      return;
    }
    const steps = c.stages.map((st) => {
      const off = st.ref === null || st.t > m;
      const cls = "s-" + st.label.toLowerCase().replace(/[^a-z]/g, "");
      return `<div class="step ${cls}${off ? " off" : ""}" title="${esc(st.label + (st.ref ? " " + st.ref : "") + ": " + st.text)}"><div class="lab">${esc(st.label)}</div>` +
        `<div class="ref">${st.ref ? esc(st.ref) : "&mdash;"}</div><div class="txt">${esc(st.text)}</div></div>`;
    });
    $("strip").innerHTML = `<div class="head">Latest conflict<b>minute ${c.t}</b><span>${B.conflicts.indexOf(c) + 1} of ${B.conflicts.length} in this run</span></div>` +
      steps.join('<div class="arrow">&rarr;</div>');
  }

  // ───────── Controls ─────────
  const scrub = $("scrub"), playBtn = $("play"), pauseBox = $("pausebox");
  let tau = 0, playing = false, speed = 1, last = null;
  scrub.max = N;
  $("last").textContent = String(N);
  const meta = B.meta;

  function setPlaying(on) {
    playing = on; last = null;
    playBtn.innerHTML = on ? "&#10074;&#10074; Pause" : (tau >= N ? "&#8634; Replay" : "&#9654; Play");
  }
  function jump(t) { tau = clamp(t, 0, N); render(tau); if (!playing) setPlaying(false); }

  function loop(now) {
    if (playing) {
      const before = tau;
      if (last !== null) tau += (Math.min(now - last, MAX_FRAME_MS) / 1000) * speed / SECONDS_PER_MINUTE;   // no jumps after a stall
      last = now;
      const hit = pauseBox.checked && B.conflicts.find((c) => c.t > before && c.t <= tau);
      if (hit) { tau = hit.t; render(tau); setPlaying(false); }               // stop on the minute the conflict appears
      else if (tau >= N) { tau = N; render(tau); setPlaying(false); }
      else render(tau);
    }
    requestAnimationFrame(loop);
  }

  playBtn.addEventListener("click", () => {
    if (!playing && tau >= N) tau = 0;
    setPlaying(!playing); playBtn.blur();
  });
  $("restart").addEventListener("click", () => { tau = 0; render(tau); setPlaying(true); $("restart").blur(); });
  scrub.addEventListener("input", () => { tau = parseFloat(scrub.value); render(tau); if (!playing) setPlaying(false); });
  document.querySelectorAll("#speeds button").forEach((b) => b.addEventListener("click", () => {
    speed = parseFloat(b.dataset.speed);
    document.querySelectorAll("#speeds button").forEach((o) => o.classList.toggle("on", o === b));
    b.blur();
  }));
  document.addEventListener("keydown", (e) => {
    if (e.target && e.target.type === "checkbox") return;
    if (e.code === "Space") { e.preventDefault(); playBtn.click(); }
    else if (e.code === "ArrowRight") jump(Math.floor(tau) + 1);
    else if (e.code === "ArrowLeft") jump(Math.ceil(tau) - 1);
  });

  // Ticks under the scrubber: incident arrivals. Markers above it: conflicts (click to jump).
  [...new Set(B.incidents.map((i) => i.arrival_min))].forEach((t) => {
    const i = document.createElement("i");
    i.style.left = `${(t / N) * 100}%`;
    $("ticks").appendChild(i);
  });
  B.conflicts.forEach((c) => {
    const i = document.createElement("i");
    i.style.left = `${(c.t / N) * 100}%`;
    i.title = `Minute ${c.t}: ${c.text}`;
    i.addEventListener("click", () => jump(c.t));
    $("cmarks").appendChild(i);
  });

  $("bedlegend").innerHTML =
    `<span><i class="bed occ" style="background:#8a9bb0"></i>occupied</span>` +
    `<span><i class="bed prom"></i>promised (on the way)</span><span><i class="bed"></i>free</span>`;

  // ───────── Legend (same palette as the map) ─────────
  const sw = (inner) => `<svg viewBox="0 0 22 14">${inner}</svg>`;
  const dot = (fill, stroke) => sw(`<circle cx="11" cy="7" r="5" fill="${fill}" stroke="${stroke || "none"}" stroke-width="1.5"/>`);
  const item = (icon, label) => `<span class="item">${icon}${label}</span>`;
  $("legend").innerHTML =
    item(dot(PALETTE.immediate), "Immediate") + item(dot(PALETTE.delayed), "Delayed") + item(dot(PALETTE.minor), "Minor") +
    item(dot(PALETTE.expectant, "#e8edf3"), "Expectant") + item(dot(PALETTE.reached), "Reached") +
    item(sw(`<rect x="1" y="2" width="20" height="10" rx="4" fill="${PALETTE.en_route}"/>`), "Ambulance") +
    item(sw(`<path d="M11,0 L19,7 L11,14 L3,7 Z" fill="${PALETTE.fire}"/>`), "Team") +
    item(sw(`<line x1="0" y1="7" x2="22" y2="7" stroke="${PALETTE.route}" stroke-width="2" stroke-dasharray="5 4"/>`), "Route") +
    item(sw(`<circle cx="11" cy="7" r="5.5" fill="none" stroke="${PALETTE.ring}" stroke-width="3"/>`), "ER beds");

  // ───────── Layout: the map is a square sized by the free height ─────────
  function fit() {
    const main = $("main"), col = $("mapcol"), wide = window.innerWidth >= 1200;
    col.classList.toggle("wide", wide);
    if (window.innerWidth <= 700) { col.style.width = ""; $("mapwrap").style.width = ""; return; }
    if (wide) {                                         // map on the left (about 55%), legend beside it, map sized by the free height
      const size = Math.max(280, Math.min(main.clientHeight, col.clientWidth - $("legend").offsetWidth - 16));
      $("mapwrap").style.width = size + "px";
      col.style.width = "";
    } else {
      $("mapwrap").style.width = "";
      col.style.width = Math.max(280, Math.min(main.clientHeight - $("legend").offsetHeight - 6, main.clientWidth - 412)) + "px";
    }
  }
  window.addEventListener("resize", fit);

  fit();
  render(0);
  setPlaying(false);
  requestAnimationFrame(loop);
  window.__player = { jump, render, bundle: B, state: () => ({ tau, playing, speed }) };   // handy for tests
})();
