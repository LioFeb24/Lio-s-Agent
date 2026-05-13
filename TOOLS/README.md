# TOOLS 目录规范

`TOOLS` 用于放置供 LLM 在 `tool` step 中直接调用的项目级工具。

## 设计目标

- 标准化：每个工具都使用同一套目录结构
- 可发现：LLM 可先通过 `list_tools` / `read_tool` 了解工具
- 可执行：执行器会自动扫描 `TOOLS/*/tool.json` 并注册工具
- 可复用：单个工具目录即可作为后续新工具的模板

## 标准目录结构

```text
TOOLS/
└─ <tool_name>/
   ├─ TOOL.md
   ├─ tool.json
   └─ <entry_file>.py
```

说明：

- `TOOL.md`：给人和 LLM 看的说明文档，建议写用途、输入、输出、约束、示例
- `tool.json`：机器可读元数据，决定注册名、别名、入口文件、输入输出 schema
- `<entry_file>.py`：真正执行逻辑，默认入口函数为 `run(args, context)`

## 当前调用方式

在 `/exec` 计划中的 `tool` step 里使用 JSON：

```json
{
  "id": "step_1",
  "title": "获取上海时间",
  "kind": "tool",
  "command": "{\"name\":\"get_current_time\",\"args\":{\"timezone\":\"Asia/Shanghai\"}}",
  "verify": "stdout 返回有效 JSON，且 timezone 为 Asia/Shanghai"
}
```

## 自动注册规则

- 执行器启动时会扫描 `TOOLS` 下所有包含 `tool.json` 的子目录
- `tool.json.name` 会作为规范工具名
- `tool.json.aliases` 中的别名也会一并注册
- `tool.json.entry.file` + `tool.json.entry.function` 决定执行入口

## Python 入口约定

入口函数签名：

```python
def run(args: dict, context: dict):
    ...
```

约定：

- `args`：来自 `tool.command.args` 的参数对象
- `context`：执行器传入的上下文，包含当前 tool 元数据和项目路径
- 返回 `dict` / `list` 时会自动转成 JSON 字符串
- 返回 `str` 时会直接作为工具输出
- 抛异常时本次 step 视为失败

## 推荐命名约定

- 目录名：`snake_case`
- `tool.json.name`：与目录名一致
- 别名：短而明确，避免与内置工具重名
- 输出：优先返回稳定 JSON，而不是自然语言段落

## 内置发现工具

- `list_tools`：列出当前项目全部标准工具
- `read_tool`：读取指定工具的完整元数据和说明

建议 LLM 在首次使用项目自定义工具前，先调用一次 `list_tools`，必要时再调用 `read_tool`。
