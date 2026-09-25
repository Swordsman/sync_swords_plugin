"""
agent.py — Universal Agent Format

An agent is a persistent cognitive entity: a context window with a coherent
narrative, knowledge, and inference traces. It is independent of any specific
CLI or model. It can be serialized to disk, deserialized into any runtime,
migrated between CLIs, swapped between models, and composed into hierarchies.

Three things that are NOT the agent:
  - The model (interchangeable inference endpoint underneath)
  - The CLI (interchangeable hosting environment around it)
  - The PIE node (manages the agent's lifecycle, not its identity)
"""

import json
import time
import uuid
import hashlib
import os
from typing import List, Dict, Optional, Tuple, Protocol, Any, runtime_checkable
from dataclasses import dataclass, field, asdict


# ============================================================================
# AGENT IDENTITY & MANIFEST
# ============================================================================

@dataclass
class AgentManifest:
    """Identity and metadata for an agent. CLI-agnostic, model-agnostic."""

    agent_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ''                        # human-readable label
    role: str = ''                        # what this agent does
    status: str = 'live'                  # live | suspended | archived

    # Lineage
    parent_agent_id: Optional[str] = None   # cloned/branched from
    source_session: Optional[str] = None    # session it was born in
    created: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)

    # Provenance (informational, not structural)
    origin_cli: Optional[str] = None      # CLI it was first created in
    origin_model: Optional[str] = None    # model it was first run with

    # Capabilities & specializations
    specializations: List[str] = field(default_factory=list)
    # e.g. ['db.py', 'auth module', 'SQL optimization']
    # Used by PIE to match ingest requests to available specialists

    knowledge_hashes: List[str] = field(default_factory=list)
    # SHA-256 hashes of files this agent has ingested.
    # The content registry (PIE-side) is authoritative;
    # this is a local cache for fast serialization/deserialization.

    def touch(self):
        self.last_active = time.time()


# ============================================================================
# CONTEXT TURNS — the agent's stream of consciousness
# ============================================================================

@dataclass
class Turn:
    """A single turn in the agent's narrative.

    This is the fundamental unit of context. The sequence of turns IS the
    agent's experience. Corrupting the sequence corrupts the agent.
    """
    role: str               # 'system', 'user', 'assistant', 'tool'
    content: Any            # str, list[dict] (multimodal), tool results, etc.
    turn_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)
    synthetic: bool = False
    # True if this turn was injected (file ingestion, narrative bridge, etc.)
    # rather than produced by actual inference or user input.
    # Preserves provenance without disrupting the narrative.

    metadata: Dict = field(default_factory=dict)
    # Arbitrary k/v. Examples:
    #   {'type': 'file_ingestion', 'files': ['main.py', 'db.py']}
    #   {'type': 'narrative_bridge', 'reason': 'session migration'}
    #   {'type': 'inference_trace', 'target_file': 'utils.py', 'target_block': 'hash_content'}
    #   {'tool_call_id': 'call_abc123', 'tool_name': 'read_file'}


@dataclass
class AgentContext:
    """The full narrative context of an agent.

    This is an ordered sequence of turns that must remain coherent.
    Editing the context (injecting files, bridging sessions) must
    maintain narrative continuity or the agent becomes disoriented.
    """
    turns: List[Turn] = field(default_factory=list)
    system_prompt: str = ''

    @property
    def token_estimate(self) -> int:
        """Rough token estimate. ~4 chars per token, good enough for
        threshold checks. Real tokenization is model-specific and
        belongs in the runtime."""
        total_chars = len(self.system_prompt)
        for turn in self.turns:
            if isinstance(turn.content, str):
                total_chars += len(turn.content)
            elif isinstance(turn.content, list):
                for block in turn.content:
                    if isinstance(block, dict) and 'text' in block:
                        total_chars += len(block['text'])
            else:
                total_chars += len(str(turn.content))
        return total_chars // 4

    def append(self, role: str, content: Any, **kwargs) -> Turn:
        """Append a turn to the narrative."""
        turn = Turn(role=role, content=content, **kwargs)
        self.turns.append(turn)
        return turn

    def inject_file_read(self, file_path: str, file_content: str):
        """Inject a file read as a coherent narrative sequence.

        Creates synthetic turns that look like the agent naturally
        read the file, so the context flows without disorientation.
        """
        self.append(
            'user',
            f'Read the file at {file_path} and confirm you understand it.',
            synthetic=True,
            metadata={'type': 'file_ingestion', 'file': file_path}
        )
        self.append(
            'assistant',
            f'I\'ve read `{file_path}`. Let me review it.\n\n```\n{file_content}\n```\n\n'
            f'I now have this file in context and understand its contents.',
            synthetic=True,
            metadata={'type': 'file_ingestion', 'file': file_path}
        )

    def inject_narrative_bridge(self, reason: str, context_notes: str = ''):
        """Insert a narrative bridge when context has been edited.

        Used during migration, cloning, or manual context surgery to
        prevent the agent from feeling disoriented by discontinuities.
        """
        content = f'[Session context note: {reason}]'
        if context_notes:
            content += f'\n\nRelevant context: {context_notes}'
        self.append(
            'user',
            content,
            synthetic=True,
            metadata={'type': 'narrative_bridge', 'reason': reason}
        )
        self.append(
            'assistant',
            f'Understood. {reason} I\'ll proceed with this context.',
            synthetic=True,
            metadata={'type': 'narrative_bridge', 'reason': reason}
        )

    def to_messages(self) -> List[Dict]:
        """Export as OpenAI-compatible messages array.

        This is the common wire format that all API endpoints accept.
        System prompt becomes the first message.
        """
        messages = []
        if self.system_prompt:
            messages.append({'role': 'system', 'content': self.system_prompt})
        for turn in self.turns:
            messages.append({'role': turn.role, 'content': turn.content})
        return messages

    @classmethod
    def from_messages(cls, messages: List[Dict]) -> 'AgentContext':
        """Import from an OpenAI-compatible messages array."""
        ctx = cls()
        for msg in messages:
            if msg['role'] == 'system' and not ctx.turns:
                ctx.system_prompt = msg['content']
            else:
                ctx.append(msg['role'], msg['content'])
        return ctx


# ============================================================================
# INFERENCE TRACES — the agent's understanding of its knowledge
# ============================================================================

@dataclass
class InferenceTrace:
    """An agent's analyzed understanding of a knowledge artifact.

    Produced by having an agent read a file/block in context and
    articulate how it connects to everything else. Richer than
    embeddings because it captures relationships and interfaces
    in natural language any AI can read.
    """
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    file_path: str = ''
    file_hash: str = ''
    block_name: Optional[str] = None     # function/class name, if block-level
    block_range: Optional[Tuple[int, int]] = None  # (start_line, end_line)

    analysis: str = ''
    # Natural language: "This function takes a DB connection and a file hash,
    # checks the files table, returns the row or None. Called by _should_skip
    # and pack_files. Assumes connection is already open."

    connections: List[str] = field(default_factory=list)
    # References to other files/blocks this trace identifies as related.
    # e.g. ['pack_files in mimepack.py', 'session_db context manager']

    model_used: Optional[str] = None     # which model generated this trace
    generated: float = field(default_factory=time.time)
    confidence: float = 1.0              # 0-1, can flag for re-analysis


# ============================================================================
# KNOWLEDGE STORE — files the agent has ingested
# ============================================================================

@dataclass
class KnowledgeEntry:
    """A file that an agent has in its knowledge base."""
    file_path: str
    file_hash: str
    content: bytes
    turn_loaded: int = 0         # which turn in the narrative loaded this
    traces: List[InferenceTrace] = field(default_factory=list)


# ============================================================================
# THE AGENT
# ============================================================================

@dataclass
class Agent:
    """A complete agent: identity + narrative + knowledge + understanding.

    This is the unit of serialization. Everything needed to revive an
    agent in any runtime is here.
    """
    manifest: AgentManifest = field(default_factory=AgentManifest)
    context: AgentContext = field(default_factory=AgentContext)
    knowledge: Dict[str, KnowledgeEntry] = field(default_factory=dict)
    # keyed by file_hash

    def ingest_file(self, file_path: str, content: bytes,
                    inject_narrative: bool = True) -> str:
        """Add a file to the agent's knowledge and optionally inject
        it into the narrative context.

        Returns the file hash.
        """
        import hashlib
        file_hash = hashlib.sha256(content).hexdigest()

        self.knowledge[file_hash] = KnowledgeEntry(
            file_path=file_path,
            file_hash=file_hash,
            content=content,
            turn_loaded=len(self.context.turns),
        )

        if file_hash not in self.manifest.knowledge_hashes:
            self.manifest.knowledge_hashes.append(file_hash)

        if inject_narrative:
            try:
                text = content.decode('utf-8')
            except UnicodeDecodeError:
                text = f'[Binary file: {len(content)} bytes]'
            self.context.inject_file_read(file_path, text)

        self.manifest.touch()
        return file_hash

    def add_trace(self, file_hash: str, trace: InferenceTrace):
        """Attach an inference trace to a knowledge entry."""
        if file_hash in self.knowledge:
            self.knowledge[file_hash].traces.append(trace)

    def get_traces_for(self, file_hash: str) -> List[InferenceTrace]:
        """Get all inference traces for a file."""
        entry = self.knowledge.get(file_hash)
        return entry.traces if entry else []


# ============================================================================
# SERIALIZATION — to/from mimepack universal format
# ============================================================================

def serialize_agent(agent: Agent) -> bytes:
    """Serialize an agent to a mimepack-compatible bundle.

    The output is a JSON manifest + JSONL narrative + knowledge files,
    all concatenated into a single self-describing blob.

    Format:
      {"type": "agent_manifest", ...}
      {"type": "turn", ...}
      {"type": "turn", ...}
      ...
      {"type": "knowledge", "file_hash": "...", "file_path": "...", "content_b64": "..."}
      {"type": "trace", "file_hash": "...", ...}
    """
    import base64
    records = []

    # Manifest
    manifest_dict = asdict(agent.manifest)
    manifest_dict['type'] = 'agent_manifest'
    manifest_dict['format_version'] = '0.1.0'
    records.append(manifest_dict)

    # System prompt (separate record for clarity)
    records.append({
        'type': 'system_prompt',
        'content': agent.context.system_prompt,
    })

    # Narrative turns
    for turn in agent.context.turns:
        record = {
            'type': 'turn',
            'turn_id': turn.turn_id,
            'role': turn.role,
            'content': turn.content,
            'timestamp': turn.timestamp,
            'synthetic': turn.synthetic,
            'metadata': turn.metadata,
        }
        records.append(record)

    # Knowledge entries
    for file_hash, entry in agent.knowledge.items():
        record = {
            'type': 'knowledge',
            'file_hash': entry.file_hash,
            'file_path': entry.file_path,
            'turn_loaded': entry.turn_loaded,
        }
        try:
            record['content'] = entry.content.decode('utf-8')
        except UnicodeDecodeError:
            record['content_b64'] = base64.b64encode(entry.content).decode('ascii')
        records.append(record)

    # Inference traces
    for file_hash, entry in agent.knowledge.items():
        for trace in entry.traces:
            record = {
                'type': 'trace',
                'trace_id': trace.trace_id,
                'file_hash': trace.file_hash,
                'file_path': trace.file_path,
                'block_name': trace.block_name,
                'block_range': trace.block_range,
                'analysis': trace.analysis,
                'connections': trace.connections,
                'model_used': trace.model_used,
                'generated': trace.generated,
                'confidence': trace.confidence,
            }
            records.append(record)

    return '\n'.join(json.dumps(r) for r in records).encode('utf-8')


def deserialize_agent(data: bytes) -> Agent:
    """Deserialize an agent from a mimepack bundle."""
    import base64
    agent = Agent()

    for line in data.decode('utf-8').strip().split('\n'):
        if not line.strip():
            continue
        record = json.loads(line)
        rtype = record.get('type')

        if rtype == 'agent_manifest':
            # Strip non-manifest fields
            for skip in ('type', 'format_version'):
                record.pop(skip, None)
            agent.manifest = AgentManifest(**record)

        elif rtype == 'system_prompt':
            agent.context.system_prompt = record.get('content', '')

        elif rtype == 'turn':
            turn = Turn(
                role=record['role'],
                content=record['content'],
                turn_id=record.get('turn_id', uuid.uuid4().hex[:8]),
                timestamp=record.get('timestamp', 0),
                synthetic=record.get('synthetic', False),
                metadata=record.get('metadata', {}),
            )
            agent.context.turns.append(turn)

        elif rtype == 'knowledge':
            if 'content_b64' in record:
                content = base64.b64decode(record['content_b64'])
            else:
                content = record.get('content', '').encode('utf-8')

            entry = KnowledgeEntry(
                file_path=record['file_path'],
                file_hash=record['file_hash'],
                content=content,
                turn_loaded=record.get('turn_loaded', 0),
            )
            agent.knowledge[entry.file_hash] = entry

        elif rtype == 'trace':
            trace = InferenceTrace(
                trace_id=record.get('trace_id', ''),
                file_path=record.get('file_path', ''),
                file_hash=record.get('file_hash', ''),
                block_name=record.get('block_name'),
                block_range=tuple(record['block_range']) if record.get('block_range') else None,
                analysis=record.get('analysis', ''),
                connections=record.get('connections', []),
                model_used=record.get('model_used'),
                generated=record.get('generated', 0),
                confidence=record.get('confidence', 1.0),
            )
            # Attach to knowledge entry if it exists
            fh = trace.file_hash
            if fh in agent.knowledge:
                agent.knowledge[fh].traces.append(trace)

    return agent


# ============================================================================
# AGENT RUNTIME PROTOCOL
# ============================================================================

@runtime_checkable
class AgentRuntime(Protocol):
    """How an agent's context is managed and inference is called.

    Three implementations:
      CLIRuntime     — agent lives inside a CLI, adapter reads/writes context
      BaremetalRuntime — agent lives in PIE's process, context in memory
      PIERuntime     — agent is actually another PIE node (recursive composition)
    """

    agent: Agent

    def get_context(self) -> List[Dict]:
        """Export current context as OpenAI-compatible messages."""
        ...

    def append_turn(self, role: str, content: Any, **kwargs) -> Turn:
        """Append a turn to the agent's narrative."""
        ...

    def call_inference(self, **api_kwargs) -> str:
        """Call the inference endpoint and return the response.
        Appends both the (implicit) user turn and assistant response."""
        ...

    def inject_files(self, files: List[Tuple[str, bytes]],
                     narrative: bool = True):
        """Inject files into the agent's knowledge and optionally
        into the narrative context."""
        ...

    def estimate_usage(self) -> Tuple[int, int]:
        """Return (current_tokens, max_tokens)."""
        ...

    def serialize(self) -> bytes:
        """Serialize the agent to the universal format."""
        ...

    @classmethod
    def deserialize(cls, data: bytes, **config) -> 'AgentRuntime':
        """Deserialize an agent into this runtime."""
        ...


# ============================================================================
# BAREMETAL RUNTIME — simplest implementation, no CLI
# ============================================================================

class BaremetalRuntime:
    """Agent lives in PIE's own process. Context is an in-memory list.
    Inference is a direct API call. No CLI involved.

    This is the default for machine-facing agents (file specialists,
    trace generators, etc.) that don't need a UI.
    """

    def __init__(self, agent: Agent, *,
                 api_base: str = 'https://api.openai.com/v1',
                 api_key: Optional[str] = None,
                 model: str = 'gpt-4o-mini',
                 max_tokens: int = 128000):
        self.agent = agent
        self.api_base = api_base
        self.api_key = api_key or os.environ.get('OPENAI_API_KEY', '')
        self.model = model
        self.max_tokens = max_tokens

    def get_context(self) -> List[Dict]:
        return self.agent.context.to_messages()

    def append_turn(self, role: str, content: Any, **kwargs) -> Turn:
        return self.agent.context.append(role, content, **kwargs)

    def call_inference(self, user_message: Optional[str] = None,
                       **api_kwargs) -> str:
        """Call the inference endpoint.

        If user_message is provided, it's appended as a user turn first.
        The assistant response is appended to the narrative and returned.
        """
        if user_message:
            self.append_turn('user', user_message)

        messages = self.get_context()

        # Direct API call — no CLI intermediary
        import urllib.request
        payload = {
            'model': self.model,
            'messages': messages,
            **api_kwargs,
        }

        req = urllib.request.Request(
            f'{self.api_base}/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {self.api_key}',
            },
        )

        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
            response_text = result['choices'][0]['message']['content']
        except Exception as e:
            response_text = f'[Inference error: {e}]'

        self.append_turn('assistant', response_text)
        self.agent.manifest.touch()
        return response_text

    def inject_files(self, files: List[Tuple[str, bytes]],
                     narrative: bool = True):
        for file_path, content in files:
            self.agent.ingest_file(file_path, content,
                                   inject_narrative=narrative)

    def estimate_usage(self) -> Tuple[int, int]:
        return (self.agent.context.token_estimate, self.max_tokens)

    def serialize(self) -> bytes:
        return serialize_agent(self.agent)

    @classmethod
    def deserialize(cls, data: bytes, **config) -> 'BaremetalRuntime':
        agent = deserialize_agent(data)
        return cls(agent, **config)
