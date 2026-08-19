const COPY = {
  unsubscribed: {
    title: "Successfully unsubscribed.",
    message: "You will no longer receive daily digest emails.",
  },
  confirm: {
    title: "Unsubscribe from digest emails?",
    message: "Click the button below to stop daily digest emails. Your profiles will be kept.",
  },
  invalid: {
    title: "Invalid link.",
    message: "Sign in using the button below to update your email settings.",
  },
};

function initEmailPreferencesPage() {
  const params = new URLSearchParams(window.location.search);
  const token = params.get("token") || "";
  let status = params.get("status") || "invalid";
  if (status === "confirm" && !token) {
    status = "invalid";
  }
  const copy = COPY[status] || COPY.invalid;

  document.getElementById("email-preferences-title").textContent = copy.title;
  document.getElementById("email-preferences-message").textContent = copy.message;

  const form = document.getElementById("email-unsubscribe-form");
  const tokenInput = document.getElementById("email-unsubscribe-token");
  if (form && tokenInput && status === "confirm") {
    tokenInput.value = token;
    form.classList.remove("hidden");
  }
}

initEmailPreferencesPage();
