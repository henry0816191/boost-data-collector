"""
Management command: run_update_db

Load data from JSON or CSV and update a chosen target (table/workflow).
One entry point; use --target to select which update to run.

Examples:
  python manage.py run_update_db --target github_account
  python manage.py run_update_db --target github_account --source /path/to/dir
  python manage.py run_update_db --target repository --source /path/to/add_to_boostExternalRepository.csv
  python manage.py run_update_db --target githubfile
  python manage.py run_update_db --target boostusage
"""

from django.core.management.base import BaseCommand, CommandError


# Registry: target -> (runner_fn, formatter_fn).
# runner_fn(source) -> dict with at least "errors" (optional list) and target-specific keys.
# formatter_fn(result) -> one-line success string.
def _format_github_account(result):
    return (
        f"table={result['table']} source={result['source_path']} "
        f"created={result['created']} updated={result['updated']}"
    )


def _format_repository(result):
    return (
        f"source={result['source_path']} "
        f"repos: created={result['created_repos']} updated={result['updated_repos']} "
        f"ext: created={result['created_ext']} updated={result['updated_ext']} "
        f"skipped_no_owner={result['skipped_no_owner']}"
    )


def _format_githubfile(result):
    return (
        f"source={result['source_path']} "
        f"created={result['created']} updated={result['updated']} "
        f"skipped_no_repo={result['skipped_no_repo']}"
    )


def _format_boostusage(result):
    return (
        f"source={result['source_path']} "
        f"created={result['created']} updated={result['updated']} "
        f"skipped_no_repo={result['skipped_no_repo']} "
        f"skipped_no_file={result['skipped_no_file']} "
        f"skipped_no_boost_header={result['skipped_no_boost_header']}"
    )


def _run_github_account(source):
    from boost_usage_tracker.update_git_account import update_git_account

    return update_git_account(source=source, table="github_account")


def _run_repository(source):
    from boost_usage_tracker.update_repository_from_csv import (
        update_repository_table_from_csv,
    )

    return update_repository_table_from_csv(source=source)


def _run_githubfile(source):
    from boost_usage_tracker.update_githubfile_from_csv import (
        update_githubfile_table_from_csv,
    )

    return update_githubfile_table_from_csv(source=source)


def _run_boostusage(source):
    from boost_usage_tracker.update_boostusage_from_csv import (
        update_boostusage_table_from_csv,
    )

    return update_boostusage_table_from_csv(source=source)


TARGETS = {
    "github_account": (
        _run_github_account,
        _format_github_account,
        "JSON in workspace/boost_usage_tracker/github_account → GitHubAccount, BaseProfile",
    ),
    "repository": (
        _run_repository,
        _format_repository,
        "add_to_boostExternalRepository.csv → GitHubRepository, BoostExternalRepository",
    ),
    "githubfile": (
        _run_githubfile,
        _format_githubfile,
        "add_to_githubFile.csv → GitHubFile",
    ),
    "boostusage": (
        _run_boostusage,
        _format_boostusage,
        "add_to_boostUsage.csv → BoostUsage",
    ),
}


class Command(BaseCommand):
    help = (
        "Load JSON/CSV from workspace (or --source) and update the chosen target. "
        "Use --target to select: github_account, repository, githubfile, boostusage."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--target",
            choices=list(TARGETS),
            required=True,
            help="Which update to run. Choices: %(choices)s.",
        )
        parser.add_argument(
            "--source",
            default=None,
            help="Path to file or directory. Default per target (e.g. workspace dir or default CSV).",
        )

    def handle(self, *args, **options):
        target = options["target"]
        source = options.get("source")

        runner, formatter, _ = TARGETS[target]
        result = runner(source)

        if result.get("errors"):
            for err in result["errors"]:
                self.stderr.write(self.style.ERROR(err))  # pylint: disable=no-member
            raise CommandError(f"run_update_db failed for target = {target}")

        msg = formatter(result)
        self.stdout.write(self.style.SUCCESS(msg))  # pylint: disable=no-member
        return None
