# Design: change orders (code plus Jev)
Status: designed, not built. Created 2026-11-01. Joe's idea, refined in session 32131678.

## What it is
A change order is a declarative file of edits to text files, written by an agent that has already read and understood the target. A runner applies it. Code does the applying, and Jev sits only at the junctions where a judgment is needed. Fixes that are already understood get carried out by code instead of a model session, and workflows we keep re-deriving get turned into automation.

## Format (YAML)
- **Header:** `file`, plus `find` (a glob or another way to locate the file), `sha256`, `created` (UTC), `commit` (the repo commit, if there is one), and `author` (the session or model that wrote it). `author` covers the source axis and `created` covers the time axis. Both cost almost nothing to include, while a stale order nobody catches has unknown cost. So they go in from the start.
- **ToC:** sections are markdown headers, or functions and classes in code. Each section has a line range, `sig_sha` (a hash of the header or declaration line), and `body_sha`. Hashing the signature and the body separately means a change to a caller's interface can be told apart from a change only inside the body.
- **Edits:** each one is `op` plus arguments, plus `why`. An edit's own `file:` overrides the header's. Raw `sh:` is the escape hatch.
- **Expected results:** `post_sha` for each edited section and for the whole file. The author computes these with a dry run when making the order.

## Runner
- Each op is a Python function in a registry. Arguments are filled from the header by matching parameter names. YAML is never turned into bash strings, which avoids quoting bugs. A command-line tool for running ops by hand is generated from the same registry.
- Locators are filled in by tools (`toc`, `locate`), never typed by a model, because line numbers written by an LLM are unreliable.
- Strictness is adjustable: a line range checked against its hash, then a section hash found anywhere in the file, then the section name, then a grep. The looser the match, the more Jev scrutiny applies.
- **Edits apply in a fixed order.** All locators are resolved against the original file first, then edits are applied from the bottom of the file upward, so an earlier edit can't shift the lines of a later one.
- **Atomic.** All edits are made on copies and all checks run before anything is written. Then the copies are written into place with `os.replace`, or nothing is written at all.
- **Fail closed.** If Jev can't be reached and the order needs a Jev check, the run stops.
- **Recognizes orders already applied.** If the current hash already equals `post_sha`, the runner reports "already applied" instead of stopping with a mismatch.
- **Receipt:** before and after hashes, Jev scores, which locator was used, and a UTC timestamp. Every stop also records its reason, which builds labeled data for tuning the thresholds. In a repo, each order becomes one commit with `why` as the message, so undoing an order is `git revert`.

## Where Jev goes (only where hashes can't decide)
- File and section hashes match: apply, check `post_sha`, done. No inference.
- The file changed but the target section's hash didn't: apply and check the section's `post_sha`. Then run one Jev staleness check: given what changed elsewhere (`git diff` since `commit`), does this edit still make sense? Until dependencies between sections are written down, Jev stands in for the dependency graph.
- The target section changed: relocate it with a Choice (candidates shuffled, plus a "none of these" Noul). Then judge the before and after diff against `why`. This is a model judgment, so stop unless the score is clearly high.
- A vague `why` leaves Jev near 0.5, so the run stops. That's intended: it forces precise statements of intent.

## Known risks, with fixes (from the axes review)
- **Saturation.** Absolute "makes sense" Nouls saturated at 0.81 to 0.99 in `pairs.py`. Using them, the brake would almost never pull. Use a Score with described levels, and calibrate it with negative controls: a wrong target, a wrong diff, and a diff that does more than its `why` must each score low. Only trust the brake once those pass.
- **Read-only cache.** The synced plugin copy (`~/.claude/plugins/synced/...`) is a read-only cache and not a git repo, so applying edits there changes nothing that lasts. Orders for Joe's plugin repo have to target a checkout of the repo.
- **Unique locators.** `find` and `grep` must each match exactly one place. More than one match goes to the Choice junction, or stops the run.

## Open questions
- **Which build comes next: the change-order runner or the lookbehind pilot?** Undecided (q51). The argument for the runner first: the op registry pays immediately inside the session and is the general machinery underneath file edits, so build the op registry before the edit ops. The session then moved to the session-map pipeline instead.
- **Any build is gated on the intent map (Joe's hard rule, k26).** See `/home/claude/skills/session-map/design/notes.md` for that pipeline.
- **Overlap check, done 2026-11-01. Verdict: stay separate, and borrow the engine and the names.**
  - taskdagger's `multiedit.py` (also in the plugin's `scripts/`) is the closest existing engine. Its edit keys are `file`, `block`, `start`, `end`, `text`, `mode`, `end_block`, `if_contains` and `if_not_contains`, and it writes atomically. It's missing hash preconditions inside `edit`, a ToC, a timestamp and a why. Its guards skip instead of stopping, and `edit` creates a missing file instead of failing. Build ops on top of it, leveraging it without depending on it.
  - Names to borrow from taskdagger: `contract_drift_policy` (`notify|halt|continue`), `hash_recipe_version`, `created_at` (ISO `…Z`), and the provenance fields `source_file`, `source_commit`, `rationale`.
  - aimpack can serve as transport: it packs files with `--checksum sha256` and has a `verify` command. Its patches are unified diffs that skip on failure. Its s-expressions assume a model interprets them.
  - futurenotes: `notes.db` (`status` pending → active → done, `content_hash`). It's specific to Kimi, but the status lifecycle fits a queue of orders.
  - io-shield (SHA-256 integrity plus write-locking) and tree-sprawler (a possible ToC generator) haven't been read yet.
- The ToC for Hy files (`hy.read_many`) and for other languages. The minimum version covers `.py` and `.md`.
- Where the runner lives: here in jev-toolkit, or in a skill of its own.
- Safety of op execution: not a concern for a single user whose orders come from his own sessions. Revisit if orders ever arrive from outside, for example from the want-ads board.
- Broader pattern: an op registry, argument filling, Jev checks, a brake and a receipt make a general runner for crystallized workflows. File edits are only the first family of ops.
