const MAGIC_LINK_SENDING_MESSAGE = "Sending magic link...";
const MAGIC_LINK_INBOX_MESSAGE = "Check your inbox for the confirmation link!";
const MAGIC_LINK_RATE_LIMIT_MESSAGE =
  "Too many sign-in attempts. Please try again later.";
const MAGIC_LINK_INVALID_EMAIL_MESSAGE = "Please enter a valid email address.";
const MAGIC_LINK_EMAIL_TOO_LONG_MESSAGE = "That email address is too long.";
const MAGIC_LINK_EMAIL_UNAVAILABLE_MESSAGE =
  "Sign-in email is temporarily unavailable. Please try again later.";
const MAGIC_LINK_EMAIL_SEND_FAILED_MESSAGE =
  "We couldn't send the sign-in email. Please try again in a few minutes.";
const MAGIC_LINK_SERVER_ERROR_MESSAGE =
  "Something went wrong on our side. Please try again later.";
const MAGIC_LINK_NETWORK_ERROR_MESSAGE =
  "Couldn't reach the server. Check your connection and try again.";
const MAGIC_LINK_GENERIC_ERROR_MESSAGE =
  "Something went wrong. Please try again later.";

const MAGIC_LINK_USER_ERROR_MESSAGES = new Set([
  MAGIC_LINK_RATE_LIMIT_MESSAGE,
  MAGIC_LINK_INVALID_EMAIL_MESSAGE,
  MAGIC_LINK_EMAIL_TOO_LONG_MESSAGE,
  MAGIC_LINK_EMAIL_UNAVAILABLE_MESSAGE,
  MAGIC_LINK_EMAIL_SEND_FAILED_MESSAGE,
  MAGIC_LINK_SERVER_ERROR_MESSAGE,
  MAGIC_LINK_NETWORK_ERROR_MESSAGE,
  MAGIC_LINK_GENERIC_ERROR_MESSAGE,
]);

function isMagicLinkStatusMessage(message) {
  return (
    message === MAGIC_LINK_SENDING_MESSAGE ||
    message === MAGIC_LINK_INBOX_MESSAGE
  );
}

function formatMagicLinkError(error) {
  if (!error) {
    return MAGIC_LINK_GENERIC_ERROR_MESSAGE;
  }
  if (error.status === 429) {
    return MAGIC_LINK_RATE_LIMIT_MESSAGE;
  }

  const message = String(error.message || error).trim();
  const lower = message.toLowerCase();

  if (MAGIC_LINK_USER_ERROR_MESSAGES.has(message)) {
    return message;
  }

  if (/fail(ed)? to fetch|network error|load failed/i.test(message)) {
    return MAGIC_LINK_NETWORK_ERROR_MESSAGE;
  }
  if (error.status === 503) {
    if (lower.includes("send")) {
      return MAGIC_LINK_EMAIL_SEND_FAILED_MESSAGE;
    }
    return MAGIC_LINK_EMAIL_UNAVAILABLE_MESSAGE;
  }
  if (error.status >= 500) {
    return MAGIC_LINK_SERVER_ERROR_MESSAGE;
  }
  if (
    lower.includes("email must be valid") ||
    lower.includes("valid email") ||
    error.status === 422
  ) {
    return MAGIC_LINK_INVALID_EMAIL_MESSAGE;
  }
  if (lower.includes("too long")) {
    return MAGIC_LINK_EMAIL_TOO_LONG_MESSAGE;
  }
  if (lower.includes("not configured") || lower.includes("unavailable")) {
    return MAGIC_LINK_EMAIL_UNAVAILABLE_MESSAGE;
  }
  if (lower.includes("failed to send") || lower.includes("couldn't send")) {
    return MAGIC_LINK_EMAIL_SEND_FAILED_MESSAGE;
  }
  if (lower.includes("database error")) {
    return MAGIC_LINK_SERVER_ERROR_MESSAGE;
  }
  if (/^request failed \(\d+\)$/i.test(message)) {
    return MAGIC_LINK_GENERIC_ERROR_MESSAGE;
  }

  return MAGIC_LINK_GENERIC_ERROR_MESSAGE;
}

function setMagicLinkFormStatus(statusEl, message) {
  statusEl.textContent = message;
  const isStatus = isMagicLinkStatusMessage(message);
  statusEl.classList.toggle("is-status", isStatus);
  statusEl.classList.toggle("is-error", Boolean(message) && !isStatus);
}

function setPageStatus(statusEl, message, isError) {
  statusEl.textContent = message || "";
  if (!message) {
    statusEl.style.removeProperty("color");
    return;
  }
  statusEl.style.color = isError ? "#b91c1c" : "#1f2937";
}

function setDebugControlsVisible(canAccess) {
  document.querySelectorAll("[data-debug-admin]").forEach(function (el) {
    el.classList.toggle("hidden", !canAccess);
  });
}

async function checkAuthenticatedSession({ sessionLabelEl, authGateEl, appEl }) {
  try {
    const session = await apiRequest("/auth/session", "GET");
    setDebugControlsVisible(Boolean(session.can_debug_access));
    if (!session.authenticated) {
      bindSessionMenu(sessionLabelEl, { authenticated: false });
      authGateEl.classList.remove("hidden");
      appEl.classList.add("hidden");
      return false;
    }
    bindSessionMenu(sessionLabelEl, {
      authenticated: true,
      email: session.email,
    });
    authGateEl.classList.add("hidden");
    appEl.classList.remove("hidden");
    return session;
  } catch (_error) {
    setDebugControlsVisible(false);
    bindSessionMenu(sessionLabelEl, { authenticated: false });
    authGateEl.classList.remove("hidden");
    appEl.classList.add("hidden");
    return false;
  }
}

function bindSessionMenu(sessionLabelEl, { authenticated, email }) {
  const root = sessionLabelEl.closest(".session-menu");
  const panel = root ? root.querySelector(".session-menu-panel") : null;
  const logoutBtn = root ? root.querySelector(".session-logout-btn") : null;
  if (!root || !panel || !logoutBtn) {
    sessionLabelEl.textContent = authenticated ? email : "Not signed in";
    return;
  }

  if (!authenticated) {
    sessionLabelEl.disabled = true;
    sessionLabelEl.textContent = "Not signed in";
    panel.classList.add("hidden");
    return;
  }

  sessionLabelEl.disabled = false;
  sessionLabelEl.textContent = email;

  if (root.dataset.bound === "1") {
    return;
  }
  root.dataset.bound = "1";

  sessionLabelEl.addEventListener("click", function (event) {
    event.stopPropagation();
    panel.classList.toggle("hidden");
  });

  logoutBtn.addEventListener("click", async function () {
    try {
      await apiRequest("/auth/logout", "POST");
      window.location.href = "/";
    } catch (error) {
      panel.classList.add("hidden");
      window.alert(String(error.message || error));
    }
  });

  if (!document.documentElement.dataset.sessionMenuDismissBound) {
    document.addEventListener("click", function () {
      document.querySelectorAll(".session-menu-panel").forEach(function (el) {
        el.classList.add("hidden");
      });
    });
    document.documentElement.dataset.sessionMenuDismissBound = "1";
  }
}

function bindMagicLinkForm({ formEl, statusEl, linkWrapEl, linkEl, nextPath = "" }) {
  formEl.addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("auth-email").value.trim();
    setMagicLinkFormStatus(statusEl, MAGIC_LINK_SENDING_MESSAGE);
    linkWrapEl.classList.add("hidden");
    try {
      const payload = await apiRequest("/auth/magic-link/request", "POST", { email });
      setMagicLinkFormStatus(statusEl, MAGIC_LINK_INBOX_MESSAGE);
      if (payload.magic_link) {
        linkEl.href = nextPath
          ? `${payload.magic_link}&next=${encodeURIComponent(nextPath)}`
          : payload.magic_link;
        linkWrapEl.classList.remove("hidden");
      }
    } catch (error) {
      setMagicLinkFormStatus(statusEl, formatMagicLinkError(error));
    }
  });
}

async function refreshDebugAccess() {
  try {
    const session = await apiRequest("/auth/session", "GET");
    setDebugControlsVisible(Boolean(session.can_debug_access));
  } catch (_error) {
    setDebugControlsVisible(false);
  }
}

refreshDebugAccess();
