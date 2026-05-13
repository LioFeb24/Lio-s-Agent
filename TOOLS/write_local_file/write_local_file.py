import argparse
import csv
import io
import json
import os
import sys
from pathlib import Path


FORMAT_ALIASES = {
    "markdown": "md",
    "text": "txt",
    "yml": "yaml",
}

TEXT_FORMATS = {"md", "txt", "html"}
STRUCTURED_FORMATS = {"json", "csv", "yaml"}
ALL_FORMATS = TEXT_FORMATS | STRUCTURED_FORMATS

EXTENSION_TO_FORMAT = {
    ".json": "json",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".csv": "csv",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".html": "html",
    ".htm": "html",
}


def _configure_console_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


def _normalize_bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _normalize_newlines(text, newline_style):
    if newline_style == "auto":
        return text

    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if newline_style == "lf":
        return normalized
    if newline_style == "crlf":
        return normalized.replace("\n", "\r\n")
    raise ValueError("newline 仅支持 auto、lf、crlf。")


def _canonical_format(requested_format, file_path):
    raw_format = str(requested_format or "auto").strip().lower()
    if raw_format == "auto":
        suffix = Path(file_path).suffix.lower()
        return EXTENSION_TO_FORMAT.get(suffix, "txt")

    canonical = FORMAT_ALIASES.get(raw_format, raw_format)
    if canonical not in ALL_FORMATS:
        raise ValueError(f"不支持的 format: {requested_format}")
    return canonical


def _find_base_dir(context):
    context = context or {}
    candidates = [
        context.get("cwd"),
        context.get("working_directory"),
        context.get("workspace"),
        context.get("project_root"),
    ]
    for candidate in candidates:
        if candidate:
            return os.path.abspath(str(candidate))
    return os.getcwd()


def _resolve_path(file_path, context):
    if not str(file_path or "").strip():
        raise ValueError("write_local_file 需要提供 file_path。")

    raw_path = os.path.expanduser(str(file_path).strip())
    if os.path.isabs(raw_path):
        return os.path.abspath(raw_path)
    return os.path.abspath(os.path.join(_find_base_dir(context), raw_path))


def _is_scalar(value):
    return value is None or isinstance(value, (str, int, float, bool))


def _yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)

    if value == "":
        return '""'
    if "\n" in value:
        indented = "\n".join(f"  {line}" for line in value.splitlines())
        return "|\n" + indented

    safe_plain = True
    for char in [":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "%", "@", "`"]:
        if char in value:
            safe_plain = False
            break
    lowered = value.lower()
    if lowered in {"true", "false", "null", "~"}:
        safe_plain = False
    if safe_plain and value.strip() == value:
        return value
    return json.dumps(value, ensure_ascii=False)


def _yaml_dump(value, indent=0):
    prefix = " " * indent
    if _is_scalar(value):
        return prefix + _yaml_scalar(value)

    if isinstance(value, dict):
        if not value:
            return prefix + "{}"
        lines = []
        for key, item in value.items():
            key_text = str(key)
            if _is_scalar(item):
                lines.append(f"{prefix}{key_text}: {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}{key_text}:")
                lines.append(_yaml_dump(item, indent + 2))
        return "\n".join(lines)

    if isinstance(value, (list, tuple)):
        if not value:
            return prefix + "[]"
        lines = []
        for item in value:
            if _is_scalar(item):
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
            else:
                lines.append(f"{prefix}-")
                lines.append(_yaml_dump(item, indent + 2))
        return "\n".join(lines)

    return prefix + json.dumps(value, ensure_ascii=False)


def _serialize_json(content, indent):
    return json.dumps(content, ensure_ascii=False, indent=indent) + "\n"


def _serialize_csv(content, delimiter, include_header):
    if isinstance(content, str):
        return content

    rows = content
    if isinstance(content, dict):
        rows = [content]
    if not isinstance(rows, (list, tuple)):
        raise ValueError("csv 格式的 content 需要是字符串、对象数组或数组数组。")

    buffer = io.StringIO()
    first_row = rows[0] if rows else None

    if isinstance(first_row, dict):
        fieldnames = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("csv 对象数组中不能混用非对象行。")
            for key in row.keys():
                if key not in fieldnames:
                    fieldnames.append(key)
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, delimiter=delimiter)
        if include_header and fieldnames:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()

    writer = csv.writer(buffer, delimiter=delimiter)
    for row in rows:
        if isinstance(row, (list, tuple)):
            writer.writerow(row)
        else:
            writer.writerow([row])
    return buffer.getvalue()


def _serialize_yaml(content):
    if isinstance(content, str):
        return content if content.endswith("\n") else content + "\n"
    return _yaml_dump(content) + "\n"


def _serialize_text(content):
    return str(content)


def _serialize_content(format_name, content, options):
    if format_name == "json":
        return _serialize_json(content, options["json_indent"])
    if format_name == "csv":
        return _serialize_csv(
            content,
            delimiter=options["csv_delimiter"],
            include_header=options["csv_include_header"],
        )
    if format_name == "yaml":
        return _serialize_yaml(content)
    if format_name in TEXT_FORMATS:
        return _serialize_text(content)
    raise ValueError(f"未知格式: {format_name}")


def execute_write(
    file_path,
    content,
    format="auto",
    mode="overwrite",
    ensure_parent_dirs=True,
    encoding="utf-8",
    newline="auto",
    json_indent=2,
    csv_delimiter=",",
    csv_include_header=True,
    context=None,
):
    resolved_path = _resolve_path(file_path, context)
    format_name = _canonical_format(format, resolved_path)
    write_mode = str(mode or "overwrite").strip().lower()
    if write_mode not in {"overwrite", "append", "create"}:
        raise ValueError("mode 仅支持 overwrite、append、create。")

    existed_before = os.path.exists(resolved_path)
    if write_mode == "create" and existed_before:
        raise FileExistsError(f"目标文件已存在，create 模式拒绝覆盖: {resolved_path}")
    if write_mode == "append" and format_name == "json":
        raise ValueError("append 不支持 json，以避免生成无效 JSON 文件。")

    parent_dir = os.path.dirname(resolved_path)
    created_parent_dirs = False
    if parent_dir and not os.path.exists(parent_dir):
        if not _normalize_bool(ensure_parent_dirs, True):
            raise FileNotFoundError(f"父目录不存在: {parent_dir}")
        os.makedirs(parent_dir, exist_ok=True)
        created_parent_dirs = True

    csv_include_header_value = _normalize_bool(csv_include_header, True)
    if (
        format_name == "csv"
        and write_mode == "append"
        and existed_before
        and os.path.getsize(resolved_path) > 0
        and not isinstance(content, str)
    ):
        csv_include_header_value = False

    rendered = _serialize_content(
        format_name,
        content,
        {
            "json_indent": int(json_indent),
            "csv_delimiter": str(csv_delimiter or ","),
            "csv_include_header": csv_include_header_value,
        },
    )
    rendered = _normalize_newlines(rendered, str(newline or "auto").strip().lower())
    payload = rendered.encode(str(encoding or "utf-8"))

    file_mode = {
        "overwrite": "wb",
        "append": "ab",
        "create": "xb",
    }[write_mode]
    with open(resolved_path, file_mode) as file_obj:
        file_obj.write(payload)

    return {
        "tool_name": "write_local_file",
        "resolved_path": resolved_path,
        "format": format_name,
        "mode": write_mode,
        "existed_before": existed_before,
        "bytes_written": len(payload),
        "encoding": str(encoding or "utf-8"),
        "created_parent_dirs": created_parent_dirs,
        "message": "Wrote file successfully.",
    }


def run(args: dict, context: dict) -> dict:
    args = args or {}
    return execute_write(
        file_path=args.get("file_path"),
        content=args.get("content"),
        format=args.get("format", "auto"),
        mode=args.get("mode", "overwrite"),
        ensure_parent_dirs=args.get("ensure_parent_dirs", True),
        encoding=args.get("encoding", "utf-8"),
        newline=args.get("newline", "auto"),
        json_indent=args.get("json_indent", 2),
        csv_delimiter=args.get("csv_delimiter", ","),
        csv_include_header=args.get("csv_include_header", True),
        context=context or {},
    )


def _parse_cli_args():
    parser = argparse.ArgumentParser(description="Write local text files for AI agents.")
    parser.add_argument(
        "--args-json",
        help="JSON string representing tool args. Example: {\"file_path\":\"a.txt\",\"content\":\"hello\"}",
    )
    parser.add_argument(
        "--args-file",
        help="Path to a JSON file that contains tool args.",
    )
    return parser.parse_args()


def _load_cli_payload(parsed_args):
    if parsed_args.args_json:
        return json.loads(parsed_args.args_json)
    if parsed_args.args_file:
        with open(parsed_args.args_file, "r", encoding="utf-8") as file_obj:
            return json.load(file_obj)
    raise ValueError("请提供 --args-json 或 --args-file。")


def main():
    _configure_console_output()
    parsed_args = _parse_cli_args()
    payload = _load_cli_payload(parsed_args)
    result = run(payload, {})
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _configure_console_output()
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
