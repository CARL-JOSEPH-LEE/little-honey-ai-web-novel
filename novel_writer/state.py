
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import ContractError


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str, *, fallback: str = "novel") -> str:
    text = value.strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff_-]+", "", text)
    text = text.strip("-_")
    if text:
        return text[:80]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"{fallback}-{digest}"


def read_json(path: Path) -> dict[str, Any]:
    try:
        return parse_json_object(path.read_text(encoding="utf-8"))
    except ContractError as exc:
        raise ContractError(f"JSON 文件格式错误：{path}；{exc}") from exc


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def parse_json_object(text: str) -> dict[str, Any]:
    parsed = parse_json_value(text, expected_type=dict)
    return parsed


def parse_json_array(text: str) -> list[Any]:
    parsed = parse_json_value(text, expected_type=list)
    return parsed


def parse_json_value(text: str, *, expected_type: type) -> Any:
    cleaned = _strip_json_wrapping(text)
    candidates = [cleaned]
    extracted = _extract_json_candidate(cleaned)
    if extracted and extracted not in candidates:
        candidates.append(extracted)
    repaired_candidates = []
    for candidate in candidates:
        repaired = _repair_json_text(candidate)
        if repaired not in candidates and repaired not in repaired_candidates:
            repaired_candidates.append(repaired)
    candidates.extend(repaired_candidates)
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            continue
        if not isinstance(parsed, expected_type):
            name = "对象" if expected_type is dict else "数组"
            raise ContractError(f"模型 JSON 输出顶层必须是{name}。")
        return parsed
    if last_error is None:
        raise ContractError("模型未输出 JSON。")
    raise ContractError(_format_json_error(last_error, candidates[-1]))


def _strip_json_wrapping(text: str) -> str:
    cleaned = text.strip().lstrip("\ufeff")
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|JSON)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _extract_json_candidate(text: str) -> str:
    starts = [(idx, ch) for idx, ch in enumerate(text) if ch in "{["]
    pairs = {"{": "}", "[": "]"}
    for start, opener in starts:
        closer = pairs[opener]
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1].strip()
    return ""


def _repair_json_text(text: str) -> str:
    repaired = text.strip()
    repaired = repaired.replace("“", '"').replace("”", '"')
    repaired = repaired.replace("‘", "'").replace("’", "'")
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r'(?<=[}\]"0-9])(\s*\n\s*)(?="[^"\n]+"\s*:)', r",\1", repaired)
    repaired = re.sub(r"\b(true|false|null)(\s*\n\s*)(?=\"[^\"\n]+\"\s*:)", r"\1,\2", repaired)
    repaired = re.sub(r"([{\[,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)", r'\1"\2"\3', repaired)
    return repaired


def _format_json_error(error: json.JSONDecodeError, text: str) -> str:
    lines = text.splitlines()
    start = max(0, error.lineno - 2)
    end = min(len(lines), error.lineno + 1)
    snippet = "\n".join(lines[start:end])[:500]
    return (
        f"模型返回的 JSON 格式不完整，位置：第 {error.lineno} 行第 {error.colno} 列。"
        f"常见原因是模型漏了逗号、引号或括号。片段：{snippet}"
    )


def chapter_filename(number: int, title: str) -> str:
    return f"{number:04d}-{slugify(title, fallback='chapter')}.md"


def plain_chapter_filename(number: int, title: str) -> str:
    return f"{number:04d}-{slugify(title, fallback='chapter')}.txt"


def merge_manuscript(chapter_paths: list[Path]) -> str:
    sections: list[str] = []
    for path in chapter_paths:
        sections.append(path.read_text(encoding="utf-8").strip())
    return "\n\n".join(sections).strip() + "\n"


def to_plain_chapter(chapter_number: int, chapter_title: str, body: str) -> str:
    cleaned = re.sub(r"^\s*#+\s*.*$", "", body, flags=re.MULTILINE)
    cleaned = re.sub(r"```[a-zA-Z0-9_]*\n", "", cleaned)
    cleaned = cleaned.replace("```", "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    heading = format_chapter_heading(chapter_number, chapter_title)
    return f"{heading}\n\n{cleaned}\n"


def format_chapter_heading(chapter_number: int, title: str) -> str:
    normalized = title.strip()
    if re.match(rf"^第\s*{chapter_number}\s*[章节回卷部]", normalized):
        return normalized
    return f"第{chapter_number}章 {normalized}"


def merge_plain_manuscript(plain_chapter_paths: list[Path]) -> str:
    sections: list[str] = []
    for path in plain_chapter_paths:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            sections.append(text)
    return "\n\n".join(sections).rstrip() + "\n"


