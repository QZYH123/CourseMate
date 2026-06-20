from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from student_course_agent.mcp_server import handle_request


class McpServerTests(unittest.TestCase):
    def test_tools_list_exposes_course_tools(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertIn("search_course_materials", names)
        self.assertIn("query_deadlines", names)

    def test_tools_call_invokes_deadline_tool(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "query_deadlines",
                    "arguments": {"course": "AI Agents", "date_range": "all"},
                },
            }
        )

        text = response["result"]["content"][0]["text"]
        self.assertIn("Experiment 2 BYOA", text)
        self.assertFalse(response["result"]["isError"])

    def test_tools_call_returns_structured_error_for_unknown_tool(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "missing_tool", "arguments": {}},
            }
        )

        self.assertEqual(response["id"], 3)
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("Unknown tool", payload["error"])

    def test_tools_call_returns_structured_error_for_bad_params(self) -> None:
        response = handle_request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": []})

        self.assertEqual(response["id"], 4)
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("Invalid params", payload["error"])

    def test_tools_call_returns_structured_error_for_bad_arguments(self) -> None:
        response = handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "query_deadlines", "arguments": ""},
            }
        )

        self.assertEqual(response["id"], 5)
        self.assertTrue(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("arguments must be an object", payload["error"])


if __name__ == "__main__":
    unittest.main()
