import ast
import configparser
import csv
import io
import json
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    yaml = None

from core.llm_api import call_llm


TYPE_CATEGORY_USAGE = {
    "json": ("Structured Data", "配置文件、数据交换、memory 存储"),
    "yaml": ("Structured Data", "配置文件、数据交换、memory 存储"),
    "xml": ("Structured Data", "配置文件、数据交换、memory 存储"),
    "toml": ("Structured Data", "配置文件、数据交换、memory 存储"),
    "ini": ("Structured Data", "配置文件、数据交换、memory 存储"),
    "python": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "javascript": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "typescript": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "c": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "cpp": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "java": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "go": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "rust": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "bash": ("Programming Languages", "代码生成、脚本执行、CLI 工具"),
    "html": ("Web Formats", "GUI / 前端界面、Web Agent"),
    "css": ("Web Formats", "GUI / 前端界面、Web Agent"),
    "scss": ("Web Formats", "GUI / 前端界面、Web Agent"),
    "jsx": ("Web Formats", "GUI / 前端界面、Web Agent"),
    "tsx": ("Web Formats", "GUI / 前端界面、Web Agent"),
    "markdown": ("Documentation", "聊天输出、报告生成、Prompt 构建"),
    "txt": ("Documentation", "聊天输出、报告生成、Prompt 构建"),
    "rtf": ("Documentation", "聊天输出、报告生成、Prompt 构建"),
    "csv": ("Data Formats", "数据分析、数据存储 / 查询"),
    "tsv": ("Data Formats", "数据分析、数据存储 / 查询"),
    "sql": ("Data Formats", "数据分析、数据存储 / 查询"),
    "dockerfile": ("DevOps / Config", "环境配置、项目部署"),
    "env": ("DevOps / Config", "环境配置、项目部署"),
    "nginx.conf": ("DevOps / Config", "环境配置、项目部署"),
    "requirements.txt": ("DevOps / Config", "环境配置、项目部署"),
    "package.json": ("DevOps / Config", "环境配置、项目部署"),
}

ALIASES = {
    "yml": "yaml",
    "js": "javascript",
    "ts": "typescript",
    "shell": "bash",
    "sh": "bash",
    "md": "markdown",
    "text": "txt",
    ".env": "env",
}

SUFFIX_TO_TYPE = {
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".toml": "toml",
    ".ini": "ini",
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".c": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".sh": "bash",
    ".bash": "bash",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".jsx": "jsx",
    ".tsx": "tsx",
    ".md": "markdown",
    ".txt": "txt",
    ".rtf": "rtf",
    ".csv": "csv",
    ".tsv": "tsv",
    ".sql": "sql",
}

JSON_PREFIX_PATTERN = re.compile(r"^\s*json\s*(?=[\{\[])", flags=re.IGNORECASE)
FENCED_CODE_BLOCK_PATTERN = re.compile(r"```(?P<lang>[a-zA-Z0-9_.+-]*)\n(?P<code>[\s\S]*?)```")


@dataclass
class FormatHandler:
    type_name: str
    usage: str
    formatter: callable
    parser: callable
    validator: callable


def _normalize_type(type_name: str | None) -> str:
    """把外部传入的类型名规整为统一注册名。"""
    text = str(type_name or "").strip().lower()
    return ALIASES.get(text, text)


def _normalize_text(content) -> str:
    """把输入整理为统一文本。"""
    if isinstance(content, bytes):
        return content.decode("utf-8", errors="replace")
    return str(content or "")


def _normalize_newlines(text: str) -> str:
    return _normalize_text(text).replace("\r\n", "\n").replace("\r", "\n")


def _strip_code_fence_markers(text: str) -> str:
    """移除常见 Markdown 代码块包裹与 json 标记。"""
    cleaned = _normalize_newlines(text).strip()
    cleaned = cleaned.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    cleaned = cleaned.replace("```json", "").replace("```JSON", "").replace("```", "")
    cleaned = cleaned.replace("'''json", "").replace("'''JSON", "").replace("'''", "")
    return cleaned.strip()


def _result(success: bool, type_name: str, mode: str, data=None, error: str = "", original_content=""):
    category, usage = TYPE_CATEGORY_USAGE.get(type_name, ("Unknown", "未登记用途"))
    return {
        "success": success,
        "type": type_name,
        "category": category,
        "usage": usage,
        "mode": mode,
        "data": data,
        "error": error,
        "original_content": _normalize_text(original_content),
    }


def _simple_text_format(text: str) -> str:
    lines = [_normalize_text(line).rstrip() for line in _normalize_newlines(text).split("\n")]
    return "\n".join(lines).strip() + ("\n" if lines and any(line for line in lines) else "")


def _parse_key_value_lines(text: str, separator: str = "=") -> dict:
    data = {}
    for line in _normalize_newlines(text).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if separator not in stripped:
            raise ValueError(f"无法解析键值行：{line}")
        key, value = stripped.split(separator, 1)
        data[key.strip()] = value.strip()
    return data


def _serialize_key_value_lines(data: dict, separator: str = "=") -> str:
    return "\n".join(f"{key}{separator}{value}" for key, value in data.items()) + ("\n" if data else "")


def _bracket_validate(text: str, pairs: dict) -> tuple[bool, str]:
    stack = []
    closing_to_open = {closing: opening for opening, closing in pairs.items()}
    for char in _normalize_text(text):
        if char in pairs:
            stack.append(char)
        elif char in closing_to_open:
            if not stack or stack[-1] != closing_to_open[char]:
                return False, f"括号不匹配：遇到 {char}"
            stack.pop()
    if stack:
        return False, f"括号未闭合：{''.join(stack)}"
    return True, ""


def _parse_markdown_code_blocks(text: str) -> list[dict]:
    blocks = []
    for index, match in enumerate(FENCED_CODE_BLOCK_PATTERN.finditer(_normalize_newlines(text)), start=1):
        lang = _normalize_type(match.group("lang"))
        code = match.group("code").strip("\n")
        inferred = detect_type(code, type_hint=lang or None)
        blocks.append(
            {
                "index": index,
                "language": lang or inferred,
                "detected_type": inferred,
                "content": code,
            }
        )
    return blocks


def normalize_json_text(text: str) -> str:
    """尽量把模型返回的非标准 JSON 文本整理成可解析的 JSON 片段。"""
    cleaned = _strip_code_fence_markers(text)
    cleaned = JSON_PREFIX_PATTERN.sub("", cleaned)
    first_object = cleaned.find("{")
    first_array = cleaned.find("[")
    candidates = [index for index in (first_object, first_array) if index != -1]
    if candidates:
        cleaned = cleaned[min(candidates):].strip()
    return cleaned


def extract_json_value(text: str):
    """从清洗后的文本中尽量提取第一个合法 JSON 值。"""
    cleaned = normalize_json_text(text)
    if not cleaned:
        raise ValueError("模型返回为空，无法解析 JSON。")
    starts = [index for marker in ("{", "[") if (index := cleaned.find(marker)) != -1]
    if not starts:
        raise ValueError("模型返回中未找到 JSON 起始符号。")
    start = min(starts)
    for end in range(len(cleaned), start, -1):
        snippet = cleaned[start:end].strip()
        if not snippet.endswith(("}", "]")):
            continue
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue
    raise ValueError("模型返回中的 JSON 内容解析失败。")


def _json_format(content) -> str:
    parsed = content if isinstance(content, (dict, list)) else extract_json_value(content)
    return json.dumps(parsed, ensure_ascii=False, indent=4, sort_keys=False) + "\n"


def _json_parse(content):
    return content if isinstance(content, (dict, list)) else extract_json_value(content)


def _json_validate(content) -> dict:
    _json_parse(content)
    return {"valid": True}


def _yaml_parse(content):
    text = _normalize_text(content)
    if yaml is not None:
        return yaml.safe_load(text)
    return _json_parse(text)


def _yaml_format(content) -> str:
    parsed = _yaml_parse(content)
    if yaml is not None:
        return yaml.safe_dump(parsed, allow_unicode=True, sort_keys=False)
    return _json_format(parsed)


def _yaml_validate(content) -> dict:
    _yaml_parse(content)
    return {"valid": True, "backend": "pyyaml" if yaml is not None else "json-fallback"}


def _xml_element_to_value(element):
    """把 XML 节点递归转换为更通用的 Python 结构。"""
    children = list(element)
    text = (element.text or "").strip()

    if not children and not element.attrib:
        return text

    data = {}
    if element.attrib:
        data["@attributes"] = dict(element.attrib)

    child_map = {}
    for child in children:
        child_value = _xml_element_to_value(child)
        if child.tag in child_map:
            if not isinstance(child_map[child.tag], list):
                child_map[child.tag] = [child_map[child.tag]]
            child_map[child.tag].append(child_value)
        else:
            child_map[child.tag] = child_value

    data.update(child_map)
    if text:
        if children or element.attrib:
            data["#text"] = text
        else:
            return text
    return data


def _xml_parse(content):
    root = ElementTree.fromstring(_normalize_text(content))
    return {root.tag: _xml_element_to_value(root)}


def _xml_format(content) -> str:
    text = _normalize_text(content).strip()
    pretty = minidom.parseString(text.encode("utf-8")).toprettyxml(indent="    ")
    lines = [line for line in pretty.splitlines() if line.strip()]
    return "\n".join(lines) + "\n"


def _xml_validate(content) -> dict:
    _xml_parse(content)
    return {"valid": True}


def _dump_toml_value(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ", ".join(_dump_toml_value(item) for item in value) + "]"
    raise TypeError(f"TOML 序列化暂不支持该值类型：{type(value).__name__}")


def _dump_toml_dict(data: dict, prefix: str = "") -> list[str]:
    lines = []
    scalars = {}
    tables = {}
    for key, value in data.items():
        if isinstance(value, dict):
            tables[key] = value
        else:
            scalars[key] = value
    for key, value in scalars.items():
        lines.append(f"{key} = {_dump_toml_value(value)}")
    for key, value in tables.items():
        if lines:
            lines.append("")
        section = f"{prefix}.{key}" if prefix else key
        lines.append(f"[{section}]")
        lines.extend(_dump_toml_dict(value, section))
    return lines


def _toml_parse(content):
    if tomllib is None:
        raise ValueError("当前 Python 环境缺少 tomllib，无法解析 TOML。")
    return tomllib.loads(_normalize_text(content))


def _toml_format(content) -> str:
    parsed = content if isinstance(content, dict) else _toml_parse(content)
    return "\n".join(_dump_toml_dict(parsed)).strip() + "\n"


def _toml_validate(content) -> dict:
    _toml_parse(content)
    return {"valid": True}


def _ini_parse(content):
    parser = configparser.ConfigParser()
    parser.read_string(_normalize_text(content))
    return {section: dict(parser.items(section)) for section in parser.sections()}


def _ini_format(content) -> str:
    parsed = content if isinstance(content, dict) else _ini_parse(content)
    parser = configparser.ConfigParser()
    for section, values in parsed.items():
        parser[section] = {str(key): str(value) for key, value in values.items()}
    buffer = io.StringIO()
    parser.write(buffer)
    return buffer.getvalue()


def _ini_validate(content) -> dict:
    _ini_parse(content)
    return {"valid": True}


def _python_parse(content):
    text = _normalize_text(content)
    tree = ast.parse(text)
    return {
        "module": "python",
        "node_count": len(list(ast.walk(tree))),
        "functions": [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)],
        "classes": [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)],
    }


def _python_format(content) -> str:
    text = _simple_text_format(content)
    try:
        module = ast.parse(text)
        return ast.unparse(module).strip() + "\n"
    except Exception:
        return text


def _python_validate(content) -> dict:
    compile(_normalize_text(content), "<python>", "exec")
    return {"valid": True}


def _generic_code_parse(content):
    text = _normalize_text(content)
    return {
        "line_count": len(_normalize_newlines(text).splitlines()),
        "char_count": len(text),
        "imports": re.findall(r"^\s*(?:import|from|use|include|require)\b.*", _normalize_newlines(text), flags=re.MULTILINE),
    }


def _generic_code_format(content) -> str:
    return _simple_text_format(content)


def _generic_code_validate(content) -> dict:
    ok, message = _bracket_validate(_normalize_text(content), {"{": "}", "(": ")", "[": "]"})
    if not ok:
        raise ValueError(message)
    return {"valid": True}


def _html_parse(content):
    text = _normalize_text(content)
    tags = re.findall(r"<([a-zA-Z][a-zA-Z0-9:-]*)\b", text)
    return {"tag_count": len(tags), "tags": tags[:50]}


def _html_format(content) -> str:
    return _xml_format(content)


def _html_validate(content) -> dict:
    _xml_validate(content)
    return {"valid": True}


def _markdown_parse(content):
    text = _normalize_newlines(content)
    return {
        "line_count": len(text.splitlines()),
        "heading_count": len(re.findall(r"^\s*#+\s+", text, flags=re.MULTILINE)),
        "code_blocks": _parse_markdown_code_blocks(text),
    }


def _markdown_format(content) -> str:
    text = _simple_text_format(content)
    lines = text.splitlines()
    output = []
    blank_count = 0
    for line in lines:
        if line.strip():
            blank_count = 0
            output.append(line)
        else:
            blank_count += 1
            if blank_count <= 1:
                output.append("")
    return "\n".join(output).strip() + "\n"


def _markdown_validate(content) -> dict:
    return {"valid": True, "code_block_count": len(_parse_markdown_code_blocks(content))}


def _txt_parse(content):
    text = _normalize_text(content)
    return {"line_count": len(_normalize_newlines(text).splitlines()), "char_count": len(text)}


def _txt_format(content) -> str:
    return _simple_text_format(content)


def _txt_validate(content) -> dict:
    return {"valid": True}


def _rtf_parse(content):
    text = _normalize_text(content)
    return {"header": text[:20], "contains_rtf_header": text.lstrip().startswith(r"{\rtf")}


def _rtf_format(content) -> str:
    return _simple_text_format(content)


def _rtf_validate(content) -> dict:
    if not _normalize_text(content).lstrip().startswith(r"{\rtf"):
        raise ValueError("RTF 缺少 {\\rtf 头。")
    return {"valid": True}


def _csv_parse_with_delimiter(content, delimiter: str):
    rows = list(csv.reader(io.StringIO(_normalize_text(content)), delimiter=delimiter))
    return {"rows": rows, "row_count": len(rows)}


def _csv_format_with_delimiter(content, delimiter: str) -> str:
    rows = content
    if isinstance(content, dict) and "rows" in content:
        rows = content["rows"]
    elif not isinstance(content, list):
        rows = _csv_parse_with_delimiter(content, delimiter)["rows"]
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def _csv_validate_with_delimiter(content, delimiter: str) -> dict:
    parsed = _csv_parse_with_delimiter(content, delimiter)
    return {"valid": True, "row_count": parsed["row_count"]}


def _sql_parse(content):
    text = _normalize_newlines(content)
    statements = [item.strip() for item in text.split(";") if item.strip()]
    return {"statement_count": len(statements), "statements": statements}


def _sql_format(content) -> str:
    statements = content if isinstance(content, list) else _sql_parse(content)["statements"]
    return ";\n\n".join(statement.strip() for statement in statements) + (";\n" if statements else "")


def _sql_validate(content) -> dict:
    text = _normalize_text(content)
    if not re.search(r"\b(select|insert|update|delete|create|alter|drop|with)\b", text, flags=re.IGNORECASE):
        raise ValueError("SQL 中未检测到常见语句关键字。")
    ok, message = _bracket_validate(text, {"(": ")"})
    if not ok:
        raise ValueError(message)
    return {"valid": True}


def _dockerfile_parse(content):
    lines = []
    for line in _normalize_newlines(content).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split(None, 1)
        instruction = parts[0].upper()
        argument = parts[1] if len(parts) > 1 else ""
        lines.append({"instruction": instruction, "argument": argument})
    return {"instructions": lines, "instruction_count": len(lines)}


def _dockerfile_format(content) -> str:
    items = content if isinstance(content, list) else _dockerfile_parse(content)["instructions"]
    return "\n".join(
        item["instruction"] if not item.get("argument") else f"{item['instruction']} {item['argument']}"
        for item in items
    ).strip() + "\n"


def _dockerfile_validate(content) -> dict:
    parsed = _dockerfile_parse(content)
    if not parsed["instructions"]:
        raise ValueError("Dockerfile 不能为空。")
    return {"valid": True, "instruction_count": parsed["instruction_count"]}


def _env_parse(content):
    return _parse_key_value_lines(content, separator="=")


def _env_format(content) -> str:
    parsed = content if isinstance(content, dict) else _env_parse(content)
    return _serialize_key_value_lines(parsed, separator="=")


def _env_validate(content) -> dict:
    _env_parse(content)
    return {"valid": True}


def _nginx_parse(content):
    text = _normalize_newlines(content)
    directives = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]
    return {"directive_count": len(directives), "directives": directives}


def _nginx_format(content) -> str:
    return _simple_text_format(content)


def _nginx_validate(content) -> dict:
    ok, message = _bracket_validate(_normalize_text(content), {"{": "}"})
    if not ok:
        raise ValueError(message)
    return {"valid": True}


def _requirements_parse(content):
    items = []
    for line in _normalize_newlines(content).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        items.append(stripped)
    return {"packages": items, "count": len(items)}


def _requirements_format(content) -> str:
    items = content if isinstance(content, list) else _requirements_parse(content)["packages"]
    return "\n".join(items).strip() + ("\n" if items else "")


def _requirements_validate(content) -> dict:
    _requirements_parse(content)
    return {"valid": True}


HANDLERS = {
    "json": FormatHandler("json", TYPE_CATEGORY_USAGE["json"][1], _json_format, _json_parse, _json_validate),
    "yaml": FormatHandler("yaml", TYPE_CATEGORY_USAGE["yaml"][1], _yaml_format, _yaml_parse, _yaml_validate),
    "xml": FormatHandler("xml", TYPE_CATEGORY_USAGE["xml"][1], _xml_format, _xml_parse, _xml_validate),
    "toml": FormatHandler("toml", TYPE_CATEGORY_USAGE["toml"][1], _toml_format, _toml_parse, _toml_validate),
    "ini": FormatHandler("ini", TYPE_CATEGORY_USAGE["ini"][1], _ini_format, _ini_parse, _ini_validate),
    "python": FormatHandler("python", TYPE_CATEGORY_USAGE["python"][1], _python_format, _python_parse, _python_validate),
    "javascript": FormatHandler("javascript", TYPE_CATEGORY_USAGE["javascript"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "typescript": FormatHandler("typescript", TYPE_CATEGORY_USAGE["typescript"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "c": FormatHandler("c", TYPE_CATEGORY_USAGE["c"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "cpp": FormatHandler("cpp", TYPE_CATEGORY_USAGE["cpp"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "java": FormatHandler("java", TYPE_CATEGORY_USAGE["java"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "go": FormatHandler("go", TYPE_CATEGORY_USAGE["go"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "rust": FormatHandler("rust", TYPE_CATEGORY_USAGE["rust"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "bash": FormatHandler("bash", TYPE_CATEGORY_USAGE["bash"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "html": FormatHandler("html", TYPE_CATEGORY_USAGE["html"][1], _html_format, _html_parse, _html_validate),
    "css": FormatHandler("css", TYPE_CATEGORY_USAGE["css"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "scss": FormatHandler("scss", TYPE_CATEGORY_USAGE["scss"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "jsx": FormatHandler("jsx", TYPE_CATEGORY_USAGE["jsx"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "tsx": FormatHandler("tsx", TYPE_CATEGORY_USAGE["tsx"][1], _generic_code_format, _generic_code_parse, _generic_code_validate),
    "markdown": FormatHandler("markdown", TYPE_CATEGORY_USAGE["markdown"][1], _markdown_format, _markdown_parse, _markdown_validate),
    "txt": FormatHandler("txt", TYPE_CATEGORY_USAGE["txt"][1], _txt_format, _txt_parse, _txt_validate),
    "rtf": FormatHandler("rtf", TYPE_CATEGORY_USAGE["rtf"][1], _rtf_format, _rtf_parse, _rtf_validate),
    "csv": FormatHandler("csv", TYPE_CATEGORY_USAGE["csv"][1], lambda c: _csv_format_with_delimiter(c, ","), lambda c: _csv_parse_with_delimiter(c, ","), lambda c: _csv_validate_with_delimiter(c, ",")),
    "tsv": FormatHandler("tsv", TYPE_CATEGORY_USAGE["tsv"][1], lambda c: _csv_format_with_delimiter(c, "\t"), lambda c: _csv_parse_with_delimiter(c, "\t"), lambda c: _csv_validate_with_delimiter(c, "\t")),
    "sql": FormatHandler("sql", TYPE_CATEGORY_USAGE["sql"][1], _sql_format, _sql_parse, _sql_validate),
    "dockerfile": FormatHandler("dockerfile", TYPE_CATEGORY_USAGE["dockerfile"][1], _dockerfile_format, _dockerfile_parse, _dockerfile_validate),
    "env": FormatHandler("env", TYPE_CATEGORY_USAGE["env"][1], _env_format, _env_parse, _env_validate),
    "nginx.conf": FormatHandler("nginx.conf", TYPE_CATEGORY_USAGE["nginx.conf"][1], _nginx_format, _nginx_parse, _nginx_validate),
    "requirements.txt": FormatHandler("requirements.txt", TYPE_CATEGORY_USAGE["requirements.txt"][1], _requirements_format, _requirements_parse, _requirements_validate),
    "package.json": FormatHandler("package.json", TYPE_CATEGORY_USAGE["package.json"][1], _json_format, _json_parse, _json_validate),
}


def detect_type(content, file_name: str | None = None, type_hint: str | None = None) -> str:
    """基于显式提示、文件名后缀和内容特征自动识别格式类型。"""
    hinted = _normalize_type(type_hint)
    if hinted in HANDLERS:
        return hinted

    if file_name:
        lower_name = Path(file_name).name.lower()
        if lower_name in {"dockerfile", "package.json", "requirements.txt", "nginx.conf"}:
            return lower_name
        if lower_name == ".env":
            return "env"
        suffix = Path(lower_name).suffix.lower()
        if suffix in SUFFIX_TO_TYPE:
            return SUFFIX_TO_TYPE[suffix]

    text = _normalize_text(content).lstrip()
    if not text:
        return "txt"
    if text.startswith("{\\rtf"):
        return "rtf"
    if text.startswith(("{", "[")):
        return "json"
    if text.startswith("<?xml") or (text.startswith("<") and re.search(r"</?[a-zA-Z]", text)):
        return "xml"
    if "```" in text:
        return "markdown"
    if re.search(r"^\s*\[.*\]\s*$", text, flags=re.MULTILINE):
        return "ini"
    if re.search(r"^\s*[A-Za-z_][A-Za-z0-9_-]*\s*=", text, flags=re.MULTILINE):
        return "env"
    if re.search(r"^\s*[A-Za-z_][A-Za-z0-9_-]*\s*:\s*", text, flags=re.MULTILINE):
        return "yaml"
    if "," in text and "\n" in text:
        return "csv"
    if "\t" in text and "\n" in text:
        return "tsv"
    if re.search(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH)\b", text, flags=re.IGNORECASE):
        return "sql"
    if re.search(r"^\s*(FROM|RUN|COPY|CMD|ENTRYPOINT|WORKDIR|ENV)\b", text, flags=re.IGNORECASE | re.MULTILINE):
        return "dockerfile"
    if re.search(r"^\s*#include\b", text, flags=re.MULTILINE):
        return "c"
    if re.search(r"^\s*package\s+\w+", text, flags=re.MULTILINE):
        return "java"
    if re.search(r"^\s*def\s+\w+|\bimport\s+\w+", text, flags=re.MULTILINE):
        return "python"
    return "txt"


def list_supported_formats() -> list[dict]:
    """列出当前系统支持的格式及其用途。"""
    return [
        {
            "type": type_name,
            "category": TYPE_CATEGORY_USAGE[type_name][0],
            "usage": TYPE_CATEGORY_USAGE[type_name][1],
        }
        for type_name in sorted(HANDLERS.keys())
    ]


def handle(type_name: str, content, mode: str, file_name: str | None = None) -> dict:
    """统一处理入口：按类型执行 format / parse / validate。"""
    normalized_type = detect_type(content, file_name=file_name, type_hint=type_name if type_name != "auto" else None)
    handler = HANDLERS.get(normalized_type)
    normalized_mode = str(mode or "").strip().lower()
    if handler is None:
        return _result(False, normalized_type or "unknown", normalized_mode, error=f"不支持的格式类型：{type_name}", original_content=content)
    if normalized_mode not in {"format", "parse", "validate"}:
        return _result(False, normalized_type, normalized_mode, error=f"不支持的处理模式：{mode}", original_content=content)

    operation = {
        "format": handler.formatter,
        "parse": handler.parser,
        "validate": handler.validator,
    }[normalized_mode]

    try:
        data = operation(content)
        return _result(True, normalized_type, normalized_mode, data=data, original_content=content)
    except Exception as exc:
        return _result(False, normalized_type, normalized_mode, error=str(exc), original_content=content)


def convert(content, source_type: str, target_type: str) -> dict:
    """在支持的格式之间进行内容互转。"""
    parse_result = handle(source_type, content, "parse")
    if not parse_result["success"]:
        return parse_result
    return handle(target_type, parse_result["data"], "format")


def extract_markdown_code_blocks(content: str) -> dict:
    """提取 markdown 中的嵌套代码块并返回识别结果。"""
    text = _normalize_text(content)
    return {
        "success": True,
        "type": "markdown",
        "mode": "parse_code_blocks",
        "data": _parse_markdown_code_blocks(text),
        "error": "",
        "original_content": text,
    }


def extract_preferred_code_block(content: str, preferred_types=None) -> dict:
    """从 markdown 代码块中优先挑出目标格式，便于后续结构化解析或脚本内容清洗。"""
    blocks = extract_markdown_code_blocks(content)["data"]
    normalized_preferred = [_normalize_type(item) for item in (preferred_types or [])]
    if not blocks:
        return {"success": False, "error": "未找到 markdown 代码块。", "data": None}

    for block in blocks:
        detected = _normalize_type(block.get("detected_type"))
        language = _normalize_type(block.get("language"))
        if detected in normalized_preferred or language in normalized_preferred:
            return {"success": True, "error": "", "data": block}

    return {"success": True, "error": "", "data": blocks[0]}


def parse_llm_output(content, preferred_types=None) -> dict:
    """面向 LLM 输出的结构化解析链：支持自动识别、多格式代码块抽取与归一化。"""
    text = _normalize_text(content)
    normalized_preferred = [_normalize_type(item) for item in (preferred_types or []) if _normalize_type(item)]

    candidate_types = []
    detected = detect_type(text)
    if normalized_preferred:
        if detected in normalized_preferred:
            candidate_types.append(detected)
        candidate_types.extend(normalized_preferred)
    else:
        if detected:
            candidate_types.append(detected)
        candidate_types.extend(["json", "yaml", "toml", "xml", "ini"])

    seen = set()
    ordered_candidates = []
    for type_name in candidate_types:
        normalized = _normalize_type(type_name)
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered_candidates.append(normalized)

    for type_name in ordered_candidates:
        if type_name in {"markdown", "txt"}:
            continue
        result = handle(type_name, text, "parse")
        if result["success"]:
            result["source"] = "raw_text"
            return result

    if "```" in text:
        block_result = extract_preferred_code_block(text, preferred_types=ordered_candidates)
        block = block_result.get("data")
        if block is not None:
            nested_candidates = []
            block_detected = _normalize_type(block.get("detected_type"))
            block_language = _normalize_type(block.get("language"))
            if block_detected:
                nested_candidates.append(block_detected)
            if block_language:
                nested_candidates.append(block_language)
            nested_candidates.extend(ordered_candidates)

            nested_seen = set()
            for type_name in nested_candidates:
                normalized = _normalize_type(type_name)
                if not normalized or normalized in nested_seen:
                    continue
                nested_seen.add(normalized)
                result = handle(normalized, block["content"], "parse")
                if result["success"]:
                    result["source"] = "markdown_code_block"
                    result["code_block"] = block
                    return result

    return {
        "success": False,
        "type": detect_type(text),
        "category": TYPE_CATEGORY_USAGE.get(detect_type(text), ("Unknown", ""))[0],
        "usage": TYPE_CATEGORY_USAGE.get(detect_type(text), ("Unknown", ""))[1],
        "mode": "parse_llm_output",
        "data": None,
        "error": "无法从 LLM 输出中识别出可解析的结构化内容。",
        "original_content": text,
    }


def call_llm_structured(
    message: str,
    model: str,
    apikey: str,
    preferred_types=None,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
):
    """调用模型后自动识别结构化输出格式，并返回解析后的内部结构。"""
    raw_text = call_llm(
        message,
        model,
        apikey,
        stream=False,
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )
    result = parse_llm_output(raw_text, preferred_types=preferred_types)
    if not result["success"]:
        raise ValueError(result["error"])
    return result["data"]


def call_llm_json(
    message: str,
    model: str,
    apikey: str,
    thinking_enabled: bool = False,
    reasoning_effort: str | None = None,
):
    """兼容旧 JSON 入口：调用模型后走新的统一格式处理系统解析 JSON。"""
    return call_llm_structured(
        message,
        model,
        apikey,
        preferred_types=["json", "yaml", "toml", "xml"],
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
    )
