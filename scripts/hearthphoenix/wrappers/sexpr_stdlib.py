"""Prebuilt s-expr adaptations — stage 3 of adaptive translation.

The stdlib from design/adaptive-translation-contracts-design.md §3:
each function returns pisces s-expression *source* for one common
Message adaptation. Sources are plain strings, so they content-hash
and cache exactly like hand-written transforms, and they can be
composed with :func:`compose_transforms`.

    from hearthphoenix.wrappers import sexpr_stdlib as std

    t = std.compose_transforms(
            std.set_action("v2/echo"),
            std.rename_payload_field("msg", "message"),
            std.wrap_payload("data"))
    translator.register_transform("http", "pipe", t)

All alist manipulation is pure pisces (define + recursion) from the
shared _PRELUDE — no Python runs on the message path beyond the
evaluator itself.
"""

from __future__ import annotations

from typing import Callable

from .protocol import Message
from .sexpr_transform import compile_transform

# Pure-pisces association-list helpers, prepended to every stdlib source.
_PRELUDE = """
(define assoc (lambda (key al)
  (if (eq? al nil) nil
    (if (eq? (car (car al)) key) (car al) (assoc key (cdr al))))))
(define alist-remove (lambda (key al)
  (if (eq? al nil) nil
    (if (eq? (car (car al)) key)
        (alist-remove key (cdr al))
        (cons (car al) (alist-remove key (cdr al)))))))
(define alist-set (lambda (key val al)
  (cons (cons key val) (alist-remove key al))))
"""


def _q(s: str) -> str:
    """Quote a string for embedding in s-expr source."""
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'


def set_action(action: str) -> str:
    """Rewrite the message action."""
    return f'(cons (cons "action" {_q(action)}) nil)'


def set_metadata(key: str, value: str) -> str:
    """Set (or overwrite) one metadata key."""
    return (_PRELUDE +
            f'(cons (cons "metadata" (alist-set {_q(key)} {_q(value)} metadata)) nil)')


def rename_payload_field(old: str, new: str) -> str:
    """Rename a payload field; identity when the field is absent."""
    return (_PRELUDE + f"""
(begin
  (define entry (assoc {_q(old)} payload))
  (cons (cons "payload"
          (if (eq? entry nil)
              payload
              (alist-set {_q(new)} (cdr entry) (alist-remove {_q(old)} payload))))
        nil))
""")


def drop_payload_field(name: str) -> str:
    """Remove a payload field; identity when absent."""
    return (_PRELUDE +
            f'(cons (cons "payload" (alist-remove {_q(name)} payload)) nil)')


def wrap_payload(key: str) -> str:
    """Nest the whole payload under a single key (envelope)."""
    return (f'(cons (cons "payload" (cons (cons {_q(key)} payload) nil)) nil)')


def unwrap_payload(key: str) -> str:
    """Replace the payload with the value nested under *key*; identity
    when the key is absent."""
    return (_PRELUDE + f"""
(begin
  (define entry (assoc {_q(key)} payload))
  (cons (cons "payload" (if (eq? entry nil) payload (cdr entry))) nil))
""")


def compose_transforms(*sources: str, **kwargs) -> Callable[[Message], Message]:
    """Compile each source (individually content-hash cached) and chain
    them left to right into one Message → Message callable."""
    compiled = [compile_transform(src, **kwargs) for src in sources]

    def chained(message: Message) -> Message:
        for transform in compiled:
            message = transform(message)
        return message

    return chained
