"""Disk cache for agent calls: identical inputs never cost twice, and reruns are identical.

The key covers the agent's name, model, instructions, and the exact prompt, so any
change to an agent's design automatically produces fresh calls.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from agents import Agent, Runner

from erc.config import LLM_CACHE_DIR


@dataclass
class LLMResult:
    output: Any            # dict for structured agents, str otherwise
    tokens_in: int
    tokens_out: int
    latency_s: float
    cache_hit: bool


def cache_key(agent: Agent, prompt: str) -> str:
    payload = json.dumps({"agent": agent.name, "model": str(agent.model),
                          "instructions": str(agent.instructions), "prompt": prompt}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def run_cached(agent: Agent, prompt: str) -> LLMResult:
    path = LLM_CACHE_DIR / agent.name / f"{cache_key(agent, prompt)}.json"
    if path.exists():
        d = json.loads(path.read_text())
        return LLMResult(d["output"], d["tokens_in"], d["tokens_out"], 0.0, cache_hit=True)
    start = time.perf_counter()
    result = await Runner.run(agent, prompt)
    latency = time.perf_counter() - start
    out = result.final_output
    output = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
    usage = result.context_wrapper.usage
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"output": output, "tokens_in": usage.input_tokens,
                                "tokens_out": usage.output_tokens, "latency_s": latency}, indent=2))
    return LLMResult(output, usage.input_tokens, usage.output_tokens, latency, cache_hit=False)