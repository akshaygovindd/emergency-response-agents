# Dashboard design system (proposal, Phase A)

Goal: a calm, professional operations product. Think clean SaaS (Linear, Vercel, Datadog), not concept art.
Everything here is a proposal for approval; nothing in the running app has changed yet. The static mockup
is `docs/design/replay_mockup.html` (screenshots next to it). The previous UI is tagged `dashboard-v1`.

Principles

1. **The map is the hero.** About 60% of the width. Everything else supports it and never fights it.
2. **One accent.** Indigo marks what you can act on or what is selected. Nothing else is decorative.
3. **Patient colors are reserved.** Red, yellow, green and black appear only on patients (map dots, legend,
   triage numbers). Nothing else in the UI uses those hues, so a red dot always means a patient.
4. **Plain words first.** Sentences say "Ambulance 3 to Incident 1"; internal IDs (`t006-M0007`, `AMB-03`)
   appear on hover and in the Negotiations page, not in the main reading path.
5. **Quiet by default.** 1px borders, soft shadows, no gradients except the map's glow and sparkline fills.
   Motion is limited to unit movement, a slow pulse on an active conflict, and 150 ms hover transitions.
6. **Projector-readable.** Nothing smaller than 12 px; body text 14 px; numbers that matter 28 px.

## 1. Color tokens

Dark theme only (the demo room is dark). Tokens are CSS custom properties on `:root`.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0A0E17` | App background (near-black navy) |
| `--panel` | `#101624` | Cards, rail, top bar |
| `--panel-2` | `#151C2C` | Raised items inside a card, hovered rows |
| `--panel-3` | `#1B2438` | Pressed state, inputs |
| `--border` | `rgba(148,163,184,.12)` | Default 1px border |
| `--border-strong` | `rgba(148,163,184,.22)` | Hover / focused border |
| `--text` | `#E6EAF2` | Primary text |
| `--text-2` | `#9AA6BA` | Secondary text, labels |
| `--text-3` | `#66728A` | Hints, units, disabled |
| `--accent` | `#6366F1` | The single accent (indigo 500) |
| `--accent-hover` | `#7C7FF5` | Hover on accent |
| `--accent-soft` | `rgba(99,102,241,.16)` | Selected backgrounds, focus glow |

Patients (map and legend only)

| Token | Value | Meaning |
|---|---|---|
| `--triage-immediate` | `#EF4444` | START Immediate (severity 4-5) |
| `--triage-delayed` | `#FACC15` | Delayed (3) |
| `--triage-minor` | `#22C55E` | Minor (1-2) |
| `--triage-expectant` | `#05070B` with a `#CBD5E1` 1.5px ring | Expectant: critical, deadline missed |
| `--triage-reached` | `#94A3B8` | Reached: fades out after first contact |

Status (never used for patients)

| Token | Value | Use |
|---|---|---|
| `--ok` | `#2DD4BF` | Stable, accepted, completed steps |
| `--warn` | `#FB923C` | Conflicts only (orange is reserved for conflicts: callout, conflict lines, the ring on a unit in a conflict) |
| `--moderate` | `#D6A94E` | Hospital "Moderate" load |
| `--danger` | `#FB7185` | Near capacity, rejected |
| `--info` | `#38BDF8` | En-route units, information |
| `--violet` | `#A78BFA` | Executed / committed by the system, transporting ambulances |

Map base: background `#0B111C`, district fills `#0F1624` / `#111A2B`, district edges `rgba(148,163,184,.07)`,
roads `rgba(148,163,184,.05)` (grid) and `.10` (arterials). The base stays darker and quieter than any marker.

## 2. Typography

**Inter**, bundled in `docs/design/assets/fonts/` (Regular 400, Medium 500, SemiBold 600; SIL Open Font
License). Fallback: `-apple-system, "Segoe UI", system-ui, sans-serif`. All numbers use
`font-variant-numeric: tabular-nums`.

| Role | Size / line | Weight |
|---|---|---|
| Tiny tag (the only all-caps) | 11 / 16, letter-spacing .06em | 600 |
| Caption, hints | 12 / 16 | 400 |
| Secondary, labels | 13 / 20 | 500 |
| Body | 14 / 20 | 400 |
| Card title | 15 / 20 | 600 |
| Page title | 16 / 24 | 600 |
| Metric (small) | 20 / 24 | 600 |
| KPI value | 28 / 32 | 600 |

Labels are sentence case ("Critical in time", not "CRITICAL IN TIME"). All caps only for tiny tags such as
`ALS`, `COUNTER`.

## 3. Space, shape, elevation

* **8 px grid.** Allowed spacings: 4 (inside chips only), 8, 16, 24, 32. Card padding 16 (compact) or 24.
  Gutter between panels 24; gap between cards in a group 16; 8 inside dense groups such as bed squares.
* **Radius.** Panels 14. Inner items (rows, inputs) 10. Pills and chips 999. Bed squares 4.
* **Borders.** 1px `--border`, always. No double borders, no thick colored side borders except the 3px status
  marker on timeline nodes.
* **Elevation.** Panels sit flat with a border. Floating things (callout, playback bar, tooltips) get
  `0 1px 2px rgba(0,0,0,.4), 0 12px 32px rgba(0,0,0,.35)` and a `backdrop-filter: blur(12px)` over a
  72% opaque panel color.

## 4. Icons

**Lucide** (ISC license), 24 px grid, 2 px stroke, round caps, `currentColor`, bundled as individual SVGs in
`docs/design/assets/icons/` (pinned to lucide-static 0.468.0). Rendered at 16 px (inline), 20 px (rail, cards)
or 24 px (primary buttons). Icons set used so far: play, pause, rotate-ccw, map, git-compare,
sliders-horizontal, chart-column, messages-square, activity, users, clock, siren, triangle-alert, hospital,
bed-double, circle-check, flag, chevron-down, brain-circuit, shield-check, ambulance, flame.

Agent icons (timeline): Assessment `brain-circuit`, Dispatch `siren`, Resource Allocation
`sliders-horizontal`, Hospital `hospital`, System `shield-check`.

## 5. Components

**App shell.** Left icon rail (80 px) + slim top bar (64 px) + content with 24 px padding. Content is a
two-column grid: map 60%, side panel 40%, 24 px gutter, both fill the viewport height (no page scroll at
1920 x 1080; the timeline is the only scrolling region).

**Navigation rail.** Logo mark at top (32 px indigo rounded square). Five items: icon 20 px above a 11-12 px
label. Item 64 x 56, radius 12. Active: `--accent-soft` background, accent icon, `--text` label. Hover:
`--panel-2`.

**Top bar.** Title (16 / 600) left. Right: *run selector pill* and an optional ghost button (Tour).

**Pill selector.** Height 40, radius 999, `--panel-2` fill, 1px `--border`, leading 16 px icon, text 14 / 500,
trailing chevron. Opens a popover with four grouped lists (Version, Scenario, Run, System). Hover border
`--border-strong`; focus ring `0 0 0 3px --accent-soft`.

**Segmented control** (speed 1x/2x/4x, All/Negotiation). Container `--panel-3`, radius 10, padding 4; segment
radius 8, 32 px high, 13 / 500. Selected: `--panel` fill with 1px border and `--text`; unselected `--text-2`.

**KPI card.** 16 px padding, radius 14. Row 1: 28 px rounded icon tile (accent-soft or status-soft) + label
(13 / 500 `--text-2`). Row 2: value (28 / 600) with optional "/ n" in `--text-3` (16), sparkline right (112 x 32,
1.5 px line, 12% fill, a dot at "now", the future part dashed and dimmer). Row 3: one short note (12 `--text-3`).
Hover: full explanation as a tooltip.

**Hospital capacity card.** Name (14 / 600), status pill (dot + "Stable / Moderate / Near capacity" in status
color), row of ER bed squares (14 px, radius 4): occupied = status color fill, promised = dashed outline in
`--info`, free = 1px `--border-strong`. Footer: "0 of 6 beds in use" and "2 doctors, 4 nurses free" (12 `--text-3`).
On the map a hospital is an icon tile with a segmented capacity ring (one arc per bed) and a soft glow in the
status color.

**Agent timeline item.** 32 px circular agent icon (border = message type color), a 1px vertical connector,
one plain sentence (14), actor name (12 `--text-2`) and time (12 `--text-3`, right aligned, "Min 6"). Hover: a
tooltip with the reason the agent gave and the internal IDs. Consecutive "executed" lines collapse into one
item. A filter segmented control (All / Negotiation) sits in the card header.

**Stepper (negotiation).** Four nodes on a line: Conflict, Counter-offer, Accepted or Rejected, Executed. Node
24 px: done = filled status color with a check, current = accent ring, upcoming = hollow. Under each node a 13 / 500
label and a 12 `--text-3` one-line detail. Connector 2 px, filled up to the current step.

**Conflict callout (map).** Floating card, 320 px wide, radius 14, orange icon tile, title "Conflict at minute 6",
one sentence, a small status line ("Negotiating"). Positioned away from the incidents and units involved;
orange dashed lines on the map show what is contested.

**Floating playback bar.** Pill-shaped (radius 20), 72 px high, 24 px inset from the bottom of the map. Left to
right: round primary play/pause button (44 px, accent), restart ghost button, speed segmented control,
scrubber (4 px track, accent fill, 16 px thumb, orange diamond markers for conflicts, tiny ticks for incident
arrivals), minute readout ("6" 20 / 600 and "/ 120" `--text-3`), auto-pause switch.

**Map markers.** Hospital: 44 px icon tile + segmented ring + glow. Incident: soft glow in the worst patient's
triage color, 1.5 px ring, small victim dots (r 5) around it, a label pill ("Incident 2"). Ambulance: 24 px chip
with icon and short name ("A3"), border in status color (available `--text-3`, en route `--info`, on scene
`--ok`, transporting `--warn`), "ALS" as a tiny tag. Responder team: 24 px round chip with icon. Route: 1.5 px
dashed line in the unit's status color at 55% opacity, dashes slowly marching toward the destination.
Resolved incidents fade to 15% and lose their label. Labels never overlap (same collision rule as today).

**States.** Hover: `--panel-2` and `--border-strong`. Focus: 3 px `--accent-soft` ring. Disabled: 40% opacity.
Empty: one line in `--text-3` plus an icon.

## 6. How this maps to the app (Phase B, after approval)

* Keep all Python data code as is (`export.py`, `story.py`, `live.py`, `tour.py`, `compare.py`, `whatif.py`,
  `results_view.py`, `negotiations.py`).
* Replace the Streamlit chrome (it is what looks default today) with a thin Streamlit launcher that serves one
  full-window HTML app: rail, top bar and pages are our own HTML/CSS/JS using these tokens; Streamlit only
  loads data and hosts it. The tokens go into one `theme.css` shared by the player, Compare, What-if, Results
  and Negotiations pages.
* Charts (Results) use the same tokens (indigo accent for the system under test, neutral grays for baselines).
* Fonts and icons are served locally from the repo: no CDN, works offline at the demo.

## 7. Accessibility and demo notes

Text contrast is at least 4.5:1 against its panel (`--text-3` is for hints only). Patient colors always
pair with a shape or a label (legend, tooltip) so color is never the only signal. Projector check: 1920 x 1080,
nothing under 12 px, key numbers 28 px.
