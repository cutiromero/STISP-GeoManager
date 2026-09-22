# 平台修复验收与代码、内容审核清单

> 后续状态：用户已批准 A01–A14，现已完成，详见 [修复验收记录](2026-09-18-a-items-acceptance.md)。本页保留整改前发现与证据；R01–R03 暂缓，R04 保持现状，R05 暂不改内容。

日期：2026-09-18。对象：本机 `GeoManager-main` 当前工作区及 `http://127.0.0.1:5173`。状态：用户指定的三项问题已修复；下列新增发现保留原状，供用户审核后安排整改。

## 一、本轮已完成的三项修复

| 用户反馈 | 原因与修复 | 验证结果 |
| --- | --- | --- |
| 浏览器标签仍显示“生态保护管理” | 后台 `ProLayout` 即使设置 `pageTitleRender=false`，仍使用 `title` 改写文档标题。后台和资源布局现在设置 `title=false`，由平台统一品牌函数维护标题。 | 实际依次进入后台个人资料、存量数据、地理工作台，均为“时空智能服务平台”；中英文布局组件回归通过。 |
| 空间查询可选择未加载数据 | 原候选项来自资源总目录。现在只从图层树中已加载、具有有效来源 ID、允许查询的矢量图层生成候选项，同一来源去重。已加载但隐藏的图层仍可查询；栅格和本地无来源图层不列入矢量查询。 | 真实目录有两份资源，未加载时候选为空；加载一份后只有一个选项；移除最后一个来源图层后清空目标、结果并禁止查询。人为延迟查询响应，再移除目标，旧结果没有回填。 |
| 编辑工程的说明下方提示看不清 | 浅色 Alert 背景与工作台浅色文字冲突。提示框明确使用浅底深字；下方访问说明继承弹窗文字颜色，同时适配深色工作台主题。 | 实际截图复核通过。提示标题与背景对比度约 10.46:1，正文约 8.26:1；深色弹窗下方说明为浅色。 |

修复位置：[后台布局](D:/6-时空智能平台开发/GeoManager-main/frontend/src/admin/AdminLayout.tsx:145)、[资源布局](D:/6-时空智能平台开发/GeoManager-main/frontend/src/resource/ResourceLayout.tsx:130)、[查询候选生成](D:/6-时空智能平台开发/GeoManager-main/frontend/src/utils/spatialQueryTargets.ts:18)、[查询移除与响应清理](D:/6-时空智能平台开发/GeoManager-main/frontend/src/pages/MapPage.tsx:594)、[提示框样式](D:/6-时空智能平台开发/GeoManager-main/frontend/src/styles.css:18708)。

截图：[工程编辑提示](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/edit-project-readable.png)、[已加载查询对象](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/spatial-loaded.png)、[移除图层后](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/spatial-after-remove.png)。[实际页面验收记录](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/ui-report.json)。

本轮没有修改 API 契约、数据库结构、项目权限、业务数据目录或栅格计算链路；没有保存、删除现有工程或修改用户数据。验证使用隔离登录会话，临时图层仅存在于验收浏览器。

## 二、待审核问题总表

共 14 项：P1 为优先整改，涉及恢复能力、成果准确性或授权提示；P2 为下一轮功能与稳定性整改；P3 为维护和体验完善。“静态确认”指代码路径已核对，不表示已在生产数据上制造故障。“容量风险”不表示当前已经出现性能超标。

| 编号 | 优先级 | 发现 | 确认方式 | 建议处理 |
| --- | --- | --- | --- | --- |
| A01 | P1 | 备份遗漏项目科研目录和内容附件等持久文件 | 只读清单实测 | 首先补齐备份范围，再做独立目录恢复演练 |
| A02 | P1 | 制图比例尺距离计算与地图框实际宽度脱节 | 调用实际函数数值复现 | 按实际地图范围、地图框像素尺寸计算比例尺 |
| A03 | P1 | 制图发布仍承诺“仅所选角色可见”，实际已按项目可见 | 前后端静态确认 | 按现行项目标签规则移除误导性可见角色设置 |
| A04 | P2 | 制图导出替换当前底图，且底图最高原始级别固定为 12 | 静态确认 | 保存并传递底图选择，统一预览、导出与清晰度规则 |
| A05 | P2 | 地图图像扩展范围后，格网仍使用扩展前的范围 | 静态确认，待样图验收 | 用同一份实际输出范围绘制图像、格网、比例尺和区位框 |
| A06 | P2 | 地图工程缺少并发覆盖检查 | 静态确认 | 给工程保存增加版本条件及冲突提示 |
| A07 | P2 | 已发布文章的新附件在点击“保存”前就能公开，取消不会撤销上传 | 静态确认 | 附件先暂存，保存时提交；取消清理暂存附件 |
| A08 | P2 | 科普/新闻快速切换筛选时，旧响应能覆盖新结果 | 隔离浏览器延迟响应复现 | 加请求代次校验或取消旧请求 |
| A09 | P2 | 部分非法输入变为未捕获异常，不能稳定返回标准 400 | 无落库函数调用复现 | 统一 JSON 根类型、UTF-8 和日期校验 |
| A10 | P2 | 在线帮助和下载手册仍讲旧首页、胡杨科普、四类数据及角色共享 | 当前页面引用链静态确认 | 按现行导航、两类数据与项目标签规则重写帮助 |
| A11 | P2 | OpenAPI 与开发说明保留过期权限语义、分类示例 | 静态确认 | 统一契约文字与示例，明确历史决策已被替代 |
| A12 | P2 | 工程列表一次返回全部工程及完整快照 | 容量风险，静态确认 | 列表分页、只返回摘要，打开工程时读取快照 |
| A13 | P3 | 新增科普、新闻及项目界面没有完整接入语言切换 | 静态确认 | 补充界面词典，保留用户正文原文 |
| A14 | P3 | 全库格式检查仍失败，检查还纳入了浏览器录制产物 | 实际命令复现 | 排除非源码产物，再独立整理历史源码格式 |

## 三、问题依据、影响与验收建议

### A01：备份未覆盖项目化后的持久文件

- 依据：[备份来源枚举](D:/6-时空智能平台开发/GeoManager-main/backend/apps/core/backup_service.py:387)只枚举旧科研根下的 `vector/raster/gene/table`；平台备份仅枚举 `database/media/uploads/config`，可选 `logs`。[项目文件路径](D:/6-时空智能平台开发/GeoManager-main/backend/apps/core/storage.py:16)已将非公开科研文件放在 `research/projects/{id}/…`，[内容附件](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/views.py:233)放在业务根 `projects/{id}/content/…`，均未被前述固定根完整覆盖。正式成果文件位于 `exports/…`，也应从缓存中区分出来纳入持久备份。
- 实测：按没有请求上下文的后台任务环境枚举来源，当前私有科研文件 **2 个，纳入 0 个**；内容附件 **22 个，纳入 0 个**。没有执行新的备份，也没有修改或恢复数据库。[只读证据](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/read-only-probes.json)。
- 影响：备份任务即使显示成功，恢复数据库后仍可能找不到私有矢量数据、新闻照片、PDF 和正式成果。后台线程未显式携带项目上下文，也不应让全平台备份的范围取决于当前浏览项目。
- 建议：定义全平台持久文件清单，显式包含所有项目目录、内容附件和正式成果；临时导出、瓦片缓存单独排除。数据库和文件清单记录同一备份批次及校验值。
- 验收：至少覆盖公开与两个私有项目，恢复到独立目录，核对资源查询、文章图片/PDF、工程及正式成果可用；不能只验压缩包能打开。

### A02：比例尺会标错距离

- 依据：[比例尺函数](D:/6-时空智能平台开发/GeoManager-main/frontend/src/map-composition/canvasScale.ts:11)使用比例尺自己的 `box.width` 计算米/像素，再乘回该宽度并固定除以 4；[调用方](D:/6-时空智能平台开发/GeoManager-main/frontend/src/map-composition/render.ts:170)没有传入主地图框像素宽度。
- 复现：赤道附近、地图经度跨度 4°、地图框宽 1000px，比例尺框宽 100px 时，画出约 89.83px 的标尺并标注“100 千米”，该线段按地图实际尺度只对应约 **40 千米**。将比例尺框改为 200px，仍标“100 千米”，实际对应约 **80 千米**。[数值证据](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/map-scale-probe.json)。
- 影响：版式看起来正常，距离表达却不可靠，不宜据此作为正式科研图的距离参照。
- 建议与验收：从输出地图实际可见范围及像素尺寸计算中心纬度附近比例；同时验证拖动、缩放、A4/A3、横竖版与 150/300 DPI，长度与标注必须对应。

### A03：旧“可见角色”承诺与实际项目授权冲突

- 依据：[发布提示与必填角色](D:/6-时空智能平台开发/GeoManager-main/frontend/src/components/map-composition/MapCompositionPanel.tsx:372)仍声明“只有所选角色…可以访问”，恢复工程也保留“工程额外可见角色”。服务端[发布操作](D:/6-时空智能平台开发/GeoManager-main/backend/apps/catalog/map_compositions.py:248)仍要求并保存角色，但[成果可见查询](D:/6-时空智能平台开发/GeoManager-main/backend/apps/catalog/map_compositions.py:564)依据项目和发布状态，没有按这些角色缩小可见范围。
- 触发：在一个多人、多角色项目内发布，界面只选择科研角色；其他符合当前项目访问规则的用户仍可能看到已发布成果。**未发现由此跨越项目成员边界；问题是界面承诺了不存在的项目内部限制。**
- 建议：遵循用户已经确定的项目标签规则，删除或标明废弃的可见角色项；查看、下载、编辑等功能权限继续分别校验，不能用旧角色字段绕过项目成员关系。
- 验收：同项目两种角色、不同项目、公开项目匿名用户分别验证实际可见性，表单提示与结果一致。

### A04：导出底图与用户选择不一致

- 依据：[createExportStyle](D:/6-时空智能平台开发/GeoManager-main/frontend/src/map/mapExport.ts:309)删除外部底图来源，统一换为平台缩略图瓦片代理，固定 `maxzoom=12`；[代理选源](D:/6-时空智能平台开发/GeoManager-main/backend/apps/core/map_thumbnail.py:77)依据服务器默认配置，Mapbox 样式固定为 satellite-streets。
- 触发与影响：工作台选择 OSM、天地图或其他可用底图后，制图和导出仍可能使用服务器默认 Mapbox 底图；局部高分辨率输出只是放大 z12 底图。上一轮修复了“失败时返回假底图”，没有解决“保留当前底图选择”。
- 建议：把底图提供者、样式和允许层级作为工程/出图配置传到受控代理；实测各底图主图、鹰眼和导出是否一致，并沿用当前输出格式规范。

### A05：输出图像和格网的实际范围可能不同

- 依据：[出图范围计算](D:/6-时空智能平台开发/GeoManager-main/frontend/src/map/mapExport.ts:144)为满足页面宽高比扩展像素范围；[图像生成](D:/6-时空智能平台开发/GeoManager-main/frontend/src/map-composition/mapImage.ts:7)只返回图像，没有返回扩展后的实际地理范围；[格网绘制](D:/6-时空智能平台开发/GeoManager-main/frontend/src/map-composition/render.ts:118)继续使用原始 `layout.mapFrame.bounds`。
- 触发与影响：长条研究区装入接近方形的地图框、切换横竖版等情况下，底图范围已扩展，而坐标标注仍按原范围铺满地图框，地物与坐标刻度可能不对应。这是范围传递问题，不能仅靠调整格网间隔修复。
- 建议：统一生成地图渲染计划，返回实际范围，让主图、格网、比例尺与区位图共用；用已知经纬度控制点核对像素落点。此项已确认代码路径，尚未做独立 GIS 样图对照。

### A06：工程保存存在后写覆盖先写的风险

- 依据：[工程更新](D:/6-时空智能平台开发/GeoManager-main/backend/apps/catalog/views.py:577)直接赋值并 `scene.save()`，没有比较客户端看到的版本；制图草稿已实现 `expectedUpdatedAt`，普通地图工程尚未同步。
- 触发与影响：同一账号两个标签页或工程所有者与有权管理员同时编辑，第二次保存可覆盖第一次保存的名称、说明或快照，没有冲突提示。
- 建议：为工程编辑/覆盖保存提供条件版本，冲突返回 409 并保留当前未保存内容。用两个客户端读同一版本、交错保存验证。

### A07：已发布内容的附件上传绕过最终保存

- 依据：[附件上传](D:/6-时空智能平台开发/GeoManager-main/frontend/src/pages/EditorialPage.tsx:477)立即调用接口；[取消编辑](D:/6-时空智能平台开发/GeoManager-main/frontend/src/pages/EditorialPage.tsx:411)只关闭弹窗。服务端[上传](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/views.py:253)立即建立正式附件，[内容序列化](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/views.py:44)返回全部附件，[附件访问](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/views.py:270)仅看文章发布状态。
- 触发与影响：编辑已发布新闻/科普，上传图片后尚未保存甚至点击取消，新附件仍会出现在公开内容中；附件说明、正文和附件不是一次提交。文章 revision 也没有覆盖这个上传动作。
- 建议：引入未提交附件或内容修订；保存后一起发布。若产品确实希望上传即公开，应明确提示并提供撤回能力，但与现有“保存内容后生效”体验不一致。

### A08：内容筛选存在旧响应覆盖

- 依据：[EditorialPage.load](D:/6-时空智能平台开发/GeoManager-main/frontend/src/pages/EditorialPage.tsx:68)每次筛选后直接回写列表、总数和加载状态，没有请求代次或清理逻辑。
- 复现：隔离匿名浏览器内先请求“遥感基础”，延迟其 GET 响应，再点击“GIS 与地图制图”；后者先正确显示，前者迟到后覆盖列表，选中按钮仍为 GIS。全部响应仅在浏览器内模拟，未写服务器内容。[复现记录](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/editorial-race-probe.json)。
- 建议：仅最新查询能回写列表和 loading/error 状态；分页、搜索、管理视图一并覆盖。

### A09：非法输入未统一处理

- 依据：[登录入口](D:/6-时空智能平台开发/GeoManager-main/backend/apps/core/auth_views.py:48)解析 JSON 后未检查根类型就调用 `.get`；[内容日期解析](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/views.py:190)没有捕获合法日期格式但不存在的日历日期异常。
- 复现：直接调用实际函数，登录请求体 `[]` 产生 `AttributeError`；`eventDate="2026-02-30"` 产生 `ValueError`。这些异常不属于现有项目中间件处理的 `ValidationError`，会走未处理异常路径。[证据](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/read-only-probes.json)。
- 建议：根对象、字段类型和日期错误均返回标准 JSON 400；同时覆盖注册及类似旧入口。本轮没有调用真实登录尝试，也没有向已发布文章提交非法日期。

### A10：用户帮助内容已经落后于系统

- 依据：[当前 AboutV2Page 复用旧 DocsSection](D:/6-时空智能平台开发/GeoManager-main/frontend/src/pages/AboutV2Page.tsx:28)，因此不是单纯的未使用旧文件。[平台导览](D:/6-时空智能平台开发/GeoManager-main/frontend/src/about/aboutSections.ts:1042)仍介绍首页、四大分类、胡杨科普、四家单位；[权限帮助](D:/6-时空智能平台开发/GeoManager-main/frontend/src/about/aboutSections.ts:1393)仍要求按可见用户组共享。下载入口仍使用旧平台名称和 2026-07-23 版说明。
- 影响：用户按帮助操作会找不到入口，并误解公开项目、标签分配与数据共享。历史胡杨科研资料本身可以保留，错误操作指南必须更新，不能简单全库替换“胡杨”。
- 建议：优先重写快速入门、项目授权、数据上传、空间查询、工程/成果发布；同步中英文在线帮助和离线 PDF。

### A11：技术文档与接口示例没有同步到最终规则

- 依据：[创建工程契约](D:/6-时空智能平台开发/GeoManager-main/docs/openapi.yaml:2898)仍称 `accessGroupIds` 配置额外可见角色；[上传示例](D:/6-时空智能平台开发/GeoManager-main/docs/openapi.yaml:3245)仍使用 `thematic_community` 等已退出当前主分类口径的代码；[设计文档](D:/6-时空智能平台开发/GeoManager-main/docs/design-docs.md:1052)同时残留“支持只读 all”“新闻保留项目隔离”等过期决定，后文才追加新规则。AGENTS 还指向旧的 `schema.d.ts`，实际生成目录已为 `src/api/generated/`。
- 影响：类型生成和 OpenAPI 语法校验仍可通过，却无法发现权限语义和示例错误，后续维护容易重新实现已废弃行为。
- 建议：设一个“当前有效规则”入口，历史内容明确标记被替代；逐接口更新描述、示例、Mock 和开发指南，随后重新生成并验证类型。本轮未改契约，避免把待审整改混入三项界面修复。

### A12：工程列表容量风险

- 依据：[工程列表](D:/6-时空智能平台开发/GeoManager-main/backend/apps/catalog/views.py:508)没有分页，逐项调用[完整序列化](D:/6-时空智能平台开发/GeoManager-main/backend/apps/catalog/views.py:733)返回 `snapshot`；前端[工程刷新](D:/6-时空智能平台开发/GeoManager-main/frontend/src/hooks/useWorkspaceScenes.ts:92)还绑定窗口获得焦点等事件。
- 影响：工程数和快照变大后，进入工作台、窗口切换会反复传输完整快照，增加响应时间和内存占用。当前仅两个工程，**本次没有测得现有数据量下的性能故障**。
- 建议：摘要列表分页，详情按需读取，刷新合并与缓存失效；在预定工程数、图层数下测响应体大小与延迟。

### A13：新增模块语言切换不完整

- 依据：[科普/新闻页面](D:/6-时空智能平台开发/GeoManager-main/frontend/src/pages/EditorialPage.tsx:39)、[项目提示](D:/6-时空智能平台开发/GeoManager-main/frontend/src/projects/ProjectLabel.tsx:14)含大量直接中文；工程访问说明的英文仍描述旧所有者/系统可见规则。
- 影响：切换英文后导航变化，内容管理按钮和授权提示仍为中文或旧语义。`i18n:check` 仅检查已有词典键，不能发现没有接入词典的硬编码。
- 建议：翻译界面与说明，用户上传标题、正文、姓名、文件名继续保持原文。

### A14：全库格式检查未能作为可靠验收关卡

- 证据：`pnpm run check` 仍报告 **171 个文件格式问题**，其中大量为 `.playwright-cli` 录制文件，也有既有源码、配置和脚本。[完整日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-check.log)。后端 `ruff check apps` 通过，本轮相关前端文件定向 lint/format 通过。
- 建议：为录制、输出、缓存目录配置忽略；历史源码整理单独提交，恢复可以稳定通过的仓库检查。不要把 171 个格式问题解读为 171 个业务故障。

## 四、需要确认的产品规则与上线条件

这些事项不计入前面的 14 项确定问题/容量风险，也没有在本轮擅自更改。

| 编号 | 事项 | 当前状态与建议 |
| --- | --- | --- |
| R01 | 正式部署的 HTTPS 和 Cookie 策略 | 对本机开发配置执行 `check --deploy` 得到 5 项警告：DEBUG、HTTPS 跳转、HSTS、Session/CSRF Secure Cookie。开发机使用 HTTP 可以理解；公网发布前应验证真实反向代理配置并补齐安全 Cookie。没有审查远程生产主机，不能据此断言线上存在同样问题。 |
| R02 | 登录尝试频率控制 | 本仓库登录函数、中间件及已检查配置未发现失败限速/锁定；可能由外部网关实现，尚未核实。公网使用前明确由哪层限制密码尝试；不要只记录失败日志。 |
| R03 | 内容维护是否需要独立角色 | `content/views.py:26` 将内容编辑绑定超管或 `core.manage_auth`。如果后续让专职编辑维护新闻，现状会把编辑职责与账号管理耦合。建议单独内容权限；是否设审核人/发布人由您决定。 |
| R04 | 查询“已加载图层”时是否保留原属性筛选 | 当前 `MapPage.resolveSpatialQueryContext` 使用空 `attributeFilters`，从图层源重新做空间查询；原提示也说明按来源重查。本轮只限制可选对象，不擅自改查询语义。建议确认是否应在当前加载的筛选子集内查询，避免用户以为只能查询地图上现有要素。 |
| R05 | 内容发布与演示内容保留策略 | 现有 12 篇知识文章以六方向组织，课件仅作图片/来源，符合您的要求；1 篇新闻与 22 个附件保留。学习入口 24 条、不同 URL 23 个，22 个返回 200，USGS Landsat 返回 403，属于待人工复核的访问限制，不能直接判为死链。非地理分析仍有明确标注的胡杨演示数据：可决定保留在独立“示例”入口或默认不显示。专业内容审校人、插图上下文和长期链接维护责任尚需确定。 |

内容检查依据：[知识种子](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/seed_knowledge.py)、[素材来源和新闻整理](D:/6-时空智能平台开发/GeoManager-main/backend/apps/content/management/commands/seed_editorial.py)、[实际链接检查](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/content-link-check.json)。本轮没有发现应将课程目录直接作为科普主线的理由，也没有把历史科研样本名称误判为必须删除的旧文案。

## 五、审查覆盖和验证证据

覆盖：前端路由与品牌、认证/退出、项目上下文、数据与工程访问、上传落库/目录、文件下载、快照引用、栅格后台任务及撤权检查、制图保存/发布/渲染、备份、公共内容与附件、帮助文案、接口契约、测试与构建配置。采用关键调用链阅读、自动化回归、实际浏览器和只读数据核验；不等同于对每行代码作正确性证明。

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 后端完整 `pytest -q` | 659 通过，52 子测试通过；1 个 GDAL_DATA 检测警告 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-backend.log) |
| 前端 `pnpm test` | 44 文件、399 项通过 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-frontend-unit.log) |
| 前端完整浏览器测试 | 23 文件、172 项通过；有一条既有 Form 未绑定提示 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-browser-full.log) |
| 提示框最终样式调整后的定向浏览器回归 | 3 项通过 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-modal-final.log) |
| `pnpm run build:verify` | 品牌、词典、API 类型一致性、TypeScript、生产构建通过；OpenAPI 有 6 个未使用组件警告 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-build.log) |
| 后端 `ruff check apps` | 通过 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-backend-lint.log) |
| `makemigrations --check --dry-run` | 无缺失模型迁移 | [日志](D:/6-时空智能平台开发/GeoManager-main/output/platform-audit-migrations.log) |
| 全库 `pnpm run check` | 未通过：171 个历史格式问题 | A14 |
| 真实浏览器验收 | 三项修复、移除图层、延迟响应防回填通过；无页面异常 | [记录](D:/6-时空智能平台开发/GeoManager-main/output/20260918-platform-audit/ui-report.json) |

浏览器组件测试使用现有 ASCII 临时目录副本，依赖仍指向本仓库；避免 Windows 中文目录下 Vitest 浏览器路径解析问题。没有更换运行中的后端、重置数据库或远程部署。当前实际地图已加载 Mapbox 瓦片；外部网络、代理及服务商可用性仍是运行条件。

未覆盖：远程生产主机、独立恢复演练、并发压力/长时间运行、所有设备和浏览器、全部原始课件逐页专业审校、第三方依赖漏洞数据库扫描。因此“回归通过”不能替代 A01 恢复验收或 A02/A05 制图精度验收。

## 六、建议审核顺序

1. 优先批准 A01–A03：补全备份、修比例尺、清理误导性授权设置；其中备份应先完成再进行下一批数据结构调整。
2. 合并处理 A04–A09、A12：底图与输出范围、工程冲突、内容提交事务、异步响应和输入校验，并补对应回归。
3. 同步处理 A10、A11、A13、A14：更新用户帮助、API/开发文档、界面语言及检查基线。避免界面改完，帮助又教回旧规则。

审核时可按编号选择“批准 / 暂缓 / 调整方案”。本文件中的待审问题没有自动实施。
