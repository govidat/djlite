"""
Admin registration for Sales Promotion Scheme models.
Mirrors the structure of demand_forecast.py.
"""
from django.contrib import admin
from django.utils.html import format_html
from mysite.models.demand.schemes import (
    SalesScheme, SalesSchemeScope, SalesSchemePeriod,
    ResolvedSalesSchemePeriod, SalesSchemeOccurrence,
)


class SalesSchemeScopeInline(admin.TabularInline):
    model = SalesSchemeScope
    extra = 0
    raw_id_fields = ('taxonomy_node', 'item', 'planning_location',
                     'planning_customer', 'distribution_channel')


class SalesSchemePeriodInline(admin.TabularInline):
    model = SalesSchemePeriod
    extra = 0


class SalesSchemeOccurrenceInline(admin.TabularInline):
    model = SalesSchemeOccurrence
    extra = 0
    readonly_fields = ['period_type', 'period_start', 'period_end', 'actual_qty_uplift_pct',
                       'actual_value_uplift_pct', 'actual_pull_forward_pct',
                       'qty_uplift_variance', 'value_uplift_variance', 'pull_forward_variance']
    can_delete = False


_SUGGEST_JS = """
<script>
(function() {
    function getCookie(name) {
        var v = document.cookie.match('(^|;)\\s*' + name + '\\s*=\\s*([^;]+)');
        return v ? v.pop() : '';
    }

    function fetchSuggestions() {
        var codeInput = document.getElementById('id_scheme_code');
        if (!codeInput || !codeInput.value.trim()) return;

        var url = window.location.origin + '/demand/schemes/suggest/?code=' +
                  encodeURIComponent(codeInput.value.trim());
        fetch(url, {
            headers: {'X-Requested-With': 'XMLHttpRequest'}
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var s = data.suggested;
            if (!s || !s.suggested) return;

            var sug = s.suggested;
            var fields = {
                'expected_qty_uplift_pct': sug.expected_qty_uplift_pct,
                'expected_value_uplift_pct': sug.expected_value_uplift_pct,
                'pull_forward_pct': sug.pull_forward_pct
            };

            var filled = [];
            Object.keys(fields).forEach(function(key) {
                var el = document.getElementById('id_' + key);
                if (el && fields[key] !== undefined && el.value === '0.0000') {
                    el.value = fields[key];
                    el.style.backgroundColor = '#e8f5e9';
                    filled.push(key.replace(/_/g, ' '));
                }
            });

            // Show occurrence count + warnings
            var existing = document.getElementById('scheme-suggest-banner');
            if (existing) existing.remove();

            var banner = document.createElement('div');
            banner.id = 'scheme-suggest-banner';
            banner.style.cssText = 'margin:10px 0;padding:10px;border-radius:4px;font-size:13px;';

            var msg = '<strong>Based on ' + s.occurrence_count + ' prior occurrence(s):</strong> ';
            if (filled.length) msg += 'Pre-filled: ' + filled.join(', ') + '. ';

            if (s.warnings && s.warnings.length) {
                banner.style.backgroundColor = '#fff3e0';
                banner.style.border = '1px solid #ff9800';
                msg += '<br><br><strong>Warnings:</strong><ul style="margin:4px 0 0 16px;padding:0;">';
                s.warnings.forEach(function(w) { msg += '<li>' + w + '</li>'; });
                msg += '</ul>';
            } else {
                banner.style.backgroundColor = '#e8f5e9';
                banner.style.border = '1px solid #4caf50';
            }
            banner.innerHTML = msg;

            // Insert after scheme_code field row
            var codeRow = codeInput.closest('.form-row') || codeInput.closest('.field-scheme_code');
            if (codeRow) {
                codeRow.parentNode.insertBefore(banner, codeRow.nextSibling);
            }
        })
        .catch(function() {});
    }

    document.addEventListener('DOMContentLoaded', function() {
        var codeInput = document.getElementById('id_scheme_code');
        if (codeInput) {
            codeInput.addEventListener('blur', fetchSuggestions);
        }
    });
})();
</script>
"""


class SalesSchemeAdmin(admin.ModelAdmin):
    list_display = ['client', 'scheme_code', 'name', 'status', 'expected_qty_uplift_pct',
                    'expected_value_uplift_pct', 'shadow_periods', 'pull_forward_pct',
                    'updated_at']
    list_filter = ['client', 'status']
    search_fields = ['scheme_code', 'name']
    readonly_fields = ['created_by', 'created_at', 'updated_at']
    inlines = [SalesSchemeScopeInline, SalesSchemePeriodInline, SalesSchemeOccurrenceInline]

    def save_model(self, request, obj, form, change):
        if not change and obj.created_by is None:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def render_change_form(self, request, obj=None, change=False, add=False, form_url='', context=None):
        response = super().render_change_form(request, obj, change, add, form_url, context)
        if add and hasattr(response, 'content'):
            # Inject suggestion JS on the add form only
            js_tag = format_html(_SUGGEST_JS)
            response.content = response.content.replace(
                b'{{ block.super }}',
                str(js_tag).encode() + b'{{ block.super }}',
            ) if b'{{ block.super }}' in response.content else (
                response.content.replace(
                    b'</body>',
                    str(js_tag).encode() + b'\n</body>'
                )
            )
        return response


class ResolvedSalesSchemePeriodAdmin(admin.ModelAdmin):
    list_display = ['scheme', 'item', 'planning_location', 'planning_customer',
                    'distribution_channel', 'period_type', 'period_start', 'row_kind']
    list_filter = ['period_type', 'is_shadow', 'shadow_side']
    readonly_fields = [f.name for f in ResolvedSalesSchemePeriod._meta.fields]

    def row_kind(self, obj):
        if obj.is_shadow:
            return f"SHADOW({obj.shadow_side}:{obj.shadow_offset})"
        return "WINDOW"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
