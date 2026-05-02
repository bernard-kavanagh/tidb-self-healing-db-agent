"""
MCP prompts — reusable canned instructions exposed to the client.
"""

HEALTH_CHECK_PROMPT = """\
Perform a full autonomous database health check. Work through each step \
independently — do not wait for further instructions.

**Step 1 — Memory scan**
Search your episodic memory for any known past incidents with this database.

**Step 2 — Query diagnostics**
Run EXPLAIN ANALYZE on each of the following known hotspot queries and record \
the execution time and whether an index is used:

1. `SELECT * FROM orders WHERE status = 'pending' ORDER BY created_at DESC LIMIT 100`
2. `SELECT o.order_id, o.status, oi.product_id, oi.quantity FROM orders o \
JOIN order_items oi ON o.order_id = oi.order_id WHERE o.user_id = 42`
3. `SELECT user_id, event_type, COUNT(*) AS cnt FROM events \
WHERE user_id = 42 GROUP BY user_id, event_type`
4. `SELECT * FROM users WHERE country = 'IE' AND tier = 'enterprise' AND is_active = 1`
5. `SELECT product_id, SUM(quantity) AS total_sold FROM order_items \
GROUP BY product_id ORDER BY total_sold DESC LIMIT 20`

**Step 3 — Findings report**
Produce a prioritised report with severity (HIGH / MEDIUM / LOW), table \
affected, root cause, and recommended fix for each issue found.

This is a **read-only diagnostic pass** — do not create branches or apply \
fixes yet. Identify and report only.\
"""


def register(mcp):
    @mcp.prompt()
    def database_health_check() -> str:
        """Run a full read-only TiDB health check across known hotspot queries."""
        return HEALTH_CHECK_PROMPT
