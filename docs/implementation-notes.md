> 当前规则请先阅读 [current-platform-rules.md](current-platform-rules.md)。下文日期章节是历史记录；其中“all 汇总”、角色对象共享、新闻项目隔离和旧首页分类已被替代。

## 2026-11-07 管线和灾害点显示金字塔

- API-20261107-004为profile提供预生成vectorTiles，普通加载、移动、工程恢复均使用同源授权MVT；有属性筛选时保留原查询。灾害点0～9级按64显示像素网格聚合，10级原始点，关闭聚合/热力图使用raw瓦片。
- 离线一致性快照只读原始GPKG，统一GDAL CLI生成0～10级MBTiles；缓存位于TOML业务根cache/vector-tiles/v1/项目/资源/修订，完成后原子发布。修订绑定真实源路径与源更新时间，候选与生产各自准备，HTTP不生成。
- MVT是显示副本：4096 extent在10级赤道约9.55米网格，不用于精确量测或计算。属性表和导出按当前视野回源，sourceFeatureIds保留FID，并继续执行点1500/线10000及系统查询上限。尚无视野时禁止空占位导出，迟到属性响应不得覆盖新表。
- 项目、owner_only、功能权限及公开项目游客语义保留。栅格仍后端渲染。真实服务器及公网性能以本次发布目录验收回执为准，本机测试中的生成器替身不代表真实MVT验收。

## 2026-11-07 导航、保留项核查与正式资料登记

- 顶部以地理工作台、智能体、计算中心、知识库、成果展示为首五项，数据分析纳入数据资源下拉，移除独立数据导入。智能体对无权限账号保持可见且禁用；Bootstrap和后端授权仍为使用边界。导航测量包含已选低频模块展开的名称，避免中等屏宽末尾按钮被右侧控件遮挡。
- 规则自动执行流程只展示待裁定和例外，人工候选默认不选，已有确定性处置由后端固定。保留项检查投影单独分页并提供实际简化几何；单地图可缩放、平移、点击并查看测量和规则依据，前端不处理栅格像元。
- 已完成综合地质任务可显式打开保留项核查，重新校验本人/项目、当前输入、固定算法、知识和计划摘要。上一轮完整阶段、批准和成果归档；复用初检，确认后才重做处置、复查、关系、远景与报告，任务/批准表/报告采用轮次标识防止覆盖。人工ID和动作不能扩大范围，已有预算不自动提高。
- 知识正式登记保留旧修订，只有正式发布元信息变化且实际规则语义与旧快照完全相等时允许使用旧冻结绑定；规则参数、条件、来源或解释变化必须重新规划。内部trialScope等历史协议标识保持，用于项目、场景及版本校验，不表示当前发布状态为草稿。
- 原始栅格去重是管理整理程序的内部能力，需要同项目保留目标、完整历史预检查及逐像元/掩膜/网格/坐标系/范围一致证明；公开删除接口仍保护原始输入。历史删除凭据可带替代资源和像元摘要，不能授权继续执行已删除输入。唯一的历史研发资料以geology-archived来源归档并从普通目录隐藏，保留active用于历史授权读取；不可通过停用输入破坏既有历史。
- 正式登记不改变数据科学来源，模拟识别仍如实说明。资料显示名称来自当前登记，冻结计划及审计不改写；同一内容的名称调整不更改文件或内容修订时间。包版本和既有发布验收记录保持不可覆盖。


## 2026-11-07 逻辑推理单任务工作区

- 地质综合推理同族采用单一工作区，固定四个人类可读阶段和概览、成果、过程与依据三个标签。工作流的实际状态、暂停、停止和审批回调沿用现有接口；其余场景继续原呈现。
- 资料核对默认显示文件、角色与字段摘要，按需用侧栏修改。字段缺失时打开对应编辑；标签切换和同一计划轮询保留草稿。复用历史配置仍允许重新核对，不能扩大授权范围。
- taskSummary只从保存的完整输出提取实际数量，actual_changed为真的changes行计作已执行；初检与复查问题、处置数量各自独立。缺失或不完整返回null，完整A/B统计均为0才显示0。保留计数扣除实际处置，不以批准记录代替执行。依据侧栏保留初检分组，明确其统计时间。
- 详情按任务、项目及内容独立缓存快照，主动刷新或分页才读取新记录；过期planHash不能用于审批。切换任务、项目或卸载后丢弃旧响应。成果标签及报告按需加载；完成后仅为真实运行的计算或已排队的入库轮询。
- 模型预览只展示实际活动的最近片段，完整内容与初始资料识别思考放侧栏；没有人为逐字动画。计算过程不把上一轮模型活动写成正在思考。
- 本轮在本地开发、定向浏览器测试并回放已有完成任务；未重复运行241条业务证据。中文目录触发Vitest浏览器mock模块解析问题时，将同一前端同步到本机ASCII临时目录测试；主源码和提交仍在原工作区。发布只冻结一次产物，服务器使用隔离数据验收并核对静态哈希。


## 蚀变像元与归类组边界

- 算子1.1.0声明alteration_summary后，新工作流绑定逐像元蚀变协议；旧版本图斑任务保持原快照和读取路径。岩性、构造算法不变，岩性几何不简化。
- 蚀变组由规则、矿物、岩性单元/分组、边界类别与动作推导稳定AG标识，快照另绑定原栅格及权重内容。问题表只保留每组导航bbox；执行重测后逐像元产出corrected/weight/changes COG，变更每组一行。互斥规则优先级与表字段见算子README。
- 栅格组建议由系统确定，用户可明确保留、降权或剔除；模型只建议岩性/构造分组并简述解释。紧凑审批基集不包含待裁定/例外；组动作绑定批准步骤、冻结CSV及执行输出，不能扩大范围。
- 对比全局计数与按要素分页分离，revision仅随批准与实际输出改变。栅格预览仍由后端统一stdin/stdout符号化脚本生成PNG，前端SVG只做叠加。报告读取统计/归类表，不读取蚀变逐对象几何。远景区以默认100 m网格上的加权矿物比例累计，P-02需随新语义重新核查。
- 算子1.1.1不跨矿物缓存全幅数组或临时工作栅格；检查与正式输出分两遍逐矿物执行，完整批准校验先于成果写出。大于262144像元时用512×512窗口，八邻域标签沿块边及对角线通过磁盘SQLite并查集合并后才判断A-05，代表面积并列按全幅首像元排序。prospect只读取原始/修正证据及权重，不调用蚀变规则检查；分析网格累计量为float32。详细数据类型、临时空间和Linux硬限制验收入口见共享核心README。
- runner失败诊断属于内部状态协议，不增加API字段；平台沿既有任务失败说明展示白名单分类和异常类型。native与容器状态仍限4096字节，异常原文不外传；必须同时部署runner和平台runtime代码，单独更新算法包不改变失败文案。

## 模型分析说明与审计边界

- 分析说明的形态、数量及长度可规整，不因展示限制中断已获批的执行；可执行动作、修改身份、引用来源及知识修订仍严格校验。完整原始说明随每次尝试的审计响应保存。
- 模型尝试从请求发出前登记持久步骤，成功、校验失败和流异常更新同一步。响应正文脱敏并限制2 MiB；精简阶段仅返回保存状态，正文通过既有授权步骤分页读取，不新增公开下载入口。

## 独立成果对比入口

- 地质工作流的卡片、成果和逐处讲解入口统一使用 `/map?geologyReview=…`；独立页保留 `suggestion` 定位、双图及讲解，不再提供返回工作台对比的按钮。
- `MapPage` 对历史 `geologyCompare` 地址先执行 replace 跳转，保留项目、定位参数及锚点，不挂载工作台和侧栏。无其它引用的工作台对比组件、专用数据加载、图层分组及样式已移除；共享独立页地图与讲解模块保留。

## 2026-11-05 地理工作台纯矢量对比

- `/map?geologyCompare=…` 的双图使用浏览器原生 SVG 和本地 Web Mercator 坐标投影，浅色背景，无在线样式、底图、字体、瓦片、Worker 或 access token；不创建 Mapbox 实例，因而不隐藏或改写 Mapbox SDK 的标志、认证及计量逻辑。新增运行时依赖为零。常规主地图仍使用原有 Mapbox GL JS 3.25.0 和原底图、标志；独立旧审核工作区不在此次替换范围。
- 对比模式不挂载被遮挡的常规 `MapCanvas`，避免后台仍下载主地图底图；单图模式重新挂载，沿用此前保存的视角和底图偏好。双图共享视口，支持缩放、拖动、键盘平移、范围重置、点线面及多部件几何、面洞、辅助图层、当前对象轮廓与点击选取。几何路径按输入缓存，不在视口移动时重复投影；大场景 SVG 节点量仍需实景性能验收。
- `WorkflowCard` 统一提供成果对比链接，嵌套 `WorkflowResults` 不再重复生成同一入口；明细收起时保留 DOM 状态，并同时施加 `hidden`、`inert` 和 `display:none`，隔离键盘与辅助技术访问。
- `LocalGeologyReviewMaps.browser.test.tsx` 检查零网络调用、无 Mapbox 标志、矢量实际绘制与双图联动，并输出组件挂载至两帧后的首屏时间及底图请求数。此口径不含业务数据接口耗时，不能替代完整页面冷启动或生产环境前后性能对照。

## 2026-11-05 工作流计算名额与审批展示

- `WORKFLOW_COMPUTING`只含queued/running/waiting_compute，数据库唯一约束只限制这些状态。`WORKFLOW_ACTIVE`仍含waiting_approval/paused，供取消、暂停及未结束状态判断使用；停放任务不自动清理。
- 创建、批准和恢复计算共用账号事务锁；另一任务占用名额时返回明确409，保留原审核和暂停点，不隐式排队或取消。摘要区同时提供计算任务与停放任务的本人记录、来源对话、查看和结束操作，目标项目权限不变。
- 审批展示组使用要素、规则和动作，不将目标代号及快照作为展示分组键；批准请求仍提交逐对象ID。待裁定和例外按要素、规则汇总并默认折叠，不进入批准集合。动作文案在审批、地图讲解、报告和修正记录中保持一致，剔除表示从修正后成果删除。

## 2026-11-04 逻辑推理资料与配置边界

- 逻辑推理输入区以可收起面板管理资料，收起不改变批次；清空独立操作。系统数据按最近更新分页、搜索和目录筛选，目录复用现有存量数据组别，不新增平行目录模型。
- 本人项目在字段确认后将系统数据部分写入 `LogicConfiguration`；混合批次的临时资料及其角色、字段不保存，若地质图为临时上传则下次需补选。复用前匹配当前权限、资源集合、更新时间及真实画像，角色和字段可沿用，计划与逐项处置批准不能沿用。
- 计划批准前重新核对角色和字段时，未执行的原计划记为停止并保留历史，将本批引用重新交给角色核对；不删除科研原数据或已生成工作副本。
- 逻辑项目使用既有思考强度滑杆且无深度思考开关；最低档轻量默认为fast，维持原关闭深度思考语义。其他项目的控件和默认行为不变。

## 2026-10-20 登录生命周期、历史读取和地质图版本

- 登录继续使用Django Session；页面登记短期租约，刷新续接、多标签各自登记，关闭全部平台页后新开页面重新登录。新登录不再记住账号会话。关闭通知采用keepalive请求；访问租约120秒、刷新续接120秒，未挂起且有正确令牌的页面可在租约后12小时内恢复。新标签可在有效Cookie和CSRF下join仍在线会话，abandon不注销其他页面。
- 用户输入栏仅保留三档思考强度及逻辑推理开关；模型和分析方案取后台默认设置，旧localStorage选模及预算不覆盖后台。历史运行参数保持原记录。
- 历史读取与重新执行分别授权。查看已保存内容继续校验本人、当前项目、数据和知识可见性，允许元信息与知识修订发生变化；缺失资源须有服务端正式删除凭据。执行、批准、新报告生成和入库仍核对冻结依据及实际资源版本。
- 地质新输入采用原始分类TIF的29米格网，生成连通阶梯边界。活动入口迁移到新资源，旧资源和原表保留；内部验收参考独立保存，不进入模型或算法输入。两项已发布算法1.0.1继续按实际空间关系和知识条件检查、修正。
- 本次生产只读调查确认122条运行中13条受版本校验阻断，聊天原文未删除。测试与发布回执分别记录本机回归、候选验收、正式验收及新版案例的真实模型运行，不能互相替代。

## 2026-10-14 数据管理与科研交互反馈

- 胡杨内置非地理演示以已核对项目 code（default、demo-arid-ecology、05）确定展示范围；项目身份未加载及其他项目保持空态，后台实际生态资料保持现有授权规则。
- 目录文件管理调用单项目真实批量删除接口；前端按服务端确认的删除项更新，逐项保留失败说明，确认与请求固定同一项目。后端同时检查访问、owner_only及引用，复用单项后台删除，清理资源独占受控存储，共用存储保留。
- 工作流detail是原因来源。任务卡、composer及侧边优先同一当前聊天科研任务，历史手工流程和异步旧卡片不覆盖当前状态。失败时区分模型分析与算法执行，已有结果可继续查看。
- 人工审核意见通过原confirm接口绑定当前planHash保存为review_feedback步骤及checkpoint；approve继续原流程，reject停止后续并保留候选。意见携带原阶段及候选输出进入后续模型上下文，用于解释与核验，实际编辑仍通过原有参数和证据校验。
- 模型完整响应以response_received先保存再检查暂停边界；恢复只重新校验已有响应、原始证据与权限，不新增模型请求。无完整响应的旧请求保留审计并明确未提交本步计算，用户可重新发起。

## 2026-10-16 智能体目录与运行参数

- 目录统计由当前用户及项目作用域的数据库聚合产生；清单通过offset/nextOffset分页，分类用is_compute_result。非计算数据包含上传与历史登记，不能仅凭名称推测来源。
- Qwen深度工具模式取消response_format强制JSON解码，保留严格协议解析及工具权限校验；快速模式保持JSON约束。真实服务A/B验证强制JSON抑制思考标签，放开后返回标签。
- dailyRuns/maxSteps/maxResources允许0不限；正值继续作为管理员额度，其余非安全设置取消固定上界。真实模型窗口、服务并发、附件大小和工具权限仍有效。终态科研工作流的计算结果采用预览及确认清理，活动依赖继续保护，删除后保留来源和记录，见 [普通任务交互与历史清理](agent-task-interactions-20261016.md)。
- 成果Demo按当前项目和后端真实归属过滤，入口不切换项目。API设置约束同步契约、开发指南和生成类型。

## 2026-10-11 双 Demo 真实模型候选修复

- SQLite WAL 下，创建工作流的读事务遇到 worker 心跳写入后升级写入会返回 SQLITE_BUSY_SNAPSHOT。创建短事务第一条语句先以无字段变化的 UPDATE 取得写锁，再检查幂等与活动工作流；模型、知识检索保持在事务之外。同键返回同一流程，不同键仅创建一个活动流程。
- 真实模型 HTTP 流的监控线程通过 copy_context 继承启动时的项目范围；监控仍实时重读用户、项目成员和知识修订。当前项目及公开知识可用，其他私有项目、已撤回权限或已变化的依据继续中断执行。接口结构、知识可见性规则及数据路径保持。
- 真实模型的补充观测流程曾把旧统计误认作本轮已计算结果。请求新增执行状态及输出来源组，分别列出前次结果、本轮真实任务与最新统计、待提交步骤；完整统计只传一份。新增证据先经过实际重算，随后比较判断变化；最终分析依据本轮最新统计。正文优先资料标题，引用编号保存在证据字段中。
- 地质编辑请求按计划中的最近一次检查任务关联真实 issues，明确可修复属性行位置和完整字段协议；model_changes 在本次模型提出计划前仍是待生成输入。其他算法阶段保持空修改数组，编辑计划仍由模型生成，执行器逐项核对实际问题并绑定真实输入签名。证据不足可请求人工复核，空计划和越界修改继续按原校验拒绝。辅助观测支持变化解释与调查排序调整，模型说明区分规则排序和原因验证。
- 每次公开判断最多调用真实模型两次。仅本地响应结构、真实引用或修改计划校验失败可追加一次错误反馈；重新检查完整上下文预算与授权，真实请求累计受原 maxIterations 约束且共享本步时限。初始完整请求和去除思考标记后的模型正文、具体错误、反馈、请求摘要及实际 token 用量保存在计划审计中，拒绝记录先落库再重问。网络、权限、取消与预算异常直接结束，最终分析的审计同样持久恢复。
- 进程恢复时，已有模型请求审计而尚无已保存判断的步骤保留记录并停止自动重发，供核对后重新发起分析；待确认请求和已接受但尚未保存的响应均采用同一边界。
- 服务器候选的实际算法与数值已通过；本批修复后重新冻结提交，并重复真实模型与页面验收。正式发布证据保存在独立发布目录，按同 SHA 回执确认上线状态。

## 2026-10-10 双 Demo 本机科研工作流

2026-10-11 发布准备补充：用户授权测试通过后上线。准备入口新增显式超管与地质项目参数，复用现网“核地院逻辑推理”而保留人工字段；算法目标版本在业务写入前预检，公开已有版本只读核对。策略只提升预算最低值，保留原功能开关和更大人工预算。服务器真实模型、候选及正式验收分别记录，不能用本机模拟判断替代。

- 复用 AgentWorkflow、现有计算/入库、项目权限、知识分区和地图入口，增加生态调查与地质纠偏两种多步场景。每步形成公开判断摘要，引用实际输入、知识修订和真实结果；modelMode 明确区分 real/mock。普通 NDVI 快捷执行保持，完整 Demo 在任务完成后读统计并形成下一阶段判断。
- 生态明确绑定两期影像、掩膜、分区、观测表；NDVI→变化→调查排序。previousWorkflowId 支持补充观测更新，核实旧结果、保留角色参数，仅重算调查排序。缺资料区单列；排序按实际统计和关联证据形成。
- 地质明确绑定初始图、调查表和规则表，依次检查、几何候选审核、再检查、受约束属性修改和复查。参考图与设错清单隔离于科研目录 acceptance-isolated，只用于独立验收。
- 本机创建两个展示项目、九份模拟输入/观测和四条必要知识。六算法真实试运行后发布；旧填图检查 1.0.0 失败记录保留，修正版 1.0.1 发布。准备命令复用人工修改对象，并逐文件核实同版本算法源码。
- 前端科研工作流新增角色表单、判断时间线、原/新观测对照、矢量任务地图入口和地质原图/修正图对比；地图沿实际调查排序及修改字段分色，手机抽屉宽度适配。多资源地图加载等待样式就绪，沿用后端栅格渲染。
- 修复生成修改表 storage_path 缺 table/ 导致后续算子读不到实际文件的问题；缺文件明确失败。临时导出 GPKG 规范 last_change，使未变的矢量恢复保持真实文件校验和一致，原始资源不改。
- 模型请求仅去除重复表示：旧结果在当前完整读取列表中逐项核对后以来源编号关联，旧发现文字由完整统计及判断摘要承接；plan 历史和全部表格行保持完整。地质最终请求仍需真实模型分词器验证窗口。
- 地图选中对象后属性置顶，优先显示真实修改前后、原因、依据及调查顺序；字段标签区分面积占比与像元数量比例。多成果入口只加载空间产物，完成后合并视野范围。
- 输入修订、知识和算法版本在执行前重授权；取消请求及人工质量审核不被阶段保存覆盖。生态更新实跑仅新增一项调查排序，原任务保持；刷新/幂等请求复用记录。
- 契约同步 OpenAPI、开发指南、生成类型及 Prism 文档。操作和验证口径见[双Demo本机演示说明](dual-demo-20261010.md)。本轮仅本机生效；当前模型判断验收为模拟模式，真实计算已完成，真实 Qwen 连接受自动审批限制。

## 2026-09-19 用户批准的 A01–A14 整改完成

- 依次完成契约、生成类型、后端、前端交接；结果及验证范围见 [验收记录](2026-09-18-a-items-acceptance.md)。R01–R03 暂缓，R04 查询语义保留，R05 内容保留。
- 全平台备份包含 projects/exports 和完整科研目录；正式更新前完成独立恢复核验。SQLite 快照失败只清理临时副本，绝不删除原始研究文件。
- 工程列表为摘要分页，详情按需读取；普通/后台更新使用 expectedUpdatedAt 条件更新，旧版本 409。底图标识保存到快照与版式，输出范围统一用于地图、格网、比例尺和区位框。
- 新附件暂存 24 小时，保存时与正文 revision 原子提交，取消撤销；过期由上传触发或 cleanup_content_assets 命令清理，未设置周期任务。
- 实测慢速源样式后增加就绪等待及 style.load 自动预览恢复，保持超时、取消和严格瓦片失败处理。Mapbox 影像、街道恢复及实际 300 DPI 输出通过；天地图/OSM 只完成自动化选源验证。
- 本轮隔离验收会话已删除，未留下临时数据资源；实际数据/图文/工程/项目成员与整改前备份一致。

# 实现约束摘录

## 2026-09-21 智能体上下文与深度思考参数

- 运行上下文不再使用普通聊天 20000 字节、数据智能体 24000 字节的硬编码限制。模型注册公开 `context_window_tokens`，策略公开 `maxContextBytes`、`maxOutputTokens`、`temperature`、`topP`、`maxProtocolRetries` 和 `maxRunSeconds`；worker 以 UTF-8 保守预算和模型窗口扣除回答空间后取较小值。
- Qwen 注册模型通过 `thinkingMode=deep` 启用 `chat_template_kwargs.enable_thinking`。兼容 OpenAI/Qwen 流中 `reasoning_content`、`reasoning`、`thinking` 和 `<think>`，统一写入可审计的 `thinking` 事件；最终回答仍只使用普通文本。
- 深度思考能力由管理员总开关、模型 `qwen` 标记和运行请求三层共同控制；模型切换到不支持的模型时前端恢复快速模式。思考模式写入 `AgentRun`，迁移为 `0005_thinking_mode`。

## 分层与目录

- 前端和后端必须分离：`frontend/` 只放 React/Vite 工程，`backend/` 只放 Django 工程。
- 程序代码、业务数据、科研数据分离存放。两类数据根目录只从 TOML 配置读取。
- 业务数据固定子目录：`database/`、`media/`、`uploads/`、`exports/`、`logs/`、`static/`。
- 科研数据固定子目录：`vector/`、`raster/original/`、`raster/preprocessed/`、`raster/metadata/source/`、`raster/metadata/preprocessed/`、`gene/`、`table/`。
- 业务数据根目录通过 TOML 的 `storage.app_data` 指定，不在程序中硬编码。
- 科研数据根目录通过 TOML 的 `storage.research_data_root` 指定，不在程序中硬编码。

## 后端模块结构

```
backend/apps/
├── core/           # 配置加载、认证、存储路径工具
│   ├── config.py       # TOML → ProjectConfig dataclass，纯函数
│   ├── storage.py      # 安全路径拼接，防路径遍历
│   ├── auth_views.py   # 登录/登出/当前用户（基于 Django auth）
│   └── views.py        # bootstrap 端点
├── catalog/        # 数据目录、资源、图层、查询
│   ├── models.py       # DataResource, MapLayer, DataCatalog, WorkspaceScene, DictionaryItem
│   ├── serializers.py  # 模型 → JSON
│   ├── permissions.py  # access_groups 基于 Django Group 的访问控制
│   ├── vector_store.py # GeoPackage 矢量列表、profile、查询、字段元数据和要素读取
│   ├── data_query.py   # 资源 profile/query 入口，栅格 profile 桥接到 raster.profile
│   └── views.py        # 目录、资源、图层、工程专题、搜索 HTTP API
├── raster/         # 栅格数据全生命周期
│   ├── models.py       # RasterDataset
│   ├── permissions.py  # can_manage_raster_data
│   ├── views.py        # 栅格 HTTP API（导入/渲染/瓦片）
│   └── services/       # 核心业务逻辑（拆分后的包）
│       ├── __init__.py         # 公共 API 重新导出，外部调用方零修改
│       ├── exceptions.py       # RasterRenderError, RasterImportError, RasterJobError
│       ├── constants.py        # 扩展名、色板、瓦片常量
│       ├── progress.py         # 进度文本解析
│       ├── geo_utils.py        # 坐标/边界/瓦片计算
│       ├── color_mapping.py    # numpy → RGBA 色彩映射
│       ├── rules_engine.py     # 符号化规则归一化与校验
│       ├── gdal_ops.py         # GDAL CLI 封装（gdalinfo, gdalwarp）
│       ├── catalog_sync.py     # DataResource/MapLayer upsert
│       ├── serializers.py      # RasterDataset 序列化、元数据压缩
│       ├── profile.py          # 栅格资源 profile 查询（供 catalog.data_query 调用）
│       ├── importer.py         # 文件导入、预处理、扫描、数据集查找
│       ├── renderer.py         # XYZ 瓦片渲染、瓦片样式注册
│       └── jobs.py             # 异步任务系统（线程池、进度轮询）
└── audit/          # 操作日志
    ├── models.py       # OperationLog
    └── service.py      # log_operation 工具函数
```

## 专题制图对象与权限边界

- `WorkspaceScene` 只表示可编辑工程，`kind` 固定为 `project`；历史 `topic` 数据由 catalog 迁移直接清理。
- `MapComposition` 表示出图稿，发布前仅所属用户、平台管理员和超级管理员可见。
- `MapCompositionVersion` 是不可变成果版本，同时固化版式快照和工程快照；正式发布通过 `published_version` 指向一个固定版本。
- `audience_groups` 只在专题状态为 `published` 时生效。发布范围用户的预览、下载和还原能力仍由功能权限决定。
- 平台管理员、超级管理员通过统一的 `user_has_full_data_access` 获得全部工程和专题对象范围；具体操作仍由功能权限和后端接口校验。
- 还原专题时始终新建工程，不覆盖来源工程，并过滤当前用户不可访问或已失效的数据资源。

### 后端架构原则

- `services/__init__.py` 作为栅格服务包的当前公共导出入口，供视图层和测试按稳定模块边界导入。
- `services/` 内部模块按职责拆分：纯函数模块（`rules_engine`、`color_mapping`、`geo_utils`、`progress`）无外部依赖，可独立单元测试。
- `profile.py` 是 `catalog.data_query` 访问栅格数据的唯一入口，避免了 `catalog.data_query ↔ raster.services` 的循环依赖。
- `catalog.vector_store` 是 GeoPackage 矢量数据的深模块；列表、profile、字段元数据、空间查询、属性查询和图层要素读取都应通过该模块，避免视图层或扫描逻辑直接读取 `vector/vector.gpkg`。
- 栅格 XYZ 瓦片样式注册状态归 `raster.services.renderer` 所有；`jobs.py` 只维护异步任务状态、进度消息和导出 artifact 路径。
- 权限检查集中在 `permissions.py`，视图层仅负责 HTTP 协议处理。
- 异步任务（`jobs.py`）通过线程池 + 全局字典管理，进度通过轮询接口返回。

## 首批后端边界

- 当前后端迁移基线面向全新部署生成，不保留旧数据库升级兼容迁移。重新部署时应使用空业务数据库运行 `python manage.py migrate --noinput`，历史迁移链、旧权限清理和旧表结构升级逻辑不作为交付路径。
- 使用 Django 内置 auth、session、permission；平台后台是登录后的功能入口，所有登录用户可进入，后台内部菜单、页面和操作通过平台功能权限决定是否显示和访问。
- 管理后台使用前端 `/admin/` SPA 路由承载。
- 自助注册默认由 TOML 的 `system.allow_registration` 开启；迁移会创建单例 `SystemSetting`，管理员可在后台关闭注册。系统初始化单独创建 `admin` 并加入 `超级管理员`，所有自助注册账号始终先加入 `普通用户`，不存在“首个注册用户自动成为管理员”的规则。
- 本地前后端分离开发时，Vite dev server 代理 `/api` 到 Django；`[runtime].debug = true` 且未显式设置 `csrf_trusted_origins` 时，后端默认信任本地开发服务器地址，确保首次注册和登录的 CSRF Origin 校验通过。
- 运行日志统一写入业务数据根目录的 `logs/`：Django 应用日志、Django 框架日志和安全日志都落在该目录；容器运行时的 Waitress 进程日志由容器标准输出收集。
- Docker 镜像使用 `backend/pixi.lock` 安装 Pixi 后端运行环境，使用 pnpm 构建 `frontend/dist`，由 Django/WhiteNoise 在 WSGI 进程内提供前端静态资源和 SPA fallback；宿主机如需公网访问，可在容器端口前自行配置反向代理。
- Docker 启动入口必须先创建固定业务/地理/非地理数据子目录，再执行 `python manage.py migrate --noinput` 和 `collectstatic`，确保空 appdata 首次启动即可使用初始化生成的管理员账号。
- SQLite 数据库放在业务数据根目录的 `database/` 下。
- 所有矢量数据统一从地理数据根目录下的 `vector/vector.gpkg` 读取；业务库中的矢量 `storage_path` 和图层 `source_path` 字段填写该 GeoPackage 内的图层名，后端读取并输出 GeoJSON。
- Excel/CSV 导入分为预检与提交两步。预检按当前工作表读取全部字段并自动推测常见经纬度列；未识别到经纬度时前端默认选择非地理表格入库并明确提示最终列表去向，只有显式选择有效经纬度列并通过校验后才能以地理点表提交。
- 导入的地理表统一写入 `vector/vector.gpkg` 的点图层，并创建对应 `DataResource`，`DataResource.name` 保存用户填写的数据名称，`storage_path` 保存 GeoPackage 图层名。资源列表只展示业务库中登记的 `DataResource`。
- 导入的地理表字段级描述写入 GeoPackage `gpkg_data_columns`，记录键为 `table_name + column_name + description`。强行导入空坐标时允许 GeoPackage 保留空几何记录，但图层要素接口和查询 GeoJSON 输出会过滤空几何，避免前端地图渲染异常。
- 导入的非地理表统一写入 `table/data.sqlite`，业务表之外维护 `data_columns(table_name, column_name, description)` 作为 SQLite 侧字段元数据实现。非地理导入只登记 `DataResource`，不创建 `MapLayer`，资源 `storage_path` 记录 SQLite 内的表名。
- `DataResource.spatial_class` 由实际资源形态统一派生：`vector/raster -> spatial`，`table/gene/document/image -> non_spatial`。`GET /api/catalog/resources/` 使用 `spatialClass` 参数隔离地理与非地理工作台；`domainType` 仅负责业务专题归类，不能将无坐标表格带入地图资源列表。
- 坐标量化误差按经纬度文本小数位数估算：每个坐标分量取最后一位小数半个单位作为最大角度误差，纬度方向按 111320 m/deg 换算，经度方向乘以 `cos(latitude)`，再合成平面最大可能误差；该值只表示坐标记录精度引入的位置不确定性，不包含测量设备误差。
- 栅格数据统一放在地理数据根目录的 `raster/` 总目录下：源文件放在 `raster/original/`，导入后预处理 COG 放在 `raster/preprocessed/`，两份 `gdalinfo -json` 元数据放在 `raster/metadata/source/` 和 `raster/metadata/preprocessed/`。
- 非地理数据统一放在非地理数据根目录下：基因数据放在 `gene/`，表格数据放在 `table/`。后端目录扫描会登记 `gene` 和 `table` 类型的 `DataResource`，不创建地图图层。
- 栅格导入预处理固定使用 `gdalwarp` 将源文件转换为 EPSG:3857 的 COG 格式，导入记录保存源文件、预处理文件、两份 GDAL 元数据、导入时间、处理日志、错误信息、默认符号化规则、范围和关联数据资源/地图图层。GDAL 命令统一使用单线程、128 MB 缓存/工作内存和 TOML `symbolizer_timeout_seconds` 硬超时；超时必须终止进程组，不能让任务线程永久等待。
- 命令行工具统一通过 `apps.core.cli` 调用。未检测到已激活 Pixi 环境时以 `pixi run --executable ...` 从 `backend/` 工作目录启动；Docker entrypoint 通过 Pixi hook 激活环境后直接运行普通命令。业务模块不应自行拼接 Pixi 命令。
- Docker 入口脚本不得硬编码 `.pixi/envs/default/bin` 或具体 Python 路径；启动时先通过 `pixi shell-hook --no-completions --manifest-path /opt/app/backend/pixi.toml` 激活 Pixi 环境，再执行普通 `python manage.py ...`、`waitress-serve` 等命令。
- 后台数据导入页支持直接上传栅格源文件；后端必须先保存到 TOML 驱动的科研数据根目录 `raster/original/uploaded/`，再复用现有异步导入任务执行 GDAL 预处理。前端只负责上传、轮询 `/api/raster/jobs/{job_id}/` 和展示进度，不做栅格解析、重投影、COG 生成或符号化。
- 浏览器上传的栅格只有完整预处理并登记成功后才保留；异步导入失败时必须删除本次 `uploaded/` 源文件、预处理文件和两份 GDAL 元数据。服务端已有 `sourcePath` 导入和目录扫描失败时不得删除原始研究数据。
- 栅格导入、扫描、渲染和导出共用一个单并发且等待队列有硬上限的重型任务执行器，并且必须在任务线程内建立、关闭自己的 Django 数据库连接。队列饱和时任务要明确失败并提示稍后重试，不能为每次请求裸建线程。SQLite 元数据库启用 WAL 和 30 秒 busy timeout；导入进度属于临时任务态，只更新内存任务消息，不写入 `RasterDataset.progress_log`，避免上传预处理期间频繁写库导致 `database is locked`。完成任务的内存缓存必须同时受 TTL 和最大条目数约束，服务重启后遗留的 queued/running 持久任务要标记为中断。
- 系统设置页更新运行期配置后，后端必须同步刷新运行中的 `settings.PROJECT_CONFIG`；业务运行期可变配置统一通过 `apps.core.runtime_config` 从当前 TOML 读取，包括系统名称、注册开关、查询结果上限、栅格上传大小和栅格单边像素上限，避免手工改配置或设置页保存后继续使用旧值。前端也必须同步刷新应用 `bootstrap.limits`，避免栅格上传前校验继续使用旧上限。后台设置与直接 TOML 读取共同强制可配置的栅格与独立成果上传为 1–1024 MB、查询 100–10,000 条、栅格单边 1–12,000 像素、栅格任务超时 10–600 秒；Waitress 使用 1152 MiB 请求体和 720 秒连接超时为 multipart 与最长栅格任务留余量，Django 仍以 2 MiB 文件阈值把大文件落盘。矢量导入因 GeoPandas 整层读取而另取平台配置与 120 MB 的较小值，表格在线解析另取平台配置与 16 MB 的较小值；专题出图 PNG 固定使用独立 128 MB 上限，在完整解码前校验字节数和像素边界，且不随 `uploadMaxMb` 变化。Docker 必须把可写配置目录挂载到 `/config`，使后台能够在同一目录内通过临时文件和 `os.replace()` 原子持久化，不能单独 bind mount `/config/app.toml`。栅格导入界面分开展示浏览器文件上传进度和后端 GDAL 预处理进度。
- 前端加载栅格 XYZ 瓦片源时必须用数据集 `imageCoordinates`/`bounds4326` 约束 Mapbox source 的 `bounds`，避免按整个地图视窗请求无关瓦片；后端对栅格空间范围外的瓦片请求返回 `204 No Content`，并且应在打开栅格文件前优先用 `RasterDataset.bounds_3857` 快速判断。
- 后端启动 `runserver` 或 WSGI/ASGI 进程时可异步扫描 `vector/vector.gpkg`、非地理数据 `gene/`、`table/` 和 `raster/original/` 下已有数据；矢量图层会登记为 `DataResource/MapLayer`，非地理文件登记为 `DataResource`，栅格源文件会完成预处理并登记目录。迁移、测试等管理命令不触发扫描。小内存生产示例默认通过 TOML 的 `disable_catalog_startup_scan` 和 `disable_raster_startup_scan` 关闭启动扫描，待服务健康后再由维护用户手动触发。
- 启动扫描的服务命令判断必须覆盖 `runserver`、`waitress`、`uvicorn` 和 `daphne`；Docker 的 `waitress-serve geomanager.wsgi:application` 是生产启动路径，不能被当成普通管理命令跳过。目录扫描会通过 SQLite 读取统一 GeoPackage 元数据并枚举全部图层，为每个图层同步 `DataResource` 与 `MapLayer`；空间查询优先使用 GeoPackage RTree/bbox 和属性 SQL 下推，再以固定大小 GeoDataFrame 分块执行精确几何过滤，最多只保留本次返回上限内的结果。几何校验只能单遍维护计数和误差 min/max，不得保存全量顶点或误差列表。
- 普通 JSON/form 请求体由 Django 10 MB 内存上限保护；导出 JSON 另有 10 MB 有限流读取，缺少或伪造 `Content-Length` 也不能绕过。同步和异步 ZIP 导出均直接写临时文件并以流式文件响应下载，生产路径不得调用 `Path.read_bytes()` 构造完整 ZIP 副本。Excel/CSV 在线解析上限固定取平台上传限制和 16 MB 的较小值，XLSX 解压后另受 128 MB 上限保护，并直接从上传文件/临时文件交给 Pandas，避免原始 bytes 副本。
- 启动扫描或目录扫描新发现的数据资源不设置上传者/维护人，后台界面显示为“未知”；资源和关联图层访问组强制且仅保留 `超级管理员`，避免首次部署时把存量数据自动暴露给普通角色。若扫描命中已经由用户上传登记的 GeoPackage 图层，只刷新范围、坐标系、条目数等技术元数据，必须保留 `DataResource.maintainer`、用户填写名称、上传大小、访问组以及已保存的默认图层样式，并让维护人继续可见其关联 `MapLayer`。

## 统一功能权限

- 平台功能权限统一基于 Django `Permission + Group`，不引入独立角色表。用户通过所属用户组获得功能权限。
- 产品和前端界面统一把 Django Group 表述为“角色”；接口字段和后端模型名保留 `group*` 命名以兼容 Django auth 和既有 OpenAPI 路径。
- `apps.core.permissions.FEATURE_PERMISSIONS` 是统一注册表；后台用户组配置页只同步注册表内权限，保留用户组已有其他模型权限。
- 功能权限元数据按 `后台权限`、`数据权限`、`人员权限` 三类返回，前端认证授权页按该分组展示和维护。
- 迁移后初始化会先按注册表统一创建或更新 Django `Permission` 记录，再同步 `超级管理员` 用户组并补齐全部功能权限，同时创建 `普通用户` 用户组并授予全部科研数据相关权限，包括浏览、查询、导入、导出、存量数据维护、工程/专题增删查改、矢量/栅格加载、自定义符号化和栅格数据管理。
- 管理员新建普通用户和修改普通用户组归属时必须保留至少一个用户组；自助注册用户默认加入 `普通用户` 用户组。
- 自助注册和后台新建用户的邮箱均为必填项。后端统一去除首尾空格并转为小写，`UserProfile.normalized_email` 作为非空邮箱唯一身份；`auth_user.email` 继续作为 Django 用户联系字段并与其同步。游客系统账号不占用邮箱身份。
- 注册请求使用 `accountPurpose=standard|research` 表达账号用途，而不是直接选择实际角色。`research` 会创建独立 `RoleApplication` 待审核记录，审核前仍为普通用户；具备 `core.manage_auth` 的管理员批准后移除普通用户角色、加入科研用户角色并保留其他自定义角色，拒绝时不改变现有权限。
- 平台管理员属于受控管理角色：只有超级管理员可以在后台创建用户或调整角色时分配平台管理员角色；科研用户申请仍可由具备 `core.manage_auth` 的日常管理员审核。
- 当前过渡阶段不发送邮箱验证码，也不开放邮件找回密码。登录页忘记密码入口明确引导联系管理员，管理员继续通过现有重置密码接口生成仅展示一次的临时密码。
- 数据资源和图层的 `access_groups` 继续控制“能看见哪些对象”；功能权限控制“能对可见对象做什么”。
- 首批平台功能权限包括：功能权限配置、数据浏览、数据查询、矢量加载、栅格加载、自定义符号化等后台内部功能权限。
- 数据和工程/专题的增删查改均使用 Django 模型 CRUD 权限并纳入同一用户组配置入口：`catalog.add/view/change/delete_dataresource`、`catalog.add/view/change/delete_workspacescene`。`catalog.add_dataresource` 控制后台导入，`catalog.change_dataresource` 控制存量数据启停、默认可视化和访问范围配置，`catalog.delete_dataresource` 控制删除确认。
- Dashboard 数据概览卡片始终返回当前用户自己的上传统计 `ownUploads`，无需额外功能权限；`core.view_data_overview` 只控制“我可见”范围 `visibleResources`、兼容旧版的系统总量字段，以及超级管理员按 `DataResource.maintainer` 聚合的上传用户统计。
- 前后端无权限提示统一为 `当前角色“xxxx”无权限`；无角色时显示 `未分配角色`。
- 用户级权限关闭统一写入 `UserProfile.disabled_permissions`。后台认证授权页可以关闭角色继承权限或单独授予权限，但不修改角色本身；后端保存前会把关闭列表裁剪到该用户已授予权限集合。
- `core.load_raster_layer` 控制按默认规则加载栅格和访问 XYZ；`core.custom_symbolization` 只控制用户打开符号化编辑器并提交自定义规则。
- 栅格渲染 API 使用 `rulesMode` 区分默认/自定义：默认加载不传 `rules` 或传 `rulesMode: "default"`；自定义符号化传 `rulesMode: "custom"` 和 `rules`。
- 游客访问使用专用系统账号 `guest` 和独立 `游客` 用户组实现，不再复用 `普通用户` 组。`普通用户` 继续用于自助注册和后台创建的常规账号，默认保留全部科研数据相关权限；`游客` 默认不授予任何功能权限。`guest` 账号密码不可用，只能通过 `/api/auth/guest-login/` 建立会话，并在后台管理中禁止删除、停用、重置密码、改组或单独授予直授权限。
- Dashboard 的活跃账号与登录次数使用两套独立口径：认证中间件按本地时区每用户每小时最多写入一条 `UserActivityHour`，用于日/周/月去重活跃账号和柱状图；成功建立会话通过 `OperationLog.event_code` 的稳定认证事件编码统计，包含账号密码、游客和注册自动登录。迁移会从历史成功操作日志回填小时活跃记录，并为历史认证日志回填事件编码，禁止再次使用中文模块/动作文本作为统计主键。
- `游客` 内置组与 `guest` 游客账号都不可删除；前端禁用删除入口，后端继续作为强制安全边界。

## 前端模块结构

```
frontend/src/
├── main.tsx                    # React 入口，Ant Design 中文 + 主题
├── App.tsx                     # 引导（bootstrap + auth），登录/工作台路由
├── types.ts                    # 全局类型定义；后端 DTO 从 OpenAPI 生成类型派生
├── symbolization.ts            # 符号化类型、默认值、规则解析
├── styles.css                  # 全局样式
├── api/
│   ├── client.ts               # Hey API SDK 门面、CSRF、统一错误处理
│   └── generated/              # @hey-api/openapi-ts 自动生成的类型、SDK 和 fetch client
├── pages/
│   ├── LoginPage.tsx            # 登录页
│   └── MapPage.tsx              # 地图工作台主页面（协调各组件）
├── components/
│   ├── MapCanvas.tsx            # Mapbox GL JS 地图组件
│   ├── DataPanel.tsx            # 数据管理面板
│   ├── LayerPanel.tsx           # 图层管理面板（从 LayerContext 消费状态）
│   ├── RightSidePanel.tsx       # 右侧导航式信息面板
│   ├── WorkspaceBottomPanel.tsx # 底部导航式绘制/元数据面板
│   ├── LayerDataTableModal.tsx  # 图层数据表弹窗
│   └── SymbolizationEditor.tsx  # 符号化编辑器
├── hooks/
│   ├── LayerContext.tsx          # 图层状态 Context，消除 props drilling
│   ├── useLayerGroups.ts        # 图层组 CRUD（12 个操作）
│   └── useRasterRender.ts       # 栅格渲染调度/轮询/结果应用
├── workspace/
│   ├── workspaceSnapshot.ts      # 工程/专题轻量快照序列化，不保存 GeoJSON 要素集合
│   ├── workspaceRestore.ts       # 工程/专题快照恢复，必要时按资源引用重新查询矢量图层
│   └── workspaceNotifications.tsx # 工程/专题进度和 GeoJSON 警告通知
├── map/
│   ├── mapState.ts              # WeakMap<Map, MapInternalState> 状态管理
│   ├── styleHelpers.ts          # Mapbox 样式层增删改工具
│   ├── vectorLayerSync.ts       # 矢量图层同步 + 符号化映射
│   ├── rasterLayerSync.ts       # 栅格图层同步
│   ├── featureInteraction.ts    # 单击选中与 hover 高亮交互
│   └── spatialDraw.ts           # 空间绘制预览
└── utils/
    ├── geometry.ts              # 纯几何计算、边界合并、工具函数
    └── layerFactory.ts          # 矢量/栅格图层组构建工厂
```

### 前端架构原则

- **模块职责单一**：每个文件只承担一个独立职责，最大文件不超过 250 行。
- **纯函数与 React 分离**：`utils/` 和 `map/` 中的纯函数可独立测试，不依赖 React 生命周期。
- **WeakMap 替代属性挂载**：`mapState.ts` 用 `WeakMap<Map, MapInternalState>` 管理 Mapbox 实例的内部状态，避免在 map 对象上挂载自定义属性。
- **Context 消除 props drilling**：`LayerContext` 提供图层组全部操作，`LayerPanel` 零 props 通过 `useLayerContext()` 消费。
- **地图工作台持久化深模块**：`hooks/useWorkspaceScenes.ts` 负责工程/专题列表、保存、加载和恢复；`workspace/workspaceSnapshot.ts` 负责轻量快照序列化，必须避免把矢量 `geojson.features` 写入服务端工程/专题快照。
- **Discriminated union 类型安全**：`LoadedLayer = LoadedVectorLayer | LoadedRasterLayer`，通过 `layerType` 字段判别，编译期消除可选字段歧义。
- **OpenAPI 契约驱动类型**：`frontend/src/api/generated/` 由 `docs/openapi.yaml` 通过 `@hey-api/openapi-ts` 生成；`frontend/src/types.ts` 只保留前端运行态类型、少量 UI 扩展和对生成 DTO 的统一转出。
- **类型安全 API 请求**：`frontend/src/api/client.ts` 调用 Hey API 生成的 SDK 函数，并集中处理 CSRF、中文错误、Blob 下载文件名和业务资源分支；路径、路径参数、查询参数和 JSON 请求体必须来自 `docs/openapi.yaml`。
- **API 类型生成命令**：修改 `docs/openapi.yaml` 后运行 `pnpm run generate:api`，该命令先执行 Redocly lint 再生成 `src/api/generated/`；提交前运行 `pnpm run check:api` 确认 OpenAPI lint 通过且生成文件未漂移。
- **API 文档生成命令**：运行 `pnpm run api:docs` 生成 Redoc HTML 文档，运行 `pnpm run api:bundle` 生成单文件 OpenAPI bundle，便于查阅和外部工具导入。

## 首批前端边界

- 统一登录页不展示独立后台入口。
- 登录后默认进入 `/map` 地理数据工作台，不再展示独立的可视化入口页。保留现有 `/`、`/map`、`/nongeo`、`/resources` 和 `/admin` 路由路径，其中 `/` 作为系统根入口重定向到 `/map`。
- 地理数据界面、非地理可视化、数据管理和管理后台作为工作台顶栏入口呈现，并按当前路由显示选中态；`/nongeo` 复用同一工作台顶栏，仅切换主体内容区并隐藏地图、图层树、右侧属性面板和底部工具面板；数据管理 `/resources` 与后台 `/admin` 均使用后台式侧边菜单和内容区，但职责分离。
- 前端仅做矢量样式表达和 XYZ 瓦片叠加，不实现栅格符号化。
- Mapbox 公共 token 从 TOML 的 `[application.map].mapbox_access_token` 读取，经后端 bootstrap 下发，前端不硬编码默认 token。
- Mapbox 底图标注语言使用 `zh-Hans`，并在样式加载后优先读取中文名称字段。
- 前端初始化 Mapbox GL JS 时禁用 `EVENTS_URL` 和性能指标采集，避免浏览器插件拦截 `events.mapbox.com` 后产生控制台噪声；样式、瓦片和业务接口请求不受影响。
- 主交互地图保持 Mapbox GL JS 默认的 `preserveDrawingBuffer=false`，避免持续拖慢 WebGL 渲染；仅地图图片导出的离屏 Mapbox 实例启用绘图缓冲。
- 前端矢量 GeoJSON source 选项按图层 `geometryType`、要素数量和符号化配置确定：点图层使用 `buffer: 0` 和较低 `maxzoom`；只有非热力点图层显式设置 `symbolization.cluster.enabled=true` 时才启用 Mapbox source clustering，默认保持独立点显示；大型线/面图层启用 source `tolerance`，避免在每次同步时重扫 GeoJSON。
- 空间范围绘制的多边形预览在点数不足 3 个时使用 `LineString`，点数满足闭合条件后再切换为 `Polygon`；预览填充层和线层都带几何类型过滤，避免向 Mapbox 图层传入不匹配几何导致运行时异常。
- 工作台图层显隐统一通过 Mapbox 样式层的 `layout.visibility` 切换：从未显示过的隐藏图层保持延迟创建，已经加载的矢量和栅格 source 在隐藏后继续保留，只有图层真正移出工作区时才删除 source。首次底图样式同步由 `style.load` 驱动，后续图层状态变化不得再以 `isStyleLoaded()` 配合一次性 `load` 事件作为同步门槛，避免 source 或瓦片加载期间丢失显隐操作。
- Mapbox `error` 事件按反馈层级处理：活动天地图的后台瓦片波动进入底部状态诊断，自动恢复只在完成后提示一次结果；业务图层、Mapbox/OSM 与未知地图错误仍可进入顶部消息，但使用单一消息实例，将 HTTPS 与 `mapbox://` 资源 URL 归一化后语义去重并执行 60 秒冷却。没有结构化 Provider 详情的单个天地图 `sourcedata` 错误不再直接判定整套底图失败，避免外部服务抖动形成红色状态和弹窗风暴。
- 鼠标经纬度面板先用 Mapbox `map.isPointOnSurface(event.point)` 判断鼠标是否落在地球表面；不在地球表面时清空显示，在表面时使用 `event.lngLat.wrap()` 并限制到合法经纬度范围。不从屏幕像素、瓦片坐标或墨卡托坐标自行换算。

## 管理后台实现约定

- 管理后台通过前端 `/admin/` SPA 路由承载，使用 `@ant-design/pro-components` 的 `ProLayout`、`PageContainer`、`ProTable`、`ProForm` 和 `ProCard`。
- `/admin/` 默认进入运行概览；后台运行概览保留用户信息、活跃用户和服务器信息。操作日志、系统设置、认证授权根据功能权限显示。数据概览中的数据资源、图层、栅格和数据体量相关部分归入数据管理 `/resources/`，数据导入和存量数据管理也归入数据管理，不再作为后台管理菜单项。
- 后台入口只要求登录态，具体页面、菜单和操作必须同时由前端权限展示和后端权限校验控制。
- 后台“数据备份”入口使用独立功能权限 `core.manage_data_backup`，默认且锁定授予 `超级管理员` 角色，不随系统设置权限开放给普通角色。备份 API 还必须二次校验当前主体属于内置 `超级管理员`，避免普通账号被误授予权限后执行备份。备份目标支持不推荐的本地目录和推荐的 S3 兼容对象存储；对象存储参数由超级管理员通过前端配置，`secretAccessKey` 不回显。备份任务写入持久化 `BackupRun`，用户主动配置、测试和发起备份写入 `OperationLog(module="数据备份")`。
- 用户设置和系统设置默认只读，点击编辑后进入编辑态；后台创建用户不受自助注册开关影响，但必须具备 `core.create_user` 权限。
- 用户组权限配置复用 Django `Group`/`Permission`，必须具备 `core.manage_feature_permissions` 权限；超级管理员用户组不能删除，初始化的 `admin` 用户不能从该组移除。
- 数据导入入口统一为单个任意文件上传区，前端按扩展名自动分流：CSV/Excel 复用 `/api/catalog/import/preview/`、`/api/catalog/import/validate/` 和 `/api/catalog/import/commit/`，流程为文件预检、导入配置校验、数据预览和字段元数据维护；GeoTIFF/IMG/VRT 复用 `/api/raster/import/` 和栅格任务轮询；尚无后端导入流程的文件类型必须显示“暂不支持自动导入”，不得误调用表格或栅格接口。
- 应用只使用 TOML 配置。后端通过 `--config /path/to/app.toml` 接收源配置，启动、迁移和后台设置都以该源配置文件作为读写目标。

## 数据管理与图层管理

- 数据管理负责浏览、按元数据筛选、读取字段与元信息、配置空间查询和属性查询。
- 栅格上传的显示名和后台存储标识必须分离：`RasterDataset.name`、`DataResource.name`、`MapLayer.name` 使用用户填写的 `name` 或原始上传文件名；上传源文件保存为 `uploaded/<uuid><suffix>`，预处理路径和 `RasterDataset.code` 仅作为后台唯一存储/任务标识，不包含原始文件名，也不在数据资源、图层或工作台显示名称中展示。
- 地图工作台左侧保留数据面板，负责当前地图会话内的数据筛选、选择、快速加载和查询加载；顶栏“数据管理”进入 `/resources/` 面板，负责数据概览、存量数据管理和数据导入。
- 图层管理只管理已经加载到地图上的查询结果，不直接承担数据检索职责。
- 数据加载流程固定为：工作台打开后自动扫描数据目录并刷新资源列表 -> 自动加载已有可查询/可渲染资源到地图；用户也可筛选或选择数据资源 -> 后端返回字段与元信息 -> 执行空间/属性查询 -> 将查询结果加载为临时图层。
- 已保存工程/专题卡片仅展示名称和说明，必须通过“加载”按钮恢复工作台；创建、编辑名称/说明、覆盖快照和删除都要通过工作台操作日志记录。
- 空间查询由前端在地图上绘制矩形、圆、椭圆或多边形，作为 GeoJSON geometry 传给后端。
- 元数据查询作用于资源列表，当前支持名称、数据类型、分类、来源、提供单位和日期范围。
- 属性查询基于后端读取到的字段列表构建过滤条件，后端在 GeoPackage 读取结果上执行过滤。
- 后端资源能力边界：只有带 `storage_path` 的矢量 GeoPackage 资源可查询；元数据资源只可浏览和筛选。
- 数据管理 `/resources/data/inventory` 是存量数据管理入口，使用 `/api/admin/data/resources/` 查询启用和禁用资源；常规业务目录 `/api/catalog/resources/`、搜索和资源 profile/query 仍只处理 `status=active` 的数据资源。
- 工程和专题管理归入数据管理区，前端入口为 `/resources/manage/projects` 和 `/resources/manage/topics`。二者与存量数据管理复用同一管理组件结构：列表筛选、状态控制、信息抽屉、访问用户组配置和删除确认；后端契约为 `/api/admin/workspaces/`。
- `DataResource.maintainer` 同时作为上传用户和维护人员的来源；后台数据资源接口暴露结构化 `uploader`。`DataResource.size_bytes` 和 `DataResource.item_count` 记录数据大小与条目数：Excel/CSV 导入使用上传文件大小和导入行数，栅格资源使用源文件与预处理文件大小，扫描到的非地理文件使用文件大小。
- Excel/CSV 导入的后台存储标识与前端显示名分离。预检每次生成不同的 `suggestedTableName`，提交时如已有资源或真实存储已占用同一 GeoPackage 图层名或 SQLite 表名，后端会再次改写为唯一值；每次提交都创建新的 `DataResource` 记录，不按后台存储标识更新旧资源。重复检测按前端显示名 `DataResource.name` 执行：预检使用 `suggestedName`，校验和提交使用 payload 的 `name`；同名显示数据提交必须由后端阻断，除非用户已在校验阶段确认重复名称并提交 `duplicateConfirmed=true`。确认后也只会新建资源，不覆盖旧数据。
- `DataResource.default_visualization` 保存默认可视化方案 JSON；空间资源保存方案时会创建或更新关联 `MapLayer`，同步默认图层名称、默认显隐、既有默认透明度、矢量符号化和栅格规则。前端存量数据配置不再提供单独默认透明度控件；栅格色带和 PNG/XYZ 生成仍由后端栅格服务处理。
- 存量数据启停、默认可视化保存、访问用户组配置、删除和清单导出均写入 `OperationLog(module="数据管理")`。删除用户导入的矢量/表格资源时清理 GeoPackage 图层或 SQLite 表；栅格等可能复用的研究数据文件保留，仅删除资源登记和关联图层。
- 用户导入、目录扫描和栅格导入数据的可见范围由 `DataResource.access_groups` 和 `DataResource.maintainer` 共同控制：上传者本人强制可见，`超级管理员` 用户组强制写入访问组，用户选择的 `accessGroupIds` 表示额外可见用户组。选择 `游客` 用户组表示无需账号即可通过游客会话访问，前端上传和存量数据管理都必须提示。
- 存量数据可见范围可由上传者本人或具备 `catalog.change_dataresource` 的用户修改；上传者只能执行 `updateAccess`，启停和默认可视化需要 `catalog.change_dataresource`，删除需要 `catalog.delete_dataresource`。`GET /api/admin/data/resources/` 对仅具备 `catalog.add_dataresource` 的上传用户开放时只返回其本人上传的数据。
- 存量数据管理表格使用嵌套子表格按内容分组展示：父表展示“默认分组”和后端持久化自定义组别，子表复用原资源清单列。`DataResourceGroup` 保存组别名称，`DataResource.inventory_group` 保存资源所属组别；默认分组由 `inventory_group = null` 表示。删除组别时后端通过 `SET_NULL` 使组内数据进入默认分组且数据本身不删除。组别启停通过现有 `setStatus` 对组内资源逐条同步启用/禁用状态。
- 操作日志中的模块、动作和说明统一使用中文，只记录用户主动发起的关键行为。认证、用户组、用户、系统配置、存量数据管理、导入预览/校验/提交、数据查询、已加载图层导出、异步导出发起/下载、个人资料更新、个人权限开关更新、栅格渲染样式注册、栅格渲染任务发起、栅格唯一值统计和栅格导入写入 `OperationLog`。目录扫描、启动扫描、后台数据发现和异步任务内部执行进度不写入操作日志，应保留在系统日志或异步任务消息中。
- 系统日志查看复用日志入口权限 `core.view_operation_logs`，接口只读取业务数据根目录 `logs/` 下的 `.log` 与轮转 `.log.N` 文件，按文件名选择并返回尾部文本内容，不暴露服务器绝对路径，也不提供跨目录或整文件下载能力。
- 操作日志 IP 记录优先识别反向代理传入的 `CF-Connecting-IP`、`True-Client-IP`、`X-Real-IP`、`X-Forwarded-For` 和 `Forwarded` 头，并在候选链路中优先选择公网 IP；没有有效公网 IP 时才回退到首个可识别地址或 `REMOTE_ADDR`。公网部署必须由前置代理传递真实客户端 IP，否则容器内只能看到 Docker 网桥地址。

## 当前图层树约定

- 数据加载后的默认展示单位是顶级图层，不再在界面上自动显示为图层组。用户需要组合管理时，可通过“新建图层组”手动创建组并将图层拖入。
- 前端运行态仍使用 `LoadedLayerGroup.children` 作为统一容器，以兼容缓存、工程/专题快照、图层排序和栅格渲染上下文；非手动且只有一个子图层的容器在图层面板中渲染为顶级图层。
- 图层树从上到下对应地图从上到下的覆盖顺序，树中第一项为地图最上层。拖拽落点必须在 `drop` 发生时按当前目标元素和当前指针纵坐标同步判定，禁止复用上一帧 `dragover` 的异步状态；结束拖拽时必须取消待执行动画帧，避免旧落点覆盖最终顺序。
- 矢量数据查询结果来自统一 GeoJSON 数据源，正常情况下每次加载生成一个顶级矢量图层。
- 栅格数据在前端状态模型中持有栅格子图层，子图层包含 `tileUrl`、Mapbox 图片角点、透明度、元数据和符号化配置；栅格符号化仍由后端完成。
- 手动图层组保留显隐、定位、导出、排序和移除入口，不再提供图层组符号化入口；子图层保留独立显隐、定位、导出和符号化入口。
- 子图层提供数据表按钮，点击后以弹窗展示整层属性表；元数据在底部导航面板中展示。
- 已加载图层组默认按当前用户写入浏览器 IndexedDB 的 `huyang-system-map-workspace/layer-groups`，保存完整前端运行态（包含矢量 GeoJSON 查询结果、栅格 tile URL、显隐、顺序、命名、符号化方案、栅格渲染元数据和当前本地工作台状态）。地图页刷新或切换界面后由 `useLayerGroups` 自动恢复；缓存失败只影响本地恢复，不改变后端数据和权限边界。服务器端工程/专题只在用户显式保存时写入 `WorkspaceScene`，并且只保存轻量引用快照：图层结构、资源引用、查询条件、空间范围、符号化和栅格 tile/渲染引用元数据，不保存矢量 GeoJSON 要素集合、属性表行或查询结果数据本体；恢复时按资源引用和查询条件重新查询。后端会拒绝包含 `geojson` 或 `FeatureCollection.features` 的快照以及超大请求体，不做实时 server autosave。
- 保存工程或专题时，前端保存弹窗支持新建保存项或覆盖当前用户已有的同类型保存项。新建调用 `createWorkspace`，覆盖调用 `updateWorkspace` 并只替换轻量快照，已有保存项名称和说明保持不变。
- 恢复工程或专题时，前端按快照中的资源引用重新查询矢量图层，并校验栅格原始资源 profile。缺少查询条件、权限不足、原始资源不存在/停用、栅格资源变更等情况必须在加载完成后汇总提示用户；可恢复的图层继续恢复，不可重建的矢量图层跳过。账号缺少栅格加载权限或 profile 返回 403 时，栅格图层必须直接跳过且不得复用旧瓦片 URL；只有其他临时校验异常才允许保留快照引用并提示风险。

## 矢量图层符号化与交互

- 图层组和子图层均支持在图层树内直接改名；当前改名属于前端临时工作台状态，后续如需保存到业务库，应接入后端图层配置接口。
- 透明度在子图层符号化面板中配置；图层组不再提供单独透明度配置入口。
- 点要素符号化按 Mapbox Style Specification 的 `circle` 和 `symbol` 图层拆分：`circle` 参数覆盖颜色、半径、描边、模糊、位移、pitch、sort key、emissive 等；`symbol` 参数覆盖 icon/text 的 layout 与 paint 配置。
- 线、面要素继续使用 Mapbox `line`、`fill` 图层表达，符号化面板同步暴露线色、线宽、线型、填充色、透明度、位移、sort key 等参数。
- 矢量 `renderer.type` 当前支持 `single`、`uniqueValue` 和 `graduated`。唯一值分类使用 Mapbox `match` 表达式，数值分级使用 `case + to-number` 表达式；空值或无法转数字的属性落入 `defaultClass`。两者的 `gm-*` 图标都会在写入 `icon-image` 前注册为按颜色区分的运行时图片。`graduated.method=manual` 表示自定义分级，前端只维护和刷新 `classes[].min/max`，不再按等距或分位数重排区间。
- 每个前端加载的 GeoJSON source 使用 `generateId`，所有矢量 style layer 注册统一交互：鼠标覆盖仅改变指针并高亮要素，单击要素后选中并在右侧导航面板的"要素属性"标签中展示该单条记录属性。
- 主界面侧栏采用当时的 V2 设计布局（原型已清理，历史版本可从 Git 查阅）：左侧统一为 `数据`、`图层`、`工程`、`专题` 四个切换页；右侧拆成上方平面缩略图窗口和下方生态数据窗口，下方包含 `概览`、`要素`、`监测` 三个切换页，其中 `要素` 继续承载地图单击要素属性；底部面板改为空间查询工作区，包含 `空间查询`、`结果`、`时间`、`图例` 标签，`空间查询` 内按左右区域组织范围绘制/导入导出与查询状态/图例占位。共享空间范围仍同时用于空间查询和导出裁切，当前选中图层范围开关继续将 `minLng,minLat,maxLng,maxLat` 范围绘制为地图覆盖层。
- 当前符号化模型位于 `frontend/src/symbolization.ts`，编辑界面位于 `frontend/src/components/SymbolizationEditor.tsx`，Mapbox 转换逻辑位于 `frontend/src/map/vectorLayerSync.ts`。

## 栅格符号化与加载方案

- 栅格符号化规则支持四种模式：单波段灰度（可拉伸）、任意三波段 RGB 组合（可逐波段拉伸并可指定 A 透明度 mask）、单波段伪彩色、单波段唯一值渲染。
- 默认规则按波段数生成：1 波段使用灰度；2 波段使用 `[1, 2, 2]` 映射到 RGB；3 个及以上波段使用 `[1, 2, 3]` 映射到 RGB；默认都启用 min/max 拉伸和 nodata。若处理后 COG 的 `gdalinfo -json` 缺少统计值，默认规则回退使用源文件 `gdalinfo -json` 中的统计值。
- 唯一值不在导入或默认规则阶段预统计。用户在符号化面板选择整型波段后点击“分类”，后端通过 rasterio 按 block window 逐块读取，使用 `np.unique` 合并唯一值集合，不统计数量频次；浮点波段直接拒绝唯一值分类。当前单次分类最多返回 4096 个唯一值，超过说明该波段不适合唯一值渲染。
- RGB 模式支持 A 透明度来源：默认使用 `mask`，也可选择具体整型波段或关闭。XYZ 瓦片通过 Rasterio masked read 处理 nodata，若 A 选择具体波段则同步读取该波段作为 alpha。
- 栅格只支持 XYZ 加载。前端提交符号化规则后，后端按 `(预处理 COG + 规则)` 生成内存样式哈希，瓦片接口 `/api/raster/tiles/{datasetId}/{styleHash}/{z}/{x}/{y}.png` 使用 Rasterio windowed read 直接从 COG 读取 256x256 窗口并实时应用同一套规则。
- 分类栅格的重投影、COG 内部概览、后端 XYZ 输出和 Mapbox 缩放统一使用最近邻；COG 创建时必须忽略源文件已有概览。栅格渲染算法版本同时进入样式哈希、瓦片 URL 查询参数和 ETag，使旧工程、IndexedDB 工作区与浏览器中的旧父瓦片缓存不会在缩放加载阶段混入新版分类瓦片。
- XYZ 返回 tile URL 模板、EPSG:3857 范围、WGS84 范围、样式哈希和实际规则。
- 导入和符号化均通过异步任务接口返回进度。`gdalwarp` 的命令行输出会写入任务消息，前端在图层树中显示进度条和最近消息。
- 工作台初次加载栅格与已加载图层的重新符号化使用同一后端任务能力，但前端状态必须分离：初次加载在数据面板展示加载进度，任务返回完整 XYZ 结果后才把带 `tileUrl` 的栅格图层一次性加入图层树和地图；不得先加入无瓦片地址的占位图层并依赖用户再次打开符号化。图层树中的渲染进度只反馈已加载图层的重新符号化，完成后替换其现有瓦片样式。
- 栅格符号化面板支持复制完整 JSON 方案，内容包含 `opacity`、`mode`、`bands`、`alphaBand`、`nodata`、`stretch`、`palette` 和 `uniqueValues`。后台可在 `RasterDataset.default_rules` 或关联 `MapLayer.raster_rules` 中为不同数据配置默认方案；普通用户无自定义符号化权限时仍可按默认 XYZ 方案完整加载。

## 后端测试

- 测试命令：`pixi run test`
- 纯函数模块位于 `backend/tests/unit/`，不依赖数据库：
  - `test_progress.py` — 进度文本规范化、百分比解析
  - `test_rules_engine.py` — 波段极值、规则归一化、模式校验
  - `test_color_mapping.py` — hex→RGBA、色带、缩放、色彩映射
  - `test_geo_utils.py` — 坐标边界、瓦片计算、样式哈希、相交判断
- 集成测试位于 `backend/tests/integration/`，覆盖 API 端点（bootstrap、layers、resource profile/query）和文件扫描逻辑。
- 测试 mock 目标路径使用模块实际路径（如 `apps.raster.services.importer.import_raster_file`），不使用 `__init__.py` 重导出路径。

## 前端测试

- 测试框架：vitest，测试命令：`pnpm test`
- 纯函数测试位于 `src/utils/*.test.ts`，不依赖 DOM 或 React：
  - `geometry.test.ts` — 几何计算、边界合并、坐标提取、格式化工具
  - `layerFactory.test.ts` — 矢量/栅格图层组构建
- 类型检查：`pnpm run typecheck`（`tsc --noEmit`）
- 代码检查与格式化：`pnpm run check` 使用 Oxlint + Oxfmt，`pnpm run fix` 自动应用 Oxlint 可修复项并写入 Oxfmt 格式化结果。
- API 契约检查：`pnpm run check:api`（Redocly lint + OpenAPI 类型漂移检查）
- 快速生产构建：`pnpm run build`（仅执行 Vite 生产打包）
- 发布/CI 构建验证：`pnpm run build:verify`（check:api + typecheck + vite build）

## Mock Server 与前后端分离开发

- Prism 作为本地 API mock server，前端脚本位于 `frontend/package.json`：
  - `pnpm run mock:build`：从 `docs/openapi.yaml` 生成 Prism 输入文件，并注入 `mock/prism/examples/*.json` 示例。
  - `pnpm run mock:api`：在 `127.0.0.1:4010` 启动 Prism。
  - `pnpm run dev:mock`：使用 `.env.mock` 将 Vite `/api` 代理到 Prism。
  - `pnpm run dev:with-mock`：同时启动 Prism 与 Vite。
- `docs/openapi.yaml` 仍是唯一权威 API 合同；`mock/prism/openapi.prism.json` 是派生产物，不手写维护。
- Mock 示例按业务域拆分在 `mock/prism/examples/`，优先从 `config/app.test.toml` 指向的数据目录抽取真实资源、图层和栅格元数据。
- API 错误响应统一为 JSON：未认证返回 `401 {"detail":"请先登录"}`，CSRF 失败返回 `403 {"detail":"CSRF 验证失败"}`。后端 API 不返回登录页 HTML 或 Django HTML 错误页。

## 前端构建优化记录

- 路由页面使用 `React.lazy` 按需加载，登录、入口、地图、非地理、导入和后台页面由 `App.tsx` 按路由按需导入。
- Vite 按 `React.lazy` 的导入关系拆分 chunk，并过滤首屏 HTML 对后台大包的预加载。
- Mapbox GL JS 和 `mapbox-gl` 样式均从前端 npm 依赖经 Vite 加载，不在 `index.html` 通过 CDN 注入，也不依赖全局 `mapboxgl`。
- `pnpm run build` 定位为快速打包命令；需要类型检查的发布或 CI 流程使用 `pnpm run build:verify`。

## 前端性能基准与优化记录

- 前端性能验收统一使用本地生产构建、Vite preview、Prism Mock API 和 Playwright Chromium 采集。命令为 `pnpm run build`、`pnpm run perf:mock -- --label <label>`、`pnpm run perf:compare -- before after`；结果写入被 git 忽略的 `frontend/perf-results/`。

## 后端性能优化记录

- 矢量资源查询在存在空间过滤条件时，先解析查询几何并将 bbox 下推给 GeoPackage 读取；读取后仍保留 Shapely `intersects` 精确过滤。若无法可靠确认图层 CRS，则回退整层读取，避免误裁剪。
- 数据访问权限判断复用当前请求用户组 ID，并在对象已预取 `access_groups` 时直接使用预取缓存；栅格数据集列表改为数据库侧权限过滤，减少列表接口 N+1 查询。
- 栅格瓦片渲染复用注册阶段已归一化的符号化规则；透明空瓦片 PNG 进程内缓存，避免无相交瓦片重复分配和编码。
- 后续若要继续优化大数据性能，应优先用真实 30k+ GeoPackage 和大 COG 栅格采集接口级指标，重点观察矢量 profile 整层读取、GeoJSON 序列化、唯一值分类和实时 XYZ 瓦片读取耗时。
- 性能脚本覆盖 `/login`、`/map`、`/admin/dashboard`，记录加载时间、FCP、LCP、CLS、长任务数量和耗时、JS heap、资源传输体积与构建产物体积。外部地图瓦片在脚本中以透明 PNG mock 响应，避免公网波动影响本地对比。
- 本轮优化不修改 `docs/openapi.yaml`、后端接口、权限语义、数据路径或栅格渲染架构。API client 保留生成 SDK 类型约束，但把非首屏 SDK 和 fetch client 改为首次业务调用时动态加载；登录、bootstrap、当前用户等启动请求使用同一错误处理和 CSRF 逻辑的轻量 fetch 门面。
- 首屏和路由代码拆分结果：原 `MapPage` 路由 chunk 约 1.89 MB，优化后 `MapPage` 入口约 80 KB，Mapbox 相关代码延后到地图画布加载；原 `AdminDashboardPage` chunk 约 1.47 MB，优化后页面入口约 13 KB，Dashboard 活跃用户图表改为轻量 React/CSS 柱状图，不再为单个图表加载 2 MB 级图表库。
- 登录背景从 2.4 MB PNG 改为约 428 KB JPG，体积降低约 82%；登录页和工作台 Logo 改用约 4 KB SVG，并为图片提供稳定尺寸，避免加载 1024px PNG 和减少布局偏移风险。
- 地图鼠标经纬度显示通过 `requestAnimationFrame` 和 DOM ref 更新，窗口 resize 也按帧合并 `map.resize()` 与视图状态计算，避免高频事件触发 React 重渲染或连续 layout 计算；hover 高亮只在目标 feature 变化时更新 feature-state。
- 地图内部状态统一放在 `mapState` 的 WeakMap 中，包括 `sourceDataRefs`、`loadedSourceIds`、交互 handler 和交互上下文。地图图层同步跳过未变化 GeoJSON 的 `setData`，交互 handler 只注册一次并更新上下文，减少重复解绑绑定。
- 图层数据表弹窗只在打开时构建字段和轻量行索引，行数据不再复制完整 properties，单元格、排序和筛选按 feature index 懒读取原始 GeoJSON；列宽拖拽、图层树 dragover 和工作台头部尺寸测量均按帧合并状态更新，减少拖拽与导航测量造成的重排。
- 符号化编辑器、MapCanvas、后台图表等重型组件按交互或路由懒加载。IndexedDB 工作台缓存改为 debounce 写入、重复快照跳过、串行队列写入，并在页面卸载时 flush 最新快照；超过 8 MB 的图层快照不写入本地缓存并给出提示，避免主线程频繁结构化克隆大对象。
- `index.html` 提供 SVG favicon、主题色和 Mapbox `preconnect`；应用字体继续使用系统中文字体，不引入远程字体。前端构建产物继续使用 hash 命名，部署侧应对 `assets/*` 设置长期缓存、对 `index.html` 使用 no-cache 或短缓存。
- 当前 `perf:compare` 的 bundle 表按 hash 后文件名比较，适合定位构建产物变化，但重命名 chunk 会显示为旧文件移除和新文件新增；结论应优先结合路由入口 chunk、主要库 chunk 和页面指标判断。

## 前端依赖升级兼容记录

- 当前前端升级目标：React `19.2.7`、React DOM `19.2.7`、Ant Design `6.4.3`、`@ant-design/icons` `6.2.5`。
- React 19 检查项：未使用 `ReactDOM.render`、`findDOMNode`、字符串 ref、无参 `useRef()`、旧 `react-dom/test-utils` 或依赖 `ReactElement` 默认 `any` props 的写法；入口仍使用 `react-dom/client` 的 `createRoot`。
- Ant Design 6 适配项：`Alert message` 改为 `title`，`Tabs tabPosition` 改为 `tabPlacement`，`Space direction` 改为 `orientation`，`Popover styles.body` 改为 `styles.content`。
- CSS 风险项：项目仍存在少量基于 Ant Design 内部类名的布局微调（如 Tabs、Table、Descriptions、Switch），升级后需要通过页面走查持续确认 DOM 结构变化没有影响样式。
- 前端 `pnpm-workspace.yaml` 使用 overrides 覆盖开发工具链传递依赖中的 `lodash`、`uuid`、`js-yaml` 安全版本，以消除 Prism/OpenAPI 生成工具链审计漏洞。调整这些 overrides 后必须运行 `pnpm install`、`pnpm audit --audit-level moderate`、`pnpm run mock:build` 和 `pnpm run check:api`，确认锁文件、Mock bundle 和 OpenAPI 类型生成仍可用。

## 版本管理

### 实现概述

项目采用语义化版本（Semantic Versioning）进行版本管理，前后端版本号保持同步更新。

### 文件结构

```
huyang_system/
├── CHANGELOG.md                    # 项目变更日志
├── Makefile                        # 版本管理统一命令
├── frontend/
│   └── package.json                # 前端版本号及版本管理脚本
└── backend/
    ├── pyproject.toml              # 后端版本号
    └── scripts/
        └── bump_version.py         # 后端版本更新脚本
```

### 版本管理脚本

#### 前端（package.json）

```json
{
  "scripts": {
    "version:patch": "pnpm version patch",
    "version:minor": "pnpm version minor",
    "version:major": "pnpm version major"
  }
}
```

#### 后端（bump_version.py）

- 读取 `pyproject.toml` 中的版本号
- 根据参数（major/minor/patch）计算新版本号
- 更新 `pyproject.toml` 文件
- 可选：创建 git commit 和 tag

使用方式：
```bash
# 使用 Pixi 后端环境

# 更新补丁版本
pixi run python scripts/bump_version.py patch

# 更新次版本并创建 git 标签
pixi run python scripts/bump_version.py minor --tag

# 预览变更（不实际修改）
pixi run python scripts/bump_version.py patch --dry-run
```

### Makefile 命令

Makefile 提供了统一的版本管理接口，同时更新前端和后端版本：

- `make version-patch` - 同时更新前后端补丁版本
- `make version-minor` - 同时更新前后端次版本
- `make version-major` - 同时更新前后端主版本
- `make changelog` - 显示最近提交历史
- `make tag` - 创建 git 标签

### CHANGELOG.md 格式

采用 [Keep a Changelog](https://keepachangelog.com) 格式：

```markdown
## [Unreleased]

### Added
- 新增功能

### Changed
- 变更功能

### Fixed
- 修复问题

### Removed
- 移除功能

## [0.1.0] - YYYY-MM-DD

### Added
- 初始版本功能
```

### 发布流程

1. 更新 `CHANGELOG.md`，将 `[Unreleased]` 部分移至新版本
2. 运行 `make version-patch/minor/major` 更新版本号
3. 运行 `make tag` 创建 git 标签
4. 推送代码和标签：`git push && git push --tags`

### 当前版本

- 前端版本：`0.1.0`（frontend/package.json）
- 后端版本：`0.1.0`（backend/pyproject.toml）
- 最新标签：`v0.1.0`

---

## 数据表功能

### 选中机制

数据表使用 Ant Design Table 的 `rowSelection` 属性实现 checkbox 选择：

- 每行左侧有 checkbox
- 表头 checkbox 旁有下拉菜单，支持全选、反选、清空操作
- 选中后地图上对应的要素会高亮显示（通过 Mapbox GL 的 feature-state）
- 右侧面板显示第一个选中要素的属性信息

### 表头分组

使用 Ant Design Table 的表头分组功能展示字段说明：

- 第一行：显示字段名称
- 第二行：显示字段描述（从 GeoPackage `gpkg_data_columns` 表读取）
- 排序和筛选按钮只在第二行（描述行）显示
- 无描述的字段只显示一行

### 样式规范

- 所有数据单元格和表头单元格左对齐
- 内边距统一为 8px
- checkbox 列使用 Ant Design 默认样式，不使用 `ResizableHeaderCell`

---

## 字段元数据

### 存储方式

字段元数据存储在 GeoPackage 文件的 `gpkg_data_columns` 表中：

```sql
CREATE TABLE gpkg_data_columns (
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    name TEXT,
    title TEXT,
    description TEXT,
    mime_type TEXT,
    constraint_name TEXT,
    CONSTRAINT pk_gpkg_data_columns PRIMARY KEY (table_name, column_name)
)
```

### 读取方式

后端 `read_field_metadata(path, table_name)` 函数从 GeoPackage 读取字段元数据，返回 `{column_name: description}` 字典。

`gpkg_data_columns` 表不存在时按无字段说明处理并返回空字典；如果表存在但结构异常、数据库文件异常或查询失败，后端不再吞掉异常，应转为明确的数据查询错误或在扫描入口记录异常。

### API 响应

`resource_profile` 和 `resource_query` 端点的 `fields` 数组包含 `description` 字段：

```json
{
  "fields": [
    {
      "name": "species",
      "type": "object",
      "nullable": false,
      "sampleValues": ["Populus euphratica"],
      "description": "树种名称"
    }
  ]
}
```

---

## 地图视角缩略图

- 右侧“当前视角平面缩略图”不使用静态 SVG 占位。`MapCanvas` 从 Mapbox 当前中心点、整张地图容器范围、缩放、旋转和俯仰读取 `MapViewState`，传给右侧栏渲染；不再按悬浮面板计算无遮挡可视范围。
- 平面缩略图使用独立的不可交互 Mapbox GL 2D 地图承载 OSM 数据的矢量底图，不再手动计算和拼接瓦片；缩略图固定使用 OSM，不跟随系统 Mapbox 卫星底图切换。
- 缩略图 OSM 矢量底图按平台统一的 `zh-Hans` 语言模式加载；Mapbox GL 初始化和样式加载后都应用同一个中文底图语言函数，优先使用数据源内已有中文名称字段，缺失时显示数据源本地名称。
- 缩略图地图使用 Web Mercator 投影，中心与主 3D 地球当前中心同步，缩放使用主图缩放小 3 级；初始中心和缩放必须来自主图 `MapViewState`，不使用硬编码默认视角。
- 缩略图不再显示中心点、中心经纬度或缩放等级。当前主地图视口范围通过缩略图内的红色 GeoJSON 线框表示；缩略图不承载栅格符号化，栅格渲染仍由后端瓦片/PNG 服务负责。

## 右侧栅格数据洞察

- 右侧地理数据洞察按数据形态分流：矢量继续使用“概览、要素、监测”，栅格使用“概览、波段、质量”，选择栅格图层时不自动进入单要素属性视图。
- 栅格概览只解释后端 profile 和可视化摘要中的元数据，按“数据集状态与规模、波段统一值域、当前后端渲染方案、空间范围与数据体量”组织；只有最小值和最大值时不得伪装成像元直方图或真实分布。
- 栅格波段页展示波段编号、描述、数据类型、颜色解释和值域，质量页展示元数据、COG 预处理和 XYZ 瓦片三段可用性。前端可以预览已有色带和规则，但不得读取原始栅格或执行符号化计算。

## 工作台检索与地图工具

- 地图工具栏的“复位”按钮统一定义为定位到项目范围，使用项目范围边界 `[50, 35]` 至 `[100, 48]` 执行 `fitBounds`；原独立“定位到项目范围”按钮移除。
- 鼠标经纬度状态显示并入地图工具栏左侧，不再作为单独悬浮状态块。
- 顶部全局搜索不再提供独立搜索按钮。输入框聚焦后立即展开搜索面板，按“数据、工程/专题”展示当前可用内容，分类标签放在面板底部；数据条目提供快速加载入口。
- 登录前界面和后台 Dashboard 卡片使用 Ant Design `BorderBeam` 组件，颜色采用 Ocean 渐变停靠点 `#1677ff 0%`、`#36cfc9 52%`、`#95de64 100%`。

## 代码结构与内置配置

- 项目结构维护说明见 `docs/project-structure.md`；移动前端或后端模块时必须同步更新该文档。
- Django 运行元数据库使用业务数据根目录下的 `database/meta.db`，路径为 `settings.PROJECT_CONFIG.app_path("database", "meta.db")`。研究数据根只保存矢量、栅格、基因和表格等研究数据文件，不再混放 Django auth、权限、审计、目录登记、工程和专题等应用元信息。
- TOML 配置加载对布尔值和地图浮点数执行显式类型校验：布尔字段不再用 `bool(value)` 宽松转换，`default_center` 和 `default_zoom` 必须是有限数字。后台系统设置接口对同类输入返回 JSON 400，避免非法请求触发 500 或写入不可用运行配置。
- 后端内置账号和内置用户组配置集中在 `backend/apps/core/configuration/builtins.py`，包括 `超级管理员`、`普通用户`、`游客`、`guest`、初始管理员环境变量名、初始密码文件名和默认权限集合。
- 业务逻辑不得直接散落维护内置账号/用户组字符串；需要判断内置组或内置账号时，通过 `apps.core.initialization` 暴露的 helper 和常量引用配置。
- `超级管理员`、`普通用户`、`游客` 都属于系统内置受保护用户组，不能删除或重命名。`超级管理员` 权限由系统强制补齐；`普通用户` 和 `游客` 的默认权限只在用户组首次创建时应用，后续后台调整应被保留。
- 非超级管理员主体不可见的用户、角色、操作日志和访问角色过滤统一通过 `backend/apps/core/principal_visibility.py` 暴露的 helper 实现；视图和前端不得绕过该模块自行暴露或二次判断超级管理员主体。
- 数据资源导入和存量数据访问范围配置只展示可手动选择的额外角色，统一通过 `selectable_access_groups_for` 排除 `超级管理员`；后端仍在写入时强制补齐超级管理员访问范围，认证授权页继续使用主体可见性 helper 管理角色本身。
- 前端认证授权页不得通过中文用户组名推断保护规则，应消费后端返回的 `isProtected` 与 `lockedPermissions`。

## 审计目标定位

- `OperationLog` 除自由文本 `message` 外，使用 `target_type`、`target_id`、`target_code`、`target_name` 记录结构化操作目标。数据资源写 `data_resource + DataResource.id/code/name`，工程/专题写 `workspace_scene + WorkspaceScene.id/kind/name`。
- 删除操作必须在删除数据库对象前缓存目标 ID、编码和名称，并写入结构化目标字段；不能只依赖名称文本追溯。
- 后台数据资源维护按操作类型授权：`update`、`setStatus`、`saveVisualization` 必须具备 `catalog.change_dataresource`；`updateAccess` 允许资源维护人或具备 `catalog.change_dataresource` 的用户执行；空更新不写成功日志。
# 2026-07-01 矢量唯一值符号化与种质默认模板

- 矢量 `symbolization` 继续存储在现有 JSONField 中，不新增数据库迁移；OpenAPI 已补充 `VectorSymbolization`、`UniqueValueRenderer` 和 `UniqueValueSymbolClass` 以约束新结构，同时通过 `additionalProperties` 兼容历史松散样式。
- 业务默认模板先以前端模板注册表实现。首个模板为 `germplasm.dna-sex-tree.v1`：命中 `domainType=germplasm` 或字段组合 `DNA样本编号 + 性别` 时，默认使用 `gm-tree` 图标按 `性别` 分类，`雌株` 与 `雌株珠` 归并为“雌性”，`雄株` 为“雄性”，其他值走默认类。
- Mapbox 图标仍使用平台内置 `gm-*` 英文 ID。分类颜色通过运行时生成的 canvas 图片体现，图标图片 ID 形如 `gm-tree--d65a8a`，渲染前调用 `map.addImage()` 注册，并保留 `styleimagemissing` 兜底，避免未注册图标导致点位消失。

# 2026-07-03 矢量数值分级符号化

- 矢量 `symbolization.renderer` 增加 `graduated` 类型，继续复用现有 `MapLayer.symbolization` JSONField、图层序列化和默认可视化保存链路，不新增数据库迁移或分类接口。
- 前端符号化面板支持按海拔、NDVI、盐分等连续字段生成等距分级或分位数分级；字段类型不是数值但当前属性值可解析为数字时也允许分级，无法解析的值进入默认“无数值/空值”类。

# 2026-07-13 矢量源文件导入与矢量业务类型

- `DataDomainType` 在原九类基础上新增 `vector/矢量数据`，用于直接以点、线、面图层为主体管理的资源；`DataResource.data_type=vector` 继续表示技术资源类型，两者职责保持分离。
- 原始 Shapefile 以 ZIP 上传，后端验证 `.shp/.shx/.dbf` 组件完整性，忽略 ArcGIS 锁文件，并支持 `.cpg` 或人工 DBF 编码覆盖。
- 矢量预检、校验、提交使用独立 `/api/catalog/vector-import/*` 契约，不修改现有 Excel/CSV 导入行为。
- 导入成功后保留原始单文件归档，地图用数据统一转换为 EPSG:4326 写入 `vector/vector.gpkg`，并创建 `DataResource`、`VectorDataset`、`MapLayer`、`ResourceDomain` 和 `SourceDataset`。
- `VectorDataset` 保存源格式、源图层、编码、源 CRS、几何类型、要素/顶点/字段数量、几何质量、边界、SHA256 和渲染策略；当前渲染策略保持 GeoJSON，后续可在不改变资源模型的情况下扩展矢量瓦片。
- 所有 GeoPackage 写入在当前进程内串行执行；数据库登记失败时清理本次新写入图层和原始归档，不覆盖已有资源。
- Mapbox 渲染使用 `case + to-number` 表达式驱动点、线、面颜色、大小和可见性；点图标仍使用 `gm-*--color` 运行时图片 ID 并在渲染前注册，避免平台内置图标加载失败。
- 自定义分级复用同一个 `GraduatedRenderer`，以 `method=manual` 标记。用户调整等级数量时只增删 `classes`，已有区间、颜色、图标、大小和显隐保持不变；调整任一区间上下限后，前端即时刷新该区间计数和 Mapbox 表达式。

# 2026-07-13 栅格数据包导入与稳定渲染

- 栅格上传由单文件扩展为数据包：GeoTIFF/COG 和 IMG 可单文件上传；ENVI DAT/BSQ/BIL/BIP 必须包含同名 HDR；VRT 只允许引用上传包内同目录相对文件，禁止绝对路径、上级路径和网络 URL。
- 前端不再使用 `geotiff.js` 读取所有栅格或把整个文件载入浏览器内存；权威预检统一由 `/api/raster/import/preview/` 调用 GDAL 完成。
- 新上传包保存到 `raster/original/uploaded/{uuid}/`，保留原始文件名并生成 `manifest.json` 和主文件 SHA256；`RasterDataset.source_manifest` 保存可查询清单，展示 COG 继续写入 `raster/preprocessed/`。
- `RasterProcessingJob` 持久化任务状态、阶段、稀疏进度检查点和结果；内存状态仍作为高频热缓存，数据库短暂繁忙不会中断 GDAL 子进程。后续切换 Celery/Redis 时保持同一任务接口。
- `RasterStyle` 持久化 `(dataset, styleHash, rules)`，服务重启后旧瓦片 URL 可从数据库恢复样式；瓦片结果增加有界内存 LRU、ETag 和私有 HTTP 缓存。
- 栅格最终发布使用短事务同步 `DataResource`、`MapLayer`、`RasterDataset`、访问组和 `RasterBand`，重投影过程不持有数据库事务。分类栅格默认最近邻，连续栅格和多波段影像默认双线性，也允许人工选择 cubic。

# 2026-08-01 LUCC 分类栅格无插值展示

- 单波段整型栅格若包含 `CLASS_CODES`、类别名称、颜色表或 thematic RAT，预检和兼容导入路径都将其识别为分类栅格；`CLASS_CODES` 中的类别值与名称直接生成默认唯一值图例，并按林地、水体、耕地、建筑、道路等语义选择稳定颜色。默认图例同时出现至少三个典型 LUCC 类别标签时，导入页自动把权威业务分类切换为“基础地理信息数据 / LUCC”。
- 分类栅格在后端强制使用最近邻完成重投影和 COG 金字塔生成，前端导入页不可改为双线性或三次卷积。XYZ 瓦片读取继续使用最近邻；Mapbox 图层同时使用 `raster-resampling=nearest` 和零缩放级别淡入时长，避免平移缩放期间混合相邻类别颜色。
- 唯一值颜色编辑按稳定数组索引实时更新草稿，并保存 8 位十六进制透明度；点击“确定”后沿用现有异步符号化流程生成新的瓦片样式。
- 分类资源的目录图层及唯一值规则在未显式指定透明度时默认使用 100% 不透明度，防止底图纹理透出并被误判为 LUCC 分类边缘；人工设置的透明度继续原样保留。

# 2026-07-23 存量数据权威分类分组

- 存量数据页的系统分组固定为“全部数据”、四个权威一级大类、十五个可挂接业务小类和“未分组（其他）”。一级大类汇总全部后代小类，业务小类按 `DataResource.category` 实际挂接关系归组。
- `/api/admin/data/resources/` 的 `groupSummaries` 按完整筛选和权限范围聚合权威分类统计，稳定键使用 `__category__:{categoryCode}`；未挂接有效权威分类的历史资源统一归入 `__unclassified__`，不再使用兼容 `domainType` 生成系统分组。
- `DataResourceGroup`、`inventoryGroups` 和 `inventoryGroupId` 只表示用户新建的自定义分组。资源可同时出现在“全部数据”、所属一级大类、一个业务小类和至多一个自定义分组中；删除自定义分组只清空归档关系，不影响资源及其权威业务分类。

# 2026-07-15 存量数据全量统计与分页分组

- `/api/admin/data/resources/` 的 `items` 继续分页，避免一次性序列化全部资源；新增 `summary` 和 `groupSummaries` 在当前筛选、权限范围内执行数据库聚合，统计结果不受页码和每页条数影响。
- 存量数据顶部统计卡片只使用 `summary`，分组总数据规模只使用 `groupSummaries`。当前页明细数量仅在展开区域单独提示，禁止再把全量 `total` 与当前页启停数量并列为同一统计口径。
- 默认每页展示 50 项并将分页器放到分组表格上方；数据超过一页时，展开区域明确显示“当前页 / 该组总数”，避免用户将分页明细误认为数据缺失。

# 2026-07-14 专题制图第一阶段

- 正式制图使用 `WorkspaceScene(project) -> MapComposition -> MapCompositionVersion` 三层结构。工程保存可恢复工作状态，出图稿保存轻量版式，版本保存不可变成果和版式快照；旧 `WorkspaceScene(topic)` 继续在专题 Tab 的兼容区加载，不再作为正式出图成果。
- 前端出图工作台支持 A4/A3 横竖版、主地图框、标题/副标题、图例、指北针、比例尺、区位副图、经纬网、Web Mercator 投影格网、数据来源、制图说明、预览检查和 PNG/JPG/PDF 生成。图例从当前可见图层及唯一值/分级符号化自动派生。
- 前端使用 Mapbox 离屏地图复用当前样式和已授权图层生成 PNG 母图；范围绘制等临时覆盖层不进入成果。栅格仍使用后端 XYZ 瓦片，不读取原始栅格文件或在浏览器重新符号化。
- 离屏出图底图统一替换为平台同源 `/api/map/thumbnail-tiles/{z}/{x}/{y}.png` 瓦片，通过后端代理、磁盘缓存和本地世界地图兜底避免客户端直接依赖 Mapbox/OSM。只有样式、业务图层和全部瓦片均完成加载后才允许截图；超时或瓦片错误会自动重试并向用户返回明确错误。自动预览使用 `AbortController` 取消旧任务，避免连续调整版式时产生并发离屏地图和重复瓦片请求。
- 经纬网和投影格网会按主图范围推荐间隔，小范围工程允许使用 0.0001 度或 10 米起的间隔；切换格网类型时重新给出适合当前范围的推荐值。
- 编辑器只在首次打开某个出图稿时装载持久化版式，地图视角或来源摘要在后台变化时不会覆盖尚未保存的版式调整。
- 后端只接收经过前端版式合成的 PNG 母图，验证 PNG、DPI、宽高、8192 单边和 3600 万总像素限制后，使用 Pillow 写入 PNG/JPG/PDF。成果路径固定在 TOML 驱动的 `app_data/exports/map-compositions/{compositionId}/v{version}/`。
- 出图稿独立使用 Django 权限 `catalog.add/view/change/delete_mapcomposition`、`catalog.export_mapcomposition` 和 `catalog.publish_mapcomposition`。删除操作永久移除专题、版本记录及其明确记录的成果文件，逐文件处理且不递归删除目录，并通过操作日志保留审计证据。
## 工程专题可见性与加载规则（2026-07-14）

- `WorkspaceScene` 不再作为仅所属用户可见的私有快照：启用对象按“所属用户本人 + access_groups + 超级管理员全量绕过”返回，禁用对象只在后台管理中保留。
- 所属用户本人和内置 `超级管理员` 角色是不可取消的固定可见范围；新建、普通工作台更新和后台更新都会由后端补齐超级管理员角色，数据迁移为历史工程专题补齐该关系。
- 地图工作台可发现并加载其他用户共享的工程专题，但普通接口仍只允许所属用户修改或删除；超级管理员维护他人对象使用后台管理接口。
- 普通保存/编辑表单只展示可选择的额外角色，不返回也不允许手动选择超级管理员角色，避免把平台不变量误解为可取消选项。
# Test data isolation

- Backend pytest runs use `geomanager.test_settings`, which replaces the configured application and research data roots with a process-specific directory under the system temporary directory. Integration tests that create or remove `vector.gpkg`, SQLite tables, uploads, or archives must never operate on the development or deployment data roots from the runtime TOML file.

# 2026-07-22 平台品牌与智能预警占位

- 平台规范中文名称统一为“全球胡杨林生态系统保护数据共享平台”，英文名称统一为 “Global Populus euphratica Forest Ecosystem Conservation Data Sharing Platform”，英文缩写统一为 `GPEDSP`（Global Populus euphratica Data Sharing Platform）；前端展示、后端登录概览、运行配置、OpenAPI 示例、Mock 和帮助入口需保持一致。前端可见品牌字段集中维护在 `frontend/src/config/platformBrand.ts`，后端规范字段集中维护在 `backend/apps/core/platform_brand.py`；启动接口、系统设置、浏览器标签和备份清单均会把已知“中亚胡杨”历史名称升级为当前全球名称，但保留其他自定义部署名称。`pnpm run brand:check` 会阻止活动代码重新引入旧名称或绕过统一标题函数直接修改 `document.title`。
- 登录页使用 `frontend/src/assets/login-golden-poplar-bg.png` 作为金色胡杨封面；可见品牌图标继续统一复用透明底盾牌胡杨 Logo，并同步维护 SVG 的可访问标题。
- 顶部主导航预留“智能预警”按钮并进入 `/warning` 正式占位页；当前不新增实时监测 API、权限或后台业务实现，后续接入时再补齐契约与权限设计。

# 2026-07-22 九大页面、实景主视觉与成果中心

- 首页 `/data` 与数据资源 `/resources` 职责拆分，顶部导航补齐成果展示、智能预警和胡杨科普，并统一“地理工作台”命名。
- 从用户提供的胡杨背景图库中只复制三张原图到 `frontend/src/assets/portal/`，未移动或删除原目录文件。首页、胡杨科普、关于我们使用不同实景图与深色渐变遮罩。
- 数据导入页新增目标切换，原数据导入流程保持不变；成果流程支持草稿与直接发布、权威分类、提供单位和访问角色。
- 新增 `ResultArtifact`、数据库迁移和成果接口；成果页聚合已发布专题图与成果文件，按来源、格式和关键词筛选。

# 2026-07-23 成果权限解耦与统一管理

- `ResultArtifact` 独立使用 `view/add/download/publish/delete_resultartifact`，不再借用数据浏览、数据导出、数据新增或专题图发布权限。功能权限与 `access_groups` 对象范围同时生效。
- `POST /api/catalog/results/` 固定为导入并直接发布，至少选择一个访问角色；历史草稿和下架成果继续使用 `draft` 状态，并通过成果管理页发布或删除。
- `/resources/manage/topics` 保留稳定路径但页面语义升级为“成果管理”，用两个页签统一承载 `MapComposition` 与 `ResultArtifact`，保留专题图原有工程/版本操作并补齐成果文件发布范围、下架和删除。
- 删除导入成果只删除数据库记录和该对象明确记录的单个成果文件，不递归删除目录；操作写入 `OperationLog`。
- 关于我们新增塔里木大学、新疆生地所、中科院西北院、新疆林科院四个独立机构展示区和分机构成员名录；未核实成员明确显示待确认。

# 2026-07-23 胡杨科普与关于我们内容深化

- 胡杨科普一级页按“物种档案、保护管理、胡杨知识图谱”三段组织；物种档案包含物种名片、生态价值、文化象征、生存智慧和科研价值，知识图谱继续复用原有论文、机制与交互节点内容。
- 团队介绍与团队成员均采用四单位总览和单位二级路由，路径分别为 `/about/team/:institutionId` 与 `/about/members/:institutionId`；机构标识固定为 `tarim-university`、`xieg-cas`、`xjafs`、`nieer-cas`。
- 联系我们从团队内容中拆为 `/about/contact` 独立页面：数据使用、权限与资料提交联系 `lizhijun0202@126.com`，平台建设、功能问题与 Bug 修复联系 `wanghaoyu191@mails.ucas.ac.cn`。
- 帮助中心 PDF 当时使用旧版下载路径（已由 `/docs/platform-help-center.pdf` 替代），文档升级至 v2.0（2026-07-23），按九大一级页面、成果管理、专题制图、科普、四单位二级页和双邮箱支持流程重写。

# 2026-07-29 游客会话与公开对象继承

- 专用 `guest` 账号的不可用密码只在账号仍存在可用密码时重置；重复游客登录不得改变认证摘要，多个浏览器的游客会话必须可以并存。
- `游客` 访问角色是公开受众标记，不是与登录角色互斥的数据范围。资源、图层、工程、专题图和导入成果选择游客角色后，游客会话与所有已登录角色均可访问；登录不能导致公开数据不可见。

# 2026-07-29 测试报告缺陷修复

- 工程恢复必须同时检查矢量与栅格加载权限。资源 profile 返回 403 的栅格图层直接跳过并汇总提示申请权限，不再把旧瓦片 URL 交给 Mapbox 请求；其他临时校验异常才允许保留快照引用并提示风险。
- `canAccessAdmin` 只表示运维后台能力，不再对所有认证用户恒为 true。仅有数据业务权限的普通用户、科研用户和游客隐藏后台入口，直接访问运行概览时回到仍可用的个人设置页。
- GeoPackage 中内容全部可解析为数字的文本字段按数值字段建立查询语义，数值比较和区间过滤先统一转换，非法数值条件返回结构化查询错误。
- 登录页只消费 `/api/login/overview/` 的实时统计和服务状态；服务节点数等于实际返回的服务数，不再展示固定 24 节点或硬编码资源数量。

# 2026-07-30 新疆生地所团队资料更新

- 新疆生地所成员名录按项目方最新材料更新为张久丹、刘嘉伟、李若楠、汤珊珊、邓蕊、张甜、范景超、闫杨豪，成员卡片展示正式照片与研究方向；旧成员刘铁、包安明不再展示。
- 团队介绍补充胡杨林智能信息提取、湿地与冰川监测、土壤风蚀、盐碱灾害和塔里木河水资源生态响应等当前研究方向。本次变更仅涉及前端静态内容与展示样式，不涉及 API、权限、数据路径或栅格渲染。

# 2026-07-30 地理工作台网络与底图状态提示

- 地理工作台复用公开的 `/api/health/` 检查浏览器到平台的连接，同时监听 Mapbox 底图 source、idle 和 error 事件统计当前视野底图的可访问状态与最近响应耗时；不新增诊断接口，也不把业务图层瓦片错误计入底图状态。
- 诊断口径按链路分段：浏览器明确离线归为网络异常；健康接口无响应归为平台连接异常；平台可访问但底图资源失败归为底图服务异常；两段链路同时高延迟时优先提示网络较慢。该提示是浏览器端快速判断，不替代服务端监控或故障根因分析。

# 2026-08-01 地理工作台四底图选择与稳定切换

- 地理工作台正式底图固定为四项：Mapbox Satellite Streets 默认、Mapbox Streets、天地图球面墨卡托 `vec_w + cva_w` 矢量注记图、天地图球面墨卡托 `img_w + cia_w` 卫星影像图；OpenStreetMap 匿名瓦片继续作为 `selectable=false` 的内部技术兜底，不进入用户选择列表，也不承诺生产 SLA。后台概览、缩略图、专题制图和范围导出继续沿用各自既有的系统默认或平台缓存底图链路。
- 三项底图复用同一个 `mapboxgl.Map` 实例，通过 `setStyle(..., { diff: false })` 事务切换。新样式在 15 秒内完成当前底图 source 加载后才提交；失败时恢复原底图，原底图也失败时才尝试 OSM 技术兜底。三秒延迟只由状态组件提示，不自动替用户改变底图。
- 样式切换前保存 camera 和选中要素，切换后统一重新注册平台符号图片、业务矢量/栅格图层、显隐与符号化、图层顺序、空间筛选和图层范围框，并禁止新增图层恢复逻辑触发自动 `fitBounds`。绘制和地图导出期间禁用底图切换，避免中途销毁样式。
- 用户底图偏好按用户 ID 隔离保存在浏览器 `localStorage`，只有新底图事务成功才写入；失败恢复、内部兜底和重新检测均不得覆盖用户偏好。状态诊断以底图 ID、generation、source ID 和资源域名共同隔离，旧底图及业务图层错误不得污染当前底图状态。
- `application.map.tianditu_access_token` 保存天地图官方控制台签发的浏览器公开 Key，旧 TOML 缺键按空字符串兼容。该值会经公开 Bootstrap 下发，只允许配置带生产域名限制的浏览器 Key；不得填写服务端私密凭证。天地图 `vec_w`、`cva_w` 和 `cia_w` source 固定 `maxzoom=18`；`img_w` 在平台覆盖区从 z17 开始返回 HTTP 200 的“该区域无影像”占位图，因此固定 `maxzoom=16`，更高地图级别只 overscale 最后一级可靠影像。CSP 仅放行天地图 HTTPS 子域；Mapbox 与天地图署名由 Mapbox GL attribution 控件随当前 style 动态展示，平台不得隐藏 Mapbox Logo。
- 天地图 `vec_w + cva_w` 会在一次样式切换中并行加载两组 256 像素瓦片，且两组 source 必须同时存在并加载完成才可判定为就绪。页面级并发租约在任一活动主地图使用天地图时将 Mapbox GL 图片请求并发限制为 6，最后一个限制租约释放后恢复原值，避免多地图实例相互覆盖。HTTP 429 在切换事务内立即回滚；初始加载或后续平移期间遇到 429 时，只触发一次不写用户偏好的自动恢复，优先切换 Mapbox 卫星图、不可用时切换 OSM。重新选择天地图的冷却至少 30 秒；上游返回更长 `Retry-After` 时与共享调度器同步延长、最多 120 秒，避免用户重选后进入无反馈的长队列。日额度和多用户总请求仍须在天地图控制台监控。
- 天地图影像底图复用同一浏览器 Key、`t0-t7` 节点调度、请求超时、失败窗口和脱敏诊断，将 `img_w` 作为影像层、`cia_w` 作为中文影像注记层，二者缺一不得提交切换成功。天地图矢量与影像共享上游、凭证和额度，不互作自动故障兜底；任一天地图底图确认硬故障后仍按 Mapbox 卫星图、OSM 的独立故障域顺序恢复。影像是非实时服务；`img_w` 可靠级别固定到 z16，地图镜头可继续放大但只复用 z16 父瓦片，`cia_w` 中文注记仍可请求到 z18，从而避免外部服务的无影像占位图被误呈现为平台白屏。

# 2026-08-04 天地图瓦片分级恢复与失败窗口

- 天地图 Provider 只解析最多 4 KiB 的错误正文并仅保留安全业务码；`301007` 和强语义凭证提示按凭证错误立即失败，`301018`（Key 类型或接口权限不支持）跨另一节点确认一次后再判定凭证故障；确认成功则继续使用，确认失败则只触发一次自动回退与管理员导向结果提示。诊断对象与提示不得保存瓦片 URL、Key 或原始响应正文。无法确认原因的单次 HTTP 403 按瞬时错误处理，不再直接等同于整张底图故障。
- 未分类 403 和上游 404 最多跨一个备用节点确认；网络异常、408、425 和 5xx 最多使用两个备用节点重试。404 对 Mapbox 暴露为非 404 并另存脱敏的 `upstreamStatus`，不计入节点熔断和共享队列暂停，也不单独触发“连续 3 次失败”，但仍作为逻辑瓦片失败计入至少 8 个样本的失败率阈值，避免少量边界空瓦片切换整张底图。429 固定在原节点并作用于共享请求队列；10 秒以内的 `Retry-After` 可原地重试，更长值立即结束当前逻辑瓦片并触发回退，同时让共享队列按服务端要求冷却、最多 120 秒，不再让一个瓦片挂起数分钟。所有实际请求继续复用原有页面级并发与启动间隔限制，不另建绕过限速的请求通道。
- `t0`–`t7` 节点在 15 秒内连续两次瞬时失败后熔断 30 秒；重试不得重复选择同一逻辑瓦片已尝试的节点，全部节点熔断时在浏览器本地快速失败，避免继续冲击上游。Abort 不重试、不计失败。
- 每次天地图 `fetch + body` 读取使用 10 秒硬超时；内部超时按瞬时错误释放共享并发槽、切换健康节点并进入既有有限重试，Mapbox 主动取消仍立即结束且不计入失败。这样半开连接不能长期占满 6 个共享槽并阻塞后续视野请求。
- 失败统计以逻辑瓦片最终结果为单位，内部重试不重复计数。窗口保留最近 15 秒、最多 12 个样本；连续 3 个最终失败，或至少 8 个样本中至少 3 个失败且失败率达到 50%，才判定整套天地图异常。阈值以下仅显示局部波动及脱敏的业务码、图层、节点和失败比例；达到阈值后复用现有单实例冷却恢复，自动切换 Mapbox 卫星图，必要时再使用 OSM 技术兜底。
- 状态提示的普通底图软慢阈值为 3 秒；天地图因两组 source 共用 100 ms 启动节流，使用 12 秒软慢阈值。`load`/`idle` 只确认视野就绪，不再把整轮视野耗时写成“最近响应”；手动“重新检测”的整次样式重载耗时同样不得写入瓦片响应指标。天地图健康时的紧凑工具栏隐藏毫秒值，详情仅在有 source 瓦片样本时显示“近期瓦片就绪（含客户端排队）”。局部波动或错误状态也隐藏延迟，平台健康检查耗时仍独立展示。
- 自动恢复状态区分等待解锁、执行中和已结束；绘制或地图导出锁期间确认的天地图硬故障保留为待处理任务，锁解除后且底图 generation 仍匹配时只执行一次，代次已变化则丢弃。恢复冷却从真正开始执行时重新计算，最终成功或失败使用固定消息 key 只提示一次。旧天地图结构化错误或旧天地图 source 在切换到 Mapbox/OSM 后不得进入全局顶部消息。
- 天地图切换后的严格就绪等待时间为 120 秒，Mapbox 卫星实景图和 Mapbox 街道图为 60 秒；只有各自必需 source 在对应时间内仍未就绪，才按加载超时执行既有回退。OSM 技术兜底继续使用原有 15 秒等待时间。
- 该恢复链路只作用于天地图底图 source。Mapbox、OSM、业务图层、后端 API、权限、TOML Key 配置和栅格符号化链路保持不变。

# 2026-07-30 非地理真实数据分析合同

- 非地理工作台不再使用演示统计。`GET /api/catalog/resources/{id}/nongeo-analysis/` 从 SQLite 后台表或受支持的表格/基因文件读取真实记录，返回字段画像、分类与数值分布、相关矩阵、明细预览和分析口径；最多分析 10,000 条记录，但真实总数必须单独返回并通过 `sampled` 标识抽样。
- `POST /api/catalog/resources/{id}/nongeo-query/` 使用 `limit/offset` 分页并支持单字段升降序。`limit` 固定为 1–500，`offset` 固定为 0–10,000,000；排序字段必须存在于真实字段集合中，SQLite 标识符先经过字段白名单验证再安全引用，禁止把请求值直接拼接为 SQL。
- 两个接口统一要求登录、`core.query_data`、启用的 table/gene 资源和对象访问范围。直接文件分析支持 CSV/TSV/XLS/XLSX、FASTA/FASTQ、VCF、GFF/GFF3、GB/GBK，大小上限取运行时上传限制与 64 MB 的较小值。

# 2026-07-30 扫描入口权限边界

- `POST /api/catalog/scan/` 是维护性资源发现动作，要求 `catalog.add_dataresource`；同一时刻只允许一个目录扫描，已有扫描运行时返回 409。普通浏览用户和游客不得触发。
- `POST /api/raster/scan/` 复用栅格管理授权，允许 `raster.manage_raster_dataset` 或 `catalog.change_dataresource` 任一权限；同一进程存在排队或运行中的扫描时复用活动任务。两类扫描都属于系统/任务日志范围，不写用户操作日志。

# 2026-07-30 成果文件真实格式与响应安全

- `POST /api/catalog/results/` 是“查看成果、导入文件、立即发布”的原子动作，必须同时具备 `catalog.view_resultartifact`、`catalog.add_resultartifact` 和 `catalog.publish_resultartifact`。文件校验不信任客户端 Content-Type：PNG/JPG/JPEG 使用 Pillow 解码并核对扩展名，PDF 检查 `%PDF-` 与尾部 `%%EOF`，CSV 拒绝空文件和 NUL 且仅接受 UTF-8/UTF-8-SIG/GB18030，XLSX 校验工作簿关键 ZIP 条目并限制条目数与解压规模；落盘 MIME 由后端可信识别结果决定。
- `GET /api/catalog/results/{resultId}/file/` 的成功响应统一返回 `X-Content-Type-Options: nosniff`。只有 PNG/JPG/JPEG/PDF 允许 `variant=preview`，并额外返回 `X-Frame-Options: SAMEORIGIN`、`Content-Security-Policy: sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'` 与 `Referrer-Policy: no-referrer`，以允许成果页同源嵌入 PDF；`variant=artifact` 仍要求 `catalog.download_resultartifact` 并保留全局 `X-Frame-Options: DENY`。

# 2026-07-30 角色二次授权与受保护账号

- 角色增删改查以 `core.manage_auth` 为基础；创建角色并设置权限需要同时具备 `core.manage_feature_permissions`，更新请求只要包含 `permissions` 也必须执行该二次校验。五个内置角色不可删除或重命名；超级管理员角色对非超级管理员隐藏且权限锁定，其他内置角色可由具备双权限的管理员调整权限。
- `游客` 角色只允许系统 guest 账号持有，不能创建或分配给其他账号；guest 账号不可删除、停用、重置密码、改角色或配置直授权限。平台管理员角色只能由超级管理员分配；平台管理员账号是受保护管理目标，非超级管理员不能修改其状态、密码、角色、权限或删除账号。

# 2026-08-01 符号化方案 JSON 导入与复用

- 地理工作台的矢量和栅格符号化编辑器统一提供“复制 JSON”和“导入 JSON”。导入弹窗只接受复制功能生成的完整方案对象，先在浏览器校验 JSON 结构、方案类型和数值类型，再更新编辑器草稿；用户仍须点击主窗口“确定”才正式应用，避免一次粘贴直接触发栅格渲染任务。
- 矢量方案导入会检查唯一值、数值分级、热力权重和标注引用的属性字段是否存在于目标图层；栅格方案导入会检查输出波段、Alpha 波段和唯一值整型波段是否与目标数据兼容。校验失败时保留粘贴内容并展示可修正的具体原因。
- 该能力复用现有图层状态与栅格异步渲染链路，不新增 API、权限或持久化结构。栅格颜色计算和瓦片输出继续全部由后端完成，前端只导入并校验规则 JSON。

# 2026-08-01 首次导航点击响应

- 登录后不再自动打开带全屏遮罩的工作台引导，避免首次点击顶部“地理工作台”等主导航时被遮罩拦截。完整引导继续保留在“用户信息 > 显示引导”，由用户主动打开。

# 2026-08-01 LUCC 原子静态金字塔与 Mapbox 基础纹理最近邻

- 分类 COG 预处理版本升级为 v2。重投影和 COG 内部概览全部固定最近邻，并显式统一源/目标 NoData；分类瓦片不再允许动态回退。启动扫描会自动重建缺少当前标记的存量分类 COG，同时保留资源名称、上传人、访问组、权威业务分类和当前符号化规则。
- 每个分类样式在业务数据根目录 `cache/raster-tiles/v4/{datasetId}/{styleHash}.mbtiles` 生成完整 z0–原生分辨率金字塔。最大级别从 COG 最近邻渲染，低级别按四子瓦片最近邻逐级构建；临时 MBTiles 只有在瓦片总数和完成标记校验通过后才使用 `os.replace()` 原子发布。导入默认样式和自定义颜色渲染任务都必须等金字塔完成后才进入 `ready`。
- `RasterRenderResult` 返回 `minZoom`、`maxZoom` 和 `tileSampling`。前端首帧创建 raster source/layer 时写入原生缩放范围、分类最近邻、零淡入和 100% 默认不透明度；超过原生 `maxZoom` 只 overscale 最后一级，不再按 Mapbox 默认值请求到 z22。
- Mapbox GL JS 3.25.0 的 raster texture 默认带 mipmap；即使过滤器为 `NEAREST_MIPMAP_NEAREST`，mipmap 本身仍由相邻类别平均生成。项目通过 pnpm patched dependency 让 nearest raster 的当前瓦片、父瓦片、无父回退和极区路径跳过 mipmap、把各向异性过滤重置为 1，并修复纹理实际 MIN/MAG filter 缓存；continuous raster、DEM、图标及其他 linear 纹理路径保持原行为。
- 真实 `hjyt_tile_r1_c1` 验证生成 z0–16 共 2,575 张瓦片，耗时 10.0 秒、文件约 10.9 MiB；逐级扫描无部分透明像素，非透明颜色严格限定为六类正式调色板，NoData 为全透明。源数据中真实的窄道路、水体和建筑在粗尺度最近邻下仍可能表现为单像元线；若未来要隐藏这些真实小目标，需另立低缩放级 majority/mode 制图综合需求，不能将其当作插值包边修复。

# 2026-08-09 天地图认证可见署名

- 地理工作台在活动底图提供者为天地图时，于可见地图区域固定展示未经改色、裁切或变形的官方“天地图 MAP WORLD”字样标识，并链接至天地图官网；切换到 Mapbox 或 OSM 时隐藏，避免错误归属。
- 官方图形角标不替代 Mapbox GL 随当前样式生成的文本署名和 Mapbox Logo。角标避开左右面板、底部面板、地图工具栏与原有 attribution 控件，并在窄屏维持可辨识尺寸和高对比底板。
- 该整改仅涉及前端展示、静态素材和针对性浏览器测试，不新增 API，不改变权限、TOML Key、数据路径、底图请求、限流恢复或栅格渲染链路。
# 2026-08-19 中英文平台语言切换

- 平台语言支持 `zh-CN` 与 `en-US`，默认中文；用户选择保存在浏览器 `geomanager.locale`，登录前后均可切换且不影响其他用户。第一版不增加账号语言字段或数据库迁移。
- 前端统一使用 `i18next` / `react-i18next`，Ant Design、Day.js、`html lang`、浏览器标题、登录页、公共导航、数据目录、数据加载面板、预警页、资源中心与管理布局随语言切换。`pnpm run i18n:check` 校验中英文词典键和静态引用。
- API 客户端统一发送 `Accept-Language`；Django 启用 `LocaleMiddleware`，公开登录概览、认证入口、统一登录/权限错误按请求语言返回。响应结构未改变，因此不修改 OpenAPI；旧接口仍保留 `detail` 字段和前端兼容翻译。
- Mapbox 可切换 `zh-Hans` / `en` 名称字段；天地图注记为中文栅格瓦片，英文模式不能改写其地名内容。用户上传的资源名、文件名、人员机构名和自由文本保持原始数据，不做运行时机器翻译。


# 2026-09-18 项目标签、知识科普、新闻与在线布局升级

- 用户最终要求：课程只供图片、文字和案例素材。平台按六个知识方向提供文章与外链，当前首批 12 篇与 24 个学习入口。新闻新增独立列表、详情和维护能力，示例来自 2026-09-11 会议资料。
- 一人多标签，管理员分配，超管维护标签并具有全部项目权限。内置默认 ID=1 匿名可读开放数据及已发布内容；写入/下载仍验功能权限，草稿和下架媒体不公开。业务 projectTagId 与地图工程 projectId 分离。
- 业务模型增加 project_tag；上下文由请求头/查询参数决定，支持只读 all。Manager、关联/快照校验、后台任务和文件服务端实现隔离。扫描合并限同一项目；启动扫描显式默认上下文；重启遗留任务恢复是全平台内部维护。
- 默认研究目录保留，私有研究文件按项目，内容附件按项目/文章；部分缓存/导出保留全局唯一 ID 目录。根路径全部来自 TOML。业务库仍 SQLite，空间数据仍 GeoPackage。
- 首页不再进入路由；地理工作台第一、数据资源第二。项目切换取消请求、清图层并提醒先保存。
- 布局沿用 version=1，通过 editor/extraTexts 扩展，支持拖拽缩放、锁定、层级、吸附、多选对齐/分布、地图内容平移、额外文字、50 步撤销与自动保存；保存用 expectedUpdatedAt 防覆盖。栅格计算仍在服务端，输出标准沿用原规范。
- 本任务按契约 → 后端 → 前端 → 测试顺序承担全部实施角色，API 文档与生成类型同步。执行范围和实际限制见 platform-upgrade-development-plan-v2.md；验收操作与回归证据见 platform-upgrade-acceptance.md。

# 2026-09-18 需求复核：数据分类与项目访问

- 科普是平台公共内容，其列表、详情、维护及附件请求固定默认标签；新闻保留项目隔离。禁止在私有标签创建科普。
- 最新要求将标签维护和成员分配收紧为超管专属；新用户只有默认标签。ProjectScopedModel 和成员范围覆盖列表、对象及文件路径；业务角色控制动作，历史角色共享字段不再授予或限制阅读。草稿/停用状态与所有者写入约束保留。
- 数据分类为 spatial/non_spatial，两个可选择根节点；资源导入/扫描保存时按空间类型及已解析坐标系统自动归类。0017 迁移保留文件路径和对象标签、停用旧字典。坐标表转换为矢量；普通表格入口进入现有真实数据分析。
- 退出清理请求与身份并 replace 到 /login；认证状态代次阻止旧请求回写。底图偏好 v2 使升级后默认使用 Mapbox，随后允许用户自行选择。
- 修复目录概览按同一分类统计时被原 queryset 排序拆组的问题。标签管理选择用户时用请求序号防止分配表单被前一个用户的响应覆盖。
- 本任务依次承担契约、后端、前端和测试角色；验收、数据保留、文件位置及执行限制见 2026-09-18-review-fixes-acceptance.md。


## 2026-09-18 上传显式指定所属项目标签

- 表格提交、矢量提交、栅格提交及成果导入的 POST 必须带 `X-Project-Id`，不再允许静默缺省；缺失、空值或 all 返回 400。未登录仍返回 401，未授权或不存在的目标返回 404。
- 上传页面独立提供必填“所属项目标签”，初始为默认（ID=1），用户在选择文件前确定标签。表单选择优先于顶部浏览项目；预检、校验、重名检查、提交和后台任务轮询保持同一项目。
- 标签选项来自 GET /api/projects/ 的 items；超管能选所有标签，普通用户只能选默认及本人被授权的有效标签。服务端每次重新验证权限，撤权立即生效。
- 每份数据仍属于一个项目；“默认”是最低初始归属，不给私有数据额外添加公共标签。数据、关联图层和导入文件均按所选项目落库/落盘。
- 存量数据增加独立项目列、详情归属和项目筛选；既有数据/工程/文件的归属保留。用户项目分配在项目管理完成，资料夹不授予项目访问权限。
- 受影响接口：POST /api/catalog/import/commit/、/api/catalog/vector-import/commit/、/api/raster/import/、/api/catalog/results/。Mock 示例：mock/prism/examples/90-platform-upgrade.json。前端生成类型位于 frontend/src/api/generated/。
- 验收：默认账号、多个标签成员与超管的选项；顶部项目不同于上传目标；跨项目列表/文件拒绝；上传期间撤权；缺失标签拒绝；异步栅格任务保持归属。


## 2026-09-18 单项目工作范围与公共团队动态

- 项目管理移动至 /admin/projects，后台侧栏由超管权限控制，原 /projects/manage 链接跳转至新位置。移除页面顶部与内容页的独立项目管理按钮。
- 顶部项目选择和存量项目筛选取消 all。业务请求读写均必须只处于单个项目，all 返回 400；认证、项目管理及内容属于平台功能，不进行多项目业务汇总。旧会话 all 自动归一为公开项目 1。
- 内置项目展示名由“默认”改为“公开”。保留 ID=1、code=default、isDefault、已有对象外键和目录结构。新用户自动可访问公开项目，超管仍能分别访问每个项目。
- 科普与团队动态及附件固定归属公开项目 1，不受顶部项目或成员关系影响。已发布内容所有人（包括未登录访问者）可读；草稿/下架内容和写入仍受内容管理权限限制。
- 迁移将历史内容及附件归属统一为公开，保留文章 ID、正文、发布状态和附件物理路径，不移动文件。冲突 seed_key 生成包含文章 ID 的唯一迁移标记，避免丢失文章。数据库约束阻止新建私有内容。
- 原上传表单仍显式指定一个目标标签，可选公开和当前用户获授权项目；不会批量在多个项目操作。栅格符号化和数据目录不变。

- 本轮迁移与验收已完成：完整后端 654 项及 52 子测试、前端 399 单元及 83 浏览器测试通过，超管/刘洋/匿名真实页面通过。项目管理同时纳入后台侧栏与后台下拉菜单。验收及迁移回退边界详见 `2026-09-18-public-project-navigation-acceptance.md`。

## 2026-09-18 制图底图加载失败

- 制图原来复用普通缩略图接口，网络故障时收到状态 200 的简化世界地图并缓存，造成主图与已有缓存的鹰眼不一致。新增 purpose=export 严格模式；只允许真实底图/缓存，失败返回 503/no-store，前端完整检查后自动重试一次。普通缩略图原行为保留。
- 本地后端曾在网络受限环境启动，Mapbox 请求 WinError 10013；已用正常网络环境重启，现有代理/凭证无需修改。后续启动用户服务必须保留上游联网能力。
- 实际工程主图/鹰眼、A4 300 DPI 输出和 503 故障注入均通过，原草稿不变。验收、命令及剩余外网依赖见 `2026-09-18-composition-basemap-fix.md`。无数据库迁移、权限/数据目录变更及业务栅格计算改动。

## 2026-09-18 标签页标题、空间查询和工程提示修复；平台审核

- ProLayout 的 `pageTitleRender=false` 仍会用 `title` 覆盖 document.title。AdminLayout 和 ResourceLayout 使用 `title=false`，保留 App 的统一中英文品牌标题。
- 空间查询候选仅来自已加载矢量图层：有效来源 ID、可查询；按来源去重，隐藏但未移除的图层仍可查询。移除最后一个来源图层后清空目标与结果，通过请求代次使迟到的元信息/查询响应失效。保留既有“按来源重新查询”的规则，本轮没有改变原属性筛选继承语义。
- ProjectNotice 明确浅底深字；工程访问说明继承弹窗文本颜色，避免在深色工作台弹窗中使用固定深色说明文字。真实截图和浏览器回归均验证。
- 仅改前端，无 API 契约、权限、数据库、数据目录或栅格计算变更。后端 659 项和 52 子测试、前端 399 单元/172 浏览器测试通过，最后提示样式调整另复核 3 项；build:verify、后端 lint、迁移检查通过。全库格式检查仍有 171 个历史问题，未批量处理。
- 已输出 `2026-09-18-ui-fixes-and-platform-audit.md`：14 项待审发现及 5 项产品/上线确认事项。优先问题包括备份漏项目目录/内容附件、比例尺距离失真、旧发布角色提示与项目授权规则冲突。发现只记录供审核，没有自动扩展实施。

## 2026-09-18 审核整改执行

本轮单执行者按契约 → 生成类型 → 后端 → 前端 → 验收顺序跨栈交接。A01–A14 已获用户授权；R01–R05 按 current-platform-rules.md 暂缓/保持现状。先验证完整备份，再进行附件暂存字段迁移。历史阶段中的 all 项目视图、角色共享、新闻项目隔离均已由 current-platform-rules.md 替代，不可按旧记录重建。

## 2026-09-19 通用计算中心实施与本机部署

- 单执行者按 OpenAPI 契约 → 生成类型 → 后端 → 前端 → 测试顺序跨栈实施。新应用 `apps/compute` 管理算法、不可变版本、持久任务、尝试、输出和幂等入库记录；API 及权限说明同步到 developer-guide。没有增加算法专用接口。
- 管理员上传 `operator.yaml` 与实现文件组成的 ZIP；清单生成输入/参数表单，草稿通过隔离试运行才允许发布。公开算法可在私有项目使用；数据、任务和结果仍固定当前项目。任务查看默认限本人，后台管理须显式权限。
- worker 独立于 Django Web 进程，使用 SQLite 持久队列、租约心跳、执行尝试标识、重启恢复、取消与幂等请求。与栅格重任务共享跨进程锁。执行器支持 Linux Docker 容器和 AutoDL 本机 Python 子进程两种模式；本机模式通过独立 runner、超时、CPU/内存软限制、状态文件和结果校验保持同一任务协议。
- 执行器只给算法所选数据快照、代码及受信任 runner，不挂载整库、凭据或 Docker socket。Docker 模式固定镜像摘要并禁网、非 root、只读且受资源限制；native 模式固定 Python 解释器和地理依赖摘要，使用独立进程、超时、CPU/内存软限制和结果逐文件检查。native 模式没有容器的文件系统、网络和 capability 隔离，服务器必须明确接受这一运行边界。
- 结果入库复用原导入服务，UUID 存储标识避免多任务同名冲突；再次检查权限后才激活资源。临时文件 7 天过期，正式入库数据保留。地理结果入库前预览元数据/属性，入库后从目录进入工作台加载。首版任务元信息不自动按 90 天删除。
- 实际 GeoTIFF 入库发现 Windows 中文路径导致 GDAL 原生环境变量解析失败：统一 CLI 封装对已知 GDAL 命令添加 Unicode `--config GDAL_DATA`、`PROJ_DATA`、`CPL_TMPDIR`。临时文件仍在 TOML 应用根缓存，不引入硬编码科研根或浏览器栅格计算。
- 迁移前备份已恢复核验；迁移后原数据、工程、成果、文章、附件、项目和成员关系逐项一致。三次 compute 迁移和草稿初始化完成。后端 701 项及 52 子测试、前端 407 单元/181 浏览器测试通过；细节与实际页面证据见 `2026-09-19-compute-deployment.md`。
- 本机 WSL/虚拟机组件安装结果为 `restart-required`；没有自动重启。应用及 worker 可用，计算运行环境尚不可用。重启后继续发行版、Docker、镜像部署及真实执行验收，之后才能开放已通过试运行的算法。

### 2026-09-19 用户重启后的最终上线

- 上段记录为首次实施时的环境状态，已被本节替代。用户手动重启后，WSL 2.7.14、Ubuntu 26.04.1、Docker 29.1.3、计算镜像及worker全部就绪。四个1.0.0样例版本经真实计算与数值核对后发布，公开算法可在私有项目调用。
- Windows WSL应用安装须提升系统权限；只有启用可选组件并不等于完成WSL应用安装。无发行版时 `wsl --list --quiet` 可以返回非零，部署脚本已区分该状态。路径转换使用字符串Replace，避免反斜杠正则错误；Docker在systemd degraded状态下也需要显式enable。
- 现有Windows代理无法由WSL NAT直接访问。自动审批拒绝改成用户级mirrored网络，因此未改变网络模式；用Windows现有代理下载Docker Hub官方Python镜像并逐层校验后导入，WSL直接下载Python依赖。可复用 `deploy/pull-compute-base.py`。
- 实测发现普通Docker cp/archive接口不能可靠读取容器tmpfs，现改用固定镜像内 `/bin/tar` 读取活跃挂载。宿主继续验证声明文件名、普通文件类型、文件数、总大小和实际格式，保持超时/取消与停止容器的finally清理。
- 镜像补充Rasterio所需 `libexpat1`，使用独立gmcompute用户组（UID/GID10001），避免基础镜像既有operator组重名。SQLite读连接用closing明确释放，避免Windows GeoPackage文件锁导致结果目录重命名失败。
- 真实容器5项验收全部通过，覆盖4算法公开试运行/发布、私有项目执行、下载预览与三类结果幂等入库，以及禁网/只读/非root/资源限额/取消清理。实际应用worker完成4次样例计算和入库；浏览器完成另1次提交、下载和入库。子系统终止后重新启动应用，Docker和worker自动恢复。
- 公开项目新增3份注明人工构造的演示输入及5份演示输出，方便复核完整流程；原2份数据、工程、制图、文章附件、项目和成员记录与备份逐项一致。验收会话已清理。最后状态、截图、镜像摘要和测试报告见 `2026-09-19-compute-deployment.md`。


## 2026-09-20 旧平台残留清理

- 保留当前科研文章、物种知识、生态样例与业务数据；删除无路由的旧中英文单位介绍和平台概览。帮助与科普组件拆到 `KnowledgeHelpSections.tsx`，内容和交互保持。
- 清理无引用旧品牌素材、重复帮助 PDF、失效生成脚本、早期原型与测试报告；历史源码由 Git 保留。当前运维与验收记录继续保留。
- 只清理明确列出的本机及服务器临时产物；配置、数据、依赖和现网启动链路不变。详见 `2026-09-20-platform-cleanup.md`。
- 单执行者完成前端与文档整理，无 API 行为、权限、数据路径及栅格渲染变更。
# 2026-09-20 本地模型智能体首版实现

- 顶部“智能预警”已改为 `/agent/chat` 与 `/agent/workbench`；入口按正式登录用户的 `core.use_local_model` / `core.use_data_agent` 以及超级管理员策略收窄。普通用户默认可聊天，科研用户与平台管理员默认可用数据智能体，游客永远不可用。
- 后端 `apps/agent` 使用独立队列与 `agent_worker`，会话、运行、事件和证据落在业务库；每次提交、每个工具步骤和历史恢复重新检查用户状态、单项目成员关系、功能权限与资源可见性。模型地址只能由服务器 TOML 注册，前端不接收地址或凭据。
- 工具层仅注册 `search_resources`、`describe_resource`、`read_rows`、`summarize_data`、`aggregate_data`、`compare_summaries`、`read_document`；首期没有任意 SQL、Shell、Python、算子、写数据和成果发布。统计最多处理前 10000 行并标记截断范围。
- 本机默认使用 127.0.0.1:19100 的明确 Mock 服务；生产需把 `config/agent.example.toml` 合并到李老师服务器现有配置并单独启动 worker。2026-09-20 实时核验只有 19000 的 Qwen3.8-27B 在线，19001/19002 离线，未把服务器代码切换到线上。
- 本地隔离 QA 使用独立 SQLite、合成授权表和真实浏览器 HTTP 链路完成模型对话、数据智能体三步只读统计、依据面板和超级管理员设置页验收；后端全量回归为 727 passed、5 skipped、52 subtests passed。agent worker 现在使用独立跨进程锁，重复启动会拒绝；栅格 `describe_resource` 复用已持久化 GDAL 元数据，只读返回尺寸、驱动、坐标系和波段摘要，不读取像元。
- 当前真实服务器候选部署尚未切换；发布前仍需在候选代码目录和数据库副本上验证 19000 的 Qwen 实际流式聊天、结构化多步工具调用、取消、撤权和至少一项真实项目资源统计，再切换 6007。

# 2026-09-21 科研工作流编排基线

- 新增项目级 `AgentWorkflow`、步骤和 checkpoint，以及独立 `workflow_worker`。工作流先完成授权数据发现和结构化算法计划；未开启 `operatorEnabled` 时只读预览，不提交算子。
- 算子调用只复用 `apps.compute.services.submit`，要求已发布算法版本的 manifest 明确 `agent.enabled=true`，并继承当前项目、输入资源、队列、幂等和计算中心运行环境约束。智能体 worker 不执行算法代码。
- 工作流恢复时保留 `waiting_compute`，由计算任务终态驱动结果登记，避免 worker 重启重新提交同一算子；每次执行仍重新检查用户、项目成员、策略和资源权限。
- 本地工作流回归覆盖领取执行、计划 checkpoint、排队取消和等待计算恢复；真实高光谱算法、成矿理论规则库及迭代评估仍需龚师弟注册算法并按 `2026-09-21-agent-architecture-review-v2.md` 的候选环境门槛验收后再开放。

# 2026-09-22 智能体算子、多模态与上下文扩展

- 工具网关新增系统运行摘要、已发布算法清单、计算任务提交、结果入库申请和受控公网检索；所有副作用继续经过计算中心服务、项目权限、幂等和审计，模型不能提交路径、代码、Shell 或容器参数。
- 会话附件使用 TOML 配置的数据根和项目目录，支持 PDF/DOCX/TXT/Markdown/CSV 文本提取及 PNG/JPEG/WebP 校验。附件在提交与 worker 读取时双重鉴权；图片只发送给显式标记并真实探测支持视觉的模型。
- 服务器 `Qwen/Qwen3.8-27B` `/v1` 实测上下文窗口 32768 token；非流式与流式深度响应可能把思考放在 `content` 前缀并只返回 `</think>`，provider 已兼容该协议并将真实片段持久化为 thinking 事件。
- 上下文超限时优先裁剪旧历史和工具返回，再有界裁剪附件文字，保留当前问题；管理员可调预算、输出、采样、工具/算子步数、附件和运行时限，模型窗口仍是硬上限。


### 2026-09-24 原生窗口与任务预算

v0.1.15 将模型物理窗口、角色授权上限、任务预算分层。AgentRun 新增预算方案和快照（迁移0008），继续保留旧任务记录。普通用户默认64K窗口/16K生成/600秒；超级管理员默认262144窗口，可按任务提高生成量，时限最高7200秒。时限是平台策略，不存在模型“原生秒数”。对话输入字节保护、附件提取和流式传输大小随预算放宽，最终仍以完整请求分词为准。

Qwen3.8-27B 独立候选服务262144窗口实测240039输入token，前中后三处校验码全部找回，耗时91.5秒；131072生成额度请求被接受，实际只生成2 token，不能据此宣称连续长输出测试通过。候选使用独立GPU4–7，正式服务使用GPU0–3；发布回执记录正式切换与应用验证。

## 2026-09-27 智能体界面与任务说明
- 本次统一承接前端交互及发布；接口契约、服务器授权与预算额度保持原有实现，没有新增 API。
- 每条回答单独展示可折叠的数据来源与分析，引用编号在该轮内解释。普通用户查看结构化结果；`bootstrap.canManage`（服务器判定超级管理员）额外显示折叠的原始调用、运行参数与生成设置。
- 按 canChat/canAgent 隐藏未授权入口，未开放联网检索不显示控件。长推理方案在支持深度思考时同步启用 deep，并清除上一方案的手动强度与生成覆盖值。
- 计算搜索只筛选当前项目可访问的输入候选；计算输出仍由 worker 按项目、任务、执行批次独立存储。任务详情提供权限控制的下载/入库。
- 项目是数据与任务范围，普通和科研角色均可进入分配的项目；角色不自动分配私有项目。顶部说明不改变授权。

## 2026-09-27 数据分析页简化
- 页面仍按项目与现有浏览/查询权限读取真实非地理数据；无分类过滤时附带内置胡杨演示案例。移除静态分析资产与重复工作区、视图、专题入口，保留中心分析标签及按需展开的字段说明。
- 地点号改为演示标识字段，不参与指标分布和二维图。分布选择直接放在直方图旁；二维图提供具名、带单位的两个数值轴，以统一大小/颜色的点展示当前明细中的有效数值对，并说明预览范围。相关矩阵补全字段标签与配色含义。
- 实际资源分析报错留在原资源，避免将演示误读为该资源结果；示例继续显式标注。
- 本次承接前端及发布，无 API 契约、权限、数据路径或栅格渲染变更。

## 2026-10-04 文档知识与质量门控

- 知识库沿用同一入口，增加“资料检索”和“自动 Wiki”；格式化规则继续单独维护。资料保存原件和 SHA，检索展示原文片段；Wiki 保留来源、主题关联和修订号。图中展示关联较多的18个主题，完整页面列表保留全部可见主题。
- 平台负责账号和可见性，WeKnora Lite负责切分、混合检索和自动整理；按项目共享/本人私有分别建立上游知识空间。公共资料在公开项目内维护，私有资料仅本人可见。跨源知识合成仅在授权空间内进行，生成Wiki不直接转成已审核规则。
- WeKnora固定官方0.8.2源码并应用SQLite Wiki兼容补丁；构建、初始化、启动和模型来源见 `deploy/knowledge/README.md` 与 `docs/knowledge-runtime.md`。向量服务使用独立GPU上的BGE-M3，Wiki共用现有Qwen；后台整理会影响同一模型的对话时延，效率实测在队列空闲时进行。
- 智能体区分知识资料编号与数据资源编号，使用独立知识全文工具；真实原文与生成内容分开。知识/算法证据不占数据资源访问额度，按目标筛选算法，回答末尾直接查询最新计算及入库状态。
- 几何修复走已有计算中心，保留输入和所有要素的审计记录。质量报告声明于manifest，计算worker、智能体、编排和自动导入均检查；需复核或报告失效暂停自动入库。当前评价范围为几何质量，矿物成因等专业语义修复仍需相应算子与验证资料。
- API契约、生成类型、开发说明和Mock同步；科研数据路径及栅格渲染方式沿用现有配置。开发候选验证与正式发布验收分开记录，正式回执绑定冻结提交与文件哈希；人工夹具和测试账号仅保留在隔离候选。

## 2026-10-05 页面精简与对话布局

- 登录直接进入工作台，权限清单保留在个人设置供主动查看。项目选择仅显示当前项目与可选项，上传页在锁定文件时提示如何换项目；权限判定与切换未保存工作确认保留。
- 新闻/科普读者页不显示内部编辑来源。科普第7、8篇现有图片仅去除精确匹配的课件讲次页码后缀，保留正文、图注解释、延伸阅读和原始来源；已归档或人工替换资料保持。
- NDVI资源层补齐用途、输入、公式与输出简介，仅更新公开内置算法的空白/已知默认描述；不变更已发布版本清单、算法包或执行逻辑。
- 智能体会话侧栏和输入区增加拖动/键盘尺寸控制，尺寸按账号与模式保存在浏览器并受当前视口约束；窄屏保留独立会话抽屉。布局修改保持现有模型、思考强度、资源选择、附件、编排、运行状态与提问滚动行为，无API变化。

## 2026-10-08 导航悬停与知识网络反馈

- 顶部导航在压缩模式下保持按钮尺寸和位置，悬停或键盘聚焦通过 Ant Design Tooltip 展示栏目名称。文字提示渲染在独立浮层，避免展开文字挤压搜索框与相邻按钮；下拉栏目的提示置于侧面并不截获鼠标，避免遮挡菜单。移除导航悬停上移效果，原有栏目跳转、下拉菜单和宽屏栏目文字保持。
- “让知识连成线”使用低对比蓝青渐变，点击节点、关系或空白画布显示短光环。反馈使用现有 SVG 坐标与缩放映射，连续点击仅保留最新效果，640毫秒后清理；减少动态偏好下使用静态光环。
- 节点拖动与点击分开判定，拖动、指针取消或捕获丢失均不误触筛选。节点筛选、关系依据抽屉、缩放、暂停浮动与键盘操作沿用原有行为。
- 本次只有前端交互及版本说明变更，服务器发布按业务表、已发布算法包、运行配置和模型/知识服务身份保持验收，不新增数据库迁移。

## 2026-10-09 聊天空间、导航切换与地矿知识

- 导航首次适配在绘制前同步测量；临时测量样式优先于压缩与搜索展开样式，移除尺寸过渡。搜索外部关闭使用点击事件，避免按下时改变导航命中位置。智能体初始化信息按用户对象、角色权限和项目在内存复用并后台复核，切换身份及失败时隔离；服务器继续判定实际访问权限。
- 智能体采用灰蓝工作区、中央消息与紧凑输入工具条。新用户输入默认64像素，合法旧尺寸记忆保持；模型、资料、联网及思考设置由按钮打开。科研工作流使用保持挂载的抽屉，关闭后保留草稿、轮询及待确认提示。主聊天移除运行详情，来源按引用编号折叠展示，保留进度、错误和重试。
- 系统简介四功能块去图标、功能标题与团队研究方向标题加粗；个人可用功能改为分组和短条目，成果装饰改蓝，导航智能体与内部采用同款机器人图标。
- 地矿知识通过 `seed_geology_knowledge --batch geology-20261009` 只增30条公开知识及对应首版修订。来源、条件与完整目录见 `knowledge-additions-2026-10-09.md`；原种子和人工修订保持，无API或迁移变化。
- 发布验收核对所有原业务行不变，仅允许冻结批次的知识条目/修订各新增30。模型与知识服务保持；本次回退应用时保留当前数据库，旧版本可读取同一知识模式。

## 2026-10-10 计算结果目录与共享参数表单

- 数据目录新增 `compute_results`，仅由真实计算输出入库维护。内部布尔标记带数据库默认值，兼容旧应用写入。历史回填依据 `ComputeImport.resource` 同项目关联；原始资源、状态、时间戳、隐私及知识内容保持。
- 五类入库成果统一进入结果目录，保留资源空间属性与存储类型；普通上传不能选择计算结果。目录、地图和后台同步展示，计算来源使用友好文案。
- 计算中心和智能体共用 `ComputeAlgorithmFields`，统一输入、参数、结果概览及校验；波段/字段关联随输入变更清空。默认参考只解释算法清单，智能体空波段不自动填充。
- HTTP结构保持；更新目录语义、Mock、生成类型与开发说明。发布按0.1.30业务数据快照核对，只允许新增分类、结果标记和可核实的历史结果分类变化。

## 2026-10-09 智能体计算执行闭环

- Chat计算以AgentRun.compute_intent保存已发布清单、输入、用户确认参数和真实任务回执。缺波段时参数卡暂停，用户文字明确波段时直接执行，NDWI与NDVI目标切换替代旧未提交计划。默认完成后选择入库；明确自动入库时保留授权。
- 结果报告与进度来自真实任务/输出/入库。后续问题限定本会话关联记录，模型不能将旧相似任务或无工具证据的答复变成执行事实。参数操作重新授权并校验资源修订、清单校验和、计划摘要和幂等。
- 新增受限后端栅格PNG预览：原始结果只读、每请求实际校验和、WGS84角点、NoData透明、8项内存LRU，临时文件当次清理。地图仅加载临时层，用户选择入库后返回名称、项目目录与地图入口。
- agent0013仅新增compute_intent JSON字段，Python默认和数据库默认均{}，旧应用写入可兼容。发布保留所有既有业务行，不导入本地/候选数据库。机制与公开架构比较见agent-compute-execution-20261009.md。

## 2026-10-10 知识关系网络视觉调整

- 格式化知识图取消领域矩形与连通分量格子，恢复全画布自然聚集布局。概念按真实关系吸引，以小节点、细线和分层标签控制密度；点击概念突出邻居，其余内容弱化，选中不重排节点。
- 四领域保留颜色和小导航锚点，以总导航节点和浅虚线串联专题。每个真实连通分量通过一个归属连接挂到所属领域；实线继续只表示已有知识条目，点击打开来源与适用条件。归属连接不生成科学关系、不进入知识检索或推理证据。
- 当前图为检索范围内的代表关系概览；知识列表仍保留全部返回条目。真实跨领域概念按精确名称共享，条目 aliases 不用作概念合并依据。
- 本轮只改前端图谱和版本说明，API、权限、数据库模式、数据路径及栅格渲染保持。发布不执行迁移或种子写入，候选/正式验收只读知识图，业务内容与独立模型/知识服务保持。

## 2026-10-10 知识网络参考视频配色

- 按用户视频恢复深青蓝至藏蓝的微渐变及按知识细分类着色的柔和节点，沿用整体自然布局、小节点和分层标签。专题锚点保留独立导航语义。
- 画布内标题、搜索、工具栏、标签、关系线及图例采用匹配的浅色；点击扩散和选中光晕提供明确反馈，减少动画偏好采用静态反馈。
- 发布为纯前端更新，后端仅版本字段变化；API、权限、业务数据、存储路径与栅格渲染保持。

## 2026-10-12 自然聊天任务解析纠正

- 科研解析使用授权目录的英文角色键，中文显示名用于公开说明。无值角色省略并澄清，候选、角色与参数仍由后端严格核验。
- JSON或参数校验失败时，携带实际错误与完整目录让模型反馈纠正一次；不映射角色或补专业答案。每次请求前、响应后、校验后保存独立审核记录，原响应与校验后的结构分别保留。
- 两次请求共用原预算与取消守卫，网络、权限及取消异常直接停止。此次修复使用既有内部JSON字段，无新增API或迁移。
- 科研续接的自动知识范围从同用户、项目、会话的已绑定任务取得，实时复核后冻结为本轮有效范围；新任务按实际场景同步范围。一般聊天沿用原自动筛选，明确知识、数据和算法手选范围继续约束历史引用。

### 2026-10-12 科研工作流成果与控制
- 原两个模拟案例阶段图保持：模型在真实证据和允许操作内判断，阶段顺序由科研工作流编排。
- WorkflowResults/DecisionTimeline收起已完成说明，RunComputeTasks复用同一轮询并集中展示最终文件、过程文件和真实CSV/地图动作。
- 新报告服务仅取公开判断、真实输入、参数、知识与结果文件，持久MD及伴随SHA清单保存于配置目录；预览、下载、可选入库按本人/项目/来源权限重查。报告不伪造单一计算任务引用。
- 暂停请求与来源阶段独立持久字段；安全点保存后paused，继续复用真实taskId并保留人工审核。后台running期间的中间保存不能抢先公开可恢复状态，过时worker不能覆盖暂停请求。
- 新接口及类型详见OpenAPI和API-20261012-002；迁移0016；用户操作见releases/0.1.39.md。

## 2026-10-14 地质成果智能检查与修正

- 新场景 `geology_map_review` 使用当前项目的 `initial_map/coverage/rules` 三角色，复用知识检索、持久科研步骤与隔离计算。模型先确定知识查询，再读取检查结果提出建议；建议位置和处理目标来自真实问题表，知识按已检索条目的ID与修订核验。
- `geology-map-check` 与 `geology-map-correct` 分别负责条件检查和受约束编辑。内部漏填须满足完整覆盖、排除例外、全周界唯一宿主等条件；地层时代按地区、地层定义和规则核对。类别以class为稳定键，同名不同编号分别保持及统计。
- 修改方案保存摘要与逐项建议。用户批准绑定输入快照、规则、算法、参数、知识引用和选择范围；方案漂移需重新确认。仅获批操作生成编辑输入，拒绝不编辑，未批准疑点在复核报告保留。实际修正结果返回模型继续判断。
- 地图采用同步双图和相同class配色，批准前显示建议范围，完成后查询实际修正图和差异图。检查报告校验真实输出、批准记录及重算统计，沿用预览、下载和文档入库权限。
- 案例运行资料与独立参考、设置清单分目录保存；导入命令只接受三项运行资料。正式入口显示演示案例；准备过程和独立验收记录保存在运行输入之外。案例操作与展示口语稿见 `geology-map-review-demo.md`。
- API-20261014-003更新场景、知识查询和逐项审批字段，OpenAPI、开发说明与生成类型同步；本次无数据库迁移，权限和数据根目录继续复用现有配置。
- 长中文自然语言检索在同一授权项目、领域和分类内，补充召回查询实际包含的subject/object/aliases概念并排序；保持候选与返回上限。逐问题所需知识由真实检查行及已检索、当前有效的条目形成，缺失或漏引进入模型既有一次纠正反馈，继续共享请求预算。

### 2026-10-14：聊天创建工作流的SQLite事务

聊天入口在创建工作流及绑定会话的外层事务内，先对当前运行做幂等键同值UPDATE，再进入共用创建服务进行鉴权读取。SQLite的内层atomic仅为保存点，单靠创建服务内的写预约无法保护外层已建立的WAL读快照；后台心跳并发提交时会触发SQLITE_BUSY_SNAPSHOT。文件WAL交错回归覆盖旧顺序失败、新顺序成功、心跳随后提交、原子回滚和幂等。业务启动错误保留具体原因，未知异常只记录类型及代码位置；算法质量报告的原摘要保留在质量结果卡，自动入库阻塞使用固定可读提示。

## 2026-11-02 平台体验与独立监测

- 快速/科研对话入口固定在主工具栏，避免窄屏会话侧栏隐藏后丢失切换入口。MH-workflow默认720px，支持拖动、键盘及宽度记忆，表单依据容器宽度排布。
- 地图左右栏按用户记忆宽度和收起状态，拖动时同步地图尺寸与底部查询区。图例只读取当前可见图层及服务端实际渲染规则，连续自动拉伸未返回数值时标低/高，RGB显示真实波段组合。
- MH-Agent为产品助手名称；每次普通模型调用注入品牌与真实模型配置，明确询问底层时如实说明。前端回答标题使用助手名，模型追溯字段保持原值。
- Mapbox仅在样式值变化时设置属性；动态栅格沿用LRU128和文件指纹缓存，通过短生命周期的同键互斥合并并发冷渲染。不同瓦片仍可并行，权限检查与栅格后端渲染保持。
- 独立监测参见[平台监测说明](platform-monitoring.md)，当前选择本机运行。Webhook、状态和日志不入Git，配置完成并实际启动后才算群通知启用。本次没有API契约、权限或数据根目录变动。
- 实际页面验收发现隐藏的工作流面板会在模式切换时提前加载完整计算资料目录，并发分页挤占请求线程。资料目录改为按需加载与取消旧请求，任务状态恢复沿用既有逻辑。计算目录单独读取轻量元数据，真实计算提交仍核对源文件；原始影像与展示COG的波段、坐标信息分别处理。
- 角色列表GET沿用启动和迁移时完成的初始化，取消读取过程中的权限与游客重复同步；实际日志确认原重复写库在并发会话活动下触发SQLite锁冲突。角色授权写接口继续执行原检查。

## 2026-10-23 海德乌拉综合推理本地集成

- 新增 `geology_multi_element_reasoning`，综合及岩性、构造、蚀变三个入口复用九角色资料和四类隔离算子。旧场景保留。分段记录本次上游资源版本，结果来自实际任务，不用交付参考图替代。
- 原件只读；准备脚本生成中性编号与去标签运行副本，原编号映射、注入记录及参考地质图仅留独立评价目录。541个岩性面和182条区内模拟构造参与运行，五类矿物保持原识别栅格。计算真实转换至EPSG:32646，显示沿用平台坐标转换。
- 17条知识保持draft，34个归一代号及38种名称映射冻结于场景输入。试用条目只在当前项目、当前场景、显式条目与修订绑定下读取，普通检索权限不变。运行CSV从服务端知识版本重建；批准前和执行前重验快照、规则摘要及允许动作。
- 检查、获批修改、构造关系重建、前后远景区为四类职责。检查表保存实测值、条件和例外；模型读取每规则代表对象，全量结果可下载。保留、待裁定、降权、剔除分开；降权保留非零权重并真实参与远景区计算。未批准对象保持，检查后再改须获得新批准。
- 地图双图扩展线、点、面，按原图例配色，几何交汇和推测交汇分别显示。报告关联实际知识、算法、参数、批准和输出。A/B表示本案例的证据组合等级；矿点验证及部分地质参数待专家核对。
- 算法发现和新提交按稳定项目编码筛选：逻辑推理复用地质及通用矢量工具，生态复用NDVI/NDWI、生态及通用矢量工具；本项目登记工具保留。历史任务读取独立，不因目录筛选失效。
- 本次仅本地集成。当前本机模型为模拟服务，GIS算法实际执行；模拟流程验收与真实大模型判断分开记录。原1.0.0失败试运行保留，新算法修复版本分别登记，不覆写旧包。
- 本机补执行已有 `agent.0017_run_interactions`、`compute.0006_nullable_historical_input`，先保留SQLite备份；本次未新增迁移。Agent worker仅对SQLite locked/busy重试，缺表/字段等配置错误明确记录退出。
- 本机完整五任务成功，批准2处代号/3条构造暂不参与/2处矿物降权；未批准及几何保持经独立核对。A区23→23，B区62→61，面积38.6924→38.0424 km²。复核新增12条背景提示来自代号修正后的实际碳酸盐背景占比变化，新的修改仍需批准。
- 综合报告以 `compact-v2` 独立目录及来源保存，保留先前报告，展开获批对象并链接全量输出；生成前核对真实处置的对象、动作、类别及权重。冻结规则入库前重查当前项目数据新增权限。操作与验证说明见 `geology-multi-demo-local-20261023.md`。
- 地图查询使用本机10,000上限覆盖本案例，前端串行读数、密集层按需加载，矿物前后分别取check/apply实际输出；公开浏览器地图令牌仅复用到本机忽略配置，未改服务器配置。
- 双图仅在完成load及范围适配后保存恢复视角，避免StrictMode初次清理把默认视角误当用户视角；综合场景默认收起详细岩性图例。真实地图面积及边界使用实际数据，不通过固定缩放伪装展示。

## 2026-10-25 地质扩区与逐处结果讲解

- 旧地质检查预设使用`expanded-20261025`独立资料版本，70.56平方公里、38图斑、13类、3漏填和2时代问题；精确匹配三角色同版code，默认max_changes=5。原版仍可从历史任务和资料读取，已发布1.0.1算法包保持。
- 海德乌拉导览以apply阶段完整changes表的actual_changed为执行依据，按对象、规则和动作关联空间疑点几何，再核对获批建议及approvedEdits中的目标代号、权重与快照。空间输出的suggested_action仅用于关联，不代替实际修改。总处数动态读取，缺少完整结果不展示已执行导览；展开依据可追溯任务、输出校验和及原表行。矿物前后权重从check/apply输出读取。
- 共享双图增加独立spotlight更新：全区数据保持，导航只更新当前对象source、背景透明度及HTML文字标记；不依赖外部字库。切换时保留Map实例、同步相机与实际几何。
- 当前对象定位直接更新相机，不以isStyleLoaded作为后续定位条件。GeoJSON更新会暂时将该值置为false，原条件会丢失导航定位；真实WebGL回归同时检查对象标签位于画布内，覆盖快速切换与异步矿物读取。
- 焦点变化时先同步两图容器尺寸，再按当前尺寸fitBounds，覆盖全区620像素与逐处紧凑画布的切换。ResizeObserver保持用户缩放，仅显式定位重新适配范围；视口验收同时核对标记与对象投影边界，避免仅标签居中而轮廓被裁切。
- 调查区按几何与证据组合等级对比，忽略重新编号及多边形环起点方向，突出实际变化；数量、面积按前后真实输出汇总。该展示说明核查建议变化，效果评价仍需后续调查证据。
- 常规工作台用`geologyCompare`任务链接恢复已授权输入及成果，复用数据加载去重；双图固定展示本任务前后结果，普通单图保留正常图层操作。独立`geologyReview`结果页继续可用。
- 地质检查的模型上下文按用途投影：保留全部问题行、签名、知识定位、面积、范围和统计，完整坐标继续保存在原输出及审核预览中。模型请求不重复传送问题表几何与审核预览几何；实际建议、批准校验及编辑算法仍核对完整原始结果。扩区真实模型首次因坐标重复超窗停止，失败记录独立保留，修复后另做真实验收。

## 分组建议校验与模型纠正预算

- 审批卡片中的可执行建议组和待裁定与例外区默认折叠；用户展开后保持状态，组内对象沿用每页50条展示。工作台对比页的前后导航统一提供“上一处修改 / 下一处修改”可访问名称，宽屏与360px测试同时检查按钮可见性、视口边界和真实切换。
- 综合推理的分组建议按冻结检查快照匹配试用知识，每组在`decision.evidenceRefs`引用一次对应知识即可；展开后仍逐对象检查动作、权重、范围与快照。重叠规则继续按检查结果顺序固定唯一处置。
- 同组同因错误仅记录一次，包含规则、动作、受影响对象数量及缺失知识的编号与修订。错误清单最多30条、12000字符，超出部分汇总数量；丢弃计数保持真实对象数量，沿用审批卡片的丢弃说明。
- 纠正提示最多16000字符。发送前使用模型实际分词服务及输入字节预算检查，超限先移除旧回答和重复任务资料，再压缩错误及重复指令；保留原始资料、证据、模型生成上限和审批边界。压缩级别与请求摘要一同保存，恢复时重建同一请求，不额外调用模型。第二次回答只保留有效建议进入人工审批，无效组不进入执行输入。

## 综合推理用户裁定与卡片持久状态

- 算子1.0.8将待裁定/例外候选保存在检查快照，审批从快照完整补齐；不依赖模型展开，模型只可保留这些对象。候选与规则状态分离，默认不选择，普通建议全选不包含候选；用户确认仍通过原有本人/项目/planHash确认接口。批准及执行均验证冻结动作和目标，并在真实修正理由中保留用户裁定标记。
- L-06仅在本演示案例以紧凑度、最小外接矩形长宽比筛查全新世冲积物团块，较高置信度仍待裁定。L-07以低置信度、近等轴、同类不相接及较年轻同类别单元占主导的边界证据补充遗漏，始终待裁定；已有发现不重复报出，不用此规则提升原例外。独立参照及注入标签只进入仓库外的事后评价，不传给算子或模型。
- 卡片实例和内部故事按工作流编号稳定，不按更新时间、阶段或proposalHash重建；详情补载期间保持已读内容，收起使用隐藏而非卸载。过程默认值只在新工作流设置，避免终态触发自动收起。审批选择仍受proposalHash隔离，展开状态不因此重置。

## 工作流操作区与阶段输入预算

- 工作流卡片的确认执行、结果审核、批准建议、继续分析、暂停、继续及停止操作不随过程折叠隐藏。修改审核状态自动读取审批详情，普通计划确认不要求展开或补读明细；历史过程和计算附件保持惰性读取，收起后保留已读节点及选择。
- 所有真实场景模型请求，包括各阶段首次请求，均使用服务端实际窗口、生成预留、同一分词接口及字节预算预检。超限依次复用重复片段、减少分组代表样本并筛选对应规则使用的测量字段、节选知识正文及历史分析摘要；完整分组数量、规则版本、实测范围、对应知识编号与修订、适用条件及例外不删减。
- `modelRequestPayload`保存压缩前资料，`modelRequestInstruction`保存系统指令；请求审计的`budgetLevel`和`repairLevel`确定实际投影及纠正提示，结合响应与`requestSha256`可重建请求。恢复校验使用相同投影，不另发模型请求；完整对象证据继续保存在冻结检查输出。
- 必要证据经全部压缩仍无法容纳时，任务停在人工审核，不发送超限请求、不伪造模型判断、不执行计算。调整窗口后确认会归档原预算审计并重新分析，不以用户确认替代缺失的模型判断；缩小输入范围需重新发起任务。

## 逻辑推理按需投影与成果默认配色

- 逻辑推理工作台对比、独立对比与逐处讲解共用本地SVG双图，保留岩性配色、叠加层、图例、对象点击及视角联动；不创建Mapbox实例、不读取token、不请求底图。普通地图继续使用原Mapbox实现。SVG控件样式由共享工作区样式提供，不依赖对比台路由。

- 审批的 suggested 对象默认勾选，用户可以取消整组或单个对象；待裁定与例外默认保留，只有明确选择冻结候选才纳入用户裁定。确认弹窗分别给出模型建议与用户裁定数量。完整分组索引保证尚未加载的对象仍能按组选择或取消；原因按类别计数，原文只在对象详情显示。
- compare 以已保存批准、实际执行明细和冻结建议的交集生成导航，验证任务、输出校验和、动作、权重、目标及快照；摘要不包含全量建议、执行行或模型请求。对象每页最多50条，对比页按25条读取，原始执行行号保留。未批准对象可经深链接查看候选范围，不标记为已批准或实际修改。
- 卡片、历史过程、活动详情及工作台分别使用 inspection/compare；过程与审批对象按需分页。展开/收起只改变显示状态，不以展开状态重复读取同一版本；轮询补载不卸载已读对象。显示几何在后端使用统一1e-5度网格量化，全体面边界共同节点化以保持共享边界；不做形状简化，仅清理连续重复点和退化环，共同节点化可能补入共享顶点。超过体积目标只警告，保留对象数量，不回写科研数据。
- 逻辑矢量成果按实际分类字段、完整类别及相关候选配色。标准及项目约定色表命中时原样采用，38类岩性的 color 与 ExportedFiles.lyrx 原色及 referenceColor 逐一相等；蚀变、等级色同样锁定。模型只为未命中类别建议颜色，色差冲突只调整非色表一方。面填充不检查白底对比；非色表色检查格式、重复、Lab ΔE76≥12及深色边框对比≥1.25，线、点另检查白底对比≥3。色表之间不做色差调整，原表完全同色保留原色、用图例名称区分并记录 duplicate_standard_color_preserved，避免破坏原色一致性。反馈修正一次，仍不合格或离线使用确定性调色板，逐类审计来源与原因。共用8秒期限和阶段输入预算投影，按相关性压缩候选但不删类别。同一流程的工作台、对比及讲解双图在分类字段相同时以成果映射为准，输入独有类别补色；仅变更流程内显示，不写回输入资源或其他项目。style_logic_results 默认输出完整预览而不保存，--apply 强制重算并写入。
- 逻辑项目的自动标题包含主资料、检查任务、时间和运行编号；自定义标题与其他项目不变。历史默认标题和已有成果配色分别由 backfill_logic_titles、style_logic_results 管理命令显式处理，执行说明见开发者指南。
- card 与 inspection 保留字段确认和沿用配置状态，普通计划确认不自动补读过程；修改审核才自动请求建议。待裁定分组通过 summary 点击更新受控展开状态，避免原生 toggle 事件与 React 状态互相覆盖。对比页自动读取首个实际修改页并定位，不要求先开启修改范围；单页保留“全部修改”，多页保留分页语义。地图与讲解区允许在固定视口内收缩，讲解内容内部滚动。
- 显示查询缓存位于配置业务根目录的 cache/vector-display，以项目 GeoPackage 路径、资源 ID 和查询参数定位文件，并校验资源 updated_at、存储图层和算法版本；资源修订后重算并原子替换，不影响科研数据。无过滤显示查询命中时跳过原始数据读取、量化和压缩预算计算；登记成果的 worker 预热工作台常用查询，失败仅记录日志。配色在 Mock、策略关闭或所选模型不在线时直接使用确定性方案，不发探测、分词或生成请求。

## 2026-11-06 规则处置与本地回放

新计划rule_geology_v2把固定计算和规则处置交给确定性代码：读取同一实际任务的scope=all问题清单，核对knowledge_id/revision、规则版本、允许动作、签名与候选目标。review/exception、同对象冲突、缺少匹配知识均不进入自动集合。所有生成建议仍通过既有逐项校验，执行前重新读取哈希相符的实际结果。

一次资料启动可选applyRuleSuggestions绑定输入版本；automatic_dispositions记录先前明确授权下的实际范围，独立于逐项modifications_approved。篡改授权、扩大选择及删除证明均停止执行。旧计划继续原协议，取消自动执行仍可在处置卡审核。最终模型报告读取完整统计、知识条件与例外及处置汇总，图像/矢量明细按reference_only引用，完整文件保留；不声称模型逐条审阅。轻量档保留原有可见思考语义。

开发先在本机回放实际241条结果，再在本机前端、后端与三个worker运行非空问题流程；只在最后冻结包进行远端实际数据验收和正式切换。X-App-Entry及更新提示处理旧标签页继续运行旧JavaScript的问题，构建标识不承担权限判断。

## 2026-11-07 逻辑推理输入竞态与地图显示修复

- 复用字段的保存移入 generic_chat 创建任务事务；原先事务外旧对象写 plan 可覆盖 worker 刚生成的 review_mapping。保留原确认和执行授权校验，不放宽阶段。
- 蚀变 before/corrected 输出按工作流一次调用模型配色，以正式候选表校验，保存在输出 metadata，之后复用；预览统一脚本按离散 RGBA 颜色表渲染，缓存键含色表。旧结果可用 style_logic_results --rasters-only 更新显示元信息，源像元/校验和不变。
- 对比页交互 SVG 的焦点提示沿真实 path/circle 显示，不再用包围盒 outline；鼠标和 Enter/Space 操作均保留。蚀变图例从后台实际色表读取，不在浏览器重着色。

## 2026-11-07 审批证据与栅格显示信息

综合地质审批重新读取全部实际输出并核对冻结结果。栅格 metadata 的 `mapColorTable`、`colorAdvice` 是可更新的显示记录，比较时仅排除这两个顶层键；输出编号、任务、类型、校验和、行内容、数量与其他科学元信息仍完整比较，文件路径、内容和权限继续由实际结果读取逐项核验。既有快照两侧统一投影后比较，不修改 planHash、建议或用户选择，兼容配色更新前后生成的任务。修复了配色保存晚于结果快照时导致的“实际检查结果已变化”误报。

## 2026-11-07 逻辑推理校验去重

- 同一批实际结果只核对一次工作流—任务绑定，批处理开始和结束仍分别重新授权；每份输出仍校验归属、状态、过期、路径和内容。审批读取由统一读取入口负责授权，去掉调用方重复的一次完整授权。
- 审批确认、单次工作流推进、结果读取及栅格预览使用仅在本次同步操作存活的 checksum_scope。相同路径只有在设备、inode、大小、mtime_ns、ctime_ns 和文件模式均不变时复用内容摘要；首次读前后核对文件描述符及路径身份，途中变化返回409。符号链接不复用。权限、项目、知识、计划与暂停/停止状态不缓存。
- 不跨 HTTP 请求、worker tick 或线程共享，异常退出也销毁缓存；后续执行边界重新校验。无需改变业务数据或既有任务计划，不能以该机制放过真正变更的文件。

## 2026-11-07 模型参与、即时停止与核查底图

- 普通停止原子发布cancelled、停止排队算子并请求终止运行算子，尚未开始的本任务自动入库标记停止，仅限本人同项目真实步骤绑定；返回card避免大响应。工作副本逐份登记，避免共享GPKG写入期间持有全批SQLite写锁；主要阶段检查取消，取消后的晚保存不能覆盖计划。
- 真实模型每次重新判断角色，包括复用资料；仅当本次角色与已确认配置一致时沿用字段。角色思考采用low、最多4096输出token/90秒，管理员思考开关仍生效。模型原始回调进入实际思考流，inputSummary显示依据和model/saved/rules/user来源。
- 新的真实模型综合任务在首次检查前形成并确认执行方案，依既定受控算子协议调用；后续算子按该任务执行和结果推进，仍保持完整测量与批准边界。规划low/4096/90秒；报告由模型直接整合核验统计（不开额外长思考，6144/120秒），不逐对象增加模型调用；模型最低阶段请求由1变2。历史已准备计划不强插新决策。
- 报告按实际模型调度记录说明分工，正式规则状态取当前登记；不把试用内部绑定字段当发布状态。重新解读已完成报告使用refresh_logic_report --workflow ID --apply，追加interpretation版本与实际模型审计，原报告保留、科学结果不重算。
- 待核查区域复用本地矢量对比渲染器。岩性和构造底图仅核查面板打开时读取后台简化几何，同ID共用请求；勾选与聚焦不重取底图、不调用算子或模型。当前/检查图左右联动、几何边界高亮，蚀变组仍明确为导航范围。

### 角色引用稳定性

模型请求使用file_短编号，并将上次角色对应转换为同批短编号，避免UUID抄写错误或无法将旧资源ID关联到文件。返回前严格校验并恢复真实uploadId，API标识不变。格式或引用错误最多校对一次，校对沿用原始资料且不重复长思考；失败如实显示平台建议，并保存角色校验审计。

### 核查地图冷启动与遮挡

工作副本提交后，单个后台读任务在模型规划/算子等待期间预热岩性和构造简化显示缓存；事务提交后启动、并发上限1、繁忙时跳过，不阻塞主流程。每份资料仍重新授权，停止或暂停后不启动下一份，缓存失败由用户查看时重试。默认以定位标记浏览疑点，只对当前对象显示实际边界；蚀变组以定位点和单一虚线范围导航，不把范围框冒充像元边界。选择与缩放不发起新的底图或模型请求。

## 2026-11-07 修正后找矿算子与单图核查

- 本轮单人承担契约、后端、算子、前端及验证，按契约→实现顺序交接。算子2.0仅处理修正后资料，以构造、邻域蚀变组合及已知基岩圈区，有利岩性参与排序；默认最多5处且每处0.2—3平方公里。无修正前找矿和A/B分级，历史证据仍按原协议读取。
- P-02通过独立知识条目和独立规则资源登记邻域语义，不覆盖旧知识与被冻结的任务。新任务优先新规则包。仅上传新prospect算子，不能用共享核心重打包后覆盖其他已登记的1.1.2版本。
- 新热力栅格仅在目标内平滑和归一化，统一后端脚本连续蓝黄红赋色；浏览器只显示PNG及实际色带图例，相对置信度不表示矿化概率。流程内待核查仅显示当前成果单图，并只读取当前岩性/构造；独立对比页仍可前后查看。


## 2026-11-07 管线显示性能

详见[pipeline-display-performance-20261107.md](pipeline-display-performance-20261107.md)。同一代理按契约→后端→前端交接。仅普通大线图层显式请求按尺度简化，不改变原displayGeometry图斑精度承诺；空间缓存有界，查询协商gzip，原始数据保留。

## 2026-11-07 输入版本复用、导航与核查概览

- 本轮由同一人按契约→后端/SDK/算子→前端实施。数据资源移至智能体右侧，首六项为地理工作台、智能体、数据资源、计算中心、知识库、成果展示。
- 输入缓存按项目/资源存储独立内容版本，不改变数据库结构或原科研文件。源文件/WAL/依赖文件身份一致时直接复用；共享GeoPackage/SQLite其他表变化时按所选表逻辑内容确认，避免整库变化导致反复GeoPandas导出。缓存清单用服务端HMAC认证，并绑定规范文件哈希与inode/时间/模式；原地变化、损坏或伪造标识停止复用。
- 任务文件采用Linux FICLONE或macOS clonefile生成独立inode的写时复制文件，不支持时直接复制；不硬链接，不给算子共享源库。栅格物化时内置掩膜，使每份GeoTIFF完整独立。每次准备首尾重新查询权限、活动状态与版本，运行时及发布前重验完整ACL。
- 缓存仅保留各资源当前副本，按最后使用时间及compute.input_mb对应的总量预算清理；清理不影响独立任务文件。心跳仍及时响应取消，全输入授权检查按阶段边界及运行周期执行，避免每份输入都重复遍历全清单。
- SDK input_evidence提供与任务文件身份绑定的像元/掩膜和权重标识。check/apply/relations升级为1.2.0，prospect升级为2.1.0，原版本保留；独立运行与受信标识路径的科学快照哈希相同。输出metadata.executionMetrics记录准备、运行、结果检查耗时和物化/复用/写时复制计数。
- 核查分页从完整冻结授权集合返回automaticMap，位置标记与人工候选审批分离。前端浅灰绿圆点按44像素邻域聚合，缩放可展开，完整数量保留；超过2000个对象先按16×16地理网格汇聚。该视图只是位置概览，不作为修改边界或像元范围，不新增模型、算子调用。

- 发布前检测到地图视口修复`4de5d49927550b0e40c0a654e07542e693a8ddf8`已并发上线。已按其正式清单校验并本地审查、整合11个源码/测试/说明文件，保留大矢量按视口加载、请求取消和空空间查询不全表扫描的修复；相关后端、前端和浏览器测试由本轮重新执行。并发发布当时仅切换Web，三个worker仍在1a62732；运维控制器按各角色实际目录和PID固定身份，新版本切换后统一到同一集成目录，回滚恢复各自原目录。


## 2026-11-07 正式基线与运行角色统一

统一基线纳入 main 9720254、管线显示 d5576dd 和矢量瓦片 f355ac2 的全部正式改动；找矿候选分支独立保存。Web、compute_worker、agent_worker、workflow_worker 及启动器两个根路径必须指向同一冻结目录；切换前按实际 PID、工作目录和命令固定四角色身份。版本沿用 0.1.67，既有标签、科学算子、审批与科研数据保留。发布过程若检测到并发更新即拒绝切换，重新审查最新基线后再冻结。详见 production-source-baseline-20261107.md 和发布回执。

## 2026-11-09 平台异常响应与账号切换

统一请求边界拒绝JSON接口的HTML成功响应，并核对启动、用户、计算运行环境及常用列表关键结构。SDK延迟加载前后、正文读取后及错误回调前核对登录/项目；账号或同ID授权变化中止旧请求并重挂业务上下文。可选family围栏在服务端阻止错误Cookie身份下执行操作，实际访问仍依赖原有权限检查。跨标签页切换重新读取Cookie用户；取消不冒充必需请求超时，无启用项目不挂载业务页面。

入口脚本按文件身份缓存解析，API返回构建和请求关联号，异常诊断仅保留结构与HTML指纹。公共历史构建由发布阶段一次性归档完整依赖、共享文件去重，当前WhiteNoise优先、历史签名清单回退；正常请求不扫描发布目录或科研文件。刷新由用户操作，焦点与定时更新检查合并在途请求。接口契约与回归见`test_platform_stability.py`、`AccountIsolation.efficiency.browser.test.tsx`及`ResponseBoundary.browser.test.ts`。
