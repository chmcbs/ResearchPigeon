function formatApiDetail(detail) {
  if (detail == null || detail === "") {
    return "";
  }
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map(function (item) {
        if (item && typeof item.msg === "string") {
          return item.msg;
        }
        try {
          return JSON.stringify(item);
        } catch (err) {
          return String(item);
        }
      })
      .filter(Boolean)
      .join(" ");
  }
  if (typeof detail === "object" && detail.msg) {
    return String(detail.msg);
  }
  try {
    return JSON.stringify(detail);
  } catch (err) {
    return String(detail);
  }
}

function getCsrfToken() {
  var match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function apiRequest(url, method, body) {
  var response;
  var headers = { "Content-Type": "application/json" };
  var normalizedMethod = (method || "GET").toUpperCase();
  var csrfToken = getCsrfToken();
  if (csrfToken && normalizedMethod !== "GET" && normalizedMethod !== "HEAD") {
    headers["X-CSRF-Token"] = csrfToken;
  }
  try {
    response = await fetch(url, {
      method: method || "GET",
      credentials: "same-origin",
      headers: headers,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    var message =
      err && err.message
        ? err.message
        : "Network error";
    if (/fail/i.test(message) || /network/i.test(message)) {
      message +=
        " — check that the API server is running and the page URL matches its origin (same host and port).";
    }
    throw new Error(message);
  }
  var rawText = await response.text();
  var payload = null;
  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch (err) {
      payload = null;
    }
  }

  if (!response.ok) {
    var detailText = "";
    if (payload && payload.detail != null) {
      detailText = formatApiDetail(payload.detail);
    } else {
      detailText = rawText.trim();
    }
    var error = new Error(detailText || ("Request failed (" + response.status + ")"));
    error.status = response.status;
    error.payload = payload;
    throw error;
  }

  if (!payload) {
    throw new Error(rawText.trim() || "No JSON response body");
  }

  return payload;
}
