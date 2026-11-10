# GeoManager 开发入口

时空智能服务平台：React / TypeScript / Vite / Ant Design / Mapbox GL JS；Python / Django / GDAL / Rasterio，业务 SQLite、矢量 GeoPackage。

## 开始工作
- 先查 `docs/agent-map.md`，只读任务相关代码、测试和文档章节；产品行为查 `docs/current-platform-rules.md`，架构疑问再查 `docs/design-docs.md` 对应章节。
- 开始时检查一次工作区、差异和近期历史，识别并保留并行修改；没有新证据时不重复核查已知事实，不逐步执行 `git status`。
- 固定个人分支 `codex/<developer>`，当前 `codex/xintao`；不新建功能分支。从已核实的 main 同步，先保护现场；提交、推送与切分支按任务授权执行。
- 禁止 `reset --hard`、`clean -fd`、强制推送、移动已发布标签；不覆盖他人未提交修改，不批量删除历史分支或恢复点。

## 本机命令
- 后端仅用 Conda `stisp-geomanager`：`/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python`；不使用 base、其他环境或本机 Pixi 命令。缺依赖先询问，不擅自安装。
- 默认验证：仓库根目录 `make verify-fast`；解释器、pnpm 前缀、测试映射与超时配置在 `scripts/verify_fast.py` 顶部。
- 前端统一 pnpm；进入 `frontend` 后的已验证写法：
```sh
export PATH=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin:$PATH
export COREPACK_ENABLE_NETWORK=0
pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false run typecheck
```
- 路径含中文时，浏览器检查必须从 `frontend` 调用 `node scripts/run-browser-check.mjs`，后接相关测试文件；不自行复制源码树或改 mock 绕过问题。

## 不可突破的边界
- `docs/openapi.yaml` 是唯一契约；`frontend/src/api/generated/` 与 `mock/prism/openapi.prism.json` 只能再生成，不手改；API DTO 不重复手写。
- 权限、项目和 owner_only 隐私在后端逐执行边界校验，前端门禁不能替代 ACL；优先 Django 内置认证、组与权限。
- 业务与科研数据根目录仅来自 TOML，代码、数据、配置分离；密钥、数据库、原始数据、日志、依赖不进 Git。
- 栅格符号化、重采样及 PNG/XYZ 生成只在后端，GDAL 调用走统一封装；不改原始科研资料或冻结算子以掩盖结果差异。
- 沿用既有模块和共享入口，先读相关测试，不做无关重构、不加隐式兼容分支；Ant Design 管非地图 UI，React key 不用数组下标，CSS 不用 `!important`。

## 变更分级
按行为风险分级，不单按文件数；仅改文案或样式不因文件位于读取模块就升级。下列秒数是本机样本，不是上限。

| 级别 | 适用情形 | 必须验证 | 必须更新文档 | 实测耗时参考 |
| --- | --- | --- | --- | --- |
| 小 | 单模块界面、文案、样式、局部缺陷；不改接口或高风险行为 | 只跑 `make verify-fast`；不跑完整构建或完整效率门禁 | 不写文档；改动点已有对应段落时才同步 | 后端 0.59s / 组件 7.46s / 样式 1.73s |
| 中 | 跨文件功能调整、单应用后端逻辑；不改契约及高风险边界 | `make verify-fast` 加触及模块的浏览器测试；可用脚本 `--browser` | 同步已有模块行为说明；新增长期约束记入对应文档 | 快速部分同上；浏览器未取得成功耗时 |
| 大 | 接口契约、跨前后端、模型迁移、权限、缓存或并发行为 | 含中级验证；契约五条命令、`build:verify`；触及下节行为再跑 `make check-efficiency` | 契约、开发指南、API 交接记录、生成物及相关模块说明 | 完整门禁未成功计时；构建 10.63s 处受沙箱阻断 |
| 发布 | 候选验收、切换、回滚 | 统一发布入口；按其检查与回执执行，不把开发备份当发布 | 发布回执；集中升级时更新版本与 Changelog | 发布入口尚未实测 |

契约五条命令依次为 `generate:api`、`check:api`、`api:changes:check`、`api:docs`、`api:lint`，均在 `frontend` 用上述 pnpm 前缀执行。
发布只用 `tools/release/release.py` 的 `inspect`、`fast`、`full`、`status`、`rollback`；入口不可用则停止发布，禁止在 `.runtime` 手写或复制改写发布脚本。

## 效率门禁范围
实际改变资源读取/查询/统计、文件摘要/像元/掩膜校验、输入版本与算子准备、缓存/锁/并发合并、轮询/会话历史/上下文/SSE，以及这些路径的撤权、取消、失败重试或失效行为时，必须跑 `make check-efficiency`。
只有文案、布局、注释等未改变上述行为的小改不触发完整门禁。路径清单、操作次数与科学一致性回归见 `docs/efficiency-contracts.md` 的“门禁触发范围”“共享边界”“必过检查”。

## 按需查细则
- 契约流程与 Mock：`docs/developer-guide.md` 的“API 契约规范”“Prism Mock Server”；前后端所有权、交接顺序：`docs/operations.md` 的“前后端分工与交接”。
- 发布冻结、候选、数据保护、静态资源兼容与账号隔离：`docs/operations.md` 的“统一发布与数据保护”“浏览器发布兼容与账号隔离”。
- Git 备份与版本粒度：`docs/github-code-tracking.md` 的“后续同步”“版本更新粒度”；不自动升级小修版本，不开启旧自动部署。
- 栅格接口、存储和性能目标：`docs/design-docs.md` 的第 6、7、8 节及“10.3 性能”；只读对应段落，不要求每项任务通读。

## 上下文与输出
- 禁止整段读取巨型文件：OpenAPI、开发指南、API 交接记录、实现笔记、生成类型、RightSidePanel、全局 styles。用 `rg -n` 按 operationId、符号、标题或选择器定位，再只读有关片段；索引见代码地图。
- 临时产物放 `.runtime/<任务名>/`，不在其中复制源码树，不删除其他任务产物；浏览器临时镜像仅由既有检查入口管理。
- 新脚本配置集中在导入后的顶部，默认可直接运行；文档与报告用中文，技术标识保留原文。
- 完成报告最多四项：改了什么；用户可见界面变化及本地/服务器是否生效；验证命令与结果；未验证事项和风险。只报告实测，不逐项声明未触及领域；验收造数及保留情况写入相关项。
