(function () {
  "use strict";

  function csrf() {
    var m = document.cookie.match(/(?:^|; )castdev_admin_csrf=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function dataset() {
    var el = document.getElementById("dataset");
    return el ? el.value : "production";
  }

  async function api(path, opts) {
    opts = opts || {};
    var headers = opts.headers || {};
    headers["Accept"] = "application/json";
    if (opts.body && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    if (opts.method && opts.method !== "GET") {
      headers["X-CSRF-Token"] = csrf();
    }
    var res = await fetch(path, {
      method: opts.method || "GET",
      headers: headers,
      credentials: "same-origin",
      body: opts.body
    });
    var data = null;
    try {
      data = await res.json();
    } catch (e) {
      data = { ok: false, error: "bad_json" };
    }
    return { res: res, data: data };
  }

  function addBubble(thread, text, cls) {
    var div = document.createElement("div");
    div.className = "bubble " + (cls || "");
    div.textContent = text;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
  }

  async function refreshSession() {
    var gate = document.getElementById("gate");
    var chat = document.getElementById("chat");
    var stats = document.getElementById("stats");
    var s = await api("/api/admin/session");
    if (!s.data.authenticated) {
      gate.hidden = false;
      chat.hidden = true;
      stats.hidden = true;
      return false;
    }
    gate.hidden = true;
    chat.hidden = false;
    stats.hidden = false;
    await refreshStats();
    return true;
  }

  async function refreshStats() {
    var r = await api("/api/admin/summary?dataset=" + encodeURIComponent(dataset()));
    if (!r.data.ok) return;
    document.getElementById("total").textContent = String(r.data.total);
    document.getElementById("latest").textContent = r.data.latest || "—";
  }

  document.getElementById("dataset").addEventListener("change", refreshStats);

  document.getElementById("btn-logout").addEventListener("click", async function () {
    await api("/api/admin/logout", { method: "POST", body: "{}" });
    window.location.reload();
  });

  document.getElementById("btn-new").addEventListener("click", function () {
    document.getElementById("thread").innerHTML = "";
  });

  document.getElementById("btn-snapshot").addEventListener("click", async function () {
    var r = await api("/api/admin/snapshot?dataset=" + encodeURIComponent(dataset()));
    if (!r.data.ok) {
      alert("Snapshot недоступен");
      return;
    }
    var blob = new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "castdev0926-snapshot-" + dataset() + ".json";
    a.click();
  });

  document.getElementById("ask-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var q = document.getElementById("question").value.trim();
    if (!q) return;
    var thread = document.getElementById("thread");
    addBubble(thread, q, "user");
    document.getElementById("question").value = "";
    var r = await api("/api/admin/ask", {
      method: "POST",
      body: JSON.stringify({ question: q, dataset: dataset() })
    });
    if (!r.data.ok && r.res.status === 401) {
      addBubble(thread, "Сессия истекла. Требуется повторная активация.", "meta");
      refreshSession();
      return;
    }
    var text = r.data.answer_text || r.data.error || "Нет ответа";
    addBubble(thread, text);
    if (r.data.capability_note) {
      var note = document.getElementById("capability-note");
      note.hidden = false;
      note.textContent = r.data.capability_note;
    }
    if (r.data.quotes && r.data.quotes.length) {
      var quotes = r.data.quotes
        .map(function (x) {
          return "[" + x.question + "] «" + x.quote + "»";
        })
        .join("\n");
      addBubble(thread, "Цитаты (RAW):\n" + quotes, "meta");
    }
    refreshStats();
  });

  refreshSession();
})();
