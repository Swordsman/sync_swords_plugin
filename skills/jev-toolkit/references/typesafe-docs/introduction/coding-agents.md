> ## Documentation Index
> Fetch the complete documentation index at: https://docs.typesafe.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Jev with coding agents

> What Jev is (and isn't) when you're using a coding agent.

If you found TypeSafe while looking for a model to plug into your coding agent, start here. Jev is **not** a drop-in replacement for the LLM behind Claude Code, Cursor, opencode, Copilot, Muse Spark, Grok Bot, or similar tools. Instead, you can use your coding agent as usual to write code that uses Jev to make decisions.

## Jev is not a chat or code-completion LLM

Jev is a [System One model](https://docs.typesafe.ai/concepts/system-one.md). It does not generate text, write code, or hold a conversation. It takes a [state](https://docs.typesafe.ai/concepts/state.md) and a set of typed [questions](https://docs.typesafe.ai/primitives) and returns structured answers your code can use directly:

* A `choice` from a list of options, with per-option probabilities.
* A `score` on a rubric you define.
* A `noul` (0–1) for a true/false statement.

Coding agents rely on an LLM that streams text, calls tools, and edits files based on natural-language instructions. Jev does none of that. There is no `model: "jev-latest"` setting that turns your coding agent into a Jev-powered agent, because the two systems solve different problems.

## What you probably want instead

Pick the row that matches what you were trying to do:

| You wanted to... | Do this |
| - | - |
| Make your coding agent better at *writing code that uses TypeSafe* | Install the [TypeSafe agent skill](https://docs.typesafe.ai/agent-skill.md). It gives Claude Code, Codex, and other agents full context on the Jev API, the [primitives](https://docs.typesafe.ai/primitives), and the [patterns](https://docs.typesafe.ai/patterns.md) so they can generate correct TypeSafe integrations for you. |
| Use Jev inside an app or agent you're building — for routing, classification, scoring, guardrails, or any structured decision | Start with the [Quick start](https://docs.typesafe.ai/introduction/quickstart.md), then read [How to build with TypeSafe](https://docs.typesafe.ai/concepts/how-to-build-with-system-one.md) and the [Patterns](https://docs.typesafe.ai/patterns.md) for common architectures like [confidence routing](https://docs.typesafe.ai/patterns/confidence-routing.md) and [intent routing](https://docs.typesafe.ai/patterns/intent-routing.md). |
| Replace or swap the model that powers a coding agent | Jev isn't the tool for this. Keep using an LLM-based coding agent, and use Jev separately wherever your product needs a fast, calibrated, structured decision. |
| Try Jev before writing any code | Open the [Playground](https://console.typesafe.ai/playground), paste some text as the state, and add a few questions. See the [Quick start](https://docs.typesafe.ai/introduction/quickstart.md) for a walkthrough. |

## When Jev is worth reaching for

Even though Jev isn't a coding-agent LLM, it's often exactly the right tool *inside* an agent or app you're building with a coding agent. Reach for Jev when your code needs to:

* Route a request to one of a fixed set of destinations, and know how confident that routing is.
* Score something on a rubric (urgency, quality, risk) and branch on the number.
* Check whether a statement is true of a document, message, or record before taking an action.
* Replace a fragile prompt that asks an LLM to "return JSON" with a call that returns typed values by construction.

If any of that matches what you're building, the fastest path in is the [Quick start](https://docs.typesafe.ai/introduction/quickstart.md), then the [primitives](https://docs.typesafe.ai/primitives) reference for the question types.

## Next steps

* [System One](https://docs.typesafe.ai/concepts/system-one.md) — What a System One model is and how it differs from an LLM.
* [Quick start](https://docs.typesafe.ai/introduction/quickstart.md) — Try Jev in the Playground, over HTTP, or with the Python SDK.
* [Agent skill](https://docs.typesafe.ai/agent-skill.md) — Give your coding agent context on the TypeSafe API.
* [Patterns](https://docs.typesafe.ai/patterns.md) — Common architectures for building with TypeSafe.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.