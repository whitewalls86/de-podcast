import asyncio
import json
import os
import subprocess
from types import SimpleNamespace

import anthropic


def _run_claude(prompt: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["claude", "-p", "--output-format", "json"],
        input=prompt,
        shell=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _log_usage(usage: dict) -> None:
    parts = [
        f"input={usage.get('input_tokens', '?')}",
        f"output={usage.get('output_tokens', '?')}",
    ]
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_read:
        parts.append(f"cache_read={cache_read}")
    cost = usage.get("total_cost_usd")
    if cost is not None:
        parts.append(f"cost=${cost:.4f}")
    print(f"[dev-client] tokens: {', '.join(parts)}", flush=True)


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

        raw = result.stdout.strip()
        if not raw:
            raise RuntimeError("claude CLI returned empty output")

        try:
            envelope = json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"claude CLI returned non-JSON output: {e}\nRaw: {raw!r}") from e

        text = envelope.get("result", "").strip()
        if not text:
            raise RuntimeError(f"claude CLI JSON missing 'result' field: {raw!r}")

        usage = envelope.get("usage", {})
        if usage:
            _log_usage(usage)

        return SimpleNamespace(content=[SimpleNamespace(text=text)])


class DevClient:
    def __init__(self):
        self.messages = _Messages()


def get_anthropic_client():
    use_dev = os.environ.get("USE_DEV_CLIENT", "").lower() == "true"
    if use_dev:
        return DevClient()
    return anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
