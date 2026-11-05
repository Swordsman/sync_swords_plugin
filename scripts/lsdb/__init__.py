"""lsdb: read and write claude.ai artifact databases directly from code.

Calls the endpoint behind Claude Code's ArtifactData tool:
    POST <origin>/v1/code/sessions/<SID>/agent-proxy/frame/db/agent  {slug, verb, args}
UNDOCUMENTED and internal: it can change or break without notice. Works only inside a
claude.ai/code session (CLAUDE_CODE_REMOTE_SDK_URL + CLAUDE_SESSION_INGRESS_TOKEN_FILE).

Library: sys.path.insert(0, <plugin>/scripts); import lsdb; lsdb.get(url, "notes/n1")
CLI:     python3 <plugin>/scripts/lsdb --help
Standard library only. Adapted from the live-skills bundle's lsdb.py.
"""

from .catalog import register
from .ids import artifact_uuid
from .reads import MAX_LIMIT, get, list_all, list_docs, query
from .transport import LsdbApiError, LsdbEnvError, LsdbError, call, session
from .writes import MAX_BATCH_OPS, batch, delete_doc, set_doc, str_replace, update_doc, write_op

__all__ = [
    "artifact_uuid", "register", "call", "session", "get", "list_docs", "list_all", "query",
    "set_doc", "update_doc", "delete_doc", "str_replace", "batch", "write_op",
    "LsdbError", "LsdbEnvError", "LsdbApiError", "MAX_LIMIT", "MAX_BATCH_OPS",
]
