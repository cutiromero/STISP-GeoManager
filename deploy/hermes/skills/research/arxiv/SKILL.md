---
name: arxiv
description: 从 arXiv 检索与核对遥感、地球科学及机器学习预印本。
author: Hermes Agent
license: MIT
metadata:
  hermes:
    category: research
    tags: [Research, Arxiv, Papers, Academic]
    requires_toolsets: [web]
    related_skills: [grounded-citations]
    source: NousResearch/hermes-agent@0f602c5f6f18615632535251d62a2db74ce93b69:skills/research/arxiv
---

# arXiv 文献检索

1. 用 `web_search` 检索公开主题词、作者、文章标题或用户给出的编号。按需附加 `site:arxiv.org/abs`，检索遥感论文时可用术语、传感器和数据集名称缩小范围。只传公开信息。
2. 用 `web_extract` 读取命中的公开摘要页，核对标题、作者、编号、版本与日期。需要讨论具体方法或实验结果时，再读取可访问的论文正文。标明结论来自摘要还是全文。
3. 每篇列出与研究问题的相关点、有关的数据和指标、适用范围及真实摘要链接。默认把 arXiv 条目标为预印本。期刊或会议发表信息以可核查来源为准。
4. 用户需要 BibTeX 时，优先使用页面提供的引用。根据已核实元数据整理时保留 arXiv 编号和版本信息。
