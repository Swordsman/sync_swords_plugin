"""Register shellcrawl-specific builtins into a pisces Evaluator.

These are the ONLY primitives the pisces shell layer can call.
No shell, http-post, or env builtins — sandbox by design.
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from pisces.eval import Environment, Evaluator, ShellConfig

from .vfs import VirtualFS


def _val(v: Any) -> Any:
    """Normalize a Python value for pisces consumption."""
    if v is None:
        return "nil"
    if isinstance(v, bool):
        return v
    return v


class ShellCrawlRuntime:
    """Holds all mutable state and exposes it as pisces builtins."""

    def __init__(self, fs: VirtualFS) -> None:
        self.fs = fs
        self.state: Dict[str, Any] = {
            "cwd": "/home/user",
            "user": "user",
            "hostname": "localhost",
            "home": "/home/user",
        }
        self.stdout_buf: List[str] = []
        self.stderr_buf: List[str] = []
        self.procs: Dict[int, Dict[str, Any]] = {}
        self._next_pid = 100
        self.env_vars: Dict[str, str] = {
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "HOME": "/home/user",
            "USER": "user",
            "SHELL": "/bin/bash",
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
            "PWD": "/home/user",
        }
        self.history: List[str] = []
        self._capture_stack: List[int] = []
        self._hooks_enter: Dict[str, Any] = {}
        self._hooks_read: Dict[str, Any] = {}
        self._hooks_cmd: Dict[str, Any] = {}
        self._event_handlers: Dict[str, List[Any]] = {}

    def create_evaluator(self, max_steps: int = 500_000,
                         timeout: float = 10.0) -> Evaluator:
        """Create a pisces Evaluator with shellcrawl builtins only."""
        ev = Evaluator(
            max_steps=max_steps,
            max_recursion_depth=500,
            timeout=timeout,
            shell_config=ShellConfig(backend="local"),
        )
        # Wipe the default builtins we don't want
        for forbidden in ("shell", "http-post", "env"):
            try:
                ev._global_env._bindings.pop(forbidden, None)
            except Exception:
                pass

        self._register_all(ev)
        return ev

    def _register_all(self, ev: Evaluator) -> None:
        b = ev._global_env
        reg = b.define

        # -- filesystem -------------------------------------------------------
        reg("fs-read", self._fs_read)
        reg("fs-write", self._fs_write)
        reg("fs-list", self._fs_list)
        reg("fs-stat", self._fs_stat)
        reg("fs-exists", self._fs_exists)
        reg("fs-is-dir", self._fs_is_dir)
        reg("fs-mkdir", self._fs_mkdir)
        reg("fs-rm", self._fs_rm)
        reg("fs-chmod", self._fs_chmod)
        reg("fs-resolve", self._fs_resolve)
        reg("fs-walk", self._fs_walk)

        # -- state ------------------------------------------------------------
        reg("state-get", self._state_get)
        reg("state-set", self._state_set)
        reg("state-get-cwd", self._state_get_cwd)
        reg("state-set-cwd", self._state_set_cwd)

        # -- output -----------------------------------------------------------
        reg("emit", self._emit)
        reg("emit-line", self._emit_line)
        reg("emit-error", self._emit_error)
        reg("stdout-capture-start", self._stdout_capture_start)
        reg("stdout-capture-end", self._stdout_capture_end)

        # -- process table ----------------------------------------------------
        reg("proc-list", self._proc_list)
        reg("proc-add", self._proc_add)
        reg("proc-kill", self._proc_kill)
        reg("proc-get", self._proc_get)

        # -- environment variables --------------------------------------------
        reg("env-get", self._env_get)
        reg("env-set", self._env_set)
        reg("env-list", self._env_list)

        # -- history ----------------------------------------------------------
        reg("history-list", self._history_list)
        reg("history-add", self._history_add)

        # -- hooks/events (for DM) --------------------------------------------
        reg("on-enter-dir", self._on_enter_dir)
        reg("on-read-file", self._on_read_file)
        reg("on-command", self._on_command)
        reg("trigger", self._trigger)

        # -- string utilities -------------------------------------------------
        reg("str-split", self._str_split)
        reg("str-join", self._str_join)
        reg("str-contains", self._str_contains)
        reg("str-replace", self._str_replace)
        reg("str-length", self._str_length)
        reg("str-substr", self._str_substr)
        reg("str-pad-right", self._str_pad_right)
        reg("str-pad-left", self._str_pad_left)
        reg("str-lines", self._str_lines)
        reg("str-trim", self._str_trim)
        reg("str-starts-with", self._str_starts_with)
        reg("str-ends-with", self._str_ends_with)
        reg("str-upper", self._str_upper)
        reg("str-lower", self._str_lower)
        reg("str-concat", self._str_concat)
        reg("str-char-at", self._str_char_at)
        reg("str-index-of", self._str_index_of)
        reg("regex-match", self._regex_match)
        reg("regex-match-all", self._regex_match_all)

        # -- numeric helpers --------------------------------------------------
        reg("number->string", self._number_to_string)
        reg("string->number", self._string_to_number)
        reg("modulo", self._modulo)

        # -- list utilities ---------------------------------------------------
        reg("length", self._length)
        reg("append", self._append)
        reg("reverse", self._reverse)
        reg("map", self._map)
        reg("filter", self._filter_fn)
        reg("for-each", self._for_each)
        reg("member", self._member)
        reg("assoc", self._assoc)
        reg("alist-ref", self._alist_ref)
        reg("range", self._range)
        reg("sort", self._sort)
        reg("list-ref", self._list_ref)
        reg("null?", self._null_p)
        reg("pair?", self._pair_p)
        reg("string?", self._string_p)
        reg("number?", self._number_p)

        # -- time -------------------------------------------------------------
        reg("current-time", self._current_time)
        reg("format-time", self._format_time)

        # Keep a reference so hooks can eval
        self._evaluator = ev

    # =====================================================================
    # Filesystem builtins
    # =====================================================================

    def _cwd(self) -> str:
        return self.state["cwd"]

    def _fs_read(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("fs-read: expected 1 arg")
        result = self.fs.read(str(args[0]), self._cwd())
        # Fire read hook if registered
        abs_path = self.fs.resolve_path(self._cwd(), str(args[0]))
        if abs_path in self._hooks_read:
            self._evaluator.eval(
                self._hooks_read[abs_path],
                self._evaluator._global_env,
            )
        return _val(result)

    def _fs_write(self, args: list) -> Any:
        if len(args) < 2:
            raise TypeError("fs-write: expected 2 args")
        ok = self.fs.write(str(args[0]), str(args[1]), self._cwd())
        return _val(ok)

    def _fs_list(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("fs-list: expected 1 arg")
        result = self.fs.ls(str(args[0]), self._cwd())
        return result if result is not None else "nil"

    def _fs_stat(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("fs-stat: expected 1 arg")
        info = self.fs.stat(str(args[0]), self._cwd())
        if info is None:
            return "nil"
        return [(k, v) for k, v in info.items()]

    def _fs_exists(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("fs-exists: expected 1 arg")
        return _val(self.fs.exists(str(args[0]), self._cwd()))

    def _fs_is_dir(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("fs-is-dir: expected 1 arg")
        return _val(self.fs.is_dir(str(args[0]), self._cwd()))

    def _fs_mkdir(self, args: list) -> Any:
        if len(args) < 1:
            raise TypeError("fs-mkdir: expected 1+ args")
        parents = len(args) > 1 and args[1] is True
        return _val(self.fs.mkdir(str(args[0]), self._cwd(), parents=parents))

    def _fs_rm(self, args: list) -> Any:
        if len(args) < 1:
            raise TypeError("fs-rm: expected 1+ args")
        recursive = len(args) > 1 and args[1] is True
        return _val(self.fs.rm(str(args[0]), self._cwd(), recursive=recursive))

    def _fs_chmod(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("fs-chmod: expected 2 args")
        return _val(self.fs.chmod(str(args[0]), int(args[1]), self._cwd()))

    def _fs_resolve(self, args: list) -> str:
        if len(args) < 1:
            raise TypeError("fs-resolve: expected 1+ args")
        cwd = str(args[1]) if len(args) > 1 else self._cwd()
        return self.fs.resolve_path(cwd, str(args[0]))

    def _fs_walk(self, args: list) -> list:
        path = str(args[0]) if args else "/"
        result = self.fs.walk(path, self._cwd())
        return [list(item) for item in result]

    # =====================================================================
    # State builtins
    # =====================================================================

    def _state_get(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("state-get: expected 1 arg")
        return _val(self.state.get(str(args[0])))

    def _state_set(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("state-set: expected 2 args")
        self.state[str(args[0])] = args[1]
        return args[1]

    def _state_get_cwd(self, args: list) -> str:
        return self.state["cwd"]

    def _state_set_cwd(self, args: list) -> str:
        if len(args) != 1:
            raise TypeError("state-set-cwd: expected 1 arg")
        self.state["cwd"] = str(args[0])
        self.env_vars["PWD"] = str(args[0])
        return str(args[0])

    # =====================================================================
    # Output builtins
    # =====================================================================

    def _emit(self, args: list) -> str:
        text = str(args[0]) if args else ""
        self.stdout_buf.append(text)
        return "nil"

    def _emit_line(self, args: list) -> str:
        text = str(args[0]) if args else ""
        self.stdout_buf.append(text + "\n")
        return "nil"

    def _emit_error(self, args: list) -> str:
        text = str(args[0]) if args else ""
        self.stderr_buf.append(text + "\n")
        return "nil"

    def _stdout_capture_start(self, args: list) -> str:
        self._capture_stack.append(len(self.stdout_buf))
        return "nil"

    def _stdout_capture_end(self, args: list) -> str:
        if not self._capture_stack:
            return ""
        start_idx = self._capture_stack.pop()
        captured = self.stdout_buf[start_idx:]
        del self.stdout_buf[start_idx:]
        return "".join(captured)

    # =====================================================================
    # Process table
    # =====================================================================

    def _proc_list(self, args: list) -> list:
        return [[pid, [[k, v] for k, v in info.items()]]
                for pid, info in sorted(self.procs.items())]

    def _proc_add(self, args: list) -> int:
        if len(args) < 1:
            raise TypeError("proc-add: expected 1+ args")
        name = str(args[0])
        pid = int(args[1]) if len(args) > 1 else self._next_pid
        self._next_pid = max(self._next_pid, pid + 1)
        self.procs[pid] = {
            "name": name,
            "user": self.state.get("user", "root"),
            "cpu": "0.0",
            "mem": "0.1",
            "vsz": "4096",
            "rss": "1024",
            "tty": "?",
            "stat": "S",
            "start": "00:00",
            "time": "0:00",
            "cmd": name,
        }
        if len(args) > 2 and isinstance(args[2], list):
            for pair in args[2]:
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    self.procs[pid][str(pair[0])] = str(pair[1])
        return pid

    def _proc_kill(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("proc-kill: expected 1 arg")
        pid = int(args[0])
        return _val(self.procs.pop(pid, None) is not None)

    def _proc_get(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("proc-get: expected 1 arg")
        info = self.procs.get(int(args[0]))
        if info is None:
            return "nil"
        return [(k, v) for k, v in info.items()]

    # =====================================================================
    # Environment variables
    # =====================================================================

    def _env_get(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("env-get: expected 1 arg")
        return _val(self.env_vars.get(str(args[0])))

    def _env_set(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("env-set: expected 2 args")
        self.env_vars[str(args[0])] = str(args[1])
        return str(args[1])

    def _env_list(self, args: list) -> list:
        return [[k, v] for k, v in sorted(self.env_vars.items())]

    # =====================================================================
    # History
    # =====================================================================

    def _history_list(self, args: list) -> list:
        return list(self.history)

    def _history_add(self, args: list) -> str:
        if len(args) != 1:
            raise TypeError("history-add: expected 1 arg")
        self.history.append(str(args[0]))
        return "nil"

    # =====================================================================
    # Hooks / events (for DM use)
    # =====================================================================

    def _on_enter_dir(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("on-enter-dir: expected 2 args (path, callback)")
        self._hooks_enter[str(args[0])] = args[1]
        return "nil"

    def _on_read_file(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("on-read-file: expected 2 args (path, callback)")
        self._hooks_read[str(args[0])] = args[1]
        return "nil"

    def _on_command(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("on-command: expected 2 args (name, callback)")
        self._hooks_cmd[str(args[0])] = args[1]
        return "nil"

    def _trigger(self, args: list) -> str:
        if len(args) < 1:
            raise TypeError("trigger: expected 1+ args")
        event = str(args[0])
        for handler in self._event_handlers.get(event, []):
            self._evaluator.eval(handler, self._evaluator._global_env)
        return "nil"

    def fire_enter_dir(self, path: str) -> None:
        if path in self._hooks_enter:
            self._evaluator.eval(
                self._hooks_enter[path],
                self._evaluator._global_env,
            )

    def get_command_hook(self, name: str) -> Optional[Any]:
        return self._hooks_cmd.get(name)

    # =====================================================================
    # String utilities
    # =====================================================================

    def _str_split(self, args: list) -> list:
        if len(args) < 1:
            raise TypeError("str-split: expected 1-2 args")
        s = str(args[0])
        delim = str(args[1]) if len(args) > 1 else None
        return s.split(delim) if delim else s.split()

    def _str_join(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("str-join: expected 2 args (list, delim)")
        items = args[0] if isinstance(args[0], list) else [args[0]]
        return str(args[1]).join(str(x) for x in items)

    def _str_contains(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("str-contains: expected 2 args")
        return _val(str(args[1]) in str(args[0]))

    def _str_replace(self, args: list) -> str:
        if len(args) != 3:
            raise TypeError("str-replace: expected 3 args")
        return str(args[0]).replace(str(args[1]), str(args[2]))

    def _str_length(self, args: list) -> int:
        if len(args) != 1:
            raise TypeError("str-length: expected 1 arg")
        return len(str(args[0]))

    def _str_substr(self, args: list) -> str:
        if len(args) < 2:
            raise TypeError("str-substr: expected 2-3 args")
        s = str(args[0])
        start = int(args[1])
        end = int(args[2]) if len(args) > 2 else len(s)
        return s[start:end]

    def _str_pad_right(self, args: list) -> str:
        if len(args) < 2:
            raise TypeError("str-pad-right: expected 2-3 args")
        s = str(args[0])
        width = int(args[1])
        pad = str(args[2]) if len(args) > 2 else " "
        return s.ljust(width, pad[0] if pad else " ")

    def _str_pad_left(self, args: list) -> str:
        if len(args) < 2:
            raise TypeError("str-pad-left: expected 2-3 args")
        s = str(args[0])
        width = int(args[1])
        pad = str(args[2]) if len(args) > 2 else " "
        return s.rjust(width, pad[0] if pad else " ")

    def _str_lines(self, args: list) -> list:
        if len(args) != 1:
            raise TypeError("str-lines: expected 1 arg")
        return str(args[0]).splitlines()

    def _str_trim(self, args: list) -> str:
        if len(args) != 1:
            raise TypeError("str-trim: expected 1 arg")
        return str(args[0]).strip()

    def _str_starts_with(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("str-starts-with: expected 2 args")
        return _val(str(args[0]).startswith(str(args[1])))

    def _str_ends_with(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("str-ends-with: expected 2 args")
        return _val(str(args[0]).endswith(str(args[1])))

    def _str_upper(self, args: list) -> str:
        return str(args[0]).upper()

    def _str_lower(self, args: list) -> str:
        return str(args[0]).lower()

    def _str_concat(self, args: list) -> str:
        return "".join(str(a) for a in args)

    def _str_char_at(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("str-char-at: expected 2 args")
        s = str(args[0])
        i = int(args[1])
        return s[i] if 0 <= i < len(s) else "nil"

    def _str_index_of(self, args: list) -> int:
        if len(args) != 2:
            raise TypeError("str-index-of: expected 2 args")
        return str(args[0]).find(str(args[1]))

    def _regex_match(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("regex-match: expected 2 args (pattern, string)")
        m = re.search(str(args[0]), str(args[1]))
        if m is None:
            return "nil"
        return list(m.groups()) if m.groups() else [m.group(0)]

    def _regex_match_all(self, args: list) -> list:
        if len(args) != 2:
            raise TypeError("regex-match-all: expected 2 args")
        return re.findall(str(args[0]), str(args[1]))

    # =====================================================================
    # Numeric helpers
    # =====================================================================

    def _number_to_string(self, args: list) -> str:
        if len(args) != 1:
            raise TypeError("number->string: expected 1 arg")
        n = args[0]
        return str(int(n)) if isinstance(n, float) and n == int(n) else str(n)

    def _string_to_number(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("string->number: expected 1 arg")
        s = str(args[0])
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return "nil"

    def _modulo(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("modulo: expected 2 args")
        return int(args[0]) % int(args[1])

    # =====================================================================
    # List utilities
    # =====================================================================

    def _length(self, args: list) -> int:
        if len(args) != 1:
            raise TypeError("length: expected 1 arg")
        v = args[0]
        if isinstance(v, (list, str)):
            return len(v)
        return 0

    def _append(self, args: list) -> list:
        result = []
        for a in args:
            if isinstance(a, list):
                result.extend(a)
            else:
                result.append(a)
        return result

    def _reverse(self, args: list) -> list:
        if len(args) != 1:
            raise TypeError("reverse: expected 1 arg")
        return list(reversed(args[0])) if isinstance(args[0], list) else args[0]

    def _map(self, args: list) -> list:
        if len(args) != 2:
            raise TypeError("map: expected 2 args (fn, list)")
        fn, lst = args
        if not isinstance(lst, list):
            return []
        return [self._evaluator._apply(fn, [x]) for x in lst]

    def _filter_fn(self, args: list) -> list:
        if len(args) != 2:
            raise TypeError("filter: expected 2 args (fn, list)")
        fn, lst = args
        if not isinstance(lst, list):
            return []
        from pisces.eval import _value_to_bool
        return [x for x in lst if _value_to_bool(self._evaluator._apply(fn, [x]))]

    def _for_each(self, args: list) -> str:
        if len(args) != 2:
            raise TypeError("for-each: expected 2 args (fn, list)")
        fn, lst = args
        if isinstance(lst, list):
            for x in lst:
                self._evaluator._apply(fn, [x])
        return "nil"

    def _member(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("member: expected 2 args")
        item, lst = args
        if isinstance(lst, list):
            return _val(str(item) in [str(x) for x in lst])
        return "#f"

    def _assoc(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("assoc: expected 2 args (key, alist)")
        key, alist = str(args[0]), args[1]
        if isinstance(alist, list):
            for pair in alist:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    if str(pair[0]) == key:
                        return list(pair)
        return "nil"

    def _alist_ref(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("alist-ref: expected 2 args (key, alist)")
        key, alist = str(args[0]), args[1]
        if isinstance(alist, list):
            for pair in alist:
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    if str(pair[0]) == key:
                        return pair[1]
        return "nil"

    def _range(self, args: list) -> list:
        if len(args) == 1:
            return list(range(int(args[0])))
        if len(args) == 2:
            return list(range(int(args[0]), int(args[1])))
        if len(args) == 3:
            return list(range(int(args[0]), int(args[1]), int(args[2])))
        raise TypeError("range: expected 1-3 args")

    def _sort(self, args: list) -> list:
        if len(args) != 1:
            raise TypeError("sort: expected 1 arg")
        if isinstance(args[0], list):
            return sorted(args[0], key=str)
        return args[0]

    def _list_ref(self, args: list) -> Any:
        if len(args) != 2:
            raise TypeError("list-ref: expected 2 args (list, index)")
        lst, idx = args
        if isinstance(lst, list) and 0 <= int(idx) < len(lst):
            return lst[int(idx)]
        return "nil"

    def _null_p(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("null?: expected 1 arg")
        v = args[0]
        return _val(v == "nil" or v == [] or v is None)

    def _pair_p(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("pair?: expected 1 arg")
        return _val(isinstance(args[0], (list, tuple)) and len(args[0]) > 0)

    def _string_p(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("string?: expected 1 arg")
        return _val(isinstance(args[0], str) and args[0] not in ("nil", "#t", "#f"))

    def _number_p(self, args: list) -> Any:
        if len(args) != 1:
            raise TypeError("number?: expected 1 arg")
        return _val(isinstance(args[0], (int, float)))

    # =====================================================================
    # Time
    # =====================================================================

    def _current_time(self, args: list) -> float:
        return time.time()

    def _format_time(self, args: list) -> str:
        if len(args) < 1:
            raise TypeError("format-time: expected 1-2 args")
        ts = float(args[0])
        fmt = str(args[1]) if len(args) > 1 else "%b %d %H:%M"
        return time.strftime(fmt, time.localtime(ts))
