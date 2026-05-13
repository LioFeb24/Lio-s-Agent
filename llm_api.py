"""兼容层：真正模型调用实现已迁移到 core.llm_api。"""

from core.llm_api import call_llm

__all__ = ["call_llm"]
