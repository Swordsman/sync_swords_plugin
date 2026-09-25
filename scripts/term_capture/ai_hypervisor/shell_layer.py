#!/usr/bin/env python3
"""
SHELL Layer - Command interception via shell hooks.

Encapsulates AI tools at the shell level:
- Intercepts ALL commands via DEBUG trap (bash) or preexec (zsh)
- Tracks command timing, exit codes
- Can modify commands before execution
- Works with: bash, zsh (any POSIX shell extensible)

This replaces the fragile PATH-wrapping approach with proper shell hooks.
"""

import os
import sys
import json
import subprocess
from typing import Optional, List, Callable, Dict
from pathlib import Path
import threading
import socket
import tempfile


class ShellLayer:
    """
    Shell command interception using shell hooks (DEBUG trap, preexec).
    
    Spawns a shell with hooks that report all commands to the hypervisor.
    """
    
    KNOWN_AI_TOOLS = {
        'claude': 'anthropic',
        'claude-code': 'anthropic',
        'aider': 'aider-ai',
        'sgpt': 'shell-gpt',
        'mods': 'charmbracelet',
        'gpt': 'various',
        'llm': 'simonw',
        'ai': 'generic',
        'codex': 'openai',
        'openai': 'openai',
        'kimi': 'moonshot',
    }
    
    def __init__(self, 
                 log_file: Optional[Path] = None,
                 on_command: Optional[Callable[[str, List[str]], None]] = None,
                 command_filter: Optional[Callable[[str, List[str]], bool]] = None):
        self.log_file = log_file
        self.on_command = on_command
        self.command_filter = command_filter
        
        self._hook_script: Optional[Path] = None
        self._socket_path: Optional[Path] = None
        self._socket_thread: Optional[threading.Thread] = None
        self._command_count = 0
        self._running = False
    
    def install(self):
        """Install shell hooks. Creates hook script and socket."""
        if self._running:
            return
        
        # Create hook script
        self._hook_script = Path(__file__).parent / 'shell_hooks.sh'
        
        # Create communication socket
        self._socket_path = Path(tempfile.gettempdir()) / f'ai_hv_{os.getpid()}.sock'
        
        self._running = True
        self._start_socket_listener()
    
    def _start_socket_listener(self):
        """Start background thread to listen for shell hook messages."""
        def listen():
            if self._socket_path.exists():
                self._socket_path.unlink()
            
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(str(self._socket_path))
            sock.listen(5)
            sock.settimeout(1.0)  # Allow checking _running periodically
            
            while self._running:
                try:
                    conn, _ = sock.accept()
                    with conn:
                        data = conn.recv(4096).decode('utf-8', errors='replace')
                        for line in data.strip().split('\n'):
                            self._handle_hook_message(line)
                except socket.timeout:
                    continue
                except OSError:
                    break
            
            sock.close()
        
        self._socket_thread = threading.Thread(target=listen, daemon=True)
        self._socket_thread.start()
    
    def _handle_hook_message(self, msg: str):
        """Handle message from shell hook."""
        if msg.startswith('CMD:'):
            cmd = msg[4:]
            self._command_count += 1
            
            # Parse command
            parts = cmd.split()
            if parts:
                if self.on_command:
                    self.on_command(parts[0], parts[1:])
    
    def get_shell_env(self) -> Dict[str, str]:
        """Get environment variables to inject into shell."""
        env = {
            'AI_HV_LOG_FILE': str(self.log_file) if self.log_file else '',
            'AI_HV_SOCKET': str(self._socket_path) if self._socket_path else '',
            'AI_HV_ACTIVE': '1',
        }
        return env
    
    def get_shell_rc(self, shell: str = 'bash') -> str:
        """Generate shell RC snippet to load hooks."""
        if shell in ('bash', 'zsh'):
            return f'''
# AI Hypervisor hooks
export AI_HV_LOG_FILE="{self.log_file or ''}"
export AI_HV_SOCKET="{self._socket_path or ''}"
export AI_HV_ACTIVE=1
source "{self._hook_script}"
'''
        return ''
    
    def spawn_shell(self, shell: str = '/bin/bash', cwd: Optional[Path] = None) -> subprocess.Popen:
        """
        Spawn a shell with hooks enabled.
        
        Returns a Popen object for the shell.
        """
        # Create temp rcfile that sources user's rc + our hooks
        rcfile = self._create_rcfile(shell)
        
        env = os.environ.copy()
        env.update(self.get_shell_env())
        
        cmd = [shell, '--rcfile', str(rcfile), '-i']
        
        return subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    
    def _create_rcfile(self, shell: str) -> Path:
        """Create a temp rcfile that loads user config + hooks."""
        # Find user's actual rcfile
        user_rc = None
        if 'bash' in shell:
            user_rc = Path.home() / '.bashrc'
        elif 'zsh' in shell:
            user_rc = Path.home() / '.zshrc'
        
        rc_content = f'''#!/bin/bash
# AI Hypervisor shell wrapper

# Source user's original config
if [ -f "{user_rc}" ]; then
    source "{user_rc}"
fi

# Load hypervisor hooks
export AI_HV_LOG_FILE="{self.log_file or ''}"
export AI_HV_SOCKET="{self._socket_path or ''}"
export AI_HV_ACTIVE=1
source "{self._hook_script}"

# Mark that we're in hypervisor shell
export PS1="[AI-HV] $PS1"
'''
        
        fd, path = tempfile.mkstemp(suffix='.sh', prefix='ai_hv_rc_')
        with os.fdopen(fd, 'w') as f:
            f.write(rc_content)
        
        return Path(path)
    
    def uninstall(self):
        """Remove shell hooks and cleanup."""
        self._running = False
        
        if self._socket_thread:
            self._socket_thread.join(timeout=2)
        
        if self._socket_path and self._socket_path.exists():
            self._socket_path.unlink()
    
    def is_ai_tool(self, command: str) -> bool:
        """Check if command is a known AI tool."""
        base = command.split('/')[-1]
        return base in self.KNOWN_AI_TOOLS
    
    def analyze_command(self, command: str, args: List[str]) -> Dict:
        """Analyze a command for AI tool characteristics."""
        base = command.split('/')[-1]
        
        return {
            'command': command,
            'base_name': base,
            'args': args,
            'is_known_ai_tool': base in self.KNOWN_AI_TOOLS,
            'tool_vendor': self.KNOWN_AI_TOOLS.get(base),
        }
