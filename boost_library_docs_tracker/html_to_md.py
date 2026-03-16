"""
HTML → Markdown conversion for Boost DocBook/BoostBook documentation.

Public API
----------
convert_html_to_markdown(html: str) -> str

Pipeline
--------
1. _preprocess_html   – remove Boost boilerplate from HTML before pandoc sees it
2. _pandoc_convert    – HTML → GFM via pypandoc (CLI fallback)
3. _postprocess_markdown – strip residual HTML artefacts and rejoin split lines
"""

import re
import subprocess

from bs4 import BeautifulSoup

try:
    import pypandoc
except Exception:  # optional runtime dependency
    pypandoc = None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def convert_html_to_markdown(html: str) -> str:
    """
    Convert an HTML string to clean GitHub-flavoured Markdown.

    Pipeline:
      1. Pre-process: strip Boost boilerplate from HTML before pandoc sees it
      2. Pandoc: HTML → GFM (via pypandoc, CLI fallback)
      3. Post-process: strip remaining HTML tags and artefacts from the output
    """
    html = _preprocess_html(html)
    md = _pandoc_convert(html)
    md = _postprocess_markdown(md)
    return md


# ---------------------------------------------------------------------------
# Pre-processing (HTML level — before pandoc)
# ---------------------------------------------------------------------------

_BS_REMOVE_TAGS = ["script", "style", "noscript"]
# CSS classes whose entire containing block carries no meaningful text content
_BS_REMOVE_CLASSES = [
    "spirit-nav",  # prev/next navigation arrows
    "copyright-footer",  # copyright boilerplate
]


def _preprocess_html(html: str) -> str:
    """Strip Boost-specific boilerplate and flatten inline code spans."""
    soup = BeautifulSoup(html, "lxml")

    # Remove <script>, <style>, <noscript>
    for tag in soup(_BS_REMOVE_TAGS):
        tag.decompose()

    # Remove nav/footer divs by class
    for cls in _BS_REMOVE_CLASSES:
        for tag in soup.find_all(class_=cls):
            tag.decompose()

    # Remove the top Boost navigation table: first <table> whose first row
    # contains an <img> with "boost" in the src (the logo + nav links row).
    for table in soup.find_all("table"):
        img = table.find("img")
        if img and "boost" in (img.get("src") or "").lower():
            table.decompose()
            break  # only remove the first matching table

    # Flatten Boost DocBook inline code: each identifier/operator token is wrapped
    # in its own <span class="identifier|special|keyword|…"> inside a <code>.
    # Pandoc emits each span as a separate backtick span joined with backticks,
    # producing `boost``::``mem_fn` instead of `boost::mem_fn`.
    # Fix: replace each <code> with a plain <code> containing just the concatenated text.
    for code in soup.find_all("code"):
        text = code.get_text()
        code.clear()
        code.append(text)

    return str(soup)


# ---------------------------------------------------------------------------
# Pandoc conversion (pypandoc primary, CLI fallback)
# ---------------------------------------------------------------------------


def _pandoc_convert(html: str) -> str:
    """Run pandoc HTML → GFM.  Tries pypandoc first, then raw CLI."""
    if pypandoc is not None:
        for fmt in ("gfm+pipe_tables", "gfm"):
            try:
                return pypandoc.convert_text(html, to=fmt, format="html")
            except RuntimeError:
                continue  # unsupported extension, try simpler format
            except OSError:
                # binary missing — let CLI path handle it
                break

    # CLI fallback
    for fmt in ("gfm+pipe_tables", "gfm"):
        try:
            proc = subprocess.run(
                ["pandoc", "--from=html", f"--to={fmt}"],
                input=html,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                return proc.stdout
        except FileNotFoundError:
            break

    raise RuntimeError(
        "pandoc is not available. Install it with `brew install pandoc` "
        "or `pip install pypandoc` followed by `pypandoc.download_pandoc()`."
    )


# ---------------------------------------------------------------------------
# Post-processing (Markdown level — after pandoc)
# ---------------------------------------------------------------------------

# Boost BoostBook nav table leftover: any pipe-table whose only data row still
# contains a Home/Libraries/People/FAQ nav pattern (edge case for pre-converted files).
_RE_NAV_TABLE = re.compile(
    r"\|[^\n]*\|\s*\n"  # header row
    r"\|[-: |]+\|\s*\n"  # separator row
    r"\|[^\n]*(Home|Libraries)[^\n]*\|\s*\n",  # data row with Boost nav links
    re.MULTILINE,
)

# Standalone horizontal rule line (full line of dashes/underscores/asterisks)
_RE_HR = re.compile(r"^[-*_]{3,}\s*$", re.MULTILINE)

# Residual <div …> / </div> lines (entire line is just a div tag)
_RE_DIV_LINE = re.compile(r"^\s*</?div[^>]*>\s*$", re.MULTILINE)

# <span id="...">…</span>  — anchors: keep inner text only
_RE_SPAN_ID = re.compile(r'<span\s+id="[^"]*"[^>]*>(.*?)</span>', re.DOTALL)

# <span class="special|identifier|keyword|type|emphasis|…">…</span>
# Unwrap, keep inner content.
_RE_SPAN_CLASS = re.compile(r'<span\s+class="[^"]*"[^>]*>(.*?)</span>', re.DOTALL)

# Generic remaining HTML tags in prose (not Markdown-meaningful).
# Must NOT be applied inside code fences — template parameters like <class T>
# look identical to HTML tags.
_RE_HTML_TAG = re.compile(r"<[^>]+>")

# Code fence with spurious language name from DocBook 'programlisting' class
# e.g.  ``` programlisting  →  ```  or  ~~~ programlisting  →  ~~~
_RE_BAD_FENCE = re.compile(r"^([`~]{3,}) *programlisting\s*$", re.MULTILINE)

# Three or more consecutive blank lines → exactly two
_RE_EXCESS_BLANK = re.compile(r"\n{3,}")

# Trailing whitespace on every line
_RE_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)

# Fenced code block: opening fence (``` or ~~~, optional lang), body, closing fence (same char/length)
_RE_FENCED_BLOCK = re.compile(
    r"(?:^|\n)(((?P<fence>[`~]{3,})[^\n]*\n.*?\n(?P=fence)))", re.DOTALL
)

# Inline code span (backtick-delimited, no newlines)
_RE_INLINE_CODE = re.compile(r"`[^`\n]+`")

# Lines that must never be joined to the previous line
_RE_BLOCK_START = re.compile(
    r"^(?:"
    r"#{1,6}\s"  # ATX heading
    r"|[*\-+]\s"  # unordered list item
    r"|\d+\.\s"  # ordered list item
    r"|>"  # blockquote
    r"|[`~]{3,}"  # fenced code fence (backticks or tildes)
    r"|\|"  # table row
    r"|$"  # blank line
    r")"
)


def _strip_html_tags_in_prose(md: str) -> str:
    """Strip HTML tags from prose only, leaving fenced and inline code intact."""
    parts = _RE_FENCED_BLOCK.split(md)
    result = []
    for part in parts:
        # Full block has newline; split() also returns the fence-only group
        if re.match(r"^[`~]{3,}", part) and "\n" in part:
            result.append(part)
        else:
            # Prose section — strip HTML tags but protect inline code spans
            segments = _RE_INLINE_CODE.split(part)
            inline_codes = _RE_INLINE_CODE.findall(part)
            cleaned_segments = [_RE_HTML_TAG.sub("", seg) for seg in segments]
            rebuilt = ""
            for i, seg in enumerate(cleaned_segments):
                rebuilt += seg
                if i < len(inline_codes):
                    rebuilt += inline_codes[i]
            result.append(rebuilt)
    return "".join(result)


def _join_wrapped_lines(md: str) -> str:
    """
    Join soft-wrapped prose lines that result from per-span line breaks in DocBook HTML.
    Lines inside fenced code blocks are left untouched.
    A line is joined to the previous one when:
    - neither is blank
    - the current line is not a block-level start (list item, fence, table, blank)
    - the previous line is either plain prose OR a heading (headings can have
      their text wrapped onto the next line by pandoc)
    """
    out_lines: list[str] = []
    in_fence = False

    for line in md.splitlines():
        if re.match(r"^[`~]{3,}", line):
            in_fence = not in_fence
            out_lines.append(line)
            continue

        if in_fence:
            out_lines.append(line)
            continue

        prev = out_lines[-1] if out_lines else ""
        prev_is_heading = bool(re.match(r"^#{1,6}\s", prev))
        current_is_block = bool(_RE_BLOCK_START.match(line))

        if (
            prev
            and line
            and not current_is_block
            and (not _RE_BLOCK_START.match(prev) or prev_is_heading)
        ):
            out_lines[-1] = prev + " " + line
        else:
            out_lines.append(line)

    return "\n".join(out_lines)


def _postprocess_markdown(md: str) -> str:
    # 1. Remove any leftover Boost nav table
    md = _RE_NAV_TABLE.sub("", md)

    # 2. Remove standalone horizontal rules (used as section separators in boilerplate)
    md = _RE_HR.sub("", md)

    # 3. Remove spirit-nav div blocks (next/prev arrows — no textual content)
    md = re.sub(
        r'<div class="spirit-nav">.*?</div>',
        "",
        md,
        flags=re.DOTALL,
    )

    # 4. Remove copyright-footer div blocks
    md = re.sub(
        r'<div class="copyright-footer">.*?</div>',
        "",
        md,
        flags=re.DOTALL,
    )

    # 5. Unwrap <span id="…"> anchors — keep inner text only
    md = _RE_SPAN_ID.sub(lambda m: m.group(1), md)

    # 6. Unwrap semantic <span class="…"> — keep inner text
    md = _RE_SPAN_CLASS.sub(lambda m: m.group(1), md)

    # 7. Strip bare <div> / </div> lines
    md = _RE_DIV_LINE.sub("", md)

    # 8. Strip remaining HTML tags from prose only (code blocks are protected)
    md = _strip_html_tags_in_prose(md)

    # 9. Fix spurious code fence language name from DocBook programlisting
    md = _RE_BAD_FENCE.sub(r"\1", md)

    # 10. Join soft-wrapped prose lines
    md = _join_wrapped_lines(md)

    # 11. Trim trailing whitespace per line
    md = _RE_TRAILING_WS.sub("", md)

    # 12. Collapse excessive blank lines to at most two
    md = _RE_EXCESS_BLANK.sub("\n\n", md)

    return md.strip() + "\n"
