"""Keep a long-running Streamlit process in step with the code on disk.

Streamlit reloads the page scripts when they change but not the modules under src/, so after a redeploy the
running process could build bundles with old Python and draw them with new JavaScript. `refresh()` reloads the
erc.dashboard modules once per process and again whenever one of their source files changes.
"""
import importlib
import sys
from pathlib import Path

import streamlit as st

SOURCE_DIR = Path(__file__).resolve().parents[1] / "src" / "erc" / "dashboard"


def source_stamp() -> float:
    return max(p.stat().st_mtime for p in SOURCE_DIR.glob("*.py"))


@st.cache_resource
def _loaded() -> dict:
    return {"stamp": None}


def refresh() -> None:
    state, stamp = _loaded(), source_stamp()
    if state["stamp"] == stamp:
        return
    names = sorted(name for name in sys.modules if name.startswith("erc.dashboard."))
    for _ in range(2):                         # twice: the second pass rebinds `from x import y` to the reloaded objects
        for name in names:
            importlib.reload(sys.modules[name])
    state["stamp"] = stamp
