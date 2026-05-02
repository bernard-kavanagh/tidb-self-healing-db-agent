"""
Read-only diagnostic tools.

Stateless wrappers that call db_manager and dba_memory directly. Each
tool returns a native dict — FastMCP serialises automatically.
"""
from db_manager import db_manager
from memory import dba_memory


_SYSTEM_SCHEMAS = "('information_schema','mysql','performance_schema','sys','metrics_schema')"
_MONO_COLUMNS = "('created_at','updated_at','timestamp','create_time','update_time','event_time','inserted_at','created_date')"


# ── Internal helpers (also reused by run_health_check) ──────────────────────

def _explain_query(sql: str) -> dict:
    result = db_manager.run_explain(sql)
    if "error" in result:
        return {"error": result["error"]}
    return {
        "execution_time_ms": result["execution_time_ms"],
        "uses_index": result["uses_index"],
        "plan_text": result["plan_text"][:2000],
    }


def _check_write_hotspots() -> dict:
    ai_pks = db_manager.execute(
        f"SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
        f"FROM INFORMATION_SCHEMA.COLUMNS "
        f"WHERE EXTRA LIKE '%auto_increment%' AND COLUMN_KEY = 'PRI' "
        f"AND TABLE_SCHEMA NOT IN {_SYSTEM_SCHEMAS} "
        f"ORDER BY TABLE_SCHEMA, TABLE_NAME"
    )
    mono_indexes = db_manager.execute(
        f"SELECT TABLE_SCHEMA, TABLE_NAME, INDEX_NAME, COLUMN_NAME "
        f"FROM INFORMATION_SCHEMA.STATISTICS "
        f"WHERE COLUMN_NAME IN {_MONO_COLUMNS} "
        f"AND TABLE_SCHEMA NOT IN {_SYSTEM_SCHEMAS} AND SEQ_IN_INDEX = 1 "
        f"ORDER BY TABLE_SCHEMA, TABLE_NAME, INDEX_NAME"
    )

    if isinstance(ai_pks, dict) and "error" in ai_pks:
        return {"error": f"AUTO_INCREMENT check failed: {ai_pks['error']}"}
    if isinstance(mono_indexes, dict) and "error" in mono_indexes:
        return {"error": f"Monotonic index check failed: {mono_indexes['error']}"}

    ai_pks = ai_pks or []
    mono_indexes = mono_indexes or []
    severity = "HIGH" if ai_pks else ("MEDIUM" if mono_indexes else "LOW")

    return {
        "severity": severity,
        "auto_increment_pks": ai_pks,
        "monotonic_indexes": mono_indexes,
        "summary": (
            f"Found {len(ai_pks)} table(s) with AUTO_INCREMENT PK (HIGH — write hotspot). "
            f"Found {len(mono_indexes)} monotonically increasing indexed column(s) (MEDIUM — index hotspot)."
        ),
        "fix": "Replace AUTO_INCREMENT with AUTO_RANDOM to distribute writes evenly across TiKV regions.",
    }


def _check_table_regions(table_name: str) -> dict:
    safe_name = "".join(c for c in table_name if c.isalnum() or c in ("_", "-"))
    if safe_name != table_name:
        return {"error": f"Invalid table name: '{table_name}'"}

    rows = db_manager.execute(f"SHOW TABLE `{safe_name}` REGIONS")
    if isinstance(rows, dict) and "error" in rows:
        return {"error": rows["error"]}
    if not rows:
        return {"error": f"No region data returned for table '{table_name}'"}

    total_written = sum(r.get("WRITTEN_BYTES", 0) for r in rows)
    max_written = max((r.get("WRITTEN_BYTES", 0) for r in rows), default=0)
    hotspot_detected = (
        len(rows) > 1 and total_written > 0 and (max_written / total_written) > 0.8
    )

    regions = [
        {
            "region_id": r.get("REGION_ID"),
            "leader_store_id": r.get("LEADER_STORE_ID"),
            "written_bytes": r.get("WRITTEN_BYTES", 0),
            "read_bytes": r.get("READ_BYTES", 0),
            "approximate_size_mb": r.get("APPROXIMATE_SIZE(MB)", r.get("APPROXIMATE_SIZE", 0)),
            "approximate_keys": r.get("APPROXIMATE_KEYS", 0),
        }
        for r in rows
    ]

    return {
        "table": table_name,
        "region_count": len(rows),
        "hotspot_detected": hotspot_detected,
        "total_written_bytes": total_written,
        "regions": regions[:30],
        "summary": (
            f"Table '{table_name}' has {len(rows)} region(s). "
            + ("⚠️ Hotspot detected — one region holds >80% of total writes."
               if hotspot_detected
               else "✅ Write distribution looks even across regions.")
        ),
    }


def _check_slow_queries(min_seconds: float = 1.0, limit: int = 10) -> dict:
    rows = db_manager.execute(
        f"SELECT Query_time, DB, LEFT(Query, 300) AS Query, Rows_examined, "
        f"Index_names, User, Start_time FROM INFORMATION_SCHEMA.SLOW_QUERY "
        f"WHERE Query_time >= {float(min_seconds)} AND Is_internal = 0 "
        f"ORDER BY Query_time DESC LIMIT {int(limit)}"
    )
    if isinstance(rows, dict) and "error" in rows:
        return {"error": rows["error"]}
    if not rows:
        return {
            "message": f"No slow queries found exceeding {min_seconds}s.",
            "slow_queries": [],
        }
    return {
        "count": len(rows),
        "threshold_seconds": min_seconds,
        "slow_queries": [
            {
                "query_time_s": float(r.get("Query_time", 0)),
                "db": r.get("DB", ""),
                "query": r.get("Query", ""),
                "rows_examined": r.get("Rows_examined", 0),
                "index_names": r.get("Index_names", ""),
                "user": r.get("User", ""),
                "start_time": str(r.get("Start_time", "")),
            }
            for r in rows
        ],
    }


def _show_databases() -> dict:
    rows = db_manager.execute("SHOW DATABASES")
    if isinstance(rows, dict) and "error" in rows:
        return {"error": rows["error"]}
    return {"databases": [list(row.values())[0] for row in rows]}


# ── Tool registration ──────────────────────────────────────────────────────

def register(mcp):
    @mcp.tool()
    def explain_query(sql: str) -> dict:
        """Run EXPLAIN ANALYZE on the given SQL against PRODUCTION (read-only)."""
        return _explain_query(sql)

    @mcp.tool()
    def check_write_hotspots() -> dict:
        """Scan tables for AUTO_INCREMENT PKs and monotonically increasing indexes."""
        return _check_write_hotspots()

    @mcp.tool()
    def check_table_regions(table_name: str) -> dict:
        """Inspect TiKV region distribution for a table; flag >80% concentration."""
        return _check_table_regions(table_name)

    @mcp.tool()
    def check_slow_queries(min_seconds: float = 1.0, limit: int = 10) -> dict:
        """Return recent queries from the slow query log exceeding min_seconds."""
        return _check_slow_queries(min_seconds, limit)

    @mcp.tool()
    def show_databases() -> dict:
        """List all databases (schemas) on the active production cluster."""
        return _show_databases()

    @mcp.tool()
    def recall_memory(error_description: str) -> dict:
        """Semantic search over past incidents. Always call first during triage."""
        results = dba_memory.recall(error_description)
        if not results:
            return {"message": "No similar past incidents found. Proceed with fresh analysis.",
                    "results": []}
        return {"count": len(results), "results": results}

    @mcp.tool()
    def save_memory(
        incident_summary: str,
        resolution_sql: str,
        resolution_type: str,
        resolution_description: str,
        before_time_ms: int,
        after_time_ms: int,
        table_affected: str,
        success_rating: float,
        branch_name: str = "",
    ) -> dict:
        """Persist a verified fix to the episodic vector store and incident_log."""
        ok = dba_memory.save(
            incident_summary=incident_summary,
            resolution_sql=resolution_sql,
            resolution_type=resolution_type,
            resolution_description=resolution_description,
            success_rating=success_rating,
            before_time_ms=before_time_ms,
            after_time_ms=after_time_ms,
            table_affected=table_affected,
            branch_name=branch_name,
        )
        return {"success": ok, "message": "Memory saved." if ok else "Failed to save memory."}

    @mcp.tool()
    def run_health_check() -> dict:
        """
        Fan-out diagnostic: write-hotspot scan, slow-query scan, and an
        EXPLAIN ANALYZE on the slowest representative query. Each sub-call's
        failure is captured locally so partial failure doesn't lose the rest.
        """
        out: dict = {"hotspots": None, "slow_queries": None, "sample_explain": None}

        try:
            out["hotspots"] = _check_write_hotspots()
        except Exception as e:
            out["hotspots"] = {"error": str(e)}

        slow = None
        try:
            slow = _check_slow_queries(min_seconds=1.0, limit=10)
            out["slow_queries"] = slow
        except Exception as e:
            out["slow_queries"] = {"error": str(e)}

        sample_sql = None
        if isinstance(slow, dict):
            queries = slow.get("slow_queries") or []
            if queries:
                sample_sql = queries[0].get("query")

        if sample_sql:
            try:
                out["sample_explain"] = {"query": sample_sql, **_explain_query(sample_sql)}
            except Exception as e:
                out["sample_explain"] = {"error": str(e), "query": sample_sql}
        else:
            out["sample_explain"] = {"message": "No slow query available to EXPLAIN."}

        return out
