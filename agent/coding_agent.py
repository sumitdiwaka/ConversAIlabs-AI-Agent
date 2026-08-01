"""
coding_agent.py
----------------
The agent's control loop. This is the piece that turns:

    "Improve the application so users can better organise and search
     their notes."

into actual, working code changes inside a target repository, with no
further human input.

Design:
    - A single ReAct-style tool-calling loop.
    - At each step the LLM either calls one or more tools (explore the
      repo / write a file) or replies with plain text (its PLAN or its
      final SUMMARY).
    - The loop terminates when the model replies with plain text tagged
      "SUMMARY:" (or, as a fallback, any final text once at least one
      write_file call has happened).
    - A hard iteration cap prevents runaway loops.

This file has no knowledge of "notes app" specifics -- the feature choice
is entirely up to the LLM, guided only by prompts.SYSTEM_PROMPT. That is
what lets the same agent generalise to a *different* follow-up request on
the same or a different repo.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .llm_client import LLMClient, MockLLM
from .prompts import SYSTEM_PROMPT
from .tools import RepoTools, TOOL_SCHEMAS

MAX_ITERATIONS = 25

# Some free/fast models (observed with Groq's llama-3.3-70b-versatile) will
# occasionally ignore the structured tool-calling API and instead print the
# tool call as plain text in a pseudo-syntax like:
#   <function(write_file)({"path": "...", "content": "..."})>
# This regex + json.raw_decode combo recovers those calls so the agent
# still executes them instead of silently doing nothing.
_PSEUDO_CALL_START = re.compile(r"<function\((\w+)\)\(")


def _extract_pseudo_tool_calls(text: str) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    pos = 0
    decoder = json.JSONDecoder()
    while True:
        match = _PSEUDO_CALL_START.search(text, pos)
        if not match:
            break
        name = match.group(1)
        json_start = match.end()
        try:
            args, json_end = decoder.raw_decode(text, json_start)
        except json.JSONDecodeError:
            # Malformed pseudo-call -- stop scanning rather than looping forever.
            break
        calls.append((name, args))
        pos = json_end
    return calls


def _sanitize_message(message) -> dict:
    """
    Build a minimal assistant message dict containing only the fields the
    OpenAI-compatible chat API actually accepts (role, content, tool_calls).

    Some SDK versions of message.model_dump() include extra fields (e.g.
    'annotations', 'refusal') that OpenAI itself ignores but that stricter
    OpenAI-compatible providers (e.g. Groq) reject with a 400 error when
    the message is echoed back into the next request. Stripping down to
    the essentials keeps the agent portable across providers.
    """
    out: dict = {"role": "assistant", "content": message.content}
    if getattr(message, "tool_calls", None):
        out["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    return out


@dataclass
class AgentResult:
    plan: str = ""
    summary: str = ""
    files_touched: list[str] = field(default_factory=list)
    transcript: list[str] = field(default_factory=list)  # human-readable log


class CodingAgent:
    def __init__(self, repo_root: str, llm: LLMClient | MockLLM, verbose: bool = True):
        self.tools = RepoTools(repo_root)
        self.llm = llm
        self.verbose = verbose

    def _log(self, msg: str, result: AgentResult) -> None:
        result.transcript.append(msg)
        if self.verbose:
            print(msg)

    def run(self, request: str) -> AgentResult:
        result = AgentResult()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Product request: {request}"},
        ]

        wrote_any_file = False
        empty_replies = 0  # guards against a model stalling with blank, non-tool replies

        self._log(f"\n{'=' * 70}\nAGENT START\nRequest: {request}\n{'=' * 70}\n", result)

        for i in range(MAX_ITERATIONS):
            message = self.llm.chat(messages, TOOL_SCHEMAS)
            text = (message.content or "").strip()

            # --- Recover tool calls the model wrote as plain text instead
            # --- of using the structured tool-calling API (see comment on
            # --- _extract_pseudo_tool_calls above).
            pseudo_calls: list[tuple[str, dict]] = []
            if not message.tool_calls and "<function(" in text:
                pseudo_calls = _extract_pseudo_tool_calls(text)

            if pseudo_calls:
                self._log(
                    f"\n[info] Model emitted {len(pseudo_calls)} tool call(s) as plain "
                    "text instead of using structured tool-calling; recovering them.\n",
                    result,
                )
                synthetic_tool_calls = [
                    {
                        "id": f"recovered_call_{i}_{j}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                    for j, (name, args) in enumerate(pseudo_calls)
                ]
                messages.append({"role": "assistant", "content": None, "tool_calls": synthetic_tool_calls})
                empty_replies = 0
                for call in synthetic_tool_calls:
                    name = call["function"]["name"]
                    args = json.loads(call["function"]["arguments"])
                    self._log(f"[tool call] {name}({args})", result)
                    try:
                        output = self._dispatch(name, args)
                    except Exception as e:  # noqa: BLE001
                        output = f"ERROR: {e}"
                    if name == "write_file":
                        wrote_any_file = True
                        if args.get("path") and args["path"] not in result.files_touched:
                            result.files_touched.append(args["path"])
                    preview = output if len(output) < 300 else output[:300] + " ...[truncated]"
                    self._log(f"[tool result] {preview}", result)
                    messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
                continue

            messages.append(_sanitize_message(message))

            # --- Plain text message (plan / summary / stray text) -------
            if not message.tool_calls:
                if text.startswith("PLAN:"):
                    result.plan = text
                    self._log(f"\n--- PLAN ---\n{text}\n", result)
                    empty_replies = 0
                    # Some models (esp. smaller/faster free ones) won't
                    # autonomously continue from "here's my plan" straight
                    # into making tool calls unless explicitly told to.
                    # Nudge it into the EXECUTE phase.
                    messages.append({
                        "role": "user",
                        "content": (
                            "Good. Now execute this plan: call write_file for "
                            "every file listed, each time with the FULL final "
                            "file content. Use the actual tool-calling "
                            "mechanism (not plain text). After all files are "
                            "written, reply with plain text starting with "
                            "'SUMMARY:'."
                        ),
                    })
                    continue

                if text.startswith("SUMMARY:"):
                    result.summary = text
                    self._log(f"\n--- SUMMARY ---\n{text}\n", result)
                    break

                if not text:
                    # Blank reply with no tool calls -- nudge, but bail out
                    # after a couple of empty turns instead of looping forever.
                    empty_replies += 1
                    self._log(
                        f"\n[info] Model returned an empty reply (attempt {empty_replies}); nudging it to continue.\n",
                        result,
                    )
                    if empty_replies >= 3:
                        self._log(
                            "\n[WARNING] Model stopped responding with no content after several nudges. Ending run.\n",
                            result,
                        )
                        break
                    next_step = (
                        "Please continue: call write_file to implement the plan."
                        if not wrote_any_file
                        else "Please reply now with plain text starting with 'SUMMARY:' describing the changes you made."
                    )
                    messages.append({"role": "user", "content": next_step})
                    continue

                # Non-empty text that isn't tagged PLAN/SUMMARY and contains no
                # recoverable pseudo tool calls.
                self._log(f"\n--- MODEL SAYS ---\n{text}\n", result)
                empty_replies = 0
                if wrote_any_file:
                    # Treat as an informal final summary rather than looping forever.
                    if not result.summary:
                        result.summary = text
                    break
                # Hasn't written anything yet -- nudge it toward EXECUTE.
                messages.append({
                    "role": "user",
                    "content": (
                        "Please proceed to implement the plan now by calling "
                        "the write_file tool (use real tool calls, not text)."
                    ),
                })
                continue

            # --- Real, structured tool calls -------------------------------
            empty_replies = 0
            for call in message.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}

                self._log(f"[tool call] {name}({args})", result)

                try:
                    output = self._dispatch(name, args)
                except Exception as e:  # noqa: BLE001 - surface tool errors to the model
                    output = f"ERROR: {e}"

                if name == "write_file":
                    wrote_any_file = True
                    if args.get("path") and args["path"] not in result.files_touched:
                        result.files_touched.append(args["path"])

                # Trim tool output shown in the transcript log (not what's sent to the model)
                preview = output if len(output) < 300 else output[:300] + " ...[truncated]"
                self._log(f"[tool result] {preview}", result)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": output,
                    }
                )
        else:
            self._log("\n[WARNING] Reached max iterations without a final SUMMARY.", result)

        self._log(f"\n{'=' * 70}\nAGENT END - files touched: {result.files_touched}\n{'=' * 70}\n", result)
        return result

    def _dispatch(self, name: str, args: dict) -> str:
        if name == "list_directory":
            return self.tools.list_directory(args.get("path", "."))
        if name == "read_file":
            return self.tools.read_file(args["path"])
        if name == "search_code":
            return self.tools.search_code(args["pattern"], args.get("path", "."))
        if name == "write_file":
            return self.tools.write_file(args["path"], args["content"])
        return f"ERROR: unknown tool '{name}'"
