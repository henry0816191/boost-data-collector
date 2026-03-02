"""
Management command: run_update_created_repos_by_language

Counts created repositories by language and year via GitHub REST API, then
upserts github_activity_tracker_createdreposbylanguage.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from boost_usage_tracker.update_created_repos_by_language import (
    LANGUAGES_ENV_KEY,
    update_created_repos_by_language,
)


class Command(BaseCommand):
    help = (
        "Count yearly repos by language via GitHub API and update "
        "CreatedReposByLanguage table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--languages",
            default=None,
            help=(
                "Comma-separated language names (e.g. 'C++,Python,Java'). "
                f"Default: env {LANGUAGES_ENV_KEY}."
            ),
        )
        parser.add_argument(
            "--start-year",
            type=int,
            default=2010,
            help="Start year (inclusive). Default: 2010.",
        )
        parser.add_argument(
            "--end-year",
            type=int,
            default=None,
            help="End year (inclusive). Default: current year.",
        )
        parser.add_argument(
            "--stars-min",
            type=int,
            default=10,
            help="Threshold for significant repos (stars > N). Default: 10.",
        )
        parser.add_argument(
            "--sleep-seconds",
            type=float,
            default=0.0,
            help="Sleep seconds between year queries. Default: 0.0.",
        )
        parser.add_argument(
            "--fail-on-missing-language",
            action="store_true",
            help="Fail if any requested language is not found in Language table.",
        )

    def handle(self, *args, **options):
        result = update_created_repos_by_language(
            languages_csv=options.get("languages"),
            start_year=options.get("start_year", 2010),
            end_year=options.get("end_year"),
            stars_min=options.get("stars_min", 10),
            sleep_seconds=options.get("sleep_seconds", 0.0),
            fail_on_missing_language=options.get("fail_on_missing_language", False),
        )

        if result.get("errors"):
            for err in result["errors"]:
                self.stderr.write(self.style.ERROR(err))  # pylint: disable=no-member

        style = self.style.WARNING if result.get("errors") else self.style.SUCCESS
        self.stdout.write(
            style(  # pylint: disable=no-member
                "languages_requested={requested} processed={processed} missing={missing} "
                "years={start}-{end} stars_min={stars} rows_processed={rows} "
                "created={created} updated={updated}".format(
                    requested=len(result.get("languages_requested", [])),
                    processed=len(result.get("languages_processed", [])),
                    missing=len(result.get("languages_missing", [])),
                    start=result.get("start_year"),
                    end=result.get("end_year"),
                    stars=result.get("stars_min"),
                    rows=result.get("rows_processed", 0),
                    created=result.get("created", 0),
                    updated=result.get("updated", 0),
                )
            )
        )

        return 1 if result.get("errors") else 0
