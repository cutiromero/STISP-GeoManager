# 制图主图底图加载修复验收

## 原因与修复

制图主图与鹰眼使用平台同源缩略图瓦片接口。该接口在外网不可达时返回本地生成的简化世界地图，状态仍为 200；导出器因此误认为瓦片加载完整，并把错误底图留在预览缓存。较低层级的鹰眼命中已有真实影像缓存，造成截图中的主图与鹰眼不一致。

现场进一步确认：原后端进程无法建立上游连接，报 WinError 10013；正常本机网络环境通过已有 HTTP 代理可在约 0.82 秒取得 Mapbox 影像，凭证有效。后端已在具备正常网络访问的环境中重启。对原失败瓦片重新请求，取得 59,309 字节真实 JPEG，替代之前 871 字节生成背景。

- 制图预览、主图、鹰眼和正式地图导出统一使用 `?purpose=export`，只接受真实底图或其缓存。不同查询参数避免复用普通缩略图的浏览器背景缓存。
- 此模式上游超时为 10 秒；失败且无缓存时返回标准 JSON 503、`Cache-Control: no-store` 和 `Retry-After: 2`。前端沿用完整瓦片检查和一次自动重试，失败时阻止输出。错误不包含上游凭证。
- 底图 raster-fade-duration 设为 0，避免出图捕获渐显中的瓦片。
- 普通工作台缩略图仍使用原有 4 秒超时和故障背景行为；不影响既有缩略图调用方。
- 无数据库迁移、业务权限或数据目录变更。既有底图缓存目录不变，业务栅格符号化仍在服务端，正式输出规格不变。

## 验证

| 检查 | 结果 |
| --- | --- |
| Pixi pytest：`test_map_export_tiles.py`、`test_api.py::MapThumbnailTileApiTests` | 9 passed；覆盖严格失败、错误脱敏、失败不污染缓存、恢复和缓存读取、普通缩略图与参数校验 |
| `pnpm test` | 399 passed |
| `pnpm run build:verify` | 品牌、语言、OpenAPI 比对、TypeScript 和生产构建通过 |
| `generate:api`、`api:changes:check`、`api:docs`、`mock:build` | 通过；API lint 保留 6 条原有未使用组件警告 |
| 本轮文件 Ruff / Oxlint / Oxfmt | 通过 |
| 实际工程 `123专题图` 的制图页面 | 主图与鹰眼均显示真实影像，业务点位和图例正常 |
| 同一实际地图的完整合成器、300 DPI 输出 | PNG 3508×2480；图像解码完整，真实底图请求均返回 200 |
| 浏览器注入瓦片 503 | 自动重试后报错，渲染 Promise 拒绝，未输出错误底图 |
| 原草稿保护 | 前后 layout、updatedAt 一致；没有保存验收图片为业务成果 |

证据位于 `output/20260918-composition-basemap/`：`preview.png`、`editor-preview.png`、`export-300dpi.png`、`live-render-report.json`、`backend-tiles-tests.log`、`frontend-tests.log`、`build.log`。300 DPI 验收图调用同一合成函数检查真实底图和输出尺寸，未传图例条目；实际页面预览包含原工程图例。可复验脚本为 `frontend/scripts/verify-composition-basemap.mjs`。独立验证会话已删除，用户原有会话和密码未修改。

## 交接与使用

本轮按契约 → 后端 → 前端 → 验证顺序完成。接口变更记录为 API-20260918-005，`docs/openapi.yaml`、`docs/developer-guide.md`、Mock 和 `frontend/src/api/generated/` 已同步；生成目录取代旧文档的 schema.d.ts 路径。

保存正在编辑的草稿后刷新浏览器，再进入制图，以清除内存中先前生成的简化预览。本地服务入口仍为 http://127.0.0.1:5173/。

新范围无缓存时仍依赖服务器到 Mapbox/OSM 的真实连接；后续重启应保持正常网络及现有代理可用。不要在限制上游网络的执行环境中启动供用户使用的后端。网络故障会明确报错，不能用简化世界地图代替正式制图底图。
