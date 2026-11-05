# Where this works, and how you'd know

Decide this from what you know about your own environment: the tools you've been given and what your harness has told you about itself. You never need to inspect a user's memory to answer it. If the requirements below don't hold where you're running, the system is moot there.

## What a harness needs

1. **Persistent memory across sessions,** kept as separate named files or documents, not one undivided blob.
2. **An always-loaded part:** at least one file or instruction block injected in full at the start of every session. This is where always-on rules and pointers live.
3. **A way for conditional files to be found:** either a listing of files with descriptions the agent sees each session, or an index the agent maintains itself inside the always-loaded part.
4. **Editable descriptions or index entries,** so they can be written as triggers.
5. **On-demand reads and writes,** so a file can be opened when its trigger fires.

**How you'd know:** you have tools for reading and writing persistent memory, and your harness describes memory that persists across sessions with some part loaded automatically. If you have no such tools, it doesn't apply.

## Where it's known to work

These details come from the products' behavior and documentation as of November 2026. They change, so trust current documentation over this list.

**Claude apps with the memory feature (claude.ai).** Memory is a set of files edited through memory tools. A profile file and a preferences file are injected in full. Every other file appears in a listing as its path, aliases and description, with descriptions cut off at about 160 characters. The listing arrives at session start and again whenever memory changes, and the preferences file holds about 16,000 characters. Everything here applies directly: preferences are the always-loaded part, and descriptions are the triggers.

**Claude Code** ([memory docs](https://code.claude.com/docs/en/memory), [skills docs](https://code.claude.com/docs/en/skills)).
- **Always-loaded:** the project and user `CLAUDE.md` files, loaded in full at launch, with `@imports` expanded. Also the first 200 lines or 25 KB of auto memory's `MEMORY.md` index.
- **Conditional, native:** auto memory's topic files are read on demand. There's no built-in listing of them with descriptions, so the `MEMORY.md` index lines play that role: write each index line as a trigger.
- **Skills are this pattern built in:** only the name and description sit in context until the skill is invoked. For content that is really a procedure, a skill may be the better home than a memory file.
- **Mechanical triggers already exist:** subdirectory `CLAUDE.md` files load when Claude touches that directory, `.claude/rules/*.md` with `paths:` load when matching files are touched, and SessionStart or UserPromptSubmit hooks can inject context. A mechanical trigger beats a written one: use these where they fit, and this system for what they don't cover.

**Elsewhere.** Any harness that meets the five requirements above. Where retrieval is fully automatic and invisible (for example embedding search with no listing), descriptions can't act as triggers, but the always-on rules and the persist-or-lose habit can still help.

## When it isn't viable

- No persistent memory, or memory that doesn't survive the session.
- One undivided memory blob, so nothing can be conditional.
- No always-loaded part, so pointers have nowhere to live.
- Memory the agent can't edit.

## When it isn't necessary

- The memory is small enough to sit entirely in the always-loaded part without crowding it.
- Short-lived or one-off use.
- The harness already loads the right material by situation, mechanically.
- The user curates memory by hand and prefers it that way.
- Memory holds only a handful of stable facts.

## Costs

- **Reads cost tool calls and time.** Every triggered file is a read, and `!!` files are read every session.
- **Adopting it takes one restructuring pass,** then incremental upkeep.
- **A bad trigger hides a file.** A description whose condition never occurs is worse than a plain summary.
- **The always-loaded part still has a cap.** Pointers are short, but they add up.
