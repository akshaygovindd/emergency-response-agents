"""Tests: the experiment runner must be reproducible and never duplicate results."""
import pytest

import erc.eval.experiment as exp
from erc.config import Mode, ScenarioName


@pytest.fixture(autouse=True)
def isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(exp, "RUNS_FILE", tmp_path / "runs.jsonl")
    monkeypatch.setattr(exp, "LOG_DIR", tmp_path / "logs")


def test_runs_are_saved_with_logs(tmp_path):
    exp.run_experiment([Mode.NAIVE, Mode.GREEDY], [ScenarioName.NORMAL], seeds=[42], progress=False)
    assert len(exp.load_runs()) == 2
    assert (tmp_path / "logs" / "greedy" / "normal_seed42_greedy.jsonl").exists()


def test_rerun_replaces_instead_of_duplicating():
    for _ in range(2):
        exp.run_experiment([Mode.NAIVE], [ScenarioName.NORMAL], seeds=[42], progress=False)
    assert len(exp.load_runs()) == 1


def test_tables():
    exp.run_experiment([Mode.NAIVE, Mode.GREEDY], [ScenarioName.NORMAL], seeds=[42, 43], progress=False)
    runs = exp.load_runs()
    assert len(exp.summary_table(runs)) == 2
    paired = exp.paired_table(runs)
    assert list(paired["mode"]) == ["naive"] and paired["seeds"].iloc[0] == 2


def test_runs_are_reproducible():
    a = exp.run_one(ScenarioName.SURGE, 42, Mode.GREEDY)
    b = exp.run_one(ScenarioName.SURGE, 42, Mode.GREEDY)
    assert a == b


def test_unimplemented_mode_is_refused():
    with pytest.raises(ValueError):
        exp.run_one(ScenarioName.NORMAL, 42, Mode.NEGOTIATION)