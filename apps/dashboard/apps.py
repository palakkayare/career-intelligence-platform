from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
    label = "dashboard"
    verbose_name = "Seeker dashboard"

    def ready(self):
        from . import signals  # noqa: F401  (connects cache invalidation)
