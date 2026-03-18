import os
import sqlite3
import json
import pytest
import responses
from unittest import mock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import fetch

@pytest.fixture
def mock_mastodon_response():
    with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'trends.json'), 'r') as f:
        return json.load(f)

@responses.activate
def test_extractLinks(mock_db, mock_mastodon_response):
    con, cur = mock_db

    # Mock the API endpoint
    instance = "example.social"
    responses.add(
        responses.GET,
        f"https://{instance}/api/v1/trends/links",
        json=mock_mastodon_response,
        status=200
    )

    # We expect 5 requests to the same endpoint due to the pagination loop
    snapshot_time = 1234567890
    fetch.extractLinks(instance, snapshot_time, con, cur)

    # Verify the database state
    cur.execute("SELECT * FROM links")
    rows = cur.fetchall()

    # We expect 10 rows (5 iterations * 2 links per response)
    assert len(rows) == 10

    # Check the first row
    assert rows[0]['link'] == "https://example.com/article1"
    assert rows[0]['rank'] == 1
    assert rows[0]['uses_1d'] == 100
    assert rows[0]['uses_total'] == 180
    assert rows[0]['instance'] == "example.social"
    assert rows[0]['snapshot'] == snapshot_time

    # Check the second row
    assert rows[1]['link'] == "https://example.com/article2"
    assert rows[1]['rank'] == 2
    assert rows[1]['uses_1d'] == 50
    assert rows[1]['uses_total'] == 70

@responses.activate
def test_extractLinks_sql_injection(mock_db):
    con, cur = mock_db

    instance = "malicious.social"
    malicious_url = "https://example.com/article'\" OR 1=1; --"
    malicious_response = [
        {
            "url": malicious_url,
            "history": [{"uses": "10"}, {"uses": "20"}],
        }
    ]
    responses.add(
        responses.GET,
        f"https://{instance}/api/v1/trends/links",
        json=malicious_response,
        status=200
    )

    # Verify that malicious input doesn't break the SQL insertion
    fetch.extractLinks(instance, 1234567890, con, cur)

    cur.execute("SELECT * FROM links WHERE instance = ? AND link = ?", (instance, malicious_url))
    rows = cur.fetchall()
    # 5 iterations * 1 link per response = 5 rows
    assert len(rows) == 5
    assert rows[0]['link'] == malicious_url

@responses.activate
def test_extractLinks_request_exception(mock_db, capsys):
    con, cur = mock_db
    instance = "error.social"

    import requests
    # Mock an error response (needs to be a RequestException to be caught)
    responses.add(
        responses.GET,
        f"https://{instance}/api/v1/trends/links",
        body=requests.exceptions.RequestException("Connection Error")
    )

    fetch.extractLinks(instance, 1234567890, con, cur)

    # Ensure error was caught and printed
    captured = capsys.readouterr()
    assert "ERROR:" in captured.out

    # Ensure no rows were inserted
    cur.execute("SELECT count(*) as count FROM links")
    assert cur.fetchone()['count'] == 0