# Design: questions as procedures written in prose

Status: designed in conversation, not built. Joe's design, worked out step by step. The notation below is a working draft; the names will settle once the design does.

## The idea
Treat prose like a programming language. Don't try to write fluent sentences. Instead, write one statement per line, where each statement says what the prose would say:
- Each line gets a number, and that number is a reference to the line's value. Later lines cite earlier ones as `[n]`.
- Each statement is a function and a variable at the same time: a formula when it's defined, a value when it's cited. That's the spreadsheet model; compilers' SSA and A-normal form are the same idea.
- Fluent prose needs implicit references between its parts. Numbered statements make every reference explicit, and that removes the gluing problem that made rendered questions absurd.

## What this is not
The design was checked against surface realization, grammatical frameworks, NLG pipelines and controlled natural languages, and all four were rejected: this is procedure-behaving prose, not production. The point is that the steps run; the output may read like a recipe, a tax form or a checklist.

## Each line has two forms
Every statement is written formally, followed by its plain-English gloss:
```
1. focus: the current work                   ... "The focus is the current work."
2. suppose: [1] is broken                    ... "Suppose the current work is broken."
3. list: the parts of [1]                    ... "List the parts of the current work."
4. combine: parts from [3] into a new arrangement that works, not [1] as it stands
                                             ... "Combine the parts you listed into an arrangement that works, since the current one doesn't."
```
- **The gloss is a check, not decoration.** The first draft of line 4 read "combine: parts from [3] into something that works, under [2]". That looked fine as notation, but its gloss had nothing to say for "under [2]", and that exposed a reference with no meaning. A line that can't be glossed coherently is a line nobody has understood.
- **The goal is conversational.** A person reading the gloss aloud to another person should find it intuitive and logically correct.

## Two kinds of line
- **Values** (focus, list, combine, ask, and so on): later lines cite them by number.
- **Scopes** (suppose): these open a context. The lines that depend on it are indented under it, as in a Fitch-style proof, and the scope closes when it's done. A scope is never cited as an argument. Its consequences are either stated in the dependent lines or inherited through indentation.

## Control flow
The library already contains control flow, implicitly:
- why-chain is a loop;
- evidence-matrix is a nested for-each;
- one-variable is a loop with an invariant;
- premortem is a scope;
- already-addressed is a guard clause, returning early.

The contract questions are DbC directly. info-need is a precondition, check-result is a postcondition, and "is each step correct?" is an invariant.

Joe's rule: it must work spoken aloud. Gotos are fine if that's what reads naturally, since that's how loops work at the CPU level anyway. It may not be good code style, but it is good, proper logic. Tax forms, checklists and recipes already work this way ("If zero or less, enter 0 and go to line 12"; "repeat steps 3 and 4 until smooth").
```
1. note: what happened                    ... "Start with what happened."
2. ask: why did [latest] happen?          ... "Why did that happen?"
3. if: can you act on [2]? yes, go to 5   ... "Is that something you can act on? If so, skip to step 5."
4. go to 2                                ... "If not, go back to step 2 and ask why that happened."
5. return: [2]                            ... "That's the thing to act on."
```
With gotos, a line number names a register, not a constant:
- `[n]` means line n's most recent value;
- `[n…]` means every value line n has produced ("all the whys so far");
- `[latest]` means "[2] if it has run, otherwise [1]".

## Named procedures
"Let's define a procedure, and call it X. Here's how X works: ... and that's how you do X." That sentence has four parts:
1. **Open and name** it.
2. **Name the parameter:** "it takes something; call it *the thing*".
3. **Body:** numbered steps local to the procedure.
4. **Result and cap:** "what you end up with is X's result. That's how you do X."

A call is "Do X on [3]", and its value lands on that line.
```
define root-cause(thing):                       ... "Let's define finding the root cause of something.
  doc: stop at the first cause you can act on; going deeper is wasted effort.
  1. ask: why did [thing] happen? (the immediate cause, not the whole history)
                                                ...  First, ask why it happened.
  2. if: can you act on [1]? yes: return [1]    ...  If you can act on that answer, that's the root cause.
  3. return root-cause([1])                     ...  If not, find the root cause of that answer instead.
  example: build failed, because a dependency changed, because nobody pinned it; that's actionable, so pin it.
end root-cause                                  ...  That's how you find a root cause."
```
- **Recursion often reads more naturally than goto.** "If not, find the root cause of that" is how people talk. And each call has its own `[1]`, so the register problem doesn't arise.
- **Line numbers are local to a procedure.** From outside, refer to `root-cause.1`, or more usually just use the call's result.

## Comments, docstrings and tests
- **A parenthetical is a comment:** a local aside about one line, which the procedure doesn't depend on.
- **A docstring is an overt, spoken explanation** of the reasoning. It isn't part of the procedure, but it helps whoever follows it understand why. Joe's code rule applies: document intent minimally, covering only the gap that the name and parameters leave.
- **A worked example is a test.** It runs the procedure once on a concrete case, so it both explains the procedure and checks it.
- **For an LLM, comments aren't inert.** A parser skips them; a model reads everything. Rationale helps the model handle cases the steps didn't anticipate. But it can also leak the answer, so the leakage check must cover docstrings and comments too.
- **Bare symbols such as arrows don't belong in glosses.** The test is whether the text makes sense read aloud, since text that would make sense on playback makes sense to whoever reasons with it. Parentheticals pass that test.

## Who runs what
Every branch condition and loop exit is a judgment, such as "Is it actionable yet?" or "Does [n] already cover this?". Those are Nouls. Bodies and lists are generation. So:
- code runs the control flow;
- Jev decides the conditions;
- the LLM writes only the bodies.

That's the "procedural first, Jev at the junctions" architecture applied to a single question (see jev-toolkit's `design/junctions.md`). jevask already expands `[n]` references in code.

## Working with the two forms (Joe)
- **Expand to check.** Formal syntax that's too terse can hide errors, even from its author. Expand it back to prose to check that it makes sense.
- **Or build expanded, then collapse once.** Work entirely in the expanded form until everything reads correctly, then collapse it to the formal form. That saves back-and-forth while constructing.
- **The formal form catches its own class of error,** the way a linter does. If the syntax doesn't check out, that tells you something the prose construction missed.
- **Neither is proof.** Only tests are (see `validation.md`).
