#!/usr/bin/env python3
"""xylem-server — browser-based terminal with xonsh + Hy agent.

Singleton shell: all WebSocket connections share the same PTY session.
All PTY output is logged to disk as timestamped asciicast v2.
"""
import os, sys, struct, fcntl, termios, signal, threading, json, asyncio, time, re
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, PlainTextResponse

app = FastAPI()

SESSIONS_ROOT = Path.home() / ".xylem" / "sessions"
SESSIONS_ROOT.mkdir(parents=True, exist_ok=True)

MIN_CHUNK_LINES = 100
DEFAULT_CHUNK_LINES = 2048

# Xylem epoch: 2026-06-01 00:00:00 UTC
XEPOCH = 1748736000.0

# ── PTY Log (asciicast v2, chunked to disk) ──────────────────────

ANSI_RE = re.compile(r'\x1b\[[^a-zA-Z]*[a-zA-Z]|\x1b[^[\\\x00-\x1f]')
PROMPT_RE = re.compile(r'xylem\s+\S+\s+>\s*$')


class PTYLog:
    """Append-only timestamped log with three streams:
      output/  — terminal output chunks (asciicast v2)
      input/   — keystroke input chunks (asciicast v2)
      commands/ — per-command files (input line + output until next prompt)
    """

    def __init__(self, session_dir, shell='xonsh', chunk_lines=DEFAULT_CHUNK_LINES,
                 naming='xepoch', tz_offset=None):
        self._dir = Path(session_dir)
        self._shell = shell
        self._naming = naming
        self._tz_offset = tz_offset
        self._sid = self._dir.name
        self._start = time.time()
        self._chunk_lines = max(chunk_lines, MIN_CHUNK_LINES)

        self._out_dir = self._dir / "output"
        self._in_dir = self._dir / "input"
        self._cmd_dir = self._dir / "commands"
        for d in (self._out_dir, self._in_dir, self._cmd_dir):
            d.mkdir(parents=True, exist_ok=True)

        self._out_f = None
        self._in_f = None
        self._out_lines = 0
        self._in_lines = 0
        self._out_chunks = 0
        self._in_chunks = 0
        self._open_out_chunk()
        self._open_in_chunk()

        self._cmd_f = None
        self._cmd_input = None
        self._cmd_count = 0

        meta = {
            "version": 2, "width": 120, "height": 30,
            "timestamp": int(self._start),
            "chunk_lines": self._chunk_lines,
            "shell": shell,
            "naming": naming,
            "tz_offset": tz_offset,
            "epoch": "2026-06-01T00:00:00Z",
            "env": {"TERM": "xterm-256color", "SHELL": shell}
        }
        (self._dir / "meta.json").write_text(json.dumps(meta, indent=2) + '\n')

    def _chunk_name(self):
        now = time.time()
        if self._naming == 'x-human':
            dt = datetime.fromtimestamp(now, tz=timezone.utc)
            cs = int((now % 1) * 100)
            base = f"xylem-{self._shell}-x-human-sid-{self._sid}-{dt:%Y-%m-%d-%H.%M.%S}.{cs:02d}"
            if self._tz_offset:
                base += f"-{self._tz_offset}"
        else:
            us_since_xepoch = int((now - XEPOCH) * 1_000_000)
            base = f"xylem-{self._shell}-xepoch-sid-{self._sid}-{us_since_xepoch:016x}"
        return base + ".cast"

    def _cast_header(self):
        return json.dumps({
            "version": 2, "width": 120, "height": 30,
            "timestamp": int(time.time()),
        })

    def _open_out_chunk(self):
        if self._out_f:
            self._out_f.close()
        path = self._out_dir / self._chunk_name()
        self._out_f = open(path, 'ab')
        self._out_f.write((self._cast_header() + '\n').encode())
        self._out_f.flush()
        self._out_lines = 0
        self._out_chunks += 1

    def _open_in_chunk(self):
        if self._in_f:
            self._in_f.close()
        path = self._in_dir / self._chunk_name()
        self._in_f = open(path, 'ab')
        self._in_f.write((self._cast_header() + '\n').encode())
        self._in_f.flush()
        self._in_lines = 0
        self._in_chunks += 1

    def _finish_command(self):
        if self._cmd_f:
            self._cmd_f.close()
            self._cmd_f = None
            self._cmd_input = None

    def _start_command(self, input_line):
        self._finish_command()
        self._cmd_count += 1
        path = self._cmd_dir / self._chunk_name()
        self._cmd_f = open(path, 'ab')
        self._cmd_f.write((self._cast_header() + '\n').encode())
        self._cmd_input = input_line
        entry = json.dumps([0.0, "i", input_line])
        self._cmd_f.write((entry + '\n').encode())
        self._cmd_f.flush()

    def append(self, data: bytes, event_type="o"):
        elapsed = time.time() - self._start
        text = data.decode('utf-8', errors='replace')
        entry = json.dumps([round(elapsed, 6), event_type, text])

        if event_type == "o":
            self._out_f.write((entry + '\n').encode())
            self._out_f.flush()
            output_lines = text.count('\n') + (1 if text and not text.endswith('\n') else 0)
            self._out_lines += max(output_lines, 1)
            if self._out_lines >= self._chunk_lines:
                self._open_out_chunk()
            if self._cmd_f:
                cmd_entry = json.dumps([round(elapsed, 6), "o", text])
                self._cmd_f.write((cmd_entry + '\n').encode())
                self._cmd_f.flush()
            clean = ANSI_RE.sub('', text)
            if PROMPT_RE.search(clean):
                self._finish_command()
        else:
            self._in_f.write((entry + '\n').encode())
            self._in_f.flush()
            self._in_lines += 1
            if self._in_lines >= self._chunk_lines:
                self._open_in_chunk()
            if text.endswith('\r') or text.endswith('\n'):
                self._start_command(text.rstrip('\r\n'))

    def close(self):
        self._finish_command()
        for f in (self._out_f, self._in_f):
            if f:
                f.close()

    @property
    def session_dir(self):
        return self._dir

    @property
    def chunk_count(self):
        return self._out_chunks + self._in_chunks

    @staticmethod
    def _read_chunk_text(path, event_filter=None):
        result = []
        try:
            with open(path, 'rb') as f:
                for raw in f:
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list) and len(parsed) >= 3:
                            if event_filter is None or parsed[1] == event_filter:
                                result.append(parsed[2])
                    except (json.JSONDecodeError, ValueError):
                        pass
        except FileNotFoundError:
            pass
        return result

    @staticmethod
    def read_tail(session_dir, lines=200, stream='output'):
        session_dir = Path(session_dir) / stream
        if not session_dir.exists():
            return ''
        chunks = sorted(session_dir.glob("*.cast"), reverse=True)
        collected = []
        for chunk_path in chunks:
            texts = PTYLog._read_chunk_text(chunk_path)
            collected = texts + collected
            total_lines = sum(t.count('\n') for t in collected)
            if total_lines >= lines:
                break
        full = ''.join(collected)
        out_lines = full.split('\n')
        if len(out_lines) > lines:
            out_lines = out_lines[-lines:]
        return '\n'.join(out_lines)

    @staticmethod
    def list_chunks(session_dir, stream='output'):
        target = Path(session_dir) / stream
        if not target.exists():
            return []
        return sorted(target.glob("*.cast"))

    @staticmethod
    def read_chunk(session_dir, stream, name):
        path = Path(session_dir) / stream / name
        if not path.suffix:
            path = path.with_suffix('.cast')
        return ''.join(PTYLog._read_chunk_text(path))

    @staticmethod
    def list_commands(session_dir):
        cmd_dir = Path(session_dir) / "commands"
        if not cmd_dir.exists():
            return []
        return sorted(cmd_dir.glob("*.cast"))

    @staticmethod
    def read_command(session_dir, name):
        path = Path(session_dir) / "commands" / name
        if not path.suffix:
            path = path.with_suffix('.cast')
        entries = PTYLog._read_chunk_text(path)
        return ''.join(entries)


# ── Shared Shell (singleton) ───────────────────────────────────────

_active_shell = None
_shell_lock = threading.Lock()
_shell_broadcast = []
_shell_reader_task = None
_shell_loop = None
_pty_log = None
_session_id = None
_log_queue = None


class ShellSession:
    def __init__(self):
        import pty as pty_mod
        rc = str(Path(__file__).parent.parent / "scripts" / "xonshrc.py")
        self.pid, self.fd = pty_mod.fork()
        if self.pid == 0:
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            signal.signal(signal.SIGPIPE, signal.SIG_DFL)
            os.execvpe("xonsh", ["xonsh", "--rc", rc],
                       {**os.environ, "TERM": "xterm-256color", "XYLEM": "1"})
            os._exit(1)
        self._set_size(30, 120)
        self.clients = []

    def _set_size(self, rows, cols):
        buf = struct.pack("HHHH", rows, cols, 0, 0)
        try: fcntl.ioctl(self.fd, termios.TIOCSWINSZ, buf)
        except OSError: pass

    def read(self):
        try: return os.read(self.fd, 65536)
        except OSError: return b""

    def write(self, data):
        try: os.write(self.fd, data)
        except OSError: pass

    def resize(self, rows, cols):
        self._set_size(rows, cols)

    def close(self):
        os.close(self.fd)
        try: os.kill(self.pid, signal.SIGTERM)
        except: pass


def _get_or_create_shell():
    global _active_shell, _shell_reader_task, _shell_loop, _shell_broadcast
    global _pty_log, _session_id, _log_queue
    with _shell_lock:
        if _active_shell is None:
            _active_shell = ShellSession()
            _shell_broadcast = []
            _shell_loop = asyncio.get_event_loop()

            _session_id = f"{int(time.time())}-{os.getpid()}"
            _pty_log = PTYLog(SESSIONS_ROOT / _session_id, shell='xonsh')

            _log_queue = asyncio.Queue(maxsize=4096)  # noqa: assigned to global above

            async def log_writer():
                """Drain log queue in background — keeps logging off the broadcast path."""
                log = _pty_log
                while True:
                    item = await _log_queue.get()
                    if item is None:
                        break
                    data, event_type = item
                    await asyncio.get_event_loop().run_in_executor(
                        None, log.append, data, event_type)

            asyncio.create_task(log_writer())

            async def broadcast_reader():
                shell = _active_shell
                loop = _shell_loop
                while True:
                    data = await loop.run_in_executor(None, shell.read)
                    if not data:
                        for q in _shell_broadcast:
                            try:
                                q.put_nowait(None)
                            except asyncio.QueueFull:
                                pass
                        try:
                            _log_queue.put_nowait(None)
                        except asyncio.QueueFull:
                            pass
                        break
                    # Broadcast to clients first — never block on logging
                    for q in list(_shell_broadcast):
                        try:
                            q.put_nowait(data)
                        except asyncio.QueueFull:
                            try:
                                q.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            try:
                                q.put_nowait(data)
                            except asyncio.QueueFull:
                                pass
                    # Queue for async logging
                    try:
                        _log_queue.put_nowait((data, "o"))
                    except asyncio.QueueFull:
                        pass

            _shell_reader_task = asyncio.create_task(broadcast_reader())
        return _active_shell


# ── WebSocket ──────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_terminal(ws: WebSocket):
    await ws.accept()
    shell = _get_or_create_shell()

    # TODO: replay needs server-side ScreenBuffer to avoid ANSI state corruption
    # Raw replay disabled — causes visual glitches from stateful escape sequences

    queue = asyncio.Queue(maxsize=256)
    _shell_broadcast.append(queue)

    async def reader():
        try:
            while True:
                data = await queue.get()
                if data is None:
                    break
                await ws.send_bytes(data)
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            if queue in _shell_broadcast:
                _shell_broadcast.remove(queue)

    async def writer():
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.receive":
                    if "bytes" in msg:
                        if _log_queue:
                            try:
                                _log_queue.put_nowait((msg["bytes"], "i"))
                            except asyncio.QueueFull:
                                pass
                        shell.write(msg["bytes"])
                    elif "text" in msg:
                        try:
                            data = json.loads(msg["text"])
                            if data.get("type") == "resize":
                                shell.resize(data["rows"], data["cols"])
                        except json.JSONDecodeError:
                            pass
        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    await asyncio.gather(reader(), writer())


# ── REST API for agents ───────────────────────────────────────────

@app.get("/scrollback")
async def scrollback(lines: int = 100, stream: str = 'output'):
    """Return recent terminal text. stream: output, input, or commands."""
    if _session_id:
        text = PTYLog.read_tail(SESSIONS_ROOT / _session_id, lines=lines, stream=stream)
        return PlainTextResponse(text)
    return PlainTextResponse("")

@app.get("/chunks/{stream}")
async def list_chunks(stream: str = 'output'):
    """List chunk files for a stream (output/input/commands)."""
    if _pty_log and _session_id:
        chunks = PTYLog.list_chunks(SESSIONS_ROOT / _session_id, stream=stream)
        return {"session_id": _session_id, "stream": stream,
                "chunks": [c.name for c in chunks]}
    return {"session_id": None, "chunks": []}

@app.get("/chunk/{stream}/{name}")
async def read_chunk(stream: str, name: str):
    """Return a specific chunk's content."""
    if _session_id:
        text = PTYLog.read_chunk(SESSIONS_ROOT / _session_id, stream, name)
        return PlainTextResponse(text)
    return PlainTextResponse("")

@app.get("/commands")
async def list_commands():
    """List per-command log files."""
    if _session_id:
        cmds = PTYLog.list_commands(SESSIONS_ROOT / _session_id)
        return {"session_id": _session_id, "commands": [c.name for c in cmds]}
    return {"session_id": None, "commands": []}

@app.get("/command/{name}")
async def read_command(name: str):
    """Return a single command's input + output."""
    if _session_id:
        text = PTYLog.read_command(SESSIONS_ROOT / _session_id, name)
        return PlainTextResponse(text)
    return PlainTextResponse("")

@app.get("/size")
async def pty_size():
    """Return current PTY dimensions."""
    if _active_shell:
        buf = fcntl.ioctl(_active_shell.fd, termios.TIOCGWINSZ, b'\x00' * 8)
        rows, cols, xpix, ypix = struct.unpack('HHHH', buf)
        return {"rows": rows, "cols": cols}
    return {"rows": None, "cols": None}

@app.get("/session")
async def session_info():
    """Return current session metadata."""
    sid = _session_id
    return {
        "session_id": sid,
        "pid": _active_shell.pid if _active_shell else None,
        "log_dir": str(SESSIONS_ROOT / sid) if sid else None,
        "streams": ["output", "input", "commands"],
        "chunk_count": _pty_log.chunk_count if _pty_log else 0,
    }


# ── HTML page ──────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html>
<head>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/xterm/css/xterm.css" />
<style>
  body { margin:0; padding:8px; background:#0a0a0d; }
  #terminal { height:100vh; }
</style>
</head>
<body><div id="terminal"></div>
<script src="https://cdn.jsdelivr.net/npm/xterm/lib/xterm.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xterm-addon-fit/lib/xterm-addon-fit.js"></script>
<script>
const term = new Terminal({
  scrollback: 10000,
  cursorBlink: true,
  cursorStyle: 'block',
  fontSize: 14,
  fontFamily: "'JetBrainsMono Nerd Font Mono', 'Courier New', monospace",
  theme: { background: '#0a0a0d', foreground: '#d3d7cf',
           cursor: '#5588cc', cursorAccent: '#ffffff' }
});
const fit = new FitAddon.FitAddon();
term.loadAddon(fit);
term.open(document.getElementById('terminal'));
fit.fit();

const ws = new WebSocket(`ws://${location.host}/ws`);
ws.binaryType = 'arraybuffer';
ws.onopen = () => {
  term.focus();
  // Send initial size — fit.fit() before ws.open loses the resize
  ws.send(JSON.stringify({type:'resize', rows: term.rows, cols: term.cols}));
};
ws.onmessage = (e) => {
  if (e.data instanceof ArrayBuffer) {
    term.write(new Uint8Array(e.data));
  } else {
    term.write(e.data);
  }
};

term.onData(data => ws.send(new TextEncoder().encode(data)));
term.onResize(({rows, cols}) => {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({type:'resize', rows, cols}));
  }
});

window.addEventListener('resize', () => fit.fit());
</script></body></html>"""

@app.get("/")
async def root():
    return HTMLResponse(HTML)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8643)
