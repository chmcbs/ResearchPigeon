const authGate = document.getElementById("auth-gate");
const feedbackApp = document.getElementById("feedback-app");
const authStatus = document.getElementById("auth-status");
const authLinkWrap = document.getElementById("auth-link-wrap");
const authLink = document.getElementById("auth-link");
const sessionLabel = document.getElementById("session-label");
const feedbackStatus = document.getElementById("feedback-status");
const feedList = document.getElementById("feed-list");
const likedList = document.getElementById("liked-list");
const dislikedList = document.getElementById("disliked-list");

function setStatus(message, isError) {
  feedbackStatus.textContent = message || "";
  if (!message) {
    feedbackStatus.style.removeProperty("color");
    return;
  }
  feedbackStatus.style.color = isError ? "#b91c1c" : "#6b7280";
}

function formatGeneratedDate(value) {
  if (!value) {
    return "\u2014";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "\u2014";
  }
  return parsed.toLocaleDateString("en-GB", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
  });
}

function scoreDisplayPercent(finalScore) {
  const raw = Number(finalScore);
  const score = Number.isFinite(raw) ? raw : 0;
  return Math.max(0, Math.min(100, Math.round(score * 100)));
}

async function submitFeedback(item, label) {
  setStatus("", false);
  await apiRequest("/api/feedback", "POST", {
    profile_id: item.profile_id,
    arxiv_id: item.arxiv_id,
    label: label,
  });
  await loadFeedbackHub();
}

async function removeFeedback(item) {
  setStatus("", false);
  await apiRequest("/api/feedback", "DELETE", {
    profile_id: item.profile_id,
    arxiv_id: item.arxiv_id,
  });
  await loadFeedbackHub();
}

function createVoteButtons(item, section) {
  const wrap = document.createElement("div");
  wrap.className = "feedback-vote-btns";

  const likeBtn = document.createElement("button");
  likeBtn.type = "button";
  likeBtn.className = "feedback-vote-btn";
  likeBtn.textContent = "\ud83d\udc4d";
  likeBtn.setAttribute("aria-label", "Like");
  if (section === "liked") {
    likeBtn.classList.add("is-active");
    likeBtn.setAttribute("aria-pressed", "true");
  }

  const dislikeBtn = document.createElement("button");
  dislikeBtn.type = "button";
  dislikeBtn.className = "feedback-vote-btn";
  dislikeBtn.textContent = "\ud83d\udc4e";
  dislikeBtn.setAttribute("aria-label", "Dislike");
  if (section === "disliked") {
    dislikeBtn.classList.add("is-active");
    dislikeBtn.setAttribute("aria-pressed", "true");
  }

  function wire(btn, label, toggleOff) {
    btn.addEventListener("click", async () => {
      if (btn.disabled) {
        return;
      }
      likeBtn.disabled = true;
      dislikeBtn.disabled = true;
      try {
        if (toggleOff) {
          await removeFeedback(item);
        } else {
          await submitFeedback(item, label);
        }
      } catch (error) {
        setStatus(String(error.message || error), true);
        likeBtn.disabled = false;
        dislikeBtn.disabled = false;
      }
    });
  }

  wire(likeBtn, "like", section === "liked");
  wire(dislikeBtn, "dislike", section === "disliked");

  wrap.appendChild(likeBtn);
  wrap.appendChild(dislikeBtn);
  return wrap;
}

function renderList(container, items, emptyText, section) {
  container.innerHTML = "";
  if (!items.length) {
    const p = document.createElement("p");
    p.className = "muted feedback-hub-empty";
    p.textContent = emptyText;
    container.appendChild(p);
    return;
  }

  items.forEach((item) => {
    const entry = document.createElement("div");
    entry.className = "feedback-hub-entry";

    const main = document.createElement("div");
    main.className = "feedback-hub-entry-main";

    const title = document.createElement("a");
    title.className = "feedback-item-text";
    title.textContent = item.title;
    title.href = item.pdf_url || "https://arxiv.org/pdf/" + item.arxiv_id;
    title.target = "_blank";
    title.rel = "noreferrer";

    const footer = document.createElement("div");
    footer.className = "feedback-hub-entry-footer";

    const meta = document.createElement("div");
    meta.className = "feedback-hub-meta";
    const pct = scoreDisplayPercent(item.final_score);
    meta.textContent =
      formatGeneratedDate(item.generated_at) +
      " \u00b7 " +
      item.profile_name +
      " \u00b7 " +
      pct +
      "% match";

    footer.appendChild(meta);
    footer.appendChild(createVoteButtons(item, section));

    main.appendChild(title);
    main.appendChild(footer);
    entry.appendChild(main);
    container.appendChild(entry);
  });
}

function refreshHub(payload) {
  renderList(feedList, payload.seen || [], "Nothing in your feed yet.", "feed");
  renderList(likedList, payload.liked || [], "No likes yet.", "liked");
  renderList(dislikedList, payload.disliked || [], "No dislikes yet.", "disliked");
}

async function loadFeedbackHub() {
  setStatus("", false);
  const payload = await apiRequest("/api/feedback/hub", "GET");
  refreshHub(payload);
}

async function checkSession() {
  const session = await apiRequest("/auth/session", "GET");
  if (!session.authenticated) {
    sessionLabel.textContent = "Not signed in";
    authGate.classList.remove("hidden");
    feedbackApp.classList.add("hidden");
    return false;
  }
  sessionLabel.textContent = session.email;
  authGate.classList.add("hidden");
  feedbackApp.classList.remove("hidden");
  return true;
}

document.getElementById("auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const email = document.getElementById("auth-email").value.trim();
  authStatus.textContent = "Sending magic link...";
  authLinkWrap.classList.add("hidden");
  try {
    const payload = await apiRequest("/auth/magic-link/request", "POST", { email });
    authStatus.textContent = "Check your inbox for the confirmation link.";
    if (payload.magic_link) {
      authLink.href = payload.magic_link + "&next=/feedback";
      authLinkWrap.classList.remove("hidden");
    }
  } catch (error) {
    authStatus.textContent = String(error.message || error);
  }
});

async function init() {
  try {
    const authenticated = await checkSession();
    if (!authenticated) {
      return;
    }
    await loadFeedbackHub();
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

init();
