"""Tests for cppa_slack_tracker.sync.sync_message helpers and sync_messages flow."""

import pytest
from datetime import date
from unittest.mock import patch

from cppa_slack_tracker.sync.sync_message import (
    _merge_messages_by_ts,
    _messages_by_day,
    _ts_to_date,
)


class TestTsToDate:
    """Tests for _ts_to_date."""

    def test_valid_ts_returns_utc_date(self):
        # 2021-01-01 00:00:00 UTC
        assert _ts_to_date("1609459200") == date(2021, 1, 1)
        assert _ts_to_date("1609459200.123456") == date(2021, 1, 1)

    def test_none_or_empty_returns_none(self):
        assert _ts_to_date(None) is None
        assert _ts_to_date("") is None

    def test_invalid_ts_returns_none(self):
        assert _ts_to_date("not-a-number") is None
        assert _ts_to_date("  ") is None


class TestMessagesByDay:
    """Tests for _messages_by_day."""

    def test_empty_messages_returns_empty_dict(self):
        result = _messages_by_day([], date(2026, 1, 1), date(2026, 1, 5))
        assert result == {}

    def test_message_on_single_day_appears_once(self):
        messages = [
            {"ts": "1735689600", "text": "hi"},  # 2025-01-01 UTC
        ]
        start = date(2025, 1, 1)
        end = date(2025, 1, 5)
        result = _messages_by_day(messages, start, end)
        assert len(result) == 1
        assert date(2025, 1, 1) in result
        assert len(result[date(2025, 1, 1)]) == 1
        assert result[date(2025, 1, 1)][0]["text"] == "hi"

    def test_message_created_and_edited_different_days_appears_twice(self):
        # Created 2025-01-01, edited 2025-01-03 (edited_ts = 2025-01-03 00:00 UTC)
        messages = [
            {
                "ts": "1735689600",  # 2025-01-01 00:00 UTC
                "text": "original",
                "edited": {"ts": "1735862400"},  # 2025-01-03 00:00 UTC
            },
        ]
        start = date(2025, 1, 1)
        end = date(2025, 1, 5)
        result = _messages_by_day(messages, start, end)
        assert date(2025, 1, 1) in result
        assert date(2025, 1, 3) in result
        assert len(result[date(2025, 1, 1)]) == 1
        assert len(result[date(2025, 1, 3)]) == 1
        assert result[date(2025, 1, 1)][0] is result[date(2025, 1, 3)][0]

    def test_message_outside_range_excluded(self):
        messages = [
            {"ts": "1735689600", "text": "hi"},  # 2025-01-01
        ]
        start = date(2025, 1, 5)
        end = date(2025, 1, 10)
        result = _messages_by_day(messages, start, end)
        assert result == {}

    def test_message_with_invalid_ts_skipped(self):
        messages = [
            {"ts": "invalid", "text": "skip"},
            {"ts": "1735689600", "text": "ok"},
        ]
        start = date(2025, 1, 1)
        end = date(2025, 1, 5)
        result = _messages_by_day(messages, start, end)
        assert date(2025, 1, 1) in result
        assert len(result[date(2025, 1, 1)]) == 1
        assert result[date(2025, 1, 1)][0]["text"] == "ok"


class TestMergeMessagesByTs:
    """Tests for _merge_messages_by_ts (same ts → update, new ts → add)."""

    def test_empty_both_returns_empty(self):
        assert _merge_messages_by_ts([], []) == []

    def test_new_only_returns_new_sorted_by_ts(self):
        new = [{"ts": "1735862400", "text": "b"}, {"ts": "1735689600", "text": "a"}]
        result = _merge_messages_by_ts([], new)
        assert len(result) == 2
        assert result[0]["ts"] == "1735689600"
        assert result[0]["text"] == "a"
        assert result[1]["ts"] == "1735862400"
        assert result[1]["text"] == "b"

    def test_same_ts_updates(self):
        existing = [{"ts": "1735689600", "text": "old"}]
        new = [{"ts": "1735689600", "text": "updated"}]
        result = _merge_messages_by_ts(existing, new)
        assert len(result) == 1
        assert result[0]["text"] == "updated"

    def test_new_ts_adds(self):
        existing = [{"ts": "1735689600", "text": "first"}]
        new = [{"ts": "1735862400", "text": "second"}]
        result = _merge_messages_by_ts(existing, new)
        assert len(result) == 2
        by_ts = {m["ts"]: m for m in result}
        assert by_ts["1735689600"]["text"] == "first"
        assert by_ts["1735862400"]["text"] == "second"

    def test_mix_update_and_add(self):
        existing = [
            {"ts": "1735689600", "text": "a"},
            {"ts": "1735776000", "text": "b"},
        ]
        new = [
            {"ts": "1735776000", "text": "b_updated"},
            {"ts": "1735862400", "text": "c"},
        ]
        result = _merge_messages_by_ts(existing, new)
        assert len(result) == 3
        by_ts = {m["ts"]: m for m in result}
        assert by_ts["1735689600"]["text"] == "a"
        assert by_ts["1735776000"]["text"] == "b_updated"
        assert by_ts["1735862400"]["text"] == "c"

    def test_message_without_ts_skipped(self):
        existing = [{"ts": "1735689600", "text": "ok"}]
        new = [{"text": "no_ts"}]
        result = _merge_messages_by_ts(existing, new)
        assert len(result) == 1
        assert result[0]["text"] == "ok"


@pytest.mark.django_db
class TestSyncMessages:
    """Tests for sync_messages (with mocked fetch)."""

    def test_sync_messages_skips_days_with_zero_messages(
        self, sample_slack_channel, tmp_path
    ):
        """When fetch returns no messages, no JSON files are created."""
        from cppa_slack_tracker.sync.sync_message import sync_messages
        from cppa_slack_tracker.workspace import (
            get_message_json_path,
            get_raw_message_json_path,
        )

        start = date(2026, 1, 1)
        end = date(2026, 1, 3)
        team_slug = sample_slack_channel.team.team_name
        channel_slug = sample_slack_channel.channel_name

        app_workspace = tmp_path / "workspace" / "cppa_slack_tracker"
        app_workspace.mkdir(parents=True, exist_ok=True)
        with patch(
            "cppa_slack_tracker.workspace.get_workspace_path",
            return_value=app_workspace,
        ), patch("cppa_slack_tracker.workspace.settings") as m_settings, patch(
            "cppa_slack_tracker.sync.sync_message.fetch_messages",
            return_value=[],
        ):
            m_settings.WORKSPACE_DIR = tmp_path / "workspace"
            m_settings.RAW_DIR = None
            sync_messages(sample_slack_channel, start_date=start, end_date=end)
            for d in [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]:
                date_str = d.strftime("%Y-%m-%d")
                wp = get_message_json_path(team_slug, channel_slug, date_str)
                rp = get_raw_message_json_path(team_slug, channel_slug, date_str)
                assert not wp.exists(), f"Workspace file should not exist: {wp}"
                assert not rp.exists(), f"Raw file should not exist: {rp}"
