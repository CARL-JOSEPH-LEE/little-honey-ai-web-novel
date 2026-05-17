
from __future__ import annotations

import unittest
from pathlib import Path

from novel_writer.config import (
    DEEPSEEK_CONTEXT_MAX_TOKENS,
    DEEPSEEK_CONTEXT_SAFE_TOKENS,
    DEEPSEEK_OUTPUT_MAX_TOKENS,
    DEFAULT_INPUT_TOKEN_LIMIT,
    DEFAULT_OUTPUT_TOKEN_LIMIT,
    INPUT_TOKEN_SAFETY_MARGIN,
)
from novel_writer.context import DEFAULT_CONTEXT_TOKEN_BUDGET, build_context_pack, upsert_chapter_summary


class ContextTests(unittest.TestCase):
    def test_token_contract_matches_product_limits(self) -> None:
        self.assertEqual(DEEPSEEK_CONTEXT_MAX_TOKENS, 1_000_000)
        self.assertEqual(DEFAULT_INPUT_TOKEN_LIMIT, 800_000)
        self.assertEqual(DEFAULT_OUTPUT_TOKEN_LIMIT, 200_000)
        self.assertEqual(INPUT_TOKEN_SAFETY_MARGIN, 10_000)
        self.assertEqual(DEEPSEEK_CONTEXT_SAFE_TOKENS, 790_000)
        self.assertEqual(DEFAULT_CONTEXT_TOKEN_BUDGET, 790_000)
        self.assertEqual(DEEPSEEK_OUTPUT_MAX_TOKENS, 200_000)

    def test_context_pack_uses_recent_summaries_and_upcoming_outlines(self) -> None:
        outlines = [
            {"chapter": 1, "title": "一"},
            {"chapter": 2, "title": "二"},
            {"chapter": 3, "title": "三"},
            {"chapter": 4, "title": "四"},
        ]
        summaries = [
            {"chapter": 1, "summary": "一"},
            {"chapter": 2, "summary": "二"},
        ]
        context = build_context_pack(
            project_dir=Path("not-existing"),
            brief={"title": "书", "tags": [], "chapter_count": 4, "premise": "设定"},
            plan={"title": "书", "logline": "卖点"},
            chapter_outline=outlines[3],
            continuity={"timeline": []},
            chapter_summaries=summaries,
            all_outlines=outlines,
            recent_chapter_count=1,
        )

        self.assertEqual(context["recent_chapter_summaries"], [{"chapter": 2, "summary": "二"}])
        self.assertEqual(context["upcoming_outlines"], [])

    def test_upsert_chapter_summary_replaces_existing_item(self) -> None:
        result = upsert_chapter_summary(
            [{"chapter": 1, "summary": "旧"}],
            {"chapter": 1, "summary": "新"},
        )
        self.assertEqual(result, [{"chapter": 1, "summary": "新"}])

    def test_upsert_chapter_summary_keeps_chapters_sorted(self) -> None:
        result = upsert_chapter_summary(
            [{"chapter": 2, "summary": "二"}, {"chapter": 1, "summary": "一"}],
            {"chapter": 3, "summary": "三"},
        )
        self.assertEqual([item["chapter"] for item in result], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
