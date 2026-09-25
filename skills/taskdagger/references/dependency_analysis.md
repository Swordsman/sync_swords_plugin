# Dependency Analysis (Optional Phase 1.5)

Optional step between DAG generation and execution. Identifies external libraries that simplify task implementation, with contract-aware recommendations.

## When to use

- Before first execution of a new DAG
- When the project involves unfamiliar domains or languages
- When contract formats could benefit from library-native type systems (e.g., Zod schemas as runnable contracts)

## Process

For each task (or group of related tasks):

1. **Identify candidate libraries** that address the task's domain
2. **Check contract alignment**: does the library produce types/schemas that can serve directly as contract definitions?
3. **Check stub generation support**: can the library generate runnable stubs from type signatures?
4. **Check fixture support**: does the library have built-in testing/validation that aligns with contract fixtures?
5. **Record recommendations** in task metadata as `dependency_hints`

## taskdagger-specific additions over tdag

| Category | What to look for |
|---|---|
| Contract-native types | Libraries whose type systems double as contract definitions (Zod, io-ts, pydantic, marshmallow) |
| Stub generators | Libraries that produce runnable mocks from type signatures (msw, polly, responses, wiremock) |
| Contract enforcement | Fixture/property testing tools by language (pytest, vitest, jest, hypothesis, fast-check) |

## Output

Recommendations are advisory. They go into task metadata or a separate recommendations document. They do not modify the DAG structure or contract definitions.

**One part is not advisory: the runtime dependency closure.** For each execution pool, emit the explicit list of runtime dependencies its tasks will need, and **name the task that will declare them** — the one that owns the manifest, lockfile, or environment definition. Recommending libraries without assigning ownership of their declaration is the half-measure that leaves a project unbuildable while every contract reads satisfied.

Do not specify tooling. Whether the project uses a venv, uv, a lockfile or a container is the project's decision; the protocol's concern is only that some task owns it and that the executor checks it before dispatch.

## Key principle

The DAG remains environment-agnostic. Library choices are late-bound and per-environment. A Zod-based contract definition in development can be swapped for a pydantic equivalent in a Python service without changing the contract semantics.

## Optional: mechanical chunk boundary proposal

Community detection / min-cut analysis on the assembled task graph can *propose* chunk boundaries before the orchestrator's manual chunking (Phase 5), using the quality metric (`chunks.md`) as the objective function: maximize internal/(internal+boundary) per proposed chunk subject to the Split justification cost check. Treat proposals as a starting point for user confirmation, not a final chunking — the orchestrator's default (one chunk per queue) already tracks human-intuitive boundaries most of the time; this is most useful when the dependency graph doesn't cleanly follow the queue structure.
