
from __future__ import annotations

import json
import threading
import urllib.error
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from typing import Any

from novel_writer.config import DeepSeekConfig
from novel_writer.deepseek_client import DeepSeekClient
from novel_writer.errors import DeepSeekAPIError


class _StreamHandler(BaseHTTPRequestHandler):
    response_chunks: list[dict[str, Any]] = []
    last_payload: dict[str, Any] = {}

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).last_payload = json.loads(body.decode("utf-8"))

        chunks = type(self).response_chunks
        out = []
        for chunk in chunks:
            out.append(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n")
        out.append("data: [DONE]\n\n")
        encoded = "".join(out).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


class StreamingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _StreamHandler)
        self._port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def tearDown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _client(
        self,
        *,
        thinking: bool = True,
        reasoning_effort: str = "high",
        model: str = "deepseek-v4-flash",
    ) -> DeepSeekClient:
        config = DeepSeekConfig(
            api_key="test-key",
            base_url=f"http://127.0.0.1:{self._port}",
            model=model,
            thinking_enabled=thinking,
            reasoning_effort=reasoning_effort,
            request_timeout_seconds=5,
            max_retries=1,
        )
        return DeepSeekClient(config)

    def test_streaming_assembles_content_reasoning_and_usage(self) -> None:
        _StreamHandler.response_chunks = [
            {
                "id": "abc",
                "created": 1,
                "choices": [
                    {"index": 0, "delta": {"reasoning_content": "想"}, "finish_reason": None}
                ],
            },
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"reasoning_content": "中"}, "finish_reason": None}
                ],
            },
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"content": "你"}, "finish_reason": None}
                ],
            },
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"content": "好"}, "finish_reason": None}
                ],
            },
            {
                "id": "abc",
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "prompt_cache_hit_tokens": 4,
                    "prompt_cache_miss_tokens": 6,
                    "total_tokens": 15,
                    "completion_tokens_details": {"reasoning_tokens": 2},
                },
            },
        ]
        events: list[tuple[str, str]] = []
        result = self._client().chat_stream(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            on_token=lambda channel, piece: events.append((channel, piece)),
        )

        self.assertEqual(result.content, "你好")
        self.assertEqual(result.reasoning_content, "想中")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.reasoning_tokens, 2)
        self.assertEqual(result.cache_hit_tokens, 4)
        self.assertEqual(result.cache_miss_tokens, 6)
        self.assertIn(("content", "你"), events)
        self.assertIn(("reasoning", "想"), events)

    def test_streaming_payload_uses_v4_flash_defaults(self) -> None:
        _StreamHandler.response_chunks = [
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"content": "x"}, "finish_reason": "stop"}
                ],
            },
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        self._client().chat_stream(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
        )
        payload = _StreamHandler.last_payload
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["stream_options"], {"include_usage": True})
        self.assertEqual(payload["max_tokens"], 100)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "high")
        self.assertNotIn("temperature", payload)

    def test_streaming_payload_can_disable_thinking_and_use_temperature(self) -> None:
        _StreamHandler.response_chunks = [
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"content": "x"}, "finish_reason": "stop"}
                ],
            },
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        self._client(thinking=False).chat_stream(
            [{"role": "user", "content": "hi"}],
            max_tokens=100,
            temperature=0.6,
        )
        payload = _StreamHandler.last_payload
        self.assertNotIn("thinking", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(payload["temperature"], 0.6)

    def test_streaming_rejects_non_stop_finish_reason(self) -> None:
        _StreamHandler.response_chunks = [
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"content": "片段"}, "finish_reason": "length"}
                ],
            },
        ]
        with self.assertRaises(DeepSeekAPIError):
            self._client().chat_stream(
                [{"role": "user", "content": "hi"}],
                max_tokens=10,
            )

    def test_streaming_rejects_empty_content(self) -> None:
        _StreamHandler.response_chunks = [
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"reasoning_content": "纯思考"}, "finish_reason": "stop"}
                ],
            },
        ]
        with self.assertRaises(DeepSeekAPIError):
            self._client().chat_stream(
                [{"role": "user", "content": "hi"}],
                max_tokens=10,
            )

    def test_streaming_passes_json_mode(self) -> None:
        _StreamHandler.response_chunks = [
            {
                "id": "abc",
                "choices": [
                    {"index": 0, "delta": {"content": "{\"a\":1}"}, "finish_reason": "stop"}
                ],
            },
            {"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}},
        ]
        self._client().chat_stream(
            [{"role": "user", "content": "请输出 json"}],
            max_tokens=100,
            json_mode=True,
        )
        payload = _StreamHandler.last_payload
        self.assertEqual(payload["response_format"], {"type": "json_object"})

    def test_connection_refused_message_is_actionable(self) -> None:
        config = DeepSeekConfig(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            request_timeout_seconds=1,
            max_retries=1,
        )
        client = DeepSeekClient(config)
        refused = urllib.error.URLError(ConnectionRefusedError(10061, "由于目标计算机积极拒绝，无法连接。"))
        with patch("urllib.request.urlopen", side_effect=refused):
            with self.assertRaises(DeepSeekAPIError) as ctx:
                client.chat_stream([{"role": "user", "content": "hi"}], max_tokens=10)
        message = str(ctx.exception)
        self.assertIn("无法连接 DeepSeek", message)
        self.assertIn("代理", message)
        self.assertIn("防火墙", message)


if __name__ == "__main__":
    unittest.main()
