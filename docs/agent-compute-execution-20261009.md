# 智能体计算执行机制（2026-10-09）

模型理解用户需求，平台执行注册算法并保存真实任务。两者通过持久计算计划连接：识别算法与授权数据 → 检索知识依据 → 提取或选择参数 → 提交与跟踪 → 验证输出 → 地图查看 → 选择入库 → 返回数据目录位置。

每轮 AgentRun.compute_intent 保存清单版本、资源修订、参数和任务回执。缺少波段语义时显示选择卡，用户文字明确波段时直接校验并执行。科研工作流继续承担多步计划；聊天计算计划复用已有计算与跟踪服务，避免占用科研工作流活动槽。输入参数来自注册清单，界面不为单个算法独立硬编码。

任务卡与成功报告由真实计算、输出与入库记录产生。用户查询进度时只查看本会话绑定任务；旧相似任务不能替代本次执行。参数确认与提交使用修订校验和幂等键，刷新及重复点击恢复原任务。默认完成后用户选择入库，明确自动入库时保留授权。Byte是存储类型，科学解释需要另外核对定标；合法波段选择依照实际计算影像的顺序。

未入库栅格通过固定stdin/stdout脚本在后端限幅、重投影和符号化，返回PNG与WGS84角点。每次预览核对项目、任务、输入访问权、过期与实际校验和。图像暂存内存（最多8项），临时文件当次清理，使用已有TOML尺寸和超时限制。前端只显示独立临时图层，不建立数据资源，不保存工程。

公开成熟框架可以借鉴的机制：

| 机制 | 本平台对应改进 |
| --- | --- |
| 工具调用与实际执行回执分开 | 文字不能替代执行记录，报告由实际任务生成 |
| 持久会话、检查点 | 保存当前计算计划及真实任务关联 |
| 暂停和恢复原流程 | 参数选择卡继续同一个计划 |
| 幂等副作用 | 重复点击、刷新、恢复不重复提交 |
| 固定全流程评价 | 检查参数、任务、输出数值、预览和入库对应关系 |

这是依据公开SDK/框架的设计比较；ChatGPT和DeepSeek对话产品的完整内部架构未公开。更换模型或安装SDK后仍须适配本平台的权限、算法清单、数据格式和结果管理。

来源：[OpenAI工具调用](https://developers.openai.com/api/docs/guides/function-calling)、[OpenAI运行智能体](https://developers.openai.com/api/docs/guides/agents/running-agents)、[LangGraph持久状态](https://docs.langchain.com/oss/python/langgraph/persistence)、[LangGraph交互中断](https://docs.langchain.com/oss/python/langgraph/interrupts)、[DeepSeek Harness公开参考](https://deepseek-harness.github.io/deepseek-harness/en/reference/)。
