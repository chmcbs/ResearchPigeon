"""
Database connection utilities
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv

load_dotenv()


def get_database_url() -> str:
    return os.environ["DATABASE_URL"]


@contextmanager
def connection_scope(conn=None) -> Iterator[psycopg.Connection]:
    if conn is not None:
        yield conn
        return

    with psycopg.connect(get_database_url()) as owned_conn:
        yield owned_conn


def check_database_connection(*, connect_timeout: int = 5) -> None:
    with psycopg.connect(
        get_database_url(),
        connect_timeout=connect_timeout,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            if cur.fetchone() is None:
                raise RuntimeError("database health check returned no rows")
