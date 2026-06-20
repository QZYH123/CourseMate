"""Agent orchestration for the student course task assistant."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .tools import PROJECT_ROOT, TOOLS, call_tool

SYSTEM_PROMPT = """你是一个单一用途的学生课程任务助手。
你的任务是帮助学生基于课程材料、截止日期和项目文件判断下一步该做什么。
回答课程相关问题前必须先调用工具，不能只依赖模型常识。
回答必须引用工具返回的本地来源。
如果本地上下文缺失，必须明确说明缺少什么，不能编造。
除非用户明确要求英文，否则使用简体中文回答。
回答要具体、简短、可执行。"""

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class AgentResponse:
    answer: str
    tool_calls: list[ToolCallRecord]


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    base_url: Optional[str]
    model_name: str


class CourseTaskAgent:
    def __init__(self, use_llm: Optional[bool] = None) -> None:
        if use_llm is None:
            use_llm = _truthy_env(os.getenv("STUDENT_AGENT_LLM"))
        self.use_llm = use_llm

    def answer(self, question: str) -> AgentResponse:
        if self.use_llm:
            try:
                return self._answer_with_openai(question)
            except Exception as exc:
                fallback = self._answer_deterministic(question)
                fallback.answer = (
                    "LLM 模式失败，已改用确定性的工具优先模式回答。\n"
                    f"失败原因: {_safe_error_message(exc)}\n\n"
                    + fallback.answer
                )
                return fallback
        return self._answer_deterministic(question)

    def _answer_deterministic(self, question: str) -> AgentResponse:
        lowered = question.lower()
        calls: list[ToolCallRecord] = []

        def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = call_tool(name, arguments)
            calls.append(ToolCallRecord(name=name, arguments=arguments, result=result))
            return result

        asks_deadline = any(
            word in lowered
            for word in ["due", "deadline", "week", "today", "截止", "ddl", "这周", "本周", "要交", "到期"]
        )
        asks_material = any(
            word in lowered
            for word in ["require", "experiment", "byoa", "assignment", "rubric", "report", "要求", "作业"]
        )
        asks_plan = any(word in lowered for word in ["hour", "minute", "tonight", "plan", "first", "study", "小时", "分钟", "今晚"])
        asks_check = any(word in lowered for word in ["check", "ready", "submit", "deliverable", "screenshot", "检查", "提交"])

        if asks_deadline or asks_plan:
            date_range = "this_week" if "week" in lowered or "这周" in lowered else "upcoming"
            invoke("query_deadlines", {"course": "AI Agents", "date_range": date_range})

        if asks_material or asks_plan:
            invoke("search_course_materials", {"query": question, "max_results": 5})

        if asks_plan:
            available = _extract_minutes(question) or 120
            invoke("plan_study_session", {"available_minutes": available, "task_goal": question})

        if asks_check:
            invoke("check_deliverables", {"project_path": ".", "assignment_name": "Experiment 2 BYOA"})

        if not calls:
            invoke("search_course_materials", {"query": question, "max_results": 3})
            invoke("query_deadlines", {"course": "AI Agents", "date_range": "upcoming"})

        return AgentResponse(answer=self._compose_answer(question, calls), tool_calls=calls)

    def _answer_with_openai(self, question: str) -> AgentResponse:
        config = _load_llm_config()

        from openai import OpenAI

        client_kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        client = OpenAI(**client_kwargs)

        if _should_use_local_tools_first(config.base_url, config.model_name):
            return self._answer_with_local_tools_and_llm(client, config.model_name, question)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        tool_schemas = [tool.openai_schema() for tool in TOOLS.values()]
        calls: list[ToolCallRecord] = []

        first = client.chat.completions.create(
            model=config.model_name,
            messages=messages,
            tools=tool_schemas,
            tool_choice="auto",
        )
        message = first.choices[0].message
        messages.append(message.model_dump())
        raw_content = message.content or ""

        if not (message.tool_calls or []) and _looks_like_raw_tool_markup(raw_content):
            return self._answer_deterministic(question)

        for tool_call in message.tool_calls or []:
            name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments or "{}")
            result = call_tool(name, arguments)
            calls.append(ToolCallRecord(name=name, arguments=arguments, result=result))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

        if not calls:
            local = self._answer_deterministic(question)
            return local

        final = client.chat.completions.create(
            model=config.model_name,
            messages=messages,
        )
        content = final.choices[0].message.content or self._compose_answer(question, calls)
        if _looks_like_raw_tool_markup(content):
            content = self._compose_answer(question, calls)
        return AgentResponse(answer=content, tool_calls=calls)

    def _answer_with_local_tools_and_llm(self, client: Any, model_name: str, question: str) -> AgentResponse:
        deterministic = self._answer_deterministic(question)
        tool_summary = [
            {
                "name": call.name,
                "arguments": call.arguments,
                "result": call.result,
            }
            for call in deterministic.tool_calls
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是一个学生课程任务助手。"
                    "下面会给你已经执行完毕的工具结果。"
                    "同时会给你一份本地确定性模式已经基于工具结果整理好的答案。"
                    "你必须严格基于这些结果生成简体中文最终回答。"
                    "如果本地确定性答案已经包含具体条目，你必须保留这些具体信息，可以润色和压缩，但不能改写成“工具结果不完整”。"
                    "不要编造新的工具调用，不要输出任何工具标记，不要输出 XML/DSML。"
                    "如果工具结果已经包含要求、截止日期或步骤，你必须直接总结出来，不要让用户自己打开文件查阅。"
                    "优先输出具体条目，而不是空泛描述。"
                    "不要说“搜索结果只返回标题”或“请打开完整文档查看”，除非工具结果确实为空。"
                    "回答要自然、清晰、可执行，并保留来源。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"用户问题：{question}\n\n"
                    f"本地确定性答案：\n{deterministic.answer}\n\n"
                    f"工具结果：\n{json.dumps(tool_summary, ensure_ascii=False, indent=2)}"
                ),
            },
        ]
        final = client.chat.completions.create(
            model=model_name,
            messages=messages,
        )
        content = final.choices[0].message.content or deterministic.answer
        if _looks_like_raw_tool_markup(content) or _looks_like_incomplete_tool_summary(content):
            content = deterministic.answer
        return AgentResponse(answer=content, tool_calls=deterministic.tool_calls)

    def _compose_answer(self, question: str, calls: list[ToolCallRecord]) -> str:
        tool_issues = _collect_tool_issues(calls)
        has_deliverable_check = any(call.name == "check_deliverables" for call in calls)
        structured_material_answer = None if has_deliverable_check else _structured_material_answer(question, calls)
        if structured_material_answer:
            return _append_tool_issues(structured_material_answer, tool_issues)

        lines: list[str] = [f"问题: {question}", "", "基于工具的回答:"]
        sources: set[str] = set()

        for call in calls:
            if call.name == "query_deadlines":
                deadlines = call.result.get("deadlines", [])
                sources.add(call.result.get("source", "data/deadlines.csv"))
                if deadlines:
                    lines.append("截止日期:")
                    for item in deadlines[:5]:
                        lines.append(f"- {item['assignment']} 截止于 {item['due_at']}: {item['notes']}")
                else:
                    lines.append("- 没有找到匹配的截止日期。")

            elif call.name == "search_course_materials":
                hits = call.result.get("hits", [])
                for source in call.result.get("sources", []):
                    sources.add(source)
                if hits:
                    lines.append("相关课程要求:")
                    for hit in hits[:3]:
                        lines.append(f"- {hit['excerpt']} ({hit['source']}, {hit['location']})")

            elif call.name == "plan_study_session":
                for source in call.result.get("sources", []):
                    sources.add(source)
                lines.append("推荐学习安排:")
                for block in call.result.get("blocks", []):
                    lines.append(f"- {block['minutes']} 分钟: {block['task']} 原因: {block['reason']}")

            elif call.name == "check_deliverables":
                sources.add(call.result.get("project_path", "."))
                lines.append("提交准备情况:")
                lines.append(f"- 是否准备好: {call.result.get('ready')}")
                deliverable_issues = call.result.get("issues", [])
                if deliverable_issues:
                    for issue in deliverable_issues:
                        lines.append(f"- {issue['severity'].upper()}: {issue['item']} - {issue['message']}")
                else:
                    lines.append("- 未发现阻塞提交的交付物问题。")

        if sources:
            lines.extend(["", "来源:"])
            lines.extend(f"- {source}" for source in sorted(sources))

        if tool_issues:
            lines.extend(["", "工具问题:"])
            lines.extend(_format_tool_issues(tool_issues))

        lines.extend(["", "工具调用:"])
        lines.extend(f"- {call.name}({json.dumps(call.arguments, ensure_ascii=False)})" for call in calls)
        return "\n".join(lines)


def _extract_minutes(text: str) -> Optional[int]:
    hour_match = re.search(r"(\d+)\s*(hour|hours|小时)", text, flags=re.IGNORECASE)
    if hour_match:
        return int(hour_match.group(1)) * 60
    minute_match = re.search(r"(\d+)\s*(minute|minutes|min|分钟)", text, flags=re.IGNORECASE)
    if minute_match:
        return int(minute_match.group(1))
    return None


def _looks_like_raw_tool_markup(content: str) -> bool:
    markers = [
        "<｜｜DSML｜｜tool_calls>",
        "<｜｜DSML｜｜invoke",
        "</｜｜DSML｜｜tool_calls>",
    ]
    return any(marker in content for marker in markers)


def _looks_like_incomplete_tool_summary(content: str) -> bool:
    normalized = re.sub(r"\s+", "", content.lower())
    markers = [
        "工具返回的内容仅限标题",
        "未提取到具体的要求",
        "无法为你总结",
        "请直接打开",
        "自行查阅",
        "搜索结果未展示",
        "没有获取到更详细的要求",
    ]
    return any(marker in normalized for marker in markers)


def _load_llm_config(env: Optional[Mapping[str, str]] = None) -> LLMConfig:
    values = os.environ if env is None else env
    openai_key = _env_value(values, "OPENAI_API_KEY")
    deepseek_key = _env_value(values, "DEEPSEEK_API_KEY")
    api_key = openai_key or deepseek_key
    if not api_key:
        raise ValueError("未设置 OPENAI_API_KEY 或 DEEPSEEK_API_KEY。")

    base_url = _env_value(values, "OPENAI_BASE_URL")
    using_deepseek_key = bool(deepseek_key and not openai_key)
    if not base_url and using_deepseek_key:
        base_url = DEEPSEEK_BASE_URL

    model_name = _env_value(values, "OPENAI_MODEL")
    if not model_name:
        model_name = (
            DEFAULT_DEEPSEEK_MODEL
            if using_deepseek_key or _should_use_local_tools_first(base_url, "")
            else DEFAULT_OPENAI_MODEL
        )

    return LLMConfig(api_key=api_key, base_url=base_url, model_name=model_name)


def _env_value(env: Mapping[str, str], name: str) -> Optional[str]:
    value = env.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _truthy_env(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_error_message(exc: Exception) -> str:
    message = str(exc)
    for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "***")
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _should_use_local_tools_first(base_url: Optional[str], model_name: str) -> bool:
    normalized_base = (base_url or "").lower()
    normalized_model = model_name.lower()
    return "deepseek" in normalized_base or normalized_model.startswith("deepseek-")


def _collect_tool_issues(calls: list[ToolCallRecord]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for call in calls:
        if call.name == "check_deliverables":
            continue
        issues.extend(call.result.get("issues", []))
    return issues


def _append_tool_issues(answer: str, issues: list[dict[str, Any]]) -> str:
    if not issues:
        return answer
    return "\n".join([answer, "", "工具问题:", *_format_tool_issues(issues)])


def _format_tool_issues(issues: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for issue in issues:
        source = issue.get("source", "unknown")
        lines.append(
            f"- {issue.get('severity', 'warning').upper()}: "
            f"{issue.get('item', 'Context')} - {issue.get('message', '')} ({source})"
        )
    return lines


def _structured_material_answer(question: str, calls: list[ToolCallRecord]) -> Optional[str]:
    lowered = question.lower()
    asks_requirement = any(word in lowered for word in ["要求", "require", "experiment", "byoa", "作业"])
    if not asks_requirement:
        return None

    material_call = next((call for call in calls if call.name == "search_course_materials"), None)
    if not material_call:
        return None

    hits = material_call.result.get("hits", [])
    if not hits:
        return None

    source_names = {hit.get("source", "") for hit in hits}
    if "data/materials/experiment-2-byoa.md" not in source_names:
        return None

    sections = _collect_sections_by_heading(hits)
    sections.update(_experiment_sections_from_local_file())
    lines = ["问题: " + question, "", "Experiment 2 的核心要求如下:"]

    goal = sections.get("## 实验目标")
    if goal:
        lines.append(f"- 实验目标：{goal}")

    tool_use = sections.get("### Tool Use / Skills")
    context = sections.get("### Context Integration")
    vibe = sections.get("### Vibe Coding Constraint")
    if tool_use or context or vibe:
        lines.append("- 技术要求：")
        if tool_use:
            lines.append(f"- Tool Use / Skills：{tool_use}")
        if context:
            lines.append(f"- Context Integration：{context}")
        if vibe:
            lines.append(f"- Vibe Coding Constraint：{vibe}")

    deliverables = sections.get("## 交付物")
    if deliverables:
        lines.append(f"- 交付物：{deliverables}")

    evaluation = []
    for heading in (
        "### System Mechanics and Tooling - 40 分",
        "### Agent Execution - 40 分",
        "### Personal Reflection - 20 分",
    ):
        if heading in sections:
            evaluation.append(f"{heading.replace('### ', '')}：{sections[heading]}")
    if evaluation:
        lines.append("- 评分标准：")
        for index, item in enumerate(evaluation, start=1):
            lines.append(f"- {item}")

    lines.extend(["", "来源:", "- data/materials/experiment-2-byoa.md", "", "工具调用:"])
    lines.extend(f"- {call.name}({json.dumps(call.arguments, ensure_ascii=False)})" for call in calls)
    return "\n".join(lines)


def _collect_sections_by_heading(hits: list[dict[str, Any]]) -> dict[str, str]:
    known_headings = (
        "### System Mechanics and Tooling - 40 分",
        "### Personal Reflection - 20 分",
        "### Vibe Coding Constraint",
        "### Context Integration",
        "### Agent Execution - 40 分",
        "### Tool Use / Skills",
        "## 评分标准",
        "## 技术要求",
        "## 交付物",
        "## 实验目标",
    )
    sections: dict[str, str] = {}
    for hit in hits:
        excerpt = hit.get("excerpt", "")
        matched_heading = next((heading for heading in known_headings if excerpt.startswith(heading)), None)
        if matched_heading:
            sections[matched_heading] = excerpt[len(matched_heading) :].strip()
            continue
        match = re.match(r"^(#+\s+[^\s].*?)(?:\s{2,}|\s)(.*)$", excerpt)
        if not match:
            continue
        heading = match.group(1).strip()
        body = match.group(2).strip()
        sections[heading] = body
    return sections


def _experiment_sections_from_local_file() -> dict[str, str]:
    path = PROJECT_ROOT / "data" / "materials" / "experiment-2-byoa.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return _collect_sections_from_markdown(text)


def _collect_sections_from_markdown(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_heading: Optional[str] = None
    current_body: list[str] = []

    def flush() -> None:
        if current_heading is None:
            return
        body = re.sub(r"\s+", " ", "\n".join(current_body)).strip()
        sections[current_heading] = body

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            current_heading = stripped
            current_body = []
            continue
        if current_heading is not None:
            current_body.append(stripped)

    flush()
    return sections
