import {
  $,
  esc,
  excerpt,
  fmt,
  fmtUpdated,
  formatBriefingDate,
  loadJson,
  para,
  safeUrl,
  selectCommunityTopTen,
  selectDailyTopTen,
  sortByImportance,
} from "./shared.js?v=4";

(async function () {

  let data;
  try {
    data = await loadJson("articles.json");
  } catch (error) {
    console.error("브리핑 데이터를 불러오지 못했습니다.", error);
    $("updated").textContent = "업데이트 데이터를 불러오지 못했습니다.";
    document.querySelector("main").innerHTML = `
      <section class="load-error" role="alert">
        <h2>브리핑을 불러오지 못했습니다.</h2>
        <p>로컬 서버를 통해 다시 접속하거나 잠시 후 새로고침해 주세요.</p>
      </section>`;
    return;
  }

  const sectors = ["전체"].concat(data.sectors || ["설계", "공정", "소자", "패키징"]);
  const communityFilters = [
    { key: "all", label: "전체" },
    { key: "domestic", label: "국내 커뮤니티" },
    { key: "reddit", label: "Reddit" }
  ];
  let activeSector = "전체";
  let activeCommunity = "all";
  let activeView = location.hash === "#community" ? "community" : "news";
  let previousFocus = null;
  let previousSummaryFocus = null;
  let returnToDailySummary = false;
  let summaryReturnItem = null;
  let summaryReturnScrollTop = 0;
  const articles = Array.isArray(data.articles) ? data.articles : [];
  const communityItems = selectCommunityTopTen(data);
  const byId = Object.fromEntries(articles.concat(communityItems).map((a) => [a.id, a]));
  $("updated").textContent = fmtUpdated(data.generated_at);

  function badge(a) {
    const score = Number(a.importance_score || a.importance || 0);
    const scoreLabel = score ? `<span class="weight">W${score}</span>` : "";
    return `<span class="sector">${esc(a.sector || "반도체")}</span>${scoreLabel}<span>${esc(a.source_name || "출처 미상")}</span><span>${esc(fmt(a.created_at, true))}</span>`;
  }
  function communityOrigin(a) {
    if (a.community_origin) return a.community_origin;
    const source = String(a.source_name || "").toLowerCase();
    if (source.includes("reddit")) return "reddit";
    if (["naver cafe", "카페", "dcinside", "클리앙", "퀘이사존", "루리웹", "뽐뿌", "fmkorea"].some((name) => source.includes(name))) return "domestic";
    return "other";
  }
  function communityMeta(a) {
    const origin = communityOrigin(a);
    const label = origin === "reddit" ? "Reddit" : origin === "domestic" ? "국내 커뮤니티" : "글로벌 커뮤니티";
    const place = a.community_name || a.source_name || "커뮤니티";
    const date = `${a.date_is_estimated ? "수집 " : ""}${fmt(a.created_at, true)}`;
    return `<span class="origin-label">${esc(label)}</span><span>${esc(place)}</span><span>${esc(date)}</span>`;
  }
  function sourceLink(a) {
    const href = safeUrl(a.source_url);
    if (!href) return "";
    return `<a class="source" href="${esc(href)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">원문 보기 →</a>`;
  }
  function renderFilters() {
    $("news-filters").innerHTML = sectors.map((sector) =>
      `<button class="filter ${sector === activeSector ? "active" : ""}" data-sector="${esc(sector)}" aria-pressed="${sector === activeSector}">${esc(sector)}</button>`
    ).join("");
    $("news-filters").querySelectorAll(".filter").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeSector = btn.dataset.sector;
        renderNews();
      });
    });
    $("community-filters").innerHTML = communityFilters.map((filter) =>
      `<button class="filter ${filter.key === activeCommunity ? "active" : ""}" data-community-filter="${filter.key}" aria-pressed="${filter.key === activeCommunity}">${filter.label}</button>`
    ).join("");
    $("community-filters").querySelectorAll(".filter").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeCommunity = btn.dataset.communityFilter;
        renderCommunity();
      });
    });
  }
  function visibleArticles() {
    return activeSector === "전체" ? articles : articles.filter((a) => a.sector === activeSector);
  }
  function sortRows(rows) {
    return sortByImportance(rows);
  }
  function dailyTopTen() {
    return selectDailyTopTen(data);
  }
  function briefingDate(iso) {
    return formatBriefingDate(iso, "short");
  }
  function shortSourceName(value) {
    return String(value || "출처 미상").replace(/\s*(Search|RSS)$/i, "").trim();
  }
  function thumbnailCell(a) {
    const fallback = `<span class="summary-thumb-fallback"><span class="ph-sector">${esc(a.sector || "반도체")}</span><span class="ph-source">${esc(shortSourceName(a.source_name))}</span></span>`;
    const src = safeUrl(a.image_url);
    if (!src) return `<span class="summary-thumb-cell is-broken">${fallback}</span>`;
    return `<span class="summary-thumb-cell"><img class="summary-thumb" src="${esc(src)}" alt="" loading="lazy" onerror="this.parentElement.classList.add('is-broken');this.remove()">${fallback}</span>`;
  }
  function summaryTopTenItem(a, index) {
    const score = Number(a.importance_score || a.importance || 0);
    return `<button class="summary-top10-item" type="button" data-summary-article="${esc(a.id)}" aria-label="${index + 1}위 ${esc(a.headline)} 자세히 보기">
      <span class="summary-rank">${index + 1}</span>
      <span>
        <span class="summary-item-meta"><span class="score">중요도 ${score || "-"}</span><span>${esc(a.sector || "반도체")}</span><span>${esc(a.source_name || "출처 미상")}</span><span>${esc(fmt(a.created_at, true))}</span></span>
        <h3>${esc(a.headline || "제목 없음")}</h3>
        <p>${esc(excerpt(a.body, 420, 5) || "기사 요약을 준비 중입니다.")}</p>
      </span>
      ${thumbnailCell(a)}
    </button>`;
  }
  function openDailySummary() {
    const topTen = dailyTopTen();
    previousSummaryFocus = document.activeElement;
    $("daily-summary-dialog-title").textContent = `${briefingDate(data.generated_at)} TOP 10 뉴스`;
    $("daily-summary-date").textContent = `중요도 점수 우선 · 동점은 최신 기사 순 · ${topTen.length}개 선정`;
    $("daily-summary-overview").innerHTML = data.daily_summary
      ? para(data.daily_summary)
      : `<p>오늘의 핵심 흐름을 정리 중입니다.</p>`;
    $("daily-summary-top10").innerHTML = topTen.length
      ? topTen.map(summaryTopTenItem).join("")
      : `<div class="empty">표시할 뉴스가 없습니다.</div>`;
    $("daily-summary-dialog").classList.add("open");
    $("daily-summary-dialog").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    $("daily-summary-close").focus();
  }
  function closeDailySummary(restoreFocus = true) {
    if (!$("daily-summary-dialog").classList.contains("open")) return;
    $("daily-summary-dialog").classList.remove("open");
    $("daily-summary-dialog").setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    if (restoreFocus && previousSummaryFocus && typeof previousSummaryFocus.focus === "function") previousSummaryFocus.focus();
  }
  function returnToSummary() {
    const dialog = $("daily-summary-dialog");
    dialog.classList.add("open");
    dialog.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    dialog.scrollTop = summaryReturnScrollTop;
    if (summaryReturnItem && summaryReturnItem.isConnected) summaryReturnItem.focus();
    else $("daily-summary-close").focus();
  }
  function storyCard(a, variant) {
    if (!a) return `<div class="empty">표시할 뉴스가 없습니다.</div>`;
    const className = variant === "lead" ? "story story-lead" : variant === "latest" ? "story latest-item" : "story story-secondary";
    const heading = variant === "lead" ? "h2" : "h3";
    const summary = variant === "latest" ? "" : `<p class="${variant === "lead" ? "lede" : ""}">${esc(excerpt(a.body, variant === "lead" ? 520 : 380, 5))}</p>`;
    const link = variant === "latest" ? "" : sourceLink(a);
    return `<article class="${className}" data-id="${esc(a.id)}" role="button" tabindex="0">
      <div class="meta">${badge(a)}</div>
      <${heading}>${esc(a.headline)}</${heading}>
      ${summary}${link}
    </article>`;
  }
  // Everything outside the TOP 10 is published as a headline that links
  // straight to the original article.
  function titleRow(a) {
    const href = safeUrl(a.source_url);
    const tag = href ? "a" : "div";
    const attrs = href ? ` href="${esc(href)}" target="_blank" rel="noopener"` : "";
    return `<${tag} class="feed-row"${attrs}>
      <div class="meta"><span class="sector">${esc(a.sector || "반도체")}</span></div>
      <div class="feed-source">${esc(a.source_name || "출처 미상")}<br>${esc(fmt(a.created_at, true))}</div>
      <div class="feed-title">${esc(a.headline || "제목 없음")}</div>
      <div class="feed-link">원문 보기 →</div>
    </${tag}>`;
  }
  function communityTopTenItem(a, index) {
    const score = Number(a.community_score || 0);
    const topic = a.topic || a.headline || "반도체 커뮤니티 이슈";
    return `<button class="summary-top10-item community-top10-item" type="button" data-id="${esc(a.id)}" aria-label="${index + 1}위 ${esc(topic)} 자세히 보기">
      <span class="summary-rank">${index + 1}</span>
      <span>
        <span class="summary-item-meta"><span class="score">W${score || "-"}</span>${communityMeta(a)}</span>
        <h3>${esc(topic)}</h3>
        <span class="community-post-headline">게시글 · ${esc(a.headline || "제목 없음")}</span>
        <p>${esc(excerpt(a.body, 420, 5) || "요약을 준비 중입니다.")}</p>
      </span>
    </button>`;
  }
  function openReader(id, returnFocus = document.activeElement) {
    const a = byId[id];
    if (!a) return;
    previousFocus = returnFocus;
    $("reader-sector").innerHTML = (a.category === "community" || a.raw_source_type === "community") ? communityMeta(a) : badge(a);
    $("reader-title").textContent = a.headline || "";
    $("reader-date").textContent = `${a.date_is_estimated ? "수집 시각 " : ""}${fmt(a.created_at)}`;
    $("reader-source").innerHTML = sourceLink(a);
    const topic = a.topic ? `<p><strong>주제</strong><br>${esc(a.topic)}</p>` : "";
    $("reader-body").innerHTML = topic + para(a.body);
    $("reader").classList.add("open");
    $("reader").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    $("close").focus();
  }
  function renderNews() {
    renderFilters();
    $("daily-summary-container").innerHTML = data.daily_summary
      ? `${para(data.daily_summary)}<span class="summary-note">중요도 점수 상위 10개 기사 기준</span>`
      : `<p>오늘의 주요 기사를 정리 중입니다.</p><span class="summary-note">중요도 점수 상위 10개 기사 기준</span>`;
    const rows = sortRows(visibleArticles());
    // 전체 탭은 데일리 TOP 10을, 섹터 탭은 그 섹터에서 요약된 10개를 카드로 보여준다.
    const dailyIds = new Set(Array.isArray(data.daily_summary_article_ids) ? data.daily_summary_article_ids : []);
    const summarized = rows.filter((a) => a.summary_method === "llm" && (activeSector === "전체" ? dailyIds.has(a.id) : true));
    // 10개를 넘는 요약분은 아래 목록으로 내려보낸다.
    const shownSummaries = summarized.slice(0, 10);
    const summarizedIds = new Set(shownSummaries.map((a) => a.id));
    const rest = rows.filter((a) => !summarizedIds.has(a.id));
    $("top").innerHTML = summarized.length
      ? storyCard(summarized[0], "lead")
      : `<div class="empty">이 섹터에 요약된 뉴스가 없습니다.</div>`;
    $("main").innerHTML = summarized.slice(1, 4).map((a) => storyCard(a, "secondary")).join("") || `<div class="empty">이 섹터의 추가 브리핑이 없습니다.</div>`;
    $("side").innerHTML = summarized.slice(4, 10).map((a) => storyCard(a, "latest")).join("") || `<div class="empty">추가 뉴스가 없습니다.</div>`;
    $("more-news").innerHTML = rest.map(titleRow).join("") || `<div class="empty">표시할 추가 뉴스가 없습니다.</div>`;
  }
  function renderCommunity() {
    renderFilters();
    const filtered = communityItems
      .filter((item) => activeCommunity === "all" || communityOrigin(item) === activeCommunity);
    const label = activeCommunity === "domestic" ? "국내 커뮤니티" : activeCommunity === "reddit" ? "Reddit" : "커뮤니티";
    $("community-top-title").textContent = `${label} TOP ${filtered.length}`;
    $("community-top10").innerHTML = filtered.length
      ? filtered.map(communityTopTenItem).join("")
      : `<div class="empty">선택한 출처의 TOP 10 반응이 없습니다.</div>`;
  }
  function setView(view, updateUrl = true) {
    activeView = view === "community" ? "community" : "news";
    document.querySelectorAll(".view-tab[data-view]").forEach((tab) => {
      const selected = tab.dataset.view === activeView;
      tab.setAttribute("aria-pressed", String(selected));
    });
    $("news-view").hidden = activeView !== "news";
    $("community-view").hidden = activeView !== "community";
    if (updateUrl) history.replaceState(null, "", activeView === "community" ? "#community" : "#news");
    if (activeView === "community") renderCommunity();
    else renderNews();
  }
  function closeReader() {
    if (!$("reader").classList.contains("open")) return;
    $("reader").classList.remove("open");
    $("reader").setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
    if (returnToDailySummary) {
      returnToDailySummary = false;
      returnToSummary();
      return;
    }
    if (previousFocus && typeof previousFocus.focus === "function") previousFocus.focus();
  }

  document.querySelectorAll(".view-tab[data-view]").forEach((tab, index, tabs) => {
    tab.addEventListener("click", () => setView(tab.dataset.view));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const nextIndex = event.key === "ArrowRight" ? (index + 1) % tabs.length : (index - 1 + tabs.length) % tabs.length;
      tabs[nextIndex].focus();
      setView(tabs[nextIndex].dataset.view);
    });
  });
  document.addEventListener("click", (event) => {
    const row = event.target.closest("[data-id]");
    if (row && !event.target.closest("a")) openReader(row.dataset.id);
  });
  document.addEventListener("keydown", (event) => {
    const row = event.target.closest && event.target.closest("[data-id]");
    if (row && ["Enter", " "].includes(event.key)) {
      event.preventDefault();
      openReader(row.dataset.id);
    }
    if (event.key === "Escape") {
      if ($("daily-summary-dialog").classList.contains("open")) closeDailySummary();
      else closeReader();
    }
  });
  $("daily-summary-trigger").addEventListener("click", openDailySummary);
  $("daily-summary-close").addEventListener("click", () => closeDailySummary());
  $("daily-summary-dialog").addEventListener("click", (event) => {
    if (event.target.id === "daily-summary-dialog") closeDailySummary();
  });
  $("daily-summary-top10").addEventListener("click", (event) => {
    const item = event.target.closest("[data-summary-article]");
    if (!item) return;
    returnToDailySummary = true;
    summaryReturnItem = item;
    summaryReturnScrollTop = $("daily-summary-dialog").scrollTop;
    closeDailySummary(false);
    openReader(item.dataset.summaryArticle, item);
  });
  $("close").addEventListener("click", closeReader);
  $("reader").addEventListener("click", (e) => {
    if (e.target.id === "reader") closeReader();
  });
  window.addEventListener("hashchange", () => setView(location.hash === "#community" ? "community" : "news", false));
  renderNews();
  renderCommunity();
  setView(activeView, false);
})();
