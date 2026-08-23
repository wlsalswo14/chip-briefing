import {
  $,
  esc,
  excerpt,
  fmt,
  formatBriefingDate,
  loadJson,
  para,
  safeUrl,
  selectCommunityTopTen,
  selectDailyTopTen,
} from "./shared.js";

const state = {
  items: [],
  months: [],
  activeDate: "",
  activeMonth: "",
  articlesById: new Map(),
  snapshotCache: new Map(),
  previousFocus: null,
  requestVersion: 0,
};

const dateAtNoon = (dateKey) => `${dateKey}T12:00:00+09:00`;

function monthLabel(monthKey) {
  const [year, month] = String(monthKey).split("-");
  return `${Number(year)}년 ${Number(month)}월`;
}

function compactDateLabel(dateKey) {
  const date = new Date(dateAtNoon(dateKey));
  const monthDay = date.toLocaleDateString("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Seoul",
  }).replace(/\.\s*/g, ".").replace(/\.$/, "");
  const weekday = date.toLocaleDateString("ko-KR", {
    weekday: "short",
    timeZone: "Asia/Seoul",
  });
  return `${monthDay} ${weekday.replace("요일", "")}`;
}

function sourceLink(article) {
  const href = safeUrl(article.source_url);
  if (!href) return "";
  return `<a class="source" href="${esc(href)}" target="_blank" rel="noopener">원문 보기 →</a>`;
}

function articleMeta(article) {
  const score = Number(article.importance_score || article.importance || 0);
  const scoreLabel = score ? `<span class="weight">W${score}</span>` : "";
  const date = `${article.date_is_estimated ? "수집 " : ""}${fmt(article.created_at, true)}`;
  return `<span class="sector">${esc(article.sector || "반도체")}</span>${scoreLabel}<span>${esc(article.source_name || "출처 미상")}</span><span>${esc(date)}</span>`;
}

function communityMeta(item) {
  const score = Number(item.community_score || 0);
  const reasons = Array.isArray(item.priority_reasons) ? item.priority_reasons : [];
  const date = `${item.date_is_estimated ? "수집 " : ""}${fmt(item.created_at, true)}`;
  return `<span class="weight">W${score || "-"}</span>${reasons.map((reason) => `<span>${esc(reason)}</span>`).join("")}<span>${esc(item.source_name || "커뮤니티")}</span><span>${esc(date)}</span>`;
}

function rankedArticle(article, index) {
  return `<button class="archive-ranked-item" type="button" data-article-id="${esc(article.id)}" aria-label="${index + 1}위 ${esc(article.headline)} 자세히 보기">
    <span class="archive-rank">${index + 1}</span>
    <span class="archive-ranked-copy">
      <h3>${esc(article.headline || "제목 없음")}</h3>
      <p>${esc(excerpt(article.body, 190) || "기사 요약을 준비 중입니다.")}</p>
    </span>
    <span class="archive-ranked-meta">${articleMeta(article)}</span>
  </button>`;
}

function moreArticle(article) {
  return `<button class="archive-more-row" type="button" data-article-id="${esc(article.id)}" aria-label="${esc(article.headline)} 자세히 보기">
    <span class="archive-more-meta">${articleMeta(article)}</span>
    <h3>${esc(article.headline || "제목 없음")}</h3>
    <p>${esc(excerpt(article.body, 160) || "기사 요약을 준비 중입니다.")}</p>
  </button>`;
}

function rankedCommunityItem(item, index) {
  const topic = item.topic || item.headline || "반도체 커뮤니티 이슈";
  return `<button class="archive-ranked-item" type="button" data-article-id="${esc(item.id)}" aria-label="${index + 1}위 ${esc(topic)} 자세히 보기">
    <span class="archive-rank">${index + 1}</span>
    <span class="archive-ranked-copy">
      <h3>${esc(topic)}</h3>
      <span class="archive-community-headline">게시글 · ${esc(item.headline || "제목 없음")}</span>
      <p><strong>반응</strong> · ${esc(item.reaction_summary || "뚜렷한 반응을 확인하지 못했습니다.")}</p>
    </span>
    <span class="archive-ranked-meta">${communityMeta(item)}</span>
  </button>`;
}

function renderDateNavigation() {
  $("archive-month").textContent = monthLabel(state.activeMonth);
  const monthItems = state.items.filter((item) => item.date.startsWith(state.activeMonth));
  $("archive-dates").innerHTML = monthItems.map((item) => {
    const selected = item.date === state.activeDate;
    return `<button class="archive-date-item" type="button" role="option" data-date="${esc(item.date)}" aria-selected="${selected}">
      <span class="archive-date-label">${esc(compactDateLabel(item.date))}</span>
      <span class="archive-date-count">${Number(item.article_count || 0).toLocaleString("ko-KR")}</span>
    </button>`;
  }).join("") || `<div class="empty">이 달의 브리핑이 없습니다.</div>`;

  const monthIndex = state.months.indexOf(state.activeMonth);
  $("archive-prev-month").disabled = monthIndex < 0 || monthIndex >= state.months.length - 1;
  $("archive-next-month").disabled = monthIndex <= 0;
}

async function loadSnapshot(item) {
  if (state.snapshotCache.has(item.date)) return state.snapshotCache.get(item.date);
  const snapshot = await loadJson(item.file);
  state.snapshotCache.set(item.date, snapshot);
  return snapshot;
}

function renderEdition(data, item) {
  const articles = Array.isArray(data.articles) ? data.articles : [];
  const communityItems = Array.isArray(data.community_items) ? data.community_items : [];
  const communityTopTen = selectCommunityTopTen(data);
  const topTen = selectDailyTopTen(data);
  const topIds = new Set(topTen.map((article) => article.id));
  const remaining = articles.filter((article) => !topIds.has(article.id));

  state.articlesById = new Map(articles.concat(communityItems).map((article) => [article.id, article]));
  const selectedDate = formatBriefingDate(dateAtNoon(item.date));
  $("archive-selected-date").textContent = data.generated_at
    ? `${selectedDate} · ${fmt(data.generated_at, true)} KST 업데이트`
    : selectedDate;
  $("archive-day-title").textContent = selectedDate;
  $("archive-day-count").textContent = `총 ${articles.length.toLocaleString("ko-KR")}개 기사`;
  $("archive-generated-at").textContent = "";
  $("archive-summary-copy").innerHTML = data.daily_summary
    ? `${para(data.daily_summary)}<span class="summary-note">중요도 점수 상위 ${topTen.length}개 기사 기준</span>`
    : `<p>이날의 요약이 없습니다.</p>`;
  $("archive-top-title").textContent = `오늘의 TOP ${topTen.length}`;
  $("archive-top10").innerHTML = topTen.length
    ? topTen.map(rankedArticle).join("")
    : `<div class="empty">이날의 주요 뉴스가 없습니다.</div>`;
  $("archive-more-title").textContent = remaining.length ? `더 많은 뉴스 · ${remaining.length}` : "더 많은 뉴스";
  $("archive-more-news").innerHTML = remaining.length
    ? remaining.map(moreArticle).join("")
    : `<div class="empty">추가 뉴스가 없습니다.</div>`;

  const hasCommunity = Boolean(data.community_summary || data.community_sentiment) || communityItems.length > 0;
  $("archive-community-section").hidden = !hasCommunity;
  if (hasCommunity) {
    const communitySummary = data.community_summary || data.community_sentiment;
    $("archive-community-summary").innerHTML = communitySummary
      ? `${para(communitySummary)}<span class="summary-note">사진 중심 게시물 제외 · 설계 및 프론티어 반도체 기업 가중치 반영</span>`
      : `<p>수집된 커뮤니티 반응 ${communityTopTen.length.toLocaleString("ko-KR")}건</p>`;
    $("archive-community-top-title").textContent = `커뮤니티 TOP ${communityTopTen.length}`;
    $("archive-community-top10").innerHTML = communityTopTen.length
      ? communityTopTen.map(rankedCommunityItem).join("")
      : `<div class="empty">이날의 커뮤니티 TOP 10이 없습니다.</div>`;
  }
  document.title = `${selectedDate} · 칩 브리핑 아카이브`;
}

function renderEditionError(message) {
  $("archive-day-title").textContent = "브리핑을 불러오지 못했습니다.";
  $("archive-day-count").textContent = "";
  $("archive-generated-at").textContent = "";
  $("archive-summary-copy").innerHTML = `<p>${esc(message)}</p>`;
  $("archive-top10").innerHTML = `<div class="empty">잠시 후 다시 시도해 주세요.</div>`;
  $("archive-more-news").innerHTML = "";
}

async function selectDate(dateKey, updateUrl = true) {
  const item = state.items.find((candidate) => candidate.date === dateKey);
  if (!item) return;

  state.activeDate = item.date;
  state.activeMonth = item.date.slice(0, 7);
  renderDateNavigation();
  if (updateUrl) {
    const url = new URL(window.location.href);
    url.searchParams.set("date", item.date);
    history.replaceState(null, "", url);
  }

  const requestVersion = ++state.requestVersion;
  $("archive-day-title").textContent = "브리핑을 불러오는 중입니다.";
  try {
    const data = await loadSnapshot(item);
    if (requestVersion !== state.requestVersion) return;
    renderEdition(data, item);
  } catch (error) {
    if (requestVersion !== state.requestVersion) return;
    console.error(`아카이브 ${item.date} 데이터를 불러오지 못했습니다.`, error);
    renderEditionError("선택한 날짜의 데이터 파일을 읽을 수 없습니다.");
  }
}

function changeMonth(direction) {
  const currentIndex = state.months.indexOf(state.activeMonth);
  const targetMonth = state.months[currentIndex + direction];
  if (!targetMonth) return;
  const targetItem = state.items.find((item) => item.date.startsWith(targetMonth));
  if (targetItem) selectDate(targetItem.date);
}

function openReader(articleId, returnFocus = document.activeElement) {
  const article = state.articlesById.get(articleId);
  if (!article) return;
  state.previousFocus = returnFocus;
  const isCommunity = Boolean(article.community_score || article.topic || article.reaction_summary);
  $("archive-reader-meta").innerHTML = isCommunity ? communityMeta(article) : articleMeta(article);
  $("archive-reader-title").textContent = article.headline || "";
  $("archive-reader-date").textContent = `${article.date_is_estimated ? "수집 시각 " : ""}${fmt(article.created_at)}`;
  $("archive-reader-source").innerHTML = sourceLink(article);
  const communityDetails = isCommunity
    ? `${article.topic ? `<p><strong>주제</strong><br>${esc(article.topic)}</p>` : ""}${article.reaction_summary ? `<p><strong>반응 요약</strong><br>${esc(article.reaction_summary)}</p>` : ""}`
    : "";
  $("archive-reader-body").innerHTML = communityDetails + para(article.body);
  $("archive-reader").classList.add("open");
  $("archive-reader").setAttribute("aria-hidden", "false");
  document.body.style.overflow = "hidden";
  $("archive-reader-close").focus();
}

function closeReader() {
  if (!$("archive-reader").classList.contains("open")) return;
  $("archive-reader").classList.remove("open");
  $("archive-reader").setAttribute("aria-hidden", "true");
  document.body.style.overflow = "";
  state.previousFocus?.focus?.();
}

async function init() {
  const index = await loadJson("archive/index.json");
  state.items = Array.isArray(index.items) ? index.items.filter((item) => item.date && item.file) : [];
  if (!state.items.length) throw new Error("아카이브 인덱스가 비어 있습니다.");
  state.months = [...new Set(state.items.map((item) => item.date.slice(0, 7)))].sort().reverse();

  const requestedDate = new URL(window.location.href).searchParams.get("date");
  const initialDate = state.items.some((item) => item.date === requestedDate) ? requestedDate : state.items[0].date;

  $("archive-dates").addEventListener("click", (event) => {
    const button = event.target.closest("[data-date]");
    if (button) selectDate(button.dataset.date);
  });
  $("archive-prev-month").addEventListener("click", () => changeMonth(1));
  $("archive-next-month").addEventListener("click", () => changeMonth(-1));
  $("archive-content").addEventListener("click", (event) => {
    const article = event.target.closest("[data-article-id]");
    if (article) openReader(article.dataset.articleId, article);
  });
  $("archive-reader-close").addEventListener("click", closeReader);
  $("archive-reader").addEventListener("click", (event) => {
    if (event.target.id === "archive-reader") closeReader();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeReader();
  });
  window.addEventListener("popstate", () => {
    const date = new URL(window.location.href).searchParams.get("date");
    if (date && date !== state.activeDate) selectDate(date, false);
  });

  await selectDate(initialDate, Boolean(requestedDate));
}

init().catch((error) => {
  console.error("아카이브 초기화에 실패했습니다.", error);
  $("archive-selected-date").textContent = "아카이브";
  $("archive-dates").innerHTML = `<div class="empty">저장된 아카이브가 없습니다.</div>`;
  renderEditionError("일일 업데이트가 실행되면 날짜별 브리핑이 여기에 쌓입니다.");
});
