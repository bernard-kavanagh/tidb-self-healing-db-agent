"""
Branch operation tools — apply DDL or run EXPLAIN against a managed branch.

Both tools take only the branch_name; credentials are looked up from the
server-side BranchStateManager and never appear in the tool's input or
output schema.
"""
from db_manager import db_manager

from ..state import state


def register(mcp):
    @mcp.tool()
    def apply_ddl_on_branch(branch_name: str, ddl: str) -> dict:
        """
        Apply a DDL statement on a managed branch. The branch must have been
        created in this server session via create_branch.
        """
        creds = state.get(branch_name)
        if creds is None:
            return {
                "success": False,
                "message": (
                    f"Branch '{branch_name}' is not managed by this server. "
                    "Either it was created in a previous session (credentials lost; "
                    "delete and recreate it via create_branch), or it doesn't exist. "
                    "Use list_branches to see what's available."
                ),
            }

        ddl_upper = ddl.strip().upper()
        for forbidden in ("DROP TABLE", "TRUNCATE", "DELETE FROM"):
            if forbidden in ddl_upper:
                return {"success": False, "message": f"🚫 '{forbidden}' blocked by safety policy."}

        try:
            conn = db_manager.get_branch_connection(
                host=creds.host, port=creds.port,
                user=creds.user, password=creds.password,
            )
            db_manager.execute(ddl, connection=conn, fetch_all=False)
            return {"success": True, "message": f"DDL applied on branch '{branch_name}'."}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @mcp.tool()
    def run_query_on_branch(branch_name: str, sql: str) -> dict:
        """
        Run EXPLAIN ANALYZE on a SELECT query against a managed branch.
        Used to measure query performance after applying a fix.
        """
        creds = state.get(branch_name)
        if creds is None:
            return {
                "error": (
                    f"Branch '{branch_name}' is not managed by this server. "
                    "Use create_branch first or list_branches to inspect."
                ),
            }

        try:
            conn = db_manager.get_branch_connection(
                host=creds.host, port=creds.port,
                user=creds.user, password=creds.password,
            )
            result = db_manager.run_explain(sql, connection=conn)
            if "error" in result:
                return {"error": result["error"]}
            return {
                "execution_time_ms": result["execution_time_ms"],
                "uses_index": result["uses_index"],
                "plan_text": result["plan_text"][:2000],
            }
        except Exception as e:
            return {"error": str(e)}
