"""S-expression Message transforms — stage 2 of adaptive translation.

Implements design/adaptive-translation-contracts-design.md §3/§5.2: a
transform at the ``MessageTranslator.translate()`` seam expressed as a
pisces s-expression, compiled once and cached by the content hash of its
source, evaluated under a least-privilege evaluator (no shell, no file
I/O, step + time limits), and gated by an optional output validator.

pisces is an OPTIONAL dependency: this module imports it lazily and the
rest of hearthphoenix (which is zero-dependency stdlib) never loads it.

The transform program sees the message decomposed into bindings:

    action    — string
    payload   — alist (pisces association list)
    metadata  — alist
    version   — int

and must evaluate to an alist; keys ``action``/``payload``/``metadata``/
``version`` override the original message's fields, anything omitted is
carried over unchanged. Example — rewrite the action and wrap the payload:

    (cons (cons "action" "v2/echo")
      (cons (cons "payload" (cons (cons "wrapped" payload) nil))
        nil))
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Any, Callable, Dict, Optional

from .protocol import Message


class TransformError(RuntimeError):
    """The transform program failed to evaluate or produced invalid output."""


_COMPILE_CACHE: Dict[str, "SExprTransform"] = {}


def _require_pisces():
    try:
        import pisces  # noqa: F401
        from pisces import Evaluator, SExpParser
        from pisces.eval import IOConfig, ShellConfig, _pisces_to_py, _py_to_pisces
    except ImportError as e:
        raise TransformError(
            "s-expr transforms require the optional 'pisces' package "
            "(https://github.com/swordsman/pisces); pip install it to use them"
        ) from e
    return Evaluator, SExpParser, ShellConfig, IOConfig, _py_to_pisces, _pisces_to_py


# Builtins a message transform legitimately needs: structure building,
# comparison, and JSON. No shell, no file I/O, no HTTP.
_TRANSFORM_ALLOWLIST = [
    "cons", "car", "cdr", "list",
    "eq?", "lt?", "gt?", "not", "and", "or",
    "+", "-", "*", "/",
    "json-parse", "json-stringify", "type",
]


class SExprTransform:
    """A compiled ``Message → Message`` transform.

    Instances are cached by content hash — construct via :func:`compile_transform`.
    """

    def __init__(self, source: str, *,
                 validator: Optional[Callable[[Message], bool]] = None,
                 max_steps: int = 100_000, timeout: float = 5.0) -> None:
        (Evaluator, SExpParser, ShellConfig, IOConfig,
         self._py_to_pisces, self._pisces_to_py) = _require_pisces()
        exprs = SExpParser().parse(source)
        if not exprs:
            raise TransformError("empty transform source")
        self.source = source
        self.content_hash = hashlib.sha256(source.encode()).hexdigest()
        self.validator = validator
        self._exprs = exprs  # parsed once; never re-parsed per message
        self._make_evaluator = lambda: Evaluator(
            max_steps=max_steps,
            timeout=timeout,
            shell_config=ShellConfig(backend="none"),
            io_config=IOConfig(sandbox_root=None),
            builtin_allowlist=_TRANSFORM_ALLOWLIST,
        )

    def __call__(self, message: Message) -> Message:
        evaluator = self._make_evaluator()
        env = evaluator._global_env
        env.define("action", message.action)
        env.define("payload", self._py_to_pisces(message.payload))
        env.define("metadata", self._py_to_pisces(message.metadata))
        env.define("version", message.version)
        try:
            result: Any = None
            for expr in self._exprs:
                result = evaluator.eval(expr)
        except Exception as e:
            raise TransformError(
                f"transform {self.content_hash[:12]} failed: {e}") from e

        fields = self._pisces_to_py(result)
        if fields is None:
            fields = {}
        if not isinstance(fields, dict):
            raise TransformError(
                f"transform {self.content_hash[:12]} must return an alist, "
                f"got {type(fields).__name__}")

        out = replace(
            message,
            action=fields.get("action", message.action),
            payload=fields.get("payload", message.payload),
            metadata=fields.get("metadata", message.metadata),
            version=fields.get("version", message.version),
        )
        if self.validator is not None and not self.validator(out):
            raise TransformError(
                f"transform {self.content_hash[:12]} output rejected by validator")
        return out


def compile_transform(source: str, *,
                      validator: Optional[Callable[[Message], bool]] = None,
                      max_steps: int = 100_000,
                      timeout: float = 5.0) -> SExprTransform:
    """Compile (or fetch from the content-hash cache) an s-expr transform."""
    key = hashlib.sha256(source.encode()).hexdigest()
    cached = _COMPILE_CACHE.get(key)
    if cached is not None and cached.validator is validator:
        return cached
    transform = SExprTransform(source, validator=validator,
                               max_steps=max_steps, timeout=timeout)
    _COMPILE_CACHE[key] = transform
    return transform


def register_sexpr_transform(translator, src_type: str, backend_type: str,
                             source: str, **kwargs) -> SExprTransform:
    """Compile *source* and register it on a MessageTranslator's seam."""
    transform = compile_transform(source, **kwargs)
    translator.register_transform(src_type, backend_type, transform)
    return transform
