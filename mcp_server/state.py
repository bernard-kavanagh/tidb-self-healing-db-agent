"""
BranchStateManager — keeps TiDB branch credentials server-side so they
never leak into the agent's context window or conversation history.

Credentials are issued by TiDB Cloud at branch creation and cannot be
retrieved afterward. So this class is the only place those credentials
exist for the lifetime of the MCP server process. They are never written
to disk, never returned to the agent, and never logged.
"""
import os
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class BranchCreds:
    branch_id: str
    branch_name: str
    host: str
    port: int
    user: str
    password: str   # never leaves this module


class BranchStateManager:
    def __init__(self):
        self._creds: dict[str, BranchCreds] = {}
        self._lock = threading.Lock()

    def store(self, creds: BranchCreds) -> None:
        with self._lock:
            self._creds[creds.branch_name] = creds

    def get(self, branch_name: str) -> BranchCreds | None:
        with self._lock:
            return self._creds.get(branch_name)

    def evict(self, branch_name: str) -> bool:
        with self._lock:
            return self._creds.pop(branch_name, None) is not None

    def managed_names(self) -> set[str]:
        with self._lock:
            return set(self._creds.keys())

    @staticmethod
    def preserve_orphans() -> bool:
        return os.getenv("MCP_PRESERVE_ORPHAN_BRANCHES", "0") == "1"


state = BranchStateManager()
