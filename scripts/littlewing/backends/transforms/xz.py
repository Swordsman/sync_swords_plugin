"""xz (LZMA2) compression transform. Stdlib, no dependencies.

Roughly 30% smaller than gzip on session JSONL. Preset 6 is the default:
preset 9 buys a few percent for several times the CPU, which matters in a
SessionEnd hook with a 1.5 s budget.
"""

import lzma
from backends.transforms import Transform


class XzTransform(Transform):
    name = "xz"
    suffix = ".xz"

    def __init__(self, preset: int = 6):
        self.preset = preset

    def encode(self, data: bytes) -> bytes:
        return lzma.compress(data, preset=self.preset)

    def decode(self, data: bytes) -> bytes:
        return lzma.decompress(data)
