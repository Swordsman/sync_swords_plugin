"""Virtual filesystem: nested dicts, decorative metadata, no real I/O."""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

Path = str
Node = Union[Dict[str, Any], str]


class VirtualFS:
    """In-memory filesystem. Dirs are dicts, files are strings."""

    def __init__(self) -> None:
        self.root: Dict[str, Any] = {}
        self._permissions: Dict[str, int] = {}
        self._owners: Dict[str, Tuple[str, str]] = {}
        self._timestamps: Dict[str, float] = {}
        self._links: Dict[str, int] = {}

    def _split(self, path: Path) -> List[str]:
        return [p for p in path.split("/") if p]

    def _resolve(self, path: Path, cwd: Path = "/") -> Path:
        if not path.startswith("/"):
            path = os.path.join(cwd, path)
        parts: List[str] = []
        for p in self._split(path):
            if p == "..":
                if parts:
                    parts.pop()
            elif p != ".":
                parts.append(p)
        return "/" + "/".join(parts)

    def _get_node(self, path: Path) -> Optional[Node]:
        if path == "/":
            return self.root
        parts = self._split(path)
        node: Node = self.root
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def _get_parent(self, path: Path) -> Tuple[Optional[Dict[str, Any]], str]:
        parts = self._split(path)
        if not parts:
            return None, ""
        name = parts[-1]
        parent_path = "/" + "/".join(parts[:-1])
        parent = self._get_node(parent_path)
        if not isinstance(parent, dict):
            return None, name
        return parent, name

    def _touch(self, abs_path: str) -> None:
        self._timestamps.setdefault(abs_path, time.time())

    def _set_defaults(self, abs_path: str, is_dir: bool,
                      owner: str = "root", group: str = "root") -> None:
        self._permissions.setdefault(abs_path, 0o755 if is_dir else 0o644)
        self._owners.setdefault(abs_path, (owner, group))
        self._touch(abs_path)

    def resolve_path(self, cwd: Path, path: Path) -> Path:
        return self._resolve(path, cwd)

    def stat(self, path: Path, cwd: Path = "/") -> Optional[Dict[str, Any]]:
        abs_path = self._resolve(path, cwd)
        node = self._get_node(abs_path)
        if node is None:
            return None
        is_dir = isinstance(node, dict)
        perms = self._permissions.get(abs_path, 0o755 if is_dir else 0o644)
        owner = self._owners.get(abs_path, ("root", "root"))
        ts = self._timestamps.get(abs_path, 1735689600.0)  # 2025-01-01
        nlinks = self._links.get(abs_path, 2 if is_dir else 1)
        size = len(node) if isinstance(node, str) else len(node)
        return {
            "path": abs_path,
            "is_dir": is_dir,
            "size": size,
            "permissions": perms,
            "uid": owner[0],
            "gid": owner[1],
            "nlinks": nlinks,
            "mtime": ts,
        }

    def exists(self, path: Path, cwd: Path = "/") -> bool:
        return self._get_node(self._resolve(path, cwd)) is not None

    def is_dir(self, path: Path, cwd: Path = "/") -> bool:
        node = self._get_node(self._resolve(path, cwd))
        return isinstance(node, dict)

    def read(self, path: Path, cwd: Path = "/") -> Optional[str]:
        node = self._get_node(self._resolve(path, cwd))
        return node if isinstance(node, str) else None

    def write(self, path: Path, content: str, cwd: Path = "/",
              owner: str = "root", group: str = "root") -> bool:
        abs_path = self._resolve(path, cwd)
        parent, name = self._get_parent(abs_path)
        if parent is None or name == "":
            return False
        if isinstance(parent.get(name), dict):
            return False
        parent[name] = content
        self._set_defaults(abs_path, False, owner, group)
        self._timestamps[abs_path] = time.time()
        return True

    def mkdir(self, path: Path, cwd: Path = "/", parents: bool = False,
              owner: str = "root", group: str = "root") -> bool:
        abs_path = self._resolve(path, cwd)
        if self._get_node(abs_path) is not None:
            return False
        if parents:
            parts = self._split(abs_path)
            current: Dict[str, Any] = self.root
            built = "/"
            for part in parts:
                built = built.rstrip("/") + "/" + part
                if part not in current:
                    current[part] = {}
                    self._set_defaults(built, True, owner, group)
                current = current[part]
            return True
        parent, name = self._get_parent(abs_path)
        if parent is None or name == "" or name in parent:
            return False
        parent[name] = {}
        self._set_defaults(abs_path, True, owner, group)
        return True

    def ls(self, path: Path, cwd: Path = "/") -> Optional[List[str]]:
        node = self._get_node(self._resolve(path, cwd))
        return sorted(node.keys()) if isinstance(node, dict) else None

    def rm(self, path: Path, cwd: Path = "/", recursive: bool = False) -> bool:
        abs_path = self._resolve(path, cwd)
        node = self._get_node(abs_path)
        if node is None:
            return False
        if isinstance(node, dict) and not recursive:
            return False
        parent, name = self._get_parent(abs_path)
        if parent is None or name == "":
            return False
        del parent[name]
        prefix = abs_path + "/"
        for store in (self._permissions, self._owners, self._timestamps, self._links):
            for key in [k for k in store if k == abs_path or k.startswith(prefix)]:
                del store[key]
        return True

    def chmod(self, path: Path, mode: int, cwd: Path = "/") -> bool:
        abs_path = self._resolve(path, cwd)
        if self._get_node(abs_path) is None:
            return False
        self._permissions[abs_path] = mode & 0o777
        return True

    def walk(self, path: Path = "/", cwd: Path = "/") -> List[Tuple[str, List[str], List[str]]]:
        """Walk the tree like os.walk. Returns (dirpath, dirnames, filenames)."""
        abs_path = self._resolve(path, cwd)
        node = self._get_node(abs_path)
        if not isinstance(node, dict):
            return []
        result = []
        self._walk_recursive(abs_path, node, result)
        return result

    def _walk_recursive(self, path: str, node: dict,
                        result: List[Tuple[str, List[str], List[str]]]) -> None:
        dirs = sorted(k for k, v in node.items() if isinstance(v, dict))
        files = sorted(k for k, v in node.items() if isinstance(v, str))
        result.append((path, dirs, files))
        for d in dirs:
            child_path = path.rstrip("/") + "/" + d
            self._walk_recursive(child_path, node[d], result)
