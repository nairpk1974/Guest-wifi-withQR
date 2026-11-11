// Auto-continue helpers for the guest portal (kept external so the CSP can forbid inline scripts).
(function () {
  var form = document.querySelector('form[data-auto="1"]');
  if (form) { setTimeout(function () { form.submit(); }, 300); return; }
  var link = document.querySelector('a[data-auto="1"]');
  if (link) { setTimeout(function () { window.location.href = link.href; }, 1200); }
})();
