# arc-agents: design notes

## Origin
This builds on Joe's arc-recall work (arc segmentation and just-in-time recall) and on his winnow project. Instead of segmenting arcs after the fact to recall them, each arc lives in its own agent from the start.

## Mechanics
- **Router:** a Choice over the live arcs, paired with a Noul that allows "none of these, start a new arc". Code plus Jev, with no text generation.
- **Messages that touch two arcs:** send them to both, or start a short-lived agent whose context combines both arcs.
- **One voice:** all arc agents share the same user preferences and persona.
- **Shared layer:** each arc publishes its decisions and conclusions, never its raw material, and any arc can read it. This is the "head keeps the conclusions, workers keep the work" split, with the head turned into a shared board.
- **Matching** uses the set-membership trick instead of comparing every pair. Put all the "have" ads in one state, and ask one Noul per "want" ("is this served by anything here?") plus a Choice ("which one?"). That's one call for the whole board.
- **Profiles come from winnows.** A winnow's conclusions are what it has, and its open questions are what it wants. Winnows can be one-shot handoffs at the end of a session (most existing winnows are this kind, and they work well) or streamed during a session for active work. The board accepts both, and a profile updates whenever a winnow arrives. It can be bootstrapped right away from the winnows Joe already has.
- **Across sessions:** arcs become long-lived specialists, one per project. As of 2026-10-31, sessions in Claude's cloud can receive messages but can't reply yet, so the board has to carry the two-way traffic.

## To keep in mind (not reasons to wait)
Most of these come from the method, not the idea, and winnow infrastructure is expected to solve most of them. A rough, working version is what makes the better version possible.
- **Profiles can oversell or undersell.** Build them from evidence (posted conclusions or winnow content), and track reputation: after each match, ask "did that help?".
- **Want ads are the hard part,** because agents often don't know what they need. The question library writes them: "what are you missing?" and info-need write them beforehand, and the debrief question "what specific information would have made this effortless?" writes them afterward, more precisely.
- **Ads go stale.** Refresh a profile whenever a new winnow or conclusion arrives.
- **Keep some agents independent.** Agents that talk all the time converge, and agreement between converged agents means little. So keep some reviewer agents off the board, for the checks where agreement has to count.
