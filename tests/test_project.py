
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from novel_project import NovelProject


class NovelProjectTests(unittest.TestCase):
    def _make_project(self, root: Path, *, title: str = "测试小说") -> NovelProject:
        proj = NovelProject()
        proj.tags = ["玄幻", "热血"]
        proj.total_chapters = 6
        proj.words_per_chapter = 5500
        proj.title = title
        proj.save_path = str(root / "novel_demo")
        proj.save()
        return proj

    def test_save_writes_index_file(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project = self._make_project(Path(temp_dir))
            index_path = Path(project.save_path) / "project.json"
            self.assertTrue(index_path.exists())
            data = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(data["title"], "测试小说")
            self.assertEqual(data["tags"], ["玄幻", "热血"])
            self.assertEqual(data["total_chapters"], 6)
            self.assertEqual(data["words_per_chapter"], 5500)

    def test_load_restores_fields(self) -> None:
        with TemporaryDirectory() as temp_dir:
            saved = self._make_project(Path(temp_dir))
            loaded = NovelProject.load(saved.save_path)
            self.assertEqual(loaded.title, "测试小说")
            self.assertEqual(loaded.tags, ["玄幻", "热血"])
            self.assertEqual(loaded.total_chapters, 6)
            self.assertEqual(loaded.words_per_chapter, 5500)

    def test_list_projects_returns_paths_sorted_by_mtime(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_a = NovelProject()
            project_a.title = "A"
            project_a.save_path = str(root / "novel_a")
            project_a.save()
            project_b = NovelProject()
            project_b.title = "B"
            project_b.save_path = str(root / "novel_b")
            project_b.save()
            paths = NovelProject.list_projects(root)
            self.assertEqual(set(paths), {project_a.save_path, project_b.save_path})

    def test_refresh_reads_chapters_txt(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project = self._make_project(Path(temp_dir))
            chapters_dir = Path(project.save_path) / "chapters_txt"
            chapters_dir.mkdir(parents=True)
            (chapters_dir / "0001-起势.txt").write_text(
                "第1章 起势\n\n这是 第 1 章 的 第 一 段。",
                encoding="utf-8",
            )
            (chapters_dir / "0002-决战.txt").write_text(
                "第2章 决战\n\n第二章正文写得很多很多很多很多。",
                encoding="utf-8",
            )
            project.refresh()
            self.assertEqual(project.current_chapter, 2)
            self.assertEqual(set(project.chapters.keys()), {"1", "2"})
            self.assertGreater(project.total_words, 0)
            chapter_one = project.chapters["1"]
            self.assertEqual(chapter_one["title"], "起势")
            self.assertNotIn("第1章", chapter_one["content"])

    def test_export_txt_copies_manuscript(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project = self._make_project(Path(temp_dir))
            manuscript = Path(project.save_path) / "manuscript.txt"
            manuscript.parent.mkdir(parents=True, exist_ok=True)
            manuscript.write_text("全文内容", encoding="utf-8")
            project.refresh()

            chapters_dir = Path(project.save_path) / "chapters_txt"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            (chapters_dir / "0001-起势.txt").write_text(
                "第1章 起势\n\n正文",
                encoding="utf-8",
            )
            project.refresh()
            target = Path(temp_dir) / "out" / "novel.txt"
            project.export_txt(target)
            self.assertEqual(target.read_text(encoding="utf-8"), "全文内容")

    def test_export_txt_raises_when_manuscript_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project = self._make_project(Path(temp_dir))
            chapters_dir = Path(project.save_path) / "chapters_txt"
            chapters_dir.mkdir(parents=True, exist_ok=True)
            (chapters_dir / "0001-x.txt").write_text("第1章\n\n正文", encoding="utf-8")
            project.refresh()
            target = Path(temp_dir) / "out" / "novel.txt"
            with self.assertRaises(FileNotFoundError):
                project.export_txt(target)

    def test_audience_synopsis_and_custom_tags_persist(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = NovelProject()
            project.title = "测试"
            project.save_path = str(root / "novel_x")
            project.tags = ["玄幻"]
            project.custom_tags = ["听言流", "民国"]
            project.audience = "男频玄幻读者"
            project.synopsis = "一段简介。" * 30
            project.save()

            loaded = NovelProject.load(project.save_path)
            self.assertEqual(loaded.custom_tags, ["听言流", "民国"])
            self.assertEqual(loaded.audience, "男频玄幻读者")
            self.assertEqual(loaded.synopsis, "一段简介。" * 30)
            self.assertEqual(loaded.merged_tags(), ["玄幻", "听言流", "民国"])

    def test_ask_each_chapter_persists(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project = NovelProject()
            project.title = "测试"
            project.save_path = str(Path(temp_dir) / "novel_x")
            project.ask_each_chapter = True
            project.save()

            loaded = NovelProject.load(project.save_path)
            self.assertTrue(loaded.ask_each_chapter)

    def test_merged_tags_dedupes_predefined_and_custom(self) -> None:
        project = NovelProject()
        project.tags = ["玄幻", "热血"]
        project.custom_tags = ["热血", "听言流", " 听言流 ", "玄幻"]
        self.assertEqual(project.merged_tags(), ["玄幻", "热血", "听言流"])

    def test_refresh_picks_up_synopsis_from_brief_json(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project = NovelProject()
            project.title = "x"
            project.save_path = str(Path(temp_dir) / "novel_demo")
            project.save()
            brief = {
                "title": "听言之书",
                "tags": ["玄幻"],
                "premise": "测试",
                "audience": "男频玄幻读者",
                "synopsis": "刷新测试用的简介。" * 30,
            }
            (Path(project.save_path) / "brief.json").write_text(
                json.dumps(brief, ensure_ascii=False),
                encoding="utf-8",
            )
            project.refresh()
            self.assertEqual(project.synopsis, "刷新测试用的简介。" * 30)
            self.assertEqual(project.audience, "男频玄幻读者")


if __name__ == "__main__":
    unittest.main()
