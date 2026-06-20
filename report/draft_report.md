# 学生课程任务助手报告

## 1. 项目目标

`Student Course Task Agent` 是一个面向学生的课程任务助手。它不会只凭 LLM 常识回答，而是先读取本地课程要求、截止日期表和项目文件，再给出下一步学习或提交建议。

这个 Agent 的单一用途是：帮助学生判断“现在该做什么”，尤其适用于课程作业、项目提交和截止日期管理。

## 2. 系统机制与工具

项目包含 CLI Agent、轻量 MCP-style JSON-RPC stdio server、OpenAI-compatible LLM 配置和本地工具。主要工具包括：

- `search_course_materials`：检索本地课程材料。
- `query_deadlines`：读取并筛选 `data/deadlines.csv`。
- `plan_study_session`：根据可用时间和紧急任务生成学习安排。
- `check_deliverables`：检查 BYOA 项目目录是否具备预期交付物。

Agent 的 `SYSTEM_PROMPT` 明确要求：回答课程相关问题前必须调用工具，必须引用本地来源，如果上下文缺失则不能编造。

本地确定性模式不需要 API key，适合课堂演示和截图。可选 LLM 模式兼容 DeepSeek API：设置 `DEEPSEEK_API_KEY` 后默认使用 `https://api.deepseek.com` 和 `deepseek-chat`；DeepSeek 路径会先执行本地工具，再让模型基于工具结果总结，避免绕过本地上下文。

MCP-style stdio server 支持 `initialize`、`tools/list` 和 `tools/call`。工具调用成功时返回 `isError: false`；未知工具或坏参数会返回结构化 `isError: true`，便于客户端展示错误而不是静默失败。

## 3. 执行截图

建议放入以下 3 到 4 张截图：

1. 查询这周截止日期。
2. 查询 `Experiment 2` 的作业要求。
3. 生成 120 分钟学习计划。
4. 检查 BYOA 项目交付物是否齐全。

截图中应能看到 `工具调用` 和 `来源`，用于证明 Agent 使用了外部工具和本地上下文。

注意：截图本身是人工交付证据。代码只会通过 `check_deliverables` 检查 `screenshots/` 或 `report/screenshots/` 中是否存在 3 到 4 张图片，不会自动生成或伪造截图。

## 4. AI 使用反思

AI 对生成样板代码很有帮助，例如工具 schema、MCP `tools/list` / `tools/call`、CLI 参数解析和测试用例。但它也容易出现具体技术问题：如果 prompt 不够严格，Agent 会直接给出泛泛建议，而不是先读取本地材料；如果工具参数 schema 不清晰，模型可能会幻觉不存在的参数；如果直接依赖模型的工具调用格式，不同 OpenAI-compatible 提供商也可能出现兼容性差异。

解决方式是把工具输入收敛为明确的 Pydantic-compatible 模型，在 `SYSTEM_PROMPT` 中强制要求先调用工具，并在测试中检查关键问题是否触发正确工具。DeepSeek 路径采用“本地工具先执行，再交给模型总结”的编排方式，减少协议格式差异带来的风险。这样 Agent 从“普通聊天机器人”变成了一个真正依赖本地上下文工作的课程任务助手。
