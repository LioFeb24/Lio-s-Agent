# write_local_file

## Description

向本地文件系统写入内容，支持常见文本与结构化文本格式，包括 `json`、`md`、`txt`、`csv`、`yaml`、`html`。

## When To Use

- 需要让 AI agent 把生成结果落盘到本地文件
- 需要自动按扩展名推断格式并创建父目录
- 需要覆盖、追加或仅在文件不存在时创建文件
- 需要把结构化数据安全地序列化为 `json`、`csv`、`yaml`

## Input

```json
{
  "file_path": "C:/work/output/report.md",
  "content": "# Weekly Report\n\nAll checks passed.",
  "format": "auto",
  "mode": "overwrite",
  "ensure_parent_dirs": true,
  "encoding": "utf-8",
  "newline": "lf"
}
```

字段说明：

- `file_path`：必填，目标文件路径；支持绝对路径，也支持相对路径
- `content`：必填，要写入的内容；文本格式会转为字符串，结构化格式会按格式序列化
- `format`：可选，默认 `auto`；可选值 `auto/json/md/markdown/txt/text/csv/yaml/yml/html`
- `mode`：可选，默认 `overwrite`；可选值 `overwrite/append/create`
- `ensure_parent_dirs`：可选，默认 `true`；为 `true` 时自动创建父目录
- `encoding`：可选，默认 `utf-8`
- `newline`：可选，默认 `auto`；可选值 `auto/lf/crlf`
- `json_indent`：可选，默认 `2`；仅 `json` 生效
- `csv_delimiter`：可选，默认 `,`；仅 `csv` 生效
- `csv_include_header`：可选，默认 `true`；当 `content` 为对象数组时控制是否输出表头

格式行为：

- `json`：推荐传入对象或数组，会被格式化为 JSON 文本
- `csv`：支持字符串、对象数组、数组数组
- `yaml`：支持字符串直写，也支持对象/数组自动转 YAML
- `md/txt/html`：按普通文本写入

## Output

```json
{
  "tool_name": "write_local_file",
  "resolved_path": "C:/work/output/report.md",
  "format": "md",
  "mode": "overwrite",
  "existed_before": false,
  "bytes_written": 34,
  "encoding": "utf-8",
  "created_parent_dirs": true,
  "message": "Wrote file successfully."
}
```

字段说明：

- `resolved_path`：实际写入的绝对路径
- `format`：最终使用的规范格式名
- `mode`：实际写入模式
- `existed_before`：写入前文件是否已存在
- `bytes_written`：本次写入的字节数
- `created_parent_dirs`：是否在本次执行中创建了父目录
- `message`：结果说明

## Constraints

- `append` 不允许用于 `json`，以避免生成无效 JSON 文件
- `create` 模式下若目标文件已存在会直接报错
- `format=auto` 时会优先根据文件扩展名推断格式，未知扩展名回退为 `txt`
- 工具只处理文本类文件，不处理二进制文件

## Tool Command Example

```json
{
  "name": "write_local_file",
  "args": {
    "file_path": "C:/work/data/users.json",
    "content": [
      {
        "id": 1,
        "name": "Alice"
      }
    ],
    "format": "json",
    "mode": "overwrite"
  }
}
```

## Notes

- 相对路径会优先相对于 `context` 中可用的工作目录解析，否则相对于当前进程目录
- `csv` 追加写入对象数组时，若目标文件已非空，默认不会重复写入表头
- `yaml` 在没有第三方依赖时也可工作，工具内置了基础 YAML 序列化逻辑
