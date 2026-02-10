from django.apps import AppConfig


class AnalysisAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.analysis_app"
    verbose_name = "Analysis"

    def ready(self) -> None:
        from . import signals  # noqa: F401
