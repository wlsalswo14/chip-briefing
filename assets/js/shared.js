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

export function excerpt(value, limit = 150, maxLines = 3) {
  // Multi-line summaries are kept multi-line; only the total length is capped.
  const lines = String(value ?? "")
    .split(/\n+/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .slice(0, maxLines);
  const joined = lines.join("\n");
  if (joined.length <= limit) return joined;
  const cut = joined.slice(0, limit).replace(/\s+\S*$/, "").trim();
  return `${cut}...`;
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
    // Entries with a generated summary always outrank raw RSS snippets so the
    // main slots never show an unsummarized headline.
    const summaryDifference = (b.summary_method === "llm" ? 1 : 0) - (a.summary_method === "llm" ? 1 : 0);
    if (summaryDifference) return summaryDifference;
    const importanceDifference = Number(b.importance_score || b.importance || 0)
      - Number(a.importance_score || a.importance || 0);
    if (importanceDifference) return importanceDifference;
    return String(b.created_at || "").localeCompare(String(a.created_at || ""));
  });
}

export function selectDetailedArticles(data) {
  const articles = Array.isArray(data.articles) ? data.articles : [];
  const byId = new Map(articles.map((article) => [article.id, article]));
  const preferredIds = Array.isArray(data.summary_article_ids) ? data.summary_article_ids : [];
  const selected = [];
  const seen = new Set();

  for (const id of preferredIds) {
    const article = byId.get(id);
    if (article && article.summary_method === "llm" && !seen.has(id)) {
      selected.push(article);
      seen.add(id);
    }
  }
  for (const article of sortByImportance(articles.filter((item) => item.summary_method === "llm"))) {
    if (!seen.has(article.id)) {
      selected.push(article);
      seen.add(article.id);
    }
  }

  const configuredTarget = Number(data.collector?.summary_target || 0);
  return configuredTarget > 0 ? selected.slice(0, configuredTarget) : selected;
}

export function selectHeadlineArticles(data) {
  const articles = Array.isArray(data.articles) ? data.articles : [];
  const byId = new Map(articles.map((article) => [article.id, article]));
  const preferredIds = Array.isArray(data.headline_article_ids) ? data.headline_article_ids : [];
  const selected = [];
  const seen = new Set();

  for (const id of preferredIds) {
    const article = byId.get(id);
    if (article && article.summary_method !== "llm" && !seen.has(id)) {
      selected.push(article);
      seen.add(id);
    }
  }
  const fallback = articles
    .filter((article) => article.publication_mode === "headline")
    .sort((a, b) => {
      const scoreDifference = Number(b.title_importance_score || b.importance_score || 0)
        - Number(a.title_importance_score || a.importance_score || 0);
      if (scoreDifference) return scoreDifference;
      return String(b.created_at || "").localeCompare(String(a.created_at || ""));
    });
  for (const article of fallback) {
    if (!seen.has(article.id)) {
      selected.push(article);
      seen.add(article.id);
    }
  }
  return selected;
}

export function selectDailyTopTen(data) {
  const articles = (Array.isArray(data.articles) ? data.articles : [])
    .filter((article) => article.summary_method === "llm");
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

export function selectCommunityTopTen(data) {
  const items = Array.isArray(data.community_items) ? data.community_items : [];
  const byId = new Map(items.map((item) => [item.id, item]));
  const preferredIds = Array.isArray(data.community_top10_ids) ? data.community_top10_ids : [];
  const selected = [];
  const seen = new Set();

  for (const id of preferredIds) {
    const item = byId.get(id);
    if (item && !seen.has(id)) {
      selected.push(item);
      seen.add(id);
    }
  }
  for (const item of items.slice().sort((a, b) => {
    const scoreDifference = Number(b.community_score || 0) - Number(a.community_score || 0);
    if (scoreDifference) return scoreDifference;
    return String(b.created_at || "").localeCompare(String(a.created_at || ""));
  })) {
    if (!seen.has(item.id)) {
      selected.push(item);
      seen.add(item.id);
    }
  }
  return selected.slice(0, 10);
}
