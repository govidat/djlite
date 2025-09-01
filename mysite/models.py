from django.db import models

# Create your models here.

class Client(models.Model):
    client_id = models.CharField(max_length=15, unique=True)
    name = models.CharField(max_length=100)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children"
    )

    def __str__(self):
        return f"{self.name} ({self.client_id})"
