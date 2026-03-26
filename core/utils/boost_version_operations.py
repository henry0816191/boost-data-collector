"""
Boost release version helpers: macro packing, strict parse for Pinecone keys,
loose parse for sorting messy strings, normalization, and comparisons.

**Strict (``BOOST_VERSION`` macro / Pinecone metadata keys)** — numeric packing::

    major * 100_000 + minor * 100 + patch

Requires ``minor <= 999`` and ``patch <= 99`` for collision-free encoding.
Use :func:`parse_boost_version_string` and :func:`encode_boost_version_string`.

**Loose (sorting / analytics)** — digit runs per dot-separated segment; empty
input → ``(0, 0, 0)``. Handles strings like ``release-2.1.9-extra``. Use
:func:`loose_version_tuple` / :func:`compare_loose_version_strings`.

**GitHub stable tags** — exact ``boost-X.Y.Z`` (no ``-beta`` / ``-rc`` suffix).
Use :func:`parse_stable_boost_release_tag` with a caller-supplied minimum tuple.
"""

from __future__ import annotations

import re

# --- Macro packing (BOOST_VERSION / version.hpp) --------------------------------

MAJOR_MULTIPLIER = 100_000
MINOR_MULTIPLIER = 100

_MAX_MINOR = 999
_MAX_PATCH = 99

_VERSION_STRIP_PREFIX = re.compile(r"^boost[-_]", re.IGNORECASE)


def encode_boost_version(major: int, minor: int, patch: int) -> int:
    """Return the packed integer (``major * 100_000 + minor * 100 + patch``)."""
    if major < 0 or minor < 0 or patch < 0:
        raise ValueError(
            f"Version components must be non-negative, got {major}.{minor}.{patch}"
        )
    if minor > _MAX_MINOR or patch > _MAX_PATCH:
        raise ValueError(
            f"Encoding requires minor <= {_MAX_MINOR} and patch <= {_MAX_PATCH} "
            f"(got {major}.{minor}.{patch})"
        )
    return major * MAJOR_MULTIPLIER + minor * MINOR_MULTIPLIER + patch


def decode_boost_version(encoded: int) -> tuple[int, int, int]:
    """Split a packed ``BOOST_VERSION``-style integer into (major, minor, patch)."""
    if encoded < 0:
        raise ValueError(f"encoded version must be non-negative, got {encoded}")
    major = encoded // MAJOR_MULTIPLIER
    minor = (encoded // MINOR_MULTIPLIER) % 1000
    patch = encoded % MINOR_MULTIPLIER
    return major, minor, patch


def parse_boost_version_string(version_str: str) -> tuple[int, int, int] | None:
    """
    Parse ``1.86.0``, ``boost-1.86.0``, or ``1_86_0`` into (major, minor, patch).

    Missing minor/patch segments default to 0. Returns None if unparseable or
    out of encodable range.
    """
    if not version_str or not str(version_str).strip():
        return None
    s = _VERSION_STRIP_PREFIX.sub("", str(version_str).strip())
    s = s.replace("_", ".")
    parts = s.split(".")
    if not parts or not parts[0].strip():
        return None
    try:
        major = int(parts[0].strip())
        minor = int(parts[1].strip()) if len(parts) > 1 else 0
        patch = int(parts[2].strip()) if len(parts) > 2 else 0
    except ValueError:
        return None
    if minor > _MAX_MINOR or patch > _MAX_PATCH:
        return None
    if major < 0 or minor < 0 or patch < 0:
        return None
    return major, minor, patch


def encode_boost_version_string(version_str: str) -> int | None:
    """Parse *version_str* and return the packed int, or None if invalid."""
    triple = parse_boost_version_string(version_str)
    if triple is None:
        return None
    major, minor, patch = triple
    try:
        return encode_boost_version(major, minor, patch)
    except ValueError:
        return None


# --- Loose tuple (sorting / dirty strings) ------------------------------------


def loose_version_tuple(version: str) -> tuple[int, int, int]:
    """
    Parse *version* to (major, minor, patch) for sorting.

    Each segment uses the longest digit run only (e.g. ``1.82.x`` → ``(1, 82, 0)``).
    Empty string → ``(0, 0, 0)``.
    """
    if not version:
        return (0, 0, 0)
    parts = version.strip().split(".")
    out: list[int] = []
    for part in parts[:3]:
        number = "".join(c for c in part if c.isdigit())
        out.append(int(number) if number else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


# --- Normalization ------------------------------------------------------------


def normalize_boost_version_string(version_str: str) -> str | None:
    """
    Normalize a version string for comparison; returns None if invalid or pre-1.0.

    Strips ``boost-`` prefix, maps ``-`` / ``_`` to ``.``, appends ``.0`` when
    only two segments are present.
    """
    version = (version_str or "").strip().replace("boost-", "")
    version = version.replace("-", ".").replace("_", ".")
    if not version or version.startswith("0."):
        return None
    if len(version.split(".")) == 2:
        version = f"{version}.0"
    return version


# --- Comparison ---------------------------------------------------------------


def compare_boost_version_tuples(
    a: tuple[int, int, int], b: tuple[int, int, int]
) -> int:
    """Return -1 if a < b, 0 if equal, 1 if a > b."""
    if a < b:
        return -1
    if a > b:
        return 1
    return 0


def compare_loose_version_strings(left: str, right: str) -> int:
    """Compare two version strings using :func:`loose_version_tuple`."""
    return compare_boost_version_tuples(
        loose_version_tuple(left), loose_version_tuple(right)
    )


def compare_encoded_versions(i: int, j: int) -> int:
    """
    Compare two packed ints from :func:`encode_boost_version`.

    Do not use for arbitrary integers that were not produced by that encoding.
    """
    if i < j:
        return -1
    if i > j:
        return 1
    return 0


# --- GitHub stable release tags (boostorg/boost) --------------------------------

BOOST_STABLE_RELEASE_TAG_PATTERN = re.compile(r"^boost-(\d+)\.(\d+)\.(\d+)$")


def parse_stable_boost_release_tag(
    tag_name: str,
    min_version: tuple[int, int, int],
) -> str | None:
    """
    If *tag_name* matches ``boost-X.Y.Z`` (three numeric parts only) and the
    version is >= *min_version*, return the canonical tag (e.g. ``boost-1.90.0``).

    Returns ``None`` for empty names, non-matching patterns, or versions below
    *min_version*.
    """
    if not tag_name:
        return None
    m = BOOST_STABLE_RELEASE_TAG_PATTERN.match(tag_name.strip())
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if compare_boost_version_tuples((major, minor, patch), min_version) == -1:
        return None
    return f"boost-{major}.{minor}.{patch}"
