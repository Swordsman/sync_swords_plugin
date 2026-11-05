# When this works, when it doesn't, and when it isn't needed

Observe your harness rather than assuming. Read what actually arrives in context at session start: what's injected in full, how other memory files are shown, whether descriptions are cut off and where. The details below are the requirements; how a particular harness meets them varies and changes over time.

## What the harness needs

1. **Persistent memory across sessions,** stored as separate, named files or documents rather than one undivided blob.
2. **An always-loaded part.** At least one file (or an editable instruction block) injected in full at the start of every session. This is where always-on rules and `?!` pointers live.
3. **A visible listing of the other files,** shown to the agent each session with a per-file description or name. The descriptions are what make conditional loading work.
4. **Editable descriptions,** so they can be rewritten as triggers.
5. **On-demand reads and writes,** so the agent can open a file when its trigger fires and fix memory when something changes.

**Helpful but not required:** version tokens or atomic edits (safe concurrent changes), alias or keyword fields, size feedback on writes.

**An example of observed behavior** (Claude's memory feature, November 2026): a profile file and a preferences file were injected in full; every other file appeared as its path, its aliases and its description, with the description cut off at about 160 characters; the listing arrived at session start and again whenever the store changed; the preferences file had a cap of roughly 16,000 injected characters. Put the trigger at the front of a description, before any cut-off.

## When it isn't viable

- **No persistent memory,** or memory that doesn't survive the session.
- **One undivided memory blob** with no per-file loading. Nothing can be conditional.
- **Retrieval is fully automatic and invisible,** for example embedding similarity with no listing the agent can see. Descriptions can't act as triggers there. The always-on rules and the persist-or-lose habit may still help.
- **Descriptions can't be edited,** or memory is read-only to the agent.
- **No always-loaded part.** Pointers and always-on rules have nowhere to live.

## When it isn't necessary

- **The memory is small enough to sit entirely in the always-loaded part** without crowding it.
- **Short-lived or one-off use,** where nothing needs to survive many sessions.
- **The harness already injects the right files by situation,** through hooks or rules that fire mechanically. A mechanical trigger beats a written one; keep that, and use this system only for what it doesn't cover.
- **The user curates memory by hand and prefers it that way.** Their setup wins.
- **Memory holds only a handful of stable facts.**

## Costs

- **Reads cost tool calls and time.** Every triggered file is a read; `!!` files are read every session.
- **Restructuring takes a pass:** reading every file, classifying lines, rewriting descriptions. Do it once, then maintain it incrementally.
- **A bad trigger hides a file.** A description whose condition never occurs is worse than a plain summary. Check new descriptions against real situations.
- **The always-loaded file still has a cap.** Pointers are short, but they add up.
