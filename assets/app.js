/**
 * Лаборатория влияния — anonymous castdev survey
 * Step flow: Intro → Q1 → Q2 → Q3 → Q4 → (submit stub)
 * No mailto, no fetch, no storage, no trackers.
 *
 * Future (not wired in this build):
 *   POST /api/castdev  with JSON { q1, q2, q3, q4 }
 *   On confirmed success → show #screen-success, then redirect
 *     to https://labinfluences.ru/ after 5 seconds
 *   On error → show #screen-error, keep answers, no redirect
 */

(function () {
  "use strict";

  var REDIRECT_URL = "https://labinfluences.ru/";
  var REDIRECT_DELAY_MS = 5000;

  var SCREENS = ["intro", "q1", "q2", "q3", "q4", "success", "error"];
  var QUESTION_ORDER = ["q1", "q2", "q3", "q4"];

  var current = "intro";
  var transitioning = false;
  var redirectTimer = null;

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

  /**
   * Prepared for future confirmed-success path only.
   * Must NOT be called until backend returns success.
   */
  function showSuccessAndScheduleRedirect() {
    setScreen("success", { force: true });
    if (redirectTimer) {
      window.clearTimeout(redirectTimer);
    }
    redirectTimer = window.setTimeout(function () {
      window.location.href = REDIRECT_URL;
    }, REDIRECT_DELAY_MS);
  }

  /**
   * Prepared for future submit failure. Keeps q1–q4. No redirect.
   */
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

  /* Helpers reserved for a later backend wiring pass — not used by current UI */
  window.CastdevSurvey = {
    showSuccessAndScheduleRedirect: showSuccessAndScheduleRedirect,
    showErrorScreen: showErrorScreen,
    REDIRECT_URL: REDIRECT_URL
  };
})();
