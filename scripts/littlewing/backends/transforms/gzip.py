"""Gzip compression transform. Stdlib, no dependencies."""

import gzip as _gzip
from backends.transforms import Transform


class GzipTransform(Transform):
    name = "gzip"

    def __init__(self, level: int = 6):
        self.level = level

    def encode(self, data: bytes) -> bytes:
        return _gzip.compress(data, compresslevel=self.level)

    def decode(self, data: bytes) -> bytes:
        return _gzip.decompress(data)
