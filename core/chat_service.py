import base64
from pathlib import Path

from core.llm_api import call_llm
from core.prompt_builder import build_chat_prompt


TEXT_ATTACHMENT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".json", ".yaml", ".yml", ".toml", ".ini",
    ".cfg", ".conf", ".csv", ".tsv", ".xml", ".html", ".htm", ".css", ".js", ".ts",
    ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".sh", ".ps1",
    ".bat", ".sql", ".log", ".env",
}
IMAGE_ATTACHMENT_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
TEXT_ATTACHMENT_SIZE_LIMIT = 300_000
IMAGE_ATTACHMENT_SIZE_LIMIT = 5 * 1024 * 1024
IMAGE_ATTACHMENT_BASE64_LIMIT = 1_500_000


class ChatService:
    """负责提示词构造、模型调用与流式回调连接。"""

    def __init__(self, config) -> None:
        self.config = config

    def get_main_config(self):
        """返回主对话模型配置。"""
        return self.config.llm["main_llm"]

    def _read_text_attachment(self, path: Path) -> tuple[str, str]:
        """读取文本附件内容，并在过大时截断。"""
        raw_bytes = path.read_bytes()
        truncated = len(raw_bytes) > TEXT_ATTACHMENT_SIZE_LIMIT
        raw_bytes = raw_bytes[:TEXT_ATTACHMENT_SIZE_LIMIT]
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                text = raw_bytes.decode(encoding)
                break
            except UnicodeDecodeError:
                text = ""
        if not text:
            text = raw_bytes.decode("utf-8", errors="replace")
        notice = "，内容已截断" if truncated else ""
        return text, notice

    def _build_attachment_bundle(self, attachments) -> dict:
        """把附件整理成提示词文本和历史摘要。"""
        files = [Path(item) for item in (attachments or []) if str(item).strip()]
        if not files:
            return {
                "history_suffix": "",
                "prompt_block": "",
            }

        prompt_sections = []
        history_names = []
        for path in files:
            if not path.exists() or not path.is_file():
                prompt_sections.append(f"- {path.name}：文件不存在或不可读取")
                history_names.append(path.name)
                continue

            history_names.append(path.name)
            suffix = path.suffix.lower()
            file_size = path.stat().st_size
            if suffix in IMAGE_ATTACHMENT_EXTENSIONS:
                if file_size > IMAGE_ATTACHMENT_SIZE_LIMIT:
                    prompt_sections.append(f"- {path.name}：图片大于 5MB，未附带 base64 内容，仅提供文件信息")
                    continue
                raw_bytes = path.read_bytes()
                truncated = len(raw_bytes) > IMAGE_ATTACHMENT_BASE64_LIMIT
                encoded = base64.b64encode(raw_bytes[:IMAGE_ATTACHMENT_BASE64_LIMIT]).decode("ascii")
                notice = "，base64 内容已截断" if truncated else ""
                prompt_sections.append(
                    f"### 图片附件：{path.name}\n"
                    f"- 大小：{file_size} 字节{notice}\n"
                    "- 以下为该图片的 base64 编码，请结合文件名和编码内容一起分析：\n"
                    f"```base64\n{encoded}\n```"
                )
                continue

            if suffix in TEXT_ATTACHMENT_EXTENSIONS:
                text, notice = self._read_text_attachment(path)
                prompt_sections.append(
                    f"### 附件：{path.name}\n"
                    f"- 路径：{path}\n"
                    f"- 大小：{file_size} 字节{notice}\n"
                    f"```text\n{text}\n```"
                )
                continue

            prompt_sections.append(
                f"- {path.name}：当前按二进制/未知格式处理，未直接解析内容。"
                f" 路径：{path}；大小：{file_size} 字节"
            )

        prompt_block = "【本轮附件】\n" + "\n\n".join(prompt_sections)
        history_suffix = "\n[附件] " + "，".join(history_names)
        return {
            "history_suffix": history_suffix,
            "prompt_block": prompt_block,
        }

    def build_history_user_input(self, user_input: str, attachments=None) -> str:
        """构造写入 session history 的用户输入摘要。"""
        bundle = self._build_attachment_bundle(attachments)
        return (user_input or "").strip() + bundle["history_suffix"]

    def chat(
        self,
        memory_context: str,
        history,
        user_input: str,
        attachments=None,
        on_answer_token=None,
        on_reasoning_token=None,
    ) -> str:
        """执行普通对话并返回模型回复。"""
        main_cfg = self.get_main_config()
        use_stream = bool(main_cfg.get("stream", False))
        bundle = self._build_attachment_bundle(attachments)
        effective_user_input = (user_input or "").strip()
        if bundle["prompt_block"]:
            effective_user_input = f"{effective_user_input}\n\n{bundle['prompt_block']}".strip()
        prompt = build_chat_prompt(memory_context, history, effective_user_input)
        return call_llm(
            prompt,
            main_cfg["model"],
            main_cfg["key"],
            stream=use_stream,
            on_token=on_answer_token if use_stream else None,
            on_reasoning_token=(
                on_reasoning_token
                if use_stream and bool(main_cfg.get("show_reasoning", False))
                else None
            ),
        ).strip()
