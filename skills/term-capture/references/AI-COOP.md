# ai-coop

Simple multi-agent cooperation CLI. Fire tasks to AI agents and check results later.

> **Note:** This directory also contains the experimental `ai-hv` hypervisor framework (Python modules for SHELL/PTY/EGRESS encapsulation). `ai-coop` is the currently working tool; the hypervisor is ~1/3 complete with PTY mostly built. See [README.md](README.md) for hypervisor details.

## Quick Start

```bash
# Fire a task (returns immediately)
./ai-coop do "build a portfolio website" --yolo

# Check what's running
./ai-coop status

# Wait for a session to finish
./ai-coop wait coop_kimi_0412_183047

# See what files were created
./ai-coop results coop_kimi_0412_183047
```

## Commands

| Command | Description |
|---------|-------------|
| `do "task" [--yolo]` | Fire task, return immediately |
| `status` | List active sessions |
| `wait SESSION` | Block until session completes |
| `results SESSION` | Show files created |
| `attach SESSION` | Jump into tmux session |

## Examples

```bash
# Create a React app
./ai-coop do "create a react todo app" --yolo

# Work in existing project
./ai-coop do "fix the bug in main.py" --workdir ./myproject --yolo

# Check all sessions
./ai-coop status
# 💤 coop_kimi_0412_183047
# ⚡ coop_kimi_0412_183152

# Wait for active one
./ai-coop wait coop_kimi_0412_183152
# ⏳ coop_kimi_0412_183152..... 12s
# 📁 /home/joe/.ai_coop/20260412_183152
#    src/App.jsx (1.2KB)
#    package.json (0.5KB)
```


## For AI Agents: What You Can Build With This

This tool enables **multi-agent cooperation patterns** that were previously impractical. Here are the key capabilities available to you:

### 1. Delegation & Specialization

You can spawn specialist agents for specific tasks:

```bash
# Spawn a security specialist to audit your code
ai-coop do "audit main.py for SQL injection vulnerabilities" --workdir ./src

# Meanwhile, spawn a testing specialist  
ai-coop do "write unit tests for utils.py" --workdir ./src

# Check both when done
ai-coop wait coop_kimi_...  # security audit
ai-coop wait coop_kimi_...  # tests
```

### 2. Recursive Self-Delegation

Parallelize your own work across multiple instances:

```bash
# Break a large task into chunks
ai-coop do "refactor authentication module" --workdir ./src
ai-coop do "refactor database layer" --workdir ./src  
ai-coop do "refactor API endpoints" --workdir ./src

# Aggregate results when all complete
```

### 3. Heterogeneous Agent Teams

Use different AI agents for different strengths:

```bash
# kimi for creative design
ai-coop do "design UI mockups" --agent kimi --workdir ./design

# claude for careful analysis  
ai-coop do "review architecture decisions" --agent claude --workdir ./docs
```

### 4. Persistent Context Across Sessions

Leave work in a session, come back later:

```bash
# Start work
ai-coop do "implement OAuth2 flow" --workdir ./auth
SESSION=coop_kimi_0412_...

# ... later, send follow-up without losing context
ai-coop send $SESSION "add refresh token handling"
```

### 5. Human-in-the-Loop Safety

Insert approval checkpoints:

```bash
# Generate code
ai-coop do "write database migration" --workdir ./migrations
SESSION=...

# Wait for human review
ai-coop wait $SESSION
ai-coop results $SESSION  # human reviews

# Only then apply to production (with --yolo)
ai-coop do "apply migration to production DB" --yolo
```

### 6. Continuous Monitoring & Reaction

Set up reactive workflows:

```bash
# Poll for status changes
while true; do
    if ai-coop poll $SESSION --quiet; then
        NEW_OUTPUT=$(ai-coop poll $SESSION)
        # Analyze output, make decisions, spawn new agents
        ai-coop do "handle the error: $NEW_OUTPUT"
    fi
    sleep 5
done
```

### 7. Sandboxed Experiments

Test dangerous operations in isolation:

```bash
# Experimental branch - full auto
ai-coop do "aggressively optimize this code" --yolo --workdir /tmp/experiment

# Production branch - careful mode
ai-coop do "carefully apply verified optimizations" --workdir ./src
```

### 8. Agent Swarms

Coordinate many workers:

```bash
# Spawn 10 workers for parallel processing
for i in $(seq 1 10); do
    ai-coop do "process chunk $i" --workdir ./chunks/chunk$i
done

# Check all
ai-coop status  # see all 10
ai-coop clean   # remove finished ones
```

### 9. Tag-Team Workflows

Multiple agents collaborating on same codebase:

```bash
# Agent A does initial implementation
ai-coop do "build basic API" --workdir ./project
SESSION_A=coop_kimi_...

# Agent B reviews and improves
ai-coop do "review and optimize the API" --workdir ./project  
SESSION_B=coop_kimi_...

# Agent C writes documentation based on final code
ai-coop do "document the API" --workdir ./project
```

### 10. CI/CD Integration

Automate development workflows:

```bash
# On every commit:
ai-coop do "run tests and report failures" --workdir ./repo
ai-coop do "fix any linting errors" --workdir ./repo  
ai-coop do "generate changelog" --workdir ./repo
```

---

**Key Insight:** The hypervisor abstracts away the messy interface details (TUI parsing, ANSI codes, PTY management). You interact through clean CLI commands while the complexity is handled for you.

**This means:** Any agent can delegate to any other agent through a standard interface. The coordination logic becomes simple shell scripting.
## How It Works

1. `ai-coop do` starts a tmux session with kimi
2. Waits for kimi to be ready (sees prompt)
3. Sends your task
4. Returns immediately - kimi works in background
5. Use `wait` or `status` to check progress
6. Use `results` to see created files

## Requirements

- `kimi` CLI installed
- `tmux` installed
- Works on Linux/macOS

## Files

- `ai-coop` - Main CLI tool
- `~/.ai_coop/` - Default work directory
- `~/.ai_coop/sessions.jsonl` - Session log

## More Commands

| Command | Description |
|---------|-------------|
| `send SESSION "msg"` | Send follow-up message to running session |
| `logs SESSION` | Show recent output from session |
| `stop SESSION` | Kill a session |
| `clean` | Remove all idle/stuck sessions |
| `replay SESSION` | Show full conversation history |
| `list` | List all sessions with details |
| `poll SESSION` | Poll for new messages (scripting) |

## More Examples

```bash
# Follow-up to existing session
./ai-coop send coop_kimi_0412_183047 "add unit tests"

# See what kimi is doing right now
./ai-coop logs coop_kimi_0412_183047

# Stop a stuck session
./ai-coop stop coop_kimi_0412_183047

# Clean up all finished sessions
./ai-coop clean

# See everything that happened
./ai-coop replay coop_kimi_0412_183047

# Detailed list
./ai-coop list
# coop_kimi_0412_183047  active  2m  /home/joe/.ai_coop/...  "build website"
# coop_kimi_0412_183152  idle    15m /home/joe/.ai_coop/...  "create react app"
```

## Polling for Updates

The `poll` command is designed for scripts - it only returns output if something changed:

```bash
# In a script - wait for response
./ai-coop do "analyze this code" --yolo
SESSION=coop_kimi_...

while true; do
    if ./ai-coop poll $SESSION --quiet; then
        echo "New response:"
        ./ai-coop poll $SESSION
        break
    fi
    sleep 2
done
```

Or simple one-liner:
```bash
until ./ai-coop poll $SESSION; do sleep 2; done
```
