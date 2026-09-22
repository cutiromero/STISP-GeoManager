# LangGraph 与 Pi Agent 评估及智能体架构更新方案

> 说明：本稿记录只读数据智能体阶段的评估，已由同日的 [科研工作流智能体架构方案 V2](2026-09-21-agent-architecture-review-v2.md) 扩展和替代。V2 增加了高光谱解译、算子编排、成矿理论评估、迭代复算和生态诊断的目标架构；本稿保留作为只读阶段的历史基线。

## 1. 评估范围和结论

本方案根据 2026-09-21 测试反馈、现有代码和 LangGraph、Pi Agent 官方资料重新评估。当前平台的目标是：普通用户可以和李老师服务器上的本地模型聊天；科研用户和管理员可以让数据智能体在当前项目授权范围内自主发现数据、读取字段、做受控只读统计和逻辑分析；未来再逐步增加受审批、受沙箱限制的算子能力。

当前系统的实际执行链是：React 前端 → Django Agent API → 独立 Python `agent_worker` → 李老师服务器的 OpenAI 兼容 Qwen 服务。现有智能体是自研 JSON 工具循环，不是 Pi Agent，也不是 LangGraph。会话、运行记录、事件和证据已经持久化在 Django 模型中；数据工具每次调用都会重新检查项目成员、数据资源权限和 owner-only 规则。

**总体结论：建议将 LangGraph 作为后续数据智能体的编排运行时，保留现有 Django 业务层、权限层、工具实现和 Qwen provider；不建议采用 Pi Agent 作为平台核心，也不建议一次性替换当前 worker。**

采用 LangGraph 的理由不是“框架能自动修复模型问题”，而是它更适合当前需要持久状态、确定性步骤、流式事件、失败恢复和未来人工审批的数据分析任务。Qwen 的工具协议、权限校验和数据安全仍必须由平台自己控制。

## 2. LangGraph、Pi Agent 与现有方案对比

| 维度 | 现有自研循环 | LangGraph | Pi Agent |
| --- | --- | --- | --- |
| 主要定位 | 平台内定制的 JSON 工具循环 | Python 状态图和长任务编排运行时 | TypeScript/Node 通用 agent runtime，带工具循环和事件流 |
| 与当前后端的关系 | 直接复用 Django/Python | 可直接运行在现有 Python worker 中 | 需要 Node worker 或 Python/Node RPC |
| 确定性流程 | 通过 while 循环手写 | 节点、条件边和子图表达更清楚 | 主要围绕模型回合和工具调用 |
| 持久化与恢复 | 业务运行记录已实现，节点级恢复较弱 | 官方提供 checkpointer、thread 和恢复语义 | Agent core 有状态；长期持久化需要另配 Pi durable 或平台适配 |
| 流式事件 | 自定义 RunEvent | 支持 updates、messages、tasks、checkpoints 等流式投影 | 事件种类丰富，工具事件和文本事件较完整 |
| 人工介入 | 尚未形成统一节点 | 支持 interrupt 与恢复 | 可通过事件、steering 和 follow-up 实现，但需自行接入业务审批 |
| 权限安全 | 已与平台数据权限紧密结合 | 仍需平台包装每个节点和工具 | 官方明确不内置文件、进程、网络和凭据权限边界 |
| Qwen 兼容性 | 已有 JSON 解析、`<think>` 清理和一次纠错 | 可以复用 provider，也可以增加结构化决策节点 | 可接 OpenAI 兼容模型，但仍需验证 Qwen 工具协议 |
| 依赖与部署 | 已在李老师服务器验证 | Python 依赖增加；可留在同一个 worker | Node >=22.19，增加一套运行时和供应链 |
| 适合本项目的角色 | 当前稳定基线 | **推荐作为数据智能体编排层** | 可作为以后独立聊天/通用 agent 的候选适配器 |

LangGraph 官方定位是低层编排和运行时，重点包括持久执行、流式输出、人工介入和状态持久化；它可以不依赖 LangChain。Pi Agent 官方资料显示其核心包是 Node/TypeScript runtime，提供工具调用、事件、上下文变换和 steering，但 Pi 项目本身不提供平台级文件、进程、网络或凭据权限系统，必须由外部沙箱承担。

参考资料：

- [LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph Durable Execution](https://docs.langchain.com/oss/python/langgraph/durable-execution)
- [LangGraph Streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- [Pi Agent Core](https://github.com/earendil-works/pi/tree/main/packages/agent)
- [Pi Agent Harness](https://github.com/earendil-works/pi)

## 3. 为什么不直接采用 Pi Agent

Pi Agent 并不是不可用，而是与当前平台的核心约束不匹配：

1. 当前业务边界是 Django/Python、SQLite、独立 Python worker 和已验证的 Qwen provider。接入 Pi Agent 需要增加 Node 22 运行环境、Node worker、跨进程取消和健康检查，部署面明显扩大。
2. Pi Agent 的工具执行权限是应用方责任。它不会天然理解当前项目、项目成员、owner-only 数据、撤权后停止读取和 Django 功能权限，所有工具仍必须通过 Django 服务代理。
3. Pi Agent 的事件和 transcript 与现有 `Conversation`、`AgentRun`、`RunEvent` 不是同一套数据模型。直接替换会影响历史会话、幂等键、事件游标、恢复和审计。
4. Pi Agent 的 parallel tool execution 对只读统计可能有帮助，但当前平台需要在每次工具执行前重新鉴权，并保持证据顺序和统计口径；并行化必须由平台逐工具声明是否允许，不能直接打开全局并行。
5. Pi 生态更适合通用 agent、编码 agent 和交互式工具加载。当前数据智能体首期明确禁止任意代码、主机命令、文件系统和网络访问，Pi 的默认生态反而需要更多裁剪。

因此，Pi Agent 可以保留为未来“通用对话或交互式 agent”的实验适配器，不作为当前数据智能体的基础框架。

## 4. 为什么 LangGraph 更适合当前平台

LangGraph 的优势与本项目的真实问题一一对应：

- **Python 适配成本较低。** 它可以和现有 `agent_worker`、Django ORM、SQLite 和 `provider.py` 放在同一 Python 进程中。首期不需要改模型服务，也不需要引入 LangSmith 云服务。
- **可以把确定性规则写成图节点。** 数据发现、资源授权、字段读取、统计、比较、证据检查和最终回答可以分别成为可审计节点；模型只负责选择下一步和组织答案。
- **可以表达恢复和人工审批。** 未来开放算子或写入时，可以在执行节点前中断，等待用户或管理员批准；当前首期仍让这些分支保持关闭。
- **可以统一事件流。** 图节点更新、模型消息、工具开始/完成、checkpoint 和任务状态可以映射到已有 `RunEvent`，前端不必立即改成另一种协议。
- **可以保留自定义模型适配。** 官方文档说明非 LangChain 集成的模型可以通过自定义 stream 输出接入。因此可以继续使用已经验证过的 OpenAI 兼容 Qwen HTTP provider，而不是强行更换模型客户端。

LangGraph 不会自动解决以下问题：Qwen 是否遵循工具协议、数据是否有权限、工具是否泄漏数据、模型是否产生错误统计、SQLite 是否能承受并发 checkpoint，以及上下文预算是否合理。这些仍由平台节点、工具包装器和测试负责。

## 5. 目标架构

### 5.1 分层结构

```text
React 普通聊天 / 数据智能体
              |
现有 Agent API：会话、提交、轮询、取消、历史恢复
              |
Django Agent Service
  ├─ PolicyResolver：额度、上下文、步骤、模型与能力
  ├─ LiveAuthorization：项目、成员、owner-only、功能权限
  ├─ EvidenceStore：证据、统计口径、脱敏和再授权
  ├─ ModelAdapter：当前 OpenAI-compatible Qwen provider
  └─ RuntimeRegistry
       ├─ JsonRuntime：现有自研循环，生产基线
       └─ LangGraphRuntime：新数据智能体运行时，候选灰度
              |
LangGraph Graph（仅编排，不拥有平台权限）
  ├─ load_context
  ├─ decide_action
  ├─ validate_action
  ├─ execute_read_tool
  ├─ record_evidence
  ├─ compact_context
  ├─ approval_gate（首期关闭）
  └─ finalize_answer
              |
只读平台工具注册表 → Django 数据权限服务 → 授权数据
```

### 5.2 业务数据与 graph 状态的分工

现有 Django 模型仍是用户可见业务记录的唯一事实来源：

- `Conversation` 保存会话归属、项目和标题。
- `AgentRun` 保存每次用户提交、模型、状态、答案、资源选择、证据和幂等键。
- `RunEvent` 保存前端轮询所需的文本、工具、上下文和状态事件。
- 新增的 `AgentCheckpoint` 只保存图执行恢复所需的内部状态，不作为另一套聊天历史。

LangGraph 的 `thread_id` 使用一次 `AgentRun` 的短 UUID，而不是直接使用用户可控的标题或资源 ID。每个图节点完成后保存 checkpoint；worker 重启后从最后一个已确认节点恢复。checkpoint 只保存：节点名、版本、动作计数、策略限制摘要、待执行动作、证据 ID、消息摘要和校验信息，不保存大量原始表格行、完整文档正文或未经处理的工具返回。

首期可以在现有业务 SQLite 上实现最小 Django checkpointer 适配器；如果实测 SQLite 在多 worker 下锁竞争明显，再把 checkpoint 单独迁移到应用数据根下的 SQLite 文件。不能直接引入一个不受备份和清理策略管理的临时数据库。只有在平台未来迁移 PostgreSQL 后，才考虑使用官方 Postgres checkpointer。

### 5.3 权限与策略必须分成两类

此前方案中的“策略快照”需要修正为两层：

1. **运行限制快照。** 运行开始时固定最大输出 token、最大工具步骤、最大详细资源数、最大上下文预算、超时时间和运行时版本。这保证运行中后台修改数值不会造成行为漂移。
2. **实时安全能力。** 每次恢复、模型决策、工具调用、证据读取和最终返回前重新检查账号是否有效、项目成员是否仍存在、资源是否仍可见、owner-only 是否发生变化、文档和比较能力是否仍开启。任何撤权立即停止运行，即使运行限制快照仍然有效。

这样既能让管理员修改策略对新任务清晰生效，又不会因为旧快照绕过数据撤权。

## 6. 数据智能体图设计

### 6.1 状态字段

`AgentState` 采用显式结构，而不是让模型自由扩展字典：

```text
runId / conversationId / projectId / ownerId
modelAlias / runtimeVersion / policyRevision
prompt / compactMessages
pendingAction / actionCount / protocolRetries
evidenceIds / contextBytes / lastNode
answer / status / errorCode
```

原始工具结果只在节点内短暂存在，持久化前转换为有上限的结果摘要。证据引用通过 `evidenceIds` 回到平台的 `AgentRun.evidence`，且每次读回都重新授权。

### 6.2 节点和条件边

1. `load_context`：读取当前会话历史，按运行限制预算压缩较早内容，实时校验项目和数据权限。
2. `decide_action`：使用 Qwen 生成 `final` 或工具动作。首期继续使用 JSON 输出，不假设 Qwen 已经稳定支持 OpenAI native tool call。
3. `validate_action`：后端验证 action 名、参数类型、字段白名单、能力开关和步骤预算。失败进入 `repair_action`，最多允许配置的协议纠正次数。
4. `execute_read_tool`：调用现有 `apps.agent.tools` 的包装器。包装器固定注入 run、用户和项目上下文，模型不能传入 SQL、路径、代码或数据库连接。
5. `record_evidence`：保存统计口径、筛选条件、样本限制、资源更新时间和证据 ID，写入 `RunEvent`。
6. `compact_context`：工具结果达到上下文阈值时，只保留必要摘要和证据索引；不能默默丢掉统计限制。
7. 条件边：达到步骤、时间、上下文或取消条件则转 `finalize_answer` 或失败；有新证据则回到 `decide_action`。
8. `finalize_answer`：校验引用的证据存在且当前仍可读，禁止把样例行当作总体统计，最终答案必须说明筛选和样本口径。
9. `approval_gate`：首期永远不可达。未来算子、写入或发布能力必须先通过平台权限、二次确认和独立 compute sandbox，不能直接在 agent worker 运行。

### 6.3 普通聊天图

普通聊天不加载数据工具，只使用 `load_chat_context → call_model → stream_answer → finalize`。它与数据智能体共享会话 API、模型选择和运行限制，但不共享数据工具权限。这样可以避免普通聊天因提示词或模型幻觉而声称读取了平台数据。

## 7. 配置和反馈问题的具体修正

超级管理员配置中应增加并统一以下字段：

| 配置 | 建议范围 | 生效位置 |
| --- | --- | --- |
| `dailyRuns` | 1–1000 | Django 提交接口原子检查 |
| `maxOutputTokens` | 128–8192 | 模型调用节点 |
| `maxSteps` | 1–64 | 图的循环边和后端计数器 |
| `maxResources` | 1–20 | 工具包装器；前端只是提示 |
| `maxContextBytes` | 8,000–128,000 | context 裁剪节点 |
| `maxProtocolRetries` | 0–3 | action 校验分支 |
| `maxRunSeconds` | 30–900 | worker guard 和 graph cancel |
| `allowDocuments` | 布尔 | 实时工具鉴权 |
| `allowCompare` | 布尔 | 实时工具鉴权 |
| `dataTypes` | 已注册数据类型 | resource query 和 tool resolver |

模型注册表增加 `contextWindow`、`supportsJsonMode`、`supportsNativeTools` 和 `runtimeCompatibility`。Qwen 当前至少标记为 `supportsJsonMode=true`，`supportsNativeTools` 必须以真实服务器验证为准，不能因为接口地址兼容就自动标记为 true。

每次提交都保存 `policyRevision` 和运行限制摘要。bootstrap、会话详情和运行详情返回当前用户可见的 `effectivePolicy`，前端在模型选择器旁显示“只读分析、最多 N 步、上下文约 M 字节、每日剩余 K 次”等信息。后台修改后只影响新运行；安全能力关闭则立即影响正在运行的下一次节点检查。

注意：字节预算和 token 预算不是同一个单位，不能互相替代。实现时使用独立的 UTF-8 字节上限和模型返回的 token 上限；如果模型注册表有上下文窗口，取模型窗口、平台预算和供应商限制中的最小值。

## 8. 分阶段更新计划

### 阶段 0：依赖与环境可行性验证，不改生产

- 在本机独立 Pixi 环境验证 `langgraph` 与 Python 3.14 的实际安装、导入、同步 graph、stream 和 checkpoint 行为。LangGraph 当前 PyPI 元数据要求 Python `>=3.10`，但公开分类器最高到 3.13，因此 3.14 必须实测。
- 验证 `langgraph-checkpoint-sqlite` 的 `aiosqlite`、`sqlite-vec` 和 SQLite 并发锁行为；不直接加入正式依赖。
- 用现有 mock model 和固定 Qwen 响应回放，验证 JSON 决策、工具错误、取消、恢复和事件映射。
- 记录依赖版本、许可证、包哈希和离线安装方式。LangSmith 只作为可选开发调试工具，不上传科研数据和生产提示词。

### 阶段 1：先修正平台策略契约，不切换运行时

- 增加 `maxContextBytes`、`maxProtocolRetries`、`maxRunSeconds`、模型上下文窗口和运行限制快照。
- 增加实时能力校验，明确运行限制快照不能绕过资源撤权。
- 统一后台表单、bootstrap、运行详情、worker 提示和审计字段。
- 增加测试：额度边界、后台修改后的新旧运行差异、上下文裁剪、owner-only 撤权、项目成员撤权、模型能力标记。

### 阶段 2：抽象运行时接口，默认仍用现有循环

- 定义 `AgentRuntime` 接口：`start`、`step`、`stream_events`、`cancel`、`resume`、`finish`。
- 把现有 JSON while 循环整理为 `JsonRuntime`，不改变生产默认路径。
- 统一所有运行时产生的事件、证据、错误码和 checkpoint 边界。

### 阶段 3：实现 LangGraphRuntime 离线回放版

- 用 `StateGraph` 编排上述节点，保留当前 `provider.py`，不先引入 LangChain model wrapper。
- 每个工具通过平台包装器执行；不直接使用未经审查的 `ToolNode` 默认执行函数。
- LangGraph checkpoint 与 `AgentCheckpoint` 适配，禁止把完整数据结果写入 graph state。
- 与 `JsonRuntime` 对同一批 mock 回放做结果、证据、事件顺序、取消和恢复对比。

### 阶段 4：李老师服务器候选环境验证

- 使用与生产相同的提交，复制到独立候选目录和端口；不重启 Qwen vLLM，不改变生产 TOML、科研数据和正式数据库。
- 先做模型 health、worker health、普通聊天、数据发现、字段质量、统计、协议纠正、历史恢复和权限撤回。
- 用至少 10 个固定任务比较两种运行时：成功率、协议错误率、工具步骤、答案证据一致性、p95 延迟、恢复成功率和 SQLite 锁等待。

### 阶段 5：仅超级管理员灰度

- 运行时选择由服务端 feature flag 控制，普通用户不能提交 `runtime` 参数。
- 初始只对超级管理员和测试项目开放 LangGraphRuntime；科研用户继续使用 JsonRuntime。
- 发现权限泄漏、证据不一致、恢复重复、锁竞争或 Qwen 兼容性下降，立即关闭灰度，历史运行继续由原记录读取。

### 阶段 6：正式切换或保留双运行时

- 只有当功能、安全、恢复、性能和运维验收全部通过，才将数据智能体默认运行时改为 LangGraphRuntime。
- JsonRuntime 至少保留一个版本周期作为回滚路径；不迁移旧会话的内部 checkpoint。
- Pi Agent 只有在未来出现明确 Node/TS agent 需求时，作为独立 `PiRuntime` 重新评审，不进入本次切换。

## 9. 验收门槛与回滚条件

### 功能

- 普通聊天不读取数据，也不虚构数据访问。
- 默认问题“请查找当前项目中可分析的表格，说明字段和数据质量”在 Qwen 上成功完成。
- 至少覆盖发现、字段描述、统计、比较、协议错误纠正、空数据和模型离线。
- 历史会话、事件顺序、取消和重新打开行为与现有 API 一致。

### 安全

- owner-only 资源只能由上传者和超级管理员读取；平台管理员不能绕过该规则。
- 运行过程中撤销项目成员或数据权限后，下一节点停止，不能把已撤权证据返回给用户。
- 模型不能指定任意 SQL、文件路径、Python、Shell、网络 URL 或未注册工具。
- 工具返回中的提示注入文本只能被当作数据，不能改变图的权限或能力。

### 恢复和一致性

- 在每个节点前后终止 worker，重启后最多继续一次，不重复产生工具事件或证据。
- SQLite 锁等待、checkpoint 增长和清理策略可观测；旧版本数据库可回退。
- 运行限制快照解释“为什么停止”，实时权限解释“为什么被撤回”。

### 性能与运维

- LangGraph 运行时 p95 延迟相对现有 JsonRuntime 增加不超过 20%，否则先优化或保留双运行时。
- 不增加 Qwen 服务重启，不改变 GPU、vLLM 和生产模型配置。
- 依赖可在本机和李老师服务器离线安装；health 能明确显示 runtime、worker、模型和 checkpoint 状态。

出现权限泄漏、任意执行、恢复重复、数据证据不一致、生产数据库迁移不可逆或模型服务受影响时，立即关闭 LangGraph feature flag，恢复 JsonRuntime；不删除会话、科研数据或生产模型进程。

## 10. 最终建议

推荐路线是：**现有 JsonRuntime 作为稳定基线 → 先完成策略和实时权限契约 → 抽象运行时接口 → LangGraphRuntime 候选灰度 → 通过李老师服务器真实 Qwen 验收后再切换。**

不建议现在直接安装 LangGraph 到生产环境，也不建议把 Pi Agent 和 LangGraph 同时引入。这样可以把“是否采用框架”的风险和“是否改变业务权限”的风险分开验证，任何阶段失败都能回到当前已经上线的只读数据智能体。
