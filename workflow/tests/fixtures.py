"""
Fixtures for workflow app.
Workflow has no models; only management commands.
"""

import pytest


@pytest.fixture
def workflow_cmd_name():
    """Name of the run_all_collectors management command."""
    return "run_all_collectors"
