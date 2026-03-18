import os
import sqlite3
import pytest

@pytest.fixture
def mock_db():
    # Use an in-memory database for testing
    con = sqlite3.connect(':memory:')
    con.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cur = con.cursor()

    # Setup the database schema
    # Path is relative to the tests directory, going up one level to mastodon/setup.sql
    with open(os.path.join(os.path.dirname(__file__), '..', 'setup.sql'), 'r') as f:
        cur.executescript(f.read())

    yield con, cur