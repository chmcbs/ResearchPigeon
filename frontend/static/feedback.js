const SHOW_PAPER_DELETE_BUTTON = false;

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
const profileFilterChips = document.getElementById("profile-filter-chips");
const dateFilterChips = document.getElementById("date-filter-chips");
const feedbackNavLinks = Array.from(document.querySelectorAll(".feedback-hub-nav-link"));
const feedbackHubLayout = document.querySelector(".feedback-hub-layout");
const feedbackHubNav = document.querySelector(".feedback-hub-nav");
const feedbackHubEmpty = document.getElementById("feedback-hub-empty");
const feedbackHubIntro = document.querySelector(".feedback-hub-intro");
const feedbackHubFilters = document.querySelector(".feedback-hub-filters");
const debugResetDbBtn = document.getElementById("debug-reset-db-btn");
const feedbackSectionIds = ["feedback-feed", "feedback-liked", "feedback-disliked"];
const FEEDBACK_SECTIONS = [
  { id: "feedback-feed", key: "seen", listEl: feedList, emptyText: "Nothing in your feed yet.", section: "feed" },
  { id: "feedback-liked", key: "liked", listEl: likedList, emptyText: "No likes yet.", section: "liked" },
  {
    id: "feedback-disliked",
    key: "disliked",
    listEl: dislikedList,
    emptyText: "No dislikes yet.",
    section: "disliked",
  },
];

const DATE_FILTER_OPTIONS = [
  { id: "all", label: "All time" },
  { id: "7", label: "Last 7 days" },
  { id: "30", label: "Last 30 days" },
];

let hubPayload = null;
let profiles = [];
const selectedProfileIds = new Set();
let selectedDateFilter = "all";

function setStatus(message, isError) {
  feedbackStatus.textContent = message || "";
  if (!message) {
    feedbackStatus.style.removeProperty("color");
    return;
  }
  feedbackStatus.style.color = "#b91c1c";
}

function profileLabel(profile) {
  const name = (profile.profile_name || "").trim();
  if (name) {
    return name;
  }
  return "Profile " + profile.profile_slot;
}

function itemMatchesDateFilter(item) {
  if (selectedDateFilter === "all") {
    return true;
  }
  if (!item.generated_at) {
    return false;
  }
  const generated = new Date(item.generated_at);
  if (Number.isNaN(generated.getTime())) {
    return false;
  }
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - Number(selectedDateFilter));
  cutoff.setHours(0, 0, 0, 0);
  return generated >= cutoff;
}

function filterItems(items) {
  if (selectedProfileIds.size === 0) {
    return [];
  }
  return items.filter(
    (item) => selectedProfileIds.has(item.profile_id) && itemMatchesDateFilter(item),
  );
}

function emptyMessageForSection(defaultText) {
  if (selectedProfileIds.size === 0) {
    return "Select at least one profile.";
  }
  if (selectedDateFilter !== "all") {
    return "No papers match the current filters.";
  }
  return defaultText;
}

async function submitFeedback(item, label) {
  setStatus("", false);
  await apiRequest("/api/feedback", "POST", {
    profile_id: item.profile_id,
    arxiv_id: item.arxiv_id,
    label: label,
  });
  await loadFeedbackHub({ preserveFilters: true });
}

async function removeFeedback(item) {
  setStatus("", false);
  await apiRequest("/api/feedback", "DELETE", {
    profile_id: item.profile_id,
    arxiv_id: item.arxiv_id,
  });
  await loadFeedbackHub({ preserveFilters: true });
}

async function deletePaper(item) {
  const ok = window.confirm(
    "Permanently remove this paper from your history? It will not appear in future digests for this profile.",
  );
  if (!ok) {
    return;
  }
  setStatus("", false);
  await apiRequest("/api/papers", "DELETE", {
    profile_id: item.profile_id,
    arxiv_id: item.arxiv_id,
  });
  await loadFeedbackHub({ preserveFilters: true });
}

function createDeleteButton(item) {
  const deleteBtn = document.createElement("button");
  deleteBtn.type = "button";
  deleteBtn.className = "feedback-delete-btn";
  deleteBtn.textContent = "\ud83d\uddd1\ufe0f";
  deleteBtn.setAttribute("aria-label", "Permanently delete paper");
  deleteBtn.setAttribute("title", "Permanently delete paper");
  deleteBtn.addEventListener("click", async () => {
    if (deleteBtn.disabled) {
      return;
    }
    deleteBtn.disabled = true;
    try {
      await deletePaper(item);
    } catch (error) {
      setStatus(String(error.message || error), true);
      deleteBtn.disabled = false;
    }
  });
  return deleteBtn;
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
    p.textContent = emptyMessageForSection(emptyText);
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
      formatShortDate(item.generated_at) +
      " \u00b7 " +
      item.profile_name +
      " \u00b7 " +
      pct +
      "% match";

    footer.appendChild(meta);
    const actions = document.createElement("div");
    actions.className = "feedback-hub-entry-actions";
    actions.appendChild(createVoteButtons(item, section));
    if (SHOW_PAPER_DELETE_BUTTON) {
      actions.appendChild(createDeleteButton(item));
    }
    footer.appendChild(actions);

    main.appendChild(title);
    main.appendChild(footer);
    entry.appendChild(main);
    container.appendChild(entry);
  });
}

function getUnfilteredSectionItems(key) {
  if (!hubPayload) {
    return [];
  }
  return hubPayload[key] || [];
}

function getFilteredSectionItems(key) {
  return filterItems(getUnfilteredSectionItems(key));
}

function countTotalPapers() {
  if (!hubPayload) {
    return 0;
  }
  return (
    getUnfilteredSectionItems("seen").length +
    getUnfilteredSectionItems("liked").length +
    getUnfilteredSectionItems("disliked").length
  );
}

function updateHubLayout() {
  if (!hubPayload || !feedbackHubLayout || !feedbackHubNav) {
    return;
  }

  const totalPapers = countTotalPapers();

  if (feedbackHubEmpty) {
    feedbackHubEmpty.classList.toggle("hidden", totalPapers > 0);
  }
  if (feedbackHubIntro) {
    feedbackHubIntro.classList.toggle("hidden", totalPapers === 0);
  }
  updateFiltersVisibility();
  feedbackHubLayout.classList.toggle("hidden", totalPapers === 0);

  const showNavByVolume = totalPapers > 9;

  FEEDBACK_SECTIONS.forEach(({ id, key }) => {
    const section = document.getElementById(id);
    if (!section) {
      return;
    }
    const hasPapers = getUnfilteredSectionItems(key).length > 0;
    section.classList.toggle("hidden", !hasPapers);
  });

  feedbackNavLinks.forEach((link) => {
    const href = link.getAttribute("href") || "";
    const sectionDef = FEEDBACK_SECTIONS.find((entry) => "#" + entry.id === href);
    const showLink =
      showNavByVolume &&
      sectionDef &&
      getFilteredSectionItems(sectionDef.key).length > 0;
    link.classList.toggle("hidden", !showLink);
  });

  const anyNavLinkVisible = feedbackNavLinks.some((link) => !link.classList.contains("hidden"));
  const showNav = showNavByVolume && anyNavLinkVisible;
  feedbackHubNav.classList.toggle("hidden", !showNav);
  feedbackHubLayout.classList.toggle("is-nav-hidden", !showNav);

  if (showNav) {
    const firstVisible = feedbackNavLinks.find((link) => !link.classList.contains("hidden"));
    if (firstVisible) {
      const href = firstVisible.getAttribute("href") || "";
      setActiveNavLink(href.slice(1));
    }
  }
}

function applyFilters() {
  if (!hubPayload) {
    return;
  }
  FEEDBACK_SECTIONS.forEach(({ listEl, key, emptyText, section }) => {
    renderList(listEl, getFilteredSectionItems(key), emptyText, section);
  });
  updateHubLayout();
}

function updateFiltersVisibility() {
  if (!feedbackHubFilters) {
    return;
  }
  feedbackHubFilters.classList.toggle("hidden", countTotalPapers() === 0);
}

function renderProfileFilter() {
  profileFilterChips.innerHTML = "";
  if (!profiles.length) {
    return;
  }

  profiles.forEach((profile) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "feedback-profile-filter-chip";
    chip.textContent = profileLabel(profile);
    chip.setAttribute("aria-pressed", selectedProfileIds.has(profile.profile_id) ? "true" : "false");
    if (selectedProfileIds.has(profile.profile_id)) {
      chip.classList.add("is-selected");
    }
    chip.addEventListener("click", () => {
      if (selectedProfileIds.has(profile.profile_id)) {
        selectedProfileIds.delete(profile.profile_id);
      } else {
        selectedProfileIds.add(profile.profile_id);
      }
      renderProfileFilter();
      applyFilters();
    });
    profileFilterChips.appendChild(chip);
  });
}

function renderDateFilter() {
  dateFilterChips.innerHTML = "";

  DATE_FILTER_OPTIONS.forEach((option) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "feedback-profile-filter-chip";
    chip.textContent = option.label;
    chip.setAttribute("aria-pressed", selectedDateFilter === option.id ? "true" : "false");
    if (selectedDateFilter === option.id) {
      chip.classList.add("is-selected");
    }
    chip.addEventListener("click", () => {
      selectedDateFilter = option.id;
      renderDateFilter();
      applyFilters();
    });
    dateFilterChips.appendChild(chip);
  });
}

async function loadFeedbackHub(options) {
  const preserveFilters = Boolean(options && options.preserveFilters);
  setStatus("", false);
  const previousProfileSelection = preserveFilters ? new Set(selectedProfileIds) : new Set();
  const previousDateFilter = preserveFilters ? selectedDateFilter : "all";

  const [payload, profilesPayload] = await Promise.all([
    apiRequest("/api/papers/hub", "GET"),
    apiRequest("/api/profiles", "GET"),
  ]);

  hubPayload = payload;
  profiles = profilesPayload.profiles || [];
  selectedProfileIds.clear();
  selectedDateFilter = previousDateFilter;

  if (preserveFilters && previousProfileSelection.size) {
    profiles.forEach((profile) => {
      if (previousProfileSelection.has(profile.profile_id)) {
        selectedProfileIds.add(profile.profile_id);
      }
    });
  }

  if (selectedProfileIds.size === 0) {
    profiles.forEach((profile) => selectedProfileIds.add(profile.profile_id));
  }

  renderProfileFilter();
  renderDateFilter();
  applyFilters();
}

async function checkSession() {
  return checkAuthenticatedSession({
    sessionLabelEl: sessionLabel,
    authGateEl: authGate,
    appEl: feedbackApp,
  });
}

bindMagicLinkForm({
  formEl: document.getElementById("auth-form"),
  statusEl: authStatus,
  linkWrapEl: authLinkWrap,
  linkEl: authLink,
  nextPath: "/papers",
});

if (debugResetDbBtn) {
  debugResetDbBtn.addEventListener("click", async () => {
    const ok = window.confirm(
      "Delete ALL papers, ingestion runs, recommendations, and feedback from the database?\n\n" +
        "Profiles, keywords, and profile preferences are kept. Preference embeddings are reset " +
        "to each profile's initial interest sentence.\n\n" +
        "Admin-only debug reset. Requires DEBUG_ADMIN_EMAILS on the server.",
    );
    if (!ok) {
      return;
    }
    debugResetDbBtn.disabled = true;
    setStatus("Resetting paper and feedback data...", false);
    try {
      const result = await apiRequest("/debug/digest-data/reset", "POST");
      await loadFeedbackHub();
      setStatus(
        `Runs removed: ${result.deleted_runs}\n` +
          `Papers removed: ${result.deleted_papers}\n` +
          `Preference embeddings reset: ${result.reset_preference_embeddings}\n` +
          "Debug reset complete.",
        false,
      );
    } catch (error) {
      setStatus(String(error.message || error), true);
    } finally {
      debugResetDbBtn.disabled = false;
    }
  });
}

async function init() {
  try {
    const authenticated = await checkSession();
    if (!authenticated) {
      return;
    }
    setupFeedbackNavigation();
    setupSectionToggles();
    await loadFeedbackHub();
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

function setSectionExpanded(sectionId, expanded) {
  const section = document.getElementById(sectionId);
  if (!section) {
    return;
  }
  section.classList.toggle("is-collapsed", !expanded);
  const toggle = section.querySelector(".feedback-hub-toggle");
  if (toggle) {
    toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
  }
}

function setupSectionToggles() {
  feedbackSectionIds.forEach((sectionId) => {
    const section = document.getElementById(sectionId);
    const toggle = section && section.querySelector(".feedback-hub-toggle");
    if (!toggle) {
      return;
    }
    toggle.addEventListener("click", () => {
      section.classList.toggle("is-collapsed");
      const expanded = !section.classList.contains("is-collapsed");
      toggle.setAttribute("aria-expanded", expanded ? "true" : "false");
    });
  });
}

function setActiveNavLink(sectionId) {
  feedbackNavLinks.forEach((link) => {
    const href = link.getAttribute("href") || "";
    const isActive = href === "#" + sectionId;
    link.classList.toggle("is-active", isActive);
    link.setAttribute("aria-current", isActive ? "true" : "false");
  });
}

function setupFeedbackNavigation() {
  feedbackNavLinks.forEach((link) => {
    link.addEventListener("click", (event) => {
      const href = link.getAttribute("href") || "";
      if (!href.startsWith("#")) {
        return;
      }
      const target = document.getElementById(href.slice(1));
      if (!target) {
        return;
      }
      event.preventDefault();
      setSectionExpanded(target.id, true);
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveNavLink(target.id);
      history.replaceState(null, "", href);
    });
  });

  if (!("IntersectionObserver" in window)) {
    return;
  }

  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio);
      if (!visible.length) {
        return;
      }
      setActiveNavLink(visible[0].target.id);
    },
    {
      root: null,
      rootMargin: "-20% 0px -55% 0px",
      threshold: [0, 0.1, 0.25, 0.5],
    },
  );

  feedbackSectionIds.forEach((sectionId) => {
    const element = document.getElementById(sectionId);
    if (element) {
      observer.observe(element);
    }
  });
}

init();
