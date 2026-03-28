document.addEventListener('DOMContentLoaded', function () {

    function toggleComponentInline(levelSelect) {
        var $ = django.jQuery;
        var $row = $(levelSelect).closest('.djn-inline-form, .inline-related');
        var level = parseInt($(levelSelect).val());
        var $compInline = $row.find(
            'input[name$="component-TOTAL_FORMS"]'
        ).closest('.djn-group, .inline-group, fieldset');
        console.log("level:", level, "$compInline found:", $compInline.length);
        if (level === 40) {
            $compInline.show();
        } else {
            $compInline.hide();
        }
    }

    function initRow(row) {
        if (!row) return;
        var $ = django.jQuery;
        var $level = $(row).find('select[name$="-level"]');
        if ($level.length) {
            toggleComponentInline($level[0]);
            $level.on('change', function () {
                toggleComponentInline(this);
            });
        }
    }

    // Init all existing rows
    django.jQuery('.djn-inline-form, .inline-related').each(function () {
        initRow(this);
    });

    // New rows added by django-nested-admin
    document.addEventListener('djnesting:added', function (e) {
        if (e.detail && e.detail.row) {
            initRow(e.detail.row);
        }
    });

    // New rows added by standard formset
    document.addEventListener('formset:added', function (e) {
        if (e.detail && e.detail.row) {
            initRow(e.detail.row);
        }
    });

});

/*

(function () { 
    'use strict';

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
        function toggleComponentInline(levelSelect) {
            const $row = $(levelSelect).closest('.djn-inline-form, .inline-related');
            const level = parseInt($(levelSelect).val());
            // Find the component inline group by looking for the TOTAL_FORMS
            // hidden input whose name ends with "component-TOTAL_FORMS"
            const $compInline = $row.find(
                'input[name$="component-TOTAL_FORMS"]'
            ).closest('.djn-group, .inline-group, fieldset');

            console.log("level:", level, "$compInline found:", $compInline.length);

            if (level === 40) {
                $compInline.show();
            } else {
                $compInline.hide();
            }
        }

        function initRow(row) {
            const $level = $(row).find('select[name$="-level"]');
            if ($level.length) {
                toggleComponentInline($level[0]);
                $level.on('change', function () {
                    toggleComponentInline(this);
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

    });

}()); 
*/