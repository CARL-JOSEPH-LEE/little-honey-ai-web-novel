
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_REASONING_EFFORT = "high"
DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_RETRIES = 5

DEFAULT_INPUT_TOKEN_LIMIT = 800_000
DEFAULT_OUTPUT_TOKEN_LIMIT = 200_000
INPUT_TOKEN_SAFETY_MARGIN = 10_000
DEEPSEEK_OUTPUT_MAX_TOKENS = DEFAULT_OUTPUT_TOKEN_LIMIT
DEEPSEEK_CONTEXT_MAX_TOKENS = 1_000_000
DEEPSEEK_CONTEXT_SAFE_TOKENS = DEFAULT_INPUT_TOKEN_LIMIT - INPUT_TOKEN_SAFETY_MARGIN
DEFAULT_CONTEXT_TOKEN_BUDGET = DEEPSEEK_CONTEXT_SAFE_TOKENS


@dataclass(frozen=True)
class DeepSeekConfig:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    thinking_enabled: bool = True
    request_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = DEFAULT_MAX_RETRIES


def load_api_key(api_key_file: Path | None = None) -> str:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key

    if api_key_file is not None:
        text = api_key_file.read_text(encoding="utf-8").strip()
        if text:
            return text

    raise RuntimeError(
        "DeepSeek API key 未找到。请在 GUI 的设置页输入 Key，或设置环境变量 DEEPSEEK_API_KEY。"
    )
