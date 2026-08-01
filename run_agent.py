#!/usr/bin/env python3
"""
run_agent.py
------------
CLI entry point.

Usage:
    python run_agent.py --repo-path ./node-easy-notes-app \\
        --request "Improve the application so users can better organise and search their notes."

Environment (.env or exported vars):
    LLM_API_KEY   Free Groq API key from https://console.groq.com/keys
    LLM_BASE_URL  (optional) defaults to Groq's OpenAI-compatible endpoint
    LLM_MODEL     (optional) defaults to llama-3.3-70b-versatile

Offline demo (no API key needed):
    python run_agent.py --repo-path ./node-easy-notes-app --mock
"""

from __future__ import annotations

import argparse
import sys

from agent import CodingAgent, LLMClient
from agent.llm_client import MockLLM
from demo_mock_script import build_notes_app_mock_script


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI coding agent for an existing repo.")
    parser.add_argument("--repo-path", required=True, help="Path to the target repository.")
    parser.add_argument(
        "--request",
        default="Improve the application so users can better organise and search their notes.",
        help="Product requirement to implement.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Run with a scripted offline mock LLM (no API key / network needed).",
    )
    return parser.parse_args()


def main() -> int:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass  # python-dotenv is optional; env vars can be exported manually.

    args = parse_args()

    if args.mock:
        llm = MockLLM(script=build_notes_app_mock_script())
    else:
        llm = LLMClient()

    agent = CodingAgent(repo_root=args.repo_path, llm=llm)
    result = agent.run(args.request)

    print("\nFiles touched:")
    for f in result.files_touched:
        print(f"  - {f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
