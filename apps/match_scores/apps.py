from django.apps import AppConfig


class MatchScoresConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.match_scores'

    def ready(self):
        from . import signals  # noqa