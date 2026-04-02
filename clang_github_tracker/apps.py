"""Django app config for clang_github_tracker."""

from django.apps import AppConfig


class ClangGithubTrackerConfig(AppConfig):
    """Registers the clang_github_tracker application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "clang_github_tracker"
    verbose_name = "Clang GitHub Tracker"
