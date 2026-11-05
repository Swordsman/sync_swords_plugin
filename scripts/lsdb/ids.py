"""Artifact URL / id -> the artifact's UUID, which the db endpoint calls its "slug"."""

import re

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_SHORT_ID_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{22}$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def artifact_uuid(url_or_id: str) -> str:
    """Accepts claude.ai/artifact/<id>, claude.ai/code/artifact/<uuid>, a bare base58 id or a bare UUID.

    Raises ValueError for anything else.
    """
    segment = _artifact_segment(url_or_id)
    if _UUID_RE.match(segment):
        return segment.lower()
    if not _SHORT_ID_RE.match(segment):
        raise ValueError(f"not an artifact URL or id: {url_or_id!r}")
    value = _base58_value(segment)
    if value >= 1 << 128:
        raise ValueError(f"artifact id out of range: {url_or_id!r}")
    return _format_uuid(value)


def _artifact_segment(url_or_id: str) -> str:
    """The last path segment after /artifact/, or the bare id."""
    path = re.split(r"[?#]", url_or_id.strip(), maxsplit=1)[0]
    parts = [part for part in path.split("/") if part]
    if not parts or (len(parts) > 1 and parts[-2] != "artifact"):
        raise ValueError(f"not an artifact URL or id: {url_or_id!r}")
    return parts[-1]


def _base58_value(text: str) -> int:
    value = 0
    for char in text:
        value = value * 58 + BASE58_ALPHABET.index(char)
    return value


def _format_uuid(value: int) -> str:
    hex_digits = f"{value:032x}"
    return "-".join((hex_digits[:8], hex_digits[8:12], hex_digits[12:16], hex_digits[16:20], hex_digits[20:]))
