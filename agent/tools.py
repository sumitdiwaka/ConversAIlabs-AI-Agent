"""
tools.py
--------
File-system tools exposed to the LLM as "function calls" / tool-use.

Every tool is sandboxed to the target repository root (repo_root) so the
agent can never read or write files outside the project it was asked to
work on. This is the agent's only way of perceiving and changing the
codebase -- there is no other side channel.

Tools provided:
    - list_directory(path)   : explore repo structure
    - read_file(path)        : read a file's contents (with line numbers)
    - search_code(pattern)   : grep-like search across the repo
    - write_file(path, content): create or overwrite a file
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Directories we never want to walk into while exploring a repo.
IGNORED_DIRS = {
    ".git", "node_modules", "dist", "build", ".idea", ".vscode",
    "__pycache__", ".next", "coverage",
}


class RepoTools:
    """Sandbox wrapper around a target repository directory."""

    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root).resolve()
        if not self.repo_root.exists():
            raise FileNotFoundError(f"Repo path does not exist: {self.repo_root}")

    # ------------------------------------------------------------------ #
    # Safety: resolve a user/LLM supplied relative path and make sure it
    # stays *inside* repo_root. This stops path-traversal ("../../etc").
    # ------------------------------------------------------------------ #
    def _safe_path(self, rel_path: str) -> Path:
        candidate = (self.repo_root / rel_path).resolve()
        if self.repo_root not in candidate.parents and candidate != self.repo_root:
            raise PermissionError(
                f"Path '{rel_path}' escapes the repository sandbox."
            )
        return candidate

    # ------------------------------------------------------------------ #
    # Tool: list_directory
    # ------------------------------------------------------------------ #
    def list_directory(self, path: str = ".") -> str:
        base = self._safe_path(path)
        if not base.exists():
            return f"ERROR: path '{path}' does not exist."

        lines = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            rel_root = os.path.relpath(root, self.repo_root)
            depth = 0 if rel_root == "." else rel_root.count(os.sep) + 1
            indent = "  " * depth
            if rel_root != ".":
                lines.append(f"{indent}{os.path.basename(root)}/")
            for f in sorted(files):
                lines.append(f"{indent}  {f}")
        return "\n".join(lines) if lines else "(empty directory)"

    # ------------------------------------------------------------------ #
    # Tool: read_file
    # ------------------------------------------------------------------ #
    def read_file(self, path: str) -> str:
        target = self._safe_path(path)
        if not target.exists() or not target.is_file():
            return f"ERROR: file '{path}' not found."
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"ERROR: '{path}' is a binary file, cannot read as text."
        numbered = "\n".join(
            f"{i + 1:>4}| {line}" for i, line in enumerate(content.splitlines())
        )
        return numbered if numbered else "(empty file)"

    # ------------------------------------------------------------------ #
    # Tool: search_code (grep-like, used during exploration)
    # ------------------------------------------------------------------ #
    def search_code(self, pattern: str, path: str = ".") -> str:
        base = self._safe_path(path)
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            return f"ERROR: invalid regex pattern: {e}"

        matches = []
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
            for fname in files:
                fpath = Path(root) / fname
                try:
                    text = fpath.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if regex.search(line):
                        rel = os.path.relpath(fpath, self.repo_root)
                        matches.append(f"{rel}:{lineno}: {line.strip()}")

        if not matches:
            return f"No matches for pattern '{pattern}'."
        return "\n".join(matches[:200])  # cap output size

    # ------------------------------------------------------------------ #
    # Tool: write_file  (create or overwrite)
    # ------------------------------------------------------------------ #
    def write_file(self, path: str, content: str) -> str:
        target = self._safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        existed = target.exists()
        target.write_text(content, encoding="utf-8")
        action = "Updated" if existed else "Created"
        return f"{action} file: {path} ({len(content.splitlines())} lines)"


# ---------------------------------------------------------------------- #
# OpenAI/Groq-style tool (function) schemas. These are sent to the LLM so
# it knows what tools exist and what arguments each one takes.
# ---------------------------------------------------------------------- #
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_directory",
            "description": (
                "List files and folders inside the repository (recursively), "
                "starting at the given relative path. Use this first to "
                "understand the project layout."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path inside the repo. Use '.' for repo root.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the full contents of a file (with line numbers) at the given relative path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside the repo."}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": (
                "Search the repository for a regex pattern (like grep) to "
                "quickly locate relevant code, e.g. route definitions, "
                "model fields, or function names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for."},
                    "path": {"type": "string", "description": "Relative path to search under. Defaults to repo root."},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Create a new file or overwrite an existing file with the given "
                "full content. Always write the COMPLETE file content, not a diff/patch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path inside the repo."},
                    "content": {"type": "string", "description": "Full new content of the file."},
                },
                "required": ["path", "content"],
            },
        },
    },
]
