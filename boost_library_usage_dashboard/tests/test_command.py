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
def test_dashboard_command_publish_with_owner_repo_calls_publish_via_raw_clone(
    dashboard_cmd_name, tmp_path
):
    """When --publish and settings have owner/repo, _publish_via_raw_clone is called."""
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "Boost_Usage_Report_total.md"
    fake_analyzer.stars_min_threshold = 10
    (tmp_path / "index.html").write_text("<html/>")

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.Command._publish_via_raw_clone"
    ) as publish_raw_mock, patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER",
        "myorg",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO",
        "my-repo",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH",
        "",
    ):
        call_command(
            dashboard_cmd_name,
            "--publish",
            "--target-branch",
            "gh-pages",
            "--output-dir",
            str(tmp_path),
        )

    publish_raw_mock.assert_called_once()
    call_kw = publish_raw_mock.call_args[1]
    assert call_kw["owner"] == "myorg"
    assert call_kw["repo"] == "my-repo"
    assert call_kw["branch"] == "gh-pages"
    assert call_kw["output_dir"] == Path(tmp_path).resolve()


@pytest.mark.django_db
def test_dashboard_command_publish_uses_branch_from_settings_when_set(
    dashboard_cmd_name, tmp_path
):
    """When BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH is set, it is passed to _publish_via_raw_clone."""
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "report.md"
    fake_analyzer.stars_min_threshold = 10

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.Command._publish_via_raw_clone"
    ) as publish_raw_mock, patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER",
        "org",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO",
        "repo",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH",
        "publish-branch",
    ):
        call_command(
            dashboard_cmd_name,
            "--publish",
            "--target-branch",
            "main",
            "--output-dir",
            str(tmp_path),
        )

    assert publish_raw_mock.call_args[1]["branch"] == "publish-branch"


@pytest.mark.django_db
def test_dashboard_command_publish_no_owner_repo_raises_command_error(
    dashboard_cmd_name, tmp_path
):
    """When --publish but owner or repo missing in settings, CommandError is raised."""
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "report.md"
    fake_analyzer.stars_min_threshold = 10

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.Command._publish_via_raw_clone"
    ) as publish_raw_mock, patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER",
        "",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO",
        "",
    ):
        with pytest.raises(CommandError) as exc_info:
            call_command(
                dashboard_cmd_name,
                "--publish",
                "--output-dir",
                str(tmp_path),
            )
        assert "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH" in str(exc_info.value)
        publish_raw_mock.assert_not_called()
