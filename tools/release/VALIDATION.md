# 发布工具验证

## 离线测试入口

后端统一使用 `/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python`，测试配置为不入库的 `config/app.test.toml`。发布工具测试只使用临时目录、隔离 SQLite 和进程/网络桩，不连接服务器，不执行真实发布。

```sh
PYTHON=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python
$PYTHON -m pytest tools/release/tests scripts/tests -q -p no:cacheprovider
$PYTHON -m ruff check tools/release
$PYTHON -m ruff format --check tools/release
$PYTHON tools/release/release.py full
make verify-fast
```

`full` 不带 `--execute` 时只打印计划，不能产生候选或正式接受回执。五个命令的默认模式均通过记录器断言 SSH、SCP 和 origin 网络查询调用为零。

## 本机检查结果

| 检查 | 结果 |
| --- | --- |
| `tools/release/tests/` | 170 passed，包含真实迁移、SQLite 旧列集 INSERT、旧模型回滚事务及基线 check 入口 |
| `scripts/tests/` | 71 passed |
| `make verify-fast` 的 compute 后端相关测试 | 163 passed、5 skipped、1 deselected；完整入口因两个卡片图片检查缺少 `typescript` 失败 |
| `ruff check` / `ruff format --check` | 发布工具及两个 compute 文件格式通过，发布工具 lint 通过 |
| `release.py full` 默认离线计划 | 退出 0；缺省本机发布配置时明确打印样例计划，不连接服务器 |
| 真实迁移完整分类 | 基线 `04c3f25` 与当前源码比较，新增 compute.0007、projects.0003 均允许；分类记录保留在 `.runtime/task-k-schema-migrations/real-migration-classification.json` |
| 契约五项 | `api:changes:check` 通过；其余四项缺少前端依赖中的 `redocly`，未通过 |
| `build:verify` / 模块浏览器检查 | 缺少 `frontend/node_modules`，未通过；不安装或替换依赖 |
| `make check-efficiency` | 后端 145 passed、3494 deselected、6 errors；六个预算审计用例缺少 `/Users/xintao/逻辑推理测试数据_按草案/上传用`，前端阶段未执行 |

日志和离线分类证据位于 `.runtime/task-k-schema-migrations/`。验收造数仅在 pytest 临时 SQLite 和临时静态目录中，未创建真实平台用户、项目或业务任务，不修改正式数据库。本机验证不产生正式接受声明。

## 必过回归

| 范围 | 断言 |
| --- | --- |
| AST 分类 | 新模型、可空/数据库默认值新增列、新表索引/唯一及 CHECK 约束、可追踪新表 RunPython、字面量新表 SQL、空操作允许；删除/重命名/Alter、非空无数据库默认值、已有表唯一约束、历史迁移变化、未知操作和动态表达式拒绝 |
| 数据迁移边界 | 可读旧表但不能写旧表；禁止 raw SQL 入口、外部函数、SQL 子查询/多语句和顶层执行；函数默认参数与装饰器不能夹带执行；新模型不能冒用已知基线表名 |
| 真实迁移 | `projects.0003_project_features` 允许；`compute.0007_operator_protocol` 在三个 JSONField 带 `db_default={}` 后允许 |
| SQLite 旧 INSERT | 独立库先迁移到 compute.0006，保留历史模型，再执行 compute.0007；历史模型实际 INSERT SQL 不含三个新列且成功，读出均为空对象；列保持 NOT NULL 并有数据库默认值；旧模型兼容冒烟事务回滚不留行；无数据库默认值的非空新列使兼容冒烟失败；`makemigrations --check --dry-run` 无差异 |
| 同包绑定 | 分类、候选结构、兼容结果、接受回执的包摘要、基线提交和分类摘要必须匹配；缺证据、假无迁移、兼容失败、指纹摘要篡改和记录集合不符拒绝 |
| 正式门禁 | 基线源码不变、新增集合一致、正式迁移记录等于基线；正式迁移后结构/索引和记录等于候选；结构或记录偏差、迁移中途失败保锁，不自动启动旧代码 |
| 回退 | 健康失败恢复旧代码/启动器/静态树，保留已迁移库，回执包含结构前进说明及静止备份路径；较新结构可显式回退，未知结构在停止前拒绝并保锁 |
| 原发布边界 | 完整/增量确定性、冻结摘要、包路径与特殊文件安全、fast 拒绝、干净工作区/origin、资源缺失、进程身份、双锁、断线只读轮询、备份和旧静态身份门禁继续覆盖 |

结构指纹不包含业务数据，数据 INSERT 不改变指纹；列默认值、非空、外键、唯一/普通索引、CHECK 等约束属于结构。迁移记录按 app/name 单独核对，不能用相同结构指纹掩盖记录变化。

## 联调边界

本机测试不代表本机或服务器已部署生效。以下项目必须在授权的真实发布中验证：

- SSH 密钥/known_hosts、实际端口和四角色身份、目录权限与空间、真实上传及增量包重建、断线后的独立会话和 status。
- 正式库候选副本、真实基线代码的 check/读写兼容、历史隔离、四角色 native 运行、HTTP/静态及用户业务/浏览器钩子。
- 真实任务排空、并发与锁竞争、SQLite WAL 在线及静止备份、正式新增迁移后的结构与记录一致。
- 生产健康失败后的只回代码恢复，以及成功发布后的显式 rollback；确认数据库结构保持前进，旧代码继续读写。
- 指纹/记录偏差和未知进程的受控故障保锁、人工回执；不通过还原数据库或删除发布锁来掩盖失败。

破坏性或无法证明安全的迁移不属于自动发布能力，必须人工制定方案。科学算子版本的登记/覆盖及缺失 staged/回退证据的历史现场接入也不由迁移兼容证据豁免。
