"""Schemas used by tools and the agent orchestration layer."""

from __future__ import annotations

from typing import Any, Optional


try:
    from pydantic import BaseModel, Field

    PYDANTIC_AVAILABLE = True
except Exception:  # pragma: no cover - used only when dependencies are absent
    PYDANTIC_AVAILABLE = False

    def Field(default: Any = None, **_: Any) -> Any:
        return default

    class BaseModel:  # type: ignore[no-redef]
        """Small fallback so local demos can run without installed packages."""

        def __init__(self, **data: Any) -> None:
            annotations = getattr(self, "__annotations__", {})
            for name in annotations:
                if name in data:
                    value = data[name]
                elif hasattr(self.__class__, name):
                    value = getattr(self.__class__, name)
                    if value is Ellipsis:
                        raise ValueError(f"Missing required field: {name}")
                    if isinstance(value, (list, dict, set)):
                        value = value.copy()
                else:
                    value = None
                setattr(self, name, value)
            for name, value in data.items():
                if name not in annotations:
                    setattr(self, name, value)

        @classmethod
        def model_validate(cls, data: dict[str, Any]) -> "BaseModel":
            return cls(**data)

        @classmethod
        def model_json_schema(cls) -> dict[str, Any]:
            properties: dict[str, Any] = {}
            required: list[str] = []
            for name, annotation in getattr(cls, "__annotations__", {}).items():
                default = getattr(cls, name, Ellipsis)
                if default is Ellipsis:
                    required.append(name)
                properties[name] = {"title": name, "type": _json_type(annotation)}
            return {"type": "object", "properties": properties, "required": required}

        def model_dump(self) -> dict[str, Any]:
            output: dict[str, Any] = {}
            for name in getattr(self, "__annotations__", {}):
                value = getattr(self, name)
                if hasattr(value, "model_dump"):
                    value = value.model_dump()
                elif isinstance(value, list):
                    value = [item.model_dump() if hasattr(item, "model_dump") else item for item in value]
                output[name] = value
            return output


def _json_type(annotation: Any) -> str:
    if annotation in (int, "int"):
        return "integer"
    if annotation in (float, "float"):
        return "number"
    if annotation in (bool, "bool"):
        return "boolean"
    if annotation in (list, "list"):
        return "array"
    return "string"


class SearchCourseMaterialsArgs(BaseModel):
    query: str = Field(..., description="课程材料检索关键词。")
    max_results: int = Field(5, description="最多返回的片段数量。")


class QueryDeadlinesArgs(BaseModel):
    course: Optional[str] = Field(None, description="可选课程名称过滤条件。")
    date_range: str = Field(
        "upcoming",
        description="可选 upcoming、today、this_week、overdue、all，或 YYYY-MM-DD..YYYY-MM-DD。",
    )


class PlanStudySessionArgs(BaseModel):
    available_minutes: int = Field(..., description="本次学习可用分钟数。")
    task_goal: str = Field("coursework", description="学生希望完成的任务目标。")


class CheckDeliverablesArgs(BaseModel):
    project_path: str = Field(".", description="需要检查的项目目录路径。")
    assignment_name: str = Field("Experiment 2 BYOA", description="作业名称。")


class MaterialHit(BaseModel):
    source: str
    location: str
    score: int
    excerpt: str


class DeadlineItem(BaseModel):
    course: str
    assignment: str
    due_at: str
    kind: str
    estimated_minutes: int
    status: str
    notes: str


class StudyBlock(BaseModel):
    minutes: int
    task: str
    reason: str
    source: str


class DeliverableIssue(BaseModel):
    severity: str
    item: str
    message: str
    source: str
