# 项目结构

## 根目录

`小蜜AI网文.exe` 是最终交付给用户的 Windows 可执行文件。打包完成后固定放在项目根目录。

`README.md` 是给普通用户看的傻瓜式使用说明，只讲如何启动、激活、写书、查看作品和排查基础问题。

`LICENSE` 是 CARL JOSEPH LEE 保留全部权利的专有许可证。

`PROJECT_STRUCTURE.md` 记录项目内部结构，供维护时快速理解代码边界。

`issue_license.bat` 是卖家生成限时激活码的入口，接收机器码和授权天数。

`DeepSeekNovelWriter.spec` 是 PyInstaller 单文件打包配置。

`pyproject.toml` 定义 Python 包名、依赖、可选构建依赖和命令入口。

`gui.py` 是桌面 UI 主入口，负责设置页、新建小说页、写作进度页和作品库页。

`novel_engine.py` 是 GUI 与核心写作流水线之间的适配层，负责线程回调、暂停、继续、停止和状态同步。

`novel_project.py` 是单本小说项目的数据模型，负责项目索引、章节读取、作品导出和项目列表扫描。

`license_manager.py` 是 GUI 使用的授权薄壳，负责读取机器码、验证激活码、保存本机授权。

## `novel_writer`

`config.py` 保存 DeepSeek 默认配置。模型固定为 `deepseek-v4-flash`，上下文上限固定为 `900000`，安全上下文预算固定为 `890000`，输出上限固定为 `100000`。

`deepseek_client.py` 是 DeepSeek Chat Completions 流式客户端，只使用 Python 标准库发起请求，负责 SSE 解析、usage 收集、错误处理和重试。

`pipeline.py` 是核心写作流水线，负责新书简介、故事圣经、滚动大纲、章节蓝图、正文生成、扩写、精简、重写、评审、章节摘要、连续性记忆和全文合并。

`prompts.py` 保存内置网文创作提示词，覆盖简介、策划、蓝图、正文、评审、摘要和连续性记忆等阶段。

`context.py` 负责构造每章生成时传给模型的上下文包，只在内存中使用，不向用户项目目录写出具体 API 输入。

`state.py` 保存文件命名、JSON 读写、章节格式、正文合并和 JSON 解析工具。

`license.py` 实现机器码、RSA 签名、激活码编码、激活码解码和本地授权校验。

`license_admin.py` 是卖家端激活码签发工具，只签发永久机器码绑定授权。

`errors.py` 保存项目异常类型。

## `scripts`

`build_windows_exe.ps1` 安装构建依赖、可选运行测试、调用 PyInstaller 打包，并把最新 `DeepSeekNovelWriter.exe` 覆盖到项目根目录。

## `packaging`

`windows_desktop_entry.py` 是 PyInstaller 启动入口，设置运行路径后启动 GUI。

## `tests`

`test_context.py` 覆盖上下文预算、摘要合并和上下文打包。

`test_engine_and_pipeline.py` 使用本地 mock SSE 服务验证写作流水线和引擎集成。

`test_license.py` 覆盖机器码、授权文件、激活码编码解码和 GUI 授权薄壳。

`test_project.py` 覆盖项目保存、读取、刷新、导出和标签合并。

`test_state.py` 覆盖文件名、章节标题、纯文本转换和 JSON 解析。

`test_streaming.py` 覆盖 DeepSeek 流式客户端 payload、SSE 拼接、JSON 模式和错误处理。

## 运行时输出

用户作品默认写入 `%USERPROFILE%\dsbook_projects`。

本机设置默认写入 `%USERPROFILE%\.dsbook`。

打包临时目录 `build` 和 PyInstaller 临时输出 `dist` 都不是交付物，构建完成后 EXE 会移动到根目录。
