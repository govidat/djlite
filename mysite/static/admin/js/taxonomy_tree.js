/*
 * Expand/collapse toggle for the taxonomy tree widget.
 *
 * The htmx `click once` trigger on the same element fires the lazy
 * children fetch exactly once; this plain onclick fires on *every*
 * click to just show/hide the (by-then-populated) children list and
 * flip the arrow. Both listeners are bound to the same click event
 * and don't interfere with each other.
 */
function txToggleNode(toggleEl) {
  var targetId = toggleEl.getAttribute('data-target');
  var children = document.getElementById(targetId);
  if (!children) return;

  var collapsed = children.classList.toggle('tx-collapsed');
  toggleEl.classList.toggle('tx-toggle-open', !collapsed);
  toggleEl.textContent = collapsed ? '▸' : '▾';
}