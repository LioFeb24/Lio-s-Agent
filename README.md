# AI Agent

这是一个本地 `ai-agent` 示例项目，当前同时支持终端版与 GUI 版两种入口：

- 启动时从 `config.json` 读取用户名并恢复未结束会话
- 启动时拼接全部历史记忆作为长期上下文
- 对话过程中持续拼接当前会话上下文
- 主对话模型支持显式流式输出
- 可显示深度思考内容
- 从 `instruction.json` 读取并精确匹配 `/xxx` 指令
- 输入 `/end` 时结束会话并生成摘要记忆
- 输入 `/rm` 时删除当前用户全部会话记录
- 输入 `/exec <任务内容>` 时进入独立的本地执行工作流
- `/exec` 会自动兼容常见工具别名，如 `run_command` / `execute_command` / `list_files`，并统一归一化到内部工具
- `/exec` 现支持扫描项目级 `TOOLS` 目录，并把标准化自定义工具注册给 LLM 在 `tool` step 中直接调用
- 每个 session 只记录开始时间和结束时间，不再为每条消息单独记录时间
- 保留原有 `ai_agent.py` 终端入口，并新增 `GUI.py` 图形界面入口
- `GUI.py` 仅负责可视化框架，业务组件统一由 `core` 目录提供

## 项目结构

```text
f:\prompt
├─ ai_agent.py
├─ GUI.py
├─ config.json
├─ instruction.json
├─ usage_format_llm_output.md
├─ core
│  ├─ __init__.py
│  ├─ agent_runtime.py
│  ├─ chat_service.py
│  ├─ cli.py
│  ├─ command_handler.py
│  ├─ constants.py
│  ├─ exec_service.py
│  ├─ file_utils.py
│  ├─ format_llm_output.py
│  ├─ get_config.py
│  ├─ instruction_loader.py
│  ├─ llm_api.py
│  ├─ memory_manager.py
│  ├─ prompt_builder.py
│  ├─ sendbox
│  │  ├─ __init__.py
│  │  └─ cube_sandbox.py
│  └─ session_manager.py
├─ EXEC
│  ├─ plans
│  ├─ scripts
│  └─ results
├─ TOOLS
├─ MEMORY
├─ session_state
├─ get_config.py
└─ llm_api.py
```

说明：

- `ai_agent.py`：终端入口文件，同时保留兼容导出，真正业务实现在 `core`
- `GUI.py`：图形界面入口，仅负责可视化与事件分发，通过 `core.agent_runtime` 调用业务组件
- `core`：项目核心实现目录，承载配置、模型调用、组件分层与 CLI 逻辑
- `config.json`：模型配置，包含 `summary` 和 `main_llm`
- `instruction.json`：指令表，程序会读取全部 `instruction` 字段进行匹配
- `usage_format_llm_output.md`：`core/format_llm_output.py` 的独立使用说明
- `EXEC/plans`：保存 `/exec` 生成的 JSON 计划文件
- `EXEC/scripts`：保存 `/exec` 过程中落地的本地脚本文件
- `EXEC/results`：保存 `/exec` 的执行结果与最终确认 JSON
- `TOOLS`：项目级 LLM 工具目录，每个工具使用 `tool.json` + `TOOL.md` + Python 入口脚本的标准结构
- `MEMORY`：已结束会话的摘要记忆目录
- `session_state`：统一的 session 数据目录，保存完整会话历史与当前会话指针
- `get_config.py` / `llm_api.py`：顶层兼容壳层，真实实现已经迁移到 `core`

## GUI 说明

`GUI.py` 使用 `customtkinter` 构建图形界面，美术风格参考 `sample.py` 的浅蓝卡片式布局。

注意：

- `sample.py` 不作为运行入口，只用于迁移 GUI 美术风格
- `GUI.py` 才是当前项目新增的图形界面入口
- 原有 `ai_agent.py` 终端入口仍然保留
- `GUI.py` 不直接实现 agent 业务逻辑，只调用 `core.agent_runtime` 中的运行时组件
- 当前核心运行时组件为 `AgentRuntime`

## 组件分层

当前核心实现已经拆分到 `core` 目录，主要组件如下：

- `SessionManager`：负责活动会话的创建、恢复、保存、归档与删除
- `MemoryManager`：负责归档记忆的读取与上下文拼接
- `CommandHandler`：负责指令表加载与 `/xxx` 指令分类
- `ChatService`：负责提示词构造、模型调用、流式输出与思考回调连接
- `ExecService`：负责 `/exec` 的任务规划、脚本生成、命令执行与完成确认
- `ExecService` 同时负责 `/exec` step 的工具归一化、失败修复重试与执行报告输出，避免模型生成未注册工具名时直接中断
- `core/sendbox`：沙箱执行适配层，当前内置 `CubeSandbox` 适配器，用于把 `/exec` 的 shell / python / file / tool step 切换到安全沙箱
- `format_llm_output.py`：统一的文件格式处理系统，负责常见结构化数据、代码、文档、表格、配置文本的 format / parse / validate，并兼容 LLM JSON 清洗
- `AgentRuntime`：作为编排层，对 CLI 与 GUI 暴露统一调用接口
- `cli.py`：承载终端版主循环，`ai_agent.py` 只负责调用它
- `core/get_config.py`：负责读取本地配置
- `core/llm_api.py`：负责统一封装模型调用

额外说明：

- 当前凡是“明确要求 LLM 输出 JSON”的业务方法，都会先经过 `core/format_llm_output.py` 做一层格式化保护，再进入 JSON 解析
- `/exec` 的计划生成与结果确认阶段，除了严格 JSON，也已支持自动识别 YAML / TOML / XML 以及 Markdown 代码块中的结构化内容，并归一化为统一内部结构
- 这层保护可兼容诸如“按照要求输出 json 如下：{...}”或代码块包裹 `json{...}` 之类的随机输出

这样做的好处：

- CLI 与 GUI 共用同一套业务能力
- GUI 层只保留界面和事件分发
- 顶层入口文件保持稳定，不影响原有使用方式
- 后续新增指令、替换记忆策略或调整模型调用时，修改范围更集中

## 配置说明

当前 `config.json` 中的模型配置结构如下：

```json
{
    "agent": {
        "system": "你是一个专业的助手，能够回答用户的问题。",
        "user": "一个使用你助手的用户"
    },
    "llm": {
        "summary": {
            "key": "你的摘要模型 key",
            "model": "deepseek-v4-pro",
            "stream": false
        },
        "main_llm": {
            "key": "你的主对话模型 key",
            "model": "deepseek-v4-pro",
            "stream": true,
            "show_reasoning": true,
            "reasoning_dim": true
        },
        "intent_router": {
            "key": "你的分流辅助模型 key",
            "model": "deepseek-v4-pro",
            "stream": false
        }
    },
    "exec": {
        "retry_limit": 3,
        "max_steps": 20,
        "max_expand_depth": 3
    },
    "sandbox": {
        "enabled": false,
        "provider": "cubesandbox",
        "backend": "e2b",
        "api_key": "",
        "domain": "",
        "template": "",
        "timeout_seconds": 600,
        "command_timeout_seconds": 120,
        "workspace_root": "/workspace",
        "sync_project_on_start": true,
        "sync_back_to_host": false,
        "kill_after_run": true,
        "allow_external_paths": false,
        "max_sync_files": 200,
        "max_file_size_kb": 256,
        "sync_include": ["*.py", "*.json", "*.md", "*.txt"],
        "sync_ignore": ["env/**", ".git/**", "__pycache__/**", "EXEC/**", "MEMORY/**", "session_state/**", "*.pyc"],
        "envs": {}
    }
}
```

说明：

- `llm.summary`：用于会话结束时生成摘要
- `llm.summary.stream`：控制摘要模型是否流式输出，通常保持 `false`
- `llm.main_llm`：用于正常对话
- `llm.main_llm.stream`：控制主对话模型是否显式流式输出，终端交互建议设为 `true`
- `llm.main_llm.show_reasoning`：控制是否显示深度思考内容
- `llm.main_llm.reasoning_dim`：控制是否以较弱化样式显示思考内容；终端中用于近似“小一号”，GUI 中会直接以更小字号显示
- `llm.intent_router`：用于 chat / exec 分流判断的辅助 LLM，输入为最近 10 轮对话 JSON，只输出 `{"way":"chat"}` 或 `{"way":"exec"}`
- `agent.user`：当前终端会话使用的本地用户名，程序启动时直接读取，不再交互输入
- `exec.retry_limit`：step 验证失败后的自动修复重试次数，默认 `3`
- `exec.max_steps`：整个 exec 流程允许存在的最大 step 数量，默认 `20`
- `exec.max_expand_depth`：动态子任务拆解的最大深度，默认 `3`
- `sandbox.enabled`：是否启用 CubeSandbox 沙箱执行，默认 `false`
- `sandbox.domain`：CubeSandbox 暴露的 E2B 兼容域名
- `sandbox.api_key`：访问沙箱服务所需的 API Key
- `sandbox.template`：可选的沙箱模板名或 ID
- `sandbox.workspace_root`：沙箱内项目工作目录根路径
- `sandbox.sync_project_on_start`：执行前是否把当前项目快照同步到沙箱
- `sandbox.sync_back_to_host`：是否允许把沙箱修改结果回写到宿主机，默认关闭以优先保证安全
- `sandbox.kill_after_run`：任务结束后是否自动销毁沙箱

## 指令机制

程序会先读取 `instruction.json`，递归提取所有 `instruction` 字段，建立指令表。

当前示例：

```json
{
    "end": {
        "instruction": "/end",
        "info": "结束"
    },
    "rm": {
        "instruction": "/rm",
        "info": "删除当前用户全部会话记录"
    },
    "exec": {
        "instruction": "/exec",
        "info": "进入本地执行流程，实际使用格式为 /exec <任务内容>"
    },
    "session": {
        "instruction": "/session",
        "info": "会话管理，使用 /session list 或 /session <session_id>"
    }
}
```

规则如下：

- 用户输入以 `/` 开头时，先按指令匹配
- 只有与 `instruction` 字段内容完全一致时，才执行对应程序逻辑
- 如果是未知指令，不会发送给模型
- 如果不是指令，才进入 `call_llm`
- `/exec` 是独立分支，必须使用 `/exec <任务内容>` 才会进入本地执行流程
- `/session` 是独立分支，支持列出会话与切换会话

## Chat / Exec 分流

未显式输入 `/exec` 时，系统不会再使用简单的字符串关键词匹配来决定是否自动执行。

现在的分流方式为：

- 读取当前 session 最近 10 轮对话
- 组装为 JSON 输入给 `llm.intent_router`
- 要求辅助 LLM 只输出：

```json
{
    "way": "chat"
}
```

或：

```json
{
    "way": "exec"
}
```

当 `way="exec"` 时，自动进入 exec 工作流；当 `way="chat"` 时，走普通对话流程。

## /exec 工具规范

`/exec` 中每个 step 只允许使用 `shell`、`python`、`file`、`tool` 四种 `kind`。

其中 `tool` step 当前支持的规范工具名如下：

- `shell`：执行 `args.command` 中的命令。对于任意命令执行，仍然优先推荐直接使用 `kind="shell"`
- `list_dir`：列出目录内容，支持 `path`、`depth`、`offset`、`limit`
- `read_text`：读取文本文件，支持 `path`
- `path_exists`：判断路径是否存在，支持 `path`
- `glob`：按 glob 模式匹配路径，支持 `path`、`pattern`

为降低模型规划抖动导致的失败，执行器会自动兼容以下常见别名：

- `run_command`、`execute_command`、`command`、`powershell`、`local_shell` -> `shell`
- `list_files`、`list_directory`、`dir`、`ls` -> `list_dir`
- `read_file`、`cat_file`、`open_file` -> `read_text`
- `exists`、`file_exists` -> `path_exists`
- `glob_files`、`find_files` -> `glob`

额外兼容策略：

- 如果模型把 `tool.command` 错误地直接输出成原始命令文本，执行器会自动降级为 `shell` 工具调用
- 本地执行与 CubeSandbox 沙箱执行都会复用同一套工具别名归一化规则
- 当工具名仍然无法识别时，错误信息会直接返回当前支持的规范工具列表，方便下一轮修复
- 当任务属于“读取文件内容”“列目录”“返回命令输出”这类直接查询型场景时，聊天区会优先展示真实 `stdout` / 文件内容，而不是只展示结构化执行报告

建议：

- 任意命令执行优先用 `kind="shell"`，不要把普通命令包成未知 `tool.name`
- 目录浏览优先用 `list_dir`，读文件优先用 `read_text`，不要创造新的同义工具名
- 如果 step 需要验证目录结构，优先给出明确 `verify`，例如“输出中包含 `core/exec_service.py`”

## /exec 常见故障

### 1. 报错“未注册的工具”

当前版本会自动兼容大部分高频别名，因此再出现该报错时，通常意味着：

- 模型生成了真正不存在的工具名
- `tool.args` 结构缺字段，例如 `shell` 缺少 `command`
- 任务本质上应该使用 `kind="shell"` 或 `kind="file"`，却被错误生成为 `tool`

排查建议：

- 先查看 `EXEC/results/*_report.md` 中的“关键步骤”
- 再查看对应 `*_result.json` 里的 `command`、`stderr` 与 `step_verification.reason`
- 如果是目录或文件检查类任务，优先改用规范工具名

## 会话与记忆

### 1. 启动会话

启动程序后会直接读取 `config.json` 中的 `agent.user` 作为用户名，并从 `session_state` 目录恢复当前指针所指向的 session。

- 每个 session 都有独立 JSON 文件，内部保存完整 `history`
- 当前选中的 session 由单独的指针文件记录
- 若不存在可恢复的当前 session，则自动创建新会话

### 2. 对话过程

每轮调用模型时，程序会拼接两部分上下文：

- 全部历史记忆
- 当前会话历史消息

这样既能保留跨会话信息，也能保持当前轮次上下文连续。

当 `llm.main_llm.stream` 为 `true` 时：

- 终端版会在模型返回过程中边接收边输出内容
- GUI 版会在界面中流式刷新回答内容

当 `llm.main_llm.show_reasoning` 为 `true` 时：

- 终端版会在正式回答前额外输出“思考”内容
- GUI 版会在独立的“深度思考”区域中展示内容

说明：

- 纯终端界面通常不能真正控制字号，因此“字号小一号”这里只能近似为较淡、较弱化的显示效果
- GUI 中的深度思考区域会直接使用更小字号显示
- 如果当前终端不支持弱化样式，思考内容仍会正常显示，只是视觉效果可能与普通文本接近

当前 session 文件会保留：

- `session_id`
- `title`
- `summary_title`
- `user`
- `start_time`
- `end_time`
- `archived`
- `memory_file`
- `history`

其中 `history` 只保存消息内容与角色，不再保存每条消息的单独时间，避免无效占用上下文窗口。

### 3. session 切换与恢复

GUI 与 CLI 共用同一套 session 数据源。

- GUI 中点击左侧 session 列表项后，会立即加载该 session 的完整聊天记录，并在右侧按顺序重建
- 左侧 session 列表会优先显示归档时生成的 `summary_title`，日期时间放到次级信息行，降低视觉权重
- GUI 顶部“新建会话”按钮现在等价于 `/session new`，不再隐式归档当前 session
- CLI 中可使用 `/session list` 查看所有 session
- CLI 与 GUI 现在都支持 `/session new`，可在不归档当前会话的前提下直接新建并切换到一个新的并行 session
- CLI 中可使用 `/session <session_id>` 切换到指定 session，并立即打印完整历史消息
- 切换成功后，后续新消息会直接基于该 session 的完整 `history` 继续对话，而不仅仅是界面显示恢复
- 每次用户消息和 AI 回复都会写回当前 session 的 `history`

当前版本的并发规则如下：

- 多个未归档 session 可以同时存在，并且可以分别继续对话
- LLM / `/exec` 请求现在绑定到发起时的 `session_id`，后续即使切换到别的 session，也不会串到当前选中会话
- GUI 不再因为某个 session 正在调用 LLM 就全局锁死会话切换；可以切到其他空闲 session 继续操作
- 单个 session 在自己的请求完成前，仍然禁止再次向同一 session 发送新消息，避免同一历史被并发写坏
- 删除全部记录等全局破坏性操作，仍会在存在运行中 session 时禁止执行

### 4. 结束会话

当用户输入 `/end` 时：

1. 记录会话结束时间
2. 使用 `llm.summary` 配置生成摘要
3. 将结果写入 `MEMORY` 目录
4. 将当前 session 标记为已归档，但保留完整 history 供后续切换恢复
5. 自动新建一个新的空白 session，并切换过去

归档记忆格式如下：

```json
{
    "summary_title": "十字以内标题",
    "msg": "此字段为摘要内容",
    "time": "会话开始时间 ~ 会话结束时间",
    "user": "用户名"
}
```

摘要模型在结束会话时只调用一次，并固定输出 JSON：

```json
{
    "summary": "摘要主体内容",
    "summary_title": "十字以内标题"
}
```

归档文件名规则如下：

```text
{{user}}{{time}}.json
```

示例：

```text
lio2026-04-27_21-38-48__2026-04-27_21-40-10.json
```

### 5. 异常中断

如果程序被 `Ctrl+C` 或输入流中断：

- 不会结束会话
- 会把当前上下文保存回当前 session 文件
- 下次使用同一用户名启动时会自动恢复

### 6. 删除记录

当用户输入 `/rm` 时：

1. 删除当前用户在 `MEMORY` 中的归档记忆
2. 删除当前用户在 `session_state` 中的全部 session 文件与当前指针文件
3. 删除当前用户在 `EXEC` 目录下的计划、脚本与结果文件
4. 重新创建一个新的空白 session

终端版与 GUI 版都会在执行后自动新建会话并继续可用。

### 7. Exec 流程

当用户输入 `/exec <任务内容>` 时，程序会进入独立的 exec 分支，而不是普通对话分支。

完整流程如下：

1. 接受命令
2. 让模型理解任务并输出结构化编排结果
3. 根据 steps 顺序执行命令或本地脚本
4. 每个 step 执行后都进行 step-level verification
5. 验证失败时先自动修复重试，超过上限后再动态拆解子任务
6. 全部步骤结束后再做最终完成确认

当前 `/exec` 的实现组合为：

- Python：负责核心调度逻辑
- PowerShell / Python / 文件系统 / 工具调用：负责 step 执行
- JSON：负责保存计划、执行结果与最终确认
- 状态机：负责统一驱动 PLAN / EXECUTE / VERIFY_STEP / RETRY_STEP / EXPAND_STEP / VERIFY_FINAL / DONE / FAILED
- CubeSandbox：当 `sandbox.enabled=true` 时，shell / python / file / tool step 会优先在安全沙箱中执行

`/exec` 完成后现在会同时产出两类结果：

- 聊天窗口/终端中的 Markdown 执行报告
- `EXEC/results/<run_id>_report.md` 本地报告文件

发送到聊天窗口/终端的最终报告，优先读取已落盘的 `report.md` 或其它 markdown/txt 报告文件；
若本地报告不存在，再回退为运行时内存中构造的摘要文本。

报告内容会尽量包含：

- 任务完成状态
- 结果摘要与验证结论
- 关键步骤摘要
- 已生成的脚本文件或文件操作产物
- 当前执行后端与沙箱 ID / 工作目录
- 计划 / 结果 / 确认 / 报告 文件路径

编排结果顶层结构语义要求为：

```json
{
    "task": "原始任务",
    "tool_schema": {},
    "plan": [],
    "workflow": "流程说明",
    "steps": []
}
```

其中 `steps` 支持以下类型：

- `shell`
- `python`
- `file`
- `tool`

执行产物会落盘到：

- `EXEC/plans/*.json`
- `EXEC/scripts/*.py`
- `EXEC/results/*_result.json`
- `EXEC/results/*_verify.json`
- `EXEC/results/*_report.md`

step 级验证会强制输出：

```json
{
    "passed": true,
    "reason": ""
}
```

最终确认阶段内部也采用同样的 `passed/reason` 结构，并在程序对外返回时补充兼容字段：

- `completed`
- `summary`
- `verification`
- `next_action`

状态机规则：

- `PLAN`：生成 plan 与 steps
- `EXECUTE`：顺序执行当前 step
- `VERIFY_STEP`：把 step 定义、command/script_content、returncode、stdout、stderr、step.verify 一并交给主模型验证
- `RETRY_STEP`：验证失败且未超过 `retry_limit` 时，只允许模型修复 `command` / `script_content`
- `EXPAND_STEP`：超过重试上限或模型判断步骤过于复杂时，拆成 2 到 5 个更细粒度子步骤
- `VERIFY_FINAL`：全部步骤完成后，对整个 task 做最终判断
- `DONE` / `FAILED`：输出最终结果

### CubeSandbox 集成说明

当前版本已把 CubeSandbox 接入 `/exec` 执行器层。

- 沙箱组件位于 `core/sendbox`
- 当前适配方式基于 E2B Python SDK 兼容接口
- CubeSandbox 官方支持 E2B SDK drop-in 兼容，因此可通过配置 `sandbox.domain` / `sandbox.api_key` 接入
- CubeSandbox 运行环境需要 KVM 能力的 x86_64 Linux；在 Windows 上通常应通过 WSL2 或远端 Linux 主机部署
- 出于安全考虑，`sandbox.sync_back_to_host` 默认关闭，避免模型在未明确允许时把沙箱修改直接回写宿主机
- 当沙箱开启后，报告中会额外显示执行后端、沙箱 ID、工作目录与同步状态

如果要实际启用，需要先在当前 Python 环境安装 `e2b` SDK，再把 `config.json` 中的 `sandbox.enabled` 改为 `true`。

## 运行方式

### 1. 终端版

在 Windows 终端中运行：

```bash
C:/Users/30848/AppData/Local/Programs/Python/Python312/python.exe f:/prompt/ai_agent.py
```

终端版示例：

```text
欢迎，lio。
新会话已开始。开始时间：2026-04-27 21:38:48
可用指令：/end、/exec、/rm、/session
你：你好
思考：
我需要先用友好的方式回应用户，并保持简洁。
AI：你好，很高兴见到你。
你：/end
本次会话已结束。
会话时间：2026-04-27 21:38:48 ~ 2026-04-27 21:40:10
会话摘要：用户希望构建可交互的终端版 ai-agent，并完成了记忆与会话恢复机制。
已自动新建会话。开始时间：2026-04-27 21:40:10
```

终端版 exec 示例：

```text
你：/exec 统计当前目录下 json 文件数量
[exec] 开始生成执行计划...
[exec] 开始执行第 1 步：统计 json 文件
[exec] 第 1 步执行完成，返回码：0
[exec] 完成状态：已完成
[exec] 结果摘要：已完成当前目录 json 文件统计。
```

终端版 session 管理示例：

```text
你：/session list
[20260428_010203_ab12cd34] 会话 2026-04-28 01:02:03 / 2026-04-28 01:02:03
[20260428_000501_ef56gh78] 修复 GUI 布局 / 2026-04-28 00:05:01
你：/session 20260428_000501_ef56gh78
已切换到会话：20260428_000501_ef56gh78
会话标题：修复 GUI 布局
你：...
AI：...
```

### 2. GUI 版

在 Windows 终端中运行：

```bash
C:/Users/30848/AppData/Local/Programs/Python/Python312/python.exe f:/prompt/GUI.py
```

GUI 版特性：

- 浅蓝卡片式界面，风格参考 `sample.py`
- 采用 2:8 左右分栏布局，左侧为可滚动会话列表，右侧为主聊天界面
- 右侧主界面采用 7:3 上下分割，上部为聊天显示区，下部为输入区
- 聊天显示区使用气泡式布局，用户消息左对齐，AI 消息右对齐
- 思考内容与 exec 过程日志使用更小字号的灰色弱化气泡，和正式回复区分显示
- 顶部不再显示进度条，状态信息通过标题区与提示文案展示
- 输入框位于右侧主界面底部，并随窗口缩放自适应铺满
- 输入框高度已缩减，保留可读性同时减少对聊天显示区的占用
- 快捷键调整为“回车发送，`Ctrl+Enter` 换行”
- 点击左侧 session 列表项时，会立即切换上下文并完整重建该 session 的聊天记录
- 也支持在输入框中直接使用 `/session list` 与 `/session <session_id>` 完成相同的会话管理动作
- 支持按钮直接触发“结束会话”和“删除记录”
- 支持在输入框中直接使用 `/exec <任务内容>` 触发本地执行流程

## 扩展方法

后续如果要增加新指令，可以分两步：

1. 在 `instruction.json` 中新增指令定义
2. 在 `core/command_handler.py` 与对应业务组件中补充逻辑

例如新增 `/help`：

```json
{
    "end": {
        "instruction": "/end",
        "info": "结束"
    },
    "help": {
        "instruction": "/help",
        "info": "显示帮助"
    }
}
```

然后在程序中为 `/help` 增加处理分支即可。

## 当前状态

当前版本已经完成：

- 终端纯文本交互
- GUI 图形界面入口
- 启动时从配置读取用户名
- 主对话模型显式流式输出
- 深度思考内容显示
- 会话开始时间记录
- 会话结束时间记录
- 单条消息时间字段移除
- 记忆摘要归档
- 记忆文件写入 `MEMORY`
- 会话恢复
- 指令优先级匹配
- `/rm` 删除用户全部记录
- README 说明同步
