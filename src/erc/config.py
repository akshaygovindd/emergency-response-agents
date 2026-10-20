"""Central configuration: every tunable number in the simulation lives here.

Changing a value here changes it everywhere. Every value is documented in
docs/ASSUMPTIONS.md so results can always be traced back to their settings.
"""
from __future__ import annotations

import os
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

# ───────────────────────── Paths ─────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCENARIO_DIR = PROJECT_ROOT / "data" / "scenarios"
LLM_CACHE_DIR = PROJECT_ROOT / "data" / "llm_cache"
LOG_DIR = PROJECT_ROOT / "logs"
RESULTS_DIR = PROJECT_ROOT / "results"

BASE_SEED = 42


# ───────────────────────── Experiment design ─────────────────────────
class ScenarioName(str, Enum):
    NORMAL = "normal"
    SURGE = "surge"
    BOTTLENECK = "bottleneck"


class Mode(str, Enum):
    NAIVE = "naive"                # baseline 1: nearest resources
    GREEDY = "greedy"              # baseline 2: scored allocation
    AGENTS = "agents"              # multi-agent, negotiation disabled
    NEGOTIATION = "negotiation"    # multi-agent with negotiation
    ORACLE = "oracle"              # negotiation + ground-truth incident data


# ───────────────────────── Environment ─────────────────────────
class EnvironmentConfig(BaseModel):
    grid_size_km: float = 20.0
    duration_min: int = 90
    time_step_min: int = 1
    n_hospitals: int = 3
    n_ambulances: int = 5
    n_als_ambulances: int = 2          # the rest are basic life support
    ambulance_capacity: int = 2
    n_responder_teams: int = 3
    n_doctors: int = 6
    n_nurses: int = 12


class TravelConfig(BaseModel):
    ambulance_speed_kmh: float = 60.0  # 1 km per minute before traffic
    traffic_factor_min: float = 0.8
    traffic_factor_max: float = 1.5
    on_scene_time_min: int = 5         # loading patients at the scene
    handover_time_min: int = 5         # handing patients over at the hospital


class DeteriorationConfig(BaseModel):
    """Synthetic condition model: 100 = stable, lower = worse.

    The deadline is the time until first medical contact. Once a crew is with
    the victim (on scene or in transport), decline is slowed by a care factor.
    """
    als_care_factor: float = 0.1       # advanced crew nearly stabilizes the victim
    bls_care_factor: float = 0.5       # basic crew halves the decline
    critical_threshold: float = 40.0   # below this, the victim counts as deteriorated
    deadline_range_min: dict[int, tuple[int, int]] = {
        5: (8, 15), 4: (15, 25), 3: (25, 40), 2: (40, 60), 1: (60, 90),
    }


class TreatmentConfig(BaseModel):
    duration_min: dict[int, int] = {1: 15, 2: 20, 3: 30, 4: 45, 5: 60}


# ───────────────────────── Scenarios ─────────────────────────
class ScenarioConfig(BaseModel):
    name: ScenarioName
    n_incidents: int = Field(gt=0)
    arrival_window_min: int = Field(gt=0, description="All incidents arrive within this window")
    severity_weights: list[float] = Field(min_length=5, max_length=5, description="P(severity 1..5)")
    n_seeds: int = Field(gt=0)
    ambulances_out_of_service: int = 0
    trauma_prefill: float = Field(default=0.0, ge=0, le=1, description="Share of trauma slots busy at t=0")


SCENARIOS: dict[ScenarioName, ScenarioConfig] = {
    ScenarioName.NORMAL: ScenarioConfig(
        name=ScenarioName.NORMAL, n_incidents=12, arrival_window_min=75,
        severity_weights=[0.20, 0.25, 0.25, 0.18, 0.12], n_seeds=10),
    ScenarioName.SURGE: ScenarioConfig(
        name=ScenarioName.SURGE, n_incidents=25, arrival_window_min=75,
        severity_weights=[0.15, 0.20, 0.25, 0.22, 0.18], n_seeds=10),
    ScenarioName.BOTTLENECK: ScenarioConfig(
        name=ScenarioName.BOTTLENECK, n_incidents=10, arrival_window_min=20,
        severity_weights=[0.05, 0.10, 0.15, 0.30, 0.40], n_seeds=5,
        ambulances_out_of_service=3, trauma_prefill=0.5),
}

ORACLE_SEEDS: dict[ScenarioName, int] = {ScenarioName.NORMAL: 3, ScenarioName.SURGE: 3}


def seeds_for(scenario: ScenarioName, oracle: bool = False) -> list[int]:
    """Deterministic seed list, identical for every system being compared."""
    n = ORACLE_SEEDS.get(scenario, 0) if oracle else SCENARIOS[scenario].n_seeds
    return [BASE_SEED + i for i in range(n)]


# ───────────────────────── LLM ─────────────────────────
class LLMConfig(BaseModel):
    model: str = Field(default_factory=lambda: os.getenv("ERC_MODEL", "gpt-4o-mini"))
    temperature: float = 0.0


# ───────────────────────── All settings ─────────────────────────
class Settings(BaseModel):
    env: EnvironmentConfig = EnvironmentConfig()
    travel: TravelConfig = TravelConfig()
    deterioration: DeteriorationConfig = DeteriorationConfig()
    treatment: TreatmentConfig = TreatmentConfig()
    llm: LLMConfig = LLMConfig()


SETTINGS = Settings()