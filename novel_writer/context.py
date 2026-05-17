
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_CONTEXT_TOKEN_BUDGET
from .errors import ContractError
from .state import parse_json_array


SUMMARY_FILE = "chapter_summaries.json"


def load_chapter_summaries(project_dir: Path) -> list[dict[str, Any]]:
    path = project_dir / SUMMARY_FILE
    if not path.exists():
        return []
    parsed = parse_json_array(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, list):
        raise ContractError(f"{SUMMARY_FILE} must contain a JSON array.")
    summaries: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            raise ContractError(f"Every item in {SUMMARY_FILE} must be an object.")
        summaries.append(item)
    return summaries


def save_chapter_summaries(project_dir: Path, summaries: list[dict[str, Any]]) -> None:
    path = project_dir / SUMMARY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def upsert_chapter_summary(
    summaries: list[dict[str, Any]], summary: dict[str, Any]
) -> list[dict[str, Any]]:
    chapter = int(summary["chapter"])
    kept = [item for item in summaries if int(item.get("chapter", 0)) != chapter]
    kept.append(summary)
    kept.sort(key=lambda item: int(item.get("chapter", 0)))
    return kept


def estimate_tokens(text: str) -> int:
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_cjk = len(text) - cjk
    return int(cjk * 0.6 + non_cjk * 0.35) + 1


def estimate_json_tokens(value: Any) -> int:
    return estimate_tokens(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def build_context_pack(
    *,
    project_dir: Path,
    brief: dict[str, Any],
    plan: dict[str, Any],
    chapter_outline: dict[str, Any],
    continuity: dict[str, Any],
    chapter_summaries: list[dict[str, Any]],
    all_outlines: list[dict[str, Any]],
    recent_chapter_count: int,
    user_directions: list[dict[str, Any]] | None = None,
    context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
) -> dict[str, Any]:
    chapter_number = int(chapter_outline["chapter"])
    previous_summaries_all = [
        item
        for item in chapter_summaries
        if int(item.get("chapter", 0)) < chapter_number
    ]
    previous_summaries = [
        item
        for item in previous_summaries_all
    ][-recent_chapter_count:]
    upcoming_outlines = [
        item
        for item in all_outlines
        if chapter_number < int(item.get("chapter", 0)) <= chapter_number + 2
    ]

    context = {
        "brief": brief,
        "story_bible": {
            "title": plan.get("title"),
            "logline": plan.get("logline"),
            "reader_promise": plan.get("reader_promise", []),
            "core_hook": plan.get("core_hook"),
            "innovation": plan.get("innovation"),
            "world": plan.get("world", {}),
            "protagonist": plan.get("protagonist", {}),
            "main_cast": plan.get("main_cast", []),
            "long_arc": plan.get("long_arc", {}),
            "style_bible": plan.get("style_bible", {}),
        },
        "current_chapter": chapter_outline,
        "all_previous_chapter_summaries": previous_summaries_all,
        "recent_chapter_summaries": previous_summaries,
        "continuity_memory": continuity,
        "user_directions": user_directions or [],
        "upcoming_outlines": upcoming_outlines,
        "previous_full_chapters": [],
        "context_budget": {
            "target_tokens": context_token_budget,
            "strategy": (
                "在用户设置的输入 token 安全预算内优先保留稳定故事圣经、全量章节摘要、连续性记忆、"
                "当前章蓝图所需信息，然后从最近章节向前尽量加入完整正文。"
            ),
        },
        "quality_targets": {
            "opening": "开篇三百字内必须出现危险、冲突、奇观或不可逆选择。",
            "mobile_reading": "段落短、句群清晰、每屏都有动作、情绪或信息变化。",
            "progression": "本章必须推进主角目标、世界秘密和读者承诺中的至少两项。",
            "payoff": "兑现本章大纲的 payoff，同时保留下一章点击欲。",
            "originality": "使用用户标签，但避免陈旧桥段照搬。",
            "long_form": "以百万字长篇为目标，当前章既要独立好看，也要服务卷级矛盾和长期追读。",
        },
    }
    context["previous_full_chapters"] = _pack_previous_chapters(
        project_dir=project_dir,
        context=context,
        current_chapter=chapter_number,
        token_budget=context_token_budget,
    )
    context["context_budget"]["estimated_tokens"] = estimate_json_tokens(context)
    return context


def _pack_previous_chapters(
    *,
    project_dir: Path,
    context: dict[str, Any],
    current_chapter: int,
    token_budget: int,
) -> list[dict[str, Any]]:
    base_tokens = estimate_json_tokens(context)
    remaining = token_budget - base_tokens
    if remaining <= 0:
        return []

    chapter_dir = project_dir / "chapters"
    if not chapter_dir.exists():
        return []

    packed: list[dict[str, Any]] = []
    for path in sorted(chapter_dir.glob("*.md"), reverse=True):
        chapter_number = _chapter_number_from_path(path)
        if chapter_number >= current_chapter:
            continue
        text = path.read_text(encoding="utf-8")
        item = {"chapter": chapter_number, "path": str(path), "text": text}
        cost = estimate_json_tokens(item)
        if cost > remaining:
            continue
        packed.append(item)
        remaining -= cost

    packed.sort(key=lambda item: int(item["chapter"]))
    return packed


def _chapter_number_from_path(path: Path) -> int:
    prefix = path.name.split("-", 1)[0]
    if not prefix.isdigit():
        raise ContractError(f"Chapter filename must start with a number: {path}")
    return int(prefix)
