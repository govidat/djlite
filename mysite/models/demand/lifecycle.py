"""
Item Lifecycle Management models.

Three lifecycle events sharing one flag, one UI, one consumer pipeline:
  1. ItemDiscontinuation — item withdrawn from an effective date (Scenario 1)
  2. ItemIntroduction   — new item borrows a reference forecast (Scenario 2)
  3. ItemSubstitution   — retired item code -> successor (Scenario 3)

Invariant: three lifecycle events, three layers, one flag.
All gated by ForecastingConfig.use_item_lifecycle + item_lifecycle ClientFeatureControl key.
"""

from decimal import Decimal

from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def _assert_subject_role_free(client_id, item_id, exclude_model=None, exclude_pk=None):
    """One lifecycle directive per item: an item may hold exactly ONE subject role."""
    from mysite.models.demand.lifecycle import (ItemSubstitution, ItemDiscontinuation,
                                                ItemIntroduction)
    checks = (
        (ItemSubstitution, "old_item_id"),
        (ItemSubstitution, "new_item_id"),
        (ItemDiscontinuation, "item_id"),
        (ItemIntroduction, "new_item_id"),
    )
    for model, field in checks:
        if model is exclude_model:
            continue
        if (model.objects.filter(client_id=client_id, **{field: item_id})
                          .exclude(pk=exclude_pk).exists()):
            raise ValidationError(
                _("One lifecycle directive per item: this item already holds another role."))


class ItemSubstitution(models.Model):
    """Scenario 3 — retired item code -> successor item code, with unit conversion.

    The successor's forecast series is its OWN netted actuals PLUS the
    predecessor's netted actuals converted by conversion_factor, for
    periods before effective_from. Applied as a live re-key JOIN in
    actuals_queryset_with_net() (nothing is materialized).
    Direct mapping only: an item may never be both a predecessor and a
    successor across rows (no chains, no cycles).
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="item_substitutions")
    old_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                 related_name="substituted_by")
    new_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                 related_name="successor_of")
    # Units of NEW per unit of OLD. 2 old = 1 new  ->  0.5.
    # Applies identically to qty and revenue (per-unit price preserved).
    conversion_factor = models.DecimalField(
        _("conversion factor"), max_digits=14, decimal_places=6, default=Decimal("1"),
        help_text=_("new_qty = old_qty x factor; new_revenue = old_revenue x factor. "
                    "2 old units = 1 new unit -> 0.5."),
    )
    # Launch date of the successor. Old-item actuals with period_start <
    # effective_from are converted; rows on/after it stay with the old item
    # (which is forecast as nil on/after this date).
    effective_from = models.DateField(
        _("effective from"), null=True, blank=True,
        help_text=_("Successor launch date. Old actuals BEFORE this date convert to new_item "
                    "(null = convert the entire old history). Exclusive cutoff."),
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "old_item")]
        indexes = [
            models.Index(fields=["client", "old_item"], name="ix_itemsubst_old"),
            models.Index(fields=["client", "new_item"], name="ix_itemsubst_new"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(conversion_factor__gt=0), name="itemsubst_factor_positive"),
        ]
        verbose_name = _("02-05D Item Substitution")

    def __str__(self):
        return f"{self.old_item_id} → {self.new_item_id} (×{self.conversion_factor})"

    def clean(self):
        if self.old_item_id == self.new_item_id:
            raise ValidationError(_("old_item and new_item must differ."))
        if self.old_item_id and self.old_item.client_id != self.client_id:
            raise ValidationError(_("old_item must belong to the same client."))
        if self.new_item_id and self.new_item.client_id != self.client_id:
            raise ValidationError(_("new_item must belong to the same client."))
        if self.conversion_factor is not None and self.conversion_factor <= 0:
            raise ValidationError(_("conversion_factor must be > 0."))
        # Direct mapping only: an item may not be BOTH a predecessor and a
        # successor across substitution rows (kills chains AND cycles).
        if (ItemSubstitution.objects
                .filter(client_id=self.client_id, old_item_id=self.new_item_id)
                .exclude(pk=self.pk).exists()):
            raise ValidationError(_(
                "Direct mapping only: new_item may not itself be an old_item "
                "of another substitution."))
        if (ItemSubstitution.objects
                .filter(client_id=self.client_id, new_item_id=self.old_item_id)
                .exclude(pk=self.pk).exists()):
            raise ValidationError(_(
                "Direct mapping only: old_item may not itself be a new_item "
                "of another substitution."))
        # One lifecycle directive per item: neither subject may hold another role.
        if self.old_item_id:
            _assert_subject_role_free(self.client_id, self.old_item_id, self.__class__, self.pk)
        if self.new_item_id:
            _assert_subject_role_free(self.client_id, self.new_item_id, self.__class__, self.pk)


class ItemDiscontinuation(models.Model):
    """Scenario 1 — item withdrawn from an effective date.

    The item keeps its full history (it feeds reporting/ABC/accuracy) but its
    forecast is NIL on/after effective_from: write_forecast_lines emits no
    line for horizon periods with period_start >= effective_from. Periods
    before it forecast normally from the item's own history.
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="item_discontinuations")
    item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                             related_name="discontinuations")
    # Withdrawal date. NULL = nil forecast from the current run onward.
    effective_from = models.DateField(
        _("effective from"), null=True, blank=True,
        help_text=_("Forecast is nil on/after this date; periods before it forecast normally. "
                    "Null = nil forecast immediately."),
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "item")]
        indexes = [
            models.Index(fields=["client", "item"], name="ix_itemdisc_item"),
        ]
        verbose_name = _("02-05D Item Discontinuation")

    def __str__(self):
        eff = self.effective_from or "immediate"
        return f"{self.item_id} discontinued {eff}"

    def clean(self):
        if self.item_id and self.item.client_id != self.client_id:
            raise ValidationError(_("item must belong to the same client."))
        _assert_subject_role_free(self.client_id, self.item_id, self.__class__, self.pk)


class ItemIntroduction(models.Model):
    """Scenario 2 — new item with no history borrows a reference item's forecast.

    For horizon periods where the new item has fewer than
    ForecastingConfig.min_history_periods own actual periods AND the period is
    inside [copy_from, copy_to] (NULL bounds: copy_from -> borrow from launch,
    copy_to -> borrow until enough own history), the new item's ForecastLine is
    set to the reference item's statistical line x ratio, tagged
    borrowed_from_item / borrowed_ratio. Reference item is NOT retired.
    """
    client = models.ForeignKey("mysite.Client", on_delete=models.CASCADE,
                               related_name="item_introductions")
    new_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                 related_name="introduction_of")
    reference_item = models.ForeignKey("mysite.Item", on_delete=models.CASCADE,
                                       related_name="referenced_by")
    # Units of NEW per unit of REFERENCE. Applies identically to qty and value.
    ratio = models.DecimalField(
        _("ratio"), max_digits=14, decimal_places=6, default=Decimal("1"),
        help_text=_("new forecast = reference forecast x ratio."),
    )
    copy_from = models.DateField(
        _("copy from"), null=True, blank=True,
        help_text=_("First period to borrow (null = from the new item's launch)."),
    )
    copy_to = models.DateField(
        _("copy to"), null=True, blank=True,
        help_text=_("Last period to borrow (null = until the new item has "
                    "min_history_periods own periods). The copy stops at the "
                    "earlier of copy_to and enough own history."),
    )
    notes = models.TextField(_("notes"), blank=True)
    created_by = models.ForeignKey("auth.User", null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "mysite"
        unique_together = [("client", "new_item")]
        indexes = [
            models.Index(fields=["client", "new_item"], name="ix_itemintro_new"),
            models.Index(fields=["client", "reference_item"], name="ix_itemintro_ref"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(ratio__gt=0), name="itemintro_ratio_positive"),
        ]
        verbose_name = _("02-05D Item Introduction")

    def __str__(self):
        return f"{self.new_item_id} ← {self.reference_item_id} (×{self.ratio})"

    def clean(self):
        if self.new_item_id == self.reference_item_id:
            raise ValidationError(_("new_item and reference_item must differ."))
        if self.new_item_id and self.new_item.client_id != self.client_id:
            raise ValidationError(_("new_item must belong to the same client."))
        if self.reference_item_id and self.reference_item.client_id != self.client_id:
            raise ValidationError(_("reference_item must belong to the same client."))
        if self.ratio is not None and self.ratio <= 0:
            raise ValidationError(_("ratio must be > 0."))
        if self.copy_from and self.copy_to and self.copy_to < self.copy_from:
            raise ValidationError(_("copy_to must be >= copy_from."))
        # No reference chains: new_item may not itself be another intro's
        # reference_item, nor a substitution/discontinuation subject.
        if (ItemIntroduction.objects
                .filter(client_id=self.client_id, reference_item_id=self.new_item_id)
                .exclude(pk=self.pk).exists()):
            raise ValidationError(_(
                "Direct mapping only: new_item may not itself be a reference_item "
                "of another introduction."))
        _assert_subject_role_free(self.client_id, self.new_item_id, self.__class__, self.pk)
