(function () {
  "use strict";

  const guestItems = document.querySelectorAll("[data-auth-guest]");
  const userLabel = document.querySelector("[data-auth-user]");
  const logoutButton = document.querySelector("[data-auth-logout]");

  if (!guestItems.length && !userLabel && !logoutButton) return;

  fetch("/api/auth/me")
    .then((response) => response.ok ? response.json() : { authenticated: false })
    .then((session) => {
      const signedIn = Boolean(session.authenticated);
      guestItems.forEach((item) => {
        item.hidden = signedIn;
      });
      if (userLabel) {
        userLabel.hidden = !signedIn;
        userLabel.textContent = signedIn ? `${session.name}님` : "";
      }
      if (logoutButton) logoutButton.hidden = !signedIn;
    })
    .catch(() => {});

  if (logoutButton) {
    logoutButton.addEventListener("click", () => {
      fetch("/api/auth/logout", { method: "POST" })
        .finally(() => {
          window.location.href = "/login.html";
        });
    });
  }
})();
