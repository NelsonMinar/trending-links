import os
import sqlite3
import json
import pytest
import respx
import httpx
import asyncio
from unittest import mock

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

    with respx.mock:
        respx.get(f"https://{instance}/api/v1/trends/links").mock(
            return_value=httpx.Response(200, json=mock_mastodon_response)
        )

        snapshot_time = 1234567890
        semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient() as client:
            results = await fetch.extractLinks(instance, snapshot_time, client, semaphore)

        # Verify results returned by extractLinks
        # We expect 10 results (5 iterations * 2 links per response)
        assert len(results) == 10

        # Check the first row
        assert results[0]['link'] == "https://example.com/article1"
        assert results[0]['rank'] == 1
        assert results[0]['uses_1d'] == 100
        assert results[0]['uses_total'] == 180
        assert results[0]['instance'] == instance
        assert results[0]['snapshot'] == snapshot_time

        # Check the second row
        assert results[1]['link'] == "https://example.com/article2"
        assert results[1]['rank'] == 2
        assert results[1]['uses_1d'] == 50
        assert results[1]['uses_total'] == 70

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

    with respx.mock:
        respx.get(f"https://{instance}/api/v1/trends/links").mock(
            return_value=httpx.Response(200, json=malicious_response)
        )

        snapshot_time = 1234567890
        semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient() as client:
            results = await fetch.extractLinks(instance, snapshot_time, client, semaphore)

        assert len(results) == 5
        assert results[0]['link'] == malicious_url

@pytest.mark.asyncio
async def test_extractLinks_request_exception(mock_db, capsys):
    con, cur = mock_db
    instance = "error.social"

    with respx.mock:
        respx.get(f"https://{instance}/api/v1/trends/links").mock(
            side_effect=httpx.ConnectError("Connection Error")
        )

        snapshot_time = 1234567890
        semaphore = asyncio.Semaphore(10)
        async with httpx.AsyncClient() as client:
            results = await fetch.extractLinks(instance, snapshot_time, client, semaphore)

        # Ensure error was caught and printed
        captured = capsys.readouterr()
        assert "ERROR [error.social]:" in captured.out

        # Ensure no results were returned
        assert len(results) == 0
