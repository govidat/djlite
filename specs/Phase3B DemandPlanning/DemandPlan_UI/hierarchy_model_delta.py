# DELTA — mysite/models/demand/hierarchy.py
#
# Add `permissions` to PlanningLocation.Meta. This does NOT replace the
# class — just add the `permissions` list inside the existing Meta block.

class PlanningLocation(MaterializedPathMixin):
    # ... all existing fields unchanged ...

    class Meta:
        app_label = 'mysite'
        unique_together = [('client', 'code')]
        ordering = ['path']
        verbose_name = _('planning location')
        verbose_name_plural = _('planning locations')
        indexes = [
            models.Index(fields=['client', 'is_leaf'], name='ix_planloc_client_leaf'),
        ]
        # ── NEW: guardian object-level permissions ─────────────────────────
        permissions = [
            ('override_at_location', 'Can create/edit forecast overrides at this location and below'),
            ('view_at_location',     'Can view demand planning data at this location and below'),
        ]

# After adding this:
#   python manage.py makemigrations mysite --name planninglocation_guardian_perms
#   python manage.py migrate
#
# This creates two new rows in django_content_type's permission table
# (auth_permission). Guardian's per-object grants (UserObjectPermission,
# GroupObjectPermission tables) already exist from your project's
# earlier guardian setup — no new guardian migration needed.
