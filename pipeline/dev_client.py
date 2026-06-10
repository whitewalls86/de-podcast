import asyncio
import json
import os
import re
import subprocess
from types import SimpleNamespace

import anthropic

# API model IDs include a date suffix (e.g. claude-haiku-4-5-20251001) that the
# Claude Code CLI doesn't accept — strip it so --model gets claude-haiku-4-5.
_DATE_SUFFIX = re.compile(r"-\d{8}$")


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[: text.rfind("```")]
    return text.strip()


def _run_claude(prompt: str, model: str | None = None) -> subprocess.CompletedProcess:
    cmd = ["claude", "-p", "--output-format", "json"]
    if model:
        cmd += ["--model", _DATE_SUFFIX.sub("", model)]
    return subprocess.run(
        cmd,
        input=prompt,
        shell=False,
        capture_output=True,
        text=True,
        timeout=120,
    )


# claude-haiku-4-5 API pricing (USD per million tokens)
_INPUT_COST_PER_M = 1.00
_OUTPUT_COST_PER_M = 5.00
_CACHE_READ_COST_PER_M = 0.10


def _log_usage(usage: dict) -> None:
    input_tokens = usage.get("input_tokens", 0) or 0
    output_tokens = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0

    parts = [f"input={input_tokens}", f"output={output_tokens}"]
    if cache_read:
        parts.append(f"cache_read={cache_read}")

    est_cost = (
        input_tokens * _INPUT_COST_PER_M
        + output_tokens * _OUTPUT_COST_PER_M
        + cache_read * _CACHE_READ_COST_PER_M
    ) / 1_000_000
    parts.append(f"est. ${est_cost:.4f}")

    print(f"[dev-client] tokens: {', '.join(parts)}", flush=True)


class _Messages:
    async def create(
        self, *, model: str = "", system: str = "", messages: list[dict], **kwargs
    ) -> object:
        prompt = f"{system}\n\n{messages[0]['content']}" if system else messages[0]["content"]
        try:
            result = await asyncio.to_thread(_run_claude, prompt, model or None)
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

        text = _strip_fences(envelope.get("result", ""))
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
