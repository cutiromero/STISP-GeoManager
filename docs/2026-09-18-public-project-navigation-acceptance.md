# 后台项目管理、单项目操作与公共团队动态验收

## 已生效的行为

1. 项目管理位于“后台管理 → 项目管理”，后台侧栏和“后台管理”下拉菜单均可进入；仅超管可维护标签和分配成员。旧 `/projects/manage` 地址跳转至 `/admin/projects`。顶栏独立项目管理按钮已移除。
2. 顶部项目切换和存量数据项目筛选只提供具体项目，不再提供“全部可访问”。业务接口读写传 `all` 均返回 JSON 400。旧会话存储的 `all`、无效项目或已撤权项目恢复至公开项目。
3. 内置项目名称改为“公开”。保留 ID=1、code=default、isDefault、原数据关联和文件目录。所有用户自动可访问公开项目，超管可分别进入所有项目。
4. 科普和团队动态为平台公共内容，列表、详情、封面、图片和附件不受所选业务项目影响。已发布内容支持未登录阅读；草稿、下架内容及编辑继续受内容管理权限控制。
5. 上传仍显式指定一个目标项目，可选范围由后台授权决定。项目管理接口能够管理多个项目及成员关系，不代表业务数据可跨项目汇总。

## 真实浏览器验收

| 身份 | 项目选项 | 结果 |
| --- | --- | --- |
| 超级管理员 | 公开、管道院、核地院 | 后台菜单及项目维护表单可用；旧入口跳转正确 |
| 刘洋（科研用户） | 公开、管道院 | 私有项目下新闻及图片可读；直接访问项目管理跳至用户设置 |
| 未登录访问者 | 公开 | 已发布团队新闻及图片可读 |

两种登录身份均验证旧 `all` 会话恢复为公开；库存筛选不存在汇总选项。内容接口在公开、私有、未获授权、不存在项目和旧 `all` 参数下返回同一组已发布新闻。三个身份的业务 `all` 请求均返回 400。页面无 JavaScript 异常。

验证使用独立会话，结束后已删除两条验证会话；没有修改密码或现有登录会话，没有新增测试业务数据。服务已重启，入口为 http://127.0.0.1:5173/。

证据：`output/20260918-public-project/live-browser-report.json`、同目录 `admin-project-management.png`、三种身份的 `*-news.png` 和两种身份的 `*-inventory.png`。可复验脚本为 `frontend/scripts/verify-public-projects.mjs`。

## 数据迁移与保留

- 已应用 `projects.0002_public_project_name` 和 `content.0004_platform_public_content`。
- 应用前重新进行 SQLite 在线备份：`output/20260918-public-project/pre-migration.db`；早期备份及配置副本为 `before.db`、`before.toml`。
- 应用前后逐项比较确认保留 2 个数据资源、2 个地图工程、2 个制图对象及 1 条私有项目成员关系；导入成果为 0 条。
- 13 篇内容的 ID、类型、标题、正文、发布状态、封面关联不变；22 个附件的 ID、文章关联、路径、checksum 不变，22 个实际文件的 SHA-256 前后完全一致。
- 内容统一归属公开项目。独立迁移测试验证历史不同项目重复 seed_key 的新闻均保留，发生冲突时只调整内部种子标记。数据库约束禁止新建私有内容。
- 数据与研究根目录仍来自 TOML，业务文件和附件不移动；栅格符号化、制图及输出规范不变。
- 迁移的反向操作不恢复文章原私有归属；若未来需要恢复原归属，必须依据迁移前备份逐项处理，不能仅回滚数据库结构，也不能直接覆盖升级后的新增数据。

## 自动验证

| 命令 / 范围 | 结果 |
| --- | --- |
| Pixi Python `pytest -q --tb=short`（完整后端） | 654 passed，52 subtests passed |
| 项目导航、内容迁移、项目授权、上传标签专项 | 69 passed，已包含在完整后端结果中 |
| `pnpm test` | 399 passed |
| Vitest browser：ProjectContext、UploadProjectField、EditorialPage、AdminRoutes、App、WorkspaceHeader | 83 passed；导航菜单补齐后 WorkspaceHeader 14 项再次通过 |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `pnpm run build:verify` | 品牌、语言键、生成类型比对、TypeScript、生产构建通过 |
| `generate:api`、`check:api`、`api:lint`、`api:changes:check`、`api:docs`、`mock:build` | 通过 |
| 本轮文件 Ruff、Oxlint、Oxfmt | 通过 |

保留原有 6 条 OpenAPI 未使用组件警告及 1 条测试环境 GDAL data 探测警告，未导致失败。后端完整日志与最终构建日志保存在同一证据目录。

## 契约与交接

本任务顺序完成契约、后端、前端、测试与文档角色交接。`docs/openapi.yaml`、`docs/developer-guide.md`、`docs/api-change-requests.md`、Mock 和 `frontend/src/api/generated/` 已同步；实际生成目录为 `frontend/src/api/generated/`，不再使用旧文档中的 `schema.d.ts` 路径。

权限变化是业务单项目校验、平台新闻公开及超管后台入口守卫；历史调用方需要用具体项目 ID 替代 `all`。本轮决策取代早期文档中的“默认”展示名、只读汇总和新闻按项目隔离规则。
