// Ask-Opus chat widget. Attaches to any `.ask-opus` element with
// data-history-url + data-send-url. Optional data-extra-id names a function on
// window.__chatExtras that returns extra form fields (used by the map for the
// current scan + highlighted-node selection).
(function () {
  // Read the CSRF token lazily at submit time — this script is included inside
  // <main>, which parses BEFORE the `window.ARESCOPE_CSRF = …` line at the end of
  // <body>. Reading it at module-eval time would capture '' and every Ask-Opus
  // POST would 400 ("Something went wrong"). So resolve it per-send instead.
  function csrf() { return window.ARESCOPE_CSRF || ''; }
  var extras = window.__chatExtras || (window.__chatExtras = {});

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  }

  function render(log, msgs) {
    log.innerHTML = '';
    (msgs || []).forEach(function (m) {
      log.appendChild(el('div', 'ask-msg ask-' + m.role, m.content));
    });
    log.scrollTop = log.scrollHeight;
  }

  function mount(root) {
    var btn = root.querySelector('.ask-btn');
    var panel = root.querySelector('.ask-panel');
    var close = root.querySelector('.ask-close');
    var log = root.querySelector('.ask-log');
    var form = root.querySelector('.ask-form');
    var input = root.querySelector('.ask-input');
    var historyUrl = root.dataset.historyUrl;
    var sendUrl = root.dataset.sendUrl;
    var extraId = root.dataset.extraId;
    var loaded = false;

    btn.addEventListener('click', async function () {
      var wasOpen = !panel.hidden;
      panel.hidden = wasOpen;
      if (wasOpen) return;
      input.focus();
      if (!loaded) {
        loaded = true;
        try {
          var r = await fetch(historyUrl, { headers: { Accept: 'application/json' } });
          if (r.ok) render(log, (await r.json()).messages);
        } catch (_) {}
      }
    });

    // X closes the panel (the icon/button alone remains); clicking the button again reopens.
    if (close) close.addEventListener('click', function () { panel.hidden = true; });

    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      var q = input.value.trim();
      if (!q) return;
      input.value = '';
      log.appendChild(el('div', 'ask-msg ask-user', q));
      var pend = el('div', 'ask-msg ask-assistant ask-pending');
      pend.innerHTML = '<span class="spinner"></span>';
      log.appendChild(pend);
      log.scrollTop = log.scrollHeight;

      var body = new URLSearchParams();
      body.set('csrf', csrf());
      body.set('message', q);
      if (extraId && extras[extraId]) {
        var ex = extras[extraId]();
        Object.keys(ex).forEach(function (k) { body.set(k, ex[k]); });
      }
      try {
        var r = await fetch(sendUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
          body: body,
        });
        pend.classList.remove('ask-pending');
        if (!r.ok) {
          pend.textContent = r.status === 403
            ? 'Ask-Opus needs scan access on your account.'
            : 'Something went wrong — please try again.';
          return;
        }
        pend.textContent = ((await r.json()).reply) || '(no answer)';
      } catch (_) {
        pend.classList.remove('ask-pending');
        pend.textContent = 'Network error — please try again.';
      }
      log.scrollTop = log.scrollHeight;
    });
  }

  document.querySelectorAll('.ask-opus').forEach(mount);
})();
