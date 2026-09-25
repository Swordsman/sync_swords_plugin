# Context Atom Tier Taxonomy

**Version:** 0.1  
**Purpose:** Explicit classification rules for semantic compression levels of knowledge/context objects.

---

## Tier Definitions

Each tier is defined by **token budget**, **information density**, **structural completeness**, **actionability**, and **survival priority** under context pressure.

| Tier | Budget | Density | Completeness | Actionability | Priority |
|------|--------|---------|--------------|---------------|----------|
| **extended** | 2000-4000 | High | Full prose, examples, justifications | Complete procedures with fallbacks | 1 (last to compress) |
| **full** | 1000-2000 | High | Full prose, no examples | Complete procedures | 2 |
| **midhigh** | 500-1000 | Very high | Condensed prose, key points only | Core procedures, no fallbacks | 3 |
| **mid** | 250-500 | Very high | Bullet points, minimal prose | Action list, no explanations | 4 |
| **midlow** | 100-250 | Extreme | Short bullets, telegraphic | Commands only, context implied | 5 |
| **low** | 50-100 | Extreme | 1-2 sentences or very short list | Single action or query | 6 |
| **mini** | 20-50 | Maximum | Phrase or 1 sentence | Reminder only | 7 |
| **micro** | 5-20 | Maximum | 2-10 words | Cue only | 8 (first to compress) |

---

## Classification Rules

A context atom is classified into a tier based on evaluating these characteristics:

### 1. Structural Completeness Score (0-100)
- **100** = Full narrative with examples, rationale, and edge cases
- **75** = Full narrative without examples
- **50** = Key points in prose or bullets
- **25** = Bullet list, no prose connectors
- **10** = Telegraphic fragments
- **0** = Single phrase or words

### 2. Actionability Score (0-100)
- **100** = Can execute independently with no external context
- **75** = Can execute with minor assumed context
- **50** = Knows what to do but not exact parameters
- **25** = Knows what to ask or check
- **10** = Vague direction
- **0** = No actionable content (pure metadata/label)

### 3. Token Density (tokens per information unit)
- **< 2.0** = micro/mini (caveman speech)
- **2.0 - 4.0** = low/midlow (compressed)
- **4.0 - 8.0** = mid/midhigh (dense)
- **8.0 - 15.0** = full/extended (normal prose)
- **> 15.0** = extended (verbose with examples)

### 4. Dependency Surface Area
- **High dependencies** (references many other atoms) = tends toward **mid** or above, because compression requires decompression knowledge
- **Low dependencies** (self-contained) = can compress to **mini/micro**
- **Zero dependencies** (pure label/cue) = **micro**

### 5. Current Relevance (dynamic)
- **Focal** (active task) = maintain at original tier or higher
- **Context** (supporting) = allow 1 tier compression
- **Predicted** (likely needed soon) = allow 2 tier compression
- **Background** (available but not active) = compress to **low/mini**
- **Archived** (known but inactive) = **micro** or evict to storage

---

## Tier-to-Tier Compression Rules

When pressure forces a downgrade, the transformation must preserve **identity** (what is this about?) and **actionability** (what do I do with it?).

### extended -> full
- Strip all examples and extended rationale
- Keep all procedures and decision trees

### full -> midhigh
- Convert prose to dense bullets
- Strip explanatory transitions
- Keep explicit action verbs

### midhigh -> mid
- Remove all explanation, keep action items only
- Flatten nested lists
- Strip articles and auxiliary verbs

### mid -> midlow
- Telegraphic bullets (verb + object + parameter)
- One concept per line, no connectors

### midlow -> low
- Single sentence or 2-3 bullets maximum
- Only the most critical action

### low -> mini
- One sentence reminder
- "Check X before Y" or "Use Z for W"

### mini -> micro
- Caveman speech: all major events, no detail
- "walked dog. got mail. saw neighbor. went home."

### micro -> focal-micro
- Apply focal slice: only parts relevant to current query/goal
- Query="mail" -> "got mail."
- Query="dog" -> "walked dog. dog barked. fed dog."
- Query="accident" -> "tripped on sidewalk."

### focal-micro -> evict
- Write to storage (file/DB), leave a pointer: `[EVICTED: path/to/file]`

---

## KCK Tier Mapping

The Kimi Context Kernel exists at all tiers:

- **extended** (this doc): Full environment + diagnostic + recovery + capabilities + principles + quick checks
- **full**: Strip examples and extended explanations from extended
- **midhigh**: Dense bullet form of the above
- **mid**: Action list only
- **midlow**: Telegraphic commands
- **low**: "Check context before acting. Read session_briefing.md if lost. Export before compaction."
- **mini**: "Context kernel active. Read briefing if lost."
- **micro**: "[KCK-CLIP][KCK-CASTLE] KCK"

The **micro** form (`[KCK-CLIP][KCK-CASTLE] KCK`) acts as a trigger. Seeing it tells the model: "There is a context kernel. If you need it, request a higher tier."

---

## Procedural Determination Algorithm

Given a query and a set of context atoms, determine the optimal assembly:

```python
def assemble_context(query, atoms, budget):
    # 1. Score relevance of each atom to query
    for atom in atoms:
        atom.relevance = score_similarity(query, atom)
    
    # 2. Sort by relevance * importance
    atoms.sort(key=lambda a: a.relevance * a.importance, reverse=True)
    
    # 3. Starting from most relevant, pick tier level
    remaining = budget
    for atom in atoms:
        # Focal atoms get best tier
        if atom.relevance > 0.8:
            tier = atom.base_tier
        elif atom.relevance > 0.5:
            tier = compress_tier(atom.base_tier, 1)
        elif atom.relevance > 0.2:
            tier = compress_tier(atom.base_tier, 3)
        else:
            tier = "micro"
        
        cost = atom.tier_costs[tier]
        if cost <= remaining:
            atom.selected_tier = tier
            remaining -= cost
        else:
            # Try compressing further
            for fallback in get_lower_tiers(tier):
                cost = atom.tier_costs[fallback]
                if cost <= remaining:
                    atom.selected_tier = fallback
                    remaining -= cost
                    break
            else:
                atom.selected_tier = None  # Skip
    
    # 4. Pull dependencies at matching or lower tier
    for atom in atoms:
        if atom.selected_tier:
            for dep in atom.dependencies:
                ensure_loaded(dep, min_tier=atom.selected_tier)
    
    # 5. Order for KV cache stability (kernel first, then by dependency depth)
    ordered = topological_sort([a for a in atoms if a.selected_tier])
    return ordered
```

This is the **ContextWindow camera** algorithm from the Robody architecture.
