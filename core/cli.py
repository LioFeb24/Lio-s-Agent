"""兼容入口。真正 CLI 实现已迁移到 app.CLI。"""

from app.CLI import main, print_session_history

__all__ = ["main", "print_session_history"]

if __name__ == "__main__":
    main()
