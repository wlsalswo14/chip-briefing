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
    def test_briefing_window_ends_at_the_scheduled_seoul_hour(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        hour = collector.WINDOW_END_HOUR
        start, end = collector.briefing_window(dt.datetime(2026, 8, 23, hour, 30, tzinfo=kst))
        self.assertEqual(start, dt.datetime(2026, 8, 22, hour, 0, tzinfo=kst))
        self.assertEqual(end, dt.datetime(2026, 8, 23, hour, 0, tzinfo=kst))

    def test_briefing_window_before_the_run_hour_uses_the_previous_day(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        hour = collector.WINDOW_END_HOUR
        before = dt.datetime(2026, 8, 23, hour, 0, tzinfo=kst) - dt.timedelta(minutes=30)
        start, end = collector.briefing_window(before)
        self.assertEqual(start, dt.datetime(2026, 8, 21, hour, 0, tzinfo=kst))
        self.assertEqual(end, dt.datetime(2026, 8, 22, hour, 0, tzinfo=kst))

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
            {"headline": "첫 번째 기사", "body": "요약", "importance_score": 5},
            {"headline": "두 번째 기사", "body": "요약", "importance_score": 4},
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

    def test_sector_candidates_pick_ten_per_sector(self):
        items = [
            {
                "headline": "설계 기사 %d" % index,
                "body": "설계 공정 소자 패키징",
                "sector": "설계",
                "trust": "medium",
                "category": "news",
                "created_at": "2026-09-23T%02d:00:00+09:00" % (index % 24),
            }
            for index in range(12)
        ]
        items.append(
            {
                "headline": "공정 기사",
                "body": "공정",
                "sector": "공정",
                "trust": "medium",
                "category": "news",
                "created_at": "2026-09-23T09:00:00+09:00",
            }
        )
        picked = collector.select_sector_candidates(items, per_sector=10)
        self.assertEqual(len([item for item in picked if item["sector"] == "설계"]), 10)
        self.assertEqual(len([item for item in picked if item["sector"] == "공정"]), 1)
        self.assertEqual(len(picked), 11)


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


class SectorRoutingTests(unittest.TestCase):
    """Korean headlines decide the process and packaging tabs.

    The keyword list in sources.json is English, so those two tabs used to fall
    back to the default sector and stayed at three or four items a day.
    """

    def test_a_korean_process_headline_routes_to_process(self):
        sector, hits = collector.headline_sector(
            "TSMC, 내년 파운드리 가격 최대 6% 인상 전망…2·3나노는 더 오른다"
        )
        self.assertEqual(sector, "공정", hits)

    def test_a_bonding_headline_routes_to_packaging(self):
        sector, hits = collector.headline_sector(
            '"하이브리드는 아직"…엇갈린 본딩 베팅, 한미반도체가 웃었다'
        )
        self.assertEqual(sector, "패키징", hits)

    def test_packaging_wins_over_a_passing_foundry_mention(self):
        sector, _ = collector.headline_sector("TSMC, CoWoS 패키징 증설…파운드리 2나노 확대")
        self.assertEqual(sector, "패키징")

    def test_an_ordinary_headline_has_no_signal(self):
        sector, hits = collector.headline_sector("삼성전자 주가 목표가, 증권사별 40~65만원")
        self.assertEqual(sector, "")
        self.assertEqual(hits, [])

    def test_make_article_uses_the_headline_signal(self):
        article = collector.make_article(
            "CXMT, EUV 없이 5세대 D램 양산…수율 한계 명확",
            "https://example.com/news/1",
            "snippet",
            {"name": "test", "category_default": "news", "trust_default": "medium"},
            "news",
            collector.now_iso(),
        )
        self.assertEqual(article["sector"], "공정")


class RetryGuardTests(unittest.TestCase):
    """The hourly cron must not build today's briefing before its cutoff hour."""

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

    def test_after_the_cutoff_a_missing_briefing_is_rebuilt(self):
        payload = self._healthy("2026-09-24T07:00:00+09:00")
        retry, reason = self._decide(payload, self._kst(3, 0))
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
