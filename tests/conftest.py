"""
Shared pytest fixtures for the test suite
"""

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def database_schema() -> None:
    if not os.environ.get("DATABASE_URL"):
        return

    from core.schema import main as setup_database

    setup_database()
