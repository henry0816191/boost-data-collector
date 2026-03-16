import logging
import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from boost_library_usage_dashboard.analyzer import BoostUsageDashboardAnalyzer
from boost_library_usage_dashboard.renderer import render_dashboard_html
from boost_library_usage_dashboard.report import write_summary_report
from config.workspace import get_workspace_path
from github_ops.git_ops import clone_repo, pull, push

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Generate Boost library usage report/dashboard from PostgreSQL data, "
        "then optionally publish generated files to a target GitHub repository."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--publish",
            action="store_true",
            help="Publish generated files to the repository configured in settings.",
        )
        parser.add_argument(
            "--target-branch",
            type=str,
            default="main",
            help="Branch for pushing generated dashboard files.",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default="",
            help="Custom output directory. Defaults to workspace/boost_library_usage_dashboard.",
        )

    def handle(self, *args, **options):
        output_dir = (
            Path(options["output_dir"]).resolve()
            if options["output_dir"]
            else get_workspace_path("boost_library_usage_dashboard")
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        self.stdout.write("Step 1: Collecting dashboard data from PostgreSQL...")
        analyzer = BoostUsageDashboardAnalyzer(
            base_dir=settings.BASE_DIR, output_dir=output_dir
        )
        stats = analyzer.run()

        self.stdout.write("Step 2: Writing Markdown report...")
        write_summary_report(
            analyzer.report_file,
            stats,
            stars_min_threshold=analyzer.stars_min_threshold,
        )

        self.stdout.write("Step 3: Rendering HTML files...")
        render_dashboard_html(base_dir=settings.BASE_DIR, output_dir=output_dir)

        self.stdout.write(
            self.style.SUCCESS(f"Dashboard artifacts generated at: {output_dir}")
        )

        if options["publish"]:
            owner = (
                getattr(settings, "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER", "")
                or ""
            ).strip()
            repo = (
                getattr(settings, "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO", "")
                or ""
            ).strip()
            branch = (
                getattr(
                    settings,
                    "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_BRANCH",
                    "",
                )
                or ""
            ).strip() or options["target_branch"]
            if owner and repo:
                self._publish_via_raw_clone(
                    output_dir=output_dir,
                    owner=owner,
                    repo=repo,
                    branch=branch,
                )
            else:
                raise CommandError(
                    "Cannot publish: BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_OWNER "
                    "and BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_REPO must be set in settings."
                )

    def _publish_via_raw_clone(
        self,
        output_dir: Path,
        owner: str,
        repo: str,
        branch: str,
    ) -> None:
        """
        Publish using persistent clone at raw/boost_library_usage_dashboard/owner/repo.
        Clone if missing, pull, remove contents, copy output_dir, add/commit/push.
        """
        clone_dir = (
            Path(settings.RAW_DIR) / "boost_library_usage_dashboard" / owner / repo
        )
        clone_dir = clone_dir.resolve()
        output_dir = output_dir.resolve()
        if (
            clone_dir == output_dir
            or clone_dir in output_dir.parents
            or output_dir in clone_dir.parents
        ):
            raise CommandError(
                "--output-dir must not overlap with the publish clone path: "
                f"{clone_dir}"
            )
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        token = (
            getattr(settings, "BOOST_LIBRARY_USAGE_DASHBOARD_PUBLISH_TOKEN", None)
            or None
        )
        repo_slug = f"{owner}/{repo}"
        self.stdout.write(
            f"Publishing dashboard artifacts to {repo_slug} ({branch})..."
        )
        if not clone_dir.exists() or not (clone_dir / ".git").is_dir():
            if clone_dir.exists():
                shutil.rmtree(clone_dir)
            self.stdout.write(f"Cloning {repo_slug} to {clone_dir}...")
            clone_repo(repo_slug, clone_dir, token=token)
        self.stdout.write("Pulling latest...")
        pull(clone_dir, branch=branch, token=token)
        for child in clone_dir.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir() and child.name == "develop":
                shutil.rmtree(child)
        publish_subdir = clone_dir / "develop"
        publish_subdir.mkdir(parents=True, exist_ok=True)
        for child in output_dir.iterdir():
            dest = publish_subdir / child.name
            if child.is_dir():
                shutil.copytree(child, dest)
            else:
                if child.suffix != ".html":
                    continue
                shutil.copy2(child, dest)
        tz_name = getattr(settings, "CELERY_TIMEZONE", None) or settings.TIME_ZONE
        commit_time = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S")
        commit_message = (
            f"Update Boost library usage dashboard artifacts ({commit_time})"
        )
        push(
            clone_dir,
            remote="origin",
            branch=branch,
            commit_message=commit_message,
            token=token,
        )
        self.stdout.write(
            self.style.SUCCESS("Dashboard artifacts published successfully.")
        )
