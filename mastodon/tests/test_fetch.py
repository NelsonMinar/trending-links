import os
import sqlite3
import json
import pytest
import respx
import httpx
from unittest import mock
import asyncio

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import fetch

@pytest.fixture
def mock_mastodon_response():
    with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'trends.json'), 'r') as f:
        return json.load(f)

@pytest.mark.asyncio
async def test_extractLinks(mock_db, mock_mastodon_response):
    con, cur = mock_db

    # Mock the API endpoint
    instance = "example.social"

    async with respx.mock:
        respx.get(f"https://{instance}/api/v1/trends/links").mock(
            return_value=httpx.Response(200, json=mock_mastodon_response)
        )

        # We expect 5 requests to the same endpoint due to the pagination loop
        snapshot_time = 1234567890
        semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient() as client:
            returned_instance, links = await fetch.extractLinks(instance, snapshot_time, client, semaphore)

        assert returned_instance == instance
        assert len(links) == 10 # 5 iterations * 2 links per response

        # Note: fetch.py's extractLinks no longer writes to the DB itself,
        # it returns the links and they are written in main().
        # Let's mock the main writing logic here to verify the data structure.
        for index, link in enumerate(links, start=1):
            linkMeta = {
                'link': link['url'],
                'rank': index,
                'uses_1d': int(link['history'][0]['uses']),
                'uses_total': sum(int(activity['uses']) for activity in link['history']),
                'instance': instance,
                'snapshot': snapshot_time
            }
            clean_meta = fetch.clean_dict(linkMeta)
            columns = ', '.join(clean_meta.keys())
            placeholders = ', '.join(['?'] * len(clean_meta))
            query = f"INSERT INTO links ({columns}) VALUES ({placeholders});"
            cur.execute(query, tuple(clean_meta.values()))

    # Verify the database state
    cur.execute("SELECT * FROM links")
    rows = cur.fetchall()

    # We expect 10 rows
    assert len(rows) == 10

    # Check the first row
    assert rows[0]['link'] == "https://example.com/article1"
    assert rows[0]['rank'] == 1
    assert rows[0]['uses_1d'] == 100
    assert rows[0]['uses_total'] == 180
    assert rows[0]['instance'] == "example.social"
    assert rows[0]['snapshot'] == snapshot_time

@pytest.mark.asyncio
async def test_extractLinks_sql_injection(mock_db):
    con, cur = mock_db

    instance = "malicious.social"
    malicious_url = "https://example.com/article'\" OR 1=1; --"
    malicious_response = [
        {
            "url": malicious_url,
            "history": [{"uses": "10"}, {"uses": "20"}],
        }
    ]

    async with respx.mock:
        respx.get(f"https://{instance}/api/v1/trends/links").mock(
            return_value=httpx.Response(200, json=malicious_response)
        )

        # Verify that malicious input doesn't break the SQL insertion
        snapshot_time = 1234567890
        semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient() as client:
            returned_instance, links = await fetch.extractLinks(instance, snapshot_time, client, semaphore)

        for index, link in enumerate(links, start=1):
            linkMeta = {
                'link': link['url'],
                'rank': index,
                'uses_1d': int(link['history'][0]['uses']),
                'uses_total': sum(int(activity['uses']) for activity in link['history']),
                'instance': instance,
                'snapshot': snapshot_time
            }
            clean_meta = fetch.clean_dict(linkMeta)
            columns = ', '.join(clean_meta.keys())
            placeholders = ', '.join(['?'] * len(clean_meta))
            query = f"INSERT INTO links ({columns}) VALUES ({placeholders});"
            cur.execute(query, tuple(clean_meta.values()))

    cur.execute("SELECT * FROM links WHERE instance = ? AND link = ?", (instance, malicious_url))
    rows = cur.fetchall()
    # 5 iterations * 1 link per response = 5 rows
    assert len(rows) == 5
    assert rows[0]['link'] == malicious_url

@pytest.mark.asyncio
async def test_extractLinks_request_exception(mock_db, capsys):
    con, cur = mock_db
    instance = "error.social"

    async with respx.mock:
        respx.get(f"https://{instance}/api/v1/trends/links").mock(
            side_effect=httpx.ConnectError("Connection Error")
        )

        snapshot_time = 1234567890
        semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient() as client:
            returned_instance, links = await fetch.extractLinks(instance, snapshot_time, client, semaphore)

    # Ensure error was caught and printed
    captured = capsys.readouterr()
    assert f"ERROR [{instance}]:" in captured.out
    assert len(links) == 0
