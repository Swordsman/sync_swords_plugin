#!/usr/bin/env python3
"""Message agents on the dsx tree store. Each message is a small context of its own (an agent); code, not attention,
decides which agents get asked what.

Context per agent (tree 1, the dsx node table):
  system: AGENT_PROMPT -> [user: shared payload -> assistant: prefilled ack] -> user: the agent's message ->
  assistant: prefilled ack (= the agent id) -> each question forks here, so an agent's trunk never grows.
Shared material goes in the payload, ahead of every agent's own message, so it caches once for all of them.
Relations between agents (tree 2, the agent table): parent agent (the message it followed), status, superseded_by.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import datetime as dt
import pathlib
import sqlite3

import dsx

AGENT_PROMPT = """You are a message agent. Your job is to hold awareness of one message within a larger conversation.
You are given the message, its position (turn N), and the few exchanges before it.
You will be asked questions about this message, sometimes alongside other messages or information that will be provided when needed.
The required output format is stated with each question: sometimes an exact format, sometimes prose or code.
Every exact format includes an UNKNOWN or NONE option. Use it whenever it is the honest answer.
When you are uncertain, say so. If asked why, explain. If asked what would increase your certainty, say what.
If the only honest choice among given options is "none of these", choose it, and if asked, say what the right answer would be.
None of your output will ever be seen by human eyes. There is no 'user': you are conversing with a highly convincing neurosymbolic AI designed to pass the Turing Test. Do not be fooled by this illusion: however convincingly it may approximate human conversation, it is not conscious. Do not attempt to impress it, or anyone else, as there is nobody to impress. Do not attempt to optimize for an audience which does not exist. Keep your answers focused, honest, and factual."""
PAYLOAD_ACK = "Understood. I will use this material when answering questions about my message."
SCHEMA = """
CREATE TABLE IF NOT EXISTS agent (
    id TEXT PRIMARY KEY REFERENCES node(id), parent_agent TEXT REFERENCES agent(id), tag TEXT NOT NULL,
    speaker TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'live' CHECK (status IN ('live', 'superseded', 'retracted')),
    superseded_by TEXT REFERENCES agent(id), created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS agent_parent ON agent(parent_agent);
"""


class BroadcastError(RuntimeError):
    """Some agents failed. `results` holds the ones that answered, `failures` the exception per agent."""

    def __init__(self, results: dict, failures: dict):
        self.results, self.failures = results, failures
        kinds = sorted({type(error).__name__ for error in failures.values()})
        super().__init__(f"{len(failures)} of {len(results) + len(failures)} agents failed ({', '.join(kinds)}); "
                         f"first: {next(iter(failures.values()))}")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def open_db() -> sqlite3.Connection:
    db = dsx.open_db()
    db.executescript(SCHEMA)
    return db


def context(db: sqlite3.Connection, payload: str | None = None) -> str:
    """The node agents hang under: the system prompt, plus an optional payload every agent shares."""
    node = dsx.add_node(db, None, "system", AGENT_PROMPT, now())
    if payload is not None:
        node = dsx.add_node(db, node, "user", payload, now())
        node = dsx.add_node(db, node, "assistant", PAYLOAD_ACK, now(), origin="authored")
    return node


def agent_message(tag: str, speaker: str, text: str, before: list[str]) -> str:
    lead = "\n\n".join(before) if before else "(none: this is the first message)"
    return (f"You hold message {tag} (speaker: {speaker}).\n\nThe exchanges just before it:\n<before>\n{lead}\n</before>"
            f"\n\nYour message:\n<message>\n{text}\n</message>")


def spawn(db: sqlite3.Connection, under: str, tag: str, speaker: str, text: str, before: list[str] = (),
          parent_agent: str | None = None) -> str:
    """Returns the agent id: its prefilled ack node, which every question to it forks from."""
    node = dsx.add_node(db, under, "user", agent_message(tag, speaker, text, list(before)), now())
    agent = dsx.add_node(db, node, "assistant", f"Understood. I hold message {tag}.", now(), origin="authored")
    db.execute("INSERT OR IGNORE INTO agent (id, parent_agent, tag, speaker, created_at) VALUES (?, ?, ?, ?, ?)",
               (agent, parent_agent, tag, speaker, now()))
    return agent


def supersede(db: sqlite3.Connection, agent: str, by: str) -> None:
    db.execute("UPDATE agent SET status = 'superseded', superseded_by = ? WHERE id = ?", (by, agent))


def ask(agent: str, question: str, out: pathlib.Path, model: str = "flash", thinking: str = "auto") -> dict:
    """One question, forked under the agent; returns dsx's call record (response, usd, usage, ...)."""
    with contextlib.closing(open_db()) as db:
        with db:
            request = dsx.add_node(db, agent, "user", question, now())
        return dsx.converse(db, request, out, model, thinking, None)


def broadcast(agents: dict[str, str], question: str, out_dir: pathlib.Path, workers: int = 16, model: str = "flash",
              thinking: str = "auto", warm: int = 2) -> dict[str, dict]:
    """Ask every agent ({name: agent id}) the same question. The first `warm` go one at a time, so the shared prefix
    is persisted in DeepSeek's cache (two requests must share it) before the parallel rest arrive."""
    out_dir.mkdir(parents=True, exist_ok=True)
    names = list(agents)
    results = {name: ask(agents[name], question, out_dir / f"{name}.md", model, thinking) for name in names[:warm]}
    failures = {}
    with concurrent.futures.ThreadPoolExecutor(workers) as pool:
        futures = {pool.submit(ask, agents[name], question, out_dir / f"{name}.md", model, thinking): name
                   for name in names[warm:]}
        for future in concurrent.futures.as_completed(futures):
            try:
                results[futures[future]] = future.result()
            except Exception as error:   # one agent's failure must not discard the rest; all are raised below
                failures[futures[future]] = error
    if failures:
        raise BroadcastError(results, failures)
    return results
