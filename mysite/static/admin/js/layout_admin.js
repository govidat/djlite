(function ($) {
    'use strict';

    function toggleComponentInline(levelSelect) {
        const $row = $(levelSelect).closest('.djn-inline-form, .inline-related');
        const level = parseInt($(levelSelect).val());
        // Component inline is the one containing comp_id field
        const $compInline = $row.find('.djn-fieldset, .inline-group').filter(function () {
            return $(this).find('[name*="comp_id"], [name*="component"]').length > 0;
        });
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

}(django.jQuery));