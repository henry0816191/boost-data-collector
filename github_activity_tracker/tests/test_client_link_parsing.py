"""Tests for GitHubAPIClient Link header parsing methods."""

from github_ops.client import GitHubAPIClient


def test_parse_link_rels_parses_all_rels():
    """_parse_link_rels returns dict with all rel→url pairs from Link header."""
    link_header = (
        '<https://api.github.com/repos/o/r/commits?page=2>; rel="next", '
        '<https://api.github.com/repos/o/r/commits?page=50>; rel="last", '
        '<https://api.github.com/repos/o/r/commits?page=1>; rel="first"'
    )
    result = GitHubAPIClient._parse_link_rels(link_header)
    assert result == {
        "next": "https://api.github.com/repos/o/r/commits?page=2",
        "last": "https://api.github.com/repos/o/r/commits?page=50",
        "first": "https://api.github.com/repos/o/r/commits?page=1",
    }


def test_parse_link_rels_handles_prev_rel():
    """_parse_link_rels includes prev rel when present."""
    link_header = (
        '<https://api.github.com/repos/o/r/commits?page=49>; rel="prev", '
        '<https://api.github.com/repos/o/r/commits?page=1>; rel="first"'
    )
    result = GitHubAPIClient._parse_link_rels(link_header)
    assert result == {
        "prev": "https://api.github.com/repos/o/r/commits?page=49",
        "first": "https://api.github.com/repos/o/r/commits?page=1",
    }


def test_parse_link_rels_returns_empty_dict_when_no_header():
    """_parse_link_rels returns empty dict when Link header is None or empty."""
    assert GitHubAPIClient._parse_link_rels(None) == {}
    assert GitHubAPIClient._parse_link_rels("") == {}


def test_parse_link_rels_handles_single_rel():
    """_parse_link_rels works with a single rel in the header."""
    link_header = '<https://api.github.com/repos/o/r/commits?page=2>; rel="next"'
    result = GitHubAPIClient._parse_link_rels(link_header)
    assert result == {"next": "https://api.github.com/repos/o/r/commits?page=2"}


def test_parse_link_rels_handles_github_repository_id_format():
    """_parse_link_rels handles GitHub's /repositories/{id}/commits format."""
    link_header = (
        '<https://api.github.com/repositories/7590028/commits?per_page=100&page=1>; rel="first", '
        '<https://api.github.com/repositories/7590028/commits?per_page=100&page=522>; rel="prev"'
    )
    result = GitHubAPIClient._parse_link_rels(link_header)
    assert result == {
        "first": "https://api.github.com/repositories/7590028/commits?per_page=100&page=1",
        "prev": "https://api.github.com/repositories/7590028/commits?per_page=100&page=522",
    }
