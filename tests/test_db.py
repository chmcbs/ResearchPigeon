"""
Tests for database utilities
"""

from unittest.mock import MagicMock

from core.db import connection_scope


def test_connection_scope_yields_provided_connection():
    conn = MagicMock()
    with connection_scope(conn) as active_conn:
        assert active_conn is conn
