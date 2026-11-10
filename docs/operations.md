# 开发、测试与部署手册

本文档收敛本地环境、常用验证命令、测试约束和 Linux 部署说明。计算中心支持具备隔离能力的 Docker 模式，也支持 AutoDL 的本机 Python 子进程模式。产品与架构约束见 `docs/design-docs.md`，API 契约见 `docs/openapi.yaml`，接口使用说明见 `docs/developer-guide.md`。

## 本机登录凭据

### 智能体本地验证

智能体使用独立的本地模型模拟服务和独立 worker，不连接李老师服务器，也不读取生产数据。先在一个终端运行 `cd backend; pixi run python manage.py mock_agent_model --port 19100`，再启动平台；启动脚本会单独拉起 `agent_worker`。本地配置在未配置 `[application.agent.models]` 时自动使用 `127.0.0.1:19100/v1` 的合成模型。模拟服务只用于验证界面、流式输出、取消、权限和统计口径。

科研工作流另外使用 `workflow_worker`，负责持久化的计划、checkpoint 和计算任务等待，不与聊天队列共用进程。可用 `start-local.ps1 -Mode Workflow` 单独启动；生产环境只有在超级管理员开启工作流策略后才会提交已发布且标记为 `agent.enabled` 的算子，算子仍由计算中心 worker 执行。工作流 worker 重启时保留 `waiting_compute` 状态，避免重复提交同一算子。

### 服务器候选验收

生产 TOML 需将 `config/agent.example.toml` 的本机模型注册合并到现有配置；不覆盖生产路径、数据库、凭据或师弟的模型启动参数。把 `agent_worker` 加入现有 `/etc/autodl-geomanager.sh` 的应用进程组，保留现有 `PROJ_DATA`、`GDAL_DATA`、`PYTHONPATH` 和配置指针。候选阶段使用新程序目录和候选数据库副本，确认 `/api/agent/bootstrap/`、真实模型流式输出、取消和受控统计后，再切换 6007。只重启 GeoManager 和 agent worker，不重启 19000–19002 的 vLLM 服务。

当前实时核验结果（2026-09-20）：19000 返回 `Qwen/Qwen3.8-27B`；19001、19002 连接拒绝。候选上线前必须重新检查三端口，不把离线模型显示为可用；模型服务异常时平台普通页面与数据目录仍应可用。

本机已部署网页端的超级管理员账号：

```text
用户名：admin
密码：不在仓库保存；读取本机数据目录 database/initial_superadmin_password.txt，或由管理员重设。
```

说明：历史明文密码已从当前文档移除；初始密码文件只代表初始化记录，后台改密后以实际认证为准。旧交接原件仍在本机保存，不上传新仓库。

## 本地环境

本机后端使用 Conda `stisp-geomanager`，解释器为 `/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python`。依赖缺失先确认安装，不切换到 base 或其他环境。Windows 环境说明见 `docs/local-conda-setup.md`；Pixi 配置保留给其他运行环境，不作为本机命令。

前端使用 Node.js 和 pnpm，禁止使用 npm 运行项目脚本。在包含 `frontend/package.json` 的目录执行 pnpm，避免 Corepack 在仓库根目录尝试下载默认版本。现有依赖可以只读复用，不运行自动安装。

```bash
cd frontend
export COREPACK_ENABLE_NETWORK=0
pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false run dev
```

后端本机启动：

```bash
cd backend
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python manage.py runserver --config ../config/app.test.toml
```

默认开发配置使用 `config/app.test.toml`。业务数据根目录和科研数据根目录只从 TOML 读取，代码、业务数据和科研数据必须分离。

常用前端命令：

```bash
cd frontend
pnpm run check:api
pnpm test
pnpm run check
pnpm run typecheck
pnpm run build
```

常用后端命令：

```bash
cd backend
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python -m pytest
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python -m ruff format --check .
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python -m ruff check .
```

## API 与 Mock

`docs/openapi.yaml` 是唯一权威 API 契约。修改接口、响应字段、状态码、权限或认证行为时，同步更新 `docs/developer-guide.md` 和 `docs/api-change-requests.md`，并重新生成前端类型。

```bash
cd frontend
pnpm run generate:api
pnpm run check:api
pnpm run api:changes:check
pnpm run api:docs
pnpm run api:lint
```

前端生成的 Redoc HTML 和 OpenAPI bundle 输出到 `frontend/generated/`。Prism mock 输入文件由 `pnpm run mock:build` 生成到 `mock/prism/openapi.prism.json`，示例数据维护在 `mock/prism/examples/*.json`。

```bash
cd frontend
pnpm run mock:build
pnpm run mock:api
pnpm run dev:mock
```

也可以同时启动 Prism 和 Vite：

```bash
cd frontend
pnpm run dev:with-mock
```

### 前后端分工与交接

计算中心算子制作采用 [operator-authoring.md](operator-authoring.md) 的第2版规范；接口交接记录为 `API-20261110-011`。后端提供带权限的只读 `operator_catalog`、预检 `gaps` 和运行 `failure`，不在目录读取时执行算子或自动转换数据。智能体工具目录与业务流输入准备需显式接入这些服务，不能用字段相似度或前端门禁替代真实来源检查。旧版本包保持不可变，新包须上传新草稿、实际试运行后发布；旧工作流固定的版本不会随示例源码升级而改变。

- 前端维护 `docs/openapi.yaml`、`docs/api-change-requests.md` 和按领域划分的 `mock/prism/examples/`；生成类型来自契约，不能在 UI 类型文件手写另一套 DTO。示例使用实际可用的资料元信息，缺失时使用合理的中文小样例，不依赖其他开发者机器的绝对路径。
- API 交接记录写明接口、变更、前端原因、示例文件、后端实现注意点及验证预期。修改契约或示例后运行 `api:changes:check`；生成的 Prism 文件只通过 `mock:build` 更新。
- 后端按契约、示例及交接记录实现行为和测试，真实响应一致后才标记已实现。无法安全实现时先提出契约调整，不静默返回不同结构。
- 前后端分人开发时不越界修改对方应用代码；必须跨界时先明确交接范围，并在完成报告中说明。契约与生成物先落地，再做后端实现、前端使用，最后更新文档；共享文件避免并行覆盖。
- `frontend/src/types.ts`、`frontend/src/App.tsx`、`backend/apps/core/permissions.py`、实现笔记和 Changelog 仅在任务确需时最小修改。不用临时前端兜底或未声明后端兼容分支掩盖契约缺口。

## 测试分层

后端测试使用 pytest + pytest-django：

- `backend/tests/unit/` 覆盖配置加载、路径约束、字段规范化、查询过滤、栅格规则、瓦片坐标、进度解析等纯逻辑。
- `backend/tests/integration/` 使用 Django test client 覆盖认证、权限、目录、图层、导入、导出、栅格和后台管理 API。
- 需要文件、GeoPackage、SQLite 或上传样本时，测试必须使用临时目录或测试内创建的小样本，不依赖真实业务或科研数据目录。
- 导入回归验证结构、字段类型、坐标字段及空间范围，失败返回可纠正的结构化错误；目录分类保持主题、时间、空间和来源一致。数据、权限、配置、导入、导出及栅格任务的关键操作沿用 audit 记录。
- 超级管理员隔离回归测试覆盖用户列表、角色列表、日志查询、日志角色范围、上传人脱敏和访问角色过滤；新增权限隔离问题时优先在 `backend/tests/integration/core/test_api.py` 或对应应用集成测试中补充后端断言，确保敏感主体不从 API 返回。
- 权限安全回归需要覆盖组合入口，而不是只测单个接口。`FeaturePermissionTests::test_regular_admin_security_surfaces_do_not_serialize_superadmin_principals` 以非超级管理员身份连续读取用户、角色、操作日志和 Dashboard，断言响应集合中没有超级管理员账号、角色、Django superuser 或其日志摘要。

前端测试使用 Vitest、Testing Library 和 happy-dom：

- 工具函数、API 客户端、Mapbox 样式辅助函数和 hooks 走单元测试。
- 关键登录、路由和权限门禁流程通过挂载完整 React 应用并 mock 后端 API 覆盖。
- 后台认证授权和存量数据管理的权限隔离流程使用 `pnpm run test:browser -- src/admin/AdminRoutes.browser.test.tsx` 覆盖真实浏览器渲染，确认 API 已脱敏的超级管理员主体不会出现在 UI、抽屉或选择控件中。
- 长程用户体验回归使用 `pnpm run test:browser -- src/App.browser.test.tsx -t "long research user journey"`，从普通科研用户视角覆盖进入地图、选择资源、查询加载图层、查看图层范围开关、进入后台日志，并确认认证授权、系统设置、系统日志和超级管理员主体均不可见。
- 真实地图交互或 WebGL 行为需要独立引入 Playwright 等浏览器 E2E，不混入稳定 CI 测试。

验证范围按 `AGENTS.md` 的“变更分级”执行，不为局部界面调整自动运行完整构建和浏览器全套。测试使用临时配置和小样本，不能通过放宽断言、删除 mock 或关闭原有检查消除失败。

### 快速验证入口

```bash
make verify-fast
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python scripts/verify_fast.py --list
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python scripts/verify_fast.py --base main --browser
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python -m pytest scripts/tests/test_verify_fast.py -q
```

默认比较 HEAD 与当前工作树，包含已暂存、未暂存和未跟踪文件；不操作索引或分支。`--base` 改比较基准，`--list` 仅打印计划，`--browser` 才执行浏览器测试；无可检查改动时成功退出。解释器、pnpm 前缀、测试映射及各步超时集中在 `scripts/verify_fast.py` 顶部。

- `backend/`、`scripts/` 下的 Python 文件先做增量 Ruff 格式检查；其他 Python 工具显式列为未自动覆盖，走所属工具自己的验证入口。后端优先使用显式映射、同名或应用前缀测试；找不到同名测试时，在应用映射范围内用 AST 识别直接模块引用，包括 import/from（含别名、函数内导入）、完整模块属性访问、patch/monkeypatch/import_module 等字符串路径，不依据 reverse 或 URL 猜测间接关系。仍无直接引用时才退回应用范围，并输出“未找到直接相关测试，已退回应用级范围，共 N 个文件”；13 个应用均有映射。非效率路径排除 `efficiency` 标记，模块级全效率测试不启动空选择。路径命中只纳入相关效率用例，不等于已运行完整效率门禁。
- 后端测试集合取并集并排除不适用的全效率文件后，超过配置区 `BACKEND_TEST_FILE_WARNING_LIMIT`（默认 15）时，在计划开头醒目显示数量、预计扩大的原因；只提示、不截断，仍按原集合执行。静态引用不等于完整调用链覆盖；API、权限、并发及其他高风险变更仍须执行对应完整门禁。
- 前端以 `vitest related` 选择单元测试，TypeScript 改动附加类型检查，现存改动文件交给 oxlint。oxlint 不检查 CSS 语义，因此 CSS 另做 Oxfmt 格式检查。只有浏览器用例、没有相关单元用例时，明确显示无单元测试，并列出浏览器命令，不把它说成界面验证通过。
- 单元检查使用既有 `vitest.config.ts` 和 `--configLoader native`，避免 Vite 把临时配置写入仓库外的共享 `node_modules`；不更改测试集合或断言。浏览器仍只走 `frontend/scripts/run-browser-check.mjs`，由该入口验证源码一致性并管理 ASCII 临时镜像。
- 契约或 Mock 示例变更运行 `check:api`、`api:changes:check`；这不代替大改动的契约五条完整流程。文档与图片不触发测试。快速入口自身或 Makefile 改动也会运行脚本映射回归。
- 浏览器候选由本地静态 import/export 依赖闭包及配置映射补充；全局样式影响所有浏览器文件。动态拼接路径、间接注册、运行时依赖和源码内容语义不能完全推断；新增入口须补映射并人工确认列表。新应用缺映射直接失败，不默默漏测。无法找到对应测试的脚本只检查格式，仍需人工补充行为回归。
- 超时、格式问题、命令不可用或任一步失败均返回非零，并继续展示其他步骤结果。该入口不构建、不部署，也不代替权限、缓存、并发或科学一致性相关的大改门禁。

### 本机验证耗时

测量日期 2026-11-10；同一工作区、已有 Conda 和 pnpm 依赖，使用单调时钟记录墙钟时间。日志与原始 JSON 在 `.runtime/agent-rules-20261110/`。下表是观测值，不承诺其他机器或冷缓存耗时。

| 检查 | 墙钟时间 | 结果 |
| --- | ---: | --- |
| 前端 `typecheck` | 5.306s | 通过 |
| 前端全量 `pnpm test` | 0.399s | 沙箱拒绝向仓库外共享依赖的 `.vite-temp` 写配置，未运行测试 |
| 同一 Vitest 配置、全量用例，`--configLoader native run` | 3.419s | 83 文件、589 用例通过 |
| `build:verify` | 10.634s | 品牌、文案、契约和类型阶段通过；效率单元阶段受上述写限制阻断，未到 Vite 构建 |
| 后端全量收集 `--collect-only -q` | 1.876s | 成功收集 3504 项 |
| 后端 `-m efficiency -q` | 27.111s | 106 通过、3398 未选 |
| 假设只改 `backend/apps/core/cli.py` | 计划 0.202s；执行 0.592s | 格式和 8 项相关测试通过 |
| 假设只改 `frontend/src/components/RightSidePanel.tsx` | 计划 0.196s；执行 7.464s | 21 项相关单元、类型、lint 通过 |
| 假设只改 `frontend/src/styles/login.css` | 计划 0.202s；执行 1.733s | 无相关单元用例；oxlint 调用、CSS 格式通过，浏览器未执行 |
| 当前工作区 `make verify-fast` | 21.181s | 6 个 Python 文件格式、51 项后端测试、31 项映射测试通过；独立发布工具显式列为未覆盖 |

假设改动通过向同一规划函数注入单文件列表执行 `--list` 和实际步骤，不修改应用文件或 Git 状态。最初选择的栅格 `color_mapping.py` 样本执行 0.721s（计划 0.234s），13 项测试通过，但文件已有 Ruff 格式差异使检查失败；没有为计时修改该应用文件。中级浏览器、完整大改门禁及发布流程未取得成功耗时，不作估计。

## 统一发布与数据保护

卡片预生成缩略图升级：候选切换前，使用候选代码、项目后端解释器及该环境已有 TOML，先运行 `python backend/manage.py backfill_card_thumbnails --dry-run`，再运行 `python backend/manage.py backfill_card_thumbnails`；失败项修复后重跑，已完成版本不会重编码。确认 `pdftoppm` 可用后再验收 PDF 首页。存量回填不得触及原始科研文件，不能以本机空库替换服务器业务库；本机构建仍通过已有 `local.buildResources` 提供四张未跟踪原图，构建会自动生成肖像小图，原图不进 Git。具体规格、权限与续跑规则见开发指南“卡片图片规则”。

发布入口固定为 `tools/release/release.py`，子命令仅用 `inspect`、`fast`、`full`、`status`、`rollback`。入口未就绪或检查失败即停止，不在 `.runtime` 新写、复制改写或串接历史私有发布脚本。下文 Docker 与镜像章节只描述相应运行环境，不授权绕开统一入口或启用旧 GitHub Actions 自动部署。

发布顺序：本机验证并冻结精确 commit SHA 和发布包 → 上传新候选目录 → 候选验收 → 备份与切换 → 生产验收及回执 → 按授权同步同一 SHA 到 GitHub。开发分支备份不等于服务器验收。小更新可不升级版本；统一升级时再更新版本文件、Changelog 及新标签，不移动已有正式标签，不批量推送历史标签。

配置、业务数据、科研数据与代码分离，不以本机数据库覆盖生产库。保留原始交接包、发布回执、发布目录及恢复点；仅管理已核实身份的本项目进程，不擅自重启 vLLM、Jupyter 或 AutoDL 代理。服务器应急修改先取到独立目录审查，再合并为新的本地提交并重新验收，不能用服务器目录覆盖工作树。回执、发布包和同步的 GitHub 提交必须一致；效率门禁与实际数据验收结果进入发布回执。

### 浏览器发布兼容与账号隔离

替换正式静态目录前，用新候选代码的 `archive_frontend_assets --source <上一正式版本>/frontend/dist` 保存完整公共构建依赖，并归档新构建；两者归档成功才切换。历史资源位于应用缓存，不复制科研资料；默认保留 14 天、64 构建、512MiB。旧资源未命中时提供明确的手动刷新操作，不自动循环 reload。正式前端验证构建保留默认 `/static/` 基址。

每个前端请求在响应正文解析完成及处理 401/403 前，仍核对发起时的登录代次、授权范围、项目和取消状态；迟到旧响应不得进入新账号界面。不得延长授权缓存、吞掉真实超时、构造空权限或跳过后端 ACL 来消除错误。异常 HTML 与缺字段由统一响应边界拒绝，保留可重试界面。浏览器回归使用既有入口并核对源码一致，不删除 mock 或放宽断言绕过环境问题。

## Docker 部署

Linux 部署使用单个 Docker 镜像和 TOML 配置。镜像构建使用 `backend/pixi.lock` 创建后端运行环境，不需要配置文件；容器运行时把包含 `app.toml` 的宿主机配置目录挂载到 `/config`。镜像内由 Waitress 运行 Django WSGI 应用，Django 同时提供 `/api/` 接口和前端 Vite 构建产物；对公网关、HTTPS 和域名由宿主机上的反向代理自行配置。业务数据和科研数据保存在同一个 Docker 数据卷 `huyang-data` 中，并挂载到容器内 `/data`。

容器内固定路径：

- 程序目录：`/opt/app`
- 后端目录：`/opt/app/backend`
- 后端 Pixi 环境：`/opt/app/backend/.pixi/envs/default`
- 前端构建产物：`/opt/app/frontend/dist`
- 默认输入配置：`/config/app.toml`
- 默认业务数据根目录：`/data/app`
- 默认科研数据根目录：`/data/research`

Docker 容器内配置示例见 `config/app.docker.toml`。其中容器内路径、Waitress 监听地址和默认运行参数已经固化；通常只需要按部署环境调整 `allowed_hosts`、`csrf_trusted_origins`、`waitress_port`、`waitress_threads`、`mapbox_access_token` 和 `tianditu_access_token`。

`tianditu_access_token` 必须使用天地图服务中心控制台签发的 32 位“浏览器端”应用 Key，不能把真实 Key 写入镜像、仓库或示例配置。浏览器端 Key 还必须在天地图控制台“我的应用 → 设置”中配置允许访问的域名：本地联调至少覆盖实际使用的 `localhost` 和/或 `127.0.0.1`，生产环境覆盖平台实际 HTTPS 域名；如果用户还会通过服务器 IP 或其他域名访问，也要分别纳入。域名项按控制台要求填写，不附带 URL 路径。未配置或不匹配时，WMTS 请求会返回 HTTP 403，以及错误码 `301007`（域名不匹配），平台会回滚到上一个可用底图。

服务器应把 Key 写入宿主机实际挂载目录的 `app.toml`，或以管理员身份在“后台管理 → 系统设置 → 天地图浏览器 Key”中保存。后台保存要求整个可写配置目录挂载到 `/config`；只挂载单个 `/config/app.toml` 会破坏原子替换。保存后用生产域名打开地理工作台并切换到天地图，确认 `vec_w` 与 `cva_w` 请求均返回 200、响应类型为图片、底图状态正常且业务图层仍在，才算完成生产验收。

手动 `docker run` 时，先把 `config/app.docker.toml` 复制为宿主机配置目录中的 `app.toml`，再把整个目录挂载到 `/config`。配置应使用容器内数据路径 `/data/app` 和 `/data/research`。业务数据和科研数据使用同一个 Docker named volume，不需要映射宿主机目录。

构建和启动：

```bash
docker build -t data-platform-django:latest .

docker volume create huyang-data

docker run -d --name data-platform \
  -p 80:8000 \
  -v /srv/data-platform/config:/config \
  -v huyang-data:/data \
  --memory=2300m \
  --memory-reservation=1800m \
  --memory-swap=2300m \
  --cpus=2 \
  --pids-limit=256 \
  --restart=unless-stopped \
  --log-driver=json-file \
  --log-opt max-size=10m \
  --log-opt max-file=5 \
  data-platform-django:latest serve /config/app.toml
```

Docker 配置中的数据目录应直接使用容器内路径 `/data/app` 和 `/data/research`。`docker run -p` 的宿主机端口应与 `runtime.waitress_port` 保持一致，或按反向代理需求另行映射。

### 4 GB 主机的内存安全基线

`config/app.docker.toml` 默认面向小内存单机：Waitress 使用 2 个请求线程，查询单次最多返回 5,000 条，可配置上传限制为 64 MB，栅格单边限制为 12,000 像素，并关闭目录与栅格启动扫描。后台允许设置的硬范围为栅格与独立成果上传 1–1024 MB、查询 100–10,000 条、栅格单边 1–12,000 像素和栅格任务超时 10–600 秒；Waitress 请求体硬限制为 1152 MiB，并以 720 秒连接超时为 1024 MB multipart 上传和最长 600 秒栅格任务留出余量。Django 的普通请求内存上限仍为 10 MiB、文件内存阈值仍为 2 MiB，大文件必须落临时磁盘，不能提高这两个内存阈值。矢量导入继续取平台配置与 120 MB 的较小值，表格在线解析继续取平台配置与 16 MB 的较小值；专题出图 PNG 保持独立 128 MB 上限并在完整解码前校验大小与像素边界，且不随可配置上传上限变化，避免整层、整表或图片解码耗尽内存。需要扫描时应在平台稳定后由有维护权限的用户手动触发；栅格导入、扫描、渲染和导出共用单并发、有界等待队列，不能通过提高 Waitress 线程数绕开该限制。

把生产运行值提高到 1024 MB 前，必须同步检查反向代理和磁盘。Nginx 可使用 `client_max_body_size 1152m`、`client_body_timeout 300s`、`proxy_send_timeout 300s`、`proxy_read_timeout 720s`，并保持 `proxy_request_buffering on`，通过磁盘缓冲保护应用进程。Nginx `client_body_temp_path` 和容器 `/tmp` 不能挂在 tmpfs；单次 1 GiB 栅格导入建议至少预留 8–10 GiB 可用磁盘。若域名前有 CDN/WAF，还必须确认其套餐请求体上限；低于 1 GiB 时应使用不经过该代理的受控上传入口，不能仅靠 Nginx 设置绕过。

这些文件是新部署样例，不会覆盖现有服务器的 `/config/app.toml`，其中 64 MB 也刻意保留为安全默认值。升级已有容器前必须备份宿主机 TOML，把它迁移到专用配置目录并改为目录挂载，然后显式重建容器以应用挂载、memory、CPU、pids、restart 和日志参数；单独执行 Watchtower 不会改变挂载配置或现有 HostConfig。首次部署新镜像应先保留原运行值完成健康检查，再把服务器实际挂载的 `application.limits.upload_max_mb` 显式改为 1024 并验证大栅格。单文件 bind mount 会使后台保存时的原子 `os.replace()` 返回 `Device or resource busy`，因此不能继续用于可在线维护的配置。本文示例容器名为 `data-platform`；现网容器名如果是 `geomanager`，所有检查、重建和 Watchtower 目标必须统一使用 `geomanager`，不能混用。

容器的 `2300m` 硬限制用于给 4 GB 宿主机、Docker daemon 和反向代理保留约 1.5 GB。容器可能在超限时单独重启，但不得再次拖垮宿主机。`--memory-swap` 与 `--memory` 设为相同值表示不允许容器额外消耗 swap；若宿主机有其他业务，应继续下调，而不是取消限制。镜像内置 `/api/health/` 健康检查，并从挂载的 `/config/app.toml` 自动读取容器内 Waitress 端口；宿主机端口映射仍需与实际端口保持一致。

发生卡顿或 OOM 时先保留证据，不要立即清理镜像或日志：

```bash
journalctl -k --since "30 minutes ago" --no-pager
docker inspect data-platform --format 'Status={{.State.Status}} OOMKilled={{.State.OOMKilled}} Exit={{.State.ExitCode}} RestartCount={{.RestartCount}}'
docker stats --no-stream data-platform
docker top data-platform -eo pid,ppid,nlwp,rss,vsz,etimes,args
docker exec data-platform sh -c 'cat /sys/fs/cgroup/memory.current; cat /sys/fs/cgroup/memory.max; cat /sys/fs/cgroup/memory.events'
```

如果数据库里存在服务重启前遗留的 `queued/running` 栅格任务，新进程首次访问任务系统时会将其标记为失败并提示重新提交；不要把这些僵尸状态误判为仍在执行。

### 镜像更新与回滚

Watchtower 只会根据容器当前的 image tag 拉取容器镜像，不会在服务器上执行 `git pull`，也不会从 GitHub Fork 直接构建代码。工作流使用 `ghcr.io/${GITHUB_REPOSITORY_OWNER,,}/geomanager`：主仓库 `yiguanxianyu/GeoManager` 构建的是 `ghcr.io/yiguanxianyu/geomanager`，Fork `TujinoO/GeoManager` 构建的才是 `ghcr.io/tujinoo/geomanager`。推送源码后必须先确认 GitHub Actions 已成功发布镜像，并以成功任务显示的实际 tag/digest 与现网容器 `.Config.Image` 为准。镜像命名空间必须与签发 `GITHUB_TOKEN` 的仓库所有者一致，否则构建完成后会在推送阶段因包写入权限不足而失败。

生产更新应记录当前 image ID/digest，并把旧 digest 与修改前的 `/config/app.toml`、反向代理配置备份配对保存。新容器启动时会执行 Django migration，因此更新前还必须确认平台备份任务成功，或为 `huyang-data` 中的数据库和关键业务数据制作经过校验的可恢复快照。优先部署提交 SHA tag 或固定 digest；修改 Nginx 后先运行 `nginx -t`，再 reload，完成容器健康检查、`/api/bootstrap/` 中 `uploadMaxMb=1024`、关键页面和代表性上传冒烟验证后再清理旧镜像。首次故障恢复不要使用 Watchtower `--cleanup`，否则新镜像异常时可能失去便捷回滚目标。

回滚时不能只恢复旧镜像：旧版本最多接受 120 MB 配置，必须先恢复与旧 digest 配对的旧 `app.toml`，再按原挂载、端口和资源限制用旧 digest 重建容器。数据卷是否保持现状必须依据迁移兼容性决定；若新迁移不支持降级，应同时恢复升级前的数据快照。回滚后重新检查健康状态、日志和关键页面。

远程管理应使用 SSH key，并关闭公网密码登录。密码一旦出现在聊天、终端录屏或共享日志中，应立即轮换；任何口令都不得写入仓库、部署脚本或命令历史。

如果容器前面有 Nginx、Caddy、云负载均衡或 CDN，反向代理必须把源头客户端 IP 通过 `X-Forwarded-For`、`X-Real-IP`、`CF-Connecting-IP`、`True-Client-IP` 或标准 `Forwarded` 请求头传给后端。操作日志会优先从这些请求头中选择公网 IP；只有没有有效公网 IP 时才回退到 `REMOTE_ADDR`，此时 Docker 网桥环境可能显示为 `172.19.x.x` 之类的内网地址。

### 浏览器内容安全策略与 Mapbox GL JS

平台对 Django 返回的 HTML 强制发送 `Content-Security-Policy` 和 `Permissions-Policy`，前端入口 HTML 也包含同等 CSP 兜底。策略禁止页面加载音视频、对象插件、外域脚本和外域框架，并禁用自动播放及画中画，以阻断数据导入页等功能页面上由被污染入口或代理注入的媒体浮层。

当前前端使用依赖包中的 ESM 版 `mapbox-gl`，并已禁用 Mapbox events 采集。完整策略为：

```text
default-src 'self';
base-uri 'self';
object-src 'none';
frame-ancestors 'none';
form-action 'self';
script-src 'self';
style-src 'self' 'unsafe-inline';
worker-src 'self' blob:;
img-src 'self' data: blob: https://api.mapbox.com https://tiles.openfreemap.org https://*.tile.openstreetmap.org https://*.tianditu.gov.cn https://images.unsplash.com;
font-src 'self' data:;
connect-src 'self' https://api.mapbox.com https://tiles.openfreemap.org https://*.tile.openstreetmap.org https://*.tianditu.gov.cn;
frame-src 'self' blob:;
media-src 'none';
manifest-src 'self';
```

如果后续使用非 Mapbox 官方账号的自定义样式或字体，需要同步把对应的 `/styles/v1/{username}/`、`/fonts/v1/{username}/` 端点加入 `connect-src`。只有重新启用 Mapbox events 采集时，才需要额外允许 `https://events.mapbox.com`。

如果页面仍出现带关闭按钮的陌生视频或广告浮层，先在无扩展的浏览器访客窗口复测，并检查响应头是否保留上述 CSP。浏览器特权扩展可以绕过站点策略，HTTP 链路也可能被代理篡改；生产环境应优先使用 HTTPS，并停用或卸载触发注入的浏览器扩展。反向代理可以补充安全响应头，但不得覆盖为更宽松的策略。

默认数据卷名称为 `huyang-data`。如需改名，直接创建并挂载新的 Docker volume：

```bash
docker volume create data-platform-data
docker run -d --name data-platform \
  -p 80:8000 \
  -v /srv/data-platform/config:/config \
  -v data-platform-data:/data \
  data-platform-django:latest serve /config/app.toml
```

重建容器不会删除数据卷。如需备份、迁移或删除数据，请直接操作对应 Docker volume。

系统以挂载目录中的源配置文件 `/config/app.toml` 作为运行配置和后台设置写入目标。后台保存会在 `/config` 内写入临时文件、校验 TOML 后再原子替换 `app.toml`，因此该目录必须可写。`django_secret_key` 自动生成并持久化到业务数据目录的 `database/.secret_key`，由后端专用文件管理。

## 数据目录

业务数据根目录固定子目录：

```text
database/
media/
uploads/
exports/
logs/
static/
config/
```

科研数据根目录固定子目录：

```text
vector/
  original/
    uploaded/
raster/
  original/
  preprocessed/
  metadata/
    source/
    preprocessed/
gene/
table/
```

统一 GeoPackage 矢量数据放入科研数据根目录的 `vector/vector.gpkg`；浏览器上传的 Shapefile ZIP、GeoJSON 和 GeoPackage 原始文件以 UUID 文件名归档到 `vector/original/uploaded/`，原始文件名和 SHA256 保存于 `VectorDataset`。栅格原始数据包放入 `raster/original/uploaded/{uuid}/`，GeoTIFF/IMG 可单文件归档，ENVI 数据保留主文件与 HDR，VRT 保留全部包内引用文件和 `manifest.json`；展示 COG 写入 `raster/preprocessed/`。基因数据放入 `gene/`，表格数据放入 `table/`。栅格符号化在后端完成，前端只加载后端生成的 XYZ 或 PNG 结果。

## 常见问题

### 本机计算中心

计算中心位于 `/compute`，算法维护位于 `/admin/compute`。当前实施和待完成验收见 [计算部署记录](2026-09-19-compute-deployment.md)。`start-local.ps1` 统一启动前端、后端和独立 compute worker；worker 非零退出后会重启。日志位于 `logs/local-Compute.*.log`。本机仍采用原 Vite/Django 开发服务，不表示已配置远程生产站点或开机自启。

Windows 必须完成 WSL2 组件启用及其要求的重启，才可在项目根执行 `./deploy-compute.ps1 -WithRuntime`。脚本安装 WSL 发行版内的 Docker、构建 `deploy/compute/Dockerfile`、写入 TOML、停止原本机服务、迁移/初始化草稿并重新启动。它不会重启 Windows。启用组件的脚本是 `deploy/install-compute-wsl.ps1`，安装记录位于 `.runtime/compute-wsl-install.json`。发行版和镜像下载需要联网。

2026-09-19本机已完成以上安装及真实计算验收；正常启动只需 `./start-local.ps1 -NoBrowser`。最终状态记录为 `.runtime/compute-deployment.json`，旧组件安装记录中的restart-required是历史状态。Docker已设置随Ubuntu systemd启动，验证过子系统终止后由应用worker重新唤起。

若WSL直连Docker Hub超时，保持用户现有网络模式。可在Windows使用 `deploy/pull-compute-base.py`，它通过现有127.0.0.1代理获取官方Python基础镜像并验证manifest/config/layer摘要，将生成的 `.runtime/compute-base-image/python-3.12-slim-bookworm.tar` 用WSL Docker的 `load --input <对应/mnt路径>` 导入，再执行部署脚本。不要为取镜像开放Docker TCP端口或新增公开代理监听。当前镜像构建中PyPI/Ubuntu/Debian源可直接访问。

Linux 原生部署可直接构建同一 Dockerfile，用 `configure_compute_runtime` 配置 Docker 命令；受限 AutoDL 实例也可显式使用 `configure_compute_runtime --native` 配置本机 Python 子进程执行，并将 `manage.py compute_worker --config <实际配置>` 交由进程管理器运行。native 模式不提供容器的文件系统、网络和 capability 隔离，只有在管理员接受该运行边界时启用。无可用执行环境或无 worker 时，应用应拒绝提交。新增版本须完成试运行和人工核对输出后发布；Docker 模式保留仍被任务/版本引用的旧镜像摘要，native 模式保留 Python 依赖摘要。

计算运行器失败时，内部状态文件在既有`status`之外携带受限的`error_type`和`error_detail`。异常类型限制为64个ASCII标识符字符，说明只允许固定错误分类及内存分配量，不传出原始异常文本、路径、口令或令牌；例如任务失败信息显示“内存不足：无法分配25.9 MiB”。宿主进程再次校验字段白名单，不接受算子自行注入的任意说明。native与Docker共用该协议，状态文件超过4096字节仍拒绝。需同时更新平台的`deploy/compute/runner.py`及`backend/apps/compute/runtime.py`并重启本项目compute worker；只上传算子ZIP不会启用失败原因展示。进程在写状态前被系统杀死时仍显示原有提前退出提示，不能保证取得异常类型。

计算包/持久结果位于 TOML 应用数据根 `projects/<project>/compute/`，工作暂存位于 `cache/compute/`；正式数据沿用原科研根目录。完整平台备份会包含计算模型及持久文件，缓存不纳入备份。结果 7 天过期清理只影响临时文件；任务元信息首版持续保留。默认一个重任务名额与栅格任务共享，不支持 GPU 或任意在线安装依赖。

Windows 中文数据路径下，GDAL CLI 需要由 `apps/core/cli.py` 统一封装传入 Unicode 数据目录及临时目录。不要绕过封装直接调用栅格导入 CLI，否则可能再次出现找不到 `proj.db` 或临时文件路径乱码。

### 常规排查

- pnpm 依赖异常：先核对 Node、项目 `packageManager` 和现有依赖位置；共享依赖只读不可写时，不删除或重装其他工作区的依赖。需要安装或清理先确认范围。
- 本机 Python/GDAL 错误：先核对是否使用本节指定的 `stisp-geomanager` 解释器及其 GDAL/PROJ 路径；缺包先询问，不改 base 或其他环境。
- 其他机器的 Pixi 环境问题：核对 `backend/pixi.toml` 与 `backend/pixi.lock`，按该运行环境的部署说明处理，不套用到本机。
- 权限问题：不要用 `sudo` 运行 pnpm 或环境管理器，优先检查安装路径和目录权限。
