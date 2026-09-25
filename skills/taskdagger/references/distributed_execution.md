# Distributed Execution

Load when: any worker jobs will run outside the executor's environment (other machine, platform, harness, or time).

Contracts make this legitimate — a work order is text; it runs anywhere. But the build manager loses ambient awareness of remote workers, so three things must be resolved *before* dispatch, not after something catches fire.

## The three requirements

1. **Completion signaling**: how will the build manager know when remote workers stop working — whether done or sideways?
2. **Deliverable transfer**: how do finished results get from the worker's workspace back to the build manager?
3. **Comm channel** (optional but set up proactively): a way for the build manager to say "workers A, B, C — time out, we need to talk." Rarely needed with black-box workers, but when it's needed, it's needed *now*, and it's far easier established before dispatch than during a fire. Assume the user wants one; they'll say otherwise.

## Environment intake

Ask the user what kind of environment(s) the remote workers will run in. Capabilities vary enormously and shape everything downstream:

| Environment type | Signaling | Transfer | Notes |
|---|---|---|---|
| Browser AI platform | Usually manual (user relays) | Upload/download or copy-paste; see transfer mechanics | Workarounds exist: Chrome debug mode, MCP SuperAssistant |
| Code harness (Claude Code, etc.) | Tools available; practically no issues | Filesystem, git, anything | Easiest case |
| Local GPU / localhost | Scriptable | Filesystem | Add a little glue |
| Cloud/remote GPU | Scriptable | scp/API/object storage | Add glue |
| Android / other | Varies wildly | Varies | Intake carefully |

Network path also matters: localhost, LAN, cloud, Tailscale — when code and filesystem access exist, options include sockets, REST/API, MCP, websockets, ngrok, plain webservers. Pick one. When none exist, the fallback is the user manually copy-pasting — which always works.

## Skill availability and self-containment

Check: is this skill present in the remote environment for the workers? If not, either provide it, or — usually better — rely on the fact that work orders are fully self-contained by design. Before dispatching to a skill-less environment, verify the work orders truly are self-contained: conventions included, write-safety guidance included where applicable, zero references to skill reference files. A worker with nothing but its work order must be able to complete the job.

## Transfer mechanics (upload-restricted platforms)

Many browser platforms restrict upload filetypes. Field intel, as of this writing:

- `.txt` is accepted essentially everywhere uploads exist at all
- `.pdf` usually accepted, occasionally rejected
- `.md` frequently rejected (rename to `.md.txt` — works)
- `.zip` almost always excluded when restrictions exist

When multiple files must move through a restricted gate: pack them into a **MIME multipart container** inside a `.txt` file. Preferred tools: mimepack (`.mimepack.txt`) or aimpack (`.aimpack.txt`) — see the aimpack skill if present. Also fine: Linux `munpack`, Python's stdlib `email` module, or just having an AI hand-write the container (`.mime.txt`). MIME is easy, forgiving, plaintext-readable, and vastly better than zip for AI workflows.

Packing rules:
- **No base64** unless the content is genuinely binary — base64 bloats tokens and increases hallucination risk on decode
- **No compression, ever.** Zlib/zip saves ~2% filesize and costs: unreadable-in-place content, decode steps, early compactions, context rot, lost details, wasted repair time. A few KB saved on a 175KB container buys nothing. Never use it.
- For platforms with **no upload at all**: paste the raw MIME container contents directly into the chat. It works perfectly — the container is just text.

## Lost-worker detection

The executor cannot see a remote worker's container. A worker that dies produces no signal — it simply stops. To make a lost worker detectable, the dispatch record must contain:

- **Dispatch timestamp** — when the worker was sent its work order
- **Expected completion window** — a reasonable upper bound, from the task's effort estimate
- **Last known signal** — timestamp of the most recent sign of life (progress report, partial commit, heartbeat if the comm channel supports it)

A worker past its completion window with no signal is presumed lost. The executor applies the same recovery as a local unreported worker: re-dispatch against the same work order rather than adopting whatever the remote environment may contain (see `executor.md` → Durability).

The dispatch record is also what makes accountability possible after the fact — without it, a lost worker and a never-dispatched task are indistinguishable from the commit history.

## Future consideration

A companion MCP server for this skill (signaling + transfer + comm channel as tools; "skill as plugin") would collapse most of this file into configuration. Parked for now.

## Washing across environments

If the worker wash is enabled, three things that are implicit locally have to be
made explicit for a remote worker, because none of them survive the trip:

- **The machine itself.** `washing_machine.py` is stdlib-only and self-contained
  by design — send the file, or make sure the skill is installed on that side.
  A skill-relative path in the work order resolves to nothing over there.
- **Where records go.** The machine walks upward for a `.taskdagger/` directory. A
  remote worker has no project tree, so set `TASKDAGGER_WASH_DIR` to somewhere real
  in that environment and transfer the resulting record back with the work
  product. A record stranded on a machine that gets torn down is a gate nobody
  can audit.
- **Which washer this is.** Set `TASKDAGGER_WASH_ID` per worker. Remote workers whose
  wash directory happens to be shared — a mounted volume, a common scratch
  space — otherwise collide on the current-cycle pointer.

The wash record is part of the work product, not a local side effect. Pack it
with the rest of the return payload.
