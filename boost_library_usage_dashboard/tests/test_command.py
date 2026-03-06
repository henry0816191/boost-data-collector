"""Tests for run_boost_library_usage_dashboard command."""

from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.conf import settings
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_dashboard_command_exists(dashboard_cmd_name):
    commands = get_commands()
    assert dashboard_cmd_name in commands


@pytest.mark.django_db
def test_dashboard_command_runs_generation_only(dashboard_cmd_name, tmp_path):
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {"total_repositories": 0}
    fake_analyzer.report_file = tmp_path / "Boost_Usage_Report_total.md"
    fake_analyzer.stars_min_threshold = 10

    out = StringIO()
    err = StringIO()

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ) as analyzer_cls, patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ) as write_report, patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ) as render_html:
        call_command(
            dashboard_cmd_name,
            "--output-dir",
            str(tmp_path),
            stdout=out,
            stderr=err,
        )

    analyzer_cls.assert_called_once()
    fake_analyzer.run.assert_called_once()
    write_report.assert_called_once_with(
        fake_analyzer.report_file,
        {"total_repositories": 0},
        stars_min_threshold=10,
    )
    expected_output_dir = Path(str(tmp_path)).resolve()
    render_html.assert_called_once_with(
        base_dir=settings.BASE_DIR,
        output_dir=expected_output_dir,
    )


@pytest.mark.django_db
def test_dashboard_command_publish_requires_target_repo(dashboard_cmd_name, tmp_path):
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "Boost_Usage_Report_total.md"
    fake_analyzer.stars_min_threshold = 10

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ):
        with pytest.raises(CommandError, match="--publish requires --target-repo"):
            call_command(
                dashboard_cmd_name,
                "--publish",
                "--output-dir",
                str(tmp_path),
            )


@pytest.mark.django_db
def test_dashboard_command_calls_publish_when_enabled(dashboard_cmd_name, tmp_path):
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "Boost_Usage_Report_total.md"
    fake_analyzer.stars_min_threshold = 10

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.Command._publish"
    ) as publish_mock:
        call_command(
            dashboard_cmd_name,
            "--publish",
            "--target-repo",
            "org/repo",
            "--target-branch",
            "gh-pages",
            "--output-dir",
            str(tmp_path),
        )

    publish_mock.assert_called_once_with(
        output_dir=Path(tmp_path),
        target_repo="org/repo",
        branch="gh-pages",
    )
