# what-ipo-without-fixes

Temporary workaround for a [known, unpatched platform bug](https://github.com/anthropics/claude-code/issues/92031) that has been open since June 2026 with no response from Anthropic.

## The bug

Claude Code cloud sessions (`cloud_default` environment type) inject `SKIP_PLUGIN_MARKETPLACE=true` into the container environment, silently disabling all plugin marketplace sync. The plugin bucket directory is created but never populated. `ListPlugins` returns empty. No error is shown. The documentation explicitly states that synced plugins work in cloud sessions. They do not.

Related issues: [#78119](https://github.com/anthropics/claude-code/issues/78119), [#84557](https://github.com/anthropics/claude-code/issues/84557), [#87497](https://github.com/anthropics/claude-code/issues/87497), [#92031](https://github.com/anthropics/claude-code/issues/92031), [#93264](https://github.com/anthropics/claude-code/issues/93264).

## What this skill does

The `what-ipo-without-fixes` skill ships a SessionStart hook script (`references/loader.sh`) that detects the broken sync, validates declared plugin sources, clones them, and populates the plugin bucket and skills bucket manually. It is idempotent and self-deprecating: when the upstream bug is fixed, it detects normal plugin loading and asks to be removed.

## Installation

Add this to your cloud environment's setup script on claude.ai:

```bash
cat >> ~/.claude/settings.json << 'EOF'
{"hooks":{"SessionStart":[{"matcher":"","hooks":[{"type":"command","command":"bash $(find ~/.claude/skills/synced/*/what-ipo-without-fixes/ -name loader.sh 2>/dev/null | head -1) 2>/dev/null || true"}]}]}}
EOF
```

Or invoke `/what-ipo-without-fixes` manually in a session to run the loader on demand.

## When to use

- Automatically at SessionStart via the environment hook above
- Manually via `/what-ipo-without-fixes` if plugins didn't load and you need them now
- To check status: the loader prints what it loaded or what went wrong

## When to remove

When the loader prints: `Bug fixed — plugins loaded normally.`

That means `SKIP_PLUGIN_MARKETPLACE` is no longer set and the plugin bucket populated on its own. Remove the hook from your environment setup script and uninstall this skill.
