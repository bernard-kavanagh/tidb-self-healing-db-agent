# dba-agent-mcp

## What this is

An MCP server that lets Claude Desktop / Cursor / any MCP client safely
diagnose and fix TiDB Cloud performance issues. Branch credentials are
held server-side and never appear in tool traces or conversation history.

## Security note

Database branch credentials never cross the MCP wire. They are issued by
TiDB Cloud at branch creation, stored only in this server's memory, and
used only to execute DDL on the branch. They are never returned to the
agent, never written to disk, and never logged. On server restart,
in-memory credentials are lost; orphan branches are auto-deleted unless
`MCP_PRESERVE_ORPHAN_BRANCHES=1` is set.

## Install

Tested against macOS with system Python 3.12 at `/usr/local/bin/python3`.
Linux and Windows paths will differ — adjust accordingly.

```bash
# From the dba_agent directory. Use `python3 -m pip` (not bare `pip`) to
# guarantee the install runs against the same interpreter the MCP server
# will run under.
cd /Users/bernardkavanagh/dba_agent
/usr/local/bin/python3 -m pip install -e ./mcp_server/
```

If you use a virtualenv, replace `/usr/local/bin/python3` everywhere
with the path to its `bin/python` (e.g. `.venv/bin/python`).

### Verify the install

Before configuring Claude Desktop, confirm the server runs cleanly:

```bash
cd /Users/..../dba_agent
/usr/local/bin/python3 -m mcp_server.server
```

Expected output:

```
[INFO] No branches to reconcile.
╭──── FastMCP 3.x ────╮
│  Server: dba-agent  │
╰─────────────────────╯
[INFO] Starting MCP server 'dba-agent' with transport 'stdio'
```

Then it sits silently, waiting on stdio. Press `Ctrl-C` to stop.

If you see anything else (ImportError, banner output before "No branches
to reconcile", etc.), see Troubleshooting below before continuing.

### Claude Desktop config snippet

Edit `~/Library/Application Support/Claude/claude_desktop_config.json`
and add this under `mcpServers` (alongside any existing entries):

```json
"dba-agent": {
  "command": "/usr/local/bin/python3",
  "args": ["-m", "mcp_server.server"],
  "cwd": "/Users/..../dba_agent"
}
```

Use `which python3` to confirm the path on your machine — `/usr/local/bin/python3`
is the macOS Homebrew default, but Linux distros and pyenv setups will differ.
The `command` must point at the **same interpreter** you ran `pip install` against.

Then `Cmd+Q` Claude Desktop and relaunch.

## First five minutes

After Claude Desktop restarts:

1. Type `/database_health_check` — the server's prompt template runs a
   read-only diagnostic pass and reports findings.
2. Ask: **"create a branch called fix-orders"**. The tool response
   contains `branch_name`, `branch_id`, `status`, `managed_by_server` —
   no host, port, user, or password.
3. Ask: **"apply `CREATE INDEX idx_test ON orders(status)` on the
   fix-orders branch"**. The agent refers to the branch by name only.
   No credentials appear anywhere in the tool trace.
4. Ask: **"delete the fix-orders branch"** to clean up.

## Tool reference

### Diagnostics (read-only)
- `explain_query(sql)` — EXPLAIN ANALYZE on production.
- `check_write_hotspots()` — scan for AUTO_INCREMENT PKs and monotonic indexes.
- `check_table_regions(table_name)` — TiKV region distribution for a table.
- `check_slow_queries(min_seconds, limit)` — read the slow query log.
- `show_databases()` — list schemas on the active cluster.
- `recall_memory(error_description)` — semantic search over past incidents.
- `save_memory(...)` — persist a verified fix to vector store + audit log.
- `run_health_check()` — fan-out: hotspots + slow queries + sample EXPLAIN.

### Branch lifecycle
- `create_branch(branch_name)` — spin up a branch; credentials kept server-side.
- `list_branches()` — split into `managed` (operable) vs `orphan` (no creds).
- `delete_branch_by_name(branch_name)` — delete and evict creds.

### Branch operations
- `apply_ddl_on_branch(branch_name, ddl)` — run DDL on a managed branch.
- `run_query_on_branch(branch_name, sql)` — EXPLAIN ANALYZE on a managed branch.

## Environment variables

The server loads `.env` from the parent `dba_agent/` directory. Required:

| Variable                  | Purpose                                      |
|---------------------------|----------------------------------------------|
| `TIDB_HOST`               | Production endpoint hostname                 |
| `TIDB_PORT`               | Production endpoint port (default 4000)      |
| `TIDB_USER`               | Production user                              |
| `TIDB_PASSWORD`           | Production password                          |
| `TIDB_DATABASE`           | Default database                             |
| `TIDB_SSL_CA`             | Path to ISRG Root X1 PEM                     |
| `TIDB_CLOUD_PUBLIC_KEY`   | TiDB Cloud API public key                    |
| `TIDB_CLOUD_PRIVATE_KEY`  | TiDB Cloud API private key                   |
| `TIDB_CLOUD_PROJECT_ID`   | TiDB Cloud project ID                        |
| `TIDB_CLOUD_CLUSTER_ID`   | TiDB Cloud cluster ID                        |

Optional:

| Variable                          | Purpose                                                |
|-----------------------------------|--------------------------------------------------------|
| `MCP_PRESERVE_ORPHAN_BRANCHES`    | Set to `1` to disable orphan-branch auto-cleanup on startup. |
| `TIDB_CLUSTERS`                   | Comma-separated cluster aliases for multi-cluster mode (see `db_manager.py`). |

## Troubleshooting

**`.venv/bin/python: no such file or directory`** when Claude Desktop
launches the server. The config points at a virtualenv that doesn't
exist. Run `which python3` to find your actual Python, install against
it (`<that-path> -m pip install -e ./mcp_server/`), and update the
`command` field in the config to match.

**`ModuleNotFoundError: No module named 'fastmcp'`** (or any other
dependency). The `pip install` ran against a different Python than the
one the config points at. To diagnose:

```bash
/usr/local/bin/python3 -c "import fastmcp; print(fastmcp.__file__)"
```

If that errors, install fastmcp against this interpreter:
`/usr/local/bin/python3 -m pip install fastmcp`. If it succeeds, your
config's `command` field is pointing at a different interpreter — fix it
to match the path that worked.

**Claude Desktop log: "JSON-RPC: Invalid JSON, expected value at line 1
column 1"** with a chat string in the error payload. Something in an
imported module is writing to stdout instead of stderr, polluting the
MCP wire. Check `dba_agent/branch_manager.py` and `dba_agent/db_manager.py`
for stray `print()` calls — `grep -n "print(" /Users/.../dba_agent/*.py`.
Forks that have added local `print()` calls will hit this; fix by
replacing with `logging.info()` (which goes to stderr by default) or by
wrapping the offending imports in `contextlib.redirect_stdout(sys.stderr)`
inside `mcp_server/server.py`.

**Server starts but no tools show up in Claude Desktop.** Either the
server crashed silently (check Claude Desktop's Developer → Open MCP Log)
or your config's `cwd` is wrong. The `cwd` must be `/Users/.../dba_agent`
(the parent directory) so `mcp_server.server` resolves as a module.

## Status

Tested against macOS with system Python 3.12 at `/usr/local/bin/python3`
and the `dba_agent` repo's existing dependencies. Linux and Windows
install paths will differ; PRs welcome to expand the install
instructions.
