# 发布行为与联调边界

## 职责与证据

`release.py` 负责本机命令、计划、精确 origin 分支核实、证据目录、上传与轮询；`config.py` 严格加载配置；`executor.py` 是全部 SSH、SCP 和远端 origin 查询的可替换执行入口。只读观测代码经 SSH 标准输入在内存执行，不在服务器安装或更新脚本。

`artifacts.py` 负责 Git 导出、差异分类、构建/复用、确定性完整包和增量包、清单冻结；`server.py` 保留历史切换核心；`protocol.py` 负责独立会话、上传校验、进度、候选编排和显式回退；`candidate.py` 与 `candidate_support.py` 负责独立数据副本和复制历史隔离。运行时工具必须与清单中的逐文件摘要一致，不依赖任何历史 `.runtime` 辅助模块。

清单绑定精确提交、前后端一致版本、包大小和 SHA-256、文件内容/权限、首页脚本、服务器基线身份、工具摘要、差异判定及接受证据。基线含启动器/正式 TOML 摘要、四角色完整进程身份、worker 锁、受保护依赖进程身份及静态树身份。本机将精确基线 Git 文件清单与观测 dist 摘要合并，必须还原正式 staged.json 中的 filesDigest，才能复用前端或继续发布；不能只对当前文件重新算摘要就当作上一包已经验证。该基线文件清单仅计算一次，同时供增量打包与回退清单使用。没有 staged.json、完整提交或可信文件清单摘要的旧部署必须人工补齐证据，不能从目录短 SHA 猜测。

只读 inspect 在角色缺失时仍报告 missing/ambiguous 状态，并明确 baselineVerified=false；缺 staged.json 时提交显示未知，不猜测差异。发布采用独立的严格观测，缺角色或身份不完整仍拒绝。队列分组只查询活动状态，不扫描全部已结束历史，并明确显示排队/运行的零计数。

## 已跟踪文件门禁与构建资源

正式发布使用 `git status --porcelain --untracked-files=no` 检查已跟踪文件；任何已暂存或未暂存修改均拒绝。未跟踪文件不阻断，通过 `git ls-files --others --exclude-standard -z` 收集到计划、清单及本机回执的 `untrackedFiles`。发布包源码只来自 `git archive` 导出的精确提交，未跟踪文件不能自动进入发布包，因此本机依赖链接、环境文件和并行任务产物不应造成永久阻断。被 Git 忽略的本机文件不属于该未跟踪列表；它们同样不参与源码导出。

显式配置的 `local.buildResources` 是构建输入白名单，不是附加源码。默认四张图片在两次历史发布的 Git archive 中均不存在，但实际构建目录及 dist 中存在，且内容 SHA-256 与本机资源一致；历史 `package.py` 也只将 Git 源码和正式 dist 合并打包。当前流程在正式构建前将白名单资源复制到导出目录，记录路径、大小与 SHA-256；任一资源缺失、路径越界或覆盖冻结源码均停止。构建后删除输入副本，再生成文件清单、完整包与增量包。dist 内由构建器产出的带摘要静态资源正常保留，原始图片路径不加入源码包。

历史本机导出命令在解包、借用 node_modules 后，枚举成果图和 `frontend/src/assets/team/*.jpeg`，仅将导出目录中缺失的图片用 `shutil.copy2` 补入。服务器旧部署命令则在解包后执行 `cp -a "$OLD/release-assets" "$NEW/"`，作用是跨发布保留旧现场的附属资源目录；它不在两次本机包的图片构建链路中。当前工具不依赖这个未冻结的远端目录来补源码或构建，也不改变服务器保护条件；该目录的现有内容未做远端核验。

`local.pnpm` 接受命令参数列表，默认与快速验证一致：`pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false`。嵌套构建命令继承相同的配置环境及 `COREPACK_ENABLE_NETWORK=0`；工具只借用已有 node_modules，不执行 install、不更新依赖或锁文件。前端复用仍只核对上一发布包的 dist 摘要，不读取本机资源，也不声称重建了旧 dist。

`fast --local-only` 仅验证精确提交的导出、构建/复用、清单与打包，不连接服务器，不核实 origin，也不绕过正式发布的已跟踪文件门禁；本机回执明确为 `localOnly=true`、`deployable=false`，没有正式接受声明。

## 与最新历史 server.py 的差异

比较基准：`.runtime/workflow-progress-repair-20261110/server.py`。以下是全部改变执行行为的函数；仅格式变化不改变行为。

| 函数或入口 | 差异与理由 |
| --- | --- |
| 模块配置、`load_config` | 移除现场默认目录、提交与启动器摘要。必须提供生成的 runtime JSON，不再在配置缺失时静默使用历史默认值；正式 TOML 数据目录身份、双锁不同及本机 6007 约束保留。补充精确运行参数校验，排空/停止/健康/备份/管理命令超时与轮询间隔，以及 HTTP、SQLite、心跳、启动验证、停止轮询和监听参数均须保持历史精确值，不能借配置放宽旧门禁。 |
| `readonly_db` | SQLite 连接超时从字面值 10 改为校验后仍精确等于 10 的配置值；保留只读 URI、可见 WAL 和 query_only。 |
| `safe_member` | 保留原全部禁止条件；额外拒绝空路径、点路径、反斜杠、Windows 盘符、控制字符及真实 release.local.toml，避免跨平台路径混淆和本机配置泄漏。 |
| `load_release` | `full` 保留原候选接受证据的 SHA/版本/包及全部 checks=true 约束。`fast` 按任务定义不建候选，因此改为校验同样绑定精确包的 preflightAcceptance，另要求科学算子未变及本机已核实祖先关系；不伪造 candidateAcceptance。原 noSchemaChanges、工具摘要、包摘要/大小/文件清单、独立目录约束全部保留。 |
| `environment` | PROJ_DATA/GDAL_DATA 从现场常量改为配置，正式环境变量、Django 与 PYTHONPATH 行为不变。 |
| `stop` | 0.2 秒轮询改为校验后仍精确等于 0.2 的配置值；SIGTERM、40 秒默认超时、PID/启动刻度/argv/cwd 核验、禁止 SIGKILL 均保留。 |
| `start` | 0.1 秒首次身份验证等待改为校验后仍精确等于 0.1 的配置值；启动顺序、继承原运行环境、独立会话、启动身份验证和未知子进程处理均保留。 |
| `http` | 10 秒超时参数化且保持精确值，仍禁代理、禁重定向并要求 200。增加静态 JavaScript 的 Content-Type 硬断言，只接受 application/javascript 或 text/javascript，防止以 HTML 错误页冒充脚本。 |
| `gate` | 心跳最大年龄从 40 字面值改为校验后仍精确等于 40 的配置值；启动后心跳、worker 锁、依赖进程、健康、首页 JS 列表和内容摘要检查不变。 |
| `cutover` | 静止备份之后、正式 migrate 之前写 rollback-context.json，记录 schema_version、备份目录、上一根目录与旧启动器摘要；不保存进程环境或凭据，不引入数据库还原。其余控制流、异常分类、自动回滚及人工保锁逻辑不变。 |
| 历史 `main` | 命令入口移到固定 protocol.py 与 release.py；切换在一次双锁范围中依次校验、候选（full）、stage、cutover，避免现场脚本跨命令间的协调。服务器写入口仍要求 --execute；冻结提交与清单摘要由本机实时派生并通过启动参数钉住，而非人手填入常量。 |

未改变的核心包括：四角色精确识别、重复角色拒绝、两次排空及最终活动检查、不强制取消、SQLite 在线备份完整性检查、磁盘安全余量、独占 DEPLOY.lock 与非阻塞 flock、旧锁不自动删除、迁移源码比对及已应用迁移检查、schema_version 不变、旧/新公共构建依赖归档、单文件系统静态替换、原子替换两个启动根、进程与依赖身份、回滚不还原数据库以及失败保锁。权限、应用接口、数据路径约定和后端栅格渲染没有修改。

原脚本同时要求“真实候选已接受”和“无迁移”，与 fast 不建候选及 full 用于迁移的目标存在边界冲突：fast 的接受来源已按命令定义明确调整，不能再声称全部候选门禁原样用于 fast；正式 schema 门禁没有调整。数据库迁移的生产发布需要另行批准的 schema 发布与失败恢复方案，不能通过改 noSchemaChanges=true 或放宽断言实现。

## 其他历史脚本的整理差异

- `package.py` 不再读取固定任务目录、固定基线包、固定版本或写死 scientificOperatorsUnchanged。从 Git 及正式 staged.json 推导身份；前后端版本不一致即拒绝；Git 不受工具修改。
- 历史三套 package.py 的 scientificOperatorsUnchanged 是人工布尔常量，没有可复用判定函数。新规则保守地把 `examples/compute/`、算子/算法目录、`backend/scripts/`、`scripts/`、compute/raster 实现和 operator 相关实现列为科学改动；迁移检测含新增、修改、删除及重命名两端。测试覆盖实际目录、删除和重命名。这可能要求比历史更多的小改动使用 full，不会把未知科学改动假定为未变。
- 前端变化包含 frontend 全目录及共享包/工作区输入；有变化必须执行原 `pnpm run build:verify`，不直接调用 Vite 绕过检查。不变时只读下载上一正式目录已验证的完整 dist，并与观测时逐文件 SHA-256、大小和权限比对；不是复用当前工作区 dist，也不依赖历史本机发布包仍在磁盘。
- 前端依赖只借用本机已安装 node_modules，英文临时目录中的该开发链接在打包前删除；冻结源码摘要须保持不变。pnpm 的隐式安装被设为 error，更新通知及 Corepack 网络被关闭；不会为解决构建失败自动联网安装或重写共享依赖。pnpm 依赖检查不通过时仍拒绝构建。
- `delta.py` 的确定性 gzip/tar、目标清单和逐文件摘要验证保留，扩展了重复 ZIP 成员、展开总量、符号链接、父目录链接和清单外成员拒绝。新包只记录排序后的普通文件，不重复记录目录成员；tar 元信息和 gzip 时间固定，因此包 SHA 与旧打包格式不同，但完整包与同一清单重建的增量包逐字节一致。文件删除通过目标清单自然处理，不修改上一发布目录。
- `freeze.py` 的清单绑定和静态入口验证合并入 artifacts.py，原“精确候选接受”只用于 full；候选证据在服务器验收后进入 accepted-manifest.json，正式切换使用该最终清单。fast 使用明确标记的前置检查接受证据；local-only 输出 deployable=false，永不生成正式接受证据。
- `setup_candidate.py` 不再依赖某次 delta helper、固定端口外的任务常量或业务迁移名。先校验精确包，再给候选副本运行完整 migrate；正式库永不被候选命令迁移。数据库备份带时限和完整性检查；native 策略、独立 app/research 根、禁止启动扫描、独立 secret key 副本和不复制科研原文件均保留。
- `candidate_support.py` 仅保留 bootstrap、数据库身份核验、复制历史隔离和相关原子写入；隔离事务内容保留。删除任务绑定的账号、表格、审核文案、科研数据夹具、浏览器认证、模型场景及具体业务验收。通用候选增加四角色启动、硬健康验收与按身份正常停止；无法确认/停止子进程时保留发布锁并要求人工核查。
- `release_driver.py` 不再写死 COMMIT/MANIFEST_SHA。操作目录启动标记用独占创建防重复发令，子进程 start_new_session 且 stdin=DEVNULL。本机 SSH 断开不影响切换，只读 status 比较 PID 完整身份，避免 PID 复用误判；不再把可能含敏感内容的私有日志尾部直接回传。
- 新增显式 rollback，复用原核心的排空、备份、停止、启动、迁移/健康检查和 launcher 原子替换；先验证已接受版本、旧代码完整清单、原备份摘要、未变正式配置、schema 和旧静态树 inode/内容。永不还原数据库，失败保锁；不尝试从证据不完整的旧现场任务猜测回退方法。
- 本机仅保留清单、回执及日志，源码、完整包、增量包及临时配置在系统临时目录中，正常退出或抛出异常时都清理。不删除历史 .runtime，不自动清理服务器备份或旧发布目录。强制杀死本机进程后，系统临时目录可能残留，需人工按时间核实清理。

## 步骤与原脚本映射

| 顺序 | fast | 原来源 |
| --- | --- | --- |
| 1 | 本机工作区/分支/远端个人分支 HEAD、只读正式身份、Git 差异与三项拒绝条件 | 原现场人工前置检查、server.inspect、package.py 祖先断言 |
| 2 | 英文临时路径导出指定提交 | package.py 的 git archive |
| 3 | 变化时 build:verify；不变时精确摘要复用 dist | 原现场 build 步骤及 package.py 的 DIST |
| 4 | 完整/增量包、清单、静态入口、工具与基线指纹冻结 | package.py、delta.py、freeze.py |
| 5 | 上传固定工具及较小的包、服务器 SHA/清单校验并重建 | 原远程上传、setup_candidate.py 的 delta.apply |
| 6 | 独立会话，双锁内核对身份并 stage 全新目录 | release_driver.py、server.load_release/publication_locks/stage |
| 7 | 迁移门禁、排空、在线备份、公共依赖归档、准备静态树 | server.cutover 前半段 |
| 8 | 停 web、再次排空、停 worker、静止备份、migrate 与不变 schema 门禁、切换、启动 | server.cutover 主 try |
| 9 | 进程/心跳/依赖/HTTP/静态 JS 摘要与新增 MIME 检查；失败自动回滚或保锁 | server.wait_gate/gate/http、cutover 的 except |
| 10 | 固定间隔 status 到终态、取回最终清单和回执、清理本机临时文件 | release_driver.py 的状态读取；新增固定本机编排 |

full 的 1～5 与 fast 相同，但不执行 fast 的三项拒绝条件；第 6 步在 stage 之前增加：正式库在线备份到候选 → 独立 TOML/secret key/空科研根 → 校验解包 → 仅候选 migrate → 原隔离事务 → Django/schema/静态归档 → 四角色验收 → 可选钩子 → 按身份停止 → 精确包候选接受证据 → 原 stage/cutover。生产 schema 门禁仍适用。

完整包/增量包的服务器内容校验各在明确边界发生：启动入口只检查小型清单和工具，不解包或重复扫描归档；独立作业接收时校验一次，正式 load_release 在进入 stage 前重新校验一次。离线回归断言 fast 作业恰有两次 archive_files，避免新增启动层重复扫描；full 的候选另有独立验证，正式/候选边界不复用授权或运行状态。

## 候选钩子协议

`full --candidate-check /本机/check.py --execute` 将该 Python 文件固定为 candidate-check.py 并钉住 SHA-256。钩子在服务器候选四角色已启动、隔离和通用门禁通过后，用服务器项目解释器运行：`python candidate-check.py --context <candidate-context.json>`，cwd 是候选代码根，继承候选 Django 环境。

context 包含 commit、version、root、code、config、baseUrl。脚本不得修改正式配置、数据或进程；自行确保所有连接/写入只面向 context 指定的候选。退出码必须为 0，标准输出最后一行必须是 `{"accepted":true,"checks":{"业务验收":true}}`，checks 非空且全部为 true。其余输出进入远端私有日志，不传回账号/认证资料。默认超时 600 秒。外部 Node/浏览器探针可由该脚本启动，依赖需预先准备，工具不会自动安装或创建任务专用数据。

## 沙箱外确认

### 只读可验证

- 核实 SSH 密钥授权和 known_hosts；核实样例所有占位路径、解释器、Waitress、PROJ/GDAL、日志与两把锁；确认 6007 和 19000/19010/19020 的真实身份。
- `inspect --execute` 核实启动器两个根、staged.json 的完整提交、前后端版本、四角色 argv/cwd/startTicks、worker flock、队列分类、空间和锁；确认本机持有正式提交对象及 origin 个人分支精确 SHA。
- 核实借用依赖与冻结提交的 pnpm 配置一致，英文临时路径的 build:verify 完整通过，不能安装或改锁文件后仍声称是原依赖验证。
- 核实旧静态树结构、首页真实 JS Content-Type、现用启动器为可识别的两个唯一赋值；确认旧发布根的源码确实可由本机精确 Git 对象和 dist 还原。

### 只有真实发布才能验证

- AutoDL 接收完整/增量包并重建为相同 SHA，跨 SSH 断开仍运行且 status 可恢复；服务器目录权限、上传原子完成与磁盘余量。
- 候选环境完整副本、历史隔离、四角色 native 运行及用户提供业务/浏览器钩子；不得把本机桩演练当真实模型或业务验收。
- 活动任务排空及并发边界、双发布锁竞争、SQLite 在线/静止备份、真实迁移门禁、公共静态依赖归档、原子切换及原配置不变。
- 正式四角色启动、心跳、模型/向量/知识服务不受扰动、健康/首页 JS 摘要及 MIME、用户旧浏览器构建可访问。
- 受控故障触发原自动回滚、schema/未知进程保锁及人工回执；新工具发布成功后的显式 rollback；数据库始终不回放备份。

含真实 schema 变化的正式升级、已登记科学算子版本的安装/迁移以及第一次从缺失 staged/回退证据的旧部署接入，均不在当前自动切换能力内。需另行审查批准，不能靠候选钩子放宽生产门禁。
