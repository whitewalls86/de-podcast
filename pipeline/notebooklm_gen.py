import asyncio
from pathlib import Path


async def generate_episode(batch_key: str, title: str, urls: list[str]) -> str:
    await asyncio.sleep(0)  # placeholder for real async work
    return str(Path("data") / f"{batch_key}.mp3")
