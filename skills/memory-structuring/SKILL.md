---
name: memory-structuring
description: Opt-in system for structuring an agent's persistent memory so the right file is open at the moment it's needed - memory files treated as conditionally loaded skills, descriptions written as triggers, an always-on marker, and pointers in the always-loaded file. Use when a user asks about organizing, curating or fixing agent memory, when memory files are overloaded or relevant ones never get opened, or when setting up memory conventions. Never apply it without first explaining it fully and getting the user's explicit permission.
---

# Memory structuring (opt-in)

A way to organize an agent's persistent memory so that the material a task needs is actually in front of the agent when the task happens. Memory files are treated like skills: each one opens under a stated condition, a marker flags the few that must always be present, and short pointers in the always-loaded file wake the rest. It came out of noticing that relevant memory files were almost never opened, even when the agent could see they existed.

## Rule zero: explain, ask, and act only on approval

This system changes how a user's memory is organized, and memory is personal. Users may have their own setup, possibly an elaborate one. An agent that inspects or restructures it uninvited can destroy work and trust, even with good intentions. So:

1. **Don't look first.** Don't open, list or read the user's memory to size it up before they've agreed. Even a quiet read-only look at personal material is intrusive.
2. **Judge fit from your own environment.** You already know which tools you have and what your harness told you about itself. `references/viability.md` says what a harness needs for this to work, and where it's known to work. That's knowledge about the harness, not about the user. If your environment can't support it, the question is moot; you may mention the system exists, but don't push it.
3. **Explain fully, then ask.** Tell the user in plain words what the system is, how it works and why (`references/why.md`), where it works, what it costs, and that it would change how their memory is organized. Then ask whether they want it: yes, no, or which parts. Partial adoption is fine, and the markers can be renamed.
4. **Nothing happens without approval, and approval covers only what was approved.** "Yes, look at my memory and suggest changes" permits reading and proposing, not writing. Writing needs its own yes.
5. **When applying: back up, preview, small steps.** Keep a copy of each file's current content before editing it. Show proposed changes before writing them. Apply in small steps and report what changed.
6. **Remember the answer only if they agree.** Offer to note their decision in memory, so you don't ask again. After a "no", don't raise it again unless they do.

An existing convention the user already has takes precedence over this one. Adapt to it, or ask.

## The system in brief

- **Memory is code.** Text is the language, inference the interpreter, attention the parser. Files open under conditions, like branches. Anything that must hold every turn has to live where it's always loaded.
- **Two kinds of presence.** Always-on: injected in full every session. Dormant: present somewhere in context, or only listed, and needing a trigger to wake. A short pointer in always-on text wakes the dormant material it names.
- **Descriptions are triggers, not summaries.** "Open before/when X" gets a file opened at the right moment; "this is about X and Y" never does.
- **`!!`** marks a file whose contents must always be in mind: if loaded, keep it in mind; if not, read it.
- **`?!X:Y`** in the always-loaded file means "when X is relevant, read file Y".
- **`!lock`** at the start of a line protects it: never edited unless the user asks. Every other line is open to self-curation under a written edit policy.
- **Routers:** a big subject gets a router file with the real trigger and numbered sub-files described as `.`, reached only through the router.
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
| `references/syntax.md` | Description format, `!!`, `?!`, `!lock` and the edit policy, routers and sub-files, temporary lines, keywords, bulk data |
| `references/procedures.md` | The self-check, classifying a line, the new-file checklist, the full sweep, size-cap handling, the session index |

The harness's own memory rules (privacy, what may be stored, tagging) always take precedence over anything here.
