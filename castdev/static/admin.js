(function () {
  "use strict";

  var state = {
    filter: "all",
    cabinet: null,
    dataSource: "production",
    showTestToggle: false
  };

  function csrf() {
    var m = document.cookie.match(/(?:^|; )castdev_admin_csrf=([^;]*)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function dataset() {
    if (!state.showTestToggle) return state.dataSource || "production";
    var el = document.getElementById("dataset");
    return el ? el.value : state.dataSource || "production";
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

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function addBubble(thread, text, cls) {
    var div = document.createElement("div");
    div.className = "bubble " + (cls || "");
    div.textContent = text;
    thread.appendChild(div);
    thread.scrollTop = thread.scrollHeight;
  }

  function fixTypo(s) {
    return String(s || "").replace(/Воопрос/g, "Вопрос");
  }

  function renderThemes(themes) {
    var root = document.getElementById("themes");
    root.innerHTML = "";
    if (!themes) return;
    ["q1", "q2", "q3", "q4"].forEach(function (qn) {
      var block = themes[qn];
      if (!block) return;
      var card = document.createElement("div");
      card.className = "theme-card";
      var h = document.createElement("h3");
      h.textContent = fixTypo(block.title) + " — " + (block.prompt || "");
      card.appendChild(h);

      if (!block.themes || !block.themes.length) {
        var empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "Признаков пока нет.";
        card.appendChild(empty);
        root.appendChild(card);
        return;
      }

      var table = document.createElement("table");
      table.className = "theme-table";
      table.innerHTML =
        "<thead><tr><th>Тема / признак</th><th>Количество</th><th>Доля</th><th></th></tr></thead>";
      var tbody = document.createElement("tbody");
      block.themes.forEach(function (th, idx) {
        var tr = document.createElement("tr");
        tr.innerHTML =
          "<td>" +
          escapeHtml(th.label) +
          "</td><td>" +
          escapeHtml(String(th.count)) +
          "</td><td>" +
          escapeHtml(
            th.share && th.share.percentage != null
              ? th.share.percentage + "%"
              : "—"
          ) +
          "</td>";
        var tdBtn = document.createElement("td");
        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn ghost btn-sm";
        btn.textContent = "Исходные ответы";
        var detailId = "theme-" + qn + "-" + idx;
        btn.addEventListener("click", function () {
          var el = document.getElementById(detailId);
          if (!el) return;
          el.hidden = !el.hidden;
          btn.textContent = el.hidden ? "Исходные ответы" : "Скрыть";
        });
        tdBtn.appendChild(btn);
        tr.appendChild(tdBtn);
        tbody.appendChild(tr);

        var trD = document.createElement("tr");
        trD.className = "theme-sources";
        var tdD = document.createElement("td");
        tdD.colSpan = 4;
        tdD.id = detailId;
        tdD.hidden = true;
        var html = (th.sources || [])
          .map(function (s) {
            return (
              "<div class='raw-block'><span class='muted'>" +
              escapeHtml(s.created_at_display || "") +
              "</span><p>" +
              escapeHtml(s.text || "—") +
              "</p></div>"
            );
          })
          .join("");
        tdD.innerHTML = html || "<p class='muted'>Нет исходных ответов.</p>";
        trD.appendChild(tdD);
        tbody.appendChild(trD);
      });
      table.appendChild(tbody);
      card.appendChild(table);
      root.appendChild(card);
    });
  }

  function currentAnswersTable() {
    var cab = state.cabinet;
    if (!cab) return null;
    if (state.filter === "all") return cab.answers_all;
    return (cab.answers_by_question || {})[state.filter] || null;
  }

  function renderAnswers() {
    var table = currentAnswersTable();
    var head = document.getElementById("resp-head");
    var body = document.getElementById("resp-body");
    var empty = document.getElementById("resp-empty");
    head.innerHTML = "";
    body.innerHTML = "";
    if (!table || !table.rows || !table.rows.length) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;

    var cols = table.columns || [];
    var hr = document.createElement("tr");
    var baseHeads =
      state.filter === "all"
        ? ["№", "Дата", "Ответы", "Признаки"]
        : ["№", "Дата", "Ответ респондента"];
    baseHeads.forEach(function (t) {
      var th = document.createElement("th");
      th.textContent = t;
      hr.appendChild(th);
    });
    if (state.filter !== "all") {
      cols.forEach(function (c) {
        var th = document.createElement("th");
        th.className = "col-feat";
        th.textContent = c.label;
        th.title = c.label;
        hr.appendChild(th);
      });
    }
    head.appendChild(hr);

    table.rows.forEach(function (row) {
      var tr = document.createElement("tr");
      var tdNum = document.createElement("td");
      tdNum.textContent = String(row.num);
      tr.appendChild(tdNum);

      var tdDate = document.createElement("td");
      tdDate.className = "col-date";
      tdDate.textContent = row.created_at_display || "—";
      tr.appendChild(tdDate);

      if (state.filter === "all") {
        var tdAns = document.createElement("td");
        tdAns.className = "col-answers";
        var parts = [
          ["Вопрос 1", row.answers && row.answers.q1],
          ["Вопрос 2", row.answers && row.answers.q2],
          ["Вопрос 3", row.answers && row.answers.q3],
          ["Вопрос 4", row.answers && row.answers.q4]
        ];
        tdAns.innerHTML = parts
          .map(function (p) {
            return (
              "<div class='ans-snip'><strong>" +
              escapeHtml(p[0]) +
              "</strong> " +
              escapeHtml((p[1] || "—").slice(0, 160)) +
              ((p[1] || "").length > 160 ? "…" : "") +
              "</div>"
            );
          })
          .join("");
        tr.appendChild(tdAns);

        var tdTags = document.createElement("td");
        tdTags.className = "col-tags";
        (row.feature_tags || []).forEach(function (t) {
          var span = document.createElement("span");
          span.className = "tag";
          span.textContent = t;
          tdTags.appendChild(span);
        });
        if (!(row.feature_tags || []).length) tdTags.textContent = "—";
        tr.appendChild(tdTags);
      } else {
        var tdA = document.createElement("td");
        tdA.className = "col-answer";
        tdA.textContent = row.answer_text || "—";
        tr.appendChild(tdA);
        cols.forEach(function (c) {
          var td = document.createElement("td");
          td.className = "col-check";
          var on = row.cells && row.cells[c.key];
          td.textContent = on ? "✓" : "";
          if (on) td.classList.add("hit");
          tr.appendChild(td);
        });
      }
      body.appendChild(tr);
    });
  }

  function renderCross(cross) {
    var root = document.getElementById("cross-links");
    root.innerHTML = "";
    if (!cross) return;
    if (cross.note) {
      document.getElementById("cross-note").textContent = cross.note;
    }
    if (cross.contradiction && cross.contradiction.count > 0) {
      var cbox = document.createElement("div");
      cbox.className = "cross-item";
      cbox.innerHTML =
        "<p><strong>Межвопросные противоречия (методика):</strong> " +
        escapeHtml(cross.contradiction.display) +
        "</p>";
      root.appendChild(cbox);
    }
    (cross.links || []).forEach(function (link, idx) {
      var div = document.createElement("div");
      div.className = "cross-item";
      var title =
        fixTypo(link.a.title) +
        ": «" +
        link.a.label +
        "» + " +
        fixTypo(link.b.title) +
        ": «" +
        link.b.label +
        "» — " +
        link.display;
      var p = document.createElement("p");
      p.innerHTML = "<strong>" + escapeHtml(title) + "</strong>";
      div.appendChild(p);
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn ghost btn-sm";
      btn.textContent = "Показать анкеты";
      var detailId = "cross-" + idx;
      btn.addEventListener("click", function () {
        var el = document.getElementById(detailId);
        if (!el) return;
        el.hidden = !el.hidden;
        btn.textContent = el.hidden ? "Показать анкеты" : "Скрыть";
      });
      div.appendChild(btn);
      var detail = document.createElement("div");
      detail.id = detailId;
      detail.hidden = true;
      detail.className = "cross-sources";
      detail.innerHTML = (link.sources || [])
        .map(function (s) {
          return (
            "<div class='raw-block'><span class='muted'>" +
            escapeHtml(s.created_at_display || "") +
            "</span>" +
            "<p><strong>Вопрос 1.</strong> " +
            escapeHtml(s.q1 || "") +
            "</p>" +
            "<p><strong>Вопрос 2.</strong> " +
            escapeHtml(s.q2 || "") +
            "</p>" +
            "<p><strong>Вопрос 3.</strong> " +
            escapeHtml(s.q3 || "") +
            "</p>" +
            "<p><strong>Вопрос 4.</strong> " +
            escapeHtml(s.q4 || "") +
            "</p></div>"
          );
        })
        .join("");
      div.appendChild(detail);
      root.appendChild(div);
    });
    if (!(cross.links || []).length) {
      root.innerHTML = "<p class='muted'>Пока недостаточно данных для сочетаний.</p>";
    }
  }

  async function refreshCabinet() {
    var r = await api(
      "/api/admin/summary?dataset=" + encodeURIComponent(dataset())
    );
    if (!r.data.ok) return;
    state.cabinet = r.data;
    document.getElementById("total").textContent = String(r.data.total);
    document.getElementById("latest").textContent =
      r.data.latest_display || "—";
    renderThemes(r.data.themes);
    renderAnswers();
    renderCross(r.data.cross);
  }

  async function refreshSession() {
    var gate = document.getElementById("gate");
    var cabinet = document.getElementById("cabinet");
    var s = await api("/api/admin/session");
    if (!s.data.authenticated) {
      gate.hidden = false;
      cabinet.hidden = true;
      return false;
    }
    gate.hidden = true;
    cabinet.hidden = false;
    state.dataSource = s.data.data_source || "production";
    state.showTestToggle = !!s.data.show_test_toggle;
    var wrap = document.getElementById("source-wrap");
    wrap.hidden = !state.showTestToggle;
    if (state.showTestToggle) {
      document.getElementById("dataset").value = state.dataSource;
    }
    await refreshCabinet();
    return true;
  }

  document.getElementById("q-filters").addEventListener("click", function (e) {
    var btn = e.target.closest("[data-q]");
    if (!btn) return;
    state.filter = btn.getAttribute("data-q");
    Array.prototype.forEach.call(
      document.querySelectorAll("#q-filters .chip"),
      function (c) {
        c.classList.toggle("active", c === btn);
      }
    );
    renderAnswers();
  });

  document.getElementById("dataset").addEventListener("change", refreshCabinet);

  document.getElementById("btn-logout").addEventListener("click", async function () {
    await api("/api/admin/logout", { method: "POST", body: "{}" });
    window.location.reload();
  });

  document.getElementById("btn-new").addEventListener("click", function () {
    document.getElementById("thread").innerHTML = "";
  });

  document.getElementById("btn-export").addEventListener("click", async function () {
    var url =
      "/api/admin/export?format=json&dataset=" + encodeURIComponent(dataset());
    var r = await api(url);
    if (!r.data.ok) {
      alert("Выгрузка недоступна");
      return;
    }
    var blob = new Blob([JSON.stringify(r.data, null, 2)], {
      type: "application/json"
    });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "castdev0926-данные.json";
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
    addBubble(thread, r.data.answer_text || r.data.error || "Нет ответа");
    refreshCabinet();
  });

  refreshSession();
})();
