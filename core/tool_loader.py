import importlib.util
import json
from pathlib import Path

from core.constants import TOOLS_DIR
from core.file_utils import sanitize_name


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _read_json_file(path: Path) -> dict:
    text = _read_text_file(path).strip()
    if not text:
        return {}
    data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _dedupe_texts(values) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip().lower()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


class ToolRepository:
    """从项目 TOOLS 目录加载标准化 LLM 工具。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else TOOLS_DIR
        self._handler_cache: dict[str, callable] = {}

    def _tool_dirs(self) -> list[Path]:
        if not self.base_dir.exists():
            return []
        return sorted(
            [item for item in self.base_dir.iterdir() if item.is_dir() and (item / "tool.json").exists()],
            key=lambda item: item.name.lower(),
        )

    def _guess_entry_script(self, tool_dir: Path) -> Path | None:
        candidates = [
            path
            for path in sorted(tool_dir.glob("*.py"), key=lambda item: item.name.lower())
            if path.is_file() and path.name != "__init__.py"
        ]
        return candidates[0] if candidates else None

    def _load_tool(self, tool_dir: Path) -> dict:
        tool_json_path = tool_dir / "tool.json"
        metadata = _read_json_file(tool_json_path)
        tool_doc_path = tool_dir / "TOOL.md"
        entry = metadata.get("entry", {}) if isinstance(metadata.get("entry"), dict) else {}
        guessed_entry = self._guess_entry_script(tool_dir)
        entry_file = str(entry.get("file") or metadata.get("entry_file") or "").strip()
        if entry_file:
            entry_path = tool_dir / entry_file
        else:
            entry_path = guessed_entry
        entry_function = str(entry.get("function") or metadata.get("entry_function") or "run").strip() or "run"
        name = str(metadata.get("name") or tool_dir.name).strip().lower() or tool_dir.name.lower()
        aliases = _dedupe_texts(metadata.get("aliases", []))
        examples = metadata.get("examples", {})
        return {
            "folder": tool_dir.name,
            "name": name,
            "display_name": str(metadata.get("display_name") or metadata.get("title") or name).strip() or name,
            "description": str(metadata.get("description", "")).strip(),
            "enabled": bool(metadata.get("enabled", True)),
            "dir_path": str(tool_dir),
            "tool_json_path": str(tool_json_path),
            "tool_doc_path": str(tool_doc_path) if tool_doc_path.exists() else "",
            "tool_doc_content": _read_text_file(tool_doc_path).strip() if tool_doc_path.exists() else "",
            "entry_file": entry_path.name if entry_path is not None else "",
            "entry_path": str(entry_path) if entry_path is not None else "",
            "entry_function": entry_function,
            "aliases": aliases,
            "input_schema": metadata.get("input_schema", {}),
            "output_schema": metadata.get("output_schema", {}),
            "examples": examples if isinstance(examples, dict) else {},
            "metadata": metadata,
        }

    def list_tools(self) -> list[dict]:
        tools = []
        for tool_dir in self._tool_dirs():
            tool = self._load_tool(tool_dir)
            if not tool.get("enabled", True):
                continue
            tools.append(
                {
                    "folder": tool["folder"],
                    "name": tool["name"],
                    "display_name": tool["display_name"],
                    "description": tool["description"],
                    "aliases": tool["aliases"],
                    "entry_file": tool["entry_file"],
                    "entry_function": tool["entry_function"],
                    "tool_json_path": tool["tool_json_path"],
                    "tool_doc_path": tool["tool_doc_path"],
                }
            )
        return tools

    def get_tool(self, name: str) -> dict:
        target = str(name or "").strip().lower()
        if not target:
            raise ValueError("tool 名称不能为空。")
        for tool_dir in self._tool_dirs():
            tool = self._load_tool(tool_dir)
            if not tool.get("enabled", True):
                continue
            candidates = {tool["folder"].lower(), tool["name"].lower(), *tool.get("aliases", [])}
            if target in candidates:
                return tool
        raise ValueError(f"未找到 tool：{name}")

    def render_tool_overview(self, name: str) -> str:
        tool = self.get_tool(name)
        lines = [
            f"工具：{tool['folder']}",
            f"- 名称：{tool['name']}",
            f"- 展示名：{tool['display_name']}",
            f"- 描述：{tool['description'] or '无'}",
            f"- 别名：{', '.join(tool['aliases']) if tool['aliases'] else '无'}",
            f"- 目录：{tool['dir_path']}",
            f"- 元数据：{tool['tool_json_path']}",
            f"- 文档：{tool['tool_doc_path'] or '无'}",
            f"- 入口：{tool['entry_file'] or '无'}::{tool['entry_function']}",
        ]
        if tool.get("tool_doc_content"):
            lines.extend(["", "## TOOL.md", tool["tool_doc_content"]])
        else:
            lines.extend(["", "## tool.json", json.dumps(tool["metadata"], ensure_ascii=False, indent=2)])
        return "\n".join(lines).strip()

    def _load_entry_callable(self, tool: dict):
        entry_path = Path(tool.get("entry_path", ""))
        if not entry_path.exists():
            raise FileNotFoundError(f"tool 入口脚本不存在：{entry_path}")
        module_name = f"prompt_tool_{sanitize_name(tool['folder'])}"
        spec = importlib.util.spec_from_file_location(module_name, entry_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法加载 tool 模块：{entry_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        function_name = str(tool.get("entry_function", "run")).strip() or "run"
        handler = getattr(module, function_name, None)
        if handler is None or not callable(handler):
            raise AttributeError(f"tool 入口函数不存在：{entry_path.name}::{function_name}")
        return handler

    def build_handler(self, name: str):
        tool = self.get_tool(name)
        canonical_name = tool["name"]
        cached = self._handler_cache.get(canonical_name)
        if cached is not None:
            return cached

        entry_callable = self._load_entry_callable(tool)

        def handler(args: dict) -> str:
            context = {
                "tool": tool,
                "tool_dir": tool["dir_path"],
                "tool_json_path": tool["tool_json_path"],
                "tool_doc_path": tool["tool_doc_path"],
                "project_root": str(self.base_dir.parent),
            }
            result = entry_callable(dict(args or {}), context)
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, indent=2)
            if result is None:
                return ""
            return str(result)

        self._handler_cache[canonical_name] = handler
        return handler

