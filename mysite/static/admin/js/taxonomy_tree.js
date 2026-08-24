/*
 * Expand/collapse toggle + cascading tri-state checkboxes for the
 * taxonomy tree widget.
 *
 * Expand/collapse: the htmx `click once` trigger on the same element
 * fires the lazy children fetch exactly once; this plain onclick fires
 * on *every* click to just show/hide the (by-then-populated) children
 * list and flip the arrow. Both listeners are bound to the same click
 * event and don't interfere with each other.
 *
 * Selection cascade:
 *   - Checking a node checks every rendered descendant (its whole
 *     subtree); unloaded descendants are covered by the server, which
 *     expands any chosen node to its full subtree on the query side.
 *   - Unchecking a node unchecks every rendered descendant.
 *   - A parent whose children are all checked shows checked; with some
 *     checked it shows indeterminate (partial); with none, unchecked.
 *     The state bubbles up to the root on every change.
 *   - Nodes the server renders with `data-partial` get the indeterminate
 *     property after any (re)render — including lazy htmx swaps.
 */
function txToggleNode(toggleEl) {
  var targetId = toggleEl.getAttribute('data-target');
  var children = document.getElementById(targetId);
  if (!children) return;

  var collapsed = children.classList.toggle('tx-collapsed');
  toggleEl.classList.toggle('tx-toggle-open', !collapsed);
  toggleEl.textContent = collapsed ? '▸' : '▾';
}

/* ── Selection cascade ──────────────────────────────────────────────── */

function txNodeOf(cb) {
  var row = cb.closest('.tx-node-row');
  return row ? row.parentElement : null;
}

function txChildrenBoxes(li) {
  var list = li.querySelector(':scope > .tx-children');
  if (!list) return [];
  // Checkbox lives inside <label> within .tx-node-row — use a descendant
  // selector, not `> input` (which is only a child of the label).
  return Array.prototype.slice.call(
    list.querySelectorAll(':scope > li > .tx-node-row input[type="checkbox"]')
  );
}

function txSetCheckbox(cb, state) {
  if (state === 'checked') {
    cb.checked = true;
    cb.indeterminate = false;
  } else if (state === 'partial') {
    cb.checked = false;
    cb.indeterminate = true;
  } else {
    cb.checked = false;
    cb.indeterminate = false;
  }
}

/*
 * Recompute a node's state from its direct children and set its
 * checkbox, then repeat for each ancestor up to the root.
 */
function txSyncUp(startLi) {
  var li = startLi;
  while (li && li.classList && li.classList.contains('tx-node')) {
    var boxes = txChildrenBoxes(li);
    if (boxes.length) {
      var checked = 0, partial = 0;
      boxes.forEach(function(b) {
        if (b.checked) checked += 1;
        else if (b.indeterminate) partial += 1;
      });
      if (checked === boxes.length) {
        txSetCheckbox(li.querySelector('.tx-node-row input'), 'checked');
      } else if (checked > 0 || partial > 0) {
        txSetCheckbox(li.querySelector('.tx-node-row input'), 'partial');
      } else {
        txSetCheckbox(li.querySelector('.tx-node-row input'), 'unchecked');
      }
    }
    li = li.parentElement ? li.parentElement.closest('.tx-node') : null;
  }
}

/*
 * Check/uncheck a node plus every rendered descendant. The node's own
 * state is set directly (a check always means "whole subtree"), then
 * ancestors are recomputed.
 */
function txCascade(cb) {
  var li = txNodeOf(cb);
  if (li) {
    li.querySelectorAll(':scope > .tx-children input[type="checkbox"]')
      .forEach(function(c) {
        txSetCheckbox(c, cb.checked ? 'checked' : 'unchecked');
      });
  }
  if (cb.checked) {
    cb.indeterminate = false;
  }
  if (li) txSyncUp(li);
}

function txTreeCheckboxChange(evt) {
  var cb = evt.target;
  if (!cb || !cb.classList || !cb.classList.contains('tx-checkbox')) return;
  txCascade(cb);
}

/*
 * Apply server-rendered partial state (data-partial) to any checkbox
 * that (re)appeared in the DOM. Called on load and after every htmx
 * swap so lazily-loaded branches and reloaded filter bars stay correct.
 */
function txInitPartialStates() {
  document.querySelectorAll('input.tx-checkbox[data-partial]').forEach(function(cb) {
    cb.checked = false;
    cb.indeterminate = true;
  });
}

/*
 * Cascade must run in the CAPTURE phase: the filter bar's submit handler
 * listens for 'change' on document (bubble phase, registered later), and
 * it reads the checkboxes to decide what to send. If the cascade ran
 * after it, unchecking one child would submit the still-checked parent —
 * and the server, expanding the parent's whole subtree, would re-tick
 * every child. Capture ordering guarantees the DOM reflects the cascade
 * before any submit handler reads it.
 */
document.addEventListener('change', txTreeCheckboxChange, true);

if (window.htmx) {
  document.addEventListener('htmx:afterSwap', txInitPartialStates);
}
document.addEventListener('DOMContentLoaded', txInitPartialStates);
txInitPartialStates();
