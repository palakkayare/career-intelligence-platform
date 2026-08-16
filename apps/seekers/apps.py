from django.apps import AppConfig


class SeekersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.seekers'

    def ready(self):
        from . import signals  # noqa