---
name: research-workflow
description: 从对话发起科研业务流，发现资料、选择算子、衔接成果并处理执行诊断。
metadata:
  hermes:
    requires_tools:
      - get_research_workflow
      - todo_list
---

# 科研业务流

用户在会话中说出流程名称或提出对应科研任务时，用 `get_research_workflow` 按名称读取科研路径。也可以用 `list_business_flows` 查找项目中的流程，再读取相应版本。返回 domainSkill 时用 `skill_view` 查阅对应方法。围绕用户目标，用 `todo_list` 维护本次行动清单。

用项目目录找输入资料，通过样本和字段确认用途、时间和范围。需要用户选择时，用 `clarify` 一次问清当前影响分析的资料或口径。资料有缺口时继续可开展的分析，按实际发现增补、合并或调整行动。

需要计算时，先用 `inspect_research_operator` 按候选算子代码读取当前版本及清单，也可用 `list_compute_algorithms` 查找其他算子。用 `submit_research_compute` 提交。用 `get_research_compute` 的 waitSeconds 等待短计算，也可先推进相互独立的事项。用 `read_research_output` 读取实际结果。需要在下一个算子中使用时，把计算状态返回的 outputs.id 作为 outputId 传给 `register_research_output`。在登记状态为 ready 后使用对应 resourceId。

遇到失败，先读取 inputGaps、failure 和源码位置。输入或字段差异可用参数映射、已发布的转换算子或数据衔接脚本处理。需要修改 Python 时，用 `inspect_research_operator` 读取报错模块，再用 `submit_research_compute` 的 operatorEdits 提交算子副本。before 选源码里的唯一片段，after 写本次修改，retryOf 关联并沿用前一次的副本。继续修正时按 taskId 先查看实际执行过的源码。多个算子共享同一份 Python 模块时，可通过 reuseOperatorCopyFrom 在对应发布包复用已验证的修改。按修复目标复核真实输出和输入范围，继续后续研究；需要用户决定时提出具体选择。

按科研目标交付实际发现、计算结果及其入口。
