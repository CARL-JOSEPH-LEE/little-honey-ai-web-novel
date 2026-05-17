
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .config import DeepSeekConfig
from .errors import DeepSeekAPIError


TokenCallback = Callable[[str, str], None]


@dataclass(frozen=True)
class ChatResult:
    content: str
    reasoning_content: str | None
    finish_reason: str
    usage: dict[str, Any]
    raw: dict[str, Any]

    @property
    def reasoning_tokens(self) -> int:
        details = self.usage.get("completion_tokens_details")
        if isinstance(details, dict):
            value = details.get("reasoning_tokens")
            if isinstance(value, int):
                return value
        return 0

    @property
    def cache_hit_tokens(self) -> int:
        value = self.usage.get("prompt_cache_hit_tokens")
        return int(value) if isinstance(value, int) else 0

    @property
    def cache_miss_tokens(self) -> int:
        value = self.usage.get("prompt_cache_miss_tokens")
        return int(value) if isinstance(value, int) else 0


class DeepSeekClient:

    _RETRYABLE_HTTP = {408, 409, 425, 429, 500, 502, 503, 504}

    def __init__(self, config: DeepSeekConfig) -> None:
        self._config = config
        self._endpoint = f"{config.base_url}/chat/completions"

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        json_mode: bool = False,
        temperature: float | None = None,
        on_token: TokenCallback | None = None,
    ) -> ChatResult:

        return self.chat_stream(
            messages,
            max_tokens=max_tokens,
            on_token=on_token,
            json_mode=json_mode,
            temperature=temperature,
        )

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        on_token: TokenCallback | None = None,
        json_mode: bool = False,
        temperature: float | None = None,
    ) -> ChatResult:

        payload = self._build_payload(
            messages=messages,
            max_tokens=max_tokens,
            json_mode=json_mode,
            temperature=temperature,
        )
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

        last_error: Exception | None = None
        for attempt in range(1, self._config.max_retries + 1):
            request = urllib.request.Request(
                self._endpoint,
                data=body,
                headers=headers,
                method="POST",
            )
            try:
                return self._consume_stream(request, on_token)
            except _StreamRetryable as exc:
                if self._is_connection_refused(exc.cause):
                    raise DeepSeekAPIError(
                        self._format_connection_refused(exc.cause)
                    ) from exc.cause
                last_error = exc.cause
            except urllib.error.HTTPError as exc:
                text = exc.read().decode("utf-8", errors="replace")
                if exc.code not in self._RETRYABLE_HTTP:
                    raise DeepSeekAPIError(
                        f"DeepSeek streaming HTTP {exc.code}: {text}"
                    ) from exc
                last_error = DeepSeekAPIError(
                    f"DeepSeek transient HTTP {exc.code}: {text}"
                )
            except (urllib.error.URLError, TimeoutError) as exc:
                if self._is_connection_refused(exc):
                    raise DeepSeekAPIError(
                        self._format_connection_refused(exc)
                    ) from exc
                last_error = DeepSeekAPIError(
                    f"DeepSeek streaming network error: {exc}"
                )

            if attempt < self._config.max_retries:
                time.sleep(min(2 ** (attempt - 1), 16))

        raise DeepSeekAPIError(
            f"DeepSeek request failed after {self._config.max_retries} retries: {last_error}"
        )

    def _is_connection_refused(self, exc: Exception) -> bool:
        text = str(exc)
        if "10061" in text or "Connection refused" in text or "积极拒绝" in text:
            return True
        reason = getattr(exc, "reason", None)
        if reason is not None and reason is not exc:
            return self._is_connection_refused(reason)
        errno = getattr(exc, "errno", None)
        winerror = getattr(exc, "winerror", None)
        return errno in {10061, 111} or winerror == 10061

    def _format_connection_refused(self, exc: Exception) -> str:
        return (
            "无法连接 DeepSeek：本机网络、代理或防火墙拒绝了连接。"
            "请确认网络能访问 https://api.deepseek.com；如果电脑开了代理，请确认代理软件正在运行，"
            "或关闭失效的系统代理后重试；同时确认防火墙允许本软件联网。"
            f"原始错误：{exc}"
        )

    def _build_payload(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        json_mode: bool,
        temperature: float | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._config.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
        }
        if self._config.thinking_enabled:
            payload["thinking"] = {"type": "enabled"}
            payload["reasoning_effort"] = self._config.reasoning_effort
        elif temperature is not None:
            payload["temperature"] = temperature
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _consume_stream(
        self,
        request: urllib.request.Request,
        on_token: TokenCallback | None,
    ) -> ChatResult:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        finish_reason: str | None = None
        usage: dict[str, Any] = {}
        chunk_count = 0
        first_id: str | None = None
        first_created: int | None = None
        delivered_any = False

        try:
            with urllib.request.urlopen(
                request, timeout=self._config.request_timeout_seconds
            ) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    event = json.loads(data)
                    chunk_count += 1
                    if first_id is None:
                        first_id = str(event.get("id") or "")
                        created = event.get("created")
                        if isinstance(created, int):
                            first_created = created

                    event_usage = event.get("usage")
                    if isinstance(event_usage, dict):
                        usage = event_usage

                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    chunk_finish = choice.get("finish_reason")
                    if chunk_finish:
                        finish_reason = str(chunk_finish)
                    delta = choice.get("delta") or {}
                    piece = delta.get("content")
                    reasoning_piece = delta.get("reasoning_content")
                    if isinstance(piece, str) and piece:
                        content_parts.append(piece)
                        delivered_any = True
                        if on_token is not None:
                            on_token("content", piece)
                    if isinstance(reasoning_piece, str) and reasoning_piece:
                        reasoning_parts.append(reasoning_piece)
                        delivered_any = True
                        if on_token is not None:
                            on_token("reasoning", reasoning_piece)
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, TimeoutError) as exc:
            if delivered_any:
                raise DeepSeekAPIError(
                    f"DeepSeek streaming dropped after delivering content: {exc}"
                ) from exc
            raise _StreamRetryable(exc)
        except json.JSONDecodeError as exc:
            if delivered_any:
                raise DeepSeekAPIError(
                    f"DeepSeek streaming returned malformed chunk: {exc}"
                ) from exc
            raise _StreamRetryable(exc)

        if finish_reason not in {"stop", None}:
            raise DeepSeekAPIError(
                f"DeepSeek stream stopped with finish_reason={finish_reason}. "
                "Output is not safe to use as a complete response."
            )

        content = "".join(content_parts)
        if not content.strip():
            raise DeepSeekAPIError("DeepSeek streaming response content was empty.")

        raw = {
            "stream": True,
            "model": self._config.model,
            "id": first_id,
            "created": first_created,
            "chunk_count": chunk_count,
            "finish_reason": finish_reason or "stop",
            "usage": usage,
            "content_chars": len(content),
            "reasoning_chars": sum(len(part) for part in reasoning_parts),
        }
        return ChatResult(
            content=content,
            reasoning_content="".join(reasoning_parts) or None,
            finish_reason=finish_reason or "stop",
            usage=usage,
            raw=raw,
        )


class _StreamRetryable(Exception):

    def __init__(self, cause: Exception) -> None:
        super().__init__(str(cause))
        self.cause = cause
