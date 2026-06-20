"""Local tools used by the Student Course Task Agent."""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from .models import (
    CheckDeliverablesArgs,
    DeadlineItem,
    DeliverableIssue,
    MaterialHit,
    PlanStudySessionArgs,
    QueryDeadlinesArgs,
    SearchCourseMaterialsArgs,
    StudyBlock,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
MATERIALS_DIR = DATA_DIR / "materials"
DEADLINES_FILE = DATA_DIR / "deadlines.csv"
PREFERENCES_FILE = DATA_DIR / "student_preferences.json"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    args_model: type
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def input_schema(self) -> dict[str, Any]:
        if hasattr(self.args_model, "model_json_schema"):
            return self.args_model.model_json_schema()
        return {"type": "object", "properties": {}}

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema(),
            },
        }


def search_course_materials(args: dict[str, Any]) -> dict[str, Any]:
    parsed = SearchCourseMaterialsArgs.model_validate(args)
    max_results = max(1, min(int(parsed.max_results), 10))
    query = parsed.query.strip()
    tokens = _tokens(query)
    hits: list[MaterialHit] = []
    issues: list[dict[str, str]] = []

    material_files, material_issues = _material_files()
    issues.extend(material_issues)
    for path in material_files:
        text = _read_material(path)
        if not text:
            issues.append(
                _issue(
                    "warning",
                    "Material read",
                    f"课程材料为空或无法读取: {_source(path)}。",
                    _source(path),
                )
            )
            continue
        for idx, passage in enumerate(_passages(text), start=1):
            score = _score_passage(tokens, passage)
            if score <= 0:
                continue
            hits.append(
                MaterialHit(
                    source=path.relative_to(PROJECT_ROOT).as_posix(),
                    location=f"passage {idx}",
                    score=score,
                    excerpt=_compact(passage, 520),
                )
            )

    hits.sort(key=lambda item: item.score, reverse=True)
    selected = hits[:max_results]
    return {
        "query": query,
        "result_count": len(selected),
        "hits": [item.model_dump() for item in selected],
        "sources": sorted({item.source for item in selected}),
        "issues": issues,
    }


def query_deadlines(args: dict[str, Any]) -> dict[str, Any]:
    parsed = QueryDeadlinesArgs.model_validate(args)
    today = _today()
    source = _source(DEADLINES_FILE)
    issues: list[dict[str, str]] = []
    try:
        start, end = _date_window(parsed.date_range, today)
    except ValueError as exc:
        start, end = today, None
        issues.append(_issue("warning", "Date range", str(exc), source))
    items: list[DeadlineItem] = []

    if not DEADLINES_FILE.exists():
        issues.append(_issue("error", "Deadlines file", "截止日期 CSV 文件不存在。", source))
    else:
        try:
            with DEADLINES_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                required = {"course", "assignment", "due_at", "kind", "estimated_minutes", "status", "notes"}
                missing_columns = sorted(required - set(reader.fieldnames or []))
                if missing_columns:
                    issues.append(
                        _issue(
                            "error",
                            "Deadlines columns",
                            f"截止日期 CSV 缺少列: {', '.join(missing_columns)}。",
                            source,
                        )
                    )
                else:
                    for line_number, row in enumerate(reader, start=2):
                        try:
                            if parsed.course and parsed.course.lower() not in row["course"].lower():
                                continue
                            due_at = _parse_datetime(row["due_at"])
                            if start and due_at.date() < start:
                                continue
                            if end and due_at.date() > end:
                                continue
                            items.append(
                                DeadlineItem(
                                    course=row["course"],
                                    assignment=row["assignment"],
                                    due_at=row["due_at"],
                                    kind=row["kind"],
                                    estimated_minutes=int(row["estimated_minutes"]),
                                    status=row["status"],
                                    notes=row["notes"],
                                )
                            )
                        except (KeyError, TypeError, ValueError) as exc:
                            issues.append(
                                _issue(
                                    "warning",
                                    "Deadlines row",
                                    f"跳过第 {line_number} 行: {exc}。",
                                    source,
                                )
                            )
        except OSError as exc:
            issues.append(_issue("error", "Deadlines file", f"无法读取截止日期 CSV: {exc}。", source))

    try:
        items.sort(key=lambda item: _parse_datetime(item.due_at))
    except ValueError as exc:
        issues.append(
            _issue(
                "warning",
                "Deadlines sort",
                f"截止日期排序失败，保留原始顺序: {exc}。",
                source,
            )
        )
    return {
        "date_range": parsed.date_range,
        "today": today.isoformat(),
        "result_count": len(items),
        "deadlines": [item.model_dump() for item in items],
        "source": source,
        "issues": issues,
    }


def plan_study_session(args: dict[str, Any]) -> dict[str, Any]:
    parsed = PlanStudySessionArgs.model_validate(args)
    available = max(15, int(parsed.available_minutes))
    preferences, preference_issues = _load_preferences()
    deadline_result = query_deadlines(
        {
            "course": preferences.get("default_course"),
            "date_range": "upcoming",
        }
    )
    deadlines = deadline_result["deadlines"]
    blocks: list[StudyBlock] = []
    remaining = available

    for item in deadlines:
        if remaining <= 0:
            break
        minutes = min(remaining, max(20, min(int(item["estimated_minutes"]), 60)))
        blocks.append(
            StudyBlock(
                minutes=minutes,
                task=f"{item['assignment']}: {item['notes']}",
                reason=f"截止时间是 {item['due_at']}，当前状态是 {item['status']}。",
                source=deadline_result["source"],
            )
        )
        remaining -= minutes
        if remaining >= 10:
            break_minutes = min(10, remaining)
            blocks.append(
                StudyBlock(
                    minutes=break_minutes,
                    task="短休息并检查进度。",
                    reason="避免连续推进导致遗漏，继续前先确认已经产出可见结果。",
                    source=_source(PREFERENCES_FILE),
                )
            )
            remaining -= break_minutes

    if remaining > 0:
        blocks.append(
            StudyBlock(
                minutes=remaining,
                task=f"把剩余时间用于: {parsed.task_goal}",
                reason="当前没有更多紧急 deadline 任务适合塞进剩余时间。",
                source=_source(PREFERENCES_FILE),
            )
        )

    return {
        "available_minutes": available,
        "task_goal": parsed.task_goal,
        "blocks": [block.model_dump() for block in blocks],
        "sources": [deadline_result["source"], _source(PREFERENCES_FILE)],
        "issues": preference_issues + deadline_result.get("issues", []),
    }


def check_deliverables(args: dict[str, Any]) -> dict[str, Any]:
    parsed = CheckDeliverablesArgs.model_validate(args)
    project_path = Path(parsed.project_path).expanduser()
    if not project_path.is_absolute():
        project_path = (PROJECT_ROOT / project_path).resolve()

    issues: list[DeliverableIssue] = []
    present: list[str] = []

    checks = {
        "README": [project_path / "README.md", project_path / "readme.md"],
        "Python project config": [project_path / "pyproject.toml", project_path / "requirements.txt"],
        "Agent source code": [project_path / "src", project_path / "agent.py"],
        "Report draft": [project_path / "report", project_path / "report.md", project_path / "draft_report.md"],
    }

    for label, candidates in checks.items():
        if any(path.exists() for path in candidates):
            present.append(label)
        else:
            issues.append(
                DeliverableIssue(
                    severity="high" if label in {"README", "Agent source code"} else "medium",
                    item=label,
                    message=f"{parsed.assignment_name} 缺少预期交付物: {label}。",
                    source=str(project_path),
                )
            )

    screenshot_count = _count_screenshots(project_path)
    if 3 <= screenshot_count <= 4:
        present.append("Screenshots")
    else:
        issues.append(
            DeliverableIssue(
                severity="high",
                item="Screenshots",
                message=(
                    f"{parsed.assignment_name} 需要 3 到 4 张执行截图；"
                    f"当前找到 {screenshot_count} 个图片文件。"
                ),
                source=str(project_path),
            )
        )

    code_text = _read_code_sample(project_path)
    tool_count = len(set(re.findall(r"def\s+([a-zA-Z_]+)\s*\(", code_text)))
    has_prompt = "system prompt" in code_text.lower() or "SYSTEM_PROMPT" in code_text
    has_tooling = any(word in code_text.lower() for word in ["tools/list", "tools/call", "function calling", "openai_schema"])

    if tool_count < 2:
        issues.append(
            DeliverableIssue(
                severity="high",
                item="Tool definitions",
                message="抽样代码中检测到的 Python 函数少于两个。",
                source=str(project_path),
            )
        )
    if not has_prompt:
        issues.append(
            DeliverableIssue(
                severity="medium",
                item="Prompt",
                message="抽样代码中未发现明显的 system prompt 标记。",
                source=str(project_path),
            )
        )
    if not has_tooling:
        issues.append(
            DeliverableIssue(
                severity="high",
                item="Tool integration",
                message="未发现明显的 MCP 或 function calling 集成标记。",
                source=str(project_path),
            )
        )

    return {
        "project_path": str(project_path),
        "assignment_name": parsed.assignment_name,
        "present": present,
        "issues": [issue.model_dump() for issue in issues],
        "ready": not any(issue.severity == "high" for issue in issues),
    }


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name not in TOOLS:
        raise KeyError(f"Unknown tool: {name}")
    return TOOLS[name].handler(arguments)


TOOLS: dict[str, ToolDefinition] = {
    "search_course_materials": ToolDefinition(
        name="search_course_materials",
        description="Search local course PDFs, Markdown, and text files for assignment or lecture context.",
        args_model=SearchCourseMaterialsArgs,
        handler=search_course_materials,
    ),
    "query_deadlines": ToolDefinition(
        name="query_deadlines",
        description="Read the local deadline CSV and return matching course deadlines.",
        args_model=QueryDeadlinesArgs,
        handler=query_deadlines,
    ),
    "plan_study_session": ToolDefinition(
        name="plan_study_session",
        description="Create short study blocks from available minutes and urgent local deadlines.",
        args_model=PlanStudySessionArgs,
        handler=plan_study_session,
    ),
    "check_deliverables": ToolDefinition(
        name="check_deliverables",
        description="Inspect a local project folder for BYOA deliverables such as code, README, report, and screenshots.",
        args_model=CheckDeliverablesArgs,
        handler=check_deliverables,
    ),
}


def _material_files() -> tuple[list[Path], list[dict[str, str]]]:
    if not MATERIALS_DIR.exists():
        return [], [_issue("error", "Materials directory", "课程材料目录不存在。", _source(MATERIALS_DIR))]
    try:
        return (
            sorted(
                path
                for path in MATERIALS_DIR.rglob("*")
                if path.suffix.lower() in {".md", ".txt", ".pdf"} and path.is_file()
            ),
            [],
        )
    except OSError as exc:
        return [], [_issue("error", "Materials directory", f"无法读取课程材料目录: {exc}。", _source(MATERIALS_DIR))]


def _read_material(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except Exception:
            return ""
        try:
            reader = PdfReader(str(path))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _passages(text: str) -> list[str]:
    markdown_sections = _markdown_sections(text)
    if markdown_sections:
        return markdown_sections

    raw = re.split(r"\n\s*\n+", text)
    passages = [item.strip() for item in raw if item.strip()]
    merged: list[str] = []
    index = 0
    while index < len(passages):
        current = passages[index]
        if index + 1 < len(passages) and current.lstrip().startswith("#"):
            merged.append(f"{current}\n{passages[index + 1]}")
            index += 2
            continue
        merged.append(current)
        index += 1
    passages = merged
    if len(passages) <= 1:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        passages = [" ".join(sentences[index : index + 4]).strip() for index in range(0, len(sentences), 4)]
    return [item for item in passages if item]


def _markdown_sections(text: str) -> list[str]:
    lines = text.splitlines()
    sections: list[str] = []
    current_heading: Optional[str] = None
    current_body: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_body and current_body[-1] != "":
                current_body.append("")
            continue
        if stripped.startswith("#"):
            if current_heading is not None:
                body = "\n".join(item for item in current_body).strip()
                if body:
                    sections.append(f"{current_heading}\n{body}")
                else:
                    sections.append(current_heading)
            current_heading = stripped
            current_body = []
            continue
        if current_heading is not None:
            current_body.append(stripped)

    if current_heading is not None:
        body = "\n".join(item for item in current_body).strip()
        if body:
            sections.append(f"{current_heading}\n{body}")
        else:
            sections.append(current_heading)

    return [section for section in sections if section.strip()]


def _tokens(query: str) -> list[str]:
    tokens: list[str] = []
    for token in re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", query):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) == 1:
                continue
            tokens.append(token)
            tokens.extend(token[index : index + 2] for index in range(0, len(token) - 1))
        elif len(token) > 1:
            tokens.append(token.lower())
    return tokens


def _score_passage(tokens: list[str], passage: str) -> int:
    lower = passage.lower()
    return sum(lower.count(token) for token in tokens)


def _compact(text: str, limit: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _parse_datetime(value: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported datetime: {value}")


def _today() -> date:
    override = os.getenv("STUDENT_AGENT_TODAY")
    if override:
        try:
            return datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError:
            return date.today()
    return date.today()


def _date_window(date_range: str, today: date) -> Tuple[Optional[date], Optional[date]]:
    normalized = date_range.strip().lower()
    if normalized == "all":
        return None, None
    if normalized == "today":
        return today, today
    if normalized == "this_week":
        return today, today + timedelta(days=7)
    if normalized == "overdue":
        return None, today - timedelta(days=1)
    if normalized == "upcoming":
        return today, None
    if ".." in normalized:
        start_text, end_text = normalized.split("..", 1)
        try:
            return date.fromisoformat(start_text), date.fromisoformat(end_text)
        except ValueError as exc:
            raise ValueError(f"Unsupported date range: {date_range}") from exc
    return today, None


def _load_preferences() -> tuple[dict[str, Any], list[dict[str, str]]]:
    source = _source(PREFERENCES_FILE)
    if not PREFERENCES_FILE.exists():
        return {}, [_issue("warning", "Preferences file", "学习偏好 JSON 文件不存在。", source)]
    try:
        loaded = json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [_issue("warning", "Preferences file", f"无法读取学习偏好 JSON: {exc}。", source)]
    if not isinstance(loaded, dict):
        return {}, [_issue("warning", "Preferences file", "学习偏好 JSON 顶层必须是对象。", source)]
    return loaded, []


def _read_code_sample(project_path: Path) -> str:
    if not project_path.exists():
        return ""
    chunks: list[str] = []
    sampled = 0
    for path in sorted(project_path.rglob("*.py")):
        if any(part.startswith(".") or part == "__pycache__" for part in path.parts):
            continue
        if sampled >= 40:
            break
        try:
            chunks.append(path.read_text(encoding="utf-8", errors="ignore")[:5000])
            sampled += 1
        except OSError:
            continue
    for name in ("README.md", "pyproject.toml"):
        path = project_path / name
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8", errors="ignore")[:5000])
    return "\n".join(chunks)


def _count_screenshots(project_path: Path) -> int:
    screenshot_dirs = [project_path / "screenshots", project_path / "report" / "screenshots"]
    suffixes = {".png", ".jpg", ".jpeg", ".webp"}
    count = 0
    for directory in screenshot_dirs:
        if not directory.exists():
            continue
        try:
            count += sum(1 for path in directory.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)
        except OSError:
            continue
    return count


def _source(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except (OSError, ValueError):
        return str(path)


def _issue(severity: str, item: str, message: str, source: str) -> dict[str, str]:
    return {"severity": severity, "item": item, "message": message, "source": source}
