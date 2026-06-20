# 学生课程任务助手

这是一个面向 `Experiment 2: Bring Your Own Agent (BYOA)` 的单一用途 Agent。它帮助学生基于本地课程材料、截止日期、学习偏好和项目交付物状态，回答“现在该做什么”“作业要求是什么”“是否可以提交”等课程任务问题。

项目的默认运行路径是本地工具优先模式：先调用本地工具读取上下文，再生成带来源和工具调用记录的回答。项目也支持 DeepSeek/OpenAI-compatible LLM 模式：先执行本地工具并生成本地确定性答案，再把“本地确定性答案 + 原始工具结果”交给模型润色总结；如果模型丢失关键信息或声称工具结果不完整，则回退到本地确定性答案。

## 实验要求对应

- 至少两个工具：项目提供 4 个本地工具。
- 上下文集成：支持本地文件上下文、OpenAI-compatible function calling schema、MCP-style JSON-RPC stdio server。
- 本地上下文：读取 `data/materials/experiment-2-byoa.md`、`data/deadlines.csv`、`data/student_preferences.json` 和项目文件。
- 运行证据：CLI 输出包含 `来源:` 和 `工具调用:`，适合报告截图。
- AI 使用反思：见 `report/draft_report.md`。

## 功能

可以询问：

- `Experiment 2 要求是什么？`
- `这周有什么要交？`
- `我今晚有 120 分钟，应该先做什么？`
- `检查我的 BYOA 项目是否可以提交。`

如果问题不在这些固定句式内，Agent 会根据关键词选择工具；如果无法判断，会默认检索课程材料和截止日期，避免只靠模型常识回答。

## 架构

```text
CLI / MCP client
  |
  v
CourseTaskAgent
  |
  +-- 本地确定性编排
  |     +-- search_course_materials
  |     +-- query_deadlines
  |     +-- plan_study_session
  |     +-- check_deliverables
  |
  +-- 可选 DeepSeek/OpenAI-compatible 总结层
        +-- 输入：本地确定性答案 + 原始工具结果
        +-- 输出：润色后的最终回答
        +-- 失败或丢信息：回退到本地确定性答案
```

## 工具

- `search_course_materials`：检索 `data/materials/` 下的 Markdown、文本和 PDF 课程材料。
- `query_deadlines`：读取并筛选 `data/deadlines.csv`。
- `plan_study_session`：根据截止日期和可用时间生成学习安排。
- `check_deliverables`：检查 README、源码、报告和截图等 BYOA 交付物。

所有工具都返回可追溯来源。文件缺失、坏 CSV、坏 JSON、坏日期范围等情况会以 `issues` 字段返回，而不是静默失败。

## 安装

```powershell
cd C:\Users\qingz\Desktop\agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

如果之前的 `.venv` 指向不存在的 Python，请先删除后重建：

```powershell
Remove-Item -Recurse -Force .venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

## 运行

推荐先使用本地确定性模式进行演示和截图：

```powershell
$env:STUDENT_AGENT_LLM="0"
python -m student_course_agent "Experiment 2 要求是什么？"
python -m student_course_agent "这周有什么要交？"
python -m student_course_agent "我今晚有 120 分钟，应该先做什么？"
python -m student_course_agent "检查我的 BYOA 项目是否可以提交。"
```

JSON 输出：

```powershell
python -m student_course_agent --json "这周有什么要交？"
```

交互模式：

```powershell
python -m student_course_agent --interactive
```

安装后也可以使用脚本入口：

```powershell
student-agent "这周有什么要交？"
student-agent-mcp
```

## DeepSeek 模式

DeepSeek 模式是可选总结层，不是演示必须路径。配置方式：

```powershell
$env:DEEPSEEK_API_KEY="你的 DeepSeek API Key"
$env:OPENAI_BASE_URL="https://api.deepseek.com"
$env:OPENAI_MODEL="deepseek-chat"
$env:STUDENT_AGENT_LLM="1"
```

运行：

```powershell
python -m student_course_agent --llm "Experiment 2 要求是什么？"
```

也可以依赖环境变量启用：

```powershell
python -m student_course_agent "Experiment 2 要求是什么？"
```

如果要回到稳定的本地模式：

```powershell
$env:STUDENT_AGENT_LLM="0"
```

或清除变量：

```powershell
Remove-Item Env:STUDENT_AGENT_LLM -ErrorAction SilentlyContinue
```

## MCP-style server

启动 stdio server：

```powershell
python -m student_course_agent.mcp_server
```

支持的方法：

- `initialize`
- `tools/list`
- `tools/call`

示例请求：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

`tools/call` 成功时返回 `result.content` 和 `isError: false`；工具名或参数错误时返回结构化 `isError: true`。

## 测试

```powershell
python -m unittest discover -s tests
```

测试覆盖：

- 工具检索和数据读取。
- 缺文件、坏日期、坏 JSON 等容错。
- CLI 普通输出、JSON 输出、LLM fallback。
- DeepSeek/OpenAI-compatible 配置解析。
- MCP `tools/list`、`tools/call` 和错误返回。

## 截图建议

报告要求 3 到 4 张真实运行截图。建议截以下 4 张：

1. `python -m student_course_agent "Experiment 2 要求是什么？"`
   - 截到实验目标、技术要求、交付物、评分标准、`来源:`、`工具调用:`。
2. `python -m student_course_agent "这周有什么要交？"`
   - 截到 deadline 列表、`data/deadlines.csv`、`query_deadlines`。
3. `python -m student_course_agent "我今晚有 120 分钟，应该先做什么？"`
   - 截到按分钟拆分的学习计划、来源和工具调用。
4. `python -m student_course_agent "检查我的 BYOA 项目是否可以提交。"`
   - 截到 `提交准备情况:` 和交付物检查结果。

截图放到：

```text
screenshots/
```

或：

```text
report/screenshots/
```

截图数量为 3 到 4 张后，再运行交付物检查，`Screenshots` 问题应消失。

## 项目中的 Prompt

本节只记录项目源码和示例文件中的 prompt，不包含开发对话内容。

### 1. 运行时 SYSTEM_PROMPT

位置：`src/student_course_agent/agent.py`

```text
你是一个单一用途的学生课程任务助手。
你的任务是帮助学生基于课程材料、截止日期和项目文件判断下一步该做什么。
回答课程相关问题前必须先调用工具，不能只依赖模型常识。
回答必须引用工具返回的本地来源。
如果本地上下文缺失，必须明确说明缺少什么，不能编造。
除非用户明确要求英文，否则使用简体中文回答。
回答要具体、简短、可执行。
```

### 2. DeepSeek/OpenAI-compatible 总结层 system prompt

位置：`src/student_course_agent/agent.py`

```text
你是一个学生课程任务助手。
下面会给你已经执行完毕的工具结果。
同时会给你一份本地确定性模式已经基于工具结果整理好的答案。
你必须严格基于这些结果生成简体中文最终回答。
如果本地确定性答案已经包含具体条目，你必须保留这些具体信息，可以润色和压缩，但不能改写成“工具结果不完整”。
不要编造新的工具调用，不要输出任何工具标记，不要输出 XML/DSML。
如果工具结果已经包含要求、截止日期或步骤，你必须直接总结出来，不要让用户自己打开文件查阅。
优先输出具体条目，而不是空泛描述。
不要说“搜索结果只返回标题”或“请打开完整文档查看”，除非工具结果确实为空。
回答要自然、清晰、可执行，并保留来源。
```

### 3. DeepSeek/OpenAI-compatible 总结层 user message 模板

位置：`src/student_course_agent/agent.py`

```text
用户问题：{question}

本地确定性答案：
{deterministic.answer}

工具结果：
{tool_summary_json}
```

### 4. 示例用户 prompt

位置：`examples/demo_transcript.md`

```text
这周有什么要交？
Experiment 2 要求是什么？
我今晚有 120 分钟，应该先做什么？
检查我的 BYOA 项目是否可以提交。
```

## 项目结构

```text
data/
  deadlines.csv
  materials/
    experiment-2-byoa.md
  student_preferences.json
examples/
  demo_transcript.md
report/
  draft_report.md
src/student_course_agent/
  __main__.py
  agent.py
  cli.py
  mcp_server.py
  models.py
  tools.py
tests/
  test_mcp_server.py
  test_tools.py
```

## 重要说明

- 默认截图建议使用本地确定性模式，输出更稳定。
- DeepSeek 模式用于证明兼容 OpenAI-compatible API；它不是必须截图的主路径。
- 如果 DeepSeek 总结丢失信息，代码会回退到本地确定性答案。
- 项目不会自动生成报告截图，截图必须来自真实运行结果。
