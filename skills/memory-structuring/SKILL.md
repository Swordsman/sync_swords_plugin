---
name: memory-structuring
description: Opt-in system for structuring an agent's persistent memory so the right file is open at the moment it's needed - memory files treated as conditionally loaded skills, descriptions written as triggers, an always-on marker, and pointers in the always-loaded file. Use when a user asks about organizing, curating or fixing agent memory, when memory files are overloaded or relevant ones never get opened, or when setting up memory conventions. Never apply it without first explaining it fully and getting the user's explicit permission.
---

# Memory structuring (opt-in)

A way to organize an agent's persistent memory so that the material a task needs is actually in front of the agent when the task happens. Memory files are treated like skills: each one opens under a stated condition, a marker flags the few that must always be present, and short pointers in the always-loaded file wake the rest. It came out of noticing that relevant memory files were almost never opened, even when the agent could see they existed.

## Rule zero: explicit, informed permission

This system rewrites how a user's memory is organized. Users may have their own setup, possibly an elaborate one, and an agent that restructures it uninvited can destroy work and trust. So:

1. **Survey, read-only.** List the memory store. Note its size, the always-loaded file's size against its cap, and any conventions already in use (prefixes, description styles, index files, naming). Change nothing.
2. **Check viability first.** Read `references/viability.md`. If the harness lacks what this needs, or the user's setup makes it unnecessary, say so plainly and stop there.
3. **Inform fully.** Tell the user, in plain words: what the system is, why it works (`references/why.md`), what it would change in *their* store specifically (which files get new descriptions, which lines would move where, which new files would appear), what it costs (more reads, one restructuring pass), and when it doesn't fit.
4. **Ask.** Yes, no, or which parts. Partial adoption is fine. Prefix names can be changed to anything the user likes.
5. **Record the answer** as one line in the always-loaded file, so it isn't asked again and a "no" holds in later sessions too. After a "no", leave memory alone unless the user brings it up again.
6. **If yes: back up, preview, then apply.** Keep a copy of every file's current content (or show it) before editing. Show the proposed changes before writing them. Apply in small steps and report what changed.

An existing convention the user already has takes precedence over this one. Adapt to it, or ask.

## The system in brief

- **Memory is code.** Text is the language, inference the interpreter, attention the parser. Files open under conditions, like branches. Anything that must hold every turn has to live where it's always loaded.
- **Two kinds of presence.** Always-on: injected in full every session. Dormant: present somewhere in context, or only listed, and needing a trigger to wake. A short pointer in always-on text wakes the dormant material it names.
- **Descriptions are triggers, not summaries.** "Open before/when X" gets a file opened at the right moment; "this is about X and Y" never does.
- **`!!`** marks a file whose contents must always be in mind: if loaded, keep it in mind; if not, read it.
- **`?!X:Y`** in the always-loaded file means "when X is relevant, read file Y".
- **Compartmentalize.** The always-loaded file is size-capped and re-paid every turn; detail that doesn't need to be always-on goes into its own file, which can then hold more.
- **Routing files** sit above specifics ("how to choose a tool" pointing to each tool's file).
- **A file per project**, with a concise description plus 1-5 keywords.
- **A session index** of sessions where real progress or brainstorming happened.
- **Persist or lose.** Anything not written down is gone at the next compaction or session.
- **A standing self-check:** "Am I forgetting to load or consider a memory or skill that's indicated right now? Is anything important being overlooked?"

## Reference files

Read every one of them in full before explaining the system to a user or applying it. They're short.

| File | What it covers |
|---|---|
| `references/why.md` | Where this came from, the diagnosis, and the reasoning behind each piece |
| `references/viability.md` | What a harness needs for this to work, what makes it not viable, what makes it unnecessary, and its costs |
| `references/syntax.md` | Description format, `!!`, `?!`, temporary lines, keywords |
| `references/procedures.md` | The self-check, classifying a line, the new-file checklist, the full sweep, size-cap handling, the session index |

The harness's own memory rules (privacy, what may be stored, tagging) always take precedence over anything here.
