import json
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import colorchooser, filedialog, font as tkfont, messagebox

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import customtkinter as ctk
from markdown_it import MarkdownIt

from core.agent_runtime import AgentRuntime
from core.constants import BASE_DIR
from core.get_config import Config


ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")
COLOR_FIELDS = [
    ("bg_color", "窗口背景"),
    ("card_color", "卡片背景"),
    ("panel_color", "面板背景"),
    ("input_box_color", "输入框背景"),
    ("text_color", "主文字"),
    ("subtext_color", "辅助文字"),
    ("button_color", "次按钮"),
    ("button_hover", "次按钮悬停"),
    ("primary_button", "主按钮"),
    ("primary_button_hover", "主按钮悬停"),
    ("primary_text", "主按钮文字"),
    ("border_color", "边框颜色"),
    ("selected_color", "选中高亮"),
    ("reasoning_color", "思考文字"),
    ("user_bubble", "用户气泡"),
    ("ai_bubble", "AI 气泡"),
    ("system_bubble", "系统气泡"),
    ("thinking_bubble", "思考气泡"),
    ("exec_mode_border", "执行模式边框"),
    ("exec_mode_button", "执行模式按钮"),
    ("exec_mode_button_hover", "执行模式按钮悬停"),
    ("exec_mode_hint", "执行模式提示字"),
]
CUSTOM_THEME_NAME = "自定义"
THEME_PRESETS = {
    "Dracula": {
        "description": "深紫黑底，高对比，紫/粉/青色点缀，适合长时间编码。",
        "colors": {
            "bg_color": "#282A36", "card_color": "#303341", "panel_color": "#2F3240", "input_box_color": "#343746",
            "text_color": "#F8F8F2", "subtext_color": "#C0C5D4", "button_color": "#44475A", "button_hover": "#6272A4",
            "primary_button": "#BD93F9", "primary_button_hover": "#D6ACFF", "primary_text": "#1F1028", "border_color": "#44475A",
            "selected_color": "#3B3F51", "reasoning_color": "#8BE9FD", "user_bubble": "#44475A", "ai_bubble": "#3A3F58",
            "system_bubble": "#2D303E", "thinking_bubble": "#2C3248", "exec_mode_border": "#F1FA8C", "exec_mode_button": "#FF79C6",
            "exec_mode_button_hover": "#BD93F9", "exec_mode_hint": "#8BE9FD",
        },
    },
    "One Dark": {
        "description": "深灰底，柔和均衡，蓝/绿/橙配色，通用开发体验稳定。",
        "colors": {
            "bg_color": "#282C34", "card_color": "#2C313C", "panel_color": "#21252B", "input_box_color": "#303642",
            "text_color": "#ABB2BF", "subtext_color": "#8C95A5", "button_color": "#3B4252", "button_hover": "#4B5263",
            "primary_button": "#61AFEF", "primary_button_hover": "#7BC1FF", "primary_text": "#FFFFFF", "border_color": "#3E4451",
            "selected_color": "#33415C", "reasoning_color": "#98C379", "user_bubble": "#2F3642", "ai_bubble": "#323B49",
            "system_bubble": "#272C35", "thinking_bubble": "#253042", "exec_mode_border": "#E5C07B", "exec_mode_button": "#98C379",
            "exec_mode_button_hover": "#E5C07B", "exec_mode_hint": "#E5C07B",
        },
    },
    "Monokai": {
        "description": "黑偏棕背景，高饱和跳色，荧光绿/橙/粉组合，风格鲜明。",
        "colors": {
            "bg_color": "#272822", "card_color": "#2F3129", "panel_color": "#303228", "input_box_color": "#3A3D32",
            "text_color": "#F8F8F2", "subtext_color": "#B7B9A8", "button_color": "#49483E", "button_hover": "#75715E",
            "primary_button": "#FD971F", "primary_button_hover": "#FFAE4A", "primary_text": "#1F1F1F", "border_color": "#5B5A4F",
            "selected_color": "#44483D", "reasoning_color": "#66D9EF", "user_bubble": "#3C4135", "ai_bubble": "#43352C",
            "system_bubble": "#34352E", "thinking_bubble": "#313640", "exec_mode_border": "#A6E22E", "exec_mode_button": "#F92672",
            "exec_mode_button_hover": "#FD971F", "exec_mode_hint": "#A6E22E",
        },
    },
    "Nord": {
        "description": "冷灰蓝基调，低对比偏护眼，冰蓝与雾灰适合超长时间工作。",
        "colors": {
            "bg_color": "#2E3440", "card_color": "#3B4252", "panel_color": "#353C4A", "input_box_color": "#434C5E",
            "text_color": "#E5E9F0", "subtext_color": "#D8DEE9", "button_color": "#4C566A", "button_hover": "#5E81AC",
            "primary_button": "#88C0D0", "primary_button_hover": "#81A1C1", "primary_text": "#2E3440", "border_color": "#4C566A",
            "selected_color": "#5E81AC", "reasoning_color": "#8FBCBB", "user_bubble": "#434C5E", "ai_bubble": "#4C566A",
            "system_bubble": "#3A4250", "thinking_bubble": "#3B4252", "exec_mode_border": "#EBCB8B", "exec_mode_button": "#A3BE8C",
            "exec_mode_button_hover": "#8FBCBB", "exec_mode_hint": "#88C0D0",
        },
    },
    "Gruvbox Dark": {
        "description": "复古棕黑背景，低饱和但辨识度强，土黄与橄榄绿很耐看。",
        "colors": {
            "bg_color": "#282828", "card_color": "#32302F", "panel_color": "#3C3836", "input_box_color": "#3C3836",
            "text_color": "#EBDBB2", "subtext_color": "#D5C4A1", "button_color": "#504945", "button_hover": "#665C54",
            "primary_button": "#D79921", "primary_button_hover": "#FABD2F", "primary_text": "#1D2021", "border_color": "#665C54",
            "selected_color": "#458588", "reasoning_color": "#83A598", "user_bubble": "#3C3836", "ai_bubble": "#504945",
            "system_bubble": "#32302F", "thinking_bubble": "#3F3A35", "exec_mode_border": "#FE8019", "exec_mode_button": "#B8BB26",
            "exec_mode_button_hover": "#FABD2F", "exec_mode_hint": "#FABD2F",
        },
    },
    "Tokyo Night": {
        "description": "深蓝夜色背景，现代感强，蓝紫和青色组合很适合长时间编码。",
        "colors": {
            "bg_color": "#1A1B26", "card_color": "#24283B", "panel_color": "#1F2335", "input_box_color": "#24283B",
            "text_color": "#C0CAF5", "subtext_color": "#A9B1D6", "button_color": "#2F3549", "button_hover": "#394B70",
            "primary_button": "#7AA2F7", "primary_button_hover": "#89B4FA", "primary_text": "#1A1B26", "border_color": "#414868",
            "selected_color": "#283B4F", "reasoning_color": "#7DCFFF", "user_bubble": "#2A3148", "ai_bubble": "#25304A",
            "system_bubble": "#23263A", "thinking_bubble": "#1F2A44", "exec_mode_border": "#BB9AF7", "exec_mode_button": "#7AA2F7",
            "exec_mode_button_hover": "#2AC3DE", "exec_mode_hint": "#73DACA",
        },
    },
    "GitHub Light": {
        "description": "纯白极简风格，清晰直接，适合白天办公和文档阅读。",
        "colors": {
            "bg_color": "#F6F8FA", "card_color": "#FFFFFF", "panel_color": "#F6F8FA", "input_box_color": "#FFFFFF",
            "text_color": "#1F2328", "subtext_color": "#57606A", "button_color": "#EAEEF2", "button_hover": "#DDE6F0",
            "primary_button": "#2F81F7", "primary_button_hover": "#1F6FEB", "primary_text": "#FFFFFF", "border_color": "#D0D7DE",
            "selected_color": "#DDF4FF", "reasoning_color": "#0969DA", "user_bubble": "#EAF5FF", "ai_bubble": "#F3F8FF",
            "system_bubble": "#F6F8FA", "thinking_bubble": "#F0F7FF", "exec_mode_border": "#D29922", "exec_mode_button": "#FBF3D5",
            "exec_mode_button_hover": "#F2CC60", "exec_mode_hint": "#9A6700",
        },
    },
    "Solarized Light": {
        "description": "米黄色科学配色，低对比护眼，适合长时间办公阅读。",
        "colors": {
            "bg_color": "#FDF6E3", "card_color": "#FFFDF5", "panel_color": "#F7F0DA", "input_box_color": "#FDF6E3",
            "text_color": "#657B83", "subtext_color": "#93A1A1", "button_color": "#EEE8D5", "button_hover": "#DFD8C4",
            "primary_button": "#268BD2", "primary_button_hover": "#2AA198", "primary_text": "#FDF6E3", "border_color": "#C8C1AE",
            "selected_color": "#E7E1CD", "reasoning_color": "#2AA198", "user_bubble": "#EAF2F8", "ai_bubble": "#EFF7F5",
            "system_bubble": "#F7F0DA", "thinking_bubble": "#EEE8D5", "exec_mode_border": "#B58900", "exec_mode_button": "#DFD8C4",
            "exec_mode_button_hover": "#E8D9A8", "exec_mode_hint": "#B58900",
        },
    },
    "IntelliJ Light": {
        "description": "浅灰传统 IDE 风格，层次清楚，适合企业开发和白天使用。",
        "colors": {
            "bg_color": "#F7F7F7", "card_color": "#FFFFFF", "panel_color": "#F3F3F3", "input_box_color": "#FFFFFF",
            "text_color": "#2B2B2B", "subtext_color": "#6C707E", "button_color": "#E6EBF5", "button_hover": "#D6E4FF",
            "primary_button": "#3574F0", "primary_button_hover": "#4E8AF7", "primary_text": "#FFFFFF", "border_color": "#D9E2F2",
            "selected_color": "#EAF2FF", "reasoning_color": "#4B83CD", "user_bubble": "#ECF4FF", "ai_bubble": "#F4F7FF",
            "system_bubble": "#F7F7F7", "thinking_bubble": "#F0F3F9", "exec_mode_border": "#F0A732", "exec_mode_button": "#FFF1D6",
            "exec_mode_button_hover": "#F7D59C", "exec_mode_hint": "#9C6B00",
        },
    },
    "Solarized Dark": {
        "description": "严格色彩空间设计的经典深色主题，耐看但初见可能需要适应。",
        "colors": {
            "bg_color": "#002B36", "card_color": "#073642", "panel_color": "#0A3946", "input_box_color": "#073642",
            "text_color": "#93A1A1", "subtext_color": "#839496", "button_color": "#174956", "button_hover": "#1F5E6E",
            "primary_button": "#268BD2", "primary_button_hover": "#2AA198", "primary_text": "#FDF6E3", "border_color": "#1B4D59",
            "selected_color": "#0F4C5C", "reasoning_color": "#2AA198", "user_bubble": "#0F3B46", "ai_bubble": "#113F4A",
            "system_bubble": "#08313B", "thinking_bubble": "#0D3843", "exec_mode_border": "#B58900", "exec_mode_button": "#586E75",
            "exec_mode_button_hover": "#859900", "exec_mode_hint": "#B58900",
        },
    },
    "Gruvbox Soft": {
        "description": "更柔和的 Gruvbox 变体，复古棕感更轻，适合长时间低刺激工作。",
        "colors": {
            "bg_color": "#32302F", "card_color": "#3A3735", "panel_color": "#423E3C", "input_box_color": "#504945",
            "text_color": "#EBDBB2", "subtext_color": "#BDAE93", "button_color": "#5A524C", "button_hover": "#7C6F64",
            "primary_button": "#D79921", "primary_button_hover": "#FE8019", "primary_text": "#1D2021", "border_color": "#7C6F64",
            "selected_color": "#689D6A", "reasoning_color": "#83A598", "user_bubble": "#4B443E", "ai_bubble": "#55463E",
            "system_bubble": "#3F3A36", "thinking_bubble": "#47403B", "exec_mode_border": "#B8BB26", "exec_mode_button": "#D79921",
            "exec_mode_button_hover": "#FE8019", "exec_mode_hint": "#8EC07C",
        },
    },
}
SURFACE_STYLE_FIELDS = [
    ("surface_corner_radius", "圆角半径", "int"),
    ("surface_shadow_blur", "阴影模糊", "int"),
    ("surface_shadow_offset_y", "阴影下移", "int"),
    ("surface_shadow_alpha", "阴影透明度", "int"),
    ("surface_shadow_margin", "阴影边距", "int"),
    ("surface_glass_opacity", "玻璃透明度", "float"),
    ("surface_glass_blur", "玻璃模糊", "int"),
    ("surface_enable_glass", "启用毛玻璃", "bool"),
]
GUI_FIELD_DESCRIPTIONS = {
    "theme_preset": "选择一套预设界面主题；点击“应用主题”后会批量覆盖下方颜色配置。",
    "window_width": "主窗口固定宽度，影响主界面的整体横向布局和留白空间。",
    "window_height": "主窗口固定高度，影响聊天区与设置区的可视空间。",
    "family": "聊天消息、按钮和大部分文本控件使用的主字体名称。",
    "size": "GUI 基础字号，标题、正文和辅助文字会在此基础上按比例缩放。",
    "bold": "是否默认把聊天主字体显示为加粗。",
    "italic": "是否默认把聊天主字体显示为斜体。",
    "surface_corner_radius": "主要卡片和输入区的圆角大小，值越大边角越圆。",
    "surface_shadow_blur": "阴影模糊半径，值越大阴影越柔和。",
    "surface_shadow_offset_y": "阴影向下偏移距离，决定悬浮感强弱。",
    "surface_shadow_alpha": "阴影透明度，值越大阴影越明显。",
    "surface_shadow_margin": "为阴影预留的外围空白，过小可能导致阴影被裁切。",
    "surface_glass_opacity": "毛玻璃亮色覆盖层强度，值越大越接近半透明玻璃效果。",
    "surface_glass_blur": "毛玻璃模糊强度，主要影响背景图上的朦胧感。",
    "surface_enable_glass": "是否启用模拟毛玻璃效果；关闭后界面更接近纯色卡片。",
    "bg_color": "整个应用最外层背景色。",
    "card_color": "主要卡片容器背景色，如左右主面板。",
    "panel_color": "卡片内部次级面板背景色，如聊天滚动区内层。",
    "input_box_color": "输入框与类似编辑控件的背景色。",
    "text_color": "正文、标题和主要信息的默认文字颜色。",
    "subtext_color": "状态提示、辅助说明和次级文本颜色。",
    "button_color": "普通按钮默认背景色。",
    "button_hover": "普通按钮鼠标悬停时的背景色。",
    "primary_button": "主操作按钮背景色，如发送、保存等。",
    "primary_button_hover": "主操作按钮悬停时的背景色。",
    "primary_text": "主操作按钮上的文字颜色。",
    "border_color": "输入框、卡片和列表等控件的边框颜色。",
    "selected_color": "选中态、高亮态背景色。",
    "reasoning_color": "思考过程文本的字体颜色。",
    "user_bubble": "用户消息气泡背景色。",
    "ai_bubble": "助手回复气泡背景色。",
    "system_bubble": "系统提示消息气泡背景色。",
    "thinking_bubble": "思考内容气泡背景色。",
    "exec_mode_border": "执行模式下输入框高亮边框颜色。",
    "exec_mode_button": "执行模式相关按钮的背景色。",
    "exec_mode_button_hover": "执行模式相关按钮悬停时的背景色。",
    "exec_mode_hint": "执行模式提示文案的文字颜色。",
}
SETTING_DESCRIPTIONS = {
    "agent": "当前 Agent 的基础身份信息与系统提示配置。",
    "agent.system": "提供给 Agent 的系统提示词，会直接影响整体回答与执行风格。",
    "agent.user": "当前本地用户标识，用于会话、记忆与产物目录归属。",
    "llm": "模型相关配置，分别控制主对话、摘要与意图分流。",
    "llm.summary": "摘要模型配置，用于会话摘要与记忆整理。",
    "llm.summary.key": "摘要模型的 API Key。",
    "llm.summary.model": "摘要模型名称或部署名。",
    "llm.summary.stream": "摘要任务是否启用流式输出；通常关闭即可。",
    "llm.main_llm": "主对话模型配置，负责普通聊天与核心生成。",
    "llm.main_llm.key": "主对话模型的 API Key。",
    "llm.main_llm.model": "主对话模型名称或部署名。",
    "llm.main_llm.stream": "普通聊天时是否启用流式输出。",
    "llm.main_llm.show_reasoning": "模型返回推理内容时，是否在界面中显示思考过程。",
    "llm.main_llm.reasoning_dim": "是否对推理内容使用更弱化的视觉样式，避免喧宾夺主。",
    "llm.intent_router": "辅助分流模型配置，用于判断当前请求应走 chat、skill 还是 exec。",
    "llm.intent_router.key": "辅助分流模型的 API Key；缺失时通常回退复用主模型配置。",
    "llm.intent_router.model": "辅助分流模型名称或部署名。",
    "llm.intent_router.stream": "分流判断是否启用流式输出；通常关闭即可。",
    "llm.intent_router.recent_rounds": "分流时仅参考最近多少轮对话，值越小越省上下文。",
    "exec": "Exec 自主执行闭环的步数与重试限制。",
    "exec.retry_limit": "单步失败后的最大修复重试次数。",
    "exec.review_after_retry_limit": "单步连续失败超过该阈值后，不再只修当前步骤，而是先审查整条 exec 流程再重新规划。",
    "exec.max_steps": "单次执行计划允许的最大步骤数，避免计划无限膨胀。",
    "exec.max_expand_depth": "计划拆解子步骤时允许的最大展开深度。",
    "exec.independent_llm_step_context_enabled": "是否为规划出的 `llm_dispatch` 分点自动注入独立上下文。开启后，每个认知型子任务会拼接该分点的关键前提、重要依赖、预期输出与验证要求，避免直接复用整个 exec 大上下文；关闭后仅使用 step 自己原始 args。",
    "exec.planner_runtime_context_enabled": "是否在 exec 任务规划前向规划器注入当前宿主环境与项目信息。建议开启，避免把 Windows 误规划成 Linux。",
    "exec.planner_include_system_info": "是否把操作系统、Shell、Python、路径风格、沙箱状态等系统信息拼接给规划器。",
    "exec.planner_include_project_info": "是否把项目根目录、顶层文件/目录、关键清单文件等项目概览拼接给规划器。",
    "exec.planner_include_env_vars": "是否把选定系统变量拼接给规划器。默认关闭，只有在任务确实依赖环境变量时再手动开启。",
    "exec.planner_env_var_keys": "当启用环境变量注入时，允许提供给规划器的变量名列表，使用 JSON 数组编辑。",
    "exec.planner_project_entry_limit": "规划器可见的项目根目录条目上限，值越大上下文越多。",
    "skill_review": "Skill 评审配置，当前版本仅使用评分通过阈值。",
    "skill_review.threshold": "Skill 评审通过阈值，范围通常为 0 到 10。",
    "skill_learning": "从最近一次成功 EXEC 提炼 skill 时使用的校验与修复配置。",
    "skill_learning.temp_validation_enabled": "生成后是否先做本地编译/运行校验，再确认最终落地。",
    "skill_learning.max_repair_rounds": "本地校验失败后允许执行的最大保守修复轮数。",
    "sandbox": "CubeSandbox 执行后端配置；开启后 shell/python/file/tool 会优先在沙箱中运行。",
    "sandbox.enabled": "是否启用沙箱执行后端。",
    "sandbox.provider": "沙箱提供方标识，当前默认是 cubesandbox。",
    "sandbox.backend": "具体后端类型，当前默认是 e2b 兼容后端。",
    "sandbox.api_key": "访问沙箱服务所需的 API Key。",
    "sandbox.domain": "沙箱服务域名；自托管或代理场景下可填写。",
    "sandbox.template": "创建沙箱实例时使用的模板名称或 ID。",
    "sandbox.timeout_seconds": "单次沙箱整体运行超时时间，单位为秒。",
    "sandbox.command_timeout_seconds": "沙箱内单条命令执行超时时间，单位为秒。",
    "sandbox.workspace_root": "沙箱中的项目工作目录根路径。",
    "sandbox.sync_project_on_start": "启动沙箱时是否先把当前项目同步进去。",
    "sandbox.sync_back_to_host": "执行结束后是否把沙箱内变更同步回本地宿主机。",
    "sandbox.kill_after_run": "单次执行结束后是否主动销毁沙箱实例。",
    "sandbox.allow_external_paths": "是否允许同步项目目录之外的额外路径。",
    "sandbox.max_sync_files": "单次同步到沙箱的最大文件数量限制。",
    "sandbox.max_file_size_kb": "允许同步的单文件大小上限，单位为 KB。",
    "sandbox.sync_include": "同步到沙箱时的包含文件匹配规则列表。",
    "sandbox.sync_ignore": "同步到沙箱时的忽略路径规则列表。",
    "sandbox.envs": "注入到沙箱运行环境中的额外环境变量键值对。",
}
DEFAULT_SURFACE_STYLE = {
    "corner_radius": 12,
    "shadow_blur": 10,
    "shadow_offset_y": 3,
    "shadow_alpha": 72,
    "shadow_margin": 6,
    "glass_opacity": 0.2,
    "glass_blur": 12,
    "enable_glass": True,
}
EVENT_POLL_INTERVAL_MS = 100
EVENT_POLL_BUSY_INTERVAL_MS = 15
EVENT_POLL_BATCH_SIZE = 40
STREAM_WIDGET_RESIZE_INTERVAL_S = 0.12


class AgentGUI:
    """图形界面壳层，只负责展示、交互和事件分发。"""

    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.config_manager = Config()
        self.full_config = self.config_manager.get_full_config()
        self.gui_settings = self.config_manager.get_gui_config()
        self.window_settings = dict(self.gui_settings.get("window", {}))
        self.window_width = self._normalize_window_dimension(
            self.window_settings.get("width", 1360),
            minimum=960,
            maximum=2400,
            fallback=1360,
        )
        self.window_height = self._normalize_window_dimension(
            self.window_settings.get("height", 860),
            minimum=640,
            maximum=1600,
            fallback=860,
        )
        self.font_settings = dict(self.gui_settings["chat_font"])
        self.colors = dict(self.gui_settings["colors"])
        self.surface_style = self._normalize_surface_style(
            self.gui_settings.get("surface_style", {})
        )
        self.available_fonts = self._load_available_fonts()
        self.markdown_parser = MarkdownIt("commonmark", {"linkify": True}).enable(["table", "strikethrough"])
        self._build_fonts()

        self.root.title("Lio's AI Agent")
        self.root.resizable(False, False)
        self.root.configure(fg_color=self.colors["bg_color"])
        self._apply_window_icon()
        self._apply_window_geometry(center=False)

        self.runtime = AgentRuntime()
        self.user = self.runtime.user

        self.event_queue: queue.Queue[dict] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.busy = False
        self.session_workers: dict[str, threading.Thread] = {}
        self.session_task_states: dict[str, dict] = {}
        self.answer_started = False
        self.reasoning_started = False
        self.selected_session_id = ""
        self.current_answer_widget = None
        self.current_reasoning_widget = None
        self.chat_middle_drag_active = False
        self.chat_middle_drag_last_y = 0

        self.status_var = tk.StringVar(value="就绪")
        self.detail_var = tk.StringVar(value="等待输入")
        self.user_var = tk.StringVar(value=self.user)
        self.start_time_var = tk.StringVar(value="")
        self.model_var = tk.StringVar(value="")
        self.stream_var = tk.StringVar(value="")
        self.reasoning_var = tk.StringVar(value="")
        self.instructions_var = tk.StringVar(value="")
        self.session_count_var = tk.StringVar(value="0 个会话")

        self.session_items = []
        self.session_buttons = []
        self.chat_bubble_widgets = []
        self.settings_window = None
        self.settings_tabview = None
        self.settings_vars = {}
        self.color_preview_labels = {}
        self.dynamic_field_specs = {}
        self.dynamic_color_preview_labels = {}
        self.settings_status_var = None
        self.preview_widgets = {}
        self.font_listbox = None
        self.settings_controls = []
        self.size_setting_controls = []
        self.archive_in_progress = False
        self.pending_attachments = []
        self.attachment_var = tk.StringVar(value="未选择附件")
        self.exec_mode = False
        self.applying_theme_preset = False

        self._load_session()
        self._build_ui()
        self._refresh_session_list()
        self._render_start_message()
        self.root.after(0, self._set_startup_window_state)
        self.root.after(100, self._poll_event_queue)

    def _normalize_font_family(self, family: str | None) -> str:
        """规避 Windows 竖排字体别名（如 @宋体）。"""
        normalized = str(family or "").strip().lstrip("@").strip()
        return normalized or "宋体"

    def _normalize_font_size(self, value) -> int:
        """把字号限制在可读范围内。"""
        try:
            size = int(value)
        except (TypeError, ValueError):
            size = 13
        return max(9, min(size, 32))

    def _normalize_opacity(self, value, *, fallback: float) -> float:
        """把透明度限制在 0~1。"""
        try:
            opacity = float(value)
        except (TypeError, ValueError):
            opacity = fallback
        return max(0.0, min(opacity, 1.0))

    def _normalize_surface_style(self, style: dict | None) -> dict:
        """标准化 GUI 表面样式配置。"""
        raw = style if isinstance(style, dict) else {}
        normalized = dict(DEFAULT_SURFACE_STYLE)
        normalized["corner_radius"] = self._normalize_window_dimension(
            raw.get("corner_radius", normalized["corner_radius"]),
            minimum=0,
            maximum=36,
            fallback=DEFAULT_SURFACE_STYLE["corner_radius"],
        )
        normalized["shadow_blur"] = self._normalize_window_dimension(
            raw.get("shadow_blur", normalized["shadow_blur"]),
            minimum=0,
            maximum=40,
            fallback=DEFAULT_SURFACE_STYLE["shadow_blur"],
        )
        normalized["shadow_offset_y"] = self._normalize_window_dimension(
            raw.get("shadow_offset_y", normalized["shadow_offset_y"]),
            minimum=0,
            maximum=20,
            fallback=DEFAULT_SURFACE_STYLE["shadow_offset_y"],
        )
        normalized["shadow_alpha"] = self._normalize_window_dimension(
            raw.get("shadow_alpha", normalized["shadow_alpha"]),
            minimum=0,
            maximum=180,
            fallback=DEFAULT_SURFACE_STYLE["shadow_alpha"],
        )
        normalized["shadow_margin"] = self._normalize_window_dimension(
            raw.get("shadow_margin", normalized["shadow_margin"]),
            minimum=0,
            maximum=20,
            fallback=DEFAULT_SURFACE_STYLE["shadow_margin"],
        )
        normalized["glass_opacity"] = self._normalize_opacity(
            raw.get("glass_opacity", normalized["glass_opacity"]),
            fallback=DEFAULT_SURFACE_STYLE["glass_opacity"],
        )
        normalized["glass_blur"] = self._normalize_window_dimension(
            raw.get("glass_blur", normalized["glass_blur"]),
            minimum=0,
            maximum=40,
            fallback=DEFAULT_SURFACE_STYLE["glass_blur"],
        )
        normalized["enable_glass"] = bool(raw.get("enable_glass", normalized["enable_glass"]))
        return normalized

    def _get_surface_corner_radius(self) -> int:
        """返回当前统一表面圆角。"""
        return int(self.surface_style.get("corner_radius", DEFAULT_SURFACE_STYLE["corner_radius"]))

    def _get_glass_overlay_color(self, base_color: str) -> str:
        """根据毛玻璃透明度把表面颜色向白色混合，模拟玻璃层。"""
        if not self._is_valid_color(base_color):
            return base_color
        opacity = self.surface_style.get("glass_opacity", DEFAULT_SURFACE_STYLE["glass_opacity"])
        if not self.surface_style.get("enable_glass", True):
            opacity = 0.0
        ratio = max(0.0, min(float(opacity), 1.0))
        if ratio <= 0:
            return base_color
        red = int(base_color[1:3], 16)
        green = int(base_color[3:5], 16)
        blue = int(base_color[5:7], 16)
        mixed = (
            int(red * (1 - ratio) + 255 * ratio),
            int(green * (1 - ratio) + 255 * ratio),
            int(blue * (1 - ratio) + 255 * ratio),
        )
        return "#{:02X}{:02X}{:02X}".format(*mixed)

    def _get_surface_fg_color(self, base_color: str, *, allow_transparent: bool = False) -> str:
        """返回当前表面应使用的前景色。"""
        if allow_transparent and self.surface_style.get("enable_glass", True):
            return "transparent"
        return self._get_glass_overlay_color(base_color)

    def _get_component_corner_radius(self, default_radius: int = 12) -> int:
        """组件圆角跟随 surface_style，同时保留合理下限。"""
        return max(6, min(self._get_surface_corner_radius(), default_radius))

    def _button_surface_kwargs(self, *, primary: bool = False) -> dict:
        """统一按钮玻璃/圆角样式。"""
        fg_color = self.colors["primary_button"] if primary else self.colors["button_color"]
        hover_color = self.colors["primary_button_hover"] if primary else self.colors["button_hover"]
        text_color = self.colors["primary_text"] if primary else self.colors["text_color"]
        return {
            "corner_radius": self._get_component_corner_radius(),
            "fg_color": self._get_surface_fg_color(fg_color),
            "hover_color": self._get_surface_fg_color(hover_color),
            "text_color": text_color,
            "border_width": 1,
            "border_color": self.colors["border_color"],
        }

    def _entry_surface_kwargs(self, *, border_color: str | None = None, allow_transparent: bool = False) -> dict:
        """统一输入类组件玻璃/圆角样式。"""
        return {
            "corner_radius": self._get_component_corner_radius(),
            "fg_color": self._get_surface_fg_color(self.colors["input_box_color"], allow_transparent=allow_transparent),
            "border_width": 1,
            "border_color": border_color or self.colors["border_color"],
            "text_color": self.colors["text_color"],
        }

    def _option_menu_surface_kwargs(self) -> dict:
        """统一下拉组件玻璃/圆角样式。"""
        return {
            "corner_radius": self._get_component_corner_radius(),
            "fg_color": self._get_surface_fg_color(self.colors["button_color"]),
            "button_color": self._get_surface_fg_color(self.colors["primary_button"]),
            "button_hover_color": self._get_surface_fg_color(self.colors["primary_button_hover"]),
            "text_color": self.colors["text_color"],
            "dropdown_fg_color": self._get_surface_fg_color(self.colors["card_color"]),
            "dropdown_text_color": self.colors["text_color"],
            "dropdown_hover_color": self._get_surface_fg_color(self.colors["button_hover"]),
        }

    def _checkbox_surface_kwargs(self) -> dict:
        """统一复选框玻璃/圆角样式。"""
        return {
            "corner_radius": self._get_component_corner_radius(10),
            "fg_color": self._get_surface_fg_color(self.colors["primary_button"]),
            "hover_color": self._get_surface_fg_color(self.colors["primary_button_hover"]),
            "border_color": self.colors["border_color"],
            "checkmark_color": self.colors["primary_text"],
            "text_color": self.colors["text_color"],
        }

    def _get_input_border_color(self) -> str:
        """根据当前模式返回输入区边框颜色。"""
        return self.colors["exec_mode_border"] if self.exec_mode else self.colors["border_color"]

    def _update_exec_mode_style(self) -> None:
        """刷新执行模式下的输入区高亮和按钮样式。"""
        if not hasattr(self, "input_box"):
            return
        border_color = self._get_input_border_color()
        border_width = 2 if self.exec_mode else 1
        self.input_card.configure(border_color=border_color, border_width=border_width)
        self.input_box.configure(border_color=border_color, border_width=border_width)
        if hasattr(self, "exec_button"):
            if self.exec_mode:
                self.exec_button.configure(
                    text="退出执行",
                    fg_color=self._get_surface_fg_color(self.colors["exec_mode_button"]),
                    hover_color=self._get_surface_fg_color(self.colors["exec_mode_button_hover"]),
                    text_color="#5F4B00",
                    border_color=self.colors["exec_mode_border"],
                    corner_radius=self._get_component_corner_radius(),
                )
            else:
                self.exec_button.configure(
                    text="执行模式",
                    fg_color=self._get_surface_fg_color(self.colors["button_color"]),
                    hover_color=self._get_surface_fg_color(self.colors["button_hover"]),
                    text_color=self.colors["text_color"],
                    border_color=self.colors["border_color"],
                    corner_radius=self._get_component_corner_radius(),
                )
        if hasattr(self, "input_hint_label"):
            hint = "执行模式已开启，发送时会自动添加 /exec 前缀" if self.exec_mode else "输入普通消息或使用 /add、/endsession、/rmsession、/rm、/exec、/session、/skill add、/skill 指令"
            hint_color = self.colors["exec_mode_hint"] if self.exec_mode else self.colors["subtext_color"]
            self.input_hint_label.configure(text=hint, text_color=hint_color)

    def _set_exec_mode(self, enabled: bool) -> None:
        """切换执行模式。"""
        self.exec_mode = bool(enabled)
        self._update_exec_mode_style()

    def _toggle_exec_mode(self) -> None:
        """点击按钮时切换执行模式。"""
        if self._is_session_busy(self.selected_session_id):
            return
        self._set_exec_mode(not self.exec_mode)

    def _normalize_window_dimension(self, value, *, minimum: int, maximum: int, fallback: int) -> int:
        """把窗口宽高限制在可显示范围内。"""
        try:
            dimension = int(value)
        except (TypeError, ValueError):
            dimension = fallback
        return max(minimum, min(dimension, maximum))

    def _apply_window_geometry(self, *, center: bool) -> None:
        """应用固定窗口大小，可选居中到屏幕中央。"""
        self.root.update_idletasks()
        if center:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            pos_x = max((screen_width - self.window_width) // 2, 0)
            pos_y = max((screen_height - self.window_height) // 2, 0)
            self.root.geometry(f"{self.window_width}x{self.window_height}+{pos_x}+{pos_y}")
        else:
            self.root.geometry(f"{self.window_width}x{self.window_height}")

    def _center_toplevel_to_root(self, window, *, width: int, height: int) -> None:
        """把弹出窗口相对主窗口居中显示。"""
        self.root.update_idletasks()
        window.update_idletasks()

        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()

        if root_width <= 1 or root_height <= 1:
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            pos_x = max((screen_width - width) // 2, 0)
            pos_y = max((screen_height - height) // 2, 0)
        else:
            pos_x = max(root_x + (root_width - width) // 2, 0)
            pos_y = max(root_y + (root_height - height) // 2, 0)

        window.geometry(f"{width}x{height}+{pos_x}+{pos_y}")

    def _sync_scrollable_canvas_surface(self, scrollable_widget, color: str) -> None:
        """同步 CTkScrollableFrame 内部 canvas 背景，避免露出白色直角底色。"""
        canvas = getattr(scrollable_widget, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            canvas.configure(bg=color, highlightthickness=0, bd=0)
        except Exception:
            pass

    def _refresh_scrollable_canvas_layout(self, scrollable_widget, *, yview: float | None = None) -> None:
        """强制刷新 CTkScrollableFrame 内部 canvas 布局，避免切换内容后残留旧 scrollregion。"""
        canvas = getattr(scrollable_widget, "_parent_canvas", None)
        if canvas is None:
            return
        scrollable_widget.update_idletasks()
        canvas.update_idletasks()
        window_id = getattr(scrollable_widget, "_create_window_id", None)
        if window_id is not None:
            try:
                canvas.itemconfigure(window_id, width=canvas.winfo_width())
            except Exception:
                pass
        bbox = canvas.bbox("all")
        canvas.configure(scrollregion=bbox or (0, 0, 0, 0))
        if yview is not None:
            try:
                canvas.yview_moveto(yview)
            except Exception:
                pass

    def _load_available_fonts(self) -> list[str]:
        """读取当前系统可用字体名称。"""
        try:
            families = sorted(
                {
                    name
                    for name in tkfont.families(self.root)
                    if str(name).strip() and not str(name).strip().startswith("@")
                }
            )
        except Exception:
            families = []
        current_family = self._normalize_font_family(self.font_settings.get("family", "宋体"))
        if current_family not in families:
            families.insert(0, current_family)
        return families

    def _make_ctk_font(self, size: int, *, force_bold: bool = False) -> ctk.CTkFont:
        """统一创建 CTkFont，兼容旧版 customtkinter 不支持 slant 的情况。"""
        family = self._normalize_font_family(self.font_settings.get("family", "宋体"))
        weight = "bold" if force_bold or self.font_settings.get("bold") else "normal"
        slant = "italic" if self.font_settings.get("italic") else "roman"
        try:
            return ctk.CTkFont(family=family, size=size, weight=weight, slant=slant)
        except TypeError:
            return ctk.CTkFont(family=family, size=size, weight=weight)

    def _make_tk_font(self, size: int, *, force_bold: bool = False) -> tkfont.Font:
        """为原生 Tk 文本控件创建字体。"""
        family = self._normalize_font_family(self.font_settings.get("family", "宋体"))
        weight = "bold" if force_bold or self.font_settings.get("bold") else "normal"
        slant = "italic" if self.font_settings.get("italic") else "roman"
        return tkfont.Font(family=family, size=size, weight=weight, slant=slant)

    def _build_fonts(self) -> None:
        """依据当前 GUI 配置重建字体对象。"""
        base_size = self._normalize_font_size(self.font_settings.get("size", 13))
        self.font_size_main = base_size
        self.font_size_title = base_size + 2
        self.font_size_small = max(base_size - 1, 9)
        self.font_size_reasoning = max(base_size - 2, 8)
        self.font_size_section = base_size + 5
        self.font_main = self._make_ctk_font(self.font_size_main)
        self.font_title = self._make_ctk_font(self.font_size_title, force_bold=True)
        self.font_small = self._make_ctk_font(self.font_size_small)
        self.font_reasoning = self._make_ctk_font(self.font_size_reasoning)
        self.font_section = self._make_ctk_font(self.font_size_section, force_bold=True)

    def _apply_window_icon(self) -> None:
        """为 GUI 设置窗口图标；若图标不可用则静默跳过。"""
        icon_path = BASE_DIR / "icon.ico"
        if not icon_path.exists():
            return

        try:
            self.root.iconbitmap(icon_path)
        except Exception:
            # 部分 Tk 环境或打包场景下可能不支持设置 ico，失败时不影响主界面启动。
            pass

    def _set_startup_window_state(self) -> None:
        """启动时按当前窗口尺寸居中显示。"""
        self._apply_window_geometry(center=True)

    def _load_session(self) -> None:
        """从当前运行时读取会话信息，并同步更新界面状态变量。"""
        info = self.runtime.get_runtime_info()
        self.restored = info["restored"]
        self.selected_session_id = info["session_id"]
        self.start_time_var.set(info["start_time"])
        self.model_var.set(info["model"])
        self.stream_var.set("已开启" if info["stream"] else "已关闭")
        self.reasoning_var.set("显示" if info["show_reasoning"] else "隐藏")
        self.instructions_var.set("、".join(info["instructions"]) if info["instructions"] else "暂无")

    def _build_session_task_state(self) -> dict:
        """为单个 session 构造运行中状态。"""
        return {
            "busy": False,
            "request_kind": "",
            "pending_user_display": "",
            "draft_reasoning": "",
            "draft_answer": "",
            "draft_process": "",
            "notices": [],
            "answer_started": False,
            "reasoning_started": False,
            "current_answer_widget": None,
            "current_reasoning_widget": None,
            "current_process_widget": None,
        }

    def _get_session_task_state(self, session_id: str | None) -> dict:
        """按需获取并初始化某个 session 的运行状态。"""
        key = str(session_id or "").strip()
        if key not in self.session_task_states:
            self.session_task_states[key] = self._build_session_task_state()
        return self.session_task_states[key]

    def _is_session_busy(self, session_id: str | None = None) -> bool:
        """判断指定 session 是否仍有请求在运行。"""
        return bool(self._get_session_task_state(session_id).get("busy", False))

    def _has_any_busy_session(self) -> bool:
        """判断当前是否存在任意运行中的 session。"""
        return any(bool(state.get("busy", False)) for state in self.session_task_states.values())

    def _sync_busy_flag(self) -> None:
        """把全局 busy 同步为“是否存在任意运行中的 session”。"""
        self.busy = self._has_any_busy_session()

    def _reset_session_stream_state(self, session_id: str, *, keep_pending_user: bool = True) -> None:
        """重置指定 session 的流式输出缓存。"""
        state = self._get_session_task_state(session_id)
        pending_user_display = state.get("pending_user_display", "") if keep_pending_user else ""
        busy = bool(state.get("busy", False))
        request_kind = state.get("request_kind", "")
        state.clear()
        state.update(self._build_session_task_state())
        state["busy"] = busy
        state["request_kind"] = request_kind
        state["pending_user_display"] = pending_user_display
        if str(session_id).strip() == self.selected_session_id:
            self.answer_started = False
            self.reasoning_started = False
            self.current_answer_widget = None
            self.current_reasoning_widget = None

    def _set_session_busy(self, session_id: str, busy: bool, request_kind: str = "") -> None:
        """切换某个 session 的忙碌状态。"""
        state = self._get_session_task_state(session_id)
        state["busy"] = bool(busy)
        state["request_kind"] = request_kind if busy else ""
        if not busy:
            state["current_answer_widget"] = None
            state["current_reasoning_widget"] = None
            state["current_process_widget"] = None
        self._sync_busy_flag()
        self._sync_action_button_states()

    def _make_card(self, parent, fg_color=None):
        """创建统一风格的卡片容器。"""
        if fg_color is None:
            fg_color = self.colors["card_color"]
        return ctk.CTkFrame(
            parent,
            fg_color=self._get_surface_fg_color(fg_color),
            corner_radius=self._get_surface_corner_radius(),
            border_width=1,
            border_color=self.colors["border_color"],
        )

    def _build_ui(self) -> None:
        """严格按 2:8 左右、7:3 上下比例构建主界面。"""
        self.shell = ctk.CTkFrame(self.root, fg_color=self.colors["bg_color"], corner_radius=0)
        self.shell.pack(fill="both", expand=True, padx=16, pady=16)
        self.shell.grid_rowconfigure(0, weight=1)
        self.shell.grid_columnconfigure(0, weight=2)
        self.shell.grid_columnconfigure(1, weight=8)

        self.left_panel = self._make_card(self.shell, fg_color=self.colors["panel_color"])
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.left_panel.grid_rowconfigure(2, weight=1)
        self.left_panel.grid_rowconfigure(3, weight=0)
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.right_panel = ctk.CTkFrame(self.shell, fg_color="transparent", corner_radius=0)
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(0, weight=7)
        self.right_panel.grid_rowconfigure(1, weight=3)

        self._build_session_list_panel(self.left_panel)
        self._build_chat_panel(self.right_panel)
        self._build_input_panel(self.right_panel)

    def _build_session_list_panel(self, parent) -> None:
        """左侧会话列表区域，支持滚动。"""
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 4))
        header.grid_columnconfigure(0, weight=1)

        self.session_title_label = ctk.CTkLabel(
            header,
            text="会话列表",
            font=self.font_section,
            text_color=self.colors["text_color"],
        )
        self.session_title_label.grid(row=0, column=0, sticky="w")

        self.settings_button = ctk.CTkButton(
            header,
            text="\u2699",
            command=self._open_settings_window,
            width=36,
            height=36,
            font=self.font_title,
            **self._button_surface_kwargs(),
        )
        self.settings_button.grid(row=0, column=1, sticky="e")

        self.session_count_label = ctk.CTkLabel(
            parent,
            textvariable=self.session_count_var,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        )
        self.session_count_label.grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

        self.session_scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color=self._get_surface_fg_color(self.colors["card_color"]),
            corner_radius=self._get_surface_corner_radius(),
            border_width=1,
            border_color=self.colors["border_color"],
        )
        self.session_scroll.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 14))
        self.session_scroll.grid_columnconfigure(0, weight=1)
        self._sync_scrollable_canvas_surface(self.session_scroll, self._get_surface_fg_color(self.colors["card_color"]))

        self.command_card = self._make_card(parent, fg_color=self.colors["panel_color"])
        self.command_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))
        self.command_card.grid_columnconfigure(0, weight=1)
        self.command_card.grid_columnconfigure(1, weight=1)

        self.command_title_label = ctk.CTkLabel(
            self.command_card,
            text="命令组件",
            font=self.font_section,
            text_color=self.colors["text_color"],
        )
        self.command_title_label.grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(12, 8))

        self.add_button = ctk.CTkButton(
            self.command_card,
            text="新增会话",
            command=lambda: self._handle_input("/add"),
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.add_button.grid(row=1, column=0, sticky="ew", padx=(14, 6), pady=(0, 8))

        self.endsession_button = ctk.CTkButton(
            self.command_card,
            text="结束此次会话",
            command=lambda: self._handle_input("/endsession"),
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.endsession_button.grid(row=1, column=1, sticky="ew", padx=(6, 14), pady=(0, 8))

        self.rm_button = ctk.CTkButton(
            self.command_card,
            text="删除所有会话",
            command=lambda: self._handle_input("/rm"),
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.rm_button.grid(row=2, column=0, sticky="ew", padx=(14, 6), pady=(0, 8))

        self.exec_button = ctk.CTkButton(
            self.command_card,
            text="执行模式",
            command=self._toggle_exec_mode,
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.exec_button.grid(row=2, column=1, sticky="ew", padx=(6, 14), pady=(0, 8))

        self.command_hint_label = ctk.CTkLabel(
            self.command_card,
            text="支持 /add、/endsession、/rmsession <session_id>、/rm、/session、/exec、/skill add、/skill",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            anchor="w",
            justify="left",
            wraplength=260,
        )
        self.command_hint_label.grid(row=4, column=0, columnspan=2, sticky="ew", padx=14, pady=(0, 12))

        self.learn_skill_button = ctk.CTkButton(
            self.command_card,
            text="学习技能",
            command=lambda: self._handle_input("/skill add"),
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.learn_skill_button.grid(row=3, column=0, sticky="ew", padx=(14, 6), pady=(0, 8))

    def _build_chat_panel(self, parent) -> None:
        """右侧上半区聊天显示区域，占主界面高度 70%。"""
        self.chat_card = self._make_card(parent)
        self.chat_card.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        self.chat_card.grid_rowconfigure(2, weight=1)
        self.chat_card.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(self.chat_card, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        header.grid_columnconfigure(0, weight=1)

        self.chat_title_label = ctk.CTkLabel(
            header,
            text="聊天区域",
            font=self.font_section,
            text_color=self.colors["text_color"],
        )
        self.chat_title_label.grid(row=0, column=0, sticky="w")

        self.chat_status_label = ctk.CTkLabel(
            header,
            textvariable=self.status_var,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        )
        self.chat_status_label.grid(row=0, column=1, sticky="e")

        self.detail_label = ctk.CTkLabel(
            self.chat_card,
            textvariable=self.detail_var,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            justify="left",
            anchor="w",
            wraplength=860,
        )
        self.detail_label.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 10))

        self.chat_scroll = ctk.CTkScrollableFrame(
            self.chat_card,
            corner_radius=self._get_surface_corner_radius(),
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            border_color=self.colors["border_color"],
            border_width=1,
        )
        self.chat_scroll.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        self.chat_scroll.grid_columnconfigure(0, weight=1)
        self._sync_scrollable_canvas_surface(self.chat_scroll, self._get_surface_fg_color(self.colors["panel_color"]))
        self._bind_chat_drag_scroll_target(self.chat_scroll)
        canvas = getattr(self.chat_scroll, "_parent_canvas", None)
        if canvas is not None:
            self._bind_chat_drag_scroll_target(canvas)

    def _build_input_panel(self, parent) -> None:
        """右侧下半区输入区域，占主界面高度 30%。"""
        self.input_card = self._make_card(parent, fg_color=self.colors["panel_color"])
        self.input_card.grid(row=1, column=0, sticky="nsew")
        self.input_card.grid_rowconfigure(1, weight=1)
        self.input_card.grid_columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(self.input_card, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 10))
        top_row.grid_columnconfigure(0, weight=1)
        top_row.grid_columnconfigure(1, weight=0)

        info_text = (
            f"用户：{self.user_var.get()}   "
            f"开始时间：{self.start_time_var.get()}   "
            f"模型：{self.model_var.get()}   "
            "快捷键：回车发送，Ctrl+Enter 换行"
        )
        self.input_info_label = ctk.CTkLabel(
            top_row,
            text=info_text,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            anchor="w",
            justify="left",
        )
        self.input_info_label.grid(row=0, column=0, sticky="w")

        self.input_box = ctk.CTkTextbox(
            self.input_card,
            height=90,
            font=self.font_main,
            wrap="word",
            **self._entry_surface_kwargs(allow_transparent=True),
        )
        self.input_box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 10))
        self.input_box.bind("<Return>", self._send_from_enter)
        self.input_box.bind("<Control-Return>", self._insert_newline)

        attachment_row = ctk.CTkFrame(self.input_card, fg_color="transparent")
        attachment_row.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        attachment_row.grid_columnconfigure(1, weight=1)

        self.attach_button = ctk.CTkButton(
            attachment_row,
            text="选择附件",
            command=self._choose_attachments,
            width=96,
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.attach_button.grid(row=0, column=0, padx=(0, 10))

        self.attachment_label = ctk.CTkLabel(
            attachment_row,
            textvariable=self.attachment_var,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            anchor="w",
            justify="left",
        )
        self.attachment_label.grid(row=0, column=1, sticky="ew")

        self.clear_attachments_button = ctk.CTkButton(
            attachment_row,
            text="清空附件",
            command=self._clear_attachments,
            width=92,
            height=34,
            font=self.font_main,
            state="disabled",
            **self._button_surface_kwargs(),
        )
        self.clear_attachments_button.grid(row=0, column=2, padx=(10, 0))

        bottom_row = ctk.CTkFrame(self.input_card, fg_color="transparent")
        bottom_row.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        bottom_row.grid_columnconfigure(0, weight=1)

        self.input_hint_label = ctk.CTkLabel(
            bottom_row,
            text="输入普通消息或使用 /add、/endsession、/rmsession、/rm、/exec、/session、/skill add、/skill 指令",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        )
        self.input_hint_label.grid(row=0, column=0, sticky="w")

        self.send_button = ctk.CTkButton(
            bottom_row,
            text="发送",
            command=self._send_input,
            width=120,
            height=38,
            font=self.font_title,
            **self._button_surface_kwargs(primary=True),
        )
        self.send_button.grid(row=0, column=1, sticky="e")
        self._update_exec_mode_style()

    def _build_session_items(self):
        """构建真实 session 列表，GUI 与 CLI 共用同一数据源。"""
        items = []
        for session in self.runtime.list_sessions():
            title = str(session.get("summary_title", "")).strip() or str(session.get("title", "")).strip() or session["session_id"]
            start_time = str(session.get("start_time", "")).strip()
            date_text = start_time or session["session_id"]
            if session.get("archived") and session.get("end_time"):
                end_time = str(session.get("end_time", "")).strip()
                if end_time:
                    date_text = f"{date_text}\n{end_time}"
            state = self._get_session_task_state(session["session_id"])
            status_marks = []
            if session.get("is_current"):
                status_marks.append("当前")
            if not session.get("archived"):
                status_marks.append("进行中")
            if state.get("busy"):
                if state.get("request_kind") == "exec":
                    status_marks.append("exec 中")
                else:
                    status_marks.append("调用中")
            if status_marks:
                date_text = f"{date_text}\n{' / '.join(status_marks)}"
            items.append(
                {
                    "id": session["session_id"],
                    "title": title,
                    "meta": date_text,
                    "kind": "active" if session.get("is_current") else "history",
                }
            )
        self.session_count_var.set(f"{len(items)} 个会话")
        return items

    def _refresh_session_list(self, selected_id: str | None = None) -> None:
        """刷新左侧会话列表视图。"""
        self.session_items = self._build_session_items()
        valid_ids = {item["id"] for item in self.session_items}
        if not self.session_items:
            self.selected_session_id = ""
        elif selected_id is not None and selected_id in valid_ids:
            self.selected_session_id = selected_id
        elif self.selected_session_id not in valid_ids:
            self.selected_session_id = self.session_items[0]["id"]

        for child in self.session_scroll.winfo_children():
            child.destroy()

        self.session_buttons = []
        for index, item in enumerate(self.session_items):
            is_selected = item["id"] == self.selected_session_id
            card = ctk.CTkFrame(
                self.session_scroll,
                fg_color=self._get_surface_fg_color(self.colors["selected_color"] if is_selected else self.colors["card_color"]),
                corner_radius=self._get_surface_corner_radius(),
                border_width=1,
                border_color="#C8D6E5" if is_selected else self.colors["border_color"],
            )
            card.grid(row=index, column=0, sticky="ew", pady=(0, 8))
            card.grid_columnconfigure(0, weight=1)

            title_label = ctk.CTkLabel(
                card,
                text=item["title"],
                text_color=self.colors["text_color"],
                font=self.font_main,
                anchor="w",
                justify="left",
            )
            title_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 2))

            meta_label = ctk.CTkLabel(
                card,
                text=item.get("meta", ""),
                text_color=self.colors["subtext_color"],
                font=self.font_small,
                anchor="w",
                justify="left",
            )
            meta_label.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))

            for widget in (card, title_label, meta_label):
                widget.bind("<Button-1>", lambda _event, current=item: self._select_session_item(current))

            self.session_buttons.append(card)

    def _select_session_item(self, item: dict) -> None:
        """点击左侧项时立即切换到对应 session，并完整重建聊天记录。"""
        try:
            session = self.runtime.switch_session(item["id"])
        except ValueError as exc:
            messagebox.showerror("切换失败", str(exc))
            return

        self.selected_session_id = item["id"]
        self.start_time_var.set(session.get("start_time", ""))
        self._refresh_session_list(selected_id=item["id"])
        self._render_current_session_history()
        self._sync_action_button_states()
        self.status_var.set("会话已切换")
        self.detail_var.set(f"当前选中 session：{item['id']}")
        self._update_input_info()

    def _render_start_message(self) -> None:
        """启动时渲染当前 session；若无消息则显示系统提示。"""
        self._render_current_session_history()
        if self.restored:
            self.status_var.set("会话已恢复")
            self.detail_var.set("已加载当前 session 的完整历史记录")
        else:
            self.status_var.set("新会话")
            self.detail_var.set("当前已创建新会话，可以开始输入内容")
        self._update_input_info()

    def _update_input_info(self) -> None:
        """刷新输入面板顶部的会话信息。"""
        info_text = (
            f"用户：{self.user}   "
            f"模型：{self.model_var.get()}   "
            "快捷键：回车发送，Ctrl+Enter 换行"
        )
        self.input_info_label.configure(text=info_text)

    def _render_current_session_history(self) -> None:
        """把当前 session 的完整 history 按顺序重建到聊天区。"""
        self._clear_chat()
        session_id = self.selected_session_id or self.runtime.session.get("session_id", "")
        session = self.runtime.get_session(session_id)
        history = self.runtime.get_session_history(session_id)
        if not history:
            self._append_chat_line(f"系统：当前会话为空。开始时间：{session.get('start_time', '')}")
        else:
            for item in history:
                role = item.get("role")
                content = item.get("content", "")
                if role == "user":
                    self._append_chat_line(f"你：{content}")
                elif role == "system":
                    self._append_chat_line(f"系统：{content}")
                else:
                    self._append_chat_line(f"AI：{content}")

        self.start_time_var.set(session.get("start_time", ""))
        self._render_pending_session_state(session_id)
        self._scroll_chat_to_bottom()

    def _render_pending_session_state(self, session_id: str) -> None:
        """把指定 session 尚未落盘的流式内容重建到当前聊天区。"""
        state = self._get_session_task_state(session_id)
        pending_user_display = str(state.get("pending_user_display", "")).strip()
        if pending_user_display:
            self._append_chat_line(f"你：{pending_user_display}")
        for notice in state.get("notices", []):
            if str(notice).strip():
                self._append_chat_line(str(notice))
        process_text = str(state.get("draft_process", "")).strip()
        if process_text:
            widget = self._create_bubble("process", "流程：")
            self._set_process_widget_body(widget, process_text)
            state["current_process_widget"] = widget
        reasoning_text = str(state.get("draft_reasoning", ""))
        if reasoning_text:
            widget = self._create_bubble("thinking", "思考：")
            self.current_reasoning_widget = widget
            state["current_reasoning_widget"] = widget
            widget._message_body = reasoning_text
            self._render_plain_message_widget(widget)
        answer_text = str(state.get("draft_answer", ""))
        if answer_text:
            widget = self._create_bubble("assistant", "AI：")
            self.current_answer_widget = widget
            state["current_answer_widget"] = widget
            widget._message_body = answer_text
            self._render_plain_message_widget(widget)

    def _clear_chat(self) -> None:
        """清空聊天显示区域。"""
        current_state = self._get_session_task_state(self.selected_session_id)
        current_state["current_answer_widget"] = None
        current_state["current_reasoning_widget"] = None
        current_state["current_process_widget"] = None
        for item in self.chat_bubble_widgets:
            item["outer"].destroy()
        self.chat_bubble_widgets = []
        self.current_answer_widget = None
        self.current_reasoning_widget = None
        self._refresh_scrollable_canvas_layout(self.chat_scroll, yview=0.0)

    def _scroll_chat_to_bottom(self) -> None:
        """新增消息后滚动到底部。"""
        self.root.update_idletasks()
        self._refresh_scrollable_canvas_layout(self.chat_scroll)
        canvas = getattr(self.chat_scroll, "_parent_canvas", None)
        if canvas is not None:
            canvas.yview_moveto(1.0)

    def _resolve_bubble_style(self, role: str) -> dict:
        """根据消息角色生成聊天气泡样式。"""
        style = {
            "bubble_color": self.colors["system_bubble"],
            "text_color": self.colors["subtext_color"],
            "font": self._make_tk_font(self.font_size_small),
            "sticky": "w",
            "pad_x": (0, 180),
            "width": 58,
        }
        if role == "user":
            style.update(
                {
                    "bubble_color": self.colors["user_bubble"],
                    "text_color": self.colors["text_color"],
                    "font": self._make_tk_font(self.font_size_main),
                    "sticky": "e",
                    "pad_x": (180, 0),
                    "width": 58,
                }
            )
        elif role == "assistant":
            style.update(
                {
                    "bubble_color": self.colors["ai_bubble"],
                    "text_color": self.colors["text_color"],
                    "font": self._make_tk_font(self.font_size_main),
                    "sticky": "w",
                    "pad_x": (0, 180),
                    "width": 58,
                }
            )
        elif role == "thinking":
            style.update(
                {
                    "bubble_color": self.colors["thinking_bubble"],
                    "text_color": self.colors["reasoning_color"],
                    "font": self._make_tk_font(self.font_size_reasoning),
                    "sticky": "w",
                    "pad_x": (0, 220),
                    "width": 48,
                }
            )
        elif role == "process":
            style.update(
                {
                    "bubble_color": self.colors["thinking_bubble"],
                    "text_color": self.colors["subtext_color"],
                    "font": self._make_tk_font(self.font_size_small),
                    "sticky": "w",
                    "pad_x": (0, 180),
                    "width": 60,
                }
            )
        return style

    def _bind_chat_text_widget(self, widget: tk.Text) -> None:
        """为只读聊天文本绑定复制相关快捷操作。"""
        widget.bind("<Control-c>", lambda event, current=widget: self._copy_selected_text(current))
        widget.bind("<Control-a>", lambda event, current=widget: self._select_all_text(current))
        widget.bind("<Button-3>", lambda event, current=widget: self._show_text_menu(current, event))
        widget.bind("<MouseWheel>", self._forward_chat_mousewheel)
        widget.bind("<Shift-MouseWheel>", self._forward_chat_mousewheel)
        widget.bind("<Button-4>", self._forward_chat_mousewheel)
        widget.bind("<Button-5>", self._forward_chat_mousewheel)
        self._bind_chat_drag_scroll_target(widget)

    def _bind_chat_drag_scroll_target(self, widget) -> None:
        """让聊天区任意可见控件都支持中键拖动滚动。"""
        widget.bind("<ButtonPress-2>", self._start_chat_middle_drag, add="+")
        widget.bind("<B2-Motion>", self._drag_chat_middle_scroll, add="+")
        widget.bind("<ButtonRelease-2>", self._stop_chat_middle_drag, add="+")

    def _start_chat_middle_drag(self, event) -> str:
        """按下中键时记录当前位置，进入聊天区拖动滚动模式。"""
        self.chat_middle_drag_active = True
        self.chat_middle_drag_last_y = int(getattr(event, "y_root", 0))
        return "break"

    def _drag_chat_middle_scroll(self, event) -> str:
        """按住中键上下拖动时，驱动聊天区纵向滚动。"""
        canvas = getattr(self.chat_scroll, "_parent_canvas", None)
        if canvas is None or not self.chat_middle_drag_active:
            return "break"
        current_y = int(getattr(event, "y_root", 0))
        delta = current_y - self.chat_middle_drag_last_y
        if delta == 0:
            return "break"
        step = max(1, abs(delta) // 8)
        canvas.yview_scroll(-step if delta > 0 else step, "units")
        self.chat_middle_drag_last_y = current_y
        return "break"

    def _stop_chat_middle_drag(self, _event=None) -> str:
        """释放中键后结束聊天区拖动滚动状态。"""
        self.chat_middle_drag_active = False
        return "break"

    def _forward_chat_mousewheel(self, event) -> str:
        """阻止气泡内部滚动，并把滚轮交给外层聊天列表。"""
        canvas = getattr(self.chat_scroll, "_parent_canvas", None)
        if canvas is None:
            return "break"
        event_num = getattr(event, "num", None)
        delta = getattr(event, "delta", 0)
        if event_num == 4:
            step = -1
        elif event_num == 5:
            step = 1
        else:
            if delta == 0:
                return "break"
            step = -1 if delta > 0 else 1
        canvas.yview_scroll(step, "units")
        return "break"

    def _copy_selected_text(self, widget: tk.Text):
        """复制当前文本框选中的内容。"""
        try:
            selected_text = widget.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.root.clipboard_clear()
        self.root.clipboard_append(selected_text)
        return "break"

    def _handle_font_list_mousewheel(self, event) -> str:
        """让字体列表可通过鼠标滚轮滚动。"""
        if self.font_listbox is None or not self.font_listbox.winfo_exists():
            return "break"
        delta = event.delta
        if delta == 0:
            return "break"
        step = -1 if delta > 0 else 1
        self.font_listbox.yview_scroll(step, "units")
        return "break"

    def _set_font_from_list(self, _event=None) -> None:
        """从字体列表选择后同步到当前字体变量。"""
        if self.font_listbox is None:
            return
        selection = self.font_listbox.curselection()
        if not selection:
            return
        selected_family = self.font_listbox.get(selection[0])
        self.settings_vars["family"].set(self._normalize_font_family(selected_family))

    def _sync_font_list_selection(self) -> None:
        """尽量让字体列表跟随当前输入的字体名。"""
        if self.font_listbox is None or not self.font_listbox.winfo_exists() or "family" not in self.settings_vars:
            return
        current_family = self._normalize_font_family(self.settings_vars["family"].get())
        try:
            match_index = self.available_fonts.index(current_family)
        except ValueError:
            self.font_listbox.selection_clear(0, "end")
            return
        self.font_listbox.selection_clear(0, "end")
        self.font_listbox.selection_set(match_index)
        self.font_listbox.activate(match_index)
        self.font_listbox.see(match_index)

    def _select_all_text(self, widget: tk.Text):
        """选中当前气泡的全部文本。"""
        widget.tag_add("sel", "1.0", "end-1c")
        widget.mark_set("insert", "1.0")
        widget.see("insert")
        return "break"

    def _show_text_menu(self, widget: tk.Text, event) -> str:
        """右键菜单，便于复制聊天内容。"""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="复制", command=lambda current=widget: self._copy_selected_text(current))
        menu.add_command(label="全选", command=lambda current=widget: self._select_all_text(current))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _split_message_prefix(self, role: str, text: str) -> tuple[str, str]:
        """拆分消息前缀和正文，便于正文按 Markdown 渲染。"""
        prefix_map = {
            "user": "",
            "assistant": "",
            "thinking": "思考：",
            "process": "流程：",
            "system": "系统：",
        }
        if role == "user" and text.startswith("你："):
            return "", text[len("你：") :].lstrip()
        if role == "assistant" and text.startswith("AI："):
            return "", text[len("AI：") :].lstrip()
        prefix = prefix_map.get(role, "")
        if prefix and text.startswith(prefix):
            return prefix, text[len(prefix) :].lstrip()
        if role == "thinking" and text.startswith("流程："):
            return "流程：", text[len("流程：") :].lstrip()
        return "", text

    def _configure_markdown_tags(self, widget: tk.Text, style: dict) -> None:
        """为当前聊天气泡配置 Markdown 富文本标签。"""
        base_font = style["font"]
        base_size = abs(int(base_font.cget("size")))
        base_family = str(base_font.cget("family"))

        bold_font = tkfont.Font(font=base_font)
        bold_font.configure(weight="bold")
        italic_font = tkfont.Font(font=base_font)
        italic_font.configure(slant="italic")
        bold_italic_font = tkfont.Font(font=base_font)
        bold_italic_font.configure(weight="bold", slant="italic")
        strike_font = tkfont.Font(font=base_font)
        strike_font.configure(overstrike=1)
        code_inline_font = tkfont.Font(family="Consolas", size=max(base_size - 1, 9))
        code_block_font = tkfont.Font(family="Consolas", size=max(base_size - 1, 9))

        heading_fonts = {}
        for level, size_delta in ((1, 7), (2, 5), (3, 3), (4, 2), (5, 1), (6, 0)):
            heading_font = tkfont.Font(family=base_family, size=base_size + size_delta, weight="bold")
            heading_fonts[level] = heading_font

        widget._markdown_fonts = [
            bold_font,
            italic_font,
            bold_italic_font,
            strike_font,
            code_inline_font,
            code_block_font,
            *heading_fonts.values(),
        ]
        widget._link_tag_urls = {}
        link_tags = [tag for tag in widget.tag_names() if tag.startswith("md_link_")]
        if link_tags:
            widget.tag_delete(*link_tags)

        widget.tag_configure("md_prefix", font=bold_font, spacing3=4)
        widget.tag_configure("md_body", font=base_font)
        widget.tag_configure("md_bold", font=bold_font)
        widget.tag_configure("md_italic", font=italic_font)
        widget.tag_configure("md_bold_italic", font=bold_italic_font)
        widget.tag_configure("md_strike", font=strike_font)
        widget.tag_configure(
            "md_code_inline",
            font=code_inline_font,
            background=self.colors["panel_color"],
        )
        widget.tag_configure(
            "md_code_block",
            font=code_block_font,
            background=self.colors["panel_color"],
            lmargin1=12,
            lmargin2=12,
            spacing1=4,
            spacing3=4,
        )
        widget.tag_configure("md_quote", foreground=self.colors["reasoning_color"])
        widget.tag_configure("md_rule", foreground=self.colors["subtext_color"])
        widget.tag_configure("md_link", foreground="#2563EB", underline=True)
        for level, heading_font in heading_fonts.items():
            widget.tag_configure(
                f"md_h{level}",
                font=heading_font,
                spacing1=8 if level <= 2 else 4,
                spacing3=4,
            )

    def _insert_with_tags(self, widget: tk.Text, text: str, tags: tuple[str, ...] = ()) -> None:
        """向文本控件插入带标签的文本。"""
        if not text:
            return
        widget.insert("end", text, tags)

    def _ensure_blank_line(self, widget: tk.Text) -> None:
        """在块元素间插入一个空行，避免挤在一起。"""
        content = widget.get("1.0", "end-1c")
        if not content:
            return
        if content.endswith("\n\n"):
            return
        if content.endswith("\n"):
            widget.insert("end", "\n")
        else:
            widget.insert("end", "\n\n")

    def _register_link_tag(self, widget: tk.Text, url: str) -> str:
        """为链接创建独立 tag，并绑定点击事件。"""
        link_tag = f"md_link_{len(getattr(widget, '_link_tag_urls', {}))}"
        widget._link_tag_urls[link_tag] = url
        widget.tag_configure(link_tag, foreground="#2563EB", underline=True)
        widget.tag_bind(link_tag, "<Button-1>", lambda _event, target=url: webbrowser.open(target))
        widget.tag_bind(link_tag, "<Enter>", lambda _event, current=widget: current.configure(cursor="hand2"))
        widget.tag_bind(link_tag, "<Leave>", lambda _event, current=widget: current.configure(cursor="xterm"))
        return link_tag

    def _render_inline_tokens(
        self,
        widget: tk.Text,
        tokens,
        extra_tags: tuple[str, ...] = (),
        line_prefix: str = "",
        next_line_prefix: str | None = None,
    ) -> None:
        """渲染 Markdown 行内 token。"""
        if next_line_prefix is None:
            next_line_prefix = line_prefix

        active_tags: list[str] = []
        link_tags: list[str] = []
        for token in tokens or []:
            token_type = token.type
            if token_type == "text":
                self._insert_with_tags(widget, token.content, tuple(active_tags + link_tags) + extra_tags)
            elif token_type == "softbreak":
                self._insert_with_tags(widget, "\n" + next_line_prefix, tuple(extra_tags))
            elif token_type == "hardbreak":
                self._insert_with_tags(widget, "\n" + next_line_prefix, tuple(extra_tags))
            elif token_type == "code_inline":
                self._insert_with_tags(
                    widget,
                    token.content,
                    tuple(active_tags + link_tags) + extra_tags + ("md_code_inline",),
                )
            elif token_type == "strong_open":
                active_tags.append("md_bold")
            elif token_type == "strong_close":
                if "md_bold" in active_tags:
                    active_tags.remove("md_bold")
            elif token_type == "em_open":
                active_tags.append("md_italic")
            elif token_type == "em_close":
                if "md_italic" in active_tags:
                    active_tags.remove("md_italic")
            elif token_type == "s_open":
                active_tags.append("md_strike")
            elif token_type == "s_close":
                if "md_strike" in active_tags:
                    active_tags.remove("md_strike")
            elif token_type == "link_open":
                href = token.attrGet("href") or ""
                if href:
                    link_tags.append(self._register_link_tag(widget, href))
            elif token_type == "link_close":
                if link_tags:
                    link_tags.pop()
            elif token_type == "image":
                alt_text = token.content or "图片"
                src = token.attrGet("src") or ""
                fallback = f"[图片: {alt_text}]"
                if src:
                    fallback += f" ({src})"
                self._insert_with_tags(widget, fallback, tuple(active_tags + link_tags) + extra_tags)
            elif token_type == "html_inline":
                self._insert_with_tags(widget, token.content, tuple(active_tags + link_tags) + extra_tags)

    def _build_block_prefix(self, quote_depth: int = 0, indent_level: int = 0) -> str:
        """构造引用和列表缩进前缀。"""
        return ("  " * indent_level) + ("> " * quote_depth)

    def _render_table_block(self, widget: tk.Text, tokens, start_index: int, quote_depth: int) -> int:
        """把表格 token 渲染为等宽文本表格。"""
        rows = []
        current_row = []
        header_rows = 0
        index = start_index + 1
        while index < len(tokens):
            token = tokens[index]
            if token.type == "table_close":
                break
            if token.type == "thead_open":
                header_rows = 1
            elif token.type == "tr_open":
                current_row = []
            elif token.type in {"th_open", "td_open"}:
                if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
                    current_row.append(tokens[index + 1].content.strip())
            elif token.type == "tr_close" and current_row:
                rows.append(current_row)
            index += 1

        if not rows:
            return index + 1

        widths = []
        for row in rows:
            for col_index, cell in enumerate(row):
                if len(widths) <= col_index:
                    widths.append(len(cell))
                else:
                    widths[col_index] = max(widths[col_index], len(cell))

        prefix = self._build_block_prefix(quote_depth=quote_depth)
        rendered_lines = []
        for row_index, row in enumerate(rows):
            padded = [cell.ljust(widths[col]) for col, cell in enumerate(row)]
            rendered_lines.append(prefix + "| " + " | ".join(padded) + " |")
            if row_index == header_rows - 1:
                separator = ["-" * widths[col] for col in range(len(widths))]
                rendered_lines.append(prefix + "|-" + "-|-".join(separator) + "-|")

        self._ensure_blank_line(widget)
        self._insert_with_tags(widget, "\n".join(rendered_lines) + "\n", ("md_code_block",))
        return index + 1

    def _render_markdown_blocks(self, widget: tk.Text, tokens, start_index: int = 0, quote_depth: int = 0, list_stack=None, stop_type: str | None = None) -> int:
        """递归渲染 Markdown 块级 token。"""
        if list_stack is None:
            list_stack = []

        index = start_index
        while index < len(tokens):
            token = tokens[index]
            token_type = token.type
            if stop_type and token_type == stop_type:
                return index + 1

            if token_type == "bullet_list_open":
                list_stack.append({"type": "bullet"})
                index = self._render_markdown_blocks(widget, tokens, index + 1, quote_depth, list_stack, "bullet_list_close")
                list_stack.pop()
                continue

            if token_type == "ordered_list_open":
                start_value = int(token.attrGet("start") or 1)
                list_stack.append({"type": "ordered", "counter": start_value})
                index = self._render_markdown_blocks(widget, tokens, index + 1, quote_depth, list_stack, "ordered_list_close")
                list_stack.pop()
                continue

            if token_type == "blockquote_open":
                index = self._render_markdown_blocks(widget, tokens, index + 1, quote_depth + 1, list_stack, "blockquote_close")
                continue

            if token_type == "list_item_open":
                indent_level = max(len(list_stack) - 1, 0)
                current_list = list_stack[-1] if list_stack else {"type": "bullet"}
                if current_list["type"] == "ordered":
                    marker = f"{current_list['counter']}. "
                    current_list["counter"] += 1
                else:
                    marker = "- "

                first_prefix = self._build_block_prefix(quote_depth=quote_depth, indent_level=indent_level) + marker
                next_prefix = self._build_block_prefix(quote_depth=quote_depth, indent_level=indent_level) + (" " * len(marker))
                index += 1
                while index < len(tokens) and tokens[index].type != "list_item_close":
                    child = tokens[index]
                    if child.type == "paragraph_open":
                        inline_token = tokens[index + 1] if index + 1 < len(tokens) else None
                        self._ensure_blank_line(widget)
                        self._insert_with_tags(widget, first_prefix, ("md_quote",) if quote_depth else ())
                        if inline_token is not None and inline_token.type == "inline":
                            self._render_inline_tokens(
                                widget,
                                inline_token.children,
                                ("md_quote",) if quote_depth else (),
                                line_prefix=next_prefix,
                                next_line_prefix=next_prefix,
                            )
                        self._insert_with_tags(widget, "\n", ())
                        first_prefix = next_prefix
                        index += 3
                        continue
                    index = self._render_markdown_blocks(widget, tokens, index, quote_depth, list_stack)
                index += 1
                continue

            if token_type == "heading_open":
                level = int(token.tag[1]) if token.tag.startswith("h") else 1
                inline_token = tokens[index + 1] if index + 1 < len(tokens) else None
                self._ensure_blank_line(widget)
                prefix = self._build_block_prefix(quote_depth=quote_depth, indent_level=len(list_stack))
                if prefix:
                    self._insert_with_tags(widget, prefix, ("md_quote",))
                if inline_token is not None and inline_token.type == "inline":
                    extra_tags = (f"md_h{level}",) + (("md_quote",) if quote_depth else ())
                    self._render_inline_tokens(widget, inline_token.children, extra_tags, line_prefix=prefix, next_line_prefix=prefix)
                self._insert_with_tags(widget, "\n", ())
                index += 3
                continue

            if token_type == "paragraph_open":
                inline_token = tokens[index + 1] if index + 1 < len(tokens) else None
                self._ensure_blank_line(widget)
                prefix = self._build_block_prefix(quote_depth=quote_depth, indent_level=len(list_stack))
                if prefix:
                    self._insert_with_tags(widget, prefix, ("md_quote",))
                if inline_token is not None and inline_token.type == "inline":
                    self._render_inline_tokens(
                        widget,
                        inline_token.children,
                        ("md_quote",) if quote_depth else (),
                        line_prefix=prefix,
                        next_line_prefix=prefix,
                    )
                self._insert_with_tags(widget, "\n", ())
                index += 3
                continue

            if token_type in {"fence", "code_block"}:
                self._ensure_blank_line(widget)
                prefix = self._build_block_prefix(quote_depth=quote_depth, indent_level=len(list_stack))
                lines = token.content.rstrip("\n").splitlines() or [""]
                language = token.info.strip() if token_type == "fence" else ""
                if language:
                    lines.insert(0, f"[{language}]")
                rendered = "\n".join(prefix + line for line in lines)
                self._insert_with_tags(widget, rendered + "\n", ("md_code_block",))
                index += 1
                continue

            if token_type == "hr":
                self._ensure_blank_line(widget)
                self._insert_with_tags(widget, self._build_block_prefix(quote_depth=quote_depth) + "─" * 24 + "\n", ("md_rule",))
                index += 1
                continue

            if token_type == "table_open":
                index = self._render_table_block(widget, tokens, index, quote_depth)
                continue

            if token_type == "inline":
                self._ensure_blank_line(widget)
                prefix = self._build_block_prefix(quote_depth=quote_depth, indent_level=len(list_stack))
                if prefix:
                    self._insert_with_tags(widget, prefix, ("md_quote",))
                self._render_inline_tokens(
                    widget,
                    token.children,
                    ("md_quote",) if quote_depth else (),
                    line_prefix=prefix,
                    next_line_prefix=prefix,
                )
                self._insert_with_tags(widget, "\n", ())
            index += 1

        return index

    def _render_markdown_message(self, widget: tk.Text) -> None:
        """将消息按 Markdown 渲染到聊天气泡中。"""
        role = getattr(widget, "_message_role", "system")
        prefix = getattr(widget, "_message_prefix", "")
        body = getattr(widget, "_message_body", "")
        style = self._resolve_bubble_style(role)

        self._update_text_widget_width(widget, style, prefix, body)
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        self._configure_markdown_tags(widget, style)

        if prefix:
            self._insert_with_tags(widget, prefix, ("md_prefix",))

        tokens = self.markdown_parser.parse(body) if body.strip() else []
        simple_paragraph = (
            len(tokens) == 3
            and tokens[0].type == "paragraph_open"
            and tokens[1].type == "inline"
            and tokens[2].type == "paragraph_close"
        )
        if body:
            if simple_paragraph and prefix:
                self._insert_with_tags(widget, " ", ())
                self._render_inline_tokens(widget, tokens[1].children)
            else:
                if prefix:
                    self._insert_with_tags(widget, "\n", ())
                self._render_markdown_blocks(widget, tokens)

        widget.configure(state="disabled")
        self._resize_text_widget(widget)

    def _measure_message_display_width(self, style: dict, prefix: str, body: str) -> int:
        """估算消息最长行的显示宽度，并转换为 Text 字符宽度。"""
        max_width = max(1, int(style.get("width", 58)))
        min_width = max(6, int(style.get("min_width", 10)))
        font = style["font"]
        body_lines = body.splitlines() or [""]
        display_lines = []
        if prefix and body_lines:
            display_lines.append(f"{prefix} {body_lines[0]}".rstrip())
            display_lines.extend(line.rstrip() for line in body_lines[1:])
        elif prefix:
            display_lines.append(prefix.rstrip())
        else:
            display_lines.extend(line.rstrip() for line in body_lines)
        visible_lines = [line.expandtabs(4) for line in display_lines if line.strip()]
        if not visible_lines:
            return min_width
        sample = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        avg_char_px = max(font.measure(sample) // len(sample), 1)
        longest_px = max(font.measure(line) for line in visible_lines)
        desired_width = (longest_px + avg_char_px - 1) // avg_char_px + 2
        return max(min_width, min(max_width, desired_width))

    def _update_text_widget_width(self, widget: tk.Text, style: dict, prefix: str, body: str) -> None:
        """根据消息内容调整气泡宽度，避免短消息被固定宽度撑大。"""
        widget.configure(width=self._measure_message_display_width(style, prefix, body))

    def _resize_text_widget(self, widget: tk.Text) -> None:
        """根据实际换行结果自适应文本框高度。"""
        widget.update_idletasks()
        try:
            line_count = int(widget.count("1.0", "end-1c", "displaylines")[0])
        except Exception:
            line_count = int(widget.index("end-1c").split(".")[0])
        widget.configure(height=max(1, line_count))

    def _maybe_resize_stream_widget(self, widget: tk.Text, *, force: bool = False) -> None:
        """流式输出阶段限制重排频率，避免每个 token 都触发高度重算。"""
        now = time.monotonic()
        last_resize = float(getattr(widget, "_last_stream_resize_at", 0.0) or 0.0)
        if not force and now - last_resize < STREAM_WIDGET_RESIZE_INTERVAL_S:
            return
        self._resize_text_widget(widget)
        widget._last_stream_resize_at = now

    def _configure_plain_message_tags(self, widget: tk.Text, style: dict) -> None:
        """为流式阶段配置轻量纯文本标签，避免高频 Markdown 解析。"""
        body_font = style["font"]
        prefix_font = tkfont.Font(font=body_font)
        prefix_font.configure(weight="bold")
        widget._plain_fonts = [prefix_font, body_font]
        widget.tag_configure("plain_prefix", font=prefix_font, foreground=style["text_color"], spacing3=4)
        widget.tag_configure("plain_body", font=body_font, foreground=style["text_color"])

    def _render_plain_message_widget(self, widget: tk.Text, *, force_resize: bool = True) -> None:
        """以纯文本方式重绘当前消息，供流式阶段或会话切回时使用。"""
        role = getattr(widget, "_message_role", "system")
        prefix = getattr(widget, "_message_prefix", "")
        body = getattr(widget, "_message_body", "")
        style = self._resolve_bubble_style(role)

        widget.configure(state="normal", width=int(style.get("width", 58)))
        widget.delete("1.0", "end")
        self._configure_plain_message_tags(widget, style)
        if prefix:
            widget.insert("end", prefix, ("plain_prefix",))
        if body:
            if prefix:
                widget.insert("end", "\n")
            widget.insert("end", body, ("plain_body",))
        widget._plain_body_started = bool(body)
        widget.configure(state="disabled")
        self._maybe_resize_stream_widget(widget, force=force_resize)

    def _append_plain_message_chunk(self, widget: tk.Text, text: str) -> None:
        """以追加方式刷新流式消息，避免整段删除重绘。"""
        if not text:
            return
        role = getattr(widget, "_message_role", "system")
        prefix = getattr(widget, "_message_prefix", "")
        style = self._resolve_bubble_style(role)
        self._configure_plain_message_tags(widget, style)
        widget.configure(state="normal", width=int(style.get("width", 58)))
        if prefix and not getattr(widget, "_plain_body_started", False):
            widget.insert("end", "\n")
        widget.insert("end", text, ("plain_body",))
        widget._plain_body_started = True
        widget.configure(state="disabled")
        force_resize = "\n" in text or len(text) >= 80
        self._maybe_resize_stream_widget(widget, force=force_resize)

    def _set_text_widget_content(self, widget: tk.Text, text: str, *, append: bool = False) -> None:
        """统一设置或追加聊天气泡文本，并按 Markdown 重绘。"""
        if append:
            widget._message_body = getattr(widget, "_message_body", "") + text
        else:
            role = getattr(widget, "_message_role", "system")
            prefix, body = self._split_message_prefix(role, text)
            widget._message_prefix = prefix
            widget._message_body = body
        self._render_markdown_message(widget)

    def _set_process_widget_body(self, widget: tk.Text, body: str) -> None:
        """以轻量纯文本方式刷新流程气泡，避免高频 Markdown 重绘卡住主线程。"""
        style = self._resolve_bubble_style("process")
        prefix = "流程："
        clean_body = str(body or "").strip()
        widget._message_role = "process"
        widget._message_prefix = prefix
        widget._message_body = clean_body
        widget.configure(state="normal", width=int(style.get("width", 60)))
        widget.delete("1.0", "end")
        widget.tag_configure("process_prefix", font=self._make_tk_font(self.font_size_small, force_bold=True))
        widget.tag_configure("process_body", font=style["font"])
        widget.tag_configure("process_all", foreground=style["text_color"])
        widget.insert("end", prefix, ("process_prefix", "process_all"))
        if clean_body:
            widget.insert("end", "\n" + clean_body, ("process_body", "process_all"))
        widget.configure(state="disabled")
        self._resize_text_widget(widget)

    def _refresh_process_bubble(self, session_id: str) -> None:
        """把指定 session 的流程日志合并到单个动态气泡中。"""
        if str(session_id).strip() != self.selected_session_id:
            return
        state = self._get_session_task_state(session_id)
        process_text = str(state.get("draft_process", "")).strip()
        if not process_text:
            return
        widget = state.get("current_process_widget")
        if widget is None or not widget.winfo_exists():
            widget = self._create_bubble("process", "流程：")
            state["current_process_widget"] = widget
        self._set_process_widget_body(widget, process_text)

    def _create_bubble(self, role: str, text: str):
        """创建单条聊天气泡。"""
        style = self._resolve_bubble_style(role)
        outer = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        outer.grid(row=len(self.chat_bubble_widgets), column=0, sticky="ew", padx=6, pady=(0, 10))
        outer.grid_columnconfigure(0, weight=1)

        bubble = ctk.CTkFrame(
            outer,
            fg_color=style["bubble_color"],
            corner_radius=12,
            border_width=1,
            border_color=self.colors["border_color"],
        )
        bubble.grid(row=0, column=0, sticky=style["sticky"], padx=style["pad_x"])
        self._bind_chat_drag_scroll_target(outer)
        self._bind_chat_drag_scroll_target(bubble)

        text_widget = tk.Text(
            bubble,
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            cursor="xterm",
            undo=False,
            exportselection=False,
            height=1,
            width=style["width"],
            background=style["bubble_color"],
            foreground=style["text_color"],
            insertbackground=style["text_color"],
            selectbackground=self.colors["selected_color"],
            selectforeground=self.colors["text_color"],
            font=style["font"],
        )
        text_widget.pack(fill="both", expand=True, padx=12, pady=10)
        self._bind_chat_text_widget(text_widget)
        prefix, body = self._split_message_prefix(role, text)
        text_widget._message_role = role
        text_widget._message_prefix = prefix
        text_widget._message_body = body
        if role == "process":
            self._set_process_widget_body(text_widget, body)
        else:
            self._set_text_widget_content(text_widget, text)
        self.chat_bubble_widgets.append(
            {
                "outer": outer,
                "bubble": bubble,
                "text": text_widget,
                "role": role,
            }
        )
        self._scroll_chat_to_bottom()
        return text_widget

    def _append_chat_line(self, text: str) -> None:
        """按行追加聊天文本。"""
        role = "system"
        if text.startswith("你："):
            role = "user"
        elif text.startswith("AI："):
            role = "assistant"
        elif text.startswith("思考："):
            role = "thinking"
        elif text.startswith("流程："):
            role = "process"
        self._create_bubble(role, text)

    def _append_stream_text(self, session_id: str, role: str, text: str) -> None:
        """将流式思考或回复追加到指定 session 的缓存与可见气泡。"""
        state = self._get_session_task_state(session_id)
        if role == "thinking":
            state["reasoning_started"] = True
            state["draft_reasoning"] += text
            if session_id == self.selected_session_id:
                if state.get("current_reasoning_widget") is None:
                    state["current_reasoning_widget"] = self._create_bubble("thinking", "思考：")
                self.current_reasoning_widget = state["current_reasoning_widget"]
                self.current_reasoning_widget._message_body = getattr(self.current_reasoning_widget, "_message_body", "") + text
                self._append_plain_message_chunk(self.current_reasoning_widget, text)
        else:
            state["answer_started"] = True
            state["draft_answer"] += text
            if session_id == self.selected_session_id:
                if state.get("current_answer_widget") is None:
                    state["current_answer_widget"] = self._create_bubble("assistant", "AI：")
                self.current_answer_widget = state["current_answer_widget"]
                self.current_answer_widget._message_body = getattr(self.current_answer_widget, "_message_body", "") + text
                self._append_plain_message_chunk(self.current_answer_widget, text)
        if session_id == self.selected_session_id:
            self.answer_started = bool(state.get("answer_started", False))
            self.reasoning_started = bool(state.get("reasoning_started", False))

    def _send_from_enter(self, _event=None):
        """回车直接发送当前输入。"""
        self._send_input()
        return "break"

    def _insert_newline(self, _event=None):
        """Ctrl+Enter 在输入框中插入换行。"""
        self.input_box.insert("insert", "\n")
        return "break"

    def _format_attachment_summary(self) -> str:
        """把待发送附件整理成简短摘要。"""
        if not self.pending_attachments:
            return "未选择附件"
        names = [Path(path).name for path in self.pending_attachments]
        preview = "，".join(names[:3])
        if len(names) > 3:
            preview += f" 等 {len(names)} 个文件"
        return f"已选择附件：{preview}"

    def _update_attachment_summary(self) -> None:
        """刷新输入区附件摘要文本。"""
        self.attachment_var.set(self._format_attachment_summary())
        if hasattr(self, "clear_attachments_button"):
            state = "normal" if self.pending_attachments and not self._is_session_busy(self.selected_session_id) else "disabled"
            self.clear_attachments_button.configure(state=state)

    def _choose_attachments(self) -> None:
        """打开文件选择器并记录待发送附件。"""
        if self._is_session_busy(self.selected_session_id):
            return
        selected = filedialog.askopenfilenames(title="选择附件")
        if not selected:
            return
        existing = {str(Path(path)) for path in self.pending_attachments}
        for path in selected:
            normalized = str(Path(path))
            if normalized not in existing:
                self.pending_attachments.append(normalized)
                existing.add(normalized)
        self._update_attachment_summary()

    def _clear_attachments(self) -> None:
        """清空待发送附件列表。"""
        if self._is_session_busy(self.selected_session_id):
            return
        self.pending_attachments = []
        self._update_attachment_summary()

    def _build_user_display_text(self, user_input: str, attachments=None) -> str:
        """构造聊天区中用户消息的显示文本。"""
        text = (user_input or "").strip()
        files = [Path(item).name for item in (attachments or []) if str(item).strip()]
        if not files:
            return text
        attachment_block = "\n".join(f"- {name}" for name in files)
        if text:
            return f"{text}\n\n[附件]\n{attachment_block}"
        return f"[附件]\n{attachment_block}"

    def _send_input(self) -> None:
        """收集输入框内容并进入统一处理逻辑。"""
        if self._is_session_busy(self.selected_session_id):
            return
        text = self.input_box.get("1.0", "end").strip()
        attachments = list(self.pending_attachments)
        if not text and not attachments:
            return
        if not text and attachments:
            text = "请结合我附带的附件内容进行分析。"
        actual_input = f"/exec {text}".strip() if self.exec_mode else text
        self.input_box.delete("1.0", "end")
        self.pending_attachments = []
        self._update_attachment_summary()
        self._handle_input(actual_input, attachments=attachments, display_text=text)

    def _handle_input(self, user_input: str, attachments=None, display_text: str | None = None) -> None:
        """处理普通消息或 /xxx 指令。"""
        if self._is_session_busy(self.selected_session_id):
            messagebox.showinfo("提示", "当前会话仍在处理中，请切到其他会话或等待完成。")
            return

        attachments = list(attachments or [])
        display_value = user_input if display_text is None else display_text
        self._append_chat_line(f"你：{self._build_user_display_text(display_value, attachments)}")

        command_info = self.runtime.classify_instruction(user_input)
        if attachments and command_info["kind"] != "chat":
            self._append_chat_line("系统：当前附件仅支持普通聊天消息，请不要与 /add、/endsession、/rmsession、/rm、/exec、/session、/skill add、/skill 等指令混用。")
            self.status_var.set("附件未发送")
            self.detail_var.set("请改为普通聊天输入后再发送附件。")
            return
        if command_info["kind"] == "unknown_command":
            self._append_chat_line("系统：未知指令。")
            self.status_var.set("未知指令")
            self.detail_var.set("该指令未出现在 instruction.json 中")
            return
        if self.archive_in_progress and command_info["kind"] in {"end_session", "remove_records", "session_add"}:
            self._append_chat_line("系统：会话摘要仍在后台生成中，请稍后再执行该操作。")
            self.detail_var.set("后台摘要生成中")
            return
        if command_info["kind"] == "deprecated_end":
            self._append_chat_line("系统：/end 已弃用，请改用 /add 新建会话，或使用 /endsession 结束当前会话并生成摘要。")
            self.status_var.set("命令已弃用")
            self.detail_var.set("/end 已弃用，命令组件中提供了对应的新入口。")
            return
        if command_info["kind"] == "session_missing_target":
            self._append_chat_line("系统：用法：/session list、/session new 或 /session <session_id>")
            self.status_var.set("session 参数缺失")
            self.detail_var.set("请提供 list、new 或具体 session_id")
            return
        if command_info["kind"] == "remove_session_missing_target":
            self._append_chat_line("系统：用法：/rmsession <session_id>")
            self.status_var.set("rmsession 参数缺失")
            self.detail_var.set("请提供要删除的 session_id")
            return
        if command_info["kind"] == "skill_missing_target":
            self._append_chat_line("系统：用法：/skill add、/skill list 或 /skill <skillname> [args]")
            self.status_var.set("skill 参数缺失")
            self.detail_var.set("请提供 add、list 或具体 skill 脚本名")
            return
        if command_info["kind"] == "session_list":
            sessions = self.runtime.list_sessions()
            if not sessions:
                self._append_chat_line("系统：暂无可用会话。")
            else:
                self._append_chat_line("系统：当前会话列表如下：")
                for item in sessions:
                    current_mark = " [当前]" if item.get("is_current") else ""
                    self._append_chat_line(
                        f"系统：[{item['session_id']}] {item['title']} / {item['start_time']}{current_mark}"
                    )
            self.status_var.set("会话列表")
            self.detail_var.set("已输出当前用户的全部 session")
            return
        if command_info["kind"] == "session_add":
            session = self.runtime.create_new_session()
            self.selected_session_id = session.get("session_id", "")
            self.start_time_var.set(session.get("start_time", ""))
            self._refresh_session_list(selected_id=self.selected_session_id)
            self._render_current_session_history()
            self._sync_action_button_states()
            self.status_var.set("已新建会话")
            self.detail_var.set(f"当前已切换到新会话：{self.selected_session_id}")
            self._update_input_info()
            return
        if command_info["kind"] == "session_switch":
            self._select_session_item({"id": command_info["session_id"], "kind": "history"})
            return
        if command_info["kind"] == "exec_missing_task":
            self._append_chat_line("系统：用法：/exec <任务内容>")
            self.status_var.set("exec 参数缺失")
            self.detail_var.set("请在 /exec 后输入具体任务内容")
            return
        if command_info["kind"] == "skill_list":
            skills = self.runtime.list_skills()
            if not skills:
                self._append_chat_line("系统：当前 SKILLS 目录下暂无可用 skill。")
            else:
                self._append_chat_line("系统：当前技能列表如下：")
                for item in skills:
                    self._append_chat_line(f"系统：[{item['folder']}] {item['description'] or '无描述'}")
            self.status_var.set("技能列表")
            self.detail_var.set("已输出当前项目 SKILLS 目录中的全部 skill")
            return
        if command_info["kind"] == "skill_add":
            self._start_learn_skill(display_text=display_value)
            return
        if command_info["kind"] == "skill_run":
            def skill_exec_callback(event: dict):
                event_type = event.get("type")
                if event_type == "skill_phase":
                    self._append_chat_line(f"系统：[skill] {event.get('message', '')}")
                elif event_type == "skill_result":
                    self._append_chat_line(f"系统：[skill] 执行完成：{event.get('skill_name', '')}")

            try:
                result = self.runtime.execute_skill_on_session(
                    self.selected_session_id,
                    command_info["skill_name"],
                    args_text=command_info.get("skill_args", ""),
                    callback=skill_exec_callback,
                )
            except ValueError as exc:
                self._append_chat_line(f"系统：{exc}")
                self.status_var.set("skill 不存在")
                self.detail_var.set("请先使用 /skill list 查看可用技能")
                return
            reply = str(result.get("reply", "")).strip()
            if reply:
                for line in reply.splitlines():
                    self._append_chat_line(f"AI：{line}" if line.strip() else "AI：")
            self.status_var.set("skill 已执行")
            self.detail_var.set(f"已执行 skill：{command_info['skill_name']}")
            return
        if command_info["kind"] == "end_session":
            self._start_end_session(auto_new_session=False)
            return
        if command_info["kind"] == "remove_records":
            self._handle_remove_records()
            return
        if command_info["kind"] == "remove_session":
            self._handle_remove_session(command_info["session_id"])
            return
        if command_info["kind"] == "exec":
            self._start_exec(command_info["task"], display_text=display_value)
            return
        if command_info["kind"] == "known_command":
            self._append_chat_line(f"系统：已匹配指令 {user_input}，但暂未实现对应 GUI 操作。")
            self.status_var.set("指令已匹配")
            self.detail_var.set(f"{user_input} 已匹配，但当前 GUI 里尚未实现专属动作")
            return
        self._start_chat(user_input, attachments=attachments)

    def _sync_action_button_states(self) -> None:
        """根据当前运行状态更新主要按钮可用性。"""
        selected_busy = self._is_session_busy(self.selected_session_id)
        any_busy = self._has_any_busy_session()
        send_state = "disabled" if selected_busy else "normal"
        add_state = "disabled" if selected_busy or self.archive_in_progress else "normal"
        end_state = "disabled" if selected_busy or self.archive_in_progress else "normal"
        rm_state = "disabled" if any_busy or self.archive_in_progress else "normal"
        settings_state = "disabled" if any_busy else "normal"
        self.send_button.configure(state=send_state)
        self.add_button.configure(state=add_state)
        self.endsession_button.configure(state=end_state)
        self.rm_button.configure(state=rm_state)
        self.exec_button.configure(state=send_state)
        if hasattr(self, "learn_skill_button"):
            self.learn_skill_button.configure(state=send_state)
        if hasattr(self, "attach_button"):
            self.attach_button.configure(state=send_state)
        if hasattr(self, "clear_attachments_button"):
            clear_state = "disabled" if selected_busy or not self.pending_attachments else "normal"
            self.clear_attachments_button.configure(state=clear_state)
        if hasattr(self, "settings_button"):
            self.settings_button.configure(state=settings_state)
        self._update_settings_controls_state()

    def _set_archive_in_progress(self, archive_in_progress: bool) -> None:
        """切换后台归档状态，同时刷新相关按钮。"""
        self.archive_in_progress = archive_in_progress
        self._sync_action_button_states()

    def _set_widget_state(self, widget, enabled: bool) -> None:
        """兼容 CTk 与 Tk 控件的启停状态切换。"""
        state = "normal" if enabled else "disabled"
        try:
            widget.configure(state=state)
        except Exception:
            pass

    def _update_settings_controls_state(self) -> None:
        """流式生成中冻结设置页控件，空闲时恢复。"""
        if self.settings_window is None or not self.settings_window.winfo_exists():
            return

        can_edit = not self._has_any_busy_session()
        for widget in self.settings_controls:
            self._set_widget_state(widget, can_edit)
        for widget in self.size_setting_controls:
            self._set_widget_state(widget, can_edit)

        if self.font_listbox is not None:
            try:
                self.font_listbox.configure(state=tk.NORMAL if can_edit else tk.DISABLED)
            except Exception:
                pass

        if self.settings_status_var is not None:
            self.settings_status_var.set(" " if can_edit else "流式输出中，设置已冻结")

    def _is_valid_color(self, value: str) -> bool:
        """判断颜色值是否为 #RRGGBB 形式。"""
        return bool(COLOR_PATTERN.fullmatch(str(value).strip()))

    def _build_preview_fonts(self) -> tuple[ctk.CTkFont, ctk.CTkFont, ctk.CTkFont]:
        """根据设置窗口中的临时值生成预览字体。"""
        if not self.settings_vars:
            return self.font_main, self.font_small, self.font_title

        preview_font_settings = {
            "family": self._normalize_font_family(
                self.settings_vars["family"].get().strip() or self.font_settings.get("family", "宋体")
            ),
            "size": self._normalize_font_size(self.settings_vars["size"].get()),
            "bold": bool(self.settings_vars["bold"].get()),
            "italic": bool(self.settings_vars["italic"].get()),
        }
        original = self.font_settings
        self.font_settings = preview_font_settings
        try:
            base_size = self._normalize_font_size(preview_font_settings["size"])
            preview_main = self._make_ctk_font(base_size)
            preview_small = self._make_ctk_font(max(base_size - 1, 9))
            preview_title = self._make_ctk_font(base_size + 2, force_bold=True)
        finally:
            self.font_settings = original
        return preview_main, preview_small, preview_title

    def _apply_theme_to_existing_chat(self) -> None:
        """把新的颜色和字体应用到已显示的聊天内容。"""
        for item in self.chat_bubble_widgets:
            style = self._resolve_bubble_style(item["role"])
            item["bubble"].configure(
                fg_color=style["bubble_color"],
                border_color=self.colors["border_color"],
            )
            item["text"].configure(
                background=style["bubble_color"],
                foreground=style["text_color"],
                insertbackground=style["text_color"],
                selectbackground=self.colors["selected_color"],
                selectforeground=self.colors["text_color"],
                font=style["font"],
            )
            item["bubble"].grid_configure(sticky=style["sticky"], padx=style["pad_x"])
            self._render_markdown_message(item["text"])

    def _apply_gui_settings(self) -> None:
        """把当前 gui 配置实时应用到主界面。"""
        self._build_fonts()
        self.surface_style = self._normalize_surface_style(
            self.gui_settings.get("surface_style", self.surface_style)
        )
        self.root.configure(fg_color=self.colors["bg_color"])
        self.shell.configure(fg_color=self.colors["bg_color"])
        self.left_panel.configure(
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            border_color=self.colors["border_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self.chat_card.configure(
            fg_color=self._get_surface_fg_color(self.colors["card_color"]),
            border_color=self.colors["border_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self.input_card.configure(
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            border_color=self.colors["border_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self.session_scroll.configure(
            fg_color=self._get_surface_fg_color(self.colors["card_color"]),
            border_color=self.colors["border_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self._sync_scrollable_canvas_surface(self.session_scroll, self._get_surface_fg_color(self.colors["card_color"]))
        self.chat_scroll.configure(
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            border_color=self.colors["border_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self._sync_scrollable_canvas_surface(self.chat_scroll, self._get_surface_fg_color(self.colors["panel_color"]))

        self.session_title_label.configure(font=self.font_section, text_color=self.colors["text_color"])
        self.session_count_label.configure(font=self.font_small, text_color=self.colors["subtext_color"])
        self.chat_title_label.configure(font=self.font_section, text_color=self.colors["text_color"])
        self.chat_status_label.configure(font=self.font_small, text_color=self.colors["subtext_color"])
        self.detail_label.configure(font=self.font_small, text_color=self.colors["subtext_color"])
        self.input_info_label.configure(font=self.font_small, text_color=self.colors["subtext_color"])
        self.input_hint_label.configure(font=self.font_small, text_color=self.colors["subtext_color"])
        self.attachment_label.configure(font=self.font_small, text_color=self.colors["subtext_color"])

        self.settings_button.configure(
            font=self.font_title,
            **self._button_surface_kwargs(),
        )
        self.add_button.configure(
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.endsession_button.configure(
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.rm_button.configure(
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.exec_button.configure(font=self.font_main, **self._button_surface_kwargs())
        self.attach_button.configure(
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.clear_attachments_button.configure(
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        self.send_button.configure(
            font=self.font_title,
            **self._button_surface_kwargs(primary=True),
        )
        self.input_box.configure(
            font=self.font_main,
            **self._entry_surface_kwargs(
                border_color=self._get_input_border_color(),
                allow_transparent=True,
            ),
        )

        self._refresh_session_list(selected_id=self.selected_session_id)
        self._apply_theme_to_existing_chat()
        self._update_attachment_summary()
        self._update_exec_mode_style()
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.configure(fg_color=self.colors["bg_color"])
            self._refresh_settings_preview()

    def _collect_settings_colors(self, *, use_fallback: bool = False) -> dict:
        """从设置窗口收集颜色；预览场景下可对非法值回退当前颜色。"""
        preview_colors = {}
        for key, _ in COLOR_FIELDS:
            raw_value = self.settings_vars[key].get().strip()
            if self._is_valid_color(raw_value):
                preview_colors[key] = raw_value.upper()
            elif use_fallback:
                preview_colors[key] = self.colors[key]
            else:
                preview_colors[key] = raw_value
        return preview_colors

    def _refresh_settings_preview(self) -> None:
        """实时刷新设置窗口中的颜色块与预览区域。"""
        if self.settings_window is None or not self.settings_window.winfo_exists():
            return

        preview_colors = self._collect_settings_colors(use_fallback=True)
        current_theme_name = self._detect_theme_name(preview_colors)
        for key, _label_text in COLOR_FIELDS:
            preview = self.color_preview_labels.get(key)
            if preview is None:
                continue
            raw_value = self.settings_vars[key].get().strip()
            if self._is_valid_color(raw_value):
                preview.configure(fg_color=raw_value.upper(), text="")
            else:
                preview.configure(fg_color="#FECACA", text="!")

        preview_main_font, preview_small_font, preview_title_font = self._build_preview_fonts()
        preview_shell = self.preview_widgets.get("shell")
        if preview_shell is None:
            return
        preview_surface_style = self._normalize_surface_style(
            {
                "corner_radius": self.settings_vars.get("surface_corner_radius", tk.StringVar(value="12")).get(),
                "shadow_blur": self.settings_vars.get("surface_shadow_blur", tk.StringVar(value="10")).get(),
                "shadow_offset_y": self.settings_vars.get("surface_shadow_offset_y", tk.StringVar(value="3")).get(),
                "shadow_alpha": self.settings_vars.get("surface_shadow_alpha", tk.StringVar(value="72")).get(),
                "shadow_margin": self.settings_vars.get("surface_shadow_margin", tk.StringVar(value="6")).get(),
                "glass_opacity": self.settings_vars.get("surface_glass_opacity", tk.StringVar(value="0.2")).get(),
                "glass_blur": self.settings_vars.get("surface_glass_blur", tk.StringVar(value="12")).get(),
                "enable_glass": bool(self.settings_vars.get("surface_enable_glass", tk.BooleanVar(value=True)).get()),
            }
        )
        original_surface_style = self.surface_style
        self.surface_style = preview_surface_style
        if "theme_preset" in self.settings_vars and not self.applying_theme_preset:
            self.applying_theme_preset = True
            try:
                self.settings_vars["theme_preset"].set(current_theme_name)
            finally:
                self.applying_theme_preset = False
        theme_description = self.preview_widgets.get("theme_description")
        if theme_description is not None:
            description = THEME_PRESETS.get(current_theme_name, {}).get("description", "当前颜色为自定义，可在应用主题后继续微调。")
            theme_description.configure(text=description, text_color=preview_colors["subtext_color"], font=preview_small_font)

        self.preview_widgets["shell"].configure(fg_color=preview_colors["bg_color"])
        self.preview_widgets["card"].configure(
            fg_color=self._get_surface_fg_color(preview_colors["card_color"]),
            border_color=preview_colors["border_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self.preview_widgets["panel"].configure(
            fg_color=self._get_surface_fg_color(preview_colors["panel_color"]),
            corner_radius=self._get_surface_corner_radius(),
        )
        self.preview_widgets["title"].configure(text_color=preview_colors["text_color"], font=preview_title_font)
        self.preview_widgets["detail"].configure(text_color=preview_colors["subtext_color"], font=preview_small_font)
        self.preview_widgets["user"].configure(
            fg_color=preview_colors["user_bubble"],
            text_color=preview_colors["text_color"],
            font=preview_main_font,
            corner_radius=self._get_surface_corner_radius(),
        )
        self.preview_widgets["assistant"].configure(
            fg_color=preview_colors["ai_bubble"],
            text_color=preview_colors["text_color"],
            font=preview_main_font,
            corner_radius=self._get_surface_corner_radius(),
        )
        self.preview_widgets["thinking"].configure(
            fg_color=preview_colors["thinking_bubble"],
            text_color=preview_colors["reasoning_color"],
            font=preview_small_font,
            corner_radius=self._get_surface_corner_radius(),
        )
        self.preview_widgets["input"].configure(
            font=preview_main_font,
            **self._entry_surface_kwargs(),
        )
        self.preview_widgets["button"].configure(
            font=preview_main_font,
            **self._button_surface_kwargs(primary=True),
        )
        self.preview_widgets["exec_input"].configure(
            font=preview_main_font,
            **{
                **self._entry_surface_kwargs(border_color=preview_colors["exec_mode_border"]),
                "border_width": 2,
            },
        )
        self.preview_widgets["exec_button"].configure(
            fg_color=self._get_surface_fg_color(preview_colors["exec_mode_button"]),
            hover_color=self._get_surface_fg_color(preview_colors["exec_mode_button_hover"]),
            text_color="#5F4B00",
            font=preview_main_font,
            border_color=preview_colors["exec_mode_border"],
            corner_radius=self._get_component_corner_radius(),
        )
        self.preview_widgets["exec_hint"].configure(
            text_color=preview_colors["exec_mode_hint"],
            font=preview_small_font,
        )
        self.surface_style = original_surface_style

    def _choose_color(self, key: str) -> None:
        """打开系统取色器并写回对应配置项。"""
        current_value = self.settings_vars[key].get().strip()
        _, picked_color = colorchooser.askcolor(color=current_value if self._is_valid_color(current_value) else None)
        if picked_color:
            self.settings_vars[key].set(picked_color.upper())

    def _format_setting_label(self, key: str) -> str:
        """把配置键转换为更易读的标签。"""
        return str(key).replace("_", " ").strip() or str(key)

    def _get_gui_setting_description(self, key: str) -> str:
        """返回 GUI 配置字段的中文说明。"""
        return GUI_FIELD_DESCRIPTIONS.get(key, "")

    def _get_dynamic_setting_description(self, path: tuple[str, ...]) -> str:
        """返回通用配置字段的补充中文说明。"""
        return SETTING_DESCRIPTIONS.get(".".join(path), "")

    def _create_help_label(self, parent, text: str, *, wraplength: int = 420):
        """创建统一样式的说明标签。"""
        return ctk.CTkLabel(
            parent,
            text=text,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            justify="left",
            anchor="w",
            wraplength=wraplength,
        )

    def _detect_theme_name(self, colors: dict) -> str:
        """根据当前颜色集合判断命中的预设主题。"""
        for theme_name, theme in THEME_PRESETS.items():
            if theme["colors"] == colors:
                return theme_name
        return CUSTOM_THEME_NAME

    def _on_theme_preset_changed(self, *_args) -> None:
        """选择预设主题后，一键填充颜色配置。"""
        if self.applying_theme_preset or "theme_preset" not in self.settings_vars:
            return
        selected_theme = self.settings_vars["theme_preset"].get().strip()
        if not selected_theme or selected_theme == CUSTOM_THEME_NAME:
            return
        self._apply_theme_preset(selected_theme)

    def _mark_theme_as_custom(self, *_args) -> None:
        """手动改动颜色后，将主题状态标记为自定义。"""
        if self.applying_theme_preset or "theme_preset" not in self.settings_vars:
            return
        detected = self._detect_theme_name(self._collect_settings_colors(use_fallback=True))
        self.applying_theme_preset = True
        try:
            self.settings_vars["theme_preset"].set(detected)
        finally:
            self.applying_theme_preset = False

    def _apply_theme_preset(self, theme_name: str) -> None:
        """把预设主题颜色写入 GUI 颜色字段。"""
        theme = THEME_PRESETS.get(theme_name)
        if not theme:
            return
        self.applying_theme_preset = True
        try:
            for key, _label in COLOR_FIELDS:
                self.settings_vars[key].set(theme["colors"][key])
            if "theme_preset" in self.settings_vars:
                self.settings_vars["theme_preset"].set(theme_name)
        finally:
            self.applying_theme_preset = False
        self._refresh_settings_preview()

    def _refresh_dynamic_color_preview(self, path_key: str) -> None:
        """刷新动态配置字段的颜色预览块。"""
        preview = self.dynamic_color_preview_labels.get(path_key)
        spec = self.dynamic_field_specs.get(path_key)
        if preview is None or spec is None:
            return
        value = spec["var"].get().strip()
        if self._is_valid_color(value):
            preview.configure(fg_color=value.upper(), text="")
        else:
            preview.configure(fg_color="#FECACA", text="!")

    def _choose_dynamic_color(self, path_key: str) -> None:
        """为通用配置字段打开取色器。"""
        spec = self.dynamic_field_specs.get(path_key)
        if spec is None:
            return
        current_value = spec["var"].get().strip()
        _, picked_color = colorchooser.askcolor(color=current_value if self._is_valid_color(current_value) else None)
        if picked_color:
            spec["var"].set(picked_color.upper())

    def _build_gui_config_from_settings(self) -> dict:
        """从 GUI 专用设置控件收集配置。"""
        family = self._normalize_font_family(self.settings_vars["family"].get().strip() or "宋体")
        size = self._normalize_font_size(self.settings_vars["size"].get())
        window_width = self._normalize_window_dimension(
            self.settings_vars["window_width"].get(),
            minimum=960,
            maximum=2400,
            fallback=self.window_width,
        )
        window_height = self._normalize_window_dimension(
            self.settings_vars["window_height"].get(),
            minimum=640,
            maximum=1600,
            fallback=self.window_height,
        )
        invalid_items = [
            label_text
            for key, label_text in COLOR_FIELDS
            if not self._is_valid_color(self.settings_vars[key].get().strip())
        ]
        if invalid_items:
            raise ValueError(f"以下配置不是有效颜色值：{', '.join(invalid_items)}")

        return {
            "window": {
                "width": window_width,
                "height": window_height,
            },
            "chat_font": {
                "family": family,
                "size": size,
                "bold": bool(self.settings_vars["bold"].get()),
                "italic": bool(self.settings_vars["italic"].get()),
            },
            "theme_preset": self.settings_vars.get("theme_preset", tk.StringVar(value=CUSTOM_THEME_NAME)).get().strip() or CUSTOM_THEME_NAME,
            "surface_style": {
                "corner_radius": self._normalize_window_dimension(
                    self.settings_vars.get("surface_corner_radius", tk.StringVar(value="12")).get(),
                    minimum=0,
                    maximum=36,
                    fallback=DEFAULT_SURFACE_STYLE["corner_radius"],
                ),
                "shadow_blur": self._normalize_window_dimension(
                    self.settings_vars.get("surface_shadow_blur", tk.StringVar(value="10")).get(),
                    minimum=0,
                    maximum=40,
                    fallback=DEFAULT_SURFACE_STYLE["shadow_blur"],
                ),
                "shadow_offset_y": self._normalize_window_dimension(
                    self.settings_vars.get("surface_shadow_offset_y", tk.StringVar(value="3")).get(),
                    minimum=0,
                    maximum=20,
                    fallback=DEFAULT_SURFACE_STYLE["shadow_offset_y"],
                ),
                "shadow_alpha": self._normalize_window_dimension(
                    self.settings_vars.get("surface_shadow_alpha", tk.StringVar(value="72")).get(),
                    minimum=0,
                    maximum=180,
                    fallback=DEFAULT_SURFACE_STYLE["shadow_alpha"],
                ),
                "shadow_margin": self._normalize_window_dimension(
                    self.settings_vars.get("surface_shadow_margin", tk.StringVar(value="6")).get(),
                    minimum=0,
                    maximum=20,
                    fallback=DEFAULT_SURFACE_STYLE["shadow_margin"],
                ),
                "glass_opacity": self._normalize_opacity(
                    self.settings_vars.get("surface_glass_opacity", tk.StringVar(value="0.2")).get(),
                    fallback=DEFAULT_SURFACE_STYLE["glass_opacity"],
                ),
                "glass_blur": self._normalize_window_dimension(
                    self.settings_vars.get("surface_glass_blur", tk.StringVar(value="12")).get(),
                    minimum=0,
                    maximum=40,
                    fallback=DEFAULT_SURFACE_STYLE["glass_blur"],
                ),
                "enable_glass": bool(
                    self.settings_vars.get("surface_enable_glass", tk.BooleanVar(value=True)).get()
                ),
            },
            "colors": {
                key: self.settings_vars[key].get().strip().upper()
                for key, _label_text in COLOR_FIELDS
            },
        }

    def _build_dynamic_config_tab(self, parent, top_key: str, top_value) -> None:
        """为非 GUI 顶层配置构建通用配置页。"""
        content = ctk.CTkScrollableFrame(
            parent,
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            corner_radius=self._get_surface_corner_radius(),
            border_width=1,
            border_color=self.colors["border_color"],
        )
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)

        root_card = self._make_card(content)
        root_card.grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        root_card.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            root_card,
            text=f"{top_key} 配置",
            font=self.font_title,
            text_color=self.colors["text_color"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            root_card,
            text=self._get_dynamic_setting_description((top_key,)) or f"当前页对应 config.json 中的 `{top_key}` 顶层配置，控件按字段结构自动生成。",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))

        body = ctk.CTkFrame(root_card, fg_color="transparent")
        body.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=3)

        row_cursor = [0]
        if isinstance(top_value, dict):
            for child_key, child_value in top_value.items():
                self._build_dynamic_config_node(body, row_cursor, (top_key, child_key), child_value, depth=0)
        else:
            self._build_dynamic_config_node(body, row_cursor, (top_key,), top_value, depth=0)

    def _build_dynamic_config_node(self, parent, row_cursor: list[int], path: tuple[str, ...], value, depth: int) -> None:
        """递归生成通用配置编辑控件。"""
        key = path[-1]
        if isinstance(value, dict):
            section = self._make_card(parent, fg_color=self.colors["card_color"])
            section.grid(row=row_cursor[0], column=0, sticky="ew", pady=(0, 10))
            section.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                section,
                text=self._format_setting_label(key),
                font=self.font_main if depth == 0 else self.font_small,
                text_color=self.colors["text_color"],
            ).grid(row=0, column=0, sticky="w", padx=14, pady=(12, 8))
            section_description = self._get_dynamic_setting_description(path)
            inner_row = 1
            if section_description:
                self._create_help_label(section, section_description, wraplength=700).grid(
                    row=1, column=0, sticky="w", padx=14, pady=(0, 10)
                )
                inner_row = 2
            inner = ctk.CTkFrame(section, fg_color="transparent")
            inner.grid(row=inner_row, column=0, sticky="ew", padx=14, pady=(0, 12))
            inner.grid_columnconfigure(0, weight=1)
            inner.grid_columnconfigure(1, weight=1)
            child_cursor = [0]
            for child_key, child_value in value.items():
                self._build_dynamic_config_node(inner, child_cursor, (*path, child_key), child_value, depth + 1)
            row_cursor[0] += 1
            return

        path_key = ".".join(path)
        label = ctk.CTkLabel(
            parent,
            text=self._format_setting_label(key),
            font=self.font_main,
            text_color=self.colors["text_color"],
        )
        label.grid(row=row_cursor[0], column=0, sticky="w", padx=(0, 12), pady=(0, 10))
        self.settings_controls.append(label)

        editor_frame = ctk.CTkFrame(parent, fg_color="transparent")
        editor_frame.grid(row=row_cursor[0], column=1, sticky="ew", pady=(0, 10))
        editor_frame.grid_columnconfigure(0, weight=1)

        if isinstance(value, bool):
            variable = tk.BooleanVar(value=value)
            widget = ctk.CTkCheckBox(
                editor_frame,
                text="启用",
                variable=variable,
                font=self.font_main,
                **self._checkbox_surface_kwargs(),
            )
            widget.grid(row=0, column=0, sticky="w")
            self.dynamic_field_specs[path_key] = {
                "path": path,
                "kind": "bool",
                "value_type": bool,
                "var": variable,
                "widget": widget,
            }
            self.settings_controls.append(widget)
        elif isinstance(value, list):
            text_widget = ctk.CTkTextbox(
                editor_frame,
                height=110,
                font=self.font_main,
                **self._entry_surface_kwargs(),
            )
            text_widget.grid(row=0, column=0, sticky="ew")
            text_widget.insert("1.0", json.dumps(value, ensure_ascii=False, indent=4))
            self.dynamic_field_specs[path_key] = {
                "path": path,
                "kind": "json",
                "value_type": list,
                "widget": text_widget,
            }
            self.settings_controls.append(text_widget)
        elif isinstance(value, str) and ("\n" in value or len(value) > 80):
            text_widget = ctk.CTkTextbox(
                editor_frame,
                height=110,
                font=self.font_main,
                **self._entry_surface_kwargs(),
            )
            text_widget.grid(row=0, column=0, sticky="ew")
            text_widget.insert("1.0", value)
            self.dynamic_field_specs[path_key] = {
                "path": path,
                "kind": "text",
                "value_type": str,
                "widget": text_widget,
            }
            self.settings_controls.append(text_widget)
        else:
            variable = tk.StringVar(value=str(value))
            entry = ctk.CTkEntry(
                editor_frame,
                textvariable=variable,
                font=self.font_main,
                **self._entry_surface_kwargs(),
            )
            entry.grid(row=0, column=0, sticky="ew")
            spec = {
                "path": path,
                "kind": "entry",
                "value_type": type(value),
                "var": variable,
                "widget": entry,
            }
            self.dynamic_field_specs[path_key] = spec
            self.settings_controls.append(entry)
            if isinstance(value, str) and self._is_valid_color(value):
                color_button = ctk.CTkButton(
                    editor_frame,
                    text="选择",
                    command=lambda current_path=path_key: self._choose_dynamic_color(current_path),
                    width=68,
                    height=30,
                    font=self.font_small,
                    **self._button_surface_kwargs(),
                )
                color_button.grid(row=0, column=1, padx=(8, 8))
                preview_label = ctk.CTkLabel(
                    editor_frame,
                    text="",
                    width=44,
                    corner_radius=8,
                    fg_color=value,
                )
                preview_label.grid(row=0, column=2, sticky="e")
                self.dynamic_color_preview_labels[path_key] = preview_label
                variable.trace_add("write", lambda *_args, current_path=path_key: self._refresh_dynamic_color_preview(current_path))
                self.settings_controls.extend([color_button, preview_label])

        description = self._get_dynamic_setting_description(path)
        if description:
            help_label = self._create_help_label(editor_frame, description, wraplength=560)
            help_label.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
            self.settings_controls.append(help_label)

        row_cursor[0] += 1

    def _read_dynamic_field_value(self, spec: dict):
        """按原始类型解析通用配置控件中的值。"""
        kind = spec["kind"]
        value_type = spec["value_type"]
        path_text = ".".join(spec["path"])
        if kind == "bool":
            return bool(spec["var"].get())
        if kind == "json":
            raw = spec["widget"].get("1.0", "end-1c").strip()
            if not raw:
                return []
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError(f"{path_text} 需要是 JSON 数组。")
            return parsed
        if kind == "text":
            return spec["widget"].get("1.0", "end-1c")

        raw = spec["var"].get()
        if value_type is int:
            return int(str(raw).strip())
        if value_type is float:
            return float(str(raw).strip())
        return str(raw)

    def _set_nested_config_value(self, target: dict, path: tuple[str, ...], value) -> None:
        """按路径把值写回完整配置对象。"""
        cursor = target
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value

    def _apply_dynamic_fields_to_config(self, full_config: dict) -> None:
        """把通用配置页中的值写回完整配置。"""
        for spec in self.dynamic_field_specs.values():
            value = self._read_dynamic_field_value(spec)
            self._set_nested_config_value(full_config, spec["path"], value)

    def _reload_runtime_from_saved_config(self) -> None:
        """保存配置后重建运行时并刷新界面。"""
        previous_selected_id = self.selected_session_id
        self.runtime = AgentRuntime()
        self.user = self.runtime.user
        try:
            available_ids = {item["session_id"] for item in self.runtime.list_sessions()}
            if previous_selected_id and previous_selected_id in available_ids:
                self.runtime.switch_session(previous_selected_id)
        except Exception:
            pass
        self._load_session()
        self._refresh_session_list(selected_id=self.selected_session_id)
        self._render_current_session_history()
        self._update_input_info()

    def _save_settings(self) -> None:
        """保存完整 config.json，并立即刷新 GUI 与运行时。"""
        if self.busy:
            if self.settings_status_var is not None:
                self.settings_status_var.set("流式输出中，暂不能保存设置")
            return

        try:
            full_config = self.config_manager.get_full_config()
            self._apply_dynamic_fields_to_config(full_config)
            full_config["gui"] = self._build_gui_config_from_settings()
        except ValueError as exc:
            messagebox.showerror("配置格式错误", str(exc))
            return
        except json.JSONDecodeError as exc:
            messagebox.showerror("JSON 格式错误", f"列表配置解析失败：{exc}")
            return

        self.full_config = self.config_manager.update_full_config(full_config)
        self.gui_settings = dict(self.full_config.get("gui", {}))
        self.window_settings = dict(self.gui_settings.get("window", {}))
        self.window_width = self._normalize_window_dimension(
            self.window_settings.get("width", self.window_width),
            minimum=960,
            maximum=2400,
            fallback=1360,
        )
        self.window_height = self._normalize_window_dimension(
            self.window_settings.get("height", self.window_height),
            minimum=640,
            maximum=1600,
            fallback=860,
        )
        self.font_settings = dict(self.gui_settings["chat_font"])
        self.colors = dict(self.gui_settings["colors"])
        self.surface_style = self._normalize_surface_style(
            self.gui_settings.get("surface_style", {})
        )
        self._apply_gui_settings()
        self._apply_window_geometry(center=True)
        self._reload_runtime_from_saved_config()
        if self.settings_status_var is not None:
            self.settings_status_var.set("已保存，config.json 与运行时已实时更新")

    def _close_settings_window(self) -> None:
        """关闭设置窗口并清理临时状态。"""
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.destroy()
        self.settings_window = None
        self.settings_tabview = None
        self.settings_vars = {}
        self.color_preview_labels = {}
        self.dynamic_field_specs = {}
        self.dynamic_color_preview_labels = {}
        self.preview_widgets = {}
        self.settings_status_var = None
        self.font_listbox = None
        self.settings_controls = []
        self.size_setting_controls = []

    def _build_gui_settings_tab(self, parent) -> None:
        """构建 GUI 专用配置页，保留实时预览能力。"""
        content = ctk.CTkScrollableFrame(
            parent,
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            corner_radius=self._get_surface_corner_radius(),
            border_width=1,
            border_color=self.colors["border_color"],
        )
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=1)

        font_card = self._make_card(content)
        font_card.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 10))
        font_card.grid_columnconfigure(1, weight=1)
        font_card.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(
            font_card,
            text="显示设置",
            font=self.font_title,
            text_color=self.colors["text_color"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            font_card,
            text="支持设置固定窗口尺寸、聊天字体、字号、加粗和斜体，保存后立即应用到当前 GUI。",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 12))

        theme_names = list(THEME_PRESETS.keys()) + [CUSTOM_THEME_NAME]
        configured_theme = str(self.gui_settings.get("theme_preset", "")).strip()
        detected_theme = self._detect_theme_name(self.colors)
        initial_theme = configured_theme if configured_theme in theme_names else detected_theme
        if initial_theme != CUSTOM_THEME_NAME and THEME_PRESETS.get(initial_theme, {}).get("colors") != self.colors:
            initial_theme = detected_theme
        self.settings_vars["theme_preset"] = tk.StringVar(value=initial_theme)
        self.settings_vars["theme_preset"].trace_add("write", self._on_theme_preset_changed)

        ctk.CTkLabel(
            font_card,
            text="界面主题",
            font=self.font_main,
            text_color=self.colors["text_color"],
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 10))
        theme_option = ctk.CTkOptionMenu(
            font_card,
            values=theme_names,
            variable=self.settings_vars["theme_preset"],
            font=self.font_main,
            dropdown_font=self.font_main,
            width=220,
            **self._option_menu_surface_kwargs(),
        )
        theme_option.grid(row=2, column=1, sticky="w", padx=(0, 8), pady=(0, 10))
        apply_theme_button = ctk.CTkButton(
            font_card,
            text="应用主题",
            command=lambda: self._apply_theme_preset(self.settings_vars["theme_preset"].get().strip()),
            width=96,
            height=32,
            font=self.font_small,
            **self._button_surface_kwargs(),
        )
        apply_theme_button.grid(row=2, column=2, sticky="w", padx=(0, 16), pady=(0, 10))
        self._create_help_label(
            font_card,
            self._get_gui_setting_description("theme_preset"),
            wraplength=520,
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 8))

        self.preview_widgets["theme_description"] = ctk.CTkLabel(
            font_card,
            text=THEME_PRESETS.get(initial_theme, {}).get("description", "当前颜色为自定义，可在应用主题后继续微调。"),
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            justify="left",
            anchor="w",
            wraplength=520,
        )
        self.preview_widgets["theme_description"].grid(row=4, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=(0, 10))

        ctk.CTkLabel(
            font_card,
            text="窗口宽度",
            font=self.font_main,
            text_color=self.colors["text_color"],
        ).grid(row=5, column=0, sticky="w", padx=16, pady=(0, 10))
        width_entry = ctk.CTkEntry(
            font_card,
            textvariable=self.settings_vars["window_width"],
            font=self.font_main,
            width=110,
            **self._entry_surface_kwargs(),
        )
        width_entry.grid(row=5, column=1, sticky="w", padx=(0, 8), pady=(0, 10))
        self._create_help_label(
            font_card,
            self._get_gui_setting_description("window_width"),
            wraplength=340,
        ).grid(row=5, column=2, sticky="w", padx=(0, 16), pady=(0, 10))

        ctk.CTkLabel(
            font_card,
            text="窗口高度",
            font=self.font_main,
            text_color=self.colors["text_color"],
        ).grid(row=6, column=0, sticky="w", padx=16, pady=(0, 12))
        height_entry = ctk.CTkEntry(
            font_card,
            textvariable=self.settings_vars["window_height"],
            font=self.font_main,
            width=110,
            **self._entry_surface_kwargs(),
        )
        height_entry.grid(row=6, column=1, sticky="w", padx=(0, 8), pady=(0, 12))
        self._create_help_label(
            font_card,
            self._get_gui_setting_description("window_height"),
            wraplength=340,
        ).grid(row=6, column=2, sticky="w", padx=(0, 16), pady=(0, 12))

        ctk.CTkLabel(
            font_card,
            text="字体名称",
            font=self.font_main,
            text_color=self.colors["text_color"],
        ).grid(row=7, column=0, sticky="w", padx=16, pady=(0, 12))

        font_select_frame = ctk.CTkFrame(font_card, fg_color="transparent")
        font_select_frame.grid(row=7, column=1, columnspan=2, sticky="ew", padx=(0, 16), pady=(0, 12))
        font_select_frame.grid_columnconfigure(0, weight=1)

        family_entry = ctk.CTkEntry(
            font_select_frame,
            textvariable=self.settings_vars["family"],
            font=self.font_main,
            **self._entry_surface_kwargs(),
        )
        family_entry.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        font_list_frame = ctk.CTkFrame(
            font_select_frame,
            fg_color=self._get_surface_fg_color(self.colors["card_color"]),
            corner_radius=self._get_component_corner_radius(10),
            border_width=1,
            border_color=self.colors["border_color"],
        )
        font_list_frame.grid(row=1, column=0, sticky="ew")
        font_list_frame.grid_columnconfigure(0, weight=1)
        font_list_frame.grid_rowconfigure(0, weight=1)

        font_scrollbar = tk.Scrollbar(font_list_frame, orient="vertical")
        font_scrollbar.grid(row=0, column=1, sticky="ns", padx=(0, 8), pady=8)

        self.font_listbox = tk.Listbox(
            font_list_frame,
            height=8,
            activestyle="none",
            exportselection=False,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            font=self._make_tk_font(12),
            background=self.colors["card_color"],
            foreground=self.colors["text_color"],
            selectbackground=self.colors["selected_color"],
            selectforeground=self.colors["text_color"],
            yscrollcommand=font_scrollbar.set,
        )
        self.font_listbox.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=8)
        for family_name in self.available_fonts:
            self.font_listbox.insert("end", family_name)
        self.font_listbox.bind("<<ListboxSelect>>", self._set_font_from_list)
        self.font_listbox.bind("<Double-Button-1>", self._set_font_from_list)
        self.font_listbox.bind("<MouseWheel>", self._handle_font_list_mousewheel)
        font_scrollbar.configure(command=self.font_listbox.yview)

        ctk.CTkLabel(
            font_card,
            text="可直接输入字体名，或在下方列表中用鼠标滚轮滚动选择。",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        ).grid(row=8, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=(0, 2))
        self._create_help_label(
            font_card,
            self._get_gui_setting_description("family"),
            wraplength=520,
        ).grid(row=9, column=1, columnspan=2, sticky="w", padx=(0, 16), pady=(0, 8))

        ctk.CTkLabel(
            font_card,
            text="字体大小",
            font=self.font_main,
            text_color=self.colors["text_color"],
        ).grid(row=10, column=0, sticky="w", padx=16, pady=(0, 10))
        size_entry = ctk.CTkEntry(
            font_card,
            textvariable=self.settings_vars["size"],
            font=self.font_main,
            width=90,
            **self._entry_surface_kwargs(),
        )
        size_entry.grid(row=10, column=1, sticky="w", padx=(0, 8), pady=(0, 10))
        self._create_help_label(
            font_card,
            self._get_gui_setting_description("size"),
            wraplength=340,
        ).grid(row=10, column=2, sticky="w", padx=(0, 16), pady=(0, 10))

        bold_checkbox = ctk.CTkCheckBox(
            font_card,
            text="加粗",
            variable=self.settings_vars["bold"],
            font=self.font_main,
            **self._checkbox_surface_kwargs(),
        )
        bold_checkbox.grid(row=11, column=0, sticky="w", padx=16, pady=(0, 14))
        italic_checkbox = ctk.CTkCheckBox(
            font_card,
            text="斜体",
            variable=self.settings_vars["italic"],
            font=self.font_main,
            **self._checkbox_surface_kwargs(),
        )
        italic_checkbox.grid(row=11, column=1, sticky="w", padx=(0, 16), pady=(0, 14))
        self._create_help_label(
            font_card,
            f"{self._get_gui_setting_description('bold')} {self._get_gui_setting_description('italic')}",
            wraplength=340,
        ).grid(row=11, column=2, sticky="w", padx=(0, 16), pady=(0, 14))

        surface_card = self._make_card(content)
        surface_card.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        surface_card.grid_columnconfigure(1, weight=1)
        surface_card.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(
            surface_card,
            text="框体样式",
            font=self.font_title,
            text_color=self.colors["text_color"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 8))
        ctk.CTkLabel(
            surface_card,
            text="统一控制 session list、聊天框、输入区域、输入框等主要框体的圆角、阴影和模拟毛玻璃强度。",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            justify="left",
            anchor="w",
            wraplength=700,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=16, pady=(0, 12))

        surface_row_start = 2
        for index, (var_name, label_text, field_type) in enumerate(SURFACE_STYLE_FIELDS):
            row = surface_row_start + index
            ctk.CTkLabel(
                surface_card,
                text=label_text,
                font=self.font_main,
                text_color=self.colors["text_color"],
            ).grid(row=row, column=0, sticky="w", padx=16, pady=(0, 10))
            if field_type == "bool":
                widget = ctk.CTkCheckBox(
                    surface_card,
                    text="启用",
                    variable=self.settings_vars[var_name],
                    font=self.font_main,
                    **self._checkbox_surface_kwargs(),
                )
                widget.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=(0, 10))
            else:
                widget = ctk.CTkEntry(
                    surface_card,
                    textvariable=self.settings_vars[var_name],
                    font=self.font_main,
                    width=120,
                    **self._entry_surface_kwargs(),
                )
                widget.grid(row=row, column=1, sticky="w", padx=(0, 16), pady=(0, 10))
            description = self._get_gui_setting_description(var_name)
            if description:
                self._create_help_label(surface_card, description, wraplength=360).grid(
                    row=row, column=2, sticky="w", padx=(0, 16), pady=(0, 10)
                )
            self.settings_controls.append(widget)

        self.size_setting_controls = [width_entry, height_entry]
        self.settings_controls.extend(
            [
                width_entry,
                height_entry,
                family_entry,
                size_entry,
                bold_checkbox,
                italic_checkbox,
                theme_option,
                apply_theme_button,
                font_scrollbar,
            ]
        )

        self._sync_font_list_selection()
        preview_card = self._make_card(content)
        preview_card.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))
        preview_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            preview_card,
            text="实时预览",
            text_color=self.colors["text_color"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 10))

        self.preview_widgets["shell"] = ctk.CTkFrame(
            preview_card,
            fg_color=self._get_surface_fg_color(self.colors["bg_color"]),
            corner_radius=self._get_surface_corner_radius(),
        )
        self.preview_widgets["shell"].grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.preview_widgets["shell"].grid_columnconfigure(0, weight=1)

        self.preview_widgets["card"] = ctk.CTkFrame(
            self.preview_widgets["shell"],
            fg_color=self._get_surface_fg_color(self.colors["card_color"]),
            corner_radius=self._get_surface_corner_radius(),
            border_width=1,
            border_color=self.colors["border_color"],
        )
        self.preview_widgets["card"].grid(row=0, column=0, sticky="ew", padx=14, pady=14)
        self.preview_widgets["card"].grid_columnconfigure(0, weight=1)

        self.preview_widgets["title"] = ctk.CTkLabel(
            self.preview_widgets["card"],
            text="聊天区域预览",
            font=self.font_title,
            text_color=self.colors["text_color"],
        )
        self.preview_widgets["title"].grid(row=0, column=0, sticky="w", padx=14, pady=(14, 4))

        self.preview_widgets["detail"] = ctk.CTkLabel(
            self.preview_widgets["card"],
            text="保存后主界面会立即套用这些样式",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        )
        self.preview_widgets["detail"].grid(row=1, column=0, sticky="w", padx=14, pady=(0, 10))

        self.preview_widgets["panel"] = ctk.CTkFrame(
            self.preview_widgets["card"],
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            corner_radius=self._get_component_corner_radius(10),
        )
        self.preview_widgets["panel"].grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.preview_widgets["panel"].grid_columnconfigure(0, weight=1)

        self.preview_widgets["user"] = ctk.CTkLabel(
            self.preview_widgets["panel"],
            text="这里是用户消息",
            fg_color=self.colors["user_bubble"],
            text_color=self.colors["text_color"],
            font=self.font_main,
            corner_radius=self._get_component_corner_radius(10),
            justify="left",
            anchor="w",
        )
        self.preview_widgets["user"].grid(row=0, column=0, sticky="w", padx=12, pady=(12, 8))

        self.preview_widgets["assistant"] = ctk.CTkLabel(
            self.preview_widgets["panel"],
            text="这里是助手回复",
            fg_color=self.colors["ai_bubble"],
            text_color=self.colors["text_color"],
            font=self.font_main,
            corner_radius=self._get_component_corner_radius(10),
            justify="left",
            anchor="w",
        )
        self.preview_widgets["assistant"].grid(row=1, column=0, sticky="e", padx=12, pady=(0, 8))

        self.preview_widgets["thinking"] = ctk.CTkLabel(
            self.preview_widgets["panel"],
            text="思考：这里展示推理文字颜色",
            fg_color=self.colors["thinking_bubble"],
            text_color=self.colors["reasoning_color"],
            font=self.font_small,
            corner_radius=self._get_component_corner_radius(10),
            justify="left",
            anchor="w",
        )
        self.preview_widgets["thinking"].grid(row=2, column=0, sticky="e", padx=12, pady=(0, 12))

        self.preview_widgets["input"] = ctk.CTkEntry(
            preview_card,
            placeholder_text="输入框背景预览",
            font=self.font_main,
            **self._entry_surface_kwargs(),
        )
        self.preview_widgets["input"].grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 10))
        self.preview_widgets["input"].insert(0, "输入框背景与字体预览")

        self.preview_widgets["button"] = ctk.CTkButton(
            preview_card,
            text="主按钮预览",
            font=self.font_main,
            width=140,
            height=36,
            **self._button_surface_kwargs(primary=True),
        )
        self.preview_widgets["button"].grid(row=3, column=0, sticky="e", padx=16, pady=(0, 16))

        exec_preview_row = ctk.CTkFrame(preview_card, fg_color="transparent")
        exec_preview_row.grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 8))
        exec_preview_row.grid_columnconfigure(0, weight=1)

        self.preview_widgets["exec_input"] = ctk.CTkEntry(
            exec_preview_row,
            font=self.font_main,
            **{
                **self._entry_surface_kwargs(border_color=self.colors["exec_mode_border"]),
                "border_width": 2,
            },
        )
        self.preview_widgets["exec_input"].grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.preview_widgets["exec_input"].insert(0, "执行模式输入框边框预览")

        self.preview_widgets["exec_button"] = ctk.CTkButton(
            exec_preview_row,
            text="退出执行",
            font=self.font_main,
            width=110,
            height=36,
            **self._button_surface_kwargs(),
        )
        self.preview_widgets["exec_button"].grid(row=0, column=1, sticky="e")

        self.preview_widgets["exec_hint"] = ctk.CTkLabel(
            preview_card,
            text="执行模式提示文字预览",
            font=self.font_small,
            anchor="w",
            justify="left",
        )
        self.preview_widgets["exec_hint"].grid(row=5, column=0, sticky="w", padx=16, pady=(0, 16))

        colors_card = self._make_card(content)
        colors_card.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))
        colors_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            colors_card,
            text="颜色设置",
            font=self.font_title,
            text_color=self.colors["text_color"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 10))
        colors_card.grid_columnconfigure(1, weight=1)
        colors_card.grid_columnconfigure(4, weight=1)
        self._create_help_label(
            colors_card,
            "以下颜色会实时影响预览区与主界面，推荐先应用预设主题，再按需微调单项颜色。",
            wraplength=760,
        ).grid(row=1, column=0, columnspan=5, sticky="w", padx=16, pady=(0, 12))

        for row_index, (key, label_text) in enumerate(COLOR_FIELDS, start=2):
            ctk.CTkLabel(
                colors_card,
                text=label_text,
                font=self.font_main,
                text_color=self.colors["text_color"],
            ).grid(row=row_index, column=0, sticky="w", padx=16, pady=(0, 10))

            color_entry = ctk.CTkEntry(
                colors_card,
                textvariable=self.settings_vars[key],
                font=self.font_main,
                **self._entry_surface_kwargs(),
            )
            color_entry.grid(row=row_index, column=1, sticky="ew", padx=(0, 8), pady=(0, 10))

            color_button = ctk.CTkButton(
                colors_card,
                text="选择",
                command=lambda current_key=key: self._choose_color(current_key),
                width=68,
                height=30,
                font=self.font_small,
                **self._button_surface_kwargs(),
            )
            color_button.grid(row=row_index, column=2, padx=(0, 8), pady=(0, 10))
            self.settings_controls.extend([color_entry, color_button])

            preview_label = ctk.CTkLabel(
                colors_card,
                text="",
                width=44,
                corner_radius=8,
                fg_color=self.colors[key],
            )
            preview_label.grid(row=row_index, column=3, sticky="e", padx=(0, 16), pady=(0, 10))
            self.color_preview_labels[key] = preview_label
            description = self._get_gui_setting_description(key)
            if description:
                self._create_help_label(colors_card, description, wraplength=320).grid(
                    row=row_index, column=4, sticky="w", padx=(0, 16), pady=(0, 10)
                )

    def _open_settings_window(self) -> None:
        """打开完整配置窗口，按顶层 key 自动生成选项卡。"""
        if self.busy:
            return
        if self.settings_window is not None and self.settings_window.winfo_exists():
            self.settings_window.lift()
            self.settings_window.focus()
            return

        self.full_config = self.config_manager.get_full_config()
        self.available_fonts = self._load_available_fonts()
        self.settings_vars = {
            "window_width": tk.StringVar(value=str(self.window_width)),
            "window_height": tk.StringVar(value=str(self.window_height)),
            "family": tk.StringVar(value=self._normalize_font_family(self.font_settings.get("family", "宋体"))),
            "size": tk.StringVar(value=str(self._normalize_font_size(self.font_settings.get("size", 13)))),
            "bold": tk.BooleanVar(value=bool(self.font_settings.get("bold", False))),
            "italic": tk.BooleanVar(value=bool(self.font_settings.get("italic", False))),
            "surface_corner_radius": tk.StringVar(value=str(self.surface_style.get("corner_radius", 12))),
            "surface_shadow_blur": tk.StringVar(value=str(self.surface_style.get("shadow_blur", 10))),
            "surface_shadow_offset_y": tk.StringVar(value=str(self.surface_style.get("shadow_offset_y", 3))),
            "surface_shadow_alpha": tk.StringVar(value=str(self.surface_style.get("shadow_alpha", 72))),
            "surface_shadow_margin": tk.StringVar(value=str(self.surface_style.get("shadow_margin", 6))),
            "surface_glass_opacity": tk.StringVar(value=str(self.surface_style.get("glass_opacity", 0.2))),
            "surface_glass_blur": tk.StringVar(value=str(self.surface_style.get("glass_blur", 12))),
            "surface_enable_glass": tk.BooleanVar(value=bool(self.surface_style.get("enable_glass", True))),
        }
        for key, _label_text in COLOR_FIELDS:
            self.settings_vars[key] = tk.StringVar(value=self.colors[key])
        for variable in self.settings_vars.values():
            variable.trace_add("write", lambda *_args: self._refresh_settings_preview())
        self.settings_vars["family"].trace_add("write", lambda *_args: self._sync_font_list_selection())

        self.settings_status_var = tk.StringVar(value="预览")
        self.settings_window = ctk.CTkToplevel(self.root)
        self.settings_window.title("配置设置")
        self._center_toplevel_to_root(self.settings_window, width=980, height=860)
        self.settings_window.minsize(860, 760)
        self.settings_window.configure(fg_color=self.colors["bg_color"])
        self.settings_window.transient(self.root)
        self.settings_window.grab_set()
        self.settings_window.protocol("WM_DELETE_WINDOW", self._close_settings_window)

        shell = ctk.CTkFrame(self.settings_window, fg_color="transparent", corner_radius=0)
        shell.pack(fill="both", expand=True, padx=18, pady=18)
        shell.grid_columnconfigure(0, weight=1)
        shell.grid_rowconfigure(1, weight=1)

        header = self._make_card(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="配置编辑器",
            font=self.font_section,
            text_color=self.colors["text_color"],
        ).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            header,
            text="顶部选项卡按 config.json 顶层 key 自动生成；保存后会写回完整配置并实时刷新 GUI 与运行时。",
            font=self.font_small,
            text_color=self.colors["subtext_color"],
        ).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 14))

        self.settings_tabview = ctk.CTkTabview(
            shell,
            fg_color=self._get_surface_fg_color(self.colors["panel_color"]),
            segmented_button_fg_color=self._get_surface_fg_color(self.colors["button_color"]),
            segmented_button_selected_color=self._get_surface_fg_color(self.colors["primary_button"]),
            segmented_button_selected_hover_color=self._get_surface_fg_color(self.colors["primary_button_hover"]),
            segmented_button_unselected_color=self._get_surface_fg_color(self.colors["button_color"]),
            segmented_button_unselected_hover_color=self._get_surface_fg_color(self.colors["button_hover"]),
            text_color=self.colors["text_color"],
            corner_radius=self._get_surface_corner_radius(),
        )
        self.settings_tabview.grid(row=1, column=0, sticky="nsew")

        for top_key, top_value in self.full_config.items():
            tab = self.settings_tabview.add(top_key)
            if top_key == "gui":
                self._build_gui_settings_tab(tab)
            else:
                self._build_dynamic_config_tab(tab, top_key, top_value)

        footer = self._make_card(shell)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            footer,
            textvariable=self.settings_status_var,
            font=self.font_small,
            text_color=self.colors["subtext_color"],
            anchor="w",
            justify="left",
        ).grid(row=0, column=0, sticky="w", padx=16, pady=14)

        action_row = ctk.CTkFrame(footer, fg_color="transparent")
        action_row.grid(row=0, column=1, sticky="e", padx=16, pady=12)

        close_button = ctk.CTkButton(
            action_row,
            text="关闭",
            command=self._close_settings_window,
            width=92,
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(),
        )
        close_button.grid(row=0, column=0, padx=(0, 8))
        self.settings_controls.append(close_button)

        save_button = ctk.CTkButton(
            action_row,
            text="保存",
            command=self._save_settings,
            width=92,
            height=34,
            font=self.font_main,
            **self._button_surface_kwargs(primary=True),
        )
        save_button.grid(row=0, column=1)
        self.settings_controls.append(save_button)

        self._refresh_settings_preview()
        self._update_settings_controls_state()

    def _start_chat(self, user_input: str, attachments=None) -> None:
        """启动普通聊天线程。"""
        session_id = self.selected_session_id or self.runtime.session.get("session_id", "")
        display_text = self._build_user_display_text(user_input, attachments)
        state = self._get_session_task_state(session_id)
        state["pending_user_display"] = display_text
        state["notices"] = []
        self._set_session_busy(session_id, True, request_kind="chat")
        self._reset_session_stream_state(session_id, keep_pending_user=True)
        self.status_var.set("生成中")
        attachment_count = len(attachments or [])
        if attachment_count:
            self.detail_var.set(f"正在上传并分析 {attachment_count} 个附件，请稍候...")
        else:
            self.detail_var.set("正在请求模型，请稍候...")
        worker = threading.Thread(
            target=self._chat_worker,
            args=(session_id, user_input, list(attachments or [])),
            daemon=True,
        )
        self.session_workers[session_id] = worker
        worker.start()

    def _start_exec(self, task: str, display_text: str | None = None) -> None:
        """启动 exec 工作流线程。"""
        session_id = self.selected_session_id or self.runtime.session.get("session_id", "")
        state = self._get_session_task_state(session_id)
        state["pending_user_display"] = (display_text or f"/exec {task}").strip()
        state["notices"] = []
        self._set_session_busy(session_id, True, request_kind="exec")
        self._reset_session_stream_state(session_id, keep_pending_user=True)
        self.status_var.set("exec 执行中")
        self.detail_var.set("正在生成计划、执行脚本并确认结果...")
        worker = threading.Thread(
            target=self._exec_worker,
            args=(session_id, task),
            daemon=True,
        )
        self.session_workers[session_id] = worker
        worker.start()

    def _start_learn_skill(self, display_text: str | None = None) -> None:
        """启动从当前会话学习 skill 的后台线程。"""
        session_id = self.selected_session_id or self.runtime.session.get("session_id", "")
        state = self._get_session_task_state(session_id)
        state["pending_user_display"] = (display_text or "/skill add").strip()
        state["notices"] = []
        self._set_session_busy(session_id, True, request_kind="skill_add")
        self._reset_session_stream_state(session_id, keep_pending_user=True)
        self.status_var.set("技能学习中")
        self.detail_var.set("正在提取最近成功 exec 流程、生成 skill 并执行验证...")
        worker = threading.Thread(
            target=self._learn_skill_worker,
            args=(session_id,),
            daemon=True,
        )
        self.session_workers[session_id] = worker
        worker.start()

    def _chat_worker(self, session_id: str, user_input: str, attachments=None) -> None:
        """后台线程中执行流式聊天。"""
        info = self.runtime.get_runtime_info_for_session(session_id)
        use_stream = bool(info["stream"])
        show_reasoning = bool(info["show_reasoning"])
        try:
            self.event_queue.put({"type": "stream_reset", "session_id": session_id})

            def on_reasoning_token(token: str):
                if show_reasoning and token:
                    self.event_queue.put({"type": "reasoning_token", "session_id": session_id, "text": token})

            def on_answer_token(token: str):
                if token:
                    self.event_queue.put({"type": "answer_token", "session_id": session_id, "text": token})

            def exec_callback(event: dict):
                event_type = event.get("type")
                if event_type in {"exec_phase", "exec_plan", "exec_verify", "exec_step_start"}:
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": event.get("message", "")})
                elif event_type == "skill_phase":
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": f"[skill] {event.get('message', '')}"})
                elif event_type == "skill_result":
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": f"[skill] 已完成：{event.get('skill_name', '')}"})
                elif event_type == "exec_report":
                    report_path = event.get("report_path", "")
                    if report_path:
                        self.event_queue.put(
                            {"type": "exec_log", "session_id": session_id, "text": f"已生成执行报告：{report_path}"}
                        )
                elif event_type == "exec_step_done":
                    step_result = event.get("step_result", {})
                    lines = [
                        event.get("message", ""),
                        f"stdout：{step_result.get('stdout', '').strip()}",
                        f"stderr：{step_result.get('stderr', '').strip()}",
                    ]
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": "\n".join(lines)})

            reply = self.runtime.chat_on_session(
                session_id,
                user_input,
                attachments=attachments,
                on_answer_token=on_answer_token if use_stream else None,
                on_reasoning_token=on_reasoning_token if use_stream else None,
                exec_callback=exec_callback,
            )

            if not use_stream and reply:
                self.event_queue.put({"type": "answer_token", "session_id": session_id, "text": reply})

            self.event_queue.put({"type": "chat_done", "session_id": session_id, "reply": reply})
        except Exception as exc:
            self.event_queue.put({"type": "error", "session_id": session_id, "message": f"模型调用失败：{exc}"})

    def _exec_worker(self, session_id: str, task: str) -> None:
        """后台线程中执行 exec 工作流。"""
        try:
            self.event_queue.put({"type": "stream_reset", "session_id": session_id})

            def exec_callback(event: dict):
                event_type = event.get("type")
                if event_type in {"exec_phase", "exec_plan", "exec_verify", "exec_step_start"}:
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": event.get("message", "")})
                elif event_type == "exec_report":
                    report_path = event.get("report_path", "")
                    if report_path:
                        self.event_queue.put(
                            {"type": "exec_log", "session_id": session_id, "text": f"已生成执行报告：{report_path}"}
                        )
                elif event_type == "exec_step_done":
                    step_result = event.get("step_result", {})
                    lines = [
                        event.get("message", ""),
                        f"stdout：{step_result.get('stdout', '').strip()}",
                        f"stderr：{step_result.get('stderr', '').strip()}",
                    ]
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": "\n".join(lines)})

            result = self.runtime.execute_exec_workflow_on_session(session_id, task, callback=exec_callback)
            self.event_queue.put({"type": "exec_done", "session_id": session_id, "task": task, "result": result})
        except Exception as exc:
            self.event_queue.put({"type": "error", "session_id": session_id, "message": f"exec 执行失败：{exc}"})

    def _learn_skill_worker(self, session_id: str) -> None:
        """后台线程中从当前会话学习 skill。"""
        try:
            self.event_queue.put({"type": "stream_reset", "session_id": session_id})

            def skill_callback(event: dict):
                event_type = event.get("type")
                if event_type == "skill_phase":
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": f"[skill] {event.get('message', '')}"})
                elif event_type == "skill_result":
                    self.event_queue.put({"type": "exec_log", "session_id": session_id, "text": f"[skill] 已生成：{event.get('skill_name', '')}"})

            result = self.runtime.learn_skill_from_session(session_id, callback=skill_callback)
            self.event_queue.put({"type": "skill_done", "session_id": session_id, "result": result})
        except Exception as exc:
            self.event_queue.put({"type": "error", "session_id": session_id, "message": f"skill 学习失败：{exc}"})

    def _start_end_session(self, auto_new_session: bool = False) -> None:
        """启动结束会话线程，可选择是否自动新建下一个会话。"""
        if self.archive_in_progress:
            self._append_chat_line("系统：上一轮会话归档仍在后台处理中，请稍后再试 /endsession。")
            self.detail_var.set("后台摘要仍在生成中，当前可继续聊天和操作设置。")
            return
        self._set_archive_in_progress(True)
        archive_context = self.runtime.begin_end_session(auto_new_session=auto_new_session)
        if auto_new_session:
            self._load_session()
            self._refresh_session_list(selected_id=self.selected_session_id)
            self._render_current_session_history()
        self.status_var.set("后台归档中")
        if auto_new_session:
            self.detail_var.set("上一会话正在后台生成摘要，可继续聊天、切换会话和调整设置。")
        else:
            self.detail_var.set("当前会话正在后台生成摘要，完成后会保留在原会话中。")
        self._update_input_info()
        if auto_new_session:
            self._append_chat_line("系统：上一会话已结束，摘要正在后台生成。当前已切换到新会话。")
        else:
            self._append_chat_line("系统：当前会话已结束，摘要正在后台生成，结束后不会自动新建会话。")
        self.worker = threading.Thread(
            target=self._end_session_worker,
            args=(archive_context, auto_new_session),
            daemon=True,
        )
        self.worker.start()

    def _end_session_worker(self, archive_context: dict, auto_new_session: bool) -> None:
        """后台线程中归档会话。"""
        try:
            archive_data = self.runtime.finalize_end_session(archive_context)
            self.event_queue.put(
                {
                    "type": "end_done",
                    "archive_data": archive_data,
                    "auto_new_session": auto_new_session,
                    "ended_session_id": archive_context.get("session", {}).get("session_id", ""),
                }
            )
        except Exception as exc:
            self.event_queue.put({"type": "end_error", "message": f"结束会话失败：{exc}"})

    def _handle_remove_records(self) -> None:
        """删除当前用户记录，并刷新界面。"""
        if self._has_any_busy_session():
            messagebox.showinfo("提示", "当前仍有会话请求在运行，请等待全部完成后再删除记录。")
            return
        if self.archive_in_progress:
            messagebox.showinfo("提示", "当前仍有会话摘要在后台生成，请稍后再删除记录。")
            return
        confirm = messagebox.askyesno("确认", "确定要删除当前用户的全部会话记录文件吗？")
        if not confirm:
            self._append_chat_line("系统：已取消删除记录。")
            return

        removed_count, _ = self.runtime.remove_records(auto_new_session=True)
        self._load_session()
        self._refresh_session_list()
        self._render_start_message()
        self._append_chat_line(f"系统：已删除当前用户的 {removed_count} 个会话记录文件。")
        self.status_var.set("记录已删除")
        self.detail_var.set("MEMORY、session_state 与 EXEC 中当前用户记录已清空")

    def _handle_remove_session(self, session_id: str) -> None:
        """删除单个会话，并在必要时切换到其他会话。"""
        target_id = str(session_id).strip()
        if not target_id:
            return
        if self._is_session_busy(target_id):
            messagebox.showinfo("提示", "目标会话仍在处理中，请等待完成后再删除。")
            return
        if self.archive_in_progress:
            messagebox.showinfo("提示", "当前仍有会话摘要在后台生成，请稍后再删除会话。")
            return
        if not any(item.get("id") == target_id for item in self.session_items):
            self._append_chat_line(f"系统：未找到会话：{target_id}")
            self.status_var.set("删除失败")
            self.detail_var.set("指定的 session_id 不存在。")
            return
        confirm = messagebox.askyesno("确认", f"确定要删除会话 {target_id} 吗？")
        if not confirm:
            self._append_chat_line("系统：已取消删除单个会话。")
            return

        try:
            result = self.runtime.remove_session(target_id)
        except ValueError as exc:
            messagebox.showerror("删除失败", str(exc))
            return

        removed_title = result.get("removed_title", "") or target_id
        self.session_task_states.pop(target_id, None)
        self._load_session()
        self._refresh_session_list(selected_id=result.get("current_session_id") or self.selected_session_id)
        self._render_current_session_history()
        self._append_chat_line(f"系统：已删除会话 [{target_id}] {removed_title}")
        self.status_var.set("会话已删除")
        if result.get("switched"):
            if result.get("created_new"):
                self.detail_var.set("已删除当前会话，因无剩余会话，系统已自动新建空白会话。")
            else:
                self.detail_var.set(f"已删除当前会话，并切换到：{result.get('current_session_id', '')}")
        else:
            self.detail_var.set(f"已删除指定会话：{target_id}")
        self._update_input_info()

    def _reset_after_end(self, archive_data: dict, auto_new_session: bool = False, ended_session_id: str = "") -> None:
        """结束会话后的界面收尾；可选择保留当前会话或切到新会话。"""
        self._load_session()
        selected_id = self.selected_session_id
        if not auto_new_session and ended_session_id:
            selected_id = str(ended_session_id).strip() or selected_id
        self._refresh_session_list(selected_id=selected_id)
        if selected_id:
            self.selected_session_id = selected_id
        self._render_current_session_history()
        self._update_input_info()
        if not self._has_any_busy_session():
            self.status_var.set("已归档")
            summary = archive_data.get("msg", "").replace("\n", " ").strip()
            if len(summary) > 80:
                summary = summary[:80] + "..."
            if auto_new_session:
                self.detail_var.set(f"上一会话已后台归档完成。摘要：{summary}")
            else:
                self.detail_var.set(f"当前会话已结束并完成摘要：{summary}")

    def _poll_event_queue(self) -> None:
        """轮询后台线程事件，并在主线程安全更新 GUI。"""
        processed = 0
        should_refresh_session_list = False
        dirty_process_sessions: set[str] = set()
        pending_stream_updates: dict[tuple[str, str], list[str]] = {}
        should_scroll_stream = False
        while processed < EVENT_POLL_BATCH_SIZE:
            try:
                event = self.event_queue.get_nowait()
            except queue.Empty:
                break
            processed += 1

            event_type = event.get("type")
            event_session_id = str(event.get("session_id", "")).strip()
            if event_type == "stream_reset":
                self._reset_session_stream_state(event_session_id, keep_pending_user=True)
            elif event_type == "reasoning_token":
                token = event.get("text", "")
                if token:
                    pending_stream_updates.setdefault((event_session_id, "thinking"), []).append(token)
            elif event_type == "exec_log":
                state = self._get_session_task_state(event_session_id)
                block = str(event.get("text", "")).strip()
                if block:
                    current_process = str(state.get("draft_process", "")).strip()
                    state["draft_process"] = f"{current_process}\n\n{block}".strip() if current_process else block
                if event_session_id == self.selected_session_id:
                    request_kind = state.get("request_kind", "")
                    self.status_var.set("技能学习中" if request_kind == "skill_add" else "exec 执行中")
                    latest = event.get("text", "").splitlines()
                    if latest:
                        self.detail_var.set(latest[-1][:120])
                    dirty_process_sessions.add(event_session_id)
                should_refresh_session_list = True
            elif event_type == "answer_token":
                token = event.get("text", "")
                if token:
                    pending_stream_updates.setdefault((event_session_id, "assistant"), []).append(token)
            elif event_type == "chat_done":
                state = self._get_session_task_state(event_session_id)
                reply = str(event.get("reply", ""))
                for pending_role in ("thinking", "assistant"):
                    pending_chunks = pending_stream_updates.pop((event_session_id, pending_role), [])
                    merged = "".join(pending_chunks)
                    if merged:
                        self._append_stream_text(event_session_id, pending_role, merged)
                        if event_session_id == self.selected_session_id:
                            should_scroll_stream = True
                if event_session_id == self.selected_session_id and not state.get("answer_started") and reply:
                    self._append_chat_line(f"AI：{reply}")
                elif event_session_id == self.selected_session_id and self.current_reasoning_widget is not None:
                    self._render_markdown_message(self.current_reasoning_widget)
                if event_session_id == self.selected_session_id and self.current_answer_widget is not None:
                    if reply:
                        self.current_answer_widget._message_body = reply
                        state["draft_answer"] = reply
                    self._render_markdown_message(self.current_answer_widget)
                state["pending_user_display"] = ""
                state["draft_reasoning"] = ""
                state["draft_answer"] = ""
                state["draft_process"] = ""
                state["notices"] = []
                state["answer_started"] = False
                state["reasoning_started"] = False
                self.session_workers.pop(event_session_id, None)
                self._set_session_busy(event_session_id, False)
                if event_session_id == self.selected_session_id:
                    self.status_var.set("完成")
                    self.detail_var.set("本轮对话已完成，当前会话上下文已保存")
                should_refresh_session_list = True
            elif event_type == "end_done":
                self._set_archive_in_progress(False)
                self._reset_after_end(
                    event["archive_data"],
                    auto_new_session=bool(event.get("auto_new_session", False)),
                    ended_session_id=str(event.get("ended_session_id", "")).strip(),
                )
            elif event_type == "end_error":
                self._set_archive_in_progress(False)
                self.status_var.set("归档失败")
                self.detail_var.set(event.get("message", "结束会话失败。"))
                self._append_chat_line(f"系统：{event.get('message', '结束会话失败。')}")
            elif event_type == "exec_done":
                result = event.get("result", {})
                report = result.get("chat_report", "").strip()
                state = self._get_session_task_state(event_session_id)
                if event_session_id == self.selected_session_id and report:
                    self._append_chat_line(f"AI：{report}")
                elif event_session_id == self.selected_session_id:
                    self._append_chat_line("系统：exec 已完成，但未生成可展示的结果报告。")
                state["pending_user_display"] = ""
                state["draft_reasoning"] = ""
                state["draft_answer"] = ""
                state["draft_process"] = ""
                state["notices"] = []
                state["answer_started"] = False
                state["reasoning_started"] = False
                self.session_workers.pop(event_session_id, None)
                self._set_session_busy(event_session_id, False)
                if event_session_id == self.selected_session_id:
                    self.status_var.set("exec 完成")
                    self.detail_var.set(
                        f"exec 报告已写入聊天窗口。报告文件：{result.get('report_path', '') or '未生成'}"
                    )
                should_refresh_session_list = True
            elif event_type == "skill_done":
                result = event.get("result", {})
                report = result.get("chat_report", "").strip()
                state = self._get_session_task_state(event_session_id)
                if event_session_id == self.selected_session_id and report:
                    self._append_chat_line(f"AI：{report}")
                elif event_session_id == self.selected_session_id:
                    self._append_chat_line("系统：skill 已生成，但未返回可展示摘要。")
                state["pending_user_display"] = ""
                state["draft_reasoning"] = ""
                state["draft_answer"] = ""
                state["draft_process"] = ""
                state["notices"] = []
                state["answer_started"] = False
                state["reasoning_started"] = False
                self.session_workers.pop(event_session_id, None)
                self._set_session_busy(event_session_id, False)
                if event_session_id == self.selected_session_id:
                    self.status_var.set("技能学习完成")
                    self.detail_var.set(
                        f"已生成 skill：{result.get('skill_name', '') or '未命名'}，质量评分：{result.get('review', {}).get('overall_score', 0)}"
                    )
                should_refresh_session_list = True
            elif event_type == "error":
                state = self._get_session_task_state(event_session_id)
                message = f"系统：{event.get('message', '发生未知错误。')}"
                state["notices"].append(message)
                state["pending_user_display"] = ""
                state["draft_reasoning"] = ""
                state["draft_answer"] = ""
                state["draft_process"] = ""
                state["answer_started"] = False
                state["reasoning_started"] = False
                self.session_workers.pop(event_session_id, None)
                self._set_session_busy(event_session_id, False)
                if event_session_id == self.selected_session_id:
                    self._append_chat_line(message)
                    self.status_var.set("失败")
                    self.detail_var.set(event.get("message", "发生未知错误。"))
                should_refresh_session_list = True

        for (session_id, role), chunks in pending_stream_updates.items():
            merged = "".join(chunks)
            if merged:
                self._append_stream_text(session_id, role, merged)
                if session_id == self.selected_session_id:
                    should_scroll_stream = True
        for session_id in dirty_process_sessions:
            self._refresh_process_bubble(session_id)
        if dirty_process_sessions or should_scroll_stream:
            self._scroll_chat_to_bottom()
        if should_refresh_session_list:
            self._refresh_session_list(selected_id=self.selected_session_id)

        next_delay = EVENT_POLL_BUSY_INTERVAL_MS if processed >= EVENT_POLL_BATCH_SIZE else EVENT_POLL_INTERVAL_MS
        self.root.after(next_delay, self._poll_event_queue)


def main() -> None:
    root = ctk.CTk()
    AgentGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
