import fnmatch
import importlib
import json
from pathlib import Path, PurePosixPath
from typing import Callable


class CubeSandboxDisabled:
    """空对象实现，便于执行器在未启用沙箱时保持同一调用面。"""

    enabled = False

    def prepare_run(self, run_id: str, emit: Callable[[str], None] | None = None) -> None:
        return None

    def finish_run(self, emit: Callable[[str], None] | None = None) -> None:
        return None

    def get_runtime_summary(self) -> dict:
        return {
            "enabled": False,
            "provider": "local",
            "backend": "host",
            "sandbox_id": "",
            "workspace": "",
            "sync_enabled": False,
        }


class CubeSandboxAdapter:
    """基于 E2B SDK 兼容接口接入 CubeSandbox。"""

    def __init__(self, config: dict, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", False))
        self.provider = str(self.config.get("provider", "cubesandbox")).strip() or "cubesandbox"
        self.backend = str(self.config.get("backend", "e2b")).strip() or "e2b"
        self.template = str(self.config.get("template", "")).strip() or None
        self.timeout = int(self.config.get("timeout_seconds", 600) or 600)
        self.command_timeout = int(self.config.get("command_timeout_seconds", 120) or 120)
        self.workspace_root = self._normalize_remote_dir(self.config.get("workspace_root", "/workspace"))
        self.sync_project_on_start = bool(self.config.get("sync_project_on_start", True))
        self.sync_back_to_host = bool(self.config.get("sync_back_to_host", False))
        self.kill_after_run = bool(self.config.get("kill_after_run", True))
        self.allow_external_paths = bool(self.config.get("allow_external_paths", False))
        self.max_sync_files = max(1, int(self.config.get("max_sync_files", 200) or 200))
        self.max_file_size_kb = max(1, int(self.config.get("max_file_size_kb", 256) or 256))
        self.sync_include = list(self.config.get("sync_include", ["*.py", "*.json", "*.md", "*.txt"]))
        self.sync_ignore = list(
            self.config.get(
                "sync_ignore",
                ["env/**", ".git/**", "__pycache__/**", "EXEC/**", "MEMORY/**", "session_state/**", "*.pyc"],
            )
        )
        self.envs = dict(self.config.get("envs", {}) or {})
        self.sandbox = None
        self.sandbox_id = ""
        self.run_id = ""
        self.workspace_dir = ""
        self.synced_files = []
        self.modified_remote_paths = set()

    def prepare_run(self, run_id: str, emit: Callable[[str], None] | None = None) -> None:
        """创建并准备沙箱。"""
        if not self.enabled:
            return

        Sandbox = self._import_sandbox_class()
        self.run_id = str(run_id).strip()
        self.workspace_dir = f"{self.workspace_root}/{self.run_id}"
        self.synced_files = []
        self.modified_remote_paths = set()

        if emit:
            emit("正在创建 CubeSandbox 沙箱环境...")
        self.sandbox = Sandbox(
            template=self.template,
            timeout=self.timeout,
            metadata={"project": "prompt", "run_id": self.run_id, "provider": self.provider},
            envs=self.envs or None,
            api_key=self._get_optional("api_key"),
            domain=self._get_optional("domain"),
            debug=bool(self.config.get("debug", False)),
        )
        self.sandbox_id = str(getattr(self.sandbox, "sandbox_id", "") or "")
        self.sandbox.files.make_dir(self.workspace_dir)
        if emit:
            emit(f"CubeSandbox 已创建，sandbox_id={self.sandbox_id or 'unknown'}")

        if self.sync_project_on_start:
            if emit:
                emit("正在把当前项目快照同步到沙箱工作目录...")
            synced_count = self._sync_project_snapshot()
            if emit:
                emit(f"项目快照同步完成，共 {synced_count} 个文件。")

    def finish_run(self, emit: Callable[[str], None] | None = None) -> None:
        """根据配置决定是否销毁沙箱。"""
        if not self.enabled or self.sandbox is None:
            return
        if self.kill_after_run:
            if emit:
                emit("正在销毁 CubeSandbox 沙箱环境...")
            try:
                self.sandbox.kill()
            finally:
                self.sandbox = None
        if emit:
            emit("CubeSandbox 流程结束。")

    def get_runtime_summary(self) -> dict:
        """返回当前沙箱运行摘要。"""
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "backend": self.backend,
            "sandbox_id": self.sandbox_id,
            "workspace": self.workspace_dir,
            "sync_enabled": self.sync_project_on_start,
            "sync_back_to_host": self.sync_back_to_host,
            "synced_files": list(self.synced_files),
            "modified_remote_paths": sorted(self.modified_remote_paths),
        }

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
        }
        return aliases.get(text, text)

    def _normalize_tool_args(self, name: str, args) -> dict:
        data = dict(args or {}) if isinstance(args, dict) else {}
        if name == "shell":
            return {
                "command": str(data.get("command") or data.get("cmd") or data.get("script") or data.get("text") or "").strip()
            }
        if name == "list_dir":
            return {
                "path": str(
                    data.get("path") or data.get("target_directory") or data.get("directory") or data.get("dir") or "."
                ).strip()
                or ".",
                "depth": self._to_int(data.get("depth", 1), default=1, minimum=1),
                "offset": self._to_int(data.get("offset", 0), default=0, minimum=0),
                "limit": self._to_int(data.get("limit", 200), default=200, minimum=1),
            }
        if name == "read_text":
            return {
                "path": str(data.get("path") or data.get("file_path") or data.get("target_file") or data.get("file") or "").strip()
            }
        if name == "path_exists":
            return {
                "path": str(
                    data.get("path") or data.get("file_path") or data.get("target_path") or data.get("target") or ""
                ).strip()
            }
        if name == "glob":
            return {
                "path": str(
                    data.get("path")
                    or data.get("target_directory")
                    or data.get("directory")
                    or data.get("base_path")
                    or "."
                ).strip()
                or ".",
                "pattern": str(data.get("pattern") or data.get("glob") or data.get("match") or "*").strip() or "*",
            }
        return data

    def normalize_tool_call(self, name: str, args) -> tuple[str, dict]:
        normalized_name = self._normalize_tool_name(name)
        normalized_args = self._normalize_tool_args(normalized_name, args)
        return normalized_name, normalized_args

    def run_shell(self, command: str):
        """在沙箱中执行 shell 命令。"""
        sandbox = self._require_sandbox()
        result = sandbox.commands.run(
            command,
            cwd=self.workspace_dir,
            envs=self.envs or None,
            timeout=self.command_timeout,
        )
        return self._to_completed_process(result)

    def run_python(self, remote_script_name: str, content: str):
        """把脚本上传到沙箱后执行。"""
        sandbox = self._require_sandbox()
        remote_path = self._join_remote(self.workspace_dir, remote_script_name)
        sandbox.files.write(remote_path, content)
        self.modified_remote_paths.add(remote_path)
        result = sandbox.commands.run(
            f'python "{remote_path}"',
            cwd=self.workspace_dir,
            envs=self.envs or None,
            timeout=self.command_timeout,
        )
        return self._to_completed_process(result)

    def run_file_step(self, action_spec: dict, script_content: str):
        """在沙箱文件系统中执行文件读写操作。"""
        sandbox = self._require_sandbox()
        action = str(action_spec.get("action", "")).strip().lower()
        remote_path = self._map_host_path_to_remote(action_spec.get("path", ""))

        if action == "read":
            text = sandbox.files.read(remote_path)
            return self._build_completed(0, stdout=text)

        if action == "write":
            sandbox.files.write(remote_path, script_content)
            self.modified_remote_paths.add(remote_path)
            return self._build_completed(0, stdout=f"已在沙箱写入文件：{remote_path}")

        if action == "append":
            current = ""
            if sandbox.files.exists(remote_path):
                current = sandbox.files.read(remote_path)
            sandbox.files.write(remote_path, f"{current}{script_content}")
            self.modified_remote_paths.add(remote_path)
            return self._build_completed(0, stdout=f"已在沙箱追加文件：{remote_path}")

        if action == "replace":
            old = str(action_spec.get("old", ""))
            new = str(action_spec.get("new", ""))
            if not sandbox.files.exists(remote_path):
                raise FileNotFoundError(f"沙箱文件不存在：{remote_path}")
            text = sandbox.files.read(remote_path)
            if old not in text:
                raise ValueError("replace 失败：未找到 old 内容。")
            sandbox.files.write(remote_path, text.replace(old, new))
            self.modified_remote_paths.add(remote_path)
            return self._build_completed(0, stdout=f"已在沙箱修改文件：{remote_path}")

        if action == "delete":
            if sandbox.files.exists(remote_path):
                sandbox.files.remove(remote_path)
            self.modified_remote_paths.add(remote_path)
            return self._build_completed(0, stdout=f"已在沙箱删除：{remote_path}")

        if action == "mkdir":
            sandbox.files.make_dir(remote_path)
            self.modified_remote_paths.add(remote_path)
            return self._build_completed(0, stdout=f"已在沙箱创建目录：{remote_path}")

        if action == "list":
            entries = sandbox.files.list(remote_path)
            names = []
            for item in entries:
                name = getattr(item, "name", None)
                if name is None and isinstance(item, dict):
                    name = item.get("name")
                names.append(str(name or item))
            return self._build_completed(0, stdout="\n".join(names))

        raise ValueError(f"不支持的 file.action：{action}")

    def run_tool_step(self, tool_name: str, args: dict):
        """在沙箱上下文中执行基础文件系统工具。"""
        raw_name = str(tool_name or "").strip()
        name, args = self.normalize_tool_call(raw_name, args)
        if name == "shell":
            command = str(args.get("command", "")).strip()
            if not command:
                raise ValueError("tool.args.command 不能为空。")
            return self.run_shell(command)
        if name == "list_dir":
            remote_path = self._map_host_path_to_remote(args.get("path", "."))
            output = self._run_remote_list_dir(
                remote_path,
                depth=self._to_int(args.get("depth", 1), default=1, minimum=1),
                offset=self._to_int(args.get("offset", 0), default=0, minimum=0),
                limit=self._to_int(args.get("limit", 200), default=200, minimum=1),
            )
            return self._build_completed(0, stdout=output)

        if name == "read_text":
            remote_path = self._map_host_path_to_remote(args.get("path", ""))
            return self._build_completed(0, stdout=self._require_sandbox().files.read(remote_path))

        if name == "path_exists":
            remote_path = self._map_host_path_to_remote(args.get("path", ""))
            exists = self._require_sandbox().files.exists(remote_path)
            return self._build_completed(0, stdout="true" if exists else "false")

        if name == "glob":
            base_path = self._map_host_path_to_remote(args.get("path", "."))
            pattern = str(args.get("pattern", "*")).strip() or "*"
            output = self._run_remote_glob(base_path, pattern)
            return self._build_completed(0, stdout=output)

        supported = "shell、list_dir、read_text、path_exists、glob"
        raise ValueError(f"沙箱未注册的工具：{raw_name or name}。当前支持：{supported}")

    def _run_remote_list_dir(self, remote_base: str, depth: int, offset: int, limit: int) -> str:
        """通过 Python 一次性在沙箱中完成带分页和层级的目录列举。"""
        script = (
            "from pathlib import Path\n"
            f"base = Path({json.dumps(remote_base)})\n"
            f"depth = int({json.dumps(depth)})\n"
            f"offset = int({json.dumps(offset)})\n"
            f"limit = int({json.dumps(limit)})\n"
            "items = []\n"
            "for path in sorted(base.rglob('*')):\n"
            "    rel = path.relative_to(base)\n"
            "    if len(rel.parts) > depth:\n"
            "        continue\n"
            "    text = rel.as_posix() + ('/' if path.is_dir() else '')\n"
            "    items.append(text)\n"
            "print('\\n'.join(items[offset:offset + limit]))\n"
        )
        remote_script_name = f"{self.run_id}_list_dir_helper.py"
        remote_path = self._join_remote(self.workspace_dir, remote_script_name)
        self._require_sandbox().files.write(remote_path, script)
        result = self._require_sandbox().commands.run(
            f'python "{remote_path}"',
            cwd=self.workspace_dir,
            envs=self.envs or None,
            timeout=self.command_timeout,
        )
        completed = self._to_completed_process(result)
        return completed.stdout

    def _run_remote_glob(self, remote_base: str, pattern: str) -> str:
        """通过 Python 一次性在沙箱中完成 glob。"""
        script = (
            "from pathlib import Path\n"
            f"base = Path({json.dumps(remote_base)})\n"
            f"pattern = {json.dumps(pattern)}\n"
            "matches = sorted(str(p) for p in base.glob(pattern))\n"
            "print('\\n'.join(matches))\n"
        )
        remote_script_name = f"{self.run_id}_glob_helper.py"
        remote_path = self._join_remote(self.workspace_dir, remote_script_name)
        self._require_sandbox().files.write(remote_path, script)
        result = self._require_sandbox().commands.run(
            f'python "{remote_path}"',
            cwd=self.workspace_dir,
            envs=self.envs or None,
            timeout=self.command_timeout,
        )
        completed = self._to_completed_process(result)
        return completed.stdout

    def _sync_project_snapshot(self) -> int:
        """按配置把项目快照同步到沙箱。"""
        sandbox = self._require_sandbox()
        synced = 0
        for local_path in sorted(self.base_dir.rglob("*")):
            if not local_path.is_file():
                continue
            relative_posix = local_path.relative_to(self.base_dir).as_posix()
            if self._should_skip_sync_file(relative_posix, local_path):
                continue

            text = self._read_text_file(local_path)
            remote_path = self._join_remote(self.workspace_dir, relative_posix)
            sandbox.files.write(remote_path, text)
            self.synced_files.append(relative_posix)
            synced += 1
            if synced >= self.max_sync_files:
                break
        return synced

    def _should_skip_sync_file(self, relative_posix: str, path: Path) -> bool:
        if any(fnmatch.fnmatch(relative_posix, pattern) for pattern in self.sync_ignore):
            return True
        if self.sync_include and not any(fnmatch.fnmatch(relative_posix, pattern) for pattern in self.sync_include):
            return True
        try:
            size_kb = path.stat().st_size / 1024
        except OSError:
            return True
        return size_kb > self.max_file_size_kb

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    def _map_host_path_to_remote(self, path_text: str) -> str:
        """把宿主机路径映射到沙箱工作目录。"""
        raw = str(path_text or "").strip()
        if not raw:
            raise ValueError("缺少 path。")

        host_path = Path(raw)
        if not host_path.is_absolute():
            host_path = (self.base_dir / host_path).resolve()
        else:
            host_path = host_path.resolve()

        try:
            relative = host_path.relative_to(self.base_dir).as_posix()
            return self._join_remote(self.workspace_dir, relative)
        except ValueError:
            if not self.allow_external_paths:
                raise ValueError(f"沙箱模式下禁止访问项目目录之外的路径：{host_path}")
            safe_drive = host_path.drive.replace(":", "").lower() or "drive"
            relative_external = Path(*host_path.parts[1:]).as_posix()
            return self._join_remote(self.workspace_dir, "_external", safe_drive, relative_external)

    def _normalize_remote_dir(self, path_text: str) -> str:
        path = PurePosixPath(str(path_text or "/workspace").strip() or "/workspace")
        return str(path)

    def _join_remote(self, *parts: str) -> str:
        current = PurePosixPath("/")
        for part in parts:
            text = str(part or "").strip()
            if not text:
                continue
            candidate = PurePosixPath(text)
            current = candidate if candidate.is_absolute() else current / candidate
        return str(current)

    def _get_optional(self, key: str):
        value = self.config.get(key)
        text = str(value).strip() if value is not None else ""
        return text or None

    def _require_sandbox(self):
        if self.sandbox is None:
            raise RuntimeError("CubeSandbox 尚未初始化。")
        return self.sandbox

    def _import_sandbox_class(self):
        try:
            module = importlib.import_module("e2b")
        except ImportError as exc:
            raise RuntimeError(
                "已启用 CubeSandbox，但当前环境未安装 `e2b` Python SDK。"
                "请先安装 `e2b`，并在 config.json 中配置 sandbox.domain / sandbox.api_key。"
            ) from exc
        Sandbox = getattr(module, "Sandbox", None)
        if Sandbox is None:
            raise RuntimeError("当前 `e2b` SDK 不包含 `Sandbox` 类，无法连接 CubeSandbox。")
        return Sandbox

    def _build_completed(self, returncode: int, stdout="", stderr=""):
        from subprocess import CompletedProcess

        return CompletedProcess(args=[], returncode=returncode, stdout=str(stdout), stderr=str(stderr))

    def _to_completed_process(self, result):
        returncode = getattr(result, "exit_code", None)
        if returncode is None:
            returncode = getattr(result, "returncode", None)
        if returncode is None:
            returncode = getattr(result, "code", 0)
        stdout = getattr(result, "stdout", "")
        stderr = getattr(result, "stderr", "")
        return self._build_completed(int(returncode), stdout=stdout, stderr=stderr)
