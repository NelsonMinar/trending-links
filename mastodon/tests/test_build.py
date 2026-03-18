import os
import sqlite3
import json
import pytest
import responses
from unittest import mock
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import build

@pytest.fixture
def mock_db():
    # Use an in-memory database for testing
    con = sqlite3.connect(':memory:')
    con.row_factory = lambda c, r: dict(zip([col[0] for col in c.description], r))
    cur = con.cursor()

    # Setup the database schema
    with open(os.path.join(os.path.dirname(__file__), '..', 'setup.sql'), 'r') as f:
        cur.executescript(f.read())

    yield con, cur

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

    # Link C: too few instances (5). Should be filtered out.
    for i in range(5):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/C", 1, 5000, 10000, f"inst{i}", snapshot))

    # Link D: old snapshot. Should be deleted.
    for i in range(6):
        cur.execute("INSERT INTO links (link, rank, uses_1d, uses_total, instance, snapshot) VALUES (?, ?, ?, ?, ?, ?)",
                    ("https://example.com/D", 1, 1000, 2000, f"inst{i}", snapshot - 100))

@responses.activate
def test_build_algorithm_and_output(mock_db, test_page_html, tmpdir):
    con, cur = mock_db
    populate_test_data(cur)
    con.commit()

    # Change the output path to a temporary directory so we don't overwrite real files
    with mock.patch('build.path', str(tmpdir)):

        # We need to mock the template loading path differently since we changed `build.path`
        real_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

        # Mock LinkGrabber content fetching to return our fixture
        responses.add(
            responses.GET,
            "https://example.com/A",
            body=test_page_html,
            status=200
        )
        responses.add(
            responses.GET,
            "https://example.com/B",
            body=test_page_html,
            status=200
        )

        # We must copy templates to the tmpdir so Environment can find them
        os.makedirs(os.path.join(tmpdir, "templates"), exist_ok=True)
        import shutil
        for tpl in ["trending-links.json", "trending-links.xml", "trending-links.html"]:
            shutil.copy(os.path.join(real_path, "templates", tpl), os.path.join(tmpdir, "templates", tpl))

        # Mock linkpreview.LinkGrabber instead of requests directly
        # because the internal implementation might not just use requests.get in a simple way
        with mock.patch('build.LinkGrabber') as mock_grabber_class:
            mock_grabber = mock.Mock()
            # Return our test HTML string when get_content is called
            mock_grabber.get_content.return_value = (test_page_html.encode('utf-8'), "https://example.com/mock-url")
            mock_grabber_class.return_value = mock_grabber

            # Mock sqlite3.connect to return our in-memory DB connection
            with mock.patch('sqlite3.connect', return_value=con):
                # Run the build process
                with mock.patch('build.path', str(tmpdir)):
                    build.main()

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
        # Only Link A and B should remain.
        assert len(items) == 2

        # Link A has score 6000, Link B has score 300, so Link A should be first.
        assert items[0]["url"] == "https://example.com/A"
        assert items[1]["url"] == "https://example.com/B"

        # 4. Verify Link preview meta mapping
        # Linkpreview prefers OpenGraph tags over standard meta tags
        assert items[0]["title"] == "Open Graph Test Title"
        assert items[0]["content_text"] == "Open Graph Test Description"
        assert items[0]["image"] == "https://example.com/test-image.jpg"