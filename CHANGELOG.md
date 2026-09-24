# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.17] - 2026-09-24

- 新闻改写为会议概况、参会单位与李茂林汇报，规范图注和附件名称，新闻页不再展示内部来源说明。
- 平台及智能体导航图标恢复上一版，删除黄思圻研究方向末尾句号。
- 栅格详情增加灰度、伪彩色、RGB及四种配色，支持波段、不透明度、拉伸和NoData调整，应用后调用已有后端渲染。

## [0.1.16] - 2026-09-24

- 模型对话和数据智能体支持用户调整深度思考强度，保留后台默认值与总开关。
- 移除本地模型提示；发送问题后定位最新提问。
- 使用新栏目图标和成果背景，补齐三位成员与照片，更新张依涵邮箱。
- 发布时清理指定人工验收项目，保留其中的用户对话和审计记录。

## [0.1.15] - 2026-09-24

- 新增普通分析、长材料、长推理任务预算和自定义生成预留；显示服务窗口、用户可用窗口、输入预算及实际调用用量。
- 后台配置方案默认值和普通用户/超级管理员额度，服务端强制鉴权并保存每次任务参数快照。
- 支持262144-token模型窗口，扩大长文本、附件提取和流式响应保护范围；保留取消、超时及权限撤销检查。
- 新增预算传参、越权、幂等、快照及长输入回归测试。

## [0.1.14] - 2026-09-23

- 修复数据智能体在深度模式下把直接返回的JSON命令误记为思考、导致工具协议失败的问题。
- 每轮明确传入当前选择的资源ID和当前问题，历史选择独立标记；上传附件保留当前资源范围，协议纠正包含实际错误响应。
- 增加结构化深度响应、分片思考标记、历史资源切换和真实HTTP多步工具回归测试。

## [0.1.13] - 2026-09-23

- 修复深度思考遇到生成上限时缓存丢失；保留思考与正文，明确显示截断原因。
- 增加输入 token 预算和思考强度；通过模型分词接口检查完整请求，显示实际服务窗口、本轮参数与生成用量；生成上限允许配置至32768。
- 工具列表按当前策略过滤，权限错误保留具体原因；工作流入口明确为算法计划预览，预留迭代参数不再作为有效控制展示。
- 新增 NDWI 水体指数与矢量面积周长算法模板，算法目录按分类排序值、分类名、算法名及ID稳定排列。

## [0.1.12] - 2026-09-22

- 采用用户选定的“轨道地球”STISP 图标，统一登录页、工作台导航及浏览器标签图标；保留旧素材和三个设计方案供追溯。
- 图标使用原生 SVG，提供蓝绿彩色和深色背景白色版本；不变更 API、权限、数据路径或业务逻辑。

## [0.1.11] - 2026-09-22

- 智能体接入受策略控制的系统参数、已发布计算算法、算子提交、计算结果入库和受限公网检索，并保留项目权限、审计和计算中心隔离边界。
- 支持当前会话上传 PDF、DOCX、TXT、Markdown、CSV 及 PNG/JPEG/WebP；文档提取文本，已实测 Qwen3.8-27B 视觉输入后支持图片分析。
- 修正 32768 token 模型的上下文裁剪，管理员可调整预算、输出、采样、步骤、附件和运行参数，长历史/附件会保留当前问题并有界截断。
- 深度思考兼容 Qwen vLLM 实际返回的 `content` 思考前缀与 `</think>`，生成时持续展开、完成后折叠并显示耗时，历史记录可恢复真实思考事件。

## [0.1.10] - 2026-09-21

- 智能体管理新增模型上下文窗口、上下文字节预算、输出 token、Temperature、Top P、协议重试和单次运行时限设置；默认上下文预算从硬编码的小文件限制提升为按模型窗口计算的可配置预算。
- Qwen 模型支持快速回答与深度思考切换；深度思考事件以可折叠面板实时显示，非 Qwen 模型和管理员关闭策略时自动禁用。
- 运行记录持久化思考模式，兼容 Qwen 的 `reasoning_content`、`reasoning`、`thinking` 和 `<think>` 流式响应，并同步 OpenAPI、生成类型、迁移和测试。

## [0.1.7] - 2026-09-21

- 后台服务器信息支持 NVIDIA 单卡/多卡显存与利用率监控；后台下拉菜单补齐算法与计算管理入口。
- 上传数据默认对项目组成员可见，并可在数据资源管理中切换为仅上传者和超级管理员可见，目录、查询、图层、导出和数据智能体统一执行权限过滤。
- 智能体会话切换后恢复历史消息，工具步骤上限提升至 64，并兼容 Qwen 常见的扁平化 JSON 工具参数响应。

## [0.1.8] - 2026-09-21

- 登录背景改为静态图片淡入切换，取消平移和缩放动画。
- 后台服务器 GPU 型号按“型号 × 数量”整齐展示，补齐后台“智能体管理”入口。
- 计算中心改为先选择算法版本再执行，算法卡片采用紧凑网格布局。

## [0.1.9] - 2026-09-21

- 新增可恢复、可审计的科研工作流基线：持久化工作流、步骤、检查点，支持创建、查看和取消。
- 工作流默认只生成计划，不自动提交算子；算子执行仍受现有计算中心、权限和策略开关约束。
- 增加独立工作流 worker、排队取消收口、重启恢复和 `waiting_compute` 幂等保护，并同步 OpenAPI、前端面板和测试。
- 当前版本仍未接入真实岩矿算法、成矿理论规则库和完整迭代评估，先提供安全可部署的工作流骨架。

## [0.1.6] - 2026-09-20

- 将原“智能预警”入口改为“智能体”，提供本地模型对话、当前项目授权数据的受控只读分析、增量任务、取消、证据展示及超级管理员可见范围策略。
- 新增独立 agent worker、模型注册、会话与运行事件持久化、幂等提交、权限撤回复核和本地 Mock 模型；栅格元数据纳入只读依据，算子、代码执行、写入与发布能力保持关闭并预留扩展接口。

## [0.1.5] - 2026-09-20

- 计算工作进程心跳改为单次写入，避免 SQLite 并发事务升级冲突；遇到短暂锁竞争时按队列间隔恢复检查，防止进程退出后试运行持续不可用。
- 包含 0.1.4 的 HTTP UUID 兼容修复。

## [0.1.4] - 2026-09-20

- 兼容通过 HTTP 访问且不提供 `crypto.randomUUID` 的浏览器，修复算法试运行和专题文字操作触发前端崩溃的问题。
- 前端异常不再因 UUID API 缺失而阻断计算中心侧栏、后退和其他路由导航。

## [0.1.3] - 2026-09-20

- 将 AutoDL 计算中心切换为可配置的本机 Python 子进程执行，不再要求服务器具备 Docker 权限。
- 保留算法包校验、任务队列、超时、资源软限制、取消/恢复和结果格式检查；运行环境摘要绑定到算法版本。
- 补充服务器本机进程部署说明和运行环境验收记录。

## [0.1.2] - 2026-09-20

- 明确项目编码创建后不可修改，补充编辑页提示。
- 修正算法管理页在运行环境未就绪或权限尚未加载时的状态显示，补充删除操作反馈。
- 删除没有任务历史的算法时在事务提交后清理版本包；有任务历史的算法继续要求归档停用。
- 记录计算环境部署阻塞：服务器 Docker 需要受限 daemon 参数运行，待镜像加载与 worker 验收完成。

## [0.1.1] - 2026-09-20

- 修复算法管理删除登记：没有任务历史的算法可安全删除版本包，已有任务历史的算法必须归档停用。
- 运行环境不可用时继续明确禁用试运行；补充算法删除接口、契约和前端管理操作。

### Added
- Added and locally deployed a general compute center with administrator-managed algorithm packages and immutable versions, manifest-generated forms, project-scoped durable jobs, result downloads and imports, and a Linux-only isolated executor. Four example algorithms passed real container, deployed-worker and browser acceptance; see docs/2026-09-19-compute-deployment.md.
- Added multi-project memberships, administrator assignment, superadmin tag management and a built-in public default project, with scoped business models, media and background jobs
- Added knowledge articles organized by six subject areas, course-sourced illustrations, learning links and a team news editorial module with revision protection
- Added interactive composition dragging/resizing, selection, snapping, alignment/distribution, locks, layer order, extra text, undo/redo and conflict-aware autosave
- Made the geographic workbench the default entry and the data catalog the second module; removed the homepage route
- Added role-scoped thematic publishing with immutable published versions, audience groups, object-level capabilities and restore-to-project workflow
- Added workspace snapshots, resource manifests and SHA-256 checksums to thematic output versions for reproducible project restoration
- Added project-to-thematic-map composition workflow with persisted layouts, immutable versions, PNG/JPG/PDF artifacts, preview, publish and archive actions
- Added A4/A3 layouts, overview maps, geographic/Web Mercator grids, automatic legends, north arrows, scale bars, data sources and cartographic notes
- Version management system with bump scripts for frontend and backend
- Makefile for unified version management commands
- CHANGELOG.md to track project changes

### Fixed

- Retrieve live container tmpfs results through a bounded tar stream, include Rasterio's libexpat dependency, and close SQLite inspection connections before archiving results on Windows.

- Pass GDAL/PROJ and temporary paths as Unicode GDAL CLI configuration on Windows so raster imports work under Chinese data directories.

- Completed approved audit items A01–A14: full-project backups, cartographic scale/extent and basemap persistence, project-based sharing prompts, workspace conflict protection and paged summaries, staged editorial attachments, stale-response and input validation fixes, bilingual help and documentation, and formatting checks. See docs/2026-09-18-a-items-acceptance.md for verification and deferred R items.
- Wait for source map styles and refresh composition previews after delayed style loading; preserve strict failures when export tiles are unavailable.
- Preserve the platform browser title across administration and resource layouts instead of allowing ProLayout to overwrite it
- Restrict spatial query targets to loaded queryable vector layers, clear removed targets and ignore stale responses after layer removal
- Restore readable project notices and access guidance in the workspace project editor

- Require real basemap imagery for composition previews and exports; return a retryable error instead of silently rendering thumbnail fallback polygons when upstream tiles are unavailable
- Move project management into the administration navigation, remove aggregate project selection, rename the built-in project to “公开”, and make published team news and its media available across all projects and to anonymous readers
- Require an explicit authorized project tag for data/result uploads, keep preflight and async jobs in the selected destination, and expose inventory project columns and filtering
- Classify raster uploads as geographic data instead of submitting retired thematic category codes
- Route thematic map basemaps through the platform tile proxy/cache, wait for complete tiles, retry transient failures and cancel stale auto-preview renders instead of exporting partial black maps
- Unified thematic inventory around `MapComposition`; removed the duplicate legacy `WorkspaceScene(topic)` creation and display flow
- Kept draft and unpublished thematic maps private to their owners, platform administrators and super administrators
- Preserve unsaved map-composition edits when the live map view or source summary changes
- Recommend usable geographic and Web Mercator grid intervals for both local and regional extents

## [0.1.0] - 2026-05-28

### Added
- Initial project setup with frontend (React + Vite + Ant Design + Mapbox GL JS) and backend (Python + Django)
- Unified feature permissions system
- Layer export functionality
- Workspace panel layout for map interface
- User authentication and authorization system
- Data management capabilities
- Raster data processing and visualization
- Vector data display with GeoPackage support
- Configuration management via TOML files
- Docker deployment support

### Changed
- Refactored codebase for better organization
- Renamed files and directories for consistency
- Adjusted workspace panel layout for improved user experience
- Formatted code according to project standards

### Fixed
- UI fixes for better visual consistency
- Resolved issues with raster image loading
- Fixed various bugs and minor issues

### Removed
- Removed full raster image loading for performance optimization
