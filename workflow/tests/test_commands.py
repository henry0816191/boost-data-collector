"""Tests for workflow management commands."""

import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

from django.core.management import call_command, get_commands
from django.core.management.base import CommandError


@pytest.mark.django_db
def test_run_all_collectors_command_exists(workflow_cmd_name):
    """run_all_collectors is registered and runnable; sub-commands are mocked to avoid hanging."""
    commands = get_commands()
    assert (
        workflow_cmd_name in commands
    ), f"Command {workflow_cmd_name!r} should be registered"

    out = StringIO()
    err = StringIO()
    with patch(
        "workflow.management.commands.run_all_collectors.call_command",
        return_value=None,
    ):
        call_command(workflow_cmd_name, stdout=out, stderr=err)
    content = out.getvalue()
    assert "Running" in content and "succeeded" in content


@pytest.mark.django_db
def test_run_all_collectors_success_when_all_succeed(workflow_cmd_name):
    """When all sub-commands succeed, run_all_collectors exits 0 and writes success summary."""
    out = StringIO()
    err = StringIO()
    with patch(
        "workflow.management.commands.run_all_collectors.call_command",
        return_value=None,
    ):
        call_command(workflow_cmd_name, stdout=out, stderr=err)
    content = out.getvalue()
    assert "succeeded" in content and "failed" in content
    assert "success" in content.lower()


@pytest.mark.django_db
def test_run_all_collectors_exits_nonzero_on_command_error(workflow_cmd_name):
    """When a sub-command raises CommandError, run_all_collectors exits with non-zero."""
    out = StringIO()
    err = StringIO()
    with patch(
        "workflow.management.commands.run_all_collectors.call_command",
        side_effect=CommandError("sub-command failed"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            call_command(workflow_cmd_name, stdout=out, stderr=err)
    assert exc_info.value.code != 0


@pytest.mark.django_db
def test_run_all_collectors_stop_on_failure(workflow_cmd_name):
    """With --stop-on-failure, only one sub-command is run when the first fails."""
    out = StringIO()
    err = StringIO()
    call_command_mock = MagicMock(side_effect=CommandError("first failed"))
    with patch(
        "workflow.management.commands.run_all_collectors.call_command",
        call_command_mock,
    ):
        with pytest.raises(SystemExit):
            call_command(
                workflow_cmd_name,
                "--stop-on-failure",
                stdout=out,
                stderr=err,
            )
    # With --stop-on-failure, only the first command runs (count 1 regardless of len(COLLECTOR_COMMANDS)).
    assert call_command_mock.call_count == 1


@pytest.mark.django_db
def test_run_all_collectors_exits_nonzero_on_generic_exception(workflow_cmd_name):
    """When a sub-command raises a generic Exception, run_all_collectors exits with 1."""
    out = StringIO()
    err = StringIO()
    with patch(
        "workflow.management.commands.run_all_collectors.call_command",
        side_effect=RuntimeError("unexpected error"),
    ):
        with pytest.raises(SystemExit) as exc_info:
            call_command(workflow_cmd_name, stdout=out, stderr=err)
    assert exc_info.value.code == 1
