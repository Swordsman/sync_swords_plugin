Canonical code encoding for AI-first containers. Source code carries arbitrary choices
that obscure meaning: names, ordering, expression form, formatting, legacy comments.
This encoding strips those away in layers, each independently useful, converging on a
representation where functionally identical code is always structurally identical.

The core axiom: aimpack contents are for AI consumption. Human readability is a
non-goal for the stored representation. `unpack` reconstructs source when a human
needs it; inside the container, the representation optimizes for machine
comprehension, structural diffing, and semantic equivalence.

S-expressions inside containers are flat — no newlines, no indentation. Formatting
is token waste. Design docs and READMEs can use pretty-printed examples for human
readers, but the wire format is a single line per s-expression. An LLM reads
parenthetical structure natively; whitespace formatting adds nothing for it and costs
tokens on every read.

## Encoding levels

Each level removes a class of arbitrary choice. A container can carry a file at any
level, or at multiple levels simultaneously as parallel parts with the same logical
filename. Higher levels are strictly more canonical — code that means the same thing
produces the same representation.

| Level | Removes | Content-Type suffix | Reconstructible |
|-------|---------|---------------------|-----------------|
| 0 | nothing | `text/plain` | identity |
| 1 | formatting, comments | `x-aimpack-ast` | `ast.unparse` (semantic, not byte-identical) |
| 2 | naming | `x-aimpack-ast; symbols=table` | yes, via symbol table |
| 3 | arbitrary ordering | `x-aimpack-ast; flow=dataflow` | yes, with `seq`/`par` annotation |
| 4 | expression choice | `x-aimpack-egraph` | yes, via extraction with cost function |

Level 0 is what aimpack does today. Each higher level is additive — a codec registered
via the extension system or built into aimpack directly.

## Level 1: AST s-expression

Python source → AST via `ast.parse` → s-expression serialization. Comments are
discarded unless explicitly promoted to `(annotate ...)` nodes. Formatting is
discarded entirely — reconstruction via `ast.unparse` produces clean, canonical
source.

```python
def calculate_sum(x, y):
    # add the two numbers
    return x + y
```

```lisp
(FunctionDef "calculate_sum" (arguments (arg "x") (arg "y"))
  (Return (BinOp (Name "x") Add (Name "y"))))
```

The comment is gone because it restates what the code does. An AI-facing annotation
would be preserved explicitly:

```lisp
(annotate "overflow is intentional here — wrapping semantics required by protocol"
  (FunctionDef ...))
```

### Encoding efficiency

Frequency-ranked node-type codes, context folding (elide fields inferrable from
parent), and trailing-None elision keep the s-expression compact. The encoding is
pure Python using the stdlib `ast` module. No external dependencies.

### Round-trip

`ast.parse(source)` → s-expression → `ast.unparse(rebuild(sexp))` → source.
Semantically identical, not byte-identical. The original formatting, comments, and
whitespace are not preserved — by design.

## Level 2: symbol table

Identifiers are abstracted into a binding table. Each unique identifier gets a
numeric slot at its binding site. Use sites reference the slot, not the name string.

Both halves are quoted (evaluation-disabled) s-expressions. The symbol table is
declared first, the AST body second. "Executing" the symbol table against the body
is macro expansion — substituting slot references with their name strings to recover
the named AST.

```lisp
'(symbols
  (0 calculate_sum)
  (1 x)
  (2 y))

'(FunctionDef 0 (arguments (arg 1) (arg 2))
  (Return (BinOp (Name 1) Add (Name 2))))
```

### Properties

- **Rename = one edit.** Changing `x` to `quantity` modifies slot 1's binding and
  nothing else, regardless of how many times the identifier appears in the body.
- **Functionally identical code with different names produces identical bodies.**
  `add(a, b)` and `sum(x, y)` with the same structure have the same body
  s-expression; only the symbol tables differ.
- **Scope is explicit.** An inner function that shadows an outer name gets a distinct
  slot. Python's scoping rules (`global`, `nonlocal`, closures) are encoded
  structurally rather than inferred from indentation and keywords.
- **The format is homoiconic with aimpack's instruction DSL.** Same grammar for
  instructions, metadata, and code. One parser, one mental model.

### Slot assignment

Slots are assigned in binding order (depth-first, left-to-right traversal of the
AST). This makes slot assignment deterministic from structure alone — no dependency
on the original names. Two functions with the same structure always produce the same
slot numbering.

## Level 3: dataflow graph (par/seq)

Independent operations are grouped into `par` blocks; dependent operations are
sequenced in `seq` blocks. The distinction is semantic: `par` declares that its
children are unordered by definition, not merely reorderable.

```lisp
(par
  (= (0 1 2) (1 "hello" 42))
  (call (init_db) (init_cache)))
(seq
  (= 3 (connect 0))
  (= 4 (query 3)))
```

### Independence criteria

Reorder when independence is **provable from the AST alone**:

- Top-level `def` and `class` with no cross-references → `par`
- Parallel assignments to distinct names from pure expressions → `par`
- Anything involving a call, attribute access, subscript, or shared name → `seq`

Conservative by default: if independence cannot be proven, preserve source order in
`seq`. The encoder never breaks semantics. An AI or human can promote `seq` blocks
to `par` when they can verify independence — the canonical form is a target to
refactor toward, not a requirement of the initial encoding.

### Why par, not just canonical sorting

Canonical sorting (e.g., by subtree hash) makes reordering invisible in diffs, but
it's a weaker statement. `par` declares that ordering doesn't *exist*, not just that
we *chose* an order. An AI reading `par` knows the children are semantically
independent — information source code doesn't carry at all.

A `par` block's children are canonically sorted (by subtree hash) to ensure a single
representation, but the sorting is a consequence of unorderedness, not the point.

## Level 4: e-graph (equality saturation)

Expressions that compute the same value are collapsed into equivalence classes
(e-classes). An e-class *is* the meaning — not any particular way of writing it.

```lisp
'(rules
  (commute add (add a b) (add b a))
  (commute mul (mul a b) (mul b a))
  (strength (mul a 2) (shl a 1))
  (identity (add a 0) a)
  (identity (mul a 1) a)
  (distribute (mul a (add b c)) (add (mul a b) (mul a c))))

'(e-graph
  (e-class 0
    (shl (slot 1) 1)
    (add (slot 1) (slot 1))
    (mul (slot 1) 2)))
```

E-class 0 *is* "double x." All three expressions are equivalent. A diff that
changes `x * 2` to `x << 1` produces zero semantic diff because both are already
in the same class.

### Bounded saturation

Full equality saturation with unrestricted rules can diverge. For aimpack's
purposes, saturation is bounded:

- A fixed rule set: commutativity, associativity, identity, strength reduction,
  distribution. Extensible via the container's own `rules` declaration.
- A node-count ceiling per e-class. If saturation would exceed it, stop. The graph
  is still valid — just not fully saturated.
- Rules and the graph are both quoted s-expressions. Homoiconic with everything else.

### Extraction

An e-graph stores equivalences; concrete code requires choosing a representative
from each e-class via a cost function. Different cost functions serve different
purposes:

| Cost function | Optimizes for | Use case |
|---------------|---------------|----------|
| `min-nodes` | smallest AST | diffing, deduplication |
| `min-depth` | flattest tree | readability |
| `perf` | known-fast ops | code generation |
| `target(lang)` | target language idioms | cross-language extraction |

`unpack` uses a default cost function to reconstruct source. But the container
carries the full equivalence structure — any consumer that wants more information
can read the e-graph directly.

### Cross-language portability

The e-graph is language-independent. The same equivalence structure can extract to
Python, JavaScript, Rust, or any language with a target cost function and syntax
mapper. Language becomes a build target. The container stores what the code *means*;
the consumer chooses how to write it.

## Integration with aimpack

### Content-Types

New part types in the existing type system:

| Content-Type | Level | Role |
|---|---|---|
| `application/x-aimpack-ast` | 1-3 | Canonical AST s-expression |
| `application/x-aimpack-egraph` | 4 | Equivalence graph |

Parameters on the Content-Type distinguish levels within the AST encoding:
`application/x-aimpack-ast; symbols=table; flow=dataflow` for a level-3 encoding.

### Parallel parts

A file can exist at multiple encoding levels simultaneously. The parts share a
logical filename via `Content-Disposition` and are distinguished by Content-Type.
An AI consumer picks the highest level it can use; `unpack` always extracts level 0
(source) by reconstructing from whatever level is stored.

### Structural diffs

At levels 2+, diffs operate on the s-expression structure, not text. A rename
refactor that touches 47 lines of source becomes a single symbol-table edit. A
reorder of function definitions produces zero diff in a `par` block. An expression
substitution within an e-class produces zero diff at level 4.

The `text/x-diff` part type can carry either textual unified diffs (for level 0
parts) or structural s-expression diffs (for level 1+ parts). Structural diffs use
a new format: `text/x-aimpack-sdiff`.

### Annotations

Comments that matter — invariants, constraints, "don't optimize this because..." —
are preserved as explicit `(annotate "reason" node)` wrappers in the AST. They
survive all encoding levels because they are structural nodes, not line comments.

This makes the distinction between "documentation for humans" (discarded) and
"information for the AI" (preserved) explicit. If it's in an `(annotate)` node,
it's there on purpose.

### Extension system

Codecs for each language register via the existing extension handler interface:

```python
CONTENT_TYPES = ["application/x-aimpack-ast"]
FILE_EXTENSIONS = [".py"]

def on_pack(filepath, metadata):
    source = filepath.read_text()
    tree = ast.parse(source)
    sexp = ast_to_sexp(tree)
    symbols, body = extract_symbol_table(sexp)
    body = "'(symbols\n" + symbols + ")\n\n'(" + body + ")\n"
    return {"Content-Transfer-Encoding": "x-ast-sexp"}, body

def on_unpack(headers, body, dest):
    sexp = parse_sexp(body)
    tree = sexp_to_ast(expand_symbols(sexp))
    dest.write_text(ast.unparse(tree))
```

Python (via stdlib `ast`) is the first language. Others register via the same
mechanism. The e-graph engine is a separate module, pure Python, no dependencies.

## Implementation plan

### Phase 1: AST codec (levels 1-2)

Pure Python, stdlib only (`ast` module). Buildable now.

- `ast_to_sexp(tree)` — AST to s-expression with frequency-ranked codes
- `sexp_to_ast(sexp)` — inverse
- `extract_symbols(sexp)` — pull identifiers into a binding table
- `expand_symbols(table, body)` — macro-expand slots back to names
- Round-trip test: `ast.unparse(sexp_to_ast(expand_symbols(extract_symbols(ast_to_sexp(ast.parse(source))))))` equals `ast.unparse(ast.parse(source))` for all valid Python

### Phase 2: dataflow analysis (level 3)

Dependency analysis over the AST to partition statements into `par`/`seq` blocks.
Conservative: default to `seq`, promote to `par` only when independence is provable.

- `analyze_deps(sexp)` — build dependency graph from name references
- `partition_flow(sexp, deps)` — partition into `par`/`seq` blocks
- `canonical_order(par_block)` — sort children by subtree hash

### Phase 3: e-graph engine (level 4)

Bounded equality saturation. Pure Python, ~500 lines.

- `EGraph` — e-class union-find, e-node storage, hash-consing
- `saturate(egraph, rules, limit)` — apply rules to fixpoint or limit
- `extract(egraph, cost_fn)` — choose representatives
- Default rule set: arithmetic identities, commutativity, associativity

### Phase 4: structural diffs

Diff algorithm over s-expression trees. Edit distance on ordered labeled trees
(Zhang-Shasha or similar), producing a minimal edit script in s-expression form.

### Packaging

The codec is a pure-Python module that ships alongside `scripts/aimpack.py` — either
as a sibling file or bundled as a first-party extension. It has no external
dependencies. `aimpack.py` itself remains stdlib-only; the codec is an optional
import that enables higher encoding levels when present.

## Hy as an existing implementation target

[Hy](https://github.com/hylang/hy) is an s-expression language that compiles to
Python's AST. Python translates to Hy largely automatically. This is relevant
because:

- Hy *is* s-expressions over Python AST — exactly what levels 1-2 describe.
- Hy's existing tooling (parser, printer, AST round-trip) could replace a custom
  s-expression encoder for the Python language codec.
- A Hy version of aimpack itself would be dogfooding: the tool written in its own
  canonical form.
- Hy is pure Python with no C extensions, so it could ship as a bundled dependency
  without violating the "no external runtime deps" constraint if we vendor it or
  treat it as a first-party optional component.

Hy does not cover levels 3-4 (dataflow analysis, e-graphs) — those are aimpack-
specific and would still need custom implementation. But for the AST↔s-expression
layer, Hy is prior art worth evaluating before building from scratch.

## Wire format notes

S-expressions inside containers are flat: `'(symbols (0 f) (1 x) (2 y))` not
pretty-printed across lines. Newlines and indentation are token waste for an AI
reader that parses parenthetical structure natively. Design docs use formatted
examples for human readers; the wire format does not.
