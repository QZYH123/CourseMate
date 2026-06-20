# Experiment 2: Bring Your Own Agent (BYOA)

## 实验目标

使用 Vibe Coding，通过 Cursor、Codex 等工具快速搭建并部署一个自定义的、单一用途的 AI Agent。

Agent 的功能可以自由指定，例如总结本地 PDF 阅读材料、检查日历并起草邮件等。

Agent 必须依赖外部工具和上下文，不能只依赖 LLM 的基础知识。

## 技术要求

### Tool Use / Skills

Agent 必须配备至少两个不同的功能性技能，例如抓取网页、查询数据库、解析 CSV、调用外部天气 API。

### Context Integration

Agent 必须使用标准化协议，例如 MCP，或标准 LLM function calling。目标是把 Agent 的“大脑”与本地环境或 API 连接起来。

### Vibe Coding Constraint

必须使用 AI 编写样板代码，包括 MCP server 设置、函数参数的 Pydantic 模型、API 请求逻辑等。这样开发者可以专注于 system prompt 和 orchestration loop。

## 交付物

截止日期：2026-06-20 23:59:59。

1. 代码仓库：包含 Agent 逻辑和工具定义。
2. 简短报告：不超过 5 页。
3. 报告必须包含 3 到 4 张执行截图。
4. 报告必须包含一段关于开发中使用 AI 的简短反思。

## 评分标准

### System Mechanics and Tooling - 40 分

评估代码仓库，需包含所有相关提示词。

### Agent Execution - 40 分

评估报告中的执行截图。

### Personal Reflection - 20 分

评估报告正文。必须包含一段简洁、诚实的反思，指出 AI 面临的具体技术障碍，例如协议语法不稳定、参数幻觉等。同时需要说明如何通过工程手段解决该问题。
