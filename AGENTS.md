# GeoManager Agent Instructions

## 效率回归门禁（2026-11-09）

- 涉及读取、查询、校验、缓存、算子准备或轮询的改动，提交和发布前必须运行 `make check-efficiency`。后端使用已激活的项目运行环境；可通过 `EFFICIENCY_PYTHON` 显式指定同一运行环境。前端 `build:verify` 同时包含快速效率检查。
- 先记录实际操作次数和调用链，再优化；相同输入、相同数据版本及同一授权范围的在途只读工作优先通过统一入口合并。不能在组件、轮询或逐资源循环中另建重复的请求、来源扫描、文件摘要或几何生成逻辑。
- 前端资源概况、可视化统计及显示查询使用 `api/client.ts` 的共享在途读取入口。共享键必须包含登录代次、项目、资源修订和全部查询参数；调用者取消不能终止其他使用者，最后一个使用者取消时才停止底层请求。失败和已完成响应不得作为权限缓存继续复用；写入和上传边界使旧的在途共享失效。
- 后端共享计算只复用纯结果，权限、项目、owner_only、暂停/停止及执行授权仍由每个请求或执行边界实时检查。持久显示缓存要核对完整版本和参数；并发冷启动必须经统一存储锁合并，缓存命中不占计算槽，失败必须释放锁并允许重试。
- 文件摘要、像元及掩膜校验不得为提速改动科学摘要、跳过版本检查或扩大输入范围。复用需有身份/版本约束；栅格像元摘要、几何和属性等优化必须提供结果一致性及原始文件未修改的回归。
- 新增昂贵调用必须同时提供执行次数、不同版本/项目隔离、撤权、取消、失败重试及缓存失效中的适用回归。不得只断言“最后成功”，不得通过放宽回归断言或关闭检查来消除失败。发布回执记录效率检查及实际数据验收结果。
- 智能体进度和会话历史通过 `load_run_activity` 按响应批量读取事件，只取最新参数及回答预览。上下文构建沿用同次检查的精确来源列表，禁止先计数再读取或再次查询祖先列表；实时权限与停止检查仍逐边界执行，不跨请求缓存授权或生成状态。

## 个人开发分支（2026-11-07，用户最新规则）

- 每位开发者固定使用一个自己的开发分支，连续功能、修复和优化均在该分支提交，不得按功能或任务新开分支。
- 当前开发者使用 `codex/xintao`；其他开发者使用各自身份命名的固定分支 `codex/<developer>`。已有个人分支必须复用。
- 从最新已核实的 `main` 同步更新到个人分支；先检查工作区和并行修改，保留其他开发者成果。
- 历史功能分支保留追溯，不批量删除、不改写其历史；新工作遵循个人分支规则。
- 本规则优先于本仓库历史说明中的按任务、按功能开分支要求。

## 更新粒度（2026-11-06）

- 用户要求：小修复和日常优化不单独升级版本号；大改动或小更新累计到合适规模后再统一升级。
- 小更新仍须必要验证、Git 提交及对应分支备份；生产更新以精确 commit SHA、独立发布目录和实际回执追溯，可沿用当前版本号。既有正式标签不移动、不覆盖。
- 下文版本递增步骤仅在需要统一升级版本的发布任务中执行，不因一次热修自动触发。

## 最新综合移交（2026-11-02）

- 接手先读 `docs/development-handover-20261102.md` 及配套发布依赖清单，再按任务读下文规范。密码在仓库外私密附件，不进入 Git。
- 当前正式基线为 `v0.1.51` / `d3b3e82685d2c8ec6055084304fff4f8d8c6c4b2`；如现场已有新回执，以实际版本为准。下文 `v0.1.11` 是历史接手来源。
- 本次核对 GitHub `main` 仍落后正式基线，未整理前从正式标签或明确集成分支开发；不要将旧 main 当作当前系统。
- 现用 AutoDL native 与本机 Conda、普通会话三路并发、私有发布工具递归依赖等，以最新移交和实际配置/回执为准。旧 Pixi/WSL/GHCR 说明保留为历史，不直接执行。

## 接续开发补充规则（2026-09-22）

本节承接用户本次交接要求；保留下文原有规则。接手入口为 `docs/handoff-2026-09-22.md`。

### GitHub 长期跟踪补充（2026-09-22）

- 用户已要求建立自己的长期代码库：`https://github.com/cutiromero/STISP-GeoManager`（私有），作为 `origin`；师兄仓库保留为 `mentor`。日常开发在各开发者固定个人分支进行，并从已核实的 `main` 同步更新。
- 新库首次提交是凭据清理后的当前代码快照；原交接历史、旧任务分支与发布标签继续保存在本机。不要向新库执行 `push --all`、`push --mirror` 或 `push --tags`，避免把旧历史中的明文口令带上去。
- 以后完成开发任务时，做必要检查后小步提交并同步 `origin` 对应个人分支，用于开发备份；不把开发备份误称为服务器验收或生产发布。正式部署、生产版本标签及师兄仓库同步仍遵守下文服务器验收流程。
- 本库 GitHub Actions 已关闭，保留历史工作流文件供参考；未经明确部署任务不启用镜像发布或自动部署。数据库、运行配置、日志、依赖、密钥和原始交接包不上传。
- 详细来源、分支边界和推送方式见 `docs/github-code-tracking.md`。以下涉及从交接基线开始、服务器验收后才推送 GitHub 的旧条款，分别理解为历史来源和正式发布要求，不阻止当前私有库的开发备份。

- `v0.1.11` / `c8a1d57769ec2eb50a8cbdd283046ba941d02e91` 为历史交接基线；当前开发复用开发者固定个人分支 `codex/<developer>`。先看 status、diff、已核实的最新 main 和近期历史，再修改文件。
- 代码与必要的文本说明纳入 Git，小步提交，明确列出待提交文件。不把数据库、科研数据、依赖、缓存、日志、密钥或整份敏感交接文档加入 Git；不因本规则批量移除历史已跟踪素材。
- 保留原始交接包、历史文档、已有修改、发布回执及恢复点。未经明确要求，不执行 `reset --hard`、`clean -fd`、强制推送、移动已发布标签、批量删除或覆盖重要文件；确需替换时先保存可恢复副本并说明范围。
- 开发和最小必要验证在本机完成。现网更新沿用“冻结提交和发布包 → SSH 上传新候选目录 → 候选验收 → 备份及切换 → 生产验收和回执 → 本机推送同一 SHA 到 GitHub”。下文通用发布命令必须服从此顺序，不能直接启用旧 Docker/GHCR 自动同步方案。
- 服务器通常返回回执。若服务器有应急代码修改，先取回到独立目录审查差异，再合并为新本地提交并重新验收；禁止用服务器目录直接覆盖本机仓库。回执、发布包与 GitHub 提交必须一致。
- 配置、业务数据、科研数据与代码分离；禁止以本机数据库覆盖生产数据库。只管理本项目已核实身份的进程，不擅自重启 vLLM、Jupyter 或 AutoDL 代理。
- 继续遵循 OpenAPI 唯一契约、生成类型禁止手改、后端鉴权、单项目范围、owner_only 隐私边界，以及栅格后端渲染和统一 GDAL CLI 封装。
- 文档冲突按版本和证据处理：最新交接回执说明历史部署状态，代码说明已有实现，运行配置决定实际开启能力；设计计划不能当作已交付。已知冲突见接手说明，不删除原始历史以消除冲突。
- 用户已于 2026-09-22 授权新建环境。本机项目使用独立 Conda `stisp-geomanager`（Python 3.14 / Django 6），执行前在仓库根目录点载 `. ./activate-local.ps1`，或使用 `start-local.ps1`；不要用 `uboo` 或 base 跑本项目，也不要修改它们。原 Pixi 配置保留供其他机器和服务器使用。配置、启动及验证见 `docs/local-conda-setup.md`。
- 任务保持简单；按改动范围做必要检查，不自动增加无关重构和流程。一次写入不超过 500 行代码。报告区分本次实测、历史验收与尚未验证，不把静态阅读说成测试通过。
- 每次系统更新后的汇报必须列出用户可见的前端变化：页面入口、具体控件/文案/排序/默认值的前后变化，以及本地和服务器是否已生效。仅后端修复也要明确说明没有新增界面、原界面行为如何改变。测试过程新增的项目、数据、会话或任务需要单独说明用途和保留情况，避免将验收内容混同为业务功能。

时空智能服务平台。Current product rules: docs/current-platform-rules.md. Historical ecological datasets remain valid research material.

These instructions are for AI coding agents working in this repository. Treat every rule below as operational guidance: read the required context, preserve architecture boundaries, keep API contracts synchronized, and report verification results explicitly.

## 1. Project Context

The platform is a browser-based spatiotemporal intelligence service platform (STISP). It manages geospatial and non-geospatial research data, project workspaces, map compositions, content, and isolated computation. Historical ecological datasets and publications remain valid research material; current product behavior is defined in docs/current-platform-rules.md.

Read `docs/design-docs.md` before writing code. It is the primary functional and architectural specification, including page structure, feature scope, data model expectations, performance targets, and acceptance criteria.

### Core product shape

- Users enter through one unified login page.
- The main web application contains both user-facing workflows and permission-gated admin features.
- Backend admin is a login-after feature controlled by permissions, not a separate public entry point.
- The UI should be Chinese-facing unless a task explicitly requires otherwise.
- Normal users, researchers, data admins, and system admins have different functional and data-access permissions.

### Primary references

| Document | Purpose |
| --- | --- |
| `docs/design-docs.md` | Full functional spec, architecture, data model, and acceptance criteria |
| `docs/openapi.yaml` | Authoritative OpenAPI 3.1.0 contract |
| `docs/api-change-requests.md` | Frontend-maintained API change handoff notes for backend implementation |
| `docs/developer-guide.md` | API behavior, API specification rules, usage notes, permissions, and examples |
| `docs/implementation-notes.md` | Shared implementation decisions and development memory |
| `docs/operations.md` | Local setup, testing, mock server, and deployment guidance |

> **Important:** When a decision affects future implementation, summarize it in `docs/`. Do not leave architectural decisions only in code comments, chat history, or commit messages.

## 2. System Architecture

### Technology stack

- **Frontend:** React, Vite, Ant Design, Mapbox GL JS
- **Backend:** Python, Django, GeoPandas, GDAL, Rasterio
- **Business data:** SQLite and application-managed metadata
- **Spatial/vector data:** GeoPackage `.gpkg`
- **Raster data:** Raw raster files, backend-generated PNG/XYZ output, PNG cache
- **Configuration:** TOML for data roots, cache policy, raster symbolization interface, and runtime paths

### Storage boundaries

Program code, business data, and research data must live in separate directory trees.

- Program paths belong to the repository and deployment code tree.
- Business-data root is configured in TOML.
- Research-data root is configured in TOML.
- Subdirectory layout under the data roots is fixed by convention, not configurable per item.
- Never hardcode business-data or research-data roots in application code.

> **Pitfall:** Data path shortcuts are easy to introduce during tests or imports. Keep roots TOML-driven and make tests provide explicit temporary config.

### Backend components

Use Django built-in auth, admin, sessions, groups, and permissions where possible. Do not reinvent user, role, session, or permission systems from scratch.

Backend app boundaries:

- `backend/apps/core/`: configuration, auth integration, permissions, system settings
- `backend/apps/catalog/`: data catalog, resources, vector query, imports, exports
- `backend/apps/raster/`: raster import, preprocessing, symbolization, tiles, async jobs
- `backend/apps/audit/`: operation logs and traceability

Sensitive operations require backend permission checks. Frontend route or button gating is not a substitute for server-side authorization.

### Frontend components

Ant Design is the primary UI library for non-map interfaces. Mapbox GL JS handles map rendering.

Preferred frontend boundaries:

- Map workspace: `frontend/src/pages/MapPage.tsx`, `frontend/src/components/MapCanvas.tsx`, `frontend/src/map/`
- Layer state: `frontend/src/hooks/LayerContext.tsx`, `frontend/src/hooks/useLayerGroups.ts`, `frontend/src/utils/layerFactory.ts`
- Data panel and query/import flows: `frontend/src/components/DataPanel.tsx`
- Admin pages: `frontend/src/admin/`
- API client: `frontend/src/api/client.ts`, using generated OpenAPI types

Do not use an array index as a React `key`. Do not use `!important` in CSS.

### Raster and map rendering

Raster files are never symbolized in the browser.

- Backend Python scripts generate PNG/XYZ output.
- The frontend only loads rendered imagery or tile services.
- Each raster type may have its own symbolization script.
- Raster symbolization scripts must be invoked through the unified stdin/stdout interface.
- PNG cache keys must include raster file identity, symbolization rules, and output size.
- Cache size cap and cleanup policy come from TOML config.

> **Important:** Any raster feature that moves color ramps, classification, resampling, or PNG generation into React violates the architecture. Keep raster computation behind backend services or configured symbolization scripts.

### Performance targets

Use the targets in `docs/design-docs.md` as acceptance constraints:

- Map interaction: at least 20fps where feasible
- Layer operations: no more than 500ms
- Query response: no more than 1s for up to 30k rows
- Layer management: support at least 5 concurrent loaded layers

When changing query, rendering, cache, or layer-state logic, consider these targets. They are not hard requirements but are good guidelines.

## 3. API Contract Rules

All backend API endpoints must be defined in `docs/openapi.yaml` using OpenAPI 3.1.0. `docs/openapi.yaml` is the authoritative contract.

Whenever an API endpoint is added, removed, or modified, including URL, method, parameters, request body, response shape, status codes, permissions, or authentication behavior:

1. Update `docs/openapi.yaml`.
2. Update `docs/developer-guide.md`.
3. Regenerate/check frontend API types when applicable.
4. Implement backend behavior and tests.
5. Implement frontend usage and tests.

### OpenAPI requirements

- Every operation must have a unique camelCase `operationId`.
- All parameters, request bodies, response schemas, and error cases need complete `description` fields.
- Error responses must use the standard `ErrorResponse` schema with a `detail` field.
- Authentication must be declared through `components.securitySchemes`.
- Public endpoints must explicitly declare `security: []`.
- Authenticated endpoints must declare session-based security.
- Permission behavior must be documented in both `docs/openapi.yaml` and `docs/developer-guide.md`.
- Frontend DTO types must come from `frontend/src/api/generated/`; do not hand-write duplicate backend DTO types.

### API verification

After changing OpenAPI, run:

```bash
cd frontend
pnpm run generate:api
pnpm run check:api
pnpm run api:changes:check
pnpm run api:docs
pnpm run api:lint
```

> **Pitfall:** API changes are high-conflict in multi-agent work. Prefer landing contract changes first, then backend implementation, then frontend usage.

### Mock server workflow

- Use Prism for frontend/backend separation. The canonical contract remains `docs/openapi.yaml`; do not create a second hand-written OpenAPI spec.
- Mock response examples live in `mock/prism/examples/*.json`, split by domain. Do not keep growing one large fixture file.
- Build the Prism spec with `cd frontend && pnpm run mock:build`; this generates `mock/prism/openapi.prism.json` from the canonical contract and injects examples.
- Run Prism with `pnpm run mock:api`, or run Prism and Vite together with `pnpm run dev:with-mock`.
- `pnpm run dev:mock` uses `.env.mock` to proxy Vite `/api` to `http://127.0.0.1:4010`.
- Prefer real local names and metadata from `/Users/gx/Documents/Source/huyang_system_data` for examples; when actual data is empty or incomplete, generate small, plausible Chinese-facing examples.
- API errors must be JSON: unauthenticated API requests return `401 {"detail":"请先登录"}` and CSRF failures return `403 {"detail":"CSRF 验证失败"}`. Do not allow API endpoints to redirect to a login page or return Django HTML error pages.

### Frontend/backend separation workflow

Use this protocol when one developer owns frontend work and another developer owns backend work.

- Frontend owns the API contract. `docs/openapi.yaml` is the frontend developer's responsibility because it defines the data shape the UI needs.
- Frontend code must use generated OpenAPI types from `frontend/src/api/generated/`; do not hand-write duplicate backend DTOs or infer hidden backend fields.
- Frontend expresses data requirements by updating `docs/openapi.yaml` and `mock/prism/examples/*.json`, not by changing backend implementation code.
- If frontend needs a new field, endpoint, status code, permission behavior, or response shape, the frontend developer updates `docs/openapi.yaml`, regenerates/checks `frontend/src/api/generated/`, and adds or updates a small domain-focused mock example that demonstrates the expected response.
- Every frontend-owned API contract change must also be recorded in `docs/api-change-requests.md`. Keep each entry concise but actionable: affected endpoint, change summary, frontend reason, mock example file, backend implementation notes, and verification expectation.
- Run `cd frontend && pnpm run api:changes:check` after changing `docs/openapi.yaml` or `mock/prism/examples/*.json`; the check fails when contract/mock files change without a tracked API change request.
- Backend implements the API contract. The backend developer reads `docs/openapi.yaml` and matching mock examples, then updates backend behavior and backend tests so real responses conform to the frontend-maintained contract.
- Backend developers should use `docs/api-change-requests.md` as the implementation queue for API changes. Mark entries implemented only after backend behavior, tests, and real response shapes match `docs/openapi.yaml` and the referenced mock examples.
- If backend cannot implement a proposed API shape safely, the backend developer must raise the contract issue and request an OpenAPI change instead of silently returning a different shape.
- Frontend and backend developers must not edit each other's application code without explicit handoff. Frontend-owned work stays under `frontend/`, `docs/openapi.yaml`, generated API types, and mock examples needed to express API needs. Backend-owned work stays under `backend/`, backend tests, and backend-facing API documentation.
- Shared contract files are coordinated, not casually edited. Treat `docs/openapi.yaml`, `frontend/src/api/generated/`, `mock/prism/examples/*.json`, and `mock/prism/openapi.prism.json` as the handoff surface between frontend and backend.
- `mock/prism/openapi.prism.json` is generated output. Do not hand-edit it; run `cd frontend && pnpm run mock:build`.
- Do not add temporary frontend fallbacks for missing backend fields, and do not add backend compatibility branches for undocumented frontend assumptions. Fix the OpenAPI contract and mock examples first.

## 4. Development Environment

### Package managers and environments

- Use `pnpm` for all frontend dependency and script commands.
- Do not use `npm`.
- Use Pixi for backend Python commands:

```bash
cd backend
pixi install
pixi run dev
```

### Formatting and checks

Frontend scripts are defined in `frontend/package.json`:

```bash
cd frontend
pnpm run check
pnpm run fix
pnpm run typecheck
pnpm test
```

Backend formatting:

```bash
cd backend
pixi run format
pixi run test
```

Run the smallest reliable verification set for the changed area. For merge-ready work, prefer the full relevant set.

## 5. Implementation Guardrails

### General rules

- No legacy fallback paths.
- Read existing code and tests before editing.
- Follow local patterns instead of introducing parallel architecture.
- Keep changes small, focused, and reviewable.
- Do not refactor unrelated files while implementing a feature.
- Do not revert or overwrite changes made by another agent unless explicitly instructed.
- Clarify uncertain behavior through tests and documentation rather than hidden compatibility branches.
- Format code before committing.

### Permissions and security

- Use Django permissions and groups where possible.
- Enforce permissions in backend views/services for menus, data resources, queries, exports, admin features, and configuration changes.
- Treat frontend permission gates as usability only; never rely on them as the security boundary.
- Log key operations in the audit app where the action affects data, permissions, configuration, imports, exports, or raster jobs.

### Data and import behavior

- Keep business-data and research-data roots configurable only through TOML.
- Validate imported data structure, field types, coordinate fields, and spatial bounds before accepting it.
- Return structured validation errors that help users correct data.
- Keep catalog classification based on topic, time, space, and source consistent with the design document.

### Frontend behavior

- Use Ant Design for forms, tables, menus, modals, panels, and admin interfaces.
- Use Mapbox GL JS for map rendering and map interaction.
- Keep raster symbolization out of frontend code.
- Keep UI state and generated API DTOs separate; do not hand-write API response duplicates in `frontend/src/types.ts`.
- Preserve responsiveness and avoid UI text overflow in panels, buttons, and tables.

## 6. Multi-Agent Coordination

Assume other agents may be working in parallel. Keep task boundaries narrow, inspect current file state before editing, and avoid unrelated churn. Do not overwrite or revert changes you did not make unless the user explicitly instructs you to do so.

### Task intake

At the start of each task, identify these items from the user request and repository context:

- Background: why the change is needed.
- Scope: files or modules likely to change.
- Out of scope: files or behavior that must remain untouched.
- API impact: endpoints, schemas, permissions, or authentication behavior affected; if none, treat it as no API change.
- Required references: normally `docs/design-docs.md`, `docs/implementation-notes.md`, and the relevant code/tests.
- Verification: the smallest reliable command set for the changed area.

If a task request is missing one of these items, infer it from the repository where safe. Ask the user only when the missing information could cause an unsafe or incompatible implementation.

### Execution roles

Use these role boundaries to choose files and responsibilities. A single agent may perform multiple roles in one task, but keep edits ordered by dependency.

- **Coordinator Agent:** task breakdown, merge order, API conflict tracking.
- **Contract Agent:** `docs/openapi.yaml`, `docs/developer-guide.md`, API examples, generated frontend API types. In frontend/backend split work, this role is owned by the frontend developer unless explicitly delegated.
- **Backend Agent:** Django features by app boundary. Backend agents must not edit React UI code except during an explicit cross-stack handoff.
- **Frontend Agent:** React features by UI/state boundary. Frontend agents must not edit Django code except during an explicit cross-stack handoff.
- **Testing Agent:** verification, failure reproduction, missing tests.
- **Documentation Agent:** implementation notes, testing notes, changelog entries, implementation explanations.

### Frontend/backend ownership

When frontend and backend are developed by different people, use these ownership boundaries:

| Area | Owner | Allowed changes |
| --- | --- | --- |
| `backend/` | Backend developer | Django views, services, models, permissions, backend tests |
| `docs/openapi.yaml` | Frontend developer | Authoritative API contract defining the data shape required by the UI |
| `docs/api-change-requests.md` | Frontend developer | API change handoff notes that tell backend what to implement |
| `frontend/` except generated API types | Frontend developer | React UI, state, routes, API client usage, frontend tests |
| `frontend/src/api/generated/` | Generated from OpenAPI | Never hand-edit; regenerate after contract changes |
| `mock/prism/examples/*.json` | Frontend developer | Expected data examples that demonstrate UI requirements; backend verifies real responses against them |
| `mock/prism/openapi.prism.json` | Generated from OpenAPI and examples | Never hand-edit; regenerate with `pnpm run mock:build` |

Cross-boundary edits require an explicit handoff note in the task or completion report. If a frontend task appears to require backend code changes, finish the OpenAPI/mock requirement and hand implementation to the backend owner. If a backend task appears to require contract or UI changes, implement only the backend-compatible part and hand the OpenAPI/UI change to the frontend owner.

### Branch model

Use one persistent development branch per developer. Reuse that branch across features, bug fixes and tasks; do not create feature or task branches.

```text
codex/<developer>
```

The current developer uses `codex/xintao`. Other developers use their own stable identity. Synchronize verified main updates into the personal branch and preserve existing work. Retain historical branches for traceability.

### Conflict-prone files

Avoid editing these files unless the task explicitly owns them:

| File | Default owner | Reason |
| --- | --- | --- |
| `docs/openapi.yaml` | Frontend-owned Contract Agent | Authoritative API contract defining frontend data requirements |
| `frontend/src/api/generated/` | Frontend-owned Contract Agent | Generated API types; never hand-edit |
| `frontend/src/types.ts` | Frontend architecture owner | Separates UI types from API DTOs |
| `backend/apps/core/permissions.py` | Permission owner | Central permission registry |
| `frontend/src/App.tsx` | Frontend architecture owner | Routing and auth gate entry |
| `docs/implementation-notes.md` | Documentation Agent | Shared implementation memory |
| `CHANGELOG.md` | Release owner | Release-level summary |

If a required change touches a conflict-prone file, keep the edit minimal and note it in the completion report. For API changes, finish the contract change before backend and frontend implementation.

### Merge order for API changes

1. Contract change: `docs/openapi.yaml`, `docs/developer-guide.md`, generated API types
2. Backend implementation: endpoint, permissions, service behavior, tests
3. Frontend implementation: API usage, UI behavior, frontend tests
4. Documentation and release notes: implementation notes, testing notes, `CHANGELOG.md`

Small tasks may combine these steps in one change set, but preserve this order while editing and reporting.

## 7. Verification Checklist

Use the checklist that matches the touched area.

### Backend

```bash
cd backend
pixi run test
pixi run format
```

### Frontend

```bash
cd frontend
pnpm run check:api
pnpm test
pnpm run check
pnpm run typecheck
```

### API docs

```bash
cd frontend
pnpm run api:lint
pnpm run api:docs
```

### Completion report

Every completion response must state:

- What changed.
- Which verification commands ran and whether they passed.
- Whether an API contract changed; if yes, confirm `docs/openapi.yaml`, `docs/developer-guide.md`, and `frontend/src/api/generated/` were updated or explain why not.
- Whether permissions, data paths, or raster rendering changed.
- Remaining risks, especially performance, migration, data compatibility, or deployment risks.

## 8. Versioning and Releases

The project uses Semantic Versioning and Keep a Changelog format.

Version files:

- Frontend: `frontend/package.json`
- Backend: `backend/pyproject.toml`
- Changelog: `CHANGELOG.md`

When handling a release task:

1. Update `CHANGELOG.md` with the new version changes.
2. Bump version using `make version-patch`, `make version-minor`, or `make version-major`.
3. Create a tag using `make tag` or `git tag -a v{version} -m "Version {version}"`.
4. Push changes and tags with `git push && git push --tags`.

Release commands:

```bash
make help
make version-patch
make version-minor
make version-major
make changelog
make tag
```
