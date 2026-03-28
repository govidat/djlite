document.addEventListener('DOMContentLoaded', function () {

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
        if (!row) return;
        var $ = django.jQuery;

        var $slotType = $(row).find('select[name$="-slot_type"]');
        if ($slotType.length) {
            toggleSlotFields($slotType[0]);
            $slotType.on('change', function () {
                toggleSlotFields(this);
            });
        }

        var $compId = $(row).find('select[name$="-comp_id"]');
        if ($compId.length) {
            toggleCompFields($compId[0]);
            $compId.on('change', function () {
                toggleCompFields(this);
            });
        }
    }

    // Init all existing rows
    django.jQuery('.djn-inline-form, .inline-related').each(function () {
        initRow(this);
    });

    // New rows — django-nested-admin native event
    document.addEventListener('djnesting:added', function (e) {
        if (e.detail && e.detail.row) {
            initRow(e.detail.row);
        }
    });

    // New rows — standard Django formset event
    document.addEventListener('formset:added', function (e) {
        if (e.detail && e.detail.row) {
            initRow(e.detail.row);
        }
    });

});

/*
(function () { 
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

    function waitForJQuery(callback) {
        if (typeof django !== 'undefined' && typeof django.jQuery !== 'undefined') {
            callback(django.jQuery);
        } else {
            setTimeout(function () {
                waitForJQuery(callback);
            }, 50);
        }
    }

    waitForJQuery(function ($) {    
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
            // djnesting:added passes the new row as event.detail or second arg
            $(document).on('djnesting:added', function (e) {
                // django-nested-admin passes row in event.detail
                const row = e.detail && e.detail.row
                    ? e.detail.row
                    : e.originalEvent && e.originalEvent.detail
                        ? e.originalEvent.detail.row
                        : null;
                if (row) initRow(row);
            });

            // formset:added passes $row as second argument
            $(document).on('formset:added', function (e, $row) {
                if ($row && $row.length) {
                    initRow($row[0]);
                }
            });        

        });
    });

}());
*/