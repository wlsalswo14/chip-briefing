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
  selectDailyTopTen,
  sortByImportance,
} from "./shared.js";

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
  const communityItems = Array.isArray(data.community_items) ? data.community_items : [];
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
  function metrics(a) {
    const values = [];
    if (Number(a.comment_count) > 0) values.push(`댓글 ${Number(a.comment_count).toLocaleString("ko-KR")}`);
    if (Number(a.score) > 0) values.push(`추천 ${Number(a.score).toLocaleString("ko-KR")}`);
    if (Number(a.upvote_ratio) > 0) values.push(`긍정 ${Math.round(Number(a.upvote_ratio) * 100)}%`);
    return values.length ? `<div class="metrics">${values.map((value) => `<span>${esc(value)}</span>`).join("")}</div>` : "";
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
  function summaryTopTenItem(a, index) {
    const score = Number(a.importance_score || a.importance || 0);
    return `<button class="summary-top10-item" type="button" data-summary-article="${esc(a.id)}" aria-label="${index + 1}위 ${esc(a.headline)} 자세히 보기">
      <span class="summary-rank">${index + 1}</span>
      <span>
        <span class="summary-item-meta"><span class="score">중요도 ${score || "-"}</span><span>${esc(a.sector || "반도체")}</span><span>${esc(a.source_name || "출처 미상")}</span><span>${esc(fmt(a.created_at, true))}</span></span>
        <h3>${esc(a.headline || "제목 없음")}</h3>
        <p>${esc(excerpt(a.body, 170) || "기사 요약을 준비 중입니다.")}</p>
      </span>
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
    const summary = variant === "latest" ? "" : `<p class="${variant === "lead" ? "lede" : ""}">${esc(excerpt(a.body, variant === "lead" ? 260 : 150))}</p>`;
    const link = variant === "latest" ? "" : sourceLink(a);
    return `<article class="${className}" data-id="${esc(a.id)}" role="button" tabindex="0">
      <div class="meta">${badge(a)}</div>
      <${heading}>${esc(a.headline)}</${heading}>
      ${summary}${link}
    </article>`;
  }
  function feedRow(a, isCommunity = false) {
    const first = isCommunity
      ? `<span class="origin-label">${communityOrigin(a) === "reddit" ? "Reddit" : "국내"}</span>`
      : `<span class="sector">${esc(a.sector || "반도체")}</span>`;
    const source = isCommunity ? (a.community_name || a.source_name || "커뮤니티") : (a.source_name || "출처 미상");
    const summary = isCommunity ? (a.reaction_summary || excerpt(a.body, 150)) : excerpt(a.body, 150);
    const date = `${isCommunity && a.date_is_estimated ? "수집 " : ""}${fmt(a.created_at, true)}`;
    return `<article class="feed-row" data-id="${esc(a.id)}" role="button" tabindex="0">
      <div class="meta">${first}</div>
      <div class="feed-source">${esc(source)}<br>${esc(date)}</div>
      <div class="feed-title">${esc(a.headline)}</div>
      <div class="feed-summary">${esc(summary)}</div>
    </article>`;
  }
  function communityCard(a, variant = "item") {
    if (!a) return `<div class="empty">해당 출처의 반응이 없습니다.</div>`;
    if (variant === "lead") {
      return `<article class="community-story community-lead" data-id="${esc(a.id)}" role="button" tabindex="0">
        <div class="meta">${communityMeta(a)}</div>
        <h2>${esc(a.headline)}</h2>
        <p class="lede">${esc(a.reaction_summary || excerpt(a.body, 260))}</p>
        ${metrics(a)}${sourceLink(a)}
        <p class="community-disclaimer">커뮤니티의 의견과 추측을 요약한 내용이며, 확인된 사실이 아닐 수 있습니다.</p>
      </article>`;
    }
    return `<article class="community-story community-item" data-id="${esc(a.id)}" role="button" tabindex="0">
      <div class="meta">${communityMeta(a)}</div>
      <h3>${esc(a.headline)}</h3>
      <p>${esc(a.reaction_summary || excerpt(a.body, 160))}</p>
      ${metrics(a)}
    </article>`;
  }
  function openReader(id, returnFocus = document.activeElement) {
    const a = byId[id];
    if (!a) return;
    previousFocus = returnFocus;
    $("reader-sector").innerHTML = (a.category === "community" || a.raw_source_type === "community") ? communityMeta(a) : badge(a);
    $("reader-title").textContent = a.headline || "";
    $("reader-date").textContent = `${a.date_is_estimated ? "수집 시각 " : ""}${fmt(a.created_at)}`;
    $("reader-source").innerHTML = sourceLink(a);
    const reaction = a.reaction_summary ? `<p><strong>반응 요약</strong><br>${esc(a.reaction_summary)}</p>` : "";
    $("reader-body").innerHTML = reaction + para(a.body);
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
    const top = rows[0];
    const rest = rows.slice(1);
    $("top").innerHTML = storyCard(top, "lead");
    $("main").innerHTML = rest.slice(0, 3).map((a) => storyCard(a, "secondary")).join("") || `<div class="empty">이 섹터의 추가 브리핑이 없습니다.</div>`;
    $("side").innerHTML = rest.slice(3, 9).map((a) => storyCard(a, "latest")).join("") || `<div class="empty">추가 뉴스가 없습니다.</div>`;
    $("more-news").innerHTML = rest.slice(9).map((a) => feedRow(a)).join("") || `<div class="empty">표시할 추가 뉴스가 없습니다.</div>`;
  }
  function renderCommunity() {
    renderFilters();
    const filtered = communityItems
      .filter((item) => activeCommunity === "all" || communityOrigin(item) === activeCommunity)
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    $("community-sentiment-container").innerHTML = data.community_sentiment
      ? `${para(data.community_sentiment)}<span class="summary-note">커뮤니티 반응은 사실 확인 전 의견·추측을 포함할 수 있습니다.</span>`
      : `<p>${communityItems.length ? "오늘 수집된 반응을 출처별로 모았습니다." : "오늘 수집된 커뮤니티 반응이 없습니다."}</p><span class="summary-note">커뮤니티 반응은 사실 확인 전 의견·추측을 포함할 수 있습니다.</span>`;
    const lead = filtered[0];
    const remaining = filtered.slice(1);
    let domestic = remaining.filter((item) => communityOrigin(item) === "domestic");
    let reddit = remaining.filter((item) => communityOrigin(item) === "reddit");
    if (activeCommunity === "domestic") {
      domestic = remaining.slice(0, 3);
      reddit = remaining.slice(3, 6);
      $("domestic-title").textContent = "국내 커뮤니티";
      $("reddit-title").textContent = "국내 반응 더보기";
    } else if (activeCommunity === "reddit") {
      domestic = remaining.slice(0, 3);
      reddit = remaining.slice(3, 6);
      $("domestic-title").textContent = "Reddit";
      $("reddit-title").textContent = "Reddit 더보기";
    } else {
      $("domestic-title").textContent = "국내 커뮤니티";
      $("reddit-title").textContent = "Reddit";
    }
    $("community-lead").innerHTML = lead ? communityCard(lead, "lead") : `<div class="empty">선택한 출처의 반응이 없습니다.</div>`;
    $("community-domestic").innerHTML = domestic.slice(0, 3).map((a) => communityCard(a)).join("") || `<div class="empty">수집된 반응이 없습니다.</div>`;
    $("community-reddit").innerHTML = reddit.slice(0, 3).map((a) => communityCard(a)).join("") || `<div class="empty">수집된 반응이 없습니다.</div>`;
    const shown = new Set([lead, ...domestic.slice(0, 3), ...reddit.slice(0, 3)].filter(Boolean).map((item) => item.id));
    $("more-community").innerHTML = filtered.filter((item) => !shown.has(item.id)).map((a) => feedRow(a, true)).join("") || `<div class="empty">표시할 추가 반응이 없습니다.</div>`;
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
