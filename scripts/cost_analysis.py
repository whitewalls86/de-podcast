"""
One-shot cost analysis: runs discover → rank → cluster against the real
Anthropic API and prints token usage + estimated cost per call.

Usage:
    python scripts/cost_analysis.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import anthropic

from pipeline.clustering import build_system as cluster_build_system
from pipeline.discovery import discover
from pipeline.feedback import DEFAULT_FEEDBACK, build_few_shot_context
from pipeline.ranking import _MODEL, build_ranking_prompt
from pipeline.ranking import build_system as rank_build_system
from pipeline.topic import load_topic

_TOPIC_PATH = Path(__file__).parent.parent / "config" / "topic.json"

_INPUT_COST_PER_M = 1.00
_OUTPUT_COST_PER_M = 5.00
_CACHE_READ_COST_PER_M = 0.10


def cost(usage) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache = getattr(usage, "cache_read_input_tokens", 0) or 0
    return (
        inp * _INPUT_COST_PER_M + out * _OUTPUT_COST_PER_M + cache * _CACHE_READ_COST_PER_M
    ) / 1_000_000


def print_usage(label: str, usage) -> float:
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cache = getattr(usage, "cache_read_input_tokens", 0) or 0
    c = cost(usage)
    parts = [f"input={inp}", f"output={out}"]
    if cache:
        parts.append(f"cache_read={cache}")
    parts.append(f"cost=${c:.4f}")
    print(f"  [{label}] {', '.join(parts)}")
    return c


async def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set")

    client = anthropic.AsyncAnthropic(api_key=api_key)
    sources_path = Path(__file__).parent.parent / "config" / "sources.json"
    topic = load_topic(_TOPIC_PATH)

    print("Discovering articles...")
    articles = await discover(sources_path, hn_query=topic["hn_query"])
    print(f"  {len(articles)} articles discovered")

    print("\nRanking (real API call)...")
    few_shot = build_few_shot_context(path=DEFAULT_FEEDBACK)
    rank_prompt = build_ranking_prompt(articles, few_shot)
    rank_response = await client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=rank_build_system(topic),
        messages=[{"role": "user", "content": rank_prompt}],
    )
    rank_cost = print_usage("ranking", rank_response.usage)

    raw = rank_response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        end = raw.rfind("```")
        if end != -1:
            raw = raw[:end].strip()
    scores = json.loads(raw)
    ranked = [
        {**a, "score": s["score"], "topic_tags": s.get("topic_tags", [])}
        for a in articles
        for s in [next((x for x in scores if x["url"] == a["url"]), None)]
        if s and s.get("score", 0) >= 0.5
    ]
    ranked.sort(key=lambda a: a["score"], reverse=True)
    ranked = ranked[:10]
    print(f"  {len(ranked)} articles scored >= 0.5")

    if len(ranked) < 2:
        sys.exit("Not enough ranked articles to cluster — run during a heavier news day")

    print("\nClustering (real API call)...")
    items = [{"url": a["url"], "title": a["title"]} for a in ranked]
    cluster_msg = f"Group these articles into 2 batches:\n{json.dumps(items, indent=2)}"
    cluster_response = await client.messages.create(
        model=_MODEL,
        max_tokens=1024,
        system=cluster_build_system(topic),
        messages=[{"role": "user", "content": cluster_msg}],
    )
    cluster_cost = print_usage("clustering", cluster_response.usage)

    total = rank_cost + cluster_cost
    print(f"\n{'-' * 40}")
    print(f"  Total per run:   ${total:.4f}")
    print(f"  Daily (1 run):   ${total:.4f}")
    print(f"  Monthly (30d):   ${total * 30:.4f}")
    print(f"{'-' * 40}")


asyncio.run(main())
