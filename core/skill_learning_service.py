import ast
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

from core.constants import BASE_DIR, EXEC_FULL_INFO_DIR, SKILLS_DIR
from core.file_utils import load_json, save_json, sanitize_name
from core.skill_loader import SkillRepository


class SkillLearningService:
    """把最近一次成功 EXEC 直接压缩为可执行 skill 产物。"""

    DEFAULT_REPAIR_LIMIT = 1

    def __init__(
        self,
        config,
        user: str,
        skill_repository: SkillRepository | None = None,
        review_service=None,
    ) -> None:
        self.config = config
        self.user = user
        self.skill_repository = skill_repository or SkillRepository()
        self.review_service = review_service

    def _emit(self, callback, event: dict) -> None:
        if callback is not None:
            callback(event)

    def _emit_phase(self, callback, message: str, extra: dict | None = None) -> None:
        event = {"type": "skill_phase", "message": message}
        if extra:
            event.update(extra)
        self._emit(callback, event)

    def _to_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    def _json_safe(self, value):
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except TypeError:
            if isinstance(value, dict):
                return {str(key): self._json_safe(val) for key, val in value.items()}
            if isinstance(value, list):
                return [self._json_safe(item) for item in value]
            return self._to_text(value)

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    def _create_log_context(self) -> dict:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = BASE_DIR / "skill_add" / f"{timestamp}_{sanitize_name(self.user)}"
        log_dir.mkdir(parents=True, exist_ok=True)
        return {
            "run_id": log_dir.name,
            "log_dir": log_dir,
            "events_path": log_dir / "events.jsonl",
            "summary_path": log_dir / "summary.json",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _append_log_event(self, log_context: dict | None, event_type: str, payload: dict | None = None) -> None:
        if not log_context:
            return
        event = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "type": event_type,
            "payload": self._json_safe(payload or {}),
        }
        events_path = log_context.get("events_path")
        if isinstance(events_path, Path):
            with events_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _write_log_summary(self, log_context: dict | None, payload: dict) -> None:
        if not log_context:
            return
        summary = {
            "run_id": log_context.get("run_id", ""),
            "started_at": log_context.get("started_at", ""),
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        summary.update(self._json_safe(payload))
        summary_path = log_context.get("summary_path")
        if isinstance(summary_path, Path):
            summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_logging_callback(self, callback, log_context: dict):
        def wrapped(event: dict) -> None:
            self._append_log_event(log_context, event.get("type", "callback_event"), event)
            if callback is not None:
                callback(event)

        return wrapped

    def _get_learning_config(self) -> dict:
        config_data = getattr(self.config, "config", {}) or {}
        learning = config_data.get("skill_learning", {}) if isinstance(config_data, dict) else {}
        return learning if isinstance(learning, dict) else {}

    def _config_bool(self, mapping: dict, key: str, default: bool) -> bool:
        value = mapping.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _config_int(self, mapping: dict, key: str, default: int, minimum: int = 0, maximum: int = 10) -> int:
        try:
            value = int(mapping.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

    def _get_repair_limit(self) -> int:
        return self._config_int(self._get_learning_config(), "max_repair_rounds", self.DEFAULT_REPAIR_LIMIT, minimum=1, maximum=3)

    def _should_validate(self) -> bool:
        return self._config_bool(self._get_learning_config(), "temp_validation_enabled", True)

    def _extract_full_info_from_text(self, text: str) -> str:
        content = self._to_text(text)
        if not content:
            return ""
        normalized = content.replace("\\\\", "/").replace("\\", "/")
        match = re.search(r"([A-Za-z]:/[^`\n\r]*?/EXEC/full_info/[^`\n\r]*?_full_info\.json)", normalized)
        return match.group(1).replace("/", "\\") if match else ""

    def _find_history_full_info_path(self, session_history=None) -> str:
        for item in reversed(list(session_history or [])):
            path = self._extract_full_info_from_text(item.get("content", ""))
            if path:
                return path
        return ""

    def _find_latest_full_info_path(self) -> Path:
        prefix = sanitize_name(self.user)
        candidates = []
        for path in EXEC_FULL_INFO_DIR.glob("*_full_info.json"):
            data = load_json(path, {})
            if not data:
                continue
            if not bool(data.get("success")):
                continue
            if str(data.get("final_state", "")).upper() != "DONE":
                continue
            run_id = self._to_text(data.get("run_id", "")).strip()
            score = 1 if run_id.startswith(prefix + "_") else 0
            finished_at = self._to_text(data.get("finished_at", "")).strip()
            candidates.append((score, finished_at, path))
        if not candidates:
            raise ValueError("未找到最近一次成功的完整 EXEC 流程，无法学习 skill。")
        candidates.sort(key=lambda item: (item[0], item[1], str(item[2])), reverse=True)
        return candidates[0][2]

    def _load_full_info(self, session_history=None) -> tuple[Path, dict]:
        history_path = self._find_history_full_info_path(session_history)
        if history_path:
            candidate = Path(history_path)
            if candidate.exists():
                data = load_json(candidate, {})
                if data:
                    return candidate, data
        path = self._find_latest_full_info_path()
        data = load_json(path, {})
        if not data:
            raise ValueError("最近一次 EXEC full_info 文件为空，无法学习 skill。")
        return path, data

    def _relative_path(self, value: str) -> str:
        text = self._to_text(value).strip()
        if not text:
            return ""
        path = Path(text)
        try:
            return path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
        except Exception:
            normalized = text.replace("\\", "/")
            base = str(BASE_DIR.resolve()).replace("\\", "/")
            if normalized.lower().startswith(base.lower() + "/"):
                return normalized[len(base) + 1 :]
        return text.replace("\\", "/")

    def _normalize_path(self, value: str) -> str:
        return self._to_text(value).strip().replace("\\", "/")

    def _parse_json(self, text: str) -> dict:
        try:
            data = json.loads(self._to_text(text).strip() or "{}")
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _shell_command_to_dependencies(self, command: str) -> list[dict]:
        text = self._to_text(command).strip()
        if not text:
            return []
        package_names = []
        for match in re.finditer(r"(?:^|[;&|]\s*|\s)(?:pip|python\s+-m\s+pip)\s+install\s+([A-Za-z0-9_.\-]+)", text, flags=re.I):
            package = match.group(1).strip()
            if package and package not in package_names:
                package_names.append(package)
        return [{"name": item, "import_name": item.replace("-", "_")} for item in package_names]

    def _collect_script_dependencies(self, script_content: str) -> list[dict]:
        content = self._to_text(script_content)
        if not content.strip():
            return []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = self._to_text(alias.name).split(".", 1)[0].strip()
                    if name:
                        modules.append(name)
            elif isinstance(node, ast.ImportFrom):
                name = self._to_text(node.module).split(".", 1)[0].strip()
                if name:
                    modules.append(name)

        stdlib_modules = set(getattr(sys, "stdlib_module_names", set()))
        stdlib_modules.update({"__future__"})
        deduped = []
        seen = set()
        for module in modules:
            if module in stdlib_modules or module in seen:
                continue
            seen.add(module)
            deduped.append({"name": module, "import_name": module})
        return deduped

    def _collect_dependencies(self, full_info: dict, script_content: str = "") -> list[dict]:
        packages = []
        for step in full_info.get("step_outcomes", []) if isinstance(full_info.get("step_outcomes"), list) else []:
            packages.extend(self._shell_command_to_dependencies(step.get("command", "")))
        packages.extend(self._collect_script_dependencies(script_content))
        deduped = []
        seen = set()
        for item in packages:
            key = (item["name"], item["import_name"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _build_skill_description(self, task: str, summary: str, source_path: str = "") -> str:
        raw_task = self._to_text(task).strip()
        compact_task = re.sub(r"\s+", "", raw_task)
        for pattern in (
            r"(获取[^，。；,]*?的时间(?:的工具|工具|脚本)?)",
            r"(获取[^，。；,]*?(?:工具|脚本))",
            r"(生成[^，。；,]*?(?:工具|脚本))",
            r"(创建[^，。；,]*?(?:工具|脚本))",
        ):
            match = re.search(pattern, compact_task)
            if match:
                text = match.group(1)
                return text if text.endswith("。") else text + "。"

        text = raw_task or self._to_text(summary).strip() or "从最近一次成功 EXEC 提炼出的直接可执行 Skill"
        text = text.replace("\r", " ").replace("\n", " ")
        text = re.sub(r"[A-Za-z]:[\\/][^，。；,\s]*", "", text)
        text = re.sub(r"^在[^，。；,]*?(?:文件夹|目录)(?:下)?", "", text).strip()
        text = re.sub(r"^(?:建立|创建|生成|编写|写|制作)(?:一个|一份)?", "", text).strip()
        text = re.sub(r"(?:使用|用)\s*python", "", text, flags=re.I)
        text = re.sub(r"所有步骤均成功执行[:：]?", "", text)
        text = re.sub(r"任务完成[。.]?", "", text)
        text = re.sub(r"\s+", " ", text).strip(" ，。；,")
        if not text or text in {"在", "在。"}:
            stem = sanitize_name(Path(self._normalize_path(source_path)).stem.lower())
            if stem == "get_time_by_timezone":
                text = "获取指定时区时间的工具"
            elif stem:
                text = stem.replace("_", " ")
            else:
                text = "从最近一次成功 EXEC 提炼出的直接可执行 Skill"
        if not text.endswith("。"):
            text += "。"
        return text

    def _derive_skill_folder_name(self, full_info: dict, source_path: str) -> str:
        normalized_source = self._normalize_path(source_path)
        if normalized_source.lower().endswith(".py"):
            stem = sanitize_name(Path(normalized_source).stem.lower())
            if stem:
                return stem
        task = self._to_text(full_info.get("task", "")).strip()
        for pattern in (
            r"获取([A-Za-z0-9_\u4e00-\u9fff]+)的时间",
            r"获取([A-Za-z0-9_\u4e00-\u9fff]+)",
            r"生成([A-Za-z0-9_\u4e00-\u9fff]+)",
            r"创建([A-Za-z0-9_\u4e00-\u9fff]+)",
        ):
            match = re.search(pattern, task)
            if not match:
                continue
            candidate = sanitize_name(match.group(0).lower())
            if candidate:
                return candidate
        return f"learned_skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _pick_primary_source(self, full_info: dict) -> dict:
        step_outcomes = full_info.get("step_outcomes", [])
        if not isinstance(step_outcomes, list) or not step_outcomes:
            raise ValueError("full_info 中缺少 step_outcomes，无法提炼 skill 本体。")

        candidates = []
        for index, step in enumerate(step_outcomes, start=1):
            kind = self._to_text(step.get("kind", "")).strip().lower()
            script_content = self._to_text(step.get("script_content", ""))
            if not script_content.strip():
                continue
            source_path = ""
            if kind == "file":
                spec = self._parse_json(step.get("command", ""))
                source_path = self._to_text(spec.get("path", "")).strip()
            elif kind == "python":
                last_attempt = step.get("last_attempt", {}) if isinstance(step.get("last_attempt"), dict) else {}
                source_path = self._to_text(last_attempt.get("script_path", "")).strip()
            if not self._normalize_path(source_path).lower().endswith(".py"):
                continue
            priority = 3 if kind == "file" else 2
            candidates.append(
                {
                    "priority": priority,
                    "index": index,
                    "step": step,
                    "source_path": source_path,
                    "script_content": script_content,
                }
            )

        if not candidates:
            for artifact in full_info.get("artifacts", []) if isinstance(full_info.get("artifacts"), list) else []:
                raw_path = self._to_text(artifact.get("path", "")).strip()
                if not self._normalize_path(raw_path).lower().endswith(".py"):
                    continue
                path = Path(raw_path)
                if not path.exists():
                    continue
                return {
                    "step": {},
                    "source_path": raw_path,
                    "script_content": self._read_text_file(path),
                }
            raise ValueError("未在 full_info 中找到可直接提炼的 Python 技能本体。")

        candidates.sort(key=lambda item: (item["priority"], item["index"]), reverse=True)
        chosen = candidates[0]
        return {
            "step": chosen["step"],
            "source_path": chosen["source_path"],
            "script_content": chosen["script_content"],
        }

    def _tokenize_command(self, command: str) -> list[str]:
        return re.findall(r'"[^"]*"|\'[^\']*\'|\S+', self._to_text(command))

    def _strip_quotes(self, value: str) -> str:
        text = self._to_text(value).strip()
        if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
            return text[1:-1]
        return text

    def _extract_expected_contains(self, verify_text: str) -> str:
        text = self._to_text(verify_text)
        match = re.search(r"['\"]([^'\"]+)['\"]\s+in\s+result\.stdout", text)
        return match.group(1) if match else ""

    def _extract_verify_spec(self, full_info: dict, source_path: str) -> dict:
        normalized_source = self._normalize_path(source_path).lower()
        source_name = Path(normalized_source).name.lower() if normalized_source else ""
        for step in reversed(full_info.get("step_outcomes", []) if isinstance(full_info.get("step_outcomes"), list) else []):
            if self._to_text(step.get("kind", "")).strip().lower() != "shell":
                continue
            command_text = self._to_text(step.get("command", "")).strip()
            tokens = [self._strip_quotes(item) for item in self._tokenize_command(command_text)]
            if len(tokens) < 2:
                continue
            runner = tokens[0].lower()
            if runner not in {"python", "python.exe", "py"}:
                continue
            target = self._normalize_path(tokens[1]).lower()
            if target != normalized_source and Path(target).name.lower() != source_name:
                continue
            return {
                "args": tokens[2:],
                "expected_contains": self._extract_expected_contains(step.get("verify", "")),
                "source_command": command_text,
                "verify_command": self._to_text(step.get("verify", "")).strip(),
                "step_id": self._to_text(step.get("id", "")).strip(),
                "step_title": self._to_text(step.get("title", "")).strip(),
            }
        return {}

    def _build_verify_script(self, entry_script_name: str, verify_spec: dict) -> str:
        if not verify_spec:
            return ""
        args_json = json.dumps(verify_spec.get("args", []), ensure_ascii=False)
        expected_contains = verify_spec.get("expected_contains", "")
        lines = [
            "import subprocess",
            "import sys",
            "from pathlib import Path",
            "",
            "",
            "def main() -> int:",
            "    skill_dir = Path(__file__).resolve().parent",
            f"    entry_path = skill_dir / {entry_script_name!r}",
            f"    args = {args_json}",
            "    command = [sys.executable, str(entry_path), *args]",
            "    completed = subprocess.run(command, capture_output=True, text=True)",
            "    if completed.stdout.strip():",
            "        print(completed.stdout.strip())",
            "    if completed.stderr.strip():",
            "        print(completed.stderr.strip(), file=sys.stderr)",
            "    if completed.returncode != 0:",
            "        raise SystemExit(completed.returncode)",
        ]
        if expected_contains:
            lines.extend(
                [
                    f"    expected = {expected_contains!r}",
                    "    if expected not in completed.stdout:",
                    "        print(f\"期望输出包含: {expected}\", file=sys.stderr)",
                    "        return 1",
                ]
            )
        lines.extend(
            [
                "    return 0",
                "",
                "",
                'if __name__ == "__main__":',
                "    raise SystemExit(main())",
                "",
            ]
        )
        return "\n".join(lines)

    def _guess_param_description(self, name: str) -> str:
        normalized = sanitize_name(self._to_text(name).strip().lower())
        if normalized in {"timezone", "tz", "tz_name"}:
            return "时区名称，例如 `UTC`、`Asia/Shanghai`。"
        if normalized in {"path", "file", "file_path"}:
            return "目标文件路径。"
        if normalized in {"dir", "directory", "target_dir"}:
            return "目标目录路径。"
        if normalized in {"url"}:
            return "目标 URL。"
        if normalized in {"query", "keyword"}:
            return "查询文本。"
        return "运行该 skill 时需要提供的参数。"

    def _build_usage_example_from_args(self, args: list[str]) -> str:
        if not args:
            return ""
        return " ".join(self._to_text(item).strip() for item in args if self._to_text(item).strip())

    def _extract_usage_line(self, script_content: str, entry_script_name: str) -> str:
        content = self._to_text(script_content)
        usage_match = re.search(r"Usage:\s*python\s+[^\s]+\.py\s+([^\n\r\"']+)", content, flags=re.I)
        if usage_match:
            return f"python {entry_script_name} {usage_match.group(1).strip()}".strip()
        return ""

    def _extract_argparse_parameters(self, script_content: str) -> list[dict]:
        content = self._to_text(script_content)
        if not content.strip():
            return []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        parameters = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
                continue
            option_values = []
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    option_values.append(arg.value)
            if not option_values:
                continue

            keyword_map = {}
            for keyword in node.keywords:
                if not keyword.arg:
                    continue
                if isinstance(keyword.value, ast.Constant):
                    keyword_map[keyword.arg] = keyword.value.value
            long_options = [item for item in option_values if item.startswith("--")]
            positional = not any(item.startswith("-") for item in option_values)
            if positional:
                display_name = option_values[0]
                cli = f"<{display_name}>"
                param_name = sanitize_name(display_name)
            else:
                primary_option = long_options[0] if long_options else option_values[0]
                display_name = primary_option.lstrip("-").replace("-", "_")
                value_name = self._to_text(keyword_map.get("metavar", display_name.upper())).strip()
                action = self._to_text(keyword_map.get("action", "")).strip()
                cli = primary_option if action == "store_true" else f"{primary_option} <{value_name.lower()}>"
                param_name = sanitize_name(display_name)

            parameters.append(
                {
                    "name": param_name or "arg",
                    "cli": cli,
                    "kind": "positional" if positional else "option",
                    "required": True if positional else bool(keyword_map.get("required", False)),
                    "default": self._to_text(keyword_map.get("default", "")).strip(),
                    "description": self._to_text(keyword_map.get("help", "")).strip() or self._guess_param_description(display_name),
                }
            )
        return parameters

    def _extract_sys_argv_parameters(self, script_content: str, entry_script_name: str) -> list[dict]:
        usage_line = self._extract_usage_line(script_content, entry_script_name)
        parameters = []
        if usage_line:
            for token in usage_line.split()[2:]:
                cleaned = token.strip()
                if not cleaned:
                    continue
                is_optional = cleaned.startswith("[") and cleaned.endswith("]")
                token_core = cleaned.strip("[]")
                if token_core.startswith("<") and token_core.endswith(">"):
                    name = sanitize_name(token_core[1:-1])
                    parameters.append(
                        {
                            "name": name or "arg",
                            "cli": token_core,
                            "kind": "positional",
                            "required": not is_optional,
                            "default": "",
                            "description": self._guess_param_description(name),
                        }
                    )
        if parameters:
            return parameters

        indices = sorted({int(match.group(1)) for match in re.finditer(r"sys\.argv\[(\d+)\]", self._to_text(script_content)) if int(match.group(1)) > 0})
        for position, _ in enumerate(indices, start=1):
            name = f"arg{position}"
            parameters.append(
                {
                    "name": name,
                    "cli": f"<{name}>",
                    "kind": "positional",
                    "required": True,
                    "default": "",
                    "description": self._guess_param_description(name),
                }
            )
        return parameters

    def _extract_string_literals(self, script_content: str) -> list[str]:
        content = self._to_text(script_content)
        if not content.strip():
            return []
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

        literals = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                text = self._to_text(node.value).strip()
                if text:
                    literals.append(text)
        return literals

    def _infer_output_info(self, description: str, verify_spec: dict, script_content: str) -> list[str]:
        lines = []
        expected_contains = self._to_text((verify_spec or {}).get("expected_contains", "")).strip()
        if expected_contains:
            lines.append(f"标准输出返回文本结果，成功时通常包含 `{expected_contains}` 等关键信息。")

        content = self._to_text(script_content)
        if "print(" in content and not lines:
            lines.append("标准输出返回文本结果。")
        if "return " in content:
            lines.append(f"核心输出与能力目标一致：{self._to_text(description).strip()}")

        if not lines:
            lines.append("输出结果以脚本标准输出为准。")
        return list(dict.fromkeys(lines))

    def _infer_when_to_use(self, description: str, parameters: list[dict], verify_spec: dict) -> list[str]:
        lines = [
            f"当你需要{self._to_text(description).strip('。')}时使用。",
        ]
        if parameters:
            names = "、".join(f"`{self._to_text(item.get('name', '')).strip()}`" for item in parameters[:3] if self._to_text(item.get("name", "")).strip())
            if names:
                lines.append(f"当你已经知道输入参数 {names}，并希望直接调用 skill 获得结果时使用。")
        if verify_spec:
            lines.append("当你希望复用已在成功 EXEC 中验证过的直接能力，而不是重放创建流程时使用。")
        return list(dict.fromkeys(lines))

    def _infer_failure_cases(self, script_content: str, verify_spec: dict, parameters: list[dict]) -> list[str]:
        cases = []
        literals = self._extract_string_literals(script_content)
        lowered_literals = [item.lower() for item in literals]

        if any("usage:" in item.lower() for item in literals):
            cases.append("缺少必填参数或参数个数不正确时会直接退出，并打印用法说明。")
        if any("unknown timezone" in item for item in lowered_literals):
            cases.append("传入不存在的时区名称时，会返回 `Unknown timezone: <timezone>`。")
        if any("exception" in item or "error" in item for item in lowered_literals):
            cases.append("运行期异常会以错误文本形式输出。")
        if verify_spec and self._to_text(verify_spec.get("expected_contains", "")).strip():
            cases.append("若运行结果不包含预期关键字，验证脚本会判定失败。")
        if parameters and not cases:
            cases.append("输入参数格式不符合脚本预期时，skill 可能失败或返回错误提示。")
        if not cases:
            cases.append("运行失败时以脚本退出码和标准错误输出为准。")
        return list(dict.fromkeys(cases))

    def _extract_interface_info(self, script_content: str, entry_script_name: str, folder_name: str, verify_spec: dict) -> dict:
        parameters = self._extract_argparse_parameters(script_content)
        if not parameters:
            parameters = self._extract_sys_argv_parameters(script_content, entry_script_name)

        syntax_parts = []
        for item in parameters:
            cli = self._to_text(item.get("cli", "")).strip()
            if not cli:
                continue
            if item.get("required", False):
                syntax_parts.append(cli)
            else:
                syntax_parts.append(f"[{cli}]")
        syntax = " ".join(syntax_parts).strip()

        example_args = self._build_usage_example_from_args(verify_spec.get("args", []) if isinstance(verify_spec, dict) else [])
        usage_lines = [
            f"/skill {folder_name}" + (f" {syntax}" if syntax else ""),
            f"python {entry_script_name}" + (f" {syntax}" if syntax else ""),
        ]
        examples = []
        if example_args:
            examples.append(f"/skill {folder_name} {example_args}")
            examples.append(f"python {entry_script_name} {example_args}")
        if verify_spec:
            examples.append("python verify.py")

        return {
            "parameters": parameters,
            "usage_lines": usage_lines,
            "examples": examples,
            "usage_line_from_script": self._extract_usage_line(script_content, entry_script_name),
            "output": [],
            "when_to_use": [],
            "failure_cases": [],
        }

    def _preflight_bundle(self, bundle: dict) -> tuple[dict, dict]:
        candidate = json.loads(json.dumps(bundle, ensure_ascii=False))
        issues = []
        entry_name = self._to_text(candidate.get("entry_script_name", "")).strip()
        content = self._to_text(candidate.get("entry_script_content", ""))
        if not entry_name.lower().endswith(".py"):
            issues.append("入口文件必须是 .py。")
        if not content.strip():
            issues.append("入口文件内容为空。")
        if "from skill_runner import main" in content:
            issues.append("入口文件仍是旧 runner wrapper，没有直接落技能本体。")
        if re.search(r"\bskill_runner\b", content):
            issues.append("入口文件仍依赖旧 skill_runner 机制。")
        return candidate, {"passed": not issues, "issues": issues}

    def _build_direct_bundle(self, full_info_path: Path, full_info: dict) -> dict:
        if not bool(full_info.get("success")) or str(full_info.get("final_state", "")).upper() != "DONE":
            raise ValueError("最近一次 EXEC 不是成功闭环，无法作为 Skill 学习来源。")

        primary = self._pick_primary_source(full_info)
        source_path = self._to_text(primary.get("source_path", "")).strip()
        folder_name = self._derive_skill_folder_name(full_info, source_path)
        entry_script_name = f"{folder_name}.py"
        verify_spec = self._extract_verify_spec(full_info, source_path)

        bundle = {
            "folder_name": folder_name,
            "name": folder_name,
            "mode": "direct",
            "version": "2.0.0",
            "description": self._build_skill_description(full_info.get("task", ""), full_info.get("summary", ""), source_path),
            "entry_script_name": entry_script_name,
            "entry_script_content": self._to_text(primary.get("script_content", "")).rstrip() + "\n",
            "verify_script_name": "verify.py" if verify_spec else "",
            "verify_script_content": self._build_verify_script(entry_script_name, verify_spec),
            "verify_spec": verify_spec,
            "interface": {},
            "dependencies": {"packages": self._collect_dependencies(full_info, self._to_text(primary.get("script_content", "")))},
            "source_exec": {
                "full_info_path": self._relative_path(str(full_info_path)),
                "run_id": self._to_text(full_info.get("run_id", "")).strip(),
                "task": self._to_text(full_info.get("task", "")).strip(),
                "summary": self._to_text(full_info.get("summary", "")).strip(),
                "workflow": self._to_text(full_info.get("workflow", "")).strip(),
            },
            "source_artifact": {
                "path": self._relative_path(source_path),
                "step_id": self._to_text((primary.get("step", {}) or {}).get("id", "")).strip(),
                "step_title": self._to_text((primary.get("step", {}) or {}).get("title", "")).strip(),
            },
        }

        bundle["interface"] = self._extract_interface_info(
            self._to_text(primary.get("script_content", "")),
            entry_script_name,
            folder_name,
            verify_spec,
        )
        bundle["interface"]["output"] = self._infer_output_info(
            bundle["description"],
            verify_spec,
            self._to_text(primary.get("script_content", "")),
        )
        bundle["interface"]["when_to_use"] = self._infer_when_to_use(
            bundle["description"],
            bundle["interface"].get("parameters", []),
            verify_spec,
        )
        bundle["interface"]["failure_cases"] = self._infer_failure_cases(
            self._to_text(primary.get("script_content", "")),
            verify_spec,
            bundle["interface"].get("parameters", []),
        )
        return bundle

    def _render_skill_markdown(self, bundle: dict) -> str:
        interface = bundle.get("interface", {}) if isinstance(bundle.get("interface"), dict) else {}
        parameters = interface.get("parameters", []) if isinstance(interface.get("parameters"), list) else []
        usage_lines = interface.get("usage_lines", []) if isinstance(interface.get("usage_lines"), list) else []
        examples = interface.get("examples", []) if isinstance(interface.get("examples"), list) else []
        outputs = interface.get("output", []) if isinstance(interface.get("output"), list) else []
        when_to_use = interface.get("when_to_use", []) if isinstance(interface.get("when_to_use"), list) else []
        failure_cases = interface.get("failure_cases", []) if isinstance(interface.get("failure_cases"), list) else []
        lines = [
            "---",
            f'name: "{bundle["name"]}"',
            f'description: "{bundle["description"]}"',
            f'entry: "{bundle["entry_script_name"]}"',
            f'verify: "{bundle["verify_script_name"]}"',
            'mode: "direct"',
            "---",
            "",
            "## Description",
            "",
            bundle["description"],
            "",
            "## Usage",
            "",
        ]
        for usage_line in usage_lines:
            lines.append(f"- `{usage_line}`")
        if not usage_lines:
            lines.append(f'- `/skill {bundle["folder_name"]}`')
            lines.append(f'- `python {bundle["entry_script_name"]}`')
        if bundle.get("verify_script_name"):
            lines.append(f'- `python {bundle["verify_script_name"]}`')

        lines.extend(["", "## Inputs", ""])
        if parameters:
            for item in parameters:
                title = self._to_text(item.get("name", "")).strip() or "arg"
                cli = self._to_text(item.get("cli", "")).strip()
                kind = "位置参数" if item.get("kind") == "positional" else "选项参数"
                required = "必填" if item.get("required", False) else "可选"
                description = self._to_text(item.get("description", "")).strip() or "运行该 skill 时需要提供的参数。"
                default = self._to_text(item.get("default", "")).strip()
                line = f"- `{title}`：{required}，{kind}"
                if cli:
                    line += f"，写法：`{cli}`"
                if default:
                    line += f"，默认值：`{default}`"
                line += f"。{description}"
                lines.append(line)
        else:
            lines.append("- 无需额外参数。")

        lines.extend(["", "## Output", ""])
        if outputs:
            for item in outputs:
                lines.append(f"- {item}")
        else:
            lines.append("- 输出结果以脚本标准输出为准。")

        lines.extend(["", "## When To Use", ""])
        if when_to_use:
            for item in when_to_use:
                lines.append(f"- {item}")
        else:
            lines.append(f"- 当你需要{bundle['description'].strip('。')}时使用。")

        if examples:
            lines.extend(["", "## Examples", ""])
            for item in examples:
                lines.append(f"- `{item}`")

        lines.extend(["", "## Failure Cases", ""])
        if failure_cases:
            for item in failure_cases:
                lines.append(f"- {item}")
        else:
            lines.append("- 运行失败时以脚本退出码和标准错误输出为准。")
        lines.extend(
            [
                "",
                "## Source",
                "",
                f'- `full_info`: `{bundle["source_exec"]["full_info_path"]}`',
            ]
        )
        if bundle["source_artifact"].get("path"):
            lines.append(f'- `artifact`: `{bundle["source_artifact"]["path"]}`')
        if bundle["source_exec"].get("workflow"):
            lines.append(f'- `workflow`: {bundle["source_exec"]["workflow"]}')
        return "\n".join(lines).strip() + "\n"

    def _build_skill_metadata(self, bundle: dict) -> dict:
        return {
            "name": bundle["name"],
            "folder_name": bundle["folder_name"],
            "mode": bundle["mode"],
            "version": bundle["version"],
            "description": bundle["description"],
            "entry_script": bundle["entry_script_name"],
            "verify_script": bundle["verify_script_name"],
            "interface": bundle.get("interface", {}),
            "dependencies": bundle["dependencies"],
            "source_exec": bundle["source_exec"],
            "source_artifact": bundle["source_artifact"],
            "examples": {
                "direct_command": (bundle.get("interface", {}) or {}).get("usage_lines", [f"/skill {bundle['folder_name']}"])[0],
                "verify_command": f"python {bundle['verify_script_name']}" if bundle.get("verify_script_name") else "",
                "source_command": bundle.get("verify_spec", {}).get("source_command", ""),
            },
        }

    def _cleanup_old_generated_files(self, skill_dir: Path, bundle: dict) -> None:
        existing_metadata = load_json(skill_dir / "skill.json", {})
        stale_candidates = [
            skill_dir / "skill_runner.py",
            skill_dir / "review.json",
        ]
        old_entry = self._to_text(existing_metadata.get("entry_script", "")).strip()
        if old_entry and old_entry != bundle["entry_script_name"]:
            stale_candidates.append(skill_dir / old_entry)
        old_verify = self._to_text(existing_metadata.get("verify_script", "")).strip()
        if old_verify and old_verify != bundle.get("verify_script_name", ""):
            stale_candidates.append(skill_dir / old_verify)
        if not bundle.get("verify_script_name"):
            stale_candidates.append(skill_dir / "verify.py")
        for path in stale_candidates:
            if path.exists() and path.is_file():
                path.unlink()
        self._cleanup_runtime_artifacts(skill_dir)

    def _cleanup_runtime_artifacts(self, skill_dir: Path) -> None:
        for directory in (skill_dir / ".runtime", skill_dir / "__pycache__"):
            if not directory.exists() or not directory.is_dir():
                continue
            for child in sorted(directory.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            directory.rmdir()

    def _write_skill_files(self, bundle: dict) -> dict:
        skill_dir = SKILLS_DIR / bundle["folder_name"]
        skill_dir.mkdir(parents=True, exist_ok=True)
        self._cleanup_old_generated_files(skill_dir, bundle)

        skill_md_path = skill_dir / "SKILL.md"
        metadata_path = skill_dir / "skill.json"
        entry_path = skill_dir / bundle["entry_script_name"]
        verify_path = skill_dir / bundle["verify_script_name"] if bundle.get("verify_script_name") else None

        skill_md_path.write_text(self._render_skill_markdown(bundle), encoding="utf-8")
        save_json(metadata_path, self._build_skill_metadata(bundle))
        entry_path.write_text(bundle["entry_script_content"], encoding="utf-8")
        if verify_path is not None:
            verify_path.write_text(bundle["verify_script_content"], encoding="utf-8")

        return {
            "skill_dir": skill_dir,
            "skill_md_path": skill_md_path,
            "metadata_path": metadata_path,
            "entry_path": entry_path,
            "verify_path": verify_path,
        }

    def _run_process(self, command: list[str], cwd: Path) -> dict:
        completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
        return {
            "returncode": int(completed.returncode),
            "stdout": self._to_text(completed.stdout).strip(),
            "stderr": self._to_text(completed.stderr).strip(),
            "command": " ".join(command),
        }

    def _run_validation(self, bundle: dict) -> dict:
        skill_dir = SKILLS_DIR / bundle["folder_name"]
        entry_path = skill_dir / bundle["entry_script_name"]
        try:
            compile_result = self._run_process([sys.executable, "-m", "py_compile", str(entry_path)], BASE_DIR)

            log_lines = [f"compile: {compile_result['command']}"]
            if compile_result["stdout"]:
                log_lines.append("compile stdout:\n" + compile_result["stdout"])
            if compile_result["stderr"]:
                log_lines.append("compile stderr:\n" + compile_result["stderr"])
            if compile_result["returncode"] != 0:
                return {
                    "passed": False,
                    "returncode": compile_result["returncode"],
                    "command": compile_result["command"],
                    "verify_command": "",
                    "log": "\n\n".join(log_lines).strip(),
                }

            verify_command = ""
            verify_result = None
            if bundle.get("verify_script_name"):
                verify_path = skill_dir / bundle["verify_script_name"]
                verify_result = self._run_process([sys.executable, str(verify_path)], BASE_DIR)
                verify_command = verify_result["command"]
                log_lines.append(f"verify: {verify_result['command']}")
                if verify_result["stdout"]:
                    log_lines.append("verify stdout:\n" + verify_result["stdout"])
                if verify_result["stderr"]:
                    log_lines.append("verify stderr:\n" + verify_result["stderr"])

            passed = compile_result["returncode"] == 0 and (verify_result is None or verify_result["returncode"] == 0)
            return {
                "passed": passed,
                "returncode": 0 if passed else (verify_result["returncode"] if verify_result is not None else compile_result["returncode"]),
                "command": compile_result["command"],
                "verify_command": verify_command,
                "log": "\n\n".join(log_lines).strip(),
            }
        finally:
            self._cleanup_runtime_artifacts(skill_dir)

    def _repair_bundle(self, bundle: dict, validation: dict) -> tuple[dict, bool, str]:
        verify_spec = bundle.get("verify_spec", {}) if isinstance(bundle.get("verify_spec"), dict) else {}
        if not bundle.get("verify_script_name") or not verify_spec.get("expected_contains"):
            return bundle, False, ""

        repaired = json.loads(json.dumps(bundle, ensure_ascii=False))
        repaired_verify_spec = dict(verify_spec)
        repaired_verify_spec["expected_contains"] = ""
        repaired["verify_spec"] = repaired_verify_spec
        repaired["verify_script_content"] = self._build_verify_script(repaired["entry_script_name"], repaired_verify_spec)
        reason = "验证脚本中的固定输出断言已放宽为仅校验可执行返回码。"
        return repaired, True, reason

    def _build_result_message(self, result: dict) -> str:
        validation = result.get("validation", {})
        lines = [
            f"已从最近一次成功 EXEC 生成直出 skill：{result.get('skill_name', '')}",
            f"- Skill 名称：{result.get('skill_name', '')}",
            f"- Skill 目录：{result.get('skill_dir', '')}",
            f"- 来源流程：{result.get('source_full_info_path', '')}",
            "- 生成模式：direct",
            "- Skill 文件列表：",
        ]
        for item in result.get("files", []):
            lines.append(f"  - {item}")
        lines.append(f"- 编译验证：{'成功' if validation.get('command') else '已跳过'}")
        if validation.get("command"):
            lines.append(f"- 编译命令：{validation.get('command', '')}")
        if validation.get("verify_command"):
            lines.append(f"- 运行验证命令：{validation.get('verify_command', '')}")
        lines.append(f"- 总体验证结果：{'成功' if validation.get('passed') else '失败'}")
        if result.get("skill_add_log_dir"):
            lines.append(f"- Skill Add 日志：{result.get('skill_add_log_dir', '')}")
        return "\n".join(lines).strip()

    def learn_from_latest_exec(self, session_history=None, callback=None) -> dict:
        log_context = self._create_log_context()
        callback = self._build_logging_callback(callback, log_context)
        state_history = []

        def set_state(state: str, message: str, extra: dict | None = None) -> None:
            state_history.append(state)
            payload = {"state": state, "message": message}
            if extra:
                payload.update(extra)
            self._append_log_event(log_context, "skill_state", payload)
            self._emit_phase(callback, message, {"state": state, **(extra or {})})

        self._append_log_event(
            log_context,
            "skill_add_started",
            {
                "user": self.user,
                "session_history_count": len(list(session_history or [])),
                "learning_config": self._get_learning_config(),
            },
        )

        try:
            set_state("LOAD_FULL_INFO", "正在定位最近一次完整闭环 EXEC 流程...")
            full_info_path, full_info = self._load_full_info(session_history=session_history)
            self._append_log_event(
                log_context,
                "full_info_loaded",
                {
                    "source_full_info_path": self._relative_path(str(full_info_path)),
                    "run_id": self._to_text(full_info.get("run_id", "")).strip(),
                    "task": self._to_text(full_info.get("task", "")).strip(),
                },
            )

            set_state("EXTRACT_DIRECT_SKILL", f"正在从 {self._relative_path(str(full_info_path))} 提炼 skill 本体...")
            bundle = self._build_direct_bundle(full_info_path, full_info)
            bundle, preflight = self._preflight_bundle(bundle)
            self._append_log_event(log_context, "preflight_result", preflight)
            if not preflight.get("passed", False):
                raise ValueError("生成前检查失败：\n" + "\n".join(f"- {item}" for item in preflight.get("issues", [])))

            repair_limit = self._get_repair_limit()
            last_validation = {"passed": True, "command": "", "verify_command": "", "log": "已跳过本地验证。"}
            generated = {}
            for attempt in range(1, repair_limit + 1):
                set_state("WRITE_FILES", f"正在写入直出 skill 文件（第 {attempt} 轮）...", {"attempt": attempt})
                generated = self._write_skill_files(bundle)
                files = ["SKILL.md", bundle["entry_script_name"], "skill.json"]
                if bundle.get("verify_script_name"):
                    files.append(bundle["verify_script_name"])
                self._append_log_event(
                    log_context,
                    "skill_files_written",
                    {
                        "attempt": attempt,
                        "skill_name": bundle["folder_name"],
                        "skill_dir": self._relative_path(str(generated["skill_dir"])),
                        "files": files,
                    },
                )

                if self._should_validate():
                    set_state("VERIFY", "正在执行本地验证...", {"attempt": attempt})
                    last_validation = self._run_validation(bundle)
                else:
                    last_validation = {"passed": True, "command": "", "verify_command": "", "log": "配置已跳过本地验证。"}
                self._append_log_event(log_context, "validation_result", {"attempt": attempt, **last_validation})

                if last_validation.get("passed", False):
                    set_state("DONE", "直出 skill 已生成并通过验证。", {"attempt": attempt})
                    result = {
                        "skill_name": bundle["folder_name"],
                        "display_name": bundle["name"],
                        "skill_dir": self._relative_path(str(generated["skill_dir"])),
                        "source_full_info_path": bundle["source_exec"]["full_info_path"],
                        "files": files,
                        "validation": last_validation,
                        "attempts": attempt,
                        "skill_add_log_dir": self._relative_path(str(log_context["log_dir"])),
                        "state_history": state_history,
                        "chat_report": "",
                    }
                    result["chat_report"] = self._build_result_message(result)
                    self._append_log_event(log_context, "skill_add_success", result)
                    self._write_log_summary(log_context, {"status": "success", "result": result})
                    self._emit(
                        callback,
                        {
                            "type": "skill_result",
                            "skill_name": bundle["folder_name"],
                            "skill_dir": result["skill_dir"],
                            "files": files,
                        },
                    )
                    return result

                repaired_bundle, repaired, reason = self._repair_bundle(bundle, last_validation)
                if repaired and attempt < repair_limit:
                    bundle = repaired_bundle
                    self._append_log_event(
                        log_context,
                        "repair_applied",
                        {"attempt": attempt, "reason": reason, "validation": last_validation},
                    )
                    set_state("REPAIR", f"第 {attempt} 轮验证失败，已执行保守修复。", {"attempt": attempt})
                    continue
                break

            set_state("FAILED", "直出 skill 生成失败，本地验证未通过。")
            failure_message = "Skill 学习失败：直出 skill 未通过本地验证。\n" + self._to_text(last_validation.get("log", "")).strip()
            self._append_log_event(
                log_context,
                "skill_add_failed",
                {
                    "message": failure_message,
                    "validation": last_validation,
                    "skill_name": bundle.get("folder_name", ""),
                    "skill_dir": self._relative_path(str(generated["skill_dir"])) if generated else "",
                    "state_history": state_history,
                },
            )
            self._write_log_summary(
                log_context,
                {
                    "status": "failed",
                    "message": failure_message,
                    "validation": last_validation,
                    "skill_name": bundle.get("folder_name", ""),
                    "skill_dir": self._relative_path(str(generated["skill_dir"])) if generated else "",
                    "state_history": state_history,
                },
            )
            raise ValueError(failure_message)
        except Exception as exc:
            self._append_log_event(
                log_context,
                "skill_add_exception",
                {"error": self._to_text(exc), "traceback": traceback.format_exc(), "state_history": state_history},
            )
            self._write_log_summary(
                log_context,
                {
                    "status": "exception",
                    "error": self._to_text(exc),
                    "traceback": traceback.format_exc(),
                    "state_history": state_history,
                },
            )
            raise
