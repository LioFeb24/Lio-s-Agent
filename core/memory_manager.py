import math

from core.constants import MEMORY_DIR, SESSION_DIR
from core.file_utils import load_json
from core.prompt_builder import build_mixed_session_context
from core.session_manager import normalize_session_record


RECENT_HISTORY_RATIO = 0.3


class MemoryManager:
    """负责历史记忆的读取、拼接与上下文生成。"""

    def __init__(self, user: str) -> None:
        self.user = str(user).strip()

    def load_records(self):
        """读取当前用户全部摘要记忆记录。"""
        records = []
        for path in sorted(MEMORY_DIR.glob("*.json")):
            data = load_json(path, None)
            if isinstance(data, dict) and str(data.get("user", "")).strip() == self.user:
                records.append(data)
        return records

    def load_sessions(self):
        """读取当前用户全部完整 session。"""
        records = []
        for path in sorted(SESSION_DIR.glob("*.json")):
            if path.name.endswith("_current.json") or path.name.endswith("_active.json"):
                continue
            data = load_json(path, None)
            if not isinstance(data, dict):
                continue
            if str(data.get("user", "")).strip() != self.user:
                continue
            session_id = str(data.get("session_id", "")).strip()
            if not session_id:
                continue
            records.append(normalize_session_record(self.user, session_id, data))
        records.sort(key=lambda item: item.get("start_time", ""), reverse=True)
        return records

    def _build_summary_record_from_session(self, session):
        """当 memory 文件缺失时，使用 session 数据回退生成摘要视图。"""
        start_time = str(session.get("start_time", "")).strip() or "未知开始时间"
        end_time = str(session.get("end_time", "")).strip() or "进行中"
        title = str(session.get("summary_title", "")).strip() or str(session.get("title", "")).strip()
        history = session.get("history", [])
        if history:
            pieces = []
            for item in history[-4:]:
                role = "用户" if item.get("role") == "user" else "助手"
                content = str(item.get("content", "")).strip().replace("\n", " ")
                if content:
                    pieces.append(f"{role}：{content[:120]}")
            msg = "；".join(pieces) or "该会话暂无可用摘要。"
        else:
            msg = "该会话暂无有效消息。"
        return {
            "msg": msg,
            "summary_title": title,
            "time": f"{start_time} ~ {end_time}",
            "user": self.user,
            "session_id": session.get("session_id", ""),
        }

    def _load_summary_record(self, session):
        """优先读取 session 对应的 memory 文件，缺失时回退到 session 自身。"""
        memory_file = str(session.get("memory_file", "")).strip()
        if memory_file:
            data = load_json(MEMORY_DIR / memory_file, None)
            if isinstance(data, dict):
                return data
        return self._build_summary_record_from_session(session)

    def _split_sessions(self, sessions):
        """按近 30% 完整 history、其余摘要进行拆分。"""
        if not sessions:
            return [], []
        history_count = max(1, math.ceil(len(sessions) * RECENT_HISTORY_RATIO))
        history_count = min(history_count, len(sessions))
        return sessions[:history_count], sessions[history_count:]

    def build_context(self, current_session_id: str = "") -> str:
        """生成混合式历史上下文：近 30% 读完整 history，其余读摘要。"""
        sessions = [
            session
            for session in self.load_sessions()
            if session.get("session_id") != str(current_session_id).strip()
        ]
        recent_history_sessions, summary_sessions = self._split_sessions(sessions)
        summary_records = [self._load_summary_record(session) for session in summary_sessions]
        return build_mixed_session_context(recent_history_sessions, summary_records)
