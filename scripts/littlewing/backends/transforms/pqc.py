"""Post-quantum hybrid encryption transform (X-Wing pattern).

Combines X25519 (classical) + ML-KEM-768 (post-quantum) via HKDF-SHA256,
then encrypts with AES-256-GCM. An adversary must break BOTH to recover
the symmetric key.

Requires: pqcrypto, cryptography (pyca)

Key management:
    Recipient generates a keypair once. The public keys (ML-KEM + X25519)
    are stored in a JSON keyfile. The private keys are stored separately.

    # Generate keypair:
    from backends.transforms.pqc import HybridPQCTransform
    pub, priv = HybridPQCTransform.generate_keypair()
    # pub  -> give to anyone who encrypts for you
    # priv -> keep secret, needed for decryption

Config examples:
    # Encrypt-only (archival):
    {"name": "pqc", "public_key_file": "/path/to/recipient.pub.json"}

    # Full round-trip:
    {"name": "pqc",
     "public_key_file": "/path/to/recipient.pub.json",
     "private_key_file": "/path/to/recipient.sec.json"}
"""
from __future__ import annotations

import json
import os
import struct

from backends.transforms import Transform

# Lazy imports — fail at instantiation, not at module load
_pqcrypto = None
_crypto = None


def _ensure_deps():
    global _pqcrypto, _crypto
    if _pqcrypto is None:
        from pqcrypto.kem import ml_kem_768
        _pqcrypto = ml_kem_768
    if _crypto is None:
        from cryptography.hazmat.primitives.asymmetric.x25519 import (
            X25519PrivateKey, X25519PublicKey,
        )
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.hashes import SHA256
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat, NoEncryption, PrivateFormat,
        )
        _crypto = type("C", (), {
            "X25519PrivateKey": X25519PrivateKey,
            "X25519PublicKey": X25519PublicKey,
            "HKDF": HKDF, "SHA256": SHA256, "AESGCM": AESGCM,
            "Encoding": Encoding, "PublicFormat": PublicFormat,
            "NoEncryption": NoEncryption, "PrivateFormat": PrivateFormat,
        })()


HEADER_MAGIC = b"LWPQC1"
HKDF_INFO = b"littlewing-pqc-hybrid-v1"


class HybridPQCTransform(Transform):
    name = "pqc"

    def __init__(
        self,
        public_key_file: str | None = None,
        private_key_file: str | None = None,
    ):
        _ensure_deps()
        self._pq_pk = None
        self._pq_sk = None
        self._x_pk = None
        self._x_sk = None

        if public_key_file:
            pub = json.loads(open(public_key_file).read())
            self._pq_pk = bytes.fromhex(pub["ml_kem_768_pk"])
            self._x_pk = _crypto.X25519PublicKey.from_public_bytes(
                bytes.fromhex(pub["x25519_pk"])
            )

        if private_key_file:
            sec = json.loads(open(private_key_file).read())
            self._pq_sk = bytes.fromhex(sec["ml_kem_768_sk"])
            self._x_sk = _crypto.X25519PrivateKey.from_private_bytes(
                bytes.fromhex(sec["x25519_sk"])
            )

    def encode(self, data: bytes) -> bytes:
        if self._pq_pk is None or self._x_pk is None:
            raise RuntimeError("pqc encode requires public_key_file")

        pq_ct, pq_ss = _pqcrypto.encaps(self._pq_pk)

        eph_sk = _crypto.X25519PrivateKey.generate()
        eph_pk_bytes = eph_sk.public_key().public_bytes(
            _crypto.Encoding.Raw, _crypto.PublicFormat.Raw,
        )
        x_ss = eph_sk.exchange(self._x_pk)

        aes_key = _crypto.HKDF(
            algorithm=_crypto.SHA256(), length=32,
            salt=None, info=HKDF_INFO,
        ).derive(pq_ss + x_ss)

        nonce = os.urandom(12)
        ciphertext = _crypto.AESGCM(aes_key).encrypt(nonce, data, None)

        # Header: magic | pq_ct_len (2B) | pq_ct | eph_x25519_pk (32B) | nonce (12B) | ciphertext
        header = (
            HEADER_MAGIC
            + struct.pack(">H", len(pq_ct))
            + pq_ct
            + eph_pk_bytes
            + nonce
        )
        return header + ciphertext

    def decode(self, data: bytes) -> bytes:
        if self._pq_sk is None or self._x_sk is None:
            raise RuntimeError("pqc decode requires private_key_file")

        if not data.startswith(HEADER_MAGIC):
            raise ValueError("not a LWPQC1 encrypted blob")

        off = len(HEADER_MAGIC)
        pq_ct_len = struct.unpack(">H", data[off:off + 2])[0]
        off += 2
        pq_ct = data[off:off + pq_ct_len]
        off += pq_ct_len
        eph_pk_bytes = data[off:off + 32]
        off += 32
        nonce = data[off:off + 12]
        off += 12
        ciphertext = data[off:]

        pq_ss = _pqcrypto.decaps(self._pq_sk, pq_ct)

        eph_pk = _crypto.X25519PublicKey.from_public_bytes(eph_pk_bytes)
        x_ss = self._x_sk.exchange(eph_pk)

        aes_key = _crypto.HKDF(
            algorithm=_crypto.SHA256(), length=32,
            salt=None, info=HKDF_INFO,
        ).derive(pq_ss + x_ss)

        return _crypto.AESGCM(aes_key).decrypt(nonce, ciphertext, None)

    @staticmethod
    def generate_keypair(
        public_key_file: str | None = None,
        private_key_file: str | None = None,
    ) -> tuple[dict, dict]:
        """Generate a hybrid keypair. Returns (pub_dict, priv_dict).

        If file paths are given, writes the keys as JSON.
        """
        _ensure_deps()

        pq_pk, pq_sk = _pqcrypto.keygen()
        x_sk = _crypto.X25519PrivateKey.generate()
        x_pk = x_sk.public_key()

        pub = {
            "algorithm": "x-wing-v1 (x25519 + ml-kem-768)",
            "ml_kem_768_pk": pq_pk.hex(),
            "x25519_pk": x_pk.public_bytes(
                _crypto.Encoding.Raw, _crypto.PublicFormat.Raw,
            ).hex(),
        }
        priv = {
            "algorithm": "x-wing-v1 (x25519 + ml-kem-768)",
            "ml_kem_768_sk": pq_sk.hex(),
            "x25519_sk": x_sk.private_bytes(
                _crypto.Encoding.Raw, _crypto.PrivateFormat.Raw,
                _crypto.NoEncryption(),
            ).hex(),
        }

        if public_key_file:
            with open(public_key_file, "w") as f:
                json.dump(pub, f, indent=2)
        if private_key_file:
            with open(private_key_file, "w") as f:
                json.dump(priv, f, indent=2)
                os.fchmod(f.fileno(), 0o600)

        return pub, priv
