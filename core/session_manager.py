import copy
import threading
from uuid import uuid4

from core.constants import EXEC_PLAN_DIR, EXEC_RESULT_DIR, EXEC_SCRIPT_DIR, MEMORY_DIR, SESSION_DIR
from core.file_utils import ensure_dirs, load_json, now_text, sanitize_username, save_json
from core.format_llm_output import call_llm_json
from core.prompt_builder import build_summary_prompt


def get_session_path(user: str):
    """兼容旧接口，返回当前会话指针文件路径。"""
    return get_current_pointer_path(user)


def get_current_pointer_path(user: str):
    """记录当前选中 session_id 的指针文件。"""
    return SESSION_DIR / f"{sanitize_username(user)}_current.json"


def get_legacy_active_path(user: str):
    """兼容旧版单活动会话文件。"""
    return SESSION_DIR / f"{sanitize_username(user)}_active.json"


def build_session_id() -> str:
    """生成稳定且足够短的会话 ID。"""
    return f"{now_text().replace('-', '').replace(':', '').replace(' ', '_')}_{uuid4().hex[:8]}"


def get_session_file_path(user: str, session_id: str):
    """根据用户和 session_id 定位会话文件。"""
    return SESSION_DIR / f"{sanitize_username(user)}_{session_id}.json"


def build_session_memory_filename(user: str, session_id: str):
    """为每个 session 生成稳定的摘要文件名。"""
    return f"{sanitize_username(user)}_{session_id}_memory.json"


def normalize_history(history):
    """清洗会话历史，只保留路由与摘要所需的 role / content。"""
    normalized = []
    for item in history or []:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant", "system"} and isinstance(content, str):
            normalized.append({"role": role, "content": content})
    return normalized


def normalize_session_record(user: str, session_id: str, session):
    """补齐 session 必要字段，确保 GUI/CLI 可共享同一数据结构。"""
    data = dict(session or {})
    start_time = str(data.get("start_time", "")).strip() or now_text()
    summary_title = str(data.get("summary_title", "")).strip()
    data["session_id"] = str(data.get("session_id", "")).strip() or session_id
    data["user"] = str(data.get("user", "")).strip() or user
    data["title"] = str(data.get("title", "")).strip() or summary_title or f"会话 {start_time}"
    data["summary_title"] = summary_title
    data["start_time"] = start_time
    data["end_time"] = str(data.get("end_time", "")).strip()
    data["archived"] = bool(data.get("archived", False))
    data["memory_file"] = str(data.get("memory_file", "")).strip()
    data["history"] = normalize_history(data.get("history", []))
    return data


def save_session(session_path, session):
    """将完整 session 写入磁盘。"""
    save_json(session_path, session)


def save_current_pointer(user: str, session_id: str):
    """保存当前选中的 session_id。"""
    save_json(
        get_current_pointer_path(user),
        {"user": user, "current_session_id": session_id},
    )


def create_session(user: str):
    """创建一个新的空白会话，并立即设为当前会话。"""
    ensure_dirs()
    session_id = build_session_id()
    session_path = get_session_file_path(user, session_id)
    session = normalize_session_record(
        user,
        session_id,
        {
            "title": f"会话 {now_text()}",
            "start_time": now_text(),
            "history": [],
        },
    )
    save_session(session_path, session)
    save_current_pointer(user, session_id)
    return session_path, session


def migrate_legacy_active_session(user: str):
    """把旧版 _active.json 迁移为新版 session 文件。"""
    legacy_path = get_legacy_active_path(user)
    if not legacy_path.exists():
        return None

    legacy_data = load_json(legacy_path, None)
    if not isinstance(legacy_data, dict):
        legacy_path.unlink(missing_ok=True)
        return None

    session_id = build_session_id()
    session_path = get_session_file_path(user, session_id)
    session = normalize_session_record(
        user,
        session_id,
        {
            "title": f"会话 {legacy_data.get('start_time', now_text())}",
            "start_time": legacy_data.get("start_time", now_text()),
            "history": legacy_data.get("history", []),
        },
    )
    save_session(session_path, session)
    save_current_pointer(user, session_id)
    legacy_path.unlink(missing_ok=True)
    return session_path, session


def load_session_by_id(user: str, session_id: str):
    """按 session_id 读取完整会话。"""
    session_path = get_session_file_path(user, session_id)
    data = load_json(session_path, None)
    if not isinstance(data, dict):
        raise ValueError(f"未找到会话：{session_id}")
    session = normalize_session_record(user, session_id, data)
    save_session(session_path, session)
    return session_path, session


def list_sessions(user: str):
    """列出当前用户全部可恢复 session。"""
    ensure_dirs()
    safe_user = sanitize_username(user)
    items = []
    for path in sorted(SESSION_DIR.glob(f"{safe_user}_*.json")):
        if path.name in {f"{safe_user}_current.json", f"{safe_user}_active.json"}:
            continue
        data = load_json(path, None)
        if not isinstance(data, dict):
            continue
        session_id = str(data.get("session_id", "")).strip()
        if not session_id:
            session_id = path.stem[len(f"{safe_user}_") :]
        session = normalize_session_record(user, session_id, data)
        save_session(path, session)
        items.append(
            {
                "session_id": session["session_id"],
                "title": session["title"],
                "summary_title": session.get("summary_title", ""),
                "start_time": session["start_time"],
                "end_time": session["end_time"],
                "archived": session["archived"],
                "history_count": len(session["history"]),
                "path": path,
            }
        )

    items.sort(key=lambda item: item["start_time"], reverse=True)
    return items


def load_or_create_session(user: str):
    """按当前指针恢复会话；若不存在则创建新会话。"""
    ensure_dirs()
    migrated = migrate_legacy_active_session(user)
    if migrated is not None:
        session_path, session = migrated
        return session_path, session, True

    pointer_data = load_json(get_current_pointer_path(user), {})
    current_session_id = str(pointer_data.get("current_session_id", "")).strip()
    if current_session_id:
        try:
            session_path, session = load_session_by_id(user, current_session_id)
            return session_path, session, True
        except ValueError:
            pass

    sessions = list_sessions(user)
    for item in sessions:
        if not item.get("archived"):
            session_path, session = load_session_by_id(user, item["session_id"])
            save_current_pointer(user, item["session_id"])
            return session_path, session, True

    session_path, session = create_session(user)
    return session_path, session, False


def build_fallback_summary(session):
    """当摘要模型不可用时，基于最近几条消息构造本地回退摘要。"""
    history = session.get("history", [])
    title = str(session.get("title", "")).strip()
    if not history:
        return "本次会话无有效消息。", title or "空白会话"

    pieces = []
    for item in history[-6:]:
        role = "用户" if item.get("role") == "user" else "助手"
        content = str(item.get("content", "")).strip().replace("\n", " ")
        if content:
            pieces.append(f"{role}：{content[:120]}")
    summary = "；".join(pieces) or "本次会话已保存，但暂未生成模型摘要。"
    summary_title = str(session.get("summary_title", "")).strip() or title or summary[:10]
    return summary, summary_title


def summarize_session(config, session):
    """基于完整 history 生成当前 session 的摘要。"""
    history = session.get("history", [])
    if history:
        try:
            summary_cfg = config.llm["summary"]
            summary_payload = call_llm_json(
                build_summary_prompt(session.get("user", ""), history),
                summary_cfg["model"],
                summary_cfg["key"],
            )
            summary = str(summary_payload.get("summary", "")).strip()
            summary_title = str(summary_payload.get("summary_title", "")).strip()
        except Exception:
            summary, summary_title = build_fallback_summary(session)
    else:
        summary = "本次会话无有效消息。"
        summary_title = "空白会话"

    if not summary:
        summary = "本次会话已保存，但摘要为空。"
    if not summary_title:
        summary_title = summary.replace("\n", " ").strip()[:10] or "会话摘要"
    summary_title = summary_title.replace("\n", " ").strip()[:10] or "会话摘要"
    return summary, summary_title


def sync_session_memory(config, session_path, session):
    """为 session 持续写入摘要 memory，保证每个会话同时拥有完整 history 与摘要。"""
    summary, summary_title = summarize_session(config, session)
    start_time = session.get("start_time", now_text())
    end_time = session.get("end_time", "")
    memory_file = str(session.get("memory_file", "")).strip() or build_session_memory_filename(
        session.get("user", ""),
        session.get("session_id", ""),
    )
    archive_data = {
        "msg": summary,
        "summary_title": summary_title,
        "time": f"{start_time} ~ {end_time or '进行中'}",
        "user": session.get("user", ""),
        "session_id": session.get("session_id", ""),
        "archived": bool(session.get("archived", False)),
    }
    save_json(MEMORY_DIR / memory_file, archive_data)
    session["memory_file"] = memory_file
    session["summary_title"] = summary_title
    if session.get("archived"):
        session["title"] = summary_title
    if session_path is not None:
        save_session(session_path, session)
    return archive_data


def clear_session_archive_state(session):
    """当已归档 session 被继续使用时，解除归档状态，但保留摘要文件。"""
    session["archived"] = False
    session["end_time"] = ""
    return session


def collect_user_record_files(user: str):
    """收集当前用户在各目录下的会话与记忆 JSON 文件。"""
    target_user = str(user).strip()
    if not target_user:
        return []

    matched = []
    seen = set()
    for directory in (MEMORY_DIR, SESSION_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            data = load_json(path, None)
            if not isinstance(data, dict):
                continue
            if str(data.get("user", "")).strip() != target_user:
                continue
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            matched.append(path)

    pointer_path = get_current_pointer_path(user)
    if pointer_path.exists():
        matched.append(pointer_path)
    return matched


def remove_user_records(user: str):
    """删除当前用户全部会话记录文件，并返回删除结果。"""
    record_files = collect_user_record_files(user)
    removed_count = 0
    for path in record_files:
        path.unlink(missing_ok=True)
        removed_count += 1

    safe_user = sanitize_username(user)
    for directory in (EXEC_PLAN_DIR, EXEC_SCRIPT_DIR, EXEC_RESULT_DIR):
        if not directory.exists():
            continue
        for path in sorted(directory.glob(f"{safe_user}_*")):
            path.unlink(missing_ok=True)
            removed_count += 1

    return removed_count, record_files


def remove_session_record(user: str, session_id: str):
    """删除单个 session 及其关联摘要文件。"""
    session_path, session = load_session_by_id(user, session_id)
    removed_files = []
    memory_names = []
    memory_file = str(session.get("memory_file", "")).strip()
    if memory_file:
        memory_names.append(memory_file)
    fallback_memory_file = build_session_memory_filename(user, session_id)
    if fallback_memory_file not in memory_names:
        memory_names.append(fallback_memory_file)

    for memory_name in memory_names:
        memory_path = MEMORY_DIR / memory_name
        if memory_path.exists():
            memory_path.unlink(missing_ok=True)
            removed_files.append(memory_path)

    if session_path.exists():
        session_path.unlink(missing_ok=True)
        removed_files.append(session_path)
    return session, removed_files


def archive_session(config, session_path, session):
    """结束当前会话并生成摘要，同时保留完整 history 供后续切换恢复。"""
    end_time = now_text()
    session["archived"] = True
    session["end_time"] = end_time
    archive_data = sync_session_memory(config, session_path, session)
    session["title"] = session.get("summary_title", "") or session.get("title", "")
    save_session(session_path, session)
    return archive_data


class SessionManager:
    """负责完整 session 生命周期管理，包括创建、切换、恢复、归档与删除。"""

    def __init__(self, user: str, config) -> None:
        self.user = user
        self.config = config
        self._lock = threading.RLock()
        self.session_path = None
        self.session = None
        self.restored = False

    def reload(self) -> None:
        """重新加载当前指针所指向的 session。"""
        with self._lock:
            self.session_path, self.session, self.restored = load_or_create_session(self.user)

    def get_current_session_id(self) -> str:
        """返回当前选中的 session_id。"""
        with self._lock:
            if isinstance(self.session, dict):
                return str(self.session.get("session_id", "")).strip()
            return ""

    def get_session(self, session_id: str | None = None) -> dict:
        """读取指定 session；未指定时返回当前选中的 session。"""
        with self._lock:
            target_id = str(session_id or "").strip()
            current_id = self.get_current_session_id()
            if not target_id or target_id == current_id:
                if self.session is None:
                    self.reload()
                return copy.deepcopy(self.session or {})
            _session_path, session = load_session_by_id(self.user, target_id)
            return copy.deepcopy(session)

    def get_session_history(self, session_id: str | None = None) -> list[dict]:
        """返回指定 session 的历史消息副本。"""
        session = self.get_session(session_id)
        return list(session.get("history", []))

    def save(self, session_id: str | None = None) -> None:
        """保存当前 session。"""
        with self._lock:
            target_id = str(session_id or "").strip()
            current_id = self.get_current_session_id()
            if not target_id or target_id == current_id:
                if self.session_path is not None and self.session is not None:
                    save_session(self.session_path, self.session)
                    save_current_pointer(self.user, self.session["session_id"])
                return
            session_path, session = load_session_by_id(self.user, target_id)
            save_session(session_path, session)

    def list_sessions(self):
        """列出当前用户全部 session。"""
        with self._lock:
            sessions = list_sessions(self.user)
            current_id = self.get_current_session_id()
            for item in sessions:
                item["is_current"] = item["session_id"] == current_id
            return sessions

    def switch_session(self, session_id: str):
        """切换到指定 session，并让后续对话直接基于该 history。"""
        with self._lock:
            self.session_path, self.session = load_session_by_id(self.user, session_id)
            self.restored = True
            save_current_pointer(self.user, session_id)
            return copy.deepcopy(self.session)

    def create_and_switch_new_session(self):
        """新建 session 并切换过去。"""
        with self._lock:
            self.session_path, self.session = create_session(self.user)
            self.restored = False
            return copy.deepcopy(self.session)

    def ensure_all_session_memories(self) -> None:
        """为已有 session 回补缺失的摘要文件。"""
        with self._lock:
            for item in list_sessions(self.user):
                session_path, session = load_session_by_id(self.user, item["session_id"])
                memory_file = str(session.get("memory_file", "")).strip()
                if memory_file and (MEMORY_DIR / memory_file).exists():
                    continue
                sync_session_memory(self.config, session_path, session)

    def append_history(
        self,
        user_input: str,
        reply: str,
        session_id: str | None = None,
        system_logs: list[str] | None = None,
    ) -> None:
        """将一轮问答写入当前 session；若原会话已归档，则自动恢复为可继续状态。"""
        with self._lock:
            target_id = str(session_id or "").strip()
            current_id = self.get_current_session_id()
            if not target_id or target_id == current_id:
                if self.session is None:
                    self.reload()
                target_path = self.session_path
                target_session = self.session
            else:
                target_path, target_session = load_session_by_id(self.user, target_id)

            if target_session.get("archived"):
                clear_session_archive_state(target_session)
            if not target_session.get("history") and user_input and not user_input.startswith("/"):
                preview = user_input.strip().replace("\n", " ")
                target_session["title"] = preview[:24] + ("..." if len(preview) > 24 else "")
            target_session["history"].append({"role": "user", "content": user_input})
            target_session["history"].append({"role": "assistant", "content": reply})
            for item in system_logs or []:
                text = str(item or "").strip()
                if text:
                    target_session["history"].append({"role": "system", "content": text})
            save_session(target_path, target_session)
            sync_session_memory(self.config, target_path, target_session)

            if not target_id or target_id == current_id:
                self.session_path = target_path
                self.session = target_session

    def end_current_session(self, auto_new_session: bool = True):
        """结束当前 session 并按需新建下一个 session。"""
        with self._lock:
            archive_data = archive_session(self.config, self.session_path, self.session)
            if auto_new_session:
                self.create_and_switch_new_session()
            return archive_data

    def prepare_end_current_session(self, auto_new_session: bool = True):
        """立即切换到新会话，并返回旧会话快照供后台归档。"""
        with self._lock:
            archive_context = {
                "session_path": self.session_path,
                "session": copy.deepcopy(self.session),
            }
            if auto_new_session:
                self.create_and_switch_new_session()
            return archive_context

    def remove_all_records(self, auto_new_session: bool = True):
        """删除当前用户全部 session/记忆记录。"""
        with self._lock:
            removed_count, removed_files = remove_user_records(self.user)
            if auto_new_session:
                self.create_and_switch_new_session()
            return removed_count, removed_files

    def remove_session(self, session_id: str, auto_select_fallback: bool = True):
        """删除指定 session，并在必要时切换到其他会话或新建会话。"""
        with self._lock:
            target_id = str(session_id).strip()
            if not target_id:
                raise ValueError("缺少要删除的 session_id。")

            current_id = self.get_current_session_id()
            available_ids = {item["session_id"] for item in list_sessions(self.user)}
            if target_id not in available_ids:
                raise ValueError(f"未找到会话：{target_id}")

            removed_session, removed_files = remove_session_record(self.user, target_id)
            switched = False
            created_new = False

            if current_id == target_id:
                remaining_sessions = list_sessions(self.user)
                if remaining_sessions:
                    next_session_id = remaining_sessions[0]["session_id"]
                    self.session_path, self.session = load_session_by_id(self.user, next_session_id)
                    self.restored = True
                    save_current_pointer(self.user, next_session_id)
                    switched = True
                elif auto_select_fallback:
                    self.session_path, self.session = create_session(self.user)
                    self.restored = False
                    switched = True
                    created_new = True
                else:
                    self.session_path = None
                    self.session = None
                    self.restored = False
            elif self.session is not None:
                save_current_pointer(self.user, current_id)

            current_session_id = self.get_current_session_id()
            return {
                "removed_session_id": target_id,
                "removed_title": removed_session.get("summary_title", "") or removed_session.get("title", "") or target_id,
                "removed_files": removed_files,
                "current_session_id": current_session_id,
                "switched": switched,
                "created_new": created_new,
            }
