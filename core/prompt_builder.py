import json

from core.constants import ANSI_DIM, ANSI_RESET
from core.file_utils import sanitize_username


def style_reasoning_text(text: str, use_dim: bool) -> str:
    """为终端中的思考内容附加弱化样式。"""
    if not use_dim:
        return text
    return f"{ANSI_DIM}{text}{ANSI_RESET}"


def build_memory_context(records) -> str:
    """将全部历史记忆拼接为一段可直接送给模型的文本。"""
    if not records:
        return "暂无历史会话记忆。"

    lines = []
    for idx, record in enumerate(records, start=1):
        title = str(record.get("summary_title", "")).strip()
        msg = str(record.get("msg", "")).strip() or "无摘要"
        time_text = str(record.get("time", "")).strip() or "未知时间"
        user = str(record.get("user", "")).strip() or "未知用户"
        title_text = f"；标题：{title}" if title else ""
        lines.append(f"{idx}. 用户：{user}；时间：{time_text}{title_text}；摘要：{msg}")
    return "\n".join(lines)


def build_history_context(sessions) -> str:
    """把完整历史 session 整理成便于模型复用的文本。"""
    if not sessions:
        return "暂无近期完整历史会话。"

    lines = []
    for idx, session in enumerate(sessions, start=1):
        title = str(session.get("summary_title", "")).strip() or str(session.get("title", "")).strip()
        start_time = str(session.get("start_time", "")).strip() or "未知开始时间"
        end_time = str(session.get("end_time", "")).strip() or "进行中"
        title_text = f"；标题：{title}" if title else ""
        lines.append(f"### 近期会话 {idx}")
        lines.append(f"用户：{session.get('user', '未知用户')}；时间：{start_time} ~ {end_time}{title_text}")
        lines.append(format_history(session.get("history", [])))
        lines.append("")
    return "\n".join(lines).strip()


def build_mixed_session_context(recent_history_sessions, summary_records) -> str:
    """同时拼接近期完整 history 与较早摘要 memory。"""
    sections = []
    if recent_history_sessions:
        sections.append(
            "【近期开启完整上下文的历史会话】\n"
            f"{build_history_context(recent_history_sessions)}"
        )
    if summary_records:
        sections.append(
            "【较早历史会话摘要】\n"
            f"{build_memory_context(summary_records)}"
        )
    if not sections:
        return "暂无可复用历史会话记忆。"
    return "\n\n".join(sections)


def format_history(history) -> str:
    """把当前会话消息列表整理成便于模型理解的文本。"""
    if not history:
        return "当前会话暂无历史消息。"

    lines = []
    for idx, item in enumerate(history, start=1):
        role = "用户" if item.get("role") == "user" else "助手"
        content = str(item.get("content", "")).strip()
        lines.append(f"{idx}. {role}：{content}")
    return "\n".join(lines)


def build_chat_prompt(memory_context: str, history, user_input: str) -> str:
    """拼接历史记忆、当前会话上下文和本轮输入，形成主模型提示词。"""
    history_with_current = list(history) + [{"role": "user", "content": user_input}]
    return (
        "请基于以下信息继续与用户进行连贯对话。\n"
        "需要优先参考历史会话记忆，并结合当前会话上下文回答。\n\n"
        f"【历史会话记忆】\n{memory_context}\n\n"
        f"【当前会话上下文】\n{format_history(history_with_current)}\n\n"
        f"【当前用户输入】\n{user_input}"
    )


def build_summary_prompt(user: str, history) -> str:
    """构造摘要模型提示词，用于在结束会话时写入记忆。"""
    return (
        "请将以下会话整理为结构化摘要，便于下次恢复会话时继续使用。\n"
        "你必须只输出 JSON，不要输出 Markdown，不要输出任何解释文字。\n"
        '固定输出格式：{"summary":"","summary_title":""}\n'
        "要求：\n"
        "1. summary：摘要主体内容，保留用户目标、关键问题、重要结论、待办事项。\n"
        "2. summary_title：10 个字以内的中文短标题，用于 session 列表展示。\n"
        "3. summary_title 必须简洁、可读、可区分，不要使用标点堆砌。\n"
        "4. 不要遗漏重要数值，尤其不要写错数据指标。\n\n"
        "对于数据指标，你需要格外确定数值是否记录正确，千万不能记录错误数值。\n\n"
        f"用户名：{user}\n"
        f"会话内容：\n{format_history(history)}"
    )


def sanitize_time_for_filename(time_text: str) -> str:
    """将时间字符串转换为可用作文件名的安全格式。"""
    return time_text.replace(":", "-").replace(" ", "_")


def build_archive_filename(user: str, start_time: str, end_time: str) -> str:
    """按 {{user}}{{time}}.json 规则生成记忆文件名。"""
    safe_user = sanitize_username(user)
    safe_time = f"{sanitize_time_for_filename(start_time)}__{sanitize_time_for_filename(end_time)}"
    return f"{safe_user}{safe_time}.json"


def extract_json_object(text: str):
    """从模型返回文本中尽量提取第一个合法 JSON 对象。"""
    if not isinstance(text, str):
        raise ValueError("模型返回结果不是字符串，无法解析 JSON。")

    start = text.find("{")
    if start == -1:
        raise ValueError("模型返回中未找到 JSON 对象。")

    for end in range(len(text), start, -1):
        snippet = text[start:end].strip()
        if not snippet.endswith("}"):
            continue
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            continue

    raise ValueError("模型返回中的 JSON 对象解析失败。")
