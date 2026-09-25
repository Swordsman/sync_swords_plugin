#!/usr/bin/env python3
"""
Transparent FUSE I/O watcher.
Mounts over a target directory, logs all filesystem operations with PID/UID/GID,
and passes through all operations unchanged.
"""

import argparse
import datetime
import errno
import os
import signal
import sys
import threading

import fuse
from fuse import FUSE, FuseOSError, Operations, fuse_get_context

fuse.fuse_python_api = (0, 2)


class LoggingFS(Operations):
    VIRTUAL_FH = 0  # sentinel for handles that don't need os.close()

    def __init__(self, root_fd, log_file):
        self.root_fd = root_fd
        self.log_file = log_file
        self.log_lock = threading.Lock()
        self._log_fd = None
        self._ensure_log_dir()
        self._open_log()

    def _ensure_log_dir(self):
        log_dir = os.path.dirname(self.log_file)
        if log_dir:
            try:
                os.makedirs(log_dir, exist_ok=True)
            except OSError:
                pass

    def _open_log(self):
        """Open the log file once and keep the fd. Avoids re-entering FUSE on every write."""
        try:
            self._log_fd = os.open(
                self.log_file,
                os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                0o644,
            )
        except OSError:
            # Fallback to stderr (which may be /dev/null after daemonization)
            self._log_fd = sys.stderr.fileno()

    def _log(self, op, path, **kwargs):
        ctx = fuse_get_context()
        pid, uid, gid = ctx
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        details = " ".join(f"{k}={v}" for k, v in kwargs.items())
        line = f"{ts} | PID={pid} UID={uid} | OP={op} | PATH={path}"
        if details:
            line += f" | {details}"
        line += "\n"
        with self.log_lock:
            try:
                os.write(self._log_fd, line.encode("utf-8"))
            except OSError:
                pass

    # --- Required operations ---

    def init(self, path):
        self._log("init", path)

    def destroy(self, path):
        self._log("destroy", path)
        try:
            os.close(self.root_fd)
        except OSError:
            pass
        if self._log_fd is not None and self._log_fd != sys.stderr.fileno():
            try:
                os.close(self._log_fd)
            except OSError:
                pass

    def _full_path(self, partial):
        """Convert a FUSE path to a real path via /proc/self/fd to avoid loops."""
        if partial.startswith("/"):
            partial = partial[1:]
        return os.path.join(f"/proc/self/fd/{self.root_fd}", partial)

    def getattr(self, path, fh=None):
        self._log("getattr", path, fh=fh)
        try:
            if fh is not None:
                st = os.fstat(fh)
            else:
                st = os.lstat(self._full_path(path))
        except OSError as exc:
            raise FuseOSError(exc.errno)
        return {k: getattr(st, k) for k in dir(st) if k.startswith("st_")}

    def readdir(self, path, fh):
        self._log("readdir", path)
        try:
            entries = os.listdir(self._full_path(path))
        except OSError as exc:
            raise FuseOSError(exc.errno)
        return [".", ".."] + entries

    def open(self, path, flags):
        self._log("open", path, flags=hex(flags))
        try:
            fd = os.open(self._full_path(path), flags)
            # Avoid fd 0 so release() can distinguish virtual handles from real ones.
            if fd == self.VIRTUAL_FH:
                fd2 = os.dup(fd)
                os.close(fd)
                fd = fd2
            return fd
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def create(self, path, mode, fi=None):
        self._log("create", path, mode=oct(mode))
        try:
            fd = os.open(
                self._full_path(path),
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                mode,
            )
            if fd == self.VIRTUAL_FH:
                fd2 = os.dup(fd)
                os.close(fd)
                fd = fd2
            return fd
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def read(self, path, length, offset, fh):
        self._log("read", path, length=length, offset=offset)
        try:
            os.lseek(fh, offset, os.SEEK_SET)
            return os.read(fh, length)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def write(self, path, data, offset, fh):
        self._log("write", path, length=len(data), offset=offset)
        try:
            os.lseek(fh, offset, os.SEEK_SET)
            return os.write(fh, data)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def release(self, path, fh):
        self._log("release", path)
        if fh != self.VIRTUAL_FH:
            try:
                return os.close(fh)
            except OSError as exc:
                raise FuseOSError(exc.errno)
        return 0

    def flush(self, path, fh):
        self._log("flush", path)
        return 0

    def fsync(self, path, datasync, fh):
        self._log("fsync", path, datasync=datasync)
        try:
            return os.fsync(fh)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def readlink(self, path):
        self._log("readlink", path)
        try:
            return os.readlink(self._full_path(path))
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def access(self, path, mode):
        self._log("access", path, mode=oct(mode))
        try:
            if not os.access(self._full_path(path), mode):
                raise FuseOSError(errno.EACCES)
        except OSError as exc:
            if exc.errno != errno.EACCES:
                raise FuseOSError(exc.errno)
            raise
        return 0

    def unlink(self, path):
        self._log("unlink", path)
        try:
            return os.unlink(self._full_path(path))
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def mkdir(self, path, mode):
        self._log("mkdir", path, mode=oct(mode))
        try:
            return os.mkdir(self._full_path(path), mode)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def rmdir(self, path):
        self._log("rmdir", path)
        try:
            return os.rmdir(self._full_path(path))
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def rename(self, old, new):
        self._log("rename", old, new=new)
        try:
            return os.rename(self._full_path(old), self._full_path(new))
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def chmod(self, path, mode):
        self._log("chmod", path, mode=oct(mode))
        try:
            return os.chmod(self._full_path(path), mode)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def chown(self, path, uid, gid):
        self._log("chown", path, uid=uid, gid=gid)
        try:
            return os.chown(self._full_path(path), uid, gid)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def truncate(self, path, length, fh=None):
        self._log("truncate", path, length=length)
        try:
            if fh is not None:
                return os.ftruncate(fh, length)
            return os.truncate(self._full_path(path), length)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def utimens(self, path, times=None):
        self._log("utimens", path, times=times)
        try:
            return os.utime(self._full_path(path), times=times)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def statfs(self, path):
        self._log("statfs", path)
        try:
            stv = os.statvfs(self._full_path(path))
        except OSError as exc:
            raise FuseOSError(exc.errno)
        return {
            key: getattr(stv, key)
            for key in (
                "f_bavail", "f_bfree", "f_blocks", "f_bsize",
                "f_favail", "f_ffree", "f_files", "f_flag",
                "f_frsize", "f_namemax",
            )
        }

    def symlink(self, target, source):
        self._log("symlink", source, target=target)
        try:
            return os.symlink(target, self._full_path(source))
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def link(self, target, source):
        """
        FUSE link(target, source): create a hard link at `source` pointing to `target`.
        os.link(src, dst): create a hard link from existing `src` to new `dst`.
        """
        self._log("link", source, target=target)
        try:
            return os.link(self._full_path(target), self._full_path(source))
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def mknod(self, path, mode, dev):
        self._log("mknod", path, mode=oct(mode), dev=dev)
        try:
            return os.mknod(self._full_path(path), mode, dev)
        except OSError as exc:
            raise FuseOSError(exc.errno)

    def fsyncdir(self, path, datasync, fh):
        self._log("fsyncdir", path, datasync=datasync)
        return 0


def daemonize(pid_file):
    """Double-fork daemonize. Parent writes PID file and exits on readiness."""
    pid_dir = os.path.dirname(pid_file)
    if pid_dir:
        os.makedirs(pid_dir, exist_ok=True)

    r, w = os.pipe()
    pid = os.fork()
    if pid < 0:
        os.close(r)
        os.close(w)
        sys.exit(1)
    if pid > 0:
        # Parent: wait for grandchild readiness
        os.close(w)
        with os.fdopen(r, "r") as f:
            msg = f.read().strip()
        if msg.startswith("READY "):
            grandchild_pid = int(msg.split()[1])
            with open(pid_file, "w") as f:
                f.write(str(grandchild_pid))
            sys.exit(0)
        else:
            sys.exit(1)

    # First child
    os.close(r)
    os.setsid()
    pid = os.fork()
    if pid < 0:
        os._exit(1)
    if pid > 0:
        os._exit(0)

    # Grandchild (daemon)
    os.chdir("/")
    os.umask(0o022)

    # Redirect stdio to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, sys.stdin.fileno())
    os.dup2(devnull, sys.stdout.fileno())
    os.dup2(devnull, sys.stderr.fileno())
    if devnull > 2:
        os.close(devnull)

    # Ignore SIGINT so terminal Ctrl+C doesn't kill the daemon
    signal.signal(signal.SIGINT, signal.SIG_IGN)

    # Signal readiness to parent with PID
    with os.fdopen(w, "w") as f:
        f.write(f"READY {os.getpid()}\n")


def main():
    parser = argparse.ArgumentParser(description="Transparent FUSE I/O watcher")
    parser.add_argument("--target", default="/home/joe/kimi-home", help="Directory to proxy")
    parser.add_argument("--mountpoint", default=None, help="Mount point (default: same as target)")
    parser.add_argument("--log-file", default="/tmp/fuse_watcher.log", help="Log file path")
    parser.add_argument("--pid-file", default="/tmp/fuse_watcher.pid", help="PID file path")
    parser.add_argument("--daemon", action="store_true", help="Run as a background daemon")
    args = parser.parse_args()

    target = args.target
    mountpoint = args.mountpoint or target

    # Guard against logging recursion: refuse to start if log file is inside mountpoint
    log_file_real = os.path.realpath(args.log_file)
    mountpoint_real = os.path.realpath(mountpoint)
    try:
        if os.path.commonpath([log_file_real, mountpoint_real]) == mountpoint_real:
            print(
                f"ERROR: Log file {args.log_file} is inside mountpoint {mountpoint}. "
                "This would cause infinite recursion.",
                file=sys.stderr,
            )
            sys.exit(1)
    except ValueError:
        # Different drives (shouldn't happen on Linux, but safe to ignore)
        pass

    # Open target directory BEFORE mounting to get a fd to the real filesystem
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        root_fd = os.open(target, flags)
    except OSError as exc:
        print(f"Failed to open target directory {target}: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.daemon:
        daemonize(args.pid_file)

    fs = LoggingFS(root_fd, args.log_file)
    try:
        FUSE(
            fs,
            mountpoint,
            foreground=True,
            allow_other=False,
            nothreads=False,
            nonempty=True,
            fsname="fuse_watcher",
        )
    except RuntimeError as exc:
        # Log the error using the already-opened fd
        try:
            if fs._log_fd is not None:
                line = (
                    f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
                    f"| FUSE ERROR: {exc}\n"
                )
                os.write(fs._log_fd, line.encode("utf-8"))
        except OSError:
            pass
        sys.exit(1)
    finally:
        try:
            os.close(root_fd)
        except OSError:
            pass


if __name__ == "__main__":
    main()
