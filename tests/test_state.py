
from __future__ import annotations

import unittest

from novel_writer.state import (
    chapter_filename,
    format_chapter_heading,
    parse_json_object,
    plain_chapter_filename,
    slugify,
    to_plain_chapter,
)


class StateTests(unittest.TestCase):
    def test_parse_json_object_accepts_plain_json(self) -> None:
        self.assertEqual(
            parse_json_object('{"title": "天命之外"}'),
            {"title": "天命之外"},
        )

    def test_parse_json_object_accepts_fenced_json(self) -> None:
        self.assertEqual(parse_json_object('```json\n{"chapter": 1}\n```'), {"chapter": 1})

    def test_parse_json_object_recovers_from_padding(self) -> None:

        text = '一些前导说明...{"chapter": 7, "title": "登顶"}收尾'
        self.assertEqual(parse_json_object(text), {"chapter": 7, "title": "登顶"})

    def test_parse_json_object_repairs_missing_comma_between_fields(self) -> None:
        text = '{\n  "chapter": 1,\n  "title": "起势"\n  "summary": "主角入局"\n}'
        self.assertEqual(
            parse_json_object(text),
            {"chapter": 1, "title": "起势", "summary": "主角入局"},
        )

    def test_parse_json_object_removes_trailing_comma(self) -> None:
        self.assertEqual(parse_json_object('{"chapter": 1,}'), {"chapter": 1})

    def test_slugify_keeps_chinese_title(self) -> None:
        self.assertEqual(slugify("天命之外：第一卷"), "天命之外第一卷")

    def test_slugify_falls_back_to_hash_when_empty(self) -> None:
        slug = slugify("...///", fallback="novel")
        self.assertTrue(slug.startswith("novel-"))
        self.assertGreater(len(slug), len("novel-"))

    def test_chapter_filename_is_zero_padded(self) -> None:
        self.assertEqual(chapter_filename(7, "登顶"), "0007-登顶.md")
        self.assertEqual(plain_chapter_filename(120, "决战"), "0120-决战.txt")

    def test_to_plain_chapter_strips_markdown_headings(self) -> None:
        body = "# 多余的标题\n\n这是正文第一段。\n\n这是正文第二段。"
        out = to_plain_chapter(7, "登顶", body)
        self.assertTrue(out.startswith("第7章 登顶"))
        self.assertIn("这是正文第一段", out)
        self.assertNotIn("# 多余的标题", out)

    def test_format_chapter_heading_handles_existing_prefix(self) -> None:
        self.assertEqual(format_chapter_heading(3, "第3章 起势"), "第3章 起势")
        self.assertEqual(format_chapter_heading(3, "起势"), "第3章 起势")

if __name__ == "__main__":
    unittest.main()
