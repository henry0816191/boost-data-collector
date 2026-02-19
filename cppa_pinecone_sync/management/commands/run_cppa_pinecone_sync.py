"""
Management command: run_cppa_pinecone_sync

Runs Pinecone sync for a single (app_id, namespace, preprocessor) when invoked
with all three parameters (e.g. by another app or scheduler).

Usage:
    python manage.py run_cppa_pinecone_sync --app-id 1 --namespace slack-Cpplang --preprocessor myapp.preprocessors.slack_preprocess
    python manage.py run_cppa_pinecone_sync   # no args: hint only (run-all not yet implemented)
"""

import importlib
import logging

from django.core.management.base import BaseCommand

from cppa_pinecone_sync.sync import sync_to_pinecone

logger = logging.getLogger(__name__)


def _resolve_preprocessor(dotted_path: str):
    """Resolve a dotted path (e.g. 'myapp.preprocessors.slack_preprocess') to a callable."""
    if "." not in dotted_path:
        raise ValueError(
            "Preprocessor must be a dotted path to a callable, e.g. 'myapp.preprocessors.slack_preprocess'"
        )
    module_path, _, name = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    fn = getattr(module, name, None)
    if fn is None:
        raise ValueError(f"Module {module_path!r} has no attribute {name!r}")
    if not callable(fn):
        raise ValueError(f"{dotted_path!r} is not callable")
    return fn


class Command(BaseCommand):
    help = (
        "Run CPPA Pinecone Sync. Pass --app-id, --namespace and --preprocessor to run "
        "sync_to_pinecone for one source; other apps can call sync_to_pinecone() directly."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--app-id",
            type=int,
            default=None,
            help="App ID (e.g. 1, 2, 3). Required with --namespace and --preprocessor.",
        )
        parser.add_argument(
            "--namespace",
            type=str,
            default=None,
            help="Pinecone namespace to upsert into. Required when --app-id is set.",
        )
        parser.add_argument(
            "--preprocessor",
            type=str,
            default=None,
            help="Dotted path to preprocess function (e.g. 'myapp.preprocessors.slack_preprocess'). Required when --app-id is set.",
        )

    def handle(self, *args, **options):
        app_id = options.get("app_id")
        namespace = (options.get("namespace") or "").strip() or None
        preprocessor_path = (options.get("preprocessor") or "").strip() or None

        if app_id is not None and not (namespace and preprocessor_path):
            self.stderr.write(
                self.style.ERROR(
                    "When --app-id is set, both --namespace and --preprocessor are required."
                )
            )
            return 1
        if (namespace or preprocessor_path) and app_id is None:
            self.stderr.write(
                self.style.ERROR(
                    "When --namespace or --preprocessor is set, --app-id is required."
                )
            )
            return 1

        if app_id is None:
            self.stdout.write(
                self.style.WARNING(
                    "No --app-id/--namespace/--preprocessor given. "
                    "Run with --app-id, --namespace and --preprocessor to sync one source; "
                    "or register sources and run 'all' (not yet implemented)."
                )
            )
            return 0

        logger.info(
            "run_cppa_pinecone_sync: starting app_id=%s namespace=%s preprocessor=%s",
            app_id,
            namespace,
            preprocessor_path,
        )

        try:
            preprocess_fn = _resolve_preprocessor(preprocessor_path)
            result = sync_to_pinecone(app_id, namespace, preprocess_fn)
            self.stdout.write(
                self.style.SUCCESS(
                    f"CPPA Pinecone Sync completed: upserted={result['upserted']}, "
                    f"total={result['total']}, failed_count={result['failed_count']}"
                )
            )
            if result.get("errors"):
                for err in result["errors"]:
                    self.stdout.write(self.style.WARNING(str(err)))
            logger.info("run_cppa_pinecone_sync: finished successfully")
            return 0
        except Exception as e:
            logger.exception("run_cppa_pinecone_sync failed: %s", e)
            self.stderr.write(self.style.ERROR(f"Sync failed: {e}"))
            raise
