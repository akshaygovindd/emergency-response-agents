"""Shared page chrome for the dashboard: theme, top navigation bar, and the run picker.

The sidebar is hidden; every page starts with the same bar: title and subtitle on the left, the five
page links on the right, and (on pages that need them) pickers after that.
"""
from pathlib import Path

import streamlit as st

BASE = Path(__file__).resolve().parent
PAGES = [("Replay", "views/replay.py"), ("Compare", "views/compare.py"), ("What-if", "views/whatif.py"),
         ("Results", "views/results.py"), ("Negotiations", "views/negotiations.py")]
TITLE = "Emergency Response Command Center"

CSS = """<style>
header[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"]{display:none}
.block-container{padding:0.6rem 1rem 0 1rem;max-width:100%}
.cc-title{font-size:1.55rem;font-weight:700;line-height:1.15;color:#dbe3ee}
.cc-sub{font-size:0.95rem;color:#8a9bb0;margin-top:2px}
div[data-testid="stSelectbox"] label p,div[data-testid="stNumberInput"] label p,div[data-testid="stSlider"] label p{font-size:0.75rem;color:#8a9bb0}
a[data-testid="stPageLink-NavLink"]{background:#121b27;border:1px solid #243246;border-radius:8px;padding:0.35rem 0.5rem;justify-content:center;width:100%}
a[data-testid="stPageLink-NavLink"]:hover{background:#1a2736}
a[data-testid="stPageLink-NavLink"][aria-current="page"]{background:#27527a;border-color:#34648f}
a[data-testid="stPageLink-NavLink"] p{font-size:0.95rem;font-weight:600;color:#dbe3ee}
.cc-note{font-size:1.1rem;color:#a9b8cb;margin:0.2rem 0 1rem 0;padding:0.5rem 0.9rem;background:#121b27;border-left:3px solid #4aa3a0;border-radius:6px}
.cc-h{font-size:1.15rem;font-weight:700;color:#dbe3ee;margin:0.8rem 0 0.1rem 0}
.cc-ver{font-size:0.75rem;font-weight:700;letter-spacing:.1em;padding:1px 8px;border-radius:999px;border:1px solid #34648f;color:#8fb8de;margin-left:8px}
</style>"""


def setup(page_title: str = "Emergency response command center") -> None:
    """Call first on every page: layout and theme."""
    st.markdown(CSS, unsafe_allow_html=True)


def subtitle(slot, text: str) -> None:
    slot.markdown(f"<div class='cc-sub'>{text}</div>", unsafe_allow_html=True)


def header(control_weights: tuple = ()) -> tuple:
    """Title, the navigation links, and one column per extra control.

    Returns (subtitle slot, list of control columns); fill the slot with subtitle(slot, text) once the
    page knows what it shows (for example the selected run).
    """
    cols = st.columns([2.6, 3.0, *control_weights], vertical_alignment="bottom")
    cols[0].markdown(f"<div class='cc-title'>{TITLE}</div>", unsafe_allow_html=True)
    slot = cols[0].empty()
    links = [(label, path) for label, path in PAGES if (BASE / path).exists()]
    with cols[1]:
        for col, (label, path) in zip(st.columns(len(links)), links):
            col.page_link(path, label=label)
    return slot, cols[2:]
