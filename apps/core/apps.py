from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"

    def ready(self):
        # Registers the JWT security scheme with drf-spectacular.
        from . import schema  # noqa: F401
