#!/usr/bin/env python3
"""
S-expression parser and evaluator for rule configuration.

Lightweight Lisp-style expressions for defining capture rules:

(profile claude
  (scrollback-ignore
    (pattern "^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏\\s]*$")
    (pattern "^\\s*Thinking\\.*\\s*$"))
  
  (screen-capture token-usage
    (pattern "Tokens:\\s*([\\d,]+)\\s*→\\s*([\\d,]+)")
    (groups input output))
  
  (scrollback-capture prompt
    (pattern "^>\\s+(.+)")
    (group prompt-text)))
"""

import re
from typing import Any, List, Union, Callable, Dict, Optional
from dataclasses import dataclass
from pathlib import Path


class SExp:
    """An S-expression: atom or list."""
    
    def __init__(self, value: Union[str, List['SExp']]):
        self.value = value
    
    @property
    def is_atom(self) -> bool:
        return isinstance(self.value, str)
    
    @property
    def is_list(self) -> bool:
        return isinstance(self.value, list)
    
    @property
    def atom(self) -> str:
        if not self.is_atom:
            raise ValueError("Not an atom")
        return self.value
    
    @property
    def list(self) -> List['SExp']:
        if not self.is_list:
            raise ValueError("Not a list")
        return self.value
    
    @property
    def car(self) -> 'SExp':
        """First element of list."""
        if self.is_atom:
            raise ValueError("Atom has no car")
        return self.value[0] if self.value else SExp('nil')
    
    @property
    def cdr(self) -> 'SExp':
        """Rest of list."""
        if self.is_atom:
            raise ValueError("Atom has no cdr")
        return SExp(self.value[1:]) if len(self.value) > 1 else SExp('nil')
    
    def __getitem__(self, index: int) -> 'SExp':
        if self.is_atom:
            raise ValueError("Cannot index atom")
        return self.value[index]
    
    def __len__(self) -> int:
        if self.is_atom:
            return 1
        return len(self.value)
    
    def __repr__(self) -> str:
        if self.is_atom:
            return repr(self.value)
        return '(' + ' '.join(repr(x) for x in self.value) + ')'
    
    def __eq__(self, other) -> bool:
        if isinstance(other, SExp):
            return self.value == other.value
        return False


class SExpParser:
    """Parse S-expressions from text."""
    
    TOKEN_PATTERN = re.compile(r'''
        (?P<LPAREN>\() |
        (?P<RPAREN>\)) |
        (?P<STRING>"(?:[^"\\]|\\.)*") |
        (?P<COMMENT>;[^\n]*) |
        (?P<ATOM>[^\s()";]+) |
        (?P<WHITESPACE>\s+)
    ''', re.VERBOSE)
    
    def parse(self, text: str) -> List[SExp]:
        """Parse text into list of S-expressions."""
        tokens = self._tokenize(text)
        pos = [0]  # Use list for mutable reference
        
        expressions = []
        while pos[0] < len(tokens):
            expr = self._parse_expr(tokens, pos)
            if expr is not None:
                expressions.append(expr)
        
        return expressions
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize input text."""
        tokens = []
        for match in self.TOKEN_PATTERN.finditer(text):
            kind = match.lastgroup
            value = match.group()
            
            if kind in ('LPAREN', 'RPAREN', 'STRING', 'ATOM'):
                tokens.append(value)
            # Ignore comments and whitespace
        
        return tokens
    
    def _parse_expr(self, tokens: List[str], pos: List[int]) -> Optional[SExp]:
        """Parse single expression."""
        if pos[0] >= len(tokens):
            return None
        
        token = tokens[pos[0]]
        
        if token == '(':
            pos[0] += 1
            elements = []
            while pos[0] < len(tokens) and tokens[pos[0]] != ')':
                elements.append(self._parse_expr(tokens, pos))
            pos[0] += 1  # Skip ')'
            return SExp(elements)
        
        elif token == ')':
            raise ValueError("Unexpected ')'")
        
        else:
            pos[0] += 1
            return SExp(self._unescape(token))
    
    def _unescape(self, token: str) -> str:
        """Unescape string or atom."""
        if token.startswith('"') and token.endswith('"'):
            # String literal
            return token[1:-1].encode('utf-8').decode('unicode_escape')
        return token


@dataclass
class CaptureRule:
    """A capture rule derived from S-expression."""
    name: str
    pattern: re.Pattern
    capture_type: str  # 'scrollback', 'screen', 'scrollback-line'
    group_names: List[str]
    action: str = 'capture'  # 'capture', 'ignore', 'transform'
    priority: int = 0


class ProfileBuilder:
    """Build tool profiles from S-expressions."""
    
    def __init__(self):
        self.profiles: Dict[str, 'ToolProfile'] = {}
    
    def load_file(self, path: Path) -> Dict[str, 'ToolProfile']:
        """Load profiles from S-expression file."""
        text = path.read_text()
        parser = SExpParser()
        expressions = parser.parse(text)
        
        for expr in expressions:
            if expr.is_list and expr.car.atom == 'profile':
                profile = self._build_profile(expr)
                self.profiles[profile.name] = profile
        
        return self.profiles
    
    def _build_profile(self, expr: SExp):
        """Build ToolProfile from (profile ...) expression."""
        try:
            from .pty_layer_v2 import ToolProfile, CaptureRule
        except ImportError:
            from pty_layer_v2 import ToolProfile, CaptureRule
        
        name = expr[1].atom
        rules = []
        scrollback_ignore = []
        defaults = {}
        parent_profile = None
        
        for child in expr.list[2:]:
            if not child.is_list:
                continue
            
            head = child.car.atom
            
            if head == 'inherit':
                parent_name = child[1].atom
                parent_profile = self.profiles.get(parent_name)
            
            elif head == 'scrollback-ignore':
                for pattern_expr in child.list[1:]:
                    if pattern_expr.is_list and pattern_expr.car.atom == 'pattern':
                        flags = 0
                        if len(pattern_expr) > 2:
                            flag_str = pattern_expr[2].atom
                            if 'i' in flag_str:
                                flags |= re.I
                        pattern = re.compile(pattern_expr[1].atom, flags)
                        scrollback_ignore.append(pattern)
            
            elif head == 'screen-capture':
                rule = self._build_capture_rule(child, 'screen')
                rules.append(rule)
            
            elif head == 'scrollback-capture':
                rule = self._build_capture_rule(child, 'scrollback')
                rules.append(rule)
            
            elif head == 'defaults':
                for default in child.list[1:]:
                    if default.is_list:
                        key = default.car.atom
                        val = default[1].atom if len(default) > 1 else None
                        defaults[key] = val
        
        # Apply inheritance: parent properties first, child overrides/extends
        if parent_profile:
            merged_defaults = {
                'rows': str(parent_profile.default_rows),
                'cols': str(parent_profile.default_cols),
            }
            merged_defaults.update(defaults)
            defaults = merged_defaults
            
            screen_rules = list(parent_profile.screen_capture_rules)
            scrollback_rules = list(parent_profile.scrollback_capture_rules)
            scrollback_ignore = list(parent_profile.scrollback_ignore_patterns) + scrollback_ignore
        else:
            screen_rules = []
            scrollback_rules = []
        
        screen_rules.extend([r for r in rules if r.capture_type == 'screen'])
        scrollback_rules.extend([r for r in rules if r.capture_type == 'scrollback'])
        
        return ToolProfile(
            name=name,
            default_rows=int(defaults.get('rows', 24)),
            default_cols=int(defaults.get('cols', 80)),
            scrollback_ignore_patterns=scrollback_ignore,
            screen_capture_rules=screen_rules,
            scrollback_capture_rules=scrollback_rules,
        )
    
    def _build_capture_rule(self, expr: SExp, capture_type: str) -> CaptureRule:
        """Build CaptureRule from S-expression."""
        name = expr[1].atom
        pattern_str = None
        group_names = []
        priority = 0
        
        for child in expr.list[2:]:
            if not child.is_list:
                continue
            
            head = child.car.atom
            
            if head == 'pattern':
                pattern_str = child[1].atom
            
            elif head == 'groups':
                group_names = [x.atom for x in child.list[1:]]
            
            elif head == 'group':
                group_names = [child[1].atom]
            
            elif head == 'priority':
                priority = int(child[1].atom)
        
        return CaptureRule(
            name=name,
            pattern=re.compile(pattern_str) if pattern_str else re.compile(''),
            capture_type=capture_type,
            group_names=group_names,
            priority=priority
        )


def dump_profile(profile: 'ToolProfile') -> str:
    """Dump ToolProfile to S-expression string."""
    lines = [f'(profile {profile.name}']
    
    lines.append(f'  (defaults (rows {profile.default_rows}) (cols {profile.default_cols}))')
    
    if profile.scrollback_ignore_patterns:
        lines.append('  (scrollback-ignore')
        for pat in profile.scrollback_ignore_patterns:
            lines.append(f'    (pattern {repr(pat.pattern)})')
        lines.append('  )')
    
    for rule in profile.screen_capture_rules:
        lines.append(f'  (screen-capture {rule.name}')
        lines.append(f'    (pattern {repr(rule.pattern.pattern)})')
        if rule.group_names:
            lines.append(f'    (groups {" ".join(rule.group_names)}))')
        else:
            lines.append('  )')
    
    for rule in profile.scrollback_capture_rules:
        lines.append(f'  (scrollback-capture {rule.name}')
        lines.append(f'    (pattern {repr(rule.pattern.pattern)})')
        if rule.group_names:
            lines.append(f'    (group {rule.group_names[0]}))')
        else:
            lines.append('  )')
    
    lines.append(')')
    return '\n'.join(lines)


# Example profile in S-expression format
CLAUDE_PROFILE_SEXP = """
(profile claude
  (defaults (rows 24) (cols 120))
  
  ; Ignore spinner animations and transient UI
  (scrollback-ignore
    (pattern "^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏\\s]*$")
    (pattern "^\\s*Thinking\\.*\\s*$")
    (pattern "^\\s*\\d+%\\s*$"))
  
  ; Capture token usage from screen (transient but important)
  (screen-capture token-usage
    (pattern "Tokens:\\s*([\\d,]+)\\s*→\\s*([\\d,]+)")
    (groups input output)
    (priority 100))
  
  ; Capture cost display
  (screen-capture cost
    (pattern "\\$([\\d.]+)")
    (group amount)
    (priority 90))
  
  ; Capture prompts from scrollback
  (scrollback-capture user-prompt
    (pattern "^>\\s+(.+)")
    (group prompt-text)
    (priority 100))
  
  ; Detect AI responses
  (scrollback-capture ai-response
    (pattern "^(?!>\\s).{20,}")  ; Non-prompt lines of substance
    (priority 10)))
"""


if __name__ == '__main__':
    # Test parser
    parser = SExpParser()
    
    print("Testing S-expression parser")
    print("=" * 50)
    
    # Parse example
    expressions = parser.parse(CLAUDE_PROFILE_SEXP)
    print(f"Parsed {len(expressions)} top-level expressions")
    
    for expr in expressions:
        print(f"\nExpression: {expr}")
    
    # Build profile
    print("\n" + "=" * 50)
    print("Building profile from S-expression...")
    
    builder = ProfileBuilder()
    profiles = builder.load_file(Path('/dev/stdin'))
    
    # Actually, let's parse the string directly
    from io import StringIO
    
    profiles = {}
    for expr in expressions:
        if expr.is_list and expr.car.atom == 'profile':
            profile = builder._build_profile(expr)
            profiles[profile.name] = profile
    
    for name, profile in profiles.items():
        print(f"\nProfile: {name}")
        print(f"  Rows: {profile.default_rows}, Cols: {profile.default_cols}")
        print(f"  Ignore patterns: {len(profile.scrollback_ignore_patterns)}")
        print(f"  Screen rules: {len(profile.screen_capture_rules)}")
        print(f"  Scrollback rules: {len(profile.scrollback_capture_rules)}")
        
        for rule in profile.screen_capture_rules:
            print(f"    Screen: {rule.name} -> groups: {rule.group_names}")
        
        for rule in profile.scrollback_capture_rules:
            print(f"    Scrollback: {rule.name} -> group: {rule.group_names}")
    
    # Round-trip test
    if profiles:
        print("\n" + "=" * 50)
        print("Round-trip dump:")
        print(dump_profile(list(profiles.values())[0]))
