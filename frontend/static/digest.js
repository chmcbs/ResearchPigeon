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
const GENERATE_PROGRESS_POLL_MS = 500;
let generateProgressTimer = null;

function setStatus(message, isError) {
  setPageStatus(digestStatus, message, isError);
}

function formatGenerateProgress(progress) {
  if (!progress || !progress.active) {
    return "";
  }
  // Label only in the digest UI; detail stays on GET /daily-picks/generate/progress for debugging.
  return progress.label || progress.step || "Working…";
}

function stopGenerateProgressPolling() {
  if (generateProgressTimer !== null) {
    clearInterval(generateProgressTimer);
    generateProgressTimer = null;
  }
}

function startGenerateProgressPolling() {
  stopGenerateProgressPolling();
  generateProgressTimer = setInterval(async function () {
    try {
      var progress = await apiRequest("/daily-picks/generate/progress", "GET");
      var message = formatGenerateProgress(progress);
      if (message) {
        setStatus(message, false);
      }
    } catch (_error) {
      // Ignore poll errors; the POST will surface failures.
    }
  }, GENERATE_PROGRESS_POLL_MS);
}

function sectionHeading(section) {
  const profileName = (section.profile_name || "").trim();
  if (profileName) {
    return profileName;
  }
  return "Profile " + section.profile_slot;
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

      if (pick.description) {
        const description = document.createElement("p");
        description.className = "digest-pick-description";
        description.textContent = pick.description;
        item.appendChild(description);
      }

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
  return checkAuthenticatedSession({
    sessionLabelEl: sessionLabel,
    authGateEl: authGate,
    appEl: digestApp,
  });
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
        "No profiles are enabled for the digest.",
        true,
      );
      renderSections([]);
      return;
    }
    throw error;
  }
}

async function generateDigest() {
  setStatus("Starting…", false);
  generateBtn.disabled = true;
  startGenerateProgressPolling();
  try {
    const profilesPayload = await apiRequest("/api/profiles", "GET");
    const profileIds = (profilesPayload.profiles || [])
      .filter((p) => p.digest_enabled)
      .map((p) => p.profile_id);
    if (!profileIds.length) {
      throw new Error("Select at least one profile for the digest.");
    }
    await apiRequest("/daily-picks/generate", "POST", { profile_ids: profileIds });
    const digestPayload = await apiRequest("/daily-picks", "GET");
    renderSections(digestPayload.sections || []);
    const allPicks = (digestPayload.sections || []).flatMap(function (section) {
      return section.picks || [];
    });
    if (
      allPicks.length > 0 &&
      allPicks.every(function (pick) {
        return !pick.description;
      })
    ) {
      setStatus(
        "Descriptions were not generated as LLM timed out.",
        false,
      );
    } else {
      setStatus("", false);
    }
  } finally {
    stopGenerateProgressPolling();
    generateBtn.disabled = false;
  }
}

bindMagicLinkForm({
  formEl: document.getElementById("auth-form"),
  statusEl: authStatus,
  linkWrapEl: authLinkWrap,
  linkEl: authLink,
  nextPath: "/digest",
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
      "Admin-only debug reset. Requires DEBUG_ADMIN_EMAILS on the server.",
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
