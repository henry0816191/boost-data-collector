import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from boost_library_usage_dashboard.analyzer import BoostUsageDashboardAnalyzer
from boost_library_usage_dashboard.publisher import publish_dashboard
from boost_library_usage_dashboard.renderer import render_dashboard_html
from boost_library_usage_dashboard.report import write_summary_report
from config.workspace import get_workspace_path

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Generate Boost library usage report/dashboard from PostgreSQL data, "
        "then publish generated files to a target GitHub repository unless skipped."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-collect",
            action="store_true",
            help="Skip PostgreSQL collection and Markdown report generation.",
        )
        parser.add_argument(
            "--skip-render",
            action="store_true",
            help="Skip HTML rendering.",
        )
        parser.add_argument(
            "--skip-publish",
            action="store_true",
            help="Skip publishing to the configured GitHub repository.",
        )
        parser.add_argument(
            "--owner",
            type=str,
            default="",
            help="Publish repo owner (overrides BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER).",
        )
        parser.add_argument(
            "--repo",
            type=str,
            default="",
            help="Publish repo name (overrides BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO).",
        )
        parser.add_argument(
            "--branch",
            type=str,
            default="",
            help="Branch to publish to (overrides BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH; default main).",
        )

    def handle(self, *args, **options):
        output_dir = get_workspace_path("boost_library_usage_dashboard").resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        skip_collect = options["skip_collect"]
        skip_render = options["skip_render"]
        skip_publish = options["skip_publish"]

        if not skip_collect:
            logger.info("Step 1: Collecting dashboard data from PostgreSQL...")
            analyzer = BoostUsageDashboardAnalyzer(output_dir=output_dir)
            stats = analyzer.run()

            logger.info("Step 2: Writing Markdown report...")
            write_summary_report(
                analyzer.report_file,
                stats,
                stars_min_threshold=analyzer.stars_min_threshold,
            )

        if not skip_render:
            logger.info("Step 3: Rendering HTML files...")
            render_dashboard_html(base_dir=settings.BASE_DIR, output_dir=output_dir)

        if not skip_collect or not skip_render:
            logger.info("Dashboard artifacts at: %s", output_dir)

        if not skip_publish:
            owner = (options["owner"] or "").strip() or (
                getattr(settings, "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER", "")
                or ""
            ).strip()
            repo = (options["repo"] or "").strip() or (
                getattr(settings, "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO", "")
                or ""
            ).strip()
            branch = (
                (options["branch"] or "").strip()
                or (
                    getattr(
                        settings,
                        "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH",
                        "",
                    )
                    or ""
                ).strip()
                or "main"
            )

            if not owner or not repo:
                logger.warning(
                    "Skipping publish: set BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER "
                    "and BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO in settings, or pass "
                    "--owner and --repo."
                )
            else:
                publish_dashboard(
                    output_dir=output_dir,
                    owner=owner,
                    repo=repo,
                    branch=branch,
                )
