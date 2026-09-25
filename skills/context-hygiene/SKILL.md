# Context Hygiene (Project Version)

**For universal version, see:** `~/.kimi/skills/context-hygiene/SKILL.md`

This project uses the context hygiene process. Quick reference:

## Quick Diagnostic

```bash
# Global diagnostic (works everywhere)
python3 ~/.kimi/skills/context-hygiene/quick_diagnose.py

# Or local customized version
python3 .knowledge/skills/context-hygiene/quick_diagnose.py
```

## Project-Specific Session Reset

This project maintains session reset docs in:
```
.knowledge/session_reset/
├── README.md                    # Index
├── CONTEXT_HYGIENE_PROCESS.md   # Full process documentation  
├── working_systems.md           # IRC + Knowledge Base status
├── pending_tasks.md             # Research findings + tasks
├── archived.md                  # Broken components
├── context.md                   # Session notes
└── verification.md              # Health checks
```

## Quick Status

**Working:**
- IRC Server: `http://localhost:8000` (PID 47973)
- Knowledge Base: 17 entries, queue clean

**Pending:**
- MiniMax + Claude Code integration
- Python PTY wrapper implementation
- DeepSeek research

**Archived:**
- `researcher_daemon_v2.py` (broken, 4+ failed fixes)
- `prompts.py` (over-engineered)

## When to Run Hygiene Check

1. Before long breaks
2. After thrashing detected
3. Before major handoffs
4. When context feels "heavy"

## Full Process

See `~/.kimi/skills/context-hygiene/SKILL.md` for complete 6-phase process:
1. Self-Assessment
2. System Inventory
3. Data Quality Audit
4. Fix & Archive
5. Documentation
6. Handoff Preparation
