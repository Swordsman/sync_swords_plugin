"""LLM adapter for littlewing semantic overlays.

Provides a single `complete()` function that routes through litellm when
available, falling back to direct OpenAI-compatible HTTP for providers
whose API keys are injected by the environment (e.g. DeepSeek via proxy).

Design principles:
  - litellm is optional. When absent, direct HTTP works for any
    OpenAI-compatible endpoint.
  - Model selection via LITTLEWING_MODEL env var, defaulting to
    deepseek/deepseek-v4-pro.
  - No API keys in code. Keys come from env vars or proxy injection.
  - Fail loudly on LLM calls (callers handle graceful degradation).
  - Stateless — no conversation memory, no retry loops.
  - Never specify max_tokens — let the model use its full capacity.
  - Prompts structured for cache hits: stable system message prefix,
    variable content in user message.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Optional

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"

PROVIDERS = {
    "deepseek": ("https://api.deepseek.com/v1", "DEEPSEEK_API_KEY"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY"),
}


def _get_model():
    return os.environ.get("LITTLEWING_MODEL", DEFAULT_MODEL)


def _parse_model(model_str):
    if "/" in model_str:
        provider, model = model_str.split("/", 1)
        return provider, model
    if model_str.startswith("deepseek"):
        return "deepseek", model_str
    if model_str.startswith("gpt") or model_str.startswith("o1") or model_str.startswith("o3"):
        return "openai", model_str
    return "deepseek", model_str


def complete(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.3,
    **kwargs,
) -> str:
    """Send a chat completion request. Returns the assistant message text.

    Never specifies max_tokens — the model uses its full output capacity,
    including thinking/reasoning when available (deepseek-v4-pro).

    Tries litellm first (supports 100+ providers). Falls back to direct
    HTTP for OpenAI-compatible APIs.
    """
    model = model or _get_model()

    # Strip max_tokens if caller accidentally passes it
    kwargs.pop("max_tokens", None)

    try:
        return _complete_litellm(messages, model, temperature, **kwargs)
    except Exception:
        pass

    return _complete_http(messages, model, temperature)


def _complete_litellm(messages, model, temperature, **kwargs):
    import litellm
    response = litellm.completion(
        model=model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    return response.choices[0].message.content


def _complete_http(messages, model, temperature):
    provider, model_name = _parse_model(model)

    if provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. "
            f"Known: {', '.join(PROVIDERS)}. Install litellm for others."
        )

    base_url, key_env = PROVIDERS[provider]
    api_key = os.environ.get(key_env, "")

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
    }

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"LLM API error {e.code}: {body}") from e

    return result["choices"][0]["message"]["content"]


def available() -> bool:
    """Check whether any LLM backend is reachable."""
    try:
        import litellm  # noqa: F401
        return True
    except Exception:
        pass

    model = _get_model()
    provider, _ = _parse_model(model)
    if provider in PROVIDERS:
        _, key_env = PROVIDERS[provider]
        if os.environ.get(key_env):
            return True
        if os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy"):
            return True
    return False
