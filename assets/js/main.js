import {
  $,
  bulletList,
  esc,
  excerpt,
  firstSentence,
  fmt,
  fmtUpdated,
  formatBriefingDate,
  initTheme,
  loadJson,
  para,
  safeUrl,
  selectCommunityTopTen,
  selectDailyTopTen,
  selectDetailedArticles,
  selectHeadlineArticles,
  sortByImportance,
} from "./shared.js?v=28";
import { initAnalytics, setAnalyticsCategory } from "./analytics.js?v=1";

(async function () {
  initTheme();

  let data;
  try {
    data = window.__CHIP_ARTICLES__ || await loadJson("articles.json");
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

  const sectors = ["전체"].concat(
    data.sectors || ["설계", "공정", "소자", "패키징", "신제품/발표", "실적/투자/정책/인사"]
  );
  const communityFilters = [
    { key: "all", label: "전체" },
    { key: "domestic", label: "국내 커뮤니티" },
    { key: "reddit", label: "Reddit" }
  ];
  let activeSector = "전체";
  let activeCommunity = "all";
  let activeView = location.hash === "#community" ? "community" : "news";

  function analyticsCategory() {
    if (activeView === "community") {
      if (activeCommunity === "domestic") return "커뮤니티/국내";
      if (activeCommunity === "reddit") return "커뮤니티/Reddit";
      return "커뮤니티/전체";
    }
    return activeSector === "전체" ? "뉴스/전체" : activeSector;
  }

  let previousFocus = null;
  let previousSummaryFocus = null;
  let returnToDailySummary = false;
  let summaryReturnItem = null;
  let summaryReturnScrollTop = 0;
  const articles = Array.isArray(data.articles) ? data.articles : [];
  const detailedArticles = selectDetailedArticles(data);
  const detailedIds = new Set(detailedArticles.map((article) => article.id));
  const headlineArticles = selectHeadlineArticles(data);
  const headlineIds = new Set(headlineArticles.map((article) => article.id));
  const communityItems = selectCommunityTopTen(data);
  const byId = Object.fromEntries(articles.concat(communityItems).map((a) => [a.id, a]));
  $("updated").textContent = fmtUpdated(data.generated_at);

  function renderNotice() {
    const notice = $("site-notice");
    if (!notice) return;
    const messages = [];
    const generated = new Date(data.generated_at);
    if (!Number.isNaN(generated.getTime())) {
      const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
      const shown = generated.toLocaleDateString("en-CA", { timeZone: "Asia/Seoul" });
      if (today !== shown) {
        messages.push("오늘 브리핑이 아직 준비되지 않았습니다. 이전 브리핑을 보여드립니다.");
      }
    }
    notice.textContent = messages.join(" ");
    notice.hidden = messages.length === 0;
  }

  function shortSourceName(value) {
    const raw = String(value || "뉴스").replace(/\s*(Search|RSS)$/i, "").trim();
    return raw === "Naver News" ? "국내 언론" : raw;
  }

  function badge(a) {
    return `<span class="sector">${esc(a.sector || "반도체")}</span><span class="meta-dot">·</span><span>${esc(shortSourceName(a.source_name))}</span><span class="meta-dot">·</span><span>${esc(fmt(a.created_at, true))}</span>`;
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
    const place = a.community_name || shortSourceName(a.source_name) || "커뮤니티";
    const date = a.date_is_estimated ? `수집 ${fmt(a.created_at)}` : fmt(a.created_at);
    return `<span class="origin-label">${esc(label)}</span><span class="meta-dot">·</span><span>${esc(place)}</span><span class="meta-dot">·</span><span>${esc(date)}</span>`;
  }
  function sourceLink(a) {
    const href = safeUrl(a.source_url);
    if (!href) return "";
    return `<a class="source" href="${esc(href)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">원문 보기 <span aria-hidden="true">↗</span></a>`;
  }
  function renderFilters() {
    $("news-filters").innerHTML = sectors.map((sector) =>
      `<button class="filter ${sector === activeSector ? "active" : ""}" data-sector="${esc(sector)}" aria-pressed="${sector === activeSector}">${esc(sector)}</button>`
    ).join("");
    $("news-filters").querySelectorAll(".filter").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeSector = btn.dataset.sector;
        setAnalyticsCategory(analyticsCategory());
        renderNews();
      });
    });
    $("community-filters").innerHTML = communityFilters.map((filter) =>
      `<button class="filter ${filter.key === activeCommunity ? "active" : ""}" data-community-filter="${filter.key}" aria-pressed="${filter.key === activeCommunity}">${filter.label}</button>`
    ).join("");
    $("community-filters").querySelectorAll(".filter").forEach((btn) => {
      btn.addEventListener("click", () => {
        activeCommunity = btn.dataset.communityFilter;
        setAnalyticsCategory(analyticsCategory());
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
  function thumbnailCell(a) {
    const src = safeUrl(a.image_url);
    if (!src) return "";
    return `<span class="summary-thumb-cell"><img class="summary-thumb" src="${esc(src)}" alt="" loading="lazy" onerror="this.closest('button').classList.remove('has-thumb');this.parentElement.remove()"></span>`;
  }
  function storyMedia(a, variant) {
    const src = safeUrl(a.image_url);
    if (!src) return "";
    return `<div class="story-media story-media-${variant}" aria-hidden="true"><img src="${esc(src)}" alt="" loading="lazy" onerror="this.closest('article').classList.remove('has-image');this.parentElement.remove()"></div>`;
  }
  function dailySummaryText() {
    const first = String(data.daily_summary || "")
      .split(/\n+/)
      .map((line) => line.replace(/^\s*[-*•·]+\s*/, "").trim())
      .find(Boolean) || "";
    const match = first.match(/^.*?[.!?。！？](?=\s|$)/);
    return match ? match[0].trim() : first;
  }
  function summaryTopTenItem(a, index) {
    const hasThumb = Boolean(safeUrl(a.image_url));
    const snippet = firstSentence(a.body, 95);
    return `<button class="summary-top10-item${hasThumb ? " has-thumb" : ""}" type="button" data-summary-article="${esc(a.id)}" aria-label="${index + 1}위 ${esc(a.headline)} 자세히 보기">
      <span class="summary-rank">${String(index + 1).padStart(2, "0")}</span>
      <span class="summary-item-body">
        <span class="summary-item-meta"><span class="sector">${esc(a.sector || "반도체")}</span><span>${esc(shortSourceName(a.source_name))}</span><span>${esc(fmt(a.created_at, true))}</span></span>
        <h3>${esc(a.headline || "제목 없음")}</h3>
        ${snippet ? `<p>${esc(snippet)}</p>` : ""}
      </span>
      ${thumbnailCell(a)}
    </button>`;
  }
  function openDailySummary() {
    const topTen = dailyTopTen();
    previousSummaryFocus = document.activeElement;
    $("daily-summary-dialog-title").textContent = `${briefingDate(data.generated_at)} TOP 10 뉴스`;
    $("daily-summary-date").textContent = `중요도 상위 ${topTen.length}개 핵심 기사`;
    const overview = dailySummaryText();
    $("daily-summary-overview").innerHTML = overview
      ? `<p>${esc(overview)}</p>`
      : `<p>지난 24시간 반도체 상황을 정리 중입니다.</p>`;
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
    const hasImage = Boolean(safeUrl(a.image_url));
    const className = (variant === "lead" ? "story story-lead" : variant === "latest" ? "story latest-item" : "story story-secondary")
      + (hasImage ? " has-image" : "");
    if (variant === "lead") {
      const lede = firstSentence(a.body, 130);
      return `<article class="${className}" data-id="${esc(a.id)}" role="button" tabindex="0">
        ${storyMedia(a, "lead")}
        <div class="meta">${badge(a)}</div>
        <h2>${esc(a.headline)}</h2>
        ${lede ? `<p class="lede">${esc(lede)}</p>` : ""}
        ${sourceLink(a)}
      </article>`;
    }
    if (variant === "secondary") {
      const snippet = firstSentence(a.body, 88);
      return `<article class="${className}" data-id="${esc(a.id)}" role="button" tabindex="0">
        <div class="story-content">
          <div class="meta">${badge(a)}</div>
          <h3>${esc(a.headline)}</h3>
          ${snippet ? `<p class="story-snippet">${esc(snippet)}</p>` : ""}
        </div>
        ${storyMedia(a, "secondary")}
      </article>`;
    }
    return `<article class="${className}" data-id="${esc(a.id)}" role="button" tabindex="0">
      <div class="story-content">
        <div class="meta">${badge(a)}</div>
        <h3>${esc(a.headline)}</h3>
      </div>
      ${storyMedia(a, "latest")}
    </article>`;
  }
  function titleRow(a) {
    const href = safeUrl(a.source_url);
    const tag = href ? "a" : "div";
    const attrs = href ? ` href="${esc(href)}" target="_blank" rel="noopener"` : "";
    return `<${tag} class="feed-row"${attrs}>
      <div class="meta"><span class="sector">${esc(a.sector || "반도체")}</span></div>
      <div class="feed-title">${esc(a.headline || "제목 없음")}</div>
      <div class="feed-source">${esc(shortSourceName(a.source_name))} · ${esc(fmt(a.created_at, true))}</div>
    </${tag}>`;
  }
  function summaryRow(a) {
    return `<article class="feed-row summary-feed-row" data-id="${esc(a.id)}" role="button" tabindex="0">
      <div class="meta"><span class="sector">${esc(a.sector || "반도체")}</span></div>
      <div class="feed-title">${esc(a.headline || "제목 없음")}</div>
      <div class="feed-source">${esc(shortSourceName(a.source_name))} · ${esc(fmt(a.created_at, true))}</div>
    </article>`;
  }
  function communityTopTenItem(a, index) {
    const topic = a.topic || a.headline || "반도체 커뮤니티 이슈";
    return `<button class="summary-top10-item community-top10-item" type="button" data-id="${esc(a.id)}" aria-label="${index + 1}위 ${esc(topic)} 자세히 보기">
      <span class="summary-rank">${String(index + 1).padStart(2, "0")}</span>
      <span class="summary-item-body">
        <span class="summary-item-meta">${communityMeta(a)}</span>
        <h3>${esc(topic)}</h3>
        <span class="community-post-headline">${esc(a.headline || "제목 없음")}</span>
        <p>${esc(firstSentence(a.body, 120) || "요약을 준비 중입니다.")}</p>
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
    const mediaBox = $("reader-media");
    const imgUrl = safeUrl(a.image_url);
    if (mediaBox) {
      if (imgUrl) {
        mediaBox.innerHTML = `<img src="${esc(imgUrl)}" alt="" loading="lazy" onerror="this.parentElement.hidden=true">`;
        mediaBox.hidden = false;
      } else {
        mediaBox.innerHTML = "";
        mediaBox.hidden = true;
      }
    }
    const topic = a.topic ? `<p class="reader-topic"><strong>핵심 주제</strong> · ${esc(a.topic)}</p>` : "";
    $("reader-body").innerHTML = topic + bulletList(a.body);
    $("reader").classList.add("open");
    $("reader").setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    $("close").focus();
  }
  function renderNews() {
    renderFilters();
    const dailySummary = dailySummaryText();
    $("daily-summary-container").innerHTML = dailySummary
      ? `<p class="summary-single-line">${esc(dailySummary)}</p><span class="summary-note">중요도 TOP 10 뉴스 기준</span>`
      : `<p class="summary-single-line">지난 24시간 반도체 상황을 정리 중입니다.</p><span class="summary-note">중요도 TOP 10 뉴스 기준</span>`;
    const rows = sortRows(visibleArticles());
    const summarized = rows.filter((article) => detailedIds.has(article.id));
    const headlineOnly = rows.filter((article) => headlineIds.has(article.id));
    const shownSummaries = summarized.slice(0, 10);
    const extraSummaries = summarized.slice(10);

    $("top").innerHTML = shownSummaries.length
      ? storyCard(shownSummaries[0], "lead")
      : `<div class="empty">이 섹터에 요약된 뉴스가 없습니다.</div>`;
    $("main").innerHTML = shownSummaries.slice(1, 4).map((a) => storyCard(a, "secondary")).join("") || `<div class="empty">이 섹터의 추가 브리핑이 없습니다.</div>`;
    $("side").innerHTML = shownSummaries.slice(4, 10).map((a) => storyCard(a, "latest")).join("") || `<div class="empty">추가 뉴스가 없습니다.</div>`;

    const groups = [];
    if (extraSummaries.length) {
      groups.push(`<div class="more-news-group">
        <h3>추가 요약 뉴스 · ${extraSummaries.length}</h3>
        ${extraSummaries.map(summaryRow).join("")}
      </div>`);
    }
    if (headlineOnly.length) {
      groups.push(`<div class="more-news-group">
        <h3>제목 뉴스 · ${headlineOnly.length}</h3>
        ${headlineOnly.map(titleRow).join("")}
      </div>`);
    }
    const scope = activeSector === "전체" ? "전체" : activeSector;
    $("more-news-title").textContent = `${scope} 뉴스 · 요약 ${summarized.length}개 · 제목 ${headlineOnly.length}개`;
    $("more-news").innerHTML = groups.join("") || `<div class="empty">표시할 추가 뉴스가 없습니다.</div>`;
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
    setAnalyticsCategory(analyticsCategory());
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
  renderNotice();
  renderNews();
  renderCommunity();
  setView(activeView, false);
  initAnalytics(analyticsCategory());
})();
