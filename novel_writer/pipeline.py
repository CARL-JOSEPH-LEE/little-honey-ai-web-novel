
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .config import DEEPSEEK_OUTPUT_MAX_TOKENS, DEFAULT_CONTEXT_TOKEN_BUDGET
from .context import (
    build_context_pack,
    estimate_json_tokens,
    load_chapter_summaries,
    save_chapter_summaries,
    upsert_chapter_summary,
)
from .deepseek_client import ChatResult, DeepSeekClient
from .errors import ContractError
from .prompts import (
    ANTI_CLICHE_BANNED_PHRASES,
    SYSTEM_NOVELIST,
    blueprint_prompt,
    chapter_prompt,
    chapter_summary_prompt,
    concept_synthesis_prompt,
    continuity_prompt,
    expansion_prompt,
    next_chapter_prompt,
    planning_prompt,
    quality_review_prompt,
    quality_rewrite_prompt,
    tightening_prompt,
)
from .state import (
    chapter_filename,
    format_chapter_heading,
    merge_manuscript,
    merge_plain_manuscript,
    now_iso,
    parse_json_object,
    parse_json_array,
    plain_chapter_filename,
    read_json,
    slugify,
    to_plain_chapter,
    write_json,
    write_text,
)









DEFAULT_CHAPTER_COUNT = 1000
DEFAULT_WORDS_PER_CHAPTER = 5000
MIN_WORDS_PER_CHAPTER = 1000
MAX_WORDS_PER_CHAPTER = 20000
DEFAULT_MIN_QUALITY_SCORE = 88
DEFAULT_RECENT_CHAPTER_COUNT = 8

DEFAULT_PLAN_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS
DEFAULT_CHAPTER_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS
DEFAULT_REVIEW_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS
DEFAULT_SUMMARY_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS
DEFAULT_CONTINUITY_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS
DEFAULT_BLUEPRINT_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS
DEFAULT_CONCEPT_MAX_TOKENS = DEEPSEEK_OUTPUT_MAX_TOKENS

USER_DIRECTIONS_FILE = "user_directions.json"

WORD_COUNT_LOWER_RATIO = 0.85
WORD_COUNT_UPPER_RATIO = 1.15
MAX_EXPANSION_ATTEMPTS = 2
MAX_TIGHTENING_ATTEMPTS = 1


@dataclass(frozen=True)
class PipelineOptions:
    output_root: Path
    words_per_chapter: int = DEFAULT_WORDS_PER_CHAPTER
    plan_max_tokens: int = DEFAULT_PLAN_MAX_TOKENS
    chapter_max_tokens: int = DEFAULT_CHAPTER_MAX_TOKENS
    review_max_tokens: int = DEFAULT_REVIEW_MAX_TOKENS
    summary_max_tokens: int = DEFAULT_SUMMARY_MAX_TOKENS
    continuity_max_tokens: int = DEFAULT_CONTINUITY_MAX_TOKENS
    blueprint_max_tokens: int = DEFAULT_BLUEPRINT_MAX_TOKENS
    concept_max_tokens: int = DEFAULT_CONCEPT_MAX_TOKENS
    min_quality_score: int = DEFAULT_MIN_QUALITY_SCORE
    recent_chapter_count: int = DEFAULT_RECENT_CHAPTER_COUNT
    context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET
    overwrite_plan: bool = False
    overwrite_chapters: bool = False
    golden_chapter_count: int = 3
    golden_min_quality_score: int = 90
    promise_due_lookahead: int = 5
    cancel_check: Callable[[], bool] | None = None
    chapter_feedback_provider: Callable[[int, str], str | None] | None = None


    explicit_project_dir: Path | None = None





ProgressCallback = Callable[[str, dict[str, Any]], None]


def count_chinese_chars(text: str) -> int:
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    if cjk:
        return cjk
    return len(re.sub(r"\s+", "", text))


def count_anti_cliche_phrases(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for phrase in ANTI_CLICHE_BANNED_PHRASES:
        occurrence = text.count(phrase)
        if occurrence:
            counts[phrase] = occurrence
    return counts


class _StageReporter:

    def __init__(
        self,
        *,
        chapter_number: int,
        label: str,
        stage: str,
        progress: ProgressCallback | None,
        throttle_chars: int = 200,
    ) -> None:
        self._chapter_number = chapter_number
        self._label = label
        self._stage = stage
        self._progress = progress
        self._throttle = throttle_chars
        self._content_chars = 0
        self._reasoning_chars = 0
        self._reported_content = 0
        self._reported_reasoning = 0
        self._delta_buffer: list[str] = []

    def __call__(self, channel: str, piece: str) -> None:
        if channel == "content":
            self._content_chars += len(piece)
            self._delta_buffer.append(piece)
            if self._content_chars - self._reported_content >= self._throttle:
                self._emit()
        elif channel == "reasoning":
            self._reasoning_chars += len(piece)
            if self._reasoning_chars - self._reported_reasoning >= self._throttle:
                self._emit()

    def finish(self) -> None:
        if (
            self._content_chars != self._reported_content
            or self._reasoning_chars != self._reported_reasoning
        ):
            self._emit()

    def _emit(self) -> None:
        delta = "".join(self._delta_buffer)
        self._delta_buffer.clear()
        self._reported_content = self._content_chars
        self._reported_reasoning = self._reasoning_chars
        if self._progress is None:
            return
        self._progress(
            "stream",
            {
                "stage": self._stage,
                "label": self._label,
                "chapter": self._chapter_number,
                "content_chars": self._content_chars,
                "reasoning_chars": self._reasoning_chars,
                "content_delta": delta,
            },
        )


class CancelledError(Exception):
    pass


class NovelPipeline:
    def __init__(self, client: DeepSeekClient) -> None:
        self._client = client





    def synthesize_brief(
        self,
        *,
        tags: list[str],
        chapter_count: int,
        words_per_chapter: int,
        audience: str = "",
        requested_title: str = "",
        requested_synopsis: str = "",
        avoid_history: list[dict[str, Any]] | None = None,
        progress: ProgressCallback | None = None,
        max_tokens: int = DEFAULT_CONCEPT_MAX_TOKENS,
    ) -> dict[str, Any]:

        self._emit(progress, "concept", {"phase": "synthesizing", "tags": tags, "audience": audience})
        response = self._stream_json(
            stage="concept",
            label="concept-synthesis",
            chapter_number=0,
            prompt=concept_synthesis_prompt(
                tags=tags,
                chapter_count=chapter_count,
                words_per_chapter=words_per_chapter,
                audience=audience,
                requested_title=requested_title,
                requested_synopsis=requested_synopsis,
                avoid_history=avoid_history,
            ),
            max_tokens=max_tokens,
            progress=progress,
        )
        brief = parse_json_object(response.content)
        self._validate_synth_brief(
            brief,
            tags,
            chapter_count,
            audience=audience,
            requested_title=requested_title,
            requested_synopsis=requested_synopsis,
        )
        return brief

    def _validate_synth_brief(
        self,
        brief: dict[str, Any],
        tags: list[str],
        chapter_count: int,
        *,
        audience: str = "",
        requested_title: str = "",
        requested_synopsis: str = "",
    ) -> None:
        required = ["title", "premise"]
        missing = [key for key in required if not brief.get(key)]
        if missing:
            raise ContractError(f"自动 brief 缺少字段：{', '.join(missing)}")
        requested_title = requested_title.strip()
        requested_synopsis = requested_synopsis.strip()
        if requested_title:
            brief["title"] = requested_title
        if not brief.get("tags"):
            brief["tags"] = list(tags)
        brief["chapter_count"] = chapter_count
        if audience.strip():
            brief["audience"] = audience.strip()
        else:
            brief.setdefault("audience", "中国网络小说读者")
        brief.setdefault("must_have", [])
        brief.setdefault("avoid", [])
        brief.setdefault("commercial_goal", "黄金三章强钩子，章章有爽点和追读悬念，适合移动端连载。")
        synopsis = requested_synopsis or str(brief.get("synopsis") or "").strip()
        if not synopsis:
            raise ContractError("自动 brief 必须包含 500 字以内的 synopsis 字段。")

        cjk_chars = sum(1 for ch in synopsis if "\u4e00" <= ch <= "\u9fff") or len(synopsis)
        if cjk_chars > 525:
            raise ContractError(
                f"synopsis 字段超出 500 字硬上限（实际 {cjk_chars} 字）。"
            )
        if not requested_synopsis and cjk_chars < 150:
            raise ContractError(
                f"synopsis 字段过短（{cjk_chars} 字），至少需要 200 字才能有钩子价值。"
            )
        brief["synopsis"] = synopsis
        for key in ["first_three_chapters_outline", "chapter_outlines", "golden_three_chapters"]:
            brief.pop(key, None)





    def run(
        self,
        brief: dict[str, Any],
        options: PipelineOptions,
        progress: ProgressCallback | None = None,
    ) -> Path:
        self._validate_brief(brief)
        if options.explicit_project_dir is not None:
            project_dir = options.explicit_project_dir
        else:
            project_dir = self._project_dir(brief, options.output_root)
        project_dir.mkdir(parents=True, exist_ok=True)
        write_json(project_dir / "brief.json", brief)

        self._emit(progress, "ready", {"project_dir": str(project_dir)})
        expected_chapters = int(brief["chapter_count"])
        plan = self._load_or_create_plan(project_dir, brief, options, progress)
        continuity = self._load_continuity(project_dir)
        summaries = load_chapter_summaries(project_dir)
        completed = self._completed_chapters(project_dir)

        for chapter_number in range(1, expected_chapters + 1):
            self._raise_if_cancelled(options)
            user_directions = self._load_user_directions(project_dir)
            outline = self._load_or_create_chapter_plan(
                project_dir=project_dir,
                plan=plan,
                brief=brief,
                summaries=summaries,
                continuity=continuity,
                user_directions=user_directions,
                chapter_number=chapter_number,
                expected_chapters=expected_chapters,
                options=options,
                progress=progress,
            )
            title = str(outline["title"])
            chapter_path = project_dir / "chapters" / chapter_filename(chapter_number, title)
            if (
                chapter_number in completed
                and chapter_path.exists()
                and not options.overwrite_chapters
            ):
                self._emit(
                    progress,
                    "skipped",
                    {"chapter": chapter_number, "title": title},
                )
                continue

            previous_cliffhanger = self._previous_cliffhanger(summaries, chapter_number)
            context_pack = build_context_pack(
                project_dir=project_dir,
                brief=brief,
                plan=plan,
                chapter_outline=outline,
                continuity=continuity,
                chapter_summaries=summaries,
                all_outlines=[],
                recent_chapter_count=options.recent_chapter_count,
                user_directions=user_directions,
                context_token_budget=options.context_token_budget,
            )
            if previous_cliffhanger is not None:
                context_pack["previous_chapter_cliffhanger"] = previous_cliffhanger
            self._emit(
                progress,
                "chapter_start",
                {
                    "chapter": chapter_number,
                    "title": title,
                    "context_tokens": estimate_json_tokens(context_pack),
                    "total": expected_chapters,
                },
            )
            chapter_text = self._write_chapter(
                project_dir=project_dir,
                context_pack=context_pack,
                options=options,
                progress=progress,
                plan=plan,
            )
            write_text(
                chapter_path,
                f"# {format_chapter_heading(chapter_number, title)}\n\n{chapter_text}",
            )
            plain_path = (
                project_dir
                / "chapters_txt"
                / plain_chapter_filename(chapter_number, title)
            )
            write_text(plain_path, to_plain_chapter(chapter_number, title, chapter_text))
            self._write_chapter_meta(
                project_dir=project_dir,
                chapter_number=chapter_number,
                title=title,
                chapter_text=chapter_text,
                is_golden=chapter_number <= options.golden_chapter_count,
            )
            summaries = self._summarize_chapter(
                project_dir=project_dir,
                summaries=summaries,
                chapter_number=chapter_number,
                chapter_title=title,
                chapter_text=chapter_text,
                options=options,
                progress=progress,
            )
            continuity = self._update_continuity(
                project_dir=project_dir,
                continuity=continuity,
                chapter_number=chapter_number,
                chapter_title=title,
                chapter_text=chapter_text,
                options=options,
                progress=progress,
            )
            completed.add(chapter_number)
            self._write_state(project_dir, completed)
            self._write_manuscript(project_dir)
            self._write_plain_manuscript(project_dir)
            self._write_metadata(
                project_dir=project_dir,
                brief=brief,
                plan=plan,
                completed_chapters=completed,
                expected_chapters=expected_chapters,
            )
            self._emit(
                progress,
                "chapter_done",
                {
                    "chapter": chapter_number,
                    "title": title,
                    "chars": count_chinese_chars(chapter_text),
                    "completed": len(completed),
                    "total": expected_chapters,
                    "progress_percent": round(
                        len(completed) / expected_chapters * 100, 2
                    ),
                    "chapter_path": str(chapter_path),
                    "plain_path": str(plain_path),
                },
            )
            self._collect_user_direction(
                project_dir=project_dir,
                chapter_number=chapter_number,
                title=title,
                expected_chapters=expected_chapters,
                options=options,
                progress=progress,
            )

        self._emit(progress, "done", {"project_dir": str(project_dir)})
        return project_dir

    def _raise_if_cancelled(self, options: PipelineOptions) -> None:
        check = options.cancel_check
        if check is not None and check():
            raise CancelledError("任务被用户取消")





    def _load_or_create_plan(
        self,
        project_dir: Path,
        brief: dict[str, Any],
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> dict[str, Any]:
        plan_path = project_dir / "plan.json"
        if plan_path.exists() and not options.overwrite_plan:
            plan = self._sanitize_story_bible(read_json(plan_path))
            self._validate_plan_structure(plan)
            write_json(plan_path, plan)
            return plan

        self._emit(progress, "plan_start", {"max_tokens": options.plan_max_tokens})
        response = self._stream_json(
            stage="plan",
            label="plan",
            chapter_number=0,
            prompt=planning_prompt(brief),
            max_tokens=options.plan_max_tokens,
            progress=progress,
        )
        raw_path = project_dir / "raw" / "plan-response.json"
        write_json(raw_path, response.raw)
        self._record_api_result(project_dir, "plan", response, raw_path, progress)
        plan = self._sanitize_story_bible(parse_json_object(response.content))
        self._validate_plan_structure(plan)
        self._validate_plan(plan)
        write_json(plan_path, plan)
        return plan

    def _load_or_create_chapter_plan(
        self,
        *,
        project_dir: Path,
        plan: dict[str, Any],
        brief: dict[str, Any],
        summaries: list[dict[str, Any]],
        continuity: dict[str, Any],
        user_directions: list[dict[str, Any]],
        chapter_number: int,
        expected_chapters: int,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> dict[str, Any]:
        path = project_dir / "chapter_plans" / f"chapter-{chapter_number:04d}.json"
        if path.exists() and not options.overwrite_chapters:
            plan_item = read_json(path)
            return self._normalize_chapter_plan(plan_item, chapter_number)

        self._emit(progress, "chapter_plan", {"chapter": chapter_number})
        plan_summary = self._extract_plan_summary(plan)
        response = self._stream_json(
            stage="chapter_plan",
            label=f"chapter-{chapter_number:04d}-plan",
            chapter_number=chapter_number,
            prompt=next_chapter_prompt(
                brief=brief,
                plan_summary=plan_summary,
                chapter_number=chapter_number,
                total_chapters=expected_chapters,
                previous_summaries=summaries,
                continuity=continuity,
                user_directions=user_directions,
            ),
            max_tokens=options.plan_max_tokens,
            progress=progress,
        )
        raw_path = project_dir / "raw" / f"chapter-{chapter_number:04d}-plan.json"
        write_json(raw_path, response.raw)
        self._record_api_result(
            project_dir,
            f"chapter-{chapter_number:04d}-plan",
            response,
            raw_path,
            progress,
        )
        plan_item = self._normalize_chapter_plan(
            parse_json_object(response.content),
            chapter_number,
        )
        write_json(path, plan_item)
        return plan_item

    def _normalize_chapter_plan(
        self,
        item: dict[str, Any],
        chapter_number: int,
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise ContractError("Chapter plan must be an object.")
        item["chapter"] = chapter_number
        title = str(item.get("title") or "").strip()
        if not title:
            raise ContractError(f"Chapter plan {chapter_number} missing title.")
        item["title"] = title
        for key in ["pov", "purpose", "stakes", "payoff", "cliffhanger"]:
            item.setdefault(key, "")
        beats = item.get("beats")
        if not isinstance(beats, list):
            item["beats"] = []
        if not item.get("volume"):
            item["volume"] = 1
        return item

    def _load_user_directions(self, project_dir: Path) -> list[dict[str, Any]]:
        path = project_dir / USER_DIRECTIONS_FILE
        if not path.exists():
            return []
        parsed = parse_json_array(path.read_text(encoding="utf-8"))
        if not isinstance(parsed, list):
            raise ContractError(f"{USER_DIRECTIONS_FILE} must contain a JSON array.")
        return [item for item in parsed if isinstance(item, dict)]

    def _collect_user_direction(
        self,
        *,
        project_dir: Path,
        chapter_number: int,
        title: str,
        expected_chapters: int,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> None:
        provider = options.chapter_feedback_provider
        if provider is None or chapter_number >= expected_chapters:
            return
        self._emit(
            progress,
            "user_feedback",
            {"chapter": chapter_number, "title": title},
        )
        direction = provider(chapter_number, title)
        text = str(direction or "").strip()
        if not text:
            return
        directions = self._load_user_directions(project_dir)
        directions.append(
            {
                "after_chapter": chapter_number,
                "chapter_title": title,
                "direction": text,
                "created_at": now_iso(),
            }
        )
        write_json(project_dir / USER_DIRECTIONS_FILE, directions)





    def _write_chapter(
        self,
        *,
        project_dir: Path,
        context_pack: dict[str, Any],
        options: PipelineOptions,
        progress: ProgressCallback | None,
        plan: dict[str, Any],
    ) -> str:
        outline = context_pack["current_chapter"]
        chapter_number = int(outline["chapter"])
        is_golden = chapter_number <= options.golden_chapter_count

        min_quality_score = (
            max(options.min_quality_score, options.golden_min_quality_score)
            if is_golden
            else options.min_quality_score
        )

        due_promises = self._collect_due_promises(
            continuity=context_pack.get("continuity_memory") or {},
            current_chapter=chapter_number,
            lookahead=options.promise_due_lookahead,
        )
        pacing_phase = self._find_pacing_phase(plan, chapter_number)

        blueprint = self._load_or_create_blueprint(
            project_dir=project_dir,
            context_pack=context_pack,
            chapter_number=chapter_number,
            options=options,
            progress=progress,
        )
        self._emit(
            progress,
            "draft_start",
            {
                "chapter": chapter_number,
                "is_golden": is_golden,
                "due_promises": len(due_promises),
                "pacing_tempo": (pacing_phase or {}).get("tempo"),
            },
        )
        text = self._stream_chapter(
            project_dir=project_dir,
            chapter_number=chapter_number,
            label=f"chapter-{chapter_number:04d}-draft",
            stage="chapter",
            prompt=chapter_prompt(
                context_pack=context_pack,
                blueprint=blueprint,
                words_per_chapter=options.words_per_chapter,
                is_golden=is_golden,
                due_promises=due_promises,
                pacing_phase=pacing_phase,
            ),
            options=options,
            progress=progress,
        )

        text = self._enforce_word_count(
            project_dir=project_dir,
            context_pack=context_pack,
            blueprint=blueprint,
            chapter_number=chapter_number,
            text=text,
            options=options,
            progress=progress,
        )

        quality_index = 1
        while True:
            self._raise_if_cancelled(options)
            self._emit(
                progress,
                "quality_review",
                {
                    "chapter": chapter_number,
                    "pass": quality_index,
                    "min_score": min_quality_score,
                },
            )
            review = self._review_chapter(
                project_dir=project_dir,
                context_pack=context_pack,
                blueprint=blueprint,
                chapter_number=chapter_number,
                chapter_text=text,
                quality_index=quality_index,
                options=options,
                progress=progress,
            )
            score = int(review.get("overall_score") or 0)
            if (
                score >= min_quality_score
                and not review.get("fatal_issues")
            ):
                self._emit(
                    progress,
                    "quality_pass",
                    {"chapter": chapter_number, "score": score},
                )
                break
            self._emit(
                progress,
                "quality_rewrite",
                {"chapter": chapter_number, "score": score},
            )
            text = self._stream_chapter(
                project_dir=project_dir,
                chapter_number=chapter_number,
                label=f"chapter-{chapter_number:04d}-quality-rewrite-{quality_index}",
                stage="quality_rewrite",
                prompt=quality_rewrite_prompt(
                    context_pack=context_pack,
                    blueprint=blueprint,
                    review=review,
                    chapter_text=text,
                    words_per_chapter=options.words_per_chapter,
                ),
                options=options,
                progress=progress,
            )
            text = self._enforce_word_count(
                project_dir=project_dir,
                context_pack=context_pack,
                blueprint=blueprint,
                chapter_number=chapter_number,
                text=text,
                options=options,
                progress=progress,
                label_suffix=f"-after-quality-{quality_index}",
            )
            quality_index += 1

        return text





    def _collect_due_promises(
        self,
        *,
        continuity: dict[str, Any],
        current_chapter: int,
        lookahead: int,
    ) -> list[dict[str, Any]]:
        promises = continuity.get("promises_to_payoff")
        if not isinstance(promises, list):
            return []
        due: list[dict[str, Any]] = []
        for entry in promises:
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status") or "pending").lower()
            if status == "done":
                continue
            deadline = entry.get("deadline_chapter")
            if not isinstance(deadline, int):
                continue
            if deadline <= current_chapter + lookahead:
                due.append(entry)
        return due

    def _find_pacing_phase(
        self,
        plan: dict[str, Any],
        chapter_number: int,
    ) -> dict[str, Any] | None:
        pacing = plan.get("pacing_curve")
        if not isinstance(pacing, list):
            return None
        for phase in pacing:
            if not isinstance(phase, dict):
                continue
            chapter_range = str(phase.get("chapter_range") or "")
            if not chapter_range:
                continue
            match = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", chapter_range)
            if not match:
                continue
            start = int(match.group(1))
            end = int(match.group(2))
            if start <= chapter_number <= end:
                return phase
        return None

    def _previous_cliffhanger(
        self,
        summaries: list[dict[str, Any]],
        current_chapter: int,
    ) -> dict[str, Any] | None:
        if current_chapter <= 1:
            return None
        previous_chapter = current_chapter - 1
        for item in summaries:
            if int(item.get("chapter", 0)) == previous_chapter:
                hook = (
                    item.get("next_chapter_pressure")
                    or item.get("open_hooks")
                    or item.get("summary")
                )
                if not hook:
                    return None
                return {
                    "previous_chapter": previous_chapter,
                    "previous_title": item.get("title"),
                    "open_hooks": item.get("open_hooks") or [],
                    "next_chapter_pressure": item.get("next_chapter_pressure") or "",
                }
        return None

    def _stream_chapter(
        self,
        *,
        project_dir: Path,
        chapter_number: int,
        label: str,
        stage: str,
        prompt: str,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> str:
        self._raise_if_cancelled(options)
        reporter = _StageReporter(
            chapter_number=chapter_number,
            label=label,
            stage=stage,
            progress=progress,
        )
        response = self._client.chat_stream(
            [
                {"role": "system", "content": SYSTEM_NOVELIST},
                {"role": "user", "content": prompt},
            ],
            max_tokens=options.chapter_max_tokens,
            on_token=reporter,
        )
        reporter.finish()
        raw_path = project_dir / "raw" / f"{label}.json"
        write_json(raw_path, response.raw)
        self._record_api_result(project_dir, label, response, raw_path, progress)
        return response.content.strip()

    def _stream_json(
        self,
        *,
        stage: str,
        label: str,
        chapter_number: int,
        prompt: str,
        max_tokens: int,
        progress: ProgressCallback | None,
    ) -> ChatResult:
        reporter = _StageReporter(
            chapter_number=chapter_number,
            label=label,
            stage=stage,
            progress=progress,
        )
        response = self._client.chat_stream(
            [
                {"role": "system", "content": SYSTEM_NOVELIST},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            on_token=reporter,
            json_mode=True,
        )
        reporter.finish()
        return response

    def _enforce_word_count(
        self,
        *,
        project_dir: Path,
        context_pack: dict[str, Any],
        blueprint: dict[str, Any],
        chapter_number: int,
        text: str,
        options: PipelineOptions,
        progress: ProgressCallback | None,
        label_suffix: str = "",
    ) -> str:
        target = options.words_per_chapter
        lower = int(target * WORD_COUNT_LOWER_RATIO)
        upper = int(target * WORD_COUNT_UPPER_RATIO)

        for attempt in range(1, MAX_EXPANSION_ATTEMPTS + 1):
            actual = count_chinese_chars(text)
            if actual >= lower:
                break
            self._emit(
                progress,
                "expansion",
                {
                    "chapter": chapter_number,
                    "actual": actual,
                    "target": target,
                    "attempt": attempt,
                },
            )
            text = self._stream_chapter(
                project_dir=project_dir,
                chapter_number=chapter_number,
                label=(
                    f"chapter-{chapter_number:04d}-expansion-{attempt}{label_suffix}"
                ),
                stage="expansion",
                prompt=expansion_prompt(
                    context_pack=context_pack,
                    blueprint=blueprint,
                    draft=text,
                    target_words=target,
                    actual_words=actual,
                ),
                options=options,
                progress=progress,
            )

        for attempt in range(1, MAX_TIGHTENING_ATTEMPTS + 1):
            actual = count_chinese_chars(text)
            if actual <= upper:
                break
            self._emit(
                progress,
                "tightening",
                {
                    "chapter": chapter_number,
                    "actual": actual,
                    "target": target,
                    "attempt": attempt,
                },
            )
            text = self._stream_chapter(
                project_dir=project_dir,
                chapter_number=chapter_number,
                label=(
                    f"chapter-{chapter_number:04d}-tightening-{attempt}{label_suffix}"
                ),
                stage="tightening",
                prompt=tightening_prompt(
                    context_pack=context_pack,
                    blueprint=blueprint,
                    draft=text,
                    target_words=target,
                    actual_words=actual,
                ),
                options=options,
                progress=progress,
            )

        return text

    def _load_or_create_blueprint(
        self,
        *,
        project_dir: Path,
        context_pack: dict[str, Any],
        chapter_number: int,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> dict[str, Any]:
        path = project_dir / "blueprints" / f"chapter-{chapter_number:04d}.json"
        if path.exists() and not options.overwrite_chapters:
            return read_json(path)

        self._emit(progress, "blueprint", {"chapter": chapter_number})
        response = self._stream_json(
            stage="blueprint",
            label=f"chapter-{chapter_number:04d}-blueprint",
            chapter_number=chapter_number,
            prompt=blueprint_prompt(
                context_pack=context_pack,
                words_per_chapter=options.words_per_chapter,
            ),
            max_tokens=options.blueprint_max_tokens,
            progress=progress,
        )
        raw_path = project_dir / "raw" / f"chapter-{chapter_number:04d}-blueprint.json"
        write_json(raw_path, response.raw)
        self._record_api_result(
            project_dir,
            f"chapter-{chapter_number:04d}-blueprint",
            response,
            raw_path,
            progress,
        )
        blueprint = parse_json_object(response.content)
        write_json(path, blueprint)
        return blueprint

    def _review_chapter(
        self,
        *,
        project_dir: Path,
        context_pack: dict[str, Any],
        blueprint: dict[str, Any],
        chapter_number: int,
        chapter_text: str,
        quality_index: int,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> dict[str, Any]:
        response = self._stream_json(
            stage="quality_review",
            label=f"chapter-{chapter_number:04d}-quality-review-{quality_index}",
            chapter_number=chapter_number,
            prompt=quality_review_prompt(
                context_pack=context_pack,
                blueprint=blueprint,
                chapter_text=chapter_text,
            ),
            max_tokens=options.review_max_tokens,
            progress=progress,
        )
        raw_path = (
            project_dir
            / "raw"
            / f"chapter-{chapter_number:04d}-quality-review-{quality_index}.json"
        )
        write_json(raw_path, response.raw)
        self._record_api_result(
            project_dir,
            f"chapter-{chapter_number:04d}-quality-review-{quality_index}",
            response,
            raw_path,
            progress,
        )
        review = parse_json_object(response.content)
        if "overall_score" not in review:
            raise ContractError("Quality review missing overall_score.")

        cliche_counts = count_anti_cliche_phrases(chapter_text)
        if cliche_counts:
            review.setdefault("auto_detected_cliche_counts", cliche_counts)
            existing = review.get("cliche_detected") or []
            if isinstance(existing, list):
                merged = set(existing) | set(cliche_counts.keys())
                review["cliche_detected"] = sorted(merged)
        write_json(
            project_dir
            / "reviews"
            / f"chapter-{chapter_number:04d}-review-{quality_index}.json",
            review,
        )
        return review

    def _update_continuity(
        self,
        *,
        project_dir: Path,
        continuity: dict[str, Any],
        chapter_number: int,
        chapter_title: str,
        chapter_text: str,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> dict[str, Any]:
        response = self._stream_json(
            stage="continuity",
            label=f"chapter-{chapter_number:04d}-continuity",
            chapter_number=chapter_number,
            prompt=continuity_prompt(
                existing_continuity=continuity,
                chapter_number=chapter_number,
                chapter_title=chapter_title,
                chapter_text=chapter_text,
            ),
            max_tokens=options.continuity_max_tokens,
            progress=progress,
        )
        raw_path = project_dir / "raw" / f"continuity-{chapter_number:04d}.json"
        write_json(raw_path, response.raw)
        self._record_api_result(
            project_dir,
            f"chapter-{chapter_number:04d}-continuity",
            response,
            raw_path,
            progress,
        )
        updated = parse_json_object(response.content)
        write_json(project_dir / "continuity.json", updated)
        return updated

    def _summarize_chapter(
        self,
        *,
        project_dir: Path,
        summaries: list[dict[str, Any]],
        chapter_number: int,
        chapter_title: str,
        chapter_text: str,
        options: PipelineOptions,
        progress: ProgressCallback | None,
    ) -> list[dict[str, Any]]:
        self._emit(progress, "summary", {"chapter": chapter_number})
        response = self._stream_json(
            stage="summary",
            label=f"chapter-{chapter_number:04d}-summary",
            chapter_number=chapter_number,
            prompt=chapter_summary_prompt(
                chapter_number=chapter_number,
                chapter_title=chapter_title,
                chapter_text=chapter_text,
            ),
            max_tokens=options.summary_max_tokens,
            progress=progress,
        )
        raw_path = project_dir / "raw" / f"chapter-{chapter_number:04d}-summary.json"
        write_json(raw_path, response.raw)
        self._record_api_result(
            project_dir,
            f"chapter-{chapter_number:04d}-summary",
            response,
            raw_path,
            progress,
        )
        summary = parse_json_object(response.content)
        summary["chapter"] = chapter_number
        summary.setdefault("title", chapter_title)
        updated = upsert_chapter_summary(summaries, summary)
        save_chapter_summaries(project_dir, updated)
        return updated

    def _load_continuity(self, project_dir: Path) -> dict[str, Any]:
        path = project_dir / "continuity.json"
        if path.exists():
            return read_json(path)
        continuity = {
            "latest_chapter": 0,
            "timeline": [],
            "character_state": {},
            "world_facts": [],
            "open_threads": [],
            "promises_to_payoff": [],
            "style_notes": [],
        }
        write_json(path, continuity)
        return continuity

    def _completed_chapters(self, project_dir: Path) -> set[int]:
        state_path = project_dir / "state.json"
        if not state_path.exists():
            return set()
        state = read_json(state_path)
        chapters = state.get("completed_chapters", [])
        if not isinstance(chapters, list):
            raise ContractError("state.completed_chapters must be a list.")
        return {int(value) for value in chapters}

    def _write_state(self, project_dir: Path, completed: set[int]) -> None:
        write_json(
            project_dir / "state.json",
            {
                "updated_at": now_iso(),
                "completed_chapters": sorted(completed),
            },
        )

    def _write_manuscript(self, project_dir: Path) -> None:
        chapter_paths = sorted((project_dir / "chapters").glob("*.md"))
        if chapter_paths:
            write_text(project_dir / "manuscript.md", merge_manuscript(chapter_paths))

    def _write_plain_manuscript(self, project_dir: Path) -> None:
        plain_paths = sorted((project_dir / "chapters_txt").glob("*.txt"))
        if plain_paths:
            write_text(
                project_dir / "manuscript.txt",
                merge_plain_manuscript(plain_paths),
            )

    def _write_chapter_meta(
        self,
        *,
        project_dir: Path,
        chapter_number: int,
        title: str,
        chapter_text: str,
        is_golden: bool,
    ) -> None:
        meta_path = (
            project_dir
            / "chapters_meta"
            / f"chapter-{chapter_number:04d}.json"
        )
        write_json(
            meta_path,
            {
                "chapter": chapter_number,
                "title": title,
                "heading": format_chapter_heading(chapter_number, title),
                "char_count": count_chinese_chars(chapter_text),
                "byte_count": len(chapter_text.encode("utf-8")),
                "is_golden": is_golden,
                "updated_at": now_iso(),
            },
        )

    def _write_metadata(
        self,
        *,
        project_dir: Path,
        brief: dict[str, Any],
        plan: dict[str, Any],
        completed_chapters: set[int],
        expected_chapters: int,
    ) -> None:
        chapters_dir = project_dir / "chapters"
        total_chars = 0
        chapter_index: list[dict[str, Any]] = []
        for path in sorted(chapters_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            count = count_chinese_chars(text)
            total_chars += count
            chapter_index.append({"filename": path.name, "char_count": count})

        usage = self._aggregate_usage(project_dir)
        metadata = {
            "title": str(brief.get("title") or ""),
            "tags": brief.get("tags") or [],
            "audience": brief.get("audience"),
            "premise": brief.get("premise"),
            "completed_chapters": sorted(completed_chapters),
            "expected_chapters": expected_chapters,
            "progress_percent": round(
                len(completed_chapters) / expected_chapters * 100, 2
            )
            if expected_chapters
            else 0.0,
            "total_chars": total_chars,
            "plan_logline": plan.get("logline"),
            "plan_core_hook": plan.get("core_hook"),
            "plan_innovation": plan.get("innovation"),
            "engine_version": __version__,
            "updated_at": now_iso(),
            "usage": usage,
            "chapter_index": chapter_index,
        }
        write_json(project_dir / "metadata.json", metadata)

    def _aggregate_usage(self, project_dir: Path) -> dict[str, Any]:
        usage_path = project_dir / "usage.jsonl"
        totals = {
            "api_calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cache_hit_tokens": 0,
            "cache_miss_tokens": 0,
        }
        if not usage_path.exists():
            return totals
        for line in usage_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            usage = entry.get("usage") or {}
            totals["api_calls"] += 1
            totals["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            totals["completion_tokens"] += int(usage.get("completion_tokens") or 0)
            totals["reasoning_tokens"] += int(entry.get("reasoning_tokens") or 0)
            totals["cache_hit_tokens"] += int(usage.get("prompt_cache_hit_tokens") or 0)
            totals["cache_miss_tokens"] += int(usage.get("prompt_cache_miss_tokens") or 0)
        return totals

    def _project_dir(self, brief: dict[str, Any], output_root: Path) -> Path:
        title = str(brief.get("title") or "未命名小说")
        return output_root / slugify(title)

    def _sanitize_story_bible(self, value: dict[str, Any]) -> dict[str, Any]:
        blocked = {
            "chapter_outlines",
            "golden_three_chapters",
            "first_three_chapters_outline",
            "volume_arcs",
            "pacing_curve",
            "chapter_range",
            "payoff_chapter",
            "monetization_chapters",
            "golden_three_mission",
        }

        def clean(item: Any) -> Any:
            if isinstance(item, dict):
                return {
                    key: clean(child)
                    for key, child in item.items()
                    if key not in blocked
                }
            if isinstance(item, list):
                return [clean(child) for child in item]
            return item

        cleaned = clean(value)
        if not isinstance(cleaned, dict):
            raise ContractError("Plan must be a JSON object.")
        return cleaned

    def _validate_brief(self, brief: dict[str, Any]) -> None:
        required = ["title", "tags", "chapter_count", "premise"]
        missing = [key for key in required if key not in brief]
        if missing:
            raise ContractError(f"Brief missing required fields: {', '.join(missing)}")
        if int(brief["chapter_count"]) < 1:
            raise ContractError("brief.chapter_count must be at least 1.")

    def _validate_plan_structure(self, plan: dict[str, Any]) -> None:
        required = [
            "title",
            "logline",
            "reader_promise",
            "core_hook",
            "style_bible",
        ]
        missing = [key for key in required if key not in plan]
        if missing:
            raise ContractError(f"Plan missing required fields: {', '.join(missing)}")

    def _validate_plan(self, plan: dict[str, Any]) -> None:
        self._validate_plan_structure(plan)

    def _extract_plan_summary(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            key: plan[key]
            for key in [
                "title", "logline", "reader_promise", "core_hook", "innovation",
                "protagonist", "main_cast", "opposition_design",
                "world", "long_arc", "style_bible", "anti_cliche",
                "reader_retention_design",
            ]
            if key in plan
        }

    def _emit(
        self,
        progress: ProgressCallback | None,
        stage: str,
        payload: dict[str, Any],
    ) -> None:
        if progress is not None:
            progress(stage, payload)

    def _record_api_result(
        self,
        project_dir: Path,
        label: str,
        response: ChatResult,
        raw_path: Path,
        progress: ProgressCallback | None,
    ) -> None:
        usage_path = project_dir / "usage.jsonl"
        usage_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "label": label,
            "finish_reason": response.finish_reason,
            "usage": response.usage,
            "reasoning_tokens": response.reasoning_tokens,
            "raw_path": str(raw_path),
            "preview": self._preview(response.content),
        }
        with usage_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._emit(
            progress,
            "api",
            {
                "label": label,
                "finish_reason": response.finish_reason,
                "prompt_tokens": response.usage.get("prompt_tokens"),
                "completion_tokens": response.usage.get("completion_tokens"),
                "reasoning_tokens": response.reasoning_tokens,
                "total_tokens": response.usage.get("total_tokens"),
                "cache_hit_tokens": response.cache_hit_tokens,
                "cache_miss_tokens": response.cache_miss_tokens,
                "raw_path": str(raw_path),
                "preview": self._preview(response.content),
            },
        )

    def _preview(self, text: str, limit: int = 420) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        if len(compact) <= limit:
            return compact
        return compact[:limit] + "..."






def collect_avoid_history(projects_dir: Path) -> list[dict[str, Any]]:

    if not projects_dir.exists():
        return []

    history: list[dict[str, Any]] = []
    for child in sorted(projects_dir.iterdir()):
        if not child.is_dir():
            continue
        plan_path = child / "plan.json"
        brief_path = child / "brief.json"
        if not (plan_path.exists() or brief_path.exists()):
            continue

        plan = read_json(plan_path) if plan_path.exists() else {}
        brief = read_json(brief_path) if brief_path.exists() else {}
        protagonist = plan.get("protagonist") or {}
        world = plan.get("world") or {}
        long_arc = plan.get("long_arc") or {}
        golden = plan.get("golden_three_chapters") or []
        first_golden = golden[0] if golden and isinstance(golden, list) else {}
        history.append(
            {
                "title": brief.get("title") or plan.get("title") or child.name,
                "tags": brief.get("tags") or [],
                "premise": brief.get("premise"),
                "innovation": plan.get("innovation"),
                "protagonist_edge": protagonist.get("edge"),
                "power_system": world.get("power_system"),
                "system_level_secret": long_arc.get("system_level_secret"),
                "first_chapter_core_event": first_golden.get("core_event")
                if isinstance(first_golden, dict)
                else None,
            }
        )
    return history


def load_brief_file(path: Path) -> dict[str, Any]:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ContractError("Brief file must contain a JSON object.")
    return parsed
