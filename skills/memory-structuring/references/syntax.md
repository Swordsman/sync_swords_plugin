# Syntax

All prefixes are conventions, not requirements of any harness. If the user prefers other names, use theirs and record the mapping in the always-loaded file.

## Descriptions

Form: `importance: <what the file is for>. Open before/when <condition>, but not <exclusion>.`

A good description:
1. **Says when to use the file.** The condition is the point.
2. **Says what it's good for.**
3. **Gives an idea of what's inside,** enough to guess, not a table of contents.
4. **Contains the primary subject word,** so the situation it's needed in matches it.
5. **Is concise but complete.**
6. **Signals importance,** so it isn't skipped when its need is recognized.

Put the condition near the front, in case the harness cuts descriptions off.

- Weak: `Notes on the billing service, its history and the team's conventions`
- Strong: `importance: how to work on the billing service. Open before editing billing code or answering billing questions`

## `!!` (always aware)

A description starting with `!!` means: keep this file's full contents in mind. If it's loaded in context, attend to all of it; if it isn't, read it. Use it for content that must apply every turn. Any file that contains even part of such content needs `!!`, or that part moves into the always-loaded file. Keep `!!` files few and small; each one is a read every session.

## `?!X:Y` (pointer)

A line in the always-loaded file meaning "when X is relevant, read file Y". It puts a trigger where it can't be missed. Use pointers for high-value conditions, and for files whose listing might be overlooked. Several files may follow one condition: `?!X:Y, Z`.

## `!lock` (protected lines)

A line starting with `!lock` is protected: it's important and is never edited, condensed, moved or deleted unless the user asks. Use it for text the user wants kept word for word, and for the line that defines the markers. Every other line is open to self-curation, done by a written edit policy.

The always-loaded file carries one locked line that defines the markers and points to the policy file, for example: `!lock Markers: '!lock' = protected; other lines may be curated following <policy file>; '!!' = always aware; '?!X:Y' = pointer`. The policy file says what curation keeps: every fact's meaning, the user's wording where it carries the point, tags and other tools' dated lines; and that a stated instruction is never softened or reinterpreted while condensing.

## Routers and sub-files

A subject too big for one file gets a router file plus numbered sub-files (`hooks-index`, `hooks-1`, `hooks-2`, ...). The router carries the real trigger description and one line per sub-file saying when to open it. Sub-files get the description `.` (or none, if the harness allows), so they don't clutter the listing: they're reached through the router, never opened from the listing directly.

## Temporary lines

Lines that hold for a phase of work, not permanently, carry a marker (for example `-$-`). Any file holding them gets a one-line note saying what the marker means and that such lines are removed once no longer needed.

## Keywords

Project and area files carry 1-5 keywords (more only for a good reason), in the harness's alias or keyword field if it has one, otherwise in the description. They're what lets a mention of the project, or one of its other names, find the file.

## Bulk data

Memory files are for triggers and compact facts; every read of one costs context. Large or structured data (records, logs, graphs, payloads) belongs where code can read and write it without passing through the context. In claude.ai/code sessions that can be an artifact database through the lsdb skill: a memory file then holds only the store's URL, what its collections are for, and when to query it. Setting one up is part of the same consent as the rest of this skill.
