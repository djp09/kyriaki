"""Pytest configuration — ensures SQLite is used for all tests."""

import os
import tempfile

# Use a shared temp file so all connections see the same tables
_test_db = os.path.join(tempfile.gettempdir(), "kyriaki_test.db")
os.environ.setdefault("KYRIAKI_DATABASE_URL", f"sqlite+aiosqlite:///{_test_db}")
