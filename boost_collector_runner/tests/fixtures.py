"""
Fixtures for boost_collector_runner app.
"""

import pytest


@pytest.fixture
def boost_collector_runner_cmd_name():
    """Name of the run_collectors management command."""
    return "run_collectors"
