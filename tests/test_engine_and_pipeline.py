
from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from novel_engine import NovelEngine
from novel_project import NovelProject
from novel_writer.pipeline import (
    DEFAULT_WORDS_PER_CHAPTER,
    MAX_WORDS_PER_CHAPTER,
    MIN_WORDS_PER_CHAPTER,
    NovelPipeline,
    PipelineOptions,
    collect_avoid_history,
    count_anti_cliche_phrases,
)
from novel_writer.config import DeepSeekConfig
from novel_writer.deepseek_client import DeepSeekClient
from novel_writer.errors import ContractError
from novel_writer.prompts import (
    SYSTEM_NOVELIST,
    concept_synthesis_prompt,
    planning_prompt,
)







class _ScriptedSSEServer:

    def __init__(self, scripts: list[list[dict[str, Any]]]) -> None:
        self._scripts = list(scripts)
        self._index = 0
        self._lock = threading.Lock()
        self.requests: list[str] = []

    def next_chunks(self, body: str) -> list[dict[str, Any]]:
        with self._lock:
            self.requests.append(body)
            chunks = self._scripts[min(self._index, len(self._scripts) - 1)]
            if self._index < len(self._scripts) - 1:
                self._index += 1
            return chunks


_SERVER: _ScriptedSSEServer | None = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_POST(self) -> None:
        global _SERVER
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        chunks = _SERVER.next_chunks(body) if _SERVER else []
        body = "".join(
            f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks
        )
        body += "data: [DONE]\n\n"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _start_server(scripts: list[list[dict[str, Any]]]) -> tuple[HTTPServer, str]:
    global _SERVER
    _SERVER = _ScriptedSSEServer(scripts)
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _content_chunks(text: str, *, usage: dict[str, Any] | None = None) -> list[dict[str, Any]]:

    chunks: list[dict[str, Any]] = []
    chunks.append(
        {
            "id": "x",
            "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": "stop"}],
        }
    )
    chunks.append({"choices": [], "usage": usage or {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
    return chunks







class AntiClicheTests(unittest.TestCase):
    def test_count_anti_cliche_phrases_finds_known_offenders(self) -> None:
        text = "他冷笑一声，反手把杯子按在桌上。"
        counts = count_anti_cliche_phrases(text)
        self.assertGreaterEqual(counts.get("冷笑一声", 0), 1)
        self.assertEqual(set(counts), {"冷笑一声"})

    def test_count_anti_cliche_phrases_returns_empty_for_clean_text(self) -> None:
        text = "他抬手挡住刀锋，反手把对方按到桌沿，盯着对方的瞳孔说，'你不该来。'"
        self.assertEqual(count_anti_cliche_phrases(text), {})







class AvoidHistoryTests(unittest.TestCase):
    def test_collect_avoid_history_extracts_innovation_keys(self) -> None:
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "novel_a"
            project_dir.mkdir()
            (project_dir / "brief.json").write_text(
                json.dumps(
                    {
                        "title": "天命之外",
                        "tags": ["玄幻"],
                        "premise": "少年听见死物遗言。",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (project_dir / "plan.json").write_text(
                json.dumps(
                    {
                        "title": "天命之外",
                        "innovation": "金手指来源是死物遗言",
                        "protagonist": {"edge": "听见万物死前低语"},
                        "world": {"power_system": {"name": "听言阶梯"}},
                        "long_arc": {"system_level_secret": "气运榜其实是收割众生"},
                        "golden_three_chapters": [
                            {"chapter": 1, "core_event": "灭门夜里听见尸体呢喃"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            history = collect_avoid_history(root)
        self.assertEqual(len(history), 1)
        entry = history[0]
        self.assertEqual(entry["title"], "天命之外")
        self.assertEqual(entry["innovation"], "金手指来源是死物遗言")
        self.assertIn("听言阶梯", json.dumps(entry["power_system"], ensure_ascii=False))
        self.assertEqual(entry["system_level_secret"], "气运榜其实是收割众生")
        self.assertEqual(entry["first_chapter_core_event"], "灭门夜里听见尸体呢喃")

    def test_collect_avoid_history_handles_missing_dir(self) -> None:
        with TemporaryDirectory() as temp_dir:
            self.assertEqual(collect_avoid_history(Path(temp_dir) / "nope"), [])







class PipelineDefaultsTests(unittest.TestCase):
    def test_default_word_count_is_within_5000_to_10000(self) -> None:
        self.assertGreaterEqual(DEFAULT_WORDS_PER_CHAPTER, MIN_WORDS_PER_CHAPTER)
        self.assertLessEqual(DEFAULT_WORDS_PER_CHAPTER, MAX_WORDS_PER_CHAPTER)
        self.assertEqual(DEFAULT_WORDS_PER_CHAPTER, 5000)
        self.assertEqual(MIN_WORDS_PER_CHAPTER, 1000)
        self.assertEqual(MAX_WORDS_PER_CHAPTER, 20000)







class PipelineRunTests(unittest.TestCase):

    def setUp(self) -> None:
        self._server: HTTPServer | None = None

    def tearDown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _run_one_chapter(self, project_dir: Path) -> None:
        plan = {
            "title": "测试书",
            "logline": "测试用",
            "reader_promise": ["读者承诺"],
            "core_hook": "测试钩子",
            "innovation": "新颖设定",
            "protagonist": {"name": "主角", "voice": "克制冷峻"},
            "main_cast": [],
            "antagonist_ladder": [],
            "world": {"power_system": {"name": "听言阶梯", "tiers": ["一阶"]}},
            "long_arc": {"system_level_secret": "测试谜底"},
            "pacing_curve": [
                {"phase": 1, "chapter_range": "1-1", "tempo": "fast", "purpose": "黄金"}
            ],
            "golden_three_chapters": [
                {"chapter": 1, "title": "起势"}
            ],
            "style_bible": {"tone": "克制"},
            "chapter_outlines": [
                {"chapter": 1, "title": "起势", "pov": "主角", "purpose": "钩子",
                 "beats": ["a", "b", "c"], "stakes": "代价",
                 "payoff": "兑现", "cliffhanger": "钩子", "volume": 1}
            ],
        }
        blueprint = {
            "chapter": 1,
            "title": "起势",
            "previous_cliffhanger_response": "首章不需要",
            "opening_hook": "前 300 字钩子",
            "main_hook": "主钩",
            "secondary_hook": "副钩",
            "scene_cards": [],
            "midpoint_escalation": "二爆",
            "payoff_checklist": ["payoff"],
            "foreshadowing_to_plant": [],
            "foreshadowing_to_payoff": [],
            "anti_cliche_check": "避开降智反派",
            "cliffhanger_line_strategy": "短句",
        }
        chapter_plan = {
            "chapter": 1,
            "title": "起势",
            "pov": "主角",
            "purpose": "用第一章抓住读者",
            "beats": ["危机开场", "主角选择", "章末压力"],
            "stakes": "主角必须当场付出代价",
            "payoff": "核心能力第一次兑现",
            "cliffhanger": "门外有人逼近",
            "volume": 1,
        }
        review = {
            "overall_score": 92,
            "scores": {},
            "fatal_issues": [],
            "rewrite_directives": [],
            "line_level_notes": [],
            "keep": [],
            "predicted_retention": "高",
            "cliche_detected": [],
        }
        chapter_text = "他按住门轴。" * 1000
        summary = {
            "chapter": 1,
            "title": "起势",
            "summary": "起势章节摘要",
            "key_events": ["事件"],
            "character_changes": {},
            "new_facts": [],
            "foreshadowing_planted": [],
            "foreshadowing_payoff": [],
            "open_hooks": ["钩子"],
            "payoffs": [],
            "next_chapter_pressure": "下一章压力是反派来了",
        }
        continuity = {
            "latest_chapter": 1,
            "timeline": ["事件"],
            "character_state": {"主角": {"voice": "克制"}},
            "world_facts": [],
            "open_threads": ["钩子"],
            "promises_to_payoff": [],
            "style_notes": [],
        }

        scripts = [
            _content_chunks(json.dumps(plan, ensure_ascii=False)),
            _content_chunks(json.dumps(chapter_plan, ensure_ascii=False)),
            _content_chunks(json.dumps(blueprint, ensure_ascii=False)),
            _content_chunks(chapter_text),
            _content_chunks(json.dumps(review, ensure_ascii=False)),
            _content_chunks(json.dumps(summary, ensure_ascii=False)),
            _content_chunks(json.dumps(continuity, ensure_ascii=False)),
        ]

        self._server, base_url = _start_server(scripts)
        config = DeepSeekConfig(
            api_key="t",
            base_url=base_url,
            model="deepseek-v4-flash",
            thinking_enabled=False,
            reasoning_effort="high",
            request_timeout_seconds=30,
            max_retries=1,
        )
        client = DeepSeekClient(config)
        pipeline = NovelPipeline(client)
        brief = {
            "title": "测试书",
            "tags": ["玄幻"],
            "audience": "测试",
            "chapter_count": 1,
            "premise": "测试前提",
        }
        options = PipelineOptions(
            output_root=project_dir.parent,
            words_per_chapter=5000,
            min_quality_score=90,
            recent_chapter_count=4,
            golden_chapter_count=1,
            golden_min_quality_score=90,
            explicit_project_dir=project_dir,
        )

        events: list[tuple[str, dict[str, Any]]] = []
        pipeline.run(brief=brief, options=options, progress=lambda s, p: events.append((s, p)))


        self.assertTrue((project_dir / "plan.json").exists())
        saved_plan = json.loads((project_dir / "plan.json").read_text(encoding="utf-8"))
        self.assertNotIn("chapter_outlines", saved_plan)
        self.assertNotIn("golden_three_chapters", saved_plan)
        self.assertTrue((project_dir / "manuscript.md").exists())
        self.assertTrue((project_dir / "manuscript.txt").exists())
        self.assertTrue((project_dir / "metadata.json").exists())
        chapter_files = list((project_dir / "chapters_txt").glob("*.txt"))
        self.assertEqual(len(chapter_files), 1)

        stages = {stage for stage, _ in events}
        self.assertIn("stream", stages)
        self.assertIn("api", stages)
        self.assertIn("chapter_plan", stages)
        self.assertIn("chapter_done", stages)

    def test_pipeline_writes_chapter_files(self) -> None:
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "novel_demo"
            project_dir.mkdir()
            self._run_one_chapter(project_dir)

    def test_pipeline_repeats_quality_review_until_target_score(self) -> None:
        plan = {
            "title": "测试书",
            "logline": "测试用",
            "reader_promise": ["读者承诺"],
            "core_hook": "测试钩子",
            "innovation": "新颖设定",
            "protagonist": {"name": "主角", "voice": "克制冷峻"},
            "main_cast": [],
            "world": {"power_system": {"name": "听言阶梯", "tiers": ["一阶"]}},
            "long_arc": {"system_level_secret": "测试谜底"},
            "style_bible": {"tone": "克制"},
        }
        chapter_plan = {
            "chapter": 1,
            "title": "起势",
            "pov": "主角",
            "purpose": "第一章抓住读者",
            "beats": ["危机开场", "主角选择", "章末压力"],
            "stakes": "主角必须当场付出代价",
            "payoff": "核心能力第一次兑现",
            "cliffhanger": "门外有人逼近",
            "volume": 1,
        }
        blueprint = {
            "chapter": 1,
            "title": "起势",
            "previous_cliffhanger_response": "首章不需要",
            "opening_hook": "前 300 字钩子",
            "main_hook": "主钩",
            "secondary_hook": "副钩",
            "scene_cards": [],
            "midpoint_escalation": "二爆",
            "payoff_checklist": ["payoff"],
            "foreshadowing_to_plant": [],
            "foreshadowing_to_payoff": [],
            "anti_cliche_check": "避开降智反派",
            "cliffhanger_line_strategy": "短句",
        }
        low_review = {
            "overall_score": 72,
            "scores": {},
            "fatal_issues": [],
            "rewrite_directives": ["强化主角主动选择"],
            "line_level_notes": [],
            "keep": [],
            "predicted_retention": "低",
            "cliche_detected": [],
        }
        passing_review = {
            "overall_score": 91,
            "scores": {},
            "fatal_issues": [],
            "rewrite_directives": [],
            "line_level_notes": [],
            "keep": [],
            "predicted_retention": "高",
            "cliche_detected": [],
        }
        summary = {
            "chapter": 1,
            "title": "起势",
            "summary": "起势章节摘要",
            "key_events": ["事件"],
            "character_changes": {},
            "new_facts": [],
            "foreshadowing_planted": [],
            "foreshadowing_payoff": [],
            "open_hooks": ["钩子"],
            "payoffs": [],
            "next_chapter_pressure": "下一章压力是反派来了",
        }
        continuity = {
            "latest_chapter": 1,
            "timeline": ["事件"],
            "character_state": {"主角": {"voice": "克制"}},
            "world_facts": [],
            "open_threads": ["钩子"],
            "promises_to_payoff": [],
            "style_notes": [],
        }

        scripts = [
            _content_chunks(json.dumps(plan, ensure_ascii=False)),
            _content_chunks(json.dumps(chapter_plan, ensure_ascii=False)),
            _content_chunks(json.dumps(blueprint, ensure_ascii=False)),
            _content_chunks("初稿正文" * 250),
            _content_chunks(json.dumps(low_review, ensure_ascii=False)),
            _content_chunks("重写达标" * 250),
            _content_chunks(json.dumps(passing_review, ensure_ascii=False)),
            _content_chunks(json.dumps(summary, ensure_ascii=False)),
            _content_chunks(json.dumps(continuity, ensure_ascii=False)),
        ]

        self._server, base_url = _start_server(scripts)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "novel_demo"
            project_dir.mkdir()
            config = DeepSeekConfig(
                api_key="t",
                base_url=base_url,
                model="deepseek-v4-flash",
                thinking_enabled=False,
                reasoning_effort="high",
                request_timeout_seconds=30,
                max_retries=1,
            )
            pipeline = NovelPipeline(DeepSeekClient(config))
            brief = {
                "title": "测试书",
                "tags": ["玄幻"],
                "audience": "测试",
                "chapter_count": 1,
                "premise": "测试前提",
            }
            options = PipelineOptions(
                output_root=project_dir.parent,
                words_per_chapter=1000,
                min_quality_score=90,
                golden_chapter_count=0,
                explicit_project_dir=project_dir,
            )

            pipeline.run(brief=brief, options=options, progress=lambda s, p: None)

            self.assertTrue(
                (project_dir / "reviews" / "chapter-0001-review-2.json").exists()
            )
            chapter_text = next((project_dir / "chapters_txt").glob("0001-*.txt")).read_text(
                encoding="utf-8"
            )
            self.assertIn("重写达标", chapter_text)

    def test_pipeline_records_feedback_for_next_chapter(self) -> None:
        plan = {
            "title": "测试书",
            "logline": "测试用",
            "reader_promise": ["读者承诺"],
            "core_hook": "测试钩子",
            "innovation": "新颖设定",
            "protagonist": {"name": "主角", "voice": "克制冷峻"},
            "main_cast": [],
            "world": {"power_system": {"name": "听言阶梯", "tiers": ["一阶"]}},
            "long_arc": {"system_level_secret": "测试谜底"},
            "style_bible": {"tone": "克制"},
        }
        chapter_one_plan = {
            "chapter": 1,
            "title": "起势",
            "pov": "主角",
            "purpose": "第一章抓住读者",
            "beats": ["a", "b", "c"],
            "stakes": "代价",
            "payoff": "兑现",
            "cliffhanger": "钩子",
            "volume": 1,
        }
        chapter_two_plan = {
            "chapter": 2,
            "title": "顺着读者选择推进",
            "pov": "主角",
            "purpose": "承接用户反馈",
            "beats": ["d", "e", "f"],
            "stakes": "更大代价",
            "payoff": "反馈兑现",
            "cliffhanger": "新钩子",
            "volume": 1,
        }
        blueprint = {
            "chapter": 1,
            "title": "起势",
            "previous_cliffhanger_response": "自然承接",
            "opening_hook": "钩子",
            "main_hook": "主钩",
            "secondary_hook": "副钩",
            "scene_cards": [],
            "midpoint_escalation": "二爆",
            "payoff_checklist": ["payoff"],
            "foreshadowing_to_plant": [],
            "foreshadowing_to_payoff": [],
            "anti_cliche_check": "避开降智",
            "cliffhanger_line_strategy": "短句",
        }
        review = {
            "overall_score": 92,
            "scores": {},
            "fatal_issues": [],
            "rewrite_directives": [],
            "line_level_notes": [],
            "keep": [],
            "predicted_retention": "高",
            "cliche_detected": [],
        }
        summary_one = {
            "chapter": 1,
            "title": "起势",
            "summary": "第一章摘要",
            "key_events": ["事件"],
            "character_changes": {},
            "new_facts": [],
            "foreshadowing_planted": [],
            "foreshadowing_payoff": [],
            "open_hooks": ["钩子"],
            "payoffs": [],
            "next_chapter_pressure": "下一章压力",
        }
        summary_two = dict(summary_one)
        summary_two["chapter"] = 2
        summary_two["title"] = "顺着读者选择推进"
        continuity_one = {
            "latest_chapter": 1,
            "timeline": ["事件"],
            "character_state": {"主角": {"voice": "克制"}},
            "world_facts": [],
            "open_threads": ["钩子"],
            "promises_to_payoff": [],
            "style_notes": [],
        }
        continuity_two = dict(continuity_one)
        continuity_two["latest_chapter"] = 2
        chapter_text = "他按住门轴。" * 1000
        scripts = [
            _content_chunks(json.dumps(plan, ensure_ascii=False)),
            _content_chunks(json.dumps(chapter_one_plan, ensure_ascii=False)),
            _content_chunks(json.dumps(blueprint, ensure_ascii=False)),
            _content_chunks(chapter_text),
            _content_chunks(json.dumps(review, ensure_ascii=False)),
            _content_chunks(json.dumps(summary_one, ensure_ascii=False)),
            _content_chunks(json.dumps(continuity_one, ensure_ascii=False)),
            _content_chunks(json.dumps(chapter_two_plan, ensure_ascii=False)),
            _content_chunks(json.dumps({**blueprint, "chapter": 2, "title": "顺着读者选择推进"}, ensure_ascii=False)),
            _content_chunks(chapter_text),
            _content_chunks(json.dumps(review, ensure_ascii=False)),
            _content_chunks(json.dumps(summary_two, ensure_ascii=False)),
            _content_chunks(json.dumps(continuity_two, ensure_ascii=False)),
        ]

        self._server, base_url = _start_server(scripts)
        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "novel_demo"
            project_dir.mkdir()
            config = DeepSeekConfig(
                api_key="t",
                base_url=base_url,
                model="deepseek-v4-flash",
                thinking_enabled=False,
                reasoning_effort="high",
                request_timeout_seconds=30,
                max_retries=1,
            )
            pipeline = NovelPipeline(DeepSeekClient(config))
            brief = {
                "title": "测试书",
                "tags": ["玄幻"],
                "audience": "测试",
                "chapter_count": 2,
                "premise": "测试前提",
            }
            options = PipelineOptions(
                output_root=project_dir.parent,
                words_per_chapter=5000,
                min_quality_score=90,
                recent_chapter_count=4,
                golden_chapter_count=1,
                golden_min_quality_score=90,
                explicit_project_dir=project_dir,
                chapter_feedback_provider=lambda chapter, title: "下一章让女主主动拆穿谎言",
            )
            pipeline.run(brief=brief, options=options, progress=lambda s, p: None)

            directions_path = project_dir / "user_directions.json"
            self.assertTrue(directions_path.exists())
            directions = json.loads(directions_path.read_text(encoding="utf-8"))
            self.assertEqual(directions[0]["after_chapter"], 1)
            self.assertEqual(directions[0]["direction"], "下一章让女主主动拆穿谎言")

        server = _SERVER
        self.assertIsNotNone(server)
        joined_requests = "\n".join(server.requests)
        self.assertIn("下一章让女主主动拆穿谎言", joined_requests)







class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._server: HTTPServer | None = None

    def tearDown(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def _build_scripts(self) -> list[list[dict[str, Any]]]:
        synopsis = (
            "夜风灌进祠堂的瞬间，少年陆听言被自家供桌上的尸体唤了名字。"
            "那是十年前死去的父亲，喉咙里渗出的不是血，而是一句迟到的告诫："
            "天命榜不是命，是有人用命喂出来的祭。从此，陆听言能听见死物开口前的最后一句话，"
            "代价是他自己每听一次，命数就被抽走一寸。他要做的不只是查清父亲为何会成为天命榜上的名字，"
            "更要在被人撕成第一千零八块碎片之前，把那张笼罩九州的榜，亲手撕个干净。"
            "执念能借因果，遗言能换运势，少年穿过祠堂、穿过宗门、穿过天上人间的无数尸骨，"
            "听到了藏在每一具死物深处的同一句呐喊：原来榜上没有神，只有一群把自己写成神的人。"
        )
        concept_brief = {
            "title": "听言之书",
            "tags": ["玄幻"],
            "audience": "男频玄幻读者",
            "premise": "他能听见万物死前的话。",
            "synopsis": synopsis,
            "core_innovation": "金手指来源是死物遗言",
            "tag_fusion": "听言流",
            "commercial_goal": "黄金三章稳爆款",
            "must_have": ["前 300 字危机", "金手指代价清晰"],
            "avoid": ["套壳退婚"],
            "tone_keywords": ["冷硬克制"],
            "first_three_chapters_outline": [
                {"chapter": 1, "core_event": "灭门夜听见尸体说话", "ending_hook": "门外有人"}
            ],
        }
        plan = {
            "title": "听言之书",
            "logline": "听言定命",
            "reader_promise": ["承诺"],
            "core_hook": "钩子",
            "golden_three_chapters": [{"chapter": 1, "title": "起势"}],
            "style_bible": {"tone": "克制"},
            "chapter_outlines": [
                {
                    "chapter": 1, "title": "起势", "pov": "主角",
                    "purpose": "钩子", "beats": ["a", "b", "c"],
                    "stakes": "代价", "payoff": "兑现",
                    "cliffhanger": "钩子", "volume": 1,
                }
            ],
        }
        chapter_plan = {
            "chapter": 1,
            "title": "起势",
            "pov": "主角",
            "purpose": "第一章抓住读者",
            "beats": ["a", "b", "c"],
            "stakes": "代价",
            "payoff": "兑现",
            "cliffhanger": "钩子",
            "volume": 1,
        }
        blueprint = {
            "chapter": 1, "title": "起势",
            "previous_cliffhanger_response": "首章不需要",
            "opening_hook": "钩子", "main_hook": "主钩",
            "secondary_hook": "副钩", "scene_cards": [],
            "midpoint_escalation": "二爆",
            "payoff_checklist": ["payoff"],
            "foreshadowing_to_plant": [], "foreshadowing_to_payoff": [],
            "anti_cliche_check": "避开降智", "cliffhanger_line_strategy": "短句",
        }
        chapter_text = "他按住门轴。" * 1000
        review = {
            "overall_score": 95, "scores": {}, "fatal_issues": [],
            "rewrite_directives": [], "line_level_notes": [],
            "keep": [], "predicted_retention": "高",
            "cliche_detected": [],
        }
        summary = {
            "chapter": 1, "title": "起势",
            "summary": "摘要", "key_events": ["e"],
            "character_changes": {}, "new_facts": [],
            "foreshadowing_planted": [], "foreshadowing_payoff": [],
            "open_hooks": ["钩"], "payoffs": [],
            "next_chapter_pressure": "反派要来",
        }
        continuity = {
            "latest_chapter": 1, "timeline": ["e"],
            "character_state": {"主角": {"voice": "克制"}},
            "world_facts": [], "open_threads": [],
            "promises_to_payoff": [], "style_notes": [],
        }
        return [
            _content_chunks(json.dumps(concept_brief, ensure_ascii=False)),
            _content_chunks(json.dumps(plan, ensure_ascii=False)),
            _content_chunks(json.dumps(chapter_plan, ensure_ascii=False)),
            _content_chunks(json.dumps(blueprint, ensure_ascii=False)),
            _content_chunks(chapter_text),
            _content_chunks(json.dumps(review, ensure_ascii=False)),
            _content_chunks(json.dumps(summary, ensure_ascii=False)),
            _content_chunks(json.dumps(continuity, ensure_ascii=False)),
        ]

    def test_engine_synthesises_brief_then_writes_chapter(self) -> None:
        scripts = self._build_scripts()
        self._server, base_url = _start_server(scripts)

        with TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "novel_demo"
            project = NovelProject()
            project.tags = ["玄幻"]
            project.custom_tags = ["听言流"]
            project.audience = "男频玄幻读者"
            project.total_chapters = 1
            project.words_per_chapter = 5000
            project.min_quality_score = 90
            project.save_path = str(project_dir)
            project.save()

            engine = NovelEngine(
                api_key="t",
                project=project,
                model="deepseek-v4-flash",
                projects_root=Path(temp_dir),
                base_url=base_url,
                reasoning_effort="high",
                thinking_enabled=False,
                request_timeout_seconds=30,
                max_retries=1,
            )
            statuses: list[str] = []
            chapter_done: list[tuple[int, int]] = []
            chunks: list[str] = []
            errors: list[str] = []
            engine.run(
                on_status=statuses.append,
                on_chapter_start=lambda n, t: None,
                on_chunk=chunks.append,
                on_chapter_complete=lambda n, w: chapter_done.append((n, w)),
                on_complete=lambda: None,
                on_error=errors.append,
            )

            self.assertFalse(errors, msg=f"engine reported errors: {errors}")
            self.assertEqual(len(chapter_done), 1)
            self.assertEqual(chapter_done[0][0], 1)
            self.assertEqual(project.title, "听言之书")
            self.assertEqual(project.status, "completed")
            self.assertGreater(project.total_words, 0)

            self.assertTrue(any(chunks))

            self.assertGreaterEqual(len(project.synopsis), 200)
            self.assertLessEqual(len(project.synopsis), 525)
            brief_path = project_dir / "brief.json"
            brief = json.loads(brief_path.read_text(encoding="utf-8"))
            self.assertIn("synopsis", brief)

            self.assertEqual(brief["audience"], "男频玄幻读者")
            self.assertEqual(project.audience, "男频玄幻读者")

            self.assertIn("听言流", project.merged_tags())


class PromptExtraInjectionTests(unittest.TestCase):
    def test_concept_prompt_requires_synopsis(self) -> None:
        text = concept_synthesis_prompt(
            tags=["玄幻"], chapter_count=10, words_per_chapter=7000
        )
        self.assertIn("synopsis", text)
        self.assertIn("200-500", text)

    def test_concept_prompt_does_not_request_chapter_outlines(self) -> None:
        text = concept_synthesis_prompt(
            tags=["玄幻"], chapter_count=10, words_per_chapter=7000
        )
        self.assertNotIn("first_three_chapters_outline", text)
        self.assertNotIn("chapter_outlines", text)
        self.assertNotIn("大纲", text)

    def test_concept_prompt_locks_user_audience(self) -> None:
        text = concept_synthesis_prompt(
            tags=["玄幻"], chapter_count=10, words_per_chapter=7000,
            audience="女频言情读者",
        )
        self.assertIn("女频言情读者", text)
        self.assertIn("用户已指定，必须采纳", text)

    def test_concept_prompt_locks_user_title_and_synopsis(self) -> None:
        text = concept_synthesis_prompt(
            tags=["玄幻"],
            chapter_count=10,
            words_per_chapter=7000,
            requested_title="借命天书",
            requested_synopsis="少年用寿命借来死者遗愿。",
        )
        self.assertIn("借命天书", text)
        self.assertIn("少年用寿命借来死者遗愿。", text)
        self.assertIn("必须使用这个标题", text)

    def test_builtin_system_prompt_is_used(self) -> None:
        self.assertIn("中国网络小说作者兼连载编辑", SYSTEM_NOVELIST)
        self.assertIn("黄金三章", SYSTEM_NOVELIST)

    def test_planning_prompt_does_not_request_outlines(self) -> None:
        text = planning_prompt(
            {
                "title": "测试书",
                "tags": ["玄幻"],
                "chapter_count": 1000,
                "premise": "测试前提",
            }
        )
        forbidden = [
            "chapter_outlines",
            "golden_three_chapters",
            "first_three_chapters",
            "chapter_range",
            "大纲",
            "细纲",
            "前三章",
            "第2章",
            "第3章",
        ]
        for word in forbidden:
            self.assertNotIn(word, text)


class SynopsisValidationTests(unittest.TestCase):
    def _pipeline(self) -> NovelPipeline:
        return NovelPipeline(client=DeepSeekClient.__new__(DeepSeekClient))

    def test_validate_synth_brief_rejects_missing_synopsis(self) -> None:
        pipeline = self._pipeline()
        with self.assertRaises(ContractError) as ctx:
            pipeline._validate_synth_brief(
                {"title": "x", "premise": "y"},
                tags=["玄幻"],
                chapter_count=10,
            )
        self.assertIn("synopsis", str(ctx.exception))

    def test_validate_synth_brief_rejects_too_long_synopsis(self) -> None:
        pipeline = self._pipeline()
        too_long = "这是一段很长的中文文字测试用例" * 50
        with self.assertRaises(ContractError):
            pipeline._validate_synth_brief(
                {"title": "x", "premise": "y", "synopsis": too_long},
                tags=["玄幻"],
                chapter_count=10,
            )

    def test_validate_synth_brief_rejects_too_short_synopsis(self) -> None:
        pipeline = self._pipeline()
        with self.assertRaises(ContractError):
            pipeline._validate_synth_brief(
                {"title": "x", "premise": "y", "synopsis": "太短了"},
                tags=["玄幻"],
                chapter_count=10,
            )

    def test_validate_synth_brief_locks_user_audience(self) -> None:
        pipeline = self._pipeline()
        good_synopsis = "一段两百字以上的合格简介。" * 20
        brief = {"title": "x", "premise": "y", "synopsis": good_synopsis, "audience": "随便"}
        pipeline._validate_synth_brief(
            brief,
            tags=["玄幻"],
            chapter_count=10,
            audience="女频言情读者",
        )
        self.assertEqual(brief["audience"], "女频言情读者")

    def test_validate_synth_brief_locks_user_title_and_short_synopsis(self) -> None:
        pipeline = self._pipeline()
        brief = {"title": "模型标题", "premise": "y", "synopsis": "模型简介。" * 30}
        pipeline._validate_synth_brief(
            brief,
            tags=["玄幻"],
            chapter_count=10,
            requested_title="用户标题",
            requested_synopsis="用户短简介。",
        )
        self.assertEqual(brief["title"], "用户标题")
        self.assertEqual(brief["synopsis"], "用户短简介。")


if __name__ == "__main__":
    unittest.main()
