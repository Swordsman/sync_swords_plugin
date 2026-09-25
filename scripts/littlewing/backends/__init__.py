"""Storage backend system — transports + transforms composed via Store.

Usage:
    from backends import Store, Transport, Transform

    store = Store(
        transport=Transport.get("local")(root="/path/to/raw"),
        transforms=[Transform.get("gzip")()],
    )
    store.write("session-abc.jsonl", data)
    data = store.read("session-abc.jsonl")

    # Or from config dict:
    store = Store.from_config({
        "transport": {"name": "rclone", "remote": "gdrive", "path": "littlewing/raw"},
        "transforms": [
            {"name": "gzip"},
            {"name": "age", "recipient": "age1..."},
        ],
    })
"""

from backends.transports import Transport
from backends.transforms import Transform


class Store:
    """Composes a transport with an ordered pipeline of transforms."""

    def __init__(
        self,
        transport: Transport,
        transforms: list[Transform] | None = None,
    ):
        self.transport = transport
        self.transforms = transforms or []

    def write(self, key: str, data: bytes) -> None:
        for t in self.transforms:
            data = t.encode(data)
        self.transport.write(key, data)

    def read(self, key: str) -> bytes:
        data = self.transport.read(key)
        for t in reversed(self.transforms):
            data = t.decode(data)
        return data

    def list(self) -> list[str]:
        return self.transport.list()

    def exists(self, key: str) -> bool:
        return self.transport.exists(key)

    def delete(self, key: str) -> None:
        self.transport.delete(key)

    @classmethod
    def from_config(cls, config: dict) -> "Store":
        """Build a Store from a config dict.

        Expected shape:
            {
                "transport": {"name": "local", "root": "/path/..."},
                "transforms": [
                    {"name": "gzip"},
                    {"name": "age", "recipient": "age1..."},
                ]
            }
        """
        tc = config["transport"]
        transport_cls = Transport.get(tc["name"])
        transport_kwargs = {k: v for k, v in tc.items() if k != "name"}
        transport = transport_cls(**transport_kwargs)

        transforms = []
        for xc in config.get("transforms", []):
            transform_cls = Transform.get(xc["name"])
            transform_kwargs = {k: v for k, v in xc.items() if k != "name"}
            transforms.append(transform_cls(**transform_kwargs))

        return cls(transport=transport, transforms=transforms)

    def __repr__(self) -> str:
        chain = " -> ".join(t.name for t in self.transforms)
        if chain:
            return f"Store({chain} -> {self.transport.name})"
        return f"Store({self.transport.name})"
