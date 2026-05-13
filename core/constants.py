from pathlib import Path


# ANSI 样式仅用于终端版思考文本的弱化显示。
ANSI_DIM = "\033[2m"
ANSI_RESET = "\033[0m"

# 以项目根目录为基准，统一管理运行期目录位置。
BASE_DIR = Path(__file__).resolve().parent.parent
SKILLS_DIR = BASE_DIR / "SKILLS"
TOOLS_DIR = BASE_DIR / "TOOLS"
INSTRUCTION_PATH = BASE_DIR / "instruction.json"
MEMORY_DIR = BASE_DIR / "MEMORY"
SESSION_DIR = BASE_DIR / "session_state"
EXEC_DIR = BASE_DIR / "EXEC"
EXEC_PLAN_DIR = EXEC_DIR / "plans"
EXEC_SCRIPT_DIR = EXEC_DIR / "scripts"
EXEC_RESULT_DIR = EXEC_DIR / "results"
EXEC_FULL_INFO_DIR = EXEC_DIR / "full_info"
