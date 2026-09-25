# squishyatoms

Multi-tier knowledge compression for context window management.

## What it does

Each ContextAtom stores a concept at 8 compression levels:
`extended > full > midhigh > mid > midlow > low > mini > micro`

A ContextAssembler selects the right tier per atom based on query relevance, importance, and token budget. Greedy tier selection under budget with dependency resolution.

## Usage

```python
from context_atom import ContextAtom, ContextAssembler

atom = ContextAtom(
    name="concept",
    forms={"full": "detailed explanation...", "mini": "short version"},
    importance=0.8
)
assembler = ContextAssembler(atoms=[atom], budget=4000)
result = assembler.assemble(query="relevant topic")
print(result.render())
```

## When to use

- Compressing verbose context into tiered storage
- Assembling budget-constrained context for a query
- Cross-agent handoffs where full context doesn't fit
- Hierarchical memory systems

## Reference

See `references/CONTEXT_ATOM_TIERS.md` for the full tier taxonomy and scoring rules.

## Location

Script: `${CLAUDE_PLUGIN_ROOT}/scripts/context_atom.py`

Stdlib-only Python, no dependencies.

## Source

[Swordsman/squishyatoms](https://github.com/Swordsman/squishyatoms)
