#!/usr/bin/env python3
"""
Robody Memory Subsystem — Tiered Context Management

Memory tiers:
    PUBLIC  — class-level, every agent sees it (kernel memory)
    SHARED  — class-level, scoped by group/tag (shared segments)
    PRIVATE — instance-level, only the owning agent (process memory)

Each tier is a MemoryPool containing MemorySegments.
Segments carry priority metadata so the system can evict intelligently
under context pressure.

Design for extensibility:
    - Eviction policy is a callable (swap in your own later)
    - Tiers can be added at runtime (just create a new shared pool)
    - Budget per agent can differ (heterogeneous model context windows)
    - Segment migration between tiers is a first-class operation
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

log = logging.getLogger("robody.memory")


# ---------------------------------------------------------------------------
# MemorySegment — the unit of managed memory
# ---------------------------------------------------------------------------

@dataclass
class MemorySegment:
    """
    A single chunk of memory with metadata for management.

    This is the "page" in our virtual memory system.
    Content can be anything — text, dicts, lists, structured data.
    size_tokens is an estimate used for budget accounting.
    """
    key: str
    content: Any
    priority: int = 50              # 0=garbage, 100=critical. default=medium
    size_tokens: int = 0            # estimated token cost (0 = auto-estimate)
    tier: str = "private"           # "public", "shared", "private"
    origin_agent: str = ""          # who created this
    tags: Set[str] = field(default_factory=set)

    # Managed automatically by the pool
    created_at: str = ""
    last_accessed: str = ""
    access_count: int = 0
    evictable: bool = True          # False = pinned, never evict
    _cached_from: str = ""          # if this was offloaded from another tier

    def __post_init__(self):
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.last_accessed:
            self.last_accessed = now
        if self.size_tokens == 0:
            self.size_tokens = self._estimate_tokens()

    def _estimate_tokens(self) -> int:
        """Rough token estimate. ~4 chars per token for English."""
        if isinstance(self.content, str):
            return max(1, len(self.content) // 4)
        serialized = json.dumps(self.content, default=str)
        return max(1, len(serialized) // 4)

    def touch(self):
        """Mark as recently accessed."""
        self.last_accessed = datetime.now().isoformat()
        self.access_count += 1

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "priority": self.priority,
            "size_tokens": self.size_tokens,
            "tier": self.tier,
            "origin_agent": self.origin_agent,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "access_count": self.access_count,
            "evictable": self.evictable,
            "_cached_from": self._cached_from,
        }


# ---------------------------------------------------------------------------
# Eviction policies (swappable)
# ---------------------------------------------------------------------------

def evict_lowest_priority(segments: Dict[str, MemorySegment],
                          target_reduction: int) -> List[str]:
    """
    Default eviction policy: evict lowest-priority evictable segments
    until we've freed at least target_reduction tokens.

    Returns list of keys to evict.
    """
    candidates = [
        s for s in segments.values()
        if s.evictable
    ]
    # Sort: lowest priority first, then least-recently-accessed
    candidates.sort(key=lambda s: (s.priority, s.last_accessed))

    to_evict = []
    freed = 0
    for seg in candidates:
        if freed >= target_reduction:
            break
        to_evict.append(seg.key)
        freed += seg.size_tokens
    return to_evict


def evict_lru(segments: Dict[str, MemorySegment],
              target_reduction: int) -> List[str]:
    """LRU eviction — least recently accessed first."""
    candidates = [s for s in segments.values() if s.evictable]
    candidates.sort(key=lambda s: s.last_accessed)

    to_evict = []
    freed = 0
    for seg in candidates:
        if freed >= target_reduction:
            break
        to_evict.append(seg.key)
        freed += seg.size_tokens
    return to_evict


# ---------------------------------------------------------------------------
# MemoryPool — a managed collection of segments
# ---------------------------------------------------------------------------

class MemoryPool:
    """
    A pool of memory segments with budget tracking and eviction.

    Reads/writes go through methods that auto-manage metadata.
    When the pool exceeds its budget, the eviction policy runs.

    budget_tokens: soft limit. 0 = unlimited.
    eviction_policy: callable(segments, target_reduction) -> [keys_to_evict]
    on_evict: callback(evicted_segments) — for migration to another tier
    """

    def __init__(
        self,
        name: str,
        budget_tokens: int = 0,
        eviction_policy: Callable = None,
        on_evict: Optional[Callable] = None,
    ):
        self.name = name
        self.budget_tokens = budget_tokens
        self._segments: Dict[str, MemorySegment] = {}
        self._total_tokens: int = 0
        self._eviction_policy = eviction_policy or evict_lowest_priority
        self._on_evict = on_evict

    # --- Properties for self-managing state ---

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def headroom(self) -> int:
        """How many tokens can we add before hitting budget. -1 = unlimited."""
        if self.budget_tokens == 0:
            return -1
        return max(0, self.budget_tokens - self._total_tokens)

    @property
    def pressure(self) -> float:
        """0.0 = empty, 1.0 = at budget, >1.0 = over budget."""
        if self.budget_tokens == 0:
            return 0.0
        return self._total_tokens / self.budget_tokens

    @property
    def segment_count(self) -> int:
        return len(self._segments)

    # --- Core operations ---

    def read(self, key: str, default: Any = None) -> Any:
        """Read a segment's content. Updates access metadata."""
        seg = self._segments.get(key)
        if seg is None:
            return default
        seg.touch()
        return seg.content

    def write(self, key: str, content: Any, *,
              priority: int = 50,
              tags: Set[str] = None,
              origin_agent: str = "",
              evictable: bool = True,
              pinned: bool = False) -> MemorySegment:
        """
        Write a segment. Overwrites if key exists.
        Triggers eviction if over budget after write.
        """
        # Remove old version if exists
        if key in self._segments:
            self._remove(key)

        seg = MemorySegment(
            key=key,
            content=content,
            priority=priority,
            tier=self.name,
            origin_agent=origin_agent,
            tags=tags or set(),
            evictable=evictable and not pinned,
        )
        self._segments[key] = seg
        self._total_tokens += seg.size_tokens

        # Check pressure
        if self.budget_tokens > 0 and self._total_tokens > self.budget_tokens:
            self._run_eviction()

        return seg

    def delete(self, key: str) -> Optional[MemorySegment]:
        """Explicitly remove a segment."""
        return self._remove(key)

    def has(self, key: str) -> bool:
        return key in self._segments

    def keys(self) -> List[str]:
        return list(self._segments.keys())

    def segments(self) -> List[MemorySegment]:
        return list(self._segments.values())

    def get_segment(self, key: str) -> Optional[MemorySegment]:
        """Get the segment object itself (not just content)."""
        return self._segments.get(key)

    def find_by_tag(self, tag: str) -> List[MemorySegment]:
        return [s for s in self._segments.values() if tag in s.tags]

    def find_by_priority(self, min_priority: int = 0,
                         max_priority: int = 100) -> List[MemorySegment]:
        return [
            s for s in self._segments.values()
            if min_priority <= s.priority <= max_priority
        ]

    # --- Eviction ---

    def _remove(self, key: str) -> Optional[MemorySegment]:
        seg = self._segments.pop(key, None)
        if seg:
            self._total_tokens -= seg.size_tokens
        return seg

    def _run_eviction(self):
        """Evict segments until we're under budget."""
        if self.budget_tokens == 0:
            return
        overage = self._total_tokens - self.budget_tokens
        if overage <= 0:
            return

        to_evict = self._eviction_policy(self._segments, overage)
        evicted = []
        for key in to_evict:
            seg = self._remove(key)
            if seg:
                evicted.append(seg)
                log.info("pool %s evicted %s (%d tokens, priority=%d)",
                         self.name, key, seg.size_tokens, seg.priority)

        # Callback for migration (offload to agents, etc.)
        if evicted and self._on_evict:
            self._on_evict(evicted)

    def force_evict(self, target_tokens: int) -> List[MemorySegment]:
        """Manually trigger eviction of N tokens worth of segments."""
        to_evict = self._eviction_policy(self._segments, target_tokens)
        evicted = []
        for key in to_evict:
            seg = self._remove(key)
            if seg:
                evicted.append(seg)
        return evicted

    # --- Bulk operations ---

    def absorb(self, segment: MemorySegment):
        """
        Take in a segment from another pool (migration).
        Preserves metadata, updates tier name.
        """
        segment.tier = self.name
        self._segments[segment.key] = segment
        self._total_tokens += segment.size_tokens

    def dump_stats(self) -> dict:
        return {
            "name": self.name,
            "budget_tokens": self.budget_tokens,
            "total_tokens": self._total_tokens,
            "pressure": round(self.pressure, 3),
            "segment_count": self.segment_count,
            "evictable": sum(1 for s in self._segments.values() if s.evictable),
            "pinned": sum(1 for s in self._segments.values() if not s.evictable),
        }


# ---------------------------------------------------------------------------
# MemoryManager — coordinates tiers across the system
# ---------------------------------------------------------------------------

class MemoryManager:
    """
    Coordinates memory across all tiers and agents.

    Tiers:
        public  — one global pool, everyone reads/writes
        shared  — named pools, scoped by group/purpose
        private — per-agent pools (managed by each Robody instance)

    The manager handles:
        - Creating/destroying shared pools
        - Migration between tiers under pressure
        - Distributing evicted shared memory across agents
        - Reporting on system-wide memory usage
    """

    def __init__(self, default_budget: int = 0):
        self.public = MemoryPool(
            "public",
            budget_tokens=default_budget,
            on_evict=self._handle_public_eviction,
        )
        self._shared_pools: Dict[str, MemoryPool] = {}
        self._default_budget = default_budget

    # --- Shared pool management ---

    def create_shared_pool(self, name: str,
                           budget_tokens: int = 0) -> MemoryPool:
        """Create a named shared pool (e.g., per team, per task group)."""
        pool = MemoryPool(
            f"shared:{name}",
            budget_tokens=budget_tokens or self._default_budget,
            on_evict=self._handle_shared_eviction,
        )
        self._shared_pools[name] = pool
        log.info("shared pool created: %s (budget=%d)", name, pool.budget_tokens)
        return pool

    def get_shared_pool(self, name: str) -> Optional[MemoryPool]:
        return self._shared_pools.get(name)

    def delete_shared_pool(self, name: str):
        self._shared_pools.pop(name, None)

    def list_shared_pools(self) -> List[str]:
        return list(self._shared_pools.keys())

    # --- Migration ---

    def migrate(self, key: str, source: MemoryPool,
                dest: MemoryPool) -> bool:
        """Move a segment from one pool to another."""
        seg = source.delete(key)
        if seg is None:
            return False
        seg._cached_from = source.name
        dest.absorb(seg)
        log.info("migrated %s: %s -> %s", key, source.name, dest.name)
        return True

    def distribute_to_agents(self, segments: List[MemorySegment],
                             agent_pools: List[MemoryPool]):
        """
        Distribute evicted segments across agent private pools.

        Round-robin by headroom — agents with more space get more segments.
        Each segment is tagged so it can be reclaimed later.
        """
        if not agent_pools:
            log.warning("no agent pools to distribute to — segments dropped")
            return

        # Sort agents by headroom (most space first)
        pools = sorted(agent_pools,
                       key=lambda p: p.headroom if p.headroom >= 0 else float("inf"),
                       reverse=True)

        for i, seg in enumerate(segments):
            target = pools[i % len(pools)]
            seg._cached_from = seg.tier
            seg.tags.add("_cached")
            target.absorb(seg)
            log.info("distributed %s to %s (cached from %s)",
                     seg.key, target.name, seg._cached_from)

    def reclaim_cached(self, agent_pool: MemoryPool,
                       dest: MemoryPool) -> int:
        """Pull back segments that were temporarily cached in an agent."""
        cached = [s for s in agent_pool.segments() if "_cached" in s.tags]
        count = 0
        for seg in cached:
            agent_pool.delete(seg.key)
            seg.tags.discard("_cached")
            dest.absorb(seg)
            count += 1
        if count:
            log.info("reclaimed %d segments from %s to %s",
                     count, agent_pool.name, dest.name)
        return count

    # --- Eviction callbacks ---

    def _handle_public_eviction(self, evicted: List[MemorySegment]):
        """When public pool evicts, try to distribute to shared or agents."""
        log.info("public eviction: %d segments need rehoming", len(evicted))
        # Subclass or replace this for custom behavior

    def _handle_shared_eviction(self, evicted: List[MemorySegment]):
        """When a shared pool evicts, try to distribute to agents."""
        log.info("shared eviction: %d segments need rehoming", len(evicted))

    # --- Reporting ---

    def system_stats(self) -> dict:
        stats = {
            "public": self.public.dump_stats(),
            "shared_pools": {
                name: pool.dump_stats()
                for name, pool in self._shared_pools.items()
            },
            "total_managed_tokens": self.public.total_tokens + sum(
                p.total_tokens for p in self._shared_pools.values()
            ),
        }
        return stats


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def demo():
    print("=" * 60)
    print("ROBODY MEMORY SUBSYSTEM DEMO")
    print("=" * 60)

    # --- Create memory manager with budget ---
    mm = MemoryManager(default_budget=1000)  # 1000 tokens per pool

    # --- Public memory ---
    mm.public.write("project", "CastleHeck", priority=100, pinned=True)
    mm.public.write("objectives", ["build knowledge graph", "robody v1"],
                    priority=80, tags={"planning"})
    mm.public.write("api_keys", {"kimi": "sk-xxx"}, priority=90, pinned=True)

    print(f"\nPublic pool: {mm.public.dump_stats()}")
    print(f"Project: {mm.public.read('project')}")

    # --- Shared pool for a team ---
    team_pool = mm.create_shared_pool("extraction_team", budget_tokens=500)
    team_pool.write("batch_config", {"conv_ids": [1, 2, 3, 4, 5]}, priority=70)
    team_pool.write("schema", "Messages -> Phases -> Conversations -> Tags",
                    priority=90, pinned=True)

    print(f"\nTeam pool: {team_pool.dump_stats()}")

    # --- Private pools (simulating agents) ---
    alice_mem = MemoryPool("private:alice", budget_tokens=200)
    bob_mem = MemoryPool("private:bob", budget_tokens=300)

    alice_mem.write("working_conv", "Conversation 42 analysis in progress...",
                    priority=60, origin_agent="alice")
    bob_mem.write("findings", "Found 12 orphaned objectives",
                  priority=70, origin_agent="bob")

    # --- Pressure test: fill public pool past budget ---
    print("\n--- Filling public pool past budget ---")
    for i in range(20):
        mm.public.write(
            f"filler_{i}",
            "x" * 200,  # ~50 tokens each
            priority=10 + i,  # low priority = evicted first
            tags={"filler"},
        )

    print(f"Public after fill: {mm.public.dump_stats()}")
    print(f"Filler segments remaining: {len(mm.public.find_by_tag('filler'))}")
    print(f"Pinned still there: {mm.public.has('project')}, {mm.public.has('api_keys')}")

    # --- Distribute evicted segments to agents ---
    print("\n--- Manual distribution demo ---")
    evicted = team_pool.force_evict(200)
    if evicted:
        mm.distribute_to_agents(evicted, [alice_mem, bob_mem])
        print(f"Alice after distribution: {alice_mem.dump_stats()}")
        print(f"Bob after distribution: {bob_mem.dump_stats()}")

    # --- Reclaim cached segments ---
    reclaimed = mm.reclaim_cached(alice_mem, team_pool)
    print(f"\nReclaimed {reclaimed} segments back to team pool")
    print(f"Alice after reclaim: {alice_mem.dump_stats()}")
    print(f"Team after reclaim: {team_pool.dump_stats()}")

    # --- System-wide stats ---
    print(f"\n--- System Stats ---")
    for k, v in mm.system_stats().items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    demo()
