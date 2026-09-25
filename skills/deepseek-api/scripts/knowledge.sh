#!/usr/bin/env bash
# knowledge.sh — serve skill fragments with dedup (no double-serving).
#
# Usage:
#   scripts/knowledge.sh list                  # all fragments + bundles
#   scripts/knowledge.sh <name> [<name> ...]   # print those fragments (bundles expand)
#   scripts/knowledge.sh --id=NAME <names...>  # identify your context
#   scripts/knowledge.sh --again <names...>    # reprint even if already served
#   scripts/knowledge.sh register NAME...      # head agent: pre-register subagent ids
#   scripts/knowledge.sh status                # served fragments, all agent ids
#   scripts/knowledge.sh --reset               # forget served state for YOUR id only
#
# Dedup: markers at ../.consumed/<agent-id>/<frag> (gitignored). Repeat
# requests print a skip notice. --again overrides. --reset clears your markers.
# Env: DEEPSEEK_SKILL_SESSION_SCOPED=1 trusts markers (no TTL).
#      DEEPSEEK_SKILL_TTL_MIN (default 360) — stale-marker cleanup in unscoped mode.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
REF="$ROOT/references"
BASE="$ROOT/.consumed"
TTL_MIN="${DEEPSEEK_SKILL_TTL_MIN:-360}"
SESSION_SCOPED="${DEEPSEEK_SKILL_SESSION_SCOPED:-0}"
AGENT_ID="${DEEPSEEK_SKILL_AGENT_ID:-main}"

frag_file() { # fragment name -> path relative to references/
  case "$1" in
    chat)         echo "chat-completions.md" ;;
    streaming)    echo "streaming.md" ;;
    thinking)     echo "thinking-mode.md" ;;
    tools)        echo "tool-calling.md" ;;
    structured)   echo "structured-output.md" ;;
    fim)          echo "fim-completion.md" ;;
    anthropic)    echo "anthropic-endpoint.md" ;;
    pricing)      echo "pricing-caching.md" ;;
    ops)          echo "ops-troubleshooting.md" ;;
    integrations) echo "integrations.md" ;;
    claude-code|copilot|oh-my-pi|nanobot|crush|deep-code|workbuddy|pi)
                  echo "integrations/$1.md" ;;
    *) return 1 ;;
  esac
}

bundle_expand() { # bundle name -> fragment list
  case "$1" in
    agent-loop) echo "thinking tools" ;;
    full-chat)  echo "chat thinking streaming" ;;
    *) return 1 ;;
  esac
}

list_all() {
  cat <<'EOF'
Fragments (name -> references/ file):
  chat          chat-completions.md      full /chat/completions request/response schema
  streaming     streaming.md             SSE parsing, keep-alive, timing
  thinking      thinking-mode.md         thinking states, effort, reasoning_content rules
  tools         tool-calling.md          function calling, quirks, strict mode
  structured    structured-output.md     JSON mode + chat prefix completion
  fim           fim-completion.md        fill-in-the-middle endpoint
  anthropic     anthropic-endpoint.md    Anthropic-compat field tables
  pricing       pricing-caching.md       model choice, prices, KV cache
  ops           ops-troubleshooting.md   errors, rate limits, /models, /balance
  integrations  integrations.md          tool-integration router (short setups inline)
  claude-code | copilot | oh-my-pi | nanobot | crush | deep-code | workbuddy | pi
                integrations/<name>.md   per-tool integration configs

Bundles (expand to several fragments, deduped):
  agent-loop    = thinking tools
  full-chat     = chat thinking streaming

Flags: --again (reprint already-served), --reset (forget served state)
EOF
}

if [ "$SESSION_SCOPED" != "1" ] && [ -d "$BASE" ]; then
  # Unscoped topology: expire stale markers (all ids) so persistent
  # workspaces don't poison new sessions. (Session-scoped envs reset
  # by construction.)
  find "$BASE" -type f -mmin +"$TTL_MIN" -delete 2>/dev/null || true
fi

AGAIN=0
WANT_STATUS=0
WANT_RESET=0
WANT_REGISTER=0
names=""
for arg in "$@"; do
  case "$arg" in
    list|--list|-l) list_all; exit 0 ;;
    register)       WANT_REGISTER=1 ;;
    status)         WANT_STATUS=1 ;;
    --reset)        WANT_RESET=1 ;;
    --again)        AGAIN=1 ;;
    --id=*)         AGENT_ID="${arg#--id=}" ;;
    -h|--help)      sed -n '2,43p' "$0"; exit 0 ;;
    *)              names="$names $arg" ;;
  esac
done

REGISTRY="$BASE/.registry"

if [ "$WANT_REGISTER" -eq 1 ]; then
  [ -z "${names// /}" ] && { echo "usage: knowledge.sh register <id> [<id>...]" >&2; exit 1; }
  mkdir -p "$BASE"
  for id in $names; do
    case "$id" in
      *[!A-Za-z0-9_-]*|"") echo "error: id must match [A-Za-z0-9_-]+ (got '$id')" >&2; exit 1 ;;
    esac
    grep -qx "$id" "$REGISTRY" 2>/dev/null || echo "$id" >> "$REGISTRY"
  done
  echo "[registered:$(printf ' %s' $names) — tell each subagent its id in its spawn prompt]"
  exit 0
fi

case "$AGENT_ID" in
  *[!A-Za-z0-9_-]*|"")
    echo "error: --id must match [A-Za-z0-9_-]+ (got '$AGENT_ID')" >&2; exit 1 ;;
esac
if [ -s "$REGISTRY" ] && [ "$AGENT_ID" != "main" ] && ! grep -qx "$AGENT_ID" "$REGISTRY"; then
  echo "error: id '$AGENT_ID' is not registered (typo?). Registered ids:$(printf ' %s' $(cat "$REGISTRY")). Head agent can add yours: knowledge.sh register $AGENT_ID" >&2
  exit 1
fi
MARK="$BASE/$AGENT_ID"
mkdir -p "$MARK"

if [ "$WANT_STATUS" -eq 1 ]; then
  [ -s "$REGISTRY" ] && echo "registered ids:$(printf ' %s' $(cat "$REGISTRY"))"
  any=0
  for d in "$BASE"/*/; do
    [ -d "$d" ] || continue
    id="$(basename "$d")"
    served=""
    for m in "$d"*; do [ -e "$m" ] && served="$served $(basename "$m")"; done
    [ -n "$served" ] && { echo "agent '$id' served:$served"; any=1; }
  done
  [ "$any" -eq 0 ] && echo "No fragments marked served (any agent id)."
  exit 0
fi

if [ "$WANT_RESET" -eq 1 ]; then
  rm -rf "$MARK"; echo "[served-state reset for agent '$AGENT_ID']"; exit 0
fi

[ -z "${names// /}" ] && { list_all; exit 0; }

# Expand bundles, then dedupe while preserving order.
expanded=""
for n in $names; do
  if b="$(bundle_expand "$n" 2>/dev/null)"; then expanded="$expanded $b"; else expanded="$expanded $n"; fi
done
final=""
for n in $expanded; do
  case " $final " in *" $n "*) ;; *) final="$final $n" ;; esac
done

# Validate everything before serving anything.
for n in $final; do
  if ! frag_file "$n" >/dev/null 2>&1; then
    echo "error: unknown fragment '$n'" >&2
    echo >&2; list_all >&2
    exit 1
  fi
done

for n in $final; do
  f="$(frag_file "$n")"
  if [ -e "$MARK/$n" ] && [ "$AGAIN" -eq 0 ]; then
    if [ "$SESSION_SCOPED" = "1" ]; then
      echo "[already served to agent '$AGENT_ID' this session: '$n'. Different context? pass --id=<your-name>. Reprint: --again. File: references/$f]"
    else
      echo "[skipped '$n' — marked served for agent '$AGENT_ID' in this workspace. Different context? pass --id=<your-name>. Marker possibly stale (prior session, compaction)? --again reprints. File: references/$f]"
    fi
  else
    printf '\n===== %s (references/%s) =====\n\n' "$n" "$f"
    cat "$REF/$f"
    touch "$MARK/$n"
  fi
done

# State receipt: a compact copy of this agent's served-set, carried in the
# agent's own context — cheap, unmanaged, and it survives compaction better
# than the fragments it summarizes.
receipt=""
for m in "$MARK"/*; do [ -e "$m" ] && receipt="$receipt $(basename "$m")"; done
echo ""
echo "[state receipt — agent '$AGENT_ID' has now been served:$receipt]"
