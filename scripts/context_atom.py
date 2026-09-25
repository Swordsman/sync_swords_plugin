#!/usr/bin/env python3
"""
ContextAtom -- Multi-tier knowledge objects with procedural assembly.

Implements the tier taxonomy from CONTEXT_ATOM_TIERS.md:
    extended -> full -> midhigh -> mid -> midlow -> low -> mini -> micro
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


TIERS = ["extended", "full", "midhigh", "mid", "midlow", "low", "mini", "micro"]
TIER_INDEX = {t: i for i, t in enumerate(TIERS)}

# Default token budgets per tier (approximate, for planning)
DEFAULT_TIER_BUDGETS = {
    "extended": 3500,
    "full": 1500,
    "midhigh": 750,
    "mid": 375,
    "midlow": 175,
    "low": 75,
    "mini": 35,
    "micro": 10,
}


def compress_tier(tier: str, levels: int = 1) -> str:
    """Move a tier N levels toward micro."""
    idx = TIER_INDEX[tier]
    new_idx = min(len(TIERS) - 1, idx + levels)
    return TIERS[new_idx]


def expand_tier(tier: str, levels: int = 1) -> str:
    """Move a tier N levels toward extended."""
    idx = TIER_INDEX[tier]
    new_idx = max(0, idx - levels)
    return TIERS[new_idx]


@dataclass
class ContextAtom:
    """
    A knowledge object with intrinsic multi-tier compression.

    Fields:
        atom_id: unique identifier
        forms: dict mapping tier name to content string
        tags: searchable tags
        dependencies: atom_ids this atom depends on
        importance: 0-100 (resistance to compression)
        relevance_score: dynamic, set by assembler
        selected_tier: dynamic, set by assembler
    """

    atom_id: str
    forms: Dict[str, str] = field(default_factory=dict)
    tags: Set[str] = field(default_factory=set)
    dependencies: Set[str] = field(default_factory=set)
    importance: int = 50
    relevance_score: float = 0.0
    selected_tier: Optional[str] = None

    def get_content(self, tier: Optional[str] = None, focal_query: Optional[str] = None) -> str:
        """Return content at the requested tier, falling back to available forms."""
        target = tier or self.selected_tier or "extended"
        content = self._resolve_tier(target)
        if focal_query and target in ("micro", "focal-micro"):
            content = self._apply_focal(content, focal_query)
        return content

    def _resolve_tier(self, target: str) -> str:
        if target in self.forms:
            return self.forms[target]
        idx = TIER_INDEX[target]
        for delta in range(1, len(TIERS)):
            up = expand_tier(target, delta)
            if up in self.forms:
                return self.forms[up]
            down = compress_tier(target, delta)
            if down in self.forms:
                return self.forms[down]
        return f"[ATOM:{self.atom_id}:NO_CONTENT]"

    def _apply_focal(self, content: str, query: str) -> str:
        """Extract only the most relevant sentences/lines for the focal query."""
        query_words = set(query.lower().split())
        lines = [line.strip() for line in content.split(".") if line.strip()]
        scored = []
        for line in lines:
            line_lower = line.lower()
            score = sum(2 for qw in query_words if qw in line_lower)
            # Partial/substring matches
            for qw in query_words:
                for word in line_lower.split():
                    if qw != word and (qw in word or word in qw):
                        score += 0.5
            scored.append((score, line))

        scored.sort(reverse=True, key=lambda x: x[0])
        if not scored:
            return content

        best_score = scored[0][0]
        if best_score == 0:
            # No match found, return micro as-is
            return content

        # Keep only lines that are within 50% of the best score
        # and require at least some match
        threshold = max(best_score * 0.5, 1.0)
        relevant = [line for score, line in scored if score >= threshold]

        # If we got everything, be more aggressive: keep top 1-2 lines
        if len(relevant) >= len(lines) - 1 and len(lines) > 2:
            relevant = [line for score, line in scored[:2] if score > 0]

        if not relevant:
            relevant = [scored[0][1]]

        return ". ".join(relevant) + "."

    def cost_at_tier(self, tier: str) -> int:
        """Estimated token cost at a given tier."""
        if tier in self.forms:
            return max(1, len(self.forms[tier]) // 4)
        # Fallback cost
        available = [t for t in TIERS if t in self.forms]
        if available:
            return max(1, len(self.forms[available[0]]) // 4)
        return DEFAULT_TIER_BUDGETS.get(tier, 50)

    def to_dict(self) -> dict:
        return {
            "atom_id": self.atom_id,
            "forms": self.forms,
            "tags": list(self.tags),
            "dependencies": list(self.dependencies),
            "importance": self.importance,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ContextAtom":
        return cls(
            atom_id=d["atom_id"],
            forms=d.get("forms", {}),
            tags=set(d.get("tags", [])),
            dependencies=set(d.get("dependencies", [])),
            importance=d.get("importance", 50),
        )


class ContextAssembler:
    """
    Assembles a context window from a pool of ContextAtoms for a given query.
    """

    def __init__(self, atoms: List[ContextAtom], budget: int = 100_000):
        self.atoms = {a.atom_id: a for a in atoms}
        self.budget = budget

    def score_relevance(self, query: str, atom: ContextAtom) -> float:
        """Simple keyword overlap relevance scorer."""
        query_words = set(query.lower().split())
        score = 0.0

        # Tag overlap
        for tag in atom.tags:
            if any(q in tag.lower() or tag.lower() in q for q in query_words):
                score += 3.0

        # Content overlap at best available tier
        best_tier = next((t for t in TIERS if t in atom.forms), "extended")
        content = atom.forms.get(best_tier, "")
        content_lower = content.lower()
        for qw in query_words:
            if qw in content_lower:
                score += 1.0

        return score

    def assemble(self, query: str, kernel_atom_id: str = "kck") -> List[ContextAtom]:
        """
        Procedurally determine which atoms to load and at what tier.
        Returns atoms in dependency-resolved order.
        """
        # 1. Score relevance
        for atom in self.atoms.values():
            atom.relevance_score = self.score_relevance(query, atom)
            atom.selected_tier = None

        # 2. Sort by relevance * importance (descending)
        sorted_atoms = sorted(
            self.atoms.values(),
            key=lambda a: a.relevance_score * a.importance,
            reverse=True,
        )

        remaining = self.budget
        selected: Dict[str, ContextAtom] = {}

        # 3. Always include kernel at minimum viable tier
        if kernel_atom_id in self.atoms:
            kck = self.atoms[kernel_atom_id]
            # Try to fit low tier, fall back to mini/micro
            for tier in ["low", "mini", "micro"]:
                cost = kck.cost_at_tier(tier)
                if cost <= remaining:
                    kck.selected_tier = tier
                    selected[kck.atom_id] = kck
                    remaining -= cost
                    break

        # 4. Greedily select atoms and tiers
        for atom in sorted_atoms:
            if atom.atom_id == kernel_atom_id:
                continue
            if atom.atom_id in selected:
                continue

            # Determine base tier based on relevance
            if atom.relevance_score > 8.0:
                base_tier = "extended"
            elif atom.relevance_score > 5.0:
                base_tier = "full"
            elif atom.relevance_score > 2.0:
                base_tier = "midhigh"
            elif atom.relevance_score > 0.5:
                base_tier = "mid"
            else:
                base_tier = "micro"

            # Start from best tier and compress until it fits
            start_idx = TIER_INDEX[base_tier]
            for idx in range(start_idx, len(TIERS)):
                tier = TIERS[idx]
                cost = atom.cost_at_tier(tier)
                if cost <= remaining:
                    atom.selected_tier = tier
                    selected[atom.atom_id] = atom
                    remaining -= cost
                    break

        # 5. Resolve dependencies (pull in anything selected atoms need)
        queue = list(selected.values())
        visited = set(selected.keys())
        idx = 0
        while idx < len(queue):
            atom = queue[idx]
            idx += 1
            for dep_id in atom.dependencies:
                if dep_id in visited or dep_id not in self.atoms:
                    continue
                dep = self.atoms[dep_id]
                # Load dependency at same tier or lower
                dep_target = atom.selected_tier or "micro"
                dep_idx = TIER_INDEX.get(dep_target, len(TIERS) - 1)
                for try_idx in range(dep_idx, len(TIERS)):
                    tier = TIERS[try_idx]
                    cost = dep.cost_at_tier(tier)
                    if cost <= remaining:
                        dep.selected_tier = tier
                        selected[dep_id] = dep
                        visited.add(dep_id)
                        queue.append(dep)
                        remaining -= cost
                        break

        # 6. Topological sort: kernel first, then by dependency depth, then by relevance
        def sort_key(a: ContextAtom) -> tuple:
            is_kernel = 0 if a.atom_id == kernel_atom_id else 1
            dep_depth = self._dep_depth(a.atom_id, visited)
            relevance = -(a.relevance_score * a.importance)
            return (is_kernel, dep_depth, relevance)

        ordered = sorted(selected.values(), key=sort_key)
        return ordered

    def _dep_depth(self, atom_id: str, available: Set[str], memo: Dict[str, int] = None) -> int:
        if memo is None:
            memo = {}
        if atom_id in memo:
            return memo[atom_id]
        atom = self.atoms.get(atom_id)
        if not atom:
            return 0
        deps = [d for d in atom.dependencies if d in available]
        if not deps:
            memo[atom_id] = 0
            return 0
        depth = 1 + max(self._dep_depth(d, available, memo) for d in deps)
        memo[atom_id] = depth
        return depth

    def render(self, atoms: List[ContextAtom], focal_query: Optional[str] = None) -> str:
        """Render selected atoms into a single context string."""
        parts = []
        for atom in atoms:
            content = atom.get_content(focal_query=focal_query)
            parts.append(f"<!-- ATOM: {atom.atom_id} | TIER: {atom.selected_tier} | REL: {atom.relevance_score:.1f} -->")
            parts.append(content)
            parts.append("")
        return "\n".join(parts)


def load_atoms_from_kck(kck_path: Path) -> List[ContextAtom]:
    """
    Parse KIMI_CONTEXT_KERNEL.md into a single ContextAtom with all tiers.
    """
    text = kck_path.read_text(encoding="utf-8")
    forms = {}
    current_tier = None
    current_lines = []

    for line in text.splitlines():
        if line.startswith("## [TIER: "):
            if current_tier and current_lines:
                forms[current_tier] = "\n".join(current_lines).strip()
            current_tier = line.split(":")[1].split("]")[0].strip()
            current_lines = []
        elif current_tier is not None:
            current_lines.append(line)

    if current_tier and current_lines:
        forms[current_tier] = "\n".join(current_lines).strip()

    return [
        ContextAtom(
            atom_id="kck",
            forms=forms,
            tags={"kernel", "bios", "context-management"},
            importance=100,  # Never evict
        )
    ]


def demo():
    """Demonstrate the ContextAtom + Assembler system."""
    kck_path = Path("../../KIMI_CONTEXT_KERNEL.md")
    if kck_path.exists():
        atoms = load_atoms_from_kck(kck_path)
    else:
        atoms = []

    # Add demo atoms to show multi-atom assembly
    atoms.extend([
        ContextAtom(
            atom_id="robody",
            forms={
                "extended": "Robody is an object-oriented agentic containment system. The LLM is the pilot; the robody is the protective shell. Key innovation: class-level _bus is heap memory shared across all agents. The orchestrator controls each agent's VIEW of the shared state.",
                "mid": "Robody: Python shell for LLM agents. Shared bus + view filters. Class-level heap memory.",
                "micro": "Robody: LLM spacesuit",
            },
            tags={"robody", "architecture"},
            dependencies={"kck"},
            importance=80,
        ),
        ContextAtom(
            atom_id="robody_memory",
            forms={
                "extended": "Robody Memory Subsystem provides three tiers: public (all agents), shared (group-scoped), and private (per-agent). MemoryPool manages segments with priority, size_tokens, and auto-eviction. MemoryManager coordinates migration between tiers.",
                "mid": "Robody memory: public/shared/private tiers. Budget tracking, eviction, migration.",
                "micro": "Robody: 3-tier memory",
            },
            tags={"robody", "memory", "architecture"},
            dependencies={"kck", "robody"},
            importance=75,
        ),
        ContextAtom(
            atom_id="sper",
            forms={
                "extended": "SPER (Sorted Profile Embedding Representation) decomposes embedding vectors into permutation (semantic fingerprint), profile curve (energy distribution), and zero set (sparsity mask). Plateaus in the sorted profile are discovered feature clusters without any training.",
                "mid": "SPER: sort embedding dims -> permutation + profile + zeros. Plateaus = feature clusters.",
                "micro": "SPER: sorted profile decomposition",
            },
            tags={"sper", "research", "bitnet"},
            dependencies={"kck"},
            importance=85,
        ),
        ContextAtom(
            atom_id="bitnet",
            forms={
                "extended": "BitNet b1.58 is Microsoft's 1-bit LLM with natively trained ternary weights {-1, 0, +1} and ReLU^2 activations. Not post-training quantization. SPER analysis on BitNet activations is the path to procedural .exe extraction.",
                "mid": "BitNet: ternary weights {-1,0,+1}, ReLU^2, natively trained. Target for SPER decompilation.",
                "micro": "BitNet: 1-bit LLM",
            },
            tags={"bitnet", "sper", "research"},
            dependencies={"kck", "sper"},
            importance=70,
        ),
        ContextAtom(
            atom_id="dog_walk",
            forms={
                "extended": "I went for a walk to take the dog out to do #2. I got the mail. I saw the neighbors. I waved and said hi. The dog barked at them. I turned around and tripped over the sidewalk. I brought the dog back inside and shut the door and took off the leash and fed the dog.",
                "mid": "walked dog. got mail. saw neighbor. dog barked. tripped on sidewalk. went home. fed dog.",
                "micro": "walked dog. got mail. saw neighbor. tripped. went home. fed dog.",
            },
            tags={"example", "compression"},
            dependencies={"kck"},
            importance=30,
        ),
    ])

    assembler = ContextAssembler(atoms, budget=1200)

    print("=" * 60)
    print("QUERY: 'robody memory bus'")
    print("=" * 60)
    result = assembler.assemble("robody memory bus")
    total_cost = sum(a.cost_at_tier(a.selected_tier) for a in result)
    print(f"Assembly: {len(result)} atoms | Total cost: ~{total_cost} tokens")
    for atom in result:
        print(f"\n>>> ATOM: {atom.atom_id} | TIER: {atom.selected_tier} | REL: {atom.relevance_score:.1f} | COST: ~{atom.cost_at_tier(atom.selected_tier)} tokens")
        try:
            print(atom.get_content()[:250] + "...")
        except UnicodeEncodeError:
            print(atom.get_content()[:250].encode('ascii', 'replace').decode('ascii') + "...")

    print("\n" + "=" * 60)
    print("QUERY: 'SPER validation'")
    print("=" * 60)
    assembler2 = ContextAssembler(atoms, budget=1200)
    result = assembler2.assemble("SPER validation")
    total_cost = sum(a.cost_at_tier(a.selected_tier) for a in result)
    print(f"Assembly: {len(result)} atoms | Total cost: ~{total_cost} tokens")
    for atom in result:
        print(f"\n>>> ATOM: {atom.atom_id} | TIER: {atom.selected_tier} | REL: {atom.relevance_score:.1f} | COST: ~{atom.cost_at_tier(atom.selected_tier)} tokens")
        try:
            print(atom.get_content()[:250] + "...")
        except UnicodeEncodeError:
            print(atom.get_content()[:250].encode('ascii', 'replace').decode('ascii') + "...")

    print("\n" + "=" * 60)
    print("FOCAL-MICRO DEMONSTRATION")
    print("=" * 60)
    dog = next(a for a in atoms if a.atom_id == "dog_walk")
    print(f"\nDog walk atom (micro): {dog.get_content('micro')}")
    print(f"Focal-micro (query='mail'): {dog.get_content('micro', focal_query='mail')}")
    print(f"Focal-micro (query='dog'): {dog.get_content('micro', focal_query='dog')}")
    print(f"Focal-micro (query='accident'): {dog.get_content('micro', focal_query='accident')}")
    print(f"Focal-micro (query='neighbor'): {dog.get_content('micro', focal_query='neighbor')}")


if __name__ == "__main__":
    demo()
