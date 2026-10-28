"""Tests: the experiment CLI must refuse unsafe invocations before doing any work."""
import subprocess
import sys
from pathlib import Path

RUN = str(Path(__file__).resolve().parents[1] / "scripts" / "run.py")


def run_cli(*args):
    return subprocess.run([sys.executable, RUN, *args], capture_output=True, text=True)


def test_running_a_mode_requires_an_explicit_version():
    r = run_cli("--mode", "naive")
    assert r.returncode != 0 and "--version is required" in r.stderr


def test_v1_write_is_refused_without_flag():
    r = run_cli("--mode", "naive", "--scenario", "normal", "--seed", "42", "--version", "v1")
    assert r.returncode != 0 and "frozen" in r.stderr
