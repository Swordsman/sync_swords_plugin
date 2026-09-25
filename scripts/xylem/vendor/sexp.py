"""
Vendored S-expression parser from term_capture/ai_hypervisor/sexp.py.

Snapshot taken 2026-06-08 to insulate xylem from Pisces language rebuild.
If Pisces changes break backwards compatibility, this copy remains stable.

Provides: SExp (data type), SExpParser (text → SExp tree).
"""

import re
from typing import List, Union, Optional


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
        if self.is_atom:
            raise ValueError("Atom has no car")
        return self.value[0] if self.value else SExp('nil')

    @property
    def cdr(self) -> 'SExp':
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
        tokens = self._tokenize(text)
        pos = [0]
        expressions = []
        while pos[0] < len(tokens):
            expr = self._parse_expr(tokens, pos)
            if expr is not None:
                expressions.append(expr)
        return expressions

    def _tokenize(self, text: str) -> List[str]:
        tokens = []
        for match in self.TOKEN_PATTERN.finditer(text):
            kind = match.lastgroup
            value = match.group()
            if kind in ('LPAREN', 'RPAREN', 'STRING', 'ATOM'):
                tokens.append(value)
        return tokens

    def _parse_expr(self, tokens: List[str], pos: List[int]) -> Optional[SExp]:
        if pos[0] >= len(tokens):
            return None
        token = tokens[pos[0]]
        if token == '(':
            pos[0] += 1
            elements = []
            while pos[0] < len(tokens) and tokens[pos[0]] != ')':
                elements.append(self._parse_expr(tokens, pos))
            pos[0] += 1
            return SExp(elements)
        elif token == ')':
            raise ValueError("Unexpected ')'")
        else:
            pos[0] += 1
            return SExp(self._unescape(token))

    def _unescape(self, token: str) -> str:
        if token.startswith('"') and token.endswith('"'):
            return token[1:-1].encode('utf-8').decode('unicode_escape')
        return token
