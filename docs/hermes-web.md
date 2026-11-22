# Hermes 网页开发

科研智能体和快速对话入口分别是 `/agent/workbench` 和 `/agent/chat`。顶部的「经典版／新版」切换执行入口，默认经典版。新版基于 Hermes Agent，负责会话状态、模型调用、上下文、工具调度、技能和 SSE。Django 保存会话的账号和项目归属，代理浏览器请求。平台业务流保留发布版本、输入适配、节点执行和人工审核。会话历史按所选运行时分别列出。

## 服务器运行

服务器使用 MH-agent 独立网关和千问本机模型。将 `config/mh-agent.example.toml` 的配置保存到正式业务数据根的 `config/mh-agent.toml`，填入安装好的 Hermes 可执行文件、千问监听端口和模型 ID。平台原有启动入口会启动旧工作进程并托管 MH-agent 子进程。网关凭据和会话位于同一业务数据根的 `config/mh-agent/`，候选使用自己的数据根和网关端口。网关仅监听回环地址。

发布前检查千问的原生 `tool_calls` 与工具结果回传。当前千问配置提供 131,072 token 的上下文窗口，满足 Hermes 运行时要求的至少 64,000 token。使用标准 `full` 发布和 `tools/release/validate_mh_agent_candidate.py` 验收候选，检查真实千问调用、工具回执、SSE、幂等及跨账号读取。新版接口位于 `/api/agent/hermes`。

## 本机运行

1. 按平台开发规范设置独立的业务与科研目录，在开发 TOML 中开启 `runtime.debug`。平台后端使用 `stisp-geomanager` 环境，执行 `python manage.py migrate`。初次使用空库时，执行 `python manage.py createsuperuser` 创建登录账号。以 `python manage.py runserver 127.0.0.1:8000` 启动后端。需要让平台处理已启动的业务流时，同时运行现有业务流队列及其所需算子服务。
2. 从仓库根目录运行 `/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python scripts/run_hermes_web.py`。脚本按固定提交准备 Hermes 及其隔离的 uv 环境，在回环地址启动网关。按终端提示输入 DeepSeek API 密钥，或通过进程环境提供 `DEEPSEEK_API_KEY`。
3. 在 `frontend` 运行 `pnpm dev`，打开本机网页并登录具有对应项目权限的账号。智能体沿用平台的会话侧栏和底部输入区。点击输入区工具栏的「技能与工具」，可以查看当前网关的技能说明、启用的工具集和工具名称。

模型暂用 `deepseek-v4-flash`。会话和调用中的业务流工具结果会发送给 DeepSeek。Hermes 的模型凭据由网关进程持有。网关内部凭据由启动脚本生成并保存在仓库忽略的 `.runtime/hermes-web/credentials.json` 中。

## 网页协议和平台扩展

网页使用 `/api/agent/hermes` 前缀下的原生 Sessions、Runs、Capabilities、Skills 和 Toolsets 路径。创建运行携带 `Idempotency-Key`。运行中的 `message.delta`、`message.interim`、工具和控制事件由 Hermes 生成。浏览器用事件序号续接，并用运行状态及会话消息对齐终态。网页凭据采用平台 Cookie、CSRF 和 `X-Project-Id`。

`deploy/hermes/plugin` 通过上游插件接口注册 `list_business_flows`、`prepare_business_flow_inputs` 和 `start_business_flow`。参数来自平台 OpenAPI 生成的工具合同。回调按会话真实账号和当前项目执行平台授权，业务流启动结果指向平台已有运行页面。平台业务流节点使用平台已登记的执行与审核模型。

`deploy/hermes/toolsets.json` 列出新版接入的项目工具，包括数据目录、样本和统计、知识检索、算子目录、地图数据概况及站内导航。工具实际调用前校验当前权限与参数合同，读取后保存摘要指纹和证据引用。读取或续接历史时重新校验已引用的资料与知识权限。

技能位于 `deploy/hermes/skills`，遵循 Hermes 的 `SKILL.md` 和 `metadata.hermes.requires_tools`。网关从精简索引发现技能，模型按需通过 `skill_view` 读取正文。共享技能由开发者维护。

## 科研技能与公开网页

| Hermes 官方能力 | 平台用途 |
| - | - |
| `web_search`、`web_extract` | 检索公开资料、读取公开网页。默认配置使用 Hermes 的 Keenable 后端。 |
| `todo_list` | 在当前会话拆解科研任务和跟踪进度。 |
| `grounded-citations` | 核对原始资料和引用位置。 |
| `arxiv` | 查找并核对预印本及版本。 |
| `document-to-action-items` | 从会话正文和可访问的公开说明提取附有出处的要求与后续行动。 |

管理员开启平台的联网检索策略后，可在科研智能体输入区开启当前会话的「联网检索」。启用后，公开主题词或网址会交给搜索服务。每次实际调用复核会话及当前项目的权限。三个官方技能沿用上游名称，按网页工具接口调整其执行步骤。来源提交和许可见 `deploy/hermes`。

上游来源是 NousResearch/hermes-agent 的 MIT 许可提交 `0f602c5f6f18615632535251d62a2db74ce93b69`。本机启动时移除该提交在技能发现 API 中传给 `find_all_skills` 的失效关键字，运行器及协议沿用上游。
