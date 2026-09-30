/* Pages need #loading, #unlockSection (#unlockForm, #secret), #app and #toast,
   and call Admin.start(load), where load() fetches and calls Admin.showApp(). */
(function () {
  var STORAGE_KEY = 'adminSecret';

  function readSecret() {
    try { return sessionStorage.getItem(STORAGE_KEY); } catch (e) { return null; }
  }
  function writeSecret(value) {
    try {
      if (value) sessionStorage.setItem(STORAGE_KEY, value);
      else sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) { /* storage unavailable: keep it in memory */ }
  }
  var secret = readSecret();

  var toastTimer;
  function toast(message, isError) {
    var node = document.getElementById('toast');
    node.textContent = message;
    node.classList.toggle('error', !!isError);
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { node.hidden = true; }, isError ? 5000 : 2200);
  }

  function show(id) {
    ['loading', 'unlockSection', 'app'].forEach(function (other) {
      document.getElementById(other).hidden = other !== id;
    });
  }

  function showApp() { show('app'); }

  function lock() {
    secret = null;
    writeSecret(null);
    show('unlockSection');
    document.getElementById('secret').focus();
  }

  function api(method, path, body) {
    var opts = { method: method, headers: { 'Authorization': 'Bearer ' + secret } };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      if (res.status === 401) {
        lock();
        throw new Error('Wrong admin secret.');
      }
      return res.json().catch(function () { return null; }).then(function (data) {
        if (!res.ok) throw new Error((data && data.detail) || ('Request failed (' + res.status + ')'));
        return data;
      });
    });
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function start(load) {
    document.getElementById('unlockForm').addEventListener('submit', function (e) {
      e.preventDefault();
      secret = document.getElementById('secret').value;
      load().then(function () {
        writeSecret(secret);
        document.getElementById('secret').value = '';
      }).catch(function (err) { toast(err.message, true); });
    });
    if (!secret) {
      lock();
      return;
    }
    show('loading');
    load().catch(function (err) {
      document.getElementById('loading').hidden = true;
      toast(err.message, true);
    });
  }

  window.Admin = { api: api, el: el, toast: toast, showApp: showApp, start: start };
})();
