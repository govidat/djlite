from django.apps import AppConfig


class MysiteConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mysite'
    label = 'mysite'

    #def ready(self):
    #    from mysite.signals import register_signals
    #    register_signals()    


    def ready(self):
        from mysite.signals import register_signals
        register_signals()   # connects CMS/taxonomy cache-invalidation handlers

