"""Tests for boost_mailing_list_tracker.workspace.

Covers paths for messages and raw dirs (workspace/raw/boost_mailing_list_tracker/<list_name>),
edge cases: empty list_name, unsafe msg_id chars, long ids, iterators.
"""

from unittest.mock import patch

import pytest

from boost_mailing_list_tracker.workspace import (
    get_list_dir,
    get_message_json_path,
    get_messages_dir,
    get_raw_dir,
    get_raw_json_path,
    get_workspace_root,
    iter_all_existing_message_jsons,
    iter_all_list_dirs,
    iter_existing_message_jsons,
)


@pytest.fixture
def mock_workspace_path(tmp_path):
    """Patch get_workspace_path so app slug returns tmp_path subdir; creates dirs like real impl."""

    def _get_path(app_slug):
        p = tmp_path / app_slug
        p.mkdir(parents=True, exist_ok=True)
        return p

    with patch(
        "boost_mailing_list_tracker.workspace.get_workspace_path", side_effect=_get_path
    ):
        yield tmp_path


# --- get_workspace_root ---


def test_get_workspace_root_returns_path(mock_workspace_path):
    """get_workspace_root returns Path for app workspace."""
    root = get_workspace_root()
    assert root == mock_workspace_path / "boost_mailing_list_tracker"
    assert "boost_mailing_list_tracker" in str(root)


def test_get_workspace_root_creates_dir(mock_workspace_path):
    """get_workspace_root causes workspace dir to exist (via get_workspace_path)."""
    root = get_workspace_root()
    assert root.is_dir()


# --- get_list_dir ---


def test_get_list_dir_returns_list_subdir(mock_workspace_path):
    """get_list_dir returns workspace/boost_mailing_list_tracker/<list_name>/."""
    path = get_list_dir("boost@lists.boost.org")
    assert (
        path
        == mock_workspace_path / "boost_mailing_list_tracker" / "boost@lists.boost.org"
    )
    assert path.is_dir()


def test_get_list_dir_creates_parents(mock_workspace_path):
    """get_list_dir creates parent directories."""
    path = get_list_dir("boost-users@lists.boost.org")
    assert path.exists()
    assert path.name == "boost-users@lists.boost.org"


def test_get_list_dir_sanitizes_unsafe_list_name(mock_workspace_path):
    """get_list_dir uses _safe_msg_id for list_name (replaces / \\ : * ? etc.)."""
    from boost_mailing_list_tracker.workspace import _safe_msg_id

    path = get_list_dir("list/with:bad*chars")
    safe = _safe_msg_id("list/with:bad*chars")
    assert path.name == safe
    assert "/" not in path.name and ":" not in path.name and "*" not in path.name


# --- get_raw_dir (workspace/raw/boost_mailing_list_tracker/<list_name>) ---


def test_get_raw_dir_returns_raw_app_list_path(mock_workspace_path):
    """get_raw_dir returns workspace/raw/boost_mailing_list_tracker/<list_name>/."""
    path = get_raw_dir("boost@lists.boost.org")
    assert (
        path
        == mock_workspace_path
        / "raw"
        / "boost_mailing_list_tracker"
        / "boost@lists.boost.org"
    )
    assert "raw" in str(path)
    assert "boost_mailing_list_tracker" in str(path)
    assert path.is_dir()


def test_get_raw_dir_creates_parents(mock_workspace_path):
    """get_raw_dir creates raw/boost_mailing_list_tracker/<list_name>."""
    path = get_raw_dir("boost-announce@lists.boost.org")
    assert path.exists()
    assert (mock_workspace_path / "raw" / "boost_mailing_list_tracker").exists()


def test_get_raw_dir_idempotent(mock_workspace_path):
    """get_raw_dir can be called twice without error."""
    p1 = get_raw_dir("boost@lists.boost.org")
    p2 = get_raw_dir("boost@lists.boost.org")
    assert p1 == p2


# --- get_raw_json_path ---


def test_get_raw_json_path_returns_raw_list_msg_json(mock_workspace_path):
    """get_raw_json_path returns .../raw/boost_mailing_list_tracker/<list_name>/<msg_id_safe>.json."""
    path = get_raw_json_path("boost@lists.boost.org", "<msg-123@example.com>")
    assert path.parent == get_raw_dir("boost@lists.boost.org")
    assert path.suffix == ".json"
    assert "raw" in str(path)
    assert "boost_mailing_list_tracker" in str(path)


def test_get_raw_json_path_sanitizes_msg_id(mock_workspace_path):
    """get_raw_json_path uses filesystem-safe filename for msg_id."""
    unsafe_chars = set(r'/\:*?"<>|')
    path = get_raw_json_path("list", "<msg/with\\:bad*chars?")
    assert path.parent.is_dir() or path.parent == get_raw_dir("list")
    assert path.suffix == ".json"
    assert not unsafe_chars.intersection(
        path.stem
    ), f"path.name {path.name!r} should not contain unsafe chars {unsafe_chars}"


# --- get_messages_dir ---


def test_get_messages_dir_returns_messages_subdir(mock_workspace_path):
    """get_messages_dir returns .../boost_mailing_list_tracker/<list_name>/messages/."""
    path = get_messages_dir("boost@lists.boost.org")
    assert (
        path
        == mock_workspace_path
        / "boost_mailing_list_tracker"
        / "boost@lists.boost.org"
        / "messages"
    )
    assert path.is_dir()


# --- get_message_json_path ---


def test_get_message_json_path_returns_messages_msg_json(mock_workspace_path):
    """get_message_json_path returns .../messages/<msg_id_safe>.json."""
    path = get_message_json_path("boost@lists.boost.org", "<abc@example.com>")
    assert path.parent.name == "messages"
    assert path.suffix == ".json"


# --- _safe_msg_id (via get_raw_json_path / get_list_dir behavior) ---


def test_safe_msg_id_empty_returns_unknown():
    """_safe_msg_id('') returns 'unknown' (used in path)."""
    from boost_mailing_list_tracker.workspace import _safe_msg_id

    assert _safe_msg_id("") == "unknown"


def test_safe_msg_id_whitespace_only_returns_unknown_after_strip():
    """_safe_msg_id strips first; whitespace-only becomes empty and returns 'unknown'."""
    from boost_mailing_list_tracker.workspace import _safe_msg_id

    assert _safe_msg_id("   ") == "unknown"


def test_safe_msg_id_replaces_unsafe_chars():
    """_safe_msg_id replaces / \\ : * ? " < > | with underscore."""
    from boost_mailing_list_tracker.workspace import _safe_msg_id

    out = _safe_msg_id("<msg/with\\:bad*chars?>")
    assert "/" not in out
    assert "\\" not in out
    assert ":" not in out
    assert "*" not in out
    assert "?" not in out
    assert '"' not in out
    assert "<" not in out
    assert ">" not in out
    assert "|" not in out


def test_safe_msg_id_truncates_over_200():
    """_safe_msg_id truncates to 200 chars."""
    from boost_mailing_list_tracker.workspace import _safe_msg_id

    long_id = "a" * 250
    out = _safe_msg_id(long_id)
    assert len(out) == 200


# --- iter_existing_message_jsons ---


def test_iter_existing_message_jsons_empty_when_no_dir(mock_workspace_path):
    """iter_existing_message_jsons yields nothing when messages dir does not exist."""
    listed = list(iter_existing_message_jsons("nonexistent-list"))
    assert listed == []


def test_iter_existing_message_jsons_yields_json_files(mock_workspace_path):
    """iter_existing_message_jsons yields Path for each *.json in messages/."""
    messages_dir = (
        mock_workspace_path / "boost_mailing_list_tracker" / "some-list" / "messages"
    )
    messages_dir.mkdir(parents=True)
    (messages_dir / "a.json").write_text("{}")
    (messages_dir / "b.json").write_text("{}")
    paths = list(iter_existing_message_jsons("some-list"))
    assert len(paths) == 2
    assert {p.name for p in paths} == {"a.json", "b.json"}


def test_iter_existing_message_jsons_ignores_non_json(mock_workspace_path):
    """iter_existing_message_jsons only yields *.json files."""
    messages_dir = (
        mock_workspace_path / "boost_mailing_list_tracker" / "list" / "messages"
    )
    messages_dir.mkdir(parents=True)
    (messages_dir / "x.json").write_text("{}")
    (messages_dir / "x.txt").write_text("")
    paths = list(iter_existing_message_jsons("list"))
    assert len(paths) == 1
    assert paths[0].name == "x.json"


# --- iter_all_list_dirs ---


def test_iter_all_list_dirs_empty_when_no_root(mock_workspace_path):
    """iter_all_list_dirs yields nothing when no list subdirs have messages/."""
    # Root exists but no list_name/messages/
    listed = list(iter_all_list_dirs())
    assert listed == []


def test_iter_all_list_dirs_yields_lists_with_messages(mock_workspace_path):
    """iter_all_list_dirs yields (list_name, messages_dir) for each list with messages/."""
    (mock_workspace_path / "boost_mailing_list_tracker" / "list1" / "messages").mkdir(
        parents=True
    )
    (mock_workspace_path / "boost_mailing_list_tracker" / "list2" / "messages").mkdir(
        parents=True
    )
    (
        mock_workspace_path
        / "boost_mailing_list_tracker"
        / "list2"
        / "messages"
        / "1.json"
    ).write_text("{}")
    pairs = list(iter_all_list_dirs())
    assert len(pairs) == 2
    names = {p[0] for p in pairs}
    assert "list1" in names
    assert "list2" in names


# --- iter_all_existing_message_jsons ---


def test_iter_all_existing_message_jsons_yields_list_and_path(mock_workspace_path):
    """iter_all_existing_message_jsons yields (list_name, path) for each message JSON."""
    root = mock_workspace_path / "boost_mailing_list_tracker"
    root.mkdir(parents=True)
    (root / "listA" / "messages").mkdir(parents=True)
    (root / "listA" / "messages" / "m1.json").write_text("{}")
    with patch(
        "boost_mailing_list_tracker.workspace.get_workspace_path", return_value=root
    ):
        items = list(iter_all_existing_message_jsons())
    assert len(items) == 1
    assert items[0][0] == "listA"
    assert items[0][1].name == "m1.json"
