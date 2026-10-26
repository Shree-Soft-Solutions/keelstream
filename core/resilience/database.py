"""
Resilient database session and connection drop recovery for KeelStream.
Protects against transient network partitions, socket resets, and database failovers.
"""

from typing import Any, Callable, Dict, List, Optional
import time


class DatabaseConnectionError(Exception):
    """Raised when the database connection drops or is unreachable."""
    pass


class ResilientDatabaseSession:
    """
    Manages database transactions with automatic reconnect and idempotent query retry.
    """

    def __init__(self, connection_url: str = "postgresql://keelstream:keelstream_secret@localhost:5432/db_keelstream_core"):
        self.connection_url = connection_url
        self.is_connected = True
        self.in_transaction = False
        self.transaction_log: List[str] = []
        self.reconnect_count = 0
        self.queries_executed = 0

    def simulate_disconnect(self) -> None:
        """Simulates an abrupt network partition or DB server restart."""
        self.is_connected = False

    def reconnect(self) -> bool:
        """Restores database connectivity."""
        self.is_connected = True
        self.reconnect_count += 1
        return True

    def begin(self) -> None:
        """Starts a database transaction."""
        if not self.is_connected:
            raise DatabaseConnectionError("Cannot begin transaction: database disconnected.")
        self.in_transaction = True
        self.transaction_log = []

    def commit(self) -> None:
        """Commits the active transaction."""
        if not self.is_connected:
            self.rollback()
            raise DatabaseConnectionError("Commit failed: database disconnected during commit phase.")
        self.in_transaction = False
        self.transaction_log = []

    def rollback(self) -> None:
        """Rolls back the active transaction."""
        self.in_transaction = False
        self.transaction_log = []

    def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None,
        is_idempotent: bool = True,
        max_reconnect_attempts: int = 2,
    ) -> Dict[str, Any]:
        """
        Executes a database query with transient failure recovery.
        Only retries automatically if the operation is explicitly flagged as idempotent.
        """
        attempts = 0

        while True:
            attempts += 1
            if not self.is_connected:
                if attempts <= max_reconnect_attempts and is_idempotent:
                    # Roll back dirty state if any and attempt reconnect
                    self.rollback()
                    self.reconnect()
                else:
                    self.rollback()
                    raise DatabaseConnectionError(
                        f"Database execution failed on query '{query[:30]}...'. Connection lost."
                    )

            try:
                # Execute query logic simulation
                self.queries_executed += 1
                if self.in_transaction:
                    self.transaction_log.append(query)
                return {"status": "SUCCESS", "query": query, "rows_affected": 1}
            except Exception as exc:
                self.rollback()
                raise
