import datetime as dt
import json
import tempfile
import unittest
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
    def test_briefing_window_ends_at_latest_seoul_0700(self):
        kst = dt.timezone(dt.timedelta(hours=9))
        start, end = collector.briefing_window(dt.datetime(2026, 8, 23, 7, 30, tzinfo=kst))
        self.assertEqual(start, dt.datetime(2026, 8, 22, 7, 0, tzinfo=kst))
        self.assertEqual(end, dt.datetime(2026, 8, 23, 7, 0, tzinfo=kst))

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


if __name__ == "__main__":
    unittest.main()
