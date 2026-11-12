# 智能体代码地图

所有路径相对仓库根目录；先用 `rg -n` 定位符号，再读取命中附近片段。默认最小检查为根目录 `make verify-fast`；只看计划或附加浏览器分别使用脚本 `--list` / `--browser`。

下列后端命令中的 `$PY` 先在仓库根目录设置；浏览器命令在 `frontend` 执行，路径有中文时也只能使用既有 runner。
```sh
export PY=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python
```

## 业务流
- 新流程搭建标准：`docs/business-flow-development-standard.md`；主执行、校验与上下文排查：`docs/business-flow-audit-20261112.md`；传输与预算排查：`docs/business-flow-boundary-budget-audit-20261113.md`。新流程以同一主执行者贯穿任务，节点不是独立执行智能体。
- 节点工具合同与循环：`backend/apps/business_flows/node_contracts.py`、`node_loop.py`、`node_recovery.py`；模型协议 `backend/apps/agent/business_flow_actions.py`；前端恢复 `frontend/src/businessflows/BusinessFlowNodeRecovery.tsx`。示范 `examples/business-flows/adaptive-statistics.json`；专项 `backend/tests/integration/test_business_flow_node_tools.py`、`backend/tests/unit/test_business_flow_tool_protocol.py`、`frontend/src/businessflows/BusinessFlowNodeRecovery.efficiency.browser.test.tsx`。行为见 `docs/business-flows.md` 的“节点合同与有限工具循环”“失败自恢复与等待”。
- 后端入口：`backend/apps/business_flows/views.py`、`catalog.py`、`definitions.py`、`runtime.py`、`engine.py`；输入：同目录 `input_preparation.py`、`input_adapters.py`、`node_inputs.py`；专业衔接：`legacy.py`。
- 前端入口：`frontend/src/businessflows/BusinessFlowsPage.tsx`；样式与状态在 `frontend/src/businessflows/`。
- 测试：`backend/tests/integration/test_business_flow_catalog.py`、`backend/tests/integration/test_business_flow_runtime.py`、`backend/tests/unit/test_input_adapters.py`；浏览器 `frontend/src/businessflows/BusinessFlows.efficiency.browser.test.tsx`、`BusinessFlowInputPreparation.efficiency.browser.test.tsx`。
- 最小：`make verify-fast`；定点后端：`cd backend && "$PY" -m pytest tests/integration/test_business_flow_catalog.py -q`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/businessflows/BusinessFlows.efficiency.browser.test.tsx`。

## 智能体与逻辑推理
- 后端入口：`backend/apps/agent/views.py`、`worker.py`、`workflow.py`、`workflow_worker.py`、`geology_review.py`；事件读取 `run_activity.py`、`run_stream.py`，来源核对 `context.py`；独立审核 `business_flow_review.py`。
- 前端入口：`frontend/src/agent/AgentPage.tsx`、`LogicTaskWorkspace.tsx`；客户端 `frontend/src/api/client.ts`。
- 测试：`backend/tests/integration/test_agent.py`、`test_agent_stream_efficiency.py`、`test_logic_reasoning_journey.py`、`test_business_flow_review.py`；浏览器 `frontend/src/agent/AgentPage.browser.test.tsx`、`LogicTaskWorkspace.browser.test.tsx`。
- 最小：`make verify-fast`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/agent/AgentPage.browser.test.tsx src/agent/LogicTaskWorkspace.browser.test.tsx`；读取/历史/流行为另跑 `make check-efficiency`。

## 数据目录与非地理表格
- 后端入口：`backend/apps/catalog/views.py`、`data_query.py`、`display_geometry.py`、`vector_tiles.py`、`nongeo.py`、`importer.py`、`sharing.py`。
- 前端入口：`frontend/src/pages/DataCatalogPage.tsx`、`NonGeoPage.tsx`、`frontend/src/components/DataPanel.tsx`。
- 测试：`backend/tests/unit/catalog/test_data_query.py`、`test_display_geometry.py`、`backend/tests/integration/catalog/test_api.py`、`test_nongeographic_analysis.py`；浏览器 `frontend/src/pages/DataCatalogPage.browser.test.tsx`、`NonGeoPage.browser.test.tsx`、`frontend/src/components/DataPanel.browser.test.tsx`。
- 最小：`make verify-fast`；定点：`cd backend && "$PY" -m pytest tests/unit/catalog/test_data_query.py -q`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/pages/DataCatalogPage.browser.test.tsx src/components/DataPanel.browser.test.tsx`。

## 栅格
- 后端入口：`backend/apps/raster/views.py`；渲染、CLI、缓存：`backend/apps/raster/services/renderer.py`、`gdal_ops.py`、`tile_singleflight.py`、`rules_engine.py`。
- 前端入口：`frontend/src/components/RasterRenderingControls.tsx`、`SymbolizationEditor.tsx`，只配置参数并加载后端图像。
- 测试：`backend/tests/unit/raster/test_renderer_cache.py`、`test_gdal_ops.py`、`test_rules_engine.py`、`backend/tests/integration/raster/test_api.py`；浏览器 `frontend/src/components/RasterRenderingControls.browser.test.tsx`、`SymbolizationEditor.browser.test.tsx`。
- 最小：`make verify-fast`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/components/RasterRenderingControls.browser.test.tsx`；渲染读取、摘要、缓存行为另跑 `make check-efficiency`。

## 计算中心与输入版本
- 后端入口：`backend/apps/compute/views.py`、`services.py`、`worker.py`、`packages.py`、`input_versions.py`、`result_reads.py`、`quality.py`。
- 前端入口：`frontend/src/compute/ComputePage.tsx`、`frontend/src/compute/compute.css`；地图预览在 `frontend/src/map/`，查 `ComputeOutputMapPreview`。
- 测试：`backend/tests/integration/test_compute.py`、`test_compute_input_versions.py`、`backend/tests/unit/test_result_reads_efficiency.py`；浏览器 `frontend/src/compute/ComputePage.browser.test.tsx`、`frontend/src/map/ComputeOutputMapPreview.browser.test.tsx`。
- 最小：`make verify-fast`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/compute/ComputePage.browser.test.tsx`；版本准备与结果读取另跑 `make check-efficiency`。

## 核心、权限与项目
- 通用项目功能：`backend/apps/projects/features.py`、`models.py`、管理命令 `project_feature`；前端 `ProjectManagementPage.tsx`、`monitor/project.ts`；回归 `backend/tests/integration/test_project_features.py`、`frontend/src/monitor/projectFeatures.test.tsx`、`frontend/src/projects/ProjectFeatures.browser.test.tsx`；开启与扩展见 `docs/ecology-monitor.md`。
- 后端入口：`backend/apps/core/permissions.py`、`auth_views.py`、`account_access.py`、`browser_sessions.py`、`config.py`；项目范围 `backend/apps/projects/access.py`、`context.py`、`scoping.py`；共享摘要 `backend/apps/core/file_evidence.py`。
- 前端入口：`frontend/src/auth/`、`frontend/src/projects/ProjectContext.tsx`、`frontend/src/api/client.ts`、`frontend/src/App.tsx`。
- 测试：`backend/tests/integration/core/test_permissions.py`、`test_account_access.py`、`test_browser_sessions.py`、`backend/tests/integration/test_project_public_policy.py`；浏览器 `frontend/src/api/AccountIsolation.efficiency.browser.test.tsx`、`frontend/src/projects/ProjectContext.browser.test.tsx`。
- 最小：`make verify-fast`；权限定点：`cd backend && "$PY" -m pytest tests/integration/core/test_permissions.py -q`；账号隔离：`cd frontend && node scripts/run-browser-check.mjs src/api/AccountIsolation.efficiency.browser.test.tsx`。权限变更按大改动执行完整门禁。

## 后台管理
- 后端入口：`backend/apps/core/admin_api.py`、`backup_service.py`、`principal_visibility.py`；日志 `backend/apps/audit/service.py`、`events.py`。
- 前端入口：`frontend/src/admin/AdminAuthPage.tsx`、`AdminSystemSettingsPage.tsx`、`AdminDataInventoryPage.tsx`、`AdminOperationLogsPage.tsx`。
- 测试：`backend/tests/integration/core/test_api.py`、`test_backup.py`、`backend/tests/integration/audit/test_service.py`、`frontend/src/admin/adminData.test.ts`；浏览器 `frontend/src/admin/AdminRoutes.browser.test.tsx`。
- 最小：`make verify-fast`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/admin/AdminRoutes.browser.test.tsx`。

## 地图工作台
- 入口：`frontend/src/pages/MapPage.tsx`、`frontend/src/components/MapCanvas.tsx`、`RightSidePanel.tsx`；状态 `frontend/src/hooks/LayerContext.tsx`、`useLayerGroups.ts`；地图同步、查询、布局 `frontend/src/map/`。
- 单元：`frontend/src/components/RightSidePanel.test.ts`、`frontend/src/map/viewportVectorQuery.test.ts`、`rasterLayerSync.test.ts`；浏览器 `frontend/src/components/RightSidePanel.browser.test.tsx`、`frontend/src/pages/MapPageExport.browser.test.tsx`、`frontend/src/map/WorkbenchLegend.browser.test.tsx`。
- 最小：`make verify-fast`；浏览器：`cd frontend && node scripts/run-browser-check.mjs src/components/RightSidePanel.browser.test.tsx src/pages/MapPageExport.browser.test.tsx`。

## 知识、内容与领域数据
- 知识：`backend/apps/knowledge/views.py`、`library.py`、`formal_rules.py`；前端 `frontend/src/knowledge/KnowledgePage.tsx`；测试 `backend/tests/integration/test_knowledge_library.py`、`frontend/src/knowledge/KnowledgeLibrary.browser.test.tsx`。
- 内容：`backend/apps/content/views.py`、`science_document.py`；前端 `frontend/src/pages/EditorialPage.tsx`；测试 `backend/tests/unit/test_science_document.py`、`backend/tests/integration/test_science_column_refresh.py`、`frontend/src/pages/EditorialPage.browser.test.tsx`。
- 卡片图片共用入口：`frontend/src/components/CardCover.tsx`、`backend/apps/catalog/thumbnails.py`；写入与只读回归 `backend/tests/integration/catalog/test_card_thumbnails.py`；回填 `backfill_card_thumbnails`；规则见 `docs/developer-guide.md` 的“卡片图片规则”。
- 领域模型：`backend/apps/ecology/models.py`、`backend/apps/omics/views.py`、`backend/apps/standards/views.py`；测试 `backend/tests/unit/test_ecology_demo_algorithms.py`、`backend/tests/integration/omics/test_api.py`、`backend/tests/integration/catalog/test_api.py`。
- 最小：`make verify-fast`；知识浏览器：`cd frontend && node scripts/run-browser-check.mjs src/knowledge/KnowledgeLibrary.browser.test.tsx`。

## 契约与生成物
- 契约 `docs/openapi.yaml`；变更交接 `docs/api-change-requests.md`；响应语义 `docs/developer-guide.md`；配置 `frontend/openapi-ts.config.ts`。
- SDK/类型 `frontend/src/api/generated/`；Mock 领域样例 `mock/prism/examples/`；生成的 Prism 文件 `mock/prism/openapi.prism.json`。
- 最小：`make verify-fast` 自动对契约/示例改动选择 `check:api`、`api:changes:check`；完整契约流程见 `docs/developer-guide.md` 的“API 契约规范”。
- 类型再生成：`cd frontend && pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false run generate:api`。
- Mock 再生成：`cd frontend && pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false run mock:build`。
- 完整五项依次执行同一 pnpm 前缀的 `generate:api`、`check:api`、`api:changes:check`、`api:docs`、`api:lint`；生成物禁止手改。

## 巨型文件定位索引
行数为本次核对值，定位以符号和标题为准；`sed -n '起点,终点p'` 只取相关片段，不把整份文档或生成类型塞进上下文。

| 文件 | 行数 | 检索方式或分区 |
| --- | ---: | --- |
| `docs/openapi.yaml` | 20491 | `rg -n 'operationId: getAgentRun' docs/openapi.yaml`；先找到具体 operationId 或 schema 名，再读相邻定义 |
| `docs/developer-guide.md` | 3109 | `rg -n '^#{2,4} |API 契约规范|Prism Mock Server' docs/developer-guide.md`；根据接口域标题截取 |
| `docs/api-change-requests.md` | 1720 | `rg -n '^#{2,4} |business.flow|agent' docs/api-change-requests.md`；按接口路径、operationId 或交接标题定位 |
| `docs/implementation-notes.md` | 1253 | `rg -n '^## |业务流|会话历史|账号切换' docs/implementation-notes.md`；只读对应实现记录 |
| `frontend/src/api/generated/types.gen.ts` | 23849 | `rg -n '^export type .*Agent' frontend/src/api/generated/types.gen.ts`；只核对目标 DTO，变更回源契约 |
| `frontend/src/components/RightSidePanel.tsx` | 7361 | 入口 `RightSidePanel` 365；缩略图 `buildThumbnail` 762；栅格 `RasterOverviewPanel` 1763；统计 `createInsightStats` 3883；领域统计 `communityStatsFor` 5759、`individualStatsFor` 6181、`germplasmStatsFor` 6599 |
| `frontend/src/styles.css` | 22277 | `rg -n '^\\.workspace|^\\.nongeo|^\\.map-composition|专题制图工作流' frontend/src/styles.css`；非地理面板从 3237、工作台从 4775、专题制图从 17562，按具体选择器继续缩小 |

## 工具与检查入口
- 快速规划和执行：`scripts/verify_fast.py`；映射回归：`scripts/tests/test_verify_fast.py`；根目录 `Makefile`。
- 脚本回归最小命令：`"$PY" -m pytest scripts/tests/test_verify_fast.py -q`。
- 效率行为边界与回归：`docs/efficiency-contracts.md`；完整入口：`make check-efficiency`，使用项目环境或显式 `EFFICIENCY_PYTHON`。
- 发布唯一入口：`tools/release/release.py`，仅 `inspect`、`fast`、`full`、`status`、`rollback`；说明见 `tools/release/README.md`。
- 新增型迁移分类：`tools/release/migrations.py`；候选旧代码兼容：`compatibility.py`；结构指纹/正式迁移/回退门禁：`server.py`、`protocol.py`；回归：`tools/release/tests/test_migrations.py`、`test_schema_release.py`、`test_compute_migration.py`。仅 full 可凭同包候选证据推进结构，回滚永不恢复数据库。
