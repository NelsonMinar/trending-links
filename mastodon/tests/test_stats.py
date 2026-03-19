import os
import sqlite3
import json
import pytest
import respx
import httpx
from unittest import mock
import asyncio
import sys
from bs4 import BeautifulSoup
import shutil

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import build

@pytest.fixture
def test_page_html():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:title" content="Test Title">
        <meta property="og:description" content="Test Description">
        <meta property="og:image" content="https://example.com/image.jpg">
    </head>
    <body></body>
    </html>
    """

def populate_test_data(cur):
    snapshot = 1000
    # Link A: 7 instances
    for i in range(7):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/A", 1, 1000, 2000, f"inst{i}", snapshot))

    # Link B: 6 instances
    for i in range(6):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/B", 2, 500, 1000, f"inst{i}", snapshot))

@pytest.mark.asyncio
async def test_stats_and_sorting(mock_db, test_page_html, tmpdir):
    con, cur = mock_db
    populate_test_data(cur)
    con.commit()

    # Create a mock servers.txt with all instances used in test data
    tmp_path = str(tmpdir)
    servers = [f"inst{i}" for i in range(7)]
    with open(os.path.join(tmp_path, "servers.txt"), "w") as f:
        for s in servers:
            f.write(s + "\n")

    os.makedirs(os.path.join(tmp_path, "templates"), exist_ok=True)
    real_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    for tpl in ["trending-links.json", "trending-links.xml", "trending-links.html"]:
        shutil.copy(os.path.join(real_path, "templates", tpl), os.path.join(tmp_path, "templates", tpl))

    async with respx.mock:
        # Mock link content fetching
        respx.get("https://example.com/A").mock(
            return_value=httpx.Response(200, text=test_page_html)
        )
        respx.get("https://example.com/B").mock(
            return_value=httpx.Response(200, text=test_page_html)
        )

        with mock.patch('sqlite3.connect', return_value=con):
            with mock.patch('build.path', tmp_path):
                await build.main()

    # Verify HTML output for stats
    with open(os.path.join(tmp_path, "output", "trending-links.html"), "r") as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    # 1. Check Story Count in footer
    footer = soup.find('div', class_='footer')
    assert "Stories: 2" in footer.get_text()

    # 2. Check per-story stats
    links = soup.find_all('div', class_='link')
    assert len(links) == 2

    # Link A (Rank 1) should have 1000 shares and 7 sources
    assert "1000 shares" in links[0].get_text()
    assert "7 sources" in links[0].get_text()

    # Link B (Rank 2) should have 500 shares and 6 sources
    assert "500 shares" in links[1].get_text()
    assert "6 sources" in links[1].get_text()

    # 3. Check sorted instances in footer
    # inst0 through inst5 contributed to both A and B (2 links)
    # inst6 only contributed to A (1 link)
    # So inst0-inst5 should come before inst6
    sources_text = footer.find_all('p')[-1].get_text()
    # It looks like "Sources: inst0, inst1, ..."
    sources_list = [s.strip() for s in sources_text.replace("Sources:", "").split(",")]

    # inst6 should be at the end
    assert sources_list[-1] == "inst6"
    # The first 6 should be inst0-inst5 in some order (they all have 2 contributions)
    assert set(sources_list[:6]) == {f"inst{i}" for i in range(6)}
