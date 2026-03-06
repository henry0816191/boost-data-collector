"""Tests for boost_library_docs_tracker.fetcher (unit tests with mocked HTTP)."""

from unittest.mock import MagicMock, patch

import pytest

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
    root_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm/"

    def side_effect(url, timeout=30):
        if url == root_url:
            return _mock_html_response(_ROOT_HTML, final_url=url)
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

    results = fetcher.crawl_library_pages(root_url, max_pages=10, delay_secs=0)
    urls = [url for url, _ in results]
    assert root_url in urls
    assert "https://external.com/" not in urls


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_respects_max_pages(mock_get_session, _mock_sleep):
    """crawl_library_pages stops at max_pages."""
    root_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm/"

    many_links = "".join(
        f'<a href="{root_url}page{i}.html">Page {i}</a>'
        for i in range(100)
    )
    root_html = f"<html><body>{many_links}</body></html>"

    def side_effect(url, timeout=30):
        html = root_html if url == root_url else "<html><body>page</body></html>"
        return _mock_html_response(html, final_url=url)

    session = MagicMock()
    session.get.side_effect = side_effect
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(root_url, max_pages=5, delay_secs=0)
    assert len(results) <= 5


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_skips_non_html(mock_get_session, _mock_sleep):
    """crawl_library_pages skips pages with non-HTML content type."""
    root_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm/"
    pdf_url = root_url + "reference.pdf"

    root_html = f'<html><body><a href="{pdf_url}">PDF</a></body></html>'

    def side_effect(url, timeout=30):
        if url == root_url:
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

    results = fetcher.crawl_library_pages(root_url, max_pages=10, delay_secs=0)
    urls = [url for url, _ in results]
    assert pdf_url not in urls


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_follows_redirect_url(mock_get_session, _mock_sleep):
    """crawl_library_pages uses resp.url (final URL after redirect) not the queued URL."""
    root_url = "https://www.boost.org/doc/libs/1_87_0/libs/utility/"
    htm_url = root_url + "call_traits.htm"
    html_url = root_url + "call_traits.html"  # redirect target

    root_html = f'<html><body><a href="call_traits.htm">Traits</a></body></html>'

    def side_effect(url, timeout=30):
        if url == root_url:
            return _mock_html_response(root_html, final_url=root_url)
        if url == htm_url:
            # Simulates server redirect: .htm → .html
            return _mock_html_response("<html><body>Call traits</body></html>", final_url=html_url)
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.headers = {"Content-Type": "text/plain"}
        resp.url = url
        return resp

    session = MagicMock()
    session.get.side_effect = side_effect
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(root_url, max_pages=10, delay_secs=0)
    urls = [url for url, _ in results]
    # The stored URL must be the redirected final URL, not the original .htm
    assert html_url in urls
    assert htm_url not in urls


@patch("boost_library_docs_tracker.fetcher.time.sleep", return_value=None)
@patch("boost_library_docs_tracker.fetcher._get_session")
def test_crawl_library_pages_returns_markdown(mock_get_session, _mock_sleep):
    """crawl_library_pages returns converted markdown text, not raw HTML."""
    root_url = "https://www.boost.org/doc/libs/1_87_0/libs/algorithm/"
    html = "<html><body><h1>Hello</h1><p>World</p></body></html>"

    session = MagicMock()
    session.get.return_value = _mock_html_response(html, final_url=root_url)
    mock_get_session.return_value = session

    results = fetcher.crawl_library_pages(root_url, max_pages=1, delay_secs=0)
    assert len(results) == 1
    _url, text = results[0]
    # Markdown output should not contain raw HTML tags
    assert "<html>" not in text
    assert "<body>" not in text
    # Content should be preserved
    assert "Hello" in text
    assert "World" in text
