#!/usr/bin/env python3
"""
Robody — Object-Oriented Agentic Containment with Shared Memory Bus

A "spacesuit automaton" that decouples LLM reasoning from environment
manipulation. The LLM is the "pilot" — the robody is the protective shell.

KEY INSIGHT: Class-level state = shared memory bus.
    - cls._bus is heap memory, not context window memory.
    - It doesn't degrade at 150K tokens, doesn't suffer attention loss.
    - All agents read/write to it through their robody interface.
    - The orchestrator controls each agent's VIEW of the shared state.
    - Instance-level state = private per-agent memory.

Architecture:
    ┌─────────────────────────────────────────────────────┐
    │  PYTHON PROCESS (single, async)                     │
    │                                                     │
    │  Robody._bus  ← class-level shared state (THE BUS)  │
    │      │                                              │
    │  ┌───┴───┐  ┌───┴───┐  ┌───┴───┐                   │
    │  │Agent 1│  │Agent 2│  │Agent N│  (Robody instances)│
    │  │ view  │  │ view  │  │ view  │  (filtered lens)   │
    │  └───┬───┘  └───┬───┘  └───┬───┘                   │
    │      │          │          │     async API calls     │
    └──────┼──────────┼──────────┼────────────────────────┘
           ↓          ↓          ↓
        [Kimi]     [Claude]   [Groq/etc]
"""

import asyncio
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set


# ---------------------------------------------------------------------------
# Logging — standard, thread-safe, no print()
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("robody")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ActionRecord:
    """Immutable record of a single robody action."""
    ts: str
    agent_id: str
    action: str
    args_repr: str          # truncated repr of positional args
    kwargs_repr: str        # truncated repr of keyword args
    result_repr: str = ""
    error: str = ""
    elapsed_ms: float = 0.0


@dataclass
class ContextSlice:
    """
    View controller for shared state.

    Not just metadata — this controls what an agent SEES from the bus.
    focal  = the core concept region
    context = surrounding context for understanding
    blind  = stripped entirely (agent never sees it)
    mask   = acknowledged-but-hidden (agent knows something is there)
    """
    name: str
    source_key: str                          # key into _bus["state"]
    focal_start: int
    focal_end: int
    context_start: int = 0
    context_end: int = -1                    # -1 = end of source
    blind: List[tuple] = field(default_factory=list)   # [(start, end), ...]
    mask: List[tuple] = field(default_factory=list)

    def apply(self, text: str) -> str:
        """Apply this slice to source text, returning the filtered view."""
        end = self.context_end if self.context_end != -1 else len(text)
        view = list(text[self.context_start:end])

        offset = self.context_start

        # Apply blinds (remove entirely — shift-aware, process in reverse)
        for b_start, b_end in sorted(self.blind, reverse=True):
            s = b_start - offset
            e = b_end - offset
            if 0 <= s < len(view):
                del view[s:min(e, len(view))]

        # Apply masks (replace with placeholder)
        rebuilt = "".join(view)
        for m_start, m_end in sorted(self.mask, reverse=True):
            s = m_start - offset
            e = m_end - offset
            if 0 <= s < len(rebuilt):
                rebuilt = rebuilt[:s] + "[...masked...]" + rebuilt[min(e, len(rebuilt)):]

        return rebuilt


class Tool(Protocol):
    """Anything the pilot can use. Must be registered explicitly."""
    name: str
    description: str

    def execute(self, *args: Any, **kwargs: Any) -> Any: ...


# ---------------------------------------------------------------------------
# Method interception system
# ---------------------------------------------------------------------------

def _wrap_method(cls, method_name: str, hook: Callable):
    """
    Wrap a method on the CLASS so all instances inherit the hook.

    hook signature: hook(robody_instance, original_fn, *args, **kwargs) -> Any
    The hook decides whether/when to call original_fn.
    """
    original = getattr(cls, method_name)

    def wrapped(self, *args, **kwargs):
        return hook(self, original, *args, **kwargs)

    wrapped.__name__ = method_name
    wrapped.__doc__ = original.__doc__
    wrapped._original = original            # keep a ref for unwrapping
    wrapped._is_hooked = True
    setattr(cls, method_name, wrapped)


def _unwrap_method(cls, method_name: str):
    """Remove a hook, restoring the original method."""
    current = getattr(cls, method_name, None)
    if current and getattr(current, "_is_hooked", False):
        setattr(cls, method_name, current._original)


# ---------------------------------------------------------------------------
# Robody
# ---------------------------------------------------------------------------

class Robody:
    """
    Constrained execution shell for an AI agent.

    Class-level attributes form the SHARED MEMORY BUS.
    Instance-level attributes form the agent's PRIVATE state.

    The pilot (LLM) interacts ONLY through robody methods.
    """

    # ======================================================================
    # CLASS-LEVEL: THE BUS (shared across ALL instances)
    # ======================================================================
    _bus: Dict[str, Any] = {
        "state": {},        # arbitrary shared k/v (the whiteboard)
        "config": {},       # shared configuration
        "signals": [],      # broadcast messages from orchestrator
    }
    _shared_tools: Dict[str, Tool] = {}            # tools available to all
    _registry: Dict[str, "Robody"] = {}            # agent_id -> instance
    _hooks: Dict[str, List[Callable]] = {}         # method_name -> [hooks]
    _action_log: List[ActionRecord] = []           # global audit trail

    # ======================================================================
    # INSTANCE-LEVEL: PRIVATE per-agent
    # ======================================================================

    def __init__(
        self,
        agent_id: str,
        workspace: Path,
        *,
        allowed_roots: Optional[List[Path]] = None,
        view_filter: Optional[Callable] = None,
    ):
        self.agent_id = agent_id
        self.workspace = Path(workspace).resolve()
        self.allowed_roots = [r.resolve() for r in (allowed_roots or [self.workspace])]
        self.workspace.mkdir(parents=True, exist_ok=True)

        # Per-agent private state
        self._local: Dict[str, Any] = {}
        self._local_tools: Dict[str, Tool] = {}
        self._slices: Dict[str, ContextSlice] = {}
        self._view_filter: Optional[Callable] = view_filter
        self._violation_count: int = 0
        self._terminated: bool = False
        self._local_log: List[ActionRecord] = []

        # Register self on the bus
        Robody._registry[agent_id] = self
        log.info("agent %s attached  workspace=%s", agent_id, self.workspace)

    # ------------------------------------------------------------------
    # Safety
    # ------------------------------------------------------------------

    def _validate_path(self, path: str) -> Path:
        """Jail: resolve path, ensure it stays inside allowed roots."""
        resolved = (self.workspace / path).resolve()
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return resolved
            except ValueError:
                continue
        self._violation_count += 1
        msg = f"path escape: {path!r} -> {resolved}"
        log.error("agent %s VIOLATION #%d: %s", self.agent_id, self._violation_count, msg)
        if self._violation_count >= 3:
            self.terminate("too many path violations")
        raise PermissionError(msg)

    def _check_alive(self):
        if self._terminated:
            raise RuntimeError(f"agent {self.agent_id} is terminated")

    def terminate(self, reason: str = ""):
        """Kill switch. Agent cannot perform any further actions."""
        self._terminated = True
        log.warning("agent %s TERMINATED: %s", self.agent_id, reason)
        self._record("TERMINATE", reason=reason)

    # ------------------------------------------------------------------
    # Action recording
    # ------------------------------------------------------------------

    def _record(self, action: str, args: tuple = (), kwargs: dict = None,
                result: Any = None, error: str = "", elapsed_ms: float = 0.0,
                **extra):
        kwargs = kwargs or {}
        rec = ActionRecord(
            ts=datetime.now().isoformat(),
            agent_id=self.agent_id,
            action=action,
            args_repr=repr(args)[:200],
            kwargs_repr=repr(kwargs)[:200],
            result_repr=repr(result)[:200] if result is not None else "",
            error=error,
            elapsed_ms=elapsed_ms,
        )
        self._local_log.append(rec)
        Robody._action_log.append(rec)

    # ------------------------------------------------------------------
    # BUS ACCESS: shared state read/write (the whole point)
    # ------------------------------------------------------------------

    def bus_read(self, key: str, default: Any = None) -> Any:
        """
        Read from the shared bus, filtered through this agent's view.

        If a view_filter is set, the orchestrator controls what the
        agent actually sees.  No filter = full access.
        """
        self._check_alive()
        raw = Robody._bus["state"].get(key, default)
        if self._view_filter and raw is not None:
            raw = self._view_filter(self.agent_id, key, raw)
        self._record("bus_read", args=(key,))
        return raw

    def bus_write(self, key: str, value: Any):
        """Write to the shared bus. All agents see this immediately."""
        self._check_alive()
        Robody._bus["state"][key] = value
        self._record("bus_write", args=(key,), result=repr(value)[:100])
        log.debug("agent %s wrote bus[%s]", self.agent_id, key)

    def bus_keys(self) -> List[str]:
        """List all keys currently on the bus."""
        self._check_alive()
        return list(Robody._bus["state"].keys())

    def bus_read_signal(self) -> Optional[dict]:
        """Pop the oldest unread signal from the orchestrator."""
        self._check_alive()
        if Robody._bus["signals"]:
            return Robody._bus["signals"].pop(0)
        return None

    # ------------------------------------------------------------------
    # LOCAL STATE: private per-agent
    # ------------------------------------------------------------------

    def local_read(self, key: str, default: Any = None) -> Any:
        self._check_alive()
        return self._local.get(key, default)

    def local_write(self, key: str, value: Any):
        self._check_alive()
        self._local[key] = value

    # ------------------------------------------------------------------
    # INSTRUMENT PANEL: filesystem (read)
    # ------------------------------------------------------------------

    def read_file(self, path: str, offset: int = 0, limit: int = 4096) -> str:
        """Read file contents. Truncated to `limit` chars from `offset`."""
        self._check_alive()
        t0 = time.monotonic()
        resolved = self._validate_path(path)
        if not resolved.exists():
            raise FileNotFoundError(path)
        if resolved.stat().st_size > 10_000_000:
            raise ValueError(f"file too large: {resolved.stat().st_size} bytes")
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            content = f.read(limit)
        elapsed = (time.monotonic() - t0) * 1000
        self._record("read_file", args=(path,),
                     kwargs={"offset": offset, "limit": limit},
                     result=f"{len(content)} chars", elapsed_ms=elapsed)
        return content

    def list_dir(self, path: str = ".") -> List[Dict[str, Any]]:
        """List directory contents (sanitized, no hidden files)."""
        self._check_alive()
        resolved = self._validate_path(path)
        entries = []
        for item in sorted(resolved.iterdir()):
            if item.name.startswith("."):
                continue
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        self._record("list_dir", args=(path,), result=f"{len(entries)} entries")
        return entries

    def search_text(self, needle: str, path: str = ".",
                    max_results: int = 20) -> List[Dict]:
        """
        Search files for a substring. No regex — just str.find().
        Returns snippets with surrounding context.
        """
        self._check_alive()
        resolved = self._validate_path(path)
        needle_lower = needle.lower()
        results = []
        for fp in resolved.rglob("*"):
            if not fp.is_file():
                continue
            if fp.stat().st_size > 1_000_000:
                continue
            try:
                text = fp.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue
            pos = text.lower().find(needle_lower)
            if pos == -1:
                continue
            snippet_start = max(0, pos - 120)
            snippet_end = min(len(text), pos + len(needle) + 120)
            results.append({
                "file": str(fp.relative_to(self.workspace)),
                "position": pos,
                "snippet": text[snippet_start:snippet_end],
            })
            if len(results) >= max_results:
                break
        self._record("search_text", args=(needle,),
                     kwargs={"path": path}, result=f"{len(results)} hits")
        return results

    # ------------------------------------------------------------------
    # ACTUATORS: filesystem (write)
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str,
                   mode: str = "write") -> int:
        """
        Write file. Modes: 'write' (overwrite), 'append'.
        Returns bytes written.
        """
        self._check_alive()
        resolved = self._validate_path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        open_mode = "w" if mode == "write" else "a"
        with open(resolved, open_mode, encoding="utf-8") as f:
            n = f.write(content)
        self._record("write_file", args=(path,),
                     kwargs={"mode": mode, "len": len(content)},
                     result=f"{n} chars written")
        return n

    # ------------------------------------------------------------------
    # CONTEXT SLICES: view controllers for the bus
    # ------------------------------------------------------------------

    def create_slice(self, name: str, source_key: str,
                     focal_start: int, focal_end: int,
                     **kwargs) -> ContextSlice:
        """Create a named view into a bus value."""
        self._check_alive()
        s = ContextSlice(
            name=name, source_key=source_key,
            focal_start=focal_start, focal_end=focal_end,
            **kwargs,
        )
        self._slices[name] = s
        self._record("create_slice", args=(name, source_key))
        return s

    def read_slice(self, name: str) -> Optional[str]:
        """Read bus state through a previously created slice."""
        self._check_alive()
        s = self._slices.get(name)
        if s is None:
            return None
        source = Robody._bus["state"].get(s.source_key, "")
        if not isinstance(source, str):
            source = json.dumps(source)
        return s.apply(source)

    def list_slices(self) -> List[str]:
        return list(self._slices.keys())

    # ------------------------------------------------------------------
    # TOOLS: registered capabilities
    # ------------------------------------------------------------------

    def register_tool(self, tool: Tool, *, shared: bool = False):
        """Register a tool. shared=True puts it on the bus for all agents."""
        self._check_alive()
        if shared:
            Robody._shared_tools[tool.name] = tool
            log.info("shared tool registered: %s (by %s)", tool.name, self.agent_id)
        else:
            self._local_tools[tool.name] = tool
            log.info("local tool registered: %s (for %s)", tool.name, self.agent_id)

    def use_tool(self, tool_name: str, *args, **kwargs) -> Any:
        """Execute a tool. Checks local tools first, then shared."""
        self._check_alive()
        t0 = time.monotonic()
        tool = self._local_tools.get(tool_name) or Robody._shared_tools.get(tool_name)
        if tool is None:
            raise ValueError(f"unknown tool: {tool_name!r}")
        try:
            result = tool.execute(*args, **kwargs)
            elapsed = (time.monotonic() - t0) * 1000
            self._record("use_tool", args=(tool_name,),
                         result=result, elapsed_ms=elapsed)
            return result
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            self._record("use_tool", args=(tool_name,),
                         error=str(e), elapsed_ms=elapsed)
            raise

    def list_tools(self) -> List[Dict[str, str]]:
        """What tools can this agent use?"""
        tools = {}
        for name, t in Robody._shared_tools.items():
            tools[name] = {"name": name, "description": t.description, "scope": "shared"}
        for name, t in self._local_tools.items():
            tools[name] = {"name": name, "description": t.description, "scope": "local"}
        return list(tools.values())

    # ------------------------------------------------------------------
    # INSTRUMENT PANEL: self-description for the pilot
    # ------------------------------------------------------------------

    def describe_panel(self) -> List[Dict[str, str]]:
        """Return the methods available to the pilot, with docs."""
        panel = []
        for name in sorted(dir(self)):
            if name.startswith("_"):
                continue
            attr = getattr(self, name, None)
            if not callable(attr):
                continue
            doc = (getattr(attr, "__doc__", "") or "").strip().split("\n")[0]
            panel.append({"method": name, "doc": doc})
        return panel

    def export_state(self) -> Dict:
        """Snapshot for persistence / debugging."""
        return {
            "agent_id": self.agent_id,
            "workspace": str(self.workspace),
            "terminated": self._terminated,
            "violations": self._violation_count,
            "actions": len(self._local_log),
            "slices": list(self._slices.keys()),
            "local_tools": list(self._local_tools.keys()),
            "local_state_keys": list(self._local.keys()),
            "ts": datetime.now().isoformat(),
        }


# ---------------------------------------------------------------------------
# Orchestrator — controls the swarm
# ---------------------------------------------------------------------------

class Orchestrator:
    """
    Manages the robody swarm from outside.

    NOT a robody itself — this is the human/system layer that:
      - spawns and terminates agents
      - sets view filters (what each agent sees)
      - broadcasts signals
      - installs hooks (method interception)
      - monitors the global action log
      - hot-swaps capabilities
    """

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def spawn(agent_id: str, workspace: Path, **kwargs) -> Robody:
        """Create and register a new agent."""
        return Robody(agent_id, workspace, **kwargs)

    @staticmethod
    def terminate(agent_id: str, reason: str = "orchestrator decision"):
        agent = Robody._registry.get(agent_id)
        if agent:
            agent.terminate(reason)

    @staticmethod
    def get(agent_id: str) -> Optional[Robody]:
        return Robody._registry.get(agent_id)

    @staticmethod
    def list_agents() -> List[str]:
        return [
            aid for aid, a in Robody._registry.items()
            if not a._terminated
        ]

    # ------------------------------------------------------------------
    # Shared state (bus)
    # ------------------------------------------------------------------

    @staticmethod
    def bus_write(key: str, value: Any):
        """Write directly to the bus (bypasses agent logging)."""
        Robody._bus["state"][key] = value

    @staticmethod
    def bus_read(key: str, default: Any = None) -> Any:
        return Robody._bus["state"].get(key, default)

    @staticmethod
    def bus_clear():
        Robody._bus["state"].clear()
        Robody._bus["signals"].clear()

    # ------------------------------------------------------------------
    # Signals (broadcast)
    # ------------------------------------------------------------------

    @staticmethod
    def broadcast(signal: dict):
        """
        Push a signal that all agents can read.
        Agents consume signals via robody.bus_read_signal().
        """
        signal["ts"] = datetime.now().isoformat()
        Robody._bus["signals"].append(signal)
        log.info("BROADCAST: %s", signal.get("type", "unknown"))

    # ------------------------------------------------------------------
    # View filters (control what each agent sees)
    # ------------------------------------------------------------------

    @staticmethod
    def set_view(agent_id: str, view_fn: Optional[Callable]):
        """
        Set a view filter for an agent.

        view_fn(agent_id, key, raw_value) -> filtered_value
        Return None to hide the key entirely.
        """
        agent = Robody._registry.get(agent_id)
        if agent:
            agent._view_filter = view_fn

    @staticmethod
    def set_view_keys(agent_id: str, allowed_keys: Set[str]):
        """Convenience: only let agent see specific bus keys."""
        def key_filter(aid, key, value):
            return value if key in allowed_keys else None
        Orchestrator.set_view(agent_id, key_filter)

    # ------------------------------------------------------------------
    # Method hooks (interception / monkey-patching)
    # ------------------------------------------------------------------

    @staticmethod
    def install_hook(method_name: str, hook: Callable):
        """
        Wrap a Robody method for ALL instances.

        hook(self, original_fn, *args, **kwargs) -> Any

        The hook receives the robody instance, the original method,
        and the call arguments. It decides whether/when to call
        original_fn.

        Example — universal logging:

            def log_hook(self, orig, *a, **kw):
                log.info(f"[{self.agent_id}] calling {orig.__name__}")
                result = orig(self, *a, **kw)
                log.info(f"[{self.agent_id}] done")
                return result

            Orchestrator.install_hook("read_file", log_hook)
        """
        _wrap_method(Robody, method_name, hook)
        Robody._hooks.setdefault(method_name, []).append(hook)
        log.info("hook installed on Robody.%s", method_name)

    @staticmethod
    def remove_hooks(method_name: str):
        """Remove all hooks from a method, restore original."""
        _unwrap_method(Robody, method_name)
        Robody._hooks.pop(method_name, None)

    # ------------------------------------------------------------------
    # Hot-swap capabilities
    # ------------------------------------------------------------------

    @staticmethod
    def add_capability(name: str, fn: Callable, doc: str = ""):
        """
        Add a new method to ALL robody instances instantly.

        This is the monkey-patch broadcast — define once, every agent
        has it on their next call.
        """
        fn.__name__ = name
        fn.__doc__ = doc or fn.__doc__ or ""
        setattr(Robody, name, fn)
        log.info("capability added: Robody.%s", name)

    @staticmethod
    def remove_capability(name: str):
        if hasattr(Robody, name):
            delattr(Robody, name)
            log.info("capability removed: Robody.%s", name)

    # ------------------------------------------------------------------
    # Monitoring
    # ------------------------------------------------------------------

    @staticmethod
    def global_log(last_n: int = 50) -> List[ActionRecord]:
        """Get the last N actions across ALL agents."""
        return Robody._action_log[-last_n:]

    @staticmethod
    def agent_log(agent_id: str, last_n: int = 50) -> List[ActionRecord]:
        agent = Robody._registry.get(agent_id)
        if agent:
            return agent._local_log[-last_n:]
        return []

    @staticmethod
    def agent_errors(agent_id: str) -> List[ActionRecord]:
        agent = Robody._registry.get(agent_id)
        if agent:
            return [r for r in agent._local_log if r.error]
        return []

    @staticmethod
    def status() -> Dict[str, Any]:
        """Swarm status overview."""
        agents = Robody._registry
        return {
            "total_agents": len(agents),
            "alive": sum(1 for a in agents.values() if not a._terminated),
            "terminated": sum(1 for a in agents.values() if a._terminated),
            "bus_keys": list(Robody._bus["state"].keys()),
            "pending_signals": len(Robody._bus["signals"]),
            "shared_tools": list(Robody._shared_tools.keys()),
            "total_actions": len(Robody._action_log),
            "hooks": list(Robody._hooks.keys()),
        }

    # ------------------------------------------------------------------
    # Reset (for testing / between runs)
    # ------------------------------------------------------------------

    @staticmethod
    def reset():
        """Full reset — clears bus, agents, hooks, everything."""
        Robody._bus = {"state": {}, "config": {}, "signals": []}
        Robody._shared_tools.clear()
        Robody._registry.clear()
        Robody._hooks.clear()
        Robody._action_log.clear()
        log.info("orchestrator RESET")


# ---------------------------------------------------------------------------
# Built-in tools
# ---------------------------------------------------------------------------

class SafeDBQueryTool:
    """
    Read-only database query tool.
    Parameterized queries only. No raw SQL from the pilot.
    """
    name = "db_query"
    description = "Run a parameterized read-only query against SQLite"

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)

    def execute(self, query: str, params: tuple = ()) -> List[Dict]:
        # Safety: only SELECT allowed
        normalized = query.strip().upper()
        if not normalized.startswith("SELECT"):
            raise PermissionError("only SELECT queries allowed")
        for forbidden in ("DROP", "DELETE", "INSERT", "UPDATE", "ALTER",
                          "CREATE", "ATTACH", "DETACH", "PRAGMA"):
            if forbidden in normalized:
                raise PermissionError(f"forbidden keyword: {forbidden}")

        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


class FTS5SearchTool:
    """
    Full-text search via SQLite FTS5.
    Expects an FTS5 virtual table already exists in the DB.
    """
    name = "fts_search"
    description = "Full-text search across indexed content"

    def __init__(self, db_path: Path, table: str = "messages_fts"):
        self.db_path = Path(db_path)
        self.table = table

    def execute(self, query: str, limit: int = 20) -> List[Dict]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            sql = f"SELECT * FROM {self.table} WHERE {self.table} MATCH ? LIMIT ?"
            rows = conn.execute(sql, (query, limit)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Demo / smoke test
# ---------------------------------------------------------------------------

def demo():
    """Demonstrate the shared memory bus architecture."""

    print("=" * 60)
    print("ROBODY SHARED MEMORY BUS DEMO")
    print("=" * 60)

    Orchestrator.reset()

    # --- Spawn agents ---
    a1 = Orchestrator.spawn("alice", Path("./work/alice"))
    a2 = Orchestrator.spawn("bob", Path("./work/bob"))
    a3 = Orchestrator.spawn("carol", Path("./work/carol"))

    print(f"\nAgents: {Orchestrator.list_agents()}")

    # --- Shared bus: write from orchestrator, read from any agent ---
    Orchestrator.bus_write("project_name", "CastleHeck")
    Orchestrator.bus_write("objectives", ["build knowledge graph", "implement FTS5", "robody v1"])
    Orchestrator.bus_write("secret_keys", {"api_key": "sk-12345"})

    print(f"\nAlice reads project: {a1.bus_read('project_name')}")
    print(f"Bob reads objectives: {a2.bus_read('objectives')}")

    # --- View filters: restrict what carol sees ---
    Orchestrator.set_view_keys("carol", {"project_name", "objectives"})
    print(f"\nCarol reads project: {a3.bus_read('project_name')}")
    print(f"Carol reads secrets: {a3.bus_read('secret_keys')}")  # None — filtered

    # --- Agent writes to bus (all others see it instantly) ---
    a1.bus_write("alice_finding", "found 47 orphaned objectives in logs")
    print(f"\nBob reads Alice's finding: {a2.bus_read('alice_finding')}")

    # --- Broadcast signal ---
    Orchestrator.broadcast({"type": "phase_complete", "phase": "ingestion"})
    sig = a2.bus_read_signal()
    print(f"\nBob received signal: {sig}")

    # --- Hot-swap capability ---
    def count_words(self, text: str) -> int:
        """Count words in text."""
        return len(text.split())

    Orchestrator.add_capability("count_words", count_words)
    print(f"\nAlice counts words: {a1.count_words('hello world foo bar')}")
    print(f"Bob counts words: {a2.count_words('one two three')}")

    # --- Method hook (universal interception) ---
    call_count = {"n": 0}

    def counting_hook(self, original, *args, **kwargs):
        call_count["n"] += 1
        return original(self, *args, **kwargs)

    Orchestrator.install_hook("bus_read", counting_hook)
    a1.bus_read("project_name")
    a2.bus_read("project_name")
    a3.bus_read("project_name")
    print(f"\nbus_read called {call_count['n']} times (via hook)")
    Orchestrator.remove_hooks("bus_read")

    # --- Context slice demo ---
    big_text = (
        "The CastleHeck project began as an MCP server. "
        "Over time it evolved into a three-tier architecture. "
        "SECRET: the api key is hunter2. "
        "The Task DAG system enables parallel execution of objectives. "
        "Each objective maps to a node in the dependency graph."
    )
    Orchestrator.bus_write("architecture_doc", big_text)

    a1.create_slice(
        "task_dag_section",
        source_key="architecture_doc",
        focal_start=big_text.find("Task DAG"),
        focal_end=big_text.find("dependency graph.") + len("dependency graph."),
        context_start=0,
        context_end=len(big_text),
        blind=[(big_text.find("SECRET"), big_text.find("hunter2.") + len("hunter2."))],
    )
    filtered = a1.read_slice("task_dag_section")
    print(f"\nSlice view (blind applied): {filtered[:120]}...")
    assert "hunter2" not in filtered, "blind slice failed!"

    # --- Status ---
    print(f"\n--- Swarm Status ---")
    for k, v in Orchestrator.status().items():
        print(f"  {k}: {v}")

    # --- Action log ---
    print(f"\n--- Last 5 global actions ---")
    for rec in Orchestrator.global_log(5):
        print(f"  [{rec.agent_id}] {rec.action} {rec.result_repr[:60]}")

    print("\n" + "=" * 60)
    print("DEMO COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    demo()
