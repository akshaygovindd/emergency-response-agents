"""Build docs/design/replay_mockup.html: a static Replay page mockup from real data.

Data: v1 / normal / seed 42 / negotiation at minute 6, read through the same export code the app uses
(no simulation, no API calls). Run from the repo root:  python docs/design/build_mockup.py
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from erc.dashboard.export import export_replay  # noqa: E402

DESIGN = Path(__file__).resolve().parent
ICON_DIR = DESIGN / "assets" / "icons"
MINUTE = 6
W, H = 1070, 968                               # map card size in px at 1920 x 1080
S, X0, Y_BOTTOM = 44.0, 95.0, 90.0           # px per km, left offset, space kept under the map for the playback bar
TRIAGE = {1: "var(--triage-immediate)", 2: "var(--triage-delayed)", 3: "var(--triage-minor)"}   # frame codes
STATUS_COLOR = {"available": "var(--text-3)", "en_route": "var(--info)", "on_scene": "var(--ok)", "transporting": "var(--warn)"}
AGENT_ICON = {"Assessment": "brain-circuit", "Dispatch": "siren", "Resource Allocation": "sliders-horizontal",
              "Hospital": "hospital", "System": "shield-check"}
TYPE_COLOR = {"proposal": "var(--accent)", "counter": "var(--warn)", "accept": "var(--ok)", "reject": "var(--danger)",
              "conflict": "var(--warn)", "executed": "var(--violet)", "info": "var(--text-3)", "commit": "var(--violet)"}
UNIT_NAME = {"FIRE-1": "Fire team", "RESCUE-1": "Rescue team", "MED-1": "Medical team"}
HOSPITAL_ICON_STATUS = {"Stable": "var(--ok)", "Moderate": "var(--warn)", "Near capacity": "var(--danger)"}


def X(x: float) -> float:
    return X0 + x * S


def Y(y: float) -> float:
    return H - Y_BOTTOM - y * S


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def plain(text: str) -> str:
    """'send AMB-03 to INC-01 (V-01-1)' -> 'send Ambulance 3 to Incident 1'."""
    text = re.sub(r"\s*\(V-[^)]*\)", "", text)
    text = re.sub(r"AMB-0?(\d+)", r"Ambulance \1", text)
    text = re.sub(r"INC-0?(\d+)", r"Incident \1", text)
    for raw, name in UNIT_NAME.items():
        text = text.replace(raw, name)
    return text.replace("Resource Alloc.", "Resource Allocation")


def short_unit(unit_id: str) -> str:
    return "A" + str(int(unit_id.split("-")[1])) if unit_id.startswith("AMB") else UNIT_NAME.get(unit_id, unit_id).split()[0]


# ───────── Icons: one <symbol> per Lucide file, used with <use> ─────────
def sprite(names: list[str]) -> str:
    symbols = []
    for name in names:
        svg = (ICON_DIR / f"{name}.svg").read_text()
        inner = svg.split(">", 2)[2] if svg.startswith("<!--") else svg.split(">", 1)[1]
        inner = inner.rsplit("</svg>", 1)[0]
        symbols.append(f'<symbol id="i-{name}" viewBox="0 0 24 24">{inner}</symbol>')
    return '<svg width="0" height="0" style="position:absolute" aria-hidden="true">' + "".join(symbols) + "</svg>"


def icon(name: str, size: int = 16, cls: str = "") -> str:
    return f'<svg class="i {cls}" width="{size}" height="{size}"><use href="#i-{name}"/></svg>'


def svg_icon(name: str, x: float, y: float, size: int, color: str) -> str:
    return (f'<svg class="i" x="{x - size / 2:.1f}" y="{y - size / 2:.1f}" width="{size}" height="{size}" '
            f'style="color:{color}"><use href="#i-{name}"/></svg>')


# ───────── Map ─────────
DISTRICTS = [  # soft irregular shapes, in km (the city is bigger than the 20 km study grid)
    [(-6, 25), (6.5, 25), (7.5, 14), (-6, 13)], [(6.5, 25), (14, 25), (15.5, 15), (7.5, 14)],
    [(14, 25), (26, 25), (26, 12), (15.5, 15)], [(-6, 13), (7.5, 14), (8, 7), (-6, 6.5)],
    [(7.5, 14), (15.5, 15), (16.5, 8), (8, 7)], [(15.5, 15), (26, 12), (26, 5), (16.5, 8)],
    [(-6, 6.5), (8, 7), (9, -8), (-6, -8)], [(8, 7), (16.5, 8), (17, -8), (9, -8)], [(16.5, 8), (26, 5), (26, -8), (17, -8)],
]


def base_map() -> str:
    out = ['<defs><radialGradient id="vignette" cx="50%" cy="45%" r="75%"><stop offset="0" stop-color="#0E1524"/>'
           '<stop offset="1" stop-color="#080C14"/></radialGradient></defs>',
           f'<rect width="{W}" height="{H}" fill="url(#vignette)"/>']
    for i, poly in enumerate(DISTRICTS):
        pts = " ".join(f"{X(x):.0f},{Y(y):.0f}" for x, y in poly)
        out.append(f'<polygon points="{pts}" fill="{"#0F1624" if i % 2 else "#111A2B"}" stroke="rgba(148,163,184,.07)" stroke-width="1.5" stroke-linejoin="round"/>')
    for k in range(-8, 28, 2):            # faint road grid every 2 km
        out.append(f'<line x1="{X(k):.0f}" y1="0" x2="{X(k):.0f}" y2="{H}" stroke="rgba(148,163,184,.045)"/>')
        out.append(f'<line x1="0" y1="{Y(k):.0f}" x2="{W}" y2="{Y(k):.0f}" stroke="rgba(148,163,184,.045)"/>')
    arterials = [[(-6, 12), (5, 15), (10, 11), (17, 12), (26, 9)], [(5, 15), (7.3, 18.5), (8, 25)], [(10, 11), (10, 4), (9, -8)],
                 [(15, 13), (14, 6), (13, -8)]]
    for road in arterials:
        pts = " ".join(f"{X(x):.0f},{Y(y):.0f}" for x, y in road)
        out.append(f'<polyline points="{pts}" fill="none" stroke="rgba(148,163,184,.11)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(out)


def capacity_ring(cx: float, cy: float, r: float, capacity: int, occupied: int, promised: int, color: str) -> str:
    """One arc per ER bed: occupied = status color, promised = info, free = track."""
    import math
    gap = 0.16
    seg = 2 * math.pi / capacity
    arcs = []
    for k in range(capacity):
        a0, a1 = -math.pi / 2 + k * seg + gap / 2, -math.pi / 2 + (k + 1) * seg - gap / 2
        x0, y0, x1, y1 = cx + r * math.cos(a0), cy + r * math.sin(a0), cx + r * math.cos(a1), cy + r * math.sin(a1)
        fill = color if k < occupied else "var(--info)" if k < occupied + promised else "rgba(148,163,184,.22)"
        arcs.append(f'<path d="M{x0:.1f},{y0:.1f} A{r},{r} 0 0 1 {x1:.1f},{y1:.1f}" fill="none" stroke="{fill}" stroke-width="5" stroke-linecap="round"/>')
    return "".join(arcs)


def box(cx: float, cy: float, w: float, h: float) -> tuple:
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def hit(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def label_width(text: str) -> float:
    return 8 + len(text) * 6.6


def place_label(cx: float, cy: float, text: str, spots: list, taken: list, tone: str = "var(--text-2)") -> str:
    """Pill label at the first offset in `spots` that overlaps nothing already on the map."""
    w = label_width(text)
    pick = next(((dx, dy) for dx, dy in spots if not any(hit(box(cx + dx, cy + dy, w + 4, 26), t) for t in taken)), spots[0])
    taken.append(box(cx + pick[0], cy + pick[1], w, 22))
    return pill_label(cx + pick[0], cy + pick[1], text, tone=tone)


def pill_label(x: float, y: float, text: str, anchor: str = "middle", tone: str = "var(--text-2)") -> str:
    width = 8 + len(text) * 6.6
    x0 = x - width / 2 if anchor == "middle" else x if anchor == "start" else x - width
    return (f'<g><rect x="{x0:.1f}" y="{y - 11:.1f}" width="{width:.1f}" height="22" rx="11" fill="rgba(10,14,23,.78)" '
            f'stroke="rgba(148,163,184,.16)"/><text x="{x0 + width / 2:.1f}" y="{y + 4:.1f}" text-anchor="middle" font-size="12" '
            f'font-weight="500" fill="{tone}">{esc(text)}</text></g>')


def build_map(b: dict) -> str:
    f = b["frames"][MINUTE]
    where = {h["id"]: (h["x"], h["y"]) for h in b["hospitals"]}
    where.update({i["id"]: (i["map_x"], i["map_y"]) for i in b["incidents"]})
    layers = [base_map()]

    # routes of units that are moving, plus the contested lines
    for u, row in list(zip(b["ambulances"], f["a"])) + list(zip(b["responders"], f["r"])):
        if row[2] == "en_route" and row[3] in where:
            tx, ty = where[row[3]]
            layers.append(f'<line class="route" x1="{X(row[0]):.1f}" y1="{Y(row[1]):.1f}" x2="{X(tx):.1f}" y2="{Y(ty):.1f}" '
                          f'stroke="var(--info)" stroke-opacity=".55" stroke-width="1.6" stroke-dasharray="3 7" stroke-linecap="round"/>')
    conflict = next(c for c in b["conflicts"] if c["t"] == MINUTE)
    contested = next(a for a in b["ambulances"] if a["id"] in conflict["resources"])
    cx, cy = next((X(r[0]), Y(r[1])) for a, r in zip(b["ambulances"], f["a"]) if a["id"] == contested["id"])
    for inc in conflict["incidents"]:
        tx, ty = where[inc]
        layers.append(f'<line class="conflict-line" x1="{cx:.1f}" y1="{cy:.1f}" x2="{X(tx):.1f}" y2="{Y(ty):.1f}" '
                      f'stroke="var(--warn)" stroke-width="1.8" stroke-dasharray="6 6" stroke-linecap="round"/>')

    # obstacles first (icons, glows, unit chips), so labels can be placed around them
    taken = [box(X(h["x"]), Y(h["y"]), 92, 92) for h in b["hospitals"]]
    incidents = [i for i in b["incidents"] if i["arrival_min"] <= MINUTE]
    taken += [box(X(i["map_x"]), Y(i["map_y"]), 84, 84) for i in incidents]
    taken += [box(X(r[0]), Y(r[1]), 92 if u.get("als") else 66, 66 if u["id"] == contested["id"] else 30)
              for u, r in list(zip(b["ambulances"], f["a"])) + list(zip(b["responders"], f["r"]))]
    labels = []

    # hospitals
    for i, h in enumerate(b["hospitals"]):
        er, _, promised, status = f["h"][i]
        color = HOSPITAL_ICON_STATUS[status]
        px, py = X(h["x"]), Y(h["y"])
        layers.append(f'<g><title>{esc(h["id"])} {esc(h["name"])}: {er} of {h["er_capacity"]} ER beds in use</title>'
                      f'<circle cx="{px:.1f}" cy="{py:.1f}" r="46" fill="{color}" opacity=".10"/>'
                      f'<circle cx="{px:.1f}" cy="{py:.1f}" r="34" fill="url(#vignette)" />'
                      + capacity_ring(px, py, 32, h["er_capacity"], er, promised, color)
                      + f'<circle cx="{px:.1f}" cy="{py:.1f}" r="24" fill="#131B2C" stroke="rgba(148,163,184,.25)"/>'
                      + svg_icon("hospital", px, py, 24, "#E6EAF2") + '</g>')
        labels.append((px, py, h["name"], [(0, 63), (0, -63), (96, 0), (-96, 0)], "var(--text)"))

    # incidents
    import math
    victims_by = {i["id"]: [(v, f["v"][k]) for k, v in enumerate(b["victims"]) if v["incident"] == i["id"] and f["v"][k] in TRIAGE] for i in incidents}
    for inc in incidents:
        px, py = X(inc["map_x"]), Y(inc["map_y"])
        dots = victims_by[inc["id"]]
        worst = min(code for _, code in dots)
        layers.append(f'<g><title>{esc(inc["id"])}: {len(dots)} patient{"s" if len(dots) != 1 else ""} waiting</title>'
                      f'<circle cx="{px:.1f}" cy="{py:.1f}" r="40" fill="{TRIAGE[worst]}" opacity=".13"/>'
                      f'<circle cx="{px:.1f}" cy="{py:.1f}" r="24" fill="{TRIAGE[worst]}" opacity=".12"/>'
                      f'<circle cx="{px:.1f}" cy="{py:.1f}" r="14" fill="#0E1524" stroke="{TRIAGE[worst]}" stroke-width="1.5"/>')
        for k, (_, code) in enumerate(dots):
            ang = 2 * math.pi * k / max(1, len(dots)) - math.pi / 2
            rr = 0 if len(dots) == 1 else 7
            layers.append(f'<circle cx="{px + math.cos(ang) * rr:.1f}" cy="{py + math.sin(ang) * rr:.1f}" r="{5 if len(dots) == 1 else 4.2}" fill="{TRIAGE[code]}" stroke="#0A0E17" stroke-width="1.2"/>')
        layers.append("</g>")
    left_first = sorted(incidents, key=lambda i: -i["y"])         # the upper incident labels to the left, the lower to the right
    for n, inc in enumerate(left_first):
        spots = [(-62, 0), (62, 0), (0, -48), (0, 48)] if n == 0 else [(62, 0), (-62, 0), (0, 48), (0, -48)]
        labels.append((X(inc["map_x"]), Y(inc["map_y"]), "Incident " + str(int(inc["id"].split("-")[1])), spots, "var(--text-2)"))

    # units
    for u, row in zip(b["ambulances"], f["a"]):
        px, py = X(row[0]), Y(row[1])
        color = STATUS_COLOR[row[2]]
        width = 44 + (24 if u["als"] else 0)
        ring = ('<circle class="pulse" cx="%.1f" cy="%.1f" r="26" fill="none" stroke="var(--warn)" stroke-width="2"/>' % (px, py)
                if u["id"] == contested["id"] else "")
        layers.append(f'<g><title>{esc(u["id"])} ({"advanced" if u["als"] else "basic"} life support), {row[2].replace("_", " ")}</title>{ring}'
                      f'<rect x="{px - width / 2:.1f}" y="{py - 12:.1f}" width="{width}" height="24" rx="12" fill="#131B2C" stroke="{color}" stroke-width="1.5"/>'
                      + svg_icon("ambulance", px - width / 2 + 14, py, 14, color)
                      + f'<text x="{px - width / 2 + 25:.1f}" y="{py + 4:.1f}" font-size="12" font-weight="600" fill="#E6EAF2">{esc(short_unit(u["id"]))}</text>'
                      + (f'<text x="{px + width / 2 - 24:.1f}" y="{py + 3.5:.1f}" font-size="9.5" font-weight="700" letter-spacing=".06em" fill="var(--warn)">ALS</text>' if u["als"] else "")
                      + '</g>')
    icons = {"fire": "flame", "rescue": "shield-check", "medical": "activity"}
    for u, row in zip(b["responders"], f["r"]):
        px, py = X(row[0]), Y(row[1])
        busy = row[2] != "available"
        color = "var(--info)" if busy else "var(--text-3)"
        layers.append(f'<g opacity="{1 if busy else .75}"><title>{esc(u["id"])}: {row[2].replace("_", " ")}</title>'
                      f'<circle cx="{px:.1f}" cy="{py:.1f}" r="13" fill="#131B2C" stroke="{color}" stroke-width="1.5"/>'
                      + svg_icon(icons[u["kind"]], px, py, 14, color) + '</g>')
        labels.append((px, py, UNIT_NAME[u["id"]].split()[0], [(44, 0), (-44, 0), (0, 26), (0, -26)], "var(--text-3)"))

    for px, py, text, spots, tone in labels:                         # labels last, around everything drawn
        layers.append(place_label(px, py, text, spots, taken, tone))
    return "".join(layers)


# ───────── Right panel ─────────
def sparkline(series: list, now: int, color: str, w: int = 112, h: int = 34) -> str:
    vals = [(i, v) for i, v in enumerate(series) if v is not None]
    if not vals:
        return ""
    top = max(v for _, v in vals) or 1
    pt = lambda i, v: (i / (len(series) - 1) * w, h - 3 - (v / top) * (h - 8))
    past = [pt(i, v) for i, v in vals if i <= now]
    future = [pt(i, v) for i, v in vals if i >= now]
    path = lambda pts: " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    parts = [f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']
    if len(past) > 1:
        parts.append(f'<polyline points="{path(past)}" fill="none" stroke="{color}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>')
    if len(future) > 1:
        parts.append(f'<polyline points="{path(future)}" fill="none" stroke="{color}" stroke-opacity=".35" stroke-width="1.4" stroke-dasharray="2 3"/>')
    now_pts = [pt(i, v) for i, v in vals if i == now]
    nx = now / (len(series) - 1) * w
    parts.append(f'<line x1="{nx:.1f}" y1="2" x2="{nx:.1f}" y2="{h - 2}" stroke="rgba(148,163,184,.35)" stroke-width="1"/>')
    if now_pts:
        parts.append(f'<circle cx="{now_pts[0][0]:.1f}" cy="{now_pts[0][1]:.1f}" r="3" fill="{color}"/>')
    return "".join(parts) + "</svg>"


def kpi(icon_name: str, tone: str, label: str, value: str, of: str, note: str, series: list, tip: str, span: int = 2) -> str:
    return (f'<div class="card kpi" style="grid-column:span {span}" title="{esc(tip)}">'
            f'<div class="kpi-top"><span class="tile" style="--tone:{tone}">{icon(icon_name, 16)}</span><span class="kpi-label">{esc(label)}</span></div>'
            f'<div class="kpi-mid"><div class="kpi-value">{value}{f"<span class=kpi-of> / {of}</span>" if of else ""}</div>'
            f'{sparkline(series, MINUTE, tone)}</div><div class="kpi-note">{esc(note)}</div></div>')


def hospital_card(b: dict, i: int) -> str:
    h, f = b["hospitals"][i], b["frames"][MINUTE]
    er, _, promised, status = f["h"][i]
    color = HOSPITAL_ICON_STATUS[status]
    beds = "".join(f'<i class="bed {"occ" if k < er else "prom" if k < er + promised else ""}" style="--tone:{color}"></i>' for k in range(h["er_capacity"]))
    doctors, nurses = f["s"][i]
    return (f'<div class="card hosp" title="{esc(h["id"])} {esc(h["name"])}"><div class="hosp-top"><span class="hosp-name">{esc(h["name"])}</span>'
            f'<span class="status" style="--tone:{color}"><i></i>{status}</span></div><div class="beds">{beds}</div>'
            f'<div class="hosp-foot"><span>{er} of {h["er_capacity"]} beds in use</span>'
            f'<span>{h["doctors"] - doctors} doctors, {h["nurses"] - nurses} nurses free</span></div></div>')


def resources_row(b: dict) -> str:
    r = b["frames"][MINUTE]["res"]
    amb = "".join(f'<span class="chip" style="--tone:{STATUS_COLOR[s]}"><i></i><b>{r["amb"][s]}</b><span>{label}</span></span>'
                  for s, label in (("available", "free"), ("en_route", "en route"), ("on_scene", "on scene"), ("transporting", "transporting")))
    names = {"fire": "Fire", "rescue": "Rescue", "medical": "Medical"}
    teams = "".join(f'<span class="chip {"busy" if busy else "free"}" style="--tone:{"var(--info)" if busy else "var(--text-3)"}"><i></i>'
                    f'<span style="color:var(--text)">{names[kind]}</span><span>{"busy" if busy else "free"}</span></span>' for kind, busy in r["teams"])
    return (f'<div class="res-group"><h4>Ambulances</h4><div class="chips">{amb}</div></div>'
            f'<div class="res-group"><h4>Response teams</h4><div class="chips">{teams}</div></div>')


def timeline(b: dict) -> str:
    rows = [m for m in b["messages"] if m["t"] <= MINUTE and m["type"] not in ("info", "commit")]
    items, executed = [], []
    for m in rows:                                           # newest items last; consecutive executed lines collapse
        if m["type"] == "executed":
            executed.append(m)
            continue
        if executed:
            items.append(("executed", executed)); executed = []
        items.append((m["type"], m))
    if executed:
        items.append(("executed", executed))
    out = []
    for kind, m in reversed(items[-8:]):
        if kind == "executed":
            units = ", ".join(plain(x["text"].replace("sent ", "")) for x in m)
            who, text, tip, t = "System", f"Sent {len(m)} units: " + ", ".join(plain(x["text"].replace("sent ", "").split(" to ")[0]) for x in m), units, m[0]["t"]
            ttype = "executed"
        else:
            who = plain(m["from"])
            body = plain(m["text"])
            verbs = {"proposal": "Proposed to " + body, "counter": "Suggested instead: " + body.replace("send ", ""),
                     "accept": "Accepted: " + body.replace("send ", ""), "reject": "Declined: " + body.replace("send ", ""),
                     "conflict": "Conflict: " + plain(m["text"])}
            text, tip, t, ttype = verbs.get(kind, body), f'{m["id"]} · {m["why"]}', m["t"], kind
        color = TYPE_COLOR.get(ttype, "var(--text-3)")
        agent = AGENT_ICON.get(who, "shield-check")
        out.append(f'<div class="tl-item" title="{esc(tip)}"><span class="tl-node" style="--tone:{color}">{icon(agent, 16)}</span>'
                   f'<div class="tl-body"><div class="tl-text">{esc(text)}</div><div class="tl-meta"><span>{esc(who)}</span>'
                   f'<span class="tl-tag" style="--tone:{color}">{ttype.upper() if ttype in ("counter",) else ttype.title()}</span></div></div>'
                   f'<span class="tl-time">Min {t}</span></div>')
    return "".join(out)


def stepper(b: dict) -> str:
    c = next(c for c in b["conflicts"] if c["t"] == MINUTE)
    details = [plain(c["stages"][0]["text"]), plain(c["stages"][1]["text"]), plain(c["stages"][2]["text"]), plain(c["stages"][3]["text"])]
    labels = ["Conflict", "Counter-offer", c["stages"][2]["label"], "Executed"]
    nodes = []
    for k, (label, detail, st) in enumerate(zip(labels, details, c["stages"])):
        nodes.append(f'<div class="step" title="{esc(st["ref"] or "")}"><span class="step-node">{icon("circle-check", 18)}</span>'
                     f'<div class="step-label">{esc(label)}</div><div class="step-detail">{esc(detail)}</div></div>')
    return "".join(nodes)


def build_html() -> str:
    b = export_replay("v1", "normal", 42, "negotiation")
    f = b["frames"][MINUTE]
    k = f["k"]
    series = {key: [fr["k"][key] for fr in b["frames"]] for key in ("crit_ok", "reached", "expectant", "conflicts", "resp_avg")}
    conflict = next(c for c in b["conflicts"] if c["t"] == MINUTE)
    n_total = len(b["conflicts"])
    last = b["meta"]["last_minute"]
    arrivals = sorted({i["arrival_min"] for i in b["incidents"]})
    marks = "".join(f'<i class="cm" style="left:{c["t"] / last * 100:.2f}%" title="Conflict at minute {c["t"]}">{icon("triangle-alert", 10)}</i>'
                    for c in b["conflicts"])
    ticks = "".join(f'<i class="tick" style="left:{t / last * 100:.2f}%"></i>' for t in arrivals)
    names = ["layout", "map", "git-compare", "sliders-horizontal", "chart-column", "messages-square", "play", "pause", "rotate-ccw", "siren",
             "activity", "users", "clock", "triangle-alert", "hospital", "circle-check", "flag", "chevron-down", "brain-circuit",
             "shield-check", "ambulance", "flame", "heart-pulse"]
    names = [n for n in names if (ICON_DIR / f"{n}.svg").exists()]
    kpis = (kpi("shield-check", "var(--ok)", "Critical in time", str(k["crit_ok"]), str(k["crit_n"]), f"0% · {k['crit_n']} critical so far",
                series["crit_ok"], f"{k['crit_ok']} of the {k['crit_n']} critical patients who have arrived were reached within their deadline.")
            + kpi("users", "var(--info)", "Patients reached", str(k["reached"]), str(k["arrived"]), f"of {len(b['victims'])} in this run",
                  series["reached"], f"{k['reached']} of {k['arrived']} patients who have arrived have had first medical contact.")
            + kpi("heart-pulse", "var(--text-2)", "Expectant", str(k["expectant"]), "", "missed deadline",
                  series["expectant"], "Critical patients whose deadline passed before anyone reached them.")
            + kpi("git-compare", "var(--warn)", "Conflicts", str(k["conflicts"]), "", f"{k['negotiated']} settled by negotiation",
                  series["conflicts"], "Times two agents wanted the same resource.", span=3)
            + kpi("clock", "var(--accent)", "Average response", "–", "", "no patient reached yet",
                  series["resp_avg"], "Average minutes from arrival to first medical contact.", span=3))
    return TEMPLATE.format(
        sprite=sprite(names), map_svg=build_map(b), kpis=kpis, hospitals="".join(hospital_card(b, i) for i in range(3)),
        timeline=timeline(b), stepper=stepper(b), resources=resources_row(b), marks=marks, ticks=ticks, last=last, minute=MINUTE,
        pct=MINUTE / last * 100, conflict_text=esc(plain(conflict["text"])), n_conflict=n_total,
        callout_note="Resource Allocation is negotiating a counter-offer.", W=W, H=H,
        icon_play=icon("play", 20), icon_amb=icon("ambulance", 16), icon_users=icon("users", 16), icon_hosp=icon("hospital", 16), icon_restart=icon("rotate-ccw", 16), icon_chev=icon("chevron-down", 16),
        icon_flag=icon("flag", 16), icon_alert=icon("triangle-alert", 20), icon_activity=icon("activity", 16),
        rail="".join(f'<a class="rail-item{" active" if name == "Replay" else ""}">{icon(ic, 20)}<span>{name}</span></a>'
                     for name, ic in (("Replay", "map"), ("Compare", "git-compare"), ("What-if", "sliders-horizontal"),
                                      ("Results", "chart-column"), ("Negotiations", "messages-square"))),
        icon_logo=icon("siren", 18), icon_msg=icon("messages-square", 16))


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Replay mockup</title>
<style>
@font-face {{ font-family: "Inter"; font-weight: 400; src: url("assets/fonts/Inter-Regular.woff2") format("woff2"); }}
@font-face {{ font-family: "Inter"; font-weight: 500; src: url("assets/fonts/Inter-Medium.woff2") format("woff2"); }}
@font-face {{ font-family: "Inter"; font-weight: 600; src: url("assets/fonts/Inter-SemiBold.woff2") format("woff2"); }}
:root {{
  --bg: #0A0E17; --panel: #101624; --panel-2: #151C2C; --panel-3: #1B2438;
  --border: rgba(148,163,184,.12); --border-strong: rgba(148,163,184,.22);
  --text: #E6EAF2; --text-2: #9AA6BA; --text-3: #66728A;
  --accent: #6366F1; --accent-hover: #7C7FF5; --accent-soft: rgba(99,102,241,.16);
  --triage-immediate: #EF4444; --triage-delayed: #FACC15; --triage-minor: #22C55E; --triage-expectant: #05070B; --triage-reached: #94A3B8;
  --ok: #2DD4BF; --warn: #FB923C; --danger: #FB7185; --info: #38BDF8; --violet: #A78BFA;
  --shadow: 0 1px 2px rgba(0,0,0,.4), 0 12px 32px rgba(0,0,0,.35);
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--text); overflow: hidden;
  font: 400 14px/20px Inter, -apple-system, "Segoe UI", system-ui, sans-serif; font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; }}
.i {{ fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; flex: none; }}
#shell {{ display: grid; grid-template-columns: 80px minmax(0, 1fr); height: 100vh; overflow: hidden; }}

/* rail */
#rail {{ background: var(--panel); border-right: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; padding: 16px 0; gap: 8px; }}
.logo {{ width: 40px; height: 40px; border-radius: 12px; background: var(--accent); display: grid; place-items: center; color: #fff; margin-bottom: 24px; box-shadow: 0 6px 16px rgba(99,102,241,.35); }}
.rail-item {{ width: 64px; height: 60px; border-radius: 12px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; color: var(--text-3); font-size: 11.5px; font-weight: 500; cursor: pointer; }}
.rail-item:hover {{ background: var(--panel-2); color: var(--text-2); }}
.rail-item.active {{ background: var(--accent-soft); color: var(--text); }}
.rail-item.active .i {{ color: var(--accent-hover); }}

/* main */
#content {{ display: grid; grid-template-rows: 64px minmax(0, 1fr); min-width: 0; min-height: 0; height: 100vh; }}
#topbar {{ display: flex; align-items: center; justify-content: space-between; padding: 0 24px; border-bottom: 1px solid var(--border); }}
#topbar h1 {{ margin: 0; font-size: 16px; line-height: 24px; font-weight: 600; }}
#topbar h1 span {{ color: var(--text-3); font-weight: 400; margin-left: 12px; font-size: 13px; }}
.top-right {{ display: flex; gap: 8px; align-items: center; }}
.pill {{ height: 40px; border-radius: 999px; background: var(--panel-2); border: 1px solid var(--border); display: flex; align-items: center; gap: 8px; padding: 0 16px; font-size: 14px; font-weight: 500; color: var(--text); cursor: pointer; }}
.pill:hover {{ border-color: var(--border-strong); }}
.pill .i {{ color: var(--text-2); }}
.pill .dot {{ color: var(--text-3); margin: 0 2px; }}
.ghost {{ height: 40px; border-radius: 999px; padding: 0 16px; display: flex; align-items: center; gap: 8px; background: transparent; border: 1px solid var(--border); color: var(--text-2); font-weight: 500; cursor: pointer; }}
.ghost:hover {{ background: var(--panel-2); color: var(--text); }}
#grid {{ display: grid; grid-template-columns: minmax(0, 60fr) minmax(0, 40fr); grid-template-rows: minmax(0, 1fr); gap: 24px; padding: 24px; min-height: 0; }}

/* map */
#map {{ position: relative; border-radius: 14px; border: 1px solid var(--border); overflow: hidden; background: #0B111C; box-shadow: var(--shadow); min-height: 0; }}
#map > svg.map {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.legend {{ position: absolute; bottom: 112px; right: 24px; display: flex; flex-direction: column; gap: 8px; padding: 8px 16px; border-radius: 14px; background: rgba(16,22,36,.72); backdrop-filter: blur(12px); border: 1px solid var(--border); font-size: 12.5px; color: var(--text-2); font-weight: 500; }}
.legend .row {{ display: flex; gap: 16px; align-items: center; }} .legend .row > b {{ width: 52px; font-weight: 500; color: var(--text-3); font-size: 12px; }}
.legend span {{ display: flex; align-items: center; gap: 8px; white-space: nowrap; }} .legend em {{ font-style: normal; color: var(--text-2); }} .legend u {{ text-decoration: none; font-size: 9.5px; font-weight: 700; letter-spacing: .06em; color: var(--warn); }}
.resources {{ display: grid; gap: 8px; padding: 10px 16px; }} .res-group {{ display: flex; align-items: center; gap: 12px; }} .res-group h4 {{ margin: 0; width: 100px; font-size: 12px; font-weight: 500; color: var(--text-3); }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; }} .chip {{ display: inline-flex; align-items: center; gap: 8px; height: 26px; padding: 0 12px 0 10px; border-radius: 999px; background: var(--panel-2); border: 1px solid var(--border); font-size: 13px; font-weight: 500; white-space: nowrap; }}
.chip i {{ width: 8px; height: 8px; border-radius: 50%; background: var(--tone); display: block; }} .chip span {{ color: var(--text-2); font-weight: 400; }} .chip.free {{ opacity: .65; }}
.legend i {{ width: 10px; height: 10px; border-radius: 50%; display: block; }}
.callout {{ position: absolute; top: 16px; right: 16px; width: 332px; padding: 16px; border-radius: 14px; background: rgba(16,22,36,.82); backdrop-filter: blur(12px); border: 1px solid rgba(251,146,60,.4); box-shadow: var(--shadow); display: flex; gap: 16px; }}
.callout .tile {{ width: 40px; height: 40px; border-radius: 12px; background: rgba(251,146,60,.14); color: var(--warn); display: grid; place-items: center; flex: none; }}
.callout h3 {{ margin: 0; font-size: 15px; line-height: 20px; font-weight: 600; }}
.callout p {{ margin: 4px 0 8px; font-size: 14px; color: var(--text); }}
.callout .live {{ display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-2); }}
.callout .live i {{ width: 8px; height: 8px; border-radius: 50%; background: var(--warn); animation: pulse 1.6s ease-in-out infinite; }}
@keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
.pulse {{ animation: pulse 1.6s ease-in-out infinite; }}
.route {{ animation: march 1.4s linear infinite; }} @keyframes march {{ to {{ stroke-dashoffset: -20; }} }}

/* floating playback bar */
.playbar {{ position: absolute; left: 24px; right: 24px; bottom: 24px; height: 72px; border-radius: 20px; background: rgba(16,22,36,.76); backdrop-filter: blur(14px);
  border: 1px solid var(--border-strong); box-shadow: var(--shadow); display: flex; align-items: center; gap: 16px; padding: 0 20px 0 14px; }}
.play {{ width: 44px; height: 44px; border-radius: 50%; background: var(--accent); color: #fff; display: grid; place-items: center; border: 0; cursor: pointer; box-shadow: 0 6px 16px rgba(99,102,241,.4); }}
.play:hover {{ background: var(--accent-hover); }}
.icon-btn {{ width: 36px; height: 36px; border-radius: 10px; display: grid; place-items: center; color: var(--text-2); background: transparent; border: 0; cursor: pointer; }}
.icon-btn:hover {{ background: var(--panel-2); color: var(--text); }}
.seg {{ display: inline-flex; background: var(--panel-3); border-radius: 10px; padding: 4px; gap: 2px; }}
.seg b {{ height: 32px; padding: 0 12px; display: grid; place-items: center; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--text-2); cursor: pointer; }}
.seg b.on {{ background: var(--panel); color: var(--text); box-shadow: 0 0 0 1px var(--border); }}
.scrub {{ position: relative; flex: 1; height: 44px; }}
.scrub .cms {{ position: absolute; left: 0; right: 0; top: 2px; height: 14px; }}
.cm {{ position: absolute; transform: translateX(-50%); color: var(--warn); display: grid; place-items: center; }}
.scrub .track {{ position: absolute; left: 0; right: 0; top: 24px; height: 4px; border-radius: 2px; background: rgba(148,163,184,.2); }}
.scrub .fill {{ position: absolute; left: 0; top: 24px; height: 4px; border-radius: 2px; background: var(--accent); width: {pct:.2f}%; }}
.scrub .thumb {{ position: absolute; top: 18px; left: {pct:.2f}%; width: 16px; height: 16px; border-radius: 50%; background: #fff; box-shadow: 0 0 0 4px var(--accent-soft), 0 2px 6px rgba(0,0,0,.5); transform: translateX(-50%); }}
.tick {{ position: absolute; top: 34px; width: 2px; height: 6px; background: var(--text-3); border-radius: 1px; opacity: .7; }}
.minute {{ display: flex; align-items: baseline; gap: 6px; min-width: 112px; }}
.minute small {{ font-size: 12px; color: var(--text-3); margin-right: 4px; }}
.minute b {{ font-size: 20px; line-height: 24px; font-weight: 600; }} .minute span {{ color: var(--text-3); font-size: 14px; }}
.switch {{ display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); font-weight: 500; white-space: nowrap; }}
.switch i {{ width: 34px; height: 20px; border-radius: 10px; background: var(--accent); position: relative; display: block; }}
.switch i::after {{ content: ""; position: absolute; right: 3px; top: 3px; width: 14px; height: 14px; border-radius: 50%; background: #fff; }}

/* side panel */
#side {{ display: flex; flex-direction: column; gap: 16px; min-height: 0; }}
.card {{ background: var(--panel); border: 1px solid var(--border); border-radius: 14px; }}
.kpis {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 16px; }}
.kpi {{ padding: 16px 16px 12px; min-width: 0; }}
.kpi-top {{ display: flex; align-items: center; gap: 8px; }}
.tile {{ width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; color: var(--tone); background: color-mix(in srgb, var(--tone) 14%, transparent); flex: none; }}
.kpi-label {{ font-size: 13px; font-weight: 500; color: var(--text-2); white-space: nowrap; }}
.kpi-mid {{ display: flex; align-items: flex-end; justify-content: space-between; margin-top: 8px; }}
.kpi-value {{ font-size: 28px; line-height: 32px; font-weight: 600; }} .kpi-of {{ font-size: 16px; color: var(--text-3); font-weight: 500; }}
.kpi-note {{ font-size: 12px; color: var(--text-3); margin-top: 4px; white-space: nowrap; }}
.spark {{ overflow: visible; flex: none; }}
.section-head {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }}
.section-head h2 {{ margin: 0; font-size: 15px; line-height: 20px; font-weight: 600; }}
.legend-mini {{ display: flex; gap: 16px; font-size: 12px; color: var(--text-3); }} .legend-mini span {{ display: flex; align-items: center; gap: 8px; }}
.hosps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
.hosp {{ padding: 16px; min-width: 0; }}
.hosp-top {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
.hosp-name {{ font-size: 14px; font-weight: 600; white-space: nowrap; }}
.status {{ display: inline-flex; align-items: center; gap: 8px; font-size: 12px; font-weight: 500; color: var(--tone); white-space: nowrap; }}
.status i {{ width: 8px; height: 8px; border-radius: 50%; background: var(--tone); display: block; }}
.beds {{ display: flex; gap: 4px; margin: 16px 0 8px; flex-wrap: wrap; }}
.bed {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid var(--border-strong); display: block; }}
.bed.occ {{ background: var(--tone); border-color: transparent; }} .bed.prom {{ border: 1px dashed var(--info); background: rgba(56,189,248,.15); }}
.hosp-foot {{ display: flex; flex-direction: column; gap: 0; font-size: 12px; color: var(--text-3); }}
.feed {{ flex: 1; min-height: 0; padding: 16px 16px 8px; display: flex; flex-direction: column; }}
.feed .section-head {{ margin-bottom: 8px; }}
.timeline {{ flex: 1; min-height: 0; overflow: auto; position: relative; }}
.tl-item {{ display: flex; gap: 16px; align-items: flex-start; padding: 8px 0; position: relative; }}
.tl-item:not(:last-child)::before {{ content: ""; position: absolute; left: 15.5px; top: 40px; bottom: -8px; width: 1px; background: var(--border-strong); }}
.tl-node {{ width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; flex: none; background: var(--panel-2); color: var(--tone); border: 1.5px solid var(--tone); }}
.tl-body {{ flex: 1; min-width: 0; }} .tl-text {{ font-size: 14px; line-height: 20px; color: var(--text); }}
.tl-meta {{ display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--text-3); margin-top: 0; }}
.tl-tag {{ font-size: 11px; font-weight: 600; letter-spacing: .06em; text-transform: uppercase; color: var(--tone); }}
.tl-time {{ font-size: 12px; color: var(--text-3); flex: none; padding-top: 2px; }}
.negotiation {{ padding: 16px; }}
.steps {{ display: grid; grid-template-columns: repeat(4, 1fr); position: relative; margin-top: 8px; }}
.steps::before {{ content: ""; position: absolute; left: 12.5%; right: 12.5%; top: 11px; height: 2px; background: var(--ok); opacity: .6; }}
.step {{ text-align: center; padding: 0 8px; position: relative; }}
.step-node {{ width: 24px; height: 24px; border-radius: 50%; background: var(--panel); color: var(--ok); display: grid; place-items: center; margin: 0 auto 8px; position: relative; }}
.step-label {{ font-size: 13px; font-weight: 600; }} .step-detail {{ font-size: 12px; color: var(--text-3); line-height: 16px; margin-top: 4px; }}
.sub {{ color: var(--text-3); font-size: 12px; font-weight: 400; }}
</style></head>
<body>
{sprite}
<div id="shell">
  <nav id="rail"><div class="logo">{icon_logo}</div>{rail}</nav>
  <div id="content">
    <header id="topbar">
      <h1>Emergency Response Command Center</h1>
      <div class="top-right">
        <div class="ghost">{icon_flag} Tour</div>
        <div class="pill" title="Version v1 · Scenario normal · Run 1 (seed 42) · System negotiation">{icon_activity}<span>Normal</span><span class="dot">·</span><span>Run 1</span><span class="dot">·</span><span>Negotiation</span><span class="dot">·</span><span>v1</span>{icon_chev}</div>
      </div>
    </header>
    <div id="grid">
      <section id="map">
        <svg class="map" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">{map_svg}</svg>
        <div class="legend"><div class="row"><b>Patients</b><span><i style="background:var(--triage-immediate)"></i>Immediate</span><span><i style="background:var(--triage-delayed)"></i>Delayed</span><span><i style="background:var(--triage-minor)"></i>Minor</span><span><i style="background:var(--triage-expectant);box-shadow:0 0 0 1.5px #CBD5E1"></i>Expectant</span></div><div class="row"><b>Units</b><span style="color:var(--info)">{icon_amb}<em>Ambulance</em></span><span style="color:var(--info)">{icon_amb}<em>ALS ambulance</em><u>ALS</u></span><span style="color:var(--info)">{icon_users}<em>Response team</em></span><span>{icon_hosp}<em>Hospital</em></span></div></div>
        <div class="callout"><div class="tile">{icon_alert}</div><div><h3>Conflict at minute {minute}</h3><p>{conflict_text}</p><div class="live"><i></i>Negotiating a counter-offer</div></div></div>
        <div class="playbar">
          <button class="play" title="Play (space)">{icon_play}</button>
          <button class="icon-btn" title="Restart">{icon_restart}</button>
          <div class="seg"><b class="on">1x</b><b>2x</b><b>4x</b></div>
          <div class="scrub"><div class="cms">{marks}</div><div class="track"></div><div class="fill"></div><div class="thumb"></div>{ticks}</div>
          <div class="minute"><small>Minute</small><b>{minute}</b><span>/ {last}</span></div>
          <div class="switch"><i></i>Pause on conflict</div>
        </div>
      </section>
      <aside id="side">
        <div class="kpis">{kpis}</div>
        <div class="card resources">{resources}</div>
        <div><div class="section-head"><h2>Hospitals</h2><div class="legend-mini"><span><i class="bed occ" style="--tone:var(--text-2);width:10px;height:10px"></i>in use</span><span><i class="bed prom" style="width:10px;height:10px"></i>promised</span><span><i class="bed" style="width:10px;height:10px"></i>free</span></div></div>
          <div class="hosps">{hospitals}</div></div>
        <div class="card feed"><div class="section-head"><h2>Agent activity <span class="sub">newest first</span></h2><div class="seg"><b class="on">All</b><b>Negotiation</b></div></div><div class="timeline">{timeline}</div></div>
        <div class="card negotiation"><div class="section-head"><h2>Latest negotiation</h2><span class="sub">Conflict at minute {minute} · 1 of {n_conflict} in this run</span></div><div class="steps">{stepper}</div></div>
      </aside>
    </div>
  </div>
</div>
</body></html>
"""

if __name__ == "__main__":
    out = DESIGN / "replay_mockup.html"
    out.write_text(build_html())
    print(f"wrote {out} ({out.stat().st_size // 1024} KB)")
