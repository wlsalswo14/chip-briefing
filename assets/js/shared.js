export const SEOUL_TIME_ZONE = "Asia/Seoul";

export const $ = (id) => document.getElementById(id);

export const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (character) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
}[character]));

export function safeUrl(value) {
  try {
    const parsed = new URL(String(value ?? ""), window.location.href);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "";
  } catch {
    return "";
  }
}

export function fmt(iso, timeOnly = false) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso ?? "");
  const options = timeOnly
    ? { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: SEOUL_TIME_ZONE }
    : { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit", timeZone: SEOUL_TIME_ZONE };
  return date.toLocaleString("ko-KR", options);
}

export function formatBriefingDate(iso, weekday = "long") {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "날짜 미상";
  return date.toLocaleDateString("ko-KR", {
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday,
    timeZone: SEOUL_TIME_ZONE,
  });
}

export function fmtUpdated(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return `업데이트 ${iso || "-"}`;
  return `${formatBriefingDate(iso)} · ${fmt(iso, true)} KST 업데이트`;
}

export function excerpt(value, limit = 150) {
  const clean = String(value ?? "").split(/\n+/)[0].replace(/\s+/g, " ").trim();
  return clean.length > limit ? `${clean.slice(0, limit).trim()}...` : clean;
}

export function para(value) {
  return String(value ?? "")
    .split(/\n{2,}|\n/)
    .filter(Boolean)
    .map((paragraph) => `<p>${esc(paragraph)}</p>`)
    .join("");
}

export async function loadJson(path) {
  const separator = path.includes("?") ? "&" : "?";
  const response = await fetch(`${path}${separator}t=${Date.now()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status} while loading ${path}`);
  return response.json();
}

export function sortByImportance(items) {
  return items.slice().sort((a, b) => {
    const importanceDifference = Number(b.importance_score || b.importance || 0)
      - Number(a.importance_score || a.importance || 0);
    if (importanceDifference) return importanceDifference;
    return String(b.created_at || "").localeCompare(String(a.created_at || ""));
  });
}

export function selectDailyTopTen(data) {
  const articles = Array.isArray(data.articles) ? data.articles : [];
  const byId = new Map(articles.map((article) => [article.id, article]));
  const preferredIds = Array.isArray(data.daily_summary_article_ids) ? data.daily_summary_article_ids : [];
  const selected = [];
  const seen = new Set();

  for (const id of preferredIds) {
    const article = byId.get(id);
    if (article && !seen.has(id)) {
      selected.push(article);
      seen.add(id);
    }
  }
  for (const article of sortByImportance(articles)) {
    if (!seen.has(article.id)) {
      selected.push(article);
      seen.add(article.id);
    }
  }
  return selected.slice(0, 10);
}
