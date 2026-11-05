---
name: arc-agents
description: Joe's concept for running conversations as separate arcs, each held by its own subagent, behind a cheap routing front, with a want-ads board where agents (or session winnows) post what they have and what they want and Jev matches them across sessions. Use when designing multi-agent conversation architecture, cross-session knowledge sharing, matching insights between projects, or routing messages to arc-specific agents.
---

# arc-agents

## Status
| part | state |
|---|---|
| concept | stub: worked out in conversation on 2026-10-31. Nothing is built. Joe's priority for now is making the existing skills usable first |
| next step when picked up | a minimal board: one profile per agent or winnow (what it has, what it wants), a matcher (one batched Jev call), and delivery of matches as messages |

## The idea
- **A dumb front, conversations in subagents.** The front only routes. Each conversation arc lives in its own subagent, so each turn pays for one arc's context instead of the whole conversation's, and the head barely holds anything, so it never compacts.
- **The front can be Jev plus code.** "Which live arc does this message belong to?" is a Choice over the open arcs, and "is this a new arc?" is a Noul.
- **Cross-pollination is explicit.** Agents talk to each other, within a session and across sessions.
- **The want-ads board ("dating profiles").** Every agent advertises what it has and what it wants, and matching runs in both directions.

The details, and the points to keep in mind (which don't block building), are in `design/notes.md`.
