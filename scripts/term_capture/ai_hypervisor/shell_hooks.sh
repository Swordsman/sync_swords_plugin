#!/bin/bash
# AI Hypervisor shell hooks
# Source this in bash/zsh to enable command interception

_AI_HV_LOG_FILE="${AI_HV_LOG_FILE:-/dev/null}"
_AI_HV_COMMAND_COUNT=0

# Pre-command hook (bash)
_ai_hv_preexec() {
    local cmd="$1"
    _AI_HV_LAST_CMD="$cmd"
    _AI_HV_LAST_TIME=$(date +%s%N)
    
    # Log command start
    if [[ -n "$AI_HV_LOG_FILE" && "$AI_HV_LOG_FILE" != "/dev/null" ]]; then
        echo "{\"event\":\"cmd_start\",\"time\":$_AI_HV_LAST_TIME,\"cmd\":\"$(echo "$cmd" | sed 's/"/\\"/g')\"}" >> "$AI_HV_LOG_FILE" 2>/dev/null
    fi
    
    # Notify hypervisor if socket available
    if [[ -S "${AI_HV_SOCKET}" ]]; then
        echo "CMD:$cmd" | nc -U "${AI_HV_SOCKET}" 2>/dev/null &
    fi
}

# Post-command hook (bash)  
_ai_hv_precmd() {
    local exit_code=$?
    local end_time=$(date +%s%N)
    
    if [[ -n "$_AI_HV_LAST_TIME" ]]; then
        local duration=$(( (end_time - _AI_HV_LAST_TIME) / 1000000 ))  # ms
        
        if [[ -n "$AI_HV_LOG_FILE" && "$AI_HV_LOG_FILE" != "/dev/null" ]]; then
            echo "{\"event\":\"cmd_end\",\"time\":$end_time,\"exit\":$exit_code,\"duration_ms\":$duration}" >> "$AI_HV_LOG_FILE" 2>/dev/null
        fi
    fi
    
    ((AI_HV_COMMAND_COUNT++))
    
    # Check quota
    if [[ -n "$AI_HV_TOKEN_LIMIT" && -n "$AI_HV_TOKEN_USED" ]]; then
        if (( AI_HV_TOKEN_USED > AI_HV_TOKEN_LIMIT )); then
            echo "[AI-HV] Token limit exceeded!" >&2
        fi
    fi
}

# Install hooks based on shell type
if [[ -n "${BASH_VERSION:-}" ]]; then
    # Bash: use DEBUG trap for pre-exec
    trap '_ai_hv_preexec "$BASH_COMMAND"' DEBUG
    # Use PROMPT_COMMAND for post-exec
    PROMPT_COMMAND="_ai_hv_precmd${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
    
elif [[ -n "${ZSH_VERSION:-}" ]]; then
    # Zsh: use preexec/precmd hooks
    preexec_functions+=(_ai_hv_preexec)
    precmd_functions+=(_ai_hv_precmd)
fi

# Export for subshells
export AI_HV_LOG_FILE
export AI_HV_SOCKET
export AI_HV_TOKEN_LIMIT
export AI_HV_TOKEN_USED
