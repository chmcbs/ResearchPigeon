function output(id, value) {
  document.getElementById(id).textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

function optionalString(value) {
  var trimmed = (value || "").trim();
  return trimmed.length ? trimmed : null;
}

async function run(outId, action) {
  output(outId, "Loading...");
  try {
    var result = await action();
    output(outId, result);
  } catch (err) {
    output(outId, {
      error: true,
      status: err.status || 500,
      detail: err.payload || err.message || "Unexpected error"
    });
  }
}

document.getElementById("profiles-btn").addEventListener("click", function () {
  run("profiles-out", async function () {
    var userId = encodeURIComponent(document.getElementById("profiles-user-id").value.trim() || "default");
    return apiRequest("/profiles?user_id=" + userId, "GET");
  });
});

document.getElementById("create-btn").addEventListener("click", function () {
  run("create-out", async function () {
    return apiRequest("/profiles", "POST", {
      user_id: document.getElementById("create-user-id").value.trim() || "default",
      category: document.getElementById("create-category").value.trim() || "cs.AI",
      interest_sentence: document.getElementById("create-interest-sentence").value.trim() || "Efficient LLM systems"
    });
  });
});

document.getElementById("digest-btn").addEventListener("click", function () {
  run("digest-out", async function () {
    var userId = document.getElementById("digest-user-id").value.trim() || "default";
    var profileIds = document
      .getElementById("digest-profile-ids")
      .value
      .split(",")
      .map(function (value) { return value.trim(); })
      .filter(function (value) { return value.length > 0; });
    return apiRequest("/profiles/digest-selection", "PUT", {
      user_id: userId,
      profile_ids: profileIds
    });
  });
});

function getKeywordInputs() {
  var userId = document.getElementById("keyword-user-id").value.trim() || "default";
  var profileId = document.getElementById("keyword-profile-id").value.trim();
  var keyword = document.getElementById("keyword-value").value.trim();
  if (!profileId) {
    throw { status: 400, payload: { detail: "profile_id is required" } };
  }
  return { userId: userId, profileId: profileId, keyword: keyword };
}

document.getElementById("keywords-list-btn").addEventListener("click", function () {
  run("keywords-out", async function () {
    var inputs = getKeywordInputs();
    return apiRequest(
      "/profiles/" + encodeURIComponent(inputs.profileId) + "/keywords?user_id=" + encodeURIComponent(inputs.userId),
      "GET"
    );
  });
});

document.getElementById("keywords-add-btn").addEventListener("click", function () {
  run("keywords-out", async function () {
    var inputs = getKeywordInputs();
    if (!inputs.keyword) {
      throw { status: 400, payload: { detail: "keyword is required for add" } };
    }
    return apiRequest(
      "/profiles/" + encodeURIComponent(inputs.profileId) + "/keywords",
      "POST",
      { user_id: inputs.userId, keyword: inputs.keyword }
    );
  });
});

document.getElementById("keywords-remove-btn").addEventListener("click", function () {
  run("keywords-out", async function () {
    var inputs = getKeywordInputs();
    if (!inputs.keyword) {
      throw { status: 400, payload: { detail: "keyword is required for remove" } };
    }
    return apiRequest(
      "/profiles/" + encodeURIComponent(inputs.profileId) + "/keywords",
      "DELETE",
      { user_id: inputs.userId, keyword: inputs.keyword }
    );
  });
});

document.getElementById("generate-btn").addEventListener("click", function () {
  run("generate-out", async function () {
    var profileIds = document
      .getElementById("generate-profile-ids")
      .value.split(",")
      .map(function (value) { return value.trim(); })
      .filter(function (value) { return value.length > 0; });
    if (!profileIds.length) {
      throw { status: 400, payload: { detail: "profile_ids must contain at least one id" } };
    }
    var body = {
      user_id: document.getElementById("generate-user-id").value.trim() || "default",
      profile_ids: profileIds,
      max_results: Number(document.getElementById("generate-max-results").value) || 150,
      embedding_limit: Number(document.getElementById("generate-embedding-limit").value) || 600
    };
    return apiRequest("/daily-picks/generate", "POST", body);
  });
});

document.getElementById("daily-btn").addEventListener("click", function () {
  run("daily-out", async function () {
    var userId = encodeURIComponent(document.getElementById("daily-user-id").value.trim() || "default");
    var profileId = optionalString(document.getElementById("daily-profile-id").value);
    var query = "/daily-picks?user_id=" + userId;
    if (profileId) {
      query += "&profile_id=" + encodeURIComponent(profileId);
    }
    return apiRequest(query, "GET");
  });
});

document.getElementById("debug-btn").addEventListener("click", function () {
  run("debug-out", async function () {
    var userId = encodeURIComponent(document.getElementById("debug-user-id").value.trim() || "default");
    var profileId = optionalString(document.getElementById("debug-profile-id").value);
    if (!profileId) {
      throw { status: 400, payload: { detail: "profile_id is required" } };
    }
    var query =
      "/daily-picks/debug?user_id=" +
      userId +
      "&profile_id=" +
      encodeURIComponent(profileId);
    return apiRequest(query, "GET");
  });
});

document.getElementById("feedback-btn").addEventListener("click", function () {
  run("feedback-out", async function () {
    var profileId = optionalString(document.getElementById("feedback-profile-id").value);
    if (!profileId) {
      throw { status: 400, payload: { detail: "profile_id is required" } };
    }
    var body = {
      arxiv_id: document.getElementById("feedback-arxiv-id").value.trim(),
      label: document.getElementById("feedback-label").value,
      user_id: document.getElementById("feedback-user-id").value.trim() || "default",
      profile_id: profileId,
    };
    return apiRequest("/feedback", "POST", body);
  });
});

document.getElementById("metrics-btn").addEventListener("click", function () {
  run("metrics-out", async function () {
    var limit = Number(document.getElementById("metrics-limit").value) || 10;
    return apiRequest("/metrics?latest_runs_limit=" + encodeURIComponent(limit), "GET");
  });
});
