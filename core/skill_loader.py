from pathlib import Path

from core.constants import SKILLS_DIR


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_quotes(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1]
    return text


def _list_entry_scripts(skill_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in skill_dir.glob("*.py")
            if path.is_file() and path.name not in {"skill_runner.py", "__init__.py"}
        ],
        key=lambda item: item.name.lower(),
    )


def parse_skill_markdown(text: str) -> tuple[dict, str]:
    lines = str(text or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, str(text or "").strip()

    metadata = {}
    body_start = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            body_start = index + 1
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = _strip_quotes(value)

    if body_start is None:
        return metadata, str(text or "").strip()
    body = "\n".join(lines[body_start:]).strip()
    return metadata, body


def extract_markdown_section(body: str, title: str) -> str:
    text = str(body or "").strip()
    if not text:
        return ""
    lines = text.splitlines()
    target = f"## {title}".strip().lower()
    start = None
    for index, line in enumerate(lines):
        if line.strip().lower() == target:
            start = index + 1
            break
    if start is None:
        return ""
    section_lines = []
    for line in lines[start:]:
        if line.strip().startswith("## "):
            break
        section_lines.append(line)
    return "\n".join(section_lines).strip()


class SkillRepository:
    """从项目 SKILLS 目录加载规范化 SKILL.md。"""

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else SKILLS_DIR

    def _skill_dirs(self) -> list[Path]:
        if not self.base_dir.exists():
            return []
        return sorted(
            [item for item in self.base_dir.iterdir() if item.is_dir() and (item / "SKILL.md").exists()],
            key=lambda item: item.name.lower(),
        )

    def _load_skill(self, skill_dir: Path) -> dict:
        skill_path = skill_dir / "SKILL.md"
        raw_content = _read_text_file(skill_path).strip()
        metadata, body = parse_skill_markdown(raw_content)
        description = str(metadata.get("description", "")).strip() or extract_markdown_section(body, "Description")
        entry_scripts = _list_entry_scripts(skill_dir)
        preferred_entry = None
        for path in entry_scripts:
            if path.stem.lower() == skill_dir.name.lower():
                preferred_entry = path
                break
        if preferred_entry is None and entry_scripts:
            preferred_entry = entry_scripts[0]
        files = [
            str(path.relative_to(skill_dir)).replace("\\", "/")
            for path in sorted(skill_dir.rglob("*"), key=lambda item: str(item).lower())
            if path.is_file() and path.name != "SKILL.md"
        ]
        return {
            "folder": skill_dir.name,
            "name": str(metadata.get("name", "")).strip() or skill_dir.name,
            "description": description,
            "body": body,
            "content": raw_content,
            "skill_path": str(skill_path),
            "dir_path": str(skill_dir),
            "files": files,
            "entry_files": [path.name for path in entry_scripts],
            "entry_names": [path.stem for path in entry_scripts],
            "entry_script": str(preferred_entry) if preferred_entry is not None else "",
            "entry_script_name": preferred_entry.name if preferred_entry is not None else "",
            "entry_name": preferred_entry.stem if preferred_entry is not None else "",
        }

    def list_skills(self) -> list[dict]:
        skills = []
        for skill_dir in self._skill_dirs():
            skill = self._load_skill(skill_dir)
            skills.append(
                {
                    "folder": skill["folder"],
                    "name": skill["name"],
                    "description": skill["description"],
                    "skill_path": skill["skill_path"],
                    "dir_path": skill["dir_path"],
                    "files": skill["files"],
                    "entry_files": skill["entry_files"],
                    "entry_names": skill["entry_names"],
                    "entry_script": skill["entry_script"],
                    "entry_script_name": skill["entry_script_name"],
                    "entry_name": skill["entry_name"],
                }
            )
        return skills

    def resolve_skill_entry(self, name: str) -> tuple[dict, str]:
        target = str(name or "").strip().lower()
        if not target:
            raise ValueError("skill 名称不能为空。")

        folder_or_name_match = None
        entry_match = None
        for skill_dir in self._skill_dirs():
            skill = self._load_skill(skill_dir)
            if skill["folder"].lower() == target or skill["name"].lower() == target:
                if skill["entry_script"]:
                    return skill, skill["entry_script"]
                folder_or_name_match = skill
            if target in {item.lower() for item in skill.get("entry_names", [])}:
                if entry_match is not None and entry_match[0]["folder"].lower() != skill["folder"].lower():
                    raise ValueError(f"skill 入口名重复：{name}，请改用 skill 文件夹名。")
                for path in _list_entry_scripts(skill_dir):
                    if path.stem.lower() == target:
                        entry_match = (skill, str(path))
                        break

        if entry_match is not None:
            return entry_match
        if folder_or_name_match is not None and folder_or_name_match.get("entry_script"):
            return folder_or_name_match, folder_or_name_match["entry_script"]
        raise ValueError(f"未找到可执行 skill：{name}")

    def get_skill(self, name: str) -> dict:
        target = str(name or "").strip().lower()
        if not target:
            raise ValueError("skill 名称不能为空。")

        for skill_dir in self._skill_dirs():
            skill = self._load_skill(skill_dir)
            if skill["folder"].lower() == target or skill["name"].lower() == target:
                return skill
            if target in {item.lower() for item in skill.get("entry_names", [])}:
                return skill
        raise ValueError(f"未找到 skill：{name}")

    def render_skill_overview(self, name: str) -> str:
        skill = self.get_skill(name)
        lines = [
            f"技能：{skill['folder']}",
            f"- 名称：{skill['name']}",
            f"- 描述：{skill['description'] or '无'}",
            f"- 目录：{skill['dir_path']}",
            f"- 入口文件：{skill['skill_path']}",
            f"- 可执行脚本：{skill['entry_script_name'] or '无'}",
            f"- 可调用名：{', '.join(skill['entry_names']) if skill['entry_names'] else skill['folder']}",
            f"- 附属文件：{', '.join(skill['files']) if skill['files'] else '无'}",
            "",
            "## SKILL.md",
            skill["content"],
        ]
        return "\n".join(lines).strip()
