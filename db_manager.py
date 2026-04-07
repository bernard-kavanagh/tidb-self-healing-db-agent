"""
TiDB Connection Manager
-----------------------
Manages connections to both Production and Branch endpoints.
Provides EXPLAIN ANALYZE utilities for query performance analysis.
"""

import os
import ssl
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv

load_dotenv()


class TiDBConnectionManager:
    """Manages connections to one or more named TiDB clusters."""

    def __init__(self):
        self.ssl_ca = os.getenv('TIDB_SSL_CA', '/Users/bernardkavanagh/downloads/isrgrootx1.pem')
        self._clusters = self._load_clusters()
        self._active_cluster = list(self._clusters.keys())[0] if self._clusters else None

    def _load_clusters(self) -> dict:
        """
        Build a dict of cluster configs from env vars.

        Multi-cluster format (TIDB_CLUSTERS=prod-us,prod-eu):
            TIDB_PROD_US_HOST, TIDB_PROD_US_USER, TIDB_PROD_US_PASSWORD, ...
            TIDB_PROD_EU_HOST, TIDB_PROD_EU_USER, TIDB_PROD_EU_PASSWORD, ...

        Single-cluster fallback (backward-compatible):
            TIDB_HOST, TIDB_USER, TIDB_PASSWORD, ...  → stored as "default"
        """
        clusters = {}
        cluster_str = os.getenv("TIDB_CLUSTERS", "").strip()

        if cluster_str:
            for name in [n.strip() for n in cluster_str.split(",") if n.strip()]:
                env_key = name.upper().replace("-", "_")
                host = os.getenv(f"TIDB_{env_key}_HOST")
                if host:
                    clusters[name] = {
                        'host': host,
                        'port': int(os.getenv(f"TIDB_{env_key}_PORT", 4000)),
                        'user': os.getenv(f"TIDB_{env_key}_USER"),
                        'password': os.getenv(f"TIDB_{env_key}_PASSWORD"),
                        'database': os.getenv(f"TIDB_{env_key}_DATABASE", 'dba_agent_db'),
                        'ssl_ca': self.ssl_ca,
                        'autocommit': True,
                    }

        # Fallback: legacy single-cluster env vars → "default"
        if not clusters:
            clusters["default"] = {
                'host': os.getenv("TIDB_HOST"),
                'port': int(os.getenv("TIDB_PORT", 4000)),
                'user': os.getenv("TIDB_USER"),
                'password': os.getenv("TIDB_PASSWORD"),
                'database': os.getenv("TIDB_DATABASE", 'dba_agent_db'),
                'ssl_ca': self.ssl_ca,
                'autocommit': True,
            }

        return clusters

    @property
    def cluster_names(self) -> list:
        return list(self._clusters.keys())

    @property
    def active_cluster_name(self) -> str:
        return self._active_cluster or "default"

    @property
    def prod_config(self) -> dict:
        return self._clusters.get(self._active_cluster, {})

    def set_active_cluster(self, name: str):
        """Switch the active cluster. All subsequent tool calls target this cluster."""
        if name in self._clusters:
            self._active_cluster = name

    # ── Connection Factories ──────────────────────────────────────

    def get_prod_connection(self):
        """Returns a connection to the ACTIVE cluster."""
        config = self._clusters.get(self._active_cluster)
        if not config:
            raise ValueError(f"No cluster config found for '{self._active_cluster}'")
        return mysql.connector.connect(**config)

    def get_branch_connection(self, host: str, port: int, user: str, password: str, database: str = None):
        """Returns a connection to a BRANCH database."""
        config = {
            'host': host,
            'port': port,
            'user': user,
            'password': password,
            'database': database or self.prod_config['database'],
            'ssl_ca': self.ssl_ca,
            'autocommit': True,
        }
        return mysql.connector.connect(**config)

    # ── Query Utilities ───────────────────────────────────────────

    def execute(self, query: str, params=None, connection=None, fetch_all=True):
        """Execute a query on a given connection (defaults to production)."""
        conn = connection or self.get_prod_connection()
        own_conn = connection is None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(query, params or ())
            if fetch_all:
                return cursor.fetchall()
            return cursor.fetchone()
        except Error as e:
            return {"error": str(e)}
        finally:
            if own_conn and conn.is_connected():
                conn.close()

    def run_explain(self, query: str, connection=None):
        """
        Runs EXPLAIN ANALYZE on the given query.
        Returns structured output with execution time and plan details.
        """
        conn = connection or self.get_prod_connection()
        own_conn = connection is None
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(f"EXPLAIN ANALYZE {query}")
            rows = cursor.fetchall()

            # Parse the execution time from the first row
            plan_text = "\n".join(str(row) for row in rows)
            execution_time_ms = self._extract_execution_time(rows)

            return {
                "execution_time_ms": execution_time_ms,
                "plan": rows,
                "plan_text": plan_text,
                "uses_index": self._check_index_usage(rows),
            }
        except Error as e:
            return {"error": str(e), "execution_time_ms": -1}
        finally:
            if own_conn and conn.is_connected():
                conn.close()

    def test_connection(self):
        """Quick connectivity test."""
        try:
            conn = self.get_prod_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT VERSION()")
            version = cursor.fetchone()[0]
            conn.close()
            return f"✅ Connected to TiDB {version}"
        except Error as e:
            return f"❌ Connection failed: {e}"

    # ── Private Helpers ───────────────────────────────────────────

    @staticmethod
    def _extract_execution_time(explain_rows):
        """Extract execution time in ms from EXPLAIN ANALYZE output."""
        if not explain_rows:
            return -1
        # TiDB EXPLAIN ANALYZE includes 'time:XXms' or 'time:XXs' in the first row
        first_row = str(explain_rows[0])
        import re
        # Look for patterns like time:123.4ms or time:1.2s
        match = re.search(r'time[=:](\d+\.?\d*)(ms|s|µs)', first_row)
        if match:
            value = float(match.group(1))
            unit = match.group(2)
            if unit == 's':
                return value * 1000
            elif unit == 'µs':
                return value / 1000
            return value
        return -1

    @staticmethod
    def _check_index_usage(explain_rows):
        """Check if any row in the EXPLAIN plan uses an index scan."""
        plan_str = str(explain_rows).lower()
        return 'indexscan' in plan_str or 'indexlookup' in plan_str or 'indexreader' in plan_str


# Global instance
db_manager = TiDBConnectionManager()
