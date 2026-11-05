# Where this came from, and why it works

## Origin

Developed by Joe (GitHub: Swordsman) working with Claude in November 2026. Over one long session, the agent kept failing to open memory files that were plainly relevant to what it was doing. It could see them listed; it just never opened them. Asking why produced two causes:

1. **The descriptions said what a file held, not when to use it.** "Notes about X and Y" gives the agent nothing to match against the situation it's in. A skill gets used because its description names a condition; a memory file described as a topic doesn't.
2. **Files get buried.** The list of available files sits far back in context as the session grows, and the agent's default under uncertainty is to skip a read rather than spend a tool call on it.

Everything below is a fix for one of those two causes, or for something found while fixing them.

## The model

**Memory is code.** Treat the memory store as a program the agent runs: the text (prose and shorthand) is the programming language, inference is the interpreter, attention is the parser. A file that opens "when X" is a branch with a condition. If the condition is never evaluated, the branch is dead code, however good its contents.

**Two kinds of presence.** Material in context is either always-on, guaranteed present every turn because it's injected in full, or dormant: somewhere in context, or only listed by name, and easy to overlook unless something points at it. Pointing is cheap: when the agent engages with a short reference in always-on text, the result points attention back at the material it names. So a one-line pointer in the always-loaded file can wake a large dormant file at the right moment.

**Descriptions are triggers.** A description that names a condition ("open before calling the payments API", "open when the user mentions the migration") turns the listing into a set of standing triggers. The agent matches the situation against conditions it can see, instead of guessing which topics might be relevant.

**Why mark always-on files (`!!`).** Some content has to hold every turn: how the user argues, how they make design decisions, rules that apply to everything. If such content lives in a conditional file, nothing knows to open it. The marker makes the condition "always".

**Why compartmentalize.** The always-loaded file is size-capped and its full text is re-sent with every turn for the rest of the session. Detail that only matters sometimes costs nothing per turn when it lives in its own file behind a trigger, and that file can then hold far more detail than the always-loaded one ever could.

**Why a file per project, with keywords.** So it's clear what's what without digging, and so a mention of the project name, or one of its keywords, matches the file.

**Why a session index.** Good ideas from past sessions get lost: the session ends, attention moves on, and nobody remembers which conversation held the design. An index of sessions where real progress or brainstorming happened, with the topics of each, lets the agent find and reread the right one instead of re-deriving it.

**Why persist or lose.** Anything only in the conversation is gone after the next compaction or session boundary. If something matters, write it to memory, a repo or a document while the session is still running, not at its end, because sessions can end without warning.

**Why a standing self-check.** A written rule only works if something brings it to mind. Asking "am I forgetting a memory or skill that's indicated right now?" turns the listing back into something the agent looks at, rather than something it has scrolled past.
