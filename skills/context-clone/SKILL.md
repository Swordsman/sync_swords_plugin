---
name: context-clone
description: Clone essential parent context to subagents so they know what to look for. Use when spawning subagents for file I/O, research, or any task where filtering is needed. Gives subagents your intent so they return signal not noise.
---

# Context Clone

**Subagents need to know what's important to YOU.** Without your context, they return everything (noise). With your context, they filter (signal).

## The Problem

You spawn a subagent to read a file:
```python
Agent(prompt="Read src/auth.py and tell me what's important")
```

Subagent returns: "File has 50 functions, 2000 lines, here's everything..."

**Wrong.** You wanted: "What auth mechanisms are used?"

## The Solution: Context Cloning

Pass your essential context to the subagent:

```python
Agent(
    prompt=f"""
    PARENT CONTEXT: Working on OAuth2 migration from basic auth.
    CURRENT TASK: Find how JWT tokens are currently validated.
    
    Read src/auth.py and report:
    - What token validation exists
    - Dependencies/libraries used
    - Migration blockers
    """
)
```

Now subagent knows: "I need auth mechanisms, specifically JWT validation, for a migration."

## What to Clone

**Always include:**
1. **Current goal** - What are we trying to accomplish?
2. **Relevant constraints** - OAuth2, specific libraries, timeframe?
3. **What you're looking for** - Specific patterns, functions, data?
4. **What to ignore** - Known irrelevant stuff (tests, docs, etc.)

**Example context block:**
```
PARENT CONTEXT:
- Goal: Refactor database layer to use async SQLAlchemy
- Current: Synchronous SQLite with raw queries
- Target: Async PostgreSQL with ORM
- Blocker: Unknown how many queries need rewriting

YOUR TASK:
Find all database query locations in the codebase.
For each file:
- Path
- Query count
- Whether it uses ORM or raw SQL
- How complex the queries are (simple CRUD vs joins)
```

## Context Clone Template

```python
parent_context = """
Current task: [what we're doing]
Relevant background: [what got us here]
Specific focus: [what to look for]
Known irrelevant: [what to skip]
Expected output format: [how to return findings]
"""

Agent(
    description="[task name]",
    prompt=f"""
    {parent_context}
    
    YOUR TASK:
    [specific file operation]
    """
)
```

## Examples

### Example 1: Debugging
```python
context = """
BUG: Intermittent 500 errors on /api/users endpoint
ERROR LOG: "Connection pool exhausted" 
HYPOTHESIS: Database connections not being closed
FOCUS: Find connection handling in user-related API code
"""

Agent(prompt=f"{context}\n\nFind all database connection usage in src/api/users*.py")
```

### Example 2: Feature Addition
```python
context = """
FEATURE: Add rate limiting to public API endpoints
CURRENT: No rate limiting exists
REQUIREMENTS: Max 100 req/min per IP, Redis-based
FOCUS: Where are public endpoints defined? Middleware structure?
"""

Agent(prompt=f"{context}\n\nExplore src/api/ to find public endpoint definitions and middleware patterns")
```

### Example 3: Code Review
```python
context = """
REVIEW: Security audit of authentication module
CONCERN: Potential JWT timing attacks, weak secret handling
FOCUS: Token validation flow, secret management, crypto usage
"""

Agent(prompt=f"{context}\n\nReview src/auth/ for security issues. Report specific vulnerabilities with line references.")
```

## Common Mistakes

❌ **Vague context:** "Read this file and tell me about it"
→ Subagent returns everything

✅ **Specific context:** "We're adding caching. Find all database queries in this file that should be cached."
→ Subagent filters for cacheable queries

❌ **No background:** "Find bugs in the code"
→ Subagent doesn't know what "bug" means in this context

✅ **With background:** "Memory leak reported in image processing. Find where large images are loaded but not freed."
→ Subagent knows to look for resource leaks

## Progressive Context

Don't dump your entire context. Clone what's relevant:

**Too much:**
```
[500 lines of conversation history]
[All files in the project]
[Your entire plan]
```

**Just right:**
```
Current step: Implementing OAuth2 callback handler
Blocker: Don't know where to store the access token
Looking for: Existing session/auth storage patterns
```

## The Rule

**Every subagent prompt should include:**
- What you're trying to do (goal)
- Why you need this info (context)
- What specific answer you need (task)

Without this, subagents guess. Guessing = noise.

