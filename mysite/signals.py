from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import GlobalVal
from utils.globalval import bust_globalval_cache

@receiver(post_save, sender=GlobalVal)
@receiver(post_delete, sender=GlobalVal)
def clear_globalval_cache(sender, **kwargs):
    bust_globalval_cache()