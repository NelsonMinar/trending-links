import os
import sqlite3
import json
import pytest
import niquests
from unittest.mock import AsyncMock, patch
from unittest import mock
import sys
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import build

@pytest.fixture
def test_page_html():
    with open(os.path.join(os.path.dirname(__file__), 'fixtures', 'test_page.html'), 'r') as f:
        return f.read()

def populate_test_data(cur):
    """
    Populates the database with carefully crafted data to test the algorithm.
    The algorithm filters for instances > 5.
    Score calculation: (count(distinct instance) * max(uses_1d)) / max(rank)
    """
    snapshot = 1000

    # Link A: high instance count (6), high uses (1000), great rank (1)
    # Score: (6 * 1000) / 1 = 6000
    for i in range(6):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/A", 1, 1000, 2000, f"inst{i}", snapshot))

    # Link B: high instance count (6), ok uses (500), terrible rank (10)
    # Score: (6 * 500) / 10 = 300
    for i in range(6):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/B", 10, 500, 1000, f"inst{i}", snapshot))

    # Link E: very high instance count (15), high uses (2000), great rank (1)
    # Score: (15 * 2000) / 1 = 30000
    # Should be included in RSS feed (15 > 0.75 * 19)
    for i in range(15):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/E", 1, 2000, 4000, f"inst{i}", snapshot))

    # Link C: too few instances (5). Should be filtered out.
    for i in range(5):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/C", 1, 5000, 10000, f"inst{i}", snapshot))

    # Link D: old snapshot. Should be deleted.
    for i in range(6):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/D", 1, 1000, 2000, f"inst{i}", snapshot - 100))

@pytest.mark.asyncio
async def test_build_algorithm_and_output(mock_db, test_page_html, tmpdir):
    con, cur = mock_db
    populate_test_data(cur)
    con.commit()

    # Change the output path to a temporary directory so we don't overwrite real files
    with mock.patch('build.path', str(tmpdir)):

        real_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

        # We must copy templates and servers.txt to the tmpdir so Environment can find them
        os.makedirs(os.path.join(tmpdir, "templates"), exist_ok=True)
        for tpl in ["trending-links.json", "trending-links.xml", "trending-links.html"]:
            shutil.copy(os.path.join(real_path, "templates", tpl), os.path.join(tmpdir, "templates", tpl))
        shutil.copy(os.path.join(real_path, "servers.txt"), os.path.join(tmpdir, "servers.txt"))

        with patch('niquests.AsyncSession.get', new_callable=AsyncMock) as mock_get:
            def side_effect(url, **kwargs):
                if url not in ("https://example.com/A", "https://example.com/B", "https://example.com/E"):
                    raise ValueError(f"Unexpected URL: {url}")
                resp = niquests.Response()
                resp.status_code = 200
                resp._content = test_page_html.encode('utf-8')
                resp.url = url
                return resp

            mock_get.side_effect = side_effect

            # Pass the in-memory DB connection to build.main
            await build.main(con=con)

        # 1. Verify that Old Snapshots were deleted
        cur.execute("SELECT count(*) as count FROM links WHERE link = 'https://example.com/D'")
        assert cur.fetchone()['count'] == 0

        # 2. Verify Output Files are created
        assert os.path.exists(os.path.join(tmpdir, "output", "trending-links.json"))
        assert os.path.exists(os.path.join(tmpdir, "output", "trending-links.xml"))
        assert os.path.exists(os.path.join(tmpdir, "output", "trending-links.html"))

        # 3. Verify JSON contents and ranking algorithm
        with open(os.path.join(tmpdir, "output", "trending-links.json"), "r") as f:
            feed = json.load(f)

        items = feed.get("items", [])

        # Link C is filtered out due to HAVING instances > 5. Link D is deleted.
        # Links E, A, and B should remain.
        assert len(items) == 3

        # Link E has score 30000, Link A has score 6000, Link B has score 300
        assert items[0]["url"] == "https://example.com/E"
        assert items[1]["url"] == "https://example.com/A"
        assert items[2]["url"] == "https://example.com/B"

        # 4. Verify Link preview meta mapping
        assert items[0]["title"] == "Open Graph Test Title"
        assert items[0]["content_text"] == "Open Graph Test Description"
        assert items[0]["image"] == "https://example.com/test-image.jpg"

        # 5. Verify RSS output
        import xml.etree.ElementTree as ET
        tree = ET.parse(os.path.join(tmpdir, "output", "trending-links.xml"))
        root = tree.getroot()
        rss_items = root.findall("./channel/item")

        # In RSS, only Link E should be included (15 > 0.75 * 19)
        assert len(rss_items) == 1
        assert rss_items[0].find("link").text == "https://example.com/E"
