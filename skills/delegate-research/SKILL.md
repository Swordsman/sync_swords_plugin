---
name: delegate-research
description: Delegate research and information-gathering tasks to a subagent to avoid context window pollution. Use when a task involves searching the web, reading documentation, exploring codebases, or any activity likely to generate large amounts of text that needs filtering before being useful. Spawn an agent to do the research, cache results to knowledge base, and return only distilled findings.
---

# Delegate Research Skill

Use this skill when research or information gathering would dump excessive text into your context window. Delegate to a subagent that filters and distills results, caches findings for future reuse.

**This skill can be used by other skills** - if you're implementing another skill that requires research (documentation lookups, web searches, etc.), follow this skill's patterns.

## When to Delegate

Delegate research when the task involves:
- **Web searches** that return many pages of results
- **Documentation reading** from large doc sites
- **Codebase exploration** spanning multiple files/modules
- **Data processing** that generates verbose intermediate output
- **Multiple parallel searches** that would flood context

## When NOT to Delegate

- Simple, targeted searches (1-2 queries, specific answer expected)
- Tasks where you need to see all raw output to make decisions
- Quick file reads with known paths
- Small, focused codebase exploration (<5 files expected)

## How to Delegate

### 1. Check Knowledge Cache First

Before spawning an agent, check if we already have cached research:

```python
import sys
sys.path.insert(0, '/home/joe/code-combo-home/.knowledge')
from knowledge_manager import find_research_finding

# Check if we already researched this
cached = find_research_finding("How does kimi-cli handle sessions?")
if cached:
    print(f"Found cached research (accessed {cached['access_count']} times)")
    return cached['summary']
```

### 2. Spawn Research Agent with Caching

Spawn an agent with `subagent_type="explore"` and cache the results:

```python
import sys
sys.path.insert(0, '/home/joe/code-combo-home/.knowledge')
from knowledge_manager import index_research_finding, cache_web_content

# Spawn research agent
result = Agent(
    description="Research task description",
    prompt="""
    Research task: [specific research goal]
    
    Context from parent session:
    [User's original request]
    [What we've done so far]
    [What we need to find out]
    
    Your task:
    1. [Specific research steps]
    2. Cache any web pages you fetch to /home/joe/code-combo-home/.knowledge/cache/
    3. Filter for: [what's relevant vs what's noise]
    4. Return ONLY: [concise format - key findings, relevant quotes, file paths, etc.]
    
    Use the knowledge_manager module to cache findings.
    """,
    subagent_type="explore"
)

# Index the findings for future reuse
index_research_finding(
    query="Original research query",
    summary=result,
    sources=["url1", "url2", "file_path1"],
    agent_id=result.agent_id if hasattr(result, 'agent_id') else None
)
```

### 3. Set Expectations for Output

Tell the agent what format you need:

| Research Type | Expected Output |
|---------------|-----------------|
| Web search | 3-5 key findings with source URLs |
| Documentation | Relevant sections/quotes with page links |
| Codebase exploration | File paths + 2-3 line summary per relevant file |
| Multiple searches | Consolidated answer synthesizing all sources |

### 4. Emulate Nesting via Resume

For multi-step research, resume the same agent to maintain context:

```python
# First research step
agent1 = Agent(
    description="Step 1: Find architecture docs",
    prompt="Find architecture documentation...",
    subagent_type="explore"
)

# Resume for step 2 (maintains context from step 1)
agent2 = Agent(
    description="Step 2: Analyze patterns",
    prompt="Based on what you found, analyze...",
    subagent_type="explore",
    resume=agent1.agent_id  # Resume same agent
)
```

## Knowledge Cache Management

### Check Cache Stats
```bash
cd /home/joe/code-combo-home/.knowledge
python3 knowledge_manager.py stats
```

### Clear Expired Cache
```bash
python3 knowledge_manager.py clear
```

### Manual Cache Lookup
```python
from knowledge_manager import search_research_index

# Find all research about "sessions"
results = search_research_index("sessions")
for r in results:
    print(f"Query: {r['query']}")
    print(f"Summary: {r['summary'][:200]}...")
    print(f"Accessed: {r['access_count']} times")
```

## Key Principle

**Context window is a shared resource.** The research agent's job is to:
1. Absorb the firehose of information
2. Cache raw sources to disk for future reference
3. Index distilled findings for quick lookup
4. Return only the drinkable glass to parent

This creates a knowledge base that improves over time - common questions get faster answers as cache hit rate increases.

## Thoroughness Levels for Explore Agents

When spawning research agents, specify thoroughness:

- **quick**: Targeted lookups - find specific file, function, config value
- **medium**: Understand a module - how auth works, what calls this API  
- **thorough**: Cross-cutting analysis - architecture overview, multi-module investigation
