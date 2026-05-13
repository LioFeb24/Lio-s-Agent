# get_current_time

## Description

返回指定 IANA 时区的当前时间，输出稳定的标准化 JSON，可作为其他工具的设计范本。

## When To Use

- 需要获取某个地区当前本地时间
- 需要带时区偏移的标准时间字符串
- 需要给后续流程提供可解析的时间 JSON

## Input

```json
{
  "timezone": "Asia/Shanghai"
}
```

字段说明：

- `timezone`：必填，IANA 时区名，例如 `UTC`、`Asia/Shanghai`、`America/New_York`

## Output

```json
{
  "tool_name": "get_current_time",
  "timezone": "Asia/Shanghai",
  "timezone_abbreviation": "CST",
  "utc_offset": "+08:00",
  "current_time": "2026-04-29T21:30:45+08:00",
  "local_time": {
    "iso8601": "2026-04-29T21:30:45+08:00",
    "rfc3339": "2026-04-29T21:30:45+08:00",
    "date": "2026-04-29",
    "time": "21:30:45"
  },
  "utc_time": {
    "iso8601": "2026-04-29T13:30:45+00:00",
    "rfc3339": "2026-04-29T13:30:45+00:00"
  },
  "unix_timestamp": 1777469445
}
```

## Constraints

- 仅接受 IANA 时区名
- 若时区无效，抛出明确错误
- 输出必须保持稳定字段名，便于 LLM 和程序二次解析
- 顶层 `current_time` 为兼容字段，等价于 `local_time.iso8601`

## Tool Command Example

```json
{
  "name": "get_current_time",
  "args": {
    "timezone": "Asia/Shanghai"
  }
}
```

## Notes

- `iso8601` 与 `rfc3339` 当前使用相同格式输出
- 时间精度固定到秒，避免不必要的波动
- 该工具示范了文档、元数据和 Python 入口分离的标准写法
