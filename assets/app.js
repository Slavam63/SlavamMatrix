/**
 * Лаборатория влияния — anonymous castdev survey
 * Step flow: Intro → Q1 → Q2 → Q3 → Q4 → (submit stub)
 * No mailto, no fetch, no storage, no trackers.
 */

(function () {
  "use strict";

  var REDIRECT_URL = "https://labinfluences.ru/";
  var REDIRECT_DELAY_MS = 5000;
  var SHARE_TITLE = "Лаборатория влияния — кастдев";

  var SCREENS = ["intro", "q1", "q2", "q3", "q4", "success", "error"];
  var QUESTION_ORDER = ["q1", "q2", "q3", "q4"];

  var current = "intro";
  var transitioning = false;
  var redirectTimer = null;
  var shareStatusTimer = null;

  var app = document.getElementById("app");
  if (!app) return;

  function $(id) {
    return document.getElementById(id);
  }

  function screenEl(name) {
    return $("screen-" + name);
  }

  function getAnswer(qid) {
    var el = $(qid);
    return el ? el.value : "";
  }

  function isFilled(qid) {
    return getAnswer(qid).trim().length > 0;
  }

  function showError(qid, visible) {
    var err = $(qid + "-error");
    var input = $(qid);
    if (err) {
      err.hidden = !visible;
    }
    if (input) {
      input.classList.toggle("is-invalid", !!visible);
      if (visible) {
        input.setAttribute("aria-invalid", "true");
      } else {
        input.removeAttribute("aria-invalid");
      }
    }
  }

  function clearSubmitStatus() {
    var status = $("submit-status");
    if (status) {
      status.hidden = true;
      status.textContent = "";
    }
  }

  function showSubmitStubMessage() {
    var status = $("submit-status");
    if (!status) return;
    status.hidden = false;
    status.textContent =
      "Форма готова. Отправка ответов будет подключена перед запуском опроса.";
  }

  function clearShareStatus() {
    var status = $("share-status");
    if (!status) return;
    status.hidden = true;
    status.textContent = "";
    status.classList.remove("share-status--url");
  }

  function showShareCopiedMessage() {
    var status = $("share-status");
    if (!status) return;
    if (shareStatusTimer) {
      window.clearTimeout(shareStatusTimer);
      shareStatusTimer = null;
    }
    status.classList.remove("share-status--url");
    status.hidden = false;
    status.textContent = "Ссылка скопирована.";
    shareStatusTimer = window.setTimeout(function () {
      clearShareStatus();
      shareStatusTimer = null;
    }, 4000);
  }

  function showShareUrlForManualCopy(url) {
    var status = $("share-status");
    if (!status) return;
    if (shareStatusTimer) {
      window.clearTimeout(shareStatusTimer);
      shareStatusTimer = null;
    }
    status.classList.add("share-status--url");
    status.hidden = false;
    status.textContent = "";
    var label = document.createElement("span");
    label.textContent = "Скопируйте ссылку: ";
    var link = document.createElement("input");
    link.type = "text";
    link.readOnly = true;
    link.className = "share-status__url";
    link.value = url;
    link.setAttribute("aria-label", "Ссылка на страницу");
    status.appendChild(label);
    status.appendChild(link);
    window.setTimeout(function () {
      link.focus();
      link.select();
    }, 0);
  }

  function copyWithExecCommand(url) {
    var ta = document.createElement("textarea");
    ta.value = url;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "0";
    ta.style.left = "0";
    ta.style.width = "1px";
    ta.style.height = "1px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(ta);
    return ok;
  }

  function copyPageUrl(url) {
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      return navigator.clipboard.writeText(url).then(
        function () {
          showShareCopiedMessage();
        },
        function () {
          if (copyWithExecCommand(url)) {
            showShareCopiedMessage();
          } else {
            showShareUrlForManualCopy(url);
          }
        }
      );
    }
    if (copyWithExecCommand(url)) {
      showShareCopiedMessage();
      return Promise.resolve();
    }
    showShareUrlForManualCopy(url);
    return Promise.resolve();
  }

  function handleShare() {
    var url = window.location.href;

    if (typeof navigator.share === "function") {
      try {
        var sharePromise = navigator.share({
          title: SHARE_TITLE,
          url: url
        });
        if (sharePromise && typeof sharePromise.then === "function") {
          sharePromise.then(
            function () {},
            function (err) {
              if (err && err.name === "AbortError") return;
              copyPageUrl(url);
            }
          );
          return;
        }
        return;
      } catch (err) {
        if (err && err.name === "AbortError") return;
        copyPageUrl(url);
        return;
      }
    }

    copyPageUrl(url);
  }

  function validateCurrentQuestion(qid) {
    if (!isFilled(qid)) {
      showError(qid, true);
      var input = $(qid);
      if (input) input.focus();
      return false;
    }
    showError(qid, false);
    return true;
  }

  function allAnswersFilled() {
    return QUESTION_ORDER.every(isFilled);
  }

  function setScreen(name, options) {
    options = options || {};
    if (transitioning && !options.force) return;
    if (SCREENS.indexOf(name) === -1) return;
    if (name === current && !options.force) return;

    var fromEl = screenEl(current);
    var toEl = screenEl(name);
    if (!toEl) return;

    var reduceMotion =
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function activate() {
      SCREENS.forEach(function (s) {
        var el = screenEl(s);
        if (!el) return;
        var active = s === name;
        el.hidden = !active;
        el.classList.toggle("screen--active", active);
        el.classList.remove("is-leaving");
      });
      current = name;
      transitioning = false;

      if (name.charAt(0) === "q" && name.length === 2) {
        var ta = $(name);
        if (ta && options.focusField !== false) {
          window.setTimeout(function () {
            ta.focus();
          }, reduceMotion ? 0 : 50);
        }
      }
    }

    if (reduceMotion || !fromEl || fromEl.hidden) {
      activate();
      return;
    }

    transitioning = true;
    fromEl.classList.add("is-leaving");

    window.setTimeout(function () {
      fromEl.classList.remove("is-leaving");
      fromEl.classList.remove("screen--active");
      fromEl.hidden = true;
      activate();
    }, 220);
  }

  function goNext(from) {
    if (from === "intro") {
      clearSubmitStatus();
      clearShareStatus();
      setScreen("q1");
      return;
    }
    if (!validateCurrentQuestion(from)) return;
    clearSubmitStatus();
    var idx = QUESTION_ORDER.indexOf(from);
    if (idx >= 0 && idx < QUESTION_ORDER.length - 1) {
      setScreen(QUESTION_ORDER[idx + 1]);
    }
  }

  function goBack(from) {
    clearSubmitStatus();
    if (from === "q1") {
      setScreen("intro");
      return;
    }
    var idx = QUESTION_ORDER.indexOf(from);
    if (idx > 0) {
      setScreen(QUESTION_ORDER[idx - 1], { focusField: false });
    }
  }

  /**
   * Current build: NO real submit, NO network call, NO success, NO redirect.
   * Answers remain in the DOM only.
   */
  function handleSubmitStub() {
    if (!validateCurrentQuestion("q4")) return;

    if (!allAnswersFilled()) {
      for (var i = 0; i < QUESTION_ORDER.length; i++) {
        if (!isFilled(QUESTION_ORDER[i])) {
          showError(QUESTION_ORDER[i], true);
          setScreen(QUESTION_ORDER[i]);
          return;
        }
      }
    }

    showSubmitStubMessage();
  }

  function showSuccessAndScheduleRedirect() {
    setScreen("success", { force: true });
    if (redirectTimer) {
      window.clearTimeout(redirectTimer);
    }
    redirectTimer = window.setTimeout(function () {
      window.location.href = REDIRECT_URL;
    }, REDIRECT_DELAY_MS);
  }

  function showErrorScreen() {
    if (redirectTimer) {
      window.clearTimeout(redirectTimer);
      redirectTimer = null;
    }
    setScreen("error", { force: true });
  }

  function retryFromError() {
    setScreen("q4", { force: true });
  }

  QUESTION_ORDER.forEach(function (qid) {
    var input = $(qid);
    if (!input) return;
    input.addEventListener("input", function () {
      if (input.value.trim()) {
        showError(qid, false);
      }
    });
  });

  app.addEventListener("click", function (event) {
    var btn = event.target.closest("[data-action]");
    if (!btn) return;

    var action = btn.getAttribute("data-action");
    var from = btn.getAttribute("data-from");

    if (action === "start") {
      goNext("intro");
      return;
    }
    if (action === "share") {
      handleShare();
      return;
    }
    if (action === "next" && from) {
      goNext(from);
      return;
    }
    if (action === "back" && from) {
      goBack(from);
      return;
    }
    if (action === "submit") {
      handleSubmitStub();
      return;
    }
    if (action === "retry") {
      retryFromError();
    }
  });

  window.CastdevSurvey = {
    showSuccessAndScheduleRedirect: showSuccessAndScheduleRedirect,
    showErrorScreen: showErrorScreen,
    REDIRECT_URL: REDIRECT_URL
  };
})();
