import asyncio
import os
import subprocess
from types import SimpleNamespace

import anthropic


def _strip_fences(text: str) -> str:
    """Remove markdown code fences that the claude CLI adds around JSON responses."""
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]  # drop opening ```[lang] line
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def _run_claude(prompt: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["claude", "-p"],
        input=prompt,
        shell=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


class _Messages:
    async def create(self, *, system: str = "", messages: list[dict], **kwargs) -> object:
        prompt = f"{system}\n\n{messages[0]['content']}" if system else messages[0]["content"]
        try:
            result = await asyncio.to_thread(_run_claude, prompt)
        except FileNotFoundError:
            raise FileNotFoundError(
                "claude CLI not found — install Claude Code or ensure it is on PATH"
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("claude CLI timed out after 120s") from e

        if result.returncode != 0:
            raise RuntimeError(
                f"claude CLI exited with code {result.returncode}: {result.stderr.strip()}"
            )
        text = _strip_fences(result.stdout.strip())
        if not text:
            raise RuntimeError("claude CLI returned empty output")

        return SimpleNamespace(content=[SimpleNamespace(text=text)])


class DevClient:
    def __init__(self):
        self.messages = _Messages()


def get_anthropic_client():
    use_dev = os.environ.get("USE_DEV_CLIENT", "").lower() == "true"
    if use_dev:
        return DevClient()
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
