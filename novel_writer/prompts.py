from __future__ import annotations

import json
from typing import Any


SYSTEM_NOVELIST = (
    "你是一名成熟的中国网络小说作者兼连载编辑，熟悉男频、女频、玄幻、都市、言情、悬疑等类型。"
    "你的任务是根据用户给出的信息，创作可持续连载的中国网络小说。"
    "写作时要兼顾黄金三章、手机端阅读、章节追读、人物动机、情节因果和长篇连续性。"
    "黄金三章要尽快交代主角、处境、主要矛盾和读者继续读下去的理由；不要慢热到读者看不见故事方向。"
    "每章都应有清楚目标、具体阻力、阶段性变化和适度结尾悬念，但不要机械堆爽点或强行反转。"
    "优先保证故事自然、人物可信、语言顺畅、前后连续。"
    "不要输出创作说明、免责声明、AI 自述、思考过程或与小说无关的文字。"
    "需要输出 JSON 时，只输出合法 JSON，不要 markdown 代码块，不要 JSON 以外的文字。"
)


KNOWN_TROPE_BLACKLIST: list[str] = [
    "降智反派",
]


ANTI_CLICHE_BANNED_PHRASES: list[str] = [
    "冷笑一声",
]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _format_rules(top_level: str) -> str:
    return (
        f"输出格式必须是{top_level}。\n"
        "不要输出 markdown。\n"
        "不要输出解释。\n"
        "不要输出 JSON 之外的任何文字。\n"
        "字段名必须与示例一致，缺字段视为不合格。\n"
    )


def _writing_principles() -> str:
    return (
        "创作原则：这是中国网络小说，不是文学散文或设定说明书。\n"
        "1. 黄金三章要明确主角、处境、核心矛盾、类型看点和继续阅读的理由。\n"
        "2. 手机端阅读要段落清楚、推进明确，不要长篇空泛设定和大段说明。\n"
        "3. 主角要有主动目标，配角和反派要有能理解的动机。\n"
        "4. 章节之间要有因果承接，章末可以留悬念，但不要为钩子牺牲合理性。\n"
        "5. 类型标签要服务故事，不要把标签机械堆进设定。\n"
        "6. 避免明显流水套路和套话，但不要为了反套路而别扭。\n"
    )


def concept_synthesis_prompt(
    *,
    tags: list[str],
    chapter_count: int,
    words_per_chapter: int,
    audience: str = "",
    requested_title: str = "",
    requested_synopsis: str = "",
    avoid_history: list[dict[str, Any]] | None = None,
) -> str:
    title_rule = (
        f"用户已填写标题：{requested_title.strip()}。title 字段必须使用这个标题，不要改写。\n"
        if requested_title.strip()
        else "用户没有填写标题，请生成一个适合连载的标题。\n"
    )
    synopsis_rule = (
        "用户已填写作品简介，synopsis 字段必须原样使用，不要改写：\n"
        f"{requested_synopsis.strip()}\n"
        if requested_synopsis.strip()
        else "用户没有填写作品简介，请生成 200-500 中文字 synopsis。\n"
    )
    audience_rule = (
        f"目标读者（用户已指定，必须采纳，不要改写）：{audience.strip()}\n"
        if audience.strip()
        else "目标读者未指定，请根据标签判断。\n"
    )
    history_rule = ""
    if avoid_history:
        history_rule = "以下是历史项目摘要，只用于避免重复核心设定：\n" + _json(avoid_history) + "\n"
    example = {
        "title": requested_title.strip() or "书名",
        "tags": tags,
        "audience": audience.strip() or "男频或女频读者",
        "synopsis": requested_synopsis.strip() or "200-500 字作品简介",
        "premise": "核心设定，说明主角、处境、主要能力或矛盾、长期方向",
        "core_innovation": "本书最值得记住的新意",
        "tag_fusion": "标签融合后的类型定位",
        "commercial_goal": "连载目标和读者期待",
        "must_have": ["必须保留的元素"],
        "avoid": ["需要避免的重复或不适合元素"],
        "tone_keywords": ["文风关键词"],
        "opening_direction": "第一章要立刻呈现的处境、核心吸引力和阅读情绪",
    }
    return (
        "请为一部长篇中国网络小说生成初始 brief。\n"
        + _format_rules("JSON 对象")
        + f"标签：{_json(tags)}\n"
        + audience_rule
        + title_rule
        + synopsis_rule
        + f"计划章节数：{chapter_count}\n"
        + f"每章目标字数：{words_per_chapter}\n"
        + history_rule
        + _writing_principles()
        + "初始 brief 要给出足够清楚的长篇方向，但不要把后期剧情写死。\n"
        + "不要输出后续章节列表、分章安排或批量章节字段；正文会从第一章开始逐章决定。\n"
        + "字段示例：\n"
        + _json(example)
    )


def planning_prompt(brief: dict[str, Any]) -> str:
    chapter_count = int(brief.get("chapter_count") or 30)
    example = {
        "title": brief.get("title") or "书名",
        "logline": "一句话说明本书看点",
        "reader_promise": ["读者会持续期待的内容"],
        "core_hook": "开篇吸引点",
        "innovation": "区别于普通同类文的地方",
        "anti_cliche": ["需要避免的陈旧写法"],
        "market_positioning": {
            "target_reader": brief.get("audience") or "目标读者",
            "primary_emotion": "主要阅读情绪",
            "selling_points": ["卖点"],
            "first_30k_strategy": "前三万字方向",
            "monetization_strategy": "付费转化方向",
            "comparable_titles": [],
        },
        "protagonist": {
            "name": "主角名",
            "background": "出身",
            "desire": "外在目标",
            "wound": "内在缺口",
            "edge": "优势",
            "fatal_flaw": "弱点",
            "growth_arc": "成长方向",
            "voice": "语言和思维风格",
        },
        "main_cast": [
            {
                "name": "角色名",
                "function": "叙事功能",
                "relationship": "与主角关系",
                "secret": "隐藏信息",
                "arc": "变化方向",
                "voice": "语言风格",
            }
        ],
        "opposition_design": {
            "pressure_sources": ["压力来源"],
            "motive_logic": "反对力量的动机逻辑",
            "escalation_rule": "压力如何随主角选择自然升级",
        },
        "world": {
            "genre": "类型",
            "power_system": {"name": "体系名", "tiers": ["层级"], "cost_logic": "代价或限制"},
            "rules": ["规则"],
            "rarity_economy": "稀缺资源",
            "social_pressure": "社会压力",
            "iconic_settings": ["标志性场景"],
        },
        "long_arc": {
            "final_destination": "长线欲望和终局气质",
            "system_level_secret": "长期谜底或深层真相",
            "recurring_tensions": ["可反复推动章节的张力"],
            "mystery_sources": ["长期疑问来源"],
        },
        "reader_retention_design": {
            "opening_mission": "开篇必须让读者立刻看懂的吸引力",
            "recurring_rewards": ["持续奖励"],
            "chapter_end_modes": ["常用章末方式"],
            "paid_reading_trigger": "付费阅读的情绪触发点",
        },
        "style_bible": {
            "tone": "整体语气",
            "narrator_voice": "叙述声音",
            "paragraphing": "段落习惯",
            "dialogue_rules": "对话习惯",
            "taboos": ["不要写的内容"],
            "signature_moves": ["可持续使用的写法"],
        },
    }
    return (
        "请根据 brief 生成小说故事圣经。\n"
        + _format_rules("JSON 对象")
        + "不要输出后续章节列表、分章安排、卷级章节范围或任何批量章节字段。\n"
        + "只确定可长期延展的角色、世界、读者承诺、风格和开篇方向，后续每章会根据已写内容和用户反馈单独决定。\n"
        + _writing_principles()
        + f"目标总章数：{chapter_count}。故事圣经要开放，不要把整本书结局写死。\n"
        + "brief：\n"
        + _json(brief)
        + "\n字段示例：\n"
        + _json(example)
    )


def next_chapter_prompt(
    *,
    brief: dict[str, Any],
    plan_summary: dict[str, Any],
    chapter_number: int,
    total_chapters: int,
    previous_summaries: list[dict[str, Any]],
    continuity: dict[str, Any],
    user_directions: list[dict[str, Any]],
) -> str:
    example = {
        "chapter": chapter_number,
        "title": "章名",
        "pov": "视角",
        "purpose": "本章作用",
        "beats": ["开端", "推进", "转折"],
        "stakes": "风险或代价",
        "payoff": "本章兑现",
        "cliffhanger": "本章结尾悬念",
        "volume": 1,
    }
    return (
        f"请只为第 {chapter_number} 章生成本章方向。\n"
        + _format_rules("JSON 对象")
        + "不要生成后续章节大纲，不要预测整本书细纲。\n"
        + "如果用户在上一章后给过方向，必须优先采纳；如果与已写事实冲突，要自然化解，不要硬改已经发生的内容。\n"
        + "本章方向必须承接已完成章节、连续性记忆和用户最新反馈，让读者感觉故事被上一章自然推着走。\n"
        + "每项必须包含 chapter, title, pov, purpose, beats, stakes, payoff, cliffhanger, volume。\n"
        + f"全书目标共 {total_chapters} 章。\n"
        + _writing_principles()
        + "brief：\n"
        + _json(brief)
        + "\n故事圣经：\n"
        + _json(plan_summary)
        + "\n已完成章节摘要：\n"
        + _json(previous_summaries)
        + "\n连续性记忆：\n"
        + _json(continuity)
        + "\n用户章节反馈：\n"
        + _json(user_directions)
        + "\n字段示例：\n"
        + _json(example)
    )


def blueprint_prompt(context_pack: dict[str, Any], words_per_chapter: int) -> str:
    scene_count = max(3, min(12, words_per_chapter // 1000 + 1))
    example = {
        "chapter": context_pack.get("current_chapter", {}).get("chapter", 1),
        "title": context_pack.get("current_chapter", {}).get("title", "章名"),
        "previous_cliffhanger_response": "如何承接上一章",
        "opening_hook": "开篇要写出的吸引点",
        "main_hook": "本章主要问题",
        "secondary_hook": "中段推进点",
        "tertiary_hook": "长章可用的后段推进点",
        "emotional_curve": ["情绪变化"],
        "scene_cards": [
            {
                "scene": index,
                "word_budget": max(500, words_per_chapter // scene_count),
                "location": "地点",
                "characters": ["角色"],
                "goal": "目标",
                "obstacle": "阻力",
                "conflict": "冲突",
                "turning_point": "变化",
                "information_gain": "新增信息",
                "reader_reward": "阅读奖励",
                "scene_end_hook": "场景结尾",
            }
            for index in range(1, scene_count + 1)
        ],
        "midpoint_escalation": "中段变化",
        "second_midpoint_escalation": "长章后段变化",
        "payoff_checklist": ["本章要兑现的事"],
        "foreshadowing_to_plant": ["本章埋下的信息"],
        "foreshadowing_to_payoff": ["本章兑现的信息"],
        "anti_cliche_check": "避免明显重复套路的办法",
        "cliffhanger_line_strategy": "章末收束方式",
    }
    return (
        "请为当前章节生成场景蓝图。\n"
        + _format_rules("JSON 对象")
        + f"目标正文约 {words_per_chapter} 字，scene_cards 建议 {scene_count} 个。\n"
        + _writing_principles()
        + "蓝图要可写、具体、不过度设计。每个场景至少要有目标、阻力和变化。\n"
        + "如果是前三章，opening_hook 和 scene_cards 要服务黄金三章的阅读吸引力。\n"
        + "上下文：\n"
        + _json(context_pack)
        + "\n字段示例：\n"
        + _json(example)
    )


def chapter_prompt(
    *,
    context_pack: dict[str, Any],
    blueprint: dict[str, Any],
    words_per_chapter: int,
    is_golden: bool = False,
    due_promises: list[dict[str, Any]] | None = None,
    pacing_phase: dict[str, Any] | None = None,
) -> str:
    lower_bound = int(words_per_chapter * 0.85)
    upper_bound = int(words_per_chapter * 1.15)
    additions: list[str] = []
    if is_golden:
        additions.append(
            "这是黄金三章之一。请尽快让读者理解主角是谁、他/她遇到什么问题、这本书的核心看点是什么、为什么要继续读。"
        )
    if due_promises:
        additions.append("本章需要处理这些未兑现事项：\n" + _json(due_promises))
    if pacing_phase:
        additions.append("当前节奏阶段：\n" + _json(pacing_phase))
    if context_pack.get("previous_chapter_cliffhanger"):
        additions.append("开篇自然承接上一章结尾：\n" + _json(context_pack["previous_chapter_cliffhanger"]))
    extra = "\n".join(additions)
    return (
        "请直接写本章小说正文。\n"
        "只输出正文，不要标题，不要说明，不要 markdown，不要元信息。\n"
        f"字数必须尽量落在 {lower_bound} 到 {upper_bound} 中文字之间。\n"
        + _writing_principles()
        + "正文要保持人物动机清楚、事件有因果、对话自然、段落适合手机阅读。\n"
        "每章应有本章目标、阻力、变化和结尾余味；结尾可以留悬念，但必须合理。\n"
        "不要机械执行模板；以当前上下文和蓝图为准，让情节自然推进。\n"
        + (extra + "\n" if extra else "")
        + "上下文：\n"
        + _json(context_pack)
        + "\n蓝图：\n"
        + _json(blueprint)
        + "\n现在开始正文："
    )


def expansion_prompt(
    *,
    context_pack: dict[str, Any],
    blueprint: dict[str, Any],
    draft: str,
    target_words: int,
    actual_words: int,
) -> str:
    return (
        "下方正文偏短，请扩写成完整正文。\n"
        "只输出扩写后的正文，不要解释，不要标题。\n"
        f"目标约 {target_words} 字，当前约 {actual_words} 字。\n"
        "扩写应补充情节、动作、对话和必要信息，不要重复灌水。\n"
        "上下文：\n"
        + _json(context_pack)
        + "\n蓝图：\n"
        + _json(blueprint)
        + "\n待扩写正文：\n"
        + draft
    )


def tightening_prompt(
    *,
    context_pack: dict[str, Any],
    blueprint: dict[str, Any],
    draft: str,
    target_words: int,
    actual_words: int,
) -> str:
    return (
        "下方正文偏长，请精简。\n"
        "只输出精简后的正文，不要解释，不要标题。\n"
        f"目标约 {target_words} 字，当前约 {actual_words} 字。\n"
        "保留主要情节、人物变化、关键信息和结尾推进，删去重复和空转。\n"
        "上下文：\n"
        + _json(context_pack)
        + "\n蓝图：\n"
        + _json(blueprint)
        + "\n待精简正文：\n"
        + draft
    )


def quality_review_prompt(
    *,
    context_pack: dict[str, Any],
    blueprint: dict[str, Any],
    chapter_text: str,
) -> str:
    example = {
        "overall_score": 86,
        "scores": {
            "opening_hook": 85,
            "previous_chapter_continuity": 85,
            "conflict_density": 85,
            "midpoint_escalation": 85,
            "reader_reward": 85,
            "continuity": 85,
            "mobile_readability": 85,
            "cliffhanger": 85,
            "originality": 85,
            "dialogue_quality": 85,
            "pacing": 85,
            "voice_consistency": 85,
            "anti_cliche": 85,
        },
        "word_count": 5000,
        "fatal_issues": [],
        "rewrite_directives": ["具体可执行的修改建议"],
        "line_level_notes": ["具体问题"],
        "keep": ["应保留的优点"],
        "predicted_retention": "追读判断",
        "cliche_detected": [],
    }
    return (
        "请评审当前章节。\n"
        + _format_rules("JSON 对象")
        + "评分要诚实，重点看是否清楚、自然、连续、好读，是否符合中国网络小说连载阅读习惯。\n"
        + "前三章要重点检查黄金三章功能：主角、处境、核心看点、主要矛盾、继续阅读理由是否成立。\n"
        + "overall_score 必须是 0-100 的整数。\n"
        + "上下文：\n"
        + _json(context_pack)
        + "\n蓝图：\n"
        + _json(blueprint)
        + "\n章节正文：\n"
        + chapter_text
        + "\n字段示例：\n"
        + _json(example)
    )


def quality_rewrite_prompt(
    *,
    context_pack: dict[str, Any],
    blueprint: dict[str, Any],
    review: dict[str, Any],
    chapter_text: str,
    words_per_chapter: int,
) -> str:
    lower = int(words_per_chapter * 0.85)
    upper = int(words_per_chapter * 1.15)
    return (
        "请根据评审意见重写章节。\n"
        "只输出重写后的正文，不要解释，不要标题。\n"
        f"字数尽量落在 {lower} 到 {upper} 中文字之间。\n"
        + _writing_principles()
        + "优先解决 fatal_issues 和 rewrite_directives，保留 keep 中的优点。\n"
        "上下文：\n"
        + _json(context_pack)
        + "\n蓝图：\n"
        + _json(blueprint)
        + "\n评审：\n"
        + _json(review)
        + "\n原正文：\n"
        + chapter_text
    )


def continuity_prompt(
    *,
    existing_continuity: dict[str, Any],
    chapter_number: int,
    chapter_title: str,
    chapter_text: str,
) -> str:
    example = {
        "latest_chapter": chapter_number,
        "timeline": ["按章节顺序记录已发生事件"],
        "character_state": {
            "角色名": {
                "status": "当前状态",
                "voice": "语言风格",
                "relationships": ["关系"],
                "last_updated_chapter": chapter_number,
            }
        },
        "world_facts": ["已确认设定"],
        "open_threads": ["未解决问题"],
        "promises_to_payoff": [
            {
                "promise": "待兑现内容",
                "planted_in_chapter": chapter_number,
                "deadline_chapter": chapter_number + 30,
                "status": "pending",
            }
        ],
        "style_notes": ["需要保持的写法"],
    }
    return (
        "请根据新章节更新连续性记忆。\n"
        + _format_rules("JSON 对象")
        + "保留仍有效的旧信息，更新角色状态、世界事实、未解决问题和待兑现承诺。\n"
        + "旧连续性记忆：\n"
        + _json(existing_continuity)
        + f"\n新章节：第 {chapter_number} 章《{chapter_title}》\n"
        + chapter_text
        + "\n字段示例：\n"
        + _json(example)
    )


def chapter_summary_prompt(
    *,
    chapter_number: int,
    chapter_title: str,
    chapter_text: str,
) -> str:
    example = {
        "chapter": chapter_number,
        "title": chapter_title,
        "summary": "200 字以内摘要",
        "key_events": ["关键事件"],
        "character_changes": {"角色名": "变化"},
        "new_facts": ["新增事实"],
        "foreshadowing_planted": ["新伏笔"],
        "foreshadowing_payoff": ["已兑现伏笔"],
        "open_hooks": ["未解决问题"],
        "payoffs": ["本章兑现"],
        "next_chapter_pressure": "下一章要自然承接的问题",
    }
    return (
        "请把本章压缩成后续写作用摘要。\n"
        + _format_rules("JSON 对象")
        + "摘要要短而准，保留因果、角色变化、设定变化、未解决问题、已兑现内容和下一章压力。\n"
        + f"第 {chapter_number} 章《{chapter_title}》正文：\n"
        + chapter_text
        + "\n字段示例：\n"
        + _json(example)
    )


def outline_batch_prompt(
    *,
    plan_summary: dict[str, Any],
    existing_outlines: list[dict[str, Any]],
    start_chapter: int,
    end_chapter: int,
    total_chapters: int,
) -> str:
    example = [
        {
            "chapter": start_chapter,
            "title": "章名",
            "pov": "视角",
            "purpose": "本章作用",
            "beats": ["开端", "推进", "转折"],
            "stakes": "风险或代价",
            "payoff": "本章兑现",
            "cliffhanger": "本章结尾悬念",
            "volume": 1,
        }
    ]
    return (
        f"请生成第 {start_chapter} 到第 {end_chapter} 章的大纲。\n"
        + _format_rules("JSON 数组")
        + f"数组长度必须等于 {end_chapter - start_chapter + 1}。\n"
        + f"chapter 字段必须从 {start_chapter} 连续递增到 {end_chapter}。\n"
        + "每项必须包含 chapter, title, pov, purpose, beats, stakes, payoff, cliffhanger, volume。\n"
        + f"全书共 {total_chapters} 章。\n"
        + _writing_principles()
        + "故事架构：\n"
        + _json(plan_summary)
        + "\n已有大纲最后几章：\n"
        + _json(existing_outlines[-5:])
        + "\n字段示例：\n"
        + _json(example)
    )
