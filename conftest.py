"""
Root conftest: register app-level fixture modules and optional session/global fixtures.
"""

import pytest


def _patch_django_context_copy_py314():
    """Fix Django BaseContext.__copy__ on Python 3.14 (copy(super()) is broken there)."""
    import sys

    if sys.version_info >= (3, 14):
        from django.template.context import BaseContext

        def __copy__(self):
            duplicate = object.__new__(type(self))
            duplicate.__dict__ = self.__dict__.copy()
            duplicate.dicts = self.dicts[:]
            return duplicate

        BaseContext.__copy__ = __copy__


def pytest_configure(config):  # noqa: F841 (pytest hook; name must match spec)
    _patch_django_context_copy_py314()


# Load app-level fixture modules so fixtures from each app are available everywhere.
pytest_plugins = [
    "cppa_user_tracker.tests.fixtures",
    "github_ops.tests.fixtures",
    "github_activity_tracker.tests.fixtures",
    "boost_library_tracker.tests.fixtures",
    "cppa_slack_tracker.tests.fixtures",
    "boost_library_usage_dashboard.tests.fixtures",
    "boost_usage_tracker.tests.fixtures",
    "boost_mailing_list_tracker.tests.fixtures",
    "workflow.tests.fixtures",
]


@pytest.fixture(scope="session")
def test_workspace_dir():
    """Session-scoped path to test workspace (for tests that need a real path)."""
    from pathlib import Path
    from django.conf import settings

    return getattr(
        settings,
        "WORKSPACE_DIR",
        Path(__file__).resolve().parent / ".test_artifacts" / "workspace",
    )
