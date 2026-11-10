# 标准发布工具

所有命令默认只打印完整离线计划，**不会连接服务器**；包括只读命令在内，只有 `--execute` 才连接。仅使用 SSH 密钥与严格主机指纹校验，不接收口令，不自动安装依赖、不改 Git 状态。

首次将 `tools/release/config.example.toml` 复制为 `config/release.local.toml`，在沙箱外核实并替换所有 `REPLACE_` 路径，预先准备 SSH 公钥、known_hosts 和本机前端依赖。真实配置已被 `.gitignore` 排除。

```bash
PYTHON=/opt/homebrew/Caskroom/miniconda/base/envs/stisp-geomanager/bin/python
$PYTHON tools/release/release.py inspect --execute
$PYTHON tools/release/release.py fast --execute
```

| 命令 | 用途 |
| --- | --- |
| `inspect` | 正式根、SHA、版本、四类进程、队列、磁盘、双锁，以及本机 Git 差异 |
| `fast` | 已跟踪文件干净且精确 HEAD 已推送 → 英文临时目录导出 → 正式构建或摘要核对复用 → 增量上传 → 独立会话切换 → 硬验收 → 回执 |
| `full` | 在切换前增加独立候选副本、历史隔离、迁移、四角色及 HTTP/静态验收；可追加 `--candidate-check /绝对路径/check.py` |
| `status` | 离线显示本机记录位置；`--execute` 只读查询相同服务器最近作业，重启本机工具不影响服务器会话 |
| `rollback` | `--execute` 排空并备份当前状态，核实旧代码/配置/schema/静态摘要后恢复上一根目录、启动器和静态树，不还原数据库 |

常规发布只运行 `fast --execute`。已跟踪文件有已暂存或未暂存修改、origin SHA 不一致会直接停止；未跟踪文件不阻断，在计划、清单和本机回执中列出，不自动带入源码包。含迁移、科学算子改动或非祖先会提示使用 `full`。**原正式脚本不支持 schema 变化；full 能在隔离候选中验证迁移，但正式迁移仍被原门禁拒绝，不能当作数据库升级工具。** 算子代码进入发布包，不自动登记/覆盖已发布算子版本。

`local.pnpm` 是命令参数列表，默认前缀与 `scripts/verify_fast.py`、AGENTS.md 一致：`pnpm --config.verify-deps-before-run=false --config.manage-package-manager-versions=false`；工具不执行依赖安装或修改锁文件。`local.buildResources` 是仓库相对路径列表，默认包含三张团队照片和一张成果展示图。正式构建前复制到 Git 导出目录，缺少任何一张即停止并给出路径；逐文件 SHA-256 写入清单和 `build-resources.json`，构建后删除输入副本，只将正式 dist 与冻结源码一起打包。资源不得覆盖已跟踪源码，亦不得直接写入 dist 或 node_modules。

切换失败自动恢复代码、启动器和静态树；schema 改变、进程身份不明或恢复失败则保留 `DEPLOY.lock`。先运行 `status --execute`，检查回执给出的阶段及远端操作目录 `driver.private.log`；不删除锁、不反复发起切换。显式回退只支持本工具创建且保留完整回退证据的已接受版本；旧现场脚本发布的版本仍可作为首次发布基线，但不能凭空生成回退证据。

本机证据位于 `.runtime/releases/<UTC时间>-<短SHA>-<随机标识>/`，只保存清单、回执及日志；源码与包仅在系统临时目录，退出即删除。服务器保留独立发布目录、备份与私有日志，不自动清理旧版本。实际切换在服务器独立会话运行，本机定期轮询到三种终态之一；临时 SSH 中断只重试只读查询，不重发切换命令。

离线验证：`$PYTHON -m pytest tools/release/tests`。仅验证本机阶段：`fast --local-only --base-commit <已知基线SHA> --baseline-package <该SHA的完整包>`；可用 `--commit <SHA>` 验证历史提交。该模式不连接、不核实 origin、不生成可部署或接受回执，不能绕过真实发布门禁。完整行为差异、原脚本映射及钩子协议见 `tools/release/BEHAVIOR.md`。
