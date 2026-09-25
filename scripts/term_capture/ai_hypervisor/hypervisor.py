#!/usr/bin/env python3
"""
AI Hypervisor - Main coordinator for the three-layer encapsulation.
"""

import os
import sys
import json
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Callable, Any
from pathlib import Path
from datetime import datetime

try:
    from .shell_layer import ShellLayer
    from .pty_layer_v2 import PTYLayer
    from .egress_layer import EgressLayer
    from .protocol_bridge import ProtocolBridge, HypervisorMCPServer
    from .extensions import ExtensionManager
except ImportError:
    from shell_layer import ShellLayer
    from pty_layer_v2 import PTYLayer
    from egress_layer import EgressLayer
    from protocol_bridge import ProtocolBridge, HypervisorMCPServer
    from extensions import ExtensionManager


@dataclass
class HypervisorConfig:
    """Configuration for AI hypervisor."""
    
    # Logging
    log_dir: Path = field(default_factory=lambda: Path.home() / '.ai_hypervisor')
    log_raw_pty: bool = True
    log_text_pty: bool = True
    log_network: bool = True
    log_commands: bool = True
    
    # Quota management
    daily_token_limit: Optional[int] = None
    daily_cost_limit: Optional[float] = None
    
    # Rate limiting
    requests_per_minute: Optional[int] = None
    
    # Network control
    allow_internet: bool = True
    allowed_hosts: List[str] = field(default_factory=list)
    blocked_hosts: List[str] = field(default_factory=list)
    
    # Shell integration
    shell_hooks: bool = True
    prompt_prefix: str = "[AI] "
    
    # Callbacks
    on_quota_exceeded: Optional[Callable] = None
    on_usage_update: Optional[Callable] = None


@dataclass
class UsageStats:
    """Aggregated usage statistics."""
    session_start: float
    commands_executed: int = 0
    prompts_submitted: int = 0
    
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    
    estimated_cost_usd: float = 0.0
    
    network_requests: int = 0
    network_bytes_in: int = 0
    network_bytes_out: int = 0
    
    def to_dict(self) -> Dict:
        return {
            'session_start': self.session_start,
            'session_start_iso': datetime.fromtimestamp(self.session_start).isoformat(),
            'commands_executed': self.commands_executed,
            'prompts_submitted': self.prompts_submitted,
            'input_tokens': self.input_tokens,
            'output_tokens': self.output_tokens,
            'total_tokens': self.total_tokens,
            'estimated_cost_usd': self.estimated_cost_usd,
            'network_requests': self.network_requests,
            'network_bytes_in': self.network_bytes_in,
            'network_bytes_out': self.network_bytes_out,
        }


class AIHypervisor:
    """
    Main hypervisor coordinating SHELL, PTY, and EGRESS layers.
    
    Creates a sandboxed environment for AI CLI tools with:
    - Unified logging across all layers
    - Quota enforcement (tokens, cost, rate)
    - Network traffic monitoring/filtering
    - Session replay capability
    
    Example:
        config = HypervisorConfig(
            daily_token_limit=100000,
            daily_cost_limit=5.00,
        )
        
        with AIHypervisor(config) as hv:
            # All three layers active
            hv.run_ai_tool('claude', ['--some-flag'])
    """
    
    def __init__(self, config: Optional[HypervisorConfig] = None):
        self.config = config or HypervisorConfig()
        self.config.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.stats = UsageStats(session_start=datetime.now().timestamp())
        self._lock = threading.Lock()
        
        # Three encapsulation layers
        self.shell: Optional[ShellLayer] = None
        self.pty: Optional[PTYLayer] = None
        self.egress: Optional[EgressLayer] = None
        
        # Protocol handling
        self.protocol_bridge: Optional[ProtocolBridge] = None
        self.mcp_server: Optional[HypervisorMCPServer] = None
        
        # Extension system
        self.extensions = ExtensionManager()
        
        # Active session state
        self.current_ai_tool: Optional[str] = None
        self.session_log: List[Dict] = []
        
    def __enter__(self):
        """Context manager entry - initialize all layers."""
        self.initialize()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup all layers."""
        self.shutdown()
        return False
    
    def initialize(self):
        """Initialize all three layers."""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        session_dir = self.config.log_dir / f'session_{timestamp}'
        session_dir.mkdir(exist_ok=True)
        
        # Initialize SHELL layer
        if self.config.shell_hooks:
            self.shell = ShellLayer(
                log_file=session_dir / 'commands.jsonl' if self.config.log_commands else None,
                on_command=self._on_shell_command
            )
            self.shell.install()
        
        # Initialize PTY layer
        self.pty = PTYLayer(
            raw_log=session_dir / 'pty_raw.bin' if self.config.log_raw_pty else None,
            text_log=session_dir / 'pty_text.log' if self.config.log_text_pty else None,
            on_output=self._on_pty_output,
            on_usage_pattern=self._on_usage_detected
        )
        
        # Initialize EGRESS layer
        if self.config.log_network:
            self.egress = EgressLayer(
                log_file=session_dir / 'network.jsonl',
                allow_internet=self.config.allow_internet,
                allowed_hosts=self.config.allowed_hosts,
                blocked_hosts=self.config.blocked_hosts,
                on_request=self._on_network_request
            )
            self.egress.enable()
        
        # Initialize Protocol Bridge
        self.protocol_bridge = ProtocolBridge()
        self.protocol_bridge.add_event_callback(self._on_protocol_event)
        self.protocol_bridge.start()
        
        # Wire ProtocolBridge to PTY layer
        if self.pty and self.protocol_bridge:
            self.pty.protocol_bridge = self.protocol_bridge
        
        # Initialize MCP Server for hypervisor introspection
        self.mcp_server = HypervisorMCPServer(self)
        self.mcp_server.start(transport='stdio')
        
        # Initialize extensions
        ext_results = self.extensions.initialize_all(self)
        for name, success in ext_results.items():
            if not success:
                print(f"[AI-HV] Warning: Extension {name} failed to initialize")
    
    def shutdown(self):
        """Shutdown all layers and save session data."""
        # Final stats
        self._save_session_summary()
        
        # Cleanup layers
        if self.shell:
            self.shell.uninstall()
        if self.pty:
            self.pty.cleanup()
        if self.egress:
            self.egress.disable()
        if self.protocol_bridge:
            self.protocol_bridge.stop()
        if self.mcp_server:
            # MCP server stops when stdin closes
            pass
        
        # Shutdown extensions
        self.extensions.shutdown_all()
    
    def run_shell_session(self, shell: str = '/bin/bash') -> int:
        """
        Run an interactive shell session with full hypervisor monitoring.
        
        This is the main entry point - spawns a shell with hooks, PTY,
        and egress monitoring active. User runs AI tools within this session.
        
        Args:
            shell: Shell to spawn (bash, zsh, etc)
            
        Returns:
            Exit code from shell
        """
        import termios
        import tty
        import select
        
        print(f"[AI-HV] Starting hypervisor shell session...")
        print(f"[AI-HV] Shell: {shell}")
        print(f"[AI-HV] Type 'exit' to quit\n")
        
        # Get shell with hooks
        if self.shell:
            rcfile = self.shell._create_rcfile(shell)
            cmd = [shell, '--rcfile', str(rcfile), '-i']
            env = os.environ.copy()
            env.update(self.shell.get_shell_env())
        else:
            cmd = [shell, '-i']
            env = os.environ.copy()
        
        # Apply egress controls
        if self.egress:
            env = self.egress.wrap_environment(env)
        
        # Run through PTY for screen capture
        return self.pty.run(cmd, env=env)
    
    def run_ai_tool(self, tool_name: str, args: List[str] = None, 
                   env: Optional[Dict[str, str]] = None) -> int:
        """
        Run an AI CLI tool under hypervisor control.
        
        Args:
            tool_name: Name of the tool (claude, aider, sgpt, etc)
            args: Command line arguments
            env: Additional environment variables
            
        Returns:
            Exit code from the tool
        """
        self.current_ai_tool = tool_name
        args = args or []
        
        # Pre-execution checks
        if not self._check_quotas():
            return 1
        
        # Log session start
        self._log_event('tool_start', {
            'tool': tool_name,
            'args': args,
            'stats': self.stats.to_dict()
        })
        
        # Prepare environment
        tool_env = os.environ.copy()
        if env:
            tool_env.update(env)
        
        # Add hypervisor metadata to environment
        tool_env['_AI_HYPERVISOR'] = '1'
        tool_env['_AI_HYPERVISOR_SESSION'] = str(self.config.log_dir)
        
        # Apply egress controls if enabled
        if self.egress:
            tool_env = self.egress.wrap_environment(tool_env)
        
        # Run through PTY layer
        cmd = [tool_name] + args
        exit_code = self.pty.run(cmd, env=tool_env)
        
        # Log session end
        self._log_event('tool_end', {
            'tool': tool_name,
            'exit_code': exit_code,
            'stats': self.stats.to_dict()
        })
        
        self.current_ai_tool = None
        return exit_code
    
    def _check_quotas(self) -> bool:
        """Check if quotas exceeded."""
        with self._lock:
            if self.config.daily_token_limit:
                if self.stats.total_tokens >= self.config.daily_token_limit:
                    msg = f"Daily token limit exceeded: {self.stats.total_tokens:,} / {self.config.daily_token_limit:,}"
                    print(f"[HYPERVISOR] {msg}", file=sys.stderr)
                    if self.config.on_quota_exceeded:
                        self.config.on_quota_exceeded('token_limit', msg)
                    return False
            
            if self.config.daily_cost_limit:
                if self.stats.estimated_cost_usd >= self.config.daily_cost_limit:
                    msg = f"Daily cost limit exceeded: ${self.stats.estimated_cost_usd:.2f} / ${self.config.daily_cost_limit:.2f}"
                    print(f"[HYPERVISOR] {msg}", file=sys.stderr)
                    if self.config.on_quota_exceeded:
                        self.config.on_quota_exceeded('cost_limit', msg)
                    return False
        
        return True
    
    def _on_shell_command(self, command: str, args: List[str]):
        """Callback from SHELL layer."""
        with self._lock:
            self.stats.commands_executed += 1
        
        self._log_event('shell_command', {
            'command': command,
            'args': args
        })
    
    def _on_pty_output(self, data: str, is_input: bool):
        """Callback from PTY layer."""
        # Could do real-time analysis here
        pass
    
    def _on_usage_detected(self, usage_type: str, data: Dict):
        """Callback when PTY layer detects usage pattern."""
        with self._lock:
            if usage_type == 'tokens':
                self.stats.input_tokens += data.get('input', 0)
                self.stats.output_tokens += data.get('output', 0)
                self.stats.total_tokens = self.stats.input_tokens + self.stats.output_tokens
                
                if 'cost' in data:
                    self.stats.estimated_cost_usd += data['cost']
            
            elif usage_type == 'prompt':
                self.stats.prompts_submitted += 1
        
        # Notify callbacks
        if self.config.on_usage_update:
            self.config.on_usage_update(usage_type, data, self.stats)
        
        # Check quotas after update
        self._check_quotas()
        
        self._log_event('usage', {
            'type': usage_type,
            'data': data,
            'cumulative': self.stats.to_dict()
        })
    
    def _on_network_request(self, host: str, method: str, 
                           bytes_in: int, bytes_out: int):
        """Callback from EGRESS layer."""
        with self._lock:
            self.stats.network_requests += 1
            self.stats.network_bytes_in += bytes_in
            self.stats.network_bytes_out += bytes_out
        
        self._log_event('network', {
            'host': host,
            'method': method,
            'bytes_in': bytes_in,
            'bytes_out': bytes_out
        })
    
    def _on_protocol_event(self, event):
        """Callback from Protocol Bridge."""
        self._log_event('protocol', {
            'protocol': event.protocol,
            'direction': event.direction,
            'message_type': event.message.get('method') or 
                          ('response' if 'result' in event.message else 'unknown'),
            'size_bytes': event.size_bytes
        })
    
    def _log_event(self, event_type: str, data: Dict):
        """Log an event to session log."""
        event = {
            'timestamp': datetime.now().timestamp(),
            'type': event_type,
            'data': data
        }
        self.session_log.append(event)
    
    def _save_session_summary(self):
        """Save final session summary."""
        summary = {
            'config': {
                'log_dir': str(self.config.log_dir),
                'daily_token_limit': self.config.daily_token_limit,
                'daily_cost_limit': self.config.daily_cost_limit,
            },
            'stats': self.stats.to_dict(),
            'events': self.session_log
        }
        
        summary_file = self.config.log_dir / 'session_summary.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
    
    def get_status(self) -> Dict:
        """Get current hypervisor status."""
        with self._lock:
            return {
                'active': self.current_ai_tool is not None,
                'current_tool': self.current_ai_tool,
                'stats': self.stats.to_dict(),
                'quotas': {
                    'token_limit': self.config.daily_token_limit,
                    'cost_limit': self.config.daily_cost_limit,
                    'token_percent': (self.stats.total_tokens / self.config.daily_token_limit * 100) 
                                     if self.config.daily_token_limit else None,
                    'cost_percent': (self.stats.estimated_cost_usd / self.config.daily_cost_limit * 100)
                                    if self.config.daily_cost_limit else None,
                }
            }
