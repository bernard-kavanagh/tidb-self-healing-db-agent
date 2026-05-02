"""
dba_agent_mcp — MCP server for TiDB Cloud database operations.

Exposes diagnostic, branch lifecycle, and branch operation tools to MCP
clients (Claude Desktop, Cursor, Claude Code). Branch credentials are
held server-side and never returned to the agent.
"""
import logging
import sys
from pathlib import Path
from dotenv import load_dotenv
from fastmcp import FastMCP

# Import the existing dba_agent modules without modifying them.
# Parent of this file is /Users/.../dba_agent/mcp_server; its parent is
# /Users/.../dba_agent which holds branch_manager.py, db_manager.py, memory.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from branch_manager import TiDBBranchManager  # noqa: E402

from .state import state, BranchStateManager  # noqa: E402
from .tools import register_all  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("dba-agent-mcp")

mcp = FastMCP("dba-agent")
_branch_manager = TiDBBranchManager()

register_all(mcp)


def reconcile_orphans():
    """
    On startup, list TiDB Cloud branches. Since the in-memory state dict
    is fresh and empty, every branch is an orphan. Delete them unless
    MCP_PRESERVE_ORPHAN_BRANCHES=1 is set.
    """
    if BranchStateManager.preserve_orphans():
        log.info("MCP_PRESERVE_ORPHAN_BRANCHES=1 — skipping orphan cleanup.")
        return

    try:
        branches = _branch_manager.list_branches() or []
    except Exception as e:
        log.warning(f"Could not list branches for orphan cleanup: {e}")
        return

    if not branches:
        log.info("No branches to reconcile.")
        return

    for b in branches:
        name = b.get("name")
        if not name:
            continue
        log.warning(f"Deleting orphan branch '{name}' (no server-side credentials).")
        try:
            _branch_manager.delete_branch_by_name(name)
        except Exception as e:
            log.error(f"Failed to delete orphan '{name}': {e}")


if __name__ == "__main__":
    reconcile_orphans()
    mcp.run()
