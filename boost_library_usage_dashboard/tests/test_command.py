"""Tests for run_boost_library_usage_dashboard command."""

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

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.get_workspace_path",
        return_value=tmp_path,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ) as analyzer_cls, patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ) as write_report, patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ) as render_html, patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.publish_dashboard"
    ) as publish_mock:
        call_command(dashboard_cmd_name, "--skip-publish")

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
    publish_mock.assert_not_called()


@pytest.mark.django_db
def test_dashboard_command_publish_with_owner_repo_calls_publish_dashboard(
    dashboard_cmd_name, tmp_path
):
    """When owner/repo are set (settings or CLI), publish_dashboard is called."""
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "Boost_Usage_Report_total.md"
    fake_analyzer.stars_min_threshold = 10
    (tmp_path / "index.html").write_text("<html/>")

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.get_workspace_path",
        return_value=tmp_path,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.publish_dashboard"
    ) as publish_mock, patch.object(
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
            "--branch",
            "gh-pages",
        )

    publish_mock.assert_called_once()
    call_kw = publish_mock.call_args[1]
    assert call_kw["owner"] == "myorg"
    assert call_kw["repo"] == "my-repo"
    assert call_kw["branch"] == "gh-pages"
    assert call_kw["output_dir"] == Path(tmp_path).resolve()


@pytest.mark.django_db
def test_dashboard_command_publish_uses_branch_from_settings_when_set(
    dashboard_cmd_name, tmp_path
):
    """When BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH is set, it is used if --branch omitted."""
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "report.md"
    fake_analyzer.stars_min_threshold = 10
    (tmp_path / "index.html").write_text("<html/>")

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.get_workspace_path",
        return_value=tmp_path,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.publish_dashboard"
    ) as publish_mock, patch.object(
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
        call_command(dashboard_cmd_name)

    assert publish_mock.call_args[1]["branch"] == "publish-branch"


@pytest.mark.django_db
def test_dashboard_command_publish_no_owner_repo_skips_publish(
    dashboard_cmd_name, tmp_path
):
    """When owner and repo are missing, publish is skipped (no CommandError)."""
    fake_analyzer = MagicMock()
    fake_analyzer.run.return_value = {}
    fake_analyzer.report_file = tmp_path / "report.md"
    fake_analyzer.stars_min_threshold = 10

    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.get_workspace_path",
        return_value=tmp_path,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
        return_value=fake_analyzer,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.publish_dashboard"
    ) as publish_mock, patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER",
        "",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO",
        "",
    ):
        call_command(dashboard_cmd_name)

    publish_mock.assert_not_called()


@pytest.mark.django_db
def test_dashboard_command_publish_refuses_without_html_artifacts(
    dashboard_cmd_name, tmp_path
):
    """Publish with owner/repo but no *.html under output_dir raises CommandError."""
    with patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.get_workspace_path",
        return_value=tmp_path,
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.BoostUsageDashboardAnalyzer",
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.write_summary_report"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.render_dashboard_html"
    ), patch(
        "boost_library_usage_dashboard.management.commands.run_boost_library_usage_dashboard.publish_dashboard"
    ) as publish_mock, patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER",
        "org",
    ), patch.object(
        settings,
        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO",
        "repo",
    ):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "dashboard_data.json").write_text("{}")
        with pytest.raises(CommandError) as exc_info:
            call_command(
                dashboard_cmd_name,
                "--skip-collect",
                "--skip-render",
            )
        assert "no HTML artifacts" in str(exc_info.value)
        publish_mock.assert_not_called()
