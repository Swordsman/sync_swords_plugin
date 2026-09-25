#!/usr/bin/env python3
"""
Vendored from term_capture/ai_hypervisor/pty_layer_v2.py (2026-06-08).
Insulates xylem from Pisces language rebuild.

PTY Layer v2 - 2D Screen State Tracking with Scrollback Commit Log

Captures TUI output efficiently by:
- Maintaining 2D screen buffer (rows x cols)
- Committing scrolled lines to persistent scrollback
- Ignoring transient UI (cursors, animations, spinners)
- Per-tool filter rules for pattern-based capture
"""

import os
import sys
import pty
import fcntl
import termios
import struct
import select
import re
import threading
from pathlib import Path
from typing import Optional, List, Callable, Dict, Set, Tuple
from dataclasses import dataclass, field
from collections import deque


@dataclass
class ScreenCell:
    """Single cell in the screen buffer."""
    char: str = ' '
    attrs: int = 0  # SGR attributes (bold, color, etc)


@dataclass
class CaptureRule:
    """Rule for what to capture from screen/scrollback."""
    name: str
    pattern: re.Pattern
    capture_type: str = 'scrollback'  # 'scrollback', 'screen', 'both'
    ignore_in_scrollback: bool = False  # If True, don't log to scrollback even if matched
    extract_groups: bool = True


@dataclass
class ToolProfile:
    """Profile for a specific AI tool's TUI behavior."""
    name: str
    
    # Screen dimensions (can be dynamic)
    default_rows: int = 24
    default_cols: int = 80
    
    # Noise patterns to ignore in scrollback
    scrollback_ignore_patterns: List[re.Pattern] = field(default_factory=list)
    
    # Screen patterns to capture (transient UI worth noting)
    screen_capture_rules: List[CaptureRule] = field(default_factory=list)
    
    # Scrollback patterns to capture (completed output)
    scrollback_capture_rules: List[CaptureRule] = field(default_factory=list)
    
    # Special handling
    detect_prompt: bool = True
    prompt_patterns: List[re.Pattern] = field(default_factory=list)


# Predefined tool profiles
CLAUDE_PROFILE = ToolProfile(
    name='claude',
    scrollback_ignore_patterns=[
        re.compile(r'^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏\s]*$'),  # Spinner chars
        re.compile(r'^\s*Thinking\.*\s*$', re.I),
        re.compile(r'^\s*\d+%\s*$'),  # Pure percentage
    ],
    screen_capture_rules=[
        CaptureRule(
            name='token_usage',
            pattern=re.compile(r'Tokens:\s*([\d,]+)\s*→\s*([\d,]+)'),
            capture_type='screen',
        ),
        CaptureRule(
            name='cost_display',
            pattern=re.compile(r'\$([\d.]+)'),
            capture_type='screen',
        ),
    ],
    scrollback_capture_rules=[
        CaptureRule(
            name='prompt_marker',
            pattern=re.compile(r'^>\s+(.+)'),
            capture_type='scrollback',
        ),
    ],
    prompt_patterns=[
        re.compile(r'^>\s*$'),  # Empty prompt
        re.compile(r'^>\s+.+'),  # Prompt with text
    ],
)

AIDER_PROFILE = ToolProfile(
    name='aider',
    scrollback_ignore_patterns=[
        re.compile(r'^\s*[-|/\\]\s*$'),  # Spinner
    ],
    screen_capture_rules=[
        CaptureRule(
            name='token_info',
            pattern=re.compile(r'(\d+)\s*tokens'),
        ),
    ],
)

GENERIC_PROFILE = ToolProfile(name='generic')


class ScreenBuffer:
    """
    2D screen buffer with scrollback commit log.
    
    Maintains:
    - Active screen buffer (current TUI state)
    - Scrollback buffer (completed, committed lines)
    - Dirty tracking for efficient updates
    """
    
    def __init__(self, rows: int = 24, cols: int = 80, 
                 scrollback_limit: int = 10000):
        self.rows = rows
        self.cols = cols
        self.scrollback_limit = scrollback_limit
        
        # 2D buffer: list of rows, each row is list of cells
        self.buffer: List[List[ScreenCell]] = [
            [ScreenCell() for _ in range(cols)] for _ in range(rows)
        ]
        
        # Scrollback is write-once commit log
        self.scrollback: deque = deque(maxlen=scrollback_limit)
        
        # Cursor position
        self.cursor_row = 0
        self.cursor_col = 0
        
        # Dirty tracking
        self.dirty_rows: Set[int] = set()
        self.dirty = False
        
        # ANSI parser state
        self._parse_buffer = ''
        self._csi_pattern = re.compile(r'\x1b\[([0-9;]*)([A-Za-z])')
        self._osc_pattern = re.compile(r'\x1b\]([^\x07\x1b]*)(?:\x07|\x1b\\)')
    
    def feed(self, data: bytes) -> Tuple[List[str], List[Dict]]:
        """
        Process raw terminal data.
        
        Returns:
            (new_scrollback_lines, screen_events)
        """
        text = data.decode('utf-8', errors='replace')
        new_scrollback = []
        screen_events = []
        
        for char in text:
            result = self._process_char(char)
            if result:
                event_type, content = result
                if event_type == 'scrollback':
                    new_scrollback.append(content)
                elif event_type == 'screen_event':
                    screen_events.append(content)
        
        return new_scrollback, screen_events
    
    def _process_char(self, char: str) -> Optional[Tuple[str, any]]:
        """Process single character, return event if triggered."""
        # ESC sequence handling
        if char == '\x1b':
            self._parse_buffer = char
            return None
        
        if self._parse_buffer:
            self._parse_buffer += char
            
            # Check for complete CSI sequence
            if self._parse_buffer.startswith('\x1b['):
                match = self._csi_pattern.match(self._parse_buffer)
                if match:
                    params, cmd = match.groups()
                    self._handle_csi(params, cmd)
                    self._parse_buffer = ''
                elif len(self._parse_buffer) > 32:  # Too long, probably garbage
                    self._parse_buffer = ''
            
            # Check for complete OSC sequence  
            elif self._parse_buffer.startswith('\x1b]'):
                match = self._osc_pattern.match(self._parse_buffer)
                if match:
                    self._parse_buffer = ''  # Ignore OSC (titles, etc)
                elif len(self._parse_buffer) > 256:
                    self._parse_buffer = ''
            
            # Other escapes (simple two-char)
            elif len(self._parse_buffer) == 2:
                self._handle_simple_escape(self._parse_buffer[1])
                self._parse_buffer = ''
            
            return None
        
        # Control characters
        if char == '\r':
            self.cursor_col = 0
            return None
        
        if char == '\n':
            # Line feed - commit current line if needed
            return self._line_feed()
        
        if char == '\t':
            self.cursor_col = ((self.cursor_col // 8) + 1) * 8
            if self.cursor_col >= self.cols:
                self.cursor_col = self.cols - 1
            return None
        
        if char == '\x08':  # Backspace
            if self.cursor_col > 0:
                self.cursor_col -= 1
            return None
        
        if char < ' ' and char not in ('\n', '\r', '\t'):
            # Other control chars - ignore
            return None
        
        # Printable character
        if self.cursor_row < self.rows and self.cursor_col < self.cols:
            self.buffer[self.cursor_row][self.cursor_col] = ScreenCell(char=char)
            self.cursor_col += 1
            self.dirty_rows.add(self.cursor_row)
            self.dirty = True
            
            if self.cursor_col >= self.cols:
                self.cursor_col = 0
                self.cursor_row += 1
                if self.cursor_row >= self.rows:
                    return self._scroll_up()
        
        return None
    
    def _line_feed(self) -> Optional[Tuple[str, str]]:
        """Handle line feed - returns scrollback event if line scrolled."""
        self.cursor_row += 1
        self.cursor_col = 0
        
        if self.cursor_row >= self.rows:
            return self._scroll_up()
        
        return None
    
    def _scroll_up(self) -> Tuple[str, str]:
        """Scroll screen up, return top line as scrollback."""
        top_line = self._render_line(0)
        
        # Shift up
        self.buffer = self.buffer[1:] + [[ScreenCell() for _ in range(self.cols)]]
        self.cursor_row = self.rows - 1
        
        # Mark all dirty
        self.dirty_rows = set(range(self.rows))
        self.dirty = True
        
        return ('scrollback', top_line)
    
    def _render_line(self, row: int) -> str:
        """Render a line to string, stripping trailing spaces."""
        line = self.buffer[row]
        chars = [cell.char for cell in line]
        # Strip trailing spaces
        while chars and chars[-1] == ' ':
            chars.pop()
        return ''.join(chars) if chars else ''
    
    def _handle_csi(self, params: str, cmd: str):
        """Handle CSI escape sequence."""
        args = [int(x) if x else 0 for x in params.split(';')]
        if not args:
            args = [0]
        
        n = args[0] if args else 1
        
        if cmd == 'A':  # CUU - Cursor Up
            self.cursor_row = max(0, self.cursor_row - n)
        
        elif cmd == 'B':  # CUD - Cursor Down  
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
        
        elif cmd == 'C':  # CUF - Cursor Forward
            self.cursor_col = min(self.cols - 1, self.cursor_col + n)
        
        elif cmd == 'D':  # CUB - Cursor Back
            self.cursor_col = max(0, self.cursor_col - n)
        
        elif cmd == 'E':  # CNL - Cursor Next Line
            self.cursor_row = min(self.rows - 1, self.cursor_row + n)
            self.cursor_col = 0
        
        elif cmd == 'F':  # CPL - Cursor Previous Line
            self.cursor_row = max(0, self.cursor_row - n)
            self.cursor_col = 0
        
        elif cmd == 'G':  # CHA - Cursor Horizontal Absolute
            self.cursor_col = max(0, min(self.cols - 1, n - 1))
        
        elif cmd == 'H' or cmd == 'f':  # CUP - Cursor Position
            row = args[0] - 1 if len(args) > 0 else 0
            col = args[1] - 1 if len(args) > 1 else 0
            self.cursor_row = max(0, min(self.rows - 1, row))
            self.cursor_col = max(0, min(self.cols - 1, col))
        
        elif cmd == 'J':  # ED - Erase in Display
            mode = args[0] if args else 0
            if mode == 0:  # Clear from cursor to end
                for r in range(self.cursor_row, self.rows):
                    start = self.cursor_col if r == self.cursor_row else 0
                    for c in range(start, self.cols):
                        self.buffer[r][c] = ScreenCell()
            elif mode == 1:  # Clear from start to cursor
                for r in range(0, self.cursor_row + 1):
                    end = self.cursor_col + 1 if r == self.cursor_row else self.cols
                    for c in range(0, end):
                        self.buffer[r][c] = ScreenCell()
            elif mode == 2 or mode == 3:  # Clear entire display
                self.buffer = [[ScreenCell() for _ in range(self.cols)] for _ in range(self.rows)]
            self.dirty_rows = set(range(self.rows))
            self.dirty = True
        
        elif cmd == 'K':  # EL - Erase in Line
            mode = args[0] if args else 0
            if self.cursor_row < self.rows:
                if mode == 0:  # Clear to end of line
                    for c in range(self.cursor_col, self.cols):
                        self.buffer[self.cursor_row][c] = ScreenCell()
                elif mode == 1:  # Clear to start of line
                    for c in range(0, self.cursor_col + 1):
                        self.buffer[self.cursor_row][c] = ScreenCell()
                elif mode == 2:  # Clear entire line
                    for c in range(self.cols):
                        self.buffer[self.cursor_row][c] = ScreenCell()
                self.dirty_rows.add(self.cursor_row)
                self.dirty = True
        
        elif cmd == 'L':  # IL - Insert Lines
            # Insert n blank lines at cursor position
            for _ in range(n):
                self.buffer.insert(self.cursor_row, [ScreenCell() for _ in range(self.cols)])
                self.buffer.pop()
            self.dirty_rows = set(range(self.cursor_row, self.rows))
            self.dirty = True
        
        elif cmd == 'M':  # DL - Delete Lines
            # Delete n lines at cursor position
            for _ in range(n):
                if self.cursor_row < len(self.buffer):
                    del self.buffer[self.cursor_row]
                    self.buffer.append([ScreenCell() for _ in range(self.cols)])
            self.dirty_rows = set(range(self.cursor_row, self.rows))
            self.dirty = True
        
        elif cmd == 'm':  # SGR - Select Graphic Rendition
            # We track attrs but don't store detailed color info
            pass
    
    def _handle_simple_escape(self, char: str):
        """Handle simple two-char escape sequences."""
        if char == '7':  # DECSC - Save cursor
            self._saved_cursor = (self.cursor_row, self.cursor_col)
        elif char == '8':  # DECRC - Restore cursor
            if hasattr(self, '_saved_cursor'):
                self.cursor_row, self.cursor_col = self._saved_cursor
    
    def get_screen_text(self) -> str:
        """Get current screen content as text."""
        return '\n'.join(self._render_line(r) for r in range(self.rows))
    
    def get_scrollback(self) -> List[str]:
        """Get committed scrollback lines."""
        return list(self.scrollback)
    
    def commit_to_scrollback(self, line: str):
        """Manually commit a line to scrollback."""
        self.scrollback.append(line)


class PTYLayer:
    """
    PTY Layer with 2D screen tracking and per-tool profiles.
    Backward-compatible with v1 API.
    """
    
    # Usage patterns for various AI tools (v1 compat)
    USAGE_PATTERNS = {
        'claude': [
            r'Tokens:\s*([\d,]+)\s*→\s*([\d,]+)',
            r'([\d,]+)\s*→\s*([\d,]+)\s*tokens?',
        ],
        'aider': [
            r'([\d,]+)\s*tokens\s+([\d,]+)\s*sent',
            r'\$([\d.]+)\s+cost',
        ],
        'generic': [
            r'tokens?[\s:]*([\d,]+)',
            r'cost[\s:]*\$?([\d.]+)',
        ]
    }
    
    def __init__(self,
                 raw_log: Optional[Path] = None,
                 text_log: Optional[Path] = None,
                 on_output: Optional[Callable[[str, bool], None]] = None,
                 on_usage_pattern: Optional[Callable[[str, Dict], None]] = None,
                 profile: Optional[ToolProfile] = None,
                 on_scrollback: Optional[Callable[[str], None]] = None,
                 on_screen_event: Optional[Callable[[str, Dict], None]] = None):
        # v2 params
        self.profile = profile or GENERIC_PROFILE
        self.on_scrollback = on_scrollback
        self.on_screen_event = on_screen_event
        
        # v1 compat
        self.raw_log = raw_log
        self.text_log = text_log
        self.on_output = on_output
        self.on_usage_pattern = on_usage_pattern
        self._raw_file: Optional[BinaryIO] = None
        self._text_file: Optional[TextIO] = None
        
        self.screen = ScreenBuffer(
            rows=self.profile.default_rows,
            cols=self.profile.default_cols
        )
        
        self.master_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.running = False
        self.capture_thread: Optional[threading.Thread] = None
        self.protocol_bridge = None
    
    def run(self, command: List[str], env: Optional[Dict[str, str]] = None,
            interactive: bool = True) -> int:
        """
        Run a command in PTY with capture.
        
        Args:
            command: Command to run
            env: Environment variables
            interactive: If True, forward stdin/stdout for TUI interaction
        """
        # Auto-detect: if stdin is not a TTY, force non-interactive
        if interactive and not sys.stdin.isatty():
            interactive = False
        
        # Open log files
        if self.raw_log:
            self._raw_file = open(self.raw_log, 'wb')
        if self.text_log:
            self._text_file = open(self.text_log, 'w', encoding='utf-8')
        
        # Spawn PTY
        pid, master_fd = pty.fork()
        
        if pid == 0:
            # Child process
            size = struct.pack('HHHH', self.screen.rows, self.screen.cols, 0, 0)
            fcntl.ioctl(sys.stdout.fileno(), termios.TIOCSWINSZ, size)
            
            if env:
                os.environ.update(env)
            
            os.execvp(command[0], command)
        
        # Parent
        self.master_fd = master_fd
        self.pid = pid
        
        # Make non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        
        self.running = True
        
        if interactive:
            return self._run_interactive()
        else:
            self.capture_thread = threading.Thread(target=self._capture_loop)
            self.capture_thread.start()
            return self._run_noninteractive()
    
    def _run_noninteractive(self) -> int:
        """Run in non-interactive mode (capture only, no stdin forwarding)."""
        _, status = os.waitpid(self.pid, 0)
        self.running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=1)
        self._close_logs()
        
        return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
    
    def _run_interactive(self) -> int:
        """Run in interactive mode with proper TUI support."""
        import termios
        import tty
        
        # Try to set raw mode, fall back if stdin is not a TTY
        old_tty = None
        try:
            old_tty = termios.tcgetattr(sys.stdin)
            tty.setraw(sys.stdin.fileno())
        except (termios.error, OSError):
            # Not a TTY, fall back to non-interactive capture
            return self._run_noninteractive()
        
        try:
            while self.running:
                # Check both PTY (output) and stdin (input)
                readable, _, _ = select.select(
                    [self.master_fd, sys.stdin], [], [], 0.05
                )
                
                for fd in readable:
                    if fd == self.master_fd:
                        # Output from PTY -> stdout (with capture)
                        try:
                            data = os.read(self.master_fd, 4096)
                        except OSError:
                            self.running = False
                            break
                        
                        if not data:
                            self.running = False
                            break
                        
                        # Protocol bridge interception
                        if self.protocol_bridge:
                            data = self.protocol_bridge.process_pty_output(data)
                            if not data:
                                continue
                        
                        # Capture to log (side channel)
                        if self._raw_file:
                            self._raw_file.write(data)
                            self._raw_file.flush()
                        
                        # Parse for scrollback
                        new_scrollback, screen_events = self.screen.feed(data)
                        for line in new_scrollback:
                            if self._text_file:
                                self._text_file.write(line + '\n')
                                self._text_file.flush()
                            if self.on_output:
                                self.on_output(line, False)
                            self._check_patterns(line)
                            if self.on_scrollback:
                                self.on_scrollback(line)
                        
                        # Process screen events
                        for event in screen_events:
                            pass
                        
                        # Check screen for patterns
                        self._check_screen_patterns()
                        
                        # Pass to stdout for TUI rendering
                        os.write(sys.stdout.fileno(), data)
                    
                    elif fd == sys.stdin:
                        # Input from user -> PTY
                        try:
                            data = os.read(sys.stdin.fileno(), 1024)
                        except OSError:
                            break
                        
                        if not data:
                            self.running = False
                            break
                        
                        # Protocol bridge interception
                        if self.protocol_bridge:
                            data = self.protocol_bridge.process_pty_input(data)
                        
                        if data:
                            os.write(self.master_fd, data)
                        
                        # Log input if needed
                        if self.on_output:
                            try:
                                text = data.decode('utf-8', errors='replace')
                                for char in text:
                                    if char == '\r' or char == '\n':
                                        pass  # Could track line input
                            except:
                                pass
        finally:
            # Restore terminal
            if old_tty is not None:
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_tty)
            
            # Wait for child
            _, status = os.waitpid(self.pid, 0)
            
            # Cleanup
            self.running = False
            self._close_logs()
            
            return os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
    
    def _capture_loop(self):
        """Background capture thread - raw passthrough with capture."""
        while self.running and self.master_fd:
            ready, _, _ = select.select([self.master_fd], [], [], 0.1)
            
            if ready:
                try:
                    data = os.read(self.master_fd, 4096)
                except OSError:
                    break
                
                if not data:
                    break
                
                # Protocol bridge interception
                if self.protocol_bridge:
                    data = self.protocol_bridge.process_pty_output(data)
                    if not data:
                        continue
                
                # Log raw (side channel, no stdout)
                if self._raw_file:
                    self._raw_file.write(data)
                    self._raw_file.flush()
                
                # Parse for scrollback extraction (side channel)
                new_scrollback, screen_events = self.screen.feed(data)
                for line in new_scrollback:
                    if self._text_file:
                        self._text_file.write(line + '\n')
                        self._text_file.flush()
                    if self.on_output:
                        self.on_output(line, False)
                    self._check_patterns(line)
                    if self.on_scrollback:
                        self.on_scrollback(line)
                
                # Process screen events
                for event in screen_events:
                    pass
                
                # Check screen for patterns
                self._check_screen_patterns()
                
                # CRITICAL: Pass raw data to stdout for TUI rendering
                os.write(sys.stdout.fileno(), data)
    
    def _check_patterns(self, line: str):
        """Check for usage patterns in output."""
        for tool, patterns in self.USAGE_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, line, re.I)
                if match:
                    if self.on_usage_pattern:
                        self.on_usage_pattern(tool, {
                            'pattern': pattern,
                            'match': match.group(0),
                            'groups': match.groups(),
                            'line': line
                        })
    
    def _process_scrollback_line(self, line: str):
        """Process a line committed to scrollback."""
        if not line:
            return
        
        # Check ignore patterns
        for pattern in self.profile.scrollback_ignore_patterns:
            if pattern.match(line):
                return  # Skip this line
        
        # Check capture rules
        for rule in self.profile.scrollback_capture_rules:
            match = rule.pattern.search(line)
            if match:
                if self.on_screen_event:
                    self.on_screen_event(rule.name, {
                        'line': line,
                        'match': match.group(0),
                        'groups': match.groups(),
                    })
        
        # Always notify raw scrollback
        if self.on_scrollback:
            self.on_scrollback(line)
    
    def _check_screen_patterns(self):
        """Check current screen for capture patterns."""
        screen_text = self.screen.get_screen_text()
        
        for rule in self.profile.screen_capture_rules:
            for match in rule.pattern.finditer(screen_text):
                if self.on_screen_event:
                    self.on_screen_event(rule.name, {
                        'match': match.group(0),
                        'groups': match.groups(),
                        'screen_text': screen_text,
                    })
    
    def write(self, data: bytes):
        """Write to PTY (send input to process)."""
        if self.master_fd:
            if self.protocol_bridge:
                data = self.protocol_bridge.process_pty_input(data)
            if data:
                os.write(self.master_fd, data)
    
    def get_screen(self) -> str:
        """Get current screen state."""
        return self.screen.get_screen_text()
    
    def attach_protocol_bridge(self, bridge):
        """Attach a ProtocolBridge to intercept PTY traffic."""
        self.protocol_bridge = bridge
    
    def cleanup(self):
        """Cleanup resources."""
        self.running = False
        if self.capture_thread:
            self.capture_thread.join(timeout=1)
        self._close_logs()
    
    def _close_logs(self):
        """Close log files."""
        if self._raw_file:
            self._raw_file.close()
            self._raw_file = None
        if self._text_file:
            self._text_file.close()
            self._text_file = None


# Backward compatibility alias
PTYLayerV2 = PTYLayer


if __name__ == '__main__':
    # Demo
    import tempfile
    
    print("PTY Layer V2 Demo - 2D Screen Tracking")
    print("=" * 50)
    
    def on_scrollback(line):
        print(f"[SCROLLBACK] {line[:80]}")
    
    def on_event(name, data):
        print(f"[EVENT:{name}] {data.get('groups', data.get('match', '???'))}")
    
    pty_layer = PTYLayer(
        profile=CLAUDE_PROFILE,
        on_scrollback=on_scrollback,
        on_screen_event=on_event
    )
    
    # Test with echo
    print("\nRunning: echo with ANSI...")
    pty_layer.run(['echo', '-e', 'Hello\n\x1b[1;32mGreen\x1b[0m\nWorld'])
    
    print("\nFinal scrollback:")
    for line in pty_layer.screen.get_scrollback()[-5:]:
        print(f"  {repr(line)}")
