#!/usr/bin/env bash
# deepseek.sh — minimal raw-call wrapper for the DeepSeek API.
# Requires: curl. Optional: jq (pretty-prints responses when present).
# Auth: reads DEEPSEEK_API_KEY from the environment. Never sends max_tokens (leave it unset).
#
# Usage:
#   ./deepseek.sh chat "Your prompt" [model]        # non-streaming chat completion
#   ./deepseek.sh chat --think-off "Prompt" [model] # disable thinking mode
#   ./deepseek.sh chat - [model] < prompt.txt       # prompt from stdin (any size)
#   ./deepseek.sh stream "Your prompt" [model]      # streaming (SSE to stdout); "-" reads stdin
#   ./deepseek.sh models                            # GET /models
#   ./deepseek.sh balance                           # GET /user/balance
#   ./deepseek.sh raw <endpoint> [FILE|-]           # POST a JSON body from FILE or stdin, e.g.
#   ./deepseek.sh raw chat/completions body.json  # (a short literal '{...}' still works)
# Bodies always reach curl on stdin, never as an argument: Linux refuses any one
# argument over 128 KiB, and a resent conversation passes that quickly.
set -euo pipefail

BASE="${DEEPSEEK_BASE_URL:-https://api.deepseek.com}"
MODEL_DEFAULT="deepseek-v4-pro"

case "${1:-help}" in help|-h|--help) sed -n '2,16p' "$0"; exit 0;; esac

[ -z "${DEEPSEEK_API_KEY:-}" ] && { echo "error: DEEPSEEK_API_KEY not set" >&2; exit 1; }

pretty() { if command -v jq >/dev/null 2>&1; then jq .; else cat; fi; }

post() { # post <endpoint>, JSON body on stdin
  curl -sS "${BASE}/$1" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
    --data-binary @-
}

json_string() { # stdin -> one JSON string
  jq -Rs . 2>/dev/null || python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()))'
}

prompt_json() { # prompt_json <prompt|->: "-" reads the prompt from stdin
  if [ "$1" = "-" ]; then json_string; else printf '%s' "$1" | json_string; fi
}

cmd="${1:-help}"; shift || true
case "$cmd" in
  chat)
    thinking='{"type":"enabled"}'
    if [ "${1:-}" = "--think-off" ]; then thinking='{"type":"disabled"}'; shift; fi
    prompt="${1:?usage: deepseek.sh chat [--think-off] <prompt|-> [model]}"
    model="${2:-$MODEL_DEFAULT}"
    { printf '{"model":"%s","thinking":%s,"stream":false,"messages":[{"role":"user","content":' "$model" "$thinking"
      prompt_json "$prompt"
      printf '}]}'; } | post chat/completions | pretty
    ;;
  stream)
    prompt="${1:?usage: deepseek.sh stream <prompt|-> [model]}"
    model="${2:-$MODEL_DEFAULT}"
    { printf '{"model":"%s","stream":true,"messages":[{"role":"user","content":' "$model"
      prompt_json "$prompt"
      printf '}]}'; } | post chat/completions
    ;;
  models)  curl -sS "${BASE}/models" -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" | pretty ;;
  balance) curl -sS "${BASE}/user/balance" -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" | pretty ;;
  raw)
    endpoint="${1:?usage: deepseek.sh raw <endpoint> [FILE|-]}"
    body="${2:--}"
    case "$body" in
      -)   post "$endpoint" ;;
      \{*) printf '%s' "$body" | post "$endpoint" ;;   # a short literal body, as before
      *)   post "$endpoint" < "$body" ;;
    esac | pretty
    ;;
  *) sed -n '2,16p' "$0" ;;
esac
