from core.chat_service import ChatService
from core.command_handler import CommandHandler
from core.exec_service import ExecService
from core.file_utils import ensure_dirs
from core.get_config import Config
from core.intent_router_service import IntentRouterService
from core.memory_manager import MemoryManager
from core.skill_learning_service import SkillLearningService
from core.skill_loader import SkillRepository
from core.tool_loader import ToolRepository
from core.session_manager import SessionManager, archive_session


class AgentRuntime:
    """AI Agent 的业务运行时，供 CLI 与 GUI 共用。"""

    def __init__(self) -> None:
        ensure_dirs()
        self.config = Config()
        self.user = str(self.config.agent.get("user", "")).strip() or "default_user"
        self.memory_manager = MemoryManager(self.user)
        self.session_manager = SessionManager(self.user, self.config)
        self.command_handler = CommandHandler()
        self.chat_service = ChatService(self.config)
        self.skill_repository = SkillRepository()
        self.tool_repository = ToolRepository()
        self.exec_service = ExecService(
            self.config,
            self.user,
            skill_repository=self.skill_repository,
            tool_repository=self.tool_repository,
        )
        self.skill_learning_service = SkillLearningService(
            self.config,
            self.user,
            skill_repository=self.skill_repository,
        )
        self.intent_router_service = IntentRouterService(
            self.config,
            self.exec_service,
            skill_repository=self.skill_repository,
            tool_repository=self.tool_repository,
        )
        self.memory_context = ""
        self.reload_session()

    def reload_session(self) -> None:
        """重新加载当前用户会话与历史记忆。"""
        self.session_manager.reload()
        self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))

    @property
    def session_path(self):
        """向后兼容暴露当前会话文件路径。"""
        return self.session_manager.session_path

    @property
    def session(self):
        """向后兼容暴露当前活动会话。"""
        return self.session_manager.session

    @property
    def restored(self):
        """向后兼容暴露当前恢复状态。"""
        return self.session_manager.restored

    def get_available_instructions(self):
        """返回当前可用指令列表。"""
        return self.command_handler.get_available_instructions()

    def get_runtime_info(self):
        """返回界面层需要展示的静态/半静态信息。"""
        return self.get_runtime_info_for_session()

    def get_runtime_info_for_session(self, session_id: str | None = None):
        """返回指定 session 的界面展示信息。"""
        main_cfg = self.chat_service.get_main_config()
        session = self.session if not session_id else self.session_manager.get_session(session_id)
        current_id = self.session_manager.get_current_session_id()
        target_id = str(session_id or "").strip()
        return {
            "user": self.user,
            "start_time": session.get("start_time", ""),
            "session_id": session.get("session_id", ""),
            "session_title": session.get("title", ""),
            "restored": self.restored if not target_id or target_id == current_id else True,
            "instructions": self.get_available_instructions(),
            "model": main_cfg["model"],
            "stream": bool(main_cfg.get("stream", False)),
            "show_reasoning": bool(main_cfg.get("show_reasoning", False)),
            "reasoning_dim": bool(main_cfg.get("reasoning_dim", True)),
        }

    def get_session(self, session_id: str | None = None) -> dict:
        """返回指定 session 的完整数据。"""
        if not session_id:
            return self.session
        return self.session_manager.get_session(session_id)

    def append_history(
        self,
        user_input: str,
        reply: str,
        session_id: str | None = None,
        system_logs: list[str] | None = None,
    ) -> None:
        """保存本轮对话到活动会话。"""
        self.session_manager.append_history(user_input, reply, session_id=session_id, system_logs=system_logs)
        current_id = self.session_manager.get_current_session_id()
        target_id = str(session_id or "").strip()
        if not target_id or target_id == current_id:
            self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))

    def list_sessions(self):
        """列出当前用户全部 session。"""
        return self.session_manager.list_sessions()

    def list_skills(self):
        """列出当前项目下全部可用 skill。"""
        return self.skill_repository.list_skills()

    def get_skill(self, skill_name: str) -> dict:
        """按文件夹名或 frontmatter name 读取单个 skill。"""
        return self.skill_repository.get_skill(skill_name)

    def render_skill_overview(self, skill_name: str) -> str:
        """把 skill 整理成适合 CLI / GUI 展示的文本。"""
        return self.skill_repository.render_skill_overview(skill_name)

    def list_tools(self):
        """列出当前项目下全部可用 tool。"""
        return self.tool_repository.list_tools()

    def get_tool(self, tool_name: str) -> dict:
        """按规范名、目录名或别名读取单个 tool。"""
        return self.tool_repository.get_tool(tool_name)

    def render_tool_overview(self, tool_name: str) -> str:
        """把 tool 整理成适合 CLI / GUI 展示的文本。"""
        return self.tool_repository.render_tool_overview(tool_name)

    def execute_skill(self, skill_name: str, args_text: str = "", callback=None) -> dict:
        """显式执行单个 skill，并把结果写回当前会话。"""
        return self.execute_skill_on_session(self.session.get("session_id", ""), skill_name, args_text=args_text, callback=callback)

    def execute_skill_on_session(self, session_id: str, skill_name: str, args_text: str = "", callback=None) -> dict:
        """在指定 session 上显式执行单个 skill。"""
        target_id = str(session_id or "").strip() or self.session.get("session_id", "")
        result = self.exec_service.run_skill_direct(skill_name, args_text=args_text, callback=callback)
        reply = str(result.get("reply", "")).strip()
        command_text = f"/skill {skill_name}"
        if str(args_text or "").strip():
            command_text = f"{command_text} {str(args_text).strip()}"
        if reply:
            self.append_history(command_text, reply, session_id=target_id)
        return result

    def learn_skill_from_current_session(self, callback=None) -> dict:
        """从当前会话最近一次成功 EXEC 学习并生成 skill。"""
        return self.learn_skill_from_session(self.session.get("session_id", ""), callback=callback)

    def learn_skill_from_session(self, session_id: str, callback=None) -> dict:
        """从指定会话最近一次成功 EXEC 学习并生成 skill。"""
        target_id = str(session_id or "").strip() or self.session.get("session_id", "")
        session_history = self.get_session_history(target_id)
        result = self.skill_learning_service.learn_from_latest_exec(session_history=session_history, callback=callback)
        reply = str(result.get("chat_report", "")).strip()
        if reply:
            self.append_history("/skill add", reply, session_id=target_id)
        return result

    def switch_session(self, session_id: str):
        """切换到指定 session，并立即让后续对话基于该 history。"""
        session = self.session_manager.switch_session(session_id)
        self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))
        return session

    def get_current_history(self):
        """返回当前 session 的完整 history。"""
        return self.get_session_history()

    def get_session_history(self, session_id: str | None = None):
        """返回指定 session 的完整 history。"""
        if not session_id:
            return list(self.session.get("history", []))
        return self.session_manager.get_session_history(session_id)

    def _build_execution_message(self, task: str, result: dict, autonomous: bool = False) -> str:
        """把执行结果整理为可写回会话的自然语言摘要。"""
        return self.exec_service.get_chat_report_message(task, result, autonomous=autonomous)

    def chat(self, user_input: str, attachments=None, on_answer_token=None, on_reasoning_token=None, exec_callback=None) -> str:
        """执行普通对话；若检测到本地落地意图，则自动进入自主执行闭环。"""
        return self.chat_on_session(
            self.session.get("session_id", ""),
            user_input,
            attachments=attachments,
            on_answer_token=on_answer_token,
            on_reasoning_token=on_reasoning_token,
            exec_callback=exec_callback,
        )

    def chat_on_session(
        self,
        session_id: str,
        user_input: str,
        attachments=None,
        on_answer_token=None,
        on_reasoning_token=None,
        exec_callback=None,
    ) -> str:
        """在指定 session 上执行对话，避免切换当前选中会话时串台。"""
        target_id = str(session_id or "").strip() or self.session.get("session_id", "")
        session = self.session_manager.get_session(target_id)
        memory_context = self.memory_manager.build_context(target_id)
        history_user_input = self.chat_service.build_history_user_input(user_input, attachments)
        auto_exec = self.intent_router_service.maybe_route_and_run(
            history_user_input,
            session.get("history", []),
            callback=exec_callback,
        )
        if auto_exec.get("triggered"):
            if auto_exec.get("kind") == "skill":
                reply = str(auto_exec.get("reply", "")).strip()
            else:
                reply = self._build_execution_message(
                    auto_exec.get("task", history_user_input),
                    auto_exec.get("result", {}),
                    autonomous=True,
                )
            if on_answer_token is not None and reply:
                on_answer_token(reply)
            system_logs = auto_exec.get("result", {}).get("decision_logs", []) if isinstance(auto_exec.get("result"), dict) else []
            self.append_history(history_user_input, reply, session_id=target_id, system_logs=system_logs)
            return reply

        reply = self.chat_service.chat(
            memory_context,
            session.get("history", []),
            user_input,
            attachments=attachments,
            on_answer_token=on_answer_token,
            on_reasoning_token=on_reasoning_token,
        ).strip()
        self.append_history(history_user_input, reply, session_id=target_id)
        return reply

    def end_session(self, auto_new_session: bool = True):
        """结束当前会话并归档摘要。"""
        archive_data = self.session_manager.end_current_session(auto_new_session=auto_new_session)
        if auto_new_session:
            self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))
        return archive_data

    def begin_end_session(self, auto_new_session: bool = True) -> dict:
        """立即切换到新会话，并返回旧会话快照供后台归档。"""
        archive_context = self.session_manager.prepare_end_current_session(auto_new_session=auto_new_session)
        if auto_new_session:
            self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))
        return archive_context

    def finalize_end_session(self, archive_context: dict) -> dict:
        """在后台根据旧会话快照生成摘要并归档。"""
        archive_data = archive_session(
            self.config,
            archive_context["session_path"],
            archive_context["session"],
        )
        archived_session_id = str(archive_context.get("session", {}).get("session_id", "")).strip()
        current_session_id = str(self.session.get("session_id", "")).strip()
        if archived_session_id and archived_session_id == current_session_id:
            self.reload_session()
        else:
            self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))
        return archive_data

    def remove_records(self, auto_new_session: bool = True):
        """删除当前用户全部记录，并按需重建新会话。"""
        removed_count, removed_files = self.session_manager.remove_all_records(auto_new_session=auto_new_session)
        if auto_new_session:
            self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))
        return removed_count, removed_files

    def remove_session(self, session_id: str):
        """删除指定 session，并维护当前运行时指向的活动会话。"""
        result = self.session_manager.remove_session(session_id)
        current_id = str(self.session.get("session_id", "")).strip()
        self.memory_context = self.memory_manager.build_context(current_id)
        return result

    def create_new_session(self):
        """新建一个未归档的并行会话并切换过去。"""
        session = self.session_manager.create_and_switch_new_session()
        self.memory_context = self.memory_manager.build_context(self.session.get("session_id", ""))
        return session

    def save_current_session(self) -> None:
        """保存当前活动会话。"""
        self.session_manager.save()

    def classify_instruction(self, user_input: str):
        """判断输入是否为已知指令。"""
        return self.command_handler.classify(user_input)

    def execute_exec_workflow(self, task: str, callback=None) -> dict:
        """兼容显式 /exec 入口，并把执行结果写入当前会话。"""
        return self.execute_exec_workflow_on_session(self.session.get("session_id", ""), task, callback=callback)

    def execute_exec_workflow_on_session(self, session_id: str, task: str, callback=None) -> dict:
        """在指定 session 上执行 /exec，并把结果写回该 session。"""
        target_id = str(session_id or "").strip() or self.session.get("session_id", "")
        result = self.exec_service.run(task, callback=callback)
        final_message = self._build_execution_message(task, result, autonomous=False)
        result["chat_report"] = final_message
        self.append_history(
            f"/exec {task}",
            final_message,
            session_id=target_id,
            system_logs=result.get("decision_logs", []),
        )
        return result
