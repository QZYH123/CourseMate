from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from student_course_agent import agent as agent_module
from student_course_agent.agent import (
    DEEPSEEK_BASE_URL,
    CourseTaskAgent,
    _load_llm_config,
    _looks_like_incomplete_tool_summary,
    _should_use_local_tools_first,
)
from student_course_agent import tools
from student_course_agent.cli import main as cli_main
from student_course_agent.tools import check_deliverables, plan_study_session, query_deadlines, search_course_materials


class ToolTests(unittest.TestCase):
    def test_search_course_materials_finds_byoa_requirements(self) -> None:
        result = search_course_materials({"query": "BYOA 工具 交付物 要求", "max_results": 3})

        self.assertGreaterEqual(result["result_count"], 1)
        self.assertIn("data/materials/experiment-2-byoa.md", result["sources"])

    def test_query_deadlines_returns_upcoming_assignment(self) -> None:
        result = query_deadlines({"course": "AI Agents", "date_range": "all"})

        assignments = [item["assignment"] for item in result["deadlines"]]
        self.assertIn("Experiment 2 BYOA", assignments)

    def test_plan_study_session_uses_deadlines(self) -> None:
        result = plan_study_session({"available_minutes": 120, "task_goal": "finish BYOA"})

        self.assertEqual(result["available_minutes"], 120)
        self.assertGreaterEqual(len(result["blocks"]), 1)

    def test_check_deliverables_reports_missing_screenshots(self) -> None:
        result = check_deliverables({"project_path": ".", "assignment_name": "Experiment 2 BYOA"})

        issue_items = [issue["item"] for issue in result["issues"]]
        self.assertIn("Screenshots", issue_items)
        self.assertNotIn("Tool definitions", issue_items)

    def test_query_deadlines_reports_missing_csv_without_crashing(self) -> None:
        original = tools.DEADLINES_FILE
        try:
            tools.DEADLINES_FILE = ROOT / "data" / "missing-deadlines.csv"
            result = query_deadlines({"course": "AI Agents", "date_range": "all"})
        finally:
            tools.DEADLINES_FILE = original

        self.assertEqual(result["deadlines"], [])
        self.assertEqual(result["result_count"], 0)
        self.assertTrue(result["issues"])
        self.assertEqual(result["issues"][0]["item"], "Deadlines file")

    def test_query_deadlines_reports_bad_date_range_without_crashing(self) -> None:
        result = query_deadlines({"course": "AI Agents", "date_range": "2026-99-99..bad"})

        self.assertIn("issues", result)
        issue_items = [issue["item"] for issue in result["issues"]]
        self.assertIn("Date range", issue_items)

    def test_plan_study_session_reports_bad_preferences_without_crashing(self) -> None:
        original = tools.PREFERENCES_FILE
        with tempfile.TemporaryDirectory() as directory:
            bad_preferences = Path(directory) / "student_preferences.json"
            bad_preferences.write_text("{bad json", encoding="utf-8")
            try:
                tools.PREFERENCES_FILE = bad_preferences
                result = plan_study_session({"available_minutes": 30, "task_goal": "finish BYOA"})
            finally:
                tools.PREFERENCES_FILE = original

        self.assertGreaterEqual(len(result["blocks"]), 1)
        issue_items = [issue["item"] for issue in result["issues"]]
        self.assertIn("Preferences file", issue_items)


class AgentTests(unittest.TestCase):
    def test_agent_calls_material_tool_for_assignment_question(self) -> None:
        agent = CourseTaskAgent(use_llm=False)
        response = agent.answer("Experiment 2 要求是什么？")

        tool_names = [call.name for call in response.tool_calls]
        self.assertIn("search_course_materials", tool_names)
        self.assertIn("来源:", response.answer)
        self.assertIn("Tool Use / Skills", response.answer)
        self.assertIn("Context Integration", response.answer)
        self.assertIn("交付物", response.answer)
        self.assertIn("System Mechanics and Tooling", response.answer)

    def test_agent_calls_planning_tools_for_time_question(self) -> None:
        agent = CourseTaskAgent(use_llm=False)
        response = agent.answer("我今晚有 120 分钟，应该先做什么？")

        tool_names = [call.name for call in response.tool_calls]
        self.assertIn("query_deadlines", tool_names)
        self.assertIn("plan_study_session", tool_names)

    def test_agent_calls_deadline_tool_for_chinese_week_question(self) -> None:
        agent = CourseTaskAgent(use_llm=False)
        response = agent.answer("这周有什么要交？")

        tool_names = [call.name for call in response.tool_calls]
        self.assertIn("query_deadlines", tool_names)

    def test_agent_prioritizes_deliverable_check_for_submission_question(self) -> None:
        agent = CourseTaskAgent(use_llm=False)
        response = agent.answer("检查我的 BYOA 项目是否可以提交。")

        tool_names = [call.name for call in response.tool_calls]
        self.assertIn("search_course_materials", tool_names)
        self.assertIn("check_deliverables", tool_names)
        self.assertIn("提交准备情况:", response.answer)
        self.assertIn("Screenshots", response.answer)
        self.assertNotIn("Experiment 2 的核心要求如下:", response.answer)

    def test_agent_reports_tool_issues(self) -> None:
        original = tools.DEADLINES_FILE
        try:
            tools.DEADLINES_FILE = ROOT / "data" / "missing-deadlines.csv"
            agent = CourseTaskAgent(use_llm=False)
            response = agent.answer("这周有什么要交？")
        finally:
            tools.DEADLINES_FILE = original

        self.assertIn("工具问题:", response.answer)
        self.assertIn("Deadlines file", response.answer)

    def test_structured_material_answer_reports_tool_issues(self) -> None:
        original_call_tool = agent_module.call_tool

        def fake_call_tool(name, arguments):
            if name == "search_course_materials":
                return {
                    "query": arguments["query"],
                    "result_count": 1,
                    "hits": [
                        {
                            "source": "data/materials/experiment-2-byoa.md",
                            "location": "passage 1",
                            "score": 1,
                            "excerpt": "## 实验目标\nBuild a single-purpose BYOA agent.",
                        }
                    ],
                    "sources": ["data/materials/experiment-2-byoa.md"],
                    "issues": [
                        {
                            "severity": "warning",
                            "item": "Material read",
                            "message": "课程材料部分文件无法读取。",
                            "source": "data/materials/bad.pdf",
                        }
                    ],
                }
            return original_call_tool(name, arguments)

        try:
            agent_module.call_tool = fake_call_tool
            response = CourseTaskAgent(use_llm=False).answer("Experiment 2 要求是什么？")
        finally:
            agent_module.call_tool = original_call_tool

        self.assertIn("工具问题:", response.answer)
        self.assertIn("Material read", response.answer)

    def test_local_tools_llm_falls_back_from_incomplete_summary(self) -> None:
        class FakeMessage:
            content = "工具返回的内容仅限标题信息，未提取到具体的要求条目。"

        class FakeChoice:
            message = FakeMessage()

        class FakeCompletions:
            def create(self, **_kwargs):
                return type("FakeResponse", (), {"choices": [FakeChoice()]})()

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        response = CourseTaskAgent(use_llm=False)._answer_with_local_tools_and_llm(
            FakeClient(),
            "deepseek-chat",
            "Experiment 2 要求是什么？",
        )

        self.assertIn("Tool Use / Skills", response.answer)
        self.assertIn("Context Integration", response.answer)
        self.assertNotIn("未提取到具体的要求", response.answer)


class CliTests(unittest.TestCase):
    def test_cli_plain_output_includes_sources_and_tool_calls(self) -> None:
        output = _run_cli(["Experiment 2 要求是什么？"])

        self.assertIn("来源:", output)
        self.assertIn("工具调用:", output)
        self.assertIn("search_course_materials", output)

    def test_cli_json_output_contains_tool_calls(self) -> None:
        output = _run_cli(["--json", "这周有什么要交？"])
        payload = json.loads(output)

        self.assertIn("answer", payload)
        tool_names = [call["name"] for call in payload["tool_calls"]]
        self.assertIn("query_deadlines", tool_names)

    def test_cli_llm_without_key_falls_back_to_local_tools(self) -> None:
        saved_env = {name: os.environ.get(name) for name in ("OPENAI_API_KEY", "DEEPSEEK_API_KEY")}
        try:
            os.environ.pop("OPENAI_API_KEY", None)
            os.environ.pop("DEEPSEEK_API_KEY", None)
            output = _run_cli(["--llm", "Experiment 2 要求是什么？"])
        finally:
            for name, value in saved_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertIn("LLM 模式失败", output)
        self.assertIn("工具调用:", output)
        self.assertIn("search_course_materials", output)


class LLMConfigTests(unittest.TestCase):
    def test_llm_config_uses_deepseek_key_defaults(self) -> None:
        config = _load_llm_config({"DEEPSEEK_API_KEY": " ds-test-key "})

        self.assertEqual(config.api_key, "ds-test-key")
        self.assertEqual(config.base_url, DEEPSEEK_BASE_URL)
        self.assertEqual(config.model_name, "deepseek-chat")

    def test_llm_config_respects_explicit_openai_compatible_values(self) -> None:
        config = _load_llm_config(
            {
                "OPENAI_API_KEY": "openai-compatible-key",
                "OPENAI_BASE_URL": "https://example.test/v1",
                "OPENAI_MODEL": "custom-model",
            }
        )

        self.assertEqual(config.api_key, "openai-compatible-key")
        self.assertEqual(config.base_url, "https://example.test/v1")
        self.assertEqual(config.model_name, "custom-model")

    def test_llm_config_requires_a_key(self) -> None:
        with self.assertRaises(ValueError):
            _load_llm_config({"OPENAI_API_KEY": "", "DEEPSEEK_API_KEY": " "})

    def test_deepseek_models_use_local_tools_first(self) -> None:
        self.assertTrue(_should_use_local_tools_first(DEEPSEEK_BASE_URL, "deepseek-chat"))
        self.assertTrue(_should_use_local_tools_first(None, "deepseek-reasoner"))
        self.assertFalse(_should_use_local_tools_first(None, "gpt-4.1-mini"))

    def test_detects_incomplete_tool_summary(self) -> None:
        self.assertTrue(_looks_like_incomplete_tool_summary("工具返回的内容仅限标题信息，未提取到具体的要求。"))
        self.assertFalse(_looks_like_incomplete_tool_summary("Tool Use / Skills：Agent 必须配备至少两个工具。"))


def _run_cli(argv: list[str]) -> str:
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        cli_main(argv)
    return stdout.getvalue()


if __name__ == "__main__":
    unittest.main()
