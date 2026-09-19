(function () {
  "use strict";

  var form = document.getElementById("activate-form");
  var status = document.getElementById("status");
  var tokenInput = document.getElementById("token");
  if (!form || !tokenInput) return;

  async function activate(token) {
    if (status) status.textContent = "…";
    try {
      var res = await fetch("/api/admin/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ token: token })
      });
      var data = await res.json();
      if (data.ok) {
        if (status) status.textContent = "Готово. Браузер активирован. Переход в /admin…";
        window.location.assign("/admin");
        return;
      }
      if (status) {
        status.textContent =
          "Не удалось активировать (" + (data.error || res.status) + ").";
      }
    } catch (err) {
      if (status) status.textContent = "Ошибка сети.";
    }
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    e.stopPropagation();
    activate(tokenInput.value);
    return false;
  });

  var btn = document.getElementById("btn-activate");
  if (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      activate(tokenInput.value);
    });
  }

  var params = new URLSearchParams(window.location.search);
  var q = params.get("token");
  if (q) {
    tokenInput.value = q;
  }
})();
