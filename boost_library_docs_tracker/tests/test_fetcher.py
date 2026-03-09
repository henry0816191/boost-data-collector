"""Tests for boost_library_docs_tracker.fetcher (unit tests with mocked HTTP)."""

from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

from boost_library_docs_tracker import fetcher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_html_response(html: str, final_url: str | None = None) -> MagicMock:
    """Return a mock requests.Response for an HTML page."""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    resp.text = html
    resp.url = final_url or ""
    return resp


@pytest.fixture(autouse=True)
def _mock_pandoc(monkeypatch):
    """Patch convert_html_to_markdown for all tests in this module.

    The crawl/walk tests are about HTTP/file traversal logic, not conversion.
    This avoids a hard dependency on pandoc being installed in CI.
    """
    monkeypatch.setattr(
        "boost_library_docs_tracker.fetcher.convert_html_to_markdown",
        lambda html: f"[converted]{html}",
    )


# ---------------------------------------------------------------------------
# crawl_library_pages
# ---------------------------------------------------------------------------

_ROOT_HTML = """<html><body>
<a href="page1.html">Page 1</a>
<a href="page2.html">Page 2</a>
<a href="https://external.com/">External</a>
</body></html>"""

_PAGE1_HTML = "<html><body>Content of page 1</body></html>"
_PAGE2_HTML = "<html><body>Content of page 2</body></html>"


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_visits_in_scope_pages(mock_get_session, _mock_sleep):
    """crawl_library_pages visits pages within the root URL prefix."""
    # Fetcher builds start_url as urljoin(base_url, start_path) -> no trailing slash.
    # Return final_url with trailing slash so relative links (page1.html) resolve correctly.
    start_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm"
    root_final = start_url + "/"

    def side_effect(url, timeout=30):
        if url == start_url or url == root_final:
            return _mock_html_response(_ROOT_HTML, final_url=root_final)
        elif url.endswith("page1.html"):
            return _mock_html_response(_PAGE1_HTML, final_url=url)
        elif url.endswith("page2.html"):
            return _mock_html_response(_PAGE2_HTML, final_url=url)
        else:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.headers = {"Content-Type": "text/plain"}
            resp.text = ""
            resp.url = url
            return resp

    session = MagicMock()
    session.get.side_effect = side_effect
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(
        Path("libs/algorithm"), "algorithm", "1.87.0", max_pages=10, delay_secs=0
    )
    urls = [url for url, _ in results]
    assert start_url in urls or (start_url + "/") in urls
    assert "https://external.com/" not in urls


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_respects_max_pages(mock_get_session, _mock_sleep):
    """crawl_library_pages stops at max_pages."""
    start_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm"

    many_links = "".join(f'<a href="page{i}.html">Page {i}</a>' for i in range(100))
    root_html = f"<html><body>{many_links}</body></html>"

    def side_effect(url, timeout=30):
        if url == start_url or url.startswith(start_url + "/"):
            html = root_html if url == start_url else "<html><body>page</body></html>"
        else:
            html = "<html><body>page</body></html>"
        return _mock_html_response(html, final_url=url)

    session = MagicMock()
    session.get.side_effect = side_effect
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(
        Path("libs/algorithm"), "algorithm", "1.87.0", max_pages=5, delay_secs=0
    )
    assert len(results) <= 5


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_skips_non_html(mock_get_session, _mock_sleep):
    """crawl_library_pages skips pages with non-HTML content type."""
    start_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm"
    pdf_url = start_url + "/reference.pdf"

    root_html = '<html><body><a href="reference.pdf">PDF</a></body></html>'

    def side_effect(url, timeout=30):
        if url == start_url:
            return _mock_html_response(root_html, final_url=url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.headers = {"Content-Type": "application/pdf"}
        resp.text = ""
        resp.url = url
        return resp

    session = MagicMock()
    session.get.side_effect = side_effect
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(
        Path("libs/algorithm"), "algorithm", "1.87.0", max_pages=10, delay_secs=0
    )
    urls = [url for url, _ in results]
    assert pdf_url not in urls


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_follows_redirect_url(mock_get_session, _mock_sleep):
    """crawl_library_pages uses resp.url (final URL after redirect) not the queued URL."""
    start_url = "https://www.boost.org/doc/libs/1_87_0/libs/utility"
    root_final = start_url + "/"
    htm_url = root_final + "call_traits.htm"
    html_url = root_final + "call_traits.html"  # redirect target

    root_html = '<html><body><a href="call_traits.htm">Traits</a></body></html>'

    def side_effect(url, timeout=30):
        if url == start_url or url == root_final:
            return _mock_html_response(root_html, final_url=root_final)
        if url == htm_url:
            # Simulates server redirect: .htm → .html
            return _mock_html_response(
                "<html><body>Call traits</body></html>", final_url=html_url
            )
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.headers = {"Content-Type": "text/plain"}
        resp.url = url
        return resp

    session = MagicMock()
    session.get.side_effect = side_effect
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(
        Path("libs/utility"), "utility", "1.87.0", max_pages=10, delay_secs=0
    )
    urls = [url for url, _ in results]
    # The stored URL must be the redirected final URL, not the original .htm
    assert html_url in urls
    assert htm_url not in urls


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_returns_markdown(mock_get_session, _mock_sleep):
    """crawl_library_pages returns text from convert_html_to_markdown, not raw HTML."""
    start_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm"
    html = "<html><body><h1>Hello</h1><p>World</p></body></html>"

    session = MagicMock()
    session.get.return_value = _mock_html_response(html, final_url=start_url)
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(
        Path("libs/algorithm"), "algorithm", "1.87.0", max_pages=1, delay_secs=0
    )
    assert len(results) == 1
    _url, text = results[0]
    # The autouse _mock_pandoc fixture returns "[converted]<original html>"
    # so we verify conversion was applied (not raw HTML passed through unchanged)
    assert text == f"[converted]{html}"
