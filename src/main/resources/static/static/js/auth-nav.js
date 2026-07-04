(function () {
  "use strict";

  const guestItems = document.querySelectorAll("[data-auth-guest]");
  const userLabel = document.querySelector("[data-auth-user]");
  const logoutButton = document.querySelector("[data-auth-logout]");
  const authRequired = document.body && document.body.hasAttribute("data-auth-required");

  if (!guestItems.length && !userLabel && !logoutButton) return;

  function applySession(session) {
    const signedIn = Boolean(session.authenticated);
    if (authRequired && !signedIn) {
      window.location.replace("/login.html");
      return;
    }

    guestItems.forEach((item) => {
      item.hidden = signedIn;
    });
    if (userLabel) {
      userLabel.hidden = !signedIn;
      userLabel.textContent = signedIn ? `${session.name}님` : "";
    }
    if (logoutButton) logoutButton.hidden = !signedIn;
  }

  fetch("/api/auth/me", { credentials: "same-origin", cache: "no-store" })
    .then((response) => response.ok ? response.json() : { authenticated: false })
    .then(applySession)
    .catch(() => applySession({ authenticated: false }));

  if (logoutButton) {
    logoutButton.addEventListener("click", () => {
      fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" })
        .finally(() => {
          window.location.href = "/login.html";
        });
    });
  }
})();
