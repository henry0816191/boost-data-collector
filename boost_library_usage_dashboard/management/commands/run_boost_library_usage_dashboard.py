import logging
import shutil
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from boost_library_usage_dashboard.analyzer import BoostUsageDashboardAnalyzer
from boost_library_usage_dashboard.renderer import render_dashboard_html
from boost_library_usage_dashboard.report import write_summary_report
from config.workspace import get_workspace_path
from github_ops.git_ops import clone_repo, push

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
            help="Publish generated files to --target-repo.",
        )
        parser.add_argument(
            "--target-repo",
            type=str,
            default="",
            help="Target repository slug or URL for dashboard artifacts (e.g. org/repo).",
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
            target_repo = (options["target_repo"] or "").strip()
            if not target_repo:
                raise CommandError("--publish requires --target-repo")
            self._publish(
                output_dir=output_dir,
                target_repo=target_repo,
                branch=options["target_branch"],
            )

    def _publish(self, output_dir: Path, target_repo: str, branch: str) -> None:
        self.stdout.write(
            f"Publishing dashboard artifacts to {target_repo} ({branch})..."
        )
        publish_root = (
            get_workspace_path("shared") / "boost_library_usage_dashboard_publish"
        )
        if publish_root.exists():
            shutil.rmtree(publish_root)
        clone_repo(target_repo, publish_root)

        subprocess.run(["git", "-C", str(publish_root), "checkout", branch], check=True)

        # Replace repository contents with generated artifacts.
        for child in publish_root.iterdir():
            if child.name == ".git":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

        for child in output_dir.iterdir():
            dest = publish_root / child.name
            if child.is_dir():
                shutil.copytree(child, dest)
            else:
                shutil.copy2(child, dest)

        subprocess.run(["git", "-C", str(publish_root), "add", "."], check=True)
        status = subprocess.run(
            ["git", "-C", str(publish_root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        if not status.stdout.strip():
            self.stdout.write("No dashboard changes to publish.")
            return

        commit_message = "Update Boost library usage dashboard artifacts"
        subprocess.run(
            ["git", "-C", str(publish_root), "commit", "-m", commit_message],
            check=True,
        )
        push(publish_root, branch=branch)
        self.stdout.write(
            self.style.SUCCESS("Dashboard artifacts published successfully.")
        )
