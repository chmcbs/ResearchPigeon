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
    return apiRequest("/api/profiles", "GET");
  });
});

document.getElementById("create-btn").addEventListener("click", function () {
  run("create-out", async function () {
    return apiRequest("/api/profiles", "POST", {
      category: document.getElementById("create-category").value.trim() || "cs.AI",
      interest_sentence: document.getElementById("create-interest-sentence").value.trim() || "Efficient LLM systems"
    });
  });
});

document.getElementById("digest-btn").addEventListener("click", function () {
  run("digest-out", async function () {
    var profileIds = document
      .getElementById("digest-profile-ids")
      .value
      .split(",")
      .map(function (value) { return value.trim(); })
      .filter(function (value) { return value.length > 0; });
    return apiRequest("/api/profiles/digest-selection", "PUT", {
      profile_ids: profileIds
    });
  });
});

function getKeywordInputs() {
  var profileId = document.getElementById("keyword-profile-id").value.trim();
  var keyword = document.getElementById("keyword-value").value.trim();
  if (!profileId) {
    throw { status: 400, payload: { detail: "profile_id is required" } };
  }
  return { profileId: profileId, keyword: keyword };
}

document.getElementById("keywords-list-btn").addEventListener("click", function () {
  run("keywords-out", async function () {
    var inputs = getKeywordInputs();
    return apiRequest(
      "/api/profiles/" + encodeURIComponent(inputs.profileId) + "/keywords",
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
      "/api/profiles/" + encodeURIComponent(inputs.profileId) + "/keywords",
      "POST",
      { keyword: inputs.keyword }
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
      "/api/profiles/" + encodeURIComponent(inputs.profileId) + "/keywords",
      "DELETE",
      { keyword: inputs.keyword }
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
      profile_ids: profileIds,
      max_results: Number(document.getElementById("generate-max-results").value) || 150,
      embedding_limit: Number(document.getElementById("generate-embedding-limit").value) || 600
    };
    return apiRequest("/daily-picks/generate", "POST", body);
  });
});

document.getElementById("daily-btn").addEventListener("click", function () {
  run("daily-out", async function () {
    var profileId = optionalString(document.getElementById("daily-profile-id").value);
    var query = "/daily-picks";
    if (profileId) {
      query += "?profile_id=" + encodeURIComponent(profileId);
    }
    return apiRequest(query, "GET");
  });
});

document.getElementById("debug-btn").addEventListener("click", function () {
  run("debug-out", async function () {
    var profileId = optionalString(document.getElementById("debug-profile-id").value);
    if (!profileId) {
      throw { status: 400, payload: { detail: "profile_id is required" } };
    }
    var query = "/daily-picks/debug?profile_id=" + encodeURIComponent(profileId);
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
      profile_id: profileId,
    };
    return apiRequest("/api/feedback", "POST", body);
  });
});

document.getElementById("metrics-btn").addEventListener("click", function () {
  run("metrics-out", async function () {
    var limit = Number(document.getElementById("metrics-limit").value) || 10;
    return apiRequest("/metrics?latest_runs_limit=" + encodeURIComponent(limit), "GET");
  });
});
