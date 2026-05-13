import argparse
import json
import os
import re
import sys
from pathlib import Path


LIST_LINE_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+)")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")


def _configure_console_output():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(errors="backslashreplace")


def _normalize_newlines(text, newline_style):
    if newline_style == "auto":
        return text

    normalized = str(text).replace("\r\n", "\n").replace("\r", "\n")
    if newline_style == "lf":
        return normalized
    if newline_style == "crlf":
        return normalized.replace("\n", "\r\n")
    raise ValueError("newline 仅支持 auto、lf、crlf。")


def _coerce_bool(value, default=True):
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
    raw_path = os.path.expanduser(str(file_path or "").strip())
    if not raw_path:
        raise ValueError("txt_to_md 需要提供 source_file_path。")
    if os.path.isabs(raw_path):
        return os.path.abspath(raw_path)
    return os.path.abspath(os.path.join(_find_base_dir(context), raw_path))


def _resolve_output_path(source_path, output_file_path, context):
    if str(output_file_path or "").strip():
        return _resolve_path(output_file_path, context)
    source = Path(source_path)
    return str(source.with_suffix(".md"))


def _flush_paragraph(buffer, parts):
    if not buffer:
        return
    paragraph = " ".join(item.strip() for item in buffer if item.strip()).strip()
    if paragraph:
        parts.append(paragraph)
    buffer.clear()


def _txt_to_markdown(text):
    normalized_text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized_text.split("\n")
    parts = []
    paragraph_buffer = []
    previous_was_blank = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            _flush_paragraph(paragraph_buffer, parts)
            if parts and not previous_was_blank:
                parts.append("")
            previous_was_blank = True
            continue

        if LIST_LINE_RE.match(line) or HEADING_RE.match(line):
            _flush_paragraph(paragraph_buffer, parts)
            parts.append(line)
            previous_was_blank = False
            continue

        paragraph_buffer.append(line)
        previous_was_blank = False

    _flush_paragraph(paragraph_buffer, parts)

    while parts and parts[-1] == "":
        parts.pop()

    return "\n".join(parts).strip()


def execute_conversion(
    source_file_path,
    output_file_path=None,
    title=None,
    heading_level=1,
    encoding="utf-8",
    output_encoding=None,
    newline="auto",
    overwrite=True,
    context=None,
):
    source_path = _resolve_path(source_file_path, context)
    if not os.path.exists(source_path):
        raise FileNotFoundError(f"源文件不存在: {source_path}")
    if not os.path.isfile(source_path):
        raise ValueError(f"源路径不是文件: {source_path}")

    output_path = _resolve_output_path(source_path, output_file_path, context)
    overwritten = os.path.exists(output_path)
    if overwritten and not _coerce_bool(overwrite, default=True):
        raise FileExistsError(f"目标文件已存在，且 overwrite=false: {output_path}")

    target_encoding = str(output_encoding or encoding or "utf-8")
    with open(source_path, "r", encoding=str(encoding or "utf-8")) as handle:
        source_text = handle.read()

    line_count = len(source_text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    body = _txt_to_markdown(source_text)

    heading = 0
    title_text = str(title or "").strip()
    if title_text:
        heading = int(heading_level or 1)
        if not 1 <= heading <= 6:
            raise ValueError("heading_level 必须在 1 到 6 之间。")
        body = f"{'#' * heading} {title_text}\n\n{body}".strip()

    final_text = _normalize_newlines(body + "\n", str(newline or "auto").strip().lower())

    output_parent = os.path.dirname(output_path)
    if output_parent and not os.path.exists(output_parent):
        os.makedirs(output_parent, exist_ok=True)

    payload = final_text.encode(target_encoding)
    with open(output_path, "wb") as handle:
        handle.write(payload)

    return {
        "tool_name": "txt_to_md",
        "source_path": source_path,
        "output_path": output_path,
        "title_applied": bool(title_text),
        "heading_level": heading,
        "overwritten": overwritten,
        "line_count": line_count,
        "char_count": len(final_text),
        "bytes_written": len(payload),
        "encoding": str(encoding or "utf-8"),
        "output_encoding": target_encoding,
        "message": "Converted txt to md successfully.",
    }


def run(args: dict, context: dict) -> dict:
    args = args or {}
    return execute_conversion(
        source_file_path=args.get("source_file_path"),
        output_file_path=args.get("output_file_path"),
        title=args.get("title"),
        heading_level=args.get("heading_level", 1),
        encoding=args.get("encoding", "utf-8"),
        output_encoding=args.get("output_encoding"),
        newline=args.get("newline", "auto"),
        overwrite=args.get("overwrite", True),
        context=context or {},
    )


def _parse_cli_args():
    parser = argparse.ArgumentParser(description="Convert a local txt file into markdown.")
    parser.add_argument(
        "--args-json",
        help="JSON string representing tool args. Example: {\"source_file_path\":\"a.txt\"}",
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
        with open(parsed_args.args_file, "r", encoding="utf-8") as handle:
            return json.load(handle)
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
