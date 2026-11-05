"""Session env, HTTP transport with retry, and call(): the one request every verb goes through.

The token is read fresh per call, never printed or logged, and redirects are refused so it is
never replayed to another URL.
"""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .ids import artifact_uuid

SDK_URL_ENV = "CLAUDE_CODE_REMOTE_SDK_URL"
TOKEN_FILE_ENV = "CLAUDE_SESSION_INGRESS_TOKEN_FILE"
DB_ROUTE = "/agent-proxy/frame/db/agent"
TIMEOUT_S = 30
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})  # None (no reply) is retried too
RETRY_DELAYS_S = (1, 2)  # three attempts in all
_SID_RE = re.compile(r"^/v1/code/sessions/([A-Za-z0-9_-]+)")


class LsdbError(Exception):
    """Base class for lsdb errors."""


class LsdbEnvError(LsdbError):
    """Not inside a claude.ai/code session: session env missing, malformed or unreadable."""


class LsdbApiError(LsdbError):
    """The endpoint answered non-2xx (status) or not at all (status None); body is the reply."""

    def __init__(self, status, body):
        super().__init__(f"HTTP {status}: {body}")
        self.status = status
        self.body = body

    @property
    def transient(self) -> bool:
        return self.status is None or self.status in RETRY_STATUSES


def session():
    """(sid, token) for the current claude.ai/code session; raises LsdbEnvError."""
    return _session_id(os.environ.get(SDK_URL_ENV, "")), _read_token(os.environ.get(TOKEN_FILE_ENV, ""))


def _session_id(sdk_url: str) -> str:
    match = _SID_RE.match(urllib.parse.urlsplit(sdk_url).path) if sdk_url else None
    if not match:
        raise LsdbEnvError(f"{SDK_URL_ENV} is unset or has no /v1/code/sessions/<id> path")
    return match.group(1)


def _read_token(token_file: str) -> str:
    if not token_file:
        raise LsdbEnvError(f"{TOKEN_FILE_ENV} is unset")
    try:
        with open(token_file, encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError as exc:
        raise LsdbEnvError(f"cannot read the session token file: {exc.strerror}") from None
    if not token:
        raise LsdbEnvError("the session token file is empty")
    return token


def endpoint(sid: str) -> str:
    """The db endpoint for session `sid` on the origin of CLAUDE_CODE_REMOTE_SDK_URL."""
    parts = urllib.parse.urlsplit(os.environ.get(SDK_URL_ENV, ""))
    if parts.scheme != "https" or not parts.netloc:
        raise LsdbEnvError(f"{SDK_URL_ENV} is not an https URL")
    return f"https://{parts.netloc}/v1/code/sessions/{sid}{DB_ROUTE}"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _post_once(url: str, body: bytes, token: str):
    """One POST; returns (status, raw bytes) or raises LsdbApiError."""
    request = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=TIMEOUT_S) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as exc:
        raise LsdbApiError(exc.code, _parse_body(exc.read())) from None
    except OSError as exc:  # URLError, timeouts, TLS and connection failures
        raise LsdbApiError(None, f"no HTTP reply: {getattr(exc, 'reason', exc)}") from None


def post(url: str, body: bytes, token: str, sleep=time.sleep):
    """POST, retrying transient failures (no reply, 429, 5xx) after each delay in RETRY_DELAYS_S."""
    for delay in (*RETRY_DELAYS_S, None):
        try:
            return _post_once(url, body, token)
        except LsdbApiError as exc:
            if delay is None or not exc.transient:
                raise
            sleep(delay)


def _parse_body(raw: bytes):
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except ValueError:
        return text


def call(url_or_id, verb: str, args: dict) -> dict:
    """POST one db verb for the artifact; return the decoded JSON reply.

    Raises ValueError (bad artifact id), LsdbEnvError (no session), LsdbApiError (non-2xx or no reply).
    """
    slug = artifact_uuid(url_or_id)
    sid, token = session()
    body = json.dumps({"slug": slug, "verb": verb, "args": args}).encode("utf-8")
    status, raw = post(endpoint(sid), body, token)
    reply = _parse_body(raw)
    if not 200 <= status < 300 or not isinstance(reply, dict):
        raise LsdbApiError(status, reply)
    return reply
