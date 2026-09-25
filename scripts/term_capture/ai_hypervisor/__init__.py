"""
AI CLI Hypervisor

Encapsulates AI CLI tools from three angles:
- SHELL: Command interception, shell integration
- PTY: Terminal I/O capture and manipulation  
- EGRESS: Network traffic control and monitoring

This creates a controlled execution environment for AI assistants.
"""

from .hypervisor import AIHypervisor, HypervisorConfig
from .shell_layer import ShellLayer
from .pty_layer_v2 import PTYLayer
from .egress_layer import EgressLayer

__all__ = [
    'AIHypervisor',
    'HypervisorConfig', 
    'ShellLayer',
    'PTYLayer',
    'EgressLayer',
]
