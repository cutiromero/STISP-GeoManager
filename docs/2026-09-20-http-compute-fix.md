# HTTP 试运行及计算心跳修复

服务器通过 HTTP 访问时，浏览器不提供 `crypto.randomUUID`。0.1.4 将试运行表单、结果表格及专题文字操作统一改为 `createUuid`，优先使用原生 UUID，其次使用 `getRandomValues` 生成 UUID v4，缺少 Web Crypto 时仍可生成界面标识。此工具不用于认证或生成安全凭据。API、权限、数据目录与栅格渲染未变更。

线上验收发现计算工作进程在 `pulse` 的 `update_or_create` 中遇到 SQLite 写锁冲突后退出。0.1.5 将已有心跳记录改为单条 UPDATE；首次初始化采用 get_or_create。工作循环仅对 SQLite BUSY/LOCKED 错误等待下一轮（3 秒）并重新进行已有任务恢复检查；其他数据库错误及 `--once` 执行失败仍向调用方报错。恢复沿用原有任务状态和尝试次数约束，不直接重复执行算法。

回归覆盖：HTTP 环境只提供 getRandomValues；心跳更新保留运行环境信息；队列正常运行后发生锁冲突、重新恢复并继续处理；IOERR 和单次执行错误不会被吞掉。计算仍使用用户指定的本机 Python 子进程模式，不需要 Docker。
