"""Turn chunking for overlay generation.

Groups conversation turns into chunks for LLM processing, using temporal
proximity and size to find natural boundaries. Never bisects a turn.

The algorithm:
  1. Identify temporal seams — gaps between turns above a threshold
  2. Group turns at those seams into initial chunks
  3. Merge undersized chunks into neighbors (prefer merging forward)
  4. Split oversized chunks at the largest internal temporal gap

This is purely mechanical — no LLM involved. The chunks then go through
a map-reduce pattern: each chunk gets a per-chunk analysis from the LLM
(all hitting the same cached system prompt), then a final synthesis pass
combines them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def _parse_ts(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _turn_size(turn: dict) -> int:
    return len(turn.get("text", ""))


def _chunk_size(turns: list[dict]) -> int:
    return sum(_turn_size(t) for t in turns)


def _largest_gap_index(turns: list[dict]) -> Optional[int]:
    """Find the index of the largest temporal gap within a list of turns.

    Returns the index such that turns[:index] and turns[index:] are the
    split. Returns None if fewer than 2 turns or no parseable timestamps.
    """
    if len(turns) < 2:
        return None

    best_gap = 0
    best_idx = None
    prev_ts = _parse_ts(turns[0].get("timestamp", ""))

    for i in range(1, len(turns)):
        ts = _parse_ts(turns[i].get("timestamp", ""))
        if prev_ts and ts:
            gap = (ts - prev_ts).total_seconds()
            if gap > best_gap:
                best_gap = gap
                best_idx = i
        if ts:
            prev_ts = ts

    return best_idx


def chunk_turns(
    turns: list[dict],
    gap_threshold: float = 120.0,
    min_chunk_chars: int = 2000,
    max_chunk_chars: int = 50000,
) -> list[list[dict]]:
    """Group turns into chunks for overlay processing.

    Args:
        turns: conversation turns, each with 'text', 'role', 'timestamp'
        gap_threshold: seconds of silence that marks a natural seam
        min_chunk_chars: merge chunks smaller than this into neighbors
        max_chunk_chars: split chunks larger than this at internal seams

    Returns:
        list of chunks, each a list of turns. Every turn appears in
        exactly one chunk, in original order.
    """
    if not turns:
        return []

    # Phase 1: split at temporal seams
    raw_chunks = _split_at_seams(turns, gap_threshold)

    # Phase 2: merge undersized chunks
    merged = _merge_small(raw_chunks, min_chunk_chars)

    # Phase 3: split oversized chunks
    result = _split_large(merged, max_chunk_chars)

    return result


def _split_at_seams(turns: list[dict], gap_threshold: float) -> list[list[dict]]:
    """Split turns at temporal gaps above threshold."""
    chunks = []
    current = [turns[0]]
    prev_ts = _parse_ts(turns[0].get("timestamp", ""))

    for turn in turns[1:]:
        ts = _parse_ts(turn.get("timestamp", ""))
        if prev_ts and ts:
            gap = (ts - prev_ts).total_seconds()
            if gap >= gap_threshold and current:
                chunks.append(current)
                current = []
        current.append(turn)
        if ts:
            prev_ts = ts

    if current:
        chunks.append(current)
    return chunks


def _merge_small(chunks: list[list[dict]], min_chars: int) -> list[list[dict]]:
    """Merge chunks below min_chars into their nearest neighbor.

    Prefers merging forward (into the next chunk) to keep temporal order
    intuitive. Falls back to merging backward if at the end.
    """
    if len(chunks) <= 1:
        return chunks

    merged = []
    i = 0
    while i < len(chunks):
        chunk = chunks[i]
        if _chunk_size(chunk) < min_chars:
            if i + 1 < len(chunks):
                # merge into next
                chunks[i + 1] = chunk + chunks[i + 1]
            elif merged:
                # merge into previous
                merged[-1] = merged[-1] + chunk
            else:
                merged.append(chunk)
        else:
            merged.append(chunk)
        i += 1

    return merged


def _split_large(chunks: list[list[dict]], max_chars: int) -> list[list[dict]]:
    """Split chunks exceeding max_chars at their largest internal gap.

    Recursive: a split chunk may still be oversized and gets split again.
    Stops when no further split is possible (chunk is a single turn, or
    no internal gap exists).
    """
    result = []
    for chunk in chunks:
        if _chunk_size(chunk) <= max_chars or len(chunk) <= 1:
            result.append(chunk)
            continue

        split_idx = _largest_gap_index(chunk)
        if split_idx is None or split_idx == 0:
            # can't split further — single turn or no timestamps
            result.append(chunk)
            continue

        left, right = chunk[:split_idx], chunk[split_idx:]
        # recurse on both halves
        result.extend(_split_large([left], max_chars))
        result.extend(_split_large([right], max_chars))

    return result


def chunk_stats(chunks: list[list[dict]]) -> dict:
    """Return diagnostic stats about a chunking result."""
    sizes = [_chunk_size(c) for c in chunks]
    turn_counts = [len(c) for c in chunks]
    return {
        "num_chunks": len(chunks),
        "total_chars": sum(sizes),
        "total_turns": sum(turn_counts),
        "chunk_sizes": sizes,
        "chunk_turns": turn_counts,
        "min_chunk": min(sizes) if sizes else 0,
        "max_chunk": max(sizes) if sizes else 0,
        "mean_chunk": sum(sizes) // len(sizes) if sizes else 0,
    }
