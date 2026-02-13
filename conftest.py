"""
Root conftest: register app-level fixture modules and optional session/global fixtures.
"""

import pytest

# Load app-level fixture modules so fixtures from each app are available everywhere.
pytest_plugins = [
    "workflow.tests.fixtures",
    "cppa_user_tracker.tests.fixtures",
    "github_ops.tests.fixtures",
    "github_activity_tracker.tests.fixtures",
    "boost_library_tracker.tests.fixtures",
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
