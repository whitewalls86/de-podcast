import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.clustering import cluster
from pipeline.discovery import discover
from pipeline.ranking import rank


async def main() -> None:
    if os.environ.get("USE_DEV_CLIENT", "").lower() != "true":
        sys.exit("USE_DEV_CLIENT must be set to 'true' to run this smoke test")

    sources_path = Path(__file__).parent.parent / "config" / "sources.json"

    print("Discovering articles...")
    articles = await discover(sources_path)
    print(f"  Discovered: {len(articles)} articles")

    print("Ranking articles...")
    ranked = await rank(articles)
    print(f"  Ranked (score >= 0.5): {len(ranked)} articles")

    if len(ranked) < 2:
        sys.exit(f"Need at least 2 ranked articles for clustering, got {len(ranked)}")

    print("Clustering articles...")
    batches = await cluster(ranked)

    batch_a = batches["batch_a"]
    batch_b = batches["batch_b"]
    print("\nResults:")
    print(f"  Batch A — '{batch_a['title']}': {len(batch_a['urls'])} URLs")
    print(f"  Batch B — '{batch_b['title']}': {len(batch_b['urls'])} URLs")


asyncio.run(main())
