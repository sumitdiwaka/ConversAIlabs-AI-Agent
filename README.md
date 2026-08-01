# AI Coding Agent — Notes App Assignment

A small autonomous coding agent that explores an existing repository,
plans an appropriate feature for a vague product re

The loop is capped at `MAX_ITERATIONS = 25` tool round-trips as a safety
net against runaway loops.

### How repository exploration works

All exploration goes through `agent/tools.py`'s `RepoTools`, sandboxed to
the target repo's root directory:

- `list_directory(path)` — recursive tree listing, skipping
  `node_modules`, `.git`, `dist`, `build`, etc.
- `read_file(path)` — returns file contents with line numbers (helps the
  model reference specific lines in its reasoning).
- `search_code(pattern, path)` — grep-style regex search across the repo,
  useful for quickly locating things like route definitions or a
  particular field name without reading every file.
- `write_file(path, content)` — creates or overwrites a file with full
  new content.

Every path is resolved and checked against the repo root before any
read/write (`RepoTools._safe_path`) — the agent **cannot** read or write
outside the target repository, even if the model hallucinates a
`../../` path.

The model is *not* told the file layout up front — it has to call
`list_directory` itself first, exactly like a human engineer opening the
project for the first time.

## How to run it

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Get a free Groq API key
Sign up at https://console.groq.com/keys (free, no credit card), then:
```bash
cp .env.example .env
# edit .env and paste your key into LLM_API_KEY
```

### 3. Clone the target repo
```bash
git clone https://github.com/callicoder/node-easy-notes-app.git
```

### 4. Run the agent
```bash
python run_agent.py --repo-path ./node-easy-notes-app \
  --request "Improve the application so users can better organise and search their notes."
```

The agent will print its exploration steps, its `PLAN:`, the files it
writes, and its final `SUMMARY:` to the terminal in real time — this is
what to capture in the screen recording.

To try a **different follow-up request** on the same repo (as will
happen in the interview), just change `--request`, e.g.:
```bash
python run_agent.py --repo-path ./node-easy-notes-app \
  --request "Add the ability to archive notes instead of deleting them."
```
No code changes are needed for a new request — the same explore → plan →
execute → summarize loop applies, and the LLM re-explores the (now
already-modified) repo fresh each run.

### Mock mode (offline, no API key required)

For local testing/demoing the agent *harness* itself without network
access, `--mock` swaps in `MockLLM`, which replays a scripted (but
protocol-identical) sequence of tool calls from `demo_mock_script.py`:

```bash
python run_agent.py --repo-path ./demo_target --mock
```

This exercises the exact same code path (`CodingAgent.run`, tool
dispatch, sandboxing, message loop) as a real API call would, which is
how this repo's own demo run (see below) was verified end-to-end without
needing a live key in this environment. **The real agent (without
`--mock`) does not use this script in any way** — it is purely a
test/demo fixture.

### Tests
```bash
python -m pytest tests/
# or, without pytest:
python tests/test_tools.py
```

## Assumptions & trade-offs

- **No frontend in this repo.** `node-easy-notes-app` is backend-only
  (Express REST API, no React/HTML UI). The agent therefore only touches
  backend files — model, controller, routes. If a UI existed, the same
  agent would explore and modify it too (the tools are language-agnostic
  text file operations).
- **Tags over a separate Category collection.** A dedicated
  `categories` collection with its own CRUD would be more "enterprise"
  but is over-engineering for a single-user notes API with no auth; an
  array field is the minimal correct solution and keeps all existing
  contracts intact.
- **Regex search, not a text index.** MongoDB's `$regex` is simple and
  requires no schema/index migration; a `$text` index would scale
  better for large datasets but needs an explicit index creation step
  that felt out of scope for a minimal, safe, additive change.
- **`write_file` overwrites whole files, not diffs.** This trades some
  token efficiency for reliability — partial patches from an LLM are a
  common source of corrupted files; full-file writes are easy to
  validate and impossible to mis-apply.
- **Route ordering.** `GET /notes/search` had to be registered *before*
  `GET /notes/:noteId`, otherwise Express would treat `"search"` as a
  `noteId` value and the existing single-note route would shadow it.
  The system prompt's "preserve existing functionality" instruction is
  what drives the model to notice and handle this correctly.
- **Entry-point wiring is explicitly enforced.** In an early real run, the \
LLM created a new `tag.routes.js` / `tag.controller.js` pair but never \
updated `server.js` to `require()` it -- the new endpoint was unreachable \
dead code, even though the file's own contents were correct. This is a \
common failure mode for autonomous coding agents: a file being *written* \
is not the same as it being *used*. The system prompt now explicitly \
requires the agent to (a) identify the app's entry point during EXPLORE, \
(b) update it whenever a new route/controller/module file is added, and \
(c) self-check every new file is actually reachable before writing its \
SUMMARY.
- **Free-tier LLM choice.** Groq's `llama-3.1-8b-instant` is the default --
  it's free, fast, and (importantly) has its own separate daily token
  quota from the larger `llama-3.3-70b-versatile` model, which is easy to
  exhaust after a few iterations while testing. If you have quota to
  spare and want higher-quality reasoning, set `LLM_MODEL=llama-3.3-70b-versatile`
  in `.env`. If you ever see a `RateLimitError` mentioning "tokens per
  day", that's the free tier's daily cap, not a bug -- either wait for it
  to reset (the error tells you how long) or switch models/keys.
- **Single-agent loop, not multi-agent.** For a task this scoped, one
  agent with a clear 4-phase prompt (explore/plan/execute/summarize)
  was judged more reliable and easier to reason about than a
  planner+coder multi-agent split, given the 2-3 hour time-box.
