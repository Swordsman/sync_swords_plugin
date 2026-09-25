#!/usr/bin/env python3
"""Generate a self-contained HTML session visualization.

Extracts token usage data from a session JSONL and produces an interactive
timeline chart showing token costs over time, with cache breakdowns.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "raw"


def parse_ts(ts_str):
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def extract_turns(jsonl_path):
    """Extract per-API-call turns with usage and content type info."""
    turns = []
    seen_usage = set()

    with open(jsonl_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue

            etype = ev.get("type")
            ts = ev.get("timestamp", "")
            msg = ev.get("message", {})
            usage = msg.get("usage")

            if etype == "user":
                content = msg.get("content", "")
                text_len = len(content) if isinstance(content, str) else sum(
                    len(b.get("text", "")) for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                turns.append({
                    "ts": ts,
                    "type": "user",
                    "text_len": text_len,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cache_create": 0,
                    "cache_read": 0,
                    "thinking_tokens": 0,
                })
                continue

            if etype != "assistant" or not usage:
                continue

            # Deduplicate: same API call emits multiple events (one per block)
            usage_key = (
                ts,
                usage.get("input_tokens", 0),
                usage.get("output_tokens", 0),
                usage.get("cache_creation_input_tokens", 0),
                usage.get("cache_read_input_tokens", 0),
            )
            if usage_key in seen_usage:
                # Accumulate block types for this turn
                content = msg.get("content", [])
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            bt = block.get("type", "")
                            for t in turns:
                                if t.get("_usage_key") == usage_key:
                                    t.setdefault("block_types", []).append(bt)
                                    break
                continue
            seen_usage.add(usage_key)

            content = msg.get("content", [])
            block_types = []
            if isinstance(content, list):
                block_types = [
                    b.get("type", "?") if isinstance(b, dict) else "str"
                    for b in content
                ]

            thinking = usage.get("output_tokens_details", {}).get("thinking_tokens", 0)

            turns.append({
                "ts": ts,
                "type": "assistant",
                "block_types": block_types,
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_create": usage.get("cache_creation_input_tokens", 0),
                "cache_read": usage.get("cache_read_input_tokens", 0),
                "thinking_tokens": thinking,
                "_usage_key": usage_key,
            })

    # Clean internal keys
    for t in turns:
        t.pop("_usage_key", None)

    return turns


def classify_turn(turn):
    """Classify an assistant turn by its dominant content."""
    btypes = turn.get("block_types", [])
    if not btypes:
        return "assistant"
    has_tool = "tool_use" in btypes
    has_text = "text" in btypes
    has_thinking = "thinking" in btypes
    if has_thinking and not has_text and not has_tool:
        return "thinking"
    if has_tool and not has_text:
        return "tool_call"
    if has_tool and has_text:
        return "assistant_tool"
    return "assistant"


def generate_html(turns, session_id, project):
    """Generate self-contained HTML visualization."""
    # Compute chart data
    chart_data = []
    total_input = 0
    total_output = 0
    total_cache_read = 0
    total_cache_create = 0

    for turn in turns:
        ts = turn["ts"]
        ttype = turn["type"]
        if ttype == "assistant":
            ttype = classify_turn(turn)

        inp = turn.get("input_tokens", 0)
        out = turn.get("output_tokens", 0)
        cc = turn.get("cache_create", 0)
        cr = turn.get("cache_read", 0)
        thinking = turn.get("thinking_tokens", 0)

        total_input += inp + cc + cr
        total_output += out
        total_cache_read += cr
        total_cache_create += cc

        chart_data.append({
            "ts": ts,
            "type": ttype,
            "input": inp,
            "output": out,
            "cache_create": cc,
            "cache_read": cr,
            "thinking": thinking,
            "total_context": inp + cc + cr,
        })

    data_json = json.dumps(chart_data)
    total_tokens = total_input + total_output

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Session {session_id[:8]} — {project}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: system-ui, -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }}
h1 {{ font-size: 1.2em; margin-bottom: 4px; color: #f0f6fc; }}
.meta {{ font-size: 0.85em; color: #8b949e; margin-bottom: 16px; }}
.stats {{ display: flex; gap: 24px; margin-bottom: 20px; flex-wrap: wrap; }}
.stat {{ background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 12px 16px; min-width: 140px; }}
.stat-value {{ font-size: 1.4em; font-weight: 600; color: #f0f6fc; }}
.stat-label {{ font-size: 0.75em; color: #8b949e; margin-top: 2px; }}
.chart-container {{ position: relative; background: #161b22; border: 1px solid #30363d; border-radius: 6px; padding: 16px; overflow-x: auto; }}
canvas {{ display: block; }}
.legend {{ display: flex; gap: 16px; margin-top: 12px; flex-wrap: wrap; }}
.legend-item {{ display: flex; align-items: center; gap: 6px; font-size: 0.8em; }}
.legend-swatch {{ width: 14px; height: 14px; border-radius: 3px; flex-shrink: 0; }}
.tooltip {{
  display: none; position: fixed; background: #1c2128; border: 1px solid #444c56;
  border-radius: 6px; padding: 10px 14px; font-size: 0.8em; pointer-events: none;
  z-index: 100; max-width: 280px; box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}}
.tooltip.visible {{ display: block; }}
.tooltip-row {{ display: flex; justify-content: space-between; gap: 12px; }}
.tooltip-label {{ color: #8b949e; }}
.tooltip-value {{ color: #f0f6fc; font-weight: 500; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<h1>Session {session_id[:8]}</h1>
<div class="meta">{project} &middot; {len(chart_data)} API turns</div>

<div class="stats">
  <div class="stat">
    <div class="stat-value" id="total-tokens">{total_tokens:,}</div>
    <div class="stat-label">Total tokens</div>
  </div>
  <div class="stat">
    <div class="stat-value" id="total-input">{total_input:,}</div>
    <div class="stat-label">Input (inc. cache)</div>
  </div>
  <div class="stat">
    <div class="stat-value" id="total-output">{total_output:,}</div>
    <div class="stat-label">Output</div>
  </div>
  <div class="stat">
    <div class="stat-value">{total_cache_read:,}</div>
    <div class="stat-label">Cache read</div>
  </div>
  <div class="stat">
    <div class="stat-value">{total_cache_create:,}</div>
    <div class="stat-label">Cache created</div>
  </div>
</div>

<div class="chart-container">
  <canvas id="chart"></canvas>
  <div class="legend">
    <div class="legend-item"><div class="legend-swatch" style="background:#7c3aed"></div>Cache created</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#7c3aed80"></div>Cache read</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#2563eb"></div>New input</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#059669"></div>Output</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#d97706"></div>Thinking</div>
    <div class="legend-item"><div class="legend-swatch" style="background:#dc2626;opacity:0.6"></div>User turn</div>
  </div>
</div>

<div class="tooltip" id="tooltip"></div>

<script>
const DATA = {data_json};

const COLORS = {{
  user: '#dc262699',
  assistant: '#2563eb',
  thinking: '#d97706',
  tool_call: '#0891b2',
  assistant_tool: '#6366f1',
  cache_create: '#7c3aed',
  cache_read: '#7c3aed80',
  output: '#059669',
  thinking_out: '#d97706',
  input_new: '#2563eb',
}};

const canvas = document.getElementById('chart');
const ctx = canvas.getContext('2d');
const tooltip = document.getElementById('tooltip');

const DPR = window.devicePixelRatio || 1;
const BAR_GAP = 2;
const MARGIN = {{ top: 30, right: 20, bottom: 60, left: 70 }};

function fmt(n) {{ return n.toLocaleString(); }}

function drawChart() {{
  const containerWidth = canvas.parentElement.clientWidth - 32;
  const barWidth = Math.max(4, Math.min(20, (containerWidth - MARGIN.left - MARGIN.right) / DATA.length - BAR_GAP));
  const chartWidth = MARGIN.left + MARGIN.right + DATA.length * (barWidth + BAR_GAP);
  const chartHeight = 400;

  canvas.style.width = Math.max(containerWidth, chartWidth) + 'px';
  canvas.style.height = chartHeight + 'px';
  canvas.width = Math.max(containerWidth, chartWidth) * DPR;
  canvas.height = chartHeight * DPR;
  ctx.scale(DPR, DPR);

  const plotW = Math.max(containerWidth, chartWidth) - MARGIN.left - MARGIN.right;
  const plotH = chartHeight - MARGIN.top - MARGIN.bottom;

  // Find max height (stacked: cache_create + cache_read + input + output + thinking)
  let maxH = 0;
  for (const d of DATA) {{
    const h = d.cache_create + d.cache_read + d.input + d.output + d.thinking;
    if (h > maxH) maxH = h;
  }}
  if (maxH === 0) maxH = 1;

  const scaleY = plotH / maxH;

  // Background
  ctx.fillStyle = '#161b22';
  ctx.fillRect(0, 0, canvas.width / DPR, canvas.height / DPR);

  // Y axis grid
  ctx.strokeStyle = '#21262d';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#8b949e';
  ctx.font = '11px system-ui';
  ctx.textAlign = 'right';
  const yTicks = 5;
  for (let i = 0; i <= yTicks; i++) {{
    const val = Math.round(maxH * i / yTicks);
    const y = MARGIN.top + plotH - (val * scaleY);
    ctx.beginPath();
    ctx.moveTo(MARGIN.left, y);
    ctx.lineTo(MARGIN.left + plotW, y);
    ctx.stroke();
    let label = val >= 1000 ? (val / 1000).toFixed(val >= 10000 ? 0 : 1) + 'k' : val.toString();
    ctx.fillText(label, MARGIN.left - 8, y + 4);
  }}

  // Y axis label
  ctx.save();
  ctx.translate(14, MARGIN.top + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillStyle = '#8b949e';
  ctx.font = '12px system-ui';
  ctx.fillText('Tokens', 0, 0);
  ctx.restore();

  // Bars
  const barRects = [];
  for (let i = 0; i < DATA.length; i++) {{
    const d = DATA[i];
    const x = MARGIN.left + i * (barWidth + BAR_GAP);
    let y = MARGIN.top + plotH;

    const segments = [];
    if (d.type === 'user') {{
      segments.push({{ h: 200, color: COLORS.user, label: 'User input' }});
    }} else {{
      if (d.cache_read > 0) segments.push({{ h: d.cache_read, color: COLORS.cache_read, label: 'Cache read' }});
      if (d.cache_create > 0) segments.push({{ h: d.cache_create, color: COLORS.cache_create, label: 'Cache created' }});
      if (d.input > 0) segments.push({{ h: d.input, color: COLORS.input_new, label: 'New input' }});
      if (d.thinking > 0) segments.push({{ h: d.thinking, color: COLORS.thinking_out, label: 'Thinking' }});
      if (d.output - d.thinking > 0) segments.push({{ h: d.output - d.thinking, color: COLORS.output, label: 'Output' }});
    }}

    const rects = [];
    for (const seg of segments) {{
      const sh = seg.h * scaleY;
      y -= sh;
      ctx.fillStyle = seg.color;
      ctx.fillRect(x, y, barWidth, sh);
      rects.push({{ x, y: y, w: barWidth, h: sh, ...seg }});
    }}

    barRects.push({{ x, rects, data: d, idx: i }});
  }}

  // X axis: time labels (sparse)
  ctx.fillStyle = '#8b949e';
  ctx.font = '10px system-ui';
  ctx.textAlign = 'center';
  const labelEvery = Math.max(1, Math.floor(DATA.length / 15));
  for (let i = 0; i < DATA.length; i += labelEvery) {{
    const d = DATA[i];
    if (!d.ts) continue;
    const x = MARGIN.left + i * (barWidth + BAR_GAP) + barWidth / 2;
    const time = d.ts.slice(11, 19);
    ctx.save();
    ctx.translate(x, MARGIN.top + plotH + 12);
    ctx.rotate(Math.PI / 4);
    ctx.fillText(time, 0, 0);
    ctx.restore();
  }}

  // Tooltip on hover
  canvas.onmousemove = function(e) {{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    let hit = null;
    for (const br of barRects) {{
      if (mx >= br.x && mx <= br.x + barWidth) {{
        hit = br;
        break;
      }}
    }}
    if (hit) {{
      const d = hit.data;
      let html = '<div class="tooltip-row"><span class="tooltip-label">Turn</span><span class="tooltip-value">#' + (hit.idx + 1) + ' (' + d.type + ')</span></div>';
      html += '<div class="tooltip-row"><span class="tooltip-label">Time</span><span class="tooltip-value">' + (d.ts || '').slice(11, 19) + '</span></div>';
      if (d.type !== 'user') {{
        html += '<div class="tooltip-row"><span class="tooltip-label">Cache read</span><span class="tooltip-value">' + fmt(d.cache_read) + '</span></div>';
        html += '<div class="tooltip-row"><span class="tooltip-label">Cache create</span><span class="tooltip-value">' + fmt(d.cache_create) + '</span></div>';
        html += '<div class="tooltip-row"><span class="tooltip-label">New input</span><span class="tooltip-value">' + fmt(d.input) + '</span></div>';
        html += '<div class="tooltip-row"><span class="tooltip-label">Output</span><span class="tooltip-value">' + fmt(d.output) + '</span></div>';
        if (d.thinking > 0) html += '<div class="tooltip-row"><span class="tooltip-label">Thinking</span><span class="tooltip-value">' + fmt(d.thinking) + '</span></div>';
        html += '<div class="tooltip-row"><span class="tooltip-label">Total context</span><span class="tooltip-value">' + fmt(d.total_context) + '</span></div>';
      }}
      tooltip.innerHTML = html;
      tooltip.classList.add('visible');
      tooltip.style.left = (e.clientX + 16) + 'px';
      tooltip.style.top = (e.clientY - 10) + 'px';
    }} else {{
      tooltip.classList.remove('visible');
    }}
  }};
  canvas.onmouseleave = function() {{ tooltip.classList.remove('visible'); }};
}}

drawChart();
window.addEventListener('resize', drawChart);
</script>
</body>
</html>"""


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate session visualization")
    parser.add_argument("session_id", help="Session UUID or prefix")
    parser.add_argument("--project", help="Project name")
    parser.add_argument("--output", "-o", help="Output HTML file (default: stdout)")
    args = parser.parse_args()

    # Find the session
    session_id = args.session_id
    raw_file = None
    project = None

    search_dirs = [RAW_DIR / args.project] if args.project else sorted(RAW_DIR.iterdir())
    candidates = []
    for proj_dir in search_dirs:
        if not proj_dir.is_dir():
            continue
        for jsonl in proj_dir.glob("*.jsonl"):
            if jsonl.stem == session_id or jsonl.stem.startswith(session_id):
                candidates.append((jsonl, proj_dir.name))

    if len(candidates) == 0:
        print(f"Session '{session_id}' not found.", file=sys.stderr)
        return 1
    if len(candidates) > 1:
        print(f"Ambiguous prefix '{session_id}':", file=sys.stderr)
        for c, p in candidates:
            print(f"  {p}/{c.stem}", file=sys.stderr)
        return 1

    raw_file, project = candidates[0]
    turns = extract_turns(raw_file)

    if not turns:
        print("No turns found in session.", file=sys.stderr)
        return 1

    html = generate_html(turns, raw_file.stem, project)

    if args.output:
        Path(args.output).write_text(html)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(html)

    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
