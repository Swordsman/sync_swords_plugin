"""Reading intent maps: s-expression text to IntentMap(title, nodes, project, refs)."""
from __future__ import annotations

import re
from typing import NamedTuple

KINDS = ("goal", "need", "solution", "test")
STATUSES = ("built", "measured", "partial", "design", "untested", "not-built")
SLUG = re.compile(r"[A-Za-z0-9-]+")


class Node(NamedTuple):
    kind: str
    id: str
    text: str
    links: tuple[str, ...]      # serves / meets / tests targets
    status: str | None
    icon: str | None = None     # overrides the kind/status default
    group: str | None = None    # node view: the meta-node that pulls it in; defaults to its kind
    priority: int = 0           # rules can select and order by it


# ---------------------------------------------------------------- reading

def tokens(source: str):
    """Parens, quoted strings (with \\" escapes), ;-comments and bare atoms."""
    position = 0
    while position < len(source):
        char = source[position]
        if char.isspace():
            position += 1
        elif char == ";":
            end = source.find("\n", position)
            position = len(source) if end == -1 else end
        elif char in "()":
            yield char
            position += 1
        elif char == '"':
            end, parts = position + 1, []
            while end < len(source) and source[end] != '"':
                if source[end] == "\\" and end + 1 < len(source):
                    end += 1
                parts.append(source[end])
                end += 1
            if end >= len(source):
                raise ValueError(f"unterminated string at offset {position}")
            yield ("str", "".join(parts))
            position = end + 1
        else:
            end = position
            while end < len(source) and not source[end].isspace() and source[end] not in '()";':
                end += 1
            yield source[position:end]
            position = end


def parse(source: str):
    stack: list[list] = [[]]
    for token in tokens(source):
        if token == "(":
            stack.append([])
        elif token == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')'")
            done = stack.pop()
            stack[-1].append(done)
        else:
            stack[-1].append(token)
    if len(stack) != 1:
        raise ValueError("unbalanced '(': missing ')'")
    if len(stack[0]) != 1 or not isinstance(stack[0][0], list) or stack[0][0][:1] != ["intent-map"]:
        raise ValueError("the file must hold exactly one (intent-map \"title\" ...) form")
    return stack[0][0]


def text_of(value) -> str:
    if isinstance(value, tuple) and value[0] == "str":
        return value[1]
    raise ValueError(f"expected a quoted string, got {value!r}")


class Ref(NamedTuple):
    slug: str
    why: str


class IntentMap(NamedTuple):
    title: str
    nodes: list[Node]
    project: str | None = None
    refs: tuple[Ref, ...] = ()


def read_node(item: list) -> Node:
    if len(item) < 3:
        raise ValueError(f"{item!r}: expected ({item[0]} ID \"text\" ...)")
    link_key = {"need": ":serves", "solution": ":meets", "test": ":tests"}
    kind, node_id, text, rest = item[0], item[1], text_of(item[2]), item[3:]
    options = dict(zip(rest[::2], rest[1::2]))
    allowed = {":status", ":icon", ":group", ":priority", link_key.get(kind)} - {None}
    if len(rest) % 2 or set(options) - allowed:
        raise ValueError(f"{node_id}: bad options {rest!r}")
    target = options.get(link_key.get(kind))
    links = tuple(target) if isinstance(target, list) else (target,) if target else ()
    icon = text_of(options[":icon"]) if ":icon" in options else None
    group = text_of(options[":group"]) if ":group" in options else None
    return Node(kind, node_id, text, links, options.get(":status"), icon, group, int(options.get(":priority", 0)))


def read_ref(item: list) -> Ref:
    if len(item) not in (2, 3) or not isinstance(item[1], str) or not SLUG.fullmatch(item[1]):
        raise ValueError(f"bad ref {item!r}: expected (ref other-slug \"why\")")
    return Ref(item[1], text_of(item[2]) if len(item) == 3 else "")


def read_map(source: str) -> IntentMap:
    form = parse(source)
    nodes, refs, project = [], [], None
    for item in form[2:]:
        head = item[0] if isinstance(item, list) and item else None
        if head == "project":
            if project is not None or len(item) != 2:
                raise ValueError(f"bad or repeated project form {item!r}: expected one (project \"name\")")
            project = text_of(item[1])
        elif head == "ref":
            refs.append(read_ref(item))
        elif head in KINDS:
            nodes.append(read_node(item))
        else:
            raise ValueError(f"unknown form {item!r}: expected one of {KINDS + ('project', 'ref')}")
    return IntentMap(text_of(form[1]), nodes, project, tuple(refs))


def read(source: str) -> tuple[str, list[Node]]:
    parsed = read_map(source)
    return parsed.title, parsed.nodes
