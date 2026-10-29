// Shared by the redesigned pages (everything except the Replay app, which carries its own copy of the rail and tooltip code):
// helpers, left rail, tooltips (data-tip="Title|detail"), page navigation and the run-selector popover.
window.UI = (() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const ico = (n, s = 16, extra = "") => `<svg class="i ${extra}" width="${s}" height="${s}"><use href="#i-${n}"/></svg>`;
  const NAV = [["Replay", "map", ""], ["Compare", "git-compare", "compare"], ["What-if", "sliders-horizontal", "whatif"],
    ["Results", "chart-column", "results"], ["Negotiations", "messages-square", "negotiations"]];
  const SYSTEM_LABEL = { naive: "Naive", greedy: "Greedy", agents: "Agents", negotiation: "Negotiation", oracle: "Oracle" };
  const SCENARIO_LABEL = { normal: "Normal", surge: "Surge", bottleneck: "Bottleneck" };

  const pageRoot = () => { try { return window.top.location.pathname.replace(/\/[^/]*$/, "/"); } catch (e) { return "/"; } };
  // The page sits in a sandboxed iframe that may not navigate its parent directly, so the address change is handed to
  // a tiny script that runs in the parent page itself.
  function goto(path, query) {
    const url = pageRoot() + path + (query ? "?" + query : "");
    try {
      const s = window.parent.document.createElement("script");
      s.textContent = `window.location.assign(${JSON.stringify(url)});`;
      window.parent.document.body.appendChild(s);
    } catch (e) { /* not embedded */ }
  }

  function mountRail(active) {
    $("rail").innerHTML = `<div class="logo">${ico("siren", 18)}</div>` + NAV.map(([label, icon, path]) =>
      `<button class="rail-item${label === active ? " active" : ""}" data-path="${path}">${ico(icon, 20)}<span>${label}</span></button>`).join("");
    $("rail").addEventListener("click", (e) => {
      const b = e.target.closest(".rail-item");
      if (b && !b.classList.contains("active")) goto(b.dataset.path);
    });
  }

  function mountTooltips() {
    const tip = $("tip");
    document.addEventListener("mouseover", (e) => {
      const t = e.target.closest && e.target.closest("[data-tip]");
      if (!t || !t.getAttribute("data-tip")) { tip.hidden = true; return; }
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
  }

  // Segmented control: <div class="seg"><b data-v="x">..</b></div>; calls onPick(value)
  function segmented(el, onPick) {
    el.addEventListener("click", (e) => {
      const b = e.target.closest("b[data-v]");
      if (!b || b.classList.contains("dis")) return;
      el.querySelectorAll("b").forEach((o) => o.classList.toggle("on", o === b));
      onPick(b.dataset.v);
    });
  }

  // Run selector: staged choices applied by reloading the page with the chosen run in its address.
  // fields: [["v","Version"],["s","Scenario"],["r","Run"],["m","System"] ...]; extra system fields (e.g. "m2") use the same list.
  function runPicker({ pill, pop, catalog, sel, fields, page, label }) {
    const pick = (obj, key, fallback) => (key in obj ? key : fallback in obj ? fallback : Object.keys(obj)[0]);
    function fix() {
      sel.v = pick(catalog, sel.v, "v1"); sel.s = pick(catalog[sel.v], sel.s, "normal"); sel.r = pick(catalog[sel.v][sel.s], sel.r, "1");
      const modes = catalog[sel.v][sel.s][sel.r];
      fields.filter(([k]) => k.startsWith("m")).forEach(([k]) => { if (!modes.includes(sel[k])) sel[k] = modes.includes("negotiation") ? "negotiation" : modes[0]; });
    }
    function draw() {
      const col = (title, key, items) => `<div class="pop-col"><h4>${title}</h4>` + items.map(([val, text, ok]) =>
        `<button class="opt${sel[key] === val ? " sel" : ""}" data-k="${key}" data-v="${esc(val)}"${ok ? "" : " disabled"}>${esc(text)}</button>`).join("") + "</div>";
      const modes = catalog[sel.v][sel.s][sel.r], all = ["naive", "greedy", "agents", "negotiation", "oracle"];
      const cols = fields.map(([k, title]) => k === "v" ? col(title, k, Object.keys(catalog).map((v) => [v, v, true]))
        : k === "s" ? col(title, k, Object.keys(catalog[sel.v]).map((s) => [s, SCENARIO_LABEL[s] || s, true]))
        : k === "r" ? col(title, k, Object.keys(catalog[sel.v][sel.s]).map((r) => [r, `Run ${r} (seed ${+r + 41})`, true]))
        : col(title, k, all.map((m) => [m, SYSTEM_LABEL[m], modes.includes(m)])));
      pop.innerHTML = `<div class="pop-grid" style="grid-template-columns:repeat(${fields.length},1fr)">${cols.join("")}</div>` +
        `<div class="pop-foot"><span>${esc(label(sel))}</span><button class="btn" id="popapply">Show this</button></div>`;
    }
    pill.addEventListener("click", () => {
      const open = pop.hidden; pop.hidden = !open; pill.setAttribute("aria-expanded", String(open));
      if (open) draw();
    });
    pop.addEventListener("click", (e) => {
      const o = e.target.closest(".opt");
      if (o && !o.disabled) { sel[o.dataset.k] = o.dataset.v; fix(); draw(); }
      if (e.target.closest("#popapply")) goto(page, fields.map(([k]) => `${k}=${sel[k]}`).join("&"));
    });
    document.addEventListener("click", (e) => {
      if (!pop.hidden && !e.composedPath().includes(pop.parentElement)) { pop.hidden = true; pill.setAttribute("aria-expanded", "false"); }
    });
  }

  const pillHtml = (parts) => ico("activity", 16) + parts.map(esc).join('<span class="dot">&middot;</span>') + ico("chevron-down", 16);
  return { $, esc, clamp, ico, goto, mountRail, mountTooltips, segmented, runPicker, pillHtml, SYSTEM_LABEL, SCENARIO_LABEL };
})();
