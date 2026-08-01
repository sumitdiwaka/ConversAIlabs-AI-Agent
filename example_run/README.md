# Example run output

This folder is committed as *proof/demo evidence* only (normally the
target repo would live outside this project and would not be checked
in). It contains:

- `mock_run_transcript.txt` — full terminal output of running
  `python run_agent.py --repo-path ./demo_target --mock`, i.e. the
  agent's exploration, plan, tool calls, and summary against a fresh
  copy of the original `node-easy-notes-app` repo.
- `notes_app_after_agent_run/` — the target repo *after* the agent ran,
  so you can directly diff it against the original upstream repo to see
  exactly what changed (also shown as a `diff` in the main README).

For the real submission demo (with a live Groq key, no --mock), run the
commands in the main README and record your screen — the console output
will look the same, except the plan/summary text is generated live by
the LLM instead of the offline mock script.
