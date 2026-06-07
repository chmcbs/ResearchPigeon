const authGate = document.getElementById("auth-gate");
const prefsApp = document.getElementById("prefs-app");
const authStatus = document.getElementById("auth-status");
const authLinkWrap = document.getElementById("auth-link-wrap");
const authLink = document.getElementById("auth-link");
const sessionLabel = document.getElementById("session-label");
const prefsStatus = document.getElementById("prefs-status");
const profilesGrid = document.getElementById("profiles-grid");
const addProfileBtn = document.getElementById("add-profile-btn");
const debugResetProfilesBtn = document.getElementById("debug-reset-profiles-btn");
const cardTemplate = document.getElementById("profile-card-template");

let categories = [];
let profiles = [];

function setStatus(message, isError) {
  setPageStatus(prefsStatus, message, isError);
}

async function checkSession() {
  return checkAuthenticatedSession({
    sessionLabelEl: sessionLabel,
    authGateEl: authGate,
    appEl: prefsApp,
  });
}

async function loadCategories() {
  const payload = await apiRequest("/categories", "GET");
  categories = payload.categories || [];
}

function getSelectedProfileIds() {
  return profiles
    .filter((item) => item.digest_enabled && !item.is_draft)
    .map((item) => item.profile_id);
}

function setSummaryLine(element, label, value) {
  element.innerHTML = "";
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  element.appendChild(strong);
  element.appendChild(document.createTextNode(value || "-"));
}

function calendarDayKey(value) {
  const parsed = new Date(value || 0);
  if (Number.isNaN(parsed.getTime())) {
    return 0;
  }
  return parsed.getFullYear() * 10000 + (parsed.getMonth() + 1) * 100 + parsed.getDate();
}

function sortPapersByDateAndScore(items) {
  return [...items].sort((a, b) => {
    const dayDiff = calendarDayKey(b.generated_at) - calendarDayKey(a.generated_at);
    if (dayDiff !== 0) {
      return dayDiff;
    }
    const scoreDiff = (Number(b.final_score) || 0) - (Number(a.final_score) || 0);
    if (scoreDiff !== 0) {
      return scoreDiff;
    }
    return (Number(a.rank) || 0) - (Number(b.rank) || 0);
  });
}

function buildProfilePaperList(profile) {
  const main = sortPapersByDateAndScore([
    ...(profile.papers_liked || []).map((item) => ({
      ...item,
      is_liked: true,
      is_disliked: false,
    })),
    ...(profile.papers_feed || []).map((item) => ({
      ...item,
      is_liked: false,
      is_disliked: false,
    })),
  ]);
  const disliked = sortPapersByDateAndScore(
    (profile.papers_disliked || []).map((item) => ({
      ...item,
      is_liked: false,
      is_disliked: true,
    })),
  );
  return [...main, ...disliked];
}

async function loadProfilePapers(profile) {
  const payload = await apiRequest(
    `/api/papers/hub?profile_id=${encodeURIComponent(profile.profile_id)}`,
    "GET",
  );
  profile.papers_liked = payload.liked || [];
  profile.papers_feed = payload.seen || [];
  profile.papers_disliked = payload.disliked || [];
}

function normalizeKeyword(rawKeyword, currentKeywords) {
  const keyword = rawKeyword.trim().toLowerCase();
  if (!keyword) {
    return { error: "Keyword cannot be empty." };
  }
  if (keyword.length > 24) {
    return { error: "Keyword max length is 24 characters." };
  }
  if ((currentKeywords || []).includes(keyword)) {
    return { error: "Keyword already exists on this profile." };
  }
  if ((currentKeywords || []).length >= 20) {
    return { error: "Keyword limit reached (20)." };
  }
  return { keyword };
}

async function updateDigestSelection() {
  await apiRequest("/api/profiles/digest-selection", "PUT", {
    profile_ids: getSelectedProfileIds(),
  });
}

function orderedProfilesForDisplay() {
  const saved = profiles
    .filter((item) => !item.is_draft)
    .sort((a, b) => (a.profile_slot || 0) - (b.profile_slot || 0));
  const drafts = profiles.filter((item) => item.is_draft);
  return [...saved, ...drafts];
}

function savedProfilesInSlotOrder() {
  return profiles
    .filter((item) => !item.is_draft)
    .sort((a, b) => (a.profile_slot || 0) - (b.profile_slot || 0));
}

async function persistProfileOrder(newOrder) {
  await apiRequest("/api/profiles/order", "PUT", {
    profile_ids: newOrder,
  });
  const drafts = profiles.filter((item) => item.is_draft);
  const byId = new Map(profiles.map((item) => [item.profile_id, item]));
  const reordered = newOrder.map((profileId, index) => {
    const profile = byId.get(profileId);
    if (profile) {
      profile.profile_slot = index + 1;
    }
    return profile;
  }).filter(Boolean);
  profiles = [...reordered, ...drafts];
}

function profileCardFromPoint(clientX, clientY, excludeProfileId) {
  const cards = profilesGrid.querySelectorAll(".profile-card[data-profile-id]");
  for (const card of cards) {
    if (card.dataset.profileId === excludeProfileId) {
      continue;
    }
    const rect = card.getBoundingClientRect();
    if (
      clientX >= rect.left &&
      clientX <= rect.right &&
      clientY >= rect.top &&
      clientY <= rect.bottom
    ) {
      return card;
    }
  }
  return null;
}

function clearProfileDragOverState() {
  profilesGrid.querySelectorAll(".profile-card").forEach((element) => {
    element.classList.remove("is-drag-over");
  });
}

async function reorderProfilesByIds(sourceId, targetId) {
  if (!sourceId || !targetId || sourceId === targetId) {
    return;
  }

  const savedProfiles = savedProfilesInSlotOrder();
  const fromIndex = savedProfiles.findIndex((item) => item.profile_id === sourceId);
  const toIndex = savedProfiles.findIndex((item) => item.profile_id === targetId);
  if (fromIndex === -1 || toIndex === -1) {
    return;
  }

  const reordered = [...savedProfiles];
  const [moved] = reordered.splice(fromIndex, 1);
  reordered.splice(toIndex, 0, moved);
  const newOrder = reordered.map((item) => item.profile_id);

  await persistProfileOrder(newOrder);
  renderProfiles();
  setStatus("", false);
}

function attachProfileDragBehavior(card, profile) {
  const dragHandle = card.querySelector(".profile-drag-handle");
  const canDrag = !profile.is_draft && !profile.is_editing;

  dragHandle.classList.toggle("hidden", !canDrag);
  if (!canDrag) {
    return;
  }

  card.dataset.profileId = profile.profile_id;

  dragHandle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();

    const sourceId = profile.profile_id;
    card.classList.add("is-dragging");
    dragHandle.setPointerCapture(event.pointerId);

    function finishDrag(upEvent) {
      if (dragHandle.hasPointerCapture(upEvent.pointerId)) {
        dragHandle.releasePointerCapture(upEvent.pointerId);
      }
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);

      card.classList.remove("is-dragging");
      clearProfileDragOverState();

      const targetCard = profileCardFromPoint(upEvent.clientX, upEvent.clientY, sourceId);
      const targetId = targetCard?.dataset.profileId || null;

      if (!targetId) {
        return;
      }

      reorderProfilesByIds(sourceId, targetId).catch(async (error) => {
        setStatus(String(error.message || error), true);
        await loadProfiles();
      });
    }

    function onPointerMove(moveEvent) {
      clearProfileDragOverState();
      const targetCard = profileCardFromPoint(moveEvent.clientX, moveEvent.clientY, sourceId);
      if (targetCard) {
        targetCard.classList.add("is-drag-over");
      }
    }

    function onPointerUp(upEvent) {
      finishDrag(upEvent);
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
  });
}

async function loadProfiles() {
  const payload = await apiRequest("/api/profiles", "GET");
  profiles = payload.profiles || [];
  renderProfiles();
}

function renderProfiles() {
  profilesGrid.innerHTML = "";
  if (!profiles.length) {
    profilesGrid.innerHTML = "<p class='muted'>No profiles yet. Add your first profile.</p>";
    return;
  }

  orderedProfilesForDisplay().forEach((profile) => {
    const isDraft = Boolean(profile.is_draft);
    const isEditing = isDraft || Boolean(profile.is_editing);
    const node = cardTemplate.content.firstElementChild.cloneNode(true);
    const profileTitleInput = node.querySelector(".profile-title-input");
    const categoryLabel = node.querySelector(".category-label");
    const categorySelect = node.querySelector(".category-select");
    const interestLabel = node.querySelector(".interest-label");
    const interestText = node.querySelector(".interest-text");
    const summaryBlock = node.querySelector(".profile-summary");
    const summaryCategory = node.querySelector(".summary-category");
    const summaryDescription = node.querySelector(".summary-description");
    const feedbackToggle = node.querySelector(".feedback-toggle");
    const feedbackPanel = node.querySelector(".feedback-panel");
    const feedbackList = node.querySelector(".feedback-list");
    const digestCheckbox = node.querySelector(".digest-checkbox");
    const keywordList = node.querySelector(".keyword-list");
    const saveBtn = node.querySelector(".save-btn");
    const cancelEditBtn = node.querySelector(".cancel-edit-btn");
    const deleteBtn = node.querySelector(".delete-btn");
    const editBtn = node.querySelector(".edit-btn");

    profile.keywords = Array.isArray(profile.keywords) ? profile.keywords : [];
    profile.is_adding_keyword = Boolean(profile.is_adding_keyword);
    profile.feedback_expanded = Boolean(profile.feedback_expanded);
    profileTitleInput.value = profile.profile_name || "";
    profileTitleInput.disabled = !isEditing;
    interestText.value = profile.interest_sentence;
    setSummaryLine(summaryCategory, "Category", profile.category);
    setSummaryLine(summaryDescription, "Description", profile.interest_sentence);
    feedbackToggle.textContent = profile.feedback_expanded ? "Hide papers" : "Show papers";

    const showDraftFields = isDraft && isEditing;
    categoryLabel.classList.toggle("hidden", !showDraftFields);
    categorySelect.classList.toggle("hidden", !showDraftFields);
    interestLabel.classList.toggle("hidden", !showDraftFields);
    interestText.classList.toggle("hidden", !showDraftFields);
    summaryBlock.classList.toggle("hidden", isDraft);
    feedbackToggle.classList.toggle("hidden", isDraft);
    feedbackPanel.classList.toggle("hidden", isDraft || !profile.feedback_expanded);
    interestText.readOnly = !isDraft;
    interestText.placeholder = isDraft ? "Describe your research interests." : "";
    digestCheckbox.checked = profile.digest_enabled;
    saveBtn.textContent = isDraft ? "Create profile" : "Save profile";
    deleteBtn.textContent = isDraft ? "Cancel" : "Delete";
    saveBtn.classList.toggle("hidden", !isEditing);
    cancelEditBtn.classList.toggle("hidden", !isEditing || isDraft);
    deleteBtn.classList.toggle("hidden", !isEditing);
    keywordList.classList.remove("hidden");
    editBtn.classList.toggle("hidden", isDraft || isEditing);
    editBtn.textContent = "Edit profile";
    profileTitleInput.addEventListener("input", () => {
      profile.profile_name = profileTitleInput.value;
    });

    categories.forEach((category) => {
      const option = document.createElement("option");
      const categoryId =
        typeof category === "string" ? category : category.id;
      const categoryLabel =
        typeof category === "string"
          ? category
          : category.label || category.id;
      option.value = categoryId;
      option.textContent = categoryLabel;
      if (categoryId === profile.category) {
        option.selected = true;
      }
      categorySelect.appendChild(option);
    });

    function drawKeywords(values) {
      keywordList.innerHTML = "";
      values.forEach((value) => {
        const chip = document.createElement("span");
        chip.className = "keyword-chip";
        chip.textContent = value;
        if (isEditing) {
          const removeBtn = document.createElement("button");
          removeBtn.className = "chip-btn";
          removeBtn.textContent = "x";
          removeBtn.type = "button";
          removeBtn.addEventListener("click", async () => {
            if (isDraft) {
              profile.keywords = (profile.keywords || []).filter((item) => item !== value);
              drawKeywords(profile.keywords);
              setStatus("", false);
              return;
            }
            try {
              const payload = await apiRequest(`/api/profiles/${profile.profile_id}/keywords`, "DELETE", { keyword: value });
              profile.keywords = Array.isArray(payload.keywords) ? payload.keywords : [];
              drawKeywords(profile.keywords);
              setStatus("", false);
            } catch (error) {
              setStatus(String(error.message || error), true);
            }
          });
          chip.appendChild(removeBtn);
        }
        keywordList.appendChild(chip);
      });

      if (!isEditing) {
        return;
      }

      const addChip = document.createElement("button");
      addChip.className = "keyword-chip keyword-add-chip";
      addChip.type = "button";
      addChip.textContent = "+keyword";
      addChip.addEventListener("click", () => {
        profile.is_adding_keyword = true;
        drawKeywords(profile.keywords || []);
      });
      keywordList.appendChild(addChip);

      if (!profile.is_adding_keyword) {
        return;
      }

      const inputChip = document.createElement("span");
      inputChip.className = "keyword-chip keyword-input-chip";
      const input = document.createElement("input");
      input.type = "text";
      input.placeholder = "e.g. retrieval";
      input.className = "keyword-inline-input";

      const confirmBtn = document.createElement("button");
      confirmBtn.className = "chip-btn";
      confirmBtn.type = "button";
      confirmBtn.textContent = "✓";

      const cancelBtn = document.createElement("button");
      cancelBtn.className = "chip-btn";
      cancelBtn.type = "button";
      cancelBtn.textContent = "✕";

      async function addKeywordFromInlineInput() {
        const normalized = normalizeKeyword(input.value, profile.keywords || []);
        if (normalized.error) {
          setStatus(normalized.error, true);
          return;
        }
        if (isDraft) {
          profile.keywords = [...(profile.keywords || []), normalized.keyword];
          profile.is_adding_keyword = false;
          drawKeywords(profile.keywords);
          setStatus("", false);
          return;
        }
        try {
          const payload = await apiRequest(`/api/profiles/${profile.profile_id}/keywords`, "POST", {
            keyword: normalized.keyword,
          });
          profile.keywords = Array.isArray(payload.keywords) ? payload.keywords : [];
          profile.is_adding_keyword = false;
          drawKeywords(profile.keywords);
          setStatus("", false);
        } catch (error) {
          setStatus(String(error.message || error), true);
        }
      }

      confirmBtn.addEventListener("click", addKeywordFromInlineInput);
      cancelBtn.addEventListener("click", () => {
        profile.is_adding_keyword = false;
        drawKeywords(profile.keywords || []);
      });
      input.addEventListener("keydown", async (event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          await addKeywordFromInlineInput();
        } else if (event.key === "Escape") {
          profile.is_adding_keyword = false;
          drawKeywords(profile.keywords || []);
        }
      });

      inputChip.appendChild(input);
      inputChip.appendChild(confirmBtn);
      inputChip.appendChild(cancelBtn);
      keywordList.appendChild(inputChip);
      input.focus();
    }

    function drawFeedbackItems() {
      feedbackList.innerHTML = "";
      if (isDraft) {
        return;
      }

      const papers = buildProfilePaperList(profile);

      if (!papers.length) {
        const emptyRow = document.createElement("p");
        emptyRow.className = "summary-line";
        emptyRow.textContent = "No papers yet.";
        feedbackList.appendChild(emptyRow);
        return;
      }

      papers.forEach((item) => {
          const row = document.createElement("div");
          row.className = "feedback-row";

          const leftSide = document.createElement("div");
          leftSide.className = "feedback-row-left";

          if (item.is_liked) {
            const thumb = document.createElement("span");
            thumb.className = "feedback-paper-thumb";
            thumb.textContent = "\ud83d\udc4d";
            thumb.setAttribute("aria-label", "Liked");
            leftSide.appendChild(thumb);
          } else if (item.is_disliked) {
            const thumb = document.createElement("span");
            thumb.className = "feedback-paper-thumb";
            thumb.textContent = "\ud83d\udc4e";
            thumb.setAttribute("aria-label", "Disliked");
            leftSide.appendChild(thumb);
          } else {
            const thumb = document.createElement("span");
            thumb.className = "feedback-paper-thumb";
            thumb.textContent = "\ud83c\udd95";
            thumb.setAttribute("aria-label", "New in feed");
            leftSide.appendChild(thumb);
          }

          const text = document.createElement("a");
          text.textContent = item.title;
          text.className = "feedback-item-text";
          text.href = item.pdf_url || `https://arxiv.org/pdf/${item.arxiv_id}`;
          text.target = "_blank";
          text.rel = "noopener noreferrer";

          const rightSide = document.createElement("div");
          rightSide.className = "feedback-row-actions";

          const meta = document.createElement("span");
          meta.className = "feedback-date";
          meta.textContent = formatShortDate(item.generated_at, "");

          rightSide.appendChild(meta);
          if ((item.is_liked || item.is_disliked) && isEditing) {
            const removeBtn = document.createElement("button");
            removeBtn.className = "chip-btn";
            removeBtn.type = "button";
            removeBtn.textContent = "x";
            removeBtn.addEventListener("click", async () => {
              try {
                await apiRequest("/api/feedback", "DELETE", {
                  profile_id: profile.profile_id,
                  arxiv_id: item.arxiv_id,
                });
                await loadProfilePapers(profile);
                setStatus("", false);
                drawFeedbackItems();
              } catch (error) {
                setStatus(String(error.message || error), true);
              }
            });
            rightSide.appendChild(removeBtn);
          }

          leftSide.appendChild(text);
          row.appendChild(leftSide);
          row.appendChild(rightSide);
          feedbackList.appendChild(row);
      });
    }

    drawKeywords(profile.keywords || []);
    drawFeedbackItems();
    feedbackToggle.addEventListener("click", async () => {
      const willExpand = !profile.feedback_expanded;
      profile.feedback_expanded = willExpand;
      if (willExpand && !isDraft) {
        try {
          setStatus("", false);
          await loadProfilePapers(profile);
        } catch (error) {
          profile.feedback_expanded = false;
          setStatus(String(error.message || error), true);
        }
      }
      renderProfiles();
    });

    saveBtn.addEventListener("click", async () => {
      if (isDraft) {
        const interestSentence = interestText.value.trim();
        if (!interestSentence) {
          setStatus("Interest sentence is required when creating a profile.", true);
          interestText.focus();
          return;
        }
        const prevSaveLabel = saveBtn.textContent;
        saveBtn.disabled = true;
        saveBtn.setAttribute("aria-busy", "true");
        saveBtn.textContent = "Creating…";
        setStatus("", false);
        try {
          const createPayload = await apiRequest("/api/profiles", "POST", {
            profile_name: profileTitleInput.value.trim() || `Profile ${profiles.length}`,
            category: categorySelect.value,
            interest_sentence: interestSentence,
          });
          let createdProfile = createPayload.profile;
          const draftKeywords = [...(profile.keywords || [])];
          for (const keyword of draftKeywords) {
            const keywordPayload = await apiRequest(
              `/api/profiles/${createdProfile.profile_id}/keywords`,
              "POST",
              { keyword }
            );
            createdProfile.keywords = keywordPayload.keywords;
          }
          const updatePayload = await apiRequest(`/api/profiles/${createdProfile.profile_id}`, "PUT", {
            profile_name: profileTitleInput.value,
            category: categorySelect.value,
            digest_enabled: digestCheckbox.checked,
          });
          createdProfile = updatePayload.profile;
          // Clear draft flag on the in-memory card before syncing digest selection; otherwise
          // getSelectedProfileIds() skips drafts and digest-selection disables this profile.
          const draftIdx = profiles.indexOf(profile);
          if (draftIdx !== -1) {
            Object.assign(profiles[draftIdx], {
              profile_id: createdProfile.profile_id,
              user_id: createdProfile.user_id,
              profile_slot: createdProfile.profile_slot,
              profile_name: createdProfile.profile_name,
              category: createdProfile.category,
              interest_sentence: createdProfile.interest_sentence,
              digest_enabled: createdProfile.digest_enabled,
              created_at: createdProfile.created_at,
              is_draft: false,
            });
          }
          await updateDigestSelection();
          await loadProfiles();
          setStatus("", false);
        } catch (error) {
          setStatus(String(error.message || error), true);
          saveBtn.disabled = false;
          saveBtn.removeAttribute("aria-busy");
          saveBtn.textContent = prevSaveLabel;
        }
        return;
      }
      const prevSaveLabel = saveBtn.textContent;
      saveBtn.disabled = true;
      saveBtn.setAttribute("aria-busy", "true");
      saveBtn.textContent = "Saving…";
      try {
        const updatePayload = await apiRequest(`/api/profiles/${profile.profile_id}`, "PUT", {
          profile_name: profileTitleInput.value,
          digest_enabled: digestCheckbox.checked,
        });
        profile.profile_name = updatePayload.profile.profile_name;
        profile.digest_enabled = updatePayload.profile.digest_enabled;
        profile.is_editing = false;
        await updateDigestSelection();
        renderProfiles();
        setStatus("", false);
      } catch (error) {
        setStatus(String(error.message || error), true);
        saveBtn.disabled = false;
        saveBtn.removeAttribute("aria-busy");
        saveBtn.textContent = prevSaveLabel;
      }
    });

    editBtn.addEventListener("click", async () => {
      profile.is_editing = true;
      renderProfiles();
      setStatus("", false);
    });
    cancelEditBtn.addEventListener("click", async () => {
      profile.is_editing = false;
      await loadProfiles();
      setStatus("", false);
    });

    digestCheckbox.addEventListener("change", async () => {
      profile.digest_enabled = digestCheckbox.checked;
      if (isDraft) {
        return;
      }
      try {
        await apiRequest(`/api/profiles/${profile.profile_id}`, "PUT", {
          profile_name: profile.profile_name,
          digest_enabled: profile.digest_enabled,
        });
        await updateDigestSelection();
        setStatus("", false);
      } catch (error) {
        profile.digest_enabled = !digestCheckbox.checked;
        digestCheckbox.checked = profile.digest_enabled;
        setStatus(String(error.message || error), true);
      }
    });

    deleteBtn.addEventListener("click", async () => {
      if (isDraft) {
        profiles = profiles.filter((item) => item.profile_id !== profile.profile_id);
        renderProfiles();
        setStatus("", false);
        return;
      }
      try {
        await apiRequest(`/api/profiles/${profile.profile_id}`, "DELETE");
        profiles = profiles.filter((item) => item.profile_id !== profile.profile_id);
        await updateDigestSelection();
        renderProfiles();
        setStatus("", false);
      } catch (error) {
        setStatus(String(error.message || error), true);
      }
    });

    attachProfileDragBehavior(node, profile);
    profilesGrid.appendChild(node);
  });
}

bindMagicLinkForm({
  formEl: document.getElementById("auth-form"),
  statusEl: authStatus,
  linkWrapEl: authLinkWrap,
  linkEl: authLink,
  nextPath: "/profiles",
});

addProfileBtn.addEventListener("click", async () => {
  if (profiles.length >= 3) {
    setStatus("Profile limit reached (3).", true);
    return;
  }
  if (profiles.some((item) => item.is_draft)) {
    setStatus("Finish creating the current new profile first.", true);
    return;
  }
  profiles.unshift({
    profile_id: `draft-${Date.now()}`,
    profile_slot: profiles.length + 1,
    profile_name: `Profile ${profiles.length + 1}`,
    category:
      (categories[0] && (categories[0].id || categories[0])) || "cs.AI",
    interest_sentence: "",
    digest_enabled: true,
    keywords: [],
    is_draft: true,
  });
  renderProfiles();
  setStatus("", false);
});

debugResetProfilesBtn.addEventListener("click", async () => {
  const ok = window.confirm(
    "Delete ALL user profiles from the database (every account)?\n\n" +
      "CASCADE removes profile_preferences, profile_keywords, paper_feedback, " +
      "and recommendations tied to those profiles.\n\n" +
      "Papers and runs are not removed; use Hard reset papers on the Digest page if you need a clean corpus.\n\n" +
      "Admin-only debug reset. Requires DEBUG_ADMIN_EMAILS on the server.",
  );
  if (!ok) {
    return;
  }
  debugResetProfilesBtn.disabled = true;
  try {
    const result = await apiRequest("/debug/profile-data/reset", "POST");
    await loadProfiles();
    prefsStatus.textContent = `Removed ${result.deleted_profiles} profile(s). Preferences and keywords cleared.`;
    prefsStatus.style.color = "#6b7280";
  } catch (error) {
    setStatus(String(error.message || error), true);
  } finally {
    debugResetProfilesBtn.disabled = false;
  }
});

async function init() {
  try {
    const authenticated = await checkSession();
    if (!authenticated) {
      return;
    }
    await loadCategories();
    await loadProfiles();
  } catch (error) {
    setStatus(String(error.message || error), true);
  }
}

init();
