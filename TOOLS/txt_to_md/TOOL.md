# txt_to_md

## Description

读取本地 `txt` 文件并生成对应的 `md` 文件，输出稳定的结构化 JSON，适合作为 `exec` 中的原子文件转换工具。

## When To Use

- 需要把已有纯文本文件快速转成 Markdown 文件
- 需要为转换结果自动生成同名 `.md` 文件
- 需要给转换后的 Markdown 添加标题
- 需要将转换结果提供给后续 `read_text`、`write_local_file` 或其他 tool step 继续处理

## Input

```json
{
  "source_file_path": "docs/notes.txt",
  "output_file_path": "docs/notes.md",
  "title": "会议纪要",
  "heading_level": 1,
  "encoding": "utf-8",
  "output_encoding": "utf-8",
  "newline": "lf",
  "overwrite": true
}
```

字段说明：

- `source_file_path`：必填，源 `txt` 文件路径；支持绝对路径和相对路径
- `output_file_path`：可选，目标 `md` 文件路径；未提供时默认与源文件同目录同名改为 `.md`
- `title`：可选，写入文件顶部的 Markdown 标题
- `heading_level`：可选，范围 `1-6`，默认 `1`；仅在提供 `title` 时生效
- `encoding`：可选，源文件读取编码，默认 `utf-8`
- `output_encoding`：可选，目标文件写入编码，默认与 `encoding` 一致
- `newline`：可选，默认 `auto`；可选值 `auto/lf/crlf`
- `overwrite`：可选，默认 `true`；为 `false` 时若目标文件已存在会直接报错

## Conversion Behavior

- 连续普通文本行会合并为同一段落，段内以空格连接
- 空行会作为段落分隔
- 以 `-`、`*`、`+`、`1.` 等开头的列表项会保留为独立 Markdown 列表行
- 已经是 Markdown 标题形式的 `#` 行会原样保留
- 若提供 `title`，会在最顶部插入对应级别的 Markdown 标题，并与正文之间保留一个空行

## Output

```json
{
  "tool_name": "txt_to_md",
  "source_path": "C:/work/docs/notes.txt",
  "output_path": "C:/work/docs/notes.md",
  "title_applied": true,
  "heading_level": 1,
  "overwritten": false,
  "line_count": 12,
  "char_count": 248,
  "bytes_written": 256,
  "encoding": "utf-8",
  "output_encoding": "utf-8",
  "message": "Converted txt to md successfully."
}
```

字段说明：

- `source_path`：源文件绝对路径
- `output_path`：生成的 Markdown 文件绝对路径
- `title_applied`：是否成功应用标题
- `heading_level`：实际使用的标题级别；未提供标题时为 `0`
- `overwritten`：目标文件在本次写入前是否已存在
- `line_count`：读取到的源文件总行数
- `char_count`：生成 Markdown 文本的字符数
- `bytes_written`：本次写入的字节数

## Constraints

- 只处理文本文件，不处理二进制内容
- 源文件必须存在
- 默认按 `utf-8` 读取；若源文件不是该编码，需要显式指定 `encoding`
- 输出文件扩展名不强制要求为 `.md`，但默认推导结果会使用 `.md`

## Tool Command Example

```json
{
  "name": "txt_to_md",
  "args": {
    "source_file_path": "meeting/raw_notes.txt",
    "title": "周会记录",
    "heading_level": 2
  }
}
```

## Notes

- 相对路径会优先相对于 `context` 中可用工作目录解析，否则相对于当前进程目录
- 该工具不会尝试做复杂语义改写，只做稳定的文本到 Markdown 结构整理
- 若需要更复杂的排版，可在转换后继续用其他 tool 对生成的 `.md` 做二次编辑
