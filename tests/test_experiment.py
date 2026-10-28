"""Tests: the experiment runner must be reproducible and never duplicate results."""
import pytest

import erc.config as config
import erc.eval.experiment as exp
from erc.config import Mode, ScenarioName

V = "v2"


@pytest.fixture(autouse=True)
def isolated_output(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")


def test_runs_are_saved_with_logs(tmp_path):
    exp.run_experiment([Mode.NAIVE, Mode.GREEDY], [ScenarioName.NORMAL], seeds=[42], version=V, progress=False)
    assert len(exp.load_runs(V)) == 2
    assert (tmp_path / "results" / V / "runs.jsonl").exists()
    assert (tmp_path / "logs" / V / "greedy" / "normal_seed42_greedy.jsonl").exists()


def test_rerun_replaces_instead_of_duplicating():
    for _ in range(2):
        exp.run_experiment([Mode.NAIVE], [ScenarioName.NORMAL], seeds=[42], version=V, progress=False)
    assert len(exp.load_runs(V)) == 1


def test_tables():
    exp.run_experiment([Mode.NAIVE, Mode.GREEDY], [ScenarioName.NORMAL], seeds=[42, 43], version=V, progress=False)
    runs = exp.load_runs(V)
    assert len(exp.summary_table(runs)) == 2
    paired = exp.paired_table(runs)
    assert list(paired["mode"]) == ["naive"] and paired["seeds"].iloc[0] == 2


def test_runs_are_reproducible():
    a = exp.run_one(ScenarioName.SURGE, 42, Mode.GREEDY, V)
    b = exp.run_one(ScenarioName.SURGE, 42, Mode.GREEDY, V)
    assert a == b


def test_every_mode_is_registered():
    assert set(exp.POLICIES) == set(Mode)


def test_every_row_and_table_carries_the_version():
    exp.run_experiment([Mode.NAIVE, Mode.GREEDY], [ScenarioName.NORMAL], seeds=[42, 43], version=V, progress=False)
    runs = exp.load_runs(V)
    assert all(r["version"] == V for r in runs)
    for table in (exp.summary_table(runs), exp.paired_table(runs), exp.coordination_table(runs)):
        assert table.empty or set(table["version"]) == {V}


def test_v1_is_never_written_by_default(tmp_path):
    with pytest.raises(PermissionError):
        exp.run_experiment([Mode.NAIVE], [ScenarioName.NORMAL], seeds=[42], version="v1", progress=False)
    with pytest.raises(PermissionError):
        exp.run_one(ScenarioName.NORMAL, 42, Mode.NAIVE, "v1")
    assert not (tmp_path / "results").exists() and not (tmp_path / "logs").exists()


def test_v1_write_needs_the_explicit_flag(tmp_path):
    exp.run_experiment([Mode.NAIVE], [ScenarioName.NORMAL], seeds=[42], version="v1",
                       allow_v1_write=True, progress=False)
    assert (tmp_path / "results" / "v1" / "runs.jsonl").exists()


def test_unknown_version_is_refused():
    with pytest.raises(ValueError):
        exp.run_experiment([Mode.NAIVE], [ScenarioName.NORMAL], seeds=[42], version="v3", progress=False)


def test_tables_refuse_to_mix_versions():
    exp.run_experiment([Mode.NAIVE], [ScenarioName.NORMAL], seeds=[42], version=V, progress=False)
    rows = exp.load_runs(V)
    with pytest.raises(ValueError):
        exp.summary_table(rows + [{**rows[0], "version": "v1"}])
    with pytest.raises(ValueError):
        exp.summary_table([{k: v for k, v in rows[0].items() if k != "version"}])
