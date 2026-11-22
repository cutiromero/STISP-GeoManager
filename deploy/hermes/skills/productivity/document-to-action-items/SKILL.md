---
name: document-to-action-items
description: 从科研方案、资料说明或评审意见中提取带出处的后续事项。
author: Ben Barclay (benbarclay), Hermes Agent
license: MIT
metadata:
  hermes:
    category: productivity
    tags: [Documents, Action-Items, Extraction]
    source: NousResearch/hermes-agent@0f602c5f6f18615632535251d62a2db74ce93b69:skills/productivity/document-to-action-items
---

# 从文档提取行动项

1. 使用用户粘贴的文档正文、明确授权给本次会话的摘录，或开启联网后由 `web_extract` 读取的公开页面。按标题、版次和条款定位内容。若只有文件名，要求用户提供相关正文或可访问的公开链接。
2. 将明确要求、截止日期、责任主体、所需资料和交付物写成可核查的事项。每行保留页码、章节、条款或一段可定位的短原文，标记缺失事实与矛盾。建议的行动项与文档已明确的要求分别标注。
3. 多步事项可用 `todo_list` 按优先级维护在本会话。项目任务的执行、审批和发布由平台业务流处理。
