---
name: research-workflow
description: 根据已发布的科研业务流和当前任务资料制定行动计划，查找适用的项目工具并跟进科研成果。
metadata:
  hermes:
    requires_tools:
      - get_research_workflow
      - todo_list
---

# 科研业务流

用 `get_research_workflow` 读取用户选定的版本。需要从项目中发现流程时，使用 `list_business_flows`。返回 domainSkill 时用 `skill_view` 查阅对应的科研方法。结合本次目标、资料和交付方向，用 `todo_list` 建立行动清单。随新证据调整顺序、并行推进独立事项，并记录各项实际进展。

先用项目目录和样本核对资料对应的研究问题、时间、范围、字段及单位。遇到候选资料缺少字段、覆盖范围有差异或算子输入不匹配时，按受影响的研究判断选择补充资料、调整计算口径或继续可开展的步骤；需要用户决定时，用 `clarify` 提出具体选项。

需要计算时，用 `list_compute_algorithms` 查看候选版本的输入和参数，用 `submit_research_compute` 提交，然后用 `get_research_compute` 跟进。计算排队期间可以继续独立的资料核对与分析。用 `read_research_output` 读取已完成的成果，并提供实际可访问的文件或地图入口。用户需要将中间成果用于下一个算子或加入项目数据时，用 `register_research_output` 登记成果并取得资料编号。

按用户目标组织已完成的分析、计算成果、证据和后续行动。需要继续核查时，指出具体资料、位置或选择。
