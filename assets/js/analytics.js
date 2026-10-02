const ANALYTICS_API = "https://chip-briefing-analytics.wlsalswo14.workers.dev";
const HEARTBEAT_MS = 15000;

let currentCategory = "기타";
let started = false;
let heartbeatTimer = null;

function getSessionId() {
  const key = "chip-briefing-analytics-session";
  try {
    let value = sessionStorage.getItem(key);
    if (!value) {
      value = crypto.randomUUID();
      sessionStorage.setItem(key, value);
    }
    return value;
  } catch {
    return crypto.randomUUID();
  }
}

const sessionId = getSessionId();

function updateViewCounter(views) {
  const target = document.getElementById("today-views");
  if (!target || !Number.isFinite(Number(views))) return;
  target.textContent = Number(views).toLocaleString("ko-KR");
}

async function sendEvent(event, category = currentCategory, useBeacon = false) {
  const payload = JSON.stringify({
    event,
    category,
    session_id: sessionId,
  });

  if (useBeacon && navigator.sendBeacon) {
    navigator.sendBeacon(`${ANALYTICS_API}/api/event`, payload);
    return;
  }

  try {
    const response = await fetch(`${ANALYTICS_API}/api/event`, {
      method: "POST",
      body: payload,
      mode: "cors",
      cache: "no-store",
      keepalive: event === "pause" || event === "pagehide",
    });
    if (!response.ok) return;
    const data = await response.json();
    updateViewCounter(data.views);
  } catch (error) {
    console.debug("방문 통계 전송을 건너뜁니다.", error);
  }
}

async function loadPublicStats() {
  try {
    const response = await fetch(`${ANALYTICS_API}/api/stats`, {
      mode: "cors",
      cache: "no-store",
    });
    if (!response.ok) return;
    const data = await response.json();
    updateViewCounter(data.views);
  } catch (error) {
    console.debug("오늘 조회수를 불러오지 못했습니다.", error);
  }
}

function startHeartbeat() {
  if (heartbeatTimer || document.visibilityState === "hidden") return;
  heartbeatTimer = window.setInterval(() => {
    if (document.visibilityState !== "hidden") sendEvent("heartbeat");
  }, HEARTBEAT_MS);
}

function stopHeartbeat() {
  if (!heartbeatTimer) return;
  window.clearInterval(heartbeatTimer);
  heartbeatTimer = null;
}

export function setAnalyticsCategory(category) {
  const next = String(category || "기타").trim() || "기타";
  if (next === currentCategory) return;
  currentCategory = next;
  if (started && document.visibilityState !== "hidden") sendEvent("switch", currentCategory);
}

export function initAnalytics(initialCategory = "기타") {
  if (started) {
    setAnalyticsCategory(initialCategory);
    return;
  }

  currentCategory = String(initialCategory || "기타").trim() || "기타";
  started = true;

  sendEvent("visit").finally(loadPublicStats);
  startHeartbeat();

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") {
      stopHeartbeat();
      sendEvent("pause", currentCategory, true);
    } else {
      sendEvent("resume");
      startHeartbeat();
    }
  });

  window.addEventListener("pagehide", () => {
    stopHeartbeat();
    sendEvent("pagehide", currentCategory, true);
  });
}
