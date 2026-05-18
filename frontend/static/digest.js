const authGate = document.getElementById("auth-gate");
const digestApp = document.getElementById("digest-app");
const authStatus = document.getElementById("auth-status");
const authLinkWrap = document.getElementById("auth-link-wrap");
const authLink = document.getElementById("auth-link");
const sessionLabel = document.getElementById("session-label");
const digestStatus = document.getElementById("digest-status");
const sectionsWrap = document.getElementById("sections-wrap");
const generateBtn = document.getElementById("generate-btn");
const debugResetDbBtn = document.getElementById("debug-reset-db-btn");
const sectionTemplate = document.getElementById("section-template");

function setStatus(message, isError) {
  digestStatus.textContent = message || "";
  if (!message) {
    digestStatus.style.removeProperty("color");
    return;
  }
  digestStatus.style.color = isError ? "#b91c1c" : "#6b7280";
}

function sectionHeading(section) {
  const profileName = (section.profile_name || "").trim();
  if (profileName) {
    return profileName;
  }
  return "Profile " + section.profile_slot;
}

function scoreDisplayPercent(finalScore) {
  const raw = Number(finalScore);
  const score = Number.isFinite(raw) ? raw : 0;
  const pct = Math.max(0, Math.min(100, Math.round(score * 100)));
  return pct;
}

/** 0–3 ★ from rounded percent: &lt;55 none, 55–64 → 1, 65–74 → 2, 75+ → 3 */
function starRatingFromPercent(percent) {
  if (percent >= 75) {
    return 3;
  }
  if (percent >= 65) {
    return 2;
  }
  if (percent >= 55) {
    return 1;
  }
  return 0;
}

function starsDisplay(percent) {
  return "⭐".repeat(starRatingFromPercent(percent));
}

function renderSections(sections) {
  sectionsWrap.innerHTML = "";
  if (!sections || !sections.length) {
    return;
  }

  const withPicks = sections.filter((section) => (section.picks || []).length > 0);
  if (!withPicks.length) {
    return;
  }

  withPicks.forEach((section) => {
    const node = sectionTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".digest-section-title").textContent = sectionHeading(section);
    node.querySelector(".digest-category").textContent = section.category || "";
    const picksList = node.querySelector(".digest-picks");

    section.picks.forEach((pick, index) => {
      const item = document.createElement("li");
      item.className = "digest-pick";

      const indexSpan = document.createElement("span");
      indexSpan.className = "digest-pick-index";
      indexSpan.textContent = String(index + 1) + ".";

      const title = document.createElement("a");
      title.className = "digest-pick-title";
      title.textContent = pick.title;
      title.href = pick.pdf_url || ("https://arxiv.org/abs/" + pick.arxiv_id);
      title.target = "_blank";
      title.rel = "noreferrer";

      item.appendChild(indexSpan);
      item.appendChild(title);

      const score = document.createElement("span");
      score.className = "digest-score";
      const pct = scoreDisplayPercent(pick.final_score);
      const starCount = starRatingFromPercent(pct);
      score.textContent = starsDisplay(pct);
      if (starCount === 0) {
        score.setAttribute("aria-label", pct + "% match, no stars");
      } else {
        score.setAttribute(
          "aria-label",
          starCount + " out of 3 stars (" + pct + "% match)",
        );
      }
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
  setStatus("", false);
  try {
    const payload = await apiRequest("/daily-picks", "GET");
    renderSections(payload.sections || []);
    setStatus("", false);
  } catch (error) {
    const msg = String(error.message || error);
    if (
      error.status === 400 &&
      /at least one profile must be selected for digest generation/i.test(msg)
    ) {
      setStatus(
        "No profiles are enabled for the digest. Open Preferences, turn on “Include in digest” for at least one profile, save, then try again.",
        true,
      );
      renderSections([]);
      return;
    }
    throw error;
  }
}

async function generateDigest() {
  setStatus("", false);
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
    setStatus("", false);
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
