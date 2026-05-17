
from __future__ import annotations

import json
import os
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from novel_writer.config import DEFAULT_INPUT_TOKEN_LIMIT, DEFAULT_OUTPUT_TOKEN_LIMIT


PROJECT_INDEX_FILE = "project.json"
DEFAULT_PROJECTS_DIR = Path(os.path.expanduser("~")) / "dsbook_projects"


class NovelProject:

    def __init__(self) -> None:
        self.project_id: str = uuid.uuid4().hex[:12]
        self.save_path: str = ""
        self.title: str = ""
        self.tags: list[str] = []

        self.audience: str = ""

        self.custom_tags: list[str] = []
        self.total_chapters: int = 1000
        self.words_per_chapter: int = 5000
        self.min_quality_score: int = 88
        self.input_token_limit: int = DEFAULT_INPUT_TOKEN_LIMIT
        self.output_token_limit: int = DEFAULT_OUTPUT_TOKEN_LIMIT
        self.reasoning_effort: str = "high"
        self.thinking_enabled: bool = True
        self.model: str = "deepseek-v4-flash"
        self.ask_each_chapter: bool = False
        self.status: str = "new"
        self.current_chapter: int = 0
        self.total_words: int = 0
        self.created_at: str = datetime.now().isoformat(timespec="seconds")
        self.updated_at: str = self.created_at
        self.concept: dict[str, Any] | None = None
        self.synopsis: str = ""
        self.last_error: str = ""
        self.chapters: dict[str, dict[str, Any]] = {}





    def merged_tags(self) -> list[str]:

        merged: list[str] = []
        seen: set[str] = set()
        for source in (self.tags, self.custom_tags):
            for tag in source:
                tag = str(tag).strip()
                if not tag or tag in seen:
                    continue
                seen.add(tag)
                merged.append(tag)
        return merged





    def save(self) -> None:
        if not self.save_path:
            raise ValueError("project.save_path is empty; cannot save.")
        directory = Path(self.save_path)
        directory.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        index_path = directory / PROJECT_INDEX_FILE
        index_path.write_text(
            json.dumps(self._to_index_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "NovelProject":
        directory = Path(path)
        if directory.is_file():
            directory = directory.parent
        index_path = directory / PROJECT_INDEX_FILE
        if not index_path.exists():
            raise FileNotFoundError(f"项目索引不存在：{index_path}")
        data = json.loads(index_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"项目索引格式错误：{index_path}")
        project = cls()
        project._apply_index_dict(data)
        if not project.save_path:
            project.save_path = str(directory)
        project.refresh()
        return project

    @staticmethod
    def list_projects(root: str | Path) -> list[str]:

        directory = Path(root)
        if not directory.exists():
            return []
        candidates: list[tuple[float, str]] = []
        for child in directory.iterdir():
            if not child.is_dir():
                continue
            index_path = child / PROJECT_INDEX_FILE
            if not index_path.exists():
                continue
            candidates.append((index_path.stat().st_mtime, str(child)))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in candidates]





    def refresh(self) -> None:

        if not self.save_path:
            return
        directory = Path(self.save_path)
        chapters_dir = directory / "chapters_txt"
        chapters: dict[str, dict[str, Any]] = {}
        total_words = 0
        last_chapter = 0
        if chapters_dir.exists():
            for txt_path in sorted(chapters_dir.glob("*.txt")):
                stem = txt_path.stem
                match = re.match(r"^(\d+)-(.*)$", stem)
                if not match:
                    continue
                num_str = str(int(match.group(1)))
                slug = match.group(2)
                text = txt_path.read_text(encoding="utf-8")
                title = self._extract_title_from_plain(text) or slug
                content = self._strip_heading(text)
                word_count = self._count_chinese(content)
                chapters[num_str] = {
                    "title": title,
                    "content": content,
                    "word_count": word_count,
                    "txt_path": str(txt_path),
                }
                total_words += word_count
                last_chapter = max(last_chapter, int(num_str))


        self.chapters = chapters
        self.total_words = total_words
        self.current_chapter = last_chapter

        plan_path = directory / "plan.json"
        if plan_path.exists() and not self.title:
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
                if isinstance(plan, dict):
                    title = str(plan.get("title") or "")
                    if title:
                        self.title = title
            except json.JSONDecodeError:
                pass

        brief_path = directory / "brief.json"
        if brief_path.exists():
            try:
                brief = json.loads(brief_path.read_text(encoding="utf-8"))
                if isinstance(brief, dict):
                    if self.concept is None:
                        self.concept = brief
                    if not self.title:
                        self.title = str(brief.get("title") or "")
                    synopsis = str(brief.get("synopsis") or "").strip()
                    if synopsis:
                        self.synopsis = synopsis
                    if not self.audience:
                        self.audience = str(brief.get("audience") or "")
            except json.JSONDecodeError:
                pass





    def export_txt(self, target_path: str | Path) -> None:

        if not self.save_path:
            raise ValueError("project.save_path is empty; cannot export.")
        manuscript = Path(self.save_path) / "manuscript.txt"
        if not manuscript.exists():
            raise FileNotFoundError(
                f"manuscript.txt 还没生成：{manuscript}。"
                "至少完成 1 章后再导出。"
            )
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(manuscript, target)





    def chapter_text_path(self, chapter_number: int) -> Path | None:
        if not self.save_path:
            return None
        chapters_dir = Path(self.save_path) / "chapters_txt"
        if not chapters_dir.exists():
            return None
        for txt_path in chapters_dir.glob(f"{chapter_number:04d}-*.txt"):
            return txt_path
        return None

    def manuscript_md_path(self) -> Path | None:
        if not self.save_path:
            return None
        path = Path(self.save_path) / "manuscript.md"
        return path if path.exists() else None

    def manuscript_txt_path(self) -> Path | None:
        if not self.save_path:
            return None
        path = Path(self.save_path) / "manuscript.txt"
        return path if path.exists() else None





    def _to_index_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "save_path": self.save_path,
            "title": self.title,
            "tags": list(self.tags),
            "audience": self.audience,
            "custom_tags": list(self.custom_tags),
            "total_chapters": int(self.total_chapters),
            "words_per_chapter": int(self.words_per_chapter),
            "min_quality_score": int(self.min_quality_score),
            "input_token_limit": int(self.input_token_limit),
            "output_token_limit": int(self.output_token_limit),
            "reasoning_effort": self.reasoning_effort,
            "thinking_enabled": bool(self.thinking_enabled),
            "model": self.model,
            "ask_each_chapter": bool(self.ask_each_chapter),
            "status": self.status,
            "current_chapter": int(self.current_chapter),
            "total_words": int(self.total_words),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "concept": self.concept,
            "synopsis": self.synopsis,
            "last_error": self.last_error,
        }

    def _apply_index_dict(self, data: dict[str, Any]) -> None:
        self.project_id = str(data.get("project_id") or self.project_id)
        self.save_path = str(data.get("save_path") or "")
        self.title = str(data.get("title") or "")
        tags = data.get("tags") or []
        if isinstance(tags, list):
            self.tags = [str(item) for item in tags]
        self.audience = str(data.get("audience") or "")
        custom_tags = data.get("custom_tags") or []
        if isinstance(custom_tags, list):
            self.custom_tags = [str(item) for item in custom_tags]
        self.total_chapters = int(data.get("total_chapters") or self.total_chapters)
        self.words_per_chapter = int(data.get("words_per_chapter") or self.words_per_chapter)
        self.min_quality_score = int(data.get("min_quality_score") or self.min_quality_score)
        self.input_token_limit = int(data.get("input_token_limit") or self.input_token_limit)
        self.output_token_limit = int(data.get("output_token_limit") or self.output_token_limit)
        self.reasoning_effort = str(data.get("reasoning_effort") or self.reasoning_effort)
        self.thinking_enabled = bool(data.get("thinking_enabled", self.thinking_enabled))
        self.model = str(data.get("model") or self.model)
        self.ask_each_chapter = bool(data.get("ask_each_chapter", self.ask_each_chapter))
        self.status = str(data.get("status") or self.status)
        self.current_chapter = int(data.get("current_chapter") or 0)
        self.total_words = int(data.get("total_words") or 0)
        self.created_at = str(data.get("created_at") or self.created_at)
        self.updated_at = str(data.get("updated_at") or self.updated_at)
        concept = data.get("concept")
        self.concept = concept if isinstance(concept, dict) else None
        self.synopsis = str(data.get("synopsis") or "")
        self.last_error = str(data.get("last_error") or "")

    @staticmethod
    def _extract_title_from_plain(text: str) -> str:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.match(r"^第\s*\d+\s*章\s*(.+)$", line)
            if match:
                return match.group(1).strip()
            return line
        return ""

    @staticmethod
    def _strip_heading(text: str) -> str:
        lines = text.splitlines()
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and re.match(r"^第\s*\d+\s*章", lines[0].strip()):
            lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines).strip()

    @staticmethod
    def _count_chinese(text: str) -> int:
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        if cjk:
            return cjk
        return len(re.sub(r"\s+", "", text))


__all__ = ["NovelProject", "DEFAULT_PROJECTS_DIR", "PROJECT_INDEX_FILE"]
