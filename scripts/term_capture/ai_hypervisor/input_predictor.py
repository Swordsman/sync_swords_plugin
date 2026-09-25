#!/usr/bin/env python3
"""
Input Predictor - Anticipatory screen state tracking.

Tracks keystrokes and predicts what will appear on screen before
the TUI renders it. Enables:
- Pre-filtering of input
- Cursor position prediction
- Input/output correlation
- Sensitive data detection (passwords, keys)
"""

import re
from typing import Optional, List, Dict, Callable, Tuple
from dataclasses import dataclass
from enum import Enum


class KeyType(Enum):
    """Types of key input."""
    PRINTABLE = "printable"      # Regular character
    CONTROL = "control"          # Ctrl+key
    ESCAPE = "escape"            # Escape sequences
    FUNCTION = "function"        # F1-F12
    NAVIGATION = "navigation"    # Arrows, Home, End, etc
    EDIT = "edit"                # Backspace, Delete, Insert
    ENTER = "enter"              # Return/Enter
    TAB = "tab"                  # Tab
    SPACE = "space"              # Spacebar
    UNKNOWN = "unknown"


@dataclass
class Keystroke:
    """A single keystroke event."""
    raw_bytes: bytes
    char: Optional[str]           # Display character (if printable)
    key_type: KeyType
    ctrl: bool = False
    alt: bool = False
    shift: bool = False
    
    def is_printable(self) -> bool:
        return self.key_type in (KeyType.PRINTABLE, KeyType.SPACE, KeyType.TAB)


@dataclass  
class PredictedScreenChange:
    """A predicted change to screen state."""
    row: int
    col: int
    char: str
    predicted_line: str  # Full predicted line content
    confidence: float    # 0.0-1.0 confidence score


class InputBuffer:
    """
    Buffer for tracking pending input that hasn't been rendered yet.
    """
    
    def __init__(self):
        self.buffer: List[Keystroke] = []
        self.cursor_pos = 0  # Position within buffer
        self.pending_line = ""
        
    def add_keystroke(self, key: Keystroke):
        """Add a keystroke to the buffer."""
        if key.is_printable() and key.char:
            # Insert at cursor position
            self.pending_line = (
                self.pending_line[:self.cursor_pos] + 
                key.char + 
                self.pending_line[self.cursor_pos:]
            )
            self.cursor_pos += 1
            self.buffer.append(key)
            
        elif key.key_type == KeyType.BACKSPACE:
            if self.cursor_pos > 0:
                self.pending_line = (
                    self.pending_line[:self.cursor_pos-1] + 
                    self.pending_line[self.cursor_pos:]
                )
                self.cursor_pos -= 1
                
        elif key.key_type == KeyType.DELETE:
            if self.cursor_pos < len(self.pending_line):
                self.pending_line = (
                    self.pending_line[:self.cursor_pos] + 
                    self.pending_line[self.cursor_pos+1:]
                )
                
        elif key.key_type == KeyType.ARROW_LEFT:
            self.cursor_pos = max(0, self.cursor_pos - 1)
            
        elif key.key_type == KeyType.ARROW_RIGHT:
            self.cursor_pos = min(len(self.pending_line), self.cursor_pos + 1)
            
        elif key.key_type == KeyType.HOME:
            self.cursor_pos = 0
            
        elif key.key_type == KeyType.END:
            self.cursor_pos = len(self.pending_line)
            
        elif key.key_type == KeyType.ENTER:
            # Line complete - clear buffer
            completed = self.pending_line
            self.clear()
            return completed
        
        return None
    
    def clear(self):
        """Clear the buffer."""
        self.buffer = []
        self.cursor_pos = 0
        self.pending_line = ""
    
    def get_pending(self) -> str:
        """Get current pending input line."""
        return self.pending_line


class InputPredictor:
    """
    Predicts screen changes based on user input.
    
    Maintains model of:
    - Current cursor position on screen
    - Pending input buffer
    - Expected screen state after input is processed
    """
    
    def __init__(self, rows: int = 24, cols: int = 80):
        self.rows = rows
        self.cols = cols
        
        # Track cursor position
        self.cursor_row = 0
        self.cursor_col = 0
        
        # Input buffer
        self.input_buffer = InputBuffer()
        
        # Prediction callbacks
        self.on_prediction: Optional[Callable[[PredictedScreenChange], None]] = None
        self.on_line_complete: Optional[Callable[[str], None]] = None
        self.on_sensitive_pattern: Optional[Callable[[str, str], bool]] = None
        
        # Default sensitive patterns (passwords, keys, tokens)
        self.sensitive_patterns = [
            (re.compile(r'password[:\s]*', re.I), 'password'),
            (re.compile(r'secret[:\s]*', re.I), 'secret'),
            (re.compile(r'api[_-]?key[:\s]*', re.I), 'api_key'),
            (re.compile(r'token[:\s]*', re.I), 'token'),
            (re.compile(r'sk-[a-zA-Z0-9]{48}'), 'openai_key'),  # OpenAI key format
            (re.compile(r'ghp_[a-zA-Z0-9]{36}'), 'github_token'),  # GitHub PAT
            (re.compile(r'[a-zA-Z0-9]{32,}'), 'possible_key'),  # Generic long hex
        ]
    
    def parse_input(self, data: bytes) -> List[Keystroke]:
        """Parse raw input bytes into keystrokes."""
        keystrokes = []
        i = 0
        
        while i < len(data):
            byte = data[i]
            
            # Escape sequence
            if byte == 0x1b:
                key, consumed = self._parse_escape_sequence(data, i)
                keystrokes.append(key)
                i += consumed
                continue
            
            # Control character
            elif byte < 0x20:
                key = self._parse_control_char(byte)
                keystrokes.append(key)
            
            # Printable
            else:
                try:
                    char = bytes([byte]).decode('utf-8')
                    keystrokes.append(Keystroke(
                        raw_bytes=bytes([byte]),
                        char=char,
                        key_type=KeyType.PRINTABLE
                    ))
                except:
                    pass
            
            i += 1
        
        return keystrokes
    
    def _parse_escape_sequence(self, data: bytes, start: int) -> Tuple[Keystroke, int]:
        """Parse an escape sequence starting at position."""
        if start + 1 >= len(data):
            return Keystroke(b'\x1b', None, KeyType.ESCAPE), 1
        
        next_byte = data[start + 1]
        
        # CSI sequence ESC[
        if next_byte == 0x5b:  # [
            return self._parse_csi_sequence(data, start)
        
        # Simple escapes
        simple_escapes = {
            0x1b: (KeyType.ESCAPE, 'esc'),
        }
        
        if next_byte in simple_escapes:
            key_type, _ = simple_escapes[next_byte]
            return Keystroke(data[start:start+2], None, key_type), 2
        
        # Alt+key
        if 0x20 <= next_byte <= 0x7e:
            try:
                char = bytes([next_byte]).decode('utf-8')
                return Keystroke(
                    data[start:start+2],
                    char,
                    KeyType.PRINTABLE,
                    alt=True
                ), 2
            except:
                pass
        
        return Keystroke(b'\x1b', None, KeyType.ESCAPE), 1
    
    def _parse_csi_sequence(self, data: bytes, start: int) -> Tuple[Keystroke, int]:
        """Parse CSI escape sequence ESC[..."""
        # CSI sequences: ESC[ params cmd
        i = start + 2
        params = []
        current_param = ""
        
        while i < len(data):
            byte = data[i]
            
            if 0x30 <= byte <= 0x3f:  # 0-9:;<=>?
                if 0x30 <= byte <= 0x39:  # 0-9
                    current_param += chr(byte)
                elif byte == 0x3b:  # ;
                    params.append(int(current_param) if current_param else 0)
                    current_param = ""
            elif 0x40 <= byte <= 0x7e:  # Command byte
                if current_param:
                    params.append(int(current_param) if current_param else 0)
                
                cmd = chr(byte)
                return self._handle_csi_command(params, cmd, data[start:i+1]), i - start + 1
            else:
                break
            i += 1
        
        return Keystroke(data[start:i], None, KeyType.UNKNOWN), i - start
    
    def _handle_csi_command(self, params: List[int], cmd: str, raw: bytes) -> Keystroke:
        """Handle a CSI command."""
        # Navigation keys
        nav_keys = {
            'A': KeyType.NAVIGATION,  # Up
            'B': KeyType.NAVIGATION,  # Down  
            'C': KeyType.NAVIGATION,  # Right
            'D': KeyType.NAVIGATION,  # Left
            'H': KeyType.NAVIGATION,  # Home
            'F': KeyType.NAVIGATION,  # End
        }
        
        if cmd in nav_keys:
            key_type = nav_keys[cmd]
            # Map to specific navigation types
            if cmd == 'A':
                return Keystroke(raw, None, KeyType.NAVIGATION)
            elif cmd == 'B':
                return Keystroke(raw, None, KeyType.NAVIGATION)
            elif cmd == 'C':
                return Keystroke(raw, None, KeyType.NAVIGATION, key_type=KeyType.ARROW_RIGHT)
            elif cmd == 'D':
                return Keystroke(raw, None, KeyType.NAVIGATION, key_type=KeyType.ARROW_LEFT)
        
        # Function keys
        if cmd == '~' and params:
            func_map = {
                1: KeyType.FUNCTION,   # F1
                2: KeyType.INSERT,
                3: KeyType.DELETE,
                4: KeyType.END,
                5: KeyType.HOME,
                15: KeyType.FUNCTION,  # F5
                17: KeyType.FUNCTION,  # F6
                18: KeyType.FUNCTION,  # F7
                19: KeyType.FUNCTION,  # F8
                20: KeyType.FUNCTION,  # F9
                21: KeyType.FUNCTION,  # F10
                23: KeyType.FUNCTION,  # F11
                24: KeyType.FUNCTION,  # F12
            }
            if params[0] in func_map:
                return Keystroke(raw, None, func_map[params[0]])
        
        return Keystroke(raw, None, KeyType.UNKNOWN)
    
    def _parse_control_char(self, byte: int) -> Keystroke:
        """Parse a control character."""
        control_chars = {
            0x00: ('@', KeyType.CONTROL),
            0x01: ('a', KeyType.CONTROL),  # Ctrl+A
            0x02: ('b', KeyType.CONTROL),  # Ctrl+B
            0x03: ('c', KeyType.CONTROL),  # Ctrl+C
            0x04: ('d', KeyType.CONTROL),  # Ctrl+D
            0x05: ('e', KeyType.CONTROL),  # Ctrl+E
            0x06: ('f', KeyType.CONTROL),  # Ctrl+F
            0x07: ('g', KeyType.CONTROL),  # Ctrl+G (BEL)
            0x08: ('h', KeyType.BACKSPACE),  # Backspace
            0x09: ('i', KeyType.TAB),       # Tab
            0x0a: ('j', KeyType.ENTER),     # Newline
            0x0b: ('k', KeyType.CONTROL),
            0x0c: ('l', KeyType.CONTROL),
            0x0d: ('m', KeyType.ENTER),     # Return
            0x0e: ('n', KeyType.CONTROL),
            0x0f: ('o', KeyType.CONTROL),
            0x10: ('p', KeyType.CONTROL),
            0x11: ('q', KeyType.CONTROL),
            0x12: ('r', KeyType.CONTROL),
            0x13: ('s', KeyType.CONTROL),
            0x14: ('t', KeyType.CONTROL),
            0x15: ('u', KeyType.CONTROL),
            0x16: ('v', KeyType.CONTROL),
            0x17: ('w', KeyType.CONTROL),
            0x18: ('x', KeyType.CONTROL),
            0x19: ('y', KeyType.CONTROL),
            0x1a: ('z', KeyType.CONTROL),
            0x1b: ('[', KeyType.ESCAPE),    # Escape
            0x1c: ('\\', KeyType.CONTROL),
            0x1d: (']', KeyType.CONTROL),
            0x1e: ('^', KeyType.CONTROL),
            0x1f: ('_', KeyType.CONTROL),
            0x7f: ('?', KeyType.BACKSPACE), # DEL
        }
        
        char, key_type = control_chars.get(byte, (None, KeyType.UNKNOWN))
        return Keystroke(bytes([byte]), char, key_type, ctrl=True)
    
    def process_input(self, data: bytes) -> Optional[str]:
        """
        Process raw input bytes.
        
        Returns completed line if Enter was pressed, None otherwise.
        """
        keystrokes = self.parse_input(data)
        
        completed_line = None
        
        for key in keystrokes:
            result = self.input_buffer.add_keystroke(key)
            
            # Make predictions
            if key.is_printable():
                self._predict_screen_change(key)
            
            # Check for sensitive patterns
            self._check_sensitive_patterns()
            
            # Track completed lines
            if result is not None:
                completed_line = result
                if self.on_line_complete:
                    self.on_line_complete(result)
                self.input_buffer.clear()
        
        return completed_line
    
    def _predict_screen_change(self, key: Keystroke):
        """Predict what will appear on screen."""
        if not key.char:
            return
        
        # Predict character will appear at current cursor position
        prediction = PredictedScreenChange(
            row=self.cursor_row,
            col=self.cursor_col,
            char=key.char,
            predicted_line=self.input_buffer.get_pending(),
            confidence=0.9  # High confidence for printable chars
        )
        
        if self.on_prediction:
            self.on_prediction(prediction)
        
        # Update predicted cursor position
        self.cursor_col += 1
        if self.cursor_col >= self.cols:
            self.cursor_col = 0
            self.cursor_row += 1
    
    def _check_sensitive_patterns(self):
        """Check if pending input matches sensitive patterns."""
        pending = self.input_buffer.get_pending()
        
        for pattern, pattern_name in self.sensitive_patterns:
            match = pattern.search(pending)
            if match:
                if self.on_sensitive_pattern:
                    should_mask = self.on_sensitive_pattern(pending, pattern_name)
                    if should_mask:
                        # Could trigger masking/filtering
                        pass
    
    def update_cursor_position(self, row: int, col: int):
        """Update known cursor position (from screen parsing)."""
        self.cursor_row = row
        self.cursor_col = col
    
    def get_pending_input(self) -> str:
        """Get current pending input."""
        return self.input_buffer.get_pending()


# Key type extensions
KeyType.ARROW_LEFT = "arrow_left"
KeyType.ARROW_RIGHT = "arrow_right"
KeyType.ARROW_UP = "arrow_up"
KeyType.ARROW_DOWN = "arrow_down"
KeyType.BACKSPACE = "backspace"
KeyType.DELETE = "delete"
KeyType.HOME = "home"
KeyType.END = "end"
KeyType.INSERT = "insert"


if __name__ == '__main__':
    # Demo
    predictor = InputPredictor()
    
    def on_prediction(p):
        print(f"[PREDICT] '{p.char}' at ({p.row},{p.col}) -> line: '{p.predicted_line}'")
    
    def on_complete(line):
        print(f"[COMPLETE] Line submitted: '{line}'")
    
    predictor.on_prediction = on_prediction
    predictor.on_line_complete = on_complete
    
    # Simulate typing "hello" + Enter
    test_input = b'hello\r'
    print(f"Processing: {test_input}")
    result = predictor.process_input(test_input)
    print(f"Result: {result}")
    
    # Simulate typing with backspace
    predictor2 = InputPredictor()
    predictor2.on_prediction = on_prediction
    predictor2.on_line_complete = on_complete
    
    test_input2 = b'test\x08\x08st\r'  # "test" + backspace x2 + "st" = "test" -> "te" -> "test"
    print(f"\nProcessing: {test_input2}")
    result2 = predictor2.process_input(test_input2)
    print(f"Result: {result2}")
