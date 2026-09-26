import datetime as dt
import importlib.util
import json
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import collect_news as collector


class CommunityParserTests(unittest.TestCase):
    def test_dcinside_search_parser_keeps_nested_title_text(self):
        source = """
        <a href="https://gall.dcinside.com/mgallery/board/view/?id=chips&amp;no=1" class="tit_txt">
          HBM <b>공급</b> 전망
        </a>
        <p class="link_dsc_txt">설계 병목을 우려하는 반응</p>
        <a class="sub_txt">반도체산업</a>
        <span class="date_time">2026.08.22 09:30</span>
        """
        parser = collector.DCInsideSearchParser()
        parser.feed(source)
        self.assertEqual(
            parser.items,
            [{
                "url": "https://gall.dcinside.com/mgallery/board/view/?id=chips&no=1",
                "title": "HBM 공급 전망",
                "snippet": "설계 병목을 우려하는 반응",
                "community": "반도체산업",
                "date": "2026.08.22 09:30",
            }],
        )

    def test_clien_parser_skips_notices(self):
        source = """
        <div class="list_item notice"><a class="list_subject" href="/notice">공지 HBM</a></div>
        <div class="list_item symph_row">
          <a class="list_subject" href="/service/board/cm_stock/1">
            <span class="subject_fixed" title="HBM 전망"></span>
          </a>
          <span class="icon_pic fa fa-picture-o"></span>
          <span class="timestamp">2026-08-22 10:11:12</span>
        </div>
        """
        parser = collector.ClienBoardParser()
        parser.feed(source)
        self.assertEqual(
            parser.items,
            [{
                "url": "/service/board/cm_stock/1",
                "title": "HBM 전망",
                "has_image": "true",
                "date": "2026-08-22 10:11:12",
            }],
        )


class CommunityWindowTests(unittest.TestCase):
    def test_briefing_window_is_the_rolling_24_hours_before_the_run(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        now = dt.datetime(2026, 8, 23, 5, 30, tzinfo=kst)
        start, end = collector.briefing_window(now)
        self.assertEqual(end, now)
        self.assertEqual(start, now - dt.timedelta(hours=24))

    def test_briefing_window_shifts_with_a_late_scheduled_run(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        late = dt.datetime(2026, 8, 23, 7, 50, tzinfo=kst)
        start, end = collector.briefing_window(late)
        self.assertEqual(end, late)
        self.assertEqual(start, dt.datetime(2026, 8, 22, 7, 50, tzinfo=kst))

    def test_estimated_date_item_bypasses_exact_window(self):
        item = collector.make_article(
            "HBM test",
            "https://example.com/community/1",
            "HBM",
            {"name": "test", "category_default": "community", "trust_default": "low"},
            "community",
            collector.now_iso(),
        )
        item["date_is_estimated"] = True
        self.assertEqual(len(collector.dedupe_rank([item])), 1)

    def test_estimated_date_item_is_suppressed_when_seen_yesterday(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        yesterday = (dt.datetime.now(kst).date() - dt.timedelta(days=1)).isoformat()
        url = "https://example.com/community/seen"
        item = {"source_url": url, "date_is_estimated": True}
        with tempfile.TemporaryDirectory() as directory:
            archive_dir = Path(directory)
            (archive_dir / f"{yesterday}.json").write_text(
                json.dumps({"community_items": [{"source_url": url}]}),
                encoding="utf-8",
            )
            with mock.patch.object(collector, "ARCHIVE_DIR", archive_dir):
                logs = []
                self.assertEqual(collector.suppress_seen_estimated_community([item], logs), [])
                self.assertTrue(logs)

    def test_community_ranking_prioritizes_design_and_frontier_companies(self):
        items = [
            {
                "id": "design-company",
                "headline": "엔비디아 차세대 GPU 인터커넥트 설계",
                "body": "새 아키텍처의 병목과 전력 효율을 두고 기대와 우려가 함께 나왔다.",
                "source_name": "DCInside · 반도체",
                "created_at": "2026-08-22T10:00:00+09:00",
            },
            {
                "id": "company",
                "headline": "ASML 장비 공급 전망",
                "body": "장비 인도 일정에 관한 정보를 공유했다.",
                "source_name": "Clien · 모두의공원",
                "created_at": "2026-08-22T11:00:00+09:00",
            },
            {
                "id": "ordinary",
                "headline": "반도체 시장 이야기",
                "body": "일반적인 업황 이야기를 짧게 공유했다.",
                "source_name": "Naver Cafe · 투자",
                "created_at": "2026-08-22T12:00:00+09:00",
            },
        ]
        ranked = collector.rank_community_items(items, 3, source_cap=3)
        self.assertEqual(ranked[0]["id"], "design-company")
        self.assertEqual(ranked[0]["community_score"], 5)
        self.assertIn("설계 주제", ranked[0]["priority_reasons"])
        self.assertIn("프론티어 기업", ranked[0]["priority_reasons"])
        self.assertEqual(ranked[1]["community_score"], 4)
        self.assertGreater(ranked[1]["community_score"], ranked[2]["community_score"])

    def test_photo_filter_uses_source_flags_and_strict_title_markers(self):
        items = [
            {"id": "flagged", "headline": "HBM 분석", "has_image": True},
            {"id": "photo-title", "headline": "[사진] 웨이퍼 인증", "has_image": False},
            {"id": "sensor", "headline": "CMOS 이미지 센서 설계", "has_image": False},
        ]
        logs = []
        kept = collector.exclude_photo_community_items(items, logs)
        self.assertEqual([item["id"] for item in kept], ["sensor"])
        self.assertIn("excluded 2", logs[0])

    def test_clien_collection_pages_until_window_start(self):
        pages = [
            """
            <div class="list_item symph_row">
              <span class="subject_fixed" title="HBM newest"></span>
              <a class="list_subject" href="/service/board/park/3">HBM newest</a>
              <span class="timestamp">2026-08-23 09:00:00</span>
            </div>
            """,
            """
            <div class="list_item symph_row">
              <span class="subject_fixed" title="HBM in window"></span>
              <a class="list_subject" href="/service/board/park/2">HBM in window</a>
              <span class="timestamp">2026-08-22 12:00:00</span>
            </div>
            """,
            """
            <div class="list_item symph_row">
              <span class="subject_fixed" title="HBM old"></span>
              <a class="list_subject" href="/service/board/park/1">HBM old</a>
              <span class="timestamp">2026-08-22 06:59:59</span>
            </div>
            """,
        ]
        kst = dt.timezone(dt.timedelta(hours=9))
        source = {
            "name": "Clien",
            "url": "https://www.clien.net/service/board/",
            "boards": [{"id": "park", "name": "모두의공원"}],
            "max_pages": 10,
            "category_default": "community",
            "trust_default": "low",
        }
        with (
            mock.patch.object(collector, "request_text", side_effect=pages) as request,
            mock.patch.object(
                collector,
                "briefing_window",
                return_value=(
                    dt.datetime(2026, 8, 22, 7, 0, tzinfo=kst),
                    dt.datetime(2026, 8, 23, 7, 0, tzinfo=kst),
                ),
            ),
            mock.patch.object(collector.time, "sleep"),
        ):
            items, logs = collector.collect_clien(source)

        self.assertEqual(request.call_count, 3)
        self.assertEqual(len(items), 3)
        self.assertIn("3 pages", logs[0])


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class SummaryFormattingTests(unittest.TestCase):
    def test_clean_multiline_keeps_line_breaks(self):
        self.assertEqual(
            collector.clean_multiline("첫째 줄\n\n둘째 줄   셋째\n"),
            "첫째 줄\n둘째 줄 셋째",
        )

    def test_summary_cache_key_ignores_punctuation_and_case(self):
        self.assertEqual(
            collector.summary_cache_key("SK하이닉스, HBM4 양산 시작!"),
            collector.summary_cache_key("sk하이닉스 HBM4 양산 시작"),
        )

    def test_daily_summary_fallback_lists_headlines_on_their_own_lines(self):
        items = [
            {"headline": "첫 번째 기사", "body": "요약", "summary_method": "llm", "importance_score": 5},
            {"headline": "두 번째 기사", "body": "요약", "summary_method": "llm", "importance_score": 4},
        ]
        with mock.patch.object(collector, "LLM_BASE_URL", ""):
            summary = collector.generate_collection_summary(items, [], "daily")
        self.assertEqual(summary.split("\n"), ["· 첫 번째 기사", "· 두 번째 기사"])

    def test_daily_top10_prefers_summarized_articles_over_raw_snippets(self):
        items = [
            {
                "headline": "스니펫만 있는 기사",
                "body": "원문 일부만 있는 문장",
                "summary_method": "snippet",
                "importance_score": 5,
                "created_at": "2026-09-23T10:00:00+09:00",
            },
            {
                "headline": "요약된 기사",
                "body": "첫째 줄\n둘째 줄\n셋째 줄",
                "summary_method": "llm",
                "importance_score": 2,
                "created_at": "2026-09-23T09:00:00+09:00",
            },
        ]
        selected = collector.select_daily_summary_items(items, limit=1)
        self.assertEqual(selected[0]["headline"], "요약된 기사")

    def test_daily_top10_never_fills_with_headline_only_rows(self):
        items = [
            {
                "headline": "요약 기사",
                "body": "요약",
                "summary_method": "llm",
                "importance_score": 1,
                "created_at": "2026-09-25T09:00:00+09:00",
            }
        ] + [
            {
                "headline": f"제목 뉴스 {index}",
                "body": "수집 스니펫",
                "summary_method": "snippet",
                "publication_mode": "headline",
                "importance_score": 5,
                "created_at": "2026-09-25T10:00:00+09:00",
            }
            for index in range(12)
        ]

        selected = collector.select_daily_summary_items(items, limit=10)
        self.assertEqual([item["headline"] for item in selected], ["요약 기사"])

    def test_daily_top10_uses_full_gemma_importance_after_summary(self):
        items = [
            {
                "headline": "제목 점수는 높지만 본문 영향도는 낮은 기사",
                "body": "요약",
                "summary_method": "llm",
                "title_importance_score": 5,
                "importance_score": 2,
                "created_at": "2026-09-25T10:00:00+09:00",
            },
            {
                "headline": "본문 영향도가 높은 기사",
                "body": "요약",
                "summary_method": "llm",
                "title_importance_score": 1,
                "importance_score": 5,
                "created_at": "2026-09-25T09:00:00+09:00",
            },
        ]

        selected = collector.select_daily_summary_items(items, limit=1)
        self.assertEqual(selected[0]["headline"], "본문 영향도가 높은 기사")

    def test_sort_by_importance_puts_summarized_articles_first(self):
        items = [
            {
                "headline": "스니펫 기사",
                "body": "원문",
                "summary_method": "snippet",
                "importance_score": 5,
                "created_at": "2026-09-23T10:00:00+09:00",
            },
            {
                "headline": "요약 기사",
                "body": "첫째 줄\n둘째 줄",
                "summary_method": "llm",
                "importance_score": 1,
                "created_at": "2026-09-23T09:00:00+09:00",
            },
        ]
        ordered = collector.sort_by_importance(items)
        self.assertEqual([item["headline"] for item in ordered], ["요약 기사", "스니펫 기사"])

    def test_sector_candidate_ranking_prefers_the_higher_keyword_score(self):
        items = [
            {
                "id": "low",
                "headline": "일반 소식",
                "sector": "설계",
                "sector_score": 2,
                "created_at": "2026-09-25T12:00:00+09:00",
            },
            {
                "id": "high",
                "headline": "GPU NPU ASIC HBM CoWoS EUV",
                "sector": "설계",
                "sector_score": 12,
                "created_at": "2026-09-25T09:00:00+09:00",
            },
        ]

        picked = collector.sector_candidates_for(items, "설계")

        self.assertEqual([item["id"] for item in picked], ["high", "low"])

    def test_sector_candidate_ranking_breaks_ties_by_recency(self):
        items = [
            {
                "id": "older",
                "sector": "설계",
                "sector_score": 6,
                "created_at": "2026-09-25T09:00:00+09:00",
            },
            {
                "id": "newer",
                "sector": "설계",
                "sector_score": 6,
                "created_at": "2026-09-25T10:00:00+09:00",
            },
        ]

        picked = collector.sector_candidates_for(items, "설계")

        self.assertEqual([item["id"] for item in picked], ["newer", "older"])

    def test_news_candidates_reach_gemma_without_keyword_relevance_filter(self):
        article = {
            "id": "generic-title",
            "headline": "새로운 기술 협력 발표",
            "body": "구체적인 산업 키워드가 없는 검색 결과",
            "source_url": "https://example.com/generic",
            "trust": "medium",
            "category": "news",
            "created_at": collector.now_iso(),
            "date_is_estimated": True,
        }

        self.assertEqual(collector.dedupe_rank([dict(article)], limit=None), [])
        kept = collector.dedupe_rank(
            [dict(article)],
            limit=None,
            require_relevance=False,
        )
        self.assertEqual([item["id"] for item in kept], ["generic-title"])

    def test_news_title_dedupe_removes_cross_api_duplicates(self):
        base = {
            "headline": "동일한 반도체 기사 제목",
            "body": "snippet",
            "trust": "medium",
            "category": "news",
            "created_at": collector.now_iso(),
            "date_is_estimated": True,
        }
        rows = [
            {**base, "id": "google", "source_url": "https://news.google.com/article/1"},
            {**base, "id": "naver", "source_url": "https://publisher.example.com/article/1"},
        ]

        kept = collector.dedupe_rank(
            rows,
            limit=None,
            require_relevance=False,
            dedupe_titles=True,
        )
        self.assertEqual(len(kept), 1)


class SixTabKeywordScoringTests(unittest.TestCase):
    """Keyword weights decide the tab, and zero score drops the article."""

    def _loaded_keywords(self) -> dict:
        path = Path(collector.__file__).resolve().parent / "sources.json"
        config = json.loads(path.read_text(encoding="utf-8"))
        return collector.load_sector_keywords(config)

    def test_there_are_six_tabs_with_the_earnings_tab_last(self):
        self.assertEqual(len(collector.SECTOR_NAMES), 6)
        self.assertEqual(collector.SECTOR_NAMES[-1], "실적/투자/정책/인사")
        self.assertEqual(
            collector.DETAILED_SUMMARY_TARGET,
            collector.SECTOR_SUMMARY_TARGET * len(collector.SECTOR_NAMES),
        )

    def test_sources_json_defines_weighted_terms_for_every_tab(self):
        keywords = self._loaded_keywords()
        self.assertEqual(set(keywords), set(collector.SECTOR_NAMES))
        for sector, terms in keywords.items():
            self.assertTrue(terms, sector)
            self.assertTrue(all(1 <= weight <= 3 for _, weight in terms), sector)

    def test_title_match_counts_double_and_a_snippet_match_counts_once(self):
        keywords = {
            "설계": [("EDA", 3)],
            "공정": [],
            "소자": [],
            "패키징": [],
            "신제품/발표": [],
            "실적/투자/정책/인사": [],
        }
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", keywords):
            _, title_score, _ = collector.score_article_sectors("EDA 툴 공개", "")
            _, snippet_score, _ = collector.score_article_sectors("새 툴 공개", "EDA 툴")
        self.assertEqual(title_score, 6)
        self.assertEqual(snippet_score, 3)

    def test_one_high_weight_term_beats_several_low_weight_terms(self):
        keywords = {
            "설계": [("아키텍처", 3)],
            "공정": [("박막", 1), ("계측", 1)],
            "소자": [],
            "패키징": [],
            "신제품/발표": [],
            "실적/투자/정책/인사": [],
        }
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", keywords):
            sector, _, _ = collector.score_article_sectors("아키텍처와 박막 계측", "")
        self.assertEqual(sector, "설계")

    def test_headline_evidence_beats_a_snippet_mention(self):
        keywords = {
            "설계": [],
            "공정": [],
            "소자": [],
            "패키징": [("인터포저", 3)],
            "신제품/발표": [],
            "실적/투자/정책/인사": [("실적", 3)],
        }
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", keywords):
            sector, _, _ = collector.score_article_sectors(
                "삼전닉스 3분기 실적 전망",
                "본문에는 인터포저 수요 이야기가 길게 이어진다",
            )
        self.assertEqual(sector, "실적/투자/정책/인사")

    def test_broad_terms_are_ignored_inside_the_snippet(self):
        keywords = {
            "설계": [],
            "공정": [],
            "소자": [("HBM", 3)],
            "패키징": [],
            "신제품/발표": [],
            "실적/투자/정책/인사": [],
        }
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", keywords):
            snippet_only, score, hits = collector.score_article_sectors(
                "오늘의 증시 브리핑", "HBM 가격이 올랐다는 본문"
            )
            title_hit, title_score, _ = collector.score_article_sectors("HBM 가격 급등", "")
        self.assertEqual(snippet_only, "")
        self.assertEqual(score, 0)
        self.assertEqual(hits, [])
        self.assertEqual(title_hit, "소자")
        self.assertGreater(title_score, 0)

    def test_articles_are_scored_after_the_window_filter(self):
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", self._loaded_keywords()):
            article = collector.make_article(
                "TSMC 파운드리 수율 개선",
                "https://example.com/score-order",
                "snippet",
                {"name": "test", "category_default": "news", "trust_default": "medium"},
                "news",
                collector.now_iso(),
            )
            self.assertEqual(article["sector"], "")
            self.assertEqual(article["sector_score"], 0)
            logs: list[str] = []
            ranked = collector.rank_news_candidates([article], logs)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["sector"], "공정")
        self.assertGreater(ranked[0]["sector_score"], 0)
        self.assertTrue(any(line.startswith("window filter:") for line in logs), logs)

    def test_earnings_headline_routes_to_the_new_tab(self):
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", self._loaded_keywords()):
            sector, score, hits = collector.score_article_sectors(
                "마이크론, 4분기 실적과 가이던스 공개…영업이익 시장 예상 상회", ""
            )
        self.assertEqual(sector, "실적/투자/정책/인사", hits)
        self.assertGreater(score, 0)

    def test_new_product_headline_routes_to_the_product_tab(self):
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", self._loaded_keywords()):
            sector, score, _ = collector.score_article_sectors(
                "엔비디아, 차세대 AI 칩과 랙 플랫폼 공개", ""
            )
        self.assertEqual(sector, "신제품/발표")
        self.assertGreater(score, 0)

    def test_earnings_words_beat_a_passing_foundry_word(self):
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", self._loaded_keywords()):
            sector, _, _ = collector.score_article_sectors(
                "인텔, 파운드리 증설 투자와 실적 가이던스 발표", ""
            )
        self.assertEqual(sector, "실적/투자/정책/인사")

    def test_zero_score_headline_has_no_sector(self):
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", self._loaded_keywords()):
            sector, score, hits = collector.score_article_sectors(
                "프로야구 개막전 중계 일정 안내", ""
            )
        self.assertEqual(sector, "")
        self.assertEqual(score, 0)
        self.assertEqual(hits, [])

    def test_zero_score_articles_are_dropped_from_the_news_pool(self):
        logs: list[str] = []
        with mock.patch.object(collector, "_SECTOR_KEYWORDS", self._loaded_keywords()):
            scored = collector.make_article(
                "TSMC 파운드리 수율 개선",
                "https://example.com/scored",
                "snippet",
                {"name": "test", "category_default": "news", "trust_default": "medium"},
                "news",
                collector.now_iso(),
            )
            unscored = collector.make_article(
                "프로야구 개막전 중계 일정 안내",
                "https://example.com/unscored",
                "snippet",
                {"name": "test", "category_default": "news", "trust_default": "medium"},
                "news",
                collector.now_iso(),
            )
            ranked = collector.rank_news_candidates([scored, unscored], logs)
        self.assertEqual([item["source_url"] for item in ranked], ["https://example.com/scored"])
        self.assertTrue(any("dropped 1 zero-score" in line for line in logs), logs)

    def test_summary_prompt_no_longer_asks_for_a_sector(self):
        response = {
            "summary_lines": ["첫째", "둘째", "셋째", "넷째", "다섯째"],
            "keywords": ["AI 칩", "랙 플랫폼"],
            "importance_score": 5,
        }
        captured = {}

        def fake_post_json(url, payload, headers=None, timeout=None):
            captured["system"] = payload["systemInstruction"]["parts"][0]["text"]
            return {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(response, ensure_ascii=False)}]}}
                ]
            }

        article = {
            "headline": "새 AI 칩과 랙 플랫폼 공개",
            "source_name": "테스트",
            "source_url": "https://example.com/product",
            "sector": "설계",
        }
        with (
            mock.patch.object(
                collector,
                "LLM_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai",
            ),
            mock.patch.object(collector, "LLM_MODEL", "gemma-4-31b-it"),
            mock.patch.object(collector, "LLM_API_KEYS", ["test-key"]),
            mock.patch.object(collector, "post_json", side_effect=fake_post_json),
        ):
            summary, keywords, importance = collector.summarize_with_llm(
                article,
                "새 칩과 AI 서버 랙 플랫폼의 사양과 출시 일정을 공개했다.",
            )

        self.assertEqual(len(summary.split("\n")), 5)
        self.assertEqual(keywords, ["AI 칩", "랙 플랫폼"])
        self.assertEqual(importance, 5)
        self.assertNotIn("sector", captured["system"])
        self.assertIn("summary_lines", captured["system"])


class DetailedSummaryTargetTests(unittest.TestCase):
    def _keyword_items(self, counts=None):
        counts = counts or {sector: 12 for sector in collector.SECTOR_NAMES}
        rows = []
        number = 0
        for sector in collector.SECTOR_NAMES:
            for index in range(counts.get(sector, 0)):
                rows.append(
                    {
                        "id": f"news-{number:03d}",
                        "headline": f"{sector} 뉴스 {index}",
                        "body": "수집 스니펫",
                        "sector": sector,
                        "sector_score": 20 - (index % 10),
                        "sector_method": "keyword",
                        "trust": "medium",
                        "category": "news",
                        "source_name": "테스트",
                        "source_url": f"https://example.com/{number}",
                        "created_at": f"2026-09-25T{number % 24:02d}:00:00+09:00",
                    }
                )
                number += 1
        return rows

    def _run(self, items, summarizer):
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "missing-articles.json"
            with (
                mock.patch.object(collector, "ARTICLES_PATH", cache_path),
                mock.patch.object(collector, "LLM_BASE_URL", "https://example.test/v1"),
                mock.patch.object(collector, "LLM_MODEL", "gemma-test"),
                mock.patch.object(collector, "LLM_MAX_ITEMS", 100),
                mock.patch.object(collector, "extract_article_text", return_value="기사 본문 " * 100),
                mock.patch.object(collector, "summarize_with_llm", side_effect=summarizer) as summarize,
                mock.patch.object(collector.time, "sleep"),
                mock.patch("builtins.print"),
            ):
                collector.enrich_with_llm_summaries(items, [])
        return summarize

    def test_ten_summaries_are_published_per_keyword_tab_in_one_pass(self):
        items = self._keyword_items()
        summary = "첫째\n둘째\n셋째\n넷째\n다섯째"
        summarize = self._run(items, lambda article, text: (summary, ["HBM", "CoWoS"], 4))

        detailed = collector.select_detailed_summary_items(items)
        counts = {
            sector: sum(1 for item in detailed if item["sector"] == sector)
            for sector in collector.SECTOR_NAMES
        }
        expected = collector.SECTOR_SUMMARY_TARGET * len(collector.SECTOR_NAMES)
        self.assertEqual(len(detailed), expected)
        self.assertEqual(counts, {sector: 10 for sector in collector.SECTOR_NAMES})
        self.assertEqual(summarize.call_count, expected)
        self.assertTrue(all(item["sector_method"] == "keyword" for item in detailed))
        self.assertTrue(all(item["summary_sector"] == item["sector"] for item in detailed))

    def test_failed_summaries_fall_through_to_next_candidate_in_same_tab(self):
        items = self._keyword_items(
            {"설계": 13, "공정": 0, "소자": 0, "패키징": 0, "신제품/발표": 0, "실적/투자/정책/인사": 0}
        )
        calls = {"count": 0}
        summary = "첫째\n둘째\n셋째\n넷째\n다섯째"

        def flaky_summary(article, source_text):
            calls["count"] += 1
            if calls["count"] <= 3:
                raise RuntimeError("temporary model failure")
            return summary, ["ASIC"], 3

        summarize = self._run(items, flaky_summary)
        detailed = collector.select_detailed_summary_items(items)

        self.assertEqual(len(detailed), 10)
        self.assertTrue(all(item["sector"] == "설계" for item in detailed))
        self.assertEqual(summarize.call_count, 13)

    def test_underfilled_tab_reduces_the_target_instead_of_adding_headline_only_rows(self):
        counts = {
            "설계": 10,
            "공정": 7,
            "소자": 10,
            "패키징": 10,
            "신제품/발표": 10,
            "실적/투자/정책/인사": 10,
        }
        items = self._keyword_items(counts)
        for item in items:
            item["body"] = "첫째\n둘째\n셋째\n넷째\n다섯째"
            item["summary_method"] = "llm"
            item["summary_version"] = collector.SUMMARY_PROMPT_VERSION
            item["summary_model"] = "gemma-test"
            item["importance_score"] = item["sector_score"]

        detailed = collector.select_detailed_summary_items(items)
        self.assertEqual(collector.expected_detailed_summary_target(items), 57)
        self.assertEqual(len(detailed), 57)
        self.assertEqual(collector.select_headline_only_items(items, detailed), [])

    def test_candidates_beyond_ten_are_published_as_headline_only_links(self):
        counts = {sector: 10 for sector in collector.SECTOR_NAMES}
        counts["설계"] = 13
        items = self._keyword_items(counts)
        for sector in collector.SECTOR_NAMES:
            for item in collector.sector_candidates_for(items, sector)[:10]:
                item["body"] = "첫째\n둘째\n셋째\n넷째\n다섯째"
                item["summary_method"] = "llm"
                item["summary_version"] = collector.SUMMARY_PROMPT_VERSION
                item["summary_model"] = "gemma-test"
                item["importance_score"] = item["sector_score"]

        detailed = collector.select_detailed_summary_items(items)
        headline_only = collector.select_headline_only_items(items, detailed)

        self.assertEqual(len(detailed), 60)
        self.assertEqual(len(headline_only), 3)
        self.assertTrue(all(item["sector"] == "설계" for item in headline_only))
        self.assertTrue(all(item["publication_mode"] == "headline" for item in headline_only))
        self.assertTrue(all(item.get("summary_method") != "llm" for item in headline_only))


class CommunityBatchingTests(unittest.TestCase):
    def _items(self) -> list[dict]:
        items = []
        for source_index in range(3):
            for index in range(4):
                number = source_index * 4 + index
                items.append(
                    {
                        "id": "art-%02d" % number,
                        "headline": "커뮤니티 글 %d" % number,
                        "body": "본문 스니펫입니다.",
                        "source_name": "테스트 %d" % source_index,
                        "source_url": "https://example.com/%d" % number,
                        "category": "community",
                        "raw_source_type": "community",
                        "trust": "low",
                        "community_score": 3,
                        "created_at": "2026-09-25T07:00:00+09:00",
                    }
                )
        return items

    def test_community_posts_are_summarized_in_separate_batches(self):
        items = self._items()
        prompts = []

        def fake_post_json(url, payload, headers=None, timeout=None):
            text = payload["contents"][0]["parts"][0]["text"]
            prompts.append(text)
            ids = re.findall(r'"id": "(art-\d+)"', text)
            rows = [
                {
                    "id": article_id,
                    "topic": "주제",
                    "summary_lines": ["첫째", "둘째", "셋째", "넷째", "다섯째"],
                    "reaction_summary": "한 줄 요약",
                    "community_score": 4,
                }
                for article_id in ids
            ]
            body = {"community_summary_lines": ["커뮤니티 요약"], "items": rows}
            return {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(body, ensure_ascii=False)}]}}
                ]
            }

        with (
            mock.patch.object(collector, "post_json", side_effect=fake_post_json),
            mock.patch.object(
                collector, "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
            ),
            mock.patch.object(collector, "LLM_MODEL", "gemma-4-31b-it"),
            mock.patch.object(collector, "LLM_API_KEYS", ["test-key"]),
            mock.patch.object(collector.time, "sleep"),
        ):
            rows, _ = collector.enrich_community_reactions(items, [])

        self.assertGreater(len(prompts), 1, "요약 요청이 배치로 나뉘어야 한다")
        summarized = [item for item in rows if item.get("summary_method") == "llm"]
        self.assertGreaterEqual(len(summarized), 8)
        for item in summarized:
            self.assertEqual(len((item.get("body") or "").split("\n")), 5)

    def test_one_failed_batch_does_not_clear_the_others(self):
        items = self._items()
        calls = {"count": 0}

        def flaky_post_json(url, payload, headers=None, timeout=None):
            calls["count"] += 1
            # 첫 배치는 재시도까지 두 번 모두 실패시킨다.
            if calls["count"] <= 2:
                raise urllib.error.HTTPError("https://example.test", 503, "busy", {}, None)
            text = payload["contents"][0]["parts"][0]["text"]
            ids = re.findall(r'"id": "(art-\d+)"', text)
            rows = [
                {
                    "id": article_id,
                    "topic": "주제",
                    "summary_lines": ["첫째", "둘째", "셋째", "넷째", "다섯째"],
                    "reaction_summary": "한 줄 요약",
                    "community_score": 4,
                }
                for article_id in ids
            ]
            body = {"community_summary_lines": ["커뮤니티 요약"], "items": rows}
            return {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(body, ensure_ascii=False)}]}}
                ]
            }

        logs = []
        with (
            mock.patch.object(collector, "post_json", side_effect=flaky_post_json),
            mock.patch.object(
                collector, "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
            ),
            mock.patch.object(collector, "LLM_MODEL", "gemma-4-31b-it"),
            mock.patch.object(collector, "LLM_API_KEYS", ["test-key"]),
            mock.patch.object(collector.time, "sleep"),
        ):
            rows, _ = collector.enrich_community_reactions(items, logs)

        self.assertTrue(any(item.get("summary_method") == "llm" for item in rows))
        self.assertTrue(
            any(line.startswith("community reaction summary") for line in logs), logs
        )

    def test_a_failed_batch_is_split_and_most_posts_are_still_saved(self):
        items = self._items()
        calls = {"count": 0}

        def flaky_post_json(url, payload, headers=None, timeout=None):
            calls["count"] += 1
            # The first batch fails at full size, then answers once split.
            if calls["count"] <= 2:
                raise urllib.error.HTTPError("https://example.test", 500, "boom", {}, None)
            text = payload["contents"][0]["parts"][0]["text"]
            ids = re.findall(r'"id": "(art-\d+)"', text)
            rows = [
                {
                    "id": article_id,
                    "topic": "t",
                    "summary_lines": ["1", "2", "3", "4", "5"],
                    "reaction_summary": "r",
                    "community_score": 4,
                }
                for article_id in ids
            ]
            body = {"community_summary_lines": ["c"], "items": rows}
            return {
                "candidates": [
                    {"content": {"parts": [{"text": json.dumps(body, ensure_ascii=False)}]}}
                ]
            }

        logs = []
        with (
            mock.patch.object(collector, "post_json", side_effect=flaky_post_json),
            mock.patch.object(
                collector, "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
            ),
            mock.patch.object(collector, "LLM_MODEL", "gemma-4-31b-it"),
            mock.patch.object(collector, "LLM_API_KEYS", ["test-key"]),
            mock.patch.object(collector.time, "sleep"),
        ):
            rows, _ = collector.enrich_community_reactions(items, logs)

        self.assertTrue(
            any("community reaction summary retry: splitting" in line for line in logs), logs
        )
        self.assertFalse(
            any(line.startswith("community reaction summary skip") for line in logs), logs
        )
        # finalize() keeps only the top posts, so every surviving row must be a
        # real summary rather than the raw post text.
        self.assertTrue(rows)
        for item in rows:
            self.assertEqual(item.get("summary_method"), "llm", item.get("headline"))

    def test_a_dead_model_host_names_the_posts_it_could_not_summarize(self):
        items = self._items()

        def dead_post_json(url, payload, headers=None, timeout=None):
            raise urllib.error.HTTPError("https://example.test", 500, "boom", {}, None)

        logs = []
        with (
            mock.patch.object(collector, "post_json", side_effect=dead_post_json),
            mock.patch.object(
                collector, "LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai"
            ),
            mock.patch.object(collector, "LLM_MODEL", "gemma-4-31b-it"),
            mock.patch.object(collector, "LLM_API_KEYS", ["test-key"]),
            mock.patch.object(collector.time, "sleep"),
        ):
            rows, _ = collector.enrich_community_reactions(items, logs)

        skipped = [line for line in logs if line.startswith("community reaction summary skip")]
        self.assertEqual(len(skipped), len(items), logs)
        self.assertTrue(any("12 of 12 posts failed" in line for line in logs), logs)
        self.assertFalse(any(item.get("summary_method") == "llm" for item in rows))


class HealthReportingTests(unittest.TestCase):
    """The site notice keys off build_health, so its thresholds matter."""

    def test_one_stubborn_post_does_not_mark_the_whole_run_degraded(self):
        logs = ["community reaction summary skip: some post (HTTPError: 500)"]
        health = collector.build_health(logs, article_count=40, community_count=10)
        self.assertEqual(health["status"], "ok", health)

    def test_a_half_failed_community_feed_is_reported(self):
        logs = [
            f"community reaction summary skip: post {index} (TimeoutError: slow)"
            for index in range(5)
        ]
        health = collector.build_health(logs, article_count=40, community_count=10)
        self.assertEqual(health["status"], "degraded", health)
        self.assertTrue(any("community summaries failed" in r for r in health["reasons"]), health)

    def test_a_failed_daily_summary_is_always_reported(self):
        logs = ["daily summary skip: HTTPError"]
        health = collector.build_health(logs, article_count=40, community_count=10)
        self.assertEqual(health["status"], "degraded", health)
        self.assertIn("daily summary failed", health["reasons"])

    def test_a_clean_run_is_ok(self):
        health = collector.build_health(["naver ok: search (10)"], 40, 10)
        self.assertEqual(health, {"status": "ok", "reasons": []})

    def test_fewer_than_50_detailed_summaries_marks_the_run_degraded(self):
        health = collector.build_health(
            ["llm ok: partial"],
            article_count=70,
            community_count=10,
            summary_count=49,
            summary_target=50,
        )
        self.assertEqual(health["status"], "degraded", health)
        self.assertIn("49 of 50 detailed summaries ready", health["reasons"])

    def test_underfilled_sector_is_healthy_when_dynamic_target_is_met(self):
        health = collector.build_health(
            ["sector candidate final: 공정=7"],
            article_count=47,
            community_count=10,
            summary_count=47,
            summary_target=47,
        )
        self.assertEqual(health, {"status": "ok", "reasons": []})


class PublicationPayloadTests(unittest.TestCase):
    def test_payload_contains_detailed_and_overflow_headline_articles(self):
        counts = {
            "설계": 10,
            "공정": 7,
            "소자": 10,
            "패키징": 10,
            "신제품/발표": 10,
            "실적/투자/정책/인사": 10,
        }
        headline_counts = {
            "설계": 4,
            "공정": 0,
            "소자": 2,
            "패키징": 1,
            "신제품/발표": 3,
            "실적/투자/정책/인사": 0,
        }
        articles = []
        number = 0
        for sector, count in counts.items():
            for index in range(count):
                articles.append(
                    {
                        "id": f"published-{number}",
                        "headline": f"{sector} 상세 {index}",
                        "body": "첫째\n둘째\n셋째\n넷째\n다섯째",
                        "summary_method": "llm",
                        "summary_version": collector.SUMMARY_PROMPT_VERSION,
                        "summary_model": "gemma-test",
                        "sector": sector,
                        "sector_score": 12,
                        "sector_method": "keyword",
                        "importance_score": 3,
                        "created_at": "2026-09-25T10:00:00+09:00",
                        "source_url": f"https://example.com/published/{number}",
                    }
                )
                number += 1
        for sector, count in headline_counts.items():
            for index in range(count):
                articles.append(
                    {
                        "id": f"headline-{number}",
                        "headline": f"{sector} 제목 {index}",
                        "body": "수집 스니펫",
                        "summary_method": "snippet",
                        "publication_mode": "headline",
                        "sector": sector,
                        "sector_score": 8,
                        "sector_method": "keyword",
                        "importance_score": 2,
                        "created_at": "2026-09-25T09:00:00+09:00",
                        "source_url": f"https://example.com/headline/{number}",
                    }
                )
                number += 1

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "articles.json"
            with (
                mock.patch.object(collector, "ARTICLES_PATH", output),
                mock.patch.object(collector, "write_archive_snapshot"),
            ):
                collector.write_articles(
                    articles,
                    [],
                    summary_target=57,
                    candidate_count=88,
                    sector_candidate_counts={
                        "설계": 14,
                        "공정": 7,
                        "소자": 12,
                        "패키징": 11,
                        "신제품/발표": 13,
                        "실적/투자/정책/인사": 15,
                    },
                )
            payload = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], 13)
        self.assertEqual(len(payload["articles"]), 67)
        self.assertEqual(len(payload["summary_article_ids"]), 57)
        self.assertEqual(len(payload["headline_article_ids"]), 10)
        self.assertTrue(
            all(
                item["summary_method"] == "llm"
                for item in payload["articles"]
                if item["id"] in payload["summary_article_ids"]
            )
        )
        self.assertTrue(
            all(
                item["publication_mode"] == "headline"
                for item in payload["articles"]
                if item["id"] in payload["headline_article_ids"]
            )
        )
        self.assertEqual(payload["collector"]["summary_target"], 57)
        self.assertEqual(payload["collector"]["summary_count"], 57)
        self.assertEqual(payload["collector"]["headline_count"], 10)
        self.assertEqual(payload["collector"]["candidate_count"], 88)
        self.assertEqual(payload["sectors"], list(collector.SECTOR_NAMES))
        self.assertEqual(payload["collector"]["sector_summary_counts"], counts)
        self.assertEqual(payload["collector"]["sector_headline_counts"], headline_counts)
        self.assertNotIn("supplemental_rounds", payload["collector"])
        self.assertEqual(payload["collector"]["health"]["status"], "ok")
        self.assertTrue(
            all(
                article_id in payload["summary_article_ids"]
                for article_id in payload["daily_summary_article_ids"]
            )
        )
        self.assertNotIn("title_organized_count", payload["collector"])


class CommunityPostReadTests(unittest.TestCase):
    """Only the sites that allow a crawler get their post text read."""

    def _item(self, url):
        return {
            "id": "art-post",
            "headline": "제목만 있던 글",
            "body": "검색 스니펫 한 줄",
            "source_url": url,
            "community_score": 3,
            "created_at": "2026-09-25T07:00:00+09:00",
            "date_is_estimated": True,
        }

    def _dcinside_page(self):
        """A post page whose body is long enough to count as real post text."""
        return (
            '<span class="gall_date" title="2026-09-24 18:55:25">09.24</span>'
            '<div class="write_div"><p>HBM4 패키징 경쟁이 본격화되고 있다는 내용을 공유합니다. '
            "삼성전자와 SK하이닉스의 공정 전환 속도, 그리고 중국 CXMT의 추격 속도가 주요 관전 포인트라는 의견입니다.</p>"
            "<p>수율 안정화 시점과 고객 인증 일정이 실제 실적을 가를 것 같다는 반응도 함께 언급했습니다.</p></div>"
        )

    def test_robots_disallowed_sites_are_never_read(self):
        self.assertEqual(collector.community_post_reader("https://cafe.naver.com/yttnews/25469"), "")
        self.assertEqual(collector.community_post_reader("https://www.fmkorea.com/10319572957"), "")
        self.assertEqual(
            collector.community_post_reader("https://gall.dcinside.com/mgallery/board/view?id=nasdaq&no=1"),
            "dcinside",
        )
        self.assertEqual(
            collector.community_post_reader("https://www.clien.net/service/board/cm_stock/15818583"),
            "clien",
        )

    def test_the_shortlist_skips_sites_that_cannot_be_read(self):
        items = [
            self._item("https://cafe.naver.com/yttnews/25469"),
            self._item("https://www.fmkorea.com/10319572957"),
            self._item("https://gall.dcinside.com/mgallery/board/view?id=nasdaq&no=1"),
            self._item("https://www.clien.net/service/board/cm_stock/15818583"),
        ]
        picked = collector.readable_community_candidates(items, 20)
        self.assertEqual(len(picked), 2, picked)
        self.assertTrue(all(collector.community_post_reader(i["source_url"]) for i in picked))
        self.assertEqual(len(collector.readable_community_candidates(items, 1)), 1)

    def test_dcinside_body_and_real_posting_time_are_parsed(self):
        parsed = collector.parse_community_post("dcinside", self._dcinside_page())
        self.assertIn("HBM4 패키징 경쟁", parsed["body"])
        self.assertEqual(parsed["created_at"], "2026-09-24T18:55:25+09:00")

    def test_reading_a_post_replaces_the_snippet_and_the_guessed_date(self):
        item = self._item("https://gall.dcinside.com/mgallery/board/view?id=nasdaq&no=2138177")
        page = self._dcinside_page()
        logs = []
        with (
            mock.patch.object(collector, "request_text", return_value=page),
            mock.patch.object(collector.time, "sleep"),
        ):
            collector.read_community_posts([item], logs)
        self.assertEqual(item["body_source"], "post")
        self.assertIn("HBM4 패키징 경쟁", item["body"])
        self.assertEqual(item["created_at"], "2026-09-24T18:55:25+09:00")
        self.assertFalse(item["date_is_estimated"])
        self.assertTrue(any("1 of 1 posts read" in line for line in logs), logs)

    def test_a_link_only_post_keeps_the_snippet(self):
        item = self._item("https://www.clien.net/service/board/cm_stock/15818583")
        page = '<div class="post_article">짧음</div>'
        logs = []
        with mock.patch.object(collector, "request_text", return_value=page):
            collector.read_community_posts([item], logs)
        self.assertEqual(item["body"], "검색 스니펫 한 줄")
        self.assertNotIn("body_source", item)
        self.assertTrue(item["date_is_estimated"])
        self.assertTrue(any("no body text" in line for line in logs), logs)

    def test_a_failing_fetch_leaves_the_item_untouched(self):
        item = self._item("https://www.clien.net/service/board/cm_stock/15818583")
        logs = []
        with mock.patch.object(collector, "request_text", side_effect=TimeoutError("slow")):
            collector.read_community_posts([item], logs)
        self.assertEqual(item["body"], "검색 스니펫 한 줄")
        self.assertTrue(any("community post skip: clien (TimeoutError)" in line for line in logs), logs)


class RetryGuardTests(unittest.TestCase):
    """The hourly cron must not build today's briefing before its 05:00 start."""

    @classmethod
    def setUpClass(cls):
        path = Path(collector.__file__).resolve().parent / "scripts" / "needs_retry.py"
        spec = importlib.util.spec_from_file_location("needs_retry", path)
        cls.needs_retry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.needs_retry)

    def _decide(self, payload, when):
        with tempfile.TemporaryDirectory() as directory:
            articles = Path(directory) / "articles.json"
            articles.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch.object(self.needs_retry, "ARTICLES", articles):
                return self.needs_retry.decide(now=when)

    def _kst(self, hour, minute=0):
        return dt.datetime(2026, 9, 25, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=9)))

    def _healthy(self, generated):
        return {
            "generated_at": generated,
            "collector": {"health": {"status": "ok", "reasons": []}},
        }

    def test_before_the_cutoff_hour_the_guard_waits(self):
        payload = self._healthy("2026-09-24T07:00:00+09:00")
        retry, reason = self._decide(payload, self._kst(1, 30))
        self.assertEqual(retry, "no", reason)
        self.assertIn("전이라 대기", reason)

    def test_after_the_start_hour_a_missing_briefing_is_rebuilt(self):
        payload = self._healthy("2026-09-24T07:00:00+09:00")
        retry, reason = self._decide(payload, self._kst(6, 0))
        self.assertEqual(retry, "yes", reason)

    def test_the_guard_waits_just_before_five(self):
        payload = self._healthy("2026-09-24T07:00:00+09:00")
        retry, reason = self._decide(payload, self._kst(4, 59))
        self.assertEqual(retry, "no", reason)

    def test_the_guard_allows_a_delayed_run_at_ten_past_five(self):
        payload = self._healthy("2026-09-24T07:00:00+09:00")
        retry, reason = self._decide(payload, self._kst(5, 10))
        self.assertEqual(retry, "yes", reason)

    def test_a_healthy_briefing_from_today_is_left_alone(self):
        payload = self._healthy("2026-09-25T04:30:00+09:00")
        retry, reason = self._decide(payload, self._kst(6, 0))
        self.assertEqual(retry, "no", reason)

    def test_a_degraded_briefing_is_rebuilt(self):
        payload = {
            "generated_at": "2026-09-25T04:30:00+09:00",
            "collector": {"health": {"status": "degraded", "reasons": ["community summary failed"]}},
        }
        retry, reason = self._decide(payload, self._kst(6, 0))
        self.assertEqual(retry, "yes", reason)

    def test_a_briefing_with_fewer_than_50_summaries_is_rebuilt(self):
        payload = {
            "generated_at": "2026-09-25T04:30:00+09:00",
            "collector": {
                "summary_target": 50,
                "summary_count": 49,
                "health": {"status": "ok", "reasons": []},
            },
        }
        retry, reason = self._decide(payload, self._kst(6, 0))
        self.assertEqual(retry, "yes", reason)
        self.assertIn("49/50", reason)

    def test_a_healthy_underfilled_sector_briefing_is_left_alone(self):
        payload = {
            "generated_at": "2026-09-25T04:30:00+09:00",
            "collector": {
                "summary_target": 47,
                "summary_count": 47,
                "health": {"status": "ok", "reasons": []},
            },
        }
        retry, reason = self._decide(payload, self._kst(6, 0))
        self.assertEqual(retry, "no", reason)


class ModelRetryTests(unittest.TestCase):
    def test_post_json_retries_once_on_transient_503(self):
        error = urllib.error.HTTPError("https://example.test", 503, "busy", {}, None)
        ok = _FakeResponse(b'{"candidates": []}')
        with (
            mock.patch.object(collector.urllib.request, "urlopen", side_effect=[error, ok]) as urlopen,
            mock.patch.object(collector.time, "sleep"),
        ):
            data = collector.post_json("https://example.test", {"model": "test"}, timeout=1)
        self.assertEqual(data, {"candidates": []})
        self.assertEqual(urlopen.call_count, 2)

    def test_post_json_gives_up_after_one_retry(self):
        error = urllib.error.HTTPError("https://example.test", 503, "busy", {}, None)
        with (
            mock.patch.object(collector.urllib.request, "urlopen", side_effect=[error, error]) as urlopen,
            mock.patch.object(collector.time, "sleep"),
        ):
            with self.assertRaises(urllib.error.HTTPError):
                collector.post_json("https://example.test", {"model": "test"}, timeout=1)
        self.assertEqual(urlopen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
