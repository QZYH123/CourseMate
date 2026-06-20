"""A lightweight MCP-style stdio server exposing the local tools.

The server speaks JSON-RPC over stdin/stdout and supports the MCP methods
`initialize`, `tools/list`, and `tools/call`. It avoids a hard dependency on the
official SDK so the project remains easy to run in constrained demo setups.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from .tools import TOOLS, call_tool


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            request = json.loads(raw_line)
            response = handle_request(request)
        except Exception as exc:
            response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(exc)},
            }
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    method = request.get("method")
    request_id = request.get("id")

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "student-course-agent", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        )

    if method == "tools/list":
        return _result(
            request_id,
            {
                "tools": [
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "inputSchema": tool.input_schema(),
                    }
                    for tool in TOOLS.values()
                ]
            },
        )

    if method == "tools/call":
        params = request.get("params", {})
        if not isinstance(params, dict):
            return _tool_error(request_id, "Invalid params: tools/call params must be an object.")

        name = params.get("name")
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(name, str) or not name:
            return _tool_error(request_id, "Invalid params: tools/call requires a non-empty string name.")
        if not isinstance(arguments, dict):
            return _tool_error(request_id, "Invalid params: tools/call arguments must be an object.")

        try:
            output = call_tool(name, arguments)
        except Exception as exc:
            return _tool_error(request_id, f"{type(exc).__name__}: {exc}")
        return _tool_result(request_id, output)

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_result(request_id: Any, output: dict[str, Any]) -> dict[str, Any]:
    return _result(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(output, ensure_ascii=False, indent=2),
                }
            ],
            "isError": False,
        },
    )


def _tool_error(request_id: Any, message: str) -> dict[str, Any]:
    return _result(
        request_id,
        {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"error": message}, ensure_ascii=False, indent=2),
                }
            ],
            "isError": True,
        },
    )


if __name__ == "__main__":
    main()
