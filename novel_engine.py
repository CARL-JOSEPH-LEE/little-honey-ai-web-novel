
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from novel_project import DEFAULT_PROJECTS_DIR, NovelProject
from novel_writer.config import (
    DEFAULT_BASE_URL,
    DEFAULT_INPUT_TOKEN_LIMIT,
    DEFAULT_MAX_RETRIES,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_TOKEN_LIMIT,
    DEFAULT_REASONING_EFFORT,
    DEFAULT_TIMEOUT_SECONDS,
    DeepSeekConfig,
    INPUT_TOKEN_SAFETY_MARGIN,
)
from novel_writer.deepseek_client import DeepSeekClient
from novel_writer.errors import NovelWriterError
from novel_writer.pipeline import (
    DEFAULT_MIN_QUALITY_SCORE,
    DEFAULT_RECENT_CHAPTER_COUNT,
    DEFAULT_WORDS_PER_CHAPTER,
    CancelledError,
    NovelPipeline,
    PipelineOptions,
    collect_avoid_history,
)


StatusCallback = Callable[[str], None]
ChapterStartCallback = Callable[[int, int], None]
ChunkCallback = Callable[[str], None]
ChapterCompleteCallback = Callable[[int, int], None]
ChapterFeedbackCallback = Callable[[int, str], str | None]
CompleteCallback = Callable[[], None]
ErrorCallback = Callable[[str], None]



_STAGE_LABELS = {
    "concept": "自动生成原创 brief",
    "ready": "项目就绪",
    "plan": "基础设定生成",
    "plan_start": "开始基础设定",
    "chapter_plan": "设计本章方向",
    "blueprint": "场景蓝图",
    "chapter_start": "开始生成章节",
    "draft_start": "起草章节正文",
    "chapter": "章节正文流式生成",
    "expansion": "字数不足扩写",
    "tightening": "字数超限精简",
    "quality_review": "质量评审",
    "quality_pass": "质量达标",
    "quality_rewrite": "按评审重写",
    "summary": "压缩章节记忆",
    "continuity": "更新连续性记忆",
    "chapter_done": "章节完成",
    "user_feedback": "等待用户输入下一章方向",
    "skipped": "跳过已完成章节",
    "stream": "流式生成中",
    "api": "API 调用完成",
    "done": "项目完成",
}


class NovelEngine:

    def __init__(
        self,
        api_key: str,
        project: NovelProject,
        model: str = DEFAULT_MODEL,
        *,
        projects_root: Path | str = DEFAULT_PROJECTS_DIR,
        base_url: str = DEFAULT_BASE_URL,
        reasoning_effort: str | None = None,
        thinking_enabled: bool | None = None,
        request_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError("API Key 不能为空。")
        if not project.save_path:
            raise ValueError("project.save_path 不能为空。")
        self._api_key = api_key.strip()
        self._project = project
        self._model = model or DEFAULT_MODEL
        self._reasoning_effort = (
            reasoning_effort or project.reasoning_effort or DEFAULT_REASONING_EFFORT
        )
        self._thinking_enabled = (
            thinking_enabled if thinking_enabled is not None else project.thinking_enabled
        )
        self._base_url = base_url
        self._request_timeout_seconds = request_timeout_seconds
        self._max_retries = max_retries
        self._projects_root = Path(projects_root)
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()





    def pause(self) -> None:
        self._pause_event.clear()

    def resume(self) -> None:
        self._pause_event.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._pause_event.set()

    def run(
        self,
        *,
        on_status: StatusCallback | None = None,
        on_chapter_start: ChapterStartCallback | None = None,
        on_chunk: ChunkCallback | None = None,
        on_chapter_complete: ChapterCompleteCallback | None = None,
        on_chapter_feedback: ChapterFeedbackCallback | None = None,
        on_complete: CompleteCallback | None = None,
        on_error: ErrorCallback | None = None,
    ) -> None:

        try:
            self._run_inner(
                on_status=on_status,
                on_chapter_start=on_chapter_start,
                on_chunk=on_chunk,
                on_chapter_complete=on_chapter_complete,
                on_chapter_feedback=on_chapter_feedback,
                on_complete=on_complete,
            )
        except CancelledError:
            self._project.status = "paused"
            self._project.last_error = ""
            self._project.save()
            self._notify(on_status, "已停止")
        except (NovelWriterError, ValueError, RuntimeError, FileNotFoundError) as exc:
            message = f"{type(exc).__name__}: {exc}"
            self._project.status = "error"
            self._project.last_error = message
            self._project.save()
            if on_error is not None:
                on_error(message)





    def _run_inner(
        self,
        *,
        on_status: StatusCallback | None,
        on_chapter_start: ChapterStartCallback | None,
        on_chunk: ChunkCallback | None,
        on_chapter_complete: ChapterCompleteCallback | None,
        on_chapter_feedback: ChapterFeedbackCallback | None,
        on_complete: CompleteCallback | None,
    ) -> None:
        self._project.refresh()
        config = DeepSeekConfig(
            api_key=self._api_key,
            base_url=self._base_url,
            model=self._model,
            reasoning_effort=self._reasoning_effort,
            thinking_enabled=self._thinking_enabled,
            request_timeout_seconds=self._request_timeout_seconds,
            max_retries=self._max_retries,
        )
        client = DeepSeekClient(config)
        pipeline = NovelPipeline(client)
        project_dir = Path(self._project.save_path)
        project_dir.mkdir(parents=True, exist_ok=True)

        merged_tags = self._project.merged_tags() or ["玄幻"]
        output_token_limit = max(
            1,
            int(self._project.output_token_limit or DEFAULT_OUTPUT_TOKEN_LIMIT),
        )

        if not self._project.concept:
            self._notify(on_status, "正在让模型设计独特的小说设定…")
            self._project.status = "planning"
            self._project.save()
            avoid_history = collect_avoid_history(self._projects_root)
            brief = pipeline.synthesize_brief(
                tags=merged_tags,
                chapter_count=self._project.total_chapters,
                words_per_chapter=self._project.words_per_chapter,
                audience=self._project.audience,
                requested_title=self._project.title,
                requested_synopsis=self._project.synopsis,
                avoid_history=avoid_history,
                max_tokens=output_token_limit,
                progress=self._make_progress_callback(
                    on_status=on_status,
                    on_chapter_start=on_chapter_start,
                    on_chunk=on_chunk,
                    on_chapter_complete=on_chapter_complete,
                ),
            )
            brief["chapter_count"] = self._project.total_chapters
            self._project.concept = brief
            self._project.title = str(brief.get("title") or self._project.title or "未命名小说")
            self._project.synopsis = str(brief.get("synopsis") or "").strip()
            if not self._project.audience:
                self._project.audience = str(brief.get("audience") or "")
            self._project.save()
            self._notify(
                on_status,
                f"原创设定完成：《{self._project.title}》（含 {len(self._project.synopsis)} 字简介）",
            )

        brief = dict(self._project.concept)
        brief["title"] = self._project.title
        brief["chapter_count"] = self._project.total_chapters
        if self._project.audience:
            brief["audience"] = self._project.audience
        if self._project.synopsis and not brief.get("synopsis"):
            brief["synopsis"] = self._project.synopsis

        options = PipelineOptions(
            output_root=project_dir,
            words_per_chapter=self._project.words_per_chapter,
            plan_max_tokens=output_token_limit,
            chapter_max_tokens=output_token_limit,
            review_max_tokens=output_token_limit,
            summary_max_tokens=output_token_limit,
            continuity_max_tokens=output_token_limit,
            blueprint_max_tokens=output_token_limit,
            concept_max_tokens=output_token_limit,
            min_quality_score=self._project.min_quality_score,
            recent_chapter_count=DEFAULT_RECENT_CHAPTER_COUNT,
            context_token_budget=max(
                1,
                int(self._project.input_token_limit or DEFAULT_INPUT_TOKEN_LIMIT)
                - INPUT_TOKEN_SAFETY_MARGIN,
            ),
            cancel_check=self._cancel_check,
            chapter_feedback_provider=self._make_chapter_feedback_provider(on_chapter_feedback),
            explicit_project_dir=project_dir,
        )

        self._project.status = "writing"
        self._project.save()
        self._notify(on_status, "开始生成章节…")

        progress = self._make_progress_callback(
            on_status=on_status,
            on_chapter_start=on_chapter_start,
            on_chunk=on_chunk,
            on_chapter_complete=on_chapter_complete,
        )

        pipeline.run(brief=brief, options=options, progress=progress)

        self._project.refresh()
        self._project.status = "completed"
        self._project.save()
        if on_complete is not None:
            on_complete()

    def _cancel_check(self) -> bool:

        if not self._pause_event.is_set():
            self._pause_event.wait()
        return self._stop_event.is_set()

    def _make_progress_callback(
        self,
        *,
        on_status: StatusCallback | None,
        on_chapter_start: ChapterStartCallback | None,
        on_chunk: ChunkCallback | None,
        on_chapter_complete: ChapterCompleteCallback | None,
    ):
        def progress(stage: str, payload: dict[str, Any]) -> None:
            if stage == "stream":
                if on_chunk is not None:
                    delta = payload.get("content_delta") or ""
                    if delta:
                        on_chunk(delta)
                return
            if stage == "chapter_start":
                if on_chapter_start is not None:
                    on_chapter_start(int(payload.get("chapter") or 0), int(payload.get("total") or 0))
                self._notify(on_status, _format_status(stage, payload))
                return
            if stage == "chapter_done":
                if on_chapter_complete is not None:
                    on_chapter_complete(
                        int(payload.get("chapter") or 0),
                        int(payload.get("chars") or 0),
                    )

                self._project.refresh()
                self._project.save()
                self._notify(on_status, _format_status(stage, payload))
                return
            self._notify(on_status, _format_status(stage, payload))

        return progress

    def _make_chapter_feedback_provider(
        self,
        callback: ChapterFeedbackCallback | None,
    ) -> ChapterFeedbackCallback | None:
        if not self._project.ask_each_chapter or callback is None:
            return None

        def provider(chapter: int, title: str) -> str | None:
            return callback(chapter, title)

        return provider

    def _notify(self, callback: StatusCallback | None, message: str) -> None:
        if callback is not None:
            callback(message)


def _format_status(stage: str, payload: dict[str, Any]) -> str:
    label = _STAGE_LABELS.get(stage, stage)
    chapter = payload.get("chapter")
    if chapter:
        return f"{label}（第 {chapter} 章）"
    if stage == "chapter_done":
        completed = payload.get("completed")
        total = payload.get("total")
        if completed and total:
            return f"已完成 {completed}/{total} 章"
    return label


__all__ = ["NovelEngine"]
