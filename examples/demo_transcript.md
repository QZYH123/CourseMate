# 演示 Transcript

这些示例用于报告截图前的演示准备。真实截图应运行 CLI，并保留输出里的 `来源:` 和 `工具调用:`。

## Prompt 1

User: 这周有什么要交？

预期工具调用:

- `query_deadlines`

预期验证点:

- 输出列出 `Experiment 2 BYOA`、报告截图、反思段落和仓库清理等本地 CSV 中的截止日期。
- 来源包含 `data/deadlines.csv`。
- 末尾包含 `工具调用:`。

## Prompt 2

User: Experiment 2 要求是什么？

预期工具调用:

- `search_course_materials`

预期验证点:

- 输出总结实验目标、技术要求、交付物和评分标准。
- 来源包含 `data/materials/experiment-2-byoa.md`。
- 末尾包含 `工具调用:`。

## Prompt 3

User: 我今晚有 120 分钟，应该先做什么？

预期工具调用:

- `query_deadlines`
- `search_course_materials`
- `plan_study_session`

预期验证点:

- 输出给出按分钟拆分的学习安排。
- 来源包含 `data/deadlines.csv` 和 `data/student_preferences.json`。
- 末尾包含 `工具调用:`。

## Prompt 4

User: 检查我的 BYOA 项目是否可以提交。

预期工具调用:

- `search_course_materials`
- `check_deliverables`

预期验证点:

- 输出说明交付物检查结果。
- 如果还没有 3 到 4 张截图，会明确报告 `Screenshots` 问题；这是人工交付物，不应由代码伪造。
- 末尾包含 `工具调用:`。

## JSON 输出示例

```powershell
python -m student_course_agent --json "这周有什么要交？"
```

预期验证点:

- 顶层包含 `answer` 和 `tool_calls`。
- `tool_calls` 中至少包含 `query_deadlines`。
