#!/usr/bin/env python3
# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  ⚠️  DEAD CODE / EXPERIMENTAL — NOT IMPORTED ANYWHERE IN THE CODEBASE       ║
# ║                                                                               ║
# ║  This module was an experiment in building a composable pattern DSL from      ║
# ║  S-expressions. It is NOT used by the hypervisor, PTY layer, or any other    ║
# ║  production code. The active pattern machinery lives in `sexp.py` and the     ║
# ║  `ProfileBuilder` class, which compiles regex directly.                       ║
# ║                                                                               ║
# ║  Safe to ignore. May be removed in a future cleanup pass.                     ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

"""
Composable Pattern DSL in S-expressions.

Build complex patterns from composable primitives:
- Literals, character classes, quantifiers
- Captures with named groups
- Combinators: sequence, choice, optional
- Dynamic interpolation support

Compiles to efficient regex or can be interpreted directly.
"""

import re
from typing import List, Union, Optional, Dict, Callable, Any
from dataclasses import dataclass
from abc import ABC, abstractmethod

from sexp import SExp, SExpParser


class Pattern(ABC):
    """Base class for patterns."""
    
    @abstractmethod
    def to_regex(self) -> str:
        """Convert to regex string."""
        pass
    
    @abstractmethod
    def match(self, text: str, pos: int = 0) -> Optional['MatchResult']:
        """Match against text at position."""
        pass


@dataclass
class MatchResult:
    """Result of a pattern match."""
    matched: str
    start: int
    end: int
    captures: Dict[str, 'MatchResult']
    
    @property
    def groups(self) -> List[str]:
        """Get all captured groups as list."""
        return [c.matched for c in self.captures.values()]


class Literal(Pattern):
    """Match literal text."""
    
    def __init__(self, text: str):
        self.text = text
    
    def to_regex(self) -> str:
        return re.escape(self.text)
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        if text[pos:pos + len(self.text)] == self.text:
            return MatchResult(
                matched=self.text,
                start=pos,
                end=pos + len(self.text),
                captures={}
            )
        return None


class CharClass(Pattern):
    """Match a character from a set."""
    
    def __init__(self, chars: str, negate: bool = False):
        self.chars = chars
        self.negate = negate
    
    def to_regex(self) -> str:
        escaped = re.escape(self.chars)
        if self.negate:
            return f'[^{escaped}]'
        return f'[{escaped}]'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        if pos >= len(text):
            return None
        
        char = text[pos]
        in_class = char in self.chars
        
        if (in_class and not self.negate) or (not in_class and self.negate):
            return MatchResult(
                matched=char,
                start=pos,
                end=pos + 1,
                captures={}
            )
        return None


class Sequence(Pattern):
    """Match sequence of patterns."""
    
    def __init__(self, patterns: List[Pattern]):
        self.patterns = patterns
    
    def to_regex(self) -> str:
        return ''.join(p.to_regex() for p in self.patterns)
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        current_pos = pos
        matched_parts = []
        all_captures = {}
        
        for pattern in self.patterns:
            result = pattern.match(text, current_pos)
            if result is None:
                return None
            
            matched_parts.append(result.matched)
            all_captures.update(result.captures)
            current_pos = result.end
        
        return MatchResult(
            matched=''.join(matched_parts),
            start=pos,
            end=current_pos,
            captures=all_captures
        )


class Choice(Pattern):
    """Match any of several patterns (alternation)."""
    
    def __init__(self, patterns: List[Pattern]):
        self.patterns = patterns
    
    def to_regex(self) -> str:
        inner = '|'.join(p.to_regex() for p in self.patterns)
        return f'(?:{inner})'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        for pattern in self.patterns:
            result = pattern.match(text, pos)
            if result is not None:
                return result
        return None


class Repeat(Pattern):
    """Repeat pattern (zero or more, one or more, exact count)."""
    
    def __init__(self, pattern: Pattern, min_count: int = 0, max_count: Optional[int] = None):
        self.pattern = pattern
        self.min_count = min_count
        self.max_count = max_count
    
    def to_regex(self) -> str:
        inner = self.pattern.to_regex()
        if self.min_count == 0 and self.max_count is None:
            return f'(?:{inner})*'
        elif self.min_count == 1 and self.max_count is None:
            return f'(?:{inner})+'
        elif self.min_count == 0 and self.max_count == 1:
            return f'(?:{inner})?'
        else:
            max_str = '' if self.max_count is None else str(self.max_count)
            return f'(?:{inner}){{{self.min_count},{max_str}}}'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        matches = []
        current_pos = pos
        
        while self.max_count is None or len(matches) < self.max_count:
            result = self.pattern.match(text, current_pos)
            if result is None:
                break
            matches.append(result)
            current_pos = result.end
            
            # Prevent infinite loops on zero-width matches
            if result.start == result.end:
                break
        
        if len(matches) < self.min_count:
            return None
        
        return MatchResult(
            matched=''.join(m.matched for m in matches),
            start=pos,
            end=current_pos,
            captures={}
        )


class Capture(Pattern):
    """Named capture group."""
    
    def __init__(self, name: str, pattern: Pattern):
        self.name = name
        self.pattern = pattern
    
    def to_regex(self) -> str:
        return f'(?P<{self.name}>{self.pattern.to_regex()})'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        result = self.pattern.match(text, pos)
        if result is None:
            return None
        
        return MatchResult(
            matched=result.matched,
            start=result.start,
            end=result.end,
            captures={self.name: result}
        )


class Whitespace(Pattern):
    """Match whitespace."""
    
    def to_regex(self) -> str:
        return r'\s+'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        start = pos
        while pos < len(text) and text[pos].isspace():
            pos += 1
        
        if pos > start:
            return MatchResult(
                matched=text[start:pos],
                start=start,
                end=pos,
                captures={}
            )
        return None


class AnyChar(Pattern):
    """Match any single character."""
    
    def to_regex(self) -> str:
        return '.'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        if pos < len(text):
            return MatchResult(
                matched=text[pos],
                start=pos,
                end=pos + 1,
                captures={}
            )
        return None


class StartOfLine(Pattern):
    """Match start of line/position."""
    
    def to_regex(self) -> str:
        return '^'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        if pos == 0 or text[pos - 1] == '\n':
            return MatchResult(
                matched='',
                start=pos,
                end=pos,
                captures={}
            )
        return None


class EndOfLine(Pattern):
    """Match end of line."""
    
    def to_regex(self) -> str:
        return '$'
    
    def match(self, text: str, pos: int = 0) -> Optional[MatchResult]:
        if pos >= len(text) or text[pos] == '\n':
            return MatchResult(
                matched='',
                start=pos,
                end=pos,
                captures={}
            )
        return None


# Predefined character classes
DIGIT = CharClass('0123456789')
WORD = CharClass('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_')
SPACE = CharClass(' \t\n\r\f\v')


class PatternCompiler:
    """Compile S-expressions to Pattern objects."""
    
    def __init__(self):
        self.macros: Dict[str, Callable[[List[SExp]], Pattern]] = {}
    
    def compile(self, sexp: SExp) -> Pattern:
        """Compile an S-expression to a Pattern."""
        if sexp.is_atom:
            return self._compile_atom(sexp.atom)
        
        return self._compile_list(sexp.list)
    
    def _compile_atom(self, atom: str) -> Pattern:
        """Compile an atom."""
        # Check for string literal
        if atom.startswith('"') and atom.endswith('"'):
            return Literal(atom[1:-1])
        
        # Predefined patterns
        builtins = {
            'digit': DIGIT,
            'word': WORD,
            'space': SPACE,
            'any': AnyChar(),
            'start': StartOfLine(),
            'end': EndOfLine(),
        }
        
        if atom in builtins:
            return builtins[atom]
        
        # Unknown atom - treat as literal
        return Literal(atom)
    
    def _compile_list(self, elements: List[SExp]) -> Pattern:
        """Compile a list expression."""
        if not elements:
            return Literal('')
        
        head = elements[0].atom if elements[0].is_atom else None
        
        # Pattern constructors
        constructors = {
            'lit': self._compile_literal,
            'literal': self._compile_literal,
            'char': self._compile_char_class,
            'seq': self._compile_sequence,
            'sequence': self._compile_sequence,
            'or': self._compile_choice,
            'choice': self._compile_choice,
            'opt': self._compile_optional,
            'optional': self._compile_optional,
            'star': self._compile_star,
            'zero-or-more': self._compile_star,
            'plus': self._compile_plus,
            'one-or-more': self._compile_plus,
            'repeat': self._compile_repeat,
            'capture': self._compile_capture,
            'ws': self._compile_whitespace,
            'whitespace': self._compile_whitespace,
        }
        
        if head in constructors:
            return constructors[head](elements[1:])
        
        # Unknown - treat as implicit sequence
        return self._compile_sequence(elements)
    
    def _compile_literal(self, args: List[SExp]) -> Pattern:
        text = args[0].atom if args else ''
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        return Literal(text)
    
    def _compile_char_class(self, args: List[SExp]) -> Pattern:
        chars = ''.join(a.atom for a in args if a.is_atom)
        if chars.startswith('"') and chars.endswith('"'):
            chars = chars[1:-1]
        return CharClass(chars)
    
    def _compile_sequence(self, args: List[SExp]) -> Pattern:
        patterns = [self.compile(a) for a in args]
        return Sequence(patterns)
    
    def _compile_choice(self, args: List[SExp]) -> Pattern:
        patterns = [self.compile(a) for a in args]
        return Choice(patterns)
    
    def _compile_optional(self, args: List[SExp]) -> Pattern:
        pattern = self.compile(args[0]) if args else Literal('')
        return Repeat(pattern, 0, 1)
    
    def _compile_star(self, args: List[SExp]) -> Pattern:
        pattern = self.compile(args[0]) if args else Literal('')
        return Repeat(pattern, 0, None)
    
    def _compile_plus(self, args: List[SExp]) -> Pattern:
        pattern = self.compile(args[0]) if args else Literal('')
        return Repeat(pattern, 1, None)
    
    def _compile_repeat(self, args: List[SExp]) -> Pattern:
        if len(args) < 2:
            return Literal('')
        
        pattern = self.compile(args[0])
        min_count = int(args[1].atom) if args[1].is_atom else 0
        max_count = int(args[2].atom) if len(args) > 2 and args[2].is_atom else None
        
        return Repeat(pattern, min_count, max_count)
    
    def _compile_capture(self, args: List[SExp]) -> Pattern:
        if len(args) < 2:
            return Literal('')
        
        name = args[0].atom if args[0].is_atom else 'unnamed'
        pattern = self.compile(args[1])
        
        return Capture(name, pattern)
    
    def _compile_whitespace(self, args: List[SExp]) -> Pattern:
        return Whitespace()


def compile_pattern(sexpr_str: str) -> Pattern:
    """Compile S-expression string to Pattern."""
    parser = SExpParser()
    sexps = parser.parse(sexpr_str)
    
    if not sexps:
        return Literal('')
    
    compiler = PatternCompiler()
    return compiler.compile(sexps[0])


# Example patterns as S-expressions
EXAMPLE_TOKEN_PATTERN = '''
(seq
  (lit "Tokens:")
  (ws)
  (capture input (plus (char "0123456789,")))
  (ws)
  (lit "→")
  (ws)
  (capture output (plus (char "0123456789,"))))
'''

EXAMPLE_PROMPT_PATTERN = '''
(seq
  (lit "> ")
  (capture prompt (plus any)))
'''


if __name__ == '__main__':
    # Test compilation
    print("Testing Pattern DSL")
    print("=" * 50)
    
    # Test token pattern
    print("\nToken pattern:")
    token_pat = compile_pattern(EXAMPLE_TOKEN_PATTERN)
    print(f"Regex: {token_pat.to_regex()}")
    
    test1 = "Tokens: 1,234 → 4,567"
    result1 = token_pat.match(test1)
    if result1:
        print(f"Match: '{result1.matched}'")
        print(f"Captures: {result1.captures}")
    
    # Test prompt pattern
    print("\nPrompt pattern:")
    prompt_pat = compile_pattern(EXAMPLE_PROMPT_PATTERN)
    print(f"Regex: {prompt_pat.to_regex()}")
    
    test2 = "> hello world"
    result2 = prompt_pat.match(test2)
    if result2:
        print(f"Match: '{result2.matched}'")
        print(f"Captures: {result2.captures}")
