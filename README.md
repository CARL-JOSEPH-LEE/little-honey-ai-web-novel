# Little Honey AI Web Novel

<p>
  <a href="#little-honey-ai-web-novel"><strong>English</strong></a>
  ·
  <a href="#小蜜ai网文"><strong>简体中文</strong></a>
</p>

Little Honey AI Web Novel is an AI-native long-form web novel engine packaged as a simple Windows desktop app. It is designed for one specific problem: making large language models write serialized fiction with memory, structure, pacing, and continuity instead of producing isolated chapters that drift apart.

Quick start: open the Little Honey AI Web Novel app, generate an activation code with the bundled license issuer, activate the app, enter your DeepSeek API key, and start a novel.

## Why It Exists

Most AI writing tools treat long fiction as a chat box with a larger prompt. That breaks down quickly. Characters forget what happened, promises are planted and never paid off, tone changes between chapters, and the model starts writing a new story every few thousand words.

This project takes a different approach. It treats web novel generation as a controlled production pipeline: concept, story bible, rolling chapter direction, scene blueprint, chapter draft, quality review, rewrite, summary, continuity memory, and manuscript merge. The goal is not to ask the model to “write a novel” once. The goal is to make every chapter inherit the right amount of story state and push the book forward.

## Core Idea

The heart of the project is the combination of two systems:

- A prompt architecture in `novel_writer/prompts.py` that breaks novel writing into editorial stages.
- A context construction engine in `novel_writer/context.py` that decides what the model should remember before each chapter.

Together, they turn a general-purpose language model into a staged web novel writing workflow.

## Prompt System

The prompt system is built around the way serialized Chinese web novels are actually read: fast openings, mobile-friendly paragraphs, visible conflict, chapter-end pull, long-term reader promises, and constant continuity pressure.

Instead of relying on one giant prompt, the project uses specialized prompts for different editorial jobs. The model first creates a concept brief, then a story bible, then a single next-chapter direction. It does not freeze the whole book into a brittle outline at the beginning. Each chapter is planned from the current story state, which makes the book easier to steer over hundreds or thousands of chapters.

The scene blueprint stage is where a vague chapter direction becomes something writable. It asks for concrete scene cards: location, characters, goals, obstacles, turning points, information gains, reader rewards, and scene-end hooks. This gives the prose generation step a narrative skeleton without forcing the final text to feel like a template.

The review prompts act like an internal editor. They score opening hook, continuity, conflict density, reader reward, mobile readability, cliffhanger strength, originality, dialogue, pacing, voice consistency, and anti-cliche behavior. If the chapter is weak, the rewrite prompt feeds the review back into the generation loop and asks for a stronger version.

The summary and continuity prompts are what make the system long-form. After each chapter, the project compresses the chapter into reusable memory: key events, character changes, new facts, planted foreshadowing, paid-off foreshadowing, open hooks, and next-chapter pressure. It also updates timeline, character state, world facts, unresolved threads, promises to pay off, and style notes.

## Context Engine

The context engine is the strongest part of the project.

Before every chapter, it builds a context pack instead of dumping random history into the model. The pack contains the stable concept, the useful parts of the story bible, the current chapter direction, all previous chapter summaries, a smaller recent-summary window, continuity memory, user directions, nearby upcoming pressure, and selected full previous chapters.

The important part is priority. Stable story identity comes first. Long-term memory comes next. Current chapter intent comes next. Only after those are protected does the system spend the remaining token budget on full chapter text, starting from the most recent chapters. That means the model sees both the long arc and the immediate texture of the prose, without wasting the entire context window on raw manuscript.

This creates a layered memory model:

- Story identity: title, premise, promise, hook, world, protagonist, cast, long arc, and style.
- Compressed history: every completed chapter reduced into structured summaries.
- Continuity memory: facts that must survive across the whole book.
- Local texture: recent full chapters when the token budget can afford them.
- Current intent: the chapter being written and the pressure it must resolve or create.

That is the mechanism that lets the app aim at million-word fiction rather than one-off AI prose.

## License Mechanism

The licensing system is also part of the open-source project, not an external black box. It includes the desktop license issuer, activation-code encoding and decoding, machine-code generation, local license storage, signature verification, and activation-code output files.

The machine code is derived from stable machine fingerprints and formatted as a short `NW-...` identifier. The license issuer takes that machine code plus a duration, builds a structured payload with product identity, customer label, machine binding, issued time, and expiry date, then signs the canonical payload with an RSA-style SHA-256 signature. The activation code is a portable `DSBK1.` string that wraps the payload and signature in URL-safe base64.

On the client side, the app decodes the activation code, verifies the signature with the embedded public key, checks product identity, checks that the code belongs to the current machine, checks the expiry date, and writes the accepted license locally. It also keeps a small usage-state file so the local license state can be validated consistently across launches.

The interesting part is that the whole loop is visible: issuer, payload, signature, activation string, verification, local license file, and generated activation-code archive. The project intentionally exposes the complete licensing mechanism so people can study, modify, remove, or replace it under the MIT License.

## What Makes It Interesting

The project is not just a wrapper around an API. It is an attempt to encode a serialized fiction workflow into software.

- Rolling planning keeps the story steerable instead of locking it into a dead outline.
- The golden-chapter bias pushes the opening toward conflict, premise, protagonist, and reader motivation.
- The context budgeter protects important memory before adding raw text.
- The editor loop gives the model a chance to criticize and repair its own chapter.
- The continuity memory turns every chapter into future context instead of disposable output.
- The licensing stack is fully included: issuer, machine binding, signed activation codes, local license verification, and activation-code output.
- The anti-cliche layer gives the system a place to reject stale phrasing and overused genre habits.
- The project format keeps generated novels recoverable, resumable, reviewable, and exportable.

## License

MIT License.

---

# 小蜜AI网文

<p>
  <a href="#little-honey-ai-web-novel"><strong>English</strong></a>
  ·
  <a href="#小蜜ai网文"><strong>简体中文</strong></a>
</p>

小蜜AI网文是一个面向长篇网文创作的 AI 写作引擎，并打包成了简单的 Windows 桌面软件。它解决的不是“让模型写一章”这种小问题，而是让模型在长篇连载中持续记住设定、人物、伏笔、节奏和上一章发生了什么。

快速使用：打开小蜜AI网文，用配套授权码生成器生成授权码并激活，填写 DeepSeek API Key，然后开始创建小说。

## 为什么做这个项目

大多数 AI 写作工具本质上只是一个更大的聊天框。写短内容还行，一旦进入长篇连载，就会开始崩：人物状态漂移，伏笔没人兑现，章节之间没有因果，语气忽然变化，模型像每几章都在重新开一本书。

小蜜AI网文的思路不是让模型一次性“写一本小说”，而是把网文创作拆成一条生产流水线：作品概念、故事圣经、滚动章节方向、场景蓝图、正文草稿、质量评审、重写、章节摘要、连续性记忆、整本文稿合并。每一章都从已有故事状态里自然长出来。

## 核心思路

项目真正的核心是两个系统的组合：

- `novel_writer/prompts.py` 里的分阶段提示词体系。
- `novel_writer/context.py` 里的复杂上下文构筑机制。

前者把“写小说”拆成多个编辑任务，后者决定每章生成前模型到底应该记住什么。

## 提示词系统

提示词系统围绕中文网文的真实阅读习惯设计：黄金三章、手机端阅读、章节追读、人物动机、情节因果、爽点兑现、章末钩子和长篇连续性。

它不是靠一个万能大提示词硬写到底，而是让模型在不同阶段扮演不同工种。先生成作品 brief，再生成开放式故事圣经，再根据已有章节单独规划下一章。它不会一开始就把几百上千章全部写死，因为长篇连载最怕死大纲，真正重要的是能承接、能转向、能继续长。

场景蓝图是从“这一章要干什么”到“这一章具体怎么写”的中间层。它要求每个场景都有地点、角色、目标、阻力、冲突、转折、信息增量、阅读奖励和场景结尾钩子。这样正文生成不是凭空散写，而是沿着可执行的叙事骨架推进。

质量评审相当于内置编辑。它会检查开篇吸引力、前章承接、冲突密度、阅读奖励、连续性、手机端可读性、章末钩子、原创性、对话质量、节奏、声音一致性和反套路。如果分数不够或问题严重，系统会根据评审意见重写，而不是把第一版直接当成最终稿。

摘要和连续性提示词负责把每一章变成未来可用的记忆。章节结束后，系统会提取关键事件、人物变化、新设定、伏笔、兑现、未解决问题和下一章压力；同时更新全书时间线、人物状态、世界事实、开放线索、待兑现承诺和风格注意事项。

## 上下文构筑

这是整个项目最值得吹的部分。

每章生成前，系统不会粗暴地把历史正文全塞给模型，而是构造一个分层上下文包。里面包含作品概念、故事圣经、当前章方向、全部历史章节摘要、最近章节摘要、连续性记忆、用户方向、附近章节压力，以及在预算允许时加入的最近完整章节正文。

关键是优先级。稳定设定先保住，长期记忆先保住，当前章节目标先保住，然后才把剩余 token 预算用于最近完整正文。这样模型既知道这本书长期在讲什么，也能接住最近几章的语气、动作和细节，而不会把上下文窗口浪费在一大坨原始正文上。

它形成的是一种分层记忆模型：

- 故事身份：书名、前提、读者承诺、核心钩子、世界、主角、角色群、长线和文风。
- 压缩历史：每个已完成章节都会变成结构化摘要。
- 连续性记忆：必须跨越全书保持一致的人物、事实、伏笔和承诺。
- 局部质感：预算允许时加入最近完整正文。
- 当前意图：这一章必须解决什么、推进什么、留下什么。

这套机制的目标是让 AI 写作从“一章一章失忆”变成“像一个带编辑记忆的连载系统”。

## 授权码机制

授权系统也是完整开源的一部分，不是外部黑盒。项目里包含桌面授权码生成器、激活码编码和解码、机器码生成、本机授权保存、签名校验，以及生成出来的激活码输出文件。

机器码来自本机相对稳定的机器指纹，并被格式化成简短的 `NW-...` 标识。授权码生成器接收机器码和授权天数，构造包含产品身份、客户标签、机器绑定、签发时间和到期日期的结构化 payload，然后用 RSA 风格的 SHA-256 签名对规范化 payload 进行签名。最终激活码是一个便于复制传播的 `DSBK1.` 字符串，里面用 URL-safe base64 包住 payload 和 signature。

客户端激活时会解码激活码，用内置公钥验证签名，检查产品身份，检查授权是否绑定当前机器，检查到期日期，然后把通过验证的授权写入本机授权文件。它还会维护一个小的本机状态文件，让授权状态在多次启动之间保持一致校验。

最值得看的地方是整条链路都公开：授权码生成器、payload、签名、激活码字符串、客户端校验、本机授权文件、激活码归档输出全部在项目里。这个项目现在按 MIT License 开源，所以授权系统本身也可以被学习、修改、删除或替换。

## 项目亮点

小蜜AI网文不是 API 套壳，而是在尝试把网文生产机制软件化。

- 滚动规划让故事能长期转向，而不是被一次性死大纲锁死。
- 黄金三章策略逼迫开篇尽快出现主角、处境、矛盾和继续阅读理由。
- 上下文预算器优先保护关键记忆，再加入正文细节。
- 质量评审闭环让模型能先自我批评，再按问题重写。
- 连续性记忆让每一章都成为后续章节的素材，而不是一次性输出。
- 授权链路完整开源：授权码生成器、机器绑定、签名激活码、本机授权校验和激活码输出都在项目内。
- 反套路层给系统留下识别陈词滥调和低质桥段的位置。
- 项目文件结构让长篇作品可以恢复、续写、查看和导出。

## License

MIT License.
