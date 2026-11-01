---
name: drone-uav
description: "Fly a self-piloted drone: hand heavy reading, reviewing or editing to an inference API (DeepSeek today, other providers later) as a detached job, so the coordinator's context never carries the weight. Use when a task means reading many files, reviewing a large diff, or editing code, and the coordinator would otherwise make dozens of tool calls; also when the user says drone, UAV, or offload."
---

# drone-uav

Terms (Joe): a **drone** is a pseudo-subagent reached through an inference API; a **pilot** is a subagent
operating one; a **drone pilot** is the pair; a **UAV** is a drone piloted by code, with no subagent in the
loop. This skill is the UAV: `scripts/drone_uav.py`, stdlib only.

## Flow

```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/drone_uav.py bundle JOB --task task.txt FILES...   # one input, line-numbered
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/drone_uav.py run JOB                              # detached; returns at once
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/drone_uav.py wait JOB                             # run in the background; prints only the digest
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/drone_uav.py apply JOB --root REPO [--dry-run]    # line-based edits
```

- **Plan first, combine everything:** every file the drone needs goes into one bundle; one call.
- **Request rules (fixed in code):** one user message, no system prompt, no max_tokens, no temperature or
  top_p; thinking on at max effort; model deepseek-v4-pro by default. If a system prompt ever seems
  necessary, ask Joe first.
- **Everything lands on disk** in JOB: bundle, thinking, answer, usage, finish reason, errors, apply report.
- **Edits are by line number**, each quoting its first original line; overlaps refused; applied bottom-up.
- **`--mode all-or-nothing`** (default) writes nothing if any edit fails; `--mode partial` applies the good
  ones. Also `DRONE_UAV_APPLY_MODE`; unknown values are errors.
- **Markers stay plain** unless a bundled file contains them; then a random token is added and regrown until
  it's absent (`--token-on-collision grow|fail`, `--max-tries`). Edits outside the EDITS section are never
  applied; an answer without one fails loud.
- When a drone answers in the wrong shape, re-run with the shape restated; for a file the tool can't edit
  safely (its own markers inside), ask for whole files between a fresh token.
