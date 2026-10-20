"""Disk cache for agent calls: identical inputs never cost twice, and reruns are identical.

The key covers the agent's name, model, instructions, and the exact prompt. For agents
that use propose tools, the proposals submitted during the run are stored too and
restored on a cache hit, so cached reruns replay tool behavior exactly.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any

from agents import Agent, Runner

from erc.agents.context import AgentContext
from erc.config import LLM_CACHE_DIR


@dataclass
class LLMResult:
    output: Any            # dict for structured agents, str otherwise
    tokens_in: int
    tokens_out: int
    latency_s: float
    cache_hit: bool
    requests: int = 1      # model calls made inside this agent run (tool rounds)


def cache_key(agent: Agent, prompt: str) -> str:
    payload = json.dumps({"agent": agent.name, "model": str(agent.model),
                          "instructions": str(agent.instructions), "prompt": prompt}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


async def run_cached(agent: Agent, prompt: str, context: AgentContext | None = None) -> LLMResult:
    path = LLM_CACHE_DIR / agent.name / f"{cache_key(agent, prompt)}.json"
    if path.exists():
        d = json.loads(path.read_text())
        if context is not None and d.get("context"):
            context.restore(d["context"])
        return LLMResult(d["output"], d["tokens_in"], d["tokens_out"], 0.0, True, d.get("requests", 1))

    n_prop, n_inv = (len(context.proposals), len(context.invalid)) if context else (0, 0)
    start = time.perf_counter()
    result = await Runner.run(agent, prompt, context=context)
    latency = time.perf_counter() - start
    out = result.final_output
    output = out.model_dump(mode="json") if hasattr(out, "model_dump") else out
    usage = result.context_wrapper.usage
    requests = getattr(usage, "requests", 1) or 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "output": output, "tokens_in": usage.input_tokens, "tokens_out": usage.output_tokens,
        "requests": requests, "latency_s": latency,
        "context": context.snapshot_since(n_prop, n_inv) if context else None,
    }, indent=2))
    return LLMResult(output, usage.input_tokens, usage.output_tokens, latency, False, requests)