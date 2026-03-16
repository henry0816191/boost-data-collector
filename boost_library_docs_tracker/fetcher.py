"""
Fetcher for boost_library_docs_tracker.
Handles HTTP requests, library discovery, BFS page crawling, and local zip-based scraping.
All network I/O and file I/O lives here; no DB access.
"""

import logging
import shutil
import time
import zipfile
from collections import deque
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .workspace import get_extract_dir
from .html_to_md import convert_html_to_markdown  # noqa: F401

logger = logging.getLogger(__name__)

BOOST_ORG_BASE = "https://www.boost.org"
BOOST_SOURCE_ZIP_URL = (
    "https://archives.boost.io/release/{version}/source/boost_{url_version}.zip"
)
BOOST_SOURCE_ZIP_GITHUB_URL = (
    "https://github.com/boostorg/boost/archive/refs/tags/boost-{version}.zip"
)

DEFAULT_MAX_PAGES = 1000
DEFAULT_DELAY_SECS = 0.5

_SESSION: requests.Session | None = None


def _get_session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = requests.Session()
        _SESSION.headers["User-Agent"] = "boost-data-collector/1.0"
    return _SESSION


# ---------------------------------------------------------------------------
# Local zip: download, extract, walk
# ---------------------------------------------------------------------------


def source_zip_url(version: str) -> str:
    """Return the archives.boost.io URL for the source zip of a given version.

    e.g. version='1.90.0' → 'https://archives.boost.io/release/1.90.0/source/boost_1_90_0.zip'
    """
    version = version.removeprefix("boost-")
    url_version = version.replace(".", "_")
    return BOOST_SOURCE_ZIP_URL.format(version=version, url_version=url_version)


def source_zip_fallback_url(version: str) -> str:
    """Return fallback source zip URL from GitHub tags."""
    version = version.removeprefix("boost-")
    return BOOST_SOURCE_ZIP_GITHUB_URL.format(version=version)


def download_source_zip(version: str, dest_dir: Path) -> Path:
    """
    Download the Boost source zip for *version* into *dest_dir*.

    Returns the path of the saved zip file.
    Skips the download if the file already exists (resume-safe).
    Raises requests.HTTPError on failure.
    """
    normalized = version.removeprefix("boost-")
    urls = [source_zip_url(normalized), source_zip_fallback_url(normalized)]
    zip_name = f"boost_{normalized.replace('.', '_')}.zip"
    zip_path = dest_dir / zip_name

    # if zip_path.exists():
    #     logger.info("Source zip already present, skipping download: %s", zip_path)
    #     return zip_path

    dest_dir.mkdir(parents=True, exist_ok=True)
    session = _get_session()
    last_exc: Exception | None = None

    for url in urls:
        try:
            logger.info("Downloading Boost %s source zip from %s ...", normalized, url)
            with session.get(url, stream=True, timeout=300) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                with zip_path.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            logger.debug(
                                "  %d%% (%d / %d bytes)", pct, downloaded, total
                            )
            logger.info(
                "Download complete: %s (%d bytes)",
                zip_path,
                zip_path.stat().st_size,
            )
            return zip_path
        except requests.RequestException as exc:
            last_exc = exc
            logger.warning("Failed downloading from %s: %s", url, exc)
            if zip_path.exists():
                zip_path.unlink(missing_ok=True)

    if last_exc is None:
        raise RuntimeError("Unknown error while downloading source zip")
    raise last_exc


def extract_source_zip(zip_path: Path, extract_dir: Path) -> Path:
    """
    Extract the Boost source zip into *extract_dir*.

    Returns the top-level extracted directory (e.g. /boost_1_90_0/).
    Skips extraction if the top-level dir already exists (resume-safe).
    """
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = [n for n in zf.namelist() if n and not n.startswith("__MACOSX/")]
        if not names:
            raise RuntimeError(f"Zip has no entries: {zip_path}")
        root_name = sorted({n.split("/", 1)[0] for n in names})[0]
        top_dir = extract_dir / root_name

        # if top_dir.exists():
        #     logger.info(
        #         "Extracted source already present, skipping extract: %s", top_dir
        #     )
        #     return top_dir

        logger.info("Extracting %s → %s ...", zip_path.name, extract_dir)
        zf.extractall(extract_dir)

    logger.info("Extraction complete: %s", top_dir)
    return top_dir


def delete_extract_dir(extract_dir: Path) -> None:
    """Delete the extracted source tree to free disk space after scraping."""
    if extract_dir.exists():
        shutil.rmtree(extract_dir)
        logger.info("Deleted extracted source dir: %s", extract_dir)


def _library_root_for_key(lib_key: str) -> Path:
    """Resolve extracted library root directory from BoostLibraryVersion.key."""
    key = (lib_key or "").strip().strip("/")
    if not key:
        return Path("libs")
    if key.startswith("numeric/"):
        return Path("libs") / key
    if "enable_if" in key or "swap" in key:
        return Path("libs") / "core"
    return Path("libs") / key.split("/")[0]


def get_start_path(lib_key: str, lib_documentation: str) -> Path:
    """
    Resolve first HTML path from BoostLibraryVersion.key/documentation.
    Returned path is relative to extracted source root("/libs(docs)/<lib_key>/").
    """
    lib_root = _library_root_for_key(lib_key)
    doc = (lib_documentation or "").strip()

    if doc.startswith("/doc/"):
        rel = Path(doc.lstrip("/"))
    elif doc:
        rel = lib_root / doc.lstrip("/")
    else:
        rel = lib_root / "index.html"

    if doc.endswith("/"):
        rel = rel / "index.html"
    return rel


def walk_library_html(
    start_path: Path,
    lib_key: str,
    version: str,
    *,
    max_pages: int | None = None,
) -> list[tuple[str, str]]:
    """
    Walk local HTML files for one library inside the extracted Boost source tree.

    start_path:   relative path to the library root in the extracted source tree,
                  e.g. Path("/libs/utility/doc/html/index.html")
    lib_key:       library key, e.g. 'utility'
    version:       Boost version string, e.g. '1.90.0'

    The canonical URL for each file is built as:
        https://www.boost.org/doc/libs/<url_version>/libs/<lib_key>/<rel_path>

    BFS-walks from the doc entry point, following links that stay within
    the library's `libs/<lib_key>/` subtree.

    Returns a list of (canonical_url, page_text).
    """
    url_version = version.removeprefix("boost-").replace(".", "_")
    base_url = f"{BOOST_ORG_BASE}/doc/libs/{url_version}/"

    base_path = get_extract_dir() / f"boost_{url_version}"
    start_file = base_path.resolve() / start_path

    visited: set[Path] = set()
    queue: deque[Path] = deque([start_file])
    results: list[tuple[str, str]] = []

    while queue:
        if max_pages is not None and len(results) >= max_pages:
            break
        file_path = queue.popleft()
        if file_path in visited:
            continue
        visited.add(file_path)

        if not file_path.exists() or file_path.suffix.lower() not in {".html", ".htm"}:
            continue
        if file_path.name.startswith("."):  # hidden or macos files
            continue

        try:
            html = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Could not read %s: %s", file_path, exc)
            continue

        text = convert_html_to_markdown(html)
        rel_path = file_path.relative_to(base_path).as_posix()
        canonical_url = base_url + rel_path
        results.append((canonical_url, text))

        # Enqueue in-scope links
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href: str = a["href"].split("#")[0].strip()
            if not href or href.startswith(("http://", "https://", "mailto:")):
                continue
            if not href.endswith(".html") and not href.endswith(".htm"):
                continue
            linked = (file_path.parent / href).resolve()
            # Stay within the library subtree
            if lib_key.split("/")[-1] not in linked.as_posix():
                continue
            if linked not in visited and linked not in queue:
                queue.append(linked)

    logger.debug(
        "Walked %d local pages for lib=%s version=%s", len(results), lib_key, version
    )
    return results


# ---------------------------------------------------------------------------
# HTTP page crawling
# ---------------------------------------------------------------------------


def crawl_library_pages(
    start_path: Path,
    lib_key: str,
    version: str,
    *,
    max_pages: int | None = None,
    delay_secs: float = DEFAULT_DELAY_SECS,
) -> list[tuple[str, str]]:
    """
    BFS-crawl the documentation tree rooted at doc_root_url.
    Only follows links that stay within the same URL prefix (doc_root_url).

    Returns a list of (url, page_text) for every page visited.
    Stops after max_pages pages to avoid run-away crawls. Pass None for no limit.
    Waits delay_secs between requests.
    """
    session = _get_session()
    visited: set[str] = set()
    url_version = version.removeprefix("boost-").replace(".", "_")
    base_url = f"{BOOST_ORG_BASE}/doc/libs/{url_version}/"
    start_url = urljoin(base_url, start_path.as_posix())
    queue: deque[str] = deque([start_url])
    results: list[tuple[str, str]] = []

    while queue and (max_pages is None or len(results) < max_pages):
        url = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Failed to fetch %s: %s", url, exc)
            continue

        # Use final URL after redirects (e.g. server may redirect .htm → .html)
        final_url = resp.url
        visited.add(final_url)

        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type:
            continue

        text = convert_html_to_markdown(resp.text)
        results.append((final_url, text))

        if delay_secs > 0:
            time.sleep(delay_secs)

        # Enqueue in-scope links
        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            abs_url = urljoin(final_url, href)
            # Strip fragment
            abs_url = abs_url.split("#")[0]
            if (
                abs_url not in visited
                and abs_url.startswith(start_url)
                and abs_url not in queue
            ):
                queue.append(abs_url)

    logger.debug(
        "Crawled %d pages for root %s (max_pages=%s)",
        len(results),
        start_url,
        max_pages,
    )
    return results
