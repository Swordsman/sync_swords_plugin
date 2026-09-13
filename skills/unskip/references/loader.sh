#!/usr/bin/env bash
# unskip — workaround for SKIP_PLUGIN_MARKETPLACE=true in cloud sessions
# https://github.com/anthropics/claude-code/issues/92031
#
# This bug has been reported by multiple users since June 2026 with zero
# response from Anthropic. This script exists because the platform won't
# sync plugins it promised to sync. Remove it when they fix it.

set -euo pipefail

# --- Plugins to load ---
# Format: "plugin-name|github-owner/repo|branch"
# Add your own plugins here.
DECLARED_PLUGINS=(
  "sync-swords-plugin|Swordsman/sync_swords_plugin|main"
)

# --- Only run in cloud sessions ---
if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" ]]; then
  exit 0
fi

# --- Self-deprecation: is the bug fixed? ---
if [[ "${SKIP_PLUGIN_MARKETPLACE:-}" != "true" ]]; then
  has_files=$(find ~/.claude/plugins/synced/ -mindepth 2 -maxdepth 2 \( -name "*.json" -o -name "*.md" \) 2>/dev/null | head -1)
  if [[ -n "$has_files" ]]; then
    echo "[unskip] Bug fixed — plugins loaded normally."
    echo "[unskip] Remove the unskip hook from your environment setup script."
    echo "[unskip] This workaround is no longer needed."
    exit 0
  fi
fi

# --- Find the plugin bucket ---
BUCKET_DIR=""
for d in ~/.claude/plugins/synced/*/; do
  [[ -d "$d" ]] && BUCKET_DIR="$d" && break
done
if [[ -z "$BUCKET_DIR" ]]; then
  echo "[unskip] No plugin bucket found — plugin infrastructure not present."
  exit 0
fi

# --- Idempotent: already populated? ---
if [[ $(find "$BUCKET_DIR" -mindepth 1 -maxdepth 1 -not -name '.staging' 2>/dev/null | wc -l) -gt 0 ]]; then
  exit 0
fi

# --- Load plugins ---
SCRATCH="/tmp/unskip-$$"
mkdir -p "$SCRATCH"
trap 'rm -rf "$SCRATCH"' EXIT

LOADED=0
ERRORS=0

for decl in "${DECLARED_PLUGINS[@]}"; do
  IFS='|' read -r PLUGIN_NAME REPO BRANCH <<< "$decl"
  CLONE_DIR="${SCRATCH}/${PLUGIN_NAME}"

  # Clone (validates repo existence + access in one step)
  if ! GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --branch "$BRANCH" \
    "https://github.com/${REPO}.git" "$CLONE_DIR" 2>/dev/null; then
    echo "[unskip] '${PLUGIN_NAME}': cannot clone ${REPO}@${BRANCH}"
    echo "  Repo may not exist, be private, or branch may be wrong."
    ERRORS=$((ERRORS + 1))
    continue
  fi

  # Validate: must be an actual plugin
  if [[ ! -f "$CLONE_DIR/.claude-plugin/plugin.json" ]]; then
    echo "[unskip] '${PLUGIN_NAME}': ${REPO} has no .claude-plugin/plugin.json"
    echo "  Not a valid Claude Code plugin."
    rm -rf "$CLONE_DIR"
    ERRORS=$((ERRORS + 1))
    continue
  fi

  # Populate plugin bucket
  cp -r "$CLONE_DIR/.claude-plugin" "$BUCKET_DIR/" 2>/dev/null || true
  for item in "$CLONE_DIR"/*; do
    cp -r "$item" "$BUCKET_DIR/$(basename "$item")" 2>/dev/null || true
  done

  # Inject skills into the skills bucket (skill sync works, plugin sync doesn't)
  if [[ -d "$CLONE_DIR/skills" ]]; then
    SKILLS_BUCKET=$(find ~/.claude/skills/synced/ -mindepth 1 -maxdepth 1 -type d -not -name '.staging' 2>/dev/null | head -1)
    if [[ -n "$SKILLS_BUCKET" ]]; then
      for skill_dir in "$CLONE_DIR"/skills/*/; do
        skill_name=$(basename "$skill_dir")
        [[ -e "$SKILLS_BUCKET/$skill_name" ]] || cp -r "$skill_dir" "$SKILLS_BUCKET/$skill_name"
      done
    fi
  fi

  LOADED=$((LOADED + 1))
  echo "[unskip] Loaded '${PLUGIN_NAME}' from ${REPO}@${BRANCH}"
done

if [[ "$LOADED" -gt 0 ]]; then
  echo "[unskip] ${LOADED} plugin(s) loaded. (Workaround for SKIP_PLUGIN_MARKETPLACE=true)"
fi
if [[ "$ERRORS" -gt 0 ]]; then
  echo "[unskip] ${ERRORS} plugin(s) had problems — see above."
fi
