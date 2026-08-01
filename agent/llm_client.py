"""
llm_client.py
-------------
Thin, provider-agnostic wrapper around chat-completion + tool-calling APIs.

Default provider: **Groq** (https://console.groq.com) -- it's free, fast,
and its API is OpenAI-compatible with full function/tool-calling support,
so no special SDK is needed beyond `openai`.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any


class LLMClient:
    """Real LLM client. Defaults to Groq, but works with any OpenAI-compatible endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError(
                "The 'openai' package is required. Install with: pip install openai"
            ) from e

        self.api_key = api_key or os.environ.get("LLM_API_KEY")
        self.base_url = base_url or os.environ.get(
            "LLM_BASE_URL", "https://api.groq.com/openai/v1"
        )
        self.model = model or os.environ.get("LLM_MODEL", "llama-3.1-8b-instant")

        if not self.api_key:
            raise ValueError(
                "No API key found. Set LLM_API_KEY in your environment or .env file.\n"
                "Get a free Groq key at: https://console.groq.com/keys"
            )

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def chat(self, messages: list[dict], tools: list[dict], max_retries: int = 5) -> Any:
        """
        Send the conversation to the model and return the raw response message.
        """
        import openai

        for attempt in range(max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=0.2,
                    max_tokens=2048,
                )
                return response.choices[0].message
            except openai.RateLimitError as e:
                error_text = str(e)
                if "tokens per day" in error_text.lower() or "TPD" in error_text:
                    wait_hint = _extract_retry_seconds(error_text, allow_minutes=True)
                    wait_str = f"~{int(wait_hint // 60)} min" if wait_hint else "some time"
                    raise RuntimeError(
                        "Groq's free daily token quota for this model is used up "
                        f"for today (resets in {wait_str}). Options:\n"
                        "  1) Wait for the quota to reset and re-run, or\n"
                        "  2) Switch to a lighter model with its own separate quota, "
                        "e.g. set LLM_MODEL=llama-3.1-8b-instant in your .env file, or\n"
                        "  3) Use a different free Groq account/API key.\n"
                        f"Original error: {error_text}"
                    ) from e
                if attempt == max_retries:
                    raise
                wait = _extract_retry_seconds(error_text) or (2 ** attempt)
                print(f"[rate limit] hit provider limit, waiting {wait:.1f}s before retry "
                      f"({attempt + 1}/{max_retries})...")
                time.sleep(wait)
            except openai.BadRequestError as e:
                error_text = str(e)
                if "tool_use_failed" in error_text:
                    raise RuntimeError(
                        "The model attempted a tool call but generated malformed "
                        "syntax that the provider rejected (common with smaller/"
                        "faster free models). Try switching to a model with more "
                        "reliable tool-calling, e.g. set "
                        "LLM_MODEL=llama-3.3-70b-versatile in your .env file.\n"
                        f"Original error: {error_text}"
                    ) from e
                raise
            except openai.APIStatusError as e:
                if e.status_code == 413 and attempt < max_retries:
                    keep_n = max(0, 2 - attempt)
                    trimmed_tool = _trim_large_tool_outputs(messages, keep_last_n=keep_n)
                    trimmed_calls = _trim_large_tool_call_arguments(messages, keep_last_n=keep_n)
                    total = trimmed_tool + trimmed_calls
                    print(f"[too large] trimmed {total} old message(s) to fit the "
                          f"token budget, retrying ({attempt + 1}/{max_retries})...")
                    continue
                raise


def _extract_retry_seconds(error_text: str, allow_minutes: bool = False) -> float | None:
    if allow_minutes:
        match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", error_text)
        if match:
            minutes = float(match.group(1)) if match.group(1) else 0.0
            seconds = float(match.group(2))
            return minutes * 60 + seconds + 0.5
        return None
    match = re.search(r"try again in ([\d.]+)s", error_text)
    if match:
        return float(match.group(1)) + 0.5
    return None


def _trim_large_tool_call_arguments(
    messages: list[dict], keep_last_n: int = 1, min_len_to_trim: int = 300
) -> int:
    assistant_indices = [
        i for i, m in enumerate(messages)
        if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    to_trim = assistant_indices[:-keep_last_n] if len(assistant_indices) > keep_last_n else []
    trimmed_count = 0
    for i in to_trim:
        for tc in messages[i]["tool_calls"]:
            fn = tc.get("function", {})
            if fn.get("name") != "write_file":
                continue
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                continue
            content = args.get("content", "")
            if isinstance(content, str) and len(content) > min_len_to_trim:
                path = args.get("path", "?")
                args["content"] = f"[{len(content)} chars already written to {path} -- omitted here to save space]"
                fn["arguments"] = json.dumps(args)
                trimmed_count += 1
    return trimmed_count


def _trim_large_tool_outputs(
    messages: list[dict], keep_last_n: int = 2, min_len_to_trim: int = 400
) -> int:
    tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    to_trim = tool_indices[:-keep_last_n] if len(tool_indices) > keep_last_n else []
    trimmed_count = 0
    for i in to_trim:
        content = messages[i].get("content", "")
        if isinstance(content, str) and len(content) > min_len_to_trim:
            messages[i]["content"] = (
                content[:200] + "\n...[older tool output trimmed to save context space]"
            )
            trimmed_count += 1
    return trimmed_count


class MockLLM:
    def __init__(self, script: list[dict]):
        self._script = script
        self._step = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> Any:
        if self._step >= len(self._script):
            return _FakeMessage(content="Done.", tool_calls=None)

        step = self._script[self._step]
        self._step += 1

        if step["type"] == "text":
            return _FakeMessage(content=step["content"], tool_calls=None)

        if step["type"] == "tool_calls":
            calls = [
                _FakeToolCall(
                    id=f"call_{i}",
                    name=c["name"],
                    arguments=json.dumps(c["arguments"]),
                )
                for i, c in enumerate(step["calls"])
            ]
            return _FakeMessage(content=step.get("content", ""), tool_calls=calls)

        raise ValueError(f"Unknown mock script step type: {step['type']}")


class _FakeMessage:
    def __init__(self, content: str | None, tool_calls: list | None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self):
        return {
            "role": "assistant",
            "content": self.content,
            "tool_calls": (
                [tc.model_dump() for tc in self.tool_calls] if self.tool_calls else None
            ),
        }


class _FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.type = "function"

        class _Fn:
            pass

        self.function = _Fn()
        self.function.name = name
        self.function.arguments = arguments

    def model_dump(self):
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.function.name, "arguments": self.function.arguments},
        }