# 开发者指南（Developer Guide）

> 时空智能服务平台。当前规则见 [current-platform-rules.md](current-platform-rules.md)，接口结构以 [openapi.yaml](openapi.yaml) 为准。
> 版本：v0.1.0

## 智能体额度与思考状态（2026-10-16）

`AgentPolicy.dailyRuns/maxSteps/maxResources` 支持 `0` 表示不限每日次数、工具步骤或详细读取资源数。用户及组额度中的 `dailyRuns=0` 表示该条不限制，所有匹配的正数额度取最小值；均为0时不作每日次数限制。工作流资源校验与工具读取使用同一语义，仍逐次核对当前项目、可见性和功能权限。

对话手选数据数量服从`maxResources`，去除旧版固定3项限制；手选算法允许选择一个或多个已发布版本，每项分别核验权限。前端选择框与服务端校验一致，附件数量使用已保存的`maxAttachments`。

任务预算关闭时，问题长度按`min(maxContextTokens*4, maxContextBytes/4)`估算字符额度，去除固定12000字限制；完整请求仍由实际模型分词校验。

输入字节、输入/生成token、任务时限、工作流判断/算子步骤、协议重试和附件数量可由管理员按研究任务设置，不再受旧版固定档位上限限制。角色预算和任务默认值同样放开固定上界，仍要求角色窗口容纳生成额度和输入余量。模型服务的实际窗口、分词检查、取消与超时、并发保护、附件文件大小及全部读写权限保持生效。配置高于实际模型容量不会扩大模型能力。

深度模式仅展示服务真实返回并持久化的思考内容；没有收到思考内容时准确说明该状态，工具结果与最终答复继续独立展示。

Qwen深度工具调用使用提示约束及后端严格JSON协议验证，不发送会压制思考流的`response_format=json_object`；快速模式仍可使用JSON约束。实际服务A/B验证表明，同一问题在开启该约束时没有返回思考内容，去掉后返回原生思考分隔及正文；启用深度开关本身不能证明已收到思考。

## 双Demo科研工作流（2026-10-10）

POST /api/agent/workflows/ 支持 ecology_investigation（植被变化与调查排序）和 geology_correction（初图检查、几何候选、受约束编辑与复核）。同样要求本人智能体权限、当前单项目范围和幂等键。创建先生成可确认计划，不直接执行。

inputs 使用明确资源角色。生态为 early_image、late_image、valid_mask、zones、context；地质为 initial_map、surveys、rules。resourceIds覆盖角色资源，后台maxResources默认3，可配置正数或0（不限）。knowledgeSelection支持auto/manual/all/none，manual领域沿用知识分区协议。两期日期、波段、阈值和权重放parameters，按实际算法manifest验证。

AgentWorkflowStep.decision 为可空公开判断摘要，包含问题、发现、当前判断、待核实项、下一动作、算法理由和实际引用；modelMode区分real/mock。知识引用带整数revision，资源/任务/输出通过实际对象及内部内容校验和核验。摘要用于回查依据，不保存或公开模型内部思维链。

真实模型的结构、最新统计引用或受约束修改校验失败时，每步最多追加一次具体错误反馈，由模型重新作答。plan 保存初始完整请求与各次响应审计；每次请求重新核对完整上下文和权限，actualModelCallCount 累计受原 maxIterations 预算限制，网络、取消和权限异常直接停止。

确认入口仍提交planHash。输入修订、知识版本、算法checksum及下游入库资源在执行前重新授权。needs_review候选会暂停并更新计划哈希；人工批准分析与批准质量产物分别记录，避免跨步骤复用批准。计算成功后完整读取有限统计表，将真实结果保存为下一步输入，再形成下一判断。刷新/重试复用持久步骤和原taskId。

生态更新可传previousWorkflowId，必须引用本人同项目已成功的生态分析。两期影像、掩膜、分区、日期及计算参数保持原绑定；新的context保留原观测并增加证据。更新核实原change产物及入库资源，只重新执行调查排序，plan.previousAnalysis保存旧判断、原统计和新增证据。操作说明见[双Demo本机演示](dual-demo-20261010.md)。

地图支持 /map?resourceIds=资源列表&projectTagId=项目，使用已授权项目切换和既有后端栅格渲染。矢量结果从计算卡进入已入库图层；原始地质图和修正图可一起加载。模拟地图中的参考图及设错清单不登记为业务资源，不进入模型和算子。

## 用户思考强度（2026-09-24）

智能体 bootstrap 返回 `defaultReasoningEffort`。提交接口在 `thinkingMode=deep` 时接受可选 `reasoningEffort`（`low/medium/xhigh`）。显式选择优先于预算方案强度和后台默认强度；省略时沿用原默认策略。快速模式传入强度返回 400。强度持久化到本轮任务并参与幂等校验，worker 在预算解析后、上下文计数及模型请求前应用。后台深度思考开关与模型能力检查继续生效。

> 本文保留历史业务接入说明。历史 `accessGroupIds`、`audienceGroupIds`、`availableAccessGroups` 只用于兼容元数据，不授予或限制项目内对象访问。项目、内容、工程规则以本文最新章节及上述当前规则为准；不要沿用早期按角色共享、四大类或 all 聚合的示例。

---

## 目录

1. [快速开始](#1-快速开始)
2. [认证与会话管理](#2-认证与会话管理)
3. [数据浏览与目录](#3-数据浏览与目录)
4. [数据导入](#4-数据导入)
5. [数据查询](#5-数据查询)
6. [数据导出](#6-数据导出)
7. [地图图层](#7-地图图层)
8. [栅格数据管理](#8-栅格数据管理)
9. [异步任务管理](#9-异步任务管理)
10. [搜索](#10-搜索)
11. [后台管理](#11-后台管理)
12. [最佳实践](#12-最佳实践)
13. [常见问题（FAQ）](#13-常见问题faq)
14. [版本控制与变更历史](#14-版本控制与变更历史)

---

## 1. 快速开始

### 功能简介

时空智能服务平台是一个用于管理、计算和共享多领域科研数据的综合系统。平台支持矢量数据、栅格数据、表格数据等多种数据类型的导入、查询、可视化和导出。

### 技术架构

| 层级 | 技术栈 |
|------|--------|
| 前端 | React + Vite + Ant Design + Mapbox GL JS |
| 后端 | Python + Django + GeoPandas + GDAL + Rasterio |
| 数据存储 | SQLite（业务数据）、GeoPackage（矢量数据）、原始栅格文件 |

### 核心概念

**数据资源（DataResource）**：平台中的基本数据单元，代表一个独立的数据集，如"胡杨林分布图"或"DEM高程数据"。

**数据目录（DataCatalog）**：用于组织数据资源的分类树结构，支持多级目录。

**地图图层（MapLayer）**：数据资源在地图上的可视化表现形式，分为矢量图层和栅格图层。

**栅格数据集（RasterDataset）**：经过预处理的栅格文件，支持瓦片服务和符号化渲染。

### 首次接入流程

```
1. 获取系统配置
   ↓
2. 用户注册/登录
   ↓
3. 浏览数据目录
   ↓
4. 查询/导出数据
```

### SDK 示例

**JavaScript / TypeScript（Hey API）**

前端项目使用 `@hey-api/openapi-ts` 生成 `frontend/src/api/generated/` 下的类型、SDK 和 fetch client。业务代码优先使用 `frontend/src/api/client.ts` 导出的 `api` 对象；新增 API 方法时应通过 Hey API 生成的 SDK 函数调用 OpenAPI 中定义的路径。

```typescript
import { getBootstrap } from "../frontend/src/api/generated";
import { client } from "../frontend/src/api/generated/client.gen";

// 平台浏览器端默认使用同源入口，避免跨域与 CSP 配置漂移。
client.setConfig({ baseUrl: "", credentials: "include" });

// 获取系统配置
const { data: config, error } = await getBootstrap();

if (error) {
  throw new Error(error.detail);
}

console.log("系统名称:", config.systemName);
console.log("是否开放注册:", config.allowRegistration);
```

`docs/openapi.yaml` 的首个 `servers` 条目必须保持为同源 `/`，因此重新生成的默认客户端不会写死 `localhost`。只有独立脚本或外部系统直连后端时，才应显式把 `baseUrl` 覆盖为目标 API 地址。

OpenAPI 规范更新后，在前端目录运行：

```bash
pnpm run generate:api
pnpm run check:api
pnpm run api:docs
```

`api:docs` 和 `api:bundle` 的输出属于前端生成物，保存在 `frontend/generated/`，不作为人工维护文档编辑。

### API 契约规范

`docs/openapi.yaml` 是唯一权威 API 契约，使用 OpenAPI 3.1.0。新增、删除或修改接口时，先更新契约，再同步后端实现、前端类型、mock 示例和文档说明。

强制规则：

- `operationId` 使用唯一 camelCase 名称。
- 公共接口显式声明 `security: []`，登录后接口声明 `sessionAuth`。
- 所有参数、请求体、响应 schema 和错误响应都必须有清晰 `description`。
- 错误响应统一使用 `ErrorResponse`，至少包含 `detail` 字段。
- API 未认证返回 JSON `401 {"detail":"请先登录"}`，CSRF 失败返回 JSON `403 {"detail":"CSRF 验证失败"}`，不得返回登录页 HTML 或 Django HTML 错误页。
- OpenAPI 3.1 可空字段使用 JSON Schema 语义，例如 `type: [integer, "null"]`，不使用 `nullable: true`。
- Prism 示例维护在 `mock/prism/examples/*.json`，生成的 `mock/prism/openapi.prism.json` 不手写维护。

修改 API 后运行：

```bash
cd frontend
pnpm run generate:api
pnpm run check:api
pnpm run api:changes:check
pnpm run api:docs
pnpm run api:lint
```

### Prism Mock Server

前端可在没有真实后端的情况下使用 Prism mock server：

```bash
cd frontend
pnpm run mock:build
pnpm run mock:api
pnpm run dev:mock
```

也可以一条命令同时启动 Prism 和 Vite：

```bash
cd frontend
pnpm run dev:with-mock
```

`dev:mock` 会通过 `.env.mock` 将 Vite `/api` 代理到 `http://127.0.0.1:4010`。Mock 响应样例位于 `mock/prism/examples/`，由 `pnpm run mock:build` 注入到 `mock/prism/openapi.prism.json`。

### 登录页公开概览接口

新版登录页包含平台品牌、能力标签、数据统计卡片、服务状态点阵和版本信息。为避免前端硬编码统计口径，后端需要提供公共概览接口：

```typescript
const { data: overview, error } = await client.GET("/api/login/overview/");

if (error) {
  throw new Error(error.detail);
}

console.log(overview.platform.chineseName);
console.log(overview.metrics.map((item) => item.displayValue));
```

`GET /api/login/overview/` 无需认证，专门服务登录页公开展示内容；它不同于 `/api/admin/dashboard/`，后者需要登录和后台权限，不能直接用于未登录的首页。该接口不得返回敏感路径、用户信息、权限组明细、内部服务器资源或未公开数据清单。

登录页字段和前端展示关系：

| 前端区域 | OpenAPI 字段 | 后端实现口径 |
| --- | --- | --- |
| 中文名称、英文名称、GPEDSP、版本型号 | `platform` | 来自系统设置或后端常量，需与软件发布版本保持一致 |
| 主标题上方标签、一句话概述、能力标签 | `hero` | 后端返回可配置文案，前端只负责排版展示 |
| 四个统计卡片 | `metrics` | 当前需要 `dataResources`、`thematicLayers`、`monitoringSites`、`coveredBasins` 四项，返回原始 `value` 和格式化 `displayValue` |
| 平台服务状态 | `serviceStatus.services` | 返回资源目录、图层服务、权限认证三个公开状态，不暴露内部错误堆栈 |
| 点阵图例与数量 | `serviceStatus.nodeSummary` | 返回 `normal`、`warning`、`risk` 数量和图例，前端据此渲染状态点阵 |
| 底部统计说明 | `footer.statisticsNotice` | 说明统计口径是否已接入后端概览接口 |

推荐后端将该接口结果短时间缓存，例如 60 秒到 5 分钟；数据资源、图层和监测站点数量不要求实时到秒级，但应与后台 Dashboard 或数据管理统计口径保持一致。

### 地图缩略图同源瓦片

主界面右侧“当前视角平面缩略图”必须通过平台同源接口加载底图瓦片，禁止前端直接把 Mapbox、OSM 等第三方瓦片域名写入 `<img>`。同源接口为：

```text
GET /api/map/thumbnail-tiles/{z}/{x}/{y}.png
```

后端按当前 `application.map` 配置选择 Mapbox 或 OSM 源，成功获取后缓存到业务数据目录下的 `media/map-thumbnail-tiles/`，缓存命中时按图片文件头保留真实 MIME 类型。当外部瓦片源暂时不可达且本地无缓存时，接口仍返回本地生成的 Web Mercator 2D 世界地图瓦片，避免无缓存的新电脑访问平台时出现黑屏或仅显示前端内置兜底图。

前端缩略图只需要生成同源 URL，例如：

```typescript
const tileUrl = `/api/map/thumbnail-tiles/${z}/${x}/${y}.png`;
```

该接口不暴露敏感业务数据；返回内容可能是 `image/png`、`image/jpeg`、`image/webp`、`image/avif` 或本地兜底 `image/svg+xml`，非法瓦片坐标返回标准 `ErrorResponse`。

制图预览、鹰眼与正式导出统一使用 `?purpose=export`。此模式只返回真实 Mapbox/OSM 瓦片或真实缓存；上游失败且无缓存时返回 `503 {"detail":"制图底图服务暂时不可用，请稍后重试或检查服务器到 Mapbox/OSM 的网络连接"}`，设置 `Cache-Control: no-store` 和 `Retry-After: 2`。上游连接超时为 10 秒，前端等待完整瓦片后再合成，并有一次自动重试。普通缩略图缺省 `purpose=thumbnail` 维持 4 秒超时与简化背景行为。未知 purpose 返回 400。两种模式 URL 不同，制图不会命中浏览器之前缓存的简化背景。

### 浏览器底图访问凭证

Mapbox 与天地图的浏览器端访问凭证统一保存在运行 TOML 的 `[application.map]` 中：

```toml
[application.map]
default_basemap = "satellite"
mapbox_access_token = ""
tianditu_access_token = ""
```

`tianditu_access_token` 是可选配置。旧配置文件没有该键时，后端按空字符串加载，`GET /api/bootstrap/` 和 `GET /api/admin/settings/` 仍会返回 `map.tiandituAccessToken: ""`，因此现有部署无需配置迁移即可启动。具备 `core.manage_system_settings` 权限的管理员可通过 `POST /api/admin/settings/` 的 `map.tiandituAccessToken` 更新或清空该值，修改会与其他 application 设置一样原子写回启动时指定的源 TOML。

`default_basemap` 的正式选项为 `satellite`、`mapbox-streets`、`tianditu-vector` 和 `tianditu-imagery`；其中 `tianditu-imagery` 使用天地图球面墨卡托 `img_w + cia_w` 影像与中文影像注记组合。`img_w` 固定以 z16 作为平台可靠影像上限，地图继续放大时由 Mapbox GL overscale 最后一级影像，不再请求会返回“该区域无影像”占位图的 z17；`cia_w` 注记继续使用其 z18 上限。历史 `osm` 值只作为兼容输入，并在管理员下次保存系统设置时迁移为 `satellite`。OSM 匿名公共瓦片只在四项正式底图均不可用时作为隐藏技术兜底。

这两个字段都会通过公共 Bootstrap 接口下发给浏览器，只能保存供应商明确允许公开使用的浏览器端 Token/Key，不得保存 Mapbox `sk.*`、下载账户密码或其他服务端私密凭证。管理员接口只接受 Mapbox `pk.*` 公开 Token，并要求天地图 Key 为控制台签发的 32 位字母数字串；该格式校验不能替代供应商控制台中的“浏览器端”类型、生产域名白名单和配额检查。生产环境应为开发、测试和生产分别申请凭证，并在供应商控制台配置可用的域名来源限制和配额告警。天地图瓦片请求使用 `tk` 参数；平台接入球面墨卡托 WMTS 时应使用 `_w` 服务。服务端代理、长期缓存或 CDN 分发需要单独的服务端凭证及供应商书面许可，不使用本浏览器配置替代。

**Python**

```python
import requests

session = requests.Session()
base_url = "http://localhost:8000/api"

# 获取系统配置
config = session.get(f"{base_url}/bootstrap/").json()
print(f"系统名称: {config['systemName']}")
print(f"是否开放注册: {config['allowRegistration']}")
```

---

## 2. 认证与会话管理

### 功能简介

平台采用 Django 内建的 Session 认证机制，基于 Cookie 维持会话。所有需要身份验证的操作都依赖于有效的会话。

### 使用场景

- 用户首次访问系统需要注册账号
- 已有账号的用户登录系统
- 前端应用检查用户登录状态
- 用户退出系统

### 前置条件

- 系统已正常运行
- 首次迁移后系统会自动创建用户名为 `admin` 的完整功能账号和 `超级管理员` 角色；该账号是普通用户，完整功能来自角色权限。未设置 `HUYANG_SUPERADMIN_PASSWORD` 时，随机初始密码写入业务数据目录；服务器启动时会向控制台打印账号用户名和初始/配置密码，可通过 `docker logs` 查看。
- 注册功能已开放（可通过 `/api/bootstrap/` 接口查询 `allowRegistration` 字段）

### 集成流程

```
获取 CSRF Token
   ↓
用户登录/游客登录/注册
   ↓
获取用户信息
   ↓
后续请求携带凭证
```

### 实现步骤

#### Step 1: 获取 CSRF Token

在执行任何写操作（POST）之前，必须先获取 CSRF Token。系统会设置 `csrftoken` Cookie，后续请求需从 Cookie 中读取此值并通过 `X-CSRFToken` 请求头传递。

```javascript
// JavaScript
await fetch("/api/auth/csrf/", { credentials: "include" });
```

```python
# Python
session.get(f"{base_url}/auth/csrf/")
```

如果未携带有效 CSRF Token，后端返回 JSON `403`：

```json
{"detail": "CSRF 验证失败"}
```

受保护 API 未登录时返回 JSON `401`：

```json
{"detail": "请先登录"}
```

API 不应返回登录页 HTML 或 Django HTML 错误页，前后端和 mock server 都按 `ErrorResponse.detail` 处理错误。

#### Step 2: 用户登录

使用用户名和密码进行登录。登录成功后，系统会建立会话并返回用户信息。

```javascript
// JavaScript
const response = await fetch("/api/auth/login/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({
    username: "researcher1",
    password: "your_password",
    remember: true, // true: 持久会话; false: 关闭浏览器即失效
  }),
});
const { user } = await response.json();
```

```python
# Python
response = session.post(f"{base_url}/auth/login/", json={
    "username": "researcher1",
    "password": "your_password",
    "remember": True,
})
user = response.json()["user"]
```

#### Step 3: 游客登录

无需输入账号密码，可使用系统维护的专用游客账号建立会话。游客账号用户名固定为 `guest`，显示名为“游客”，不可使用密码登录；账号只归属 `游客` 角色。游客角色默认不具备任何功能权限。管理员可在认证授权中调整游客角色权限，但游客系统账号不能被删除、停用、重置密码、改角色或单独授予直授权限，`游客` 内置角色也不能删除或重命名。

```javascript
// JavaScript
const response = await fetch("/api/auth/guest-login/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
});
const { user } = await response.json();
```

```python
# Python
response = session.post(f"{base_url}/auth/guest-login/")
user = response.json()["user"]
```

#### Step 4: 用户注册

如果系统开放了注册功能，新用户可以通过注册接口创建普通账号。完整功能账号由首次初始化流程自动创建，并自动归属 `超级管理员` 角色。自助注册邮箱必填，后端统一保存为小写并保证非空邮箱唯一；当前过渡阶段不发送验证邮件。

`accountPurpose` 只表达账号用途：`standard` 直接注册普通用户，`research` 仍先注册为普通用户，同时提交一条待审核的科研用户角色申请。注册请求不能直接授予科研用户、平台管理员或超级管理员权限。

```javascript
// JavaScript
const response = await fetch("/api/auth/register/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({
    username: "researcher1",
    email: "researcher1@example.com",
    password: "SecurePass123!",
    passwordConfirm: "SecurePass123!",
    accountPurpose: "research",
    displayName: "张研究员",
    department: "生态监测组",
    applicationReason: "需要上传和导出长期监测数据",
  }),
});
```

```python
# Python
response = session.post(f"{base_url}/auth/register/", json={
    "username": "researcher1",
    "email": "researcher1@example.com",
    "password": "SecurePass123!",
    "passwordConfirm": "SecurePass123!",
    "accountPurpose": "research",
    "displayName": "张研究员",
    "department": "生态监测组",
    "applicationReason": "需要上传和导出长期监测数据",
})
```

具备 `core.manage_auth` 的管理员通过 `GET /api/admin/role-applications/` 查看申请，并通过 `POST /api/admin/role-applications/{applicationId}/review/` 提交 `approve` 或 `reject`。批准后系统移除普通用户角色并加入科研用户角色，同时保留该用户已有的其他自定义角色；拒绝不会改变现有普通用户权限。

平台管理员和超级管理员都不能通过自助注册或角色申请获得。平台管理员角色只能由超级管理员在后台创建用户或调整角色时分配；超级管理员继续由系统初始化和受保护的管理员流程维护。

当前阶段尚未接入邮件验证码和邮件找回密码。登录页“忘记密码”入口应提示用户联系平台管理员；管理员继续通过 `POST /api/users/{userId}/password/reset/` 生成一次性展示的新密码。

#### Step 5: 检查登录状态

前端应用可以通过此接口检查当前用户的登录状态和权限信息。

```javascript
// JavaScript
const response = await fetch("/api/auth/me/", { credentials: "include" });
const data = await response.json();

if (data.authenticated) {
  console.log("当前用户:", data.user.displayName);
  console.log("用户权限:", data.user.permissions);
} else {
  // 未登录，跳转到登录页
}
```

```python
# Python
response = session.get(f"{base_url}/auth/me/")
data = response.json()

if data["authenticated"]:
    print(f"当前用户: {data['user']['displayName']}")
else:
    print("未登录")
```

### 权限系统

平台采用两层权限模型：

**功能权限**：控制用户可以执行的操作类型，如浏览数据、查询数据、加载图层等。

**数据访问权限**：控制用户可以访问的具体数据资源，通过角色进行管理；后端实现仍使用 Django Group。

| 权限标识 | 权限分组 | 功能说明 |
|----------|----------|----------|
| `core.view_operation_logs` | 后台权限 | 查看操作日志 |
| `core.view_system_logs` | 后台权限 | 查看系统日志 |
| `core.manage_system_settings` | 后台权限 | 修改系统设置 |
| `core.manage_data_backup` | 后台权限 | 管理数据备份；默认仅超级管理员角色具备 |
| `core.view_all_operation_logs` | 日志权限 | 查看所有用户日志 |
| `core.view_own_operation_logs` | 日志权限 | 只能查看自己的日志 |
| `core.view_group_operation_logs` | 日志权限 | 查看已配置角色成员的日志 |
| `core.view_dashboard_resource_card` | 概览权限 | 查看概览数据资源卡片 |
| `core.view_dashboard_layer_card` | 概览权限 | 查看概览图层数卡片 |
| `core.view_dashboard_raster_card` | 概览权限 | 查看概览栅格数量卡片 |
| `core.view_dashboard_user_card` | 概览权限 | 查看概览用户数量卡片 |
| `core.view_dashboard_active_users_card` | 概览权限 | 查看概览活跃用户卡片 |
| `core.view_dashboard_system_card` | 概览权限 | 查看概览系统信息 |
| `core.view_data_overview` | 概览权限 | 查看数据概览中的“我可见”范围、兼容旧版全局统计和上传用户统计；“我上传”概览无需此权限 |
| `core.browse_data` | 数据权限 | 浏览数据目录和资源 |
| `core.query_data` | 数据权限 | 执行数据查询 |
| `core.load_vector_layer` | 数据权限 | 加载矢量图层 |
| `core.load_raster_layer` | 数据权限 | 加载栅格图层 |
| `core.custom_symbolization` | 数据权限 | 自定义符号化规则 |
| `core.ai_interpretation` | 数据权限 | 使用 AI 智能解译 |
| `catalog.export_dataresource` | 数据权限 | 导出数据资源 |
| `catalog.add_dataresource` | 数据权限 | 新增数据资源和提交导入 |
| `catalog.view_dataresource` | 数据权限 | 查看存量数据资源清单 |
| `catalog.change_dataresource` | 数据权限 | 编辑数据资源、启停状态、默认可视化和访问范围 |
| `catalog.delete_dataresource` | 数据权限 | 删除数据资源 |
| `catalog.add_workspacescene` | 数据权限 | 新增工程或专题 |
| `catalog.view_workspacescene` | 数据权限 | 查看工程或专题 |
| `catalog.change_workspacescene` | 数据权限 | 编辑工程或专题 |
| `catalog.delete_workspacescene` | 数据权限 | 删除工程或专题 |
| `catalog.add_mapcomposition` | 数据权限 | 新建专题出图稿 |
| `catalog.view_mapcomposition` | 数据权限 | 查看专题出图稿 |
| `catalog.change_mapcomposition` | 数据权限 | 编辑专题出图稿 |
| `catalog.delete_mapcomposition` | 数据权限 | 永久删除专题出图稿、全部版本记录和成果文件 |
| `catalog.export_mapcomposition` | 数据权限 | 导出专题图成果 |
| `catalog.publish_mapcomposition` | 数据权限 | 发布或下架专题图成果 |
| `catalog.view_resultartifact` | 成果权限 | 查看访问角色范围内的导入成果和平台分析成果；进入成果管理的前置权限 |
| `catalog.add_resultartifact` | 成果权限 | 导入成果文件；导入操作还必须同时具备成果查看和发布权限 |
| `catalog.download_resultartifact` | 成果权限 | 下载成果原文件；不影响在线预览权限 |
| `catalog.publish_resultartifact` | 成果权限 | 直接发布、更新发布范围或下架成果文件 |
| `catalog.delete_resultartifact` | 成果权限 | 永久删除本人或管理范围内的成果记录和对应文件 |
| `raster.manage_raster_dataset` | 数据权限 | 管理栅格数据集 |
| `core.manage_feature_permissions` | 人员权限 | 配置角色和功能权限 |
| `core.create_user` | 人员权限 | 在后台新建用户账号 |
| `core.manage_auth` | 人员权限 | 修改认证授权 |

初始化会自动创建 `超级管理员`、`平台管理员`、`科研用户`、`普通用户` 和 `游客` 五个内置角色。`超级管理员` 默认拥有全部平台功能权限；`平台管理员` 负责日常用户、权限、日志和数据运维；`科研用户` 具备上传、导出、专题制图和科研分析能力；`普通用户` 默认用于浏览、查询、加载图层和查看共享成果；`游客` 只通过专用游客会话访问明确公开的内容。对象包含 `游客` 访问角色即表示公开共享，普通用户、科研用户和管理员登录后仍继承该公开可见范围。管理员新建用户时必须指定至少一个角色，自助注册用户始终先加入 `普通用户` 角色。

成果相关默认权限矩阵如下。访问角色决定“能看到哪一项成果”，功能权限决定“能对已经可见的成果做什么”；两者必须同时满足。

| 用户类型 | 专题图成果 | 导入/分析成果 | 默认管理范围 |
|----------|------------|---------------|--------------|
| 超级管理员 | 查看、制图、导出、发布、还原、删除 | 查看、导入、下载、发布/下架、删除 | 全部对象 |
| 平台管理员 | 查看、制图、导出、发布、还原、删除 | 查看、导入、下载、发布/下架、删除 | 全部对象 |
| 科研用户 | 查看、制图、导出、发布、还原、删除 | 查看、导入、下载、发布/下架、删除 | 本人创建对象可管理；他人成果按发布角色查看/下载 |
| 普通用户 | 查看发布范围包含自身角色的专题图 | 查看发布范围包含自身角色的成果 | 默认不可导入、下载、发布或删除 |
| 游客 | 查看明确发布给游客角色的专题图 | 查看明确发布给游客角色的成果 | 默认不可导入、下载、发布或删除 |

成果导入是“导入并正式发布”这一原子业务动作，因此账号必须同时具备 `catalog.view_resultartifact`、`catalog.add_resultartifact` 和 `catalog.publish_resultartifact`。成果下载独立由 `catalog.download_resultartifact` 控制。删除只允许对象所属用户或平台管理主体执行，并仍要求 `catalog.delete_resultartifact`；给普通查看者单独授予删除权限不会扩大其对象管理范围。

用户最终生效的功能权限由角色权限和单用户直授权限合并得到，再扣除用户主动关闭的权限。后台用户列表返回 `groupPermissions` 表示角色继承权限，`directPermissions` 表示单独授予该用户的功能权限，`disabledPermissions` 表示单独关闭权限，`effectivePermissions` 表示最终生效权限；具备 `core.manage_auth` 和 `core.manage_feature_permissions` 的管理员可通过 `POST /api/users/{userId}/permissions/` 写入其他用户的 `directPermissions`、`disabledPermissions` 和 `operationLogGroupIds`。关闭继承权限时不修改角色本身，只写入该用户的单独关闭列表。当前登录用户不能在认证授权页修改自己的权限，应在用户设置中调整主动关闭权限。

角色配置采用二次授权边界：新建角色并设置权限需要同时具备 `core.manage_auth` 和 `core.manage_feature_permissions`；更新角色时，改名或删除等不含 `permissions` 的操作只要求 `core.manage_auth`，请求体只要包含 `permissions` 就必须额外具备 `core.manage_feature_permissions`。五个内置角色均不可删除或重命名；超级管理员角色对非超级管理员隐藏且权限集合锁定，其他内置角色的权限可由具备双权限的管理员调整。

系统账号和管理目标还有独立保护：`游客` 角色只允许专用 guest 账号持有，guest 不能删除、停用、重置密码、修改角色或配置直授权限；平台管理员角色只能由超级管理员分配，平台管理员账号作为受保护目标，非超级管理员不能修改其状态、密码、角色、权限或删除账号。

### 最佳实践

- **CSRF Token 管理**：建议在应用初始化时获取一次 CSRF Token，后续请求自动从 Cookie 中读取。
- **会话持久化**：对于长期使用的应用，设置 `remember: true` 以保持会话。
- **权限检查**：在执行操作前，先检查用户是否具备相应权限，避免不必要的 API 调用。
- **错误处理**：妥善处理 401（未认证）和 403（权限不足）响应，引导用户进行相应操作。

### FAQ

**Q: 为什么收到 401 错误？**

A: 401 表示未认证。可能原因：
- 未登录或会话已过期
- Cookie 未正确携带（确保设置了 `credentials: "include"`）

**Q: 为什么收到 403 错误？**

A: 403 表示权限不足。可能原因：
- 用户不具备该功能权限
- 数据资源设置了访问限制，用户不在允许的角色中

**Q: 如何处理会话过期？**

A: 当收到 401 响应时，应引导用户重新登录。可以在前端全局拦截 401 响应并跳转到登录页。

**Q: 注册时提示"当前系统未开放自助注册"怎么办？**

A: 系统管理员可以在后台配置中关闭注册功能。如需注册，请联系管理员。

### API Reference

详见 API Reference（OpenAPI）。

---

## 3. 数据浏览与目录

### 功能简介

数据目录功能用于组织和浏览平台中的所有数据资源。支持树形目录结构，便于用户按分类查找所需数据。

### 使用场景

- 构建数据目录树导航
- 浏览特定分类下的数据资源
- 按条件筛选数据资源
- 获取数据资源的详细元数据

### 前置条件

- 用户已登录
- 用户具备 `core.browse_data` 权限

### 集成流程

```
获取数据目录树
   ↓
浏览/筛选数据资源
   ↓
获取资源详情（可选）
```

### 实现步骤

#### Step 1: 获取数据目录树

获取所有已激活的数据目录及其关联的数据资源，用于构建前端导航树。

```javascript
// JavaScript
const response = await fetch("/api/catalog/directories/", {
  credentials: "include",
});
const { items } = await response.json();

// items 为目录数组，每个目录包含 resources 字段
items.forEach((dir) => {
  console.log(`目录: ${dir.name}`);
  dir.resources.forEach((res) => {
    console.log(`  - ${res.name} (${res.dataType})`);
  });
});
```

```python
# Python
response = session.get(f"{base_url}/catalog/directories/")
directories = response.json()["items"]

for dir in directories:
    print(f"目录: {dir['name']}")
    for res in dir["resources"]:
        print(f"  - {res['name']} ({res['dataType']})")
```

#### Step 1.1: 获取平台数据分类架构

`GET /api/data-schema/summary/` 返回甲方确认的四大类权威业务分类、数据库分层、核心实体和前端目录树。四个一级类为基础地理信息数据、胡杨生境数据、胡杨空间分布信息和胡杨专题数据；资源只能挂接到可选择的叶节点。该接口只读，需要登录态和 `core.browse_data` 权限。`taxonomyVersion` 标识当前分类版本，`catalogTree` 节点提供稳定 `categoryCode`、完整路径和 `selectable` 状态。

```javascript
// JavaScript
const response = await fetch("/api/data-schema/summary/", {
  credentials: "include",
});
const schema = await response.json();

console.log(schema.domains.map((domain) => domain.name));
console.log(schema.taxonomyVersion);
console.log(schema.catalogTree);
```

该接口用于前端展示“平台到底管理哪些数据”和“这些数据对应哪些核心表”，不替代实际数据资源列表。实际文件、表格、图层仍通过 `DataResource`、`MapLayer`、`RasterDataset` 等既有资源接口管理；标准业务实体通过新增的 `standards`、`ecology`、`omics` 后端模型承接。

#### Step 2: 筛选数据资源

支持按权威业务分类、物理数据类型、空间属性、兼容业务标签、来源、提供者和日期范围筛选数据资源。业务分类与展示能力正交：同一个土壤分类可以同时包含矢量、栅格和普通表格。

```javascript
// JavaScript
  const params = new URLSearchParams({
    spatialClass: "spatial", // 技术展示能力: spatial / non_spatial
    dataType: "vector",      // 数据类型: vector / raster / gene / table / document / image
  categoryCode: "distribution_vector", // 权威业务分类；父节点自动包含后代
  q: "胡杨",              // 名称模糊搜索
});

const response = await fetch(`/api/catalog/resources/?${params}`, {
  credentials: "include",
});
const { items } = await response.json();

// items 只包含业务库登记的 DataResource，id 为 number
```

```python
# Python
response = session.get(f"{base_url}/catalog/resources/", params={
    "spatialClass": "spatial",
    "dataType": "vector",
    "categoryCode": "distribution_vector",
    "q": "胡杨",
})
resources = response.json()["items"]
```

`categoryCode` 是 V1 权威主分类。传一级节点时返回其全部后代资源，传叶节点时精确筛选；`classificationStatus=pending` 可查看尚待人工归类的历史资源。旧 `category` 查询参数在兼容期保留。

`spatialClass` 和 `dataType` 仍用于决定资源怎样存储、能否进入地图工作台；`domainType` 仅作为历史接口和既有可视化模板的兼容标签，不再驱动一级导航。资源响应中的 `categoryPath`、`availableViews` 和 `defaultView` 应作为前端面包屑与动作分发依据。

#### Step 2.1: 查询种质资源清单

`GET /api/germplasm/accessions/` 返回标准化种质资源清单，当前用于承接 DNA 样品清单中的样品编号、采集地点、性别、经纬度、海拔、资源类型和核心资源标记。接口支持 `q`、`taxon`、`site`、`isCore`、`current`、`pageSize` 查询参数；需要登录态和 `core.browse_data` 权限。无数据时返回 `{ items: [], total: 0, current, pageSize }`。

```javascript
// JavaScript
const params = new URLSearchParams({
  q: "GA1",
  taxon: "胡杨",
  site: "阿克苏",
  isCore: "true",
  current: "1",
  pageSize: "20",
});
const response = await fetch(`/api/germplasm/accessions/?${params}`, {
  credentials: "include",
});
const page = await response.json();

page.items.forEach((item) => {
  console.log(item.accessionCode, item.sampleCode, item.sourceSite?.name);
});
```

种质资源通过 `GermplasmAccession` 关联 `BiologicalSample`、`Taxon`、`Site` 和来源 `DataResource`。如果来源资源设置了访问角色，接口会沿用现有数据资源可见性规则；来源资源为空的记录视为尚未完成资源归档，但仍可作为待治理业务记录返回。

#### Step 3: 获取资源详情

获取指定数据资源的完整元数据，包括字段信息、空间范围等。

```javascript
// JavaScript
const resource = items[0];
const response = await fetch(`/api/catalog/resources/${resource.id}/profile/`, {
  credentials: "include",
});
const profile = await response.json();

console.log("资源名称:", profile.resource.name);
console.log("要素数量:", profile.featureCount);
console.log("几何类型:", profile.geometryType);
console.log("空间范围:", profile.bounds);
console.log("字段列表:", profile.fields);
```

```python
# Python
resource_id = 1
response = session.get(f"{base_url}/catalog/resources/{resource_id}/profile/")
profile = response.json()

print(f"资源名称: {profile['resource']['name']}")
print(f"要素数量: {profile['featureCount']}")
print(f"几何类型: {profile['geometryType']}")
print(f"空间范围: {profile['bounds']}")
print(f"字段列表: {profile['fields']}")
```

#### Step 3.1: 获取资源可视化聚合摘要

`GET /api/catalog/resources/{id}/visualization-summary/` 返回右侧数据洞察面板使用的轻量聚合摘要。该接口只读，不返回原始 GeoJSON、栅格像元数组或查询结果数据本体；矢量资源基于 GeoPackage 图层计算分类 TopN、数值分布、空间覆盖和质量问题，栅格资源基于栅格元数据生成分辨率、波段范围和质量提示。接口需要登录态、`core.browse_data` 权限，并沿用资源访问范围校验。

```javascript
// JavaScript
const params = new URLSearchParams({
  topN: "8",
  histogramBins: "8",
});
const response = await fetch(
  `/api/catalog/resources/${resource.id}/visualization-summary/?${params}`,
  { credentials: "include" },
);
const summary = await response.json();

console.log(summary.categoryStats);
console.log(summary.numericStats);
console.log(summary.qualityIssues);
```

该接口对应地理数据右侧栏“第二阶段”的后端聚合能力。第一阶段在前端仍可利用当前已加载图层的 GeoJSON、资源 profile 和栅格 metadata 做即时本地洞察；当后端摘要可用时，前端应优先使用接口返回的聚合结果，并将本地图层数据作为当前视图或选中要素补充。

矢量资源摘要还会返回 `recommendedSymbolizations`。该字段由后端按资源 `domainType`、字段别名命中和字段统计生成推荐符号化模板，当前覆盖种质、个体、种群、群落、野外调查五类含坐标表格数据。接口本身只读，仅要求 `core.browse_data` 和资源访问权限；前端“应用推荐方案”和保存工作台仍沿用现有自定义符号化权限与快照保存流程，不新增独立写接口。

### 最佳实践

- **缓存目录数据**：数据目录结构变化不频繁，建议在前端缓存，减少重复请求。
- **分页处理**：资源列表可能较多，建议配合分页参数使用。
- **字段元数据**：获取资源详情后，可以展示字段说明和样本值，帮助用户理解数据结构。
- **可视化摘要**：右侧数据洞察面板应优先使用可视化聚合摘要接口，避免为了图表展示重复拉取大量原始要素。

### FAQ

**Q: 如何判断一个资源是矢量还是栅格？**

A: 资源的 `dataType` 字段标识数据类型：`vector` 为矢量，`raster` 为栅格。

**Q: 资源的 `isQueryable` 和 `isRenderable` 字段是什么意思？**

A: `isQueryable` 表示该资源支持属性和空间查询（通常是有存储路径的矢量数据）；`isRenderable` 表示该资源支持地图渲染（通常是有存储路径的栅格数据）。

### API Reference

详见 API Reference（OpenAPI）。

---

## 4. 数据导入

### 功能简介

数据导入功能支持将 Excel/CSV 文件中的数据导入到平台中。系统会自动识别地理数据（含经纬度）和非地理数据，并分别存储到不同的数据存储中。

### 使用场景

- 导入野外调查采集的样地数据
- 批量导入研究数据表格
- 更新已有数据集

### 前置条件

- 用户已登录
- 用户具备 `catalog.add_dataresource` 权限
- 准备好要导入的 Excel 或 CSV 文件

`POST /api/catalog/scan/` 是维护性目录扫描入口，不是普通浏览动作，同样要求 `catalog.add_dataresource`；普通浏览用户和游客不能触发。已有目录扫描运行时接口返回 409，调用方应等待当前扫描结束后再刷新资源列表。

### 集成流程

```
上传文件预检
   ↓
数据校验
   ↓
提交导入
```

### 实现步骤

#### Step 1: 上传文件预检

上传文件后，系统会自动解析第一张表，识别字段并推测经纬度列。此步骤不写入数据，仅返回文件结构信息。

```javascript
// JavaScript
const formData = new FormData();
formData.append("file", fileInput.files[0]);

const response = await fetch("/api/catalog/import/preview/", {
  method: "POST",
  credentials: "include",
  headers: { "X-CSRFToken": getCookie("csrftoken") },
  body: formData,
});
const preview = await response.json();

console.log("字段列表:", preview.columns);
console.log("数据行数:", preview.rowCount);
console.log("是否地理数据:", preview.detected.isGeographic);
console.log("推测的经度列:", preview.detected.longitudeColumn);
console.log("推测的纬度列:", preview.detected.latitudeColumn);
```

```python
# Python
with open("survey_data.xlsx", "rb") as f:
    response = session.post(
        f"{base_url}/catalog/import/preview/",
        files={"file": f},
    )
preview = response.json()

print(f"字段列表: {preview['columns']}")
print(f"数据行数: {preview['rowCount']}")
print(f"是否地理数据: {preview['detected']['isGeographic']}")
```

#### Step 2: 数据校验

根据用户选择的导入类型和经纬度列进行数据校验。此步骤不写入数据，仅返回校验结果。

```javascript
// JavaScript
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("payload", JSON.stringify({
  name: "样地调查点",
  importMode: "geographic",      // "geographic" 或 "table"
  tableName: preview.suggestedTableName,
  longitudeColumn: "longitude",  // 地理数据必填
  latitudeColumn: "latitude",    // 地理数据必填
}));

const response = await fetch("/api/catalog/import/validate/", {
  method: "POST",
  credentials: "include",
  headers: { "X-CSRFToken": getCookie("csrftoken") },
  body: formData,
});
const validation = await response.json();

if (validation.validationIssues.length > 0) {
  console.warn("校验问题:", validation.validationIssues);
}
console.log("坐标统计:", validation.coordinateStats);
```

```python
# Python
import json

with open("survey_data.xlsx", "rb") as f:
    response = session.post(
        f"{base_url}/catalog/import/validate/",
        files={"file": f},
        data={"payload": json.dumps({
            "importMode": "geographic",
            "name": "样地调查点",
            "tableName": preview["suggestedTableName"],
            "longitudeColumn": "longitude",
            "latitudeColumn": "latitude",
        })},
    )
validation = response.json()
```

#### Step 3: 提交导入

校验通过后，提交正式导入请求。系统会将数据写入相应的存储位置，并创建新的 `DataResource` 记录。

```javascript
// JavaScript
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("payload", JSON.stringify({
  name: "样地调查点",
  domainType: "field_survey",
  tableName: preview.suggestedTableName,  // 后台存储标识建议值；后端冲突时会自动改写为唯一值
  importMode: "geographic",
  longitudeColumn: "longitude",
  latitudeColumn: "latitude",
  duplicateConfirmed: false,             // 前端显示名已存在时，用户是否已在校验阶段确认继续导入
  includedColumns: ["species", "height", "longitude", "latitude"],  // 可选，省略则导入全部
  fieldMetadata: {
    species: "中文名称：物种；数据来源：野外调查",
    height: "中文名称：株高；单位：m",
  },
  accessGroupIds: [3],               // 额外可见角色；上传者本人和超级管理员始终可见
}));

const response = await fetch("/api/catalog/import/commit/", {
  method: "POST",
  credentials: "include",
  headers: { "X-CSRFToken": getCookie("csrftoken") },
  body: formData,
});
const result = await response.json();

console.log("导入行数:", result.importedRows);
console.log("资源名称:", result.resourceName);
if (result.mode === "geographic") {
  console.log("资源ID:", result.resourceId);
  console.log("GeoPackage 图层名:", result.layerName);
  console.log("空间范围:", result.bounds);
} else {
  console.log("资源ID:", result.resourceId);
  console.log("表名:", result.tableName);
}
```

```python
# Python
import json

with open("survey_data.xlsx", "rb") as f:
    response = session.post(
        f"{base_url}/catalog/import/commit/",
        files={"file": f},
        data={"payload": json.dumps({
            "name": "样地调查点",
            "domainType": "field_survey",
            "tableName": preview["suggestedTableName"],
            "importMode": "geographic",
            "longitudeColumn": "longitude",
            "latitudeColumn": "latitude",
            "duplicateConfirmed": False,
            "fieldMetadata": {
                "species": "中文名称：物种；数据来源：野外调查",
                "height": "中文名称：株高；单位：m",
            },
        })},
    )
result = response.json()
print(f"导入行数: {result['importedRows']}")
print(f"资源名称: {result['resourceName']}")
if result["mode"] == "geographic":
    print(f"资源ID: {result['resourceId']}")
    print(f"GeoPackage 图层名: {result['layerName']}")
else:
    print(f"资源ID: {result['resourceId']}")
```

### 数据导入模式

**地理数据（Geographic）**：包含经纬度坐标的数据，系统会将其写入统一 GeoPackage 矢量文件，并创建新的 `DataResource`。提交响应返回 `mode: "geographic"`、`resourceId`、`resourceName`、`layerName`、`tableName`、`bounds`、`coordinateStats` 和 `validationIssues`。资源列表会显示 `resourceName` 对应的用户填写数据名称，`tableName/layerName` 是后端生成的唯一存储标识。

**非地理数据（Table）**：不包含坐标信息的纯表格数据，系统会将其写入 SQLite 数据库，并创建新的 `DataResource`。提交响应返回 `mode: "table"`、`resourceId`、`resourceName`、`tableName`，且 `layerId` 和 `coordinateStats` 为 `null`。

后台存储标识每次预检都会生成不同建议值；提交时若后端发现该标识已被占用，会自动改写为唯一 GeoPackage 图层名或 SQLite 表名。重复目标检测按前端显示的数据名称执行：预检使用 `suggestedName`，校验和提交使用 payload 中的 `name`。`duplicateTarget.targetType` 固定为 `data_resource_name`。提交时若同名数据已存在且 `duplicateConfirmed=false`，后端会以 `400` 和 `duplicate_target` 问题阻止导入；用户在数据校验阶段确认重复名称并传入 `duplicateConfirmed=true` 后，后端允许继续导入并创建新的数据资源记录和唯一后台存储标识，旧数据资源不会被覆盖。`domainType` 必须来自 `DataDomainType`，可选择 `other` 作为暂未归入专门专题的数据类型；缺失或无效编码都会返回结构化 400 错误。

### 字段元数据规范

建议为每个字段提供以下元数据信息：

- 中文名称
- 单位（如有）
- 计算方式（如有）
- 数据来源

格式示例：`"中文名称：株高；单位：m；数据来源：野外调查"`

### 最佳实践

- **预检先行**：在正式导入前，务必先调用预检接口了解文件结构。
- **后台存储标识规范**：`tableName` 仅支持英文字母、数字和下划线，且以字母或下划线开头。前端应优先使用预检返回的 `suggestedTableName`，不要用显示名手写生成。
- **字段选择**：使用 `includedColumns` 参数只导入需要的字段，减少数据冗余。
- **元数据完善**：为字段提供详细的元数据说明，便于其他用户理解数据含义。

### FAQ

**Q: 导入时提示"经纬度不是小数格式"怎么办？**

A: 确保经纬度列使用十进制小数格式，如 `87.600`、`43.800`，而非度分秒格式。

**Q: 如何处理坐标不确定性警告？**

A: 当坐标不确定性最大/最小差距超过 200 倍时会触发警告。可以在导入请求中设置 `ignoreCoordinateUncertainty: true` 来忽略此警告。

**Q: 同名数据已存在怎么办？**

A: 在数据校验阶段确认重复名称后，提交时设置 `duplicateConfirmed: true` 继续导入同名显示数据。后台存储标识会保持唯一，已有数据不会被覆盖。

**Q: Excel 文件有多个工作表怎么办？**

A: 系统只读取 Excel 文件的第一张工作表。如需导入其他工作表，请将其移至第一张或单独保存为新文件。

### API Reference

详见 API Reference（OpenAPI）。

---

## 5. 数据查询

### 功能简介

数据查询功能支持对矢量数据资源执行属性和空间联合查询，返回 GeoJSON 格式的查询结果，可直接用于地图可视化。

### 使用场景

- 按属性条件筛选矢量数据
- 按空间范围查询数据
- 组合属性和空间条件进行复杂查询
- 获取查询结果用于地图展示或数据分析

### 前置条件

- 用户已登录
- 用户具备 `core.query_data` 和 `core.load_vector_layer` 权限
- 目标数据资源为矢量类型且 `isQueryable` 为 `true`

### 集成流程

```
确定查询目标
   ↓
构建查询条件
   ↓
执行查询
   ↓
处理结果
```

### 实现步骤

#### Step 1: 构建查询条件

查询条件包含属性过滤器和空间过滤器两部分。

```javascript
// JavaScript
const queryBody = {
  // 属性过滤条件（可选）
  attributeFilters: [
    {
      field: "species",           // 字段名
      operator: "eq",             // 操作符: eq/ne/gt/gte/lt/lte/contains/between
      value: "Populus euphratica",
    },
    {
      field: "area_ha",
      operator: "between",        // between 操作符需要 value 和 valueTo
      value: "10",
      valueTo: "100",
    },
  ],
  // 空间过滤条件（可选）
  spatialFilter: {
    mode: "rectangle",            // rectangle/circle/ellipse/polygon
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [87.5, 41.5],
          [88.0, 41.5],
          [88.0, 42.0],
          [87.5, 42.0],
          [87.5, 41.5],
        ],
      ],
    },
  },
  limit: 1000, // 返回记录上限，默认取系统配置
};
```

#### Step 2: 执行查询

```javascript
// JavaScript
const resource = selectedResource;
const response = await fetch(`/api/catalog/resources/${resource.id}/query/`, {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify(queryBody),
});
const result = await response.json();

console.log("总记录数:", result.totalCount);
console.log("返回记录数:", result.returnedCount);
console.log("是否超过上限:", result.limitExceeded);
console.log("返回结果范围:", result.bounds);
console.log("查询耗时(ms):", result.elapsedMs);
console.log("GeoJSON:", result.geojson);
```

```python
# Python
resource_id = 1
response = session.post(
    f"{base_url}/catalog/resources/{resource_id}/query/",
    json={
        "attributeFilters": [
            {"field": "species", "operator": "eq", "value": "Populus euphratica"},
        ],
        "spatialFilter": None,
        "limit": 1000,
    },
)
result = response.json()

print(f"总记录数: {result['totalCount']}")
print(f"返回记录数: {result['returnedCount']}")
print(f"是否超过上限: {result['limitExceeded']}")
print(f"返回结果范围: {result['bounds']}")
print(f"查询耗时(ms): {result['elapsedMs']}")
print(f"GeoJSON: {result['geojson']}")
```

业务库资源使用 `/api/catalog/resources/{resourceId}/query/`，`QueryResponse.resourceId` 固定为数值型资源 ID。响应中的 `limitExceeded` 表示命中数量超过返回上限，`bounds` 是本次返回有效要素的 WGS84 边界，`elapsedMs` 是后端查询耗时，前端空间查询工作台可用这些字段展示真实命中摘要、截断状态和定位范围。生产示例的查询硬上限为 5,000 条；空间候选在服务端分块过滤，单个 Web 进程同时只执行一个重型查询。繁忙时接口返回 503 和 `Retry-After`，客户端应按该响应头退避，不能立即并发重试；查询 JSON 超过 1 MiB 返回 413。

#### Step 3: 处理查询结果

查询结果为标准的 GeoJSON FeatureCollection 格式，可直接用于 Mapbox GL JS 等地图库。

```javascript
// JavaScript - 在地图上展示查询结果
map.addSource("query-result", {
  type: "geojson",
  data: result.geojson,
});

map.addLayer({
  id: "query-result-layer",
  type: "fill",
  source: "query-result",
  paint: {
    "fill-color": "#228B22",
    "fill-opacity": 0.5,
  },
});
```

### 属性过滤操作符

| 操作符 | 说明 | 示例 |
|--------|------|------|
| `eq` | 等于 | `value: "胡杨"` |
| `ne` | 不等于 | `value: "灌木"` |
| `gt` | 大于 | `value: "100"` |
| `gte` | 大于等于 | `value: "100"` |
| `lt` | 小于 | `value: "50"` |
| `lte` | 小于等于 | `value: "50"` |
| `contains` | 包含 | `value: "杨"` |
| `between` | 范围 | `value: "10", valueTo: "100"` |

### 空间过滤模式

| 模式 | 说明 | 几何类型 |
|------|------|----------|
| `rectangle` | 矩形范围 | Polygon |
| `circle` | 圆形范围 | Point + radius |
| `ellipse` | 椭圆范围 | Point + axes |
| `polygon` | 多边形范围 | Polygon |

### 非地理表格查询与分析

`/nongeo` 左侧资源列表已经接入 `GET /api/catalog/resources/?spatialClass=non_spatial`，支持真实资源加载、业务类型筛选、关键词过滤和手动刷新。普通 Excel/CSV 在未识别到经纬度列时默认以 `table` 入库，并只出现在该列表；地理工作台使用 `spatialClass=spatial`，不会再显示此类资源。

非地理工作台使用两个已定稿接口，均要求登录、`core.query_data`、启用的 `table` 或 `gene` 资源以及对象访问范围：

- `GET /api/catalog/resources/{id}/nongeo-analysis/`：返回资源元数据、字段画像、分类/数值分布、最多六个数值字段的相关矩阵、前 80 条明细预览和分析提示。最多分析 10,000 条真实记录；`summary.rowCount` 始终保留全量计数，`analyzedRowCount` 和 `sampled` 明确统计口径。
- `POST /api/catalog/resources/{id}/nongeo-query/`：分页返回真实明细，`limit` 范围 1–500（默认 80），`offset` 范围 0–10,000,000；`sortDirection` 仅允许 `asc|desc`，`sortField` 必须是实际字段。SQLite 后台表使用字段白名单，不能把客户端字段名直接拼入 SQL。

在线分析支持 SQLite 后台表以及 CSV、TSV、XLS、XLSX、FASTA、FASTQ、VCF、GFF/GFF3、GB/GBK 文件。直接文件分析的大小上限取系统上传限制与 64 MB 的较小值，超过上限应先导入平台表格库。参数错误、不支持的资源/文件格式返回 400，未登录返回 401，功能或对象权限不足返回 403，资源不存在或未启用返回 404。

```javascript
const analytics = await fetch(`/api/catalog/resources/${resourceId}/nongeo-analysis/`, {
  credentials: "include",
}).then((response) => response.json());

const page = await fetch(`/api/catalog/resources/${resourceId}/nongeo-query/`, {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({ limit: 80, offset: 0, sortField: "height", sortDirection: "desc" }),
}).then((response) => response.json());
```

### 最佳实践

- **限制查询范围**：使用 `limit` 参数控制返回记录数，避免一次性加载过多数据。
- **组合条件**：结合属性和空间过滤，精确定位所需数据。
- **处理警告**：检查响应中的 `warnings` 字段，了解是否有数据被忽略。
- **处理截断**：检查响应中的 `limitExceeded` 字段；为 true 时应提示用户缩小空间范围或提高筛选精度。
- **字段验证**：查询前可通过资源详情接口确认字段名称和类型。

### FAQ

**Q: 查询返回的数据不完整怎么办？**

A: 检查响应中的 `limitExceeded`、`returnedCount` 和 `totalCount`。如果 `limitExceeded=true`，说明达到了查询上限；`limit` 不能突破平台配置的硬上限，应缩小空间范围或增加属性条件。

**Q: 为什么查询结果中没有某些数据？**

A: 后端会自动忽略无几何、经度越界（-180到180之外）、纬度越界（-90到90之外）的数据。检查响应中的 `warnings` 字段了解详情。

**Q: 如何查询非矢量数据？**

A: 矢量查询接口返回 GeoJSON，仅支持空间或矢量属性查询。表格和基因资源应使用 `/nongeo-analysis/` 获取字段画像与统计，再使用 `/nongeo-query/` 分页读取真实明细；不要把非空间资源提交到矢量 `/query/` 接口。

### API Reference

详见 API Reference（OpenAPI）。

---

## 6. 数据导出

### 功能简介

数据导出功能支持将平台中的数据资源导出为标准 GIS 格式，矢量图层可选择 GeoJSON 或 Shapefile，栅格图层导出为 GeoTIFF，最终打包为 ZIP 文件下载。同步和异步导出 JSON 请求体均限制为 10 MiB；服务端直接把 ZIP 写到临时文件并以文件流下载，不在 Web 进程内构造完整 ZIP bytes 副本。

### 使用场景

- 导出查询结果用于本地分析
- 导出数据供其他 GIS 软件使用
- 批量导出多个图层数据
- 导出带有坐标系转换的数据

### 前置条件

- 用户已登录
- 用户具备 `catalog.export_dataresource` 权限

### 集成流程

```
选择导出数据
   ↓
配置导出参数
   ↓
执行导出（同步或异步）
   ↓
下载文件
```

### 实现步骤

#### Step 1: 同步导出

适用于小规模数据导出，直接返回 ZIP 文件。

```javascript
// JavaScript
const exportBody = {
  epsg: 4326,           // 目标坐标系，默认 4326
  reproject: true,      // 是否重投影
  clip: false,          // 是否裁剪
  format: "shapefile",  // 矢量导出格式：shapefile 或 geojson
  items: [
    {
      layerType: "vector",
      name: "胡杨林分布",
      resourceId: 1,
      geojson: null,    // 可传入查询结果进行筛选导出
    },
    {
      layerType: "raster",
      name: "DEM高程",
      resourceId: 5,
      datasetId: 1,
    },
  ],
};

const response = await fetch("/api/catalog/export/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify(exportBody),
});

// 处理文件下载
const blob = await response.blob();
const url = URL.createObjectURL(blob);
const a = document.createElement("a");
a.href = url;
a.download = "export.zip";
a.click();
```

导出的 ZIP 中，矢量图层会包含空间文件（GeoJSON 或 Shapefile 组件文件）以及同名 `*-attributes.csv` 属性表。空间查询结果传入 `items[].geojson` 时，查询命中的 `features[].properties` 会写入该属性表，便于在 Excel/WPS 或统计软件中继续分析。

```python
# Python
response = session.post(
    f"{base_url}/catalog/export/",
    json={
        "epsg": 4326,
        "reproject": True,
        "clip": False,
        "format": "geojson",
        "items": [
            {
                "layerType": "vector",
                "name": "胡杨林分布",
                "resourceId": 1,
            },
        ],
    },
)

# 保存文件
with open("export.zip", "wb") as f:
    f.write(response.content)
```

#### Step 2: 异步导出

适用于大规模数据导出，提交任务后轮询状态。

```javascript
// JavaScript
const response = await fetch("/api/catalog/export/async/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify(exportBody),
});
const job = await response.json();

// 顺序轮询任务状态：前一次请求完成后再等待，避免慢请求重叠。
const controller = new AbortController();
const deadline = Date.now() + 120_000;
while (Date.now() < deadline) {
  await new Promise((resolve) => setTimeout(resolve, 1000));
  const statusRes = await fetch(`/api/raster/jobs/${job.id}/`, {
    credentials: "include",
    signal: controller.signal,
  });
  const status = await statusRes.json();

  if (status.status === "ready") {
    const downloadUrl = status.result.downloadUrl;
    window.open(downloadUrl);
    break;
  } else if (status.status === "failed") {
    console.error("导出失败:", status.error);
    break;
  }
}
controller.abort();
```

```python
# Python
import time

response = session.post(f"{base_url}/catalog/export/async/", json=export_body)
job = response.json()

# 轮询任务状态
while True:
    status = session.get(f"{base_url}/raster/jobs/{job['id']}/").json()
    if status["status"] == "ready":
        download_url = status["result"]["downloadUrl"]
        # 下载文件
        file_response = session.get(f"{base_url}{download_url}")
        with open("export.zip", "wb") as f:
            f.write(file_response.content)
        break
    elif status["status"] == "failed":
        print(f"导出失败: {status['error']}")
        break
    time.sleep(1)
```

### 最佳实践

- **选择合适的导出方式**：小数据量使用同步导出，大数据量使用异步导出。
- **坐标系转换**：导出时指定目标 EPSG 代码，系统会自动进行坐标系转换。
- **筛选导出**：结合查询结果，只导出需要的数据子集。
- **异步轮询**：异步导出必须使用完成后再延时的顺序轮询，设置 AbortController 和总超时；不要用异步 `setInterval` 产生重叠请求。

### FAQ

**Q: 同步导出和异步导出有什么区别？**

A: 同步导出直接返回文件，适用于小数据量；异步导出返回任务 ID，通过轮询获取结果，适用于大数据量。

**Q: 导出的文件格式是什么？**

A: 矢量数据可导出为 Shapefile 或 GeoJSON，栅格数据导出为 GeoTIFF，均打包为 ZIP 文件。

**Q: 如何导出查询结果？**

A: 在导出请求的 `items` 中传入查询返回的 `geojson` 数据，系统会只导出这些数据。

### API Reference

详见 API Reference（OpenAPI）。

---

## 7. 地图图层

### 功能简介

地图图层功能用于管理和获取平台中的地图图层信息，支持矢量图层和栅格图层。图层是数据资源在地图上的可视化表现形式。

`GET /api/layers/` 只返回当前用户可见的启用图层。图层自身可见且关联数据资源也对当前用户可见时才会返回；如果关联数据资源被角色访问范围隐藏，即使图层自身未设置访问角色也不会出现在列表中。目录接口 `/api/catalog/directories/` 返回目录下资源时同样会按当前用户的数据资源可见范围裁剪。

### 使用场景

- 构建地图图层列表
- 加载矢量图层要素到地图
- 管理图层的显示状态和样式

### 前置条件

- 用户已登录
- 用户具备 `core.browse_data` 权限（浏览图层列表）
- 用户具备 `core.load_vector_layer` 权限（加载矢量要素）

### 集成流程

```
获取图层列表
   ↓
加载图层数据
   ↓
渲染到地图
```

### 实现步骤

#### Step 1: 获取图层列表

```javascript
// JavaScript
const response = await fetch("/api/layers/", { credentials: "include" });
const { items } = await response.json();

items.forEach((layer) => {
  console.log(`图层: ${layer.name}`);
  console.log(`  类型: ${layer.layerType}`);
  if ("defaultVisible" in layer) {
    console.log(`  默认可见: ${layer.defaultVisible}`);
    console.log(`  默认透明度: ${layer.defaultOpacity}%`);
  } else {
    console.log(`  要素数: ${layer.featureCount}`);
    console.log(`  几何类型: ${layer.geometryType}`);
  }
});
```

```python
# Python
response = session.get(f"{base_url}/layers/")
layers = response.json()["items"]

for layer in layers:
    print(f"图层: {layer['name']}")
    print(f"  类型: {layer['layerType']}")
    if "defaultVisible" in layer:
        print(f"  默认可见: {layer['defaultVisible']}")
    else:
        print(f"  要素数: {layer['featureCount']}")
```

#### Step 2: 加载矢量图层要素

```javascript
// JavaScript
const layerName = "survey_points_2026";
const response = await fetch(
  `/api/layers/${encodeURIComponent(layerName)}/features/?limit=10000`,
  {
    credentials: "include",
  },
);
const geojson = await response.json();

// 添加到地图
map.addSource(`layer-${layerName}`, {
  type: "geojson",
  data: geojson,
});

map.addLayer({
  id: `layer-${layerName}`,
  type: "fill",
  source: `layer-${layerName}`,
  paint: {
    "fill-color": "#228B22",
    "fill-opacity": 0.6,
  },
});
```

### 图层类型

**矢量图层（Vector）**：来自业务库 `MapLayer`，关联正式 `DataResource`，属性查询和空间查询通过 `/api/catalog/resources/{resourceId}/...` 完成。

**栅格图层（Raster）**：来自业务库 `MapLayer`，包含栅格数据，通过瓦片服务进行渲染。

### 符号化配置

图层的符号化配置存储在 `symbolization` 字段中，包含：

- `opacity`：图层透明度百分比。
- `pointMode`：点图层基础表达方式，支持 `circle`、`symbol`、`heatmap`。
- `renderer.type=single`：单一符号渲染，继续使用 `circle`、`symbol`、`line`、`fill` 中的基础样式。
- `renderer.type=uniqueValue`：按字段唯一值分类渲染，`field` 指定分类字段，`classes[].values` 可包含多个原始字段值，用于“分类值合并/别名归一化”。
- `renderer.type=graduated`：按连续数值字段分级渲染，`field` 指定海拔、NDVI、盐分等字段，`method` 支持 `equalInterval` 等距分级、`quantile` 分位数分级和 `manual` 自定义分级，`classes[].min/max` 记录区间端点。
- `renderer.classes[].iconImage`：平台内置图标必须使用 `gm-*` 英文 ID。前端在写入 Mapbox `icon-image` 前会按“图标 ID + 颜色”生成运行时图片 ID，并通过 `map.addImage()` 注册。
- `renderer.defaultClass`：未匹配值、空值或其他值的默认图例类，避免数据因未分类而不可见。
- `cluster.enabled`：点图层是否启用 Mapbox source 聚合，默认 `false`。
- `cluster.maxZoom`：聚合生效的最大瓦片缩放级别，默认 `12`。
- `cluster.radius`：聚合半径，默认 `50`。

平台当前为五类含坐标表格业务数据内置推荐默认模板。前端加载图层时会先根据 `domainType` 套用首选默认方案；打开符号化面板时再从 `GET /api/catalog/resources/{id}/visualization-summary/` 读取后端推荐模板，供用户一键应用并继续细调。

| 业务类型 | 首选字段 | 默认表达 | 图标 |
| --- | --- | --- | --- |
| 种质数据 `germplasm` | `性别` | 唯一值分类，合并雌雄别名 | `gm-tree` |
| 个体数据 `individual` | `物种中文名`，备用 `科中文名` | 唯一值分类 | `gm-species` |
| 种群数据 `population` | `重要值`，备用 `密度` | 数值分级，备用生境分类 | `gm-populus` |
| 群落数据 `community` | `Shannon 多样性指数`，备用 `物种丰富度` | 数值分级，备用样方分组或盐分分级 | `gm-community` |
| 野外调查数据 `field_survey` | `栖息地类型`，备用 `分布方式` | 唯一值分类，备用重要值/密度分级 | `gm-sample` |

种质数据模板 `germplasm.dna-sex-tree.v1` 会使用树形图标按 `性别` 唯一值分类：

| 图例类别 | 原始值 | 图标 | 默认颜色 |
| --- | --- | --- | --- |
| 雌性 | `雌株`、`雌株珠`、`雌性`、`♀` | `gm-tree` | `#D65A8A` |
| 雄性 | `雄株`、`雄性`、`♂` | `gm-tree` | `#2878B5` |
| 未知/其他 | 未匹配值和空值 | `gm-tree` | `#8A8F98` |

该模板不修改原始属性值，只在 `symbolization.renderer.classes[].values` 中记录“多个原始值映射到同一图例类别”的关系。用户具备 `core.custom_symbolization` 权限时，可在前端符号化面板中调整类别名称、颜色、图标、大小、显隐和原始值归并关系；保存工作台快照时会保存修改后的 `symbolization`。

数值分级不新增后端接口或数据库结构。前端基于当前加载要素的字段统计生成区间、计数和默认无数值类，并在 Mapbox 中转换为 `case` 表达式；后端继续按 JSON 对象保存和序列化 `symbolization`。用户具备 `core.custom_symbolization` 权限时，可调整分级字段、方法、级数、小数位、色带、区间范围、颜色、图标、大小和显隐。选择 `manual` 后，平台不再自动重算区间边界，只根据用户维护的 `classes[].min/max` 刷新计数和地图表达式。

### 最佳实践

- **按需加载**：只加载用户可见范围内的图层，减少数据传输量。
- **透明度控制**：通过图层透明度配置，实现多图层叠加显示。
- **错误处理**：加载图层时注意处理权限不足（403）和图层不存在（404）的情况。
- **工作台保存边界**：图层树、排序、显隐和符号化的实时保存只写入浏览器本地 IndexedDB，防止刷新或切换界面后清空；服务器端仅在用户显式“保存为工程”或“保存为专题”时写入。

### 工程和专题快照

工程和专题是服务器端轻量工作台快照，保存当前图层组、顺序、查询条件、空间范围、资源引用、可视化方案、栅格渲染引用元数据、底图和地图视图。可见性由所属项目决定，历史 `accessGroupIds` 不改变范围；服务器端快照不能保存原始 GeoJSON 要素集合、属性表行或查询结果数据本体，矢量图层恢复时按资源引用和查询条件重新查询。

关键接口：

- `GET /api/catalog/workspaces/?kind=project|topic&q=关键词&limit=24&offset=0`：返回当前项目中可访问的启用工程摘要，含 total/limit/offset，不含 snapshot；limit 为 1–100。需要 `catalog.view_workspacescene`；超管在业务工作台也只操作当前项目。
- `POST /api/catalog/workspaces/`：在当前项目创建工程或专题，需要 `catalog.add_workspacescene`，提交 kind/name/description/snapshot；快照的可选 basemapId 保存底图选择。
- `GET /api/catalog/workspaces/{id}/`：读取当前项目中有权访问的单个启用工程及完整 snapshot，需要 `catalog.view_workspacescene`。
- `POST /api/catalog/workspaces/{id}/`：普通工作台保留所有者编辑规则；更新必须提供最后读取的 expectedUpdatedAt，陈旧版本返回 409，不覆盖内容。名称、说明、类型和快照更新需要 `catalog.change_workspacescene`；提交 `{"action":"delete"}` 删除需要 `catalog.delete_workspacescene`。后台更新也要求版本字段。被出图稿引用的工程删除转为停用，保留成果来源。历史角色字段不改变可见性。

`snapshot` 是前端工作台轻量 JSON 对象。后端做可见范围、所有权、JSON 对象、请求体大小和嵌入原始数据检查；出现 `geojson` 或 `FeatureCollection.features` 等原始要素集合时返回 400，超大请求体返回 413。共享用户只能加载，不能在普通工作台修改或删除他人对象；禁用对象仅保留在后台管理中。

### 专题制图与成果版本

正式专题制图与工程/专题工作台快照分离。`WorkspaceScene(kind=project)` 保存可恢复的地图工作状态；`MapComposition` 保存纸张、地图框、范围、图例、指北针、比例尺、区位副图、格网、数据来源和制图说明等轻量版式；`MapCompositionVersion` 保存每次正式生成的不可变成果版本和版式快照。

- `GET /api/catalog/map-compositions/`：列出当前用户拥有的出图稿，可按 `projectId` 和 `status=draft|completed|published` 筛选，需要 `catalog.view_mapcomposition`。
- `POST /api/catalog/map-compositions/`：从当前用户拥有且启用的 project 工程创建出图稿，需要 `catalog.add_mapcomposition`。
- `GET /api/catalog/map-compositions/{compositionId}/`：读取出图稿和版本，需要 `catalog.view_mapcomposition`。
- `POST /api/catalog/map-compositions/{compositionId}/`：`action=update` 更新轻量版式，需要 `catalog.change_mapcomposition`；发布/下架使用独立接口并需要 `catalog.publish_mapcomposition`；`action=delete` 永久删除专题、版本记录和成果文件，需要 `catalog.delete_mapcomposition`。
- `POST /api/catalog/map-compositions/{compositionId}/versions/`：以 multipart 上传前端渲染的 PNG 母图和 JSON `payload`，后端校验格式、DPI、宽高和最大像素后，在 TOML 驱动的 `app_data/exports/map-compositions/{id}/v{version}/` 下生成 PNG、JPG 或 PDF，需要 `catalog.export_mapcomposition`。
- `GET /api/catalog/map-compositions/{compositionId}/versions/{versionNumber}/file/?variant=preview|artifact`：预览需要查看权限；正式成果下载还需要导出权限。

版式 JSON 最大 512KB，不得包含 `FeatureCollection.features`、原始属性表、Data URL 或 Blob URL。单边像素不得超过 8192，总像素不得超过 3600 万。前端 Mapbox 离屏渲染只组合当前已授权图层；栅格数据继续消费后端 XYZ 瓦片，禁止在浏览器中读取原始栅格重新符号化。出图稿的新建、更新、版本生成、发布、下架和归档均写入 `OperationLog`，结构化目标类型为 `map_composition`。

### FAQ

**Q: 矢量图层和栅格图层有什么区别？**

A: 矢量图层包含离散的几何要素（点、线、面），支持属性查询；栅格图层包含连续的像素数据，通过瓦片服务渲染。

**Q: 如何判断图层是否可查询？**

A: 检查图层关联的数据资源的 `isQueryable` 字段。

### API Reference

详见 API Reference（OpenAPI）。

---

## 8. 栅格数据管理

### 功能简介

栅格数据管理功能用于导入、处理和渲染栅格数据（如 DEM、遥感影像等）。系统会自动将栅格文件预处理为 COG（Cloud Optimized GeoTIFF）格式，并提供瓦片服务。

### 使用场景

- 导入新的栅格数据文件
- 扫描未处理的栅格文件
- 渲染栅格数据为地图瓦片
- 自定义栅格符号化规则

### 前置条件

- 用户已登录
- 用户具备 `raster.manage_raster_dataset` 或 `catalog.change_dataresource` 权限
- 栅格文件可通过后台页面上传，或已放置在研究数据目录中供脚本按路径导入

### 集成流程

```
导入/扫描栅格文件
   ↓
等待预处理完成
   ↓
注册渲染样式；分类栅格等待完整静态金字塔发布
   ↓
加载瓦片到地图
```

### 实现步骤

#### Step 1: 导入栅格文件

支持两种导入方式。后台管理页面使用 `multipart/form-data` 上传本地文件；服务端保存到科研数据根目录 `raster/original/uploaded/` 后立即提交异步预处理任务。运维脚本也可以继续传入研究数据目录中已有栅格文件的 `sourcePath`。两种方式都通过 `/api/raster/jobs/{job_id}/` 轮询 `progressPercent`、`messages` 和最终状态。

`name` 始终是前端显示的数据名称，应写入 `RasterDataset.name`、`DataResource.name` 和 `MapLayer.name`。后端为避免文件冲突将浏览器上传源文件保存为 `uploaded/<uuid><suffix>`，该文件名只属于 `source_relative_path`、`processed_relative_path`、`code` 等后台存储标识，不包含原始文件名，也不得展示给用户；如果 `name` 为空，浏览器上传栅格默认回退到原始上传文件名。

栅格上传必须在前后端同时校验限制。前端使用系统启动配置 `limits.uploadMaxMb` 检查文件大小，并使用 `limits.maxRasterSidePixels` 和 `geotiff.js` 读取本地栅格首图像尺寸；文件大小超过配置上限、宽或高超过配置的单边像素上限、或无法读取尺寸时，不提交上传。后端仍是最终校验边界：上传文件大小超过 `application.limits.upload_max_mb`、源栅格宽或高超过 `application.limits.max_raster_side_pixels`、或无法读取栅格尺寸时，返回 `400 {"detail":"..."}`，不会创建异步任务；按 `sourcePath` 导入和目录扫描同样复用像素尺寸限制。可配置上传上限的硬范围为 1–1024 MB；1024 MB 主要服务于落盘处理的栅格和独立成果文件。矢量导入因 GeoPandas 需要整层读入内存，继续取平台配置与 120 MB 的较小值；表格在线解析继续取平台配置与 16 MB 的较小值；专题出图 PNG 固定使用独立 128 MB 上限并在完整解码前检查字节数和像素边界，不随 `uploadMaxMb` 变化。

```javascript
// JavaScript - 浏览器上传本地栅格文件
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("name", "2026 胡杨林遥感影像");

const response = await fetch("/api/raster/import/", {
  method: "POST",
  credentials: "include",
  headers: {
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: formData,
});
const job = await response.json();
console.log("任务ID:", job.id);
```

```javascript
// JavaScript - 导入研究数据目录中已有文件
const response = await fetch("/api/raster/import/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({
    sourcePath: "raw/new_dem.tif",  // 相对于研究数据根目录的路径
    name: "新 DEM 数据",
    async: true,                    // 推荐使用异步模式
  }),
});
const job = await response.json();
console.log("任务ID:", job.id);
```

```python
# Python - 导入研究数据目录中已有文件
response = session.post(f"{base_url}/raster/import/", json={
    "sourcePath": "raw/new_dem.tif",
    "name": "新 DEM 数据",
    "async": True,
})
job = response.json()
print(f"任务ID: {job['id']}")
```

#### Step 2: 扫描栅格源目录

扫描研究数据目录中的未处理栅格文件，自动创建数据集。调用方必须具备 `raster.manage_raster_dataset` 或 `catalog.change_dataresource`；普通浏览用户和游客不能触发。同一进程已有排队或运行中的扫描时，后端返回同一个活动任务，前端继续轮询该任务即可。

```javascript
// JavaScript
const response = await fetch("/api/raster/scan/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({}),
});
const job = await response.json();
```

```python
# Python
response = session.post(f"{base_url}/raster/scan/", json={})
job = response.json()
```

#### Step 3: 注册渲染样式

为栅格图层注册瓦片样式，获取 XYZ 瓦片 URL、原生缩放范围和客户端采样规则。分类栅格会在导入时为默认样式预生成完整的最近邻 MBTiles 金字塔；更改唯一值颜色后，异步渲染任务也必须等新样式的全部层级完成并原子发布后才返回 `ready`。连续栅格和普通影像仍按请求动态渲染。

```javascript
// JavaScript - 使用默认样式
const response = await fetch("/api/raster/render/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({
    layerId: 3,
    rulesMode: "default",
  }),
});
const renderResult = await response.json();

// 使用瓦片 URL
const tileUrl = renderResult.tileUrl;
// 例如: /api/raster/tiles/1/a1b2c3d4/{z}/{x}/{y}.png
```

```python
# Python
response = session.post(f"{base_url}/raster/render/", json={
    "layerId": 3,
    "rulesMode": "default",
})
render_result = response.json()
tile_url = render_result["tileUrl"]
```

#### Step 4: 在地图上加载瓦片

```javascript
// JavaScript
map.addSource("raster-tiles", {
  type: "raster",
  tiles: [`${baseUrl}${renderResult.tileUrl}`],
  tileSize: 256,
  bounds: renderResult.bounds4326,
  minzoom: renderResult.minZoom,
  maxzoom: renderResult.maxZoom,
});

const categorical = renderResult.tileSampling === "nearest";
map.addLayer({
  id: "raster-layer",
  type: "raster",
  source: "raster-tiles",
  paint: {
    "raster-opacity": categorical ? 1 : 0.8,
    "raster-resampling": renderResult.tileSampling,
    "raster-fade-duration": categorical ? 0 : 300,
  },
});
```

前端加载 XYZ 栅格源时必须同时传入 `bounds4326`、`minZoom` 和 `maxZoom`。这样既避免在影像范围外反复请求，也避免 Mapbox 按默认 z22 请求并长时间使用父瓦片兜底。`tileSampling=nearest` 必须在第一次 `addLayer` 时就设置，同时关闭分类栅格淡入；不得等 profile 或符号化面板异步完成后再切换。项目补丁还会让 nearest 路径跳过 GPU mipmap，并把当前、父级、回退和极区纹理的各向异性过滤固定为 1。后端对不在栅格空间范围内的瓦片请求返回 `204 No Content`；对超过分类栅格原生最大级别、过期样式或尚未完整发布的分类静态金字塔返回 `404`，不会动态补画分类瓦片。

分类栅格 COG 的重投影和内部概览统一使用最近邻，显式传播 NoData。启动扫描会识别缺少当前预处理版本标记的既有分类 COG，并保留名称、权限、业务分类和当前唯一值规则后重新处理；仅升级前端包或更换瓦片 URL 不能修复历史双线性概览中已经生成的非法类别值。

### 自定义符号化

对于需要自定义渲染规则的场景，可以使用唯一值分类符号化。

```javascript
// JavaScript - 获取唯一值列表
const uniqueValuesRes = await fetch("/api/raster/unique-values/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({
    datasetId: 1,
    band: 1,
  }),
});
const { items } = await uniqueValuesRes.json();

// items 包含每个唯一值的默认颜色和标签
// 可以在此基础上自定义颜色
```

### 渲染模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `grayscale` | 灰度渲染 | 连续数据（如 DEM） |
| `unique` | 唯一值分类 | 分类数据（如土地利用） |

### 最佳实践

- **异步处理**：栅格导入和渲染建议使用异步模式，避免请求超时。
- **COG 格式**：系统会自动转换为 COG 格式，优化瓦片加载性能。
- **样式缓存**：相同 COG 指纹和样式规则会生成相同的 `styleHash`；分类样式复用完整的内容寻址 MBTiles，连续影像复用瓦片 URL 与进程内缓存。
- **进度监控**：异步任务可以通过轮询接口获取进度信息，及时反馈给用户。

### FAQ

**Q: 栅格文件支持哪些格式？**

A: 浏览器支持 GeoTIFF/COG、ERDAS IMG、VRT 数据包，以及 ENVI DAT/BSQ/BIL/BIP + HDR。DAT 等二进制栅格必须与同名 HDR 一起上传；VRT 必须同时上传全部包内相对引用文件。前端只整理数据包，格式、CRS、尺寸和波段由 `/api/raster/import/preview/` 使用 GDAL 权威校验。

**Q: 为什么多波段影像导入后颜色不正确？**

A: 不同传感器的自然色波段顺序不同。预检页允许确认 RGB 波段；标准 WorldView 8 波段影像可使用 R=5、G=3、B=2，自然色规则会随数据集保存并由后端瓦片服务渲染。

**Q: 栅格导入任务刷新页面后还能查询吗？**

A: 可以。任务状态、阶段、进度检查点和结果已写入业务元数据库；当前进程仍负责实际 GDAL 执行，服务意外退出时未完成任务会保留最后检查点并显示为未完成，而不会丢失任务 ID。

**Q: 渲染状态显示 "failed" 怎么办？**

A: 检查任务的 `error` 字段了解失败原因。常见原因包括文件损坏、坐标系信息缺失等。

**Q: 如何更新栅格的渲染样式？**

A: 重新调用渲染接口并传入新的规则，系统会生成新的 `styleHash` 和瓦片 URL。

### API Reference

详见 API Reference（OpenAPI）。

---

## 9. 异步任务管理

### 功能简介

异步任务管理功能用于监控和管理平台中的长时间运行操作，如栅格导入、扫描、渲染和导出等。

### 使用场景

- 监控异步任务执行进度
- 获取任务执行结果
- 处理任务失败情况

### 前置条件

- 用户已登录
- 已提交异步任务（栅格导入、扫描、渲染或导出）

### 集成流程

```
提交异步任务
   ↓
获取任务 ID
   ↓
轮询任务状态
   ↓
处理任务结果
```

### 实现步骤

#### Step 1: 提交异步任务

异步任务通过相应功能的接口提交，返回统一的任务对象。

```javascript
// JavaScript - 示例：提交栅格渲染任务
const response = await fetch("/api/raster/render/async/", {
  method: "POST",
  credentials: "include",
  headers: {
    "Content-Type": "application/json",
    "X-CSRFToken": getCookie("csrftoken"),
  },
  body: JSON.stringify({
    layerId: 3,
    rulesMode: "default",
  }),
});
const job = await response.json();
console.log("任务ID:", job.id);
console.log("任务类型:", job.kind);
console.log("初始状态:", job.status);
```

#### Step 2: 轮询任务状态

```javascript
// JavaScript
async function pollJobStatus(jobId, onComplete, onError) {
  const pollInterval = setInterval(async () => {
    const response = await fetch(`/api/raster/jobs/${jobId}/`, {
      credentials: "include",
    });
    const status = await response.json();

    // 更新进度
    console.log(`进度: ${status.progressPercent}%`);
    console.log("消息:", status.messages);

    if (status.status === "ready") {
      clearInterval(pollInterval);
      onComplete(status.result);
    } else if (status.status === "failed") {
      clearInterval(pollInterval);
      onError(status.error);
    }
  }, 1000); // 每秒轮询一次

  return pollInterval;
}

// 使用示例
pollJobStatus(
  job.id,
  (result) => {
    console.log("任务完成:", result);
  },
  (error) => {
    console.error("任务失败:", error);
  }
);
```

```python
# Python
import time

def poll_job_status(job_id, timeout=300):
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = session.get(f"{base_url}/raster/jobs/{job_id}/")
        status = response.json()

        print(f"进度: {status['progressPercent']}%")
        print(f"消息: {status['messages']}")

        if status["status"] == "ready":
            return status["result"]
        elif status["status"] == "failed":
            raise Exception(f"任务失败: {status['error']}")

        time.sleep(1)

    raise Exception("任务超时")

# 使用示例
try:
    result = poll_job_status(job["id"])
    print(f"任务完成: {result}")
except Exception as e:
    print(f"错误: {e}")
```

### 任务状态

| 状态 | 说明 |
|------|------|
| `queued` | 排队中 |
| `running` | 执行中 |
| `ready` | 已完成 |
| `failed` | 已失败 |

### 任务类型

| 类型 | 说明 | 结果格式 |
|------|------|----------|
| `import` | 栅格导入 | `RasterDataset` 对象 |
| `scan` | 栅格扫描 | `{ items: RasterDataset[], count: int }` |
| `render` | 栅格渲染 | `RasterRenderResult` 对象 |
| `export` | 数据导出 | `{ filename: string, downloadUrl: string }` |

### 最佳实践

- **合理轮询**：建议轮询间隔为 1-2 秒，避免过于频繁的请求。
- **超时处理**：设置合理的超时时间，避免无限等待。
- **进度展示**：利用 `progressPercent` 和 `messages` 字段为用户提供进度反馈。
- **错误处理**：妥善处理任务失败情况，展示错误信息并提供重试选项。

### FAQ

**Q: 任务长时间停留在 "queued" 状态怎么办？**

A: 可能是系统繁忙，请耐心等待。如果持续较长时间，可以联系管理员检查系统状态。

**Q: 任务失败后如何重试？**

A: 重新提交相同的任务请求即可。

**Q: 任务 ID 会过期吗？**

A: 任务记录会保留一段时间，建议在任务完成后及时获取结果。

### API Reference

详见 API Reference（OpenAPI）。

---

## 10. 搜索

### 功能简介

搜索功能支持全局搜索数据资源。

### 使用场景

- 快速查找数据资源

### 前置条件

- 用户已登录
- 用户具备 `core.browse_data` 权限

### 实现步骤

#### 全局搜索

```javascript
// JavaScript
const query = "胡杨";
const response = await fetch(`/api/search/?q=${encodeURIComponent(query)}`, {
  credentials: "include",
});
const { resources } = await response.json();

console.log("找到数据资源:", resources.length, "个");
// resources 只包含正式登记的数据资源
```

```python
# Python
query = "胡杨"
response = session.get(f"{base_url}/search/", params={"q": query})
result = response.json()

print(f"找到数据资源: {len(result['resources'])} 个")
```

### 最佳实践

- **搜索建议**：在用户输入时提供搜索建议，提升用户体验。
- **结果展示**：展示业务数据资源的名称、类型、来源和更新时间，便于用户快速定位。
- **空结果处理**：搜索关键词为空时返回空结果，前端应妥善处理。

### FAQ

**Q: 搜索支持哪些字段？**

A: 搜索会匹配数据资源的名称、描述、来源等字段。

**Q: 搜索结果如何排序？**

A: 搜索结果按相关性排序，与关键词匹配度越高的结果越靠前。

### API Reference

详见 API Reference（OpenAPI）。

---

## 11. 后台管理

### 功能简介

后台管理位于 `/admin/`，前端基于 Ant Design Pro 组件实现，提供用户设置、日志管理、系统设置、认证授权和数据管理能力。

### 使用场景

- 管理用户账号和权限
- 配置系统参数
- 管理数据资源和目录
- 查看日志管理

### 前置条件

- 用户已登录

### 管理功能

| 功能模块 | 说明 |
|----------|------|
| 用户设置 | 用户可维护用户名、头像、邮箱、部门等个人信息，查看已授予权限，并主动关闭或重新开启已授予权限 |
| Dashboard | 后台通过 `/api/admin/dashboard/?period=day\|week\|month` 查询数据资源、图层、栅格、用户数量、指定周期活跃账号和成功登录次数；通过 `/api/admin/dashboard/server/` 查询 Windows、Linux、macOS 的 CPU、内存、硬盘和可选 GPU 监控快照，GPU 支持单卡和多卡明细。活跃账号按已认证 API 访问去重，跨日保持会话的账号在继续访问时计入当天活跃；成功登录次数仅统计新建会话，包含账号密码、游客和自助注册自动登录。只有具备至少一项运维权限的账号显示后台入口并可进入运行概览；普通用户、科研用户和游客仅保留个人设置入口。数据统计卡片由 `core.view_dashboard_*_card` 权限独立控制，服务器信息整段由 `core.view_dashboard_system_card` 控制；未授权内容不会出现在接口响应和页面中，前端每 5 秒刷新服务器信息 |
| 日志管理 | 后台通过 `/api/admin/operation-logs/` 查询真实审计日志，支持筛选、分页和 CSV 导出；所有登录用户始终可查看自己的操作日志，更大日志范围由所有用户、指定角色日志范围权限控制；具备 `core.view_system_logs` 的用户可通过 `/api/admin/system-logs/` 查看业务数据根目录 `logs/` 下的后台运行日志文件尾部内容。操作日志只记录用户主动行为，目录扫描、启动扫描、后台数据发现和任务内部进度进入系统日志或任务日志 |
| 系统设置 | 新版后台只展示用户可配置的 application 设置，并将修改直接写入启动时传入的源 TOML 配置文件；地图配置支持可公开下发到浏览器的 Mapbox Token 与可选天地图 Key，未配置天地图 Key 时返回空字符串；前后端共同限制可配置的栅格与独立成果上传为 1–1024 MB、查询结果为 100–10,000 条、栅格单边为 1–12,000 像素、栅格任务超时为 10–600 秒。矢量上传另取平台配置与 120 MB 的较小值，表格在线解析另取平台配置与 16 MB 的较小值；专题出图 PNG 固定使用独立 128 MB 上限且不随上传设置变化。配置目录必须可写并整体挂载到容器 `/config`，单文件 bind mount 不支持原子保存 |
| 数据备份 | 后台通过 `/api/admin/backups/*` 仅向内置 `超级管理员` 主体开放本地和云端对象存储备份配置、连接测试、手动备份、自动计划、任务进度和历史记录；普通用户、平台管理员、科研用户以及被误授予 `core.manage_data_backup` 的非超级管理员主体都不能执行备份 |
| 认证授权 | 后台提供用户创建、启用停用、删除、重置密码、角色分配、角色增删和功能权限配置；非超级管理员主体不会在用户、角色、日志角色等认证授权接口中看到超级管理员账号或角色；管理员创建用户不受自助注册开关影响 |
| 数据管理 / 存量数据 | 后台通过 `/api/admin/data/resources/` 分页查询当前用户可见或本人上传的已登记数据资源，支持数据资源重命名、快速检索、高级筛选、内容组别、启用/禁用、默认可视化方案保存、项目组/仅上传者可见切换、删除确认以及 CSV/Excel 清单导出；上传默认 `ownerOnly=false`，项目成员可见；切换为 `ownerOnly=true` 后仅上传者和超级管理员可见，后端在目录、查询、图层、导出和数据智能体入口统一强制过滤；超级管理员可查看和维护全部资源。历史访问角色字段保留兼容但不参与可见性判断。 |
| 数据管理 / 数据与成果导入 | 数据资源导入由 `catalog.add_dataresource` 控制；成果导入要求 `catalog.view_resultartifact + add_resultartifact + publish_resultartifact`，并直接发布到至少一个访问角色 |
| 数据管理 / 工程与成果 | 工程管理继续通过 `/api/admin/workspaces/` 维护工程；成果管理统一展示 `MapComposition` 和 `ResultArtifact`，分别按专题图权限和独立成果权限提供预览、下载、发布/下架和删除 |

### 存量数据管理

存量数据管理入口为 `/admin/data/inventory`。具备 `catalog.view_dataresource`、`catalog.change_dataresource`、`catalog.delete_dataresource` 或 `catalog.export_dataresource` 的用户可以查看当前用户可见或本人上传且符合筛选条件的存量数据；超级管理员角色可查看全部存量数据；仅具备 `catalog.add_dataresource` 的上传者可以进入该页查看自己上传的数据并修改其可见范围。界面按权威四大类及其叶节点展示系统分组，并继续展示用户新建的自定义分组；“全部数据”默认展开，顶层分组和叶节点分别采用单分支展开，打开 LUCC 等分类时会自动收起先前明细，避免同一资源在“全部数据”、大类和小类中同时堆叠。分组汇总表与资源明细表使用独立横向宽度，长资源名称在明细表内部滚动且不挤压状态、来源和操作列。历史未分类资源进入“未分组（其他）”；自定义分组不改变权威业务分类。接口的 `summary` 和 `groupSummaries` 始终按当前筛选与权限范围统计完整结果，不受明细分页影响；`items` 只承载当前页明细。前端统计卡片和分组规模必须使用完整汇总，不能再用当前页 `items` 推算全量数值。列表接口同时包含 `domainType`、`sizeBytes`、`itemCount`、结构化 `uploader`、持久化自定义组别 `inventoryGroups`、资源自定义组别 `inventoryGroupId` 和当前用户是否可修改可见范围的 `canManageAccess`；可手动配置的访问角色列表不会返回超级管理员角色，后台仍强制保留该访问范围；常规业务目录 `/api/catalog/resources/` 仍只返回启用且用户可访问的数据资源，因此禁用资源会从业务查询、加载和搜索流程中隐藏，但保留在系统中。

关键接口：

- `GET /api/admin/data/resources/`：按关键词、数据类型、状态、来源、提供单位和日期范围筛选当前用户可见或本人上传的存量数据。`items` 返回当前页明细；`summary` 返回筛选范围内的总数、启停数、受限访问数、数据大小和条目数；`groupSummaries` 返回“全部数据”、十个业务类型组及全部自定义组的完整规模。接口还返回当前主体可见的数据访问角色、上传用户、业务类型 `domainType`、用户自定义组 `inventoryGroups`、资源自定义组 `inventoryGroupId` 和 `canManageAccess`。超级管理员可查看全部资源；仅具备 `catalog.add_dataresource` 时只返回当前用户上传的数据资源。若资源维护人是当前主体不可见的超级管理员用户，`maintainer` 返回空字符串且 `uploader` 返回 `null`。
- `POST /api/admin/data/resource-groups/`：新建存量数据内容组别，需要 `catalog.change_dataresource`。组别只用于管理表格分组，不影响访问权限。
- `POST /api/admin/data/resource-groups/{groupId}/`：通过 `action=update` 改名或 `action=delete` 删除自定义组别，需要 `catalog.change_dataresource`。删除组别时，后端将组内资源的 `inventoryGroupId` 置为 `null`；资源仍保留在“全部数据”和对应业务类型系统分组中，数据本身不会被删除。
- `POST /api/admin/data/resources/{id}/`：通过 `action` 执行 `setStatus`、`saveVisualization`、`updateAccess`、`updateInventoryGroup`、`update` 或 `delete`。`update` 可通过 `name` 重命名数据资源；名称去除首尾空白后必须为 1–160 个字符。重命名只改变目录、搜索和存量数据中展示的 `DataResource.name`，不改变稳定编号 `code`、物理存储标识 `storage_path`、文件/数据表或地图默认图层名称。目标数据必须对当前用户可见或由当前用户上传；不可见数据按不存在处理；超级管理员不受对象可见范围限制。上传者本人或具备 `catalog.change_dataresource` 的用户可执行 `updateAccess`；重命名、启停、内容组别、默认可视化和普通编辑需要 `catalog.change_dataresource`；删除需要 `catalog.delete_dataresource` 并提交与数据名称完全一致的 `confirmationName`。
- `GET /api/admin/data/resources/export/?format=csv|xlsx`：按当前筛选条件导出当前用户可见或本人上传的存量数据清单，需要 `catalog.export_dataresource`；超级管理员可导出全部资源。

数据可见范围：

- 用户导入数据时，上传者本人强制可见，超级管理员角色强制可见。
- `accessGroupIds` 表示额外可见角色；后端会自动补齐超级管理员角色。访问角色列表不返回超级管理员角色，所有用户都不能选择或取消后台强制可见规则。
- 选择游客角色表示该对象公开：无需账号即可通过游客会话浏览和查询，其他已登录角色也保留访问权；前端必须给出醒目提示。

默认可视化方案保存在 `DataResource.default_visualization`。空间资源存在或创建关联 `MapLayer` 时，会同步默认图层名称、默认显隐、默认透明度、矢量符号化和栅格规则。对栅格数据只保存规则和图层配置，栅格符号化仍由后端渲染流程完成，不在前端执行。

敏感操作审计：

- 启用/禁用、内容组别新增/改名/删除、资源组别移动、默认可视化保存、访问权限配置、删除和导出都会写入 `OperationLog`，模块为“数据管理”。
- 删除用户导入的矢量/表格资源时，接口会清理对应 GeoPackage 图层或 SQLite 表；栅格等可能复用的原始文件只删除资源登记和关联图层，避免误删共享研究数据。

### 数据备份

数据备份入口位于 `/admin/backup`，仅内置 `超级管理员` 可见和可调用。后端所有 `/api/admin/backups/*` 接口除登录态和 `core.manage_data_backup` 外，还会校验当前主体是否属于系统维护的 `超级管理员`，避免普通账号通过直授权限执行备份。

备份支持两种目标：

- `local`：保存到本地目录。目录为空时使用业务数据根目录下的 `backups/local/`。本地备份只作为临时导出或内网选项，不应作为唯一容灾手段。
- `object_storage`：上传到 S3 兼容对象存储。超级管理员通过前端配置 endpoint、region、bucket、prefix、access key 和 secret；后端只在保存和连接测试时接收 `secretAccessKey`，读取配置时仅返回 `secretConfigured` 和脱敏 `secretPreview`。

备份计划分为：

- `platform`：平台业务数据，覆盖业务数据根目录中的 `database/`、`media/`、`uploads/`、`config/`，可选包含 `logs/`，并将启动源 TOML 配置加入归档。
- `research`：科研数据，覆盖科研数据根目录中的 `vector/`、`raster/`、`gene/` 和 `table/`。

关键接口：

- `GET /api/admin/backups/overview/`：返回当前备份配置、数据范围摘要、运行中任务和最近历史。
- `GET/POST /api/admin/backups/settings/`：读取或保存本地目标、对象存储目标和两类备份计划。
- `POST /api/admin/backups/targets/test/`：测试本地目录写入或对象存储上传/删除能力。
- `GET /api/admin/backups/runs/`：分页查询备份历史。
- `POST /api/admin/backups/runs/`：手动发起备份任务，返回 `202 AdminBackupRun`。
- `GET /api/admin/backups/runs/{runId}/`：轮询任务状态。
- `GET /api/admin/backups/runs/{runId}/download/`：下载本地目标成功生成的归档；对象存储目标不做代理下载。

备份任务状态为 `queued -> running -> success/failed`。任务内部进度、文件清单、manifest 和错误信息写入 `BackupRun`；用户主动保存配置、测试目标、发起备份会写入 `OperationLog(module="数据备份")`。自动计划由后端轻量调度线程按 TOML 中的 `dailyAt` 检查触发，部署环境也可以改用管理命令配合 Windows 任务计划、Linux cron 或容器定时任务执行。

### 工程与成果管理

工程管理入口位于 `/resources/manage/projects`；统一成果管理继续使用稳定路径 `/resources/manage/topics`，但菜单名称为“成果管理”。成果管理通过页签分别展示工作台专题图成果和导入/分析成果，并按对象类型提供对应操作。

关键接口：

- `GET /api/admin/workspaces/`：按关键词、类型、状态和分页参数查询工程专题，返回 `accessGroups`、`owner` 和 `canManageAccess`。
- `POST /api/admin/workspaces/{workspaceId}/`：通过 `action` 执行 `setStatus`、`updateAccess`、`update` 或 `delete`。拥有者本人或具备 `catalog.change_workspacescene` 的用户可执行 `updateAccess`；启停和信息修改需要 `catalog.change_workspacescene`，删除需要 `catalog.delete_workspacescene`。删除必须提交与工程专题名称完全一致的 `confirmationName`；无关联工程会移除记录，已被专题出图稿引用的工程会转为停用隐藏。

工程专题访问范围与存量数据一致：超级管理员角色由后端强制可见，选择游客角色表示对象公开，游客会话和其他已登录角色均可访问。普通业务搜索和工作台加载接口必须继续按对象访问范围过滤，前端菜单和按钮控制只作为可用性提示，不能替代后端权限校验。

工程和成果的启停/发布、信息修改、访问范围配置和删除都应写入 `OperationLog`；前端分别使用“工程管理”和“成果管理”，动作和说明使用中文。

### 访问方式

通过浏览器访问 `/admin/` 进入管理后台。

### 配置文件生命周期

后端启动和管理命令通过 `--config /path/to/app.toml` 参数接收 TOML 配置，并将该文件作为唯一持久化配置来源。后台设置页面直接修改源配置文件。`django_secret_key` 由后端自动生成并写入业务数据目录的 `database/.secret_key`。

内置账号和内置角色不是部署运行参数，集中维护在 `backend/apps/core/configuration/builtins.py`。如需调整 `超级管理员`、`普通用户`、`游客`、`guest`、初始管理员环境变量名或默认功能权限集合，应修改该文件并补充权限初始化测试；业务视图和前端页面不得重复硬编码这些名称。

### 权限与密码管理

- 超级管理员角色由系统维护，默认拥有全部平台功能权限；角色不可删除或重命名，初始化的 `admin` 用户也不能从该角色移除。`GET /api/groups/` 的 `lockedPermissions` 返回该角色必须保留的关键功能权限。
- 普通用户角色由系统初始化维护，默认授予全部科研数据相关权限；默认权限只在首次创建时应用，后续权限允许在后台调整，角色不能删除或重命名。
- 游客角色由系统初始化维护，默认不授予任何功能权限；默认权限只在首次创建时应用，后续权限允许在后台调整，角色不能删除或重命名。专用游客账号 `guest` 由系统维护，只能通过 `POST /api/auth/guest-login/` 建立会话，不能被删除、停用、重置密码、改角色或单独授予直授权限。
- 后台认证授权入口由 `core.manage_auth` 控制；“新建用户”还需要 `core.create_user`，创建角色和配置角色/单用户功能权限还需要 `core.manage_feature_permissions`。仅具备认证授权但不具备新建用户权限的账号不能调用 `POST /api/users/` 创建用户；调用 `POST /api/users/` 创建用户时 `groupIds` 必填且至少包含一个非超级管理员角色。启用/停用用户通过 `POST /api/users/{userId}/` 写入 `isActive`，删除用户通过同一接口提交 `action=delete` 完成；角色成员通过 `POST /api/users/{userId}/groups/` 更新，但当前登录用户、游客用户和超级管理员用户的角色不能在认证授权页修改；单用户功能权限和指定日志角色通过 `POST /api/users/{userId}/permissions/` 写入 `directPermissions`、`disabledPermissions`、`operationLogGroupIds`，但当前登录用户不能在认证授权页修改自己的权限；角色通过 `POST /api/groups/{groupId}/` 更新或提交 `action=delete` 删除；当前登录用户、游客用户和初始化管理员不能被停用或删除。重置密码通过 `POST /api/users/{userId}/password/reset/` 生成随机密码，密码规则与后台创建用户一致，`generatedPassword` 仅在响应中返回一次，当前登录用户和游客用户不能重置密码。
- Dashboard 对所有登录用户开放；数据资源、图层数、栅格数量、用户信息和活跃账号卡片分别由 `core.view_dashboard_*_card` 权限独立控制，服务器信息整段由 `core.view_dashboard_system_card` 控制，接口只返回已授权内容。数据概览拆分为 `ownUploads` 与 `visibleResources` 两个分组：`ownUploads` 仅统计当前用户上传的数据，登录用户无需额外功能权限即可查看；`visibleResources` 按数据可见范围和上传者本人规则裁剪后统计当前用户可见的数据，仅具备 `core.view_data_overview` 权限时返回。每个分组都包含资源总数、启用资源数、总大小、总条目数、按数据类型聚合，以及用于数据概览页空间可视化的 `spatialSummary`。`spatialSummary` 只基于对应分组内已授权数据计算，包含有效空间资源数量、缺失空间范围数量、合并 bbox、最多 80 项资源范围框、Top 10 覆盖面积排行和中心点聚合热力网格；没有有效经纬度范围时返回空数组与 0 计数。兼容旧版的系统总量字段也仅随 `core.view_data_overview` 返回，且不额外返回全局空间摘要。超级管理员在具备该权限时额外获得按上传用户聚合的资源数、大小和条目数。用户信息卡返回系统用户总数、启用账号数、停用账号数和角色数量。活跃账号定义为统计周期内至少发起过一次已认证 API 请求的去重账号，按小时记录并在日、周、月周期内去重，因此跨午夜保持已有会话的用户继续访问时仍会计入当天活跃；柱状图显示各小时或各日期的去重活跃账号数。登录次数单独使用稳定认证事件编码统计成功建立会话的次数，包含账号密码登录、游客登录和自助注册后的自动登录；右侧排名仅按成功登录次数排序。历史成功操作日志会在数据库迁移时回填为小时活跃记录，历史认证日志会回填稳定事件编码。
- 系统设置由 `core.manage_system_settings` 控制。`GET /api/admin/operation-logs/` 对所有登录用户开放，并始终返回当前用户自己的操作日志；`core.view_all_operation_logs` 可查看非超级管理员主体产生的所有用户日志，`core.view_group_operation_logs` 可查看当前用户 `operationLogGroupIds` 配置的可见角色成员日志。非超级管理员主体不会看到超级管理员用户产生的日志，也不能将超级管理员角色配置为日志角色。`userId` 和 `operator` 筛选只在已授权范围内生效，不能扩大可见范围。操作日志只记录登录退出、账号权限维护、数据/工程/专题的增删查改、导入导出、渲染配置和系统配置等用户主动行为；目录扫描、启动扫描、后台数据发现和任务内部进度不写入 `OperationLog`。数据资源、工程/专题相关日志必须写入结构化目标字段：数据资源使用 `targetType=data_resource` 和 `DataResource.id/code/name`，工程/专题使用 `targetType=workspace_scene` 和 `WorkspaceScene.id/kind/name`；删除后仍保留删除前的目标 ID 和名称。日志接口支持 `targetType` 与 `targetId` 精确筛选，`keyword` 也会匹配目标类型、编码和名称。`GET /api/admin/system-logs/?file=application.log&lines=500` 读取业务数据根目录 `logs/` 下的后台日志文件列表和指定文件尾部内容，由 `core.view_system_logs` 控制，只允许按文件名访问 `.log` 与轮转 `.log.N` 文件，不返回服务器绝对路径。
- 当前用户可通过 `POST /api/admin/profile/password/` 修改密码，通过 `POST /api/admin/profile/permissions/` 更新主动关闭的已授予权限。修改密码接口会校验当前密码、新密码至少 6 位和确认密码，并将成功或失败写入操作日志。头像通过 `POST /api/admin/profile/avatar/` 上传 JPG/PNG 文件并压缩入库，用户资料中的 `avatarUrl` 指向 `GET /api/users/{userId}/avatar/` 返回的图片资源。

### 最佳实践

- **权限最小化**：只授予用户必要的权限，避免权限滥用。
- **定期审计**：定期查看操作日志，监控系统使用情况。
- **数据备份**：定期备份数据库和重要数据文件。

### FAQ

**Q: 如何创建新的管理员账号？**

A: 使用初始化生成的 `admin` 登录后，可在新版后台“认证授权 / 用户管理”创建账号并分配具备对应管理功能权限的角色。`admin` 是普通用户，完整功能来自 `超级管理员` 角色权限。

**Q: 如何配置用户的数据访问权限？**

A: 在角色管理中，设置角色的 "Data access groups" 关联，然后将用户添加到相应角色。

### API Reference

后台接口详见 OpenAPI 中“管理后台”标签。

---

## 12. 最佳实践

### 认证与安全

- **CSRF 保护**：所有写操作必须携带 CSRF Token，从 Cookie 中读取 `csrftoken` 值。
- **会话管理**：使用 `remember` 参数控制会话持久性，敏感操作建议使用非持久会话。
- **权限检查**：在执行操作前检查用户权限，避免不必要的 API 调用。
- **错误处理**：妥善处理 401（未认证）和 403（权限不足）响应。

### 前端 API 契约

- **先改 OpenAPI**：新增或修改接口时，先更新 `docs/openapi.yaml`，再实现后端和前端调用。
- **使用 Hey API SDK**：前端业务代码通过 `frontend/src/api/client.ts` 暴露的 `api` 方法访问后端，不直接手写 `fetch("/api/...")`。
- **同步类型**：OpenAPI 变更后运行 `cd frontend && pnpm run generate:api`，提交前运行 `pnpm run check:api`。
- **查阅文档**：运行 `pnpm run api:docs` 生成 Redoc HTML 文档，运行 `pnpm run api:bundle` 生成单文件 OpenAPI bundle。

### 数据导入

- **预检先行**：在正式导入前，务必先调用预检接口了解文件结构。
- **数据校验**：在导入前调用校验接口，确保数据质量。
- **表名规范**：使用有意义的表名，仅包含英文字母、数字和下划线。
- **字段元数据**：为字段提供完整的元数据说明。

### 矢量源文件导入

- **独立接口链路**：Shapefile、GeoJSON 和 GeoPackage 使用 `/api/catalog/vector-import/preview/`、`validate/`、`commit/`，不要调用 Excel/CSV 导入接口。
- **Shapefile 打包**：浏览器上传时使用 ZIP，并至少包含同名 `.shp`、`.shx`、`.dbf`；建议同时包含 `.prj` 和 `.cpg`。
- **中文编码**：优先读取 `.cpg`，无声明时可在预检页面指定 `GB18030`、`GBK`、`CP936` 或 `UTF-8` 后重新预览。
- **坐标系**：源文件缺少 CRS 时必须在校验请求中传 `sourceCrs`；成功导入的地图图层统一标准化为 EPSG:4326。
- **几何质量**：无效、空和 null 几何会作为结构化问题返回；修复或跳过必须通过请求字段明确确认，后端不会静默修改。
- **业务归类**：`DataDomainType` 新增 `vector`。矢量导入默认使用该业务类型，也允许根据数据实际语义选择种群、群落、野外调查或遥感影像等现有类型。
- **物理存储**：原始上传文件保存为单文件归档；标准化几何和属性写入统一 `vector/vector.gpkg`，资源和图层元数据写入 Django 业务库。

### 数据查询

- **限制查询范围**：使用 `limit` 参数控制返回记录数，避免一次性加载过多数据。
- **组合条件**：结合属性和空间过滤，精确定位所需数据。
- **结果缓存**：对于频繁查询的相同条件，考虑缓存查询结果。

### 数据导出

- **选择合适的导出方式**：小数据量使用同步导出，大数据量使用异步导出。
- **坐标系转换**：导出时指定目标坐标系，确保数据与其他系统兼容。
- **筛选导出**：只导出需要的数据子集，减少文件大小。

### 栅格数据

- **异步处理**：栅格导入和渲染建议使用异步模式，避免请求超时。
- **进度监控**：为异步任务提供进度反馈，提升用户体验。
- **样式缓存**：复用相同的渲染样式，减少重复计算。

### 异步任务

- **合理轮询**：轮询间隔建议 1-2 秒，避免过于频繁的请求。
- **超时处理**：设置合理的超时时间，避免无限等待。
- **错误重试**：任务失败后提供重试机制，但避免无限重试。

### 性能优化

- **减少请求次数**：合并相关请求，使用批量操作。
- **数据分页**：大数据量使用分页加载，避免一次性加载全部数据。
- **缓存策略**：对不常变化的数据进行缓存，减少服务器压力。
- **按需加载**：只加载用户当前需要的数据，延迟加载其他数据。

---

## 13. 常见问题（FAQ）

### 认证相关

**Q: 为什么收到 401 错误？**

A: 401 表示未认证。可能原因：
- 未登录或会话已过期
- Cookie 未正确携带（确保设置了 `credentials: "include"`）
- CSRF Token 未正确传递

**Q: 为什么收到 403 错误？**

A: 403 表示权限不足。可能原因：
- 用户不具备该功能权限
- 数据资源设置了访问限制，用户不在允许的角色中

**Q: 如何处理会话过期？**

A: 当收到 401 响应时，应引导用户重新登录。可以在前端全局拦截 401 响应并跳转到登录页。

**Q: 为什么收到 429 错误？**

A: 429 表示请求过于频繁。请降低请求频率，或联系管理员调整限流配置。

### 数据导入相关

**Q: 导入时提示"经纬度不是小数格式"怎么办？**

A: 确保经纬度列使用十进制小数格式，如 `87.600`、`43.800`，而非度分秒格式。

**Q: 如何处理坐标不确定性警告？**

A: 当坐标不确定性最大/最小差距超过 200 倍时会触发警告。可以在导入请求中设置 `ignoreCoordinateUncertainty: true` 来忽略此警告。

**Q: 同名数据已存在怎么办？**

A: 在数据校验阶段确认重复名称后，提交时设置 `duplicateConfirmed: true` 继续导入同名显示数据。后台存储标识由后端保持唯一，已有数据不会被覆盖。

### 数据查询相关

**Q: 查询返回的数据不完整怎么办？**

A: 检查响应中的 `returnedCount` 和 `totalCount`。如果 `returnedCount < totalCount`，说明达到了查询上限，可以增大 `limit` 参数或缩小查询范围。

**Q: 为什么查询结果中没有某些数据？**

A: 后端会自动忽略无几何、经度越界（-180到180之外）、纬度越界（-90到90之外）的数据。检查响应中的 `warnings` 字段了解详情。

### 数据导出相关

**Q: 同步导出和异步导出有什么区别？**

A: 同步导出直接返回文件，适用于小数据量；异步导出返回任务 ID，通过轮询获取结果，适用于大数据量。

**Q: 导出的文件格式是什么？**

A: 矢量数据可导出为 Shapefile 或 GeoJSON，栅格数据导出为 GeoTIFF，均打包为 ZIP 文件。

### 栅格数据相关

**Q: 栅格文件支持哪些格式？**

A: 系统支持 GDAL 能够读取的常见栅格格式，如 GeoTIFF、IMG 等。建议使用 GeoTIFF 格式以获得最佳兼容性。

**Q: 渲染状态显示 "failed" 怎么办？**

A: 检查任务的 `error` 字段了解失败原因。常见原因包括文件损坏、坐标系信息缺失等。

### 异步任务相关

**Q: 任务长时间停留在 "queued" 状态怎么办？**

A: 可能是系统繁忙，请耐心等待。如果持续较长时间，可以联系管理员检查系统状态。

**Q: 任务失败后如何重试？**

A: 重新提交相同的任务请求即可。

---

## 14. 版本控制与变更历史

### 版本策略

- 遵循 [Semantic Versioning](https://semver.org/spec/v2.0.0.html)（语义化版本）
- 格式：`MAJOR.MINOR.PATCH`
  - **MAJOR**：破坏性 API 或部署基线变更
  - **MINOR**：新增当前版本功能
  - **PATCH**：当前版本缺陷修复

### 变更历史

#### v0.1.0（2026-05-28）

初始版本，包含以下功能模块：

- **认证**：登录、注册、登出、当前用户查询、CSRF
- **数据目录**：目录树、资源列表、资源详情、矢量查询、数据导出（同步/异步）
- **图层**：已登记图层列表
- **搜索**：全局搜索
- **栅格**：数据集列表、导入、扫描、渲染（同步/异步）、唯一值分类、XYZ 瓦片服务
- **异步任务**：统一任务状态查询
- **后台管理**：用户设置、日志管理、系统设置、认证授权、数据导入

### 版本策略

- 当前部署只承诺 `docs/openapi.yaml` 描述的最新 API 合同。
- 旧端点、旧权限和旧数据结构不作为运行兼容目标；重新部署应使用空业务数据库执行迁移。
- 接入方升级时应先重新生成 OpenAPI 客户端类型，并按当前合同调整调用代码。

---

> 本文档由 API 文档重构生成，面向开发者提供接入指导。详细的接口参数和响应格式请参考 API Reference（OpenAPI）。

## 15. 九大门户与成果文件（2026-07-22）

当前一级页面固定为：首页 `/data`、数据资源 `/resources`、地理工作台 `/map`、数据分析 `/nongeo`、成果展示 `/results`、智能预警 `/warning`、后台管理 `/admin`、胡杨科普 `/knowledge`、关于我们 `/about/*`。

首页承担数据发现和权威分类浏览，数据资源承担治理、存量维护和导入；两者不再共用同一入口。四大权威分类使用 `categoryCode/categoryPath`，`domainType` 仅保留为兼容业务标签，`dataType` 仅表示矢量、栅格、表格、图片等物理形态。

数据导入页提供两个互不替代的目标：

- “导入为数据资源”继续使用原表格、矢量和栅格导入流程。
- “导入并发布成果”调用 `POST /api/catalog/results/`，支持 PNG、JPG/JPEG、PDF、CSV、XLSX；导入时必须直接发布并至少选择一个访问角色，不再创建新的导入草稿。账号需要独立的成果查看、导入和发布权限。

成果上传以真实内容而不是浏览器 Content-Type 为准：PNG/JPG/JPEG 由 Pillow 解码且扩展名必须匹配实际 PNG/JPEG；PDF 必须具备 `%PDF-` 文件头和尾部 `%%EOF`；CSV 必须非空、无 NUL，编码仅接受 UTF-8/UTF-8-SIG 或 GB18030；XLSX 必须是含 `[Content_Types].xml` 与 `xl/workbook.xml` 的有效工作簿 ZIP，并受 10,000 条目及解压规模限制。后端保存可信 MIME。所有成功文件响应包含 `X-Content-Type-Options: nosniff`；PNG/JPG/JPEG/PDF 的 `variant=preview` 还包含沙箱 CSP 和 `Referrer-Policy: no-referrer`，CSV/XLSX 只提供具备下载权限的 artifact 下载。

成果展示页聚合已发布 `MapComposition` 与已发布 `ResultArtifact`。图片和 PDF 可在线预览，CSV/XLSX 仅允许授权下载。成果文件按访问角色共享；选择游客角色的成果视为公开成果，游客与其他已登录角色均可见；历史草稿或被下架成果仅创建者、超级管理员和平台管理员可见。

数据资源模块原“专题管理”入口升级为“成果管理”，同一页面分别管理工作台生成的专题图成果和导入/分析成果。专题图继续支持打开来源工程、预览、下载、选择版本发布、更新范围、下架和删除；导入成果支持预览、下载、发布历史草稿、更新范围、下架和永久删除。`POST /api/catalog/results/{resultId}/` 使用 `publish|unpublish|delete` 动作完成这些管理操作并写入审计日志。


## 项目标签与内容 API（2026-09-18）

本节更新前述首页、统一登录后访问和按旧角色共享的约定。根路径/登录默认进入 `/map`，`/resources/catalog` 承接数据发现；默认项目公开阅读无需登录。已有账号、角色功能权限仍保留。

### 上下文与权限

- 请求携带 `X-Project-Id`，图片/瓦片/文件 URL 可携带 `projectTagId`；二者相异返回 400。普通浏览缺省=公开项目 1；上传提交必须显式指定。`all` 已取消并返回 400。
- 业务 `projectTagId` 与地图工程 `projectId` 不同。业务对象只能归属一个项目；用户可加入多个项目。
- 公开项目允许匿名浏览启用资源和已发布图文/成果；私有项目要求有效账户与成员关系。仅超管分配标签、管理与读取所有项目，其他管理角色仍须获得项目授权。
- 所有业务读写均使用一个具体项目。文件预览 URL 包含对象所属标签。科普与团队动态属于平台公共内容，独立于项目切换。
- 写入与原文件下载仍检查功能权限；草稿、未共享工程、未发布版本、下架内容/附件不随默认标签公开。
- 匿名可使用默认项目资源查询及默认栅格渲染，不得自定义符号化、导入、导出或管理。异步 render 状态只对同浏览器会话发起的最近至多 20 个任务开放。
- 私有响应和已登录响应为 `private, no-store`；撤回标签后下一次请求重新授权。工作线程继承上下文并重查账户/成员状态；扫描任务仅在同项目内合并，启动扫描只处理默认项目。

### 管理端点

| API | 行为与权限 |
| --- | --- |
| GET `/api/projects/` | `items` 是可读取标签；`assignableItems` 是管理员可分配列表，两者不要混用 |
| POST `/api/projects/` | 超管创建；name/code/description/isActive/sortOrder |
| POST `/api/projects/{projectTagId}/` | 超管维护；内置“公开”项目不能改名/停用 |
| GET/POST `/api/projects/assignments/{userId}/` | 仅超管；POST 的 projectIds 替换该用户标签集合，公开项目无需成员行 |
| GET `/api/content/articles/` | kind、category、q、offset、limit；manage=1 需编辑权限 |
| POST `/api/content/articles/` | 创建内容，编辑权限=超管或 core.manage_auth |
| GET/POST `/api/content/articles/{articleId}/` | 读取/保存；POST 必须带当前 revision，冲突 409 |
| POST `/api/content/articles/{articleId}/assets/` | multipart file，图片/PDF，上限 30 MiB；新附件暂存 24 小时，仅上传者预览 |
| GET `/api/content/assets/{assetId}/` | 暂存附件仅上传者可读，过期拒绝；正式附件跟随文章发布状态 |
| DELETE `/api/content/assets/{assetId}/` | 仅上传者撤销自己的暂存附件；正式附件移除随文章保存提交 |

内容保存字段包括 `commitAssetIds`、`coverAssetId`（null 清除）、`removeAssetIds`、`assetCaptions`（id/caption 数组）。正文、封面、附件提交/说明/移除共用 revision 条件更新与事务；失败不产生部分保存。新上传先暂存；命中同一文章既有正式附件时可复用。取消编辑删除暂存附件；异常离开留下的暂存件在 24 小时后不可访问，由后续上传或 `cleanup_content_assets` 命令清理。目前未配置周期清理任务。初始化内容的 owner 可为空，管理员仍可维护。

布局更新 `POST /api/catalog/map-compositions/{compositionId}/` 支持 `expectedUpdatedAt`，编辑器每次保存发送当前值，陈旧版本返回 409 并保留本地草稿。布局 schema 仍为 version=1，新增 editor.order/editor.locked 和 extraTexts；旧稿读取补默认值。

### 存储与初始化

TOML 仍提供 app_data 与 research_data_root。默认研究文件保留原目录；私有研究文件在 `projects/<id>/`；内容附件在业务根 `projects/<id>/content/<articleId>/`。旧成果与缓存保留全局唯一对象 ID 目录，通过项目授权端点读取。

`manage.py seed_editorial --source <素材根> --config <配置>` 初始化默认项目科普与会议新闻；按 seed_key 幂等跳过已存在条目，不覆盖用户编辑。不修改源 PPTX、照片或 PDF。模型迁移先于种子命令。

API 以 `docs/openapi.yaml` 为准，生成代码实际位于 `frontend/src/api/generated/`，旧文档的 schema.d.ts 路径已不再使用。Mock 来自 `mock/prism/examples/90-platform-upgrade.json`。操作步骤与测试证据见 `platform-upgrade-acceptance.md`。


## API-20260918-002 — 分类与项目授权复核

- Status: Implementing
- Owner: 本任务顺序完成契约、后端、前端交接。
- Endpoints: catalog/standards 资源、工程、成果及导入下载接口；projects/assignments；content/articles。
- Contract: 数据分类改 spatial/non_spatial；资源依据解析后的空间类型与坐标信息自动归类。AdminDataResource 返回 projectTagId。项目成员关系是业务对象访问范围，角色只负责操作权限，历史 accessGroupIds/audienceGroupIds 保留存储兼容但不授权或限制对象阅读。草稿仍限作者或项目内管理员。仅超管维护和分配标签；默认标签自动可读。科普请求固定默认项目 1，禁止创建私有科普；新闻保持项目隔离。
- Frontend reason: 去除胡杨分类和角色共享误导，展示对象所属标签、创建目标标签；切项目科普保持可见。
- Mock: mock/prism/examples/90-platform-upgrade.json 和分类示例随新结构更新。
- Verification: 成员/非成员/超管的列表、详情、查询、工程与成果文件；新用户默认、撤权、切项目科普；真实退出跳转与默认底图。

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

## 2026-09-18 当前接口与开发规则

以 [当前有效规则](current-platform-rules.md) 为准。工程 GET 列表按 q/limit/offset 分页，返回 total/limit/offset 和不含 snapshot 的摘要；打开时 GET 详情。更新普通和后台工程必须传 expectedUpdatedAt，冲突 409 不覆盖。历史角色字段不参与项目可见性。

内容上传先暂存，只有上传者可预览。保存用 commitAssetIds 提交附件，revision 保护正文与附件的一致提交；取消时 DELETE /api/content/assets/{id}/。24 小时过期，运行 cleanup_content_assets 清理，上传也触发清理。底图代理仅接受 allowlist 标识，不接受任意上游 URL；Mapbox 22、天地图 18、OSM 19 为最高原始层级。

备份平台目录：database/media/uploads/config/projects/exports；科研备份完整 research 根（含 projects）。不备份应用缓存及备份自身。恢复应在独立目录校验 manifest SHA256、SQLite integrity_check 与文件引用，再安排正式恢复。

## 2026-09-19 计算中心 API

`/api/compute/` 接口定义见 OpenAPI。算法清单驱动输入与参数表单；上传 ZIP 不执行代码。任务绑定算法版本、项目、用户及参数；输入固定时记录 SHA256。提交需 compute.submit_task，维护需 compute.manage_algorithms，发布需 compute.publish_algorithm，源码下载需 compute.download_algorithm，管理员任务访问需 compute.manage_tasks 且项目授权；结果下载叠加 catalog.export_dataresource，入库叠加 catalog.add_dataresource（现有上传权限）。POST 显式传 X-Project-Id。没有任务历史的算法登记可通过 DELETE 删除其版本包；已有任务历史的算法只能归档停用。503 表示隔离环境或独立worker未就绪，不会回退为主机执行。结果导入异步且幂等；源任务成功与入库状态分别显示。

## 智能体接口（2026-09-21）

`/api/agent/` 接口使用 Session + CSRF，并要求 X-Project-Id 指定单个项目。bootstrap 返回当前用户能力；conversations 仅管理本人会话；runs 提交后返回 202，前端用 after 游标短轮询，终态停止。取消不重放任务，失联任务标记 interrupted。幂等键重复且参数相同返回原任务，参数不同返回 409。

普通聊天要求 core.use_local_model；数据智能体另需 core.use_data_agent、core.browse_data、core.query_data。游客永远拒绝。默认正式用户有聊天权限，科研用户和管理员有数据智能体权限。超管在 /api/agent/admin/ 管理总开关、用户/组范围、模型、配额、上下文/生成参数、附件和互联网检索开关，策略仅收窄权限。管理更新带 revision；端口和服务 ID 仅由部署 TOML 注册。启用算子后，服务端仍只允许计算中心已登记且通过权限、manifest 和项目隔离校验的操作。

数据、证据、历史及后续生成均重新授权；资源撤权后旧会话返回 403。统计默认最多读取 10000 条并明确标记全量或前缀样本；模型不能把截断数据视为总体。长任务由独立 agent_worker 执行，不占用 Waitress 请求线程。新表随业务 SQLite 备份，科研目录布局不变。

模型注册的 `context_window_tokens` 用于显示和上下文安全预算，默认 Qwen3.8-27B 为 32768 token。超级管理员可以在 `/api/agent/admin/` 修改 UTF-8 上下文字节预算、回答 token 上限、Temperature、Top P、工具/算子步骤上限、协议纠错次数、单次运行时限、附件大小/数量和互联网检索策略；worker 会按模型窗口为回答预留空间。运行提交可带 `thinkingMode=fast|deep`、`attachmentIds` 和 `internetEnabled`，服务端会重新核对模型能力和策略。深度模式只接受注册为支持思考的模型。模型真实返回的 `reasoning_content`、`reasoning`、`thinking` 或 `<think>` 片段只写入 `thinking` 事件，并持久化为思考摘要和耗时；前端生成时展开 bordered 面板，完成后收起并显示耗时，不混入最终回答。

`POST /api/agent/attachments/` 接收当前项目内的文档或图片，附件只能由上传者及有权管理员引用；服务端执行 MIME、大小和项目权限校验，并在提交时再次复核。支持的文档会提取文本，图片仅在实际探测到模型视觉能力时发送给多模态模型。互联网检索默认关闭，打开后仅通过受控 HTTP 检索器访问公开地址，结果必须带来源和时间，不能绕过数据权限。

科研工作流使用 `/api/agent/workflows/`，同样要求 Session、CSRF 和 `X-Project-Id`。提交返回 202，并保存目标、模型、资源 ID、策略快照和幂等键；独立 `workflow_worker` 负责节点执行。首期默认只生成数据发现和算法计划，`executeOperators` 必须同时满足请求开关、超级管理员 `operatorEnabled` 策略、已发布且标记为 `agent.enabled` 的算法版本以及计算中心可用，不能绕过计算中心直接运行代码。

`GET /api/agent/workflows/{workflowId}/` 返回当前状态、步骤、checkpoint 引用和结果 ID；`POST /api/agent/workflows/{workflowId}/cancel/` 在排队时立即结束任务，在运行或等待计算时设置取消标记，由 worker 在安全边界收尾。工作流 worker 重启不会重新提交处于 `waiting_compute` 的算子任务；每次恢复仍重新检查项目成员、账号和数据资源权限。当前工作流实现为 LangGraph 可选编排适配器，未安装 LangGraph 时使用同一节点契约的兼容运行路径。

## 2026-09-22 智能体生成控制与算法

maxOutputTokens为每次调用的思考与正文合计上限；maxContextTokens限制输入。reasoningEffort通过Qwen模板传递low/medium/xhigh。worker开始时读取生成策略，新保存的参数作用于之后开始的运行，权限和取消仍实时核验。

完整请求通过模型服务/tokenize计数，以/v1/models返回的max_model_len作为真实窗口，并预留256 token余量。优先裁剪旧历史和旧工具对，再截短附件文字，保留当前问题。maxContextBytes是独立文本大小保护。AgentRun.generationParameters显示最近实际参数及累计生成量，旧记录为空对象。

科研工作流目前执行一次已登记算法的计划和计算；maxIterations保留兼容，在界面标为预留。算法列表按分类sortOrder、分类名、算法名、ID分页前排序。模板5为NDWI水体指数，模板6为矢量面积与周长，均需试运行核对后发布。


### v0.1.15 任务预算

模型对话和数据智能体支持 normal/materials/reasoning 三种方案。管理员通过 `/api/agent/admin/` 配置各方案默认生成量、思考强度和任务时限，并设置 standard/superadmin 两档总窗口、生成量、时限上限。平台管理员归 standard；超级管理员身份沿用既有 Django 用户和超级管理员组判定。

`/api/agent/bootstrap/` 的 budgets 给出当前用户可用方案、默认值和上限。提交运行可带 `budgetProfile` 和可选 `maxOutputTokens`；未提供生成量时采用方案默认值，并收窄至角色上限及实际模型窗口的一半；显式设置允许更大的生成量，但必须给输入及安全余量至少留下512 token。输入预算等于可用总窗口减生成预留和256 token余量。完整消息含系统、历史、附件和工具结果，使用服务端 tokenizer 计数。

预算在提交时持久化到 AgentRun；修改方案默认值不改变已有运行。运行期间降低角色额度、撤销权限或关闭预算会停止超过新授权范围的任务。新字段不接受客户端角色声明；幂等重试要求方案和显式生成量相同。

实际参数位于 generationParameters：contextWindowTokens 为用户本次可用窗口，serviceContextWindowTokens 为服务报告窗口；inputTokens 为最近请求计数，lastGeneratedTokens 为最近一次服务回报生成量，generatedTokens 为累计生成量，modelCalls 为收到用量回报的调用次数。思考和正文共同计入生成额度，预留量不等于消耗量。服务未提供 usage 时不伪造用量。

本次预算作用于对话和数据智能体。科研工作流使用持久化状态机生成和执行可确认计划，算法调用受现有策略、权限及计算配额控制。附件仍有独立格式、大小和数量限制；扩大文本提取量不会令图片、栅格或整个数据库自动变成模型输入。


### MHGDAL多文件结果（2026-09-24）

计算输出声明支持`kind: archive`、`.zip`文件。服务端校验单层文件名、重复项、链接、CRC和解压总大小；仅供下载与元数据预览。对压缩包调用结果入库接口返回400，用户解压后按支持的数据格式分别导入。公开资源匿名读取继续只返回当前公开项目中启用且非owner_only的数据。

### 本人功能与科研用户申请
登录后通过 `/api/auth/access/` 展示本人功能及智能体开放操作；升级差异按现有科研角色计算，单独展示。普通用户通过 `/api/auth/research-application/` 提交姓名、单位和理由；pending不可重复，rejected可重提。超级管理员在角色申请列表审核，申请人可读取本人状态及审核意见。个人资料权限目录只列当前有效项。
### 2026-09-29 知识库与编排接口

`GET/POST /api/knowledge/entries/`、`GET/PATCH /api/knowledge/entries/{entryId}/` 提供格式化知识检索与维护。读取需登录；范围为当前项目和公共已发布基础知识。维护要求超级管理员或 `knowledge.change_knowledgeentry`，且只能修改当前项目内容。发布需要来源，修改携带最后读取的 revision；冲突返回 409。检索支持 q/category/offset/limit（最多200）与 manage=true（维护者查看当前项目未发布条目）。

`POST /api/knowledge/check/` 以 facts 和可选 entryIds 核查显式事实，返回 conflict/pass/needs_context 及条目版本和来源。矿物共存核查要求明确 minerals、equilibrium 和体系 system；缺失条件返回 needs_context。来源权限与图谱页面使用同一知识服务。知识图谱由条目关系派生，当前检索方式为关键词/别名匹配。

`GET /api/agent/runs/{runId}/compute-tasks/` 返回本人运行关联计算的实时状态和自动入库跟踪；复用 ComputeTask 契约。`GET /api/agent/workflows/` 恢复当前项目本人最近30个工作流。预览可传 inputs（端口到资源ID）与 importResults；`POST /api/agent/workflows/{workflowId}/confirm/` 以 planHash 确认冻结计划，重新校验权限、输入、算法与预算后执行。plan、planHash、importResults、resultResourceIds 在工作流响应中始终返回。

跨模块分工：根任务负责知识服务、OpenAPI/生成类型及集成；编排子任务负责 agent/compute 与其前端；科普/知识界面子任务负责内容刷新与知识页面。详见 [知识库与编排说明](knowledge-orchestration-20260929.md)。

### 2026-10-04 文档检索、自动 Wiki 与质量报告

知识库增加 `GET/POST /api/knowledge/documents/`、`POST /api/knowledge/documents/{documentId}/retry/`、`POST /api/knowledge/documents/search/` 与 `GET /api/knowledge/wiki/`。上传使用 multipart：file/title/visibility/sourceUrl，最大20MiB；PDF按页、DOCX按段提取可检索文字。原件和SHA256保留，WeKnora负责向量/关键词混合检索、资料索引及自动Wiki。扫描PDF须先提供可提取文字。重试处理限有知识维护权限者及当前项目。

每个项目的共享资料和各用户的owner_only资料使用独立知识空间；服务端核实当前项目和成员关系，检索只传入授权文档。公共资料来自公开项目；私有空间只对本人开放。Wiki合成在空间内进行，每页引用再映射到本地文档，未通过可见性校验的内容不返回。前端仅收到平台资料ID，不接触WeKnora凭据。配置见 `config/knowledge.example.toml`，模型与索引文件独立于源码和业务数据库，备份时一并保留。

Wiki为自动整理内容，保留来源、修订号及主题关联；既有格式化知识及可执行条件规则维持独立审核。`KnowledgeDocumentSearch.score` 表示该次匹配得分，不是知识正确率。引擎不可用时返回明确状态，结构化知识仍可使用。

智能体继续使用 `search_knowledge`：结果的items为结构化条目、documents为真实检索原文、documentSearch说明引擎可用状态。每项citation对应本轮实际证据序号，documentId/entryId仅作为平台标识。每段最多1400字，总返回不超过24KB；截断会标记。历史资料证据按可见性及文档SHA重新检查。纯知识问题直接检索知识，涉及数据才发现数据资源。回答结束时平台追加当时计算及入库状态，使用确定性查询，不增加一次模型调用；后续状态由任务卡继续刷新。

资料检索仅将原文 `text/parent_text` 分块作为证据，生成摘要、实体及 Wiki 不冒充原文；目录点线和出版联系信息降权。智能体可用 `read_knowledge_document(documentId, offset, limit)` 分页读知识资料原文，每次最多8000字，返回真实引用和续读位置。此工具使用知识资料编号，与数据目录的 `read_document(resourceId)` 分开；读取时重新核对资料权限、SHA及文档读取开关。`list_compute_algorithms` 可按目标查询并返回完整算法清单；总结果超过48KB时要求缩小检索范围。

用户明确请求字段清单而正文遗漏时，平台依据本轮数据概况证据补齐真实字段和引用号，不增加模型调用。原文检索成功与模型转述准确性分别验收；当前真实模型测试仍观察到自行补充作者首字母、矿物译名的错误，来源面板提供原文复核依据。

计算清单增加可选 `qualityReport: {file: "quality.json"}`；报告最大64KiB，字段为version=1、status=passed|needs_review、summary、metrics与knowledgeFacts。worker验证报告并将qualityCheck/knowledgeFacts写入输出元数据。声明的报告缺失、格式无效或需要复核时，直接智能体、后续计算、工作流和导入worker均阻止自动入库，原件与审计成果仍可下载。人工显式入库沿用权限控制。模板7提供面几何修复，先真实试运行再发布；算子接收已登记数据，保留原输入，输出逐要素修复日志、汇总及审核包。

入库worker仅对SQLite的BUSY/LOCKED结果码（含BUSY_SNAPSHOT）按0.2/0.5/1秒退避重试，最多额外3次；每次刷新账号、权限及自动入库意图，并按原storage_key复用资源和图层。最后登记事务先取得写锁，再读取当前权限，避免读快照升级写锁与心跳竞争。普通格式/权限/IO错误仍直接失败；持续繁忙时保留原计算成果，用户可重试入库，无需重算。未新增HTTP字段或状态。

## 聊天计算闭环（2026-10-09）

AgentRun.computeIntent 保存算法版本、输入、已确认参数和修订摘要。GET/POST `/api/agent/runs/{runId}/compute-intent/` 仅允许本用户原项目操作。POST action 为 update/submit/cancel，必须带 planRevision；资源或版本变更、后续消息替代计划返回409。band参数须由用户文字或参数卡确认。提交幂等，真实任务与会话绑定，默认完成后由用户选择入库。查询和入库仅使用本会话关联任务，不猜测最近相似任务。

GET `/api/compute/outputs/{outputId}/map-preview/` 返回后端PNG地址和WGS84四角，image子路径返回PNG。两者必须带projectTagId，每次检查用户、项目、任务、输入与文件身份，临时过期则404。前端仅放置临时图层，不入库、不保存工程。

## 知识领域与智能体工具选择（2026-10-10）

独立 `domain` 将结构化条目与文档分为 remote_sensing（遥感基础）、pipelines（油气管道相关）、geology（遥感地质填图逻辑推理）、arid_ecology（干旱区生态安全治理）。原 `category` 细分类保持。历史资料迁移只补领域，不改原文、文件、来源或版本。条目、文档、Wiki列表支持可选 `domain` 查询；文档检索支持 `domains` 数组。上传资料可带 domain；`PATCH /api/knowledge/documents/{documentId}/` 以 `{domain}` 调整资料分区，复核当前项目知识维护权限及本人隐私边界。新领域上传使用独立上游Wiki空间，旧空间中的页面只在全部引用通过当前领域与权限校验时返回。

运行提交及返回新增 `knowledgeSelection:{mode,domains}`、`algorithmSelectionMode`、`algorithmVersionIds`、`dataSelectionMode`，返回也包含 `resourceIds` 与 `resolvedKnowledgeDomains`。知识支持 auto/manual/all/none；manual须选择1至4个领域，其他模式domains为空。auto实际按本轮主题和所选算法限定检索领域；NDVI/NDMI/EVI/SAVI覆盖遥感基础与干旱生态，管道场景可同时匹配管道领域。无明确主题时使用可见领域。none关闭知识检索、原文读取与规则核查工具，并排除含历史知识证据的上下文。分区选择不扩展项目、发布状态或owner_only权限。

算法与数据支持 auto/manual。算法manual须选择1至3个实际已发布安全版本，数据manual须选择1至3项resourceIds；auto对应列表为空。旧客户端非空resourceIds兼容为手选。手选范围由服务端同时限定工具返回、输入读取、执行和计算卡候选。手选一个算法后，用户用“处理/运行/计算”即可进入该算法参数卡；多选且未明确算法时提示选择，不猜测执行。知识none模式仍可按计算清单完成计算，既有质量报告和入库验证继续生效。

偏好保存于每轮AgentRun；会话详情的runs及运行轮询可恢复，幂等比较包含所有偏好。bootstrap新增knowledgeDomains（id/label/description/count）与algorithmOptions（versionId/algorithmId/name/version/description）。普通模型聊天继续无平台工具，应在智能体模式呈现选择控件。

科研会话的auto模式还结合已绑定任务的实际知识依据：同用户、同项目、同会话的流程重新授权后，将自动使用领域保存为本轮有效范围，补证据和短进度询问持续关联原流程。manual、none及数据和算法手选范围继续逐轮核验；一般聊天保持原有主题筛选。

## 计算结果目录与统一参数表单（2026-10-10）

`GET /api/data-schema/summary/` 返回地理数据、非地理数据和计算结果三个根节点，目录版本为 `2026.10`。`compute_results` 节点的 `selectable=false`、`spatialClass=null`：普通上传不能选择该类别，计算结果自身的空间属性和数据类型保持。`GET /api/catalog/resources/?categoryCode=compute_results` 筛选当前项目可访问的已入库计算结果，空间结果继续可在地理工作台查看；未入库成果仍在原任务中。

内部 `DataResource.is_compute_result` 标记由计算入库维护，不作为客户端可写字段。栅格、矢量、表格、图片和报告入库均归入计算结果；历史回填只依据 `ComputeImport.resource` 的真实关联并核对任务与资源项目一致，不按名称或来源文字推断。迁移仅新增分类、结果标记并更新匹配资源的分类，保留原始文件、资源状态、时间戳、隐私与项目权限。计算输出 `resourceLocation` 返回项目下的“数据资源 / 计算结果 / 资源名称”。

计算中心和智能体参数卡共用 `ComputeAlgorithmFields`，按已发布算法清单展示输入数据、算法参数和结果概览。两处采用相同的波段名称、帮助说明、默认参考值和范围提示；更换输入后清空关联波段或字段。智能体仍要求用户明确确认波段，展示默认参考值不等于授权使用默认波段。

## 自然语言科研案例与在线澄清（2026-10-11）

`GET /api/agent/research-demos/` 返回本人有权进入的案例项目和就绪状态，目录查询无需当前项目头，不扩大项目访问权。成果展示入口先选择该授权项目，再创建独立智能体会话，以自然语言和可选 `demoScenario` 提交任务。模拟资料、参数预设和保存目标写在可见提示中；用户变更由模型重新解析，既有科研工作流参数页继续保留。

`AgentRun.researchIntent` 保存原运行、修订、目标、输入角色和真实工作流关联。尚未创建 `workflowId` 为 null；普通聊天字段缺省或 null。澄清问题可选 choice/text/number/resource；前端以可读标签展示，按问题键提交字符串答案。`POST /api/agent/runs/{runId}/research-intent/` 带 `action` 与 `revision`，answer 可附 `answers` 和自由文本 `answer`，返回202后续模型解析运行；confirm 和 cancel 返回200原运行最新状态。重复相同修订和答案复用已有解析及计算，不从聊天文字猜测任务。

接口要求 Session、CSRF、原用户和原单项目 `X-Project-Id`；引用每次重新授权，修订或输入变化返回409。确认用于用户明确批准当前真实审核结果，几何质量审核继续暂停至确认。聊天通过已有工作流详情展示实际判断、计算、入库与地图；刷新只恢复关联，不再次提交启动指令。

## 真实底图地质时代纠偏与成果关联（2026-10-12）

科研场景新增 `geology_age_correction`，输入角色仍为 `initial_map`、`surveys`、`rules`；其中 surveys 为空间背景与资料说明，实际编辑依据为有地区及地层适用条件的辞书规则。流程调用已发布的地层时代检查、受约束编辑和复查算法。入口 `sampleNature=real_map_with_demonstration_errors` 明示真实图件副本和少量演示录入错误。原生态及地质模拟案例保持独立，模型只读取初图、资料和知识；人工精修、正确参考及设错清单用于独立验收。

成果创建 multipart payload 可带 `resourceIds`；成果详情的 publish 请求也可更新该数组。关联限当前项目可读数据资源，最多30个且不重复；创建省略为无关联，publish省略保留原关联、空数组清除关联，其他动作不接受关联更新。响应 `relatedResources` 为 `{id,name,dataType}` 列表，读取时重新过滤项目、资源状态和 owner_only 权限。成果详情据此打开地理工作台或数据资源，成果文件本身的预览、下载与发布权限保持原规则。

## 科研工作流成果文件与暂停（2026-10-12）

原生态、地质模拟案例采用预设阶段图；模型在每阶段依据真实输入、知识引用、统计与计算结果判断，并在允许的操作内选择执行或请求复核。前端已完成步骤默认折叠，计算历史与最终文件分开呈现。

新增 POST `/api/agent/workflows/{workflowId}/pause/`、`resume/`，空请求体。本人/原项目与输入权限保持。paused 和 pauseRequested 为持久状态；已有计算允许完成，暂停停止后续调度，继续复用原taskId。waiting_approval恢复后仍需原确认，结束任务返回409。科研意图仍映射为running，前端使用所关联真实workflow.status展示已暂停。

新增 POST `.../report/` 生成成功工作流的持久Markdown报告，幂等且不调用模型或计算；GET `.../report/preview/` 返回UTF8文本；GET `.../report/download/` 需数据导出权限，返回真实attachment；POST `.../report/import/` 需数据新增权限，幂等登记document/MD、is_compute_result。所有接口检查本人、当前单项目、所有输入及关联任务/结果可见性，文件和伴随清单在TOML指定研究目录保存并核对SHA256。原始模型请求和内部思考不进入报告。缺报告404，未完成或校验异常409。前端预览受控Markdown，禁用原始HTML。

报告汇总多个真实任务，不伪造ComputeOutput或挂到单一计算任务。已有CSV输出继续真实预览、下载和登记为表格；地图动作沿用既有栅格/矢量链路。本轮规范Markdown与CSV输出，未新增算法清单的DOCX/XLSX格式。

## 目录文件管理与审核反馈（2026-10-14）

POST `/api/catalog/resources/delete/` 使用 Session/CSRF 与唯一 `X-Project-Id`，需要 `catalog.delete_dataresource`，前端按钮沿用 `canDeleteDataResources`。请求为 `{resourceIds:[...],confirmed:true}`，最多100项、正整数、去重后按原顺序处理。响应 `items` 包含 `resourceId/name/status/detail`，并返回 `deletedIds/deletedCount/failedCount`；200可以部分成功。引用中的资源返回 blocked，存储或数据库失败返回 failed；不存在、跨项目或 owner_only 不可见统一 not_found 且名称为 null。成功才清除选中项并刷新目录。无登录401、无功能权限403、参数或项目上下文错误400。

删除清理真实资源登记、目录成员、关联地图图层、矢量/栅格数据集、独占的受控导入文件与存储层，保留统一数据库容器及其他表。受控路径由TOML及当前项目决定，不接受客户端路径。现有计算输入/入库结果、成果、已保存工程和科研工作流引用阻止删除；引用原因只返回类型，不泄露其他用户对象名称。共享检查读取所有项目登记，保守保留共享存储和外部原始材料。后台已有单项删除仍要求匹配资源名，并委托同一受保护删除服务。

渲染和导出任务提交前，将精简的资源/图层/栅格数据集标识保存到 `RasterProcessingJob.result.inputRefs`，不保存导出的完整几何。任务排队或运行时，相关资源不可删除；ready/failed 后解除这项临时保护，其他永久引用继续生效。初始引用持久化失败时停止任务提交并反馈数据库错误。文件先隔离，SQLite/GPKG 存储表与业务元数据参加同一个数据库事务，提交成功后清理隔离文件；回滚恢复原文件。逐项反馈区分共用存储保留、隔离文件清理失败和原文件恢复失败。

科研工作流 confirm 请求使用 `AgentWorkflowConfirmation`：必填 `planHash`；可选 `decision=approve|reject` 默认approve，`feedback` 最多4000字。approve延续原确认；reject仅在waiting_approval停止后续，保留计算及候选输出。审核意见保存到步骤和检查点，用于判断依据；不作为算法参数或编辑指令。原本人、项目、资源授权与计划哈希检查保持，暂停/状态冲突/旧计划409，参数无效400。

### 地质成果检查与批准范围（2026-10-14）

`geology_map_review`绑定`initial_map`（待检查地质图）、`coverage`（明确制图范围与排除条件）、`rules`（结构化专家规则）。初始确认仅授权检索和检查；模型以实际资料形成`decision.knowledgeQuery`，工作流调用项目范围内知识检索并保存实际条目与修订。该字段仅知识查询阶段提供。

编辑前必须进入`review_modifications`，返回可选`AgentWorkflow.modificationReview`。建议包含实际图斑、当前与建议状态、理由、知识、规则、平方米面积和WGS84范围预览。批准请求在原`planHash`、`decision`、`feedback`之外提供`selectedSuggestionIds`，只允许当前方案中至少一项；后端保存确切批准范围，生成该子集的修改表。拒绝时停止后续编辑。修改建议、原输入、知识或算法版本变化需重新确认；客户端不能传入修改坐标或目标属性替换批准记录。

计算在既有隔离运行器执行，真实输出和新输入继续绑定任务、校验和与资源修订；模型读取修正和复核统计形成最终说明。报告和地图沿用本人、单项目、资源与输出访问授权。建议JSON只支持预览，不替代真实差异图层。
