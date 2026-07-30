import inspect
import json
import time
import tracemalloc
import unittest
from unittest import mock

from backend import platform_adapters as xhs


class XhsLeadParsingTests(unittest.TestCase):
    def test_xhs_collection_functions_accept_guest_mode(self):
        self.assertIn("guest_mode", inspect.signature(xhs.xhs_search_notes).parameters)
        self.assertIn("guest_mode", inspect.signature(xhs.xhs_get_comments).parameters)
        self.assertIn("guest_mode", inspect.signature(xhs.xhs_download_note).parameters)
        self.assertIn("guest_mode", inspect.signature(xhs.discover_xhs_leads_by_keyword).parameters)

    def test_xhs_guest_mode_does_not_use_profile_ready_for_collection(self):
        for func in (xhs.xhs_search_notes, xhs.xhs_get_comments, xhs.xhs_download_note):
            src = inspect.getsource(func)
            self.assertIn("persistent=(not guest_mode) and xhs_profile_ready", src)

    def test_xhs_guest_collection_closes_login_modal_before_scraping(self):
        module_src = inspect.getsource(xhs)
        self.assertIn("def _xhs_close_guest_login_modal(page):", module_src)
        self.assertIn("手机号登录", module_src)
        self.assertIn("登录后推荐更懂你的笔记", module_src)
        for func in (xhs.xhs_search_notes, xhs.xhs_get_comments, xhs.xhs_download_note):
            src = inspect.getsource(func)
            self.assertIn("_xhs_close_guest_login_modal(page)", src)

    def test_xhs_guest_login_wall_state_requires_account_confirmation(self):
        result = xhs.xhs_guest_collection_block_error(
            {"ok": True, "guestMode": True, "loginWall": True},
            "search",
        )

        self.assertFalse(result["ok"])
        self.assertTrue(result["needLogin"])
        self.assertEqual(result["error"], "xhs_guest_login_required")

    def test_xhs_search_url_must_match_keyword_before_accepting_results(self):
        self.assertTrue(
            xhs._xhs_search_page_matches_keyword(
                "https://www.xiaohongshu.com/search_result?keyword=%E4%B8%B0%E7%94%B0%E6%B1%BD%E8%BD%A6",
                "丰田汽车",
            )
        )
        self.assertFalse(xhs._xhs_search_page_matches_keyword("https://www.xiaohongshu.com/explore", "丰田汽车"))
        self.assertFalse(
            xhs._xhs_search_page_matches_keyword(
                "https://www.xiaohongshu.com/search_result?keyword=%E7%BE%8E%E9%A3%9F",
                "丰田汽车",
            )
        )

    def test_xhs_guest_search_rejects_unverified_recommendation_feed(self):
        src = inspect.getsource(xhs.xhs_search_notes)

        self.assertIn("search_verified", src)
        self.assertIn("_xhs_search_page_matches_keyword(page.url, keyword)", src)
        self.assertIn('result["blocked"] = True', src)
        self.assertIn('result["message"] = "xhs_search_result_unverified"', src)

    def test_strict_filter_flag_defaults_on_and_can_disable(self):
        self.assertTrue(xhs.xhs_strict_lead_filter_enabled({}))
        self.assertFalse(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "0"}))
        self.assertFalse(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "false"}))
        self.assertFalse(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "no"}))
        self.assertFalse(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "off"}))
        self.assertTrue(xhs.xhs_strict_lead_filter_enabled({"XHS_STRICT_LEAD_FILTER_ENABLED": "1"}))

    def test_comment_cleaner_removes_only_trailing_xhs_metadata(self):
        self.assertEqual(
            xhs._xhs_clean_comment_text("价格多少 07-17 黑龙江 作者 · 赞 12 回复"),
            "价格多少",
        )
        self.assertEqual(xhs._xhs_clean_comment_text("这个回答值得赞"), "这个回答值得赞")
        self.assertEqual(xhs._xhs_clean_comment_text("请回复一下"), "请回复一下")
        self.assertEqual(xhs._xhs_clean_comment_text("这个回答 值得 赞"), "这个回答 值得 赞")
        self.assertEqual(xhs._xhs_clean_comment_text("请 回复"), "请 回复")
        self.assertEqual(xhs._xhs_clean_comment_text("报价 赞12"), "报价 赞12")
        self.assertEqual(xhs._xhs_clean_comment_text("报价 赞12 回复"), "报价 赞12 回复")

    def test_comment_cleaner_removes_only_complete_trailing_metadata_lines(self):
        cases = {
            "报价\n赞": "报价",
            "报价\n回复": "报价",
            "报价\n作者": "报价",
            "报价\n作者\n赞 12\n回复": "报价",
            "报价\n07-17 黑龙江\n作者\n赞8\n回复": "报价",
        }

        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(xhs._xhs_clean_comment_text(raw), expected)

    def test_combined_metadata_lines_are_removed_and_likes_are_parsed(self):
        for metadata in ("赞 回复", "赞8回复", "赞 8 回复"):
            with self.subTest(metadata=metadata):
                self.assertEqual(xhs._xhs_clean_comment_text("报价\n" + metadata), "报价")

        self.assertEqual(xhs._xhs_raw_text_digg_count("用户\n报价\n赞8回复"), 8)
        self.assertEqual(xhs._xhs_raw_text_digg_count("用户\n报价\n赞 8 回复"), 8)

    def test_comment_fields_preserve_explicit_text_line_boundaries_for_cleaning(self):
        user, text = xhs._xhs_comment_fields({"user": "用户", "text": "报价\n赞\n回复"})

        self.assertEqual(user, "用户")
        self.assertEqual(text, "报价")

    def test_raw_dom_lines_use_username_and_first_comment_only(self):
        user, text = xhs._xhs_comment_fields(
            {
                "rawText": "正常用户\n价格多少\n07-17 黑龙江 赞 回复\n回复用户\n我也想问",
            }
        )
        self.assertEqual(user, "正常用户")
        self.assertEqual(text, "价格多少")

    def test_raw_dom_comment_line_removes_inline_trailing_metadata(self):
        user, text = xhs._xhs_comment_fields(
            {
                "rawText": "正常用户\n价格多少 07-17 黑龙江 作者 · 赞 12 回复",
            }
        )

        self.assertEqual(user, "正常用户")
        self.assertEqual(text, "价格多少")

    def test_raw_text_digg_helper_reads_only_metadata_after_comment_body(self):
        self.assertEqual(xhs._xhs_raw_text_digg_count("用户\n报价\n赞8\n回复"), 8)
        self.assertEqual(xhs._xhs_raw_text_digg_count("用户\n报价\n赞 12\n回复"), 12)
        self.assertIsNone(xhs._xhs_raw_text_digg_count("用户\n我觉得赞12\n回复"))

    def test_xhs_search_response_meta_extracts_author_like_and_collect_counts(self):
        payload = {
            "data": {
                "items": [{
                    "note_card": {
                        "note_id": "abc123",
                        "display_title": "\u539f\u59cb\u6807\u9898",
                        "user": {"nickname": "\u539f\u4f5c\u8005"},
                        "interact_info": {
                            "liked_count": "12",
                            "collected_count": "34",
                        },
                    }
                }]
            }
        }

        meta = xhs._xhs_search_note_meta_map(payload)

        self.assertEqual(meta["abc123"]["title"], "\u539f\u59cb\u6807\u9898")
        self.assertEqual(meta["abc123"]["author"], "\u539f\u4f5c\u8005")
        self.assertEqual(meta["abc123"]["diggCount"], 12)
        self.assertEqual(meta["abc123"]["collectCount"], 34)

    def test_raw_text_digg_helper_stops_before_nested_reply_content(self):
        self.assertIsNone(
            xhs._xhs_raw_text_digg_count(
                "用户\n报价\n07-17 黑龙江\n回复用户\n回复内容\n赞99"
            )
        )

    def test_explicit_zero_digg_count_does_not_fall_back_to_raw_text(self):
        item = xhs._xhs_normalize_comment(
            {
                "rawText": "用户\n价格多少\n赞 8\n回复",
                "profile": "https://www.xiaohongshu.com/user/profile/explicit-zero",
                "diggCount": 0,
            }
        )

        self.assertEqual(item["diggCount"], 0)

    def test_profile_url_is_canonical_and_drops_query_values(self):
        self.assertEqual(
            xhs._xhs_canonical_profile_url(
                "https://www.xiaohongshu.com/user/profile/abc123?xsec_token=secret#reply"
            ),
            "https://www.xiaohongshu.com/user/profile/abc123",
        )
        self.assertEqual(xhs._xhs_canonical_profile_url("https://evil.example/user/profile/abc123"), "")

    def test_prepare_rejects_missing_or_invalid_profile(self):
        item, reason = xhs._xhs_prepare_comment({"user": "小王", "text": "价格", "profile": ""}, strict=True)
        self.assertEqual(reason, "missing_profile_url")
        self.assertEqual(item["user"], "小王")

        _item, reason = xhs._xhs_prepare_comment(
            {"user": "小王", "text": "价格", "profile": "https://evil.example/user/profile/abc"},
            strict=True,
        )
        self.assertEqual(reason, "invalid_profile_url")

    def test_prepare_rejects_empty_user_and_user_equal_to_comment(self):
        profile = "https://www.xiaohongshu.com/user/profile/abc"
        _item, reason = xhs._xhs_prepare_comment({"user": "", "text": "价格", "profile": profile}, strict=True)
        self.assertEqual(reason, "empty_user")

        _item, reason = xhs._xhs_prepare_comment(
            {"user": "在那，价格多少", "text": "在那，价格多少", "profile": profile},
            strict=True,
        )
        self.assertEqual(reason, "user_equals_comment")

    def test_dot_and_emoji_usernames_are_valid_with_profile(self):
        for index, user in enumerate((".", "🌙"), start=1):
            item, reason = xhs._xhs_prepare_comment(
                {
                    "user": user,
                    "text": "价格多少",
                    "profile": "https://www.xiaohongshu.com/user/profile/user%s" % index,
                },
                strict=True,
            )
            self.assertEqual(reason, "")
            self.assertEqual(item["user"], user)


class FakeLogger:
    def __init__(self):
        self.rows = []

    def warning(self, value):
        self.rows.append(("warning", value))

    def info(self, value):
        self.rows.append(("info", value))

    def error(self, value):
        self.rows.append(("error", value))


class XhsLeadFilteringTests(unittest.TestCase):
    def test_same_profile_uses_raw_text_metadata_likes_as_rank_tiebreaker(self):
        profile = "https://www.xiaohongshu.com/user/profile/raw-likes"
        rows = [
            {
                "rawText": "用户\n价格多少\n赞2\n回复",
                "profile": profile,
                "intent": "高意向",
            },
            {
                "rawText": "用户\n怎么买\n赞 8\n回复",
                "profile": profile,
                "intent": "高意向",
            },
        ]

        result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "怎么买")
        self.assertEqual(result[0]["diggCount"], 8)

    def test_explicit_result_limit_ranks_all_candidates_and_logs_each_discard(self):
        logger = FakeLogger()
        rows = [
            {
                "user": "ordinary",
                "text": "ordinary comment",
                "profile": "https://www.xiaohongshu.com/user/profile/ordinary",
                "intent": "普通",
                "diggCount": 100,
            },
            {
                "user": "high-two",
                "text": "price two",
                "profile": "https://www.xiaohongshu.com/user/profile/high-two",
                "intent": "高意向",
                "diggCount": 2,
            },
            {
                "user": "high-eight",
                "text": "price eight",
                "profile": "https://www.xiaohongshu.com/user/profile/high-eight",
                "intent": "高意向",
                "diggCount": 8,
            },
            {
                "user": "consult",
                "text": "consult comment",
                "profile": "https://www.xiaohongshu.com/user/profile/consult",
                "intent": "咨询",
                "diggCount": 1,
            },
        ]

        result = xhs._xhs_filter_comment_candidates(
            rows,
            log=logger,
            strict=True,
            result_limit=2,
        )

        self.assertEqual([item["user"] for item in result], ["high-two", "high-eight"])
        payloads = [json.loads(raw) for _level, raw in logger.rows]
        limit_logs = [
            payload
            for payload in payloads
            if payload["event"] == "xhs_collected_record_filtered"
            and payload["reason"] == "result_limit_exceeded"
        ]
        self.assertEqual([payload["candidateIndex"] for payload in limit_logs], [0, 3])
        summary = next(payload for payload in payloads if payload["event"] == "xhs_collection_filter_summary")
        self.assertEqual(summary["acceptedCount"], 2)
        self.assertEqual(summary["reasonCounts"]["result_limit_exceeded"], 2)

    def test_explicit_result_limit_is_clamped_to_one_through_three_hundred(self):
        rows = [
            {
                "user": "user-%s" % index,
                "text": "comment-%s" % index,
                "profile": "https://www.xiaohongshu.com/user/profile/clamp-%s" % index,
            }
            for index in range(301)
        ]

        lower = xhs._xhs_filter_comment_candidates(rows[:2], log=FakeLogger(), strict=True, result_limit=0)
        upper = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True, result_limit=999)

        self.assertEqual(len(lower), 1)
        self.assertEqual(len(upper), 300)

    def test_summary_reports_explicit_raw_candidate_cap_state(self):
        logger = FakeLogger()

        xhs._xhs_filter_comment_candidates(
            [
                {
                    "user": "user",
                    "text": "price",
                    "profile": "https://www.xiaohongshu.com/user/profile/summary",
                }
            ],
            log=logger,
            strict=True,
            candidate_limit=900,
            candidate_limit_reached=True,
            candidate_duplicate_count=7,
        )

        summary = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collection_filter_summary"
        )
        self.assertEqual(summary["candidateLimit"], 900)
        self.assertIs(summary["candidateLimitReached"], True)
        self.assertEqual(summary["candidateDuplicateCount"], 7)
        self.assertIs(type(summary["candidateLimit"]), int)
        self.assertIs(type(summary["candidateLimitReached"]), bool)

    def test_collection_error_log_redacts_exception_and_url(self):
        logger = FakeLogger()
        secret_url = "https://www.xiaohongshu.com/explore/note-a?xsec_token=secret-value"

        try:
            raise RuntimeError("request failed secret-value")
        except RuntimeError as exc:
            error_id = xhs._xhs_log_collection_error(
                "xhs_note_collection_failed",
                exc,
                note_id="note-a",
                note_url=secret_url,
                log=logger,
            )

        joined = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn("secret-value", joined)
        payload = json.loads(logger.rows[-1][1])
        self.assertEqual(payload["event"], "xhs_note_collection_failed")
        self.assertEqual(payload["noteId"], "note-a")
        self.assertNotIn("noteUrl", payload)
        self.assertRegex(payload["noteUrlFingerprint"], r"^[0-9a-f]{16}$")
        self.assertEqual(error_id, payload["errorId"])
        self.assertIn("stack", payload)

    def test_strict_filter_limits_distinct_valid_profiles_to_three_hundred_and_logs_discard(self):
        logger = FakeLogger()
        rows = [
            {
                "user": "user-%s" % index,
                "text": "comment-%s" % index,
                "profile": "https://www.xiaohongshu.com/user/profile/user-%s" % index,
            }
            for index in range(301)
        ]

        result = xhs._xhs_filter_comment_candidates(rows, log=logger, strict=True)

        self.assertEqual(len(result), 300)
        self.assertEqual([item["user"] for item in result], ["user-%s" % index for index in range(300)])
        limit_logs = [
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collected_record_filtered"
            and json.loads(raw)["reason"] == "result_limit_exceeded"
        ]
        self.assertEqual(len(limit_logs), 1)
        self.assertEqual(limit_logs[0]["candidateIndex"], 300)

    def test_fake_data_smoke_filters_invalid_rows_and_keeps_dot_and_emoji(self):
        logger = FakeLogger()
        rows = [
            {"user": "无链接", "text": "价格", "profile": ""},
            {"user": "", "text": "价格", "profile": "https://www.xiaohongshu.com/user/profile/empty"},
            {"user": "在那，价格多少", "text": "在那，价格多少", "profile": "https://www.xiaohongshu.com/user/profile/equal"},
            {"user": ".", "text": "价格多少 07-17 黑龙江 赞 回复", "profile": "https://www.xiaohongshu.com/user/profile/dot"},
            {"user": "🌙", "text": "想了解", "profile": "https://www.xiaohongshu.com/user/profile/moon"},
        ]
        result = xhs._xhs_filter_comment_candidates(rows, note_id="note-smoke", log=logger, strict=True)

        self.assertEqual([item["user"] for item in result], [".", "🌙"])
        self.assertEqual(result[0]["text"], "价格多少")
        payloads = [json.loads(raw) for _level, raw in logger.rows]
        self.assertEqual(
            {payload["reason"] for payload in payloads if payload["event"] == "xhs_collected_record_filtered"},
            {"missing_profile_url", "empty_user", "user_equals_comment"},
        )

    def test_same_profile_keeps_best_intent_then_highest_likes(self):
        profile = "https://www.xiaohongshu.com/user/profile/repeat"
        rows = [
            {"user": "用户", "text": "普通内容", "profile": profile, "intent": "普通", "diggCount": 100},
            {"user": "用户", "text": "想了解", "profile": profile, "intent": "咨询", "diggCount": 2},
            {"user": "用户", "text": "价格多少", "profile": profile, "intent": "高意向", "diggCount": 1},
            {"user": "用户", "text": "怎么买", "profile": profile, "intent": "高意向", "diggCount": 8},
        ]
        result = xhs._xhs_filter_comment_candidates(rows, note_id="note-rank", log=FakeLogger(), strict=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "怎么买")
        self.assertEqual(result[0]["diggCount"], 8)

    def test_same_profile_same_intent_and_likes_keeps_first_candidate(self):
        profile = "https://www.xiaohongshu.com/user/profile/tie"
        rows = [
            {"user": "first", "text": "first comment", "profile": profile, "intent": "\u9ad8\u610f\u5411", "diggCount": 8},
            {"user": "second", "text": "second comment", "profile": profile, "intent": "\u9ad8\u610f\u5411", "diggCount": 8},
        ]

        result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)

        self.assertEqual([item["user"] for item in result], ["first"])

    def test_same_name_with_different_profiles_is_not_deduplicated(self):
        rows = [
            {"user": "同名", "text": "价格", "profile": "https://www.xiaohongshu.com/user/profile/a"},
            {"user": "同名", "text": "怎么买", "profile": "https://www.xiaohongshu.com/user/profile/b"},
        ]
        result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)
        self.assertEqual(len(result), 2)

    def test_filtered_logs_are_json_and_do_not_contain_raw_pii_or_token(self):
        logger = FakeLogger()
        user = "sensitive-user"
        comment = "sensitive-comment-price"
        url = "https://evil.example/user/profile/private-id?xsec_token=secret-value"
        xhs._xhs_filter_comment_candidates(
            [{"user": user, "text": comment, "profile": url}],
            note_id="note-log",
            log=logger,
            strict=True,
        )
        joined = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn(user, joined)
        self.assertNotIn(comment, joined)
        self.assertNotIn(url, joined)
        self.assertNotIn("secret-value", joined)
        payload = next(json.loads(raw) for _level, raw in logger.rows if json.loads(raw)["event"] == "xhs_collected_record_filtered")
        self.assertEqual(payload["reason"], "invalid_profile_url")
        self.assertRegex(payload["recordFingerprint"], r"^[0-9a-f]{16}$")

    def test_malformed_candidate_logs_redacted_stack_and_does_not_abort_batch(self):
        logger = FakeLogger()
        result = xhs._xhs_filter_comment_candidates(
            [
                {
                    "user": "sensitive-user",
                    "text": "sensitive-comment",
                    "profile": "https://www.xiaohongshu.com/user/profile/private-id?token=secret-value",
                    "diggCount": "not-a-number",
                },
                {
                    "user": "正常用户",
                    "text": "价格多少",
                    "profile": "https://www.xiaohongshu.com/user/profile/valid-id",
                },
            ],
            note_id="note-parse",
            log=logger,
            strict=True,
        )
        self.assertEqual([item["user"] for item in result], ["正常用户"])
        joined = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn("sensitive-user", joined)
        self.assertNotIn("sensitive-comment", joined)
        self.assertNotIn("secret-value", joined)
        payload = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collected_record_parse_failed"
        )
        self.assertEqual(payload["reason"], "parse_failed")
        self.assertEqual(payload["exceptionType"], "ValueError")
        self.assertIn("stack", payload)

    def test_strict_filter_can_be_disabled_for_emergency_rollback(self):
        result = xhs._xhs_filter_comment_candidates(
            [{"user": "", "text": "价格", "profile": ""}],
            log=FakeLogger(),
            strict=False,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["user"], "小红书用户")

    def test_empty_comment_is_logged_as_a_filtered_record(self):
        logger = FakeLogger()
        result = xhs._xhs_filter_comment_candidates(
            [{"user": "用户", "text": "", "profile": "https://www.xiaohongshu.com/user/profile/empty-comment"}],
            log=logger,
            strict=True,
        )
        self.assertEqual(result, [])
        payload = next(json.loads(raw) for _level, raw in logger.rows if json.loads(raw)["event"] == "xhs_collected_record_filtered")
        self.assertEqual(payload["reason"], "empty_comment")

    def test_strict_profile_reason_takes_priority_over_empty_comment(self):
        logger = FakeLogger()

        result = xhs._xhs_filter_comment_candidates(
            [{"user": "用户", "text": "", "profile": ""}],
            log=logger,
            strict=True,
        )

        self.assertEqual(result, [])
        payload = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collected_record_filtered"
        )
        self.assertEqual(payload["reason"], "missing_profile_url")

    def test_compatibility_mode_keeps_empty_comment_priority(self):
        logger = FakeLogger()

        result = xhs._xhs_filter_comment_candidates(
            [{"user": "用户", "text": "", "profile": ""}],
            log=logger,
            strict=False,
        )

        self.assertEqual(result, [])
        payload = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collected_record_filtered"
        )
        self.assertEqual(payload["reason"], "empty_comment")

    def test_legacy_duplicate_is_logged_when_strict_filter_is_disabled(self):
        logger = FakeLogger()
        result = xhs._xhs_filter_comment_candidates(
            [
                {"user": "用户", "text": "价格", "profile": ""},
                {"user": "用户", "text": "价格", "profile": ""},
            ],
            log=logger,
            strict=False,
        )
        self.assertEqual(len(result), 1)
        payload = next(json.loads(raw) for _level, raw in logger.rows if json.loads(raw)["event"] == "xhs_collected_record_deduplicated")
        self.assertEqual(payload["reason"], "duplicate_user_comment")

    def test_legacy_filter_limits_in_compatibility_order_and_logs_each_discard(self):
        logger = FakeLogger()
        rows = [
            {
                "user": "legacy-user-%s" % index,
                "text": "legacy-comment-%s" % index,
                "profile": "https://www.xiaohongshu.com/user/profile/legacy-%s" % index,
            }
            for index in range(302)
        ]

        result = xhs._xhs_filter_comment_candidates(rows, log=logger, strict=False)

        self.assertEqual(len(result), 300)
        self.assertEqual([item["user"] for item in result], ["legacy-user-%s" % index for index in range(300)])
        limit_logs = [
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collected_record_filtered"
            and json.loads(raw)["reason"] == "result_limit_exceeded"
        ]
        self.assertEqual([payload["candidateIndex"] for payload in limit_logs], [300, 301])

    def test_three_hundred_candidate_filter_stays_under_test_budget(self):
        rows = [
            {
                "user": "用户%s" % index,
                "text": "价格多少",
                "profile": "https://www.xiaohongshu.com/user/profile/user%s" % index,
            }
            for index in range(300)
        ]
        started = time.perf_counter()
        result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(result), 300)
        self.assertLess(elapsed, 0.05)

    def test_three_hundred_candidate_filter_stays_under_memory_budget(self):
        rows = [
            {
                "user": "memory-user-%s" % index,
                "text": "memory-comment-%s" % index,
                "profile": "https://www.xiaohongshu.com/user/profile/memory-%s" % index,
            }
            for index in range(300)
        ]
        tracemalloc.start()
        try:
            result = xhs._xhs_filter_comment_candidates(rows, log=FakeLogger(), strict=True)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        self.assertEqual(len(result), 300)
        self.assertLess(peak, 5 * 1024 * 1024)


class XhsLeadIntegrationTests(unittest.TestCase):
    def test_browser_collector_does_not_select_every_container_div(self):
        source = inspect.getsource(xhs.xhs_get_comments)
        self.assertNotIn(".comments-container div", source)
        self.assertNotIn(".comment-list div", source)
        self.assertIn("rawText", source)
        self.assertIn("_xhs_filter_comment_candidates", source)
        self.assertGreaterEqual(source.count("if len(raw_candidates) >= candidate_limit:"), 2)
        self.assertNotIn("rows.push({id:", source)
        self.assertIn("candidate_limit = 900", source)
        self.assertNotIn("limit * 3", source)
        self.assertIn("result_limit=limit", source)
        self.assertNotIn(")[:limit]", source)
        self.assertIn("candidate_limit=candidate_limit", source)
        self.assertIn("candidate_limit_reached=", source)
        self.assertNotIn("const seen = new Set()", source)
        self.assertIn("candidate_duplicate_count", source)
        self.assertIn("xhs_collection_page_navigation_failed", source)

    def test_discovery_returns_sanitized_collection_errors(self):
        secret_url = "https://www.xiaohongshu.com/explore/note-a?xsec_token=secret-value"
        logger = FakeLogger()

        with mock.patch.object(xhs, "xhs_search_notes", return_value={"items": [{"work_url": secret_url}]}), mock.patch.object(
            xhs,
            "xhs_get_comments",
            side_effect=RuntimeError("request failed secret-value"),
        ), mock.patch.object(xhs, "logger", logger):
            result = xhs.discover_xhs_leads_by_keyword("丰田汽车", video_num=1)

        self.assertEqual(len(result["errors"]), 1)
        error = result["errors"][0]
        self.assertEqual(error["url"], "https://www.xiaohongshu.com/explore/note-a")
        self.assertEqual(error["error"], "xhs_comment_collection_failed")
        self.assertRegex(error["errorId"], r"^err-[0-9a-f]{16}$")
        serialized = json.dumps(result["errors"], ensure_ascii=False)
        logs = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("secret-value", logs)
        payload = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_note_collection_failed"
        )
        self.assertEqual(payload["errorId"], error["errorId"])

    def test_discovery_propagates_xhs_search_ip_risk(self):
        logger = FakeLogger()

        with mock.patch.object(
            xhs,
            "xhs_search_notes",
            return_value={
                "ok": False,
                "blocked": True,
                "riskCode": "300012",
                "error": "xhs_ip_risk",
                "debug": {
                    "url": "https://www.xiaohongshu.com/search_result?keyword=secret-query",
                    "title": "安全限制",
                    "bodyText": "IP存在风险，请切换可靠网络环境后重试 300012",
                    "html": "debug.html",
                    "screenshot": "debug.png",
                },
            },
        ), mock.patch.object(xhs, "logger", logger):
            result = xhs.discover_xhs_leads_by_keyword("丰田汽车", video_num=1)

        self.assertIs(result["ok"], False)
        self.assertIs(result["blocked"], True)
        self.assertEqual(result["error"], "xhs_ip_risk")
        self.assertEqual(result["riskCode"], "300012")
        self.assertEqual(result["videoCount"], 0)
        self.assertEqual(result["commentCount"], 0)
        self.assertEqual(result["leadCount"], 0)

        logs = "\n".join(raw for _level, raw in logger.rows)
        self.assertNotIn("secret-query", logs)
        payload = next(
            json.loads(raw)
            for _level, raw in logger.rows
            if json.loads(raw)["event"] == "xhs_collection_search_failed"
        )
        self.assertEqual(payload["error"], "xhs_ip_risk")
        self.assertEqual(payload["riskCode"], "300012")
        self.assertEqual(payload["keywordLength"], 4)
        self.assertRegex(payload["keywordFingerprint"], r"^[0-9a-f]{16}$")

    def test_discovery_deduplicates_same_profile_across_notes(self):
        videos = [
            {"work_url": "https://www.xiaohongshu.com/explore/note-a", "title": "A"},
            {"work_url": "https://www.xiaohongshu.com/explore/note-b", "title": "B"},
        ]
        profile = "https://www.xiaohongshu.com/user/profile/repeat"
        side_effect = [
            {"items": [{"user": "用户", "text": "想了解", "profileUrl": profile, "intent": "咨询", "diggCount": 30, "noteId": "note-a"}]},
            {"items": [{"user": "用户", "text": "价格多少", "profileUrl": profile + "?xsec_token=secret", "intent": "高意向", "diggCount": 1, "noteId": "note-b"}]},
        ]
        with mock.patch.object(xhs, "xhs_search_notes", return_value={"items": videos}), mock.patch.object(
            xhs, "xhs_get_comments", side_effect=side_effect
        ), mock.patch.object(xhs, "json_log"):
            result = xhs.discover_xhs_leads_by_keyword("丰田汽车", video_num=2)

        self.assertEqual(result["commentCount"], 1)
        self.assertEqual(result["leadCount"], 1)
        self.assertEqual(result["leads"][0]["text"], "价格多少")
        self.assertEqual(result["leads"][0]["profileUrl"], profile)

    def test_discovery_preserves_different_profiles_with_same_username(self):
        videos = [{"work_url": "https://www.xiaohongshu.com/explore/note-a"}]
        items = [
            {"user": "同名", "text": "价格", "profileUrl": "https://www.xiaohongshu.com/user/profile/a", "intent": "高意向"},
            {"user": "同名", "text": "怎么买", "profileUrl": "https://www.xiaohongshu.com/user/profile/b", "intent": "高意向"},
        ]
        with mock.patch.object(xhs, "xhs_search_notes", return_value={"items": videos}), mock.patch.object(
            xhs, "xhs_get_comments", return_value={"items": items}
        ), mock.patch.object(xhs, "json_log"):
            result = xhs.discover_xhs_leads_by_keyword("丰田汽车", video_num=1)
        self.assertEqual(result["leadCount"], 2)


if __name__ == "__main__":
    unittest.main()
