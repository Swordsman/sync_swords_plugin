#!/usr/bin/env bash
# deepseek.sh — minimal raw-call wrapper for the DeepSeek API.
# Requires: curl. Optional: jq (pretty-prints responses when present).
# Auth: reads DEEPSEEK_API_KEY from the environment.
#
# Usage:
#   ./deepseek.sh chat "Your prompt" [model]        # non-streaming chat completion
#   ./deepseek.sh chat --think-off "Prompt" [model] # disable thinking mode
#   ./deepseek.sh stream "Your prompt" [model]      # streaming (SSE to stdout)
#   ./deepseek.sh models                            # GET /models
#   ./deepseek.sh balance                           # GET /user/balance
#   ./deepseek.sh raw <endpoint> <json-body>        # POST arbitrary body, e.g.
#   ./deepseek.sh raw chat/completions '{"model":"deepseek-v4-flash","messages":[...]}'
set -euo pipefail

BASE="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
MODEL_DEFAULT="deepseek-v4-pro"

case "${1:-help}" in help|-h|--help) sed -n '2,14p' "$0"; exit 0;; esac
[ -z "${DEEPSEEK_API_KEY:-}" ] && { echo "error: DEEPSEEK_API_KEY not set" >&2; exit 1; }

pretty() { if command -v jq >/dev/null 2>&1; then jq .; else cat; fi; }

post() { # post <endpoint> <body>
  curl -sS "${BASE}/$1" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
    -d "$2"
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  chat)
    thinking='{"type":"enabled"}'
    if [ "${1:-}" = "--think-off" ]; then thinking='{"type":"disabled"}'; shift; fi
    prompt="${1:?usage: deepseek.sh chat [--think-off] <prompt> [model]}"
    model="${2:-$MODEL_DEFAULT}"
    post chat/completions "$(printf '{"model":"%s","thinking":%s,"stream":false,"messages":[{"role":"user","content":%s}]}' \
      "$model" "$thinking" "$(printf '%s' "$prompt" | jq -Rs . 2>/dev/null || python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' <<<"$prompt")")" | pretty
    ;;
  stream)
    prompt="${1:?usage: deepseek.sh stream <prompt> [model]}"
    model="${2:-$MODEL_DEFAULT}"
    post chat/completions "$(printf '{"model":"%s","stream":true,"messages":[{"role":"user","content":%s}]}' \
      "$model" "$(printf '%s' "$prompt" | jq -Rs . 2>/dev/null || python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))' <<<"$prompt")")"
    ;;
  models)  curl -sS "${BASE}/models" -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" | pretty ;;
  balance) curl -sS "${BASE}/user/balance" -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" | pretty ;;
  raw)     post "${1:?endpoint}" "${2:?json body}" | pretty ;;
  *) sed -n '2,14p' "$0" ;;
esac
