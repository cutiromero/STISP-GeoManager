---
name: research-workflow
description: 在时空智能服务平台查找已发布的遥感科研业务流，核对实际输入和适配能力，并按用户要求启动流程。
metadata:
  hermes:
    requires_tools:
      - list_business_flows
      - prepare_business_flow_inputs
      - start_business_flow
---

# 科研业务流

用 `list_business_flows` 查找当前项目可执行的发布版本，核对资料角色、节点和审核要求。核对用户给出的资源 ID 和适用版本。

用 `prepare_business_flow_inputs` 核对输入与版本要求，按返回的候选转换工具和真实字段补充参数。存在歧义时通过 `clarify` 向用户问清所需资料或用途。

用户明确要求启动且输入准备就绪后，向 `start_business_flow` 传入发布版本、目标、输入及确认后的适配参数。以返回的工作流编号和实际状态向用户说明进度。结果解释、审核和人工决定依照平台流程节点执行。
