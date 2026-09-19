(function () {
  "use strict";

  var Q_ORDER = ["q1", "q2", "q3", "q4"];

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

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderFeatureMatrix(matrix, titles) {
    var root = document.getElementById("feature-matrix");
    root.innerHTML = "";
    if (!matrix) return;
    Q_ORDER.forEach(function (qn) {
      var block = matrix[qn];
      if (!block) return;
      var card = document.createElement("div");
      card.className = "matrix-card";
      var title = (titles && titles[qn]) || block.title || qn;
      // Guard against historical typo «Воопрос»
      title = String(title).replace(/Воопрос/g, "Вопрос");
      var h = document.createElement("h3");
      h.textContent = title + (block.prompt ? " — " + block.prompt : "");
      card.appendChild(h);

      var table = document.createElement("table");
      table.className = "matrix-table";
      var thead = document.createElement("thead");
      var hr = document.createElement("tr");
      (block.columns || []).forEach(function (col) {
        var th = document.createElement("th");
        th.textContent = col.title || col.label_ru || col.feature_value;
        hr.appendChild(th);
      });
      thead.appendChild(hr);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      var tr = document.createElement("tr");
      (block.columns || []).forEach(function (col) {
        var td = document.createElement("td");
        var n = col.numerator != null ? col.numerator : 0;
        var d = col.denominator != null ? col.denominator : 0;
        var p = col.percentage != null ? col.percentage : 0;
        td.innerHTML =
          "<strong>" +
          escapeHtml(String(n)) +
          "</strong> из " +
          escapeHtml(String(d)) +
          "<br><span class='pct'>" +
          escapeHtml(String(p)) +
          "%</span>";
        if (n > 0) td.classList.add("hit");
        tr.appendChild(td);
      });
      tbody.appendChild(tr);
      table.appendChild(tbody);
      card.appendChild(table);
      root.appendChild(card);
    });
  }

  function renderResponses(rows) {
    var body = document.getElementById("resp-body");
    var empty = document.getElementById("resp-empty");
    body.innerHTML = "";
    if (!rows || !rows.length) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    rows.forEach(function (row, idx) {
      var tr = document.createElement("tr");
      var tdDate = document.createElement("td");
      tdDate.className = "col-date";
      tdDate.textContent = row.created_at_display || row.created_at || "—";
      tr.appendChild(tdDate);

      var tdTags = document.createElement("td");
      tdTags.className = "col-tags";
      var tags = row.feature_tags || [];
      if (!tags.length) {
        tdTags.textContent = "—";
      } else {
        tags.forEach(function (t) {
          var span = document.createElement("span");
          span.className = "tag";
          span.textContent = t;
          tdTags.appendChild(span);
        });
      }
      tr.appendChild(tdTags);

      var tdRaw = document.createElement("td");
      tdRaw.className = "col-raw";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn ghost btn-sm";
      btn.textContent = "Показать ответы";
      btn.setAttribute("aria-expanded", "false");
      var detailId = "raw-" + idx;
      btn.setAttribute("aria-controls", detailId);
      btn.addEventListener("click", function () {
        var el = document.getElementById(detailId);
        if (!el) return;
        var open = el.hidden;
        el.hidden = !open;
        btn.textContent = open ? "Скрыть ответы" : "Показать ответы";
        btn.setAttribute("aria-expanded", open ? "true" : "false");
      });
      tdRaw.appendChild(btn);
      tr.appendChild(tdRaw);
      body.appendChild(tr);

      var trDetail = document.createElement("tr");
      trDetail.className = "raw-detail";
      var tdDetail = document.createElement("td");
      tdDetail.colSpan = 3;
      tdDetail.id = detailId;
      tdDetail.hidden = true;
      var parts = [
        ["Вопрос 1", row.q1],
        ["Вопрос 2", row.q2],
        ["Вопрос 3", row.q3],
        ["Вопрос 4", row.q4]
      ];
      var html = parts
        .map(function (p) {
          return (
            "<div class='raw-block'><strong>" +
            escapeHtml(p[0]) +
            "</strong><p>" +
            escapeHtml(p[1] || "—") +
            "</p></div>"
          );
        })
        .join("");
      tdDetail.innerHTML = html;
      trDetail.appendChild(tdDetail);
      body.appendChild(trDetail);
    });
  }

  async function refreshSession() {
    var gate = document.getElementById("gate");
    var chat = document.getElementById("chat");
    var statsEl = document.getElementById("stats");
    var tables = document.getElementById("tables");
    var s = await api("/api/admin/session");
    if (!s.data.authenticated) {
      gate.hidden = false;
      chat.hidden = true;
      statsEl.hidden = true;
      tables.hidden = true;
      return false;
    }
    gate.hidden = true;
    chat.hidden = false;
    statsEl.hidden = false;
    tables.hidden = false;
    await refreshStats();
    return true;
  }

  async function refreshStats() {
    var r = await api("/api/admin/summary?dataset=" + encodeURIComponent(dataset()));
    if (!r.data.ok) return;
    document.getElementById("total").textContent = String(r.data.total);
    document.getElementById("latest").textContent =
      r.data.latest_display || r.data.latest || "—";
    renderFeatureMatrix(r.data.feature_matrix, r.data.question_titles);
    renderResponses(r.data.responses || []);
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
      alert("Выгрузка недоступна");
      return;
    }
    var blob = new Blob([JSON.stringify(r.data, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "castdev0926-export-" + dataset() + ".json";
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
    // Quotes already embedded in narrative; skip separate technical dump.
    refreshStats();
  });

  refreshSession();
})();
