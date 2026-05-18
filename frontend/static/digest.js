const authGate = document.getElementById("auth-gate");
const digestApp = document.getElementById("digest-app");
const authStatus = document.getElementById("auth-status");
const authLinkWrap = document.getElementById("auth-link-wrap");
const authLink = document.getElementById("auth-link");
const sessionLabel = document.getElementById("session-label");
const digestStatus = document.getElementById("digest-status");
const emptyState = document.getElementById("digest-empty");
const sectionsWrap = document.getElementById("sections-wrap");
const generateBtn = document.getElementById("generate-btn");
const debugResetDbBtn = document.getElementById("debug-reset-db-btn");
const sectionTemplate = document.getElementById("section-template");

function setStatus(message, isError) {
  digestStatus.textContent = message;
  digestStatus.style.color = isError ? "#b91c1c" : "#6b7280";
}

function sectionHeading(section) {
  const profileName = (section.profile_name || "").trim();
  if (profileName) {
    return profileName;
  }
  return "Profile " + section.profile_slot;
}

function renderSections(sections) {
  sectionsWrap.innerHTML = "";
  if (!sections || !sections.length) {
    emptyState.classList.remove("hidden");
    return;
  }

  const withPicks = sections.filter((section) => (section.picks || []).length > 0);
  if (!withPicks.length) {
    emptyState.classList.remove("hidden");
    return;
  }
  emptyState.classList.add("hidden");

  withPicks.forEach((section) => {
    const node = sectionTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".digest-section-title").textContent = sectionHeading(section);
    node.querySelector(".digest-category").textContent = section.category || "";
    node.querySelector(".digest-interest").textContent = section.interest_sentence || "";
    const picksList = node.querySelector(".digest-picks");

    section.picks.forEach((pick) => {
      const item = document.createElement("li");
      item.className = "digest-pick";

      const title = document.createElement("a");
      title.className = "digest-pick-title";
      title.textContent = pick.title;
      title.href = pick.pdf_url || ("https://arxiv.org/abs/" + pick.arxiv_id);
      title.target = "_blank";
      title.rel = "noreferrer";
      item.appendChild(title);

      const score = document.createElement("span");
      score.className = "digest-score";
      const value = Number(pick.final_score);
      score.textContent = "score: " + (Number.isFinite(value) ? value.toFixed(4) : pick.final_score);
      item.appendChild(score);

      picksList.appendChild(item);
    });

    sectionsWrap.appendChild(node);
  });
}

async function checkSession() {
  const session = await apiRequest("/auth/session", "GET");
  if (!session.authenticated) {
    sessionLabel.textContent = "Not signed in";
    authGate.classList.remove("hidden");
    digestApp.classList.add("hidden");
    return false;
  }
  sessionLabel.textContent = session.email;
  authGate.classList.add("hidden");
  digestApp.classList.remove("hidden");
  return true;
}

async function loadDigest() {
  setStatus("Loading latest digest...", false);
  const payload = await apiRequest("/daily-picks", "GET");
  renderSections(payload.sections || []);
  if (payload.needs_generation) {
    setStatus("No picks found yet. Generate a digest to preview content.", false);
    return;
  }
  setStatus("Loaded latest digest sections.", false);
}

async function generateDigest() {
  setStatus("Generating digest...", false);
  generateBtn.disabled = true;
  try {
    const profilesPayload = await apiRequest("/profiles", "GET");
    const profileIds = (profilesPayload.profiles || [])
      .filter((p) => p.digest_enabled)
      .map((p) => p.profile_id);
    if (!profileIds.length) {
      throw new Error("Turn on at least one profile for the digest in Preferences.");
    }
    await apiRequest("/daily-picks/generate", "POST", { profile_ids: profileIds });
    await loadDigest();
    setStatus("Digest generated and refreshed.", false);
  } finally {
    generateBtn.disabled = false;
  }
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
      authLink.href = payload.magic_link + "&next=/digest";
      authLinkWrap.classList.remove("hidden");
    }
  } catch (error) {
    authStatus.textContent = String(error.message || error);
  }
});

generateBtn.addEventListener("click", async () => {
  try {
    await generateDigest();
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
});

debugResetDbBtn.addEventListener("click", async () => {
  var ok = window.confirm(
    "Delete ALL papers, ingestion runs, recommendations, and feedback from the database?\n\n" +
      "Profiles, keywords, and profile preferences are kept.\n\n" +
      "Requires ALLOW_DEBUG_DIGEST_DATA_RESET=1 on the server.",
  );
  if (!ok) {
    return;
  }
  debugResetDbBtn.disabled = true;
  setStatus("Resetting paper and feedback data...", false);
  try {
    var result = await apiRequest("/debug/digest-data/reset", "POST");
    await loadDigest();
    setStatus(
      "Debug reset complete. Removed " +
        result.deleted_runs +
        " run(s) and " +
        result.deleted_papers +
        " paper(s). Profiles and keywords unchanged.",
      false,
    );
  } catch (error) {
    setStatus(String(error.message || error), true);
  } finally {
    debugResetDbBtn.disabled = false;
  }
});

async function init() {
  try {
    const authenticated = await checkSession();
    if (!authenticated) {
      return;
    }
    await loadDigest();
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

init();
