# 项目结构与配置维护说明

本文档说明当前前后端目录职责、配置归属和维护规则。调整目录或移动模块时，应同步更新本文档和 `docs/implementation-notes.md`。

## 根目录

- `backend/`：Django 后端工程，只放服务端代码、迁移、后端测试和后端运行脚本。
- `frontend/`：React/Vite 前端工程，只放浏览器端源码、前端测试、构建脚本和生成的前端产物。
- `docs/`：产品设计、API 契约、开发指南、结构说明和实现决策记录。
- `config/`：TOML 运行配置示例。真实部署配置通过 `--config /path/to/app.toml` 指定。
- `mock/prism/`：基于 `docs/openapi.yaml` 的 Prism mock 示例与生成产物。

## 后端目录

- `backend/apps/core/`：TOML 配置加载、认证、权限、系统设置、初始化账号和管理后台 API。
- `backend/apps/core/configuration/`：后端内置业务配置。当前 `builtins.py` 维护内置用户组、游客账号、初始管理员环境变量名和默认权限集合。
- `backend/apps/catalog/`：数据目录、数据资源、GeoPackage 查询、导入、导出、资源扫描，以及 `MapComposition/MapCompositionVersion` 专题制图持久化和成果文件接口。
- `backend/apps/raster/`：栅格数据集、导入预处理、符号化规则、XYZ 瓦片和异步任务。
- `backend/apps/audit/`：操作日志模型和记录服务。
- `backend/tests/`：后端单元测试与集成测试，按 app 和测试层级组织。

## 前端目录

- `frontend/src/api/`：OpenAPI 生成 SDK、类型和统一 API 客户端。`generated/` 只能由生成命令更新。
- `frontend/src/admin/`：管理后台页面、后台专用数据转换和后台测试。
- `frontend/src/components/`：地图工作台通用组件和业务面板。
- `frontend/src/hooks/`：React 状态和业务 hook，包括图层上下文、缓存恢复和栅格渲染调度。
- `frontend/src/map/`：Mapbox GL JS 相关同步、交互和样式层工具。
- `frontend/src/map-composition/`：专题版式类型、纸张模板、图例派生、离屏地图合成、格网/比例尺绘制和出图检查纯函数。
- `frontend/src/components/map-composition/`：出图工作台、页面与整饰设置、专题成果列表、预览和导出交互组件。
- `frontend/src/pages/`：路由页面组件；`KnowledgeHelpSections.tsx` 保存帮助和科研知识共享组件，当前关于页面为 `AboutV2Page.tsx`。
- `frontend/src/utils/`：纯函数工具，避免依赖 React 生命周期或 DOM。

## 配置归属

- 运行环境、路径、地图默认值、上传限制、查询限制和栅格超时属于 TOML 配置，由 `backend/apps/core/config.py` 加载。
- 内置用户组、游客账号、初始管理员环境变量名和默认功能权限属于后端内置业务配置，由 `backend/apps/core/configuration/builtins.py` 维护。
- 前端不得根据用户组中文名称推断权限或保护规则，应使用后端 API 返回的 `isProtected`、`lockedPermissions` 和权限字段。

## 维护规则

- 新增运行期可部署调整的配置时，优先加入 TOML 配置，并更新 `config/app.example.toml`、`docs/developer-guide.md` 和相关测试。
- 新增系统内置账号、用户组或默认权限时，只修改 `backend/apps/core/configuration/builtins.py`，业务代码通过 `apps.core.initialization` 的 helper 获取。
- 不在视图、序列化或前端页面中重复硬编码内置用户组名称。
- 字段元数据、目录扫描等可选数据缺失时只能忽略明确可预期的缺失条件；结构错误、文件损坏和数据库异常应返回或记录明确错误。
