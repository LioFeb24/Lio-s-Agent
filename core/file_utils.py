import json
import re
from datetime import datetime
from pathlib import Path

from core.constants import (
    EXEC_FULL_INFO_DIR,
    EXEC_PLAN_DIR,
    EXEC_RESULT_DIR,
    EXEC_SCRIPT_DIR,
    MEMORY_DIR,
    SESSION_DIR,
    SKILLS_DIR,
    TOOLS_DIR,
)


def now_text() -> str:
    """返回统一格式的当前时间字符串。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_json(path: Path, default):
    """读取 JSON，按常见中文 Windows 场景兼容多种编码。"""
    if not path.exists():
        return default

    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            with open(path, "r", encoding=enc) as f:
                return json.load(f)
        except UnicodeDecodeError as exc:
            last_err = exc

    if last_err is not None:
        raise last_err
    return default


def save_json(path: Path, data):
    """统一以 UTF-8 写入 JSON，便于后续跨平台读取。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def ensure_dirs() -> None:
    """确保运行过程中需要的目录都已存在。"""
    MEMORY_DIR.mkdir(exist_ok=True)
    SESSION_DIR.mkdir(exist_ok=True)
    SKILLS_DIR.mkdir(exist_ok=True)
    TOOLS_DIR.mkdir(exist_ok=True)
    EXEC_PLAN_DIR.mkdir(parents=True, exist_ok=True)
    EXEC_SCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    EXEC_RESULT_DIR.mkdir(parents=True, exist_ok=True)
    EXEC_FULL_INFO_DIR.mkdir(parents=True, exist_ok=True)


def sanitize_username(user: str) -> str:
    """将用户名转换为安全文件名，避免 Windows 非法字符。"""
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", user.strip())
    return safe_name or "default_user"


def sanitize_name(value: str) -> str:
    """将一般字符串转换为安全文件名片段。"""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip())
    return safe.strip("_") or "item"
