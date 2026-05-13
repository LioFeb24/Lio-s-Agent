# search_web_with_llm

## Description

通过多个中国大陆通常可访问的搜索源聚合检索网页结果，默认直接返回完整整理文本，并同步写入本地 `txt` 文件。

## When To Use

- 需要按关键词搜索网络信息，并直接把完整整理文本返回给调用方
- 需要把完整搜索结果同步落地到本地文件，便于复用或归档
- 需要优先使用本地通常可访问的中文搜索源
- 需要把网页搜索与整理能力作为 `exec` 中的原子 `tool step`

## Input

```json
{
  "keyword": "人工智能",
  "llm_summary_enabled": true,
  "per_engine_limit": 4,
  "total_limit": 9,
  "write_to_file": true,
  "include_inline_content": false
}
```

字段说明：

- `keyword`：必填，搜索关键词
- `llm_summary_enabled`：可选，是否启用 LLM 整理，默认 `true`
- `per_engine_limit`：可选，单个搜索源最多保留的结果数，默认 `4`
- `total_limit`：可选，聚合去重后最多保留的结果数，默认 `9`
- `write_to_file`：可选，是否默认写入本地 `txt` 文件，默认 `true`
- `include_inline_content`：可选，兼容旧字段；为 `true` 时额外返回结构化搜索结果与原始内容字段，默认 `false`
- `output_dir`：可选，自定义 `txt` 输出目录；未提供时默认写入工具目录下 `outputs`

兼容说明：

- 为兼容旧脚本参数，也接受 `no_llm`
- 若同时传入 `llm_summary_enabled` 与 `no_llm`，以前者为准

## Output

```json
{
  "tool_name": "search_web_with_llm",
  "keyword": "人工智能",
  "llm_summary_enabled": true,
  "write_to_file": true,
  "include_inline_content": false,
  "search_result_count": 3,
  "deep_result_count": 3,
  "search_errors": [],
  "output_file": "f:\\prompt\\TOOLS\\search_web_with_llm\\outputs\\20260429_120000_人工智能.txt",
  "final_report_preview": "...",
  "search_results": [],
  "deep_results": [],
  "raw_report": "",
  "final_report": "这里直接返回完整整理文本",
  "final_report_text": "这里直接返回完整整理文本",
  "llm_summary": ""
}
```

字段说明：

- `output_file`：完整搜索结果同步落地的本地 `txt` 文件路径
- `final_report`：完整最终文本；开启 LLM 时返回整理结果，关闭时返回原始深抓取内容
- `final_report_preview`：最终内容的短预览，便于快速判断是否命中目标
- `final_report_text`：与 `final_report` 等价的完整最终文本，便于兼容旧调用方
- `llm_summary`：LLM 逐页整理结果；仅在 `include_inline_content=true` 时单独展开返回
- `raw_report`：逐个 URL 深抓取后的原始内容整理文本；仅在 `include_inline_content=true` 时单独返回
- `search_results` / `deep_results`：结构化搜索与抓取结果；默认不内联返回

## Constraints

- 默认会直接返回完整文本，同时默认开启本地 `txt` 落地
- `include_inline_content` 仅控制附加结构化字段，不影响 `final_report` 的完整文本返回
- 默认必须开启 LLM 整理；仅在显式传入 `llm_summary_enabled=false` 或 `no_llm=true` 时关闭
- 若所有搜索源都失败，工具会直接抛错，而不是返回伪成功结果
- LLM 整理失败时，会在单页层面回退到原始页面内容，避免整批结果完全丢失

## Tool Command Example

```json
{
  "name": "search_web_with_llm",
  "args": {
    "keyword": "Python 3.12 release",
    "llm_summary_enabled": true,
    "write_to_file": true,
    "include_inline_content": false
  }
}
```

## Notes

- 当前默认策略：直接返回完整整理文本，并同步写入本地文件
- 若需要更多结构化中间结果，再显式传入 `include_inline_content=true`
- 搜索请求与 LLM 请求都显式忽略系统代理，避免本地代理环境影响连接
- LLM 相关配置支持环境变量 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`
- 入口脚本保留 CLI 兼容，但项目内标准调用方式是 `run(args, context)`
