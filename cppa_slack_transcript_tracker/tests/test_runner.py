"""Tests for cppa_slack_transcript_tracker.runner."""

from unittest.mock import patch, MagicMock

from cppa_slack_transcript_tracker.runner import run_slack_huddle


def test_run_slack_huddle_missing_bot_token_returns_without_starting():
    """run_slack_huddle returns without starting listener when SLACK_BOT_TOKEN is missing."""
    with patch(
        "cppa_slack_transcript_tracker.runner.get_slack_bot_token",
        side_effect=ValueError("no token"),
    ):
        with patch(
            "cppa_slack_transcript_tracker.runner.get_slack_app_token",
            return_value="xapp-t",
        ):
            run_slack_huddle()
    # Should return without raising; listener.start() is never called (no import of start_slack_listener)


def test_run_slack_huddle_missing_app_token_returns_without_starting():
    """run_slack_huddle returns without starting when SLACK_APP_TOKEN is missing."""
    with patch(
        "cppa_slack_transcript_tracker.runner.get_slack_bot_token",
        return_value="xoxb-t",
    ):
        with patch(
            "cppa_slack_transcript_tracker.runner.get_slack_app_token",
            side_effect=ValueError("no app token"),
        ):
            run_slack_huddle()
    # Should return without raising


def test_run_slack_huddle_with_tokens_starts_listener():
    """run_slack_huddle with both tokens calls start_slack_listener (mocked)."""
    with patch("cppa_slack_transcript_tracker.runner.get_workspace_root"):
        with patch("cppa_slack_transcript_tracker.runner.set_working_directory"):
            with patch(
                "cppa_slack_transcript_tracker.runner.get_slack_bot_token",
                return_value="xoxb-t",
            ):
                with patch(
                    "cppa_slack_transcript_tracker.runner.get_slack_app_token",
                    return_value="xapp-t",
                ):
                    with patch(
                        "cppa_slack_transcript_tracker.utils.slack_listener.start_slack_listener",
                        MagicMock(),
                    ) as mock_start:
                        run_slack_huddle()
    mock_start.assert_called_once_with(bot_token="xoxb-t", app_token="xapp-t")


def test_run_slack_huddle_uses_provided_tokens():
    """run_slack_huddle passes provided bot_token and app_token to start_slack_listener."""
    with patch("cppa_slack_transcript_tracker.runner.get_workspace_root"):
        with patch("cppa_slack_transcript_tracker.runner.set_working_directory"):
            with patch(
                "cppa_slack_transcript_tracker.utils.slack_listener.start_slack_listener",
                MagicMock(),
            ) as mock_start:
                run_slack_huddle(bot_token="xoxb-custom", app_token="xapp-custom")
    mock_start.assert_called_once_with(bot_token="xoxb-custom", app_token="xapp-custom")
