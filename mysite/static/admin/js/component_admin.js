(function ($) {
    'use strict';

    // Fields only relevant to specific slot types
    const FIGURE_FIELDS = ['image_url', 'alt', 'figure_class'];
    const TEXT_FIELDS = ['actions_class'];    
    const ACCORDION_L1_FIELDS = ['accordion_checked'];
    const NON_FIGURE_FIELDS = [...TEXT_FIELDS, ...ACCORDION_L1_FIELDS];
    const ALL_TOGGLED = [...FIGURE_FIELDS, ...TEXT_FIELDS, ...ACCORDION_L1_FIELDS];

    // Fields only relevant to specific comp types at L0
    const CARD_FIELDS = ['card_body_class'];    
    const HERO_FIELDS = ['hero_content_class', 'hero_overlay', 'hero_overlay_style'];
    const ACCORDION_FIELDS = ['accordion_type', 'accordion_name'];
    const ALL_L0_TOGGLED = [...CARD_FIELDS, ...HERO_FIELDS, ...ACCORDION_FIELDS];

    // ── L1 slot type toggle ───────────────────────────────────
    function toggleSlotFields(slotTypeSelect) {
        const $row = $(slotTypeSelect).closest('.djn-inline-form, .inline-related');
        const slotType = $(slotTypeSelect).val();

        ALL_TOGGLED.forEach(function (fieldName) {
            $row.find('.field-' + fieldName).hide();
        });

        if (slotType === 'figure') {
            FIGURE_FIELDS.forEach(function (f) {
                $row.find('.field-' + f).show();
            });
            // hide comptextblock inline for figure slots
            $row.find('.djn-group[data-inline-model*="comptextblock"]').hide();
        } else if (slotType === 'text') {           
            NON_FIGURE_FIELDS.forEach(function (f) {
                $row.find('.field-' + f).show();
            });
            // show comptextblock inline for text slots
            $row.find('.djn-group[data-inline-model*="comptextblock"]').show();
        }
    }

    // ── L0 comp type toggle ───────────────────────────────────
    function toggleCompFields(compIdSelect) {
        const $row = $(compIdSelect).closest('.djn-inline-form, .inline-related');
        const compId = $(compIdSelect).val();

        ALL_L0_TOGGLED.forEach(function (fieldName) {
            $row.find('.field-' + fieldName).hide();
        });

        if (compId === 'hero') {
            HERO_FIELDS.forEach(function (f) {
                $row.find('.field-' + f).show();
            });
        } else if (compId === 'card') {
            CARD_FIELDS.forEach(function (f) {
                $row.find('.field-' + f).show();
            });
        } else if (compId === 'accordion') {
            ACCORDION_FIELDS.forEach(function (f) {
                $row.find('.field-' + f).show();
            });
        }
    }

    function initRow(row) {
        // L1 slot type
        const $slotType = $(row).find('select[name$="-slot_type"]');
        if ($slotType.length) {
            toggleSlotFields($slotType[0]);
            $slotType.on('change', function () {
                toggleSlotFields(this);
            });
        }

        // L0 comp_id
        const $compId = $(row).find('select[name$="-comp_id"]');
        if ($compId.length) {
            toggleCompFields($compId[0]);
            $compId.on('change', function () {
                toggleCompFields(this);
            });
        }
    }

    $(document).ready(function () {
        $('.djn-inline-form, .inline-related').each(function () {
            initRow(this);
        });
        $(document).on('djnesting:added formset:added', function (e, $row) {
            initRow($row[0] || $row);
        });
    });

}(django.jQuery));