#!/usr/bin/env python3
"""winnow s-expression reader and printer, shared by every winnow script.

    tokenize(text) -> tokens      ; comments (`;` to end of line) dropped
    parse(tokens)  -> forms       ; nested lists of str / Lit
    sx(form)       -> text        ; canonical one-line serialization
    anns(tail)     -> {key: value} for the :key value pairs in a tail

Nothing here knows about frames, statuses or graphs; that starts in
fold.py.
"""


class Lit(str):
    """Quoted string literal (as opposed to a bare symbol)."""


def tokenize(src):
    toks, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == ";":                            # comment to end of line
            while i < n and src[i] != "\n":
                i += 1
        elif c.isspace():
            i += 1
        elif c in "()":
            toks.append(c)
            i += 1
        elif c == '"':
            j = i + 1
            while j < n and src[j] != '"':
                j += 1
            toks.append(Lit(src[i + 1:j]))
            i = j + 1
        else:
            j = i
            while j < n and not src[j].isspace() and src[j] not in '()"':
                j += 1
            toks.append(src[i:j])
            i = j
    return toks


def parse(toks):
    pos = 0

    def rd():
        nonlocal pos
        t = toks[pos]
        pos += 1
        if t == "(":
            out = []
            while toks[pos] != ")":
                out.append(rd())
            pos += 1
            return out
        return t

    forms = []
    while pos < len(toks):
        forms.append(rd())
    return forms


def sx(v):
    """Serialize a parsed value back to canonical s-expr text."""
    if isinstance(v, list):
        return "(" + " ".join(sx(x) for x in v) + ")"
    if isinstance(v, Lit):
        return '"' + str(v) + '"'
    return str(v)


def _symbols(v):
    """Flatten a payload to its bare symbols (for term queries)."""
    if isinstance(v, list):
        return [s for x in v for s in _symbols(x)]
    return [] if isinstance(v, Lit) else [str(v)]


def anns(rest):
    """Collect :key value pairs from a tail; ignore anything else."""
    d, i = {}, 0
    while i < len(rest):
        k = rest[i]
        if isinstance(k, str) and not isinstance(k, Lit) and k.startswith(":"):
            d[k[1:]] = rest[i + 1]
            i += 2
        else:
            i += 1
    return d
