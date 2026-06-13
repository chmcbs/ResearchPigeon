const COPY = {
  unsubscribed: {
    title: "Successfully unsubscribed.",
    message: "You will not receive digest emails from arXiv Assistant.",
    showResubscribe: true,
  },
  resubscribed: {
    title: "Successfully resubscribed.",
    message: "You will receive daily digests for your active profiles.",
    showResubscribe: false,
  },
  invalid: {
    title: "Invalid link.",
    message: "Sign in at Manage profiles to update your email settings.",
    showResubscribe: false,
  },
};

function readQueryParams() {
  return new URLSearchParams(window.location.search);
}

function initEmailPreferencesPage() {
  const params = readQueryParams();
  const status = params.get("status") || "invalid";
  const token = params.get("token") || "";
  const copy = COPY[status] || COPY.invalid;

  const titleEl = document.getElementById("email-preferences-title");
  const messageEl = document.getElementById("email-preferences-message");
  const actionsEl = document.getElementById("email-preferences-actions");
  const resubscribeEl = document.getElementById("email-preferences-resubscribe");

  titleEl.textContent = copy.title;
  messageEl.textContent = copy.message;

  if (copy.showResubscribe && token) {
    actionsEl.classList.remove("hidden");
    resubscribeEl.href = `/email/resubscribe?token=${encodeURIComponent(token)}`;
    return;
  }

  actionsEl.classList.add("hidden");
}

initEmailPreferencesPage();
