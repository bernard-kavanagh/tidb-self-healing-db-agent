"""
Branch lifecycle tools.

Credentials returned by TiDB Cloud at branch creation are stored
server-side in the BranchStateManager and never returned to the agent.
"""
from ..state import state, BranchCreds


def register(mcp):
    # Lazy import: server.py instantiates _branch_manager after sys.path
    # is fixed; importing here at register-time avoids circular load.
    from ..server import _branch_manager

    @mcp.tool()
    def create_branch(branch_name: str) -> dict:
        """
        Create a TiDB Cloud branch. Credentials are stored server-side and
        never returned to the agent. Use the returned branch_name to
        reference this branch in subsequent apply_ddl_on_branch and
        run_query_on_branch calls.
        """
        info = _branch_manager.create_branch(branch_name)
        creds = BranchCreds(
            branch_id=info["branch_id"],
            branch_name=info["branch_name"],
            host=info["host"],
            port=info["port"],
            user=info["user"],
            password=info["password"],
        )
        state.store(creds)
        return {
            "branch_id": creds.branch_id,
            "branch_name": creds.branch_name,
            "status": info.get("status", "ACTIVE"),
            "managed_by_server": True,
        }

    @mcp.tool()
    def list_branches() -> dict:
        """
        List all TiDB Cloud branches, distinguishing those the server
        can operate on (managed) from those it cannot (orphan).
        """
        api_branches = _branch_manager.list_branches() or []
        managed_names = state.managed_names()
        return {
            "managed": [b for b in api_branches if b.get("name") in managed_names],
            "orphan":  [b for b in api_branches if b.get("name") not in managed_names],
        }

    @mcp.tool()
    def delete_branch_by_name(branch_name: str) -> dict:
        """
        Delete a TiDB Cloud branch by name. Works for both managed and
        orphan branches. Server-side credentials are evicted on success.
        """
        result = _branch_manager.delete_branch_by_name(branch_name)
        if result.get("success"):
            state.evict(branch_name)
        return result
