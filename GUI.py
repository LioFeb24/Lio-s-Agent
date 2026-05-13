"""顶层 GUI 兼容入口。真正界面实现已迁移到 app.GUI。"""

from app.GUI import AgentGUI, main

__all__ = ["AgentGUI", "main"]

if __name__ == "__main__":
    main()
