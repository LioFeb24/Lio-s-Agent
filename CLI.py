"""顶层 GUI 兼容入口。真正界面实现已迁移到 app.GUI。"""

from app.CLI import main

__all__ = ["AgentCLI"]

if __name__ == "__main__":
    main()
