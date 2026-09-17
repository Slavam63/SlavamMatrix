(() => {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const revealNodes = document.querySelectorAll("[data-reveal]");
  if (!reduceMotion && "IntersectionObserver" in window) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.setAttribute("data-inview", "");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.18, rootMargin: "0px 0px -8% 0px" }
    );
    revealNodes.forEach((node) => observer.observe(node));
  } else {
    revealNodes.forEach((node) => node.setAttribute("data-inview", ""));
  }

  const form = document.getElementById("contact-form");
  const status = document.getElementById("form-status");
  if (!form || !status) return;

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;

    const data = new FormData(form);
    const name = String(data.get("name") || "").trim();
    const email = String(data.get("email") || "").trim();
    const message = String(data.get("message") || "").trim();

    const subject = encodeURIComponent(`CASTDEV0926 — запрос от ${name}`);
    const body = encodeURIComponent(
      `Имя: ${name}\nEmail: ${email}\n\nЗадача:\n${message}`
    );

    status.hidden = false;
    status.textContent = "Открываем почтовый клиент…";
    window.location.href = `mailto:hello@castdev0926.labinfluences.su?subject=${subject}&body=${body}`;
  });
})();
