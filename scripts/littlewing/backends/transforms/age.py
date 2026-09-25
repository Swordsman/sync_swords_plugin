"""Age encryption transform.

Uses the `age` CLI tool (https://age-encryption.org/).
Encrypt with a recipient public key, decrypt with the identity (private key).

Config examples:
    # Encrypt-only (archival — you have the private key elsewhere):
    {"name": "age", "recipient": "age1ql3z7hjy54pw3hyww5ayyfg7zqgvc7w3j2elw8zmrj2kg5sfn9aqmcac8p"}

    # Encrypt + decrypt (full round-trip):
    {"name": "age", "recipient": "age1...", "identity": "/path/to/key.txt"}

    # Passphrase mode (symmetric, interactive-unfriendly but simple):
    {"name": "age", "passphrase": "my-secret"}
"""

import shutil
import subprocess
from backends.transforms import Transform


class AgeTransform(Transform):
    name = "age"

    def __init__(
        self,
        recipient: str | None = None,
        identity: str | None = None,
        passphrase: str | None = None,
    ):
        if not shutil.which("age"):
            raise RuntimeError("age not installed — apt-get install age")
        if not recipient and not passphrase:
            raise ValueError("age transform needs recipient or passphrase")
        self.recipient = recipient
        self.identity = identity
        self.passphrase = passphrase

    def encode(self, data: bytes) -> bytes:
        if self.recipient:
            cmd = ["age", "--encrypt", "--recipient", self.recipient]
            result = subprocess.run(
                cmd, input=data, capture_output=True, timeout=30,
            )
        elif self.passphrase:
            # Pipe passphrase via a temporary identity approach:
            # age doesn't support non-interactive passphrase encrypt in older versions,
            # so we use scrypt-based recipient via a temp key derived from passphrase.
            import tempfile, hashlib
            cmd = ["age", "--encrypt", "--passphrase"]
            with tempfile.NamedTemporaryFile(mode="w", suffix=".pass", delete=False) as f:
                f.write(self.passphrase + "\n")
                pass_file = f.name
            try:
                import os
                env = os.environ.copy()
                result = subprocess.run(
                    cmd, input=data, capture_output=True, timeout=30,
                    env={**env, "AGE_PASSPHRASE": self.passphrase},
                )
                if result.returncode != 0:
                    # Fallback: pipe passphrase on stdin before data
                    # Not possible with age CLI — raise clear error
                    raise RuntimeError(
                        "age passphrase mode requires age 1.2+ or AGE_PASSPHRASE support. "
                        "Use recipient/identity mode instead."
                    )
            finally:
                import os
                os.unlink(pass_file)
        else:
            raise RuntimeError("age encrypt needs recipient or passphrase")

        if result.returncode != 0:
            raise RuntimeError(f"age encrypt: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout

    def decode(self, data: bytes) -> bytes:
        if self.identity:
            cmd = ["age", "--decrypt", "--identity", self.identity]
        elif self.passphrase:
            raise RuntimeError(
                "age passphrase decrypt requires age 1.2+ or AGE_PASSPHRASE support. "
                "Use recipient/identity mode instead."
            )
        else:
            raise RuntimeError("age decrypt needs identity file or passphrase")

        result = subprocess.run(
            cmd, input=data, capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"age decrypt: {result.stderr.decode(errors='replace').strip()}")
        return result.stdout
