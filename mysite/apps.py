from django.apps import AppConfig


class MysiteConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mysite'
    def ready(self):
        import mysite.signals   # ensures signals are connected on startup

