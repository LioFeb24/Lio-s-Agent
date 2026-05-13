import json
import platform
from pathlib import Path

from core.format_llm_output import call_llm_structured, handle
from core.skill_loader import SkillRepository


class SkillReviewService:
    """使用辅助 LLM 审查 Skill 质量，输出结构化评分结果。"""

    DEFAULT_THRESHOLD = 7.0
    METADATA_CANDIDATES = ("skill.json", "skill.yaml", "skill.yml")

    def __init__(self, config, skill_repository: SkillRepository | None = None) -> None:
        self.config = config
        self.skill_repository = skill_repository or SkillRepository()

    def _to_text(self, value) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        return str(value)

    def _read_text_file(self, path: Path) -> str:
        for encoding in ("utf-8-sig", "utf-8", "gbk"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="replace")

    def _get_helper_llm_config(self) -> dict:
        """读取辅助 LLM 配置，不存在时回退到主模型。"""
        llm_config = getattr(self.config, "llm", {}) or {}
        helper_cfg = llm_config.get("helper_llm") or llm_config.get("intent_router") or llm_config.get("router_llm")
        if isinstance(helper_cfg, dict):
            key = self._to_text(helper_cfg.get("key", "")).strip()
            model = self._to_text(helper_cfg.get("model", "")).strip()
            if key and model:
                return {
                    "key": key,
                    "model": model,
                }

        main_cfg = (llm_config.get("main_llm") or {}) if isinstance(llm_config, dict) else {}
        return {
            "key": self._to_text(main_cfg.get("key", "")).strip(),
            "model": self._to_text(main_cfg.get("model", "")).strip(),
        }

    def _load_repository_skill(self, skill_name: str) -> dict:
        skill = self.skill_repository.get_skill(skill_name)
        skill_dir = Path(skill["dir_path"])

        metadata_path = ""
        metadata_content = ""
        for candidate in self.METADATA_CANDIDATES:
            path = skill_dir / candidate
            if path.exists():
                metadata_path = str(path)
                metadata_content = self._read_text_file(path).strip()
                break

        runner_files = []
        for relative_name in skill.get("files", []):
            if relative_name.lower().endswith(".py"):
                runner_files.append(relative_name)

        runner_content = ""
        runner_path = ""
        if runner_files:
            runner_path = str(skill_dir / runner_files[0])
            runner_content = self._read_text_file(Path(runner_path)).strip()

        return {
            "name": skill.get("name") or skill.get("folder") or skill_name,
            "folder": skill.get("folder") or skill_name,
            "description": skill.get("description", ""),
            "skill_path": skill.get("skill_path", ""),
            "skill_content": skill.get("content", ""),
            "runner_path": runner_path,
            "runner_content": runner_content,
            "metadata_path": metadata_path,
            "metadata_content": metadata_content,
        }

    def _parse_metadata(self, metadata_content: str) -> tuple[str, object]:
        text = self._to_text(metadata_content).strip()
        if not text:
            return "", None

        parsed = handle("auto", text, "parse")
        if parsed.get("success"):
            return parsed.get("type", ""), parsed.get("data")
        return "", None

    def _get_runtime_context(self) -> dict:
        system_name = platform.system().strip() or "Unknown"
        is_windows = system_name.lower().startswith("win")
        return {
            "system": system_name,
            "shell": "PowerShell" if is_windows else "system shell",
            "is_windows": is_windows,
        }

    def _get_threshold(self) -> float:
        config_data = getattr(self.config, "config", {}) or {}
        skill_review = config_data.get("skill_review", {}) if isinstance(config_data, dict) else {}
        raw_value = skill_review.get("threshold", self.DEFAULT_THRESHOLD) if isinstance(skill_review, dict) else self.DEFAULT_THRESHOLD
        try:
            threshold = float(raw_value)
        except (TypeError, ValueError):
            threshold = self.DEFAULT_THRESHOLD
        if threshold < 0:
            threshold = 0.0
        if threshold > 10:
            threshold = 10.0
        return round(threshold, 2)

    def _build_review_prompt(
        self,
        skill_name: str,
        skill_markdown: str,
        runner_content: str,
        metadata_content: str,
        validation_log: str,
        expected_goal: str,
    ) -> str:
        metadata_type, metadata_data = self._parse_metadata(metadata_content)
        metadata_preview = self._to_text(metadata_data).strip() if metadata_data is not None else self._to_text(metadata_content).strip()
        runtime_context = self._get_runtime_context()
        return f"""
你是一个严格的 Skill 质量审查器。

任务：
审查下面这个 Skill 是否符合预期，并给出结构化评分。

评分规则：
1. 使用 0-10 分，10 分最高。
2. 你必须分别给出以下三个维度的分数：
   - reusability：可复用性
   - stability：稳定性
   - abstraction：抽象程度
3. 你还必须给出 overall_score，取综合判断后的总分，范围也是 0-10。
4. 当 overall_score >= 配置阈值时，expected_fit 为 true；否则为 false。
5. 不要因为表述漂亮而高分，必须优先考虑是否真的可执行、是否有参数抽象、是否有清晰校验和失败处理。
6. 如果存在明显问题，必须在 problems 中给出结构化原因和修复建议。
7. 评审必须结合当前运行环境，不要默认要求跨平台。

输出要求：
只输出结构化数据，优先 JSON。
字段必须包含：
{{
  "expected_fit": true,
  "overall_score": 0,
  "dimensions": {{
    "reusability": 0,
    "stability": 0,
    "abstraction": 0
  }},
  "summary": "一句话总结",
  "strengths": ["优点1", "优点2"],
  "problems": [
    {{
      "dimension": "reusability",
      "score_impact": 0,
      "reason": "扣分原因",
      "suggestion": "修复建议"
    }}
  ]
}}

符合预期的定义：
- 结构完整
- 具有明确用途
- 具备可执行或接近可执行的流程
- 参数不要全部硬编码
- 尽量避免不必要的环境强绑定
- 校验逻辑清晰

当前运行环境：
- 操作系统：{runtime_context["system"]}
- 默认命令环境：{runtime_context["shell"]}
- 当前通过阈值：{self._get_threshold()}
- 若当前环境是 Windows，则 PowerShell / `dir` / `findstr` / `New-Item` / 反斜杠路径不应仅因“非跨平台”被重罚。
- 只有当命令在当前环境中不可执行、无法验证、或与项目目标冲突时，才应在 stability / reusability 上明显扣分。

期望目标：
{expected_goal or "审查 skill 是否适合作为项目中的可复用技能。"}

Skill Name:
{skill_name}

SKILL.md:
```markdown
{skill_markdown}
```

可执行脚本:
```python
{runner_content or "# 当前未提供可执行脚本"}
```

Skill 元信息格式：
{metadata_type or "unknown"}

Skill 元信息内容：
```text
{metadata_preview or "当前未提供 skill 元信息"}
```

验证日志：
```text
{validation_log or "当前未提供验证日志"}
```
""".strip()

    def _unwrap_review_mapping(self, value):
        if isinstance(value, dict):
            if {"overall_score", "dimensions"}.intersection(value.keys()):
                return value
            for nested in value.values():
                found = self._unwrap_review_mapping(nested)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for item in value:
                found = self._unwrap_review_mapping(item)
                if found is not None:
                    return found
        return None

    def _normalize_score(self, value) -> float:
        try:
            score = float(value)
        except (TypeError, ValueError):
            score = 0.0
        if score < 0:
            return 0.0
        if score > 10:
            return 10.0
        return round(score, 2)

    def _normalize_problems(self, value) -> list[dict]:
        problems = []
        if not isinstance(value, list):
            return problems
        for item in value:
            if not isinstance(item, dict):
                continue
            problems.append(
                {
                    "dimension": self._to_text(item.get("dimension", "")).strip(),
                    "score_impact": self._normalize_score(item.get("score_impact", 0)),
                    "reason": self._to_text(item.get("reason", "")).strip(),
                    "suggestion": self._to_text(item.get("suggestion", "")).strip(),
                }
            )
        return problems

    def _normalize_review(self, payload) -> dict:
        review = self._unwrap_review_mapping(payload)
        if review is None:
            raise ValueError("未能在辅助 LLM 输出中找到有效的评分结构。")

        dimensions = review.get("dimensions", {}) if isinstance(review, dict) else {}
        reusability = self._normalize_score((dimensions or {}).get("reusability", 0))
        stability = self._normalize_score((dimensions or {}).get("stability", 0))
        abstraction = self._normalize_score((dimensions or {}).get("abstraction", 0))
        overall_score = self._normalize_score(review.get("overall_score", 0))
        computed_score = round((reusability + stability + abstraction) / 3, 2)
        if overall_score == 0 and computed_score > 0:
            overall_score = computed_score

        threshold = self._get_threshold()
        expected_fit = bool(review.get("expected_fit", False))
        passed = overall_score >= threshold
        if expected_fit != passed:
            expected_fit = passed

        strengths = review.get("strengths", [])
        if not isinstance(strengths, list):
            strengths = []

        return {
            "expected_fit": expected_fit,
            "passed": passed,
            "overall_score": overall_score,
            "threshold": threshold,
            "dimensions": {
                "reusability": reusability,
                "stability": stability,
                "abstraction": abstraction,
            },
            "summary": self._to_text(review.get("summary", "")).strip(),
            "strengths": [self._to_text(item).strip() for item in strengths if self._to_text(item).strip()],
            "problems": self._normalize_problems(review.get("problems", [])),
            "raw_review": review,
        }

    def review_skill(
        self,
        skill_name: str = "",
        skill_markdown: str = "",
        runner_content: str = "",
        metadata_content: str = "",
        validation_log: str = "",
        expected_goal: str = "",
    ) -> dict:
        """
        审查某个 Skill 是否符合预期。

        用法：
        1. 传 skill_name，从 SKILLS 仓库读取 skill 审查。
        2. 直接传 skill_markdown / runner_content / metadata_content 审查草稿。
        """
        loaded_skill = {}
        if skill_name and not skill_markdown:
            loaded_skill = self._load_repository_skill(skill_name)
            skill_markdown = loaded_skill.get("skill_content", "")
            runner_content = runner_content or loaded_skill.get("runner_content", "")
            metadata_content = metadata_content or loaded_skill.get("metadata_content", "")

        review_target_name = skill_name or loaded_skill.get("name") or "unnamed_skill"
        prompt = self._build_review_prompt(
            skill_name=review_target_name,
            skill_markdown=self._to_text(skill_markdown).strip(),
            runner_content=self._to_text(runner_content).strip(),
            metadata_content=self._to_text(metadata_content).strip(),
            validation_log=self._to_text(validation_log).strip(),
            expected_goal=self._to_text(expected_goal).strip(),
        )
        llm_cfg = self._get_helper_llm_config()
        if not llm_cfg.get("key") or not llm_cfg.get("model"):
            raise ValueError("缺少辅助 LLM 配置，无法执行 skill 审查。")

        payload = call_llm_structured(
            prompt,
            model=llm_cfg["model"],
            apikey=llm_cfg["key"],
            preferred_types=["json", "yaml", "toml", "xml"],
        )
        result = self._normalize_review(payload)
        result["skill_name"] = review_target_name
        result["skill_path"] = loaded_skill.get("skill_path", "")
        result["metadata_path"] = loaded_skill.get("metadata_path", "")
        result["runner_path"] = loaded_skill.get("runner_path", "")
        return result

    def is_skill_expected(
        self,
        skill_name: str = "",
        skill_markdown: str = "",
        runner_content: str = "",
        metadata_content: str = "",
        validation_log: str = "",
        expected_goal: str = "",
    ) -> bool:
        """仅返回该 Skill 是否符合预期。"""
        review = self.review_skill(
            skill_name=skill_name,
            skill_markdown=skill_markdown,
            runner_content=runner_content,
            metadata_content=metadata_content,
            validation_log=validation_log,
            expected_goal=expected_goal,
        )
        return bool(review.get("passed", False))
