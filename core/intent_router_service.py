import json
import re
from pathlib import Path

from core.format_llm_output import call_llm_json, extract_json_value
from core.skill_loader import SkillRepository
from core.tool_loader import ToolRepository


class IntentRouterService:
    """负责辅助 LLM 的 chat/exec/skill 决策与执行分流。"""

    def __init__(
        self,
        config,
        exec_service,
        skill_repository: SkillRepository | None = None,
        tool_repository: ToolRepository | None = None,
    ) -> None:
        self.config = config
        self.exec_service = exec_service
        self.skill_repository = skill_repository or SkillRepository()
        self.tool_repository = tool_repository or ToolRepository()

    def _to_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

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
        return None

    def _unwrap_autonomous_decision_mapping(self, value):
        return self._unwrap_mapping_by_keys(value, {"way"})

    def _normalize_autonomous_decision(self, value) -> dict:
        candidate = self._unwrap_autonomous_decision_mapping(value)
        if candidate is None:
            raise ValueError("未能在模型输出中找到自主执行决策结构。")
        way = self._to_text(candidate.get("way", "")).strip().lower()
        if way not in {"chat", "exec", "skill"}:
            way = "chat"
        skill_name = self._to_text(candidate.get("skill_name", "")).strip()
        if way != "skill":
            skill_name = ""
        return {
            "way": way,
            "skill_name": skill_name,
        }

    def _get_main_llm_config(self) -> dict:
        return self.config.llm["main_llm"]

    def _get_router_llm_config(self) -> dict:
        """读取辅助路由 LLM 配置，不存在时回退到 main_llm。"""
        llm_config = getattr(self.config, "llm", {}) or {}
        router_cfg = llm_config.get("intent_router") or llm_config.get("helper_llm") or llm_config.get("router_llm")
        if isinstance(router_cfg, dict):
            key = self._to_text(router_cfg.get("key", "")).strip()
            model = self._to_text(router_cfg.get("model", "")).strip()
            if key and model:
                return {
                    "key": key,
                    "model": model,
                    "stream": False,
                }
        main_cfg = self._get_main_llm_config()
        return {
            "key": main_cfg["key"],
            "model": main_cfg["model"],
            "stream": False,
        }

    def _get_router_recent_rounds(self) -> int:
        """读取辅助路由使用的近几轮对话数，默认 2 轮。"""
        llm_config = getattr(self.config, "llm", {}) or {}
        router_cfg = llm_config.get("intent_router") or llm_config.get("helper_llm") or llm_config.get("router_llm")
        default_rounds = 10
        if not isinstance(router_cfg, dict):
            return default_rounds
        try:
            rounds = int(router_cfg.get("recent_rounds", default_rounds))
        except (TypeError, ValueError):
            return default_rounds
        return max(1, rounds)

    def _load_skill_summaries(self) -> list[dict]:
        try:
            return self.skill_repository.list_skills()
        except Exception:
            return []

    def _build_router_skill_context(self) -> dict:
        skills = self._load_skill_summaries()
        if not skills:
            return {
                "skills": [],
                "skill_folders": [],
                "skill_text": "当前没有可用于路由决策的 skill。",
            }

        skill_rows = []
        skill_text_lines = ["当前可用 skills："]
        for item in skills:
            row = {
                "folder": item.get("folder", ""),
                "name": item.get("name", ""),
                "description": item.get("description", ""),
            }
            skill_rows.append(row)
            skill_text_lines.append(
                f"- {row['folder']}（{row['name'] or row['folder']}）：{row['description'] or '无描述'}"
            )
        return {
            "skills": skill_rows,
            "skill_folders": [item["folder"] for item in skill_rows if item.get("folder")],
            "skill_text": "\n".join(skill_text_lines),
        }

    def _load_tool_summaries(self) -> list[dict]:
        try:
            return self.tool_repository.list_tools()
        except Exception:
            return []

    def _build_router_tool_context(self) -> dict:
        tools = self._load_tool_summaries()
        if not tools:
            return {
                "tools": [],
                "tool_names": [],
                "tool_text": "当前没有可用于辅助决策的 tool。",
            }

        tool_rows = []
        tool_text_lines = ["当前可用 tools（仅供辅助判断是否更适合走 exec 路线）："]
        for item in tools:
            row = {
                "name": item.get("name", ""),
                "display_name": item.get("display_name", ""),
                "description": item.get("description", ""),
                "aliases": item.get("aliases", []),
            }
            tool_rows.append(row)
            alias_text = f"；别名：{', '.join(row['aliases'])}" if row["aliases"] else ""
            tool_text_lines.append(
                f"- {row['name']}（{row['display_name'] or row['name']}）：{row['description'] or '无描述'}{alias_text}"
            )
        return {
            "tools": tool_rows,
            "tool_names": [item["name"] for item in tool_rows if item.get("name")],
            "tool_text": "\n".join(tool_text_lines),
        }

    def _build_recent_rounds_for_routing(self, history, user_input: str) -> list[dict]:
        """整理近 N 轮对话，供辅助 LLM 做 chat/exec/skill 分流。"""
        rounds = []
        current_user = None
        for item in history or []:
            role = str(item.get("role", "")).strip()
            content = self._to_text(item.get("content", "")).strip()
            if not content:
                continue
            if role == "user":
                if current_user is not None:
                    rounds.append({"user": current_user, "assistant": ""})
                current_user = content
            elif role == "assistant":
                if current_user is None:
                    rounds.append({"user": "", "assistant": content})
                else:
                    rounds.append({"user": current_user, "assistant": content})
                    current_user = None
        if current_user is not None:
            rounds.append({"user": current_user, "assistant": ""})

        pending_input = self._to_text(user_input).strip()
        if pending_input:
            rounds.append({"user": pending_input, "assistant": "", "pending": True})
        recent_rounds = self._get_router_recent_rounds()
        return rounds[-recent_rounds:]

    def _build_recent_system_logs_for_routing(self, history, limit: int = 12) -> list[dict]:
        """提取最近 system 日志，帮助分流器理解上一轮 exec 的内部过程。"""
        logs = []
        for item in history or []:
            if str(item.get("role", "")).strip() != "system":
                continue
            content = self._to_text(item.get("content", "")).strip()
            if not content:
                continue
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            summary = lines[0] if lines else content
            logs.append(
                {
                    "summary": summary[:240],
                    "content": content[:1200],
                }
            )
        return logs[-limit:]

    def _extract_latest_assistant_message(self, history) -> str:
        for item in reversed(history or []):
            if str(item.get("role", "")).strip() != "assistant":
                continue
            content = self._to_text(item.get("content", "")).strip()
            if content:
                return content
        return ""

    def _extract_latest_assistant_payload(self, history) -> dict:
        content = self._extract_latest_assistant_message(history)
        if not content:
            return {}
        try:
            payload = extract_json_value(content)
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass

        fallback = {}
        patterns = {
            "output_file": r'"output_file"\s*:\s*"([^"\r\n]+)"',
            "keyword": r'"keyword"\s*:\s*"([^"\r\n]+)"',
            "tool_name": r'"tool_name"\s*:\s*"([^"\r\n]+)"',
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                fallback[key] = match.group(1).strip()
        return fallback

    def _extract_windows_path(self, text: str) -> str:
        raw = self._to_text(text).strip()
        if not raw:
            return ""
        match = re.search(r"[A-Za-z]:\\[^\r\n\t\"“”<>|]*", raw)
        if not match:
            return ""
        return match.group(0).strip().rstrip("，。；,.;:)]}")

    def _looks_like_write_followup(self, user_input: str) -> bool:
        text = self._to_text(user_input).strip().lower()
        if not text:
            return False
        keywords = (
            "写到本地",
            "写入本地",
            "保存到本地",
            "落盘",
            "保存一下",
            "写一下",
            "写到",
            "保存到",
            "放在",
            "存到",
            "写入",
            "保存",
            "本地",
            "markdown",
            ".md",
        )
        return any(keyword in text for keyword in keywords)

    def _slugify_keyword(self, keyword: str) -> str:
        raw = self._to_text(keyword).strip()
        if not raw:
            return "report"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._-")
        return slug or "report"

    def _build_contextual_exec_task(self, user_input: str, history) -> str:
        task = self._to_text(user_input).strip()
        if not task:
            return ""
        if not self._looks_like_write_followup(task):
            return task

        payload = self._extract_latest_assistant_payload(history)
        if not payload:
            return task

        output_file = self._to_text(payload.get("output_file", "")).strip()
        final_report_text = self._to_text(payload.get("final_report_text") or payload.get("final_report") or "").strip()
        keyword = self._to_text(payload.get("keyword", "")).strip()
        target_path = self._extract_windows_path(task)
        if not target_path:
            return task

        target = Path(target_path)
        looks_like_dir = not target.suffix
        suggested_name = self._slugify_keyword(keyword) + ".md"

        if output_file:
            return (
                f"不要重新联网搜索，也不要重新生成内容。"
                f"直接读取上一轮 assistant 已生成的结果文件 `{output_file}`"
                f"{f'（关键词：{keyword}）' if keyword else ''}，"
                f"并将其内容写入本地 Markdown。"
                f"目标位置：`{target_path}`。"
                f"{f'如果该路径是目录，则在该目录下创建 `{suggested_name}`；' if looks_like_dir else '如果该路径是文件，则直接覆盖写入；'}"
                "若目录不存在请先创建。保留原始信息，不要替换成无关内容。"
            )

        if final_report_text:
            inline_content = final_report_text
            if len(inline_content) > 12000:
                inline_content = inline_content[:12000].rstrip() + "\n\n[内容过长，已截断]"
            return (
                f"不要重新联网搜索。"
                f"将以下现有内容直接写入本地 Markdown 文件。"
                f"目标位置：`{target_path}`。"
                f"{f'如果该路径是目录，则在该目录下创建 `{suggested_name}`；' if looks_like_dir else '如果该路径是文件，则直接覆盖写入；'}"
                "若目录不存在请先创建。\n\n"
                f"待写入内容：\n{inline_content}"
            )
        return task

    def _build_intent_router_prompt(self, user_input: str, history) -> str:
        skill_context = self._build_router_skill_context()
        tool_context = self._build_router_tool_context()
        recent_rounds = self._get_router_recent_rounds()
        system_logs = self._build_recent_system_logs_for_routing(history)
        payload = {
            "conversation_rounds": self._build_recent_rounds_for_routing(history, user_input),
            "system_logs": system_logs,
            "skills": skill_context["skills"],
            "skill_folders": skill_context["skill_folders"],
            "tools": tool_context["tools"],
            "tool_names": tool_context["tool_names"],
            "recent_rounds_limit": recent_rounds,
        }
        return (
            "你是 AI-Agent 的任务类型分流器，只负责判断当前输入应该走普通聊天、技能调用还是自主执行。\n"
            "当前只有三个方向：chat、skill、exec。\n"
            "你会拿到当前项目中真实存在的 skills list。只有当用户需求能被其中某个现有 skill 直接覆盖时，才能选择 skill。\n"
            "你也会拿到当前项目中真实存在的 tools list，但 tools 只作为辅助决策信息，不能直接成为第四种路线。\n"
            "判断规则：\n"
            "1. 如果当前已有 skill 可以直接完成任务，且任务更适合复用单个 skill，而不是走完整 exec 规划闭环，则 way=skill。\n"
            "2. 只有在已有 skill 明确匹配时才能选择 skill，并给出 skill_name；否则不要臆造 skill。\n"
            "3. skill_name 必须严格来自 skill_folders 列表，不允许输出列表之外的名字。\n"
            "4. 如果现有 tools 明显表明该需求更适合进入本地执行规划，再由 exec 阶段按需调用 tool、shell、python、file 完成，则优先考虑 way=exec。\n"
            "5. tools 不能直接单独路由；凡是需要调用 tools，也必须走 exec 路线。\n"
            "6. 如果用户当前真实意图是让 Agent 在本地环境中执行、生成脚本、落盘文件、操作目录、运行命令、读取本机/项目信息并给出执行结果，且不适合用单个 skill 解决，则 way=exec。\n"
            "7. 如果用户是在咨询、解释、讨论方案、闲聊、纯问答、让你直接回答而不是本地执行，则 way=chat。\n"
            f"8. 必须综合最近 {recent_rounds} 轮对话语境，不要只看单句关键词。\n"
            "9. 如果 payload 中给出了 system_logs，它们代表最近一轮或几轮 exec 的系统过程日志、计划摘要、验证结果与失败原因；需要把这些日志也视为 AI 历史的一部分，与对话轮次一起综合判断当前意图。\n"
            '只输出 JSON，结构必须等价于 {"way":"chat","skill_name":""}、{"way":"skill","skill_name":"time"} 或 {"way":"exec","skill_name":""}，不要输出任何额外文本。\n'
            f"Skills List:\n{skill_context['skill_text']}\n"
            f"Tools List:\n{tool_context['tool_text']}\n"
            f"输入：{json.dumps(payload, ensure_ascii=False)}"
        )

    def decide(self, user_input: str, history) -> dict:
        router_cfg = self._get_router_llm_config()
        decision_data = call_llm_json(
            self._build_intent_router_prompt(user_input, history),
            router_cfg["model"],
            router_cfg["key"],
        )
        return self._normalize_autonomous_decision(decision_data)

    def maybe_route_and_run(self, user_input: str, history, callback=None) -> dict:
        decision = self.decide(user_input, history)
        if decision.get("way") == "skill":
            skill_name = self._to_text(decision.get("skill_name", "")).strip()
            if not skill_name:
                return {"triggered": False, "decision": {"way": "chat", "skill_name": ""}}
            skill_result = self.exec_service.run_skill(user_input, skill_name, callback=callback)
            skill_result["decision"] = decision
            return skill_result
        if decision.get("way") != "exec":
            return {"triggered": False, "decision": decision}
        task = self._build_contextual_exec_task(user_input, history)
        result = self.exec_service.run(task, callback=callback)
        return {
            "triggered": True,
            "decision": decision,
            "task": task,
            "result": result,
        }
