from django.apps import AppConfig


class BoostCollectorRunnerConfig(AppConfig):
    """Django app config for boost_collector_runner (YAML-driven collector schedule)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "boost_collector_runner"
    verbose_name = "Boost Collector Runner"
