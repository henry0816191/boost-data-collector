"""Tests for boost_usage_tracker.db_from_file."""

import json
from unittest.mock import patch

import pytest

from boost_usage_tracker.db_from_file import (
    get_github_account_dir,
    update_db_from_file,
)
from cppa_user_tracker.models import GitHubAccount


def test_get_github_account_dir_returns_path_under_workspace(tmp_path):
    """get_github_account_dir returns .../boost_usage_tracker/github_account."""
    app_dir = tmp_path / "boost_usage_tracker"
    app_dir.mkdir(parents=True)
    with patch("boost_usage_tracker.db_from_file.get_workspace_path") as m:
        m.return_value = app_dir
        path = get_github_account_dir()
    assert path == app_dir / "github_account"
    assert path.is_dir()
    m.assert_called_once_with("boost_usage_tracker")


@pytest.mark.django_db
def test_update_db_from_file_unsupported_table_returns_errors():
    """update_db_from_file returns errors for unsupported table."""
    result = update_db_from_file(table="unknown_table")
    assert result["table"] == "unknown_table"
    assert result["created"] == 0
    assert result["updated"] == 0
    assert "Unsupported table" in result["errors"][0]


@pytest.mark.django_db
def test_update_db_from_file_github_account_from_dir(tmp_path):
    """update_db_from_file loads JSON from dir and creates/updates GitHubAccount and BaseProfile."""
    (tmp_path / "a.json").write_text(
        json.dumps(
            {
                "github_account_id": 1001,
                "username": "alice",
                "display_name": "Alice",
                "account_type": "user",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "b.json").write_text(
        json.dumps(
            [
                {"github_account_id": 1002, "username": "bob", "account_type": "user"},
                {
                    "github_account_id": 1003,
                    "username": "org1",
                    "account_type": "organization",
                },
            ]
        ),
        encoding="utf-8",
    )
    result = update_db_from_file(source=tmp_path, table="github_account")
    assert result["table"] == "github_account"
    assert result["source_path"] == str(tmp_path)
    assert result["created"] == 3
    assert result["updated"] == 0
    assert GitHubAccount.objects.filter(github_account_id=1001).exists()
    assert GitHubAccount.objects.filter(github_account_id=1002).exists()
    assert GitHubAccount.objects.filter(github_account_id=1003).exists()
    acc1 = GitHubAccount.objects.get(github_account_id=1001)
    assert acc1.username == "alice"
    assert acc1.display_name == "Alice"
    acc3 = GitHubAccount.objects.get(github_account_id=1003)
    assert acc3.account_type == "organization"


@pytest.mark.django_db
def test_update_db_from_file_github_account_from_single_json_file(tmp_path):
    """update_db_from_file accepts a single .json file as source."""
    (tmp_path / "single.json").write_text(
        json.dumps({"github_account_id": 2001, "username": "single"}),
        encoding="utf-8",
    )
    result = update_db_from_file(
        source=tmp_path / "single.json", table="github_account"
    )
    assert result["created"] == 1
    assert GitHubAccount.objects.get(github_account_id=2001).username == "single"


@pytest.mark.django_db
def test_update_db_from_file_github_account_skips_invalid_records(tmp_path):
    """Records missing github_account_id or with invalid id are skipped."""
    (tmp_path / "mixed.json").write_text(
        json.dumps(
            [
                {"github_account_id": 3001, "username": "ok"},
                {"username": "no_id"},
                {"github_account_id": "not_a_number", "username": "bad"},
            ]
        ),
        encoding="utf-8",
    )
    result = update_db_from_file(source=tmp_path, table="github_account")
    assert result["created"] == 1
    assert GitHubAccount.objects.filter(github_account_id=3001).exists()
