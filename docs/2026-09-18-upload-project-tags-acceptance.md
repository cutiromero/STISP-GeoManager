# 上传项目标签联动验收

## 使用方式

1. 进入“数据资源 → 数据与成果导入”。页面顶部增加必填“所属项目标签”，初始选中“默认”。
2. 先选择归属，再选择文件。超管能选择全部标签；其他用户只能选择默认及超管赋予本人的项目标签。
3. 文件预检后锁定归属，防止已确认的重名检查、坐标校验和后台任务跨项目；如需修改，点击“重新选择文件”。
4. 表格、矢量、栅格、成果均使用这个独立选择。顶部浏览项目与上传目标可以不同。成功后查看数据/成果的按钮会引导切换到对应项目。
5. “存量数据”增加“按所属项目筛选”、独立“所属项目标签”列和详情说明。项目分配控制数据访问；资料夹仅用于整理。

一份数据仍对应一个所属项目。默认标签所有人可访问；选择私有项目后仅对应成员和超管可访问，不会再自动添加默认标签而公开私有数据。存量数据的已有归属保留，本轮没有实现已有数据跨项目迁移。

## 实际浏览器结果

- 刘洋的可选标签为“默认、管道院”。
- 超管的可选标签为“默认、管道院、核地院”。
- 在顶部浏览“默认”时，表单选择“管道院”，通过真实浏览器完成 CSV 预检、校验、提交。三个请求均使用项目 2。
- 临时资源在默认项目列表不可见，在管道院库存显示且返回 projectTagId=2。
- 页面无脚本异常。测试资源通过正规删除接口清理；两条独立验证会话已删除，未改用户密码或原有会话。
- 本地后端已重启，地址 http://127.0.0.1:5173/。

证据在 `output/20260918-upload-projects/live-browser-report.json`，截图包括 `researcher-upload-options.png`、`admin-upload-options.png`、`admin-upload-completed.png`、`inventory-selected-project.png`。数据库和配置备份为同目录 `before.db` / `before.toml`；验收后无临时测试资源残留。

## 自动验证

| 检查 | 结果 |
| --- | --- |
| Pixi Python pytest：test_upload_project_tags、test_review_project_labels、test_project_content_upgrade、catalog/test_api、catalog/test_result_artifacts、raster/test_api、unit/raster/test_jobs | 194 passed + 13 subtests；新增 29 项上传归属回归 |
| `pnpm test` | 399 passed；移除了随旧分类建议函数退役的 2 条测试，栅格新分类由上传浏览器测试覆盖 |
| Vitest browser：client、UploadProjectField、AdminRoutes | 66 passed |
| `pnpm run build:verify` | 品牌、语言键、API 生成比较、TypeScript、生产构建通过 |
| `generate:api`、`api:changes:check`、`api:docs`、`api:lint`、`mock:build` | 通过 |
| Ruff、Oxlint、Oxfmt、定向 `git diff --check` | 本轮文件通过 |

权限测试覆盖：必填标签、空值/all/伪造标签拒绝、上传前撤权、同名数据分项目、地理与非地理落库、关联矢量对象、栅格上传路径与异步任务归属、成果文件授权。前端同时覆盖 fetch/SDK 和带进度的 XMLHttpRequest，验证顶部默认/其他项目/all 均不会覆盖上传选择。

## 契约与边界

- 四个上传提交接口的 X-Project-Id 现在必填。`docs/openapi.yaml`、`docs/developer-guide.md`、`docs/api-change-requests.md`、Mock 和 `frontend/src/api/generated/` 已同步。调用旧接口的脚本需要显式传入目标标签（默认为 1）。
- 权限变化只收紧上传归属的显式声明，继续使用现有成员授权。文件仍按配置的研究根和项目子目录存放，存储根和数据库结构不变，既有文件不迁移。栅格符号化和输出规范不变。
- 同时修复栅格预检仍建议已停用胡杨业务分类的问题，统一提交 geographic 分类代码 spatial，避免任务入库时分类校验失败。
- 保留既有 OpenAPI 六条未使用组件提示和测试环境一条 GDAL data 探测提示，均未造成验证失败。
