"""
Basic unit tests for agent/tools.py -- run with: python -m pytest tests/
(or just `python tests/test_tools.py` for a plain run without pytest).
"""

import shutil
import tempfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools import RepoTools  # noqa: E402


def make_sample_repo() -> str:
    tmp = tempfile.mkdtemp()
    (Path(tmp) / "app").mkdir()
    (Path(tmp) / "app" / "notes.js").write_text("console.log('hello');\n")
    (Path(tmp) / "node_modules").mkdir()
    (Path(tmp) / "node_modules" / "junk.js").write_text("should be ignored")
    return tmp


def test_list_directory_ignores_node_modules():
    repo = make_sample_repo()
    try:
        tools = RepoTools(repo)
        listing = tools.list_directory(".")
        assert "notes.js" in listing
        assert "junk.js" not in listing
    finally:
        shutil.rmtree(repo)


def test_read_file_returns_numbered_lines():
    repo = make_sample_repo()
    try:
        tools = RepoTools(repo)
        content = tools.read_file("app/notes.js")
        assert "1|" in content
        assert "console.log" in content
    finally:
        shutil.rmtree(repo)


def test_write_file_creates_and_overwrites():
    repo = make_sample_repo()
    try:
        tools = RepoTools(repo)
        msg1 = tools.write_file("app/new.js", "const x = 1;")
        assert "Created" in msg1
        msg2 = tools.write_file("app/new.js", "const x = 2;")
        assert "Updated" in msg2
        assert "const x = 2;" in tools.read_file("app/new.js")
    finally:
        shutil.rmtree(repo)


def test_write_file_blocks_path_traversal():
    repo = make_sample_repo()
    try:
        tools = RepoTools(repo)
        try:
            tools.write_file("../escape.js", "malicious")
            assert False, "should have raised PermissionError"
        except PermissionError:
            pass
    finally:
        shutil.rmtree(repo)


def test_search_code_finds_pattern():
    repo = make_sample_repo()
    try:
        tools = RepoTools(repo)
        result = tools.search_code("console")
        assert "notes.js" in result
    finally:
        shutil.rmtree(repo)


if __name__ == "__main__":
    tests = [
        test_list_directory_ignores_node_modules,
        test_read_file_returns_numbered_lines,
        test_write_file_creates_and_overwrites,
        test_write_file_blocks_path_traversal,
        test_search_code_finds_pattern,
    ]
    for t in tests:
        t()
        print(f"PASS: {t.__name__}")
    print("\nAll tests passed.")
