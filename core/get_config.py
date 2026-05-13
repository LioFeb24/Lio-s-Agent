import copy
import json
from pathlib import Path

from core.constants import BASE_DIR


DEFAULT_GUI_CONFIG = {
    "window": {
        "width": 1360,
        "height": 860,
    },
    "chat_font": {
        "family": "宋体",
        "size": 13,
        "bold": False,
        "italic": False,
    },
    "theme_preset": "自定义",
    "surface_style": {
        "corner_radius": 12,
        "shadow_blur": 10,
        "shadow_offset_y": 3,
        "shadow_alpha": 72,
        "shadow_margin": 6,
        "glass_opacity": 0.2,
        "glass_blur": 12,
        "enable_glass": True,
    },
    "colors": {
        "bg_color": "#F3F6FB",
        "card_color": "#FFFFFF",
        "panel_color": "#F7F9FC",
        "input_box_color": "#FFFFFF",
        "text_color": "#1F2937",
        "subtext_color": "#6B7280",
        "button_color": "#E8F1FF",
        "button_hover": "#D8E8FF",
        "primary_button": "#4F8CFF",
        "primary_button_hover": "#3D7AF0",
        "primary_text": "#FFFFFF",
        "border_color": "#D8E2EE",
        "selected_color": "#E6F0FF",
        "reasoning_color": "#64748B",
        "user_bubble": "#EAF3FF",
        "ai_bubble": "#DCEAFF",
        "system_bubble": "#F5F7FA",
        "thinking_bubble": "#F3F4F6",
        "exec_mode_border": "#E8D58A",
        "exec_mode_button": "#F3E3A1",
        "exec_mode_button_hover": "#E8D58A",
        "exec_mode_hint": "#8A6F00",
    },
}

DEFAULT_SANDBOX_CONFIG = {
    "enabled": False,
    "provider": "cubesandbox",
    "backend": "e2b",
    "api_key": "",
    "domain": "",
    "template": "",
    "timeout_seconds": 600,
    "command_timeout_seconds": 120,
    "workspace_root": "/workspace",
    "sync_project_on_start": True,
    "sync_back_to_host": False,
    "kill_after_run": True,
    "allow_external_paths": False,
    "max_sync_files": 200,
    "max_file_size_kb": 256,
    "sync_include": [
        "*.py",
        "*.json",
        "*.md",
        "*.txt"
    ],
    "sync_ignore": [
        "env/**",
        ".git/**",
        "__pycache__/**",
        "EXEC/**",
        "MEMORY/**",
        "session_state/**",
        "*.pyc"
    ],
    "envs": {}
}

DEFAULT_SKILL_REVIEW_CONFIG = {
    "threshold": 5.0,
}

DEFAULT_SKILL_LEARNING_CONFIG = {
    "temp_validation_enabled": True,
    "max_repair_rounds": 1,
}

DEFAULT_EXEC_CONFIG = {
    "retry_limit": 3,
    "review_after_retry_limit": 3,
    "max_steps": 20,
    "max_expand_depth": 3,
    "independent_llm_step_context_enabled": True,
    "planner_runtime_context_enabled": True,
    "planner_include_system_info": True,
    "planner_include_project_info": True,
    "planner_include_env_vars": False,
    "planner_env_var_keys": [
        "OS",
        "COMSPEC",
        "PATHEXT",
        "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS",
        "USERNAME",
        "USERPROFILE",
        "TEMP",
        "TMP",
        "VIRTUAL_ENV",
        "CONDA_DEFAULT_ENV",
        "NODE_ENV",
    ],
    "planner_project_entry_limit": 40,
}

SKILL_REVIEW_ALLOWED_KEYS = tuple(DEFAULT_SKILL_REVIEW_CONFIG.keys())
SKILL_LEARNING_ALLOWED_KEYS = tuple(DEFAULT_SKILL_LEARNING_CONFIG.keys())


def _deep_merge(defaults: dict, actual: dict) -> dict:
    """把缺失字段按默认值补齐，同时保留已有配置。"""
    merged = copy.deepcopy(defaults)
    for key, value in (actual or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _filter_allowed_keys(raw: dict, allowed_keys: tuple[str, ...]) -> dict:
    """仅保留允许的配置键，避免废弃字段继续出现在 GUI 与保存结果中。"""
    if not isinstance(raw, dict):
        return {}
    return {key: value for key, value in raw.items() if key in allowed_keys}


class Config:
    """负责读取、补齐并写回本地 config.json 配置。"""

    DEFAULT_GUI_CONFIG = DEFAULT_GUI_CONFIG
    DEFAULT_SANDBOX_CONFIG = DEFAULT_SANDBOX_CONFIG
    DEFAULT_SKILL_REVIEW_CONFIG = DEFAULT_SKILL_REVIEW_CONFIG
    DEFAULT_SKILL_LEARNING_CONFIG = DEFAULT_SKILL_LEARNING_CONFIG
    DEFAULT_EXEC_CONFIG = DEFAULT_EXEC_CONFIG

    def __init__(self, config_file: str = "config.json"):
        config_path = Path(config_file)
        if not config_path.is_absolute():
            config_path = BASE_DIR / config_file

        self.config_path = config_path
        self.config = {}
        self.llm = {}
        self.agent = {}
        self.reload()

    def reload(self) -> None:
        """重新读取配置文件并补齐默认 GUI 配置。"""
        last_err = None
        loaded = None
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(self.config_path, "r", encoding=enc) as f:
                    loaded = json.load(f)
                last_err = None
                break
            except UnicodeDecodeError as exc:
                last_err = exc

        if last_err is not None:
            raise last_err

        loaded = loaded or {}
        loaded["gui"] = _deep_merge(self.DEFAULT_GUI_CONFIG, loaded.get("gui", {}))
        loaded["exec"] = _deep_merge(self.DEFAULT_EXEC_CONFIG, loaded.get("exec", {}))
        loaded["sandbox"] = _deep_merge(self.DEFAULT_SANDBOX_CONFIG, loaded.get("sandbox", loaded.get("sendbox", {})))
        loaded["skill_review"] = _deep_merge(
            self.DEFAULT_SKILL_REVIEW_CONFIG,
            _filter_allowed_keys(loaded.get("skill_review", {}), SKILL_REVIEW_ALLOWED_KEYS),
        )
        loaded["skill_learning"] = _deep_merge(
            self.DEFAULT_SKILL_LEARNING_CONFIG,
            _filter_allowed_keys(loaded.get("skill_learning", {}), SKILL_LEARNING_ALLOWED_KEYS),
        )
        llm_config = copy.deepcopy(loaded.get("llm", {}) or {})
        main_llm = copy.deepcopy(llm_config.get("main_llm", {}) or {})
        router_defaults = {
            "key": main_llm.get("key", ""),
            "model": main_llm.get("model", ""),
            "stream": False,
            "recent_rounds": 2,
        }
        llm_config["intent_router"] = _deep_merge(router_defaults, llm_config.get("intent_router", {}))
        loaded["llm"] = llm_config
        self.config = loaded
        self.llm = self.config["llm"]
        self.agent = self.config["agent"]

    def save(self) -> None:
        """把当前配置写回 config.json。"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, ensure_ascii=False, indent=4)
            f.write("\n")

    def get_gui_config(self) -> dict:
        """返回 GUI 配置副本，避免界面层直接改写内部状态。"""
        return copy.deepcopy(self.config.get("gui", self.DEFAULT_GUI_CONFIG))

    def get_full_config(self) -> dict:
        """返回完整 config.json 的副本。"""
        return copy.deepcopy(self.config)

    def update_gui_config(self, gui_config: dict) -> dict:
        """更新 GUI 配置并保存，返回补齐后的最终配置。"""
        merged = _deep_merge(self.DEFAULT_GUI_CONFIG, gui_config or {})
        self.config["gui"] = merged
        self.save()
        self.reload()
        return self.get_gui_config()

    def update_full_config(self, full_config: dict) -> dict:
        """更新完整配置并保存，返回重新补齐后的最终结果。"""
        merged = copy.deepcopy(full_config or {})
        merged["gui"] = _deep_merge(self.DEFAULT_GUI_CONFIG, merged.get("gui", {}))
        merged["exec"] = _deep_merge(self.DEFAULT_EXEC_CONFIG, merged.get("exec", {}))
        sandbox_source = merged.get("sandbox", merged.get("sendbox", {}))
        merged["sandbox"] = _deep_merge(self.DEFAULT_SANDBOX_CONFIG, sandbox_source)
        merged["skill_review"] = _deep_merge(
            self.DEFAULT_SKILL_REVIEW_CONFIG,
            _filter_allowed_keys(merged.get("skill_review", {}), SKILL_REVIEW_ALLOWED_KEYS),
        )
        merged["skill_learning"] = _deep_merge(
            self.DEFAULT_SKILL_LEARNING_CONFIG,
            _filter_allowed_keys(merged.get("skill_learning", {}), SKILL_LEARNING_ALLOWED_KEYS),
        )
        llm_config = copy.deepcopy(merged.get("llm", {}) or {})
        main_llm = copy.deepcopy(llm_config.get("main_llm", {}) or {})
        router_defaults = {
            "key": main_llm.get("key", ""),
            "model": main_llm.get("model", ""),
            "stream": False,
            "recent_rounds": 2,
        }
        llm_config["intent_router"] = _deep_merge(router_defaults, llm_config.get("intent_router", {}))
        merged["llm"] = llm_config
        self.config = merged
        self.save()
        self.reload()
        return self.get_full_config()
