"""Command line interface for the student course task assistant."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from .agent import CourseTaskAgent


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="学生课程任务助手")
    parser.add_argument("question", nargs="*", help="要询问 Agent 的问题。")
    parser.add_argument("--interactive", "-i", action="store_true", help="启动交互模式。")
    parser.add_argument("--json", action="store_true", help="输出结构化 JSON。")
    parser.add_argument("--llm", action="store_true", help="使用 OpenAI-compatible LLM 模式，支持 DeepSeek。")
    args = parser.parse_args(argv)

    agent = CourseTaskAgent(use_llm=args.llm or None)

    if args.interactive:
        _interactive(agent, as_json=args.json)
        return

    question = " ".join(args.question).strip()
    if not question:
        parser.error("请提供一个问题，或使用 --interactive。")

    response = agent.answer(question)
    _print_response(response, as_json=args.json)


def _interactive(agent: CourseTaskAgent, as_json: bool = False) -> None:
    print("学生课程任务助手。输入 'exit' 退出。")
    while True:
        try:
            question = input("> ").strip()
        except EOFError:
            print()
            return
        if question.lower() in {"exit", "quit"}:
            return
        if not question:
            continue
        response = agent.answer(question)
        _print_response(response, as_json=as_json)


def _print_response(response, as_json: bool = False) -> None:
    if as_json:
        print(
            json.dumps(
                {
                    "answer": response.answer,
                    "tool_calls": [
                        {"name": call.name, "arguments": call.arguments, "result": call.result}
                        for call in response.tool_calls
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(response.answer)
    print()


if __name__ == "__main__":
    main(sys.argv[1:])
