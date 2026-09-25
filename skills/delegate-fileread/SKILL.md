---
name: delegate-fileread
description: Read files via subagent to protect parent context. Use for ANY file operation that might return large or unpredictable output - reading unknown files, globs, searches, directory exploration. Parent stays clean, subagent returns distilled signal.
---

# Delegate File Read

**Never read files directly in the parent agent.** Spawn a subagent for ALL file I/O.

## When to Use

**ALWAYS delegate these operations:**
- Reading any file you haven't seen before
- `glob` patterns (unknown result count)
- `Grep` searches (matches could be extensive)
- Directory listings (`ls -la`, `find`)
- Log parsing
- Reading configs, data files, JSON/CSV/XML
- Recursive operations

**Only exception:** Tiny files (<50 lines) where you wrote the content yourself in this session.

## Why This Matters

- File contents go directly into YOUR context
- A 2000-line file = 2000+ tokens you can't remove
- Unexpected large files trigger compactions
- Even "small" operations can explode (e.g., `grep -r` on node_modules)

## The Pattern

```python
# DON'T (pollutes your context):
content = ReadFile("src/unknown_module.py")  # Could be 5000 lines!

# DO (keeps context clean):
Agent(
    description="Read and summarize module",
    prompt="""
    Read src/unknown_module.py and return:
    
    FILE: src/unknown_module.py
    PURPOSE: 1-sentence summary of what it does
    KEY_FUNCTIONS: List main functions/classes with 1-line descriptions
    IMPORTS: What it depends on
    SIZE: Line count
    
    Do NOT return full code. Distill to essential facts only.
    """,
    subagent_type="explore"
)
```

## Subagent Return Format

Subagents MUST return signal, not noise:

```
FILE: path/to/file.ext
SIZE: N lines, M bytes
PURPOSE: What this file does
KEY_CONTENTS:
- Function X: does Y
- Class Z: handles W
- Config: sets A, B, C
DEPENDENCIES: imports/libs used
STATUS: success/failed
```

## Progressive Disclosure

If you need more detail after the summary:

```python
# Follow-up for specific details:
Agent(
    description="Get function signature",
    prompt="Read auth.py lines 45-60. Return ONLY the login() function signature and first 5 lines of its implementation."
)
```

## What You Keep in Context

Your context contains:
- File paths
- Summaries
- Key findings
- Decisions based on content

NOT:
- Raw file contents
- Full code listings
- Verbose logs

## Example: Batch File Operations

```python
# Delegate batch read:
Agent(
    description="Analyze codebase structure",
    prompt="""
    Find all Python files in src/ matching pattern.
    For each file (max 10), return:
    - Path
    - Line count
    - 1-sentence purpose
    - Main exported functions/classes
    
    If more than 10 files, return the 10 most important.
    """
)

# Later, get specific file contents only when needed:
Agent(
    description="Read specific implementation",
    prompt="Read src/auth.py and extract the JWT token validation logic."
)
```

## Anti-Patterns

❌ **Don't:** Read file then summarize yourself (content already in context)
❌ **Don't:** Grep for patterns and review all matches (matches pollute context)
❌ **Don't:** Use wildcards without delegation (unbounded results)
❌ **Don't:** Assume file sizes (even "config files" can be huge)

✅ **Do:** Delegate first read of any file
✅ **Do:** Ask subagent to filter/match before reporting
✅ **Do:** Get summaries, then drill down specifically
✅ **Do:** Use wc/head to check size before deciding to delegate

## Emergency: No Subagent Available

If you MUST read directly (no subagent tool available):
1. Check size first: `wc -l file` or `head -20 file`
2. If >100 lines, read in small chunks
3. Accept that compaction will happen
4. Re-read AGENTS.md immediately after to restore guidance

