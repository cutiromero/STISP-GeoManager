# 发布工具依赖与历史安全证据

整理日期：2026-11-02。本清单不含密码；与[开发移交手册](development-handover-20261102.md)一起使用。路径相对GeoManager-main仓库。

## 附录A：安全通报的历史实查结论

此处只复核2026-11-02已有文件与当时答复，没有再次探测服务器或在线重新核验公告，也没有执行缓解、升级或重启。

| 项目 | 已保存事实 | 结论与范围 |
| --- | --- | --- |
| CVE-2026-98432 | `uname`记录`7.0.0-30-generic`，签名`Ubuntu 7.0.0-30.30-generic 7.0.12`；`net.mptcp.enabled=1`、`tcp_migrate_req=0`；可见livepatch目录无补丁；当时WeKnora在回环19020有MPTCP监听 | 历史结论是“命中内核版本风险，应按受影响处理”，并引用Ubuntu官方CVE条目。保存的JSON证明系统信息，未保存官方条目原文快照；本次没有重核发行版补丁匹配，不将通报文字直接当作已成功利用或主机已失陷的证据。内核属于容器宿主，应由云平台/宿主运维确认修补状态。 |
| Claude插件2.1.313 | root、ubuntu用户常见VS Code/code-server扩展路径与额外目录均未找到Claude扩展；IOC进程、连接、23份持久化配置均无匹配；SSH授权文件只保存元信息与摘要 | 历史结论为“当前容器可见范围未检出受影响插件及所查IOC”。不覆盖Windows本机或宿主机，不排除历史安装后删除；缺少SSH密钥历史基线，不能判断是否曾异常新增。 |

内核证据：`.runtime/security-notice-check-20261102/server-kernel-readonly.json`、`kernel-extra-readonly.json`。防火墙查询返回权限不足，BPF工具不可用，因此宿主防火墙/BPF状态未完整核实。回环MPTCP监听不是直接公网暴露；关闭MPTCP也不能据此认定完成内核修复。

插件证据：同目录`server-claude-readonly.json`、`server-claude-extra-roots.json`及检查脚本`check_claude_readonly.py`。IOC为通报给出的`134.209.82.225`，检查未发现匹配，不等于独立证明通报的供应链事件本身。没有读取或输出SSH公钥正文或密码。

原答复定位：本目录`finals-01a0d14c-252b-7d01-8327-e653a8117bd0.md`中`2026-11-02T03:19:55.204Z`段落；当时引用的Ubuntu条目为`https://git.launchpad.net/ubuntu-cve-tracker/plain/active/CVE-2026-98432`。后续启动平台没有修复这两项安全问题，也没有改变sysctl、防火墙或内核。

## 附录B：现有发布器需保留的具体依赖目录

以下是保留现有发布器而不改写时，从0.1.51的manifest及helpers静态递归得到的依赖目录集合。远端目录统一位于`/root/autodl-tmp/`；本机路径相对仓库。核对只读本地文件，没有重新登录探测。0.1.50仅作为代码/回执基线；实际helper链从0.1.49逐级委托至0.1.37，后者通过`references.py`加载0.1.36、0.1.34和0.1.33的辅助模块。

| 远端发布目录名 | 对应本机目录 |
| --- | --- |
| `geomanager-release-0.1.51-d3b3e82-r1` | `.runtime/agent-concurrency-access-20261102/release-r1`，并保留相邻`release-tools` |
| `geomanager-release-0.1.50-ab230b5-r3` | `.runtime/platform-usability-20261102/release-r3` |
| `geomanager-release-0.1.49-805111a-r3` | `.runtime/geology-complete-story-20261025/release-r3` |
| `geomanager-release-0.1.48-3566c1f-r6` | `.runtime/geology-demo-story-20261025/release-r6` |
| `geomanager-release-0.1.47-9cff7f4-r8` | `.runtime/geology-multi-release-20261023/code-release-r8` |
| `geomanager-release-0.1.46-03b73bb-r2` | `.runtime/workflow-inputs-20261021/release-r2` |
| `geomanager-release-0.1.45-1666241-r3` | `.runtime/agent-history-session-20261020/release-r3` |
| `geomanager-release-0.1.44-f8f90cf-r3` | `.runtime/platform-ui-cleanup-20261019/release-r3` |
| `geomanager-release-0.1.43-e51638d-r7` | `.runtime/agent-interaction-ecology-20261016/release-r7` |
| `geomanager-release-0.1.42-a79c90a` | `.runtime/agent-catalog-policy-20261016/release-r2` |
| `geomanager-release-0.1.41-03a2949` | `.runtime/geology-review-demo-20261014/release-r5` |
| `geomanager-release-0.1.40-1f499da` | `.runtime/catalog-workflow-feedback-20261014/release` |
| `geomanager-release-0.1.39-5f41d11` | `.runtime/workflow-deliverables-20261012/release` |
| `geomanager-release-0.1.38-7db55d4-r2` | `.runtime/agent-compute-activity-20261012/release-r2` |
| `geomanager-release-0.1.37-8870510` | `.runtime/geology-real-demo-20261012/release` |
| `geomanager-release-0.1.36-8b4c9a3` | `.runtime/agent-live-activity-20261012/release` |
| `geomanager-release-0.1.34-0dd8260` | `.runtime/dual-demo-release-20261011` |
| `geomanager-release-0.1.33-00aa8a5` | `.runtime/knowledge-network-color-20261010` |

文件级最低范围包括：每层被哈希校验的`manifest.json`和正式`server-receipt.json`，实际加载的`common.py`/`release_common.py`、`preservation.py`、`auth_qa.py`、`references.py`及`reference-hashes.json`；0.1.36的`checks.py`、0.1.34的`demo_data_guard.py`和`execution_data_guard.py`、0.1.33的`database_guard.py`。各层manifest的tools/baseHelperSha256还钉住其他文件，移机应直接保留上表已验收目录，再按manifest校验；本次未验证一个删减文件后的精简包。

本机目录不是服务器目录的完整镜像。例如0.1.47本机正式回执保存名为`server-receipt-production-code-finalized.json`，0.1.51本机也缺API证据副本。移机备份应以服务器实际目录和回执哈希为准补齐，不能仅改文件名就视为同一内容。数据、QA凭据及大结果继续独立受限保存，不进入Git。

另需本机传输入口`.runtime/geology-multi-release-20261023/remote.py`及其依赖的`.runtime/brand-options/server.py`和相应SSH依赖/认证配置；后者含私有连接信息，单独加密转移。当前及直接回退程序目录`geomanager-deploy-0.1.51-d3b3e82-r1`、`geomanager-deploy-0.1.50-ab230b5-r3`与配置、环境、启动器一并保留。以上列的是发布辅助链，不要求把每个历史候选数据副本、截图和所有旧程序副本都当作日常移机最低依赖。

复核脚本`inspect_release_dependencies.py`只解析本地JSON和Python源码，不导入发布模块、不执行其代码。上表还人工核对了0.1.37的references及所加载模块的导入；0.1.36检查脚本中的0.1.35字符串是其旧独立检查流程的基线，不是本轮helper导入链，因此未额外列0.1.35为当前动态依赖。
