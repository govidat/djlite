# mysite/models/masterdata.py
#
# Audit + job record for the Master Data upload UI.

from django.contrib.auth.models import User
from django.db import models
from django.utils.translation import gettext_lazy as _


class MasterDataImport(models.Model):
    """One row = one Master Data upload/import job."""

    STATUS_CHOICES = [
        ("pending", _("Pending")),
        ("processing", _("Processing")),
        ("done", _("Done")),
        ("failed", _("Failed")),
    ]

    SCOPE_CHOICES = [
        ("client", _("Client")),
        ("global", _("Global")),
    ]

    client = models.ForeignKey(
        "mysite.Client",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="master_data_imports",
        help_text=_("Null for global (superuser) uploads."),
    )
    dataset_key = models.CharField(max_length=64)
    scope = models.CharField(max_length=16, choices=SCOPE_CHOICES, default="client")
    uploaded_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="master_data_imported",
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)
    file_name = models.CharField(max_length=512, blank=True)
    file_name_b = models.CharField(max_length=512, blank=True)

    delete_existing = models.BooleanField(default=False)
    row_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    summary = models.TextField(blank=True)
    error_log = models.TextField(blank=True)

    class Meta:
        app_label = "mysite"
        ordering = ["-uploaded_at"]
        verbose_name = _("Master data import")
        verbose_name_plural = _("Master data imports")

    def __str__(self):
        return f"{self.dataset_key} ({self.status}) — {self.uploaded_at:%Y-%m-%d %H:%M}"
