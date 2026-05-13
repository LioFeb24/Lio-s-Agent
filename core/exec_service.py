import json
import locale
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from core.constants import BASE_DIR, EXEC_FULL_INFO_DIR, EXEC_PLAN_DIR, EXEC_RESULT_DIR, EXEC_SCRIPT_DIR
from core.file_utils import sanitize_name, sanitize_username, save_json
from core.format_llm_output import call_llm_json, extract_preferred_code_block, handle
from core.llm_api import call_llm
from core.sendbox import CubeSandboxAdapter, CubeSandboxDisabled
from core.skill_loader import SkillRepository
from core.tool_loader import ToolRepository


STATE_PLAN = "PLAN"
STATE_EXECUTE = "EXECUTE"
STATE_VERIFY_STEP = "VERIFY_STEP"
STATE_RETRY_STEP = "RETRY_STEP"
STATE_REVIEW_REPLAN = "REVIEW_REPLAN"
STATE_VERIFY_FINAL = "VERIFY_FINAL"
STATE_DONE = "DONE"
STATE_FAILED = "FAILED"


class Executor:
    """统一本地执行入口，负责 shell/python/file/tool 四类 step。"""

    def __init__(self, base_dir: Path, script_dir: Path, sandbox=None) -> None:
        self.base_dir = base_dir
        self.script_dir = script_dir
        self.sandbox = sandbox or CubeSandboxDisabled()
        self.run_id = "default"
        self.tool_handlers = {
            "list_dir": self._tool_list_dir,
            "read_text": self._tool_read_text,
            "path_exists": self._tool_path_exists,
            "glob": self._tool_glob,
        }

    def set_run_context(self, run_id: str, emit=None) -> None:
        self.run_id = run_id
        self.sandbox.prepare_run(run_id, emit=emit)

    def finish_run_context(self, emit=None) -> None:
        self.sandbox.finish_run(emit=emit)

    def get_backend_summary(self) -> dict:
        return self.sandbox.get_runtime_summary()

    def register_tool(self, name: str, handler) -> None:
        self.tool_handlers[str(name).strip()] = handler

    def run(self, step: dict) -> dict:
        """统一执行入口，返回 returncode/stdout/stderr 等观测结果。"""
        step_id = str(step.get("id", "step"))
        title = str(step.get("title", step_id))
        kind = str(step.get("kind", "")).strip().lower()
        command = self._to_text(step.get("command", "")).strip()
        script_content = self._to_text(step.get("script_content", ""))
        script_path = ""

        try:
            if kind == "shell":
                if not command:
                    raise ValueError("shell step 缺少 command。")
                completed = self._run_shell(command)
            elif kind == "python":
                if not script_content.strip():
                    raise ValueError("python step 缺少 script_content。")
                path = self._write_script_file(step_id, ".py", script_content)
                script_path = str(path)
                completed = self._run_python(path, script_content)
            elif kind == "file":
                completed = self._run_file_step(command, script_content)
            elif kind == "tool":
                completed = self._run_tool_step(command)
            else:
                raise ValueError(f"未知 step.kind：{kind}")

            returncode = int(completed.returncode)
            stdout = self._to_text(completed.stdout)
            stderr = self._to_text(completed.stderr)
        except Exception as exc:
            returncode = -1
            stdout = ""
            stderr = str(exc)

        return {
            "id": step_id,
            "title": title,
            "kind": kind,
            "command": command,
            "script_content": script_content,
            "script_path": script_path,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "success": returncode == 0,
            "verify": step.get("verify", ""),
            "retry_count": step.get("_retry_count", 0),
            "depth": step.get("_depth", 0),
            "origin_id": step.get("_origin_id", step_id),
            "execution_backend": self.get_backend_summary(),
        }

    def _to_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    def _resolve_path(self, path_text: str) -> Path:
        raw = str(path_text or "").strip()
        if not raw:
            raise ValueError("缺少 path。")
        path = Path(raw)
        if not path.is_absolute():
            path = self.base_dir / path
        return path.resolve()

    def _parse_command_payload(self, command: str, field_name: str) -> dict:
        parsed = handle("json", command, "parse")
        if not parsed["success"] or not isinstance(parsed.get("data"), dict):
            raise ValueError(f"{field_name} 必须是 JSON 对象字符串。")
        return parsed["data"]

    def _to_int(self, value, default: int, minimum: int = 0) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, number)

    def _normalize_tool_name(self, name: str) -> str:
        text = str(name or "").strip().lower()
        aliases = {
            "shell": "shell",
            "run_command": "shell",
            "execute_command": "shell",
            "command": "shell",
            "command_runner": "shell",
            "powershell": "shell",
            "powershell_command": "shell",
            "local_shell": "shell",
            "list_dir": "list_dir",
            "list_files": "list_dir",
            "list_directory": "list_dir",
            "dir": "list_dir",
            "ls": "list_dir",
            "read_text": "read_text",
            "read_file": "read_text",
            "cat_file": "read_text",
            "open_file": "read_text",
            "path_exists": "path_exists",
            "exists": "path_exists",
            "file_exists": "path_exists",
            "glob": "glob",
            "glob_files": "glob",
            "find_files": "glob",
            "list_skills": "list_skills",
            "skills": "list_skills",
            "skill_list": "list_skills",
            "read_skill": "read_skill",
            "skill": "read_skill",
            "skill_read": "read_skill",
            "open_skill": "read_skill",
            "list_tools": "list_tools",
            "tools": "list_tools",
            "tool_list": "list_tools",
            "read_tool": "read_tool",
            "tool": "read_tool",
            "tool_read": "read_tool",
            "open_tool": "read_tool",
            "llm_dispatch": "llm_dispatch",
            "ask_llm": "llm_dispatch",
            "dispatch_llm": "llm_dispatch",
            "llm_task": "llm_dispatch",
            "summarize_with_llm": "llm_dispatch",
            "extract_with_llm": "llm_dispatch",
        }
        return aliases.get(text, text)

    def _normalize_tool_args(self, name: str, args) -> dict:
        data = dict(args or {}) if isinstance(args, dict) else {}
        if name == "shell":
            return {
                "command": self._to_text(
                    data.get("command")
                    or data.get("cmd")
                    or data.get("script")
                    or data.get("text")
                    or ""
                ).strip()
            }
        if name == "list_dir":
            return {
                "path": self._to_text(
                    data.get("path")
                    or data.get("target_directory")
                    or data.get("directory")
                    or data.get("dir")
                    or "."
                ).strip()
                or ".",
                "depth": self._to_int(data.get("depth", 1), default=1, minimum=1),
                "offset": self._to_int(data.get("offset", 0), default=0, minimum=0),
                "limit": self._to_int(data.get("limit", 200), default=200, minimum=1),
            }
        if name == "read_text":
            return {
                "path": self._to_text(
                    data.get("path") or data.get("file_path") or data.get("target_file") or data.get("file") or ""
                ).strip()
            }
        if name == "path_exists":
            return {
                "path": self._to_text(
                    data.get("path") or data.get("file_path") or data.get("target_path") or data.get("target") or ""
                ).strip()
            }
        if name == "glob":
            return {
                "path": self._to_text(
                    data.get("path")
                    or data.get("target_directory")
                    or data.get("directory")
                    or data.get("base_path")
                    or "."
                ).strip()
                or ".",
                "pattern": self._to_text(data.get("pattern") or data.get("glob") or data.get("match") or "*").strip()
                or "*",
            }
        if name == "list_skills":
            return {}
        if name == "read_skill":
            return {
                "name": self._to_text(
                    data.get("name")
                    or data.get("skill")
                    or data.get("skill_name")
                    or data.get("folder")
                    or ""
                ).strip()
            }
        if name == "list_tools":
            return {}
        if name == "read_tool":
            return {
                "name": self._to_text(
                    data.get("name")
                    or data.get("tool")
                    or data.get("tool_name")
                    or data.get("folder")
                    or ""
                ).strip()
            }
        if name == "llm_dispatch":
            return {
                "task": self._to_text(
                    data.get("task") or data.get("instruction") or data.get("prompt") or data.get("goal") or ""
                ).strip(),
                "input": self._to_text(
                    data.get("input") or data.get("content") or data.get("text") or data.get("source") or ""
                ),
                "context": self._to_text(
                    data.get("context") or data.get("step_context") or data.get("focus") or ""
                ),
                "system_prompt": self._to_text(data.get("system_prompt") or data.get("system") or "").strip(),
                "output_format": self._to_text(data.get("output_format") or data.get("format") or "text").strip().lower()
                or "text",
                "response_schema": data.get("response_schema", {}) if isinstance(data.get("response_schema", {}), dict) else {},
                "include_run_context": bool(data.get("include_run_context", False)),
                "include_history": bool(data.get("include_history", False)),
                "llm_profile": self._to_text(data.get("llm_profile") or data.get("profile") or "").strip(),
                "_expectation": data.get("_expectation", {}) if isinstance(data.get("_expectation", {}), dict) else {},
                "_runtime_context": data.get("_runtime_context", {}) if isinstance(data.get("_runtime_context", {}), dict) else {},
            }
        return data

    def normalize_tool_call(self, name: str, args) -> tuple[str, dict]:
        normalized_name = self._normalize_tool_name(name)
        normalized_args = self._normalize_tool_args(normalized_name, args)
        return normalized_name, normalized_args

    def normalize_tool_command(self, command: str) -> str:
        text = self._to_text(command).strip()
        if not text:
            return text
        spec = self._parse_optional_json_object(text)
        if spec is None:
            # tool.command 偶尔会被模型直接输出成原始命令，这里自动降级为 shell 工具调用。
            return json.dumps({"name": "shell", "args": {"command": text}}, ensure_ascii=False, indent=4)
        name, args = self.normalize_tool_call(spec.get("name", ""), spec.get("args", {}))
        return json.dumps({"name": name, "args": args}, ensure_ascii=False, indent=4)

    def _parse_optional_json_object(self, text: str):
        parsed = handle("json", text, "parse")
        if parsed["success"] and isinstance(parsed.get("data"), dict):
            return parsed["data"]
        return None

    def _build_completed(self, returncode: int, stdout="", stderr="") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=self._to_text(stdout),
            stderr=self._to_text(stderr),
        )

    def _decode_output(self, data) -> str:
        """按 Windows 常见编码回退解码子进程输出，避免中文乱码。"""
        if data is None:
            return ""
        if isinstance(data, str):
            return data

        preferred = locale.getpreferredencoding(False) or ""
        candidates = []
        for encoding in ("utf-8", "utf-8-sig", preferred, "gbk", "cp936"):
            normalized = str(encoding or "").strip().lower()
            if normalized and normalized not in candidates:
                candidates.append(normalized)

        for encoding in candidates:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode(candidates[0] if candidates else "utf-8", errors="replace")

    def _write_script_file(self, step_id: str, suffix: str, content: str) -> Path:
        file_name = f"{self.run_id}_{sanitize_name(step_id)}{suffix}"
        script_path = self.script_dir / file_name
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(content)
        return script_path

    def _run_shell(self, command: str) -> subprocess.CompletedProcess:
        if self.sandbox.enabled:
            return self.sandbox.run_shell(command)
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            cwd=str(self.base_dir),
            capture_output=True,
            text=False,
        )
        return self._build_completed(
            completed.returncode,
            stdout=self._decode_output(completed.stdout),
            stderr=self._decode_output(completed.stderr),
        )

    def _run_python(self, script_path: Path, script_content: str) -> subprocess.CompletedProcess:
        if self.sandbox.enabled:
            return self.sandbox.run_python(script_path.name, script_content)
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=str(self.base_dir),
            capture_output=True,
            text=False,
        )
        return self._build_completed(
            completed.returncode,
            stdout=self._decode_output(completed.stdout),
            stderr=self._decode_output(completed.stderr),
        )

    def _run_file_step(self, command: str, script_content: str) -> subprocess.CompletedProcess:
        spec = self._parse_command_payload(command, "file.command")
        if self.sandbox.enabled:
            return self.sandbox.run_file_step(spec, script_content)
        action = str(spec.get("action", "")).strip().lower()
        path = self._resolve_path(spec.get("path", ""))

        if action == "read":
            if not path.exists():
                raise FileNotFoundError(f"文件不存在：{path}")
            return self._build_completed(0, stdout=path.read_text(encoding="utf-8"))

        if action == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(script_content, encoding="utf-8")
            return self._build_completed(0, stdout=f"已写入文件：{path}")

        if action == "append":
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(script_content)
            return self._build_completed(0, stdout=f"已追加文件：{path}")

        if action == "replace":
            if not path.exists():
                raise FileNotFoundError(f"文件不存在：{path}")
            old = self._to_text(spec.get("old", ""))
            new = self._to_text(spec.get("new", ""))
            text = path.read_text(encoding="utf-8")
            if old not in text:
                raise ValueError("replace 失败：未找到 old 内容。")
            path.write_text(text.replace(old, new), encoding="utf-8")
            return self._build_completed(0, stdout=f"已修改文件：{path}")

        if action == "delete":
            if not path.exists():
                return self._build_completed(0, stdout=f"目标不存在，无需删除：{path}")
            recursive = bool(spec.get("recursive", False))
            if path.is_dir():
                if recursive:
                    shutil.rmtree(path)
                else:
                    path.rmdir()
            else:
                path.unlink()
            return self._build_completed(0, stdout=f"已删除：{path}")

        if action == "mkdir":
            path.mkdir(parents=bool(spec.get("parents", True)), exist_ok=bool(spec.get("exist_ok", True)))
            return self._build_completed(0, stdout=f"已创建目录：{path}")

        if action == "list":
            if not path.exists():
                raise FileNotFoundError(f"目录不存在：{path}")
            if not path.is_dir():
                raise ValueError(f"list 目标不是目录：{path}")
            entries = [item.name for item in sorted(path.iterdir(), key=lambda x: x.name.lower())]
            return self._build_completed(0, stdout="\n".join(entries))

        raise ValueError(f"不支持的 file.action：{action}")

    def _run_tool_step(self, command: str) -> subprocess.CompletedProcess:
        spec = self._parse_command_payload(command, "tool.command")
        raw_name = str(spec.get("name", "")).strip()
        name, args = self.normalize_tool_call(raw_name, spec.get("args", {}))
        if self.sandbox.enabled and name in {"shell", "list_dir", "read_text", "path_exists", "glob"}:
            return self.sandbox.run_tool_step(name, args)
        if name == "shell":
            shell_command = self._to_text(args.get("command", "")).strip()
            if not shell_command:
                raise ValueError("tool.args.command 不能为空。")
            return self._run_shell(shell_command)
        handler = self.tool_handlers.get(name)
        if handler is None:
            supported = "、".join(sorted(self.tool_handlers.keys() | {"shell"}))
            raise ValueError(f"未注册的工具：{raw_name or name}。当前支持：{supported}")
        output = handler(args)
        return self._build_completed(0, stdout=output)

    def _tool_list_dir(self, args: dict) -> str:
        path = self._resolve_path(args.get("path", "."))
        if not path.exists():
            raise FileNotFoundError(f"目录不存在：{path}")
        if not path.is_dir():
            raise ValueError(f"list_dir 目标不是目录：{path}")

        depth = self._to_int(args.get("depth", 1), default=1, minimum=1)
        offset = self._to_int(args.get("offset", 0), default=0, minimum=0)
        limit = self._to_int(args.get("limit", 200), default=200, minimum=1)

        entries = []
        for item in sorted(path.rglob("*"), key=lambda x: str(x).lower()):
            relative = item.relative_to(path)
            if len(relative.parts) > depth:
                continue
            display = relative.as_posix()
            if item.is_dir():
                display += "/"
            entries.append(display)
        if depth <= 1 and not entries:
            entries = [item.name + ("/" if item.is_dir() else "") for item in sorted(path.iterdir(), key=lambda x: x.name.lower())]
        return "\n".join(entries[offset : offset + limit])

    def _tool_read_text(self, args: dict) -> str:
        path = self._resolve_path(args.get("path", ""))
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{path}")
        return path.read_text(encoding="utf-8")

    def _tool_path_exists(self, args: dict) -> str:
        path = self._resolve_path(args.get("path", ""))
        return "true" if path.exists() else "false"

    def _tool_glob(self, args: dict) -> str:
        base_path = self._resolve_path(args.get("path", "."))
        pattern = str(args.get("pattern", "*")).strip() or "*"
        matches = [str(item) for item in sorted(base_path.glob(pattern), key=lambda x: str(x).lower())]
        return "\n".join(matches)


class ExecService:
    """负责 AI-Agent 自主规划、执行、验证、修复与重试闭环。"""

    def __init__(
        self,
        config,
        user: str,
        skill_repository: SkillRepository | None = None,
        tool_repository: ToolRepository | None = None,
    ) -> None:
        self.config = config
        self.user = user
        self.skill_repository = skill_repository or SkillRepository()
        self.tool_repository = tool_repository or ToolRepository()
        self.exec_config = self._load_exec_config()
        self.sandbox_config = self._load_sandbox_config()
        self.executor = Executor(BASE_DIR, EXEC_SCRIPT_DIR, sandbox=self._build_sandbox_adapter())
        self.executor.register_tool("list_skills", self._tool_list_skills)
        self.executor.register_tool("read_skill", self._tool_read_skill)
        self.executor.register_tool("list_tools", self._tool_list_tools)
        self.executor.register_tool("read_tool", self._tool_read_tool)
        self.executor.register_tool("llm_dispatch", self._tool_llm_dispatch)
        self._register_project_tools()

    def _emit(self, callback, event: dict) -> None:
        if callback is not None:
            callback(event)

    def _register_project_tools(self) -> None:
        for summary in self.tool_repository.list_tools():
            handler = self.tool_repository.build_handler(summary["name"])
            self.executor.register_tool(summary["name"], handler)
            self.executor.register_tool(summary["folder"].lower(), handler)
            for alias in summary.get("aliases", []):
                self.executor.register_tool(alias, handler)

    def _emit_phase(self, callback, message: str, state: str | None = None, extra: dict | None = None) -> None:
        event = {"type": "exec_phase", "message": message}
        if state is not None:
            event["state"] = state
        if extra:
            event.update(extra)
        self._emit(callback, event)

    def _build_run_id(self) -> str:
        return f"{sanitize_username(self.user)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def _get_plan_paths(self, run_id: str) -> dict:
        return {
            "plan": EXEC_PLAN_DIR / f"{run_id}_plan.json",
            "result": EXEC_RESULT_DIR / f"{run_id}_result.json",
            "verify": EXEC_RESULT_DIR / f"{run_id}_verify.json",
            "report": EXEC_RESULT_DIR / f"{run_id}_report.md",
        }

    def _get_full_info_path(self, run_id: str) -> Path:
        return EXEC_FULL_INFO_DIR / f"{run_id}_full_info.json"

    def _serialize_event_for_log(self, event: dict) -> dict:
        data = {}
        for key, value in (event or {}).items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                data[key] = value
            else:
                data[key] = value
        return data

    def _record_event(self, collector: list[dict], event: dict) -> None:
        collector.append(
            {
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "event": self._serialize_event_for_log(event),
            }
        )

    def _build_decision_logs(self, event_logs: list[dict]) -> list[dict]:
        decision_logs = []
        for item in event_logs:
            event = item.get("event", {}) or {}
            event_type = self._to_text(event.get("type", "")).strip()
            if event_type not in {"exec_phase", "exec_plan", "exec_verify", "exec_step_start", "exec_step_done"}:
                continue
            decision_logs.append(
                {
                    "time": item.get("time", ""),
                    "type": event_type,
                    "message": self._to_text(event.get("message", "")).strip(),
                    "state": self._to_text(event.get("state", "")).strip(),
                }
            )
        return decision_logs

    def _build_full_exec_reference(
        self,
        run_id: str,
        task: str,
        started_at: str,
        finished_at: str,
        paths: dict,
        response: dict,
        result_data: dict,
        final_verify: dict,
        event_logs: list[dict],
    ) -> dict:
        normalized_response = self._normalize_result_envelope(response)
        result_block = ((normalized_response or {}).get("result") or {}) if isinstance(normalized_response, dict) else {}
        return {
            "run_id": run_id,
            "task": task,
            "started_at": started_at,
            "finished_at": finished_at,
            "final_state": self._to_text(result_data.get("final_state", "")).strip() or STATE_DONE,
            "completed": bool(final_verify.get("completed", False)),
            "success": bool(final_verify.get("passed", False)),
            "summary": self._to_text(final_verify.get("summary", "")).strip(),
            "verification": self._to_text(final_verify.get("verification", "")).strip(),
            "result_path": str(paths["result"]),
            "plan_path": str(paths["plan"]),
            "verify_path": str(paths["verify"]),
            "report_path": str(paths["report"]),
            "chat_report": self._to_text(normalized_response.get("chat_report", "")).strip(),
            "state_history": list(result_data.get("state_history", [])),
            "workflow": self._to_text((((normalized_response or {}).get("plan") or {}).get("workflow", ""))).strip(),
            "plan": (normalized_response or {}).get("plan", {}),
            "verify": final_verify,
            "sandbox": result_block.get("sandbox", {}),
            "artifacts": normalized_response.get("artifacts", []),
            "step_outcomes": list(result_data.get("step_outcomes", [])),
            "step_attempts": list(result_data.get("steps", [])),
            "decision_logs": self._build_decision_logs(event_logs),
            "event_logs": event_logs,
        }

    def _to_int(self, value, default: int, minimum: int = 1) -> int:
        try:
            number = int(value)
        except (TypeError, ValueError):
            number = default
        return max(minimum, number)

    def _load_exec_config(self) -> dict:
        raw = {}
        if isinstance(getattr(self.config, "config", None), dict):
            raw = self.config.config.get("exec", {}) or {}
        return {
            "retry_limit": self._to_int(raw.get("retry_limit", 3), default=3, minimum=1),
            "review_after_retry_limit": self._to_int(raw.get("review_after_retry_limit", 3), default=3, minimum=1),
            "max_steps": self._to_int(raw.get("max_steps", 20), default=20, minimum=1),
            "max_expand_depth": self._to_int(raw.get("max_expand_depth", 3), default=3, minimum=1),
            "independent_llm_step_context_enabled": bool(raw.get("independent_llm_step_context_enabled", True)),
            "planner_runtime_context_enabled": bool(raw.get("planner_runtime_context_enabled", True)),
            "planner_include_system_info": bool(raw.get("planner_include_system_info", True)),
            "planner_include_project_info": bool(raw.get("planner_include_project_info", True)),
            "planner_include_env_vars": bool(raw.get("planner_include_env_vars", False)),
            "planner_env_var_keys": [
                self._to_text(item).strip()
                for item in (raw.get("planner_env_var_keys", []) or [])
                if self._to_text(item).strip()
            ],
            "planner_project_entry_limit": self._to_int(raw.get("planner_project_entry_limit", 40), default=40, minimum=5),
        }

    def _load_sandbox_config(self) -> dict:
        raw = {}
        if isinstance(getattr(self.config, "config", None), dict):
            raw = self.config.config.get("sandbox")
            if raw is None:
                raw = self.config.config.get("sendbox")
            raw = raw or {}
        return {
            "enabled": bool(raw.get("enabled", False)),
            "provider": str(raw.get("provider", "cubesandbox")).strip() or "cubesandbox",
            "backend": str(raw.get("backend", "e2b")).strip() or "e2b",
            "api_key": self._to_text(raw.get("api_key", "")).strip(),
            "domain": self._to_text(raw.get("domain", "")).strip(),
            "template": self._to_text(raw.get("template", "")).strip(),
            "timeout_seconds": self._to_int(raw.get("timeout_seconds", 600), default=600, minimum=60),
            "command_timeout_seconds": self._to_int(raw.get("command_timeout_seconds", 120), default=120, minimum=10),
            "workspace_root": self._to_text(raw.get("workspace_root", "/workspace")).strip() or "/workspace",
            "sync_project_on_start": bool(raw.get("sync_project_on_start", True)),
            "sync_back_to_host": bool(raw.get("sync_back_to_host", False)),
            "kill_after_run": bool(raw.get("kill_after_run", True)),
            "allow_external_paths": bool(raw.get("allow_external_paths", False)),
            "max_sync_files": self._to_int(raw.get("max_sync_files", 200), default=200, minimum=1),
            "max_file_size_kb": self._to_int(raw.get("max_file_size_kb", 256), default=256, minimum=1),
            "sync_include": list(raw.get("sync_include", ["*.py", "*.json", "*.md", "*.txt"])),
            "sync_ignore": list(
                raw.get(
                    "sync_ignore",
                    ["env/**", ".git/**", "__pycache__/**", "EXEC/**", "MEMORY/**", "session_state/**", "*.pyc"],
                )
            ),
            "envs": dict(raw.get("envs", {}) or {}),
            "debug": bool(raw.get("debug", False)),
        }

    def _build_sandbox_adapter(self):
        if not self.sandbox_config.get("enabled", False):
            return CubeSandboxDisabled()
        return CubeSandboxAdapter(self.sandbox_config, BASE_DIR)

    def _get_main_llm_config(self) -> dict:
        return self.config.llm["main_llm"]

    def _get_llm_profile_config(self, profile: str = "", fallback: str = "main_llm") -> dict:
        llm_config = getattr(self.config, "llm", {}) or {}
        aliases = {
            "main": "main_llm",
            "main_llm": "main_llm",
            "planner": "exec_planner",
            "worker": "exec_worker",
            "verifier": "exec_verifier",
            "repairer": "exec_repairer",
        }
        requested = aliases.get(self._to_text(profile).strip().lower(), self._to_text(profile).strip())
        fallback_name = aliases.get(self._to_text(fallback).strip().lower(), self._to_text(fallback).strip() or "main_llm")
        main_cfg = dict(llm_config.get("main_llm", {}) or {})

        for candidate_name in (requested, fallback_name, "main_llm"):
            if not candidate_name:
                continue
            candidate = llm_config.get(candidate_name)
            if isinstance(candidate, dict) and candidate:
                merged = dict(main_cfg)
                merged.update(candidate)
                merged["model"] = self._to_text(merged.get("model", "")).strip()
                merged["key"] = self._to_text(merged.get("key", "")).strip()
                return merged
        return main_cfg

    def _load_skill_summaries(self) -> list[dict]:
        try:
            return self.skill_repository.list_skills()
        except Exception:
            return []

    def _select_skill_details(self, skills: list[dict]) -> list[dict]:
        if not skills:
            return []
        if len(skills) <= 5:
            return [self.skill_repository.get_skill(item["folder"]) for item in skills]
        selected = []
        for item in skills[:3]:
            try:
                selected.append(self.skill_repository.get_skill(item["folder"]))
            except Exception:
                continue
        return selected

    def _build_skill_prompt_context(self, task: str) -> str:
        skills = self._load_skill_summaries()
        if not skills:
            return "当前 SKILLS 目录下暂无可用 skill。"

        lines = [
            "执行前已扫描当前 SKILLS 目录，请先查看技能列表并优先复用已有 skill。",
            "当某个 skill 已经提供可复用脚本、命令、流程或约束时，优先沿用该 skill，而不是重新发明一套流程。",
            "",
            "【技能列表】",
        ]
        for item in skills:
            description = self._to_text(item.get("description", "")).strip() or "无描述"
            files = ", ".join(item.get("files", [])[:6]) or "无附属文件"
            lines.append(f"- {item['folder']}：{description}；文件：{files}")

        detail_skills = self._select_skill_details(skills)
        if detail_skills:
            lines.append("")
            lines.append("【可直接复用的 SKILL.md 详情】")
            for skill in detail_skills:
                lines.append(f"### {skill['folder']}")
                lines.append(f"- 名称：{skill['name']}")
                lines.append(f"- 描述：{skill['description'] or '无'}")
                lines.append(f"- 目录：{skill['dir_path']}")
                lines.append(f"- 文件：{', '.join(skill['files']) if skill['files'] else '无'}")
                lines.append(skill["content"])
                lines.append("")
        lines.append(f"【当前任务】\n{task}")
        return "\n".join(lines).strip()

    def _build_tool_prompt_context(self, task: str) -> str:
        tools = self._load_tool_summaries()
        if not tools:
            return "当前 TOOLS 目录下暂无可用 tool。"

        recommended_tools = self._select_recommended_tools(task)
        lines = [
            "执行前已扫描当前 TOOLS 目录，请把这些 tool 视为优先可复用的原子能力。",
            "当某个 tool 已能直接提供时间、查询、读取或其他局部能力时，优先在合适的 tool step 中调用，而不是重复发明同类逻辑。",
            "若后续 step 需要使用前一步输出，可在 command / script_content / verify 中引用模板变量，如 {{last.stdout}}、{{steps.search_web.json.final_report}}。",
            "注意：tool 只是 exec 路线中的可调用能力，不是独立路线。",
            "",
            "【工具列表】",
        ]
        for item in tools:
            description = self._to_text(item.get("description", "")).strip() or "无描述"
            aliases = ", ".join(item.get("aliases", [])[:6]) or "无别名"
            lines.append(f"- {item['name']}：{description}；别名：{aliases}")

        if recommended_tools:
            lines.append("")
            lines.append("【与当前任务最相关的推荐 tool】")
            for item in recommended_tools:
                name = self._to_text(item.get("name", "")).strip() or self._to_text(item.get("folder", "")).strip()
                description = self._to_text(item.get("description", "")).strip() or "无描述"
                example = ""
                examples = item.get("examples", {})
                if isinstance(examples, dict):
                    tool_command = examples.get("tool_command")
                    if isinstance(tool_command, dict):
                        example = json.dumps(tool_command, ensure_ascii=False)
                if not example:
                    example = json.dumps({"name": name, "args": {}}, ensure_ascii=False)
                lines.append(f"- {name}：{description}")
                lines.append(f"  示例 tool step command：{example}")
            if self._is_web_research_task(task):
                lines.append("  建议模式：先用相关 web search tool 获取资料，再用 file step 把 {{steps.<step_id>.json.final_report}} 包装成 Markdown 文件。")

        lines.append("")
        lines.append("【调用建议】")
        lines.append("- 若已知目标 tool 名，可直接生成 tool step。")
        lines.append("- 若只知道大致能力，可先用 list_tools / read_tool 再决定。")
        lines.append("- 不要仅仅因为后续要写文件，就把“搜索/时间/读取”等已有原子能力重新写成 urllib、requests、curl、Invoke-WebRequest 脚本。")
        lines.append(f"【当前任务】\n{task}")
        return "\n".join(lines).strip()

    def _tool_list_skills(self, args: dict) -> str:
        payload = {
            "skills": self._load_skill_summaries(),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _tool_read_skill(self, args: dict) -> str:
        skill_name = self._to_text(args.get("name", "")).strip()
        if not skill_name:
            raise ValueError("read_skill 需要提供 name。")
        skill = self.skill_repository.get_skill(skill_name)
        return json.dumps(skill, ensure_ascii=False, indent=2)

    def _load_tool_summaries(self) -> list[dict]:
        try:
            return self.tool_repository.list_tools()
        except Exception:
            return []

    def _get_tool_detail(self, name: str) -> dict | None:
        tool_name = self._to_text(name).strip()
        if not tool_name:
            return None
        try:
            return self.tool_repository.get_tool(tool_name)
        except Exception:
            return None

    def _contains_any_keyword(self, text: str, keywords) -> bool:
        haystack = self._to_text(text).strip().lower()
        if not haystack:
            return False
        return any(str(keyword or "").strip().lower() in haystack for keyword in (keywords or []))

    def _is_web_research_task(self, task: str) -> bool:
        return self._contains_any_keyword(
            task,
            (
                "互联网",
                "网上",
                "联网",
                "在线",
                "搜索",
                "检索",
                "网页",
                "网站",
                "web",
                "url",
                "资料",
                "信息",
                "新闻",
                "调研",
            ),
        )

    def _tool_relevance_score(self, task: str, tool: dict) -> int:
        task_text = self._to_text(task).strip().lower()
        if not task_text:
            return 0

        name = self._to_text(tool.get("name", "")).strip().lower()
        folder = self._to_text(tool.get("folder", "")).strip().lower()
        aliases = [self._to_text(alias).strip().lower() for alias in tool.get("aliases", [])]
        description = self._to_text(tool.get("description", "")).strip().lower()
        doc = self._to_text(tool.get("tool_doc_content", "")).strip().lower()
        combined = "\n".join(part for part in (name, folder, " ".join(aliases), description, doc) if part)

        score = 0
        for candidate in [name, folder, *aliases]:
            if candidate and candidate in task_text:
                score += 8

        task_tokens = {token for token in re.findall(r"[a-z][a-z0-9_]{2,}", task_text)}
        tool_tokens = {token for token in re.findall(r"[a-z][a-z0-9_]{2,}", combined)}
        score += min(3, len(task_tokens & tool_tokens))

        if self._is_web_research_task(task) and self._contains_any_keyword(
            combined,
            ("search", "web", "网页", "网站", "搜索", "检索", "url", "llm"),
        ):
            score += 6

        if self._contains_any_keyword(task, ("时间", "日期", "几点", "当前时间", "timezone", "date", "time")) and self._contains_any_keyword(
            combined,
            ("time", "日期", "时间", "timezone", "clock"),
        ):
            score += 6

        return score

    def _select_recommended_tools(self, task: str, limit: int = 3) -> list[dict]:
        scored_tools = []
        for summary in self._load_tool_summaries():
            detail = self._get_tool_detail(summary.get("name", "")) or dict(summary)
            score = self._tool_relevance_score(task, detail)
            if score <= 0:
                continue
            scored_tools.append((score, detail))

        scored_tools.sort(key=lambda item: (-item[0], self._to_text(item[1].get("name", "")).lower()))
        selected = []
        seen = set()
        for _, tool in scored_tools:
            name = self._to_text(tool.get("name", "")).strip().lower()
            if not name or name in seen:
                continue
            seen.add(name)
            selected.append(tool)
            if len(selected) >= limit:
                break
        return selected

    def _tool_list_tools(self, args: dict) -> str:
        payload = {
            "tools": self._load_tool_summaries(),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _tool_read_tool(self, args: dict) -> str:
        tool_name = self._to_text(args.get("name", "")).strip()
        if not tool_name:
            raise ValueError("read_tool 需要提供 name。")
        tool = self.tool_repository.get_tool(tool_name)
        return json.dumps(tool, ensure_ascii=False, indent=2)

    def _abbreviate_text(self, value, limit: int = 1200) -> str:
        text = self._to_text(value).strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _collect_template_step_ids(self, text: str) -> list[str]:
        raw = self._to_text(text)
        if not raw:
            return []
        found = re.findall(r"\{\{\s*steps\.([^.}\s]+)\.", raw)
        result = []
        seen = set()
        for item in found:
            step_id = self._to_text(item).strip()
            if not step_id or step_id in seen:
                continue
            seen.add(step_id)
            result.append(step_id)
        return result

    def _collect_step_dependency_ids(self, step: dict) -> list[str]:
        collected = []
        seen = set()
        for field in ("command", "script_content", "verify", "context"):
            for step_id in self._collect_template_step_ids(step.get(field, "")):
                if step_id in seen:
                    continue
                seen.add(step_id)
                collected.append(step_id)
        return collected

    def _build_attempt_context_item(self, attempt: dict) -> dict:
        stdout = self._abbreviate_text(attempt.get("stdout", ""), limit=600)
        stderr = self._abbreviate_text(attempt.get("stderr", ""), limit=300)
        return {
            "id": self._to_text(attempt.get("id", "")).strip(),
            "title": self._to_text(attempt.get("title", "")).strip(),
            "kind": self._to_text(attempt.get("kind", "")).strip(),
            "success": bool(attempt.get("success", False)),
            "returncode": attempt.get("returncode", -1),
            "stdout": stdout,
            "stderr": stderr,
            "step_verification": attempt.get("step_verification", {}),
        }

    def _build_run_context_payload(self, task: str, plan_data: dict, step_attempts: list[dict], current_index: int = 0) -> dict:
        recent_attempts = [self._build_attempt_context_item(item) for item in step_attempts[-4:]]
        return {
            "task": task,
            "workflow": self._to_text(plan_data.get("workflow", "")).strip(),
            "plan": list(plan_data.get("plan", []))[:8],
            "current_index": current_index + 1,
            "completed_attempts": len(step_attempts),
            "recent_attempts": recent_attempts,
        }

    def _build_step_context_payload(
        self,
        task: str,
        plan_data: dict,
        step: dict,
        step_attempts: list[dict],
        current_index: int = 0,
    ) -> dict:
        latest_by_id = {}
        for attempt in step_attempts:
            step_id = self._to_text(attempt.get("id", "")).strip()
            if step_id:
                latest_by_id[step_id] = attempt

        dependency_items = []
        for step_id in self._collect_step_dependency_ids(step):
            attempt = latest_by_id.get(step_id)
            if attempt is None:
                continue
            dependency_items.append(self._build_attempt_context_item(attempt))

        return {
            "task": task,
            "workflow": self._to_text(plan_data.get("workflow", "")).strip(),
            "step": {
                "id": self._to_text(step.get("id", "")).strip(),
                "title": self._to_text(step.get("title", "")).strip(),
                "kind": self._to_text(step.get("kind", "")).strip(),
                "context": self._to_text(step.get("context", "")).strip(),
                "context_mode": self._to_text(step.get("context_mode", "")).strip(),
                "llm_profile": self._to_text(step.get("llm_profile", "")).strip(),
                "verify": self._to_text(step.get("verify", "")).strip(),
            },
            "current_index": current_index + 1,
            "dependencies": dependency_items,
            "recent_attempts": [self._build_attempt_context_item(item) for item in step_attempts[-2:]],
        }

    def _build_llm_step_expectation(self, step: dict, args: dict) -> dict:
        output_format = self._to_text(args.get("output_format", "text")).strip().lower() or "text"
        response_schema = args.get("response_schema", {}) if isinstance(args.get("response_schema", {}), dict) else {}
        return {
            "subtask": self._to_text(args.get("task", "")).strip(),
            "context": self._to_text(step.get("context", "")).strip() or self._to_text(args.get("context", "")).strip(),
            "verify": self._to_text(step.get("verify", "")).strip(),
            "output_format": output_format,
            "response_schema": response_schema,
        }

    def _should_attach_independent_llm_context(self, tool_name: str) -> bool:
        if tool_name != "llm_dispatch":
            return False
        return bool(self.exec_config.get("independent_llm_step_context_enabled", True))

    def _build_llm_dispatch_prompt(self, args: dict) -> str:
        subtask = self._to_text(args.get("task", "")).strip()
        if not subtask:
            raise ValueError("llm_dispatch 需要提供 task。")

        output_format = self._to_text(args.get("output_format", "text")).strip().lower() or "text"
        response_schema = args.get("response_schema", {}) if isinstance(args.get("response_schema", {}), dict) else {}
        payload = {
            "task": subtask,
            "input": self._to_text(args.get("input", "")),
            "context": self._to_text(args.get("context", "")),
            "expectation": args.get("_expectation", {}),
            "runtime_context": args.get("_runtime_context", {}),
        }
        if response_schema:
            payload["response_schema"] = response_schema

        instructions = [
            "你是 exec 流程中的 LLM 子任务工作器。",
            "你只处理当前被调度的这个局部任务，不要接管整个 exec 总任务，也不要扩展成额外规划。",
            "优先基于给定 input、context、expectation 与 runtime_context 输出结果，避免引入无关背景。",
            "重点保留前提条件、关键输入、输出目标与验证要求，不要遗漏硬性约束。",
        ]
        if output_format == "json":
            instructions.append("必须只输出 JSON，字段结构需满足 response_schema；若未给 response_schema，也要输出合理 JSON 对象。")
        else:
            instructions.append("直接输出最终结果正文，不要输出额外解释、前缀或代码围栏，除非 task 明确要求。")

        return "\n".join(
            [
                *instructions,
                f"输入：{json.dumps(payload, ensure_ascii=False)}",
            ]
        )

    def _tool_llm_dispatch(self, args: dict) -> str:
        data = dict(args or {})
        prompt = self._build_llm_dispatch_prompt(data)
        llm_profile = self._to_text(data.get("llm_profile", "")).strip() or "exec_worker"
        llm_cfg = self._get_llm_profile_config(llm_profile, fallback="main_llm")
        output_format = self._to_text(data.get("output_format", "text")).strip().lower() or "text"
        system_prompt = self._to_text(data.get("system_prompt", "")).strip()
        if system_prompt:
            prompt = f"补充系统约束：\n{system_prompt}\n\n{prompt}"

        if output_format == "json":
            result = call_llm_json(prompt, llm_cfg["model"], llm_cfg["key"])
            return json.dumps(result, ensure_ascii=False, indent=2)
        return self._to_text(call_llm(prompt, llm_cfg["model"], llm_cfg["key"], stream=False)).strip()

    def _build_executor_schema(self) -> dict:
        registered_tools = {
            "shell": "执行 args.command 中的命令。优先推荐直接使用 kind=shell；当模型已经处于 tool step 时也允许 name=shell。",
            "list_dir": "列出目录内容，args 支持 path、depth、offset、limit。",
            "read_text": "读取文本文件，args 支持 path。",
            "path_exists": "判断路径是否存在，args 支持 path。",
            "glob": "按 glob 模式匹配路径，args 支持 path、pattern。",
            "list_skills": "列出当前项目 SKILLS 目录下的全部 skill，便于优先复用已有能力。",
            "read_skill": "读取指定 skill 的完整 SKILL.md 与附属文件信息，args 支持 name。",
            "list_tools": "列出当前项目 TOOLS 目录下的全部标准工具，便于优先复用已有工具。",
            "read_tool": "读取指定 tool 的 tool.json 与 TOOL.md 信息，args 支持 name。",
            "llm_dispatch": "调度独立 LLM 子任务，适合总结、提炼、分类、改写、翻译、结构化抽取等纯认知型步骤；args 支持 task、input、context、output_format、response_schema、include_run_context、include_history、llm_profile。",
        }
        tool_aliases = {
            "shell": ["run_command", "execute_command", "command", "powershell", "local_shell"],
            "list_dir": ["list_files", "list_directory", "dir", "ls"],
            "read_text": ["read_file", "cat_file", "open_file"],
            "path_exists": ["exists", "file_exists"],
            "glob": ["glob_files", "find_files"],
            "list_skills": ["skills", "skill_list"],
            "read_skill": ["skill", "skill_read", "open_skill"],
            "list_tools": ["tools", "tool_list"],
            "read_tool": ["tool", "tool_read", "open_tool"],
            "llm_dispatch": ["ask_llm", "dispatch_llm", "llm_task", "summarize_with_llm", "extract_with_llm"],
        }
        tool_command_examples = {
            "shell": {"name": "shell", "args": {"command": "Get-ChildItem"}},
            "list_dir": {"name": "list_dir", "args": {"path": ".", "depth": 2, "limit": 100}},
            "read_text": {"name": "read_text", "args": {"path": "README.md"}},
            "path_exists": {"name": "path_exists", "args": {"path": "core/exec_service.py"}},
            "glob": {"name": "glob", "args": {"path": ".", "pattern": "*.py"}},
            "list_skills": {"name": "list_skills", "args": {}},
            "read_skill": {"name": "read_skill", "args": {"name": "time"}},
            "list_tools": {"name": "list_tools", "args": {}},
            "read_tool": {"name": "read_tool", "args": {"name": "get_current_time"}},
            "llm_dispatch": {
                "name": "llm_dispatch",
                "args": {
                    "task": "把输入内容提炼成 3 条要点",
                    "input": "{{steps.read_source.stdout}}",
                    "context": "只保留核心事实，不要扩展新信息。",
                    "output_format": "text",
                    "include_run_context": False,
                },
            },
        }
        for item in self._load_tool_summaries():
            tool_name = self._to_text(item.get("name", "")).strip().lower()
            if not tool_name:
                continue
            registered_tools[tool_name] = self._to_text(item.get("description", "")).strip() or "项目自定义工具。"
            aliases = [alias for alias in item.get("aliases", []) if alias]
            if aliases:
                tool_aliases[tool_name] = aliases
            tool_command_examples[tool_name] = {
                "name": tool_name,
                "args": {"timezone": "Asia/Shanghai"} if tool_name == "get_current_time" else {},
            }
        return {
            "entrypoint": "Executor.run(step)",
            "execution_backend": "当 sandbox.enabled=true 时，shell、list_dir、read_text、path_exists、glob 会优先在 CubeSandbox 中执行；项目自定义 tool 仍在宿主机执行。",
            "step_schema": {
                "id": "string",
                "title": "string",
                "kind": "shell | python | file | tool",
                "command": "string",
                "script_content": "string",
                "verify": "string",
                "context": "string，可选；描述当前 step 的独立聚焦上下文",
                "context_mode": "minimal | step | history | run，可选；决定 llm_dispatch 默认注入多少运行上下文",
                "llm_profile": "string，可选；指定当前 step 偏好的 LLM 配置名，如 exec_worker",
            },
            "kinds": {
                "shell": "使用 command 执行 Windows PowerShell 命令",
                "python": "使用 script_content 执行 Python 脚本",
                "file": "使用 command 中的 JSON 指令执行本地文件读写改删",
                "tool": "使用 command 中的 JSON 指令调用已注册工具；先考虑 list_tools/read_tool 发现项目自定义工具。",
            },
            "step_context_notes": {
                "purpose": "当某个 step 只是局部总结、提炼、分类、翻译或结构化抽取时，应为该 step 单独提供 context，避免把整个 exec 大任务上下文塞给局部子任务。",
                "recommended_modes": {
                    "minimal": "仅保留当前 step 的 context、task 与 input",
                    "step": "保留当前 step 上下文与被引用依赖 step 的结果",
                    "history": "在 step 模式基础上，额外附带少量最近执行历史",
                    "run": "附带任务 workflow 与近期执行概览，适合需要理解整体目标但仍需聚焦的子任务",
                },
            },
            "step_references": {
                "supported_fields": ["stdout", "stderr", "returncode", "success", "script_path"],
                "examples": {
                    "last_stdout": "{{last.stdout}}",
                    "named_step_stdout": "{{steps.search_web.stdout}}",
                    "named_step_json_field": "{{steps.search_web.json.final_report}}",
                },
                "notes": "后续 step 的 command、script_content、verify 可以引用前序 step 输出；如需复用 JSON 字段，优先使用 {{steps.<id>.json.<field>}}。",
            },
            "registered_tools": registered_tools,
            "tool_aliases": tool_aliases,
            "file_command_examples": {
                "read": {"action": "read", "path": "relative/or/absolute/path.txt"},
                "write": {"action": "write", "path": "relative/or/absolute/path.txt"},
                "replace": {"action": "replace", "path": "relative/or/absolute/path.txt", "old": "旧内容", "new": "新内容"},
                "delete": {"action": "delete", "path": "relative/or/absolute/path.txt"},
            },
            "tool_command_examples": tool_command_examples,
        }

    def _build_planner_runtime_context(self) -> str:
        if not self.exec_config.get("planner_runtime_context_enabled", True):
            return "当前未向规划器注入额外系统/项目上下文，请仅依据任务、技能与工具信息规划。"

        lines = ["以下信息由宿主运行时自动提供，规划时必须优先遵守，不要臆测其他环境："]

        if self.exec_config.get("planner_include_system_info", True):
            shell_name = "Windows PowerShell" if os.name == "nt" else (os.environ.get("SHELL", "") or "shell")
            lines.extend(
                [
                    "",
                    "【系统信息】",
                    f"- host_os: {platform.system()}",
                    f"- os_name: {os.name}",
                    f"- platform: {platform.platform()}",
                    f"- python_executable: {sys.executable}",
                    f"- default_shell: {shell_name}",
                    f"- path_separator: {os.sep}",
                    f"- project_root: {BASE_DIR}",
                    f"- sandbox_enabled: {self.sandbox_config.get('enabled', False)}",
                ]
            )
            if os.name == "nt":
                lines.append("- shell step 必须兼容 Windows PowerShell；不要使用 bash 专属语法如 `cd /path &&`, `test -s`, `nohup`, `python3` 作为默认前提。")
            else:
                lines.append("- shell step 必须兼容当前宿主 shell，不要强行使用 Windows PowerShell 专属语法。")
            if self.sandbox_config.get("enabled", False):
                lines.append(
                    f"- sandbox_workspace_root: {self._to_text(self.sandbox_config.get('workspace_root', '')).strip() or '/workspace'}"
                )

        if self.exec_config.get("planner_include_project_info", True):
            entry_limit = self.exec_config.get("planner_project_entry_limit", 40)
            root_entries = []
            try:
                for item in sorted(BASE_DIR.iterdir(), key=lambda path: path.name.lower()):
                    display = item.name + ("/" if item.is_dir() else "")
                    root_entries.append(display)
                    if len(root_entries) >= entry_limit:
                        break
            except Exception:
                root_entries = []

            important_files = []
            for name in (
                "README.md",
                "config.json",
                "requirements.txt",
                "pyproject.toml",
                "package.json",
                "GUI.py",
                "app",
                "core",
                "TOOLS",
                "SKILLS",
            ):
                path = BASE_DIR / name
                if path.exists():
                    important_files.append(name + ("/" if path.is_dir() else ""))

            lines.extend(
                [
                    "",
                    "【项目信息】",
                    f"- project_root: {BASE_DIR}",
                    f"- visible_root_entries: {json.dumps(root_entries, ensure_ascii=False)}",
                    f"- important_entries: {json.dumps(important_files, ensure_ascii=False)}",
                ]
            )

        if self.exec_config.get("planner_include_env_vars", False):
            env_payload = {}
            for key in self.exec_config.get("planner_env_var_keys", []):
                value = os.environ.get(key)
                if value is not None and str(value).strip():
                    env_payload[key] = value
            if env_payload:
                lines.extend(
                    [
                        "",
                        "【选定环境变量】",
                        json.dumps(env_payload, ensure_ascii=False),
                    ]
                )

        lines.extend(
            [
                "",
                "【规划约束】",
                "- 若系统信息与用户口头路径习惯不一致，应以当前宿主环境和 project_root 为准。",
                "- 若任务要求启动服务或打开页面，必须基于当前宿主环境可执行的命令规划。",
                "- 若当前是 Windows，优先使用 PowerShell 兼容命令、Windows 路径或 file/tool step，而不是默认假设 `/workspace`、`python3`、`test -s`、`;` 链式 bash 写法一定可用。",
            ]
        )
        return "\n".join(lines).strip()

    def _build_skill_invoke_prompt(self, user_input: str, skill: dict) -> str:
        payload = {
            "user_input": user_input,
            "skill": {
                "folder": skill.get("folder", ""),
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
                "dir_path": skill.get("dir_path", ""),
                "skill_path": skill.get("skill_path", ""),
                "files": skill.get("files", []),
                "content": skill.get("content", ""),
            },
        }
        return (
            "你是 skill 调用器。请根据用户请求与指定 skill 内容，生成一次可直接执行的本地调用方案。\n"
            "要求：\n"
            "1. 只能围绕当前给定的 skill 生成调用，不要切换到其他 skill。\n"
            "2. 如果用户信息不足，必须返回 should_ask_user=true，并给出 question。\n"
            "3. 如果信息足够，返回 should_ask_user=false，并给出可以在项目根目录直接执行的 command。\n"
            "4. command 必须是单条 PowerShell 可执行命令，优先使用 `python SKILLS/<folder>/...` 形式。\n"
            "5. 不要凭空发明 skill 不支持的参数。\n"
            '6. 只输出 JSON，结构必须等价于 {"skill_name":"","should_ask_user":false,"question":"","command":"","verify":""}。\n'
            f"输入：{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_skill_reply_prompt(self, user_input: str, skill: dict, command: str, run_result: dict) -> str:
        payload = {
            "user_input": user_input,
            "skill": {
                "folder": skill.get("folder", ""),
                "name": skill.get("name", ""),
                "description": skill.get("description", ""),
            },
            "command": command,
            "execution_result": {
                "returncode": run_result.get("returncode", -1),
                "stdout": run_result.get("stdout", ""),
                "stderr": run_result.get("stderr", ""),
            },
        }
        return (
            "你是 skill 结果整理器。请根据用户请求、skill 信息和执行结果，生成最终回复。\n"
            "要求：\n"
            "1. 优先直接回答用户真正关心的结果，不要先讲内部流程。\n"
            "2. 如果 stdout 是 JSON 或结构化结果，需要提炼成自然语言，同时保留关键值。\n"
            "3. 如果执行失败，需要明确说明失败原因，并尽量给出下一步建议。\n"
            '4. 只输出 JSON，结构必须等价于 {"reply":"","completed":true}。\n'
            f"输入：{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_plan_prompt(self, task: str) -> str:
        executor_schema = self._build_executor_schema()
        skill_context = self._build_skill_prompt_context(task)
        tool_context = self._build_tool_prompt_context(task)
        runtime_context = self._build_planner_runtime_context()
        return (
            "你是本地执行代理的规划器。请基于任务生成可执行 steps，Agent 将自主执行并持续验证。\n"
            "要求：\n"
            "1. 需要给出 plan（任务拆解）。\n"
            "2. 需要给出 workflow（整体执行思路）。\n"
            "3. steps 中的 kind 仅允许 shell、python、file、tool。\n"
            "4. shell step 使用 command；python step 使用 script_content。\n"
            "5. file step 的 command 必须是 JSON 字符串，至少包含 action 和 path；写入内容放在 script_content。\n"
            "6. tool step 的 command 必须是 JSON 字符串，结构为 {name, args}；优先使用规范名 shell、list_dir、read_text、path_exists、glob、list_skills、read_skill、list_tools、read_tool、llm_dispatch 或已注册项目 tool 名。\n"
            "7. 每个 step 都必须包含 verify，用于执行后验证。\n"
            "8. 如果 sandbox.enabled=true，shell/python/file/tool 会优先在 CubeSandbox 安全沙箱中执行，路径基于当前项目快照工作目录。\n"
            "9. 执行内容必须兼容当前执行后端；优先使用 Python / 通用 shell，不要写死仅适用于单一环境的绝对路径。\n"
            "10. steps 数量控制在 1 到 8 步，且每步尽量原子化。\n"
            "11. 如果任务需要修改已有文件，优先先读再改，避免盲写。\n"
            "12. 你必须先参考技能列表；若已有 skill 与任务相关，优先复用 skill 中的脚本、命令、流程与约束。\n"
            "13. 你必须同时参考工具列表；若已有 tool 可直接提供某个原子能力，优先在 exec 中通过 tool step 复用。\n"
            "14. 若后续 step 需要前一步的结果，使用模板变量 {{last.stdout}}、{{steps.<id>.stdout}}、{{steps.<id>.json.<field>}} 传递数据；不要为了“跨步骤传值”而把整个任务硬塞进一个大 Python 脚本。\n"
            "15. 如果任务涉及联网搜索、网页资料整理、URL 抓取，而工具列表里已有相关 web/search tool，计划中必须优先出现对应 tool step；禁止用 urllib、requests、httpx、curl、Invoke-WebRequest 临时重写同类能力，除非工具列表明确没有对应能力。\n"
            "16. 对于总结、归纳、提炼、分类、改写、翻译、结构化抽取等纯认知型局部任务，优先规划为 llm_dispatch tool step，而不是让整个 exec 主流程自己顺手完成这些认知工作。\n"
            "17. step 可额外包含 context、context_mode、llm_profile。context 用于声明该分点的独立上下文；context_mode 可选 minimal、step、history、run；若使用 llm_dispatch，优先填写 context。\n"
            "18. 当前 exec 支持对 llm_dispatch 分点统一注入独立上下文；规划时应主动把关键前提、重要约束、预期输出、验证标准拆进该 step 的 context、task、verify、output_format 或 response_schema，而不是隐含依赖主任务大上下文。\n"
            "19. llm_dispatch 的 args 推荐包含 task、input，可选 context、output_format、response_schema、include_run_context、include_history、llm_profile。\n"
            '20. 只输出 JSON，顶层结构必须等价于 {"task":"","tool_schema":{},"plan":[],"workflow":"","steps":[]}。\n'
            f"Executor 规范：{json.dumps(executor_schema, ensure_ascii=False)}\n"
            f"系统与项目上下文：\n{runtime_context}\n"
            f"Skill 上下文：\n{skill_context}\n"
            f"Tool 上下文：\n{tool_context}\n"
            f"用户任务：{task}"
        )

    def _build_step_verify_prompt(self, task: str, step: dict, step_result: dict) -> str:
        payload = {
            "task": task,
            "step": {
                "id": step.get("id", ""),
                "title": step.get("title", ""),
                "kind": step.get("kind", ""),
                "command": step.get("command", ""),
                "script_content": step.get("script_content", ""),
                "verify": step.get("verify", ""),
                "context": step.get("context", ""),
                "context_mode": step.get("context_mode", ""),
                "llm_profile": step.get("llm_profile", ""),
            },
            "execution_result": {
                "returncode": step_result.get("returncode", -1),
                "stdout": step_result.get("stdout", ""),
                "stderr": step_result.get("stderr", ""),
                "returncode": step_result.get("returncode", -1),
                "stdout": step_result.get("stdout", ""),
                "stderr": step_result.get("stderr", ""),
            },
        }
        return (
            "你是执行步骤验证器。请根据任务目标、step 定义、执行结果和 verify 条件判断该 step 是否成功。\n"
            "禁止只看 returncode，必须综合 stdout/stderr 与任务语义。\n"
            "如果任务要求联网搜索、网页抓取或互联网资料整理，必须确认真实搜索/抓取成功；若 stdout/stderr 明示 request failed、timeout、search failed、fallback、兜底 等信号，不能只因为文件已生成或非空就判定通过。\n"
            '只输出 JSON，结构必须等价于 {"passed": true, "reason": ""}。\n'
            f"验证输入：{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_retry_prompt(self, task: str, step: dict, step_result: dict, reason: str) -> str:
        executor_schema = self._build_executor_schema()
        skill_context = self._build_skill_prompt_context(task)
        tool_context = self._build_tool_prompt_context(task)
        payload = {
            "task": task,
            "step": {
                "id": step.get("id", ""),
                "title": step.get("title", ""),
                "kind": step.get("kind", ""),
                "command": step.get("command", ""),
                "script_content": step.get("script_content", ""),
                "verify": step.get("verify", ""),
            },
            "execution_result": {
                "returncode": step_result.get("returncode", -1),
                "stdout": step_result.get("stdout", ""),
                "stderr": step_result.get("stderr", ""),
            },
            "verification_reason": reason,
        }
        return (
            "你是执行步骤修复器。当前 step 执行或验证失败，请生成修复后的 step。\n"
            "约束：\n"
            "1. 只允许修改 command、script_content、context 或 llm_profile。\n"
            "2. id、title、kind、verify、context_mode 必须保持不变。\n"
            '3. 输出必须是 JSON，且结构必须等价于 {"step": {"id":"","title":"","kind":"","command":"","script_content":"","verify":"","context":"","context_mode":"","llm_profile":""}}。\n'
            "4. tool step 只能使用已注册工具；优先使用规范名 shell、list_dir、read_text、path_exists、glob、list_skills、read_skill、list_tools、read_tool、llm_dispatch 或已注册项目 tool 名。\n"
            "5. 若局部认知任务的失败根因是上下文过大或目标不聚焦，优先收紧 context、切换 llm_profile 或改为 llm_dispatch，而不是继续扩大临时脚本范围。\n"
            "6. 若当前任务涉及联网搜索且已有相关 tool，可通过模板变量复用前序输出，不要继续扩大临时脚本范围。\n"
            "7. 不要输出任何解释文字。\n"
            f"Executor 规范：{json.dumps(executor_schema, ensure_ascii=False)}\n"
            f"Skill 上下文：\n{skill_context}\n"
            f"Tool 上下文：\n{tool_context}\n"
            f"输入：{json.dumps(payload, ensure_ascii=False)}"
        )

    def _build_final_verify_prompt(self, task: str, plan_data: dict, result_data: dict) -> str:
        return (
            "请根据以下执行计划与执行结果，判断整个 task 是否完成。\n"
            "禁止仅依赖 returncode，需要综合每个 step 的验证结论与最终产物。\n"
            "如果任务要求联网搜索或外部资料整理，但执行日志显示搜索超时、抓取失败、request failed 或仅使用兜底常识填充内容，则不能只因为文件存在且非空就判定整个任务完成。\n"
            '只输出 JSON，结构必须等价于 {"passed": true, "reason": ""}。\n'
            f"原始任务：{task}\n"
            f"执行计划：{json.dumps(plan_data, ensure_ascii=False)}\n"
            f"执行结果：{json.dumps(result_data, ensure_ascii=False)}"
        )

    def _to_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    def _coerce_bool(self, value) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {
            "1",
            "true",
            "yes",
            "y",
            "ok",
            "completed",
            "done",
            "pass",
            "passed",
            "完成",
            "已完成",
            "通过",
        }

    def _normalize_plan_list(self, value):
        if isinstance(value, list):
            return [self._to_text(item).strip() for item in value if self._to_text(item).strip()]
        if isinstance(value, dict):
            items = []
            for key, item in value.items():
                text = self._to_text(item).strip()
                items.append(f"{key}: {text}" if text else str(key))
            return items
        text = self._to_text(value).strip()
        if not text:
            return []
        return [line.strip("-* \t") for line in text.splitlines() if line.strip()]

    def _normalize_tool_schema(self, value):
        if isinstance(value, dict):
            return value
        if isinstance(value, list):
            return {"items": value}
        text = self._to_text(value).strip()
        return {"raw": text} if text else {}

    def _unwrap_mapping_by_keys(self, value, keys: set[str]):
        if isinstance(value, dict):
            if keys.intersection(value.keys()):
                return value
            for nested in value.values():
                found = self._unwrap_mapping_by_keys(nested, keys)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._unwrap_mapping_by_keys(item, keys)
                if found is not None:
                    return found
        elif isinstance(value, str):
            parsed = self._parse_embedded_structured_value(value)
            if isinstance(parsed, (dict, list)):
                found = self._unwrap_mapping_by_keys(parsed, keys)
                if found is not None:
                    return found
        return None

    def _unwrap_exec_mapping(self, value):
        return self._unwrap_mapping_by_keys(value, {"task", "tool_schema", "plan", "workflow", "steps"})

    def _unwrap_step_mapping(self, value):
        return self._unwrap_mapping_by_keys(value, {"command", "script_content", "kind", "context", "llm_profile"})

    def _unwrap_verification_mapping(self, value):
        return self._unwrap_mapping_by_keys(value, {"passed", "reason"})

    def _unwrap_skill_invoke_mapping(self, value):
        return self._unwrap_mapping_by_keys(value, {"command", "question", "should_ask_user"})

    def _unwrap_skill_reply_mapping(self, value):
        return self._unwrap_mapping_by_keys(value, {"reply", "completed"})

    def _parse_embedded_structured_value(self, value):
        text = self._to_text(value).strip()
        if not text:
            return None

        preferred_types = ["json", "yaml", "toml", "xml"]
        for type_name in preferred_types:
            parsed = handle(type_name, text, "parse")
            data = parsed.get("data")
            if parsed["success"] and isinstance(data, (dict, list)):
                return data

        block_result = extract_preferred_code_block(text, preferred_types=preferred_types)
        block = block_result.get("data")
        if block is None:
            return None

        for type_name in [block.get("detected_type"), block.get("language"), *preferred_types]:
            normalized = self._to_text(type_name).strip().lower()
            if not normalized:
                continue
            parsed = handle(normalized, block.get("content", ""), "parse")
            data = parsed.get("data")
            if parsed["success"] and isinstance(data, (dict, list)):
                return data
        return None

    def _normalize_embedded_text(self, content: str, preferred_types=None) -> str:
        text = self._to_text(content).strip()
        if not text:
            return ""

        block_result = extract_preferred_code_block(text, preferred_types=preferred_types)
        if block_result.get("success") and block_result.get("data") is not None:
            block = block_result["data"]
            block_content = self._to_text(block.get("content", "")).strip()
            block_type = block.get("detected_type") or block.get("language")
            if block_type:
                formatted = handle(block_type, block_content, "format")
                if formatted["success"] and isinstance(formatted.get("data"), str):
                    return formatted["data"].rstrip()
            return block_content

        preferred = preferred_types or []
        for type_name in preferred:
            formatted = handle(type_name, text, "format")
            if formatted["success"] and isinstance(formatted.get("data"), str):
                return formatted["data"].rstrip()
        return text

    def _normalize_step_kind(self, kind: str) -> str:
        text = str(kind or "").strip().lower()
        aliases = {
            "shell": "shell",
            "command": "shell",
            "powershell": "shell",
            "powershell_command": "shell",
            "ps1": "shell",
            "ps1_script": "shell",
            "bat": "shell",
            "bat_script": "shell",
            "python": "python",
            "python_script": "python",
            "py": "python",
            "file": "file",
            "fs": "file",
            "tool": "tool",
        }
        return aliases.get(text, text)

    def _normalize_context_mode(self, mode: str) -> str:
        text = self._to_text(mode).strip().lower()
        aliases = {
            "": "step",
            "step": "step",
            "isolated": "minimal",
            "minimal": "minimal",
            "focused": "step",
            "history": "history",
            "recent": "history",
            "run": "run",
            "global": "run",
        }
        return aliases.get(text, "step")

    def _attach_runtime_fields(self, step: dict, depth: int = 0, parent_id: str = "") -> dict:
        runtime_step = dict(step)
        runtime_step["_depth"] = int(step.get("_depth", depth))
        runtime_step["_retry_count"] = int(step.get("_retry_count", 0))
        runtime_step["_attempt_count"] = int(step.get("_attempt_count", 0))
        runtime_step["_parent_id"] = str(step.get("_parent_id", parent_id))
        runtime_step["_origin_id"] = str(step.get("_origin_id", runtime_step.get("id", ""))) or str(runtime_step.get("id", ""))
        runtime_step["_final_status"] = str(step.get("_final_status", "pending"))
        runtime_step["_last_failure_reason"] = str(step.get("_last_failure_reason", ""))
        return runtime_step

    def _normalize_steps(self, value, depth: int = 0, parent_id: str = ""):
        raw_steps = value
        if isinstance(value, dict):
            if "step" in value:
                raw_steps = value["step"]
            elif "steps" in value:
                raw_steps = value["steps"]
            else:
                raw_steps = list(value.values())
        elif not isinstance(value, list):
            raw_steps = [value]

        if not isinstance(raw_steps, list):
            raw_steps = [raw_steps]

        normalized = []
        for index, item in enumerate(raw_steps, start=1):
            if isinstance(item, str):
                step = {
                    "id": f"step_{index}",
                    "title": f"步骤 {index}",
                    "kind": "shell",
                    "command": self._normalize_embedded_text(item, preferred_types=["txt", "bash"]),
                    "script_content": "",
                    "verify": "",
                }
                normalized.append(self._attach_runtime_fields(step, depth=depth, parent_id=parent_id))
                continue

            if not isinstance(item, dict):
                continue

            step_id = self._to_text(item.get("id") or item.get("step_id") or item.get("name") or f"step_{index}").strip() or f"step_{index}"
            title = self._to_text(item.get("title") or item.get("name") or step_id).strip() or step_id
            kind = self._normalize_step_kind(item.get("kind") or item.get("type") or item.get("step_kind"))
            command = self._normalize_embedded_text(item.get("command", ""), preferred_types=["json", "txt", "bash"])
            script_content = self._normalize_embedded_text(
                item.get("script_content") or item.get("script") or item.get("content") or "",
                preferred_types=["python", "markdown", "txt"],
            )
            verify = self._to_text(item.get("verify") or item.get("check") or "").strip()
            context = self._normalize_embedded_text(
                item.get("context") or item.get("step_context") or item.get("focus") or "",
                preferred_types=["markdown", "json", "txt"],
            )
            context_mode = self._normalize_context_mode(
                item.get("context_mode") or item.get("context_scope") or item.get("scope") or ""
            )
            llm_profile = self._to_text(item.get("llm_profile") or item.get("model_profile") or "").strip()
            if kind == "tool":
                command = self.executor.normalize_tool_command(command) if hasattr(self, "executor") else command

            step = {
                "id": step_id,
                "title": title,
                "kind": kind,
                "command": command,
                "script_content": script_content,
                "verify": verify,
                "context": context,
                "context_mode": context_mode,
                "llm_profile": llm_profile,
            }
            normalized.append(self._attach_runtime_fields(step, depth=depth, parent_id=parent_id))
        return normalized

    def _export_step(self, step: dict) -> dict:
        return {
            "id": step.get("id", ""),
            "title": step.get("title", ""),
            "kind": step.get("kind", ""),
            "command": step.get("command", ""),
            "script_content": step.get("script_content", ""),
            "verify": step.get("verify", ""),
            "context": step.get("context", ""),
            "context_mode": step.get("context_mode", "step"),
            "llm_profile": step.get("llm_profile", ""),
            "depth": step.get("_depth", 0),
            "retry_count": step.get("_retry_count", 0),
            "final_status": step.get("_final_status", "pending"),
            "last_failure_reason": step.get("_last_failure_reason", ""),
            "origin_id": step.get("_origin_id", ""),
            "parent_id": step.get("_parent_id", ""),
        }

    def _export_plan_data(self, plan_data: dict, steps: list[dict]) -> dict:
        return {
            "task": plan_data.get("task", ""),
            "tool_schema": plan_data.get("tool_schema", {}),
            "plan": plan_data.get("plan", []),
            "workflow": plan_data.get("workflow", ""),
            "steps": [self._export_step(step) for step in steps],
        }

    def _normalize_plan_data(self, task: str, value):
        candidate = self._unwrap_exec_mapping(value)
        if candidate is None:
            raise ValueError("未能在模型输出中找到执行计划结构。")

        plan_data = {
            "task": self._to_text(candidate.get("task") or task).strip() or task,
            "tool_schema": self._normalize_tool_schema(candidate.get("tool_schema", self._build_executor_schema())),
            "plan": self._normalize_plan_list(candidate.get("plan", [])),
            "workflow": self._to_text(candidate.get("workflow", "")).strip(),
            "steps": self._normalize_steps(candidate.get("steps", []), depth=0, parent_id=""),
        }
        if not plan_data["steps"]:
            raise ValueError("执行计划中缺少可执行 steps。")
        return plan_data

    def _extract_step_tool_name(self, step: dict) -> str:
        if self._to_text(step.get("kind", "")).strip().lower() != "tool":
            return ""
        spec = self._parse_optional_json_object(step.get("command", "")) or {}
        name, _ = self.executor.normalize_tool_call(spec.get("name", ""), spec.get("args", {}))
        return name

    def _count_tool_steps_for_names(self, plan_data: dict, candidate_names: set[str]) -> int:
        count = 0
        for step in plan_data.get("steps", []):
            tool_name = self._extract_step_tool_name(step).lower()
            if tool_name and tool_name in candidate_names:
                count += 1
        return count

    def _build_tool_priority_violation(self, task: str, plan_data: dict) -> dict | None:
        recommended_tools = self._select_recommended_tools(task)
        if not recommended_tools:
            return None

        candidate_names = set()
        for tool in recommended_tools:
            candidate_names.add(self._to_text(tool.get("name", "")).strip().lower())
            candidate_names.add(self._to_text(tool.get("folder", "")).strip().lower())
            for alias in tool.get("aliases", []):
                candidate_names.add(self._to_text(alias).strip().lower())
        candidate_names.discard("")

        if self._count_tool_steps_for_names(plan_data, candidate_names) > 0:
            return None

        reasons = []
        if self._is_web_research_task(task) and "search_web_with_llm" in candidate_names:
            reasons.append("当前任务属于联网搜索/网页资料整理，但计划中没有优先使用 `search_web_with_llm` 这类已注册原子工具。")
            suspicious_network_impl = re.compile(
                r"urllib|requests|httpx|urlopen|duckduckgo|bing|sogou|so\.com|beautifulsoup|selenium|invoke-webrequest|invoke-restmethod|curl|wget",
                re.IGNORECASE,
            )
            for step in plan_data.get("steps", []):
                source = "\n".join(
                    [
                        self._to_text(step.get("title", "")),
                        self._to_text(step.get("command", "")),
                        self._to_text(step.get("script_content", "")),
                    ]
                )
                if suspicious_network_impl.search(source):
                    reasons.append(
                        f"步骤 `{self._to_text(step.get('id', '')).strip() or self._to_text(step.get('title', '')).strip() or 'unknown'}` 使用临时网络脚本/命令替代已注册 tool。"
                    )
                    break

        if not reasons:
            names = "、".join(self._to_text(tool.get("name", "")).strip() for tool in recommended_tools if self._to_text(tool.get("name", "")).strip())
            reasons.append(f"当前任务与以下已注册 tool 高相关：{names}；计划应优先复用这些原子能力。")

        return {
            "recommended_tools": recommended_tools,
            "reasons": reasons,
        }

    def _build_tool_priority_replan_prompt(self, task: str, previous_plan: dict, violation: dict) -> str:
        executor_schema = self._build_executor_schema()
        skill_context = self._build_skill_prompt_context(task)
        tool_context = self._build_tool_prompt_context(task)
        runtime_context = self._build_planner_runtime_context()
        recommended_tools = violation.get("recommended_tools", [])
        reasons = violation.get("reasons", [])
        return (
            "你是 exec 计划修正器。上一版计划没有优先复用已注册 TOOLS，请重新生成更优计划。\n"
            "硬性要求：\n"
            "1. 若当前任务存在高相关的已注册 tool，steps 中必须优先出现对应 tool step。\n"
            "2. 不要用 urllib、requests、httpx、curl、Invoke-WebRequest 等临时脚本/命令重写已有工具能力。\n"
            "3. 如需把 tool 输出写入文件，可使用模板变量 {{last.stdout}}、{{steps.<id>.stdout}}、{{steps.<id>.json.<field>}}。\n"
            "4. steps 仍只允许 shell、python、file、tool，且每步必须包含 verify。\n"
            "5. 只输出 JSON，顶层结构必须等价于 {\"task\":\"\",\"tool_schema\":{},\"plan\":[],\"workflow\":\"\",\"steps\":[]}。\n"
            f"违反原因：{json.dumps(reasons, ensure_ascii=False)}\n"
            f"推荐优先使用的 tools：{json.dumps(recommended_tools, ensure_ascii=False)}\n"
            f"上一版计划：{json.dumps(self._export_plan_data(previous_plan, previous_plan.get('steps', [])), ensure_ascii=False)}\n"
            f"Executor 规范：{json.dumps(executor_schema, ensure_ascii=False)}\n"
            f"系统与项目上下文：\n{runtime_context}\n"
            f"Skill 上下文：\n{skill_context}\n"
            f"Tool 上下文：\n{tool_context}\n"
            f"用户任务：{task}"
        )

    def _enforce_tool_priority(self, task: str, plan_data: dict) -> dict:
        violation = self._build_tool_priority_violation(task, plan_data)
        if not violation:
            return plan_data

        main_cfg = self._get_llm_profile_config("exec_planner", fallback="main_llm")
        repaired_plan = call_llm_json(
            self._build_tool_priority_replan_prompt(task, plan_data, violation),
            main_cfg["model"],
            main_cfg["key"],
        )
        revised = self._normalize_plan_data(task, repaired_plan)

        recommended_names = set()
        for tool in violation.get("recommended_tools", []):
            recommended_names.add(self._to_text(tool.get("name", "")).strip().lower())
            recommended_names.add(self._to_text(tool.get("folder", "")).strip().lower())
            for alias in tool.get("aliases", []):
                recommended_names.add(self._to_text(alias).strip().lower())
        recommended_names.discard("")

        original_score = self._count_tool_steps_for_names(plan_data, recommended_names)
        revised_score = self._count_tool_steps_for_names(revised, recommended_names)
        return revised if revised_score >= original_score else plan_data

    def _normalize_step_verification(self, value) -> dict:
        candidate = self._unwrap_verification_mapping(value)
        if candidate is None:
            raise ValueError("未能在模型输出中找到 step 验证结果。")
        return {
            "passed": self._coerce_bool(candidate.get("passed", False)),
            "reason": self._to_text(candidate.get("reason", "")).strip(),
        }

    def _normalize_skill_invoke_data(self, skill_name: str, value) -> dict:
        candidate = self._unwrap_skill_invoke_mapping(value)
        if candidate is None:
            raise ValueError("未能在模型输出中找到 skill 调用结构。")
        command = self._to_text(candidate.get("command", "")).strip()
        question = self._to_text(candidate.get("question", "")).strip()
        verify = self._to_text(candidate.get("verify", "")).strip()
        should_ask_user = self._coerce_bool(candidate.get("should_ask_user", False))
        if should_ask_user and not question:
            question = "请补充 skill 调用所需信息。"
        if not should_ask_user and not command:
            raise ValueError("skill 调用缺少 command。")
        return {
            "skill_name": self._to_text(candidate.get("skill_name") or skill_name).strip() or skill_name,
            "should_ask_user": should_ask_user,
            "question": question,
            "command": command,
            "verify": verify,
        }

    def _normalize_skill_reply_data(self, value) -> dict:
        candidate = self._unwrap_skill_reply_mapping(value)
        if candidate is None:
            raise ValueError("未能在模型输出中找到 skill 回复结构。")
        return {
            "reply": self._to_text(candidate.get("reply", "")).strip(),
            "completed": self._coerce_bool(candidate.get("completed", False)),
        }

    def _normalize_final_verify_data(self, value) -> dict:
        candidate = self._unwrap_verification_mapping(value)
        if candidate is None:
            raise ValueError("未能在模型输出中找到最终确认结构。")

        passed = self._coerce_bool(candidate.get("passed", False))
        reason = self._to_text(candidate.get("reason", "")).strip()
        next_action = "" if passed else (reason or "请检查失败步骤并调整任务后重试。")
        return {
            "passed": passed,
            "reason": reason,
            "completed": passed,
            "summary": reason or ("任务已完成。" if passed else "任务未完成。"),
            "verification": reason,
            "next_action": next_action,
        }

    def _build_failed_final_verify(self, reason: str) -> dict:
        text = self._to_text(reason).strip() or "执行流程失败。"
        return {
            "passed": False,
            "reason": text,
            "completed": False,
            "summary": text,
            "verification": text,
            "next_action": text,
        }

    def _truncate_text(self, value, limit: int = 240) -> str:
        """截断过长文本，避免聊天报告刷屏。"""
        text = self._to_text(value).strip()
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "..."

    def _make_display_path(self, path_text: str) -> str:
        """尽量输出更易读的路径，失败时退回原始绝对路径。"""
        raw = self._to_text(path_text).strip()
        if not raw:
            return ""
        try:
            path = Path(raw)
            if path.exists():
                try:
                    return str(path.relative_to(BASE_DIR))
                except ValueError:
                    return str(path)
        except Exception:
            pass
        return raw

    def _parse_optional_json_object(self, text: str):
        """尝试把字符串解析为 JSON 对象，失败时返回 None。"""
        parsed = handle("json", text, "parse")
        if parsed["success"] and isinstance(parsed.get("data"), dict):
            return parsed["data"]
        return None

    def _lookup_step_reference(
        self,
        expression: str,
        step_attempts: list[dict],
        current_step_id: str = "",
        current_field: str = "",
    ) -> tuple[bool, str, str]:
        expr = self._to_text(expression).strip()
        if not expr:
            return False, "", "模板变量为空。"

        latest_by_id = {}
        for attempt in step_attempts:
            step_id = self._to_text(attempt.get("id", "")).strip()
            if step_id:
                latest_by_id[step_id] = attempt

        source = None
        source_name = ""
        field_path = ""
        if expr.startswith("last."):
            if not step_attempts:
                return False, "", f"当前没有可用的前序 step 输出，无法解析 `{expr}`。"
            source = step_attempts[-1]
            source_name = self._to_text(source.get("id", "")).strip() or "last"
            field_path = expr[5:]
        elif expr.startswith("steps."):
            remainder = expr[6:]
            step_id, _, field_path = remainder.partition(".")
            step_id = self._to_text(step_id).strip()
            if not step_id or not field_path:
                return False, "", f"模板变量格式错误：`{expr}`。应使用 `{{{{steps.<step_id>.<field>}}}}`。"
            source = latest_by_id.get(step_id)
            source_name = step_id
        else:
            return False, "", f"不支持的模板变量：`{expr}`。当前仅支持 `{{{{last.<field>}}}}` 或 `{{{{steps.<step_id>.<field>}}}}`。"

        if source is None:
            if current_step_id and source_name == current_step_id and current_field in {"command", "script_content"}:
                return (
                    False,
                    "",
                    f"非法自引用：当前 step `{current_step_id}` 的 `{current_field}` 不能引用自己的执行结果 `{expr}`。"
                    " 请改为引用前序 step，或把这类检查放到 `verify` 中。",
                )
            if current_step_id and source_name == current_step_id:
                return False, "", f"当前 step `{current_step_id}` 的执行结果尚不可用，无法解析 `{expr}`。"
            return False, "", f"未找到可引用的 step `{source_name}`，无法解析 `{expr}`。"
        if not field_path:
            return False, "", f"模板变量缺少字段路径：`{expr}`。"

        if field_path.startswith("json."):
            payload = self._parse_optional_json_object(source.get("stdout", ""))
            if not isinstance(payload, dict):
                return False, "", f"step `{source_name}` 的 stdout 不是 JSON，无法解析 `{expr}`。"
            current = payload
            for part in field_path[5:].split("."):
                if not isinstance(current, dict) or part not in current:
                    return False, "", f"step `{source_name}` 的 JSON 输出中不存在字段 `{part}`，无法解析 `{expr}`。"
                current = current[part]
            return True, self._to_text(current), ""

        if field_path not in source:
            return False, "", f"step `{source_name}` 的结果中不存在字段 `{field_path}`，无法解析 `{expr}`。"
        return True, self._to_text(source.get(field_path, "")), ""

    def _render_step_templates(
        self,
        text: str,
        step_attempts: list[dict],
        current_step_id: str = "",
        current_field: str = "",
    ) -> str:
        raw = self._to_text(text)
        if "{{" not in raw:
            return raw

        errors = []

        def replace(match):
            expression = match.group(1).strip()
            found, value, error = self._lookup_step_reference(
                expression,
                step_attempts,
                current_step_id=current_step_id,
                current_field=current_field,
            )
            if not found:
                errors.append(error or f"无法解析模板变量：`{expression}`。")
                return match.group(0)
            return value

        rendered = re.sub(r"\{\{\s*([^{}]+?)\s*\}\}", replace, raw)
        if errors:
            raise ValueError("；".join(dict.fromkeys(errors)))
        return rendered

    def _render_template_payload_value(
        self,
        value,
        step_attempts: list[dict],
        current_step_id: str = "",
        current_field: str = "",
    ):
        if isinstance(value, dict):
            return {
                key: self._render_template_payload_value(
                    item,
                    step_attempts,
                    current_step_id=current_step_id,
                    current_field=current_field,
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [
                self._render_template_payload_value(
                    item,
                    step_attempts,
                    current_step_id=current_step_id,
                    current_field=current_field,
                )
                for item in value
            ]
        if not isinstance(value, str):
            return value

        exact_match = re.fullmatch(r"\s*\{\{\s*([^{}]+?)\s*\}\}\s*", value)
        if exact_match:
            found, resolved, error = self._lookup_step_reference(
                exact_match.group(1).strip(),
                step_attempts,
                current_step_id=current_step_id,
                current_field=current_field,
            )
            if not found:
                raise ValueError(error or f"无法解析模板变量：`{exact_match.group(1).strip()}`。")
            return self._to_text(resolved)

        return self._render_step_templates(
            value,
            step_attempts,
            current_step_id=current_step_id,
            current_field=current_field,
        )

    def _render_command_payload_templates(
        self,
        command: str,
        step_attempts: list[dict],
        current_step_id: str = "",
        current_field: str = "command",
    ) -> str:
        raw = self._to_text(command)
        if "{{" not in raw:
            return raw

        payload = self._parse_optional_json_object(raw)
        if payload is None:
            return self._render_step_templates(
                raw,
                step_attempts,
                current_step_id=current_step_id,
                current_field=current_field,
            )

        rendered_payload = self._render_template_payload_value(
            payload,
            step_attempts,
            current_step_id=current_step_id,
            current_field=current_field,
        )
        return json.dumps(rendered_payload, ensure_ascii=False, indent=4)

    def _materialize_step(
        self,
        step: dict,
        step_attempts: list[dict],
        fields: tuple[str, ...] = ("command", "script_content", "verify", "context"),
    ) -> dict:
        materialized = dict(step)
        current_step_id = self._to_text(materialized.get("id", "")).strip()
        for field in fields:
            if field == "command" and self._to_text(materialized.get("kind", "")).strip().lower() in {"tool", "file"}:
                materialized[field] = self._render_command_payload_templates(
                    materialized.get(field, ""),
                    step_attempts,
                    current_step_id=current_step_id,
                    current_field=field,
                )
            else:
                materialized[field] = self._render_step_templates(
                    materialized.get(field, ""),
                    step_attempts,
                    current_step_id=current_step_id,
                    current_field=field,
                )
        return materialized

    def _build_retry_review_prompt(
        self,
        task: str,
        current_plan: dict,
        current_step: dict,
        step_attempts: list[dict],
        step_outcomes: dict,
        failure_reason: str,
    ) -> str:
        executor_schema = self._build_executor_schema()
        skill_context = self._build_skill_prompt_context(task)
        tool_context = self._build_tool_prompt_context(task)
        runtime_context = self._build_planner_runtime_context()
        recent_attempts = [self._build_attempt_context_item(item) for item in step_attempts[-8:]]
        failed_origin = self._to_text(current_step.get("_origin_id") or current_step.get("id", "")).strip()
        failed_attempts = [
            self._build_attempt_context_item(item)
            for item in step_attempts
            if self._to_text(item.get("origin_id", "")).strip() == failed_origin
        ][-6:]
        outcome_items = [dict(value) for value in (step_outcomes or {}).values()]
        payload = {
            "task": task,
            "failure_reason": self._to_text(failure_reason).strip(),
            "current_step": self._export_step(current_step),
            "current_plan": self._export_plan_data(current_plan, current_plan.get("steps", [])),
            "recent_attempts": recent_attempts,
            "failed_step_attempts": failed_attempts,
            "step_outcomes": outcome_items,
        }
        return (
            "你是 exec 全流程审查与重规划器。当前流程在同一步连续失败超过阈值，需要先审查失败根因，再输出一份全新的可执行计划。\n"
            "硬性要求：\n"
            "1. 必须审查当前失败根因，尤其关注：tool 名为空、调用未注册工具、模板变量把 JSON command 渲染坏、把写文件误规划成不清楚的 tool step。\n"
            "2. 重新规划时必须重新参考完整 skill 列表与 tool 列表，不能凭空发明不存在的能力。\n"
            "3. 若任务目标是把文本保存到本地文件，优先使用 file step（action=write/append），不要滥用 tool step 写文件；除非工具列表中已有明确文件写入 tool 且名称、参数都已知。\n"
            "4. tool step 的 command 必须是合法 JSON，且 name 必须是已注册工具名或受支持别名；不能输出空 name。\n"
            "5. 若后续 step 需要前序输出，继续使用模板变量；但生成到 tool/file command 时必须保持 JSON 结构合法。\n"
            "6. 允许你推翻上一版失败计划，输出一份新的完整计划；steps 控制在 1 到 8 步，每步必须包含 verify。\n"
            '7. 最终只输出 JSON，顶层结构必须等价于 {"task":"","tool_schema":{},"plan":[],"workflow":"","steps":[]}。\n'
            f"审查输入：{json.dumps(payload, ensure_ascii=False)}\n"
            f"Executor 规范：{json.dumps(executor_schema, ensure_ascii=False)}\n"
            f"系统与项目上下文：\n{runtime_context}\n"
            f"Skill 上下文：\n{skill_context}\n"
            f"Tool 上下文：\n{tool_context}\n"
            f"用户任务：{task}"
        )

    def _review_and_replan(
        self,
        task: str,
        current_plan: dict,
        current_step: dict,
        step_attempts: list[dict],
        step_outcomes: dict,
        failure_reason: str,
    ) -> dict:
        main_cfg = self._get_llm_profile_config("exec_planner", fallback="main_llm")
        reviewed_plan = call_llm_json(
            self._build_retry_review_prompt(task, current_plan, current_step, step_attempts, step_outcomes, failure_reason),
            main_cfg["model"],
            main_cfg["key"],
        )
        normalized_plan = self._normalize_plan_data(task, reviewed_plan)
        return self._enforce_tool_priority(task, normalized_plan)

    def _prepare_runtime_step(
        self,
        task: str,
        plan_data: dict,
        step: dict,
        step_attempts: list[dict],
        current_index: int,
    ) -> dict:
        prepared = dict(step)
        if self._to_text(prepared.get("kind", "")).strip().lower() != "tool":
            return prepared

        spec = self._parse_optional_json_object(prepared.get("command", "")) or {}
        name, args = self.executor.normalize_tool_call(spec.get("name", ""), spec.get("args", {}))
        if name != "llm_dispatch":
            prepared["command"] = json.dumps({"name": name, "args": args}, ensure_ascii=False, indent=4)
            return prepared

        if not self._should_attach_independent_llm_context(name):
            prepared["command"] = json.dumps({"name": name, "args": args}, ensure_ascii=False, indent=4)
            return prepared

        context_mode = self._normalize_context_mode(prepared.get("context_mode", "step"))
        runtime_context = self._build_step_context_payload(task, plan_data, prepared, step_attempts, current_index=current_index)
        if context_mode == "history":
            runtime_context["run_context"] = self._build_run_context_payload(task, plan_data, step_attempts, current_index=current_index)
        elif context_mode == "run" or bool(args.get("include_run_context", False)):
            runtime_context["run_context"] = self._build_run_context_payload(task, plan_data, step_attempts, current_index=current_index)
        elif context_mode == "minimal":
            runtime_context.pop("dependencies", None)
            runtime_context.pop("recent_attempts", None)

        if bool(args.get("include_history", False)) and "run_context" not in runtime_context:
            runtime_context["run_context"] = self._build_run_context_payload(task, plan_data, step_attempts, current_index=current_index)

        merged_args = dict(args)
        if prepared.get("context") and not self._to_text(merged_args.get("context", "")).strip():
            merged_args["context"] = prepared.get("context", "")
        if prepared.get("llm_profile") and not self._to_text(merged_args.get("llm_profile", "")).strip():
            merged_args["llm_profile"] = prepared.get("llm_profile", "")
        merged_args["_runtime_context"] = runtime_context
        merged_args["_expectation"] = self._build_llm_step_expectation(prepared, merged_args)
        prepared["command"] = json.dumps({"name": name, "args": merged_args}, ensure_ascii=False, indent=4)
        return prepared

    def _collect_artifacts_from_attempt(self, step_result: dict) -> list[dict]:
        """从单次 step 执行结果中提取产物路径与操作信息。"""
        artifacts = []
        script_path = self._to_text(step_result.get("script_path", "")).strip()
        if script_path:
            artifacts.append(
                {
                    "path": script_path,
                    "display_path": self._make_display_path(script_path),
                    "type": "script",
                    "action": "generated",
                    "step_id": step_result.get("id", ""),
                    "step_title": step_result.get("title", ""),
                }
            )

        kind = self._to_text(step_result.get("kind", "")).strip().lower()
        if kind != "file":
            return artifacts

        spec = self._parse_optional_json_object(step_result.get("command", ""))
        if not spec:
            return artifacts

        path_text = self._to_text(spec.get("path", "")).strip()
        if not path_text:
            return artifacts

        try:
            target_path = Path(path_text)
            if not target_path.is_absolute():
                target_path = (BASE_DIR / target_path).resolve()
        except Exception:
            target_path = Path(path_text)

        action = self._to_text(spec.get("action", "")).strip().lower() or "unknown"
        exists = False
        try:
            exists = target_path.exists()
        except Exception:
            exists = False

        artifacts.append(
            {
                "path": str(target_path),
                "display_path": self._make_display_path(str(target_path)),
                "type": "file",
                "action": action,
                "exists": exists,
                "step_id": step_result.get("id", ""),
                "step_title": step_result.get("title", ""),
            }
        )
        return artifacts

    def collect_result_artifacts(self, result: dict) -> list[dict]:
        """汇总本次 exec 产生的脚本与文件产物。"""
        attempts = ((result or {}).get("result") or {}).get("steps", [])
        collected = []
        seen = set()
        for step_result in attempts:
            for artifact in self._collect_artifacts_from_attempt(step_result):
                key = (
                    artifact.get("path", ""),
                    artifact.get("type", ""),
                    artifact.get("action", ""),
                    artifact.get("step_id", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                collected.append(artifact)
        return collected

    def _build_step_report_lines(self, result: dict) -> list[str]:
        """为聊天报告整理关键步骤摘要。"""
        step_outcomes = ((result or {}).get("result") or {}).get("step_outcomes", [])
        if not step_outcomes:
            return ["- 本次执行未记录步骤摘要。"]

        lines = []
        for item in step_outcomes[:8]:
            status = "成功" if item.get("status") == "success" else "失败"
            title = self._to_text(item.get("title") or item.get("id", "")).strip()
            reason = self._truncate_text(item.get("reason", ""), limit=120)
            line = f"- `{item.get('id', '')}` {title}：{status}"
            if reason:
                line += f"；{reason}"
            last_attempt = item.get("last_attempt", {}) or {}
            script_path = self._make_display_path(last_attempt.get("script_path", ""))
            if script_path:
                line += f"；脚本：`{script_path}`"
            lines.append(line)
        return lines

    def _build_artifact_report_lines(self, result: dict) -> list[str]:
        """为聊天报告整理本地产物摘要。"""
        artifacts = self.collect_result_artifacts(result)
        if not artifacts:
            return ["- 本次执行没有生成脚本文件，或未记录到可见本地产物。"]

        lines = []
        for artifact in artifacts[:12]:
            action = self._to_text(artifact.get("action", "")).strip() or "unknown"
            type_name = self._to_text(artifact.get("type", "")).strip() or "artifact"
            display_path = self._to_text(artifact.get("display_path") or artifact.get("path", "")).strip()
            prefix = "生成脚本" if type_name == "script" else f"文件操作({action})"
            lines.append(f"- {prefix}：`{display_path}`")
        return lines

    def build_report_payload(self, task: str, result: dict, autonomous: bool = False) -> dict:
        """构造统一的 exec 报告载荷，供 GUI/CLI/会话写回共用。"""
        verify = (result or {}).get("verify", {}) or {}
        completed = bool(verify.get("completed", False))
        title = "AI-Agent 已自主执行本地任务" if autonomous else "执行任务"
        return {
            "title": title,
            "task": task,
            "completed": completed,
            "summary": self._to_text(verify.get("summary", "")).strip() or ("任务已完成。" if completed else "任务未完成。"),
            "verification": self._to_text(verify.get("verification", "")).strip(),
            "next_action": self._to_text(verify.get("next_action", "")).strip(),
            "plan_path": self._to_text(result.get("plan_path", "")).strip(),
            "result_path": self._to_text(result.get("result_path", "")).strip(),
            "verify_path": self._to_text(result.get("verify_path", "")).strip(),
            "report_path": self._to_text(result.get("report_path", "")).strip(),
            "full_info_path": self._to_text(result.get("full_info_path", "")).strip(),
            "sandbox": ((result or {}).get("result") or {}).get("sandbox", {}),
            "artifacts": self.collect_result_artifacts(result),
            "step_lines": self._build_step_report_lines(result),
            "artifact_lines": self._build_artifact_report_lines(result),
        }

    def build_chat_report(self, task: str, result: dict, autonomous: bool = False) -> str:
        """生成可直接写入聊天窗口的 Markdown 执行报告。"""
        payload = self.build_report_payload(task, result, autonomous=autonomous)
        status_text = "已完成" if payload["completed"] else "未完成"
        sandbox_meta = payload.get("sandbox", {}) or {}
        lines = [
            f"{payload['title']}：{payload['task']}",
            "",
            "## 执行结果",
            f"- 完成状态：{status_text}",
            f"- 结果摘要：{payload['summary']}",
            f"- 验证结论：{payload['verification'] or '无'}",
            f"- 后续建议：{payload['next_action'] or '无'}",
            f"- 执行后端：{self._describe_backend(sandbox_meta)}",
            "",
            "## 关键步骤",
            *payload["step_lines"],
            "",
            "## 本地产物",
            *payload["artifact_lines"],
            "",
            "## 沙箱信息",
            f"- 沙箱 ID：`{self._to_text(sandbox_meta.get('sandbox_id', '')).strip() or '无'}`",
            f"- 工作目录：`{self._to_text(sandbox_meta.get('workspace', '')).strip() or '无'}`",
            f"- 项目快照同步：{'开启' if sandbox_meta.get('sync_enabled') else '关闭'}",
            "",
            "## 结果文件",
            f"- 计划文件：`{payload['plan_path'] or '无'}`",
            f"- 结果文件：`{payload['result_path'] or '无'}`",
            f"- 确认文件：`{payload['verify_path'] or '无'}`",
            f"- 报告文件：`{payload['report_path'] or '无'}`",
            f"- 完整结构化流程：`{payload['full_info_path'] or '无'}`",
        ]
        return "\n".join(lines).strip()

    def _append_full_info_notice(self, message: str, result: dict) -> str:
        full_info_path = self._to_text((result or {}).get("full_info_path", "")).strip()
        if not full_info_path:
            return self._to_text(message).strip()
        text = self._to_text(message).strip()
        notice = f"本次任务完整结构化 exec 流程文件：`{full_info_path}`"
        if not text:
            return notice
        if full_info_path in text:
            return text
        return f"{text}\n\n{notice}".strip()

    def _write_report_file(self, path: Path, text: str) -> None:
        """把最终 exec 报告写入本地 Markdown 文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._to_text(text).strip() + "\n", encoding="utf-8")

    def _read_text_file_if_exists(self, path_text: str) -> str:
        """尽量读取本地文本文件；失败时返回空字符串。"""
        raw = self._to_text(path_text).strip()
        if not raw:
            return ""
        try:
            path = Path(raw)
            if not path.exists() or not path.is_file():
                return ""
            for encoding in ("utf-8", "utf-8-sig", "gbk"):
                try:
                    return path.read_text(encoding=encoding).strip()
                except UnicodeDecodeError:
                    continue
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return ""

    def _find_preferred_report_file(self, result: dict) -> str:
        """按优先级查找可直接发送到聊天区的本地报告文件。"""
        result = self._normalize_result_envelope(result)
        direct_report = self._to_text((result or {}).get("report_path", "")).strip()
        if direct_report:
            return direct_report

        for artifact in self.collect_result_artifacts(result):
            path_text = self._to_text(artifact.get("path", "")).strip()
            if not path_text:
                continue
            suffix = Path(path_text).suffix.lower()
            if suffix in {".md", ".markdown", ".txt"}:
                return path_text
        return ""

    def _normalize_result_envelope(self, result: dict) -> dict:
        """兼容运行时返回结构与落盘 `*_result.json` 结构。"""
        data = result or {}
        if isinstance(data.get("result"), dict) and isinstance(data.get("verify"), dict):
            return data
        if "steps" in data and "verify" not in data:
            return {
                "run_id": data.get("run_id", ""),
                "task": data.get("task", ""),
                "plan_path": data.get("plan_path", ""),
                "result_path": data.get("result_path", ""),
                "verify_path": data.get("verify_path", ""),
                "report_path": data.get("report_path", ""),
                "plan": data.get("plan", {}),
                "result": {
                    "final_state": data.get("final_state", ""),
                    "state_history": data.get("state_history", []),
                    "exec_config": data.get("exec_config", {}),
                    "sandbox": data.get("sandbox", {}),
                    "steps": data.get("steps", []),
                    "step_outcomes": data.get("step_outcomes", []),
                    "artifacts": data.get("artifacts", []),
                },
                "verify": {
                    "passed": str(data.get("final_state", "")).upper() == "DONE",
                    "completed": str(data.get("final_state", "")).upper() == "DONE",
                    "summary": "",
                    "verification": "",
                    "next_action": "",
                },
            }
        return data

    def _is_markdown_like_output(self, text: str) -> bool:
        """粗略判断输出是否更适合按 Markdown 原样回传。"""
        raw = self._to_text(text)
        return any(marker in raw for marker in ("# ", "## ", "```", "- ", "* ", "| "))

    def _is_operational_stdout(self, text: str) -> bool:
        """判断 stdout 是否更像执行回执，而不是用户真正想要的结果。"""
        raw = self._to_text(text).strip()
        if not raw:
            return True
        prefixes = (
            "已写入文件：",
            "已追加文件：",
            "已修改文件：",
            "已删除：",
            "已创建目录：",
            "目标不存在，无需删除：",
            "已生成",
        )
        if raw.startswith(prefixes):
            return True
        if len(raw.splitlines()) == 1 and len(raw) <= 120 and raw.startswith("F:"):
            return True
        return False

    def _pick_user_facing_output(self, result: dict) -> dict:
        """从 step 输出中挑选最适合直接回复给用户的内容。"""
        result = self._normalize_result_envelope(result)
        attempts = ((result or {}).get("result") or {}).get("steps", [])
        best = {"score": -1, "intro": "", "body": "", "format": "text"}
        for step in attempts:
            if not step.get("success"):
                continue
            stdout = self._to_text(step.get("stdout", "")).strip()
            if not stdout or self._is_operational_stdout(stdout):
                continue

            kind = self._to_text(step.get("kind", "")).strip().lower()
            title = self._to_text(step.get("title", "")).strip()
            intro = "执行结果如下"
            score = 10
            output_format = "text"

            if kind == "tool":
                spec = self._parse_optional_json_object(step.get("command", "")) or {}
                tool_name, tool_args = self.executor.normalize_tool_call(spec.get("name", ""), spec.get("args", {}))
                if tool_name == "read_text":
                    path_text = self._to_text(tool_args.get("path", "")).strip()
                    intro = f"{path_text} 内容如下" if path_text else "读取结果如下"
                    score = 120
                    output_format = "markdown" if path_text.lower().endswith((".md", ".markdown")) else "text"
                elif tool_name in {"list_dir", "glob"}:
                    path_text = self._to_text(tool_args.get("path", "")).strip() or "."
                    intro = f"{path_text} 的内容如下"
                    score = 100
                    output_format = "text"
                elif tool_name == "llm_dispatch":
                    intro = title or "LLM 子任务结果如下"
                    score = 110
                    if self._is_markdown_like_output(stdout):
                        output_format = "markdown"
                elif tool_name == "shell":
                    intro = title or "命令输出如下"
                    score = 80
            elif kind == "file":
                spec = self._parse_optional_json_object(step.get("command", "")) or {}
                action = self._to_text(spec.get("action", "")).strip().lower()
                path_text = self._to_text(spec.get("path", "")).strip()
                if action == "read":
                    intro = f"{path_text} 内容如下" if path_text else "文件内容如下"
                    score = 120
                    output_format = "markdown" if path_text.lower().endswith((".md", ".markdown")) else "text"
                else:
                    score = 30
            elif kind == "python":
                intro = title or "脚本输出如下"
                score = 70
            elif kind == "shell":
                intro = title or "命令输出如下"
                score = 75

            if len(stdout) > 500:
                score += 5
            if self._is_markdown_like_output(stdout):
                output_format = "markdown"
                score += 3

            if score > best["score"]:
                best = {"score": score, "intro": intro, "body": stdout, "format": output_format}
        return best

    def _build_user_facing_message(self, task: str, result: dict, autonomous: bool = False) -> str:
        """优先返回真正的任务产出，其次回退到结构化执行报告。"""
        result = self._normalize_result_envelope(result)
        candidate = self._pick_user_facing_output(result)
        body = self._to_text(candidate.get("body", "")).strip()
        if body:
            intro = self._to_text(candidate.get("intro", "")).strip() or "执行结果如下"
            if candidate.get("format") == "markdown":
                return self._append_full_info_notice(f"{intro}：\n\n{body}".strip(), result)
            return self._append_full_info_notice(f"{intro}：\n\n```text\n{body}\n```".strip(), result)

        report_path = self._find_preferred_report_file(result)
        file_text = self._read_text_file_if_exists(report_path)
        if file_text:
            return self._append_full_info_notice(file_text, result)
        return self._append_full_info_notice(self.build_chat_report(task, result, autonomous=autonomous), result)

    def get_chat_report_message(self, task: str, result: dict, autonomous: bool = False) -> str:
        """优先返回任务实际产出，再回退到结构化执行报告。"""
        return self._build_user_facing_message(task, self._normalize_result_envelope(result), autonomous=autonomous)

    def _describe_backend(self, sandbox_meta: dict) -> str:
        """把执行后端整理成易读文本。"""
        meta = sandbox_meta or {}
        if meta.get("enabled"):
            provider = self._to_text(meta.get("provider", "CubeSandbox")).strip() or "CubeSandbox"
            sandbox_id = self._to_text(meta.get("sandbox_id", "")).strip()
            return f"{provider} 沙箱" + (f" / {sandbox_id}" if sandbox_id else "")
        return "宿主机本地执行"

    def _emit_skill_phase(self, callback, message: str, extra: dict | None = None) -> None:
        event = {"type": "skill_phase", "message": message}
        if extra:
            event.update(extra)
        self._emit(callback, event)

    def _quote_powershell_arg(self, value: str) -> str:
        return "'" + str(value or "").replace("'", "''") + "'"

    def _build_direct_skill_command(self, entry_script: str, args_text: str) -> str:
        command = f"& {self._quote_powershell_arg(sys.executable)} {self._quote_powershell_arg(entry_script)}"
        extra = self._to_text(args_text).strip()
        if extra:
            command = f"{command} {extra}"
        return command

    def _plan_skill_invocation(self, user_input: str, skill: dict) -> dict:
        main_cfg = self._get_main_llm_config()
        invoke_data = call_llm_json(
            self._build_skill_invoke_prompt(user_input, skill),
            main_cfg["model"],
            main_cfg["key"],
        )
        return self._normalize_skill_invoke_data(skill.get("folder", ""), invoke_data)

    def _build_skill_reply(self, user_input: str, skill: dict, command: str, run_result: dict) -> dict:
        main_cfg = self._get_main_llm_config()
        reply_data = call_llm_json(
            self._build_skill_reply_prompt(user_input, skill, command, run_result),
            main_cfg["model"],
            main_cfg["key"],
        )
        return self._normalize_skill_reply_data(reply_data)

    def run_skill(self, user_input: str, skill_name: str, callback=None) -> dict:
        skill = self.skill_repository.get_skill(skill_name)
        self._emit_skill_phase(callback, f"已匹配 skill：{skill['folder']}", {"skill_name": skill["folder"]})
        invoke_plan = self._plan_skill_invocation(user_input, skill)
        if invoke_plan.get("should_ask_user"):
            question = invoke_plan.get("question", "").strip() or "请补充 skill 调用所需信息。"
            self._emit_skill_phase(callback, question, {"skill_name": skill["folder"], "needs_input": True})
            return {
                "triggered": True,
                "kind": "skill",
                "skill_name": skill["folder"],
                "completed": False,
                "needs_user_input": True,
                "reply": question,
                "skill": {
                    "folder": skill["folder"],
                    "name": skill["name"],
                    "description": skill["description"],
                },
            }

        command = self._to_text(invoke_plan.get("command", "")).strip()
        if not command:
            raise ValueError("skill 调用缺少 command。")

        self._emit_skill_phase(
            callback,
            f"开始执行 skill：{skill['folder']}",
            {"skill_name": skill["folder"], "command": command},
        )
        run_result = self.executor.run(
            {
                "id": f"skill_{skill['folder']}",
                "title": f"skill:{skill['folder']}",
                "kind": "shell",
                "command": command,
                "verify": self._to_text(invoke_plan.get("verify", "")).strip(),
            }
        )
        reply_payload = self._build_skill_reply(user_input, skill, command, run_result)
        reply = reply_payload.get("reply", "").strip()
        if not reply:
            if run_result.get("success"):
                reply = self._to_text(run_result.get("stdout", "")).strip() or f"skill `{skill['folder']}` 已执行完成。"
            else:
                reply = self._to_text(run_result.get("stderr", "")).strip() or f"skill `{skill['folder']}` 执行失败。"

        self._emit(
            callback,
            {
                "type": "skill_result",
                "message": reply,
                "skill_name": skill["folder"],
                "command": command,
                "run_result": run_result,
            },
        )
        return {
            "triggered": True,
            "kind": "skill",
            "skill_name": skill["folder"],
            "completed": bool(reply_payload.get("completed", run_result.get("success", False))),
            "reply": reply,
            "command": command,
            "run_result": run_result,
            "skill": {
                "folder": skill["folder"],
                "name": skill["name"],
                "description": skill["description"],
            },
        }

    def run_skill_direct(self, skill_name: str, args_text: str = "", callback=None) -> dict:
        skill, entry_script = self.skill_repository.resolve_skill_entry(skill_name)
        entry_name = Path(entry_script).stem
        self._emit_skill_phase(
            callback,
            f"开始执行 skill：{skill['folder']} ({entry_name})",
            {"skill_name": skill["folder"], "entry_name": entry_name},
        )
        command = self._build_direct_skill_command(entry_script, args_text)
        run_result = self.executor.run(
            {
                "id": f"skill_{skill['folder']}",
                "title": f"skill:{skill['folder']}",
                "kind": "shell",
                "command": command,
                "verify": "",
            }
        )
        if run_result.get("success"):
            reply = self._to_text(run_result.get("stdout", "")).strip() or f"skill `{skill['folder']}` 已执行完成。"
        else:
            reply = (
                self._to_text(run_result.get("stderr", "")).strip()
                or self._to_text(run_result.get("stdout", "")).strip()
                or f"skill `{skill['folder']}` 执行失败。"
            )
        self._emit(
            callback,
            {
                "type": "skill_result",
                "message": reply,
                "skill_name": skill["folder"],
                "entry_name": entry_name,
                "command": command,
                "run_result": run_result,
            },
        )
        return {
            "triggered": True,
            "kind": "skill",
            "skill_name": skill["folder"],
            "entry_name": entry_name,
            "completed": bool(run_result.get("success", False)),
            "reply": reply,
            "command": command,
            "run_result": run_result,
            "skill": {
                "folder": skill["folder"],
                "name": skill["name"],
                "description": skill["description"],
                "entry_script": entry_script,
            },
        }

    def _verify_step(self, task: str, step: dict, step_result: dict) -> dict:
        main_cfg = self._get_llm_profile_config("exec_verifier", fallback="main_llm")
        verify_data = call_llm_json(
            self._build_step_verify_prompt(task, step, step_result),
            main_cfg["model"],
            main_cfg["key"],
        )
        return self._normalize_step_verification(verify_data)

    def _repair_step(self, task: str, step: dict, step_result: dict, reason: str) -> dict:
        profile = self._to_text(step.get("llm_profile", "")).strip() or "exec_repairer"
        main_cfg = self._get_llm_profile_config(profile, fallback="exec_worker")
        repair_data = call_llm_json(
            self._build_retry_prompt(task, step, step_result, reason),
            main_cfg["model"],
            main_cfg["key"],
        )
        candidate = self._unwrap_step_mapping(repair_data)
        if candidate is None:
            raise ValueError("未能在模型修复结果中找到 step 结构。")

        fixed_step = dict(step)
        fixed_step["command"] = self._normalize_embedded_text(
            candidate.get("command", step.get("command", "")),
            preferred_types=["json", "txt", "bash"],
        )
        fixed_step["script_content"] = self._normalize_embedded_text(
            candidate.get("script_content", step.get("script_content", "")),
            preferred_types=["python", "markdown", "txt"],
        )
        fixed_step["context"] = self._normalize_embedded_text(
            candidate.get("context", step.get("context", "")),
            preferred_types=["markdown", "json", "txt"],
        )
        fixed_step["llm_profile"] = self._to_text(candidate.get("llm_profile", step.get("llm_profile", ""))).strip()
        if fixed_step.get("kind") == "tool":
            fixed_step["command"] = self.executor.normalize_tool_command(fixed_step.get("command", ""))
            repaired_spec = self._parse_optional_json_object(fixed_step.get("command", "")) or {}
            repaired_name, _ = self.executor.normalize_tool_call(repaired_spec.get("name", ""), repaired_spec.get("args", {}))
            if not repaired_name:
                raise ValueError("修复后的 tool step 缺少有效工具名。")
        return fixed_step

    def _plan_task(self, task: str) -> dict:
        main_cfg = self._get_llm_profile_config("exec_planner", fallback="main_llm")
        plan_data = call_llm_json(
            self._build_plan_prompt(task),
            main_cfg["model"],
            main_cfg["key"],
        )
        normalized_plan = self._normalize_plan_data(task, plan_data)
        return self._enforce_tool_priority(task, normalized_plan)

    def _verify_result(self, task: str, plan_data: dict, result_data: dict) -> dict:
        main_cfg = self._get_llm_profile_config("exec_verifier", fallback="main_llm")
        verify_data = call_llm_json(
            self._build_final_verify_prompt(task, plan_data, result_data),
            main_cfg["model"],
            main_cfg["key"],
        )
        return self._normalize_final_verify_data(verify_data)

    def _build_step_outcome(self, step: dict, status: str, reason: str, attempt_result: dict | None = None) -> dict:
        outcome = self._export_step(step)
        outcome["status"] = status
        outcome["reason"] = self._to_text(reason).strip()
        if attempt_result is not None:
            outcome["last_attempt"] = {
                "returncode": attempt_result.get("returncode", -1),
                "stdout": attempt_result.get("stdout", ""),
                "stderr": attempt_result.get("stderr", ""),
                "script_path": attempt_result.get("script_path", ""),
            }
        return outcome

    def _build_result_data(
        self,
        run_id: str,
        task: str,
        plan_path: str,
        plan_data: dict,
        steps: list[dict],
        step_attempts: list[dict],
        step_outcomes: dict,
        state_history: list[str],
        final_state: str,
    ) -> dict:
        return {
            "run_id": run_id,
            "task": task,
            "plan_path": plan_path,
            "final_state": final_state,
            "state_history": state_history,
            "exec_config": self.exec_config,
            "sandbox": self.executor.get_backend_summary(),
            "plan": self._export_plan_data(plan_data, steps),
            "steps": step_attempts,
            "step_outcomes": list(step_outcomes.values()),
            "artifacts": self.collect_result_artifacts({"result": {"steps": step_attempts}}),
        }

    def _build_final_response(
        self,
        task: str,
        run_id: str,
        paths: dict,
        plan_data: dict,
        steps: list[dict],
        result_data: dict,
        final_verify: dict,
    ) -> dict:
        """统一生成最终返回结构，并写出可直接查看的 Markdown 报告。"""
        response = {
            "run_id": run_id,
            "task": task,
            "plan_path": str(paths["plan"]),
            "result_path": str(paths["result"]),
            "verify_path": str(paths["verify"]),
            "report_path": str(paths["report"]),
            "plan": self._export_plan_data(plan_data, steps),
            "result": result_data,
            "verify": final_verify,
        }
        response["artifacts"] = self.collect_result_artifacts(response)
        response["report_payload"] = self.build_report_payload(task, response, autonomous=False)
        generated_report = self.build_chat_report(task, response, autonomous=False)
        self._write_report_file(paths["report"], generated_report)
        response["chat_report"] = self.get_chat_report_message(task, response, autonomous=False)
        return response

    def run(self, task: str, callback=None) -> dict:
        """执行完整自主执行闭环：规划 -> 执行 -> 观察 -> 验证 -> 修复重试 -> 最终确认。"""
        run_id = self._build_run_id()
        paths = self._get_plan_paths(run_id)
        full_info_path = self._get_full_info_path(run_id)
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event_logs = []
        upstream_callback = callback

        def callback(event: dict):
            self._record_event(event_logs, event)
            if upstream_callback is not None:
                upstream_callback(event)

        self.executor.set_run_context(run_id, emit=lambda text: self._emit_phase(callback, text, state="SANDBOX"))

        state = STATE_PLAN
        state_history = []
        plan_data = {"task": task, "tool_schema": self._build_executor_schema(), "plan": [], "workflow": "", "steps": []}
        steps = []
        step_attempts = []
        step_outcomes = {}
        current_index = 0
        current_step = None
        current_executable_step = None
        current_step_result = None
        final_verify = None
        failure_reason = ""
        review_replan_count = 0

        try:
            while True:
                state_history.append(state)

                if state == STATE_PLAN:
                    skills = self._load_skill_summaries()
                    if skills:
                        skill_names = "、".join(item["folder"] for item in skills[:8])
                        self._emit_phase(
                            callback,
                            f"已检查技能列表，当前可用 skill：{skill_names}",
                            state=state,
                        )
                    else:
                        self._emit_phase(callback, "已检查技能列表，当前没有可用 skill。", state=state)
                    self._emit_phase(callback, "开始生成自主执行计划...", state=state)
                    try:
                        plan_data = self._plan_task(task)
                    except Exception as exc:
                        failure_reason = f"生成执行计划失败：{exc}"
                        state = STATE_FAILED
                        continue
                    steps = plan_data["steps"]
                    if len(steps) > self.exec_config["max_steps"]:
                        failure_reason = f"计划 steps 数量超出限制：{len(steps)} > {self.exec_config['max_steps']}"
                        state = STATE_FAILED
                        continue

                    save_json(paths["plan"], self._export_plan_data(plan_data, steps))
                    self._emit(
                        callback,
                        {
                            "type": "exec_plan",
                            "message": plan_data.get("workflow", ""),
                            "plan_path": str(paths["plan"]),
                            "plan": self._export_plan_data(plan_data, steps),
                        },
                    )
                    state = STATE_EXECUTE
                    continue

                if state == STATE_EXECUTE:
                    if current_index >= len(steps):
                        state = STATE_VERIFY_FINAL
                        continue

                    current_step = steps[current_index]
                    try:
                        executable_step = self._materialize_step(
                            current_step,
                            step_attempts,
                            fields=("command", "script_content", "context"),
                        )
                        executable_step = self._prepare_runtime_step(task, plan_data, executable_step, step_attempts, current_index)
                    except Exception as exc:
                        failure_reason = f"步骤准备失败：{exc}"
                        current_step["_final_status"] = "failed"
                        current_step["_last_failure_reason"] = failure_reason
                        step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                            current_step,
                            status="failed",
                            reason=failure_reason,
                        )
                        state = STATE_FAILED
                        continue
                    current_executable_step = executable_step
                    current_step["_attempt_count"] = int(current_step.get("_attempt_count", 0)) + 1
                    self._emit(
                        callback,
                        {
                            "type": "exec_step_start",
                            "message": f"开始执行第 {current_index + 1} 步：{executable_step.get('title', executable_step.get('id', current_index + 1))}",
                            "step": self._export_step(executable_step),
                            "index": current_index + 1,
                            "total": len(steps),
                        },
                    )
                    current_step_result = self.executor.run(executable_step)
                    current_step_result["attempt"] = current_step.get("_attempt_count", 1)
                    step_attempts.append(current_step_result)
                    self._emit(
                        callback,
                        {
                            "type": "exec_step_done",
                            "message": f"第 {current_index + 1} 步执行完成，返回码：{current_step_result['returncode']}",
                            "step_result": current_step_result,
                            "index": current_index + 1,
                            "total": len(steps),
                        },
                    )
                    state = STATE_VERIFY_STEP
                    continue

                if state == STATE_VERIFY_STEP:
                    verification_step = dict(current_executable_step or current_step or {})
                    try:
                        verification_step["verify"] = self._render_step_templates(
                            self._to_text((current_step or {}).get("verify", "")),
                            step_attempts,
                        )
                        verification = self._verify_step(task, verification_step, current_step_result)
                    except Exception as exc:
                        failure_reason = f"步骤验证失败：{exc}"
                        current_step["_final_status"] = "failed"
                        current_step["_last_failure_reason"] = failure_reason
                        step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                            current_step,
                            status="failed",
                            reason=failure_reason,
                            attempt_result=current_step_result,
                        )
                        state = STATE_FAILED
                        continue
                    current_step_result["step_verification"] = verification
                    self._emit_phase(
                        callback,
                        f"步骤 {current_step.get('id', '')} 验证{'通过' if verification['passed'] else '失败'}：{verification['reason']}",
                        state=state,
                    )

                    if verification["passed"]:
                        current_step["_final_status"] = "success"
                        current_step["_last_failure_reason"] = ""
                        step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                            current_step,
                            status="success",
                            reason=verification["reason"],
                            attempt_result=current_step_result,
                        )
                        current_index += 1
                        state = STATE_EXECUTE
                        continue

                    current_step["_last_failure_reason"] = verification["reason"]
                    if int(current_step.get("_retry_count", 0)) >= self.exec_config["retry_limit"]:
                        failure_reason = verification["reason"] or f"步骤 {current_step.get('id', '')} 超过重试上限。"
                        current_step["_final_status"] = "failed"
                        step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                            current_step,
                            status="failed",
                            reason=failure_reason,
                            attempt_result=current_step_result,
                        )
                        state = STATE_FAILED
                        continue

                    state = STATE_RETRY_STEP
                    continue

                if state == STATE_RETRY_STEP:
                    reason = current_step.get("_last_failure_reason", "") or "步骤验证失败。"
                    next_retry = int(current_step.get("_retry_count", 0)) + 1
                    review_after = self.exec_config.get("review_after_retry_limit", 3)
                    if next_retry > review_after:
                        if review_replan_count >= self.exec_config["max_expand_depth"]:
                            failure_reason = f"连续审查重规划次数已达上限：{review_replan_count}。最近失败原因：{reason}"
                            current_step["_final_status"] = "failed"
                            step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                                current_step,
                                status="failed",
                                reason=failure_reason,
                                attempt_result=current_step_result,
                            )
                            state = STATE_FAILED
                            continue
                        self._emit_phase(
                            callback,
                            f"步骤 {current_step.get('id', '')} 已连续失败超过 {review_after} 次，开始审查全流程并重新规划。",
                            state=STATE_REVIEW_REPLAN,
                        )
                        try:
                            plan_data = self._review_and_replan(
                                task,
                                plan_data,
                                current_step,
                                step_attempts,
                                step_outcomes,
                                reason,
                            )
                        except Exception as exc:
                            failure_reason = f"审查重规划失败：{exc}"
                            current_step["_final_status"] = "failed"
                            step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                                current_step,
                                status="failed",
                                reason=failure_reason,
                                attempt_result=current_step_result,
                            )
                            state = STATE_FAILED
                            continue
                        review_replan_count += 1
                        steps = plan_data["steps"]
                        current_index = 0
                        current_step = None
                        current_executable_step = None
                        current_step_result = None
                        final_verify = None
                        save_json(paths["plan"], self._export_plan_data(plan_data, steps))
                        self._emit(
                            callback,
                            {
                                "type": "exec_plan",
                                "message": plan_data.get("workflow", ""),
                                "plan_path": str(paths["plan"]),
                                "plan": self._export_plan_data(plan_data, steps),
                            },
                        )
                        state = STATE_EXECUTE
                        continue
                    self._emit_phase(
                        callback,
                        f"开始修复并重试 step：{current_step.get('id', '')}，第 {next_retry} 次重试。",
                        state=state,
                    )
                    try:
                        fixed_step = self._repair_step(task, current_step, current_step_result, reason)
                    except Exception as exc:
                        failure_reason = f"step 修复失败：{exc}"
                        current_step["_final_status"] = "failed"
                        step_outcomes[current_step["_origin_id"]] = self._build_step_outcome(
                            current_step,
                            status="failed",
                            reason=failure_reason,
                            attempt_result=current_step_result,
                        )
                        state = STATE_FAILED
                        continue

                    current_step["command"] = fixed_step.get("command", current_step.get("command", ""))
                    current_step["script_content"] = fixed_step.get("script_content", current_step.get("script_content", ""))
                    current_step["context"] = fixed_step.get("context", current_step.get("context", ""))
                    current_step["llm_profile"] = fixed_step.get("llm_profile", current_step.get("llm_profile", ""))
                    current_step["_retry_count"] = next_retry
                    save_json(paths["plan"], self._export_plan_data(plan_data, steps))
                    state = STATE_EXECUTE
                    continue

                if state == STATE_VERIFY_FINAL:
                    result_data = self._build_result_data(
                        run_id=run_id,
                        task=task,
                        plan_path=str(paths["plan"]),
                        plan_data=plan_data,
                        steps=steps,
                        step_attempts=step_attempts,
                        step_outcomes=step_outcomes,
                        state_history=state_history,
                        final_state=state,
                    )
                    save_json(paths["result"], result_data)
                    self._emit_phase(callback, "开始最终确认任务完成情况...", state=state)
                    try:
                        final_verify = self._verify_result(task, self._export_plan_data(plan_data, steps), result_data)
                    except Exception as exc:
                        failure_reason = f"最终确认失败：{exc}"
                        final_verify = self._build_failed_final_verify(failure_reason)
                        state = STATE_FAILED
                        continue

                    save_json(paths["verify"], final_verify)
                    self._emit(
                        callback,
                        {
                            "type": "exec_verify",
                            "message": final_verify.get("reason", ""),
                            "verify": final_verify,
                            "verify_path": str(paths["verify"]),
                        },
                    )
                    state = STATE_DONE if final_verify["passed"] else STATE_FAILED
                    if not final_verify["passed"]:
                        failure_reason = final_verify.get("reason", "") or "最终确认未通过。"
                    continue

                if state == STATE_DONE:
                    result_data = self._build_result_data(
                        run_id=run_id,
                        task=task,
                        plan_path=str(paths["plan"]),
                        plan_data=plan_data,
                        steps=steps,
                        step_attempts=step_attempts,
                        step_outcomes=step_outcomes,
                        state_history=state_history,
                        final_state=state,
                    )
                    save_json(paths["result"], result_data)
                    if final_verify is None:
                        final_verify = {
                            "passed": True,
                            "reason": "任务已完成。",
                            "completed": True,
                            "summary": "任务已完成。",
                            "verification": "任务已完成。",
                            "next_action": "",
                        }
                        save_json(paths["verify"], final_verify)
                    response = self._build_final_response(
                        task=task,
                        run_id=run_id,
                        paths=paths,
                        plan_data=plan_data,
                        steps=steps,
                        result_data=result_data,
                        final_verify=final_verify,
                    )
                    finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    full_exec_reference = self._build_full_exec_reference(
                        run_id=run_id,
                        task=task,
                        started_at=started_at,
                        finished_at=finished_at,
                        paths=paths,
                        response=response,
                        result_data=result_data,
                        final_verify=final_verify,
                        event_logs=event_logs,
                    )
                    save_json(full_info_path, full_exec_reference)
                    response["full_info_path"] = str(full_info_path)
                    response["decision_logs"] = self._build_decision_logs(event_logs)
                    response["report_payload"] = self.build_report_payload(task, response, autonomous=False)
                    response["chat_report"] = self.get_chat_report_message(task, response, autonomous=False)
                    self._emit(
                        callback,
                        {
                            "type": "exec_report",
                            "message": response["chat_report"],
                            "report_path": response["report_path"],
                            "report_payload": response["report_payload"],
                            "full_info_path": response["full_info_path"],
                        },
                    )
                    return response

                if state == STATE_FAILED:
                    if final_verify is None:
                        final_verify = self._build_failed_final_verify(failure_reason)
                    result_data = self._build_result_data(
                        run_id=run_id,
                        task=task,
                        plan_path=str(paths["plan"]),
                        plan_data=plan_data,
                        steps=steps,
                        step_attempts=step_attempts,
                        step_outcomes=step_outcomes,
                        state_history=state_history,
                        final_state=state,
                    )
                    save_json(paths["result"], result_data)
                    save_json(paths["verify"], final_verify)
                    response = self._build_final_response(
                        task=task,
                        run_id=run_id,
                        paths=paths,
                        plan_data=plan_data,
                        steps=steps,
                        result_data=result_data,
                        final_verify=final_verify,
                    )
                    response["decision_logs"] = self._build_decision_logs(event_logs)
                    self._emit(
                        callback,
                        {
                            "type": "exec_verify",
                            "message": final_verify.get("reason", ""),
                            "verify": final_verify,
                            "verify_path": str(paths["verify"]),
                        },
                    )
                    self._emit(
                        callback,
                        {
                            "type": "exec_report",
                            "message": response["chat_report"],
                            "report_path": response["report_path"],
                            "report_payload": response["report_payload"],
                        },
                    )
                    return response
        finally:
            self.executor.finish_run_context(emit=lambda text: self._emit_phase(callback, text, state="SANDBOX"))
