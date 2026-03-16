import os
import sys
import threading

from django.apps import AppConfig


class SlackEventHandlerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "slack_event_handler"
    verbose_name = "Slack Event Handler"

    def ready(self):
        if "runserver" not in sys.argv:
            return
        # Runserver reloader: parent watches files, child runs the server. Only start the
        # listener in the child so we don't open two Socket Mode connections to Slack.
        if os.environ.get("RUN_MAIN") != "true":
            return

        def start_listener():
            from slack_event_handler.runner import run_slack_event_handler

            run_slack_event_handler()

        t = threading.Thread(
            target=start_listener, daemon=True, name="slack-event-handler"
        )
        t.start()
