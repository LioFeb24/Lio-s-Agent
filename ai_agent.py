"""顶层 CLI 入口与兼容导出层。真正业务实现位于 core，用户交互层位于 app。"""

from core.agent_runtime import AgentRuntime
from core.chat_service import ChatService
from app.CLI import main
from core.command_handler import CommandHandler
from core.exec_service import ExecService
from core.get_config import Config
from core.memory_manager import MemoryManager
from core.prompt_builder import build_archive_filename, build_chat_prompt, build_memory_context, build_summary_prompt, extract_json_object, format_history, style_reasoning_text
from core.session_manager import SessionManager, archive_session, collect_user_record_files, get_session_path, load_or_create_session, normalize_history, remove_user_records, save_session


if __name__ == "__main__":
    main()
