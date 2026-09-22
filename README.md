# 时空智能服务平台（STISP）

接续开发私有仓库：[cutiromero/STISP-GeoManager](https://github.com/cutiromero/STISP-GeoManager)。当前 Windows 本机运行见 [Conda 环境说明](docs/local-conda-setup.md)，版本来源及日常同步见 [代码跟踪说明](docs/github-code-tracking.md)。新库保存开发代码，不会自动部署新疆服务器。

**Spatiotemporal Intelligence Service Platform · GeoManager**

时空智能服务平台面向空间数据管理、遥感分析与科研协作，整合数据汇聚、地理可视化、算法计算、专题制图和成果共享。用户通过浏览器进入地理工作台，在具体项目中组织数据、运行计算任务并管理成果。

当前产品名称为“时空智能服务平台”，仓库名称保留为 `GeoManager`。现有生态研究资料和历史专题内容继续作为平台的数据与应用案例。

## 主要功能

- **地理工作台**：矢量与栅格图层加载、底图切换、图层管理、属性查询、空间查询和工程保存。
- **数据资源**：地理与非地理数据的目录检索、导入校验、元数据管理、预览和导出。
- **计算中心**：管理员登记算法、上传版本、试运行并发布；用户选择项目数据提交任务，查看进度、下载结果或将结果入库。
- **专题制图与成果展示**：保存制图工程、配置输出版式、导出专题图，并组织和发布成果。
- **多项目协作**：支持公开项目与按成员授权的项目；数据、工程、计算任务和成果归属具体项目，角色控制操作权限。
- **内容与系统管理**：时空科普、团队动态、用户角色、系统设置、操作日志及平台与科研数据备份。

计算中心需要部署受控的执行环境和 worker。支持 Docker 容器模式，也支持 AutoDL 使用的本机 Python 子进程模式；应用网页可访问并不代表计算环境已经就绪。现有示例包括 NDVI、栅格线性变换、矢量缓冲区和表格分组统计，见 [`examples/compute/`](examples/compute/)。

## 技术与目录

前端采用 React、TypeScript、Vite、Ant Design 和 Mapbox GL JS；后端采用 Django、Waitress、GDAL、GeoPandas 和 Rasterio。业务元数据使用 SQLite，矢量数据使用 GeoPackage，运行配置使用 TOML。栅格渲染在后端完成，前端加载渲染结果。

| 目录 | 用途 |
| --- | --- |
| `frontend/` | 地理工作台、数据资源、计算中心和后台管理界面 |
| `backend/` | 认证权限、数据管理、栅格服务、计算任务及日志 |
| `config/` | 开发与部署配置示例 |
| `examples/compute/` | 计算中心示例算法包 |
| `deploy/` | 部署工具与服务器同步脚本 |
| `.github/workflows/` | GitHub Actions 镜像构建与发布流程 |
| `docs/` | 产品规则、API 契约、开发与运维文档 |

程序代码、业务数据和科研数据分别存放；两个数据根目录由 TOML 配置指定。

## 本地运行

准备 Node.js、pnpm 和 Pixi。首次运行时，将 [`config/app.example.toml`](config/app.example.toml) 复制为本机的 `config/app.test.toml`，填写实际的业务与科研数据目录，并按需要配置底图 Token。已有本地配置时保留原文件；`config/app.test.toml` 已被 Git 忽略。

在一个终端启动后端：

```bash
cd backend
pixi install
pixi run migrate
pixi run dev
```

在另一个终端启动前端：

```bash
cd frontend
pnpm install
pnpm dev
```

访问 [http://127.0.0.1:5173](http://127.0.0.1:5173)。前端默认代理到 `http://127.0.0.1:8000`；后端端口有变化时，在前端本地环境配置中设置 `VITE_API_PROXY_TARGET`。

Pixi 的开发和迁移任务均读取 `config/app.test.toml`。生产部署需要指定对应的生产配置，底图 Token、账号凭据与业务数据独立于源码管理。

## Docker 部署示例

以下示例适用于已具备 Docker 的新部署环境。镜像构建使用 `backend/pixi.lock` 安装后端依赖，由 Waitress + Django 提供 API 和前端构建产物。

先将 [`config/app.docker.toml`](config/app.docker.toml) 复制为宿主机配置目录中的 `app.toml`，填写实际访问主机、可信来源和底图 Token。将整个可写配置目录挂载到 `/config`，后台设置才能通过原子替换持久化；不要仅挂载单个配置文件。

```bash
docker build -t geomanager:latest .

docker volume create geomanager-data

docker run -d --name geomanager \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  -v /absolute/path/config:/config \
  -v geomanager-data:/data \
  geomanager:latest
```

容器配置中的数据路径保持：

```toml
[application.storage]
app_data = "/data/app"
research_data_root = "/data/research"
```

`/data/app` 保存业务数据库、媒体、日志等运行数据，`/data/research` 保存科研数据。已有部署应继续使用原有数据卷和配置目录；示例中的 `geomanager-data` 名称仅用于新部署。

`127.0.0.1:8000` 适合由宿主机反向代理提供外部访问。完整部署与资源限制说明见 [`docs/operations.md`](docs/operations.md)。

## GitHub 与服务器更新

本仓库位于 [spAurora/GeoManager](https://github.com/spAurora/GeoManager)。推送到 `main` 后，GitHub Actions 会构建并发布 `ghcr.io/spaurora/geomanager` 镜像，包含 `latest` 和提交短 SHA 标签。构建发布成功后，服务器仍需通过已配置的部署流程应用该版本。

截至 2026-09-20，当前部署状态为：

| 链路或能力 | 状态 |
| --- | --- |
| 本机 → GitHub | 已可推送源码与文档 |
| 本机 → 服务器 | 已可通过 SSH 上传文件、配置和手动部署 |
| 服务器主动访问 GitHub | 直连测试超时，已停止尝试 |
| GitHub → 服务器自动部署 | 尚未配置和验证 |
| 每日北京时间 04:00 自动更新 | 仓库已有 Docker 同步脚本与定时器，现网尚未启用 |

当前服务器使用 Waitress 直接运行应用，计算中心可切换到本机 Python 子进程模式；Docker 同步脚本不能直接用于该实例。底图 Mapbox 与天地图 Token 已从本机写入服务器运行配置，并通过应用端口和公网转发接口确认生效。Token 不随源码或镜像发布。

详见 [同步方案](docs/server-sync.md) 和 [现网核查记录](docs/2026-09-20-server-sync-audit.md)。后续同步方案需适配实际运行环境；服务器访问 GitHub 失败时保留当前服务并报告问题。

## 开发检查

前端检查与测试：

```bash
cd frontend
pnpm run check
pnpm run check:api
pnpm test
```

后端检查与测试：

```bash
cd backend
pixi run lint
pixi run test
```

需要格式化时，前端使用 `pnpm run fix`，后端使用 `pixi run format`。测试分层、接口变更和部署验收说明见 [开发、测试与部署手册](docs/operations.md)。

## 文档导航

- [当前有效平台规则](docs/current-platform-rules.md)：当前功能与权限规则的优先依据。
- [设计文档](docs/design-docs.md)：架构与历史设计背景；历史阶段描述以当前规则为准。
- [OpenAPI 契约](docs/openapi.yaml) 与 [接口开发指南](docs/developer-guide.md)。
- [计算中心本机部署与验收](docs/2026-09-19-compute-deployment.md)：独立计算环境、示例算法与验收范围。
- [实现记录](docs/implementation-notes.md) 与 [版本记录](CHANGELOG.md)。
