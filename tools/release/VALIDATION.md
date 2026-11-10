# 离线验证记录

日期：2026-11-10。环境：macOS、Python 3.14.6、Conda stisp-geomanager。源码工作区分支为 codex/xintao，验证时 HEAD 为 `9cc5dbf`。验证期间没有执行 SSH、SCP 或 rsync，没有连接 AutoDL，没有提交、推送、切换分支或改变暂存状态。

## 自动测试与静态检查

| 命令 | 结果 |
| --- | --- |
| `/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python -m pytest scripts/tests/test_verify_fast.py tools/release/tests -q -p no:cacheprovider` | 137 passed；1.19 秒 |
| `ruff check tools/release` | 通过 |
| `ruff format --check tools/release scripts/verify_fast.py scripts/tests/test_verify_fast.py backend/apps/compute/{services,runtime,worker,script_capabilities}.py backend/tests/integration/test_compute.py` | 21 个 Python 文件格式检查通过 |
| `make verify-fast` | 3 步通过，55.77 秒；后端 224 passed、5 skipped；脚本 50 passed |
| `make check-efficiency`（显式项目解释器与核实的 pnpm 前缀） | 后端 106 passed、3399 deselected，27.73 秒；前端因共享 node_modules/.vite-temp 写入被沙箱拒绝，整体门禁未通过 |

当前发布工具和快速验证已统一使用经过本仓库核实的 `pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false` 前缀；没有执行依赖安装或修改锁文件。效率门禁和通过既有 runner 单独发起的效率/计算中心浏览器检查，均停在共享 node_modules/.vite-temp 的 `EPERM`，没有执行前端或浏览器测试断言。日志位于 `.runtime/task-c-review-20261110/efficiency.log` 和 `browser.log`。使用 `pnpm_config_verify_deps_before_run=error` 的初始历史检查停在 patchedDependencies 校验，旧日志为 `/private/tmp/stisp-release-efficiency.log`，不代表当前阻断原因。

发布工具测试覆盖确定性完整包/增量包逐字节一致、删除文件、变更基线拒绝、正式前端必须还原上一发布清单摘要、归档绝对/上跳/盘符路径、链接/特殊成员、重复成员/特权权限/大小限制、精确清单及接受证据、fast 三项拒绝、真实算子目录/删除及重命名迁移、配置缺项/类型/危险选项、默认零连接调用、已跟踪修改与未推送拒绝、未跟踪文件不阻断且写入计划/回执、四个本机资源分别缺失时停止、资源摘要与源码/增量包排除、构建不改冻结源码及不自动安装、独立会话防重复启动、断线只重试读取、只读角色缺失、双锁/旧锁保留、解包/备份/启动器替换、自动回滚、显式回退及旧静态损坏拒绝、schema 变化与未知进程保锁。

端到端演练只在 pytest 临时目录建立小型 SQLite、静态目录和启动器；进程启停与健康检查使用桩。没有创建真实平台项目、用户会话、业务任务或科研资料。

## 默认计划命令

将样例主机改为 `does-not-exist.invalid`，用 `/private/tmp/stisp-release-offline-example.toml` 分别调用 inspect、fast、full、status、rollback，不加 --execute，五条均退出 0，打印完整计划。单元测试用可替换执行器记录器断言 SSH、SCP、origin 网络查询调用数全部为 0；执行器自身另有默认离线防线测试。CLI 计划日志位于 `/private/tmp/stisp-release-<命令>-plan.log`。

## 本机发布阶段

### 已完成的精确历史提交复用演练

目标和基线均为 `7426f958b99be0a2c67dfa42553b7a2d730b1064`，只读使用 `.runtime/workflow-progress-repair-20261110/frozen/release-code.tar.gz`，先逐文件验证基线源码与 Git 对象相同，再复用 dist。该路径验证打包工具，不代表当前 HEAD 已构建或已通过发布前置检查。

| 阶段 | 耗时 |
| --- | --- |
| Git 导出 | 0.248 秒 |
| 前端摘要核对与复用 | 0.408 秒 |
| 文件清单与版本/入口核验 | 0.155 秒 |
| 完整包、增量包及完整包复核 | 1.364 秒 |
| 计时阶段合计 | 2.175 秒 |

完整包 54,906,148 字节，SHA-256 为 `eef1ee2841ce6e4c17462e29cbf3e7545147ec50ddeb43b5a9e9a29eeeb553de`。本机记录：`.runtime/releases/20261110T111716Z-7426f95-d37653/`。仅保留 `manifest.json` 和 `timings.json`，localOnly=true、deployable=false；系统临时目录中的源码、完整包和增量包已随上下文退出删除，原基线包不变。

### 当前 HEAD 构建尝试

目标为 `9cc5dbf`，基线为 `7426f958b99be0a2c67dfa42553b7a2d730b1064`，只读使用 `.runtime/workflow-progress-repair-20261110/release-code.tar.gz`。本机四张图片在 Git archive 导出后复制到临时构建目录，路径、大小和 SHA-256 保存在 `.runtime/releases/20261110T113125Z-9cc5dbf-3071a0/build-resources.json`。

| 阶段 | 实测结果 | 耗时 |
| --- | --- | --- |
| Git 导出 | 通过 | 0.286 秒 |
| 资源复制及前端 build:verify | 品牌、i18n、API 一致性与类型检查通过；前端效率测试启动时沙箱拒绝写入共享 node_modules/.vite-temp | 9.755 秒，失败 |
| 清单 | 未执行 | 无实测值 |
| 打包 | 未执行 | 无实测值 |

构建错误为 `EPERM: operation not permitted, open .../frontend/node_modules/.vite-temp/vitest.config.ts.timestamp-....mjs`，发生在 `check:efficiency`，尚未到达 Vite 正式构建。没有改动构建脚本、复制依赖或更改 mock 来绕过沙箱，也没有把单元测试中的模拟构建当作 HEAD 的正式构建。完整日志及阶段计时位于 `.runtime/releases/20261110T113125Z-9cc5dbf-3071a0/`；该次失败没有生成成功清单、发布包或可部署回执。

沙箱外执行以下完整命令可复核当前 HEAD 的全部本机阶段，不连接服务器：

```sh
cd /Users/xintao/Project/时空智能遥感平台/GeoManager-logic-fixes-20261106
export PATH=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin:$PATH
export COREPACK_ENABLE_NETWORK=0
/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python tools/release/release.py fast --local-only --config tools/release/config.example.toml --commit HEAD --base-commit 7426f958b99be0a2c67dfa42553b7a2d730b1064 --baseline-package .runtime/workflow-progress-repair-20261110/release-code.tar.gz
```

### 历史图片处理

两次历史发布目录为 `.runtime/workflow-progress-repair-20261110/` 和 `.runtime/workflow-node-progress/release/`。历史导出命令在解包后，用 `shutil.copy2` 将本机成果展示图及团队目录中缺失的 JPEG 补进构建目录；历史 `package.py` 只打包 Git 源码和构建后的 dist。四张图片的原始路径均不在 `source.tar` 或最终源码包中，两个构建目录及最终 dist 里的对应图片却与本机 SHA-256 一致。逐项证据为 `.runtime/task-c-review-20261110/asset-evidence.json`。

本地历史记录里的服务器旧脚本在解包后执行 `cp -a "$OLD/release-assets" "$NEW/"`，沿用旧发布的附属资源目录；它不是上述两次本机补图构建的来源。当前工具不从该远端目录补源码，不改服务器保护条件；未连接服务器核验其当前内容。命令摘录与来源见 `.runtime/task-c-review-20261110/asset-history.md`。

## 尚未验收

AutoDL 只读身份、SSH 密钥/known_hosts、所有占位路径、真实上传与候选、断线持续运行、正式排空/切换/健康验收、真实故障回滚和显式回退均未联调。含生产 schema 变化的正式发布没有实现，因为原 noSchemaChanges、迁移源码一致和 schema_version 不变门禁必须保留；只支持在候选副本验证迁移。已登记科学算子版本不会自动安装或覆盖。

没有新增或修改用户界面、应用 API、权限规则、业务/科研数据路径机制或栅格渲染；本机与服务器均未部署生效。工作区并行修改予以保留，详细联调清单见 BEHAVIOR.md。
