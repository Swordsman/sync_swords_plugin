"""Base85 text armor. Stdlib, no dependencies.

Turns binary (compressed or encrypted) data into plain ASCII text, for
stores that accept text only, such as Claude Docs uploads. Costs 25% in
size, against base64's 33%.

Output: one header line, then the base85 body wrapped at `width` columns.
The header carries the SHA-256 of the binary input, checked on decode,
and the storage key when Store sets `label`, since an upload can lose its
file name (Claude Docs keeps only an asset id):

    #littlewing-b85 v1 sha256=<hex> bytes=<n> key=<url-quoted key>
"""

import base64
import hashlib
from urllib.parse import quote, unquote
from backends.transforms import Transform

MAGIC = b"#littlewing-b85 v1"


class Base85Transform(Transform):
    name = "base85"
    suffix = ".b85"

    def __init__(self, width: int = 100):
        self.width = width
        self.label = None   # set per write by Store: the storage key

    @staticmethod
    def header_fields(data: bytes) -> dict:
        """Header fields of an armored file, {} if it isn't one."""
        header = data.split(b"\n", 1)[0]
        if not header.startswith(MAGIC):
            return {}
        fields = dict(f.split(b"=", 1) for f in header[len(MAGIC):].split() if b"=" in f)
        out = {k.decode(): v.decode() for k, v in fields.items()}
        if "key" in out:
            out["key"] = unquote(out["key"])
        return out

    def encode(self, data: bytes) -> bytes:
        body = base64.b85encode(data)
        lines = [body[i:i + self.width] for i in range(0, len(body), self.width)]
        header = MAGIC + b" sha256=" + hashlib.sha256(data).hexdigest().encode() \
            + b" bytes=" + str(len(data)).encode()
        if self.label:
            header += b" key=" + quote(self.label, safe="/").encode()
        return b"\n".join([header] + lines) + b"\n"

    def decode(self, data: bytes) -> bytes:
        fields = self.header_fields(data)
        want = fields.get("sha256", "")
        if not want:
            raise ValueError("not littlewing base85 armor, or its header is damaged")
        body = data.split(b"\n", 1)[1] if b"\n" in data else b""
        # b85 has no whitespace in its alphabet, so stripping it is lossless
        raw = base64.b85decode(b"".join(body.split()))
        if hashlib.sha256(raw).hexdigest() != want:
            raise ValueError("base85 armor: sha256 mismatch, file is damaged")
        return raw
