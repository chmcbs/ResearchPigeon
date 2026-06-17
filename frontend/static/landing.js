const form = document.getElementById("signup-form");
const statusEl = document.getElementById("signup-status");
const linkWrap = document.getElementById("signup-link-wrap");
const linkEl = document.getElementById("signup-link");

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("email").value.trim();
  setMagicLinkFormStatus(statusEl, MAGIC_LINK_SENDING_MESSAGE);
  linkWrap.classList.add("hidden");
  try {
    const payload = await apiRequest("/auth/magic-link/request", "POST", { email });
    if (payload.magic_link) {
      setMagicLinkFormStatus(statusEl, MAGIC_LINK_INBOX_MESSAGE);
      linkEl.href = payload.magic_link;
      linkWrap.classList.remove("hidden");
    } else {
      setMagicLinkFormStatus(statusEl, MAGIC_LINK_INBOX_MESSAGE);
    }
  } catch (error) {
    setMagicLinkFormStatus(statusEl, formatMagicLinkError(error));
  }
});
