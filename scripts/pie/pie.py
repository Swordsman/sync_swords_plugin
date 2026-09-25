"""
pie.py — Procedural Inference Emulator

PIE is a state machine, not an AI. It:
  - Manages agent lifecycle (spawn, suspend, resume, clone, split, merge)
  - Gates content access (prevents wasteful duplication across agents)
  - Presents as a standard inference endpoint (OpenAI/Anthropic API)
  - Composes recursively (a PIE node looks like a model to the layer above)

PIE does not make decisions. It executes rules from the user and orchestrator.
The agents get to be creative. The scheduler is boring and correct.
"""

import json
import time
import hashlib
import sqlite3
import os
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager

from agent import (
    Agent, AgentManifest, AgentContext, Turn,
    InferenceTrace, KnowledgeEntry,
    BaremetalRuntime, AgentRuntime,
    serialize_agent, deserialize_agent,
)


# ============================================================================
# CONTENT REGISTRY — who has what, across all agents in a session
# ============================================================================

REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    name TEXT DEFAULT '',
    role TEXT DEFAULT '',
    runtime_type TEXT DEFAULT 'baremetal',
    status TEXT NOT NULL DEFAULT 'live',
    context_tokens INTEGER DEFAULT 0,
    context_capacity INTEGER DEFAULT 128000,
    created REAL NOT NULL,
    last_active REAL NOT NULL,
    parent_agent_id TEXT,
    archetype_id TEXT,
    PRIMARY KEY (agent_id, session_id)
);

CREATE TABLE IF NOT EXISTS content_map (
    file_hash TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    lines INTEGER NOT NULL,
    turn_loaded INTEGER DEFAULT 0,
    turn_last_referenced INTEGER DEFAULT 0,
    PRIMARY KEY (file_hash, agent_id, session_id)
);

CREATE TABLE IF NOT EXISTS archetypes (
    archetype_id TEXT PRIMARY KEY,
    name TEXT DEFAULT '',
    role TEXT DEFAULT '',
    specializations TEXT DEFAULT '[]',
    knowledge_hashes TEXT DEFAULT '[]',
    blob_path TEXT NOT NULL,
    created REAL NOT NULL,
    source_session TEXT,
    source_agent TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    created REAL NOT NULL,
    last_active REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_content_hash
    ON content_map(file_hash, session_id);
CREATE INDEX IF NOT EXISTS idx_content_agent
    ON content_map(agent_id, session_id);
"""


class ContentRegistry:
    """SQLite-backed registry tracking which agents hold which content.

    This is PIE's source of truth. Every content gating decision
    flows from this registry.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._ensure_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self):
        with self._conn() as conn:
            conn.executescript(REGISTRY_SCHEMA)

    # --- Session management ---

    def init_session(self, session_id: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                (session_id, time.time(), time.time())
            )

    def touch_session(self, session_id: str):
        with self._conn() as conn:
            conn.execute(
                "UPDATE sessions SET last_active = ? WHERE session_id = ?",
                (time.time(), session_id)
            )

    # --- Agent tracking ---

    def register_agent(self, agent: Agent, session_id: str,
                       runtime_type: str = 'baremetal',
                       context_capacity: int = 128000):
        m = agent.manifest
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agents "
                "(agent_id, session_id, name, role, runtime_type, status, "
                " context_tokens, context_capacity, created, last_active, "
                " parent_agent_id, archetype_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (m.agent_id, session_id, m.name, m.role,
                 runtime_type, m.status,
                 agent.context.token_estimate, context_capacity,
                 m.created, m.last_active,
                 m.parent_agent_id, None)
            )

    def update_agent_status(self, agent_id: str, session_id: str,
                            status: str, context_tokens: int = 0):
        with self._conn() as conn:
            conn.execute(
                "UPDATE agents SET status = ?, context_tokens = ?, "
                "last_active = ? WHERE agent_id = ? AND session_id = ?",
                (status, context_tokens, time.time(), agent_id, session_id)
            )

    def get_agent_info(self, agent_id: str,
                       session_id: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM agents WHERE agent_id = ? AND session_id = ?",
                (agent_id, session_id)
            ).fetchone()
            return dict(row) if row else None

    def list_agents(self, session_id: str,
                    status: Optional[str] = None) -> List[Dict]:
        with self._conn() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM agents "
                    "WHERE session_id = ? AND status = ?",
                    (session_id, status)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM agents WHERE session_id = ?",
                    (session_id,)
                ).fetchall()
            return [dict(r) for r in rows]

    # --- Content tracking ---

    def record_content(self, agent_id: str, session_id: str,
                       file_hash: str, file_path: str,
                       file_size: int, lines: int, turn: int = 0):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO content_map "
                "(file_hash, agent_id, session_id, file_path, "
                " file_size, lines, turn_loaded, turn_last_referenced) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (file_hash, agent_id, session_id,
                 file_path, file_size, lines, turn, turn)
            )

    def who_has(self, file_hash: str,
                session_id: str) -> List[Dict]:
        """Which live agents in this session have this content?"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT cm.*, a.name as agent_name, a.role as agent_role, "
                "       a.status, a.context_tokens, a.context_capacity "
                "FROM content_map cm "
                "JOIN agents a ON cm.agent_id = a.agent_id "
                "  AND cm.session_id = a.session_id "
                "WHERE cm.file_hash = ? AND cm.session_id = ? "
                "  AND a.status = 'live'",
                (file_hash, session_id)
            ).fetchall()
            return [dict(r) for r in rows]

    def agent_content(self, agent_id: str,
                      session_id: str) -> List[Dict]:
        """What content does this agent have?"""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM content_map "
                "WHERE agent_id = ? AND session_id = ?",
                (agent_id, session_id)
            ).fetchall()
            return [dict(r) for r in rows]

    def content_overlap(self, agent_a: str, agent_b: str,
                        session_id: str) -> List[str]:
        """Return file hashes that both agents hold."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT a.file_hash FROM content_map a "
                "JOIN content_map b ON a.file_hash = b.file_hash "
                "  AND a.session_id = b.session_id "
                "WHERE a.agent_id = ? AND b.agent_id = ? "
                "  AND a.session_id = ?",
                (agent_a, agent_b, session_id)
            ).fetchall()
            return [r['file_hash'] for r in rows]

    # --- Archetype management ---

    def save_archetype(self, archetype_id: str, name: str, role: str,
                       specializations: List[str],
                       knowledge_hashes: List[str],
                       blob_path: str,
                       source_session: str = '',
                       source_agent: str = ''):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO archetypes "
                "(archetype_id, name, role, specializations, "
                " knowledge_hashes, blob_path, created, "
                " source_session, source_agent) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (archetype_id, name, role,
                 json.dumps(specializations),
                 json.dumps(knowledge_hashes),
                 blob_path, time.time(),
                 source_session, source_agent)
            )

    def find_archetype(self, file_hash: str) -> Optional[Dict]:
        """Find an archetype that specializes in this content."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM archetypes"
            ).fetchall()
            for row in rows:
                hashes = json.loads(row['knowledge_hashes'])
                if file_hash in hashes:
                    return dict(row)
            return None

    def list_archetypes(self) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM archetypes").fetchall()
            return [dict(r) for r in rows]


# ============================================================================
# PIE RESPONSES — the fixed vocabulary
# ============================================================================

@dataclass
class PIEResponse:
    """PIE's response to a content or lifecycle request.

    PIE only speaks in these structured responses. No free-form text,
    no hallucination, no "I think maybe you should."
    """
    action: str
    # APPROVE          — go ahead, content attached
    # REDIRECT         — agent X has this, talk to them
    # REDIRECT_SUMMARY — agent X has this, here's a briefing
    # SPAWN_SUGGESTION — no live agent has this, but archetype Y does
    # DENY             — hard block (budget, policy, capacity)
    # MERGE_WARNING    — significant overlap detected
    # OK               — lifecycle action completed
    # ERROR            — something went wrong

    content: Optional[bytes] = None       # packed content (APPROVE)
    to_agent: Optional[str] = None        # redirect target agent_id
    agent_name: Optional[str] = None      # human-readable name of target
    summary: Optional[str] = None         # trace/briefing for redirect
    archetype: Optional[Dict] = None      # archetype info (SPAWN_SUGGESTION)
    overlap_hashes: Optional[List] = None # (MERGE_WARNING)
    message: str = ''                     # human-readable status/error
    metadata: Dict = field(default_factory=dict)


# ============================================================================
# PIE — the state machine
# ============================================================================

class PIE:
    """Procedural Inference Emulator.

    A deterministic state machine that manages agents and gates content.
    Presents as an inference endpoint to callers.

    PIE does not make decisions. It applies rules from the user and
    orchestrator. The agents are creative. PIE is correct.
    """

    def __init__(self, session_id: str, *,
                 db_path: Optional[str] = None,
                 duplication_threshold: int = 8192,
                 context_warning_ratio: float = 0.85,
                 archetype_dir: str = './archetypes'):
        self.session_id = session_id
        self.duplication_threshold = duplication_threshold
        self.context_warning_ratio = context_warning_ratio
        self.archetype_dir = archetype_dir

        if db_path is None:
            runtime_dir = os.environ.get('XDG_RUNTIME_DIR', '/tmp')
            db_path = os.path.join(runtime_dir, f'pie-{session_id}.db')

        self.registry = ContentRegistry(db_path)
        self.registry.init_session(session_id)

        # Live runtimes (only for agents PIE manages directly)
        self.runtimes: Dict[str, AgentRuntime] = {}

    # ----------------------------------------------------------------
    # CONTENT GATING — the core routing logic
    # ----------------------------------------------------------------

    def handle_ingest_request(self, requesting_agent_id: str,
                              file_path: str,
                              file_content: bytes,
                              reason: str = '') -> PIEResponse:
        """Agent wants to read a file. Check registry, apply rules.

        This is the primary content gating function. Deterministic:
        same inputs always produce the same routing decision.
        """
        file_hash = hashlib.sha256(file_content).hexdigest()
        file_size = len(file_content)

        # Who already has this?
        holders = self.registry.who_has(file_hash, self.session_id)

        # Filter out the requesting agent itself
        other_holders = [h for h in holders
                         if h['agent_id'] != requesting_agent_id]

        # Case 1: Nobody else has it
        if not other_holders:
            # Check archetypes (frozen agents on disk)
            archetype = self.registry.find_archetype(file_hash)
            if archetype and file_size >= self.duplication_threshold:
                return PIEResponse(
                    action='SPAWN_SUGGESTION',
                    archetype=archetype,
                    message=f"No live agent has this, but archetype "
                            f"'{archetype.get('name', '?')}' specializes in it.",
                )

            # Approve — record in registry
            lines = self._count_lines(file_content)
            self.registry.record_content(
                requesting_agent_id, self.session_id,
                file_hash, file_path, file_size, lines,
                turn=self._agent_turn(requesting_agent_id),
            )
            return PIEResponse(
                action='APPROVE',
                content=file_content,
                message=f'Approved: {file_path} ({file_size} bytes)',
            )

        # Case 2: Someone has it, but it's small enough to duplicate
        if file_size < self.duplication_threshold:
            lines = self._count_lines(file_content)
            self.registry.record_content(
                requesting_agent_id, self.session_id,
                file_hash, file_path, file_size, lines,
                turn=self._agent_turn(requesting_agent_id),
            )
            return PIEResponse(
                action='APPROVE',
                content=file_content,
                message=f'Approved (small file, duplicated): {file_path}',
                metadata={'also_held_by': [h['agent_id'] for h in other_holders]},
            )

        # Case 3: Large file, someone else has it — redirect
        # Pick the best holder: most recently active, least loaded
        best = self._pick_holder(other_holders)
        agent_info = self.registry.get_agent_info(
            best['agent_id'], self.session_id
        )

        return PIEResponse(
            action='REDIRECT',
            to_agent=best['agent_id'],
            agent_name=agent_info.get('name', '') if agent_info else '',
            summary=f"Agent '{best.get('agent_name', best['agent_id'])}' "
                    f"has {file_path} (loaded turn {best.get('turn_loaded', '?')}). "
                    f"Consult them instead of ingesting directly.",
            message=f'Redirected to {best["agent_id"]} for {file_path}',
        )

    def check_overlap(self, agent_a: str, agent_b: str) -> PIEResponse:
        """Check content overlap between two agents."""
        overlap = self.registry.content_overlap(
            agent_a, agent_b, self.session_id
        )
        if len(overlap) > 3:  # arbitrary threshold
            return PIEResponse(
                action='MERGE_WARNING',
                overlap_hashes=overlap,
                message=f'{len(overlap)} shared files between '
                        f'{agent_a} and {agent_b}. Consider consolidating.',
            )
        return PIEResponse(action='OK', message='Overlap within tolerance.')

    def check_context_health(self, agent_id: str) -> PIEResponse:
        """Check if an agent is approaching context capacity.

        Returns a warning if the agent should be proactively managed
        before the CLI's compaction algorithm fires.
        """
        info = self.registry.get_agent_info(agent_id, self.session_id)
        if not info:
            return PIEResponse(action='ERROR', message='Agent not found')

        tokens = info['context_tokens']
        capacity = info['context_capacity']
        ratio = tokens / capacity if capacity > 0 else 0

        if ratio >= self.context_warning_ratio:
            return PIEResponse(
                action='MERGE_WARNING',
                message=f'Agent {agent_id} at {ratio:.0%} context capacity '
                        f'({tokens}/{capacity} tokens). '
                        f'Consider offloading or splitting before compaction.',
                metadata={'tokens': tokens, 'capacity': capacity, 'ratio': ratio},
            )
        return PIEResponse(
            action='OK',
            message=f'Agent {agent_id} at {ratio:.0%} capacity.',
            metadata={'tokens': tokens, 'capacity': capacity, 'ratio': ratio},
        )

    # ----------------------------------------------------------------
    # AGENT LIFECYCLE — executed on request, never self-initiated
    # ----------------------------------------------------------------

    def spawn_agent(self, name: str = '', role: str = '',
                    system_prompt: str = '',
                    model: str = 'gpt-4o-mini',
                    api_base: str = 'https://api.openai.com/v1',
                    api_key: Optional[str] = None,
                    max_tokens: int = 128000,
                    parent_agent_id: Optional[str] = None
                    ) -> Tuple[str, PIEResponse]:
        """Spawn a new baremetal agent. Returns (agent_id, response)."""
        agent = Agent()
        agent.manifest.name = name
        agent.manifest.role = role
        agent.manifest.parent_agent_id = parent_agent_id
        agent.context.system_prompt = system_prompt

        runtime = BaremetalRuntime(
            agent,
            model=model,
            api_base=api_base,
            api_key=api_key,
            max_tokens=max_tokens,
        )

        agent_id = agent.manifest.agent_id
        self.runtimes[agent_id] = runtime
        self.registry.register_agent(
            agent, self.session_id,
            runtime_type='baremetal',
            context_capacity=max_tokens,
        )

        return agent_id, PIEResponse(
            action='OK',
            message=f'Spawned agent {agent_id} ({name or "unnamed"})',
            metadata={'agent_id': agent_id, 'model': model},
        )

    def suspend_agent(self, agent_id: str,
                      save_path: Optional[str] = None) -> PIEResponse:
        """Serialize an agent to disk and remove from active runtimes."""
        runtime = self.runtimes.get(agent_id)
        if not runtime:
            return PIEResponse(action='ERROR',
                               message=f'Agent {agent_id} not in active runtimes')

        blob = serialize_agent(runtime.agent)

        if save_path is None:
            os.makedirs(self.archetype_dir, exist_ok=True)
            save_path = os.path.join(self.archetype_dir,
                                     f'{agent_id}.agent')

        with open(save_path, 'wb') as f:
            f.write(blob)

        self.registry.update_agent_status(
            agent_id, self.session_id, 'suspended'
        )
        del self.runtimes[agent_id]

        return PIEResponse(
            action='OK',
            message=f'Suspended agent {agent_id} → {save_path}',
            metadata={'save_path': save_path, 'blob_size': len(blob)},
        )

    def resume_agent(self, save_path: str, *,
                     model: str = 'gpt-4o-mini',
                     api_base: str = 'https://api.openai.com/v1',
                     api_key: Optional[str] = None,
                     max_tokens: int = 128000,
                     bridge_reason: str = ''
                     ) -> Tuple[str, PIEResponse]:
        """Deserialize an agent from disk and bring it live."""
        if not os.path.exists(save_path):
            return '', PIEResponse(action='ERROR',
                                   message=f'Not found: {save_path}')

        with open(save_path, 'rb') as f:
            blob = f.read()

        agent = deserialize_agent(blob)

        # Inject narrative bridge if migrating
        if bridge_reason:
            agent.context.inject_narrative_bridge(bridge_reason)

        runtime = BaremetalRuntime(
            agent, model=model, api_base=api_base,
            api_key=api_key, max_tokens=max_tokens,
        )

        agent_id = agent.manifest.agent_id
        agent.manifest.status = 'live'
        agent.manifest.touch()

        self.runtimes[agent_id] = runtime
        self.registry.register_agent(
            agent, self.session_id,
            runtime_type='baremetal',
            context_capacity=max_tokens,
        )

        # Re-register all knowledge in the content map
        for file_hash, entry in agent.knowledge.items():
            lines = self._count_lines(entry.content)
            self.registry.record_content(
                agent_id, self.session_id,
                file_hash, entry.file_path,
                len(entry.content), lines,
                turn=entry.turn_loaded,
            )

        return agent_id, PIEResponse(
            action='OK',
            message=f'Resumed agent {agent_id} from {save_path}',
            metadata={'agent_id': agent_id},
        )

    def clone_agent(self, source_id: str, *,
                    name: str = '', role: str = '',
                    mutations: Optional[Dict] = None
                    ) -> Tuple[str, PIEResponse]:
        """Clone an agent, optionally mutating the copy.

        The clone gets a new agent_id but inherits the source's
        narrative, knowledge, and traces. Parent lineage is tracked.
        """
        runtime = self.runtimes.get(source_id)
        if not runtime:
            return '', PIEResponse(
                action='ERROR',
                message=f'Agent {source_id} not in active runtimes')

        # Serialize and deserialize to get a deep copy
        blob = serialize_agent(runtime.agent)
        clone = deserialize_agent(blob)

        # New identity, preserve lineage
        import uuid
        clone.manifest.agent_id = uuid.uuid4().hex[:12]
        clone.manifest.parent_agent_id = source_id
        clone.manifest.name = name or f'{clone.manifest.name} (clone)'
        if role:
            clone.manifest.role = role
        clone.manifest.created = time.time()
        clone.manifest.touch()

        # Apply mutations (e.g. different system prompt, pruned knowledge)
        if mutations:
            if 'system_prompt' in mutations:
                clone.context.system_prompt = mutations['system_prompt']
            if 'remove_knowledge' in mutations:
                for fh in mutations['remove_knowledge']:
                    clone.knowledge.pop(fh, None)
                    if fh in clone.manifest.knowledge_hashes:
                        clone.manifest.knowledge_hashes.remove(fh)

        # Bridge the narrative
        clone.context.inject_narrative_bridge(
            f'You have been cloned from agent {source_id}. '
            f'You are now agent {clone.manifest.agent_id}. '
            f'Your role: {clone.manifest.role or clone.manifest.name}.'
        )

        clone_runtime = BaremetalRuntime(
            clone,
            model=getattr(runtime, 'model', 'gpt-4o-mini'),
            api_base=getattr(runtime, 'api_base', 'https://api.openai.com/v1'),
            api_key=getattr(runtime, 'api_key', ''),
            max_tokens=getattr(runtime, 'max_tokens', 128000),
        )

        clone_id = clone.manifest.agent_id
        self.runtimes[clone_id] = clone_runtime
        self.registry.register_agent(clone, self.session_id)

        # Register clone's content
        for file_hash, entry in clone.knowledge.items():
            lines = self._count_lines(entry.content)
            self.registry.record_content(
                clone_id, self.session_id,
                file_hash, entry.file_path,
                len(entry.content), lines,
                turn=entry.turn_loaded,
            )

        return clone_id, PIEResponse(
            action='OK',
            message=f'Cloned {source_id} → {clone_id}',
            metadata={'clone_id': clone_id, 'parent_id': source_id},
        )

    def save_archetype(self, agent_id: str,
                       archetype_name: str = '') -> PIEResponse:
        """Save a live agent as a reusable archetype on disk."""
        runtime = self.runtimes.get(agent_id)
        if not runtime:
            return PIEResponse(action='ERROR',
                               message=f'Agent {agent_id} not in active runtimes')

        agent = runtime.agent
        import uuid
        archetype_id = uuid.uuid4().hex[:12]

        os.makedirs(self.archetype_dir, exist_ok=True)
        blob_path = os.path.join(self.archetype_dir,
                                 f'archetype-{archetype_id}.agent')

        blob = serialize_agent(agent)
        with open(blob_path, 'wb') as f:
            f.write(blob)

        self.registry.save_archetype(
            archetype_id=archetype_id,
            name=archetype_name or agent.manifest.name,
            role=agent.manifest.role,
            specializations=agent.manifest.specializations,
            knowledge_hashes=agent.manifest.knowledge_hashes,
            blob_path=blob_path,
            source_session=self.session_id,
            source_agent=agent_id,
        )

        return PIEResponse(
            action='OK',
            message=f'Saved archetype {archetype_id} ({archetype_name})',
            metadata={'archetype_id': archetype_id, 'blob_path': blob_path},
        )

    # ----------------------------------------------------------------
    # INFERENCE ENDPOINT FACADE
    # ----------------------------------------------------------------

    def handle_chat_completion(self, request: Dict) -> Dict:
        """Handle an OpenAI-compatible chat completion request.

        This is how PIE presents itself as a model. The caller sends
        a standard messages array; PIE routes to the appropriate agent(s)
        and returns a standard response.

        For now: routes to a designated "primary" agent or round-robins.
        The orchestrator agent (if present) is the default target.
        """
        messages = request.get('messages', [])
        target_agent = request.get('agent_id')  # PIE extension field
        model_override = request.get('model')

        if not messages:
            return self._error_response('No messages provided')

        # Find target runtime
        runtime = None
        if target_agent and target_agent in self.runtimes:
            runtime = self.runtimes[target_agent]
        elif self.runtimes:
            # Default to first live agent (orchestrator convention:
            # first spawned agent is the orchestrator)
            for aid, rt in self.runtimes.items():
                info = self.registry.get_agent_info(aid, self.session_id)
                if info and info['status'] == 'live':
                    runtime = rt
                    target_agent = aid
                    break

        if runtime is None:
            return self._error_response('No live agent available')

        # Extract the last user message as the input
        last_user_msg = None
        for msg in reversed(messages):
            if msg.get('role') == 'user':
                last_user_msg = msg.get('content', '')
                break

        if last_user_msg is None:
            return self._error_response('No user message found')

        # Call inference through the runtime
        response_text = runtime.call_inference(user_message=last_user_msg)

        # Update registry with new context size
        usage = runtime.estimate_usage()
        self.registry.update_agent_status(
            target_agent, self.session_id,
            'live', context_tokens=usage[0],
        )

        # Return OpenAI-compatible response
        return {
            'id': f'pie-{self.session_id}-{int(time.time())}',
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': f'pie/{self.session_id}',
            'choices': [{
                'index': 0,
                'message': {
                    'role': 'assistant',
                    'content': response_text,
                },
                'finish_reason': 'stop',
            }],
            'usage': {
                'prompt_tokens': usage[0],
                'completion_tokens': len(response_text) // 4,
                'total_tokens': usage[0] + len(response_text) // 4,
            },
            # PIE extension: which agent actually handled this
            'pie_metadata': {
                'agent_id': target_agent,
                'session_id': self.session_id,
            },
        }

    # ----------------------------------------------------------------
    # STATUS & INTROSPECTION
    # ----------------------------------------------------------------

    def status(self) -> Dict:
        """Full session status dump."""
        agents = self.registry.list_agents(self.session_id)
        archetypes = self.registry.list_archetypes()

        total_content = 0
        for agent in agents:
            content = self.registry.agent_content(
                agent['agent_id'], self.session_id
            )
            agent['content_count'] = len(content)
            total_content += len(content)

        return {
            'session_id': self.session_id,
            'agents': agents,
            'active_runtimes': list(self.runtimes.keys()),
            'archetypes': len(archetypes),
            'total_content_entries': total_content,
            'duplication_threshold': self.duplication_threshold,
        }

    # ----------------------------------------------------------------
    # INTERNAL HELPERS
    # ----------------------------------------------------------------

    def _pick_holder(self, holders: List[Dict]) -> Dict:
        """Pick the best content holder for a redirect.

        Prefers: most recently active, then least loaded.
        """
        def score(h):
            # Higher = better
            recency = h.get('turn_last_referenced', 0)
            capacity = h.get('context_capacity', 1)
            tokens = h.get('context_tokens', 0)
            headroom = (capacity - tokens) / capacity if capacity else 0
            return (recency, headroom)

        return max(holders, key=score)

    def _agent_turn(self, agent_id: str) -> int:
        """Get current turn number for an agent."""
        runtime = self.runtimes.get(agent_id)
        if runtime:
            return len(runtime.agent.context.turns)
        return 0

    @staticmethod
    def _count_lines(content: bytes) -> int:
        try:
            return content.decode('utf-8', errors='strict').count('\n') + 1
        except UnicodeDecodeError:
            return 0

    @staticmethod
    def _error_response(message: str) -> Dict:
        return {
            'error': {
                'message': message,
                'type': 'pie_error',
            }
        }


# ============================================================================
# CLI (optional — for testing and standalone use)
# ============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog='pie',
        description='Procedural Inference Emulator',
    )
    parser.add_argument('--version', action='version', version='PIE 0.1.0')

    sub = parser.add_subparsers(dest='command')

    # --- status ---
    p_status = sub.add_parser('status', help='Show session status')
    p_status.add_argument('session_id')

    # --- spawn ---
    p_spawn = sub.add_parser('spawn', help='Spawn a new agent')
    p_spawn.add_argument('session_id')
    p_spawn.add_argument('--name', default='')
    p_spawn.add_argument('--role', default='')
    p_spawn.add_argument('--model', default='gpt-4o-mini')
    p_spawn.add_argument('--system-prompt', default='You are a helpful assistant.')

    # --- list ---
    p_list = sub.add_parser('list', help='List agents')
    p_list.add_argument('session_id')

    # --- suspend ---
    p_suspend = sub.add_parser('suspend', help='Suspend an agent to disk')
    p_suspend.add_argument('session_id')
    p_suspend.add_argument('agent_id')
    p_suspend.add_argument('--path', default=None)

    # --- resume ---
    p_resume = sub.add_parser('resume', help='Resume an agent from disk')
    p_resume.add_argument('session_id')
    p_resume.add_argument('path')
    p_resume.add_argument('--model', default='gpt-4o-mini')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    pie = PIE(args.session_id)

    if args.command == 'status':
        print(json.dumps(pie.status(), indent=2))

    elif args.command == 'spawn':
        agent_id, resp = pie.spawn_agent(
            name=args.name, role=args.role,
            model=args.model,
            system_prompt=args.system_prompt,
        )
        print(resp.message)
        print(f'Agent ID: {agent_id}')

    elif args.command == 'list':
        agents = pie.registry.list_agents(args.session_id)
        for a in agents:
            print(f"  {a['agent_id']}  {a['name'] or '(unnamed)':20s}  "
                  f"{a['status']:10s}  {a['runtime_type']}")

    elif args.command == 'suspend':
        resp = pie.suspend_agent(args.agent_id, save_path=args.path)
        print(resp.message)

    elif args.command == 'resume':
        agent_id, resp = pie.resume_agent(args.path, model=args.model)
        print(resp.message)


if __name__ == '__main__':
    main()
