# Content-hash node ids — design note

Status: implemented — hashing in `fold.py --hashes` / `Graph.hash_id`,
cross-log merge in `merge.py` (the sketch below is now code; conflicts
surface as `reconcile-status` questions, self-merge verified as a fixed
point). Remaining v0.3 items: session-namespaced `:src`, alias-aware
registry reconciliation (see TODO.md).
Spec context: §3 (ids), §12 (hash ids for merge, global KB).

## Problem

Serial ids (`c1`, `d3`) are token-cheap and human-readable but session-local:
the same proposition extracted in two conversations gets two unrelated ids.
That blocks three things the spec defers to the hash-id era:

1. **Cross-log merge** — folding two logs requires knowing which nodes are
   the same node; today only the `merge` op (manual, per-pair) covers this.
2. **Global KB** (§10.5 rung 4) — a cross-conversation store needs stable
   keys that don't depend on which session minted them.
3. **Cross-representation equivalence** (§4) — comparing logs from different
   term-identity modes requires an id derived from content, not from
   extraction order.

## Design

```
hash(node) = sha256( frame ++ " " ++ resolve(canonical-payload) )[:12]
```

where `resolve` renders the payload in canonical s-expr form with one
transformation: **node-id arguments are replaced by `#hash(referent)`,
recursively**. Everything else — term ids, string literals, numbers —
hashes as its canonical surface form.

### What's in the hash

| Included | Excluded | Why |
|---|---|---|
| frame | annotations (`:by :src :conf :status ...`) | Two speakers asserting the same proposition in different turns are asserting *the same node*; provenance is metadata on the assertion, and status is mutable state. Hashing them would make identity depend on history, defeating dedup. |
| canonical payload | edges | Edges are structural, not identity-bearing (Lumo's IR question, resolved the same way): `(supports X Y)` relates two nodes, it doesn't change what X *is*. |
| referenced nodes' hashes (recursive) | serial ids | `(achieves d2 lossless-roundtrip)` must hash identically across logs even though "d2" is log-local; resolving the reference to the referent's own content-hash makes the id transitive. Verified property: `tests/test_fold.py::test_node_ref_args_resolve_recursively`. |

### Consequences, accepted

- **Same proposition, twice, on purpose = one node.** If two sessions
  independently claim `(causes single-file-fs total-loss-risk)`, they merge.
  That is the point. Divergent *stances* toward it live in annotations and
  `contradicts` edges, which are preserved per-log and union on merge.
- **Identity is registry-relative.** The hash is over canonical term ids, so
  it inherits the §6 caveat: shared registry ⇒ shared hashes. Alias drift
  between lineages produces distinct hashes for the same meaning — that's the
  cross-lineage reconciliation problem, and it stays out of scope here
  (UEL / converter territory, §12).
- **Cycles collapse.** Claims-about-claims can in principle form reference
  cycles; `resolve` carries a visited set and renders a back-reference as the
  marker `cycle`. Coarse but deterministic; cycles among proposition
  arguments are degenerate enough that finer treatment can wait for a
  real-world example.
- **`def` payloads include the gloss.** Two defs of the same term with
  different gloss text are different nodes; the right dedup for near-miss
  glosses is `merge`, chosen by an agent, not silent hash collision.
- **12 hex chars (48 bits).** Collision risk is negligible at conversation
  scale (birthday bound ≈ 16M nodes for 50% collision odds); the full digest
  is available if the global KB ever needs it.

## Merge sketch (v0.3)

```
merge(logA, logB):
  fold each; compute hash for every node
  identity map: hash -> canonical node (union annotations, keep both :src)
  edges: rewrite endpoints to hashes, union
  statuses: latest-delta-wins within a log; conflicts across logs surface
            as a (question ...) node, not silent resolution
  serial ids: reassign in the merged log; hashes are the join keys,
              serials remain the wire format (token economy unchanged)
```

Note the last line: **hashes are join keys, not wire ids.** Logs keep
emitting serial ids; hashes are computed at fold time. This keeps the wire
format byte-cheap while making merge deterministic — no spec change to §7
is required, which is why the prototype can ship ahead of v0.3.

## Prototype

`fold.py --hashes` prints the id → hash → payload table for a folded log.
`Graph.hash_id(nid)` implements the recursive resolution. Cross-log
stability is pinned by unit tests (`TestHashIds`).
