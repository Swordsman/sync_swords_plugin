---
name: ucf
description: "Universal Context Format. JSONL-based interchange format for converting AI conversation transcripts between providers (Claude, DeepSeek, Kimi, Hermes, Claude Web). Bidirectional adapters preserve provider-specific metadata in a _native field for lossless roundtrips. Cross-format sanitization pipelines handle role alternation, reasoning content, surrogate cleanup, and provider-specific API requirements."
---

# UCF — Universal Context Format

Bidirectional conversion of AI conversation transcripts between provider formats.

## Supported providers

| Provider | Adapter | Roundtrip |
|---|---|---|
| Claude Code | `ucf_adapter_claude.py` | Lossless |
| Claude Web | `ucf_adapter_claudeweb.py` | Lossless |
| DeepSeek | `ucf_adapter_ds.py` | Lossless |
| Kimi | `ucf_adapter_kimi.py` | Lossless |
| Hermes | `ucf_adapter_hermes.py` | Lossless |

## Cross-format sanitization

`ucf_cross_format.py` provides provider-targeted repair pipelines:

- `prepare_for_ds()` — role alternation, reasoning_content padding, content normalization
- `prepare_for_openai()` — strip reasoning fields, thinking-only turn removal
- `prepare_for_anthropic()` — content block arrays, thinking tag stripping
- `prepare_generic()` — minimal structural repairs

Every fix corresponds to a real production 400/empty-response diagnosed in Hermes.

## UCF schema

Messages are JSONL with fields: `v`, `type`, `id`, `parent_id`, `ts`, `data`.
Types: system, checkpoint, user, assistant, tool_result, usage, attachment, meta, branch.
Schema at `${CLAUDE_PLUGIN_ROOT}/scripts/ucf/schema/ucf-schema.json`.

## Usage

```python
from ucf_adapter_claude import claude_to_ucf, ucf_to_claude
from ucf_cross_format import prepare_for_ds

ucf_msgs = claude_to_ucf(claude_jsonl_lines)
ds_ready = prepare_for_ds([ucf_to_ds(m) for m in ucf_msgs])
```

## Scripts

All scripts are in `${CLAUDE_PLUGIN_ROOT}/scripts/ucf/`.
