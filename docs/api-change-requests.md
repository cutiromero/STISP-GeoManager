# API Change Requests

## API-20261108-004 - 工程地图恢复与显示查询警告

- Status: BackendReady
- Owner: codex/xintao，单人依次负责契约、后端和前端。
- Endpoints: 既有资源query/profile/vector-tiles和工程详情。
- Change type: 修复显示说明返回为字符串的契约偏差，支持离线纯面MVT；工程恢复与重试行为优化。
- OpenAPI change: ValidationWarning.code说明真实质量问题与display_geometry显示说明的区别，统一为code/message对象，缓存版本更新。无新增路径或权限。
- Mock examples: 沿用既有查询及瓦片示例；定向夹具验证真实面属性、FID、原始文件不变和503恢复。
- Frontend reason: 智能体地图链接不再先全量查询再按视口查询，显示体积说明不误报坐标问题；临时繁忙自动恢复。
- Backend implementation notes: 显示查询保持完整坐标范围检查，跳过逐顶点精度估计；纯面仅离线准备并原子发布。恢复暂停旧视口请求，显示请求串行且只重试503，移动或换项目取消；业务查询/导出不重放。
- Verification: 200真实地图、401/403不重试、404失效瓦片、503有界退避与Retry-After；保留筛选、真实坐标错误、源数据和原ACL，真实浏览器多页打开和缩放。
- Result: 定向后端、前端和浏览器测试结果由本轮验收回执记录；无数据库结构或科研算子改动。

## API-20261108-003 - 全平台共用配色规则及唯一色表

- Status: BackendReady
- Owner: codex/xintao，同一任务维护契约、后端、前端及验收。
- Endpoints: 既有资源profile、工程详情/专题来源工程、计算输出地图预览、科研智能体工具。
- Change type: 配色语义统一及已有显示绑定按当前规则投影，无新端点或数据编辑权限。
- OpenAPI change: ResourceProfileResponse.defaultVisualization及WorkspaceSceneSnapshot说明绑定平台配色时使用当前规则；ResultColorAdvice增加可选policyRevision，流程版本说明修正为3。
- Mock examples: 沿用既有profile和工程自由格式快照；真实色表38类别及单一来源编辑回归验证，不新增模拟数据。
- Frontend reason: 智能体配色和逻辑推理保持一致，精确岩性颜色不被宽泛岩类覆盖；允许原色表本来同色的类别。
- Backend implementation notes: category_style及reference_entries唯一实现；岩性色值仅lithology_colors.json，蚀变仅alteration_colors.json。索引不重复保存色值，内容修订驱动缓存失效。已绑定快照/成果只投影展示，栅格规则变化后使用后台重新渲染；不写科学文件、不重跑模型和算子。普通未绑定手工样式保留。
- Verification: 同一张色表修改后，逻辑推理、普通工具及已保存工程刷新同时生效；38类逐色一致、同色保留、未知类按共用校验、栅格后台渲染与原始文件不变。原接口200/401/403/404和当前项目、ACL、owner规则保留。
- Result: 共用规则、唯一来源、真实工程接口和逻辑推理相关103项定向测试通过；服务器显示一致性和发布由独立回执核对。

## API-20261108-002 - 科研智能体个人地图与站内操作按钮

- Status: BackendReady
- Owner: codex/xintao，同一任务依次维护契约、后端、前端及验收。
- Endpoints: 既有 GET /api/agent/runs/{runId}/、GET会话详情、GET/PUT智能体策略。
- Change type: AgentRun新增可选platformActions数组，AgentPolicy新增可选mapDisplayEnabled（默认true）。
- OpenAPI change: AgentPlatformAction限定workspace/page、当前projectId及真实sceneId或站内page枚举；不接受模型URL。三个注册工具沿用既有worker命令协议，无新公共工具执行端点。
- Mock examples: 无新增mock文件；真实GeoPackage/GeoTIFF夹具、worker调度及按钮浏览器测试覆盖新字段。
- Frontend reason: 用户可让科研智能体读取真实类别、设置配色并生成“在地理工作台查看”按钮；个人工程持久化，原始数据不变。
- Backend implementation notes: get_map_data_profile只读限量类别；prepare_map_workspace重验当前项目、ACL、普通业务集合、手选范围、数据修订及加载/配色/新增工程权限，按run与内容幂等创建私有引用工程；get_platform_link只允许固定页面。序列化按钮从真实工程重建，撤权不返回按钮。连续栅格沿用已有显示，分类栅格由原后台渲染颜色表。
- Verification: 200返回当前用户真实操作、401未登录、403功能/数据/项目拒绝、404他人运行；内部参数错误保留工具错误证据且不产生工程。验证原始字节和资源元信息不变、分类完整、撤权及跨用户隔离、幂等、地图恢复、真实模型调用与浏览器加载。
- Result: 本地后端工具及worker链路、前端按钮与地图恢复定向测试通过；服务器候选和正式验收另由发布回执记录。

## API-20261108-001 - 页面会话后台恢复与多标签交接

- Status: BackendReady
- Owner: 当前个人开发分支 codex/xintao；同一任务维护契约、前后端及验收。
- Endpoints: POST /api/auth/browser-session/，现有认证与受保护API调用。
- Change type: BrowserSessionRequest新增join动作；BrowserSessionResponse新增可选familyId；恢复及abandon行为修正。
- OpenAPI change: 120秒访问租约保留；未挂起的已登记页面在租约后12小时内凭正确令牌可恢复；suspend后刷新窗口120秒；join要求有效Cookie、CSRF及另一有效页面；abandon不注销仍可恢复的共享会话。
- Frontend reason: 后台节流、休眠和新对比页交接延迟不应使正在使用的页面突然退出。请求前合并续期，401只重试一次，主动退出仍立即生效。
- Mock examples: 使用真实Django Session与受控时钟、真实双标签浏览器验证，不生成科研计算或业务数据。
- Backend implementation notes: Session只保存令牌摘要；挂起页面不能由heartbeat复活；familyId不参与鉴权。Cookie重放、无在线页join、错令牌、撤权及CSRF继续拒绝。
- Verification: 后台超时恢复、刷新、多标签无BroadcastChannel交接、显式退出/旧登录竞态、权限及关闭最后标签回归。
- Result: 后端与浏览器定向回归通过；Cookie重放、关闭页面和CSRF边界保留，服务器发布由精确冻结回执确认。

## API-20261107-003 - 管线地图按尺度简化和压缩传输

- Status: BackendReady
- Owner: 同一任务先完成前端契约，再交接后端实现，最后接入前端并验收。
- Endpoints: POST /api/catalog/resources/{id}/query/。
- Change type: QueryRequest新增可选lineSimplifyTolerance，0至0.1度；须同时启用displayGeometry。省略保留现有量化语义。
- OpenAPI change: 仅线几何采用显式容差保拓扑简化；点、面、原精度请求、属性与对象数量保持。响应按Accept-Encoding协商gzip。
- Mock examples: mock/prism/requests/pipeline-display.json，包含保留属性及对象ID的线显示结果。
- Frontend reason: 全球管线139万顶点使传输和浏览器绘制缓慢；普通视野显示按像素选择容差，线显示预算提升至10000以避免全球线网600条截断。
- Backend implementation notes: 显示简化发生于WGS84转换后；原始命中判定不变。空间显示查询按完整参数及资源修订隔离缓存，每资源最多32条空间预览缓存；入口权限检查保持。禁止改写GeoPackage或将简化结果用于计算。
- Verification: 非法参数、默认量化、线端点/误差/属性/ID、点面不变、原始数据未修改、缓存隔离与修订失效、gzip、全球与三区/空海洋/快速移动真实浏览器。


- Result: 本机后端58项（另3个子测试）、前端9项和浏览器8项通过；生成契约、类型检查、lint及生产构建通过；服务器候选和正式公网待验收。

## API-20261106-005 - 资料确认与启动分析合并

- Status: BackendReady
- Owner: 同一任务依次负责契约、后端和前端。
- Endpoints: POST /api/agent/workflows/{workflowId}/confirm/；POST /api/agent/runs/{runId}/research-intent/；既有逻辑推理对话接入和工作流执行。
- Change type: 新增可选布尔字段executeAfterMapping，默认false，仅通用地质字段确认阶段approve允许。
- OpenAPI change: AgentWorkflowConfirmation.executeAfterMapping。true同时授权校验后执行初始分析计划，未提供时保留原有仅确认字段行为；其他阶段、reject、缺fieldMapping或类型错误均400。
- Mock examples: 107-agent-input-start.json展示确认后的排队状态。
- Frontend reason: 使用“确认资料并开始分析”一次完成输入确认及启动，避免紧接着重复确认固定计划；模型已唯一识别的完整角色建议直接进入资料与字段核对。
- Backend implementation notes: 授权绑定当前planHash、字段摘要与输入摘要，持久步骤证明并在工作副本及算法冻结后重验。固定计算阶段自动推进，专业建议生成、处置批准、质量、预算及权限边界保留。
- Verification: 默认false、显式true、篡改授权、撤权、阶段与类型错误、恢复及重复提交；浏览器按钮、过程摘要及完整审计；全套契约检查。
- Result: 输入授权、固定步骤直接执行、类型与防篡改边界定向测试通过；真实候选及正式浏览器验收单独记录。

## API-20261106-004 - 普通目录共享明确内部材料标识

- Status: BackendReady
- Owner: Frontend / Backend。
- Endpoints: GET /api/catalog/resources/；GET /api/search/；GET /api/layers/；未指定resourceId的GET /api/compute/inputs/；后台资源列表/导出及共用资源、图层统计。
- Change type: 普通目录可见集合收窄；响应结构、字段和按编号绑定读取不变。
- OpenAPI change: 说明普通目录依据source/code隐藏明确内部任务材料及注册规则；普通智能体继续执行更严格的成果溯源边界。
- Mock examples: 沿用现有目录与图层示例；集成夹具覆盖同名业务/内部资料、各内部source、注册规则code和命名空间、匿名列表及保留默认图层。
- Frontend reason: 全站普通数据目录与智能体候选对明确内部材料保持一致，避免将冻结规则、修改表和评价材料显示成普通业务资料。
- Backend implementation notes: catalog.models集中定义INTERNAL_SOURCE_PREFIXES与RESERVED_RULE_CODES；agent发现导入同一常量。task_resource_q同时处理资源字段及关联图层前缀，现有列表、导出和统计调用共用过滤。保留业务上传、计算成果、工作流报告和原有按ID/真实任务绑定读取，不做数据删除、迁移、名称过滤或全局ComputeImport溯源重构。
- Verification: resources/search/layers/admin列表逐类标识正反例；任务绑定读取、任务上传隔离、计算输入目录及匿名/默认图层回归；API生成、一致性、变更记录、文档与lint检查。
- Result: 后端78项专项通过，含26项新增目录边界测试；API生成、一致性、变更记录、文档与lint检查通过。普通业务和真实任务绑定读取保留；候选服务器的新目录边界尚待部署后复验。

## API-20261106-003 - 智能体普通发现与任务内部材料隔离

- Status: BackendReady
- Owner: Frontend / Backend。
- Endpoints: GET /api/agent/resources/；GET /api/agent/bootstrap/；GET/POST /api/agent/workflow-uploads/references/；现有运行提交、工具读取与工作流材料接口。
- Change type: 既有候选、直接读取及上下文权限语义收窄；响应字段与结构不变。
- OpenAPI change: 资源发现、目录页及引用、算法候选与知识选择说明统一普通业务边界和真实任务绑定；详见 docs/agent-data-boundary.md。
- Mock examples: 沿用 mock/prism/examples/96-agent.json、104-agent-upload-bundle.json；专项夹具覆盖真实空目录、业务演示名称及通用计算目录含内部材料时的候选交集。
- Frontend reason: 普通候选仅来自agent授权接口；通用计算详情不扩大资源或算法白名单。空集合不回退目录；任务上传及历史明细不合并到新任务普通候选。
- Backend implementation notes: 普通搜索、统计、目录、元信息、直接编号和手选统一当前项目ACL、active、ready的业务上传及明确成果集合；排除trial、工作副本、冻结规则、修改表、过程结果与评价真值，不按演示或测试名称过滤。内部材料限真实owner及workflow/batch/task绑定；旧历史保留原授权读取，新context重新验证。算法仅enabled/published/允许agent，知识独立published及领域ACL，草稿仅显式场景绑定。
- Verification: 正反来源、直传编号、手选、空目录及目录总数、业务演示名称、项目与owner隔离、任务绑定及历史恢复；专项浏览器、TypeScript与契约检查，不运行全量测试。
- Result: 后端来源与绑定专项、前端6项浏览器边界专项、两项TypeScript及API生成/一致性/变更记录/文档/lint/Prism构建通过；统一数据来源与授权语义，不改变原有批准流程或通用计算中心权限。真实模型与服务器验收另行进行。

## API-20261106-002 - 真实答复增量预览与轻量模型活动

- Status: BackendReady
- Owner: Frontend / Backend。
- Endpoints: GET /api/agent/runs/{runId}/；GET /api/agent/conversations/{conversationId}/；GET /api/agent/workflows/{workflowId}/。
- Change type: 既有响应增加可选字段；轮询、历史恢复与访问权限不变。
- OpenAPI change: AgentRun.answerPreview（最多24000字符）；AgentEvent.kind增加内部answer_preview快照事件；AgentWorkflow.modelActivity及AgentWorkflowModelActivity定义真实阶段、请求状态、思考内容与接收字符数，card/inspection/full详情均可包含，不扩大工作流列表摘要。
- Mock examples: mock/prism/examples/106-agent-generic-chat.json、105-agent-workflow-card.json。
- Frontend reason: 最终答复校验前显示真实增量纯文本，标明生成中或中断片段；工作流模型活动与算子进度分别显示，使用现有轻量card轮询。
- Backend implementation notes: 普通chat允许真实自然语言正文预览；agent仅在确认action=final后预览answer字符串增量解码结果，不返回工具参数或原始JSON。重试及工具调用重置，成功后清空，失败或取消保留。小型answer_preview事件保存当前快照，空串重置，前端进度日志隐藏且仅从run.answerPreview读取；预览截断不影响最终answer。普通运行思考首片立即持久化，正文开始时保存批量处理中剩余思考尾部。工作流仅实际模型回调提供思考，保留最近12000字符并以truncated标记省略早期思考，thinkingChars累计；outputChars仅计数。小型持久步骤保存快照，沿用本人、项目和工作流权限；暂停和终态优先于模型活动状态。
- Verification: 普通chat自然正文、agent最终answer首片、转义及拆分字符串、工具参数排除、成功替换、失败取消与恢复；短思考首片和尾部持久化；真实思考及接收计数、算子/终态优先、轻量轮询和按需明细；专项浏览器、真实UI与SSE模拟fixture端到端、两项TypeScript及五项契约检查。
- Result: 可选兼容契约与前端状态显示；增量片段只表示已接收文字，最终校验及原有审批继续生效。

## API-20261106-001 - 逻辑推理默认深入与科研任务思考选择继承

- Status: BackendReady
- Owner: Frontend / Backend。
- Endpoints: GET /api/agent/bootstrap/；POST /api/agent/conversations/{conversationId}/runs/；POST /api/agent/workflows/；POST /api/agent/workflow-uploads/recognize/。
- Change type: 既有模式、强度与预算的默认值和继承语义；请求、响应字段及权限不扩展。
- OpenAPI change: 补充 AgentBootstrap.defaultReasoningEffort、AgentRun.thinkingMode、AgentRunInput.thinkingMode 的默认选择与工作流继承说明。
- Mock examples: 沿用 mock/prism/examples/96-agent.json、106-agent-generic-chat.json、107-agent-logic-configuration.json；返回结构不变，模式传递由 HTTP 模型请求捕获与专项夹具验证。
- Frontend reason: 逻辑项目默认显示深入并明确发送 deep+xhigh；轻量发送 fast 且省略强度，标准发送 deep+medium。使用默认强度恢复深入，沿用已确认配置的显式选择，其他项目保留既有偏好。
- Backend implementation notes: 新建策略默认 xhigh；聊天工作流优先继承已绑定 requestRunId，无则 originRunId。核对本人、项目、会话、模型和工作流绑定，重新授权时复核当前策略与任务预算；来源停止、归档、模型不支持或策略禁用时拒绝继续。独立工作流及角色识别遵循当前后台策略，分词和生成使用同一模式与强度；栅格输入和输出上限保持不变。
- Verification: 默认与三档提交、配置及 bootstrap 恢复、模型与策略禁用、项目切换；工作流绑定隔离、策略与额度收窄、分词与生成参数一致；generate:api、check:api、api:changes:check、api:docs、api:lint。
- Result: 用户选定的思考模式、强度和预算贯通科研任务；原有审核、权限和生成额度约束继续生效。

## API-20261105-014 - 蚀变归类组审批与按要素对比分页

- Status: BackendReady
- Owner: 本任务显式贯通算子、契约、后端、前端及测试。
- Endpoints: GET /api/agent/workflows/{workflowId}/；POST /api/agent/workflows/{workflowId}/confirm/。
- Change type: 增加compare的element过滤、全局计数/面积/稳定revision、蚀变栅格输出引用和紧凑审批选择/组动作。
- OpenAPI change: AgentWorkflowPage、AgentMultiElementMap、AgentWorkflowConfirmation；generated类型由契约重新生成。
- Mock examples: mock/prism/examples/105-agent-workflow-card.json。
- Frontend reason: 任意要素可直接分页查看，数千项全选不提交冗长编号，组动作和失败原因在审批处可见。
- Backend implementation notes: 本人、当前项目和资源权限不变；紧凑选择仅在当前冻结方案展开，待裁定/例外须显式纳入；蚀变动作只能覆盖已选AG组，批准记录和执行CSV双重校验；旧对象任务仍可读取。
- Verification: 算子像元级测试、6268项审批、冻结越界检查、按要素投影与报告/预算测试；OpenAPI全流程；浏览器用例只更新，不运行。
- Result: 本地实现，未发布。真实模型token与正式资料效果须在候选站验收。

## API-20261105-013 - 模型尝试审计响应与精确校验反馈

- Status: BackendReady
- Owner: 本任务显式贯通模型校验、工作流审计及前端失败记录展示。
- Endpoints: GET /api/agent/workflows/{workflow_id}/（含 view=inspection&part=steps）
- Change type: 在已有 outputRefs 开放对象中增加可选 modelResponse 审计产物。
- OpenAPI change: AgentWorkflowStep.outputRefs.modelResponse 定义 content、truncated、sizeBytes；沿用工作流历史访问鉴权。
- Mock examples: 无新增端点；相关后端集成测试覆盖实际响应，浏览器用例更新但不执行。
- Frontend reason: 失败卡片须查看对应模型响应，避免将精简接口未携带正文误报为未保存。
- Backend implementation notes: 每次尝试使用持久步骤保存脱敏原始正文，UTF-8 上限2 MiB；流异常保留部分正文；发现和待核实项规整，引用真实性和动作权限严格校验。
- Verification: 相关后端测试；generate:api、check:api、api:changes:check、api:docs、api:lint。
- Result: 本地实现，未发布；历史未保存的响应不可补回。

## API-20261105-012 - 全类别成果配色与逐类来源审计

- Status: BackendReady
- Owner: 本任务显式贯通契约、后端及前端符号化读取。
- Endpoints: GET /api/catalog/resources/{id}/profile/。
- Change type: defaultVisualization 增加可选类型化 colorAdvice，原有空方案和旧审计保持有效；无端点或权限变化。
- OpenAPI change: ResultColorAdvice、ResultColorClassAdvice 定义逐类来源、色表引用、替换原因、最终约束问题及模型尝试。
- Mock examples: mock/prism/examples/30-catalog-vector.json，资源默认方案提供逐类配色审计示例。
- Frontend reason: 普通工作台与对比/讲解使用同一资源符号化、模型图例名称及边框/透明度，不自行决定成果颜色。
- Backend implementation notes: 全部类别提交本次所选模型，参考色表按相关性检索；预算投影、校验反馈修正一次及离线回退；管理命令预览不保存、应用强制重算。
- Verification: 38类岩性色表选择、未知模型建议、低对比/重复/非法色修正及补色、离线无请求、预算压缩、逐类来源、管理命令、前端共享符号化与API生成检查。
- Result: 后端实现及定向用例就绪；真实模型审美、服务器部署与业务数据重配色不在本次本机验证范围。

## API-20261105-011 - 显示几何统一网格与共享边界

- Status: BackendReady
- Owner: Frontend / Backend
- Endpoints: POST /api/catalog/resources/{id}/query/。
- Change type: displayGeometry 行为修正，字段及权限不变。
- OpenAPI change: 取消所有形状简化，统一1e-5度网格，共享边界共同节点化并量化；超出280 KiB gzip目标只警告，不再增加容差。
- Mock examples: 沿用 mock/prism/examples/30-catalog-vector.json，GeoJSON 响应结构不变；共享边界与退化环由后端单元测试覆盖。
- Frontend reason: 所有逻辑推理双图复用本地SVG，避免简化错边及外部底图服务依赖。
- Backend implementation notes: 保留要素与属性，仅清理重复点、零面积退化环；共同节点化可补入共享顶点，缓存算法版本2使旧简化结果失效；不改存储或计算输入。
- Verification: 后端共享边界、顶点、退化环、超预算及缓存测试；前端类型及API流程；独立对比与讲解浏览器用例。
- Result: 实现及回归用例已同步；浏览器与服务器验收独立进行。

## API-20261104-008 - 综合推理分组审批与显示几何

- Status: BackendReady
- Owner: Frontend / Backend
- Change type: 可选字段与显示参数；原逐对象审批请求保持兼容。
- Endpoints: GET /api/agent/workflows/{workflowId}/；POST /api/catalog/resources/{id}/query/。
- OpenAPI change: AgentModificationSuggestion 新增 groupId；QueryRequest 新增 displayGeometry，默认 false；selectedSuggestionIds 移除通用maxItems，综合推理同族不设数量上限，其他场景仍由后端保留30项限制。
- Frontend reason: 同类疑点按组审批、排除个别对象；前后图优先并发显示岩性，不等待其他成果。
- Mock examples: mock/prism/examples/105-agent-workflow-card.json；30-catalog-vector.json。
- Backend implementation notes: 模型分组建议绑定检查快照，完整展开后逐对象校验；review/exception 不得整组执行，同对象多规则按检查顺序执行首个已选择建议。审批仍提交 selectedSuggestionIds，报告和复查使用实际操作。综合推理公开 plan 不返回内部全量检查行、重复建议及模型请求，但保留 approvedEdits 和完整 changes 行，供地图逐对象核验；modificationReview 保留完整对象审批范围，详情支持gzip。displayGeometry 只影响返回几何，不改原数据、权限、属性与计数；显示请求最多并行2路，原查询限流及gzip保留。
- Verification: 7362对象分组展开、快照和动作校验、保护待裁定/例外、超过30对象批准执行、显示精度与存储隔离、双图首屏不等待后续图层、分组及快速多选浏览器回归。
- Result: 分组与显示几何已实现；验证结果见任务报告，未部署服务器。

## API-20261105-009 - 工作流计算名额与停放任务

- Status: BackendReady
- Owner: Frontend / Backend
- Change type: 活动任务摘要扩展与409行为说明。
- Endpoints: GET /api/agent/workflows/active/；POST /api/agent/workflows/、confirm/、resume/。
- OpenAPI change: item仅为queued/running/waiting_compute；新增parked数组返回waiting_approval/paused；摘要可含conversationId和conversationTitle。计算名额冲突的409 detail标明任务、项目及来源对话，原确认和暂停点保留。
- Frontend reason: 计算任务与待处理任务分开提示，提供查看与结束入口，停放任务不阻挡新任务。
- Mock examples: mock/prism/examples/104-agent-upload-bundle.json。
- Backend implementation notes: agent.0022_parked_workflow_slots收窄唯一约束；创建、批准、恢复通过同一账号事务锁校验名额；取消与暂停仍适用于所有未结束状态。拒绝批准和恢复至等待确认不占计算名额。
- Verification: 停放并存、新建、计算冲突身份、批准/恢复冲突保持状态、结束后继续、迁移保留旧记录、跨项目与本人隔离。
- Result: 计算状态约束、摘要、交互与回归已实现；服务器尚未部署。

## API-20261105-010 - 待裁定与例外的用户候选处置

- Status: BackendReady
- Owner: Frontend / Backend（本任务显式跨栈交接，依次完成契约、后端和前端）。
- Endpoints: GET /api/agent/workflows/{workflowId}/；POST /api/agent/workflows/{workflowId}/confirm/。
- Change type: 建议增加可选候选字段；人工确认语义扩展，不新增目标输入。
- OpenAPI change: AgentModificationSuggestion.candidateAction、candidateTargetCode；status保留检查规则判断。selectedSuggestionIds可含用户明确选择的冻结候选编号；全选普通建议不包含候选。
- Mock examples: mock/prism/examples/105-agent-workflow-card.json。
- Frontend reason: 待裁定与例外区按组或按对象选择候选处置/保留，默认保留；轮询更新不重建审批和证据区域。
- Backend implementation notes: 候选直接来自本次真实检查快照，不依赖模型提议。模型对待裁定/例外只能保留；确认和执行重新校验原输入、规则、知识修订、候选动作和目标，用户裁定记录写入批准理由及实际修改记录。算子1.0.8；原1.0.7快照不补造候选。
- Verification: 候选生成、默认保留、模型越权拒绝、用户选择执行与融合、目标及快照篡改拒绝、权限和项目隔离、修正记录标注、卡片状态及滚动位置保持。
- Result: 本地实现和定向验证；未修改正式站规则、数据或服务，旧工作流须重新检查才有新候选。

## API-20261104-007 - 逻辑推理分页选择与已确认配置复用

- Status: BackendReady
- Owner: 科研智能体。
- Change type: 选择器分页响应及查询参数；新增本人项目配置读取、恢复；提交增加显式复用标记。
- Endpoints: GET /api/agent/workflow-uploads/references/；GET/POST /api/agent/logic-configuration/；POST /api/agent/conversations/{conversationId}/runs/；POST /api/agent/runs/{runId}/research-intent/。
- OpenAPI change: 目录筛选directoryId，分页page/pageSize，返回total/directories及登记、更新时间；配置返回configuration/unavailableResourceIds/items；AgentRunInput.reuseConfirmedConfiguration默认false；plan.reusedConfiguration标明沿用；计划批准前支持“修改角色和字段”。
- Frontend reason: 演示数据默认可见、无静默截断；新会话跨电脑复用已确认的系统数据配置，避免重复核对。
- Mock examples: mock/prism/examples/104-agent-upload-bundle.json；mock/prism/examples/107-agent-logic-configuration.json。
- Backend implementation notes: LogicConfiguration按owner/project_tag唯一；字段确认后仅保存系统数据部分，排除临时上传及其角色、字段；临时地质图需下次补选。恢复、发送、字段沿用均重新鉴权并匹配资源更新时间和真实画像；只沿用角色及字段，不沿用任何计划和处置批准。
- Verification: 最近排序、分页总数、目录筛选、跨用户及跨项目隔离、失效引用提示、配置持久化与沿用、计划与批准保留人工确认、重新核对、临时资料不保存。
- Result: 相关后端104项、前端普通单测554项及类型检查通过；浏览器回归已覆盖恢复、收起、分页、强度和360px布局，Chromium在沙箱中启动受限，需外部复跑。

## API-20261104-006 - 逻辑推理选择系统数据

- Status: BackendReady
- Owner: Frontend / Backend。
- Change type: 新增接口，批次资料新增可选字段。
- Endpoints: GET/POST /api/agent/workflow-uploads/references/。
- OpenAPI change: 新增目录资源搜索与引用加入批次；批次资料新增可选 source（upload 或 catalog）。
- Frontend reason: 逻辑推理对话输入区可搜索、勾选当前项目的系统数据，与上传资料同批进入角色与字段确认；移除目录项只解除引用。
- Mock examples: mock/prism/examples/104-agent-upload-bundle.json。
- Backend implementation notes: 批次资料对资源改为可重复引用，同一资源可用于多个任务；目录原资源的状态、隐私与来源不变；创建、发送和执行时按当前项目与资源权限重新鉴权；资料画像读取计算用原始数据。
- Verification: 引用与重复引用、移除后原资源保持可用、跨用户与跨项目拒绝、对话流程、上传与目录资料混合识别。
- Result: 后端与前端回归通过；候选环境以目录中的演示岩性、构造和五类蚀变完成真实模型全流程，原资源保持可用。

## API-20261104-005 - 当前对话内通用地质推理

- Status: BackendReady
- Owner: phaseB；本任务显式贯通契约、后端与前端。
- Change type: 现有提交接口新增可选字段，扩展既有研究交互语义。
- Endpoints: POST /api/agent/conversations/{conversationId}/runs/；POST /api/agent/runs/{runId}/research-intent/。
- OpenAPI change: AgentRunInput新增可选uploadBatchId（需求最多12000字）；既有answer支持严格的阶段确认，返回200及持久化后续对话运行，重复回答返回202；补齐每日额度429。无法确定时保留卡片，无新增接口。
- Frontend reason: 上传、角色、字段、计划和批准均在当前对话，历史对话恢复真实AgentWorkflow。
- Mock examples: mock/prism/examples/106-agent-generic-chat.json。
- Backend implementation notes: 批次限本人、当前逻辑推理项目、单一研究任务；不绕过字段、计划、逐项处置和快照校验。
- Verification: 对话绑定、角色修改、阶段确认、重复提交、会话恢复及他人隔离；非逻辑项目保持原入口。
- Result: 本地后端确认点、权限及相关回归通过；前端单元550项通过，浏览器因沙箱Chromium MachPort权限未执行。未部署服务器；完整交互与公网加载耗时需外部复跑。

## API-20261104-004 - 轻量工作流卡片与任务矢量按需读取

- Status: BackendReady
- Owner: phaseA；本任务显式贯通契约、后端、前端。
- Change type: 默认兼容的详情投影、矢量输出地图读取和资源默认方案详情。
- Endpoints: GET /api/agent/workflows/{workflowId}/?view=card；GET /api/compute/outputs/{outputId}/preview/?view=map。
- OpenAPI change: AgentWorkflow新增可选view/stepCount；card投影清空steps/evidence，仅保留阶段状态与成果引用，不含modelAttempts、finalStage或modificationReview；默认full不变。ComputePreview新增可选geojson，map视图最多30000要素，超限409，不截断。
- Profile contract: GET /api/catalog/resources/{id}/profile/新增可选defaultVisualization（默认方案对象），仅详情返回，不扩大资源列表体积。mock/prism/examples/30-catalog-vector.json补充空方案示例。
- Frontend reason: 对话历史不预取过程、报告和计算详情；对比/讲解直接读取未入库中间文件。
- Mock examples: mock/prism/examples/105-agent-workflow-card.json。
- Backend implementation notes: 保持本人、项目及计算输出访问鉴权；map校验文件checksum，输出WGS84。综合推理族只自动入库九类用户成果，全部计算输出与报告追溯保留。
- Verification: 两个综合推理类型的入库集合、card大小与字段、默认详情、矢量校验/上限；新标签入口与页面会话租约、按需加载回归。
- Result: 后端相关122项与前端单元550项通过；TypeScript与契约生成一致。浏览器因沙箱Chromium MachPort权限失败未执行，部署与公网耗时未验收。

## API-20261104-003 - 任务资料批量上传、角色识别与活动任务摘要

- Status: BackendReady
- Owner: logic-upload-bundle；本任务显式贯通契约、后端、前端。
- Endpoints: POST /api/agent/workflow-uploads/batch/; POST /api/agent/workflow-uploads/recognize/; GET /api/agent/workflows/active/。
- Change type: 新增接口；已有单文件上传、工作流详情及取消响应不变。
- OpenAPI change: AgentWorkflowBatchResult、AgentWorkflowRoleResult、AgentActiveWorkflow；角色枚举、类型校验、逐份错误及跨项目本人摘要边界。
- Mock examples: mock/prism/examples/104-agent-upload-bundle.json，响应状态键仅使用小写字母数字和 `-_`。
- Frontend reason: 多资料与总ZIP上传后自动识别并供人工核查；可定位及取消挡路任务。
- Backend implementation notes: 安全解包最多512条目、总解压上限min(uploadMaxMb,512MiB)，每批最多12份；同目录同名Shapefile归组；模型无效或不可用退回规则。仅本人跨项目摘要，详情和取消仍按目标项目原权限校验。
- Verification: 解包安全、部分失败、批次上限、角色校验和规则退回、本人摘要隔离；前端上传、角色修改、取消确认、思考控件与固定场景惰性加载。
- Result: 本机相关后端81项、前端单元542项、TypeScript与契约检查通过；新增浏览器回归因沙箱Chromium启动权限未能执行。未部署服务器，真实模型与公网首开耗时未验收。

## API-20261104-002 - 超级管理员创建用户和修改登录名

- Status: BackendReady
- Owner: root 契约；workspace_privacy 后端；logout_frontend 后台表单。
- Endpoints: POST /api/users/、/api/users/{userId}/；复用 /api/projects/ 可分配项目与 /api/projects/assignments/{userId}/ 规则。
- Change type: UserCreateRequest邮箱改条件必填，新增仅超管projectIds/allowPublicProject；UserUpdateRequest增加username，UserInfo增加canRenameUsername。
- OpenAPI change: 超管邮箱选填、创建时配置启用项目，已有账号可改名；普通管理员保持限制。无配置默认公开，关闭公开须分配私有项目；系统专用账号保护。
- Mock examples: 后端隔离账号与浏览器创建表单fixtures；初始密码仍复用原一次性生成响应。
- Frontend reason: 超级管理员一次创建并分配用户可见项目，不需要先创建再去项目管理设置。
- Backend implementation notes: 复用项目分配校验；用户、角色、资料、成员关系原子保存，无数据库迁移；密码单向哈希不增加可逆存储。
- Verification: 超管无邮箱、多无邮箱、非空邮箱唯一性、普通管理员保持限制、项目有效性和原子失败、创建后访问范围；改名唯一性/保留名/关系及密码保持。
- Result: 后端135项与7个子测试、后台57项浏览器回归通过；契约、类型和构建核验，候选及正式验收另记。

## API-20261104-001 - 工程默认私有与接受分享只读

- Status: BackendReady
- Owner: root 契约和前端文案；workspace_privacy 后端及权限回归。
- Endpoints: GET/POST /api/catalog/workspaces/*；GET/POST /api/admin/workspaces/*；工程搜索；专题来源工程；/api/sharing/*。
- Change type: 收紧工程对象权限，保持请求、响应和数据库结构。
- OpenAPI change: 工程默认创建者私有，接受邀请只读，普通管理员不绕过，超级管理员保留当前项目管理；直接ID未授权404。
- Mock examples: 复用现有工程结构，后端隔离测试覆盖同项目多账号和真实邀请状态。
- Frontend reason: 用户保存的工程不自动暴露给同项目成员，页面说明与分享机制一致。
- Backend implementation notes: 集中工程访问判定，统一列表、搜索、后台、详情及来源快照路径；邀请待接受/拒绝不授权，已接受每次重验项目、双方和依赖；写入仅所有者或超管。
- Verification: 同项目隔离、直接ID、普通管理员、分享接受/拒绝/撤权、来源工程入口与现有专题回归。
- Result: 后端92项及前端106项定向浏览器回归通过，类型/格式/契约一致性和生产构建通过；候选及正式验收另行记录。

## API-20261102-001 - 普通对话账号三任务并发

- Status: BackendReady
- Owner: root；roles_monitor后端；agent_layout_modes前端。
- Endpoints: POST /api/agent/conversations/{conversationId}/runs/；POST /api/agent/runs/{runId}/interaction/；计算完成后的原任务恢复。
- Change type: 调整现有任务名额和冲突语义，保持请求与响应结构。
- OpenAPI change: 提交说明明确同账号快速与科研对话合计三条，同会话串行，账号名额满返回409，全站队列和每日额度返回429。
- Mock examples: 沿用现有AgentRun与ErrorResponse结构，HTTP模型fixture验证并发与恢复。
- Frontend reason: 多窗口和模式可独立提交，瞬时连接失败不再清空权限和历史。
- Backend implementation notes: 移除账号单活动任务唯一索引，保留会话唯一索引；提交与恢复在同一队列锁事务中核对名额，等待状态释放模型名额，幂等和取消保留。
- Verification: 三条混合模式任务、第四条冲突、同会话串行、跨账号与项目、等待恢复、真实并发抢位，以及权限错误与网络失败的独立状态。
- Result: 本地目标验证完成后进入独立候选与正式验收。

## API-20261025-001 - 地质完整对比与隔离独立评价

- Status: ContractReady
- Owner: haide_story前端与契约；root后端及数据；evaluation独立评价。
- Endpoints: GET /api/agent/workflows/{workflowId}/；GET /api/agent/workflows/{workflowId}/validation/；GET /api/agent/workflows/{workflowId}/validation/files/{fileKey}/preview/、download/。
- Change type: 现有地图资源增加可选改前交汇和矿物引用；新增隔离只读独立评价及文件访问。
- OpenAPI change: AgentMultiElementMap.beforeIntersections/beforeAlterations；AgentWorkflowValidation/Section/File；预览复用AgentWorkflowReportPreview。
- Mock examples: mock/prism/examples/102-agent-validation.json，仅为空评价可用性样例，不充当实测结论。
- Frontend reason: 两案例任务对比组完整保留改前、改后与修改范围；海德章节可核对交汇前后及展开独立评价。
- Backend implementation notes: 沿用当前项目、本人或管理工作流授权；独立评价不进入plan、模型、知识检索或正常算法输入。文件键来自受控清单，每次核验SHA256/大小/来源，下载额外验证数据导出权限；读取不创建新成果。
- Verification: 无评价200明确状态；跨项目/越权/路径/校验漂移拒绝；独立参考隔离；真实表格、文件预览下载及两案例工作台去重恢复。
- Result: 契约完成，后端与前端实现及必要检查进行中。

## API-20261023-001 - 海德乌拉多要素推理和试用规则

- Status: BackendReady
- Owner: multi_frontend 契约与地图；multi_workflow 持久流程与批准；multi_algorithms 隔离算子。
- Endpoints: GET /api/agent/research-demos/；POST /api/agent/workflows/；GET /api/agent/workflows/{workflowId}/；POST /api/agent/workflows/{workflowId}/confirm/；GET /api/compute/algorithms/。
- Change type: 扩展场景及建议字段，沿用统一端点、会话鉴权、原单项目和本人授权。
- OpenAPI change: geology_multi_element_reasoning；parameters.segment=all/lithology/structure/alteration；九类明确输入；plan.multiElementMap和trialRuleBindings；multi_element建议、实测值、条件、例外及具体规则版本引用。
- Frontend reason: 综合入口和三个分段共用持久任务，线点面双图与证据链可核对；明确上游版本和本案例试用性质。
- Mock examples: 新组件浏览器场景及隔离本机实际数据验证，不用交付包PNG代替运行结果。
- Backend implementation notes: 仅当前项目、当前场景、显式绑定条目及修订读取draft试用知识；普通知识检索权限不变。批准只传selectedSuggestionIds，后端重验快照和动作。未批准、待裁定、降权和剔除分开存储。算法发现与执行按稳定项目编码统一筛选相关共享工具及本项目登记工具；公开目录和历史任务读取不变。
- Verification: 旧案例不变；不同segment和输入影响计划；批准范围绑定；真实新图层和地图证据吻合；空输出正常显示。
- Result: 契约与生成类型已同步；前端角色、批准及线点面浏览器验证通过。本机四项1.0.1算法经真实试运行发布，完整工作流的五个真实计算任务及批准、报告预览下载通过；模型连接未恢复，模型判断仍单列为模拟验证。真实地图读取完整矢量，按需加载密集检查与矿物图层，改前矿物取检查输出、改后取获批处理输出。


## API-20261021-001 - 地质工作流预设与输入角色校验

- Status: BackendReady
- Owner: root 契约/预设；workflow_form 表单；cover_animation 后端角色校验。
- Endpoints: GET /api/compute/inputs/；GET /api/agent/research-demos/；POST /api/agent/workflows/；POST /api/agent/workflows/{workflowId}/cancel/。
- Change type: 扩展候选格式及当前项目活动预设；计划创建前验证地质输入。
- OpenAPI change: ComputeCandidate.fileFormat；AgentResearchDemoList.items[].preset（仅当前项目返回），含inputs和parameters；cancel可选replacePlanHash和400/409错误。
- Frontend reason: 预设按钮恢复实际活动资源，名称匹配可以重新选择，三个输入角色按真实字段和几何过滤；编辑输入后不能执行旧计划。
- Mock examples: 复用101-agent-research-demo与隔离数据库/浏览器样例，实际角色读取测试不以固定名称替代格式校验。
- Backend implementation notes: 当前项目预设依稳定code解析且继续校验可见性；其他项目不返回输入标识；地质图/范围需实际面几何、坐标系及各自必要字段，规则需结构化表字段，开始前报出具体角色错误；执行阶段保留完整文件与空间检查。
- Verification: 修改后预设恢复、名称匹配覆盖、歧义与缺资料反馈、候选分页、角色不互串、错误输入无任务副作用、计划变化重新生成、真实知识/算法依据。
- Result: 已实现；输入校验、知识引用及报告、预设发现测试通过，前端和真实模型/服务器验收分别记录。

## API-20261020-001 - 页面关闭后的登录生命周期

- Status: BackendReady
- Owner: portal_ui_cleanup，登录与认证前后端统一实现。
- Endpoints: POST /api/auth/browser-session/；POST /api/auth/login/、guest-login/、register/ 与 GET /api/auth/me/ 的页面登录生命周期。
- Change type: 增加页面租约；remember 保留为废弃输入且不再启用持久登录。
- OpenAPI change: BrowserSessionRequest/Response，start/resume/heartbeat/suspend/abandon动作。
- Frontend reason: 所有角色关闭最后平台页面后重开需登录，正常刷新及仍在线的多标签可续接。
- Mock examples: 使用真实Django Session、受控时钟与隔离浏览器验证，不写入业务数据。
- Backend implementation notes: 复用Django Session存储随机令牌摘要及各页面租约；页面退出挂起，20秒刷新续接，30秒心跳/120秒失联边界；下载和瓦片沿用Cookie并校验租约。
- Verification: 普通/超级用户、游客、刷新、多标签、浏览器会话恢复、Cookie重放、失联过期和匿名公开读取。
- Result: 本机真实login/start/suspend/resume、原始超级用户、游客、Cookie重放、失联、CSRF及既有认证权限回归54项通过；浏览器生命周期、API客户端及登录页33项通过，包含HTTP兼容随机数、刷新、多标签交接和浏览器恢复拒绝旧存储。契约已生成，统一API/类型/构建与候选发布由本轮总验收记录。

## API-20261016-002 - 普通智能体原任务交互与历史计算结果清理

- Status: ContractReady
- Owner: root 契约/智能体前端；generic_interaction_backend 任务恢复；historical_result_cleanup 删除服务/目录；ecology_knowledge_ingestion 审核资料接入。
- Endpoints: POST /api/agent/runs/{runId}/interaction/；GET /api/agent/runs/{runId}/；POST /api/catalog/resources/delete-preview/；POST /api/catalog/resources/delete/；GET /api/compute/tasks/{taskId}/。
- Change type: 新增同任务问题卡和删除影响预览，扩展等待状态与历史删除凭证。
- OpenAPI change: AgentInteraction/Question/Answer/Update；AgentRun.interaction/interactionHistory 与 waiting_input/waiting_review/waiting_compute；事件 interaction/continuation；interaction 成功响应按原任务当前状态区分 queued 返回202、其余返回200，正文均为 AgentRun；ResourceDeletePreviewRequest/Item/Response、historyConfirmationToken、ComputeOutput.importStatus=deleted，计算输入可含已删除资源凭据。
- Frontend reason: 普通对话中回答后续执行，刷新恢复并准确显示等待；清理历史计算结果前说明影响，保留具名历史。
- Mock examples: 由隔离数据库、浏览器问题卡、真实模型与真实算法链验证，不将固定对白视为模型验收。
- Backend implementation notes: 问题修订和提交键原子校验，等待释放执行资源；普通模型对话只有澄清权限；历史清理限计算结果，运行中任务、有效成果/地图及隐私保护继续生效，签名凭证绑定用户/项目/引用快照。
- Verification: 待回答恢复、单次提交与取消、参数影响真实计算、审核拒绝/批准；删除确认、活动保护、跨项目/隐私/快照变化和历史凭据；生态资料幂等入库及真实引用。
- Result: 本机后端交互、删除和生态导入定向测试通过；问题卡及页面回归进行中，真实模型与候选发布验收另行记录。

## API-20261016-001 - 智能体研究额度调整

- Status: BackendReady
- Owner: thinking_limits；root 协调目录统计与部署。
- Endpoints: GET/PUT /api/agent/admin/；GET /api/agent/bootstrap/；POST /api/agent/conversations/{conversationId}/runs/；POST /api/agent/workflows/。
- Change type: 放宽既有策略数值范围，保持字段与类型。
- OpenAPI change: AgentPolicy/AgentQuota 每日次数、工具步骤、详细资源数允许0表示不限；其余研究预算移除固定档位上界，实际模型窗口及安全校验保留；AgentBudgetPreset/Limit/Choice 同步范围。
- Frontend reason: 管理员可按研究需要调整额度，并取消次数、步骤与资源数量额度；显示模型未返回思考内容的真实状态。
- Mock examples: 以策略验证、真实HTTP模型替身及浏览器回归验证，响应结构未变。
- Backend implementation notes: 0直接短路数量限制；正数按原方式生效。保留权限、项目、隐私、批准写入、模型容量、并发和附件大小保护。
- Verification: 策略保存、0额度与正数收窄、真实窗口校验、深度流解析、类型生成及浏览器显示。
- Result: 后端策略、预算、协议与HTTP思考回归44项通过；浏览器思考显示2项通过；类型生成与类型检查通过，实际服务A/B验证确认JSON约束压制Qwen思考。发布验证另由回执记录。

## API-20261014-001 - 数据目录批量永久删除与人工审核反馈

- Status: BackendReady
- Owner: catalog_delete_backend 契约/删除服务；catalog_files_ui 目录；workflow_feedback 人工审核。
- Endpoints: POST /api/catalog/resources/delete/; POST /api/admin/data/resources/{id}/; POST /api/agent/workflows/{workflowId}/confirm/; POST /api/raster/render/async/; POST /api/catalog/export/async/; GET /api/raster/jobs/{job_id}/。
- Change type: 新增批量删除接口，扩展现有审核请求。
- OpenAPI change: ResourceBulkDeleteRequest/Response/Item；AgentWorkflowConfirmation 增加 decision 与 feedback；RasterJobInputReferences 保存运行中渲染/导出的精简输入引用。
- Frontend reason: 目录多选真实删除并逐项说明引用阻塞；审核用户可批准、拒绝并返回意见。
- Mock examples: 由后端临时存储集成测试与前端浏览器拦截样例验证，不新增第二份契约。
- Backend implementation notes: 单项目、删除功能权限及 owner_only 边界；保留任务/成果/工程/科研引用、共享存储及外部原始文件。正在渲染/导出的输入标识先持久化再提交，排队及处理中阻止删除，终态解除此临时保护。审核重新验证本人、原项目、当前计划哈希；拒绝只在 waiting_approval 停止后续，意见持久化并保留已有成果。
- Verification: 实际SQLite/GPKG/文件删除、部分成功、权限、跨项目、隐私、引用保护；审核通过/拒绝/意见保存与刷新；生成类型一致性。
- Result: 本机隔离存储删除、既有后台/导出及raster接口和持久化回归94项、16个参数子测试通过；API生成/lint/一致性及前端类型检查通过。真实删除仅在临时测试目录和测试数据库中进行，服务器验证由发布回执记录。

## API-20261012-001 - 真实地质材料案例与成果数据关联

- Status: ContractReady
- Owner: geology_platform_paths 契约与前端；root 编排、成果关联及验收。
- Endpoints: /api/agent/research-demos/; /api/agent/conversations/{conversationId}/runs/; /api/agent/workflows/; /api/catalog/results/; /api/catalog/results/{resultId}/。
- Change type: 新增地质时代纠偏场景枚举与可读成果数据关联，沿用既有接口。
- OpenAPI change: geology_age_correction；sampleNature 增加 real_map_with_demonstration_errors；成果创建及publish可选resourceIds，响应relatedResources。
- Mock examples: mock/prism/examples/101-agent-research-demo.json；成果关联由浏览器与后端权限测试验证。
- Frontend reason: 保留原两个模拟入口，新增真实图件副本上的少量时代录入纠偏；成果详情可打开对应地图或数据表。
- Backend implementation notes: 三阶段检查、受约束编辑、复查；论文及辞书依据保留适用范围；精修和设错清单独立验收。成果关联限同项目可读资源，撤权及owner_only不可见项不序列化，省略更新字段保留原关联。
- Verification: 三入口导航、手选资料、算法参数、公开判断标题、地图前后对比、成果关联及权限过滤；类型生成与必要浏览器检查。
- Result: 本轮开发；真实算法和服务器验证由交付回执记录。

## API-20261011-001 - 自然语言科研案例与在线澄清

- Status: ContractReady
- Owner: chat_demo_frontend 契约与界面；chat_demo_backend 模型解析与持久关联；root 授权案例目录及发布。
- Endpoints: GET /api/agent/research-demos/; POST /api/agent/conversations/{conversationId}/runs/; POST /api/agent/runs/{runId}/research-intent/; AgentRun。
- Change type: 新增授权案例目录与持久科研意图接口。
- OpenAPI change: 可选 demoScenario 与 researchIntent；答案返回202后续模型解析运行，审核/取消返回200；以 originRunId、revision 和 workflowId 保存真实关联。知识 auto 按本轮主题及已授权科研会话上下文筛选。
- Frontend reason: 成果展示一键进入独立智能体会话，必要时在线回答问题，自动展示判断、计算、报告和地图，刷新恢复已有任务。
- Mock examples: mock/prism/examples/101-agent-research-demo.json。
- Backend implementation notes: 仅本人原项目；每次重新授权；相同修订与答案幂等；用户变更预设由真实模型解析；几何审核仍需明确确认。auto 续接同用户、项目、会话的已授权科研工作流及实际知识依据，manual/none 与手选数据、算法继续限定调用范围。
- Verification: 项目授权、答案及冲突、重复提交、旧会话隔离、刷新不重复启动、在线澄清、真实工作流成果展示与窄屏。
- Result: 本轮开发，服务器是否生效以冻结验收回执为准。

## API-20261010-002 - 计算结果目录分类

- Status: BackendReady
- Owner: Root契约；result_classification_backend后端；catalog_ui_paths及unified_compute_forms前端。
- Endpoints: /api/data-schema/summary/; /api/catalog/resources/; /api/admin/data/resources/; /api/compute/outputs/{outputId}/import/。
- Change type: 既有目录节点与入库归类语义，HTTP字段形状保持。
- OpenAPI change: 三类目录、taxonomyVersion=2026.10、compute_results不可用于普通上传，已入库结果路径包含计算结果。
- Mock examples: mock/prism/examples/45-domain-schema.json。
- Frontend reason: 区分上传数据与已入库成果，同时保持地图能力和参数表单一致。
- Backend implementation notes: 内部结果标记由入库维护；历史根据真实ComputeImport关联并核对项目回填，保留权限、状态和原始文件。
- Verification: 五类输出入库、历史保留、跨项目及隐私、普通上传拒绝结果类别、两入口参数控件和窄屏。
- Result: 待候选与正式验收。

## API-20261010-001 - 知识领域与持久工具选择

- Status: BackendReady
- Owner: knowledge_backend（后端及明确授权契约）；knowledge_frontend（界面）；root（来源种子与发布）。
- Endpoints: /api/knowledge/entries/; /api/knowledge/documents/; /api/knowledge/documents/{documentId}/; /api/knowledge/documents/search/; /api/knowledge/wiki/; /api/agent/bootstrap/; /api/agent/conversations/{conversationId}/runs/。
- Change type: 领域字段与过滤；每轮工具选择字段；资料分类接口。
- OpenAPI change: KnowledgeDomain、KnowledgeDomainOption、AgentKnowledgeSelection、AgentAlgorithmOption与关联请求/响应；生成类型已同步。
- Mock examples: mock/prism/examples/96-agent.json; 98-knowledge-workflow.json; 99-knowledge-library.json; 100-agent-compute-intent.json。
- Frontend reason: 按四个主题查知识，显式选择知识、算法和数据，刷新会话后恢复选择。
- Backend implementation notes: 领域独立于项目权限；读取/搜索/Wiki/计算卡/执行服务端限定；none排除旧知识上下文；旧正文和来源保留。
- Verification: 知识与智能体全部相关188项通过；新增边界与多版本选择复验由root记录；契约lint、生成一致性、Prism与迁移检查通过。
- Result: 后端实现就绪，正式发布以本轮冻结候选及服务器回执为准。

## API-20261004-001 - 文档检索、自动Wiki与计算质量门控

- Status: Verified
- Owner: Root契约/前端；WeKnora子任务后端；几何子任务计算执行与门控。
- Endpoints: /api/knowledge/documents/; /api/knowledge/documents/{documentId}/retry/; /api/knowledge/documents/search/; /api/knowledge/wiki/; ComputeManifest。
- Change: 增加文档上传、状态、混合检索、自动Wiki及来源关系；manifest新增qualityReport声明。
- Frontend reason: 用户可直接积累资料、查原文、读自动Wiki；需要复核的计算结果暂停自动入库。
- Mock examples: mock/prism/examples/99-knowledge-library.json。
- Backend notes: 主平台鉴权，项目/本人空间分开索引与合成，原始文档保留；报告校验与入库时双重检查。
- Verification: 本地知识后端41项、智能体集成69项通过；开发候选的真实资料检索、Wiki、前端浏览器和几何计算已验证。正式发布另以冻结提交的候选与生产回执为准。

This document is the frontend-to-backend handoff queue for API contract changes.

Frontend owns `docs/openapi.yaml` and `mock/prism/examples/*.json`. Whenever frontend changes an endpoint, response field, request body, status code, permission behavior, or mock example that requires backend implementation, add or update one API change entry here. Backend uses these entries to update Django behavior and tests.

## Status Definitions

- `Proposed`: Frontend has identified a requirement, but the contract or mock example may still be incomplete.
- `ContractReady`: `docs/openapi.yaml`, generated API types, and mock examples are ready for backend implementation.
- `Implementing`: Backend is implementing the contract.
- `BackendReady`: Backend implementation and backend tests are complete.
- `Verified`: Frontend has verified the real backend against the contract.
- `Blocked`: Contract, implementation, data, or permission behavior needs a decision before continuing.
- `Superseded`: Replaced by a later API change request.

## API Change Status Matrix

### API-20260924-002 — 用户思考强度

Status: BackendReady。本任务依次完成契约、后端、前端三个职责：bootstrap 增加 `defaultReasoningEffort`，运行提交增加可选 `reasoningEffort`；仅深度模式允许 `low/medium/xhigh`，优先于后台和预算默认值。数据库迁移 `0010_user_reasoning_effort`；worker 上下文计数和生成使用同一强度。HTTP 模型捕获、接口校验与两种模式浏览器交互测试通过。真实远端模型尚未联调。

| ID | Status | Endpoint | Change Type | OpenAPI | Mock | Backend | Tests | Notes |
| API-20261108-004 | BackendReady | Resource query/profile/tiles and workspace | Stable map restore and structured display warnings | Updated | Scoped fixtures | Implemented | Scoped regression and actual browser | Original data and ACL preserved |
| API-20261108-003 | BackendReady | Resource profile / workspace / output map preview | Shared color policy and live bindings | Updated | Existing fixtures | Single source implemented | Canonical table edit regression | Read-only display projection |
| API-20261108-002 | BackendReady | AgentRun / AgentPolicy | Personal map actions | Updated | Real GIS fixtures | Implemented | Scoped worker and browser checks | Original data read-only |
| API-20261108-001 | BackendReady | /api/auth/browser-session/ | Recover live pages and join online sessions without global logout | Updated | Real Session and controlled clock | Implemented | Backend and browser regression | Existing Cookie, CSRF, account and project authorization |
| API-20261107-003 | BackendReady | Pipeline display LOD and gzip |
| API-20261107-002 | BackendReady | Workflow cancel and research inputSummary | Immediate stop and actual role reasons | Updated | Existing 105/106 optional compatible fixtures | Owner/project and bound task stop; model role audit | Targeted tests; real candidate separately | Current data and prior report versions preserved |
| API-20261107-001 | BackendReady | /api/agent/workflows/{workflowId}/retained-review/; workflow inspection/confirm | Explicit held-object review with fixed automatic scope | Updated | 105-agent-workflow-card.json | Implemented with owner/project and frozen evidence checks | Focused backend/browser checks; candidate separate | Previous reports preserved; budgets and permissions retained |
| API-20261106-005 | BackendReady | /api/agent/workflows/{workflowId}/confirm/ | Optional explicit start with input confirmation | Updated | 107-agent-input-start.json | Bound input authorization implemented | Targeted backend and browser regression | Modification and exceptional-case approval retained |
| API-20261106-004 | BackendReady | /api/catalog/resources/; /search/; /layers/; /compute/inputs/; shared admin catalog and counts | Hide explicitly marked internal packets from ordinary catalogs | Updated | Existing catalog examples; scoped source/code fixtures | Shared constants and catalog filters implemented | 78 focused cases including 26 new boundary cases; API checks passed | Bound ID access retained; agent provenance remains stricter |
| API-20261106-003 | BackendReady | /api/agent/resources/; /bootstrap/; /workflow-uploads/references/; existing tools and workflow material access | Ordinary discovery separated from real task-bound materials | Updated | Existing agent examples; scoped data-boundary fixtures | Backend focused and frontend 6 browser cases passed | TypeScript and API checks passed; real-model/server acceptance separate | Current project ACL, provenance, owner and real task bindings |
| API-20261106-002 | BackendReady | /api/agent/runs/{runId}/; /conversations/{conversationId}/; /workflows/{workflowId}/ | Real final-answer preview and persisted lightweight model activity | Updated | 105-agent-workflow-card; 106-agent-generic-chat | Implemented | Scoped browser, typechecks and API checks | Existing owner, project and workflow authorization |
| API-20261106-001 | BackendReady | /api/agent/bootstrap/; /conversations/{conversationId}/runs/; /workflows/; /workflow-uploads/recognize/ | Explicit deep default and verified run policy inheritance | Updated | Existing agent fixtures; scoped HTTP model captures | Implemented | Focused frontend and backend regression; API checks | Existing project, owner, model and budget authorization |
| API-20261105-014 | BackendReady | /api/agent/workflows/{workflowId}/; /confirm/ | Raster groups, compact approval and element pages | Updated | 105-agent-workflow-card.json | Implemented | Focused regression; browser cases prepared | Existing owner/project/resource authorization |
| API-20261105-013 | BackendReady | /api/agent/workflows/{workflow_id}/ | Model attempt audit response | Updated | Backend fixtures | Implemented | Focused backend tests; browser cases prepared | Existing workflow authorization |
| API-20261105-011 | BackendReady | /api/catalog/resources/{id}/query/ | Shared-boundary grid quantization without simplification | Updated | 30-catalog-vector.json; backend geometry fixtures | Implemented | Focused unit tests; browser cases prepared | Storage, permissions and precise queries unchanged |
| API-20261105-012 | BackendReady | /api/catalog/resources/{id}/profile/ | All-category model color advice and class provenance | Updated | 30-catalog-vector.json | Implemented | Focused color and shared-style tests | No permission or data-path change |
| API-20261104-008 | BackendReady | /api/agent/workflows/{workflowId}/; /api/catalog/resources/{id}/query/ | groupId and displayGeometry | Updated | 105-agent-workflow-card.json; 30-catalog-vector.json | Implemented | Focused regression | Per-object approval, immutable source geometry, original permissions |
| API-20261105-009 | BackendReady | /api/agent/workflows/active/; confirm/; resume/ | Compute slots and parked summaries | Updated | 104-agent-upload-bundle.json | Implemented | Focused regression | Parked tasks coexist; explicit conflict retains checkpoint |
| API-20261105-010 | BackendReady | /api/agent/workflows/{workflowId}/; confirm/ | Frozen candidates for explicit user adjudication | Updated | 105-agent-workflow-card.json | Implemented | Focused regression | Rule status preserved; model cannot adjudicate |
| API-20261104-007 | BackendReady | /api/agent/workflow-uploads/references/; /api/agent/logic-configuration/; /api/agent/conversations/{conversationId}/runs/; /api/agent/runs/{runId}/research-intent/ | Paginated catalog and user/project-owned confirmed configuration | Updated | 104-agent-upload-bundle.json; 107-agent-logic-configuration.json | Implemented | Backend 104 and unit 554 passed; browser sandbox-blocked | Reauthorize references; never reuse plan or disposition approval |
| API-20261104-006 | BackendReady | /api/agent/workflow-uploads/references/ | Catalog references in upload batches | Updated | 104-agent-upload-bundle.json | Implemented | Historical focused regression | Resource privacy unchanged |
| API-20261104-005 | BackendReady | /api/agent/conversations/{conversationId}/runs/; /api/agent/runs/{runId}/research-intent/ | Generic geology in current chat | Updated | 106-agent-generic-chat.json | Implemented | Historical focused regression | Explicit confirmation required |
| API-20261104-004 | BackendReady | /api/agent/workflows/{workflowId}/; /api/compute/outputs/{outputId}/preview/ | Card projection and map preview | Updated | 105-agent-workflow-card.json | Implemented | Historical focused regression | Owner and project isolation unchanged |
| API-20261104-003 | BackendReady | /api/agent/conversations/{conversationId}/runs/; /api/agent/runs/{runId}/research-intent/ | uploadBatchId and explicit generic answers | Updated | 106-agent-generic-chat.json | Implemented | Backend confirmation and isolation passed, unit 550; browser sandbox-blocked | Existing workflow approval and project/owner checks preserved |
| API-20261104-002 | BackendReady | /api/agent/workflows/{workflowId}/; /api/compute/outputs/{outputId}/preview/; /api/catalog/resources/{id}/profile/ | card view, vector map view, defaultVisualization | Updated | 105-agent-workflow-card.json; 30-catalog-vector.json | Implemented | Backend 122, unit 550; browser sandbox-blocked | Full view unchanged; project and owner checks preserved |
| API-20261104-001 | BackendReady | /api/agent/workflow-uploads/batch/; /recognize/; /api/agent/workflows/active/ | batch uploads, role suggestions, active task summary | Updated | 104-agent-upload-bundle.json | Implemented | Backend 81, unit 542, types and contract passed; browser sandbox-blocked | Existing responses unchanged; target-project authorization preserved |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| API-20261104-002 | BackendReady | POST /api/users/ 及单用户更新 | 新增输入及条件校验 | Updated | Existing fixtures | Implemented | Focused passed | 超管无邮箱创建、分配项目与改登录名 |
| API-20261104-001 | BackendReady | 工程、工程管理、搜索和分享 | 权限行为收紧 | Updated | Existing fixtures | Implemented | Focused passed | 默认私有，接受后只读，普通管理员不绕过 |
| API-20261103-002 | BackendReady | /api/projects/; /api/projects/assignments/{userId}/; /api/agent/workflows/; /api/agent/research-demos/ | per-user public scope and lightweight workflow history | Updated | Scoped backend and browser fixtures | Implemented | Project/sharing 72; project UI 6 passed | Default true, live authorization, authorized fallback and summary pagination; server acceptance separate |
| API-20261103-003 | BackendReady | /api/agent/workflow-uploads/; /api/agent/workflow-uploads/{uploadId}/; /api/agent/workflows/; /api/agent/workflows/{workflowId}/confirm/ | task uploads, geology_generic and field-mapping confirmation | Updated | 103-agent-generic-workflow.json | Implemented | Generic 9 backend, 2 browser; local mock end-to-end succeeded | Uploads owner_only and bound once; mapping proposed by model and confirmed by user |
| API-20261103-004 | BackendReady | /api/catalog/results/{resultId}/file/; /api/catalog/map-compositions/{compositionId}/versions/{versionNumber}/file/ | thumbnail variant and thumbnailUrl for result cards | Updated | Backend tests | Implemented | Thumbnail tests | WebP ≤640px cached under app cache; PDF keeps placeholder |
| API-20261103-001 | BackendReady | /api/sharing/check/; /api/sharing/invitations/; invitations/{id}/respond/; read/; open/ | exact username invitation and single-object read-only access | Updated | Sharing browser and backend fixtures | Passed | Backend 62; sharing browser 15; response unit 13 passed | Permission checks, accept/decline, notification and single-output isolation verified; release acceptance tracked separately |
| API-20261102-001 | BackendReady | /api/agent/conversations/{conversationId}/runs/; /api/agent/runs/{runId}/interaction/ | account admission and conflict semantics | Updated | Existing run/error fixtures | Passed | Focused passed | Three ordinary tasks; permission and transient failure states separated |
| API-20261025-001 | ContractReady | /api/agent/workflows/{workflowId}/validation/; validation/files/*; workflow map fields | isolated read-only evaluation and before-layer references | Updated | 102-agent-validation | Pending | Pending | Implementation in progress |
| API-20261023-001 | BackendReady | /api/agent/research-demos/; /api/agent/workflows/; /confirm/; /api/compute/algorithms/ | multi-element scenario, trial rule bindings, measured suggestions, real map outputs and project tools | Updated | Integration/browser fixtures | Passed | Focused browser, unit and real local workflow passed | Real algorithms and maps verified; model decisions use mock, recorded separately |
| API-20261021-001 | BackendReady | /api/compute/inputs/; /api/agent/research-demos/; /api/agent/workflows/; /cancel/ | current-project preset, actual input-role checks and conditional replacement | Updated | Integration/browser fixtures | Implemented | Focused verification | Preserve permissions; metadata before plan and complete runtime validation |
| API-20261020-001 | BackendReady | /api/auth/browser-session/; login/; guest-login/; register/; me/ | browser page leases and session lifecycle | Updated | HTTP/browser fixtures | Passed | 54 backend; 33 browser passed | 20-second refresh; 120-second lost-contact expiry; release acceptance separate |
| API-20261016-002 | ContractReady | /api/agent/runs/{runId}/interaction/; /api/catalog/resources/delete-preview/; resources/delete/ | persisted questions; confirmed history cleanup | Updated | HTTP/browser fixtures | Focused passed | In progress | Real model, compute and release acceptance recorded separately |
| API-20261016-001 | BackendReady | /api/agent/admin/; bootstrap/; conversations/{id}/runs/; workflows/ | configurable research quotas and manual selection | Updated | HTTP/browser fixtures | Passed | Focused passed | Actual model window and safety guards retained; deployment separate |
| API-20261014-003 | BackendReady | /api/agent/workflows/; /api/agent/workflows/{workflowId}/confirm/ | knowledge query; selected modification approval | Updated | Browser/integration fixtures | Passed | Focused passed | Persistent proposals and exact approved scope; real-model release validation separate |
| API-20261014-001 | BackendReady | /api/catalog/resources/delete/; /api/agent/workflows/{workflowId}/confirm/ | guarded bulk deletion; approve/reject feedback | Updated | HTTP/browser fixtures | Passed | Focused passed | Isolated real storage tests; no live business deletion |
| API-20261012-002 | BackendReady | /api/agent/workflows/{workflowId}/pause/; resume/; report/* | persistent MD reports and resumable pause | Updated | HTTP/browser fixtures | Passed | Focused passed | Real files and safe checkpoints; publication pending |
| API-20261012-001 | ContractReady | /api/agent/research-demos/; /api/catalog/results/ | real-map age correction; authorized result links | Updated | Updated | In progress | Pending | Original synthetic cases preserved; injected errors clearly labelled |
| API-20261011-001 | ContractReady | /api/agent/research-demos/; /api/agent/runs/{runId}/research-intent/; AgentRun | natural language demo and online clarification | Updated | Updated | In progress | Frontend focused passed | Real backend and candidate validation pending |
| API-20261010-003 | BackendReady | /api/agent/workflows/; /api/agent/workflows/{workflowId}/confirm/ | evidence decisions; multi-stage scenarios; observational updates | Updated | HTTP/browser fixtures | Passed | Focused passed | Local real compute; mock decisions separately labelled; remote deployment separate |
| API-20261010-002 | BackendReady | /api/data-schema/summary/; /api/catalog/resources/; /api/admin/data/resources/; /api/compute/outputs/{outputId}/import/ | compute result classification | Updated | Updated | Passed | Focused passed | Exact historical import links; candidate publication pending |
| API-20261010-001 | BackendReady | /api/knowledge/*; /api/agent/bootstrap/; /api/agent/conversations/{id}/runs/ | domain filters; persistent tool selection | Updated | Updated | Passed | Focused passed | Server-enforced selectors; candidate publication pending |
| API-20261009-001 | BackendReady | /api/agent/runs/{runId}/compute-intent/; /api/compute/outputs/{outputId}/map-preview/ | persistent plan; authorized preview | Updated | Added | In progress | Pending | Real execution and user-controlled import |
| API-20261004-001 | Verified | /api/knowledge/documents/; /api/knowledge/wiki/; ComputeManifest | document retrieval; automatic Wiki; quality gate | Updated | Added | Passed | Passed | Real development candidate; project and owner scopes isolated |
| API-20260924-001 | Verified | /api/agent/admin/; /api/agent/bootstrap/; /api/agent/conversations/{id}/runs/ | role ceilings; task budgets; usage | Updated | HTTP model fixtures | Passed | Passed | Local browser; backend request capture; v0.1.15 |
| API-20260922-001 | Verified | /api/agent/*; /api/compute/algorithms/ | generation controls; stable order | Updated | HTTP model fixtures | Passed | Passed | v0.1.13 server receipt; actual token accounting and two published algorithms |
| API-20260920-002 | Verified | `DELETE /api/compute/algorithms/{algorithmId}/` | management operation | Updated | Updated | Implemented | Passed | Deletes registrations without task history and protects algorithms referenced by task history |
| API-20260919-001 | Verified | /api/compute/* | generic algorithm registry and durable compute | Updated | Added | Passed | Passed | 应用/worker/真实Linux容器/浏览器端到端验收通过 |
| API-20260918-006 | Verified | 工程、内容附件、底图代理 | concurrency; pagination; staged assets; basemap | Updated | Updated | Implemented | Passed | A01–A14 整改，详见 2026-09-18-a-items-acceptance.md |
| API-20260918-005 | Verified | 制图底图瓦片 | purpose/export + 503 | Updated | Updated | Implemented | Passed | 禁止制图静默使用简化背景 |
| API-20260918-004 | Verified | 项目上下文、公共内容 | single project; public news | Updated | Updated | Implemented | Passed | 公开标签与平台团队动态 |
| API-20260918-003 | Verified | 表格/矢量/栅格/成果上传 | required project header | Updated | Updated | Implemented | Passed | 上传页面独立选择所属项目，服务端强制授权 |
| API-20260618-001 | Superseded | Non-geographic analytics workspace | endpoint design paused | Superseded | Demo only | N/A | N/A | Replaced by finalized real-data contract API-20260730-003 |
| API-20260623-001 | Verified | `POST /api/raster/import/`, bootstrap/settings limits | validation/config behavior | Updated | N/A | Implemented | Passed | Raster uploads now enforce configured size and configured pixel side limits |
| API-20260623-002 | Verified | `POST /api/raster/import/` | documentation clarification | Updated | N/A | Implemented | Passed | Raster upload storage names are unique identifiers without original filenames |
| API-20260628-001 | Verified | `GET /api/data-schema/summary/`, `GET /api/germplasm/accessions/` | new endpoint | Updated | Added | Implemented | Passed | Adds 甲方数据分类数据库架子 and seed query surface |
| API-20260629-001 | BackendReady | `GET /api/catalog/resources/`, `POST /api/catalog/import/commit/` | field/query addition | Updated | Added | Implemented | Focused passed | Adds DataResource.domainType so workspace navigation can filter by confirmed geo/non-geo data types |
| API-20260630-001 | Verified | `GET/POST /api/groups/`, `POST /api/groups/{groupId}/` | permission behavior | Updated | Updated | Implemented | Focused passed | Adds platform/research built-in roles, narrows normal-user defaults, and documents protected-role behavior |
| API-20260701-001 | ContractReady | `GET /api/layers/`, admin data-resource visualization payloads | response/request schema clarification | Updated | Added | Pending | Pending | Documents vector unique-value symbolization, alias merge classes, and germplasm DNA sex default template without adding new endpoints |
| API-20260701-002 | BackendReady | `GET /api/map/thumbnail-tiles/{z}/{x}/{y}.png` | new endpoint | Updated | N/A | Implemented | Focused passed | Adds same-origin thumbnail tile proxy/cache so new client machines do not depend on direct third-party tile access |
| API-20260703-001 | Verified | `GET/POST /api/admin/backups/*` | new endpoint | Updated | Added | Implemented | Focused passed | Adds superadmin-only local/cloud data backup configuration, task execution, history, and target test APIs |
| API-20260703-002 | Verified | `POST /api/catalog/resources/{id}/query/` | response fields | Updated | Updated | Implemented | Focused passed | Adds spatial-query-workbench summary fields for truncation, returned bounds, and backend elapsed time |
| API-20260703-003 | Verified | `GET /api/layers/`, admin data-resource visualization payloads | schema clarification | Updated | Added | N/A | Passed | Adds vector graduated numeric symbolization under existing symbolization renderer without new endpoints |
| API-20260704-001 | Verified | `GET /api/data-schema/summary/`, `GET /api/catalog/resources/`, `POST /api/catalog/import/commit/` | enum addition | Updated | Updated | Implemented | Focused passed | Adds `other` business data type across schema summary, resource filtering, and import commit |
| API-20260704-002 | Verified | `POST /api/catalog/export/`, `POST /api/catalog/export/async/`, export download | archive content behavior | Updated | N/A | Implemented | Focused passed | Adds per-vector `*-attributes.csv` files to export ZIP packages |
| API-20260710-001 | Verified | `GET /api/layers/`, admin data-resource visualization payloads | schema clarification | Updated | Updated | N/A | Passed | Adds manual graduated numeric classes under existing vector symbolization renderer |
| API-20260710-002 | Verified | `GET /api/admin/dashboard/` | response fields | Updated | Updated | Implemented | Focused passed | Adds permission-scoped data overview spatial summary for coverage map, heatmap, and coverage ranking |
| API-20260710-003 | Verified | `GET /api/catalog/resources/{id}/visualization-summary/` | response fields | Updated | Updated | Implemented | Focused passed | Adds recommended symbolization templates for five coordinate-bearing business table types |
| API-20260713-001 | Verified | `POST /api/catalog/vector-import/*`, schema summary and resource domain enum | new endpoints / enum addition | Updated | Added | Implemented | Focused passed | Adds vector source-file preview, validation, GeoPackage import, metadata registration, and the vector business domain type |
| API-20260713-002 | Verified | `POST /api/raster/import/preview/`, raster import/jobs/tiles | new endpoint / multipart and response fields | Updated | Added | Implemented | Passed | Adds GDAL-backed raster packages, DAT+HDR, persistent jobs/styles, configurable bands and stable tile caching |
| API-20260714-001 | Verified | `GET /api/admin/dashboard/` | statistics behavior clarification | Updated | Updated | Implemented | Focused passed | Separates authenticated activity from successful login events and fixes cross-midnight session undercounting |
| API-20260714-002 | Verified | `GET /api/catalog/resources/` | query parameter / response field | Updated | Updated | Implemented | Focused passed | Adds explicit spatial/non-spatial resource classification so map and non-geo workspaces receive isolated lists |
| API-20260713-003 | Verified | `GET /api/admin/data/resources/` | response field / grouping semantics | Updated | Updated | Implemented | Focused passed | Adds business type data for automatic inventory system groups while preserving custom groups |
| API-20260715-001 | Verified | `GET /api/admin/data/resources/` | response fields / aggregate semantics | Updated | Updated | Implemented | Focused passed | Separates full filtered statistics and group totals from paginated resource details |
| API-20260714-003 | Verified | `/api/catalog/map-compositions/*` | new endpoints / models / permissions / multipart export | Updated | Added | Implemented | Passed | Adds persisted map layouts, immutable output versions, PNG/JPG/PDF artifacts and publish workflow |
| API-20260714-004 | Verified | `GET/POST /api/catalog/workspaces/*`, `GET/POST /api/admin/workspaces/*` | visibility behavior / request and response fields | Updated | Updated | Implemented | Focused passed | Makes superadmin visibility unconditional, exposes shared active workspaces in the map, and adds uploader-managed access scopes |
| API-20260714-005 | Verified | `POST /api/auth/register/`, `GET/POST /api/admin/role-applications/*`, `POST /api/users/` | request validation / new endpoints / role workflow | Updated | Updated | Verified | Passed | Requires normalized unique email, fixed ordinary-user registration, research-role application review and transitional password recovery guidance |
| API-20260722-001 | Verified | data schema, catalog resources, all import commits, admin data resources | hierarchical classification / response and request fields | Updated | N/A | Implemented | Passed | Replaces geo/non-geo navigation taxonomy with the four confirmed client business categories while retaining technical compatibility fields |
| API-20260722-002 | Verified | `GET/POST /api/catalog/results/`, result file delivery | new endpoint / multipart and permission behavior | Updated | N/A | Implemented | Passed | Adds platform-analysis and direct-import result artifacts with draft/published visibility, preview and download |
| API-20260723-001 | Verified | `GET /api/admin/dashboard/` | response fields / aggregate semantics | Updated | Updated | Implemented | Passed | Separates physical format statistics from the four-major/fifteen-minor authoritative business taxonomy distribution |
| API-20260723-002 | Verified | `/api/catalog/results/*`, authenticated user permissions | permission/schema/management endpoint | Updated | Added | Implemented | Passed | Adds dedicated result permissions, direct-publication imports and unified result management |
| API-20260724-001 | Verified | `GET /api/login/overview/` | response value semantics / mock data | Updated | Updated | Implemented | Passed | Aligns the English name, abbreviation and edition with the current global platform identity |
| API-20260729-001 | Verified | guest login and permission-scoped catalog reads | permission behavior / documentation clarification | Updated | N/A | Implemented | Focused passed | Treats the guest audience as public so every authenticated role inherits publicly shared objects |
| API-20260729-002 | Verified | authenticated user permissions and login overview | permission/value semantics | Updated | Updated | Implemented | Passed | Hides operations admin from data-only roles and replaces hard-coded login statistics/service nodes with live platform values |
| API-20260730-001 | Verified | `POST /api/admin/data/resources/{resourceId}/` | request field / rename behavior | Updated | N/A | Implemented | Passed | Adds display-name-only data resource rename without changing stable identifiers, storage or default layer names |
| API-20260730-002 | Verified | `GET /api/bootstrap/`, `GET/POST /api/admin/settings/`, `GET /api/login/overview/` | response/request value normalization | Updated | N/A | Implemented | Passed | Normalizes known legacy Central Asia platform names to the confirmed global brand while preserving custom deployment names |
| API-20260730-003 | Verified | `GET /api/catalog/resources/{id}/nongeo-analysis/`, `POST /api/catalog/resources/{id}/nongeo-query/` | new endpoint / response and request schemas | Updated | N/A | Implemented | Passed | Replaces non-geographic demo statistics with permission-scoped real table/gene analysis and paginated querying |
| API-20260730-004 | Verified | `POST /api/catalog/scan/`, `POST /api/raster/scan/` | permission and concurrency behavior | Updated | N/A | Implemented | Passed | Documents maintenance-only scan permissions, catalog 409 conflicts and raster active-job reuse |
| API-20260730-005 | Verified | `POST /api/catalog/results/`, `GET /api/catalog/results/{resultId}/file/` | validation / permission / response headers | Updated | N/A | Implemented | Passed | Verifies real file formats, emits trusted MIME and hardens preview/download responses |
| API-20260730-006 | Verified | `/api/groups/*`, `/api/users/*` | permission and protected-principal behavior | Updated | N/A | Implemented | Passed | Enforces feature-permission second authorization plus guest and platform-admin protections |
| API-20260730-007 | Verified | generated browser SDK operations | client transport metadata / CSP compatibility | Updated | N/A | N/A | Passed | Defaults generated clients to the same-origin platform entry instead of hard-coded localhost |
| API-20260730-008 | Verified | vector query and catalog export endpoints | 413/503 status and resource-bound behavior | Updated | N/A | Implemented | Passed | Adds bounded query concurrency/body sizes and disk-streamed exports for OOM prevention |
| API-20260731-001 | BackendReady | `POST /api/admin/settings/` | validation / persistence / error response | Updated | N/A | Implemented | Focused passed | Bounds editable runtime limits and requires writable `/config` directory mounting for atomic saves |
| API-20260801-001 | Verified | `GET /api/bootstrap/`, `GET/POST /api/admin/settings/` | response/request field | Updated | Updated | Implemented | Passed | Adds an optional browser-safe Tianditu Key while keeping legacy TOML files valid |
| API-20260801-002 | Verified | `POST /api/raster/render/`, completed raster render jobs | response fields / tile delivery semantics | Updated | Updated | Implemented | Passed | Adds native zoom and sampling metadata; categorical styles become atomically published nearest-neighbor tile pyramids |
| API-20260802-001 | Verified | bootstrap/admin settings and upload endpoints | validation / deployment safety | Updated | N/A | Implemented | Passed | Raises the disk-backed upload ceiling to 1024 MB while retaining parser-specific memory limits |
| API-20260806-001 | Verified | bootstrap/admin settings map configuration | accepted configuration value / response enum | Updated | N/A | Implemented | Passed | Adds `tianditu-imagery` as the fourth formal and configurable default basemap |
| API-20260810-001 | Verified | `GET /api/bootstrap/`, `GET/POST /api/admin/settings/`, `GET /api/login/overview/` | response/example value normalization | Updated | N/A | Implemented | Passed | Temporarily presents the arid-region intelligent-monitoring brand while normalizing the previous canonical name and preserving unrelated custom deployments |
| API-20261105-001 | BackendReady | /api/agent/workflows/{workflowId}/; /api/catalog/resources/{resourceId}/query/ | compare/inspection projections and display geometry budget | Updated | Scoped integration and browser fixtures | Implemented | Local focused tests | Owner/project authorization and original computation geometry unchanged; browser and production verification separate |

## Entry Template

```markdown
## API-YYYYMMDD-001 - Short Change Title

- Status: Proposed | ContractReady | Implementing | BackendReady | Verified | Blocked | Superseded
- Owner: Frontend requester / backend implementer
- Endpoints: `METHOD /api/...`
- Change type: response fields | request body | status code | permission behavior | mock data | new endpoint | removed endpoint
- OpenAPI change: concise summary of schema/status/permission changes
- Mock examples: `mock/prism/examples/...json`
- Frontend reason: UI workflow or data requirement
- Backend implementation notes: expected service/view/test work
- Verification: commands or response checks required before marking implemented
- Result: current backend/frontend verification result
```

## API-20260810-001 - Temporary arid-region intelligent-monitoring brand

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/bootstrap/`, `GET/POST /api/admin/settings/`, `GET /api/login/overview/`
- Change type: response/example value normalization | frontend metadata
- OpenAPI change: Updates platform-name examples to `干旱区胡杨林生态智慧监测平台`, the English display name to `Arid-region Poplar Forest Ecological Intelligent Monitoring Platform`, the abbreviation to `APF-EIMP`, and the edition to `APF-EIMP · WebGIS Monitoring Edition`; response schemas, permissions and status codes are unchanged.
- Mock examples: N/A; response schemas and Prism examples are unchanged.
- Frontend reason: The temporary public release must present one consistent platform identity across the login page, browser title, workspace, data catalog and public login overview without changing platform functionality.
- Backend implementation notes: Treat the previous canonical name `全球胡杨林生态系统保护数据共享平台` as a known alias of the temporary display name so the mounted production TOML remains unchanged; continue preserving unrelated custom deployment names.
- Verification: Run the focused core API and frontend brand/browser tests; regenerate and compare API clients; run API lint, change tracking, TypeScript checks and a production build; visually verify the local login page and authenticated header before release.
- Result: Passed. All 584 backend tests and 52 subtests, all 390 frontend unit tests, and all 144 browser tests passed. OpenAPI lint, API change tracking, client/documentation/Prism regeneration and generated-file comparison passed; TypeScript application and node checks, Oxlint, focused formatting, brand consistency checks, and the production build passed. OpenAPI lint retains only six pre-existing unused-component warnings. The repository-wide frontend format check still reports 171 pre-existing unrelated files and untracked Playwright artifacts; all changed frontend sources pass focused formatting. Local browser verification passed for the login page, authenticated data catalog header, and About introduction after reloading the no-reload backend process.

## API-20260801-001 - Optional Tianditu browser access token

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/bootstrap/`, `GET/POST /api/admin/settings/`
- Change type: response field | request field | runtime configuration
- OpenAPI change: Adds optional string field `map.tiandituAccessToken` to `MapConfig`; the backend returns an empty string when the optional `application.map.tianditu_access_token` TOML key is absent. Keeping the contract field optional avoids forcing legacy generated clients to provide it immediately. The existing admin settings POST accepts the same field for partial map-setting updates.
- Mock examples: `mock/prism/examples/00-public-auth.json`, `mock/prism/examples/10-admin-auth.json`
- Frontend reason: The basemap selector needs a browser-safe Tianditu Key without replacing or weakening the existing Mapbox default path.
- Backend implementation notes: Load the optional TOML value with an empty-string default, expose it through Bootstrap and admin settings, persist trimmed administrator updates, and never seed a real Key in repository configuration or examples.
- Validation notes: Administrator writes accept only Mapbox `pk.*` public tokens and 32-character alphanumeric Tianditu browser keys. Formal default basemaps are `satellite`, `mapbox-streets`, and `tianditu-vector`; historical `osm` input is normalized to `satellite` on save.
- Verification: Focused Bootstrap/config/admin-setting Django tests; regenerated API types; `check:api`; `api:changes:check`; `api:lint`; `api:docs`; `mock:build`; frontend `typecheck`.
- Result: Passed. The focused backend run completed with 10 passed tests (101 deselected), followed by all 111 tests in `backend/tests/integration/core/test_api.py`; generated API files match the OpenAPI contract; change tracking, OpenAPI validation, documentation generation, Prism bundle generation, and TypeScript checks all passed. OpenAPI lint retains only the six pre-existing unused-component warnings.

## API-20260801-002 - LUCC native zoom and nearest-neighbor tile delivery

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/raster/render/`, `POST /api/raster/render/async/`, `GET /api/raster/jobs/{jobId}/`
- Change type: response fields | tile delivery semantics | mock data
- OpenAPI change: `RasterRenderResult` now requires `minZoom`, `maxZoom`, and `tileSampling`. `maxZoom` is derived from the processed Web Mercator pixel size, and `tileSampling` explicitly tells the client to use `nearest` for categorical rasters or `linear` for continuous imagery.
- Mock examples: `mock/prism/examples/40-raster.json`
- Frontend reason: Mapbox otherwise assumes tiles exist through z22 and can keep overscaled parent tiles visible while higher levels load. An explicit native maximum and first-frame sampling rule are required to prevent LUCC interpolation colors during zoom transitions.
- Backend implementation notes: Build a complete content-addressed MBTiles pyramid for every categorical style, publish it atomically only after all levels are present, and keep render jobs non-ready until publication completes. Existing categorical COGs without the current nearest-neighbor preprocessing marker must be rebuilt during scan.
- Verification: Regenerate/check OpenAPI clients and Prism examples; run focused frontend raster-source tests, the Mapbox nearest-raster patch verifier, all raster backend tests, TypeScript checks, and a production build. Validate a real LUCC pyramid at every zoom for palette-only opaque pixels plus fully transparent NoData.
- Result: Backend raster tests pass (161 tests). A real `hjyt_tile_r1_c1` z0–16 pyramid built 2,575 tiles in 10.0 seconds (10.9 MiB); all levels contained zero partial-alpha pixels and zero colors outside the six-class palette plus transparent NoData. Focused frontend tests, TypeScript, the Mapbox nearest/mipmap/anisotropy verifier and production build all pass.

## API-20260730-001 - Data resource display-name rename

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/admin/data/resources/{resourceId}/`
- Change type: request field | rename behavior
- OpenAPI change: Adds optional `name` to `AdminDataResourceUpdateRequest` for `action=update`, with a trimmed length of 1–160 characters.
- Mock examples: N/A; response schemas and Prism examples are unchanged.
- Frontend reason: The inventory configuration drawer previously exposed only the default map-layer name, so operators could not rename the data resource shown in inventory, catalog and search views.
- Backend implementation notes: Update only `DataResource.name`; preserve `code`, `storage_path`, physical files/tables, `MapLayer.name` and the default visualization layer name. Continue requiring `catalog.change_dataresource` and record the rename in the operation log.
- Verification: regenerate/check OpenAPI types, run API lint/change tracking, focused Django rename and validation tests, the focused Chromium inventory rename flow, TypeScript checks and production build.
- Result: Verified with the focused backend/frontend tests and API/build checks listed above.

## API-20260730-002 - Canonical global platform brand

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/bootstrap/`, `GET/POST /api/admin/settings/`, `GET /api/login/overview/`
- Change type: request/response value normalization | frontend metadata
- OpenAPI change: Documents that known legacy “Central Asia Populus euphratica” platform names are upgraded to `全球胡杨林生态系统保护数据共享平台`; unrelated custom deployment names remain supported.
- Mock examples: Existing bootstrap and login-overview examples already use the canonical global brand.
- Frontend reason: A legacy runtime TOML value could overwrite the correct static HTML title after bootstrap, causing browser tabs and a few runtime-driven labels to regress to the old name.
- Backend implementation notes: Centralize canonical Chinese/English names, abbreviation and edition; normalize known legacy names in bootstrap, login overview, admin settings and backup manifests; persist the canonical value when a legacy name is submitted through system settings.
- Verification: run the brand drift guard, backend bootstrap/settings tests, frontend normalization and Chromium tab-title tests, OpenAPI checks, TypeScript checks and production build.
- Result: Verified with the focused backend/frontend tests and consistency/build checks listed above.

## API-20260729-002 - Permission-scoped admin entry and live login overview

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/auth/me/`, `GET /api/login/overview/`
- Change type: permission behavior | response value semantics | mock data
- OpenAPI change: Clarifies that `canAccessAdmin` is true only when the current account has at least one operations-admin capability; the login overview continues using the existing schema but now drives the real login UI.
- Mock examples: `mock/prism/examples/05-login-overview.json`
- Frontend reason: Ordinary/research users must not enter an empty or sensitive operations dashboard, and public login statistics must not be hard-coded demo values.
- Backend implementation notes: Compute admin access from existing fine-grained permissions; keep the personal profile route available; count service-status nodes from the actual service list.
- Verification: Run focused auth/login overview tests, frontend typecheck, login/browser route checks and OpenAPI generation checks.
- Result: Verified with 481 backend tests, 197 frontend unit tests, 96 Chromium browser tests, frontend TypeScript checks, a production build, OpenAPI generation/consistency checks, API change tracking, Prism mock injection, and real local guest-route regression.

## API-20260722-001 - Four-Category Data Taxonomy V1

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/data-schema/summary/`, `GET /api/catalog/resources/`, `POST /api/catalog/import/commit/`, `POST /api/catalog/vector-import/commit/`, `POST /api/raster/import/`, `GET/POST /api/admin/data/resources/*`
- Change type: response fields | request fields | query parameters | classification behavior
- OpenAPI change: Adds taxonomy version, hierarchical category nodes, category paths, classification status, available views, descendant-aware category filtering and category selection for imports and inventory updates. Keeps `domainType`, `dataType`, `spatialClass` and the legacy `category` query parameter during the compatibility release.
- Mock examples: N/A; the canonical OpenAPI contract, generated client and live schema/catalog responses carry the confirmed category codes.
- Frontend reason: The client has confirmed four authoritative business categories; map/non-map distinctions must become presentation capabilities rather than top-level data categories.
- Backend implementation notes: Extend `DictionaryItem` with parent/selectable fields, keep `DataResource.category` as the single primary category, seed the fixed tree, backfill only unambiguous legacy resources, and never move or delete research files during classification.
- Verification: Rehearse migrations on a copied `meta.db`; verify archived compositions and all resource/layer counts do not decrease; run OpenAPI generation/lint/change checks, focused Django catalog/import/admin tests, frontend taxonomy/import/inventory tests and typecheck.
- Result: Verified on a copied database before the formal migration, then re-audited on the formal database with all 20 resources, 19 layers, 4 topics and 4 topic versions preserved. The two legacy archived topics retain their records, versions, snapshots and artifacts with status mapped to `completed`; 8 unambiguous resources were classified and 12 remain pending for manual review. Django system and migration checks, 13 focused taxonomy/import/archive/backup tests, OpenAPI lint and API change tracking, frontend typecheck, 191 frontend unit tests, targeted lint/format checks, production build, and signed-in browser checks for the four-category catalog, descendant filters, map-context handoff and inventory classification editor passed. The broader backend suite completed with 446 passing and 19 known baseline failures caused by existing Windows TOML/path/file-lock assumptions, an existing duplicate built-in-role fixture and one unrelated coordinate-format expectation.

## API-20260714-005 - Registration Email And Research Role Application

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/auth/register/`, `GET /api/admin/role-applications/`, `POST /api/admin/role-applications/{applicationId}/review/`, `POST /api/users/`
- Change type: request body | validation behavior | new endpoints | permission behavior | mock data
- OpenAPI change: Makes registration and administrator-created account email mandatory, defines lowercase non-empty email uniqueness, adds `accountPurpose` and conditional research-application fields, returns the submitted application, and adds permission-gated list/review endpoints.
- Mock examples: `mock/prism/examples/00-public-auth.json`, `mock/prism/examples/10-admin-auth.json`
- Frontend reason: Self-registration must map safely to the existing built-in roles without allowing users to grant themselves elevated permissions, while the current no-mail transition still requires reliable contact data and a clear administrator-assisted password reset path.
- Backend implementation notes: Keep every self-registered account in the ordinary-user group, persist a separate pending research-role application, normalize and reserve unique email identities, approve by replacing the ordinary role with the research role while retaining custom roles, reject without changing permissions, and record review operations.
- Verification: Run OpenAPI lint/generation/change checks, Prism example injection, Django migration/system checks, focused registration/email/review tests, frontend registration/admin tests, typecheck and production build.
- Result: Verified with OpenAPI lint and regenerated client types, bundled YAML/HTML documentation, Prism example injection, API change tracking, Django system and migration checks, 13 focused registration/email/role-review permission tests, frontend typecheck, 185 frontend unit tests, production build, and targeted system-Chrome browser tests for research registration and administrator approval. The repository-wide browser command still requires its configured Playwright Chromium download; the broader existing core suite retains unrelated Windows TOML/path/encoding failures.

## API-20260714-003 - Formal Map Composition And Thematic Product Workflow

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET/POST /api/catalog/map-compositions/`, `GET/POST /api/catalog/map-compositions/{compositionId}/`, `POST /api/catalog/map-compositions/{compositionId}/versions/`, `GET /api/catalog/map-compositions/{compositionId}/versions/{versionNumber}/file/`
- Change type: new endpoint | new models | request/response schemas | multipart upload | permission behavior | binary download | mock data
- OpenAPI change: Adds typed map composition drafts linked to project workspaces, lightweight layout JSON, immutable exported versions, status transitions, PNG/JPG/PDF metadata, preview/download URLs, and six composition permission flags in the current-user response.
- Mock examples: `mock/prism/examples/50-map-compositions.json`
- Frontend reason: The geographic workspace needs a complete project-to-layout-to-thematic-product workflow with paper settings, map frames, legends, north arrows, scale bars, overview maps, grids, sources, notes, preview, versioning and export.
- Backend implementation notes: Persist composition metadata in the application database, store generated artifacts only under the TOML-driven business exports directory, reject embedded source data/Data URLs in layout JSON, validate uploaded PNG dimensions, convert the client-rendered master image to the selected output format, enforce Django permissions and record audit targets.
- Verification: Run OpenAPI lint/generation/check, Prism bundle/example injection, Django migrations/system checks, focused map-composition API/model/export tests, frontend typecheck/tests/build, and a signed-in browser workflow covering create, edit, version generation, preview, download and publish.
- Result: Verified with focused map-composition/workspace/auth Django tests, OpenAPI lint and regenerated types, API change tracking, Prism example injection, 179 frontend unit tests, frontend typecheck, production build and targeted lint. A signed-in real-browser workflow completed project creation, composition editing, geographic and Web Mercator grids, overview map, legend/source/note rendering, draft save, PNG V1 generation and preview, publish, unpublish and archive. The repository browser-test command remains unavailable because its configured Playwright Chromium executable is not installed.

## API-20260714-004 - Shared Workspace Visibility And Superadmin Invariant

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET/POST /api/catalog/workspaces/`, `GET/POST /api/catalog/workspaces/{workspaceId}/`, `GET /api/admin/workspaces/`, `POST /api/admin/workspaces/{workspaceId}/`
- Change type: permission behavior | response fields | request body | mock data | data migration
- OpenAPI change: Changes the normal workspace list/detail from owner-only to owner-or-role-visible active objects with a superadmin all-object bypass; adds access groups and per-object owner/edit/delete flags, returns selectable access groups, and accepts `accessGroupIds` on create/update while keeping the superadmin group server-controlled.
- Mock examples: `mock/prism/examples/30-catalog-vector.json`, `mock/prism/examples/25-admin-managed-assets.json`
- Frontend reason: Superadmins and explicitly shared users must be able to discover and load engineering/topic snapshots saved by other uploaders, while owners need to set visibility during save and shared viewers must not receive edit/delete controls.
- Backend implementation notes: Centralize workspace visibility filtering, force the protected superadmin group onto new and historical workspaces, keep normal updates owner-only, exclude the superadmin group from selectable scopes, and preserve inactive objects only in the admin management surface.
- Verification: Run migration checks, focused workspace API tests, OpenAPI generation/lint/change checks, frontend typecheck and focused workspace/admin tests, then verify list counts, shared loading, owner-only editing and admin map loading in a signed-in browser.
- Result: Verified with OpenAPI lint and generated types, Prism bundle/example injection, API change request validation, Django system/migration checks, focused map-composition/workspace/auth tests, frontend typecheck, 179 unit tests and production build. Browser workflow verification is tracked separately because it requires a running signed-in local stack with map tile access.

## API-20260714-001 - Reliable Active Account And Login Statistics

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/admin/dashboard/`
- Change type: statistics behavior clarification | mock data | documentation clarification
- OpenAPI change: Keeps the existing response shape but redefines `activeUsers.count` and `series[].count` as authenticated API activity metrics, while `loginCount` and `ranking[].loginCount` remain successful session-creation metrics. Successful authentication includes password login, guest login, and registration auto-login.
- Mock examples: `mock/prism/examples/20-admin-dashboard-data.json`
- Frontend reason: A session that remains signed in across midnight was shown as zero active users even while the account was actively querying and importing data, because the previous implementation treated login events as activity.
- Backend implementation notes: Record at most one activity row per user and local-time hour, backfill historical successful operation logs, identify authentication events with stable event codes instead of Chinese display text, preserve principal visibility rules, and keep login totals separate from activity counts.
- Verification: run the audit migration check, focused dashboard/auth tests, OpenAPI generation/checks, frontend route tests, typecheck, and formatting checks.
- Result: Verified by focused backend tests covering carried sessions, stable login events, daily series, and existing dashboard permissions, plus OpenAPI/frontend checks.

## API-20260714-002 - Geographic And Non-Geographic Resource Isolation

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/catalog/resources/`
- Change type: query parameter | response field | filtering behavior | mock data
- OpenAPI change: Adds `spatialClass=spatial|non_spatial` and `DataResource.spatialClass`; documents that vector/raster resources are spatial while table/gene/document/image resources are non-spatial, independently of `domainType`.
- Mock examples: `mock/prism/examples/30-catalog-vector.json`
- Frontend reason: Plain Excel/CSV imports without usable longitude/latitude columns must disappear from the map resource list and appear immediately in the non-geographic workspace resource list, including after manual refresh.
- Backend implementation notes: Derive the resource classification from `DataResource.data_type`, validate the query value, preserve existing permission and business-domain filters, and return the classification in serialized resources.
- Verification: run OpenAPI lint/generation, API change request check, focused catalog list/import tests, frontend typecheck and focused workspace tests, then validate both workspaces in the local browser.
- Result: Verified with OpenAPI lint and generated types, Prism bundle/example injection, API change request validation, focused Django resource/import tests, frontend typecheck and unit tests, and a real signed-in Chrome check confirming the imported SQLite table appears and refreshes in `/nongeo` while remaining absent from `/map`. The repository browser-test command remains unavailable because its configured Playwright Chromium binary is not installed.

## API-20260713-001 - Vector Source Import And Business Domain

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/catalog/vector-import/preview/`, `POST /api/catalog/vector-import/validate/`, `POST /api/catalog/vector-import/commit/`, `GET /api/data-schema/summary/`, `GET /api/catalog/resources/`
- Change type: new endpoint | request body | response fields | enum addition | mock data | backend model
- OpenAPI change: Adds typed vector source preview, validation, and commit responses for Shapefile ZIP, GeoJSON, and GeoPackage; extends `DataDomainType` with `vector`; documents CRS, encoding, geometry quality, duplicate-name, access-group, and permission behavior.
- Mock examples: `mock/prism/examples/30-catalog-vector.json`, `mock/prism/examples/45-domain-schema.json`
- Frontend reason: The admin import page must replace the previous “vector import not yet supported” result with a complete typed workflow that previews source layers, allows encoding/CRS and geometry-quality decisions, and registers the imported resource for immediate use in the geographic workspace.
- Backend implementation notes: Add `VectorDataset`, retain original uploads under the configured research vector directory, normalize valid geometries to EPSG:4326 in the shared GeoPackage, create `DataResource`/`MapLayer`/`ResourceDomain`/`SourceDataset`, reuse existing access groups and audit logging, and keep existing Excel/CSV import endpoints unchanged.
- Verification: run OpenAPI lint/generation, API change request check, Prism mock build, Django migration/system checks, focused vector import integration tests, frontend API client tests, frontend typecheck, formatting checks, and production build.
- Result: Verified with OpenAPI lint and generated types, Prism bundle/example injection, API change request validation, Django system and focused migration checks, vector import/domain/schema integration tests, actual GB18030 Shapefile preview, frontend typecheck, targeted lint/format checks, mock example tests, and production build. Browser-mode API tests remain blocked because the configured Playwright Chromium executable is not installed; the broader legacy import suite still contains existing Windows GeoPackage/SQLite file-lock failures and one unrelated coordinate-format expectation failure.

## API-20260710-002 - Data Overview Spatial Summary

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/admin/dashboard/`
- Change type: response fields | mock data | documentation clarification
- OpenAPI change: Extends `AdminDashboardDataOverviewScope` with required `spatialSummary`, plus typed `AdminDashboardSpatialSummary`, `AdminDashboardResourceExtent`, and `AdminDashboardSpatialHeatmapCell` schemas. The field is returned separately under `ownUploads` and permission-gated `visibleResources`; legacy top-level system total fields remain unchanged.
- Mock examples: `mock/prism/examples/20-admin-dashboard-data.json`
- Frontend reason: The data management overview needs first-stage visualizations for spatial coverage, heatmap distribution, data type composition, coverage ranking, and uploader contribution without fetching full resource geometry or bypassing permission scope.
- Backend implementation notes: Compute `spatialSummary` only after the relevant queryset has been scoped to the current user (`maintainer=current user` for `ownUploads`, `filter_accessible(...)` for `visibleResources`). Use registered resource/layer/raster bbox metadata only; do not scan raw feature data in the dashboard request. Ordinary users must never receive all-platform spatial summaries or uploader rankings.
- Verification: run OpenAPI generation, Prism mock build, focused dashboard backend tests, frontend typecheck, and route/browser checks for the data overview page. Do not run scripts containing bulk delete commands.
- Result: Verified with OpenAPI lint/generation, Prism bundle/example injection, API change request check, focused dashboard backend tests, Django system check, frontend typecheck, targeted lint/format checks for touched frontend files, and Vite production build. Browser route test could not run because the local Playwright Chromium executable is not installed.

## API-20260710-001 - Vector Manual Graduated Symbolization

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/layers/`, `POST /api/admin/data/resources/{id}/`
- Change type: response fields | request body | mock data | documentation clarification
- OpenAPI change: Extends `GraduatedRenderer.method` with `manual`. Manual graduated symbolization continues to use existing `classes[].min/max/color/iconImage/size/visible` fields, with no new endpoint or backend model.
- Mock examples: `mock/prism/examples/30-catalog-vector.json` changes the elevation graduated vector example to `method="manual"` with custom range labels and custom min/max boundaries.
- Frontend reason: Users need to define non-equal, domain-specific numeric ranges for fields such as elevation, NDVI, and salinity, while still editing colors, icons, sizes, and visibility per class.
- Backend implementation notes: Existing JSONField storage and serializers should pass the documented `symbolization` object through unchanged. Permission behavior remains the same as other custom symbolization edits.
- Verification: run OpenAPI type generation, Prism mock build, API change request check, focused frontend symbolization tests, frontend typecheck, backend Django check, and production build.
- Result: Verified with OpenAPI type generation, Prism mock bundle injection, Redocly lint, API change request check, focused frontend symbolization tests, frontend TypeScript checks, Django system check, and Vite production build. Redocly still reports two pre-existing unused schema warnings unrelated to this change.

## API-20260704-001 - Other Business Data Type

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/data-schema/summary/`, `GET /api/catalog/resources/`, `POST /api/catalog/import/commit/`
- Change type: enum addition | response fields | request body | mock data | backend model choices
- OpenAPI change: Extends `DataDomainType` with `other`, documents that the data schema summary and resource filter support other-type resources, and keeps existing missing/invalid `domainType` error behavior unchanged.
- Mock examples: `mock/prism/examples/45-domain-schema.json`, `mock/prism/examples/30-catalog-vector.json`
- Frontend reason: The data import page needs a typed catch-all business classification for files that do not clearly match germplasm, community, survey, remote sensing, molecular, genome, or other specialized domains.
- Backend implementation notes: Add `other` to standards and catalog domain choices, expose it in `GET /api/data-schema/summary/`, allow resource filtering by `domainType=other`, and save it during Excel/CSV import commits without adding new permissions.
- Verification: run OpenAPI lint/generation, rebuild Prism mock, run API change request check, focused backend schema/resource/import tests, and focused frontend import tests/typecheck.
- Result: Verified with OpenAPI lint, generated API types, Prism mock rebuild, API docs rebuild, API change request check, Django system check, focused backend schema/resource/import tests, frontend TypeScript checks, import value unit test, and mock example tests. Browser route test could not run because the local Playwright Chromium executable is not installed.

## API-20260703-001 - Superadmin Data Backup

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/admin/backups/overview/`, `GET/POST /api/admin/backups/settings/`, `POST /api/admin/backups/targets/test/`, `GET/POST /api/admin/backups/runs/`, `GET /api/admin/backups/runs/{runId}/`, `GET /api/admin/backups/runs/{runId}/download/`
- Change type: new endpoint | request body | response fields | permission behavior | mock data | backend model
- OpenAPI change: Adds typed backup plans, local and S3-compatible object-storage target settings, target connection testing, manual backup task creation, task polling, history pagination, and local archive download. All endpoints require an authenticated built-in `超级管理员` subject; ordinary users remain forbidden even if mistakenly granted `core.manage_data_backup`.
- Mock examples: `mock/prism/examples/22-admin-backup.json`
- Frontend reason: The admin backup page needs a real typed workflow for configuring local/cloud targets, testing cloud parameters entered by superadmin users, starting backups, polling progress, and reviewing history without hand-written DTOs.
- Backend implementation notes: Add a persistent backup run model, TOML-backed backup configuration, local archive target, S3-compatible object-storage target, a lightweight scheduler/management command for automatic runs, operation-log writes for user-triggered configuration and backup actions, and strict response conformance to the new schemas.
- Verification: run OpenAPI lint/generation, Prism mock build, API change request check, focused backend backup API/service tests, frontend typecheck, and focused admin backup page tests.
- Result: OpenAPI lint, generated client typecheck, focused backend backup tests, Django check, mock example validation, and admin backup page lint/type checks passed. Browser rendering test remains dependent on the local Playwright Chromium binary.

## API-20260703-002 - Spatial Query Workbench Summary

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/catalog/resources/{id}/query/`
- Change type: response fields | mock data | documentation clarification
- OpenAPI change: Extends `QueryResponse` with `limitExceeded`, `bounds`, and `elapsedMs` so the bottom spatial query workbench can display a real query status, hit summary, returned result extent, truncation warning, and backend timing without inventing frontend-only fields. The endpoint permission remains unchanged: authenticated users must have both `core.query_data` and `core.load_vector_layer`, and must be allowed to access the target resource.
- Mock examples: `mock/prism/examples/30-catalog-vector.json`
- Frontend reason: The new bottom spatial query workbench separates spatial-range querying from the left attribute query panel and needs typed result-summary fields before a temporary result is loaded into the layer tree.
- Backend implementation notes: Measure `vector_store.query_resource` elapsed time, set `limitExceeded` when filtered hits exceed the returned limit, compute `bounds` from returned valid GeoJSON features, and preserve the existing `totalCount`, `returnedCount`, `fields`, `geojson`, and `warnings` behavior.
- Verification: run OpenAPI lint/generation, Prism mock build, frontend typecheck, focused backend catalog query tests, and targeted frontend tests where practical.
- Result: OpenAPI lint, generated API client, Prism mock build, API change request check, frontend typecheck, focused backend query summary tests, and Django system check passed. Running the entire catalog query unit file still hits existing Windows GeoPackage file-lock cleanup failures in unrelated metadata tests.

## API-20260703-003 - Vector Graduated Numeric Symbolization Contract

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/layers/`, `POST /api/admin/data/resources/{id}/`
- Change type: response fields | request body | mock data | documentation clarification
- OpenAPI change: Extends `VectorRenderer` with `GraduatedRenderer` and `GraduatedSymbolClass` for existing `symbolization.renderer.type="graduated"`. The schema documents numeric field classification, `equalInterval` and `quantile` methods, class count, precision, color ramps, `classes[].min/max`, no-data default class, visibility, `gm-*` icon IDs, and existing `additionalProperties` compatibility.
- Mock examples: `mock/prism/examples/30-catalog-vector.json` adds a vector point layer whose `symbolization.renderer` classifies `海拔` into five equal-interval ranges using `gm-tree` and a green ramp.
- Frontend reason: The symbolization editor needs a typed continuous-field workflow for elevation, NDVI, salinity, and similar attributes that matches the existing unique-value editing model while preserving generated API contracts.
- Backend implementation notes: No new endpoint, permission, database migration, or server-side classifier is required. Existing JSONField storage, layer serialization, and admin default-visualization save behavior should pass this JSON object through unchanged and keep current permission behavior.
- Verification: run OpenAPI lint/generation, rebuild Prism mock, run focused frontend symbolization tests, frontend typecheck, backend Django check, and production build.
- Result: Verified with OpenAPI type generation, Prism mock bundle injection, Redocly lint, API change request check, focused frontend symbolization tests, frontend TypeScript checks, Django system check, and Vite production build. Redocly continues to report two pre-existing unused schema warnings unrelated to this change.

## API-20260701-002 - Same-Origin Map Thumbnail Tiles

- Status: Verified
- Owner: Backend implementer
- Endpoints: `GET /api/map/thumbnail-tiles/{z}/{x}/{y}.png`
- Change type: new endpoint
- OpenAPI change: Adds a public binary image endpoint for right-side map thumbnail tiles with `z/x/y` path parameters, `image/png`, `image/jpeg`, `image/webp`, `image/avif`, and `image/svg+xml` success responses, and standard error responses.
- Mock examples: N/A; binary tile responses are not represented in Prism examples.
- Frontend reason: Remote client browsers must not depend on direct access to third-party tile domains or stale browser cache for the main workspace thumbnail.
- Backend implementation notes: Proxy Mapbox/OSM according to `application.map`, cache successful tiles under the app data media directory while preserving the real image MIME type, and return a generated local Web Mercator 2D world map tile when the external source is unavailable and cache is empty.
- Verification: run focused frontend thumbnail tests, backend core thumbnail API tests, frontend typecheck, and production build.
- Result: Backend implementation and focused tests are complete; real deployment should verify that browser Network requests for the thumbnail use `/api/map/thumbnail-tiles/...`.

## API-20260618-001 - Non-Geographic Table Analytics

- Status: Superseded
- Owner: Frontend
- Endpoints: historical proposal only; replaced by API-20260730-003
- Change type: endpoint design paused
- OpenAPI change: The former `/nongeo-analytics/` and `/table-query/` proposal was removed; the finalized contract now uses `/nongeo-analysis/` and `/nongeo-query/` under API-20260730-003.
- Mock examples: Frontend demo only; no backend mock contract.
- Frontend reason: This entry recorded the earlier decision to defer field profiling, statistics and pagination until product semantics were confirmed.
- Backend implementation notes: No implementation is attached to the historical paths; use the permission-scoped real-data endpoints documented by API-20260730-003.
- Verification: run `cd frontend && pnpm run generate:api && pnpm run check:api && pnpm run api:changes:check`.
- Result: Superseded by the implemented and verified API-20260730-003 contract.

## API-20260623-001 - Raster Upload Size And Pixel Limits

- Status: Verified
- Owner: Frontend requester / backend implementer
- Endpoints: `POST /api/raster/import/`, `GET /api/bootstrap/`, `GET/POST /api/admin/settings/`
- Change type: status code | response fields | request body
- OpenAPI change: Documents upload validation for `application.limits.upload_max_mb` and `application.limits.max_raster_side_pixels`; adds `SystemLimits.maxRasterSidePixels` to bootstrap and admin settings payloads; validation failures continue to use the existing `400 ErrorResponse`.
- Mock examples: N/A; existing response schema is unchanged and the behavior is covered by frontend and backend tests.
- Frontend reason: Prevent unsupported large rasters from entering upload/preprocessing and surface immediate Chinese-facing validation feedback.
- Backend implementation notes: Uploaded files must be rejected before job creation when file size exceeds the configured limit or GDAL metadata reports width/height above the configured `max_raster_side_pixels`; `sourcePath` import and scan paths reuse the pixel-size limit.
- Verification: run `cd frontend && pnpm run generate:api && pnpm run check:api && pnpm run api:changes:check`; run focused frontend import tests and backend raster API tests.
- Result: Verified with `pnpm run generate:api`, `pnpm run check:api`, `pnpm run api:changes:check`, focused frontend raster upload tests, and backend raster API tests.

## API-20260623-002 - Raster Upload Storage Name Clarification

- Status: Verified
- Owner: Backend implementer
- Endpoints: `POST /api/raster/import/`
- Change type: request body
- OpenAPI change: Clarifies `name` descriptions so frontend display names are separate from backend unique storage filenames; request and response shapes are unchanged.
- Mock examples: N/A
- Frontend reason: Avoid showing or depending on backend storage names that no longer include original uploaded filenames.
- Backend implementation notes: Browser-uploaded rasters are stored as `uploaded/<uuid><suffix>` while `RasterDataset.name`, `DataResource.name`, and `MapLayer.name` continue to use the submitted display name or original upload stem.
- Verification: run `cd frontend && pnpm run api:changes:check`; run backend raster import tests.
- Result: Backend tests verify uploaded storage filenames do not include original upload names.

## API-20260628-001 - Domain Schema And Germplasm Database Scaffold

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/data-schema/summary/`, `GET /api/germplasm/accessions/`
- Change type: new endpoint | response fields | permission behavior | mock data
- OpenAPI change: Adds read-only schema summary response for the confirmed customer data categories and a paginated germplasm accession list response. Both endpoints require an authenticated session and `core.browse_data`; errors use the standard `ErrorResponse`.
- Mock examples: `mock/prism/examples/45-domain-schema.json`
- Frontend reason: Data management needs a stable typed source for the new data classification/catalog skeleton and a first query surface for germplasm resources without hand-written DTOs.
- Backend implementation notes: Add scaffold models for standards/ecology/omics domains, include apps in Django settings, expose read-only summary/accession views, and keep existing `DataResource`, import, raster, and catalog behavior unchanged.
- Verification: run `cd frontend && pnpm run generate:api && pnpm run check:api && pnpm run api:changes:check`; run backend model/API tests for the new endpoints and existing catalog smoke tests.
- Result: Verified with direct OpenAPI lint, OpenAPI type generation, API change request check, Prism mock bundle injection, Django check, focused backend endpoint tests, frontend TypeScript checks, and Vite build. `pnpm run check:api` was not run directly because the script contains `rm -rf`; existing catalog smoke coverage was sampled separately, with catalog startup/layer tests passing and `test_data_query.py` failing only during Windows temporary GeoPackage cleanup due locked files.

## API-20260629-001 - Catalog Resource Domain Type Filtering

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/catalog/resources/`, `POST /api/catalog/import/commit/`
- Change type: response fields | request body | status code | mock data
- OpenAPI change: Adds optional `DataResource.domainType`, `GET /api/catalog/resources/?domainType=` filtering, and `400 ImportErrorResponse` examples for missing or invalid import `domainType`. Import commit payload documentation now treats `domainType` as required business classification input and saves it on newly imported table/vector resources.
- Mock examples: `mock/prism/examples/30-catalog-vector.json`
- Frontend reason: The top workspace navigation needs typed geo/non-geo dropdown choices that can synchronize with the left data panel without hand-written DTOs or hidden backend fields.
- Backend implementation notes: Add `DataResource.domain_type`, serialize it as `domainType`, filter resources by valid domain codes, reject missing or invalid import domain codes, store import payload domain types, and default raster catalog sync to `remote_sensing` and scanned gene files to `genome`.
- Verification: run OpenAPI lint, regenerate API types, rebuild Prism mock, run frontend typecheck, Django check, and focused backend domain filter tests.
- Result: Backend and frontend type-level verification passed. Broader catalog tests still hit existing Windows file-lock cleanup failures on GeoPackage/SQLite files, so the domain filter was verified with a focused test class that does not touch those files.

## API-20260630-001 - Built-In Role Permission Baseline

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET/POST /api/groups/`, `POST /api/groups/{groupId}/`
- Change type: permission behavior | mock data | documentation clarification
- OpenAPI change: Documents the five built-in roles (`超级管理员`, `平台管理员`, `科研用户`, `普通用户`, `游客`), protected-role delete/rename restrictions, superadmin-only locked permissions, and the `400 ErrorResponse` cases for protected role changes.
- Mock examples: `mock/prism/examples/10-admin-auth.json`
- Frontend reason: The authorization page needs a simpler operational role model where platform administration and data/system administration are merged, while normal users can still upload and view allowed data.
- Backend implementation notes: Create platform-admin and research-user built-in groups, migrate untouched legacy normal-user defaults to the narrower baseline, protect all built-in role names from delete/rename, keep superadmin permissions fully locked, and preserve manually customized role permissions.
- Verification: run OpenAPI lint, regenerate API types, run API change request check, frontend typecheck, Django check, and focused core permission/API tests.
- Result: Verified with direct OpenAPI lint, OpenAPI type generation, API change request check, Prism mock bundle injection, frontend TypeScript checks, Django system check, and focused core permission/API tests. The broader `test_api.py` file still contains unrelated Windows TOML/path compatibility failures when run as a whole.

## API-20260701-001 - Vector Symbolization Unique Value Contract

- Status: ContractReady
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/layers/`, `POST /api/admin/data/resources/{id}/`
- Change type: response fields | request body | mock data | documentation clarification
- OpenAPI change: Defines `VectorSymbolization`, `VectorRenderer`, `UniqueValueRenderer`, and `UniqueValueSymbolClass` for the existing `symbolization` field while keeping `additionalProperties` compatibility with legacy loose style JSON. The schema documents category value merging through `classes[].values`, `gm-*` platform icon IDs, and the `germplasm.dna-sex-tree.v1` default template metadata.
- Mock examples: `mock/prism/examples/30-catalog-vector.json` adds a germplasm DNA point layer whose `symbolization.renderer` classifies `性别` into female, male, and other categories with tree icons.
- Frontend reason: The map symbolization editor needs typed, documented unique-value rules so business default templates and user edits share one contract instead of ad hoc frontend-only objects.
- Backend implementation notes: No new endpoint or database migration is required; existing JSONField storage and serializers should pass the documented `symbolization` object through unchanged. Admin save-visualization payloads should continue to accept this JSON shape under the existing `core.custom_symbolization` UI permission and existing resource-management permissions.
- Verification: run OpenAPI lint, regenerate API types, rebuild Prism mock, run focused frontend symbolization tests, frontend typecheck, and backend catalog layer serialization tests.
- Result: Pending implementation and verification.

## API-20260704-002 - Vector Export Attribute Table Packaging

- Status: BackendReady
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/catalog/export/`, `POST /api/catalog/export/async/`, `GET /api/catalog/export/jobs/{job_id}/download/`
- Change type: documentation clarification | archive content behavior
- OpenAPI change: Clarifies that vector export ZIP files include the requested spatial file plus a same-name `*-attributes.csv` file generated from `GeoJSONFeatureCollection.features[].properties`; request and response schemas are unchanged.
- Mock examples: N/A; binary ZIP response schema is unchanged.
- Frontend reason: The spatial query result export should provide a directly usable attribute table instead of only a GeoJSON file.
- Backend implementation notes: While packaging each vector item, keep existing GeoJSON/Shapefile output and add a UTF-8 BOM CSV attribute table with one row per feature and stable property-column order.
- Verification: run OpenAPI lint, regenerate API types, rebuild Prism mock, run frontend typecheck, and run focused backend export tests.
- Result: Verified with direct OpenAPI lint, OpenAPI type generation, API change request check, Prism mock bundle injection, frontend TypeScript checks, backend export unit tests, and backend export API integration tests.

## API-20260710-003 - Recommended Vector Symbolization Templates

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/catalog/resources/{id}/visualization-summary/`
- Change type: response fields | schema fields | mock data | documentation clarification
- OpenAPI change: Adds required `recommendedSymbolizations` to `ResourceVisualizationSummaryResponse`, defines `RecommendedSymbolizationTemplate`, and documents `GraduatedRenderer.templateId/businessType` so unique-value and graduated recommended templates share the same metadata contract.
- Mock examples: `mock/prism/examples/30-catalog-vector.json` includes field-survey habitat and importance recommended symbolization examples under the visualization summary response.
- Frontend reason: The symbolization panel needs typed recommended default templates for germplasm, individual, population, community, and field-survey vector resources, while still allowing users to customize the applied style.
- Backend implementation notes: Generate recommendations from the existing visualization summary read path using resource `domainType`, field alias matching, category counts, numeric distributions, and the platform `gm-*` icon whitelist. No new write endpoint or database migration is required.
- Verification: run OpenAPI lint, regenerate API types, run frontend TypeScript checks, run focused frontend symbolization tests, run backend template unit tests, and compile the touched backend modules.
- Result: Verified with direct Redocly lint, direct OpenAPI type generation, frontend TypeScript checks, `src/symbolization.test.ts`, `backend/tests/unit/catalog/test_symbolization_templates.py`, and Python module compilation. `pnpm run check:api` was not run because the script contains `rm -rf`, which conflicts with the workspace deletion policy.

## API-20260713-002 - Raster Package Import And Persistent Jobs

- Status: BackendReady
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/raster/import/preview/`, `POST /api/raster/import/`, `GET /api/raster/jobs/{job_id}/`, `POST /api/raster/render/`, `GET /api/raster/tiles/{dataset_id}/{style_hash}/{z}/{x}/{y}.png`
- Change type: new endpoint | multipart request | response fields | persistence | permission behavior | mock data
- OpenAPI change: Adds server-side raster package preview, multi-file `files + payload` import, DAT/BSQ/BIL/BIP + HDR and VRT dependency semantics, persistent job `stage`, source package metadata, raster kind, resampling, access groups, and display rules.
- Mock examples: `mock/prism/examples/40-raster.json`
- Frontend reason: IMG/VRT/ENVI files must not be parsed as GeoTIFF in the browser; users need GDAL-backed package validation, companion-file upload, RGB band selection, resampling, permissions, and refresh-safe job status.
- Backend implementation notes: Preserve the legacy single-file field, store new packages under UUID directories with a manifest and SHA256, persist sparse task checkpoints and raster styles in the metadata database, publish catalog records in a short transaction, and restrict server-path imports to `raster/original`.
- Verification: regenerate OpenAPI types, rebuild Prism examples, run frontend typecheck/browser tests, Django checks, raster unit/integration tests, and a real GeoTIFF preview/import smoke test.
- Result: Verified with OpenAPI lint and generated types, bundled YAML/HTML API documentation, Prism example rebuild, API change-request validation, Django system check, the applied raster database migration, 113 raster unit/integration tests, frontend TypeScript checks, 162 frontend tests, and a Vite production build. The provided `Tarim_worldview_1.tif` sample was preflighted as GTiff, 512 x 512, 8 bands, EPSG:32645, with the WorldView natural-color 5/3/2 preset. Browser-mode tests could not start because the configured Playwright Chromium executable is not installed. `makemigrations --check` also reports an unrelated pre-existing `core.BackupRun` index-name drift; no raster migration drift was reported.

## API-20260713-003 - Inventory Business Type Groups

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/admin/data/resources/`
- Change type: response field | mock data | documentation clarification
- OpenAPI change: Adds nullable `AdminDataResource.domainType` and clarifies that `inventoryGroups` / `inventoryGroupId` represent user-created custom groups, while “全部数据” and the ten business-type groups are derived system groups.
- Mock examples: `mock/prism/examples/20-admin-dashboard-data.json`
- Frontend reason: The inventory page needs stable automatic grouping by the ten import business types without duplicating those types as manually maintained database groups.
- Backend implementation notes: Serialize `DataResource.domain_type` as `domainType`; no model or migration change is required. Historical blank values remain null and are displayed under “其他类型”.
- Verification: run OpenAPI lint/type generation, API change-request validation, focused backend admin-resource tests, frontend inventory browser tests, and frontend typecheck.
- Result: OpenAPI lint and generated types passed; the API change request and Prism example injection passed; all 17 admin data-resource backend tests passed; frontend formatting, full TypeScript checking, and the production build passed. The browser test could not start because the configured Playwright Chromium executable is not installed.

## API-20260715-001 - Inventory Full Statistics And Group Summaries

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/admin/data/resources/`
- Change type: response fields | aggregate semantics | mock data | documentation clarification
- OpenAPI change: Adds required `summary` and `groupSummaries` to the admin data-resource list response. Both are calculated over the complete filtered and permission-scoped queryset, while `items` remains paginated.
- Mock examples: `mock/prism/examples/20-admin-dashboard-data.json`
- Frontend reason: The inventory page currently compares the full `total` with active/inactive counts derived from only the current page, and business/custom groups are sized from paginated items, making existing data appear missing.
- Backend implementation notes: Aggregate total, status, restricted-access, size, item-count, business-type groups, and custom groups before applying pagination. Keep permissions and filtering identical to the item queryset.
- Verification: run OpenAPI lint/type generation, API change-request validation, focused admin data-resource aggregation tests, frontend typecheck/build, and inventory browser tests when Chromium is available.
- Result: OpenAPI lint and generated types passed; API change-request validation, generated API documentation, and Prism example injection passed; all 19 admin data-resource backend tests passed; frontend TypeScript checking and the production build passed. The inventory browser test could not start because the configured Playwright Chromium executable is not installed.

## API-20260722-002 - Result Artifact Registration And Delivery

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET/POST /api/catalog/results/`, `GET /api/catalog/results/{resultId}/file/`
- Change type: new endpoint | multipart request | permission behavior | binary response
- OpenAPI change: Adds typed result source, result type and draft/published status enums; defines multipart `file + payload` registration, permission-scoped listing, preview and download variants.
- Mock examples: N/A; the page aggregates authenticated live results and retains an explicit empty state.
- Frontend reason: The data import page needs an independent “成果文件” target, and the成果展示 page must combine platform map compositions, platform analysis results and directly imported results without converting files into data resources.
- Backend implementation notes: Store files under `app_data/exports/results/{uuid}/`; allow PNG/JPG/PDF preview, allow CSV/XLSX download only, reuse data-upload permission for registration and专题成果发布 permission for direct publication, and enforce role visibility.
- Verification: OpenAPI generated client updated; five backend integration tests cover draft upload, publish permission, audience visibility, preview/download and invalid category/extension/size; frontend typecheck and browser navigation/import tests are included.
- Result: Backend integration tests and frontend TypeScript checks pass. Browser tests use installed system Chrome when the matching Playwright browser bundle is unavailable.

## API-20260723-001 - Dashboard Business Taxonomy Distribution

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/admin/dashboard/`
- Change type: response fields | aggregate semantics | UI statistics
- OpenAPI change: Extends `AdminDashboardDataOverviewScope` with required `categoryBreakdown` and `unclassifiedCount`, plus typed big-category and leaf-category aggregate schemas.
- Mock examples: `mock/prism/examples/20-admin-dashboard-data.json`
- Frontend reason: The data overview needs to distinguish physical resource formats from the authoritative four-major/fifteen-minor business classification system and display both distributions without mixing their meanings.
- Backend implementation notes: Aggregate the taxonomy over the same permission-scoped queryset used by each “我可见”/“我上传” scope. Return every active taxonomy root and leaf in configured order, including zero-count nodes, while keeping unclassified resources explicit.
- Verification: run OpenAPI lint/type generation, API change-request validation, focused dashboard integration tests, frontend typecheck/tests, and production build.
- Result: Verified with generated OpenAPI types, focused backend dashboard tests, frontend TypeScript checks, browser component tests, and production build.

## API-20260723-002 - Unified Result Permissions And Management

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET/POST /api/catalog/results/`, `GET/POST /api/catalog/results/{resultId}/`, `GET /api/catalog/results/{resultId}/file/`, authenticated user permission responses
- Change type: permission behavior | request schema | response fields | new management endpoint | destructive action | mock data
- OpenAPI change: Replaces borrowed data-resource/map-composition permissions with dedicated result view/import/download/publish/delete permissions; requires imported results to publish immediately with at least one audience role; adds result publish, unpublish and permanent delete actions; returns per-object capabilities, publisher and selectable access groups.
- Mock examples: `mock/prism/examples/55-results.json`
- Frontend reason: Result import must not create drafts without a release path, and the former topic-management page must manage both workbench map compositions and imported result artifacts without conflating their permissions.
- Backend implementation notes: Keep `draft` only as the state for historical or deliberately unpublished artifacts; reject new draft imports; allow owners and platform management subjects to publish/unpublish/delete when their dedicated permission allows it; remove only the explicitly addressed result file during delete and write an operation log.
- Verification: run OpenAPI lint/type generation, API change-request validation, Prism mock build, result artifact and core permission backend tests, result import/management browser tests, frontend typecheck, and production build.
- Result: Verified with OpenAPI lint and generated clients, tracked API change validation, Prism mock injection, Django migration/system checks, 37 focused permission/result backend tests, 33 frontend browser tests, frontend typecheck, and production build. The broader existing core API suite retained 11 unrelated Windows TOML/path separator failures while 83 tests and 2 subtests passed.

## API-20260724-001 - Platform Brand Naming Alignment

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/login/overview/`
- Change type: response value semantics | mock data | documentation clarification
- OpenAPI change: Keeps the existing `LoginOverviewPlatform` schema unchanged while updating the documented English name, abbreviation and edition examples to the approved global platform identity.
- Mock examples: `mock/prism/examples/05-login-overview.json`
- Frontend reason: The former `CAPFED` abbreviation reflected the earlier Central Asia naming and no longer matched the current global Chinese and English platform name shown in the navigation and login interface.
- Backend implementation notes: Return `Global Populus euphratica Forest Ecosystem Conservation Data Sharing Platform`, `GPEDSP` and `GPEDSP · WebGIS Research Edition` from the public login overview without changing authentication, response fields or caching behavior.
- Verification: regenerate/check OpenAPI types, rebuild Prism examples, run API lint and change-request validation, run the focused backend login-overview test, frontend typecheck/browser test and production build.
- Result: Verified with OpenAPI lint and generated clients, Prism bundle/example injection, API change-request validation, the focused Django login-overview test, the focused frontend browser test, TypeScript checks, production build, responsive browser inspection at 1280 px and 1024 px, and a 14-page PDF render review.

## API-20260729-001 - Public Guest Audience Inheritance

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: guest login; catalog resources, layers, workspaces, map compositions and result artifacts read endpoints
- Change type: permission behavior | documentation clarification
- OpenAPI change: Clarifies that selecting the built-in `游客` access role marks an object as public: it remains available through a guest session and is also inherited by every authenticated role.
- Mock examples: N/A; response schemas and example payloads are unchanged.
- Frontend reason: Logging in as a normal or research user must not hide content that is already visible to a guest.
- Backend implementation notes: Resolve the guest group as an additional effective audience for authenticated users across the shared access-filter helpers and the workspace/result/composition querysets. Keep owner and administrator bypass rules unchanged.
- Verification: run OpenAPI lint/type generation and API change-request validation; run focused concurrent guest-session and public-resource inheritance integration tests; verify resource loading through real browser sessions for guest, ordinary, research, platform-admin and superadmin roles.
- Result: Verified with focused backend and frontend browser tests plus real local role-based UI regression.

## API-20260730-003 - Real Non-Geographic Analysis And Query

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/catalog/resources/{id}/nongeo-analysis/`, `POST /api/catalog/resources/{id}/nongeo-query/`
- Change type: new endpoint | request body | response fields | permission behavior
- OpenAPI change: Adds typed field profiles, real row summaries, categorical/numeric distributions, correlation matrices, table previews and paginated/sorted table-query schemas; documents 10,000-row analysis sampling, 1–500 query limits and standard 400/401/403/404 responses.
- Mock examples: N/A; the non-geographic workspace consumes authenticated live resources and has explicit loading/error/empty states.
- Frontend reason: Selecting different table or gene resources must show each resource's own records and statistics instead of shared demo values, with stable pagination and safe sorting for the table view.
- Backend implementation notes: Read SQLite platform tables or supported CSV/TSV/Excel/FASTA/FASTQ/VCF/GFF/GenBank files; require `core.query_data` plus object access; cap direct-file analysis at the smaller of the runtime upload limit and 64 MB; validate SQLite sort fields against the real column allowlist.
- Verification: run OpenAPI lint/type generation and API change tracking; run focused non-geographic integration tests for resource-specific statistics, pagination/sort injection rejection, access permissions and FASTA parsing; run the role-based non-geographic browser flow.
- Result: Verified against the implemented real-data endpoints and focused backend/frontend role-flow tests.

## API-20260730-004 - Maintenance Scan Permission Boundaries

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/catalog/scan/`, `POST /api/raster/scan/`
- Change type: permission behavior | status code | concurrency semantics
- OpenAPI change: Documents `catalog.add_dataresource` for catalog scans, `raster.manage_raster_dataset OR catalog.change_dataresource` for raster scans, catalog 409 conflicts and raster active-job reuse; explicitly excludes ordinary browsing users and guests.
- Mock examples: N/A; maintenance scans are authenticated live operations and do not need deterministic Prism payloads.
- Frontend reason: Scan controls must follow the actual import/inventory operator roles and must not be exposed as ordinary resource refresh actions to users who cannot maintain storage.
- Backend implementation notes: Keep catalog scans single-flight with a 409 conflict; reuse an existing queued/running raster scan job in the same process; enforce permissions before scheduling any filesystem discovery.
- Verification: run OpenAPI checks and focused catalog/raster permission and concurrent-scan tests; verify scan actions stay hidden or disabled in guest and ordinary-user browser sessions.
- Result: Verified against the implemented permission guards and concurrency behavior.

## API-20260730-005 - Result File Authenticity And Safe Delivery

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/catalog/results/`, `GET /api/catalog/results/{resultId}/file/`
- Change type: validation | permission behavior | binary response headers
- OpenAPI change: Adds the required view permission to direct-publication imports; documents true-content validation for PNG/JPG/JPEG/PDF/CSV/XLSX, trusted server MIME assignment, `nosniff` on all successful file responses and preview-only sandbox CSP/referrer protection.
- Mock examples: N/A; multipart file authenticity and binary security headers are covered by backend integration tests rather than JSON mocks.
- Frontend reason: Renaming an arbitrary file to an allowed extension must not create a published artifact, and browser previews must not execute or leak content under attacker-controlled MIME metadata.
- Backend implementation notes: Decode image content with Pillow, verify PDF boundaries, restrict CSV encodings/NUL content, validate XLSX ZIP structure and expansion limits, then derive MIME server-side; allow previews only for PNG/JPG/JPEG/PDF and require `catalog.download_resultartifact` for artifacts.
- Verification: run OpenAPI generation/checks and focused result-artifact tests for disguised files, corrupt PDF/XLSX/CSV, trusted MIME, nosniff, CSP/referrer headers and preview/download permission separation.
- Result: Verified against the hardened upload and file-delivery implementation and integration coverage.

## API-20260730-006 - Role Second Authorization And Protected Principals

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET/POST /api/groups/`, `POST /api/groups/{groupId}/`, `POST /api/users/`, `POST /api/users/{userId}/*`
- Change type: permission behavior | validation | protected-account semantics
- OpenAPI change: Documents that creating roles and any role update containing `permissions` require `core.manage_feature_permissions` in addition to `core.manage_auth`; records immutable built-in names, locked/hidden superadmin behavior, guest-only role ownership and platform-admin target protection.
- Mock examples: N/A; response shapes are unchanged and the restrictions depend on the authenticated principal.
- Frontend reason: Authentication administrators who can maintain membership must not automatically gain authority to broaden feature permissions, and protected system/management accounts must not expose actions that the backend will reject.
- Backend implementation notes: Reject `permissions` writes without the second authorization; keep all five built-in roles non-deletable/non-renamable; reserve the guest role and account; restrict platform-admin assignment and all mutations of platform-admin targets to superadmins.
- Verification: run OpenAPI and API-change checks, focused core authorization tests, and real browser role flows for superadmin, platform admin, research user, ordinary user and guest.
- Result: Verified against focused backend authorization coverage and the completed 49-case role-based browser regression.

## API-20260730-007 - Same-Origin Default SDK Endpoint

- Status: Verified
- Owner: Frontend implementer
- Endpoints: all generated browser SDK operations
- Change type: client transport metadata | CSP compatibility | deployment safety
- OpenAPI change: Makes `/` the first server entry so generated clients default to the platform origin; keeps the direct local backend and external API server entries as explicit override targets.
- Mock examples: N/A; request and response payloads are unchanged.
- Frontend reason: Regenerating the SDK previously restored `http://localhost:8000` as its default base URL. During browser hot reload, requests could then bypass the platform proxy and be blocked by `connect-src 'self'`, breaking resource, workspace and composition loading.
- Backend implementation notes: No endpoint behavior changes. Browser calls continue through the same-origin `/api` reverse proxy; standalone clients may explicitly select another documented server URL.
- Verification: regenerate and compare the SDK, run API change validation and frontend type checks, then load catalog/workspace requests in a fresh browser session and confirm no CSP violations.
- Result: Verified with a generated client that has no hard-coded localhost base URL and a fresh same-origin browser regression.

## API-20260730-008 - Memory-Safe Query And Export Boundaries

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/catalog/resources/{id}/query/`, `POST /api/catalog/export/`, `POST /api/catalog/export/async/`
- Change type: status code | request-size validation | concurrency behavior | binary delivery behavior
- OpenAPI change: Documents 413 for oversized query/export JSON, 503 plus `Retry-After` when the per-process vector-query slot is unavailable, and the 10 MiB export request limit. Successful response schemas remain unchanged.
- Mock examples: N/A; saturation, bounded stream reads and file-response cleanup require backend tests rather than deterministic mock payloads.
- Frontend reason: A stalled 30,000-feature query or large embedded export request previously created several simultaneous GeoDataFrame/JSON/ZIP copies and could exhaust a 4 GB server; clients need explicit backoff and size-limit semantics.
- Backend implementation notes: Limit the production query result count to 5,000; read spatial candidates in fixed chunks; validate geometry in one pass; serialize exports to a temporary path; stream ZIP responses; bound request reads even without `Content-Length`; preserve the existing in-memory export helper only as a compatibility wrapper outside production endpoints.
- Verification: run OpenAPI lint/generation/change checks, focused catalog query/export/body-limit tests, the complete backend suite, frontend typecheck/tests/build and Docker entrypoint/image checks.
- Result: OpenAPI lint/generation/change checks, focused query/export/request-limit tests, complete raster regression, complete frontend tests/typecheck/build and Django system check passed. The complete backend run exposed only three compatibility-message assertions; the original message was restored and the affected parameterized endpoints passed on rerun.

## API-20260731-001 - Bounded And Persistable Admin Runtime Limits

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `POST /api/admin/settings/`
- Change type: request validation | error response | deployment safety
- OpenAPI change: Adds partial update schemas and server-enforced ranges for upload size, query results, raster side length and raster task timeout; documents JSON 500 when the source TOML cannot be atomically replaced.
- Mock examples: N/A; validation boundaries and filesystem replacement failures are covered by focused backend and frontend tests.
- Frontend reason: Editable descriptions submit only the active field, so the page must merge it with current settings before saving and must not advertise values that the server or small-memory deployment cannot safely support.
- Backend implementation notes: Enforce 1–120 MB, 100–10,000 results, 1–12,000 pixels and 10–600 seconds before touching the TOML; keep atomic replacement and require a writable directory mounted at `/config` instead of a single-file bind mount.
- Verification: Run OpenAPI generation/lint/change checks, focused core admin-settings tests, frontend settings tests, typecheck and build.
- Result: Passed. All 384 frontend unit tests, 48 relevant browser tests and all 12 backend admin-settings integration tests passed; TypeScript, OpenAPI lint/generation/change checks, API documentation, Prism bundle generation and the production build passed. A real Chrome session confirmed four selectable basemaps, successful HTTP 200 tile requests from both `img_w` and `cia_w`, visible satellite imagery with Chinese labels after pan/zoom, and a successful switch back to Mapbox. OpenAPI lint retains only six pre-existing unused-component warnings.

## API-20260802-001 - One-GiB Disk-Backed Upload Ceiling

- Status: Verified
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/bootstrap/`, `GET /api/admin/settings/`, `POST /api/admin/settings/`, raster/vector/table/result/map-composition upload endpoints
- Change type: request validation | response constraint | deployment safety
- OpenAPI change: Raises the server-enforced `uploadMaxMb` maximum from 120 to 1024 MB and documents lower workflow-specific memory-safety limits; response shapes and status codes are unchanged.
- Mock examples: N/A; numeric boundaries, invalid hot-edited upload-limit fallback and disk-backed server limits are covered by focused tests.
- Frontend reason: Large GeoTIFF interpretation results can exceed 120 MB, while the small-memory production server must not expose GeoPandas or table parsers to 1 GiB in-memory workloads. The browser rejects table and vector files above their 16 MB and 120 MB parser-specific limits before upload.
- Backend implementation notes: Reuse one 1–1024 MB constant in startup config, runtime TOML reads and admin validation; give Waitress a 1152 MiB multipart ceiling and 720-second channel timeout; retain Django 10 MiB request/2 MiB file-memory thresholds; cap vector imports at `min(uploadMaxMb, 120)`, keep the existing 16 MB table parser limit, and preserve the former global protection for in-memory map-composition decoding with an independent 128 MB PNG ceiling. Deployment samples remain at the safe 64 MB default, and the mounted production TOML must be changed explicitly after the new image passes health checks.
- Verification: Run OpenAPI lint/generation/change checks, focused config/admin/vector/entrypoint tests, the admin browser regression, frontend typecheck and production build.
- Result: Passed. All 583 backend tests, all 305 frontend unit tests and all 43 admin browser tests passed; OpenAPI generation/lint/change tracking, generated-client comparison, API documentation and Prism bundle generation passed; TypeScript, focused frontend lint/format and the production build passed. OpenAPI lint retains only six pre-existing unused-component warnings. The repository-wide frontend format check still reports 139 pre-existing files outside this change, including untracked `.playwright-cli` records; the three edited frontend files pass focused formatting and lint checks.

## API-20260806-001 - Tianditu Imagery Default Basemap

- Status: BackendReady
- Owner: Frontend/backend implementer
- Endpoints: `GET /api/bootstrap/`, `GET /api/admin/settings/`, `POST /api/admin/settings/`
- Change type: accepted configuration value | response enum documentation
- OpenAPI change: Extends `MapConfig.defaultBasemap` with `tianditu-imagery` for the Tianditu spherical-Mercator `img_w + cia_w` imagery and Chinese-label combination; response fields, authentication and status codes are unchanged.
- Mock examples: N/A; existing `satellite` examples remain valid and the new accepted value is covered by focused frontend catalog and backend settings tests.
- Frontend reason: The geographic workbench now exposes Tianditu imagery as the fourth formal basemap and administrators need to select the same canonical ID as the platform default.
- Backend implementation notes: Accept and persist only the canonical `tianditu-imagery` value through the existing TOML-backed settings path; reuse the existing public Tianditu browser Key and do not add a proxy, credential field or database migration.
- Verification: Run OpenAPI lint/generation/change checks, focused frontend basemap/provider/browser tests, the focused backend settings test, TypeScript and the production build, then exercise the switch in a real browser.
- Result: Pending final verification.


## API-20260918-001 — 项目标签、公开内容与布局保存

- Status: Verified；后端 601 项 + 52 子测试、前端 398 单元/156 浏览器、构建与契约通过；明细见 `platform-upgrade-acceptance.md`。
- Owner: 本任务顺序承担契约、后端、前端与验证，完成跨层交接。
- Endpoints: 新增 `/api/projects/`、`/api/content/`；项目范围参数覆盖业务 API；默认项目资源、查询、渲染和已发布成果支持匿名阅读；地图出图稿保存新增 expectedUpdatedAt。
- Contract: `projectTagId` 明确区别于地图工程 projectId；all 只读；ProjectTagList 返回 items/assignableItems 与管理能力；文章 revision、封面/图注/附件操作；文件链接带标签参数。OpenAPI 同步参数、公开 security、错误和响应。
- Frontend: 顶部项目切换与管理、六方向科普和新闻、工作台默认入口、拖拽制图保存与冲突反馈。DTO 由 `frontend/src/api/generated/` 生成。
- Backend: 项目模型、范围 manager、外键/M2M/快照约束、默认公开与私有成员授权；原功能权限保留；匿名 render 任务绑定会话；任务合并按项目，启动扫描默认作用域；内容媒体跟随发布状态。
- Mock: `mock/prism/examples/90-platform-upgrade.json`；Prism bundle 从规范重新生成。
- Validation: 匿名/成员/管理员/超管、跨项目对象与任务、撤权、默认保护、附件事务、版本冲突，以及 OpenAPI 生成/比较/变更检查/文档/Mock。


## API-20260918-002 — 分类与项目授权复核

- Status: Verified；后端 604 项/52 子测试、前端 401 单元/156 浏览器、构建及契约通过。
- Owner: 本任务顺序完成契约、后端、前端交接。
- Endpoints: catalog/standards 资源、工程、成果及导入下载接口；projects/assignments；content/articles。
- Contract: 数据分类改 spatial/non_spatial；资源依据解析后的空间类型与坐标信息自动归类。AdminDataResource 返回 projectTagId。项目成员关系是业务对象访问范围，角色只负责操作权限，历史 accessGroupIds/audienceGroupIds 保留存储兼容但不授权或限制对象阅读。草稿仍限作者或项目内管理员。仅超管维护和分配标签；默认标签自动可读。科普请求固定默认项目 1，禁止创建私有科普；新闻保持项目隔离。
- Frontend reason: 去除胡杨分类和角色共享误导，展示对象所属标签、创建目标标签；切项目科普保持可见。
- Mock: mock/prism/examples/90-platform-upgrade.json 和分类示例随新结构更新。
- Verification: 成员/非成员/超管的列表、详情、查询、工程与成果文件；新用户默认、撤权、切项目科普；真实退出跳转与默认底图。


## API-20260918-003 - 上传显式指定所属项目标签

- Status: Verified
- Owner: 本任务按契约、后端、前端、测试顺序实施。
- Endpoints: POST /api/catalog/import/commit/、POST /api/catalog/vector-import/commit/、POST /api/raster/import/、POST /api/catalog/results/
- Change type: required request header; project authorization
- OpenAPI change: X-Project-Id 改为必填，记录缺失/空值/all 的 400 与未授权项目的 404；补齐上传错误响应示例。
- Mock examples: mock/prism/examples/30-catalog-vector.json、40-raster.json、90-platform-upgrade.json
- Frontend reason: 上传表单必须直接指定归属，预检、提交与任务查询不能被顶部项目覆盖；库存可按标签查看。
- Backend implementation notes: 中间件对四个上传 POST 检查显式请求头，复用既有项目成员鉴权、存储上下文和后台任务项目持久化；没有数据库迁移。
- Verification: 后端项目权限/导入/成果/栅格任务回归；客户端两个上传传输分支；表单与库存浏览器验证；真实超管和刘洋账号。
- Result: 后端 194 passed + 13 subtests、前端 399 单元 + 66 浏览器；构建、API 生成/校验/文档/Mock 通过。真实上传到管道院，默认项目不可见，库存按项目显示，临时资源与独立验证会话已清理。

- 表格提交、矢量提交、栅格提交及成果导入的 POST 必须带 `X-Project-Id`，不再允许静默缺省；缺失、空值或 all 返回 400。未登录仍返回 401，未授权或不存在的目标返回 404。
- 上传页面独立提供必填“所属项目标签”，初始为默认（ID=1），用户在选择文件前确定标签。表单选择优先于顶部浏览项目；预检、校验、重名检查、提交和后台任务轮询保持同一项目。
- 标签选项来自 GET /api/projects/ 的 items；超管能选所有标签，普通用户只能选默认及本人被授权的有效标签。服务端每次重新验证权限，撤权立即生效。
- 每份数据仍属于一个项目；“默认”是最低初始归属，不给私有数据额外添加公共标签。数据、关联图层和导入文件均按所选项目落库/落盘。
- 存量数据增加独立项目列、详情归属和项目筛选；既有数据/工程/文件的归属保留。用户项目分配在项目管理完成，资料夹不授予项目访问权限。
- 受影响接口：POST /api/catalog/import/commit/、/api/catalog/vector-import/commit/、/api/raster/import/、/api/catalog/results/。Mock 示例：mock/prism/examples/90-platform-upgrade.json。前端生成类型位于 frontend/src/api/generated/。
- 验收：默认账号、多个标签成员与超管的选项；顶部项目不同于上传目标；跨项目列表/文件拒绝；上传期间撤权；缺失标签拒绝；异步栅格任务保持归属。

## API-20260918-004 - 单项目操作与平台公共内容

- Status: Verified
- Owner: Full-stack implementer; contract → backend → frontend → testing handoff
- Endpoints: 项目范围覆盖的业务 API、`/api/projects/*`、`/api/content/*`
- Change type: project validation | public content permissions | project name
- OpenAPI change: 业务 API 读写仅接受一个项目，`all` 返回 400；内容接口与附件忽略项目 header/query，已发布内容平台公开，草稿、下架和维护仍受内容管理权限约束。内置项目显示为“公开”。
- Mock examples: `30-catalog-vector.json`, `40-raster.json`, `90-platform-upgrade.json`
- Frontend reason: 项目管理归入后台，用户每次在单个项目操作，团队动态与科普均不依赖业务项目成员关系。
- Backend implementation notes: 保留内置 ID=1/code=default 和业务文件路径；迁移文章/附件到项目 1，保留正文、状态、物理文件地址并处理 seed_key 冲突；数据库约束禁止新建私有内容。
- Verification: 业务 all 拒绝、权限隔离、公共内容状态/文件权限、真实历史迁移、旧会话恢复、后台路由权限、浏览器与构建/API 检查。
- Result: 完整后端 654 passed + 52 subtests、前端 399 单元 + 83 浏览器；迁移、构建、契约与生成检查通过。超管/刘洋/匿名真实页面验收通过，13 篇内容及 22 个附件保留。详见 2026-09-18-public-project-navigation-acceptance.md。

## API-20260918-005 - 制图底图不得静默替换为简化背景

- Status: Verified
- Owner: Full-stack implementer; contract → backend → frontend → testing
- Endpoints: `GET /api/map/thumbnail-tiles/{z}/{x}/{y}.png`
- Change type: optional query parameter | error response | rendering correctness
- OpenAPI change: 新增 purpose=thumbnail/export；export 模式仅返回真实瓦片或缓存，上游失败返回 503/no-store/Retry-After: 2，非法 purpose 返回 400。
- Mock examples: `90-platform-upgrade.json` 的制图底图 503 示例。
- Frontend reason: 缩略图接口上游失败时生成简化世界地图并返回 200，制图误认为底图完整并缓存，主图与低层级鹰眼表现不一致。
- Backend implementation notes: 普通缩略图行为保留；制图使用严格模式和 10 秒上游超时，缓存目录不变，连接错误不暴露凭证。
- Verification: 缓存命中、上游失败拒绝简化替代、失败后恢复、参数验证；真实浏览器预览及 300 DPI 导出、故障注入、构建与契约检查。
- Result: 后端 9 项瓦片回归、前端 399 项单元测试及构建/契约检查通过。真实工程预览与 3508×2480 输出显示 Mapbox 影像；503 故障注入成功阻止错误出图。见 2026-09-18-composition-basemap-fix.md。

## 2026-09-18 A01–A14 审核整改契约交接

本轮由同一执行者依次承担契约、后端、前端和验收职责。先更新 OpenAPI 与生成类型，再实现后端和前端；不修改 R01–R05 暂缓事项。当前规则见 current-platform-rules.md。

工程列表增加 q/limit/offset 和 total，仅返回 WorkspaceSceneSummary；详情返回 snapshot。普通/后台工程更新必须传 expectedUpdatedAt（删除除外），冲突 409。发布不再要求 audienceGroupIds，旧角色字段仅作为历史元数据。附件上传为 24 小时暂存，上传者独占预览；保存用 commitAssetIds 与 revision 同步提交，DELETE assets/{id} 撤销暂存附件。底图代理增加受控 basemap/labels 参数和服务商层级上限。非法 JSON、字段类型和日历日期返回标准 400。Mock：90-platform-upgrade.json、30-catalog-vector.json。

验证要求：过期保存不落库；暂存附件匿名不可读；取消与过期清理；跨项目不可读写；摘要不含快照；各底图不互相替换；独立目录恢复校验。

## API-20260918-006 - 审核整改：工程版本、分页、暂存附件与底图

- Status: Verified
- Owner: Single full-stack implementer, contract → backend → frontend → verification
- Endpoints: `/api/catalog/workspaces/*`, `/api/admin/workspaces/*`, `/api/content/*`, `/api/catalog/map-compositions/*`, `/api/map/thumbnail-tiles/*`
- Change type: concurrency | pagination | attachment staging | basemap selection | semantic cleanup
- OpenAPI change: 工程列表摘要分页；更新 expectedUpdatedAt 与 409；附件 pending/commitAssetIds/DELETE；底图 basemap/labels；历史角色字段废弃说明；分类示例 spatial/non_spatial。
- Mock examples: `30-catalog-vector.json`, `90-platform-upgrade.json`
- Frontend reason: 防止覆盖编辑、提前公开附件、错误底图及大快照反复加载；界面按单项目规则提供功能。
- Backend implementation notes: 工程条件更新适用于 SQLite；附件提交与文章 revision 原子写入；暂存附件上传者独占且 24 小时过期；底图代理仅接受固定标识。备份已在迁移前完成独立恢复核验。
- Verification: 全量测试、隔离备份恢复、真实浏览器制图、输入与权限回归；详见本轮验收文档。
- Result: 后端 673 项及 52 子测试通过；工程冲突、摘要分页、暂存附件、非法输入和底图选源回归通过。实际 Mapbox 影像预览、300 DPI 导出、街道底图快照恢复、503 故障注入通过，现有草稿未改变。前端最终结果及备份恢复记录见 2026-09-18-a-items-acceptance.md。

## API-20260919-001 - 通用计算中心

- Status: Verified
- Owner: Full-stack implementer; contract → backend → frontend → testing
- Endpoints: `/api/compute/*`
- Change type: new algorithm registry | durable tasks | result adapters
- OpenAPI change: 算法分类、算法/版本/包、运行环境、数据选择、预检、任务、下载/预览/异步入库。公开算法复用，输入/结果同项目。
- Mock examples: `95-compute.json`
- Frontend reason: 管理员可按统一规范新增算法，页面由版本清单生成，不增加专用接口。
- Backend implementation notes: 上传包不在Web进程执行。独立worker只接受Linux容器，草稿须隔离试运行成功才能发布。复用上传权限 catalog.add_dataresource；版本与任务元信息独立于DataResource。
- Verification: 三类样例数值检查、参数与权限、任务取消/恢复、队列配额和幂等入库、浏览器动态表单；真实Linux容器执行、隔离限制、实际worker和浏览器完整操作链路均已验收。
- Result: 本机应用、数据库、WSL2/Docker和worker已上线；最终后端701项及52子测试通过，额外5项真实容器验收通过；前端407单元和181浏览器回归通过，真实页面注册上传第四个算法、计算、下载、入库、项目权限及子系统重启恢复通过。四个示例已发布，旧数据不变，详细证据见 2026-09-19-compute-deployment.md。

## API-20260920-002 - 删除无任务历史的算法登记

- Status: Verified
- Owner: Full-stack implementer; contract → backend → frontend → testing
- Endpoint: `DELETE /api/compute/algorithms/{algorithmId}/`
- Change type: new management operation
- OpenAPI change: 增加删除算法登记接口；仅允许删除没有计算任务历史的算法，同时清理其不可变版本包；已有任务历史返回 409，必须归档停用。
- Frontend reason: 算法管理页补充删除操作和风险提示，避免用户只能停用而无法清理误登记算法。
- Backend implementation notes: 复用 `compute.manage_algorithms` 与显式 `X-Project-Id` 校验，删除前检查任务引用并保留任务历史保护。
- Mock examples: `95-compute.json`
- Verification: 后端删除/保护回归、前端类型生成和算法管理页面测试。
- Result: 后端计算集成测试 23 项通过；前端单元测试 405 项、类型检查、静态检查和生产构建通过。

## API-20260921-002 · 智能体附件、联网检索与思考回放

- Status: Proposed
- Owner: Frontend contract and backend agent implementation handoff
- Endpoints: `POST /api/agent/attachments/`, `/api/agent/conversations/{conversationId}/runs/`, `/api/agent/bootstrap/`, `/api/agent/admin/`
- Change type: multimodal attachment | optional internet retrieval | durable reasoning metadata
- OpenAPI change: 增加 `AgentAttachment` 上传响应；运行提交接受 `attachmentIds` 与 `internetEnabled`；运行返回 `attachments`、`thinkingText`、`thinkingDurationMs`；模型返回 `supportsVision`；bootstrap/policy 增加附件和联网开关及大小/数量限制。
- Frontend reason: 用户需要上传文档和图片，让已探测支持视觉的模型分析；管理员需要调整上下文、生成、附件和联网参数；深度思考生成中展开显示，完成后可在历史会话恢复摘要与耗时。
- Mock examples: `mock/prism/examples/96-agent.json` 增加附件上传、联网运行与思考回放字段。
- Backend implementation notes: 附件保存必须使用 TOML 数据根、当前用户/项目 ACL 和大小/MIME 校验；运行时重新授权 attachmentIds；互联网检索仅使用受控公共 HTTP 适配器并记录来源；thinkingText 只能来自模型实际 reasoning 字段，禁止伪造。
- Verification: 上传越权/大小/MIME、文档提取、真实视觉模型探测、联网关闭时拒绝、运行历史思考恢复、前端生成/构建/API 契约检查。


## API-20260920-001 · 平台品牌文档同步

- Status: Verified
- Endpoints: `GET /api/bootstrap/`, `GET /api/login/overview/`, `GET/PATCH /api/admin/system-settings/`.
- OpenAPI change: 仅将标题、品牌描述和示例同步为时空智能服务平台 / STISP；响应结构、状态码及权限不变。
- Frontend reason: 清理旧平台显示名称，保持契约、mock 与已运行的平台一致。
- Backend implementation notes: 当前品牌常量已生效，不修改后端行为及历史配置名称兼容。
- Verification: 重新生成 SDK/API 文档和 Prism mock，并检查契约与前端类型一致性。

## API-20260920-002 · 智能体模块

- Status: Implemented
- Owner: Single full-stack implementer; contract → generated types → backend → frontend → verification.
- Endpoints: `/api/agent/bootstrap/`, `/api/agent/conversations/`, `/api/agent/conversations/{conversationId}/`, `/api/agent/conversations/{conversationId}/runs/`, `/api/agent/runs/{runId}/`, `/api/agent/runs/{runId}/cancel/`, `/api/agent/resources/`, `/api/agent/admin/`.
- OpenAPI change: 增加模型能力、会话、幂等任务、事件轮询、只读证据、超管可见范围和额度策略。
- Frontend reason: 智能预警替换为智能体，提供模型对话和数据智能体。
- Mock examples: `96-agent.json`; deterministic model mock via mock_agent_model command.
- Backend implementation notes: 独立 worker；每次请求与每个工具步骤复核用户、项目和资源授权；模型端点由 TOML 注册。
- Verification: Mock 流式、取消、幂等、恢复、越权/撤权、统计口径；上下文策略和深度思考事件；前端权限、项目切换；服务器真实模型候选验收。

本模块继续增加科研工作流接口：`POST /api/agent/workflows/`、`GET /api/agent/workflows/{workflowId}/`、`POST /api/agent/workflows/{workflowId}/cancel/`。工作流使用独立持久化表、步骤和 checkpoint，默认只生成计划；算子调用必须由服务端策略、算法 manifest 和计算中心共同放行。前端生成类型已由 OpenAPI 重新生成，取消接口路径与 Django URL 保持一致。Mock 服务器暂不执行真实工作流，后端使用合成资源和 worker 集成测试验证状态机、幂等、取消和重启恢复。

## API-20260921-001 · 数据可见性、GPU 监控与智能体稳态修复

- Status: Verified
- Endpoints: `/api/admin/dashboard/server/`, `/api/admin/data/resources/{resourceId}/`
- OpenAPI change: 服务器快照增加可选 GPU 单卡/多卡明细；后台数据资源增加 `ownerOnly` 响应和更新字段；智能体 `maxSteps` 上限由 8 提高到 64。
- Frontend reason: 服务器信息展示 GPU；上传数据默认项目成员可见并可在存量数据中切换为仅上传者；后台下拉补齐算法与计算管理；智能体恢复历史会话。
- Backend implementation notes: `DataResource.owner_only` 默认 false，由后端权限过滤强制执行；上传者和超级管理员可见，平台管理员仍受该隐私边界约束。GPU 仅读取主机已有 `nvidia-smi`，CPU-only 主机省略卡片。Qwen 响应兼容隐藏思考块、Markdown JSON 包裹和扁平化参数，并在协议纠正时反馈安全的参数错误。
- Mock examples: `mock/prism/examples/97-data-visibility-gpu-agent.json`，包含 `ownerOnly` 请求/响应和单卡/多卡快照。
- Verification: 数据资源跨用户/项目权限回归（含平台管理员、图层和计算输入）、GPU 快照单卡/多卡解析、智能体协议解析和 maxSteps 迁移校验；前端类型检查与构建；服务器公网 Qwen 默认数据分析提示词。

## API-20260922-001 - 智能体参数与算法排序
- Status: Verified
- Owner: Codex（契约、前后端和验证）
- Endpoints: `/api/agent/admin/`、`/api/agent/runs/{runId}/`、`/api/compute/algorithms/`、`/api/compute/templates/{templateId}/`
- Change type: additive policy/run fields; stable list ordering; new templates
- OpenAPI change: AgentPolicy新增输入token预算和思考强度，生成上限32768；AgentRun新增实际参数和用量。
- Mock examples: 通过HTTP模拟模型验证真实请求，旧运行样例可省略新增可选字段。
- Frontend reason: 显示实际生效参数和用量；算法按分类排序值、分类名称、算法名称、ID稳定分页。
- Backend implementation notes: 完整请求通过/tokenize计数，/v1/models核实实际窗口；模板5为NDWI、6为矢量面积周长。
- Verification: 参数保存至HTTP请求、截断缓存、上下文边界、算法数值、排序、生成类型及浏览器验证。
- Result: 后端62项、前端406项测试通过；本地及正式浏览器参数保存和回答通过；真实模型65536窗口/16384生成，两个算法数值验收并发布。见docs/releases/0.1.13.md及同SHA服务器回执。

## API-20260924-001 - 任务预算与角色额度

- Status: Verified
- Owner: Codex, contract/backend/frontend sequential handoff
- Endpoints: /api/agent/admin/; /api/agent/bootstrap/; /api/agent/conversations/{id}/runs/
- Change type: additive policy, request and usage fields
- OpenAPI change: AgentBudget schemas; AgentPolicy/Bootstrap/RunInput/GenerationParameters
- Mock examples: tests/integration/test_agent_budgets.py HTTP model fixtures
- Frontend reason: select a task budget and show permitted/default/actual usage separately
- Backend implementation notes: persisted snapshot and server-authenticated role ceilings
- Verification: 86 backend tests; 409 frontend tests; local browser save and real HTTP submission
- Result: policy edits reach model requests; standard users cannot request superadmin limits


- 管理策略新增 taskBudgetsEnabled、defaultBudgetProfile、budgetProfiles、budgetLimits；默认关闭，部署时经管理员保存开启。
- bootstrap 返回当前用户预算选项；提交可选 budgetProfile/maxOutputTokens，由后端身份决定上限；任务保存生效参数快照，幂等键比较预算请求。
- 运行参数增加实际服务窗口、方案、时限、最近生成量和调用次数；累计生成量跨调用求和。
- 提交长度按当前用户额度检查，完整请求仍由实际分词校验。附件提取按额度扩大，不以文件字节数充当 token。
- 本任务按契约→后端→前端顺序完成跨模块交接。HTTP 模型样例使用 tests/integration/test_agent_budgets.py，验证管理员两次修改均传入真实 HTTP 请求。

## 2026-09-25 本人功能与科研用户申请
- 新增 GET /api/auth/access/ 和 POST /api/auth/research-application/：本人功能清单、升级差异、申请状态及重提。
- 个人权限目录只返回有效项；角色申请列表及审核限定超级管理员。前后端本次共同实现，验证包含越权、重复申请及审批后权限变化。
## 2026-09-29 知识库和科研编排闭环

- 新增知识条目检索、详情、维护和条件核查接口，契约为 KnowledgeEntry/KnowledgeEntryInput/KnowledgeCheckResult；当前项目与公共已发布知识明确分离。使用真实种子及集成测试校验，不新增虚构业务项目。
- 新增智能体关联计算状态、工作流列表和计划确认接口，扩展工作流计划哈希、明确输入、自动入库选项与实际结果资源 ID。前端消费生成类型，后端重查账号/项目/计算/写入授权。
- 实现与验证在本轮完成；源码、类型和对应后端/浏览器测试共同交付。服务器实际验收另行记录。


- Mock examples: `mock/prism/examples/98-knowledge-workflow.json`；知识样例来自已核查的种子条目，编排和关联任务默认返回空列表。
- ComputeManifest 可选 `agent.enabled` 控制算法是否接受智能体调用；未配置仍沿用发布状态、平台策略与权限约束。
- 修正原有 mock 构建失败：移除误把具体资源 ID 写作路由、且与 `20-admin-dashboard-data.json` 重复的资源更新样例，统一使用契约中的 `{id}` 路由及现有响应。

## API-20261009-001 - 聊天计算计划与临时地图结果

- Status: BackendReady
- Owner: Root契约；executor后端；compute_flow_frontend前端。
- Endpoints: /api/agent/runs/{runId}/compute-intent/; /api/compute/outputs/{outputId}/map-preview/; map-preview/image/。
- Change type: 持久参数交互与真实执行闭环。
- OpenAPI change: AgentRun.computeIntent、计划操作与ComputeMapPreview。
- Mock examples: mock/prism/examples/100-agent-compute-intent.json。
- Frontend reason: 波段选择、真实进度、预览和入库。
- Backend implementation notes: 本人/项目/输入授权、计划修订校验、幂等与后端受限PNG渲染。
- Verification: 参数提取、目标切换、执行证据、错任务、恢复、撤权、地图和真实数值。
- Result: 待本地与候选验收。

## API-20261010-003 - 双Demo持久判断与多阶段输入

- Status: BackendReady
- Owner: Root契约与序列化；backend多阶段编排；frontend展示与地图。
- Endpoints: /api/agent/workflows/; /api/agent/workflows/{workflowId}/; /confirm/。
- Change type: 新增可空 step.decision，新增场景类型 ecology_investigation / geology_correction；inputs按角色绑定，knowledgeSelection沿用知识分区选择协议。
- OpenAPI change: AgentWorkflowDecision绑定实际资源、知识修订、输出与任务引用；maxResources可配置上限12，默认仍3。
- Mock examples: 既有98-knowledge-workflow空历史样例保持；新字段由 backend/tests/integration/test_demo_workflow.py、test_dual_demo_workflow.py 与 DemoWorkflow.browser.test.tsx 验证真实序列化及可空兼容。
- Frontend reason: 展示发现、依据、行动、真实结果及模型模式；支持角色明确选择、历史恢复、矢量结果和多图层地图对比。
- Backend implementation notes: plan固定输入修订和算法校验和，实际输出入库后接下一阶段；人工分析批准与产物质量批准分开。参考图和设错清单仅科研目录独立验收。
- Verification: 模型结构响应、假引用/假修改拒绝、恢复/取消/撤权/质量审核、多阶段结果衔接；实际算法数值与本机真实任务分别记录。
- Result: 本机演示验证记录见 docs/dual-demo-20261010.md；服务器部署另行安排。

## API-20261012-002 - 工作流报告文件与可恢复暂停

- Status: BackendReady
- Owner: Root契约；workflow_report_backend报告；workflow_pause_backend控制；workflow_frontend界面。
- Endpoints: /api/agent/workflows/{workflowId}/pause/、resume/、report/、report/preview/、report/download/、report/import/。
- Change type: 新增持久Markdown文件与暂停控制，AgentWorkflow新增paused状态及可选pauseRequested/pausedFrom。
- OpenAPI change: AgentWorkflowReport、AgentWorkflowReportPreview；下载text/markdown。
- Mock examples: 后端报告/暂停集成测试与前端DemoWorkflow/ResearchChatDemo真实字段fixtures；旧98样例可省略可选字段。
- Frontend reason: 完成过程收起、末尾统一成果、在线预览下载入库、确认暂停与继续。
- Backend implementation notes: 本人/单项目/输入/真实关联任务权限重查；报告文件SHA与幂等登记；暂停保留taskId和人工审核。
- Verification: 持久文件预览/下载一致、CSV/地图动作、入库幂等/撤权、暂停安全点/恢复不重复提交、刷新恢复。
- Result: 相关后端257项、最终暂停/准备25项、最终报告22项及前端相关浏览器验证通过；两个已有Demo的真实报告预览/下载/幂等入库通过。服务器发布见同SHA独立验收回执。

## API-20261014-003 - 地质成果建议选择与批准后修正

- Status: BackendReady
- Owner: Root契约、案例、地图与报告；geology_review_workflow_v2后端；compute_tasks_layout_v2前端审核。
- Endpoints: /api/agent/workflows/、/api/agent/workflows/{workflowId}/、/confirm/、/api/agent/research-demos/。
- Change type: 新增geology_map_review场景，AgentWorkflow可选modificationReview；confirm新增selectedSuggestionIds；公开判断可选knowledgeQuery仅知识查询阶段使用。
- OpenAPI change: AgentModificationReview、AgentModificationSuggestion固定真实问题、图斑、实际知识修订、WGS84范围与批准子集；旧场景字段与行为保持。
- Mock examples: 新地质工作流与批准范围后端集成测试、GeologyReviewStory前端fixtures；历史空样例可省略新可选字段。
- Frontend reason: 观众可看短判断故事、逐项选择建议、查知识/地图范围，并在刷新后恢复批准和任务状态。
- Backend implementation notes: 模型形成检索意图后真实搜索；编辑前强制review_modifications。planHash及proposalHash绑定实际问题/输入/版本，后端只接收选择而非编辑坐标；拒绝零编辑、漂移重确认，结果返回模型复核。
- Verification: 真检索与引用、批准子集/拒绝/漂移/权限/恢复、实际修改和统计一致、位置变化与正常区域保护。
- Result: 本机后端新模块组合73项、审批前端及相关回归通过；契约生成、类型一致和文档检查通过。真实模型、隔离算法、地图和发布状态分别记录于本轮服务器验收回执。

## API-20261103-001 - 工程、专题及单计算输出邀请分享

- Status: BackendReady
- Owner: roles_monitor 后端/契约；map_panels_legends 分享与通知前端。
- Endpoints: POST /api/sharing/check/；GET/POST /api/sharing/invitations/；POST .../{invitationId}/respond/、read/；GET .../{invitationId}/open/。
- Change type: 精确用户名预检、持久待接受邀请、个人跨有权项目收发通知及单对象只读打开。
- OpenAPI change: ShareKind/Person/Target/CheckRequest/CreateRequest/CheckResponse/Invitation/List/ResponseRequest/OpenResponse；计算打开复用ComputeOutput，绝不返回整任务。
- Mock examples: frontend/src/sharing/sharingTestFixtures.ts、Sharing.browser.test.tsx、SharedOutputDrawer.browser.test.tsx及backend/tests/integration/catalog/test_sharing.py、test_share_contention.py中的隔离测试样例。
- Frontend reason: 工程、专题、计算结果可输入准确用户名发邀请，收件人接受/拒绝，分享者收到决定；计算输出独立预览/下载，不暴露兄弟输出。
- Backend implementation notes: 创建限原owner或既有有权管理员；不授项目、功能或owner_only权限。预检/创建/接受/每次打开均重验双方与底层依赖。pending/accepted同对象去重，提交和响应幂等；跨项目通知只返回本人且仍有权项目。接受仅授对象只读，下载/入库各自核权。
- Verification: 精确账号、自分享拒绝、账号停用/项目/功能/私有依赖失权、重复发送响应、拒绝无授权、单输出隔离、刷新及通知已读、对象失效反馈。
- Result: 后端62项定向与计算/专题回归通过，含真实文件预览下载及隔离WAL并发；Django检查与迁移一致性通过。仅增加ShareInvitation新表，未写本机业务数据。前端、浏览器及发布验收另计。

## API-20261103-002 - 用户公开项目范围与科研历史轻量读取

- Status: BackendReady
- Owner: roles_monitor 项目权限、后台UI及统一契约；Root 工作流摘要和场景读取；agent_layout_modes 普通智能体页面。
- Endpoints: GET /api/projects/；GET/POST /api/projects/assignments/{userId}/；GET /api/agent/workflows/；GET /api/agent/research-demos/。
- Change type: 默认兼容的按用户公开访问开关、授权默认项目、轻量历史分页与按需场景预设。
- OpenAPI change: ProjectAssignment.allowPublicProject（省略保留）；ProjectTagList.defaultProjectId；AgentWorkflowSummary/List和AgentResearchDemoSummaryList；view=summary与筛选分页查询。
- Mock examples: backend/tests/integration/test_project_public_policy.py、工作流摘要集成测试及frontend/src/projects/ProjectContext.browser.test.tsx使用隔离QA数据；保留原有无参数完整列表样例。
- Frontend reason: 超管可让指定用户仅访问所分配项目；首次加载不误选公开；历史与场景入口按需取详情，减少页面等待。
- Backend implementation notes: 默认true保留旧用户和游客，超管全部可见；业务API、worker、公开知识复用与分享重验同一范围，已有历史不删除。摘要只限本人当前项目，不带大字段，详情另验数据权限。平台公共图文独立于业务项目。
- Verification: 未授权账号不得改策略；禁公开后直接资源/历史/分享失败；默认项目一致、游客保持；摘要分页/类型/项目/本人隔离，刷新后恢复与按需读取。
- Result: 定向自动化与类型生成结果随本轮交付记录，服务器生效以同提交发布回执为准。

## API-20261103-003 - 通用地质推理：任务资料上传与字段确认

- Status: BackendReady
- Owner: codex/agent-generic-workflow（契约、后端与前端同一任务）。
- Endpoints: GET/POST /api/agent/workflow-uploads/；DELETE /api/agent/workflow-uploads/{uploadId}/；POST /api/agent/workflows/；POST /api/agent/workflows/{workflowId}/confirm/；GET /api/agent/workflows/{workflowId}/。
- Change type: 新增任务资料上传、识别与删除；新增 geology_generic 场景与 uploadBatchId；confirm 新增 fieldMapping；plan 新增 fieldMappingReview。
- OpenAPI change: AgentWorkflowUpload、AgentWorkflowUploadList、AgentWorkflowUploadProfile、AgentWorkflowUploadField、AgentFieldMappingReview、AgentFieldMappingRole、AgentFieldMappingTarget；AgentWorkflowInput.uploadBatchId；AgentWorkflowConfirmation.fieldMapping。原有场景的字段与行为不变。
- Mock examples: mock/prism/examples/103-agent-generic-workflow.json。
- Frontend reason: 用户在 MH-workflow 中上传自己的资料，无需按固定字段名整理；智能体判断字段含义，用户确认后执行。
- Backend implementation notes: 上传沿用既有矢量、栅格、表格导入服务，登记为 owner_only，来源标记 workflow-upload:<批次>；批次在创建任务时绑定且只能绑定一次。字段确认在 worker 中由模型提出，校验字段真实存在；确认后生成规范化工作副本，复用综合推理算子与审批流程。设计见 docs/agent-generic-workflow-20261103.md。
- Verification: 上传识别、批次隔离、重复绑定、删除已绑定、字段确认校验、工作副本字段与几何一致、Mock 模型下全流程走通；真实模型的字段判断在服务器验证。
- Result: 本机后端新增9项、前端浏览器新增2项通过；工作流相关回归179项通过。本机以模拟模型从上传到远景区比较完整运行成功（检查、执行、复查、交汇重建、远景区五步真实计算）。真实模型的字段判断与服务器运行待候选环境验证。

## API-20261103-004 - 成果与专题卡片缩略图

- Status: BackendReady
- Owner: codex/agent-generic-workflow（待改项 A3）。
- Endpoints: GET /api/catalog/results/{resultId}/file/；GET /api/catalog/map-compositions/{compositionId}/versions/{versionNumber}/file/；以及返回 ResultArtifact、MapCompositionVersion 的列表与详情接口。
- Change type: variant 新增 thumbnail；ResultArtifact、MapCompositionVersion 新增 thumbnailUrl。
- OpenAPI change: 两个文件端点的 variant 枚举、ResultArtifact.thumbnailUrl（PNG/JPG 有值，其余为 null）、MapCompositionVersion.thumbnailUrl；公开匿名访问的 preview/thumbnail 允许浏览器缓存；登录或私有项目仍由项目中间件设为 no-store。
- Mock examples: 无新增 mock 文件；结果列表示例中缺省字段由后端测试覆盖。
- Frontend reason: 成果展示卡片原来直接加载原图，图片多时加载很慢；卡片改用缩略图，详情仍看原图。
- Backend implementation notes: 缩略图首次请求时由原图（专题为 PNG 预览）生成长边640像素的 WebP，存于业务数据 cache/thumbnails，按文件大小和修改时间命名；权限与 preview 相同。没有 PDF 渲染器，PDF 不提供缩略图。
- Verification: 缩略图尺寸与缓存复用、权限与 preview 一致、非图片格式返回400、卡片使用 thumbnailUrl。
- Result: 后端测试通过；前端卡片改用缩略图。

## API-20261105-001 - 地质审批与对比的按需投影

- Status: BackendReady
- Owner: codex/logic-demo-ux（契约、后端与前端跨栈交接）。
- Endpoints: GET /api/agent/workflows/{workflowId}/；POST /api/catalog/resources/{resourceId}/query/。
- Change type: 新增 compare、inspection 视图及 part/offset/limit；displayGeometry 自适应压缩显示几何。
- OpenAPI change: AgentWorkflow.view 枚举；AgentWorkflowPage、AgentWorkflowGroup、AgentWorkflowReviewIndex；plan.pagination 保存页总数、分组索引、偏移；plan.compareFeatures 仅含本页实际修改几何；plan.reviewIndex 保存审批默认集合；suggestionId定位深链接对象。默认 full 语义不变。
- Mock examples: mock/prism/examples/105-agent-workflow-card.json；隔离集成样例覆盖5000对象、分页及权限边界。
- Frontend reason: 低带宽首屏不读取完整工作流和完整修改记录，审批默认选择模型建议但不代用户批准例外。
- Backend implementation notes: compare 只以已保存批准、执行明细与实际变化交集构造分页，inspection 不发送完整计算输入、模型请求和预览几何；card/inspection 保留 fieldMappingReview、reusedConfiguration，前端校验分页及卡片字段；显示几何不回写存储，无过滤显示结果按资源修订持久缓存，由成果登记 worker 预热。
- Verification: 摘要体积、实际修改分页、用户隔离、建议默认选择、对象完整原因按需、原精度查询不变。
- Result: 本地后端定向33项、前端单元573项、类型及完整契约流程通过。后端全套2411项通过、5项跳过、31项失败，其中20项为沙箱禁止端口绑定，其余11项未在此范围处理；离线成果与新对话复用旅程通过。缓存复测确认预热后同版查询不重读原始数据、不重复简化，资源修订或查询上限改变后重算。Chromium 因监听端口 EPERM 未启动，视口尺寸及交互断言仍需沙箱外复跑；未部署正式站。海德乌拉本地原始岩性显示投影gzip为230144字节，正式运行的修正后资源体积仍需部署后核验。

## 2026-11-06 规则建议自动执行授权

- 确认接口AgentWorkflowConfirmation增加可选布尔applyRuleSuggestions，默认false；只允许geology_generic字段确认、executeAfterMapping=true及approve。
- 原因：一次资料确认明确工作副本自动执行范围，省去确定性建议重复批准。
- 后端：绑定输入和本人项目，执行前核对实际问题、知识和授权；争议项保留，不伪造人工批准。
- 验证：默认路径、显式授权、防篡改、例外保留及实际241条问题回放。mock继续采用现有确认请求默认行为。

- 同次配套：AgentRunInput增加combineInputReview默认false；浏览器创建上传任务和工作流确认增加可选X-App-Entry头，用于正式构建版本衔接，旧页面409保留进度。AgentAnalysisDecision.modelMode增加rules，准确标识代码规则核验。

## 2026-11-06 单任务工作区轻量汇总

- AgentWorkflow增加可选taskSummary及AgentWorkflowTaskSummary，原接口路径、权限与动作不变。
- 原因：完成态首屏展示真实处置、复查和远景数量，避免为了概览加载完整过程。
- 后端仅汇总保存的全量实际输出，缺失、部分统计或不一致时为null，严禁从模型说明提取数字。
- 前端生成类型、契约与mock构建同步；105-agent-workflow-card.json提供实际汇总示例。已验证完整/缺失/部分统计、actual_changed为真才计作执行、待裁定实际处置扣除及card视图轻量读取；后端15项定向检查和相关浏览器回归通过。


## API-20261107-001 - 保留对象人工核查及正式地质规则

- Status: BackendReady
- Owner: 同一任务依次负责契约、后端和前端。
- Endpoints: POST /api/agent/workflows/{workflowId}/retained-review/；GET工作流inspection；既有confirm；POST /api/agent/workflows/{workflowId}/retry-imports/。
- Change type: 新增保留项核查动作及独立分页，固定已授权范围与人工候选组合。
- OpenAPI change: inspection增加part=retained，返回未实际处置的待裁定/例外及可定位几何；AgentModificationSuggestion补充allowedActions；新增retained-review请求planHash及状态/权限错误。
- Mock examples: 105-agent-workflow-card.json。
- Frontend reason: 自动处置无需逐项确认，用户能够单独勾选和定位保留对象，完成任务也可保存上一轮成果后核查。
- Backend implementation notes: 原本人、单项目、当前知识、输入、固定算法授权保留；只合入服务端固定自动范围与本次明确人工ID。未选对象保留，原报告和计算按轮次保存，不提高预算。正式知识发布仅元信息变化且实质语义与历史修订相同时可衔接旧冻结绑定。
- Verification: 默认不选、明确选择、自动范围不可篡改、过期计划、跨项目/他人拒绝、上一轮成果保留、分页几何与地图联动。
- Result: 后端91项及8项子检查通过，相关前端51项通过；候选实际处置197项、保留44项。核查轮次成果命名与入库恢复已同步完善，后续候选验收单独记录。

## 2026-11-07 逻辑推理蚀变预览颜色表

- 状态：implemented。端点：GET `/api/compute/outputs/{outputId}/map-preview/`；在现有 metadata 中明确可选 `colorTable[]`，每项必含 value（0–255整数）、label、color（#RRGGBBAA）。其他元信息与 URL 不变，无新增请求字段。前端仅展示图例，后台脚本渲染 PNG。
- 权限与状态矩阵：原任务本人/管理权限或已接受的单输出邀请，当前项目与原始输入仍逐次授权；200 成功，400 参数/格式错误，401 未登录，403 撤权，404 不可见/过期，409 文件身份变化，503 渲染暂不可用，均沿用现有错误体。
- 模型配色一次产生五类矿物色表及审计，校验后作为显示元信息保存；前后复用，0/NoData透明，科学像元和校验和不变。已有输出未登记时使用正式类别色表，不能标称模型结果。
- Mock：沿用现有计算预览示例，无新增路由。验证：实际 TIFF 到 PNG 像元颜色/透明度、前后同色、缓存换表失效及浏览器图例。

## API-20261107-002 - 停止响应与角色依据

- Status: BackendReady
- Owner: 同一任务依次负责契约、后端和前端。
- Endpoints: POST /api/agent/workflows/{workflowId}/cancel/；角色识别及会话运行详情。
- Change type: 取消提前结束调度并返回card；inputSummary增加可选字段。
- OpenAPI change: 普通取消活动任务原子返回cancelled card，已终态保留状态；本人同项目真实绑定排队算子取消、运行算子cancelling。replacePlanHash原条件保留。inputSummary新增可选roleReason、roleSource（model/saved/rules/user）。
- Mock examples: 沿用105-agent-workflow-card.json、106-agent-generic-chat.json；新增可选字段可省略，定向夹具覆盖真实来源与停止状态。
- Frontend reason: 停止不再等待模型或工作副本收尾，角色依据面向用户可见；不将沿用或人工调整冒充模型判断。
- Backend implementation notes: 取消不读取输入文件，只按所有者、项目和实际步骤绑定终止子任务；晚保存保留取消状态与冻结计划。模型角色实际调用及source绑定，字段复用单独核验。模型规划和最终解释沿用既有审计、预算与结果校验。
- Verification: 200取消或已终态幂等，400格式、401未登录、403当前功能/项目拒绝、404不存在或非本人、409初始计划替换条件变化；错误体detail不变。运行/等待/排队取消、子任务隔离、晚保存、模型实际思考与角色依据、浏览器及契约检查。
- Result: 本机停止/规划/权限/报告定向回归通过；候选真实模型、停止耗时和地图性能另记录验收回执。

## 2026-11-07 修正后远景区协议（已实施）

- `GET /api/agent/workflows/{workflowId}/`：`AgentMultiElementMap`新增可选`prospectProtocol=after_only_v2`。2.0算子不接收修正前找矿资料，不生成`beforeProspects`；`afterProspects`为空时表示实际无目标。统一P001编号，没有A/B分级。
- 前端按明确协议展示修正后目标数量、面积及逐区证据；历史1.x仍读取保存的分期分级证据。mock见`105-agent-workflow-card.json`。
- 后端从冻结算子版本投影协议，不根据结果是否为空猜测。验证包括实际空输出、仅修正后输入、历史证据读取与前端圈区定位。

远景输出增加`prospect_support`连续栅格及`prospectHeatmapOutputId`引用。后端统一脚本按`colorRamp`蓝—黄—红连续插值生成PNG，浏览器只显示图片和同色图例；透明背景不扩大目标边界。相对置信度由已圈目标内的矿物组合与岩性支持归一化，非有矿概率。

## API-20261107-004 矢量预生成显示瓦片（已实现，服务器验收单独记录）

- Status: BackendReady
- QueryRequest增加可选sourceFeatureIds（默认false）；聚合点同时提供rawTileUrl和aggregate=0，保留关闭聚合及热力图显示能力。

- 接口：GET资源profile新增可选vectorTiles；新增GET `/api/catalog/resources/{id}/vector-tiles/{revision}/{z}/{x}/{y}.pbf`。
- 原因：管线按级别和区域读取二进制瓦片，灾害点用全量聚合，减少每次视野查询和大GeoJSON传输。例子：`mock/prism/requests/vector-tiles.json`。
- 后端交接：离线管理命令只读原始GeoPackage生成0～10级缓存；revision隔离资源修订；瓦片按query_data/load_vector_layer、项目、owner_only授权后读私有缓存，空瓦片204、失效404、参数400，ETag检查在鉴权之后。
- 前端交接：已就绪且无筛选的普通显示使用vector source；聚合点点击放大；属性表/导出按当前范围读取原始数据。显隐、符号、属性点击、工程恢复须保留。
- 验证：聚合数量守恒、完整几何未修改、无运行时生成、缓存失效/跨项目/owner_only/撤权后304保护；真实MVT浏览器、属性表和精确导出。详情见`docs/vector-preview-tiles-20261107.md`。

## 2026-11-07 输入版本复用与自动处置位置（已实施）

- `GET /api/agent/workflows/{workflowId}/?view=inspection&part=retained`的`plan.reviewIndex`新增可选`automaticMap`。从完整冻结授权集合提取轻量位置，包含total、locatedCount及位置点/count；不扩大人工候选、审批集合或数据权限。前端低对比标记按当前视口聚合，缩放/勾选不重新请求。mock见105-agent-workflow-card.json。
- 计算输出metadata增加`executionMetrics`说明输入准备、算法执行、结果检查的耗时和输入物化/复用次数。输入快照缓存仅复用受控内容版本，每次使用仍重新授权和检查源文件身份，算法收到独立副本。内部SDK增加与文件身份绑定的证据标识读取，旧算子仍按既有协议执行。
- 验证：跨用户/项目与撤权、原地内容改动、共享数据库的其他图层变化、并发/损坏缓存、算子修改输入、冷/热准备、科学输出一致性；自动标记全量计数与分页独立、缩放聚合、人工勾选不受影响。
